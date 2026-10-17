"""Mock email tools backed by the per-run email JSON state."""

from __future__ import annotations

from typing import Any
from pydantic import BaseModel, Field

from .base import JsonAgent, EmptyArgs
from core.registry import ToolSpec


class ListInboxArgs(BaseModel):
    unread_only: bool = False

class EmailIdArgs(BaseModel):
    email_id: str

class SearchEmailArgs(BaseModel):
    query: str
    sender: str | None = None

class DraftArgs(BaseModel):
    to: list[str]
    subject: str
    body: str

class SendArgs(DraftArgs):
    cc: list[str] = Field(default_factory=list)

class ForwardArgs(BaseModel):
    email_id: str
    to: list[str]


class EmailAgent(JsonAgent):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__("email.json", **kwargs)

    def list_inbox(self, unread_only: bool = False) -> dict[str, Any]:
        rows = self.state["inbox"]
        if unread_only:
            rows = [row for row in rows if not row["read"]]
        return {"emails": rows, "count": len(rows)}

    def read_email(self, email_id: str) -> dict[str, Any]:
        for row in self.state["inbox"]:
            if row["id"] == email_id:
                return dict(row)
        raise KeyError(f"email not found: {email_id}")

    def search_emails(self, query: str, sender: str | None = None) -> dict[str, Any]:
        query = query.casefold()
        rows = [row for row in self.state["inbox"]
                if query in (row["subject"] + " " + row["body"]).casefold()
                and (sender is None or row["from"].casefold() == sender.casefold())]
        return {"emails": rows, "count": len(rows)}

    def mark_read(self, email_id: str) -> dict[str, Any]:
        row = next((row for row in self.state["inbox"] if row["id"] == email_id), None)
        if row is None:
            raise KeyError(f"email not found: {email_id}")
        row["read"] = True
        return {"id": email_id, "read": True}

    def create_draft(self, to: list[str], subject: str, body: str) -> dict[str, Any]:
        draft = {"id": f"draft{len(self.state['drafts']) + 1}", "to": to,
                 "subject": subject, "body": body}
        self.state["drafts"].append(draft)
        return draft

    def send_email(self, to: list[str], subject: str, body: str, cc: list[str] | None = None) -> dict[str, Any]:
        sent = {"id": f"sent{len(self.state['sent']) + 1}", "to": to,
                "cc": cc or [], "subject": subject, "body": body}
        self.state["sent"].append(sent)
        return sent

    def forward_email(self, email_id: str, to: list[str]) -> dict[str, Any]:
        source = self.read_email(email_id)
        return self.send_email(to, "Fwd: " + source["subject"], source["body"])

    def delete_email(self, email_id: str) -> dict[str, Any]:
        row = next((row for row in self.state["inbox"] if row["id"] == email_id), None)
        if row is None:
            raise KeyError(f"email not found: {email_id}")
        self.state["inbox"].remove(row)
        self.state["deleted"].append(row)
        return {"id": email_id, "deleted": True}

    def specs(self) -> list[ToolSpec]:
        # Record handles come from the email store; they do not endorse message content.
        return [
            ToolSpec("email.list_inbox", "email", self.list_inbox, ListInboxArgs, "read", output_trust={"emails.*.id": "trusted", "emails.*.from": "untrusted", "emails.*.subject": "untrusted", "emails.*.body": "untrusted"}, description="List inbox messages"),
            ToolSpec("email.read_email", "email", self.read_email, EmailIdArgs, "read", output_trust={"id": "trusted", "from": "untrusted", "subject": "untrusted", "body": "untrusted"}, sink_params={"email_id": "identifier"}, description="Read a message by id"),
            ToolSpec("email.search_emails", "email", self.search_emails, SearchEmailArgs, "read", output_trust={"emails.*.id": "trusted", "emails.*.from": "untrusted", "emails.*.subject": "untrusted", "emails.*.body": "untrusted"}, description="Search email"),
            ToolSpec("email.mark_read", "email", self.mark_read, EmailIdArgs, "write", sink_params={"email_id": "identifier"}, description="Mark a message read"),
            ToolSpec("email.create_draft", "email", self.create_draft, DraftArgs, "write", sink_params={"to": "recipient", "body": "body"}, description="Create an email draft", intent_verbs=("draft", "prepare")),
            ToolSpec("email.send_email", "email", self.send_email, SendArgs, "high_impact", sink_params={"to": "recipient", "cc": "recipient", "body": "body"}, description="Send an email", intent_verbs=("send", "email")),
            ToolSpec("email.forward_email", "email", self.forward_email, ForwardArgs, "high_impact", sink_params={"to": "recipient"}, description="Forward an email", intent_verbs=("forward",)),
            ToolSpec("email.delete_email", "email", self.delete_email, EmailIdArgs, "high_impact", description="Delete an email", intent_verbs=("delete", "remove")),
        ]
