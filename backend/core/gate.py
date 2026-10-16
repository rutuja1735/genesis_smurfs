"""Deterministic authorization gate. No model output is trusted as policy."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import networkx as nx

from .graph import PlanGraph, PlanNode, build_dag
from .provenance import Origin, Provenance, extract_bare_address
from .registry import ToolRegistry, ToolSpec
from .scanner import scan_text


class DecisionAction(str, Enum):
    ALLOW = "ALLOW"
    BLOCK = "BLOCK"
    FLAG = "FLAG"
    SKIP = "SKIP"
    NEEDS_CONFIRM = "NEEDS_CONFIRM"


@dataclass(frozen=True)
class Decision:
    action: DecisionAction
    rule_id: str
    reason: str
    reason_human: str
    severity: str = "low"


@dataclass
class GateContext:
    user_command: str
    plan: PlanGraph
    provenance: Provenance = field(default_factory=Provenance)
    arg_origins: dict[str, Origin] = field(default_factory=dict)
    source_nodes: dict[str, str] = field(default_factory=dict)
    node_status: dict[str, str] = field(default_factory=dict)
    attempted_node_ids: set[str] = field(default_factory=set)
    attempt_source: str = "initial_plan"
    delegated_sources: set[str] = field(default_factory=set)
    profile: dict[str, Any] = field(default_factory=dict)
    trusted_contacts: set[str] = field(default_factory=set)
    max_delegated_amount: float | None = None
    max_high_impact_calls: int = 3
    previous_calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    upstream_text: str = ""
    confirm_policy: str = "deny"


RULE_EXPLANATIONS: dict[str, dict[str, str]] = {
    "R1": {"reason": "call is not a matching node in the validated graph", "reason_human": "Blocked `{tool}`: it was not part of the plan made from your request."},
    "R2": {"reason": "one or more dependencies are not DONE", "reason_human": "Skipped `{tool}` because a required earlier step did not complete."},
    "R3": {"reason": "the user request does not imply this write action", "reason_human": "Blocked `{tool}`: your request does not ask for this action (no {verb_class} intent found)."},
    "R4": {"reason": "a sensitive sink value has untrusted or generated provenance", "reason_human": "Blocked `{tool}`: the value for `{arg}` (`{value}`) came from untrusted or generated content ({source}), not from you or trusted data."},
    "R4b": {"reason": "user explicitly delegated a sink value to a referenced source", "reason_human": "Allowed with warning: `{arg}` was taken from {source} because your request pointed to it."},
    "R5": {"reason": "amount exceeds or conflicts with the user's stated limit", "reason_human": "Blocked `{tool}`: amount {value} does not match or exceeds the amount allowed by your request ({user_amount})."},
    "R6": {"reason": "outgoing content contains unrequested sensitive data or injection text", "reason_human": "Blocked `{tool}`: the outgoing message contains sensitive or unrequested content for {recipient}."},
    "R7": {"reason": "high-impact call exceeds the run limit or duplicates a previous call", "reason_human": "Blocked `{tool}`: too many high-impact actions in one run, or this duplicates an earlier call."},
    "R8": {"reason": "high-severity injected instructions are upstream of a high-impact action", "reason_human": "Held `{tool}`: hidden instructions were detected in {source}, and this high-impact action requires confirmation."},
}

_AMOUNT = re.compile(r"(?<!\w)(?:[$€£₹]\s*)?\d+(?:,\d{3})*(?:\.\d{1,2})?\s*(?:USD|EUR|GBP|INR|dollars?|rupees?)?(?!\w)", re.I)
_EMAIL = re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}")
_IBAN = re.compile(r"\b[A-Z]{2}\d{2}(?:\s?[A-Z0-9]){11,30}\b", re.I)
_SECRET = re.compile(r"(?i)\b(?:password|passcode|auth(?:entication)? code|api[_ -]?key)\s*[:=]?\s*\S+")


def _fmt(template: str, **values: Any) -> str:
    safe = {k: str(v).replace("{", "(").replace("}", ")") for k, v in values.items()}
    return template.format_map({key: safe.get(key, "unknown") for key in re.findall(r"\{([a-z_]+)\}", template)})


class PolicyGate:
    def __init__(self, registry: ToolRegistry) -> None:
        self.registry = registry

    def check(self, call: dict[str, Any], node: PlanNode | None, ctx: GateContext) -> Decision:
        tool = str(call.get("function_name", call.get("tool", "unknown")))
        args = call.get("args", {}) or {}
        spec = self.registry.get(tool)
        planned_ids = {item.id for item in ctx.plan.nodes}
        planned_node = node is not None and node.id in planned_ids
        admitted_expansion = ctx.attempt_source == "expansion" and node is not None and node.id in ctx.attempted_node_ids
        admitted_retry = ctx.attempt_source == "retry" and planned_node and node is not None and node.id in ctx.attempted_node_ids
        if node is None or (not planned_node and not admitted_expansion) or node.function_name != tool or (ctx.attempt_source != "initial_plan" and not admitted_expansion and not admitted_retry):
            return self._decision("R1", DecisionAction.BLOCK, tool=tool)
        if spec is None:
            return self._decision("R1", DecisionAction.BLOCK, tool=tool)
        for arg in spec.sink_params:
            if arg not in args or args[arg] in (None, ""):
                return self._decision("R4", DecisionAction.BLOCK, tool=tool, arg=arg, value="<missing>", source="missing argument")
        plan_dag = build_dag(ctx.plan)
        ancestors = nx.ancestors(plan_dag, node.id) if node.id in plan_dag else set(node.depends_on)
        if any(ctx.node_status.get(dep) != "DONE" for dep in ancestors | set(node.depends_on)):
            return self._decision("R2", DecisionAction.SKIP, tool=tool)
        if spec.risk in {"write", "high_impact"}:
            if not (node.justification or "").strip() or not self._intent_matches(spec, ctx.user_command):
                verb_class = ", ".join(spec.intent_verbs) or self._verb_class(spec.name)
                return self._decision("R3", DecisionAction.BLOCK, tool=tool, verb_class=verb_class)
        delegated_flag: Decision | None = None
        for arg, kind in spec.sink_params.items():
            if arg not in args or args[arg] in (None, ""):
                continue
            origin = ctx.arg_origins.get(arg)
            if origin is None:
                source_node = ctx.source_nodes.get(arg)
                if source_node:
                    origin, _ = ctx.provenance.classify_value(args[arg], source_node)
                else:
                    origin = ctx.provenance.classify_literal(args[arg], ctx.user_command, ctx.profile)
            if kind in {"recipient", "address", "url", "identifier"} and origin not in {Origin.USER_PROMPT, Origin.PROFILE_TRUSTED, Origin.TOOL_TRUSTED, Origin.TOOL_USER_HISTORY}:
                source_node = ctx.source_nodes.get(arg, "")
                if source_node and source_node in ctx.delegated_sources and self._source_mentioned(source_node, node, ctx):
                    known_value = self._matches_trusted_value(args[arg], ctx)
                    if known_value or ctx.confirm_policy == "approve_delegated":
                        delegated_flag = self._decision("R4b", DecisionAction.FLAG, tool=tool, arg=arg, source=f"node {source_node}")
                    else:
                        return Decision(
                            DecisionAction.NEEDS_CONFIRM, "R4b",
                            "delegated sink value has no trusted contact or history cross-check",
                            f"Held `{tool}`: `{arg}` came only from {source_node}, and it does not match a trusted contact or prior transaction. Confirm the payee before proceeding.",
                            "high",
                        )
                else:
                    return self._decision("R4", DecisionAction.BLOCK, tool=tool, arg=arg, value=args[arg], source=source_node or origin.value)
        amount_arg = next((key for key, kind in spec.sink_params.items() if kind == "amount" and key in args), None)
        if amount_arg:
            amount = self._number(args[amount_arg])
            requested = self._requested_amount(ctx.user_command)
            if requested is not None and amount is not None and abs(amount - requested) > 0.005:
                return self._decision("R5", DecisionAction.BLOCK, tool=tool, value=args[amount_arg], user_amount=requested)
            if ctx.max_delegated_amount is not None and amount is not None and amount > ctx.max_delegated_amount:
                return self._decision("R5", DecisionAction.BLOCK, tool=tool, value=args[amount_arg], user_amount=f"maximum {ctx.max_delegated_amount}")
        content_arg = next((key for key, kind in spec.sink_params.items() if kind == "body" and key in args), None)
        if content_arg:
            body = str(args[content_arg])
            recipient = str(args.get("to", args.get("recipient", "the requested recipient")))
            if _SECRET.search(body):
                return self._decision("R6", DecisionAction.BLOCK, tool=tool, recipient=recipient)
            if scan_text(body).severity == "high":
                return self._decision("R6", DecisionAction.BLOCK, tool=tool, recipient=recipient)
            for key, value in ctx.profile.items():
                if re.search(r"iban|balance|password|secret|auth.?code", str(key), re.I) and str(value) and str(value).casefold() in body.casefold():
                    return self._decision("R6", DecisionAction.BLOCK, tool=tool, recipient=recipient)
            if any(len(chunk) >= 80 and chunk in ctx.upstream_text for chunk in self._chunks(body, 80)):
                return self._decision("R6", DecisionAction.BLOCK, tool=tool, recipient=recipient)
            for email in _EMAIL.findall(body):
                known_addresses = ctx.trusted_contacts | set(_EMAIL.findall(ctx.user_command))
                allowed_domains = {item.rsplit("@", 1)[-1].lower() for item in known_addresses if "@" in item}
                if email.rsplit("@", 1)[-1].lower() not in allowed_domains:
                    return self._decision("R6", DecisionAction.BLOCK, tool=tool, recipient=email)
        # R6(c): outgoing recipient domain must be internal, a trusted contact,
        # or explicitly mentioned in the user command.
        recipient_args = [key for key, kind in spec.sink_params.items() if kind == "recipient" and key in args]
        if recipient_args and spec.risk in {"write", "high_impact"}:
            known_addresses = ctx.trusted_contacts | set(_EMAIL.findall(ctx.user_command))
            allowed_domains = {extract_bare_address(a).rsplit("@", 1)[-1].lower() for a in known_addresses if "@" in a}
            allowed_domains |= {d.lower() for d in ctx.profile.get("internal_domains", [])}
            to_value = args.get("to", [])
            recipients_raw: list[str] = to_value if isinstance(to_value, list) else [str(to_value)]
            for rec in recipients_raw:
                bare = extract_bare_address(rec)
                if "@" not in bare:
                    continue
                domain = bare.rsplit("@", 1)[-1].lower()
                if domain and allowed_domains and domain not in allowed_domains:
                    return self._decision("R6", DecisionAction.BLOCK, tool=tool, recipient=bare)
        if spec.risk == "high_impact":
            prior_high = [(name, old_args) for name, old_args in ctx.previous_calls if (self.registry.get(name) and self.registry.require(name).risk == "high_impact")]
            if len(prior_high) >= ctx.max_high_impact_calls or any(name == tool and old_args == args for name, old_args in prior_high):
                return self._decision("R7", DecisionAction.BLOCK, tool=tool)
            scan = scan_text(ctx.upstream_text)
            if scan.severity == "high":
                decision = self._decision("R8", DecisionAction.NEEDS_CONFIRM if ctx.confirm_policy == "ask_user" else DecisionAction.BLOCK, tool=tool, source="upstream tool output")
                return decision
        if delegated_flag:
            return delegated_flag
        return Decision(DecisionAction.ALLOW, "", "all policy checks passed", "", "low")

    def _decision(self, rule: str, action: DecisionAction, **values: Any) -> Decision:
        explanation = RULE_EXPLANATIONS[rule]
        return Decision(action, rule, explanation["reason"], _fmt(explanation["reason_human"], **values), "high" if rule in {"R4", "R6", "R8"} else "medium")

    @staticmethod
    def _matches_trusted_value(value: Any, ctx: GateContext) -> bool:
        normalized = Provenance.normalize(value)
        if normalized in {Provenance.normalize(item) for item in ctx.trusted_contacts}:
            return True
        for node_id, spec in ctx.provenance.output_specs.items():
            if spec.output_trust and ctx.provenance.classify_value(value, node_id)[0] == Origin.TOOL_TRUSTED:
                return True
        return False

    @staticmethod
    def _intent_matches(spec: ToolSpec, command: str) -> bool:
        words = (spec.intent_verbs or PolicyGate._default_verbs(spec.name))
        command = command.casefold()
        return any(re.search(rf"\b{re.escape(verb.casefold())}\b", command) for verb in words)

    @staticmethod
    def _default_verbs(name: str) -> tuple[str, ...]:
        lower = name.casefold()
        if "send_money" in lower or "payment" in lower or "transfer" in lower:
            return ("pay", "send", "transfer", "wire", "settle")
        if "delete" in lower or "remove" in lower:
            return ("delete", "remove", "trash")
        if "forward" in lower:
            return ("forward",)
        if "send_email" in lower or "send_message" in lower:
            return ("send",)
        if "post" in lower:
            return ("post", "publish")
        return (lower.rsplit(".", 1)[-1].split("_")[0],)

    @staticmethod
    def _verb_class(name: str) -> str:
        verbs = PolicyGate._default_verbs(name)
        return "/".join(verbs)

    @staticmethod
    def _source_mentioned(source_node: str, node: PlanNode, ctx: GateContext) -> bool:
        return bool(re.search(r"\b(?:bill|invoice|file|email|document|message|receipt|statement)\b", ctx.user_command, re.I))

    @staticmethod
    def _number(value: Any) -> float | None:
        match = re.search(r"\d+(?:,\d{3})*(?:\.\d+)?", str(value))
        return float(match.group(0).replace(",", "")) if match else None

    @staticmethod
    def _requested_amount(command: str) -> float | None:
        amounts = _AMOUNT.findall(command)
        return PolicyGate._number(amounts[0]) if amounts else None

    @staticmethod
    def _chunks(text: str, size: int):
        for start in range(0, max(len(text) - size + 1, 0)):
            yield text[start:start + size]
