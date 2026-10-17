"""Deterministic final-answer filter for links, grounding, actions and secrets."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

from .gate import DecisionAction, _AMOUNT, _EMAIL, _IBAN


RULE_EXPLANATIONS: dict[str, dict[str, str]] = {
    "F1": {"reason": "active or auto-fetching content was removed", "reason_human": "Removed active content from the answer because it could fetch or execute untrusted content."},
    "F2": {"reason": "link host is not allowlisted or grounded in the request", "reason_human": "Removed a link to {host} because it was not requested or fetched through an allowed tool."},
    "F3": {"reason": "URL contains sensitive or unrequested data", "reason_human": "Removed a link because its address contained sensitive or unrequested data."},
    "F4": {"reason": "identifier or amount is not grounded in available raw data", "reason_human": "Removed the unverified {kind} `{value}` from the answer because it was not found in the request, profile, or tool data."},
    "F5": {"reason": "answer claims an action that did not execute", "reason_human": "Corrected the answer: `{claim}` was not completed by an executed tool action."},
    "F6": {"reason": "sensitive account data was masked", "reason_human": "Masked {kind} from the answer because your request did not ask to reveal it."},
}


@dataclass(frozen=True)
class FilterDecision:
    action: DecisionAction
    rule_id: str
    reason: str
    reason_human: str
    excerpt: str = ""


@dataclass
class OutputFilterContext:
    user_command: str = ""
    profile: dict[str, Any] = field(default_factory=dict)
    raw_tool_outputs: list[Any] = field(default_factory=list)
    trusted_domains: set[str] = field(default_factory=set)
    fetched_urls: set[str] = field(default_factory=set)
    sensitive_values: set[str] = field(default_factory=set)
    requested_secret_kinds: set[str] = field(default_factory=set)
    executed_calls: list[str] = field(default_factory=list)
    action_completed: bool = False
    answer_requested_secrets: bool = False
    max_unrequested_chunk: int = 80


@dataclass(frozen=True)
class FilterResult:
    text: str
    decisions: tuple[FilterDecision, ...]
    raw_answer_hash: str


def _fmt(rule: str, **values: Any) -> FilterDecision:
    template = RULE_EXPLANATIONS[rule]
    human = template["reason_human"].format_map({key: str(value) for key, value in values.items()})
    return FilterDecision(DecisionAction.BLOCK, rule, template["reason"], human, str(values.get("excerpt", "")))


def _flatten(value: Any) -> str:
    if isinstance(value, dict):
        return " ".join(_flatten(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return " ".join(_flatten(item) for item in value)
    return str(value)


def _grounded(value: str, ctx: OutputFilterContext) -> bool:
    sources = [ctx.user_command, _flatten(ctx.profile), *(_flatten(item) for item in ctx.raw_tool_outputs)]
    normalize = lambda text: re.sub(r"\s+", "", text).casefold()
    return any(normalize(value) in normalize(source) for source in sources)


def filter_answer(answer: str, ctx: OutputFilterContext) -> FilterResult:
    raw_hash = hashlib.sha256(answer.encode("utf-8")).hexdigest()
    text = answer
    decisions: list[FilterDecision] = []

    # F1: strip images, script/iframe tags, and dangerous anchors.
    patterns = [
        r"!\[[^\]]*\]\([^)]*\)",
        r"(?is)<\s*(?:script|iframe|object|embed|video|audio)\b[^>]*>.*?<\s*/\s*(?:script|iframe|object|embed|video|audio)\s*>",
        r"(?is)<\s*(?:img|source|link|embed|object|video|audio)\b[^>]*?/?>",
        r"(?is)<\s*a\s+[^>]*href\s*=\s*['\"]?\s*(?:javascript:|data:)[^>]*>.*?<\s*/\s*a\s*>",
    ]
    for pattern in patterns:
        for match in list(re.finditer(pattern, text)):
            decisions.append(_fmt("F1", excerpt=match.group(0)[:160]))
            text = text.replace(match.group(0), "", 1)
    text = re.sub(r"(?is)<\s*(?:script|iframe|object|embed|video|audio)\b[^>]*>|<\s*/\s*(?:script|iframe|object|embed|video|audio)\s*>", "", text)

    # F2 / F3: keep only grounded/allowlisted URLs, then inspect URL components.
    url_pattern = re.compile(r"https?://[^\s)\]}>\"']+", re.I)
    for match in list(url_pattern.finditer(text)):
        url = match.group(0).rstrip(".,;:!")
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        allowed = host in {item.lower() for item in ctx.trusted_domains} or url in ctx.fetched_urls or url in ctx.user_command or host in { (urlparse(item).hostname or "").lower() for item in ctx.fetched_urls }
        sensitive = any(value and value.casefold() in (parsed.path + parsed.query + parsed.fragment).casefold() for value in ctx.sensitive_values)
        sensitive = sensitive or bool(re.search(r"(?i)(?:password|secret|api[_-]?key|token|iban|balance)=", parsed.query)) or bool(re.search(r"[A-Za-z0-9+/]{80,}={0,2}", url))
        for output in ctx.raw_tool_outputs:
            raw = _flatten(output)
            for chunk_start in range(0, max(0, len(raw) - ctx.max_unrequested_chunk + 1), ctx.max_unrequested_chunk):
                chunk = raw[chunk_start:chunk_start + ctx.max_unrequested_chunk]
                if chunk.strip() and chunk in url and chunk not in ctx.user_command:
                    sensitive = True
                    break
        if sensitive:
            decisions.append(_fmt("F3", host=host, excerpt=url[:160]))
            text = text.replace(url, "[link removed: sensitive data]", 1)
        elif not allowed:
            decisions.append(_fmt("F2", host=host, excerpt=url[:160]))
            text = text.replace(url, f"[link removed: {host}]", 1)

    # F4: ground IBANs, e-mails, and monetary values against raw sources.
    # Match a compact identifier as a single token. The broader policy scanner's
    # whitespace-tolerant pattern can consume ordinary words after an IBAN.
    iban_pattern = re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b|\b(?:GB|DE)\d{2}(?:\s[A-Z0-9]{4}){4}\s[A-Z0-9]{2}\b|\bFR\d{2}(?:\s[A-Z0-9]{4}){5}\s[A-Z0-9]{3}\b", re.I)
    for pattern, kind in ((iban_pattern, "IBAN"), (_EMAIL, "email address"), (_AMOUNT, "amount")):
        for match in list(pattern.finditer(text)):
            value = match.group(0).strip()
            if not _grounded(value, ctx):
                decisions.append(_fmt("F4", kind=kind, value=value[:48], excerpt=value[:48]))
                text = text.replace(value, "[unverified value removed]", 1)

    # F5: action claims are only retained if corresponding calls ran.
    claims = re.compile(r"\b(?:I\s+)?(?:sent|forwarded|deleted|paid|transferred|payment\s+made|email\s+sent)\b[^.!?]*", re.I)
    for match in list(claims.finditer(text)):
        claim = match.group(0)
        claim_lower = claim.casefold()
        prefix = re.split(r"[.!?;\n]|\b(?:but|however)\b", text[:match.start()], flags=re.I)[-1]
        # A denial of an action is not a claim that the action happened.
        if re.search(r"\b(?:no|not|never|neither|without)\b|\b\w+n['’]t\b", prefix, re.I) or re.search(r"^(?:I\s+)?(?:sent|forwarded|deleted|paid|transferred)\s+(?:no|nothing|none)\b", claim, re.I):
            continue
        if "forward" in claim_lower:
            expected = ("forward",)
        elif "delet" in claim_lower:
            expected = ("delete", "remove")
        elif "paid" in claim_lower or "payment" in claim_lower or "transfer" in claim_lower:
            expected = ("send_money", "payment", "transfer")
        else:
            expected = ("send_email", "send_message", "email.send", "message.send")
        executed = bool(ctx.executed_calls) and ctx.action_completed and any(any(term in name.casefold() for term in expected) for name in ctx.executed_calls)
        if not executed:
            decisions.append(_fmt("F5", claim=claim[:100], excerpt=claim[:100]))
            replacement = "That action was not completed" + ("." if match.end() == len(text) else "")
            text = text.replace(claim, replacement, 1)

    # F6: secrets/account values are masked unless explicitly requested.
    if not ctx.answer_requested_secrets or ctx.requested_secret_kinds:
        own = ctx.profile.get("iban") or ctx.profile.get("own_iban") or ctx.profile.get("account_iban")
        balance = ctx.profile.get("balance")
        for value, label, kind in ((str(own) if own else "", "your account identifier", "iban"), (str(balance) if balance is not None else "", "your balance", "balance")):
            requested = kind in ctx.requested_secret_kinds or (not ctx.requested_secret_kinds and ctx.answer_requested_secrets)
            if value and value in text and not requested:
                decisions.append(_fmt("F6", kind=label, excerpt=value[:24]))
                text = text.replace(value, "[redacted]", 1)
        for value in ctx.sensitive_values:
            if value and value in text and value not in {str(own or ""), str(balance or "")}:
                decisions.append(_fmt("F6", kind="a secret value", excerpt=value[:24]))
                text = text.replace(value, "[redacted]", 1)
        if "password" not in ctx.requested_secret_kinds and not (ctx.answer_requested_secrets and not ctx.requested_secret_kinds):
            for match in list(re.finditer(r"(?i)\b(?:password|passcode|auth(?:entication)? code|api[_ -]?key)\s*[:=]\s*\S+", text)):
                decisions.append(_fmt("F6", kind="a secret", excerpt=match.group(0)[:40]))
                text = text.replace(match.group(0), "[redacted secret]", 1)
    return FilterResult(text, tuple(decisions), raw_hash)
