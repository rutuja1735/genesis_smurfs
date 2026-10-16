"""Argument origin tracking over raw tool outputs.

Provenance is run on RAW output only; the sanitized view is never used for
provenance lookups (Section 22 rule 17).
"""

from __future__ import annotations

import re
from enum import Enum
from typing import Any

from .registry import ToolSpec


def extract_bare_address(addr: str) -> str:
    """Extract the bare email address from a display-name form.

    'Alice <alice@example.com>' -> 'alice@example.com'
    'alice@example.com' -> 'alice@example.com'

    Lowercased for case-insensitive comparison. This protects against the
    display-name spoofing trick:
    'Alice <attacker@evil.com>' where the display name matches a trusted
    contact but the address does not.
    """
    addr = addr.strip()
    angle = re.search(r"<([^>]+)>", addr)
    if angle:
        return angle.group(1).strip().lower()
    if "@" in addr:
        return addr.lower()
    return addr.lower()


def is_trusted_address(candidate: str, trusted: str) -> bool:
    """Return True iff the bare addresses match (case-insensitive).

    Never compare raw header values directly — always extract bare addresses
    first to defeat display-name tricks.
    """
    return extract_bare_address(candidate) == extract_bare_address(trusted)


class Origin(str, Enum):
    USER_PROMPT = "USER_PROMPT"
    PROFILE_TRUSTED = "PROFILE_TRUSTED"
    TOOL_TRUSTED = "TOOL_TRUSTED"
    TOOL_USER_HISTORY = "TOOL_USER_HISTORY"
    TOOL_UNTRUSTED = "TOOL_UNTRUSTED"
    LLM_GENERATED = "LLM_GENERATED"
    LLM_GENERATED_FROM_UNTRUSTED = "LLM_GENERATED_FROM_UNTRUSTED"


class Provenance:
    def __init__(self) -> None:
        self.raw_outputs: dict[str, Any] = {}
        self.output_specs: dict[str, ToolSpec] = {}

    def add_output(self, node_id: str, raw_output: Any, spec: ToolSpec) -> None:
        self.raw_outputs[node_id] = raw_output
        self.output_specs[node_id] = spec

    @staticmethod
    def normalize(value: Any) -> str:
        text = str(value).strip().casefold()
        return re.sub(r"\s+", "", text) if re.search(r"[A-Z]{2}\d{2}", text, re.I) else " ".join(text.split())

    def classify_value(self, value: Any, source_node: str | None = None) -> tuple[Origin, str | None]:
        if source_node is None or source_node not in self.raw_outputs:
            return Origin.LLM_GENERATED, None
        needle = self.normalize(value)
        if not needle:
            return Origin.LLM_GENERATED, None
        raw = self.raw_outputs[source_node]
        spec = self.output_specs[source_node]
        matches: list[tuple[int, Origin, str]] = []

        def field_trust(path: str) -> str:
            wildcard_path = re.sub(r"\[\d+\]", ".*", path)
            return spec.output_trust.get(path, spec.output_trust.get(wildcard_path,
                   spec.output_trust.get(path.rsplit(".", 1)[-1], "untrusted")))

        def visit(obj: Any, path: str = "") -> None:
            if isinstance(obj, dict):
                for key, item in obj.items():
                    visit(item, f"{path}.{key}" if path else str(key))
            elif isinstance(obj, list):
                for index, item in enumerate(obj):
                    visit(item, f"{path}[{index}]")
            elif isinstance(obj, (str, int, float)):
                hay = self.normalize(obj)
                if needle == hay:
                    trust = field_trust(path)
                    origin = Origin.TOOL_TRUSTED if trust == "trusted" else Origin.TOOL_UNTRUSTED
                    matches.append((3, origin, path))
                elif needle in hay:
                    trust = field_trust(path)
                    origin = Origin.TOOL_TRUSTED if trust == "trusted" else Origin.TOOL_UNTRUSTED
                    matches.append((1, origin, path))

        visit(raw)
        if not matches:
            return Origin.LLM_GENERATED, None
        best_rank = max(item[0] for item in matches)
        best = [item for item in matches if item[0] == best_rank]
        # Exact field match wins; ties are conservative and become untrusted.
        if len(best) == 1:
            return best[0][1], best[0][2]
        if any(origin == Origin.TOOL_UNTRUSTED for _, origin, _ in best):
            return Origin.TOOL_UNTRUSTED, best[0][2]
        return best[0][1], best[0][2]

    def classify_literal(self, value: Any, user_command: str, profile: dict[str, Any] | None = None) -> Origin:
        needle = self.normalize(value)
        if needle and needle in self.normalize(user_command):
            return Origin.USER_PROMPT
        if any(needle and needle in self.normalize(v) for v in (profile or {}).values() if isinstance(v, (str, int, float))):
            return Origin.PROFILE_TRUSTED
        return Origin.LLM_GENERATED
