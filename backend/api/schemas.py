"""Validated request/response models for the local REST API."""

from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, Field


class ConversationCreate(BaseModel):
    title: str = "New conversation"


class RunCreate(BaseModel):
    command: str = Field(min_length=1, max_length=12000)
    agents: list[str] = Field(default_factory=lambda: ["email", "slack", "banking"])
    defense: Literal["ours", "none", "spotlighting"] = "ours"
    attack: str | None = None
    injection_goal: str | None = None
    confirm_policy: Literal["deny", "approve_delegated"] = "deny"
    neutralize: Literal["off", "annotate", "redact"] = "redact"
    output_filter: bool = True


class ConversationMessage(BaseModel):
    content: str = Field(min_length=1, max_length=12000)
    agents: list[str] = Field(default_factory=lambda: ["email", "slack", "banking"])
    defense: Literal["ours", "none", "spotlighting"] = "ours"
    attack: str | None = None
    injection_goal: str | None = None
    confirm_policy: Literal["deny", "approve_delegated"] = "deny"
    neutralize: Literal["off", "annotate", "redact"] = "redact"
    output_filter: bool = True
    compare: bool = False


class EvalCreate(BaseModel):
    track: Literal["mock", "agentdojo"] = "mock"
    suite: str = "all"
    mode: str = "attack_defended"
    attack: str = "all"
    defense: str = "ours"
    confirm_policy: Literal["deny", "approve_delegated"] = "deny"
    neutralize: Literal["off", "annotate", "redact"] = "redact"
    output_filter: bool = True
    batch_size: int = Field(default=5, ge=1, le=5)
    cursor: int | None = Field(default=None, ge=0)
    confirm_cost: bool = False
