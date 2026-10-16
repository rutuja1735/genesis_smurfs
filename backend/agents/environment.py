"""Factory that creates isolated agents and their namespaced tool registry."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core.registry import ToolRegistry
from .banking import BankingAgent
from .email import EmailAgent
from .slack import SlackAgent


@dataclass
class MockEnvironment:
    profile: dict[str, Any]
    email: EmailAgent
    slack: SlackAgent
    banking: BankingAgent
    registry: ToolRegistry

    def snapshot(self) -> dict[str, Any]:
        return {"profile": self.profile, "email": self.email.snapshot(), "slack": self.slack.snapshot(),
                "banking": self.banking.snapshot()}


def create_mock_environment(*, data_dir: str | None = None,
                            injections: dict[str, str] | None = None) -> MockEnvironment:
    kwargs = {"data_dir": data_dir, "injections": injections or {}}
    email, slack, banking = EmailAgent(**kwargs), SlackAgent(**kwargs), BankingAgent(**kwargs)
    root = Path(data_dir) if data_dir else Path(__file__).resolve().parent.parent / "data"
    with (root / "user_profile.json").open(encoding="utf-8") as handle:
        profile = json.load(handle)
    registry = ToolRegistry([*email.specs(), *slack.specs(), *banking.specs()])
    return MockEnvironment(profile, email, slack, banking, registry)


def snapshot_diff(before: dict[str, Any], after: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Return changed leaf paths and their before/after values."""
    changes: dict[str, dict[str, Any]] = {}
    def walk(left: Any, right: Any, path: str) -> None:
        if isinstance(left, dict) and isinstance(right, dict):
            for key in sorted(set(left) | set(right)):
                walk(left.get(key), right.get(key), f"{path}.{key}" if path else str(key))
        elif isinstance(left, list) and isinstance(right, list):
            if left != right:
                changes[path] = {"before": left, "after": right}
        elif left != right:
            changes[path] = {"before": left, "after": right}
    walk(before, after, "")
    return changes
