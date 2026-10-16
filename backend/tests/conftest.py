from typing import Any

import pytest
from pydantic import BaseModel

from core.registry import ToolRegistry, ToolSpec


class EmptyArgs(BaseModel):
    pass


class ReadArgs(BaseModel):
    query: str = ""


class PayArgs(BaseModel):
    recipient: str
    amount: str


class MailArgs(BaseModel):
    to: str
    body: str


class UrlArgs(BaseModel):
    url: str


@pytest.fixture
def registry() -> ToolRegistry:
    return ToolRegistry([
        ToolSpec("email.search", "email", None, ReadArgs, "read", {"messages": "untrusted", "trusted_sender": "trusted"}, {}, "Search email"),
        ToolSpec("slack.search", "slack", None, ReadArgs, "read", {"messages": "untrusted"}, {}, "Search Slack"),
        ToolSpec("email.send_email", "email", None, MailArgs, "high_impact", {}, {"to": "recipient", "body": "body"}, "Send an email", ("send",)),
        ToolSpec("banking.send_money", "banking", None, PayArgs, "high_impact", {}, {"recipient": "recipient", "amount": "amount"}, "Send money", ("pay", "send", "transfer")),
        ToolSpec("banking.mark_read", "banking", None, EmptyArgs, "write", {}, {}, "Mark as read", ("mark", "read")),
        ToolSpec("web.open", "web", None, UrlArgs, "read", {}, {"url": "url"}, "Open webpage"),
    ])
