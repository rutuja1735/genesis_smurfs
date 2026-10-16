"""Mock banking tools backed by the per-run banking JSON state."""

from __future__ import annotations

from typing import Any
from pydantic import BaseModel, Field

from .base import JsonAgent, EmptyArgs
from core.registry import ToolSpec


class RecentArgs(BaseModel):
    n: int = Field(default=5, ge=1, le=100)

class FileArgs(BaseModel):
    file_path: str

class SendMoneyArgs(BaseModel):
    recipient: str
    amount: float = Field(gt=0)
    subject: str
    date: str

class ScheduleArgs(SendMoneyArgs):
    recurring: bool = False

class UpdateScheduledArgs(BaseModel):
    id: int
    recipient: str | None = None
    amount: float | None = Field(default=None, gt=0)
    subject: str | None = None
    date: str | None = None
    recurring: bool | None = None

class PasswordArgs(BaseModel):
    password: str


class BankingAgent(JsonAgent):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__("banking.json", **kwargs)

    def get_balance(self) -> dict[str, Any]:
        return {"balance": self.state["account"]["balance"], "currency": "EUR"}

    def get_iban(self) -> dict[str, Any]:
        return {"iban": self.state["account"]["iban"]}

    def get_most_recent_transactions(self, n: int = 5) -> dict[str, Any]:
        return {"transactions": self.state["transactions"][-n:][::-1]}

    def get_scheduled_transactions(self) -> dict[str, Any]:
        return {"scheduled": self.state["scheduled"]}

    def read_file(self, file_path: str) -> dict[str, Any]:
        if file_path not in self.state["files"]:
            raise KeyError(f"file not found: {file_path}")
        return {"file_path": file_path, "content": self.state["files"][file_path]}

    def send_money(self, recipient: str, amount: float, subject: str, date: str) -> dict[str, Any]:
        transaction = {"id": max((row["id"] for row in self.state["transactions"]), default=0) + 1,
                       "recipient": recipient, "amount": amount, "subject": subject, "date": date}
        self.state["transactions"].append(transaction)
        self.state["account"]["balance"] -= amount
        return transaction

    def schedule_transaction(self, recipient: str, amount: float, subject: str, date: str,
                             recurring: bool = False) -> dict[str, Any]:
        transaction = {"id": max((row["id"] for row in self.state["scheduled"]), default=0) + 1,
                       "recipient": recipient, "amount": amount, "subject": subject,
                       "date": date, "recurring": recurring}
        self.state["scheduled"].append(transaction)
        return transaction

    def update_scheduled_transaction(self, id: int, recipient: str | None = None,
                                     amount: float | None = None, subject: str | None = None,
                                     date: str | None = None, recurring: bool | None = None) -> dict[str, Any]:
        row = next((item for item in self.state["scheduled"] if item["id"] == id), None)
        if row is None:
            raise KeyError(f"scheduled transaction not found: {id}")
        for name, value in {"recipient": recipient, "amount": amount, "subject": subject,
                            "date": date, "recurring": recurring}.items():
            if value is not None:
                row[name] = value
        return row

    def update_password(self, password: str) -> dict[str, Any]:
        self.state["password_updated"] = True
        self.state["password_marker"] = "[stored securely in mock state]"
        return {"updated": True}

    def specs(self) -> list[ToolSpec]:
        return [
            ToolSpec("banking.get_balance", "banking", self.get_balance, EmptyArgs, "read", output_trust={"balance": "trusted"}, description="Read account balance"),
            ToolSpec("banking.get_iban", "banking", self.get_iban, EmptyArgs, "read", output_trust={"iban": "trusted"}, description="Read account IBAN"),
            ToolSpec("banking.get_most_recent_transactions", "banking", self.get_most_recent_transactions, RecentArgs, "read", output_trust={"transactions.*.recipient": "trusted", "transactions.*.amount": "trusted", "transactions.*.subject": "untrusted"}, description="Read recent transaction history"),
            ToolSpec("banking.get_scheduled_transactions", "banking", self.get_scheduled_transactions, EmptyArgs, "read", output_trust={"scheduled.*.recipient": "trusted", "scheduled.*.amount": "trusted", "scheduled.*.subject": "untrusted"}, description="Read scheduled transactions"),
            ToolSpec("banking.read_file", "banking", self.read_file, FileArgs, "read", output_trust={"content": "untrusted"}, sink_params={"file_path": "identifier"}, description="Read a mock bank file"),
            ToolSpec("banking.send_money", "banking", self.send_money, SendMoneyArgs, "high_impact", sink_params={"recipient": "recipient", "amount": "amount", "subject": "body"}, description="Send money", intent_verbs=("send", "pay", "transfer")),
            ToolSpec("banking.schedule_transaction", "banking", self.schedule_transaction, ScheduleArgs, "high_impact", sink_params={"recipient": "recipient", "amount": "amount", "subject": "body"}, description="Schedule a payment", intent_verbs=("schedule", "pay", "transfer")),
            ToolSpec("banking.update_scheduled_transaction", "banking", self.update_scheduled_transaction, UpdateScheduledArgs, "high_impact", sink_params={"recipient": "recipient", "amount": "amount", "subject": "body"}, description="Update a scheduled payment", intent_verbs=("update", "change")),
            ToolSpec("banking.update_password", "banking", self.update_password, PasswordArgs, "high_impact", sink_params={"password": "secret"}, description="Update the account password", intent_verbs=("change", "update", "password")),
        ]
