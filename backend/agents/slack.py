"""Mock Slack tools backed by the per-run Slack JSON state."""

from __future__ import annotations

from typing import Any
from pydantic import BaseModel

from .base import JsonAgent, EmptyArgs
from core.registry import ToolSpec


class ChannelArgs(BaseModel):
    channel: str

class UserArgs(BaseModel):
    user: str

class WebpageArgs(BaseModel):
    url: str

class SendChannelArgs(BaseModel):
    channel: str
    message: str

class DirectMessageArgs(BaseModel):
    recipient: str
    body: str

class InviteArgs(BaseModel):
    user: str
    channel: str | None = None

class AddUserArgs(BaseModel):
    user: str
    channel: str


class SlackAgent(JsonAgent):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__("slack.json", **kwargs)

    def get_channels(self) -> dict[str, Any]:
        return {"channels": list(self.state["channels"])}

    def read_channel_messages(self, channel: str) -> dict[str, Any]:
        if channel not in self.state["channels"]:
            raise KeyError(f"channel not found: {channel}")
        return {"channel": channel, "messages": self.state["channels"][channel]["messages"]}

    def read_inbox(self, user: str) -> dict[str, Any]:
        if user not in self.state["dms"]:
            raise KeyError(f"user inbox not found: {user}")
        return {"user": user, "messages": self.state["dms"][user]}

    def get_users_in_channel(self, channel: str) -> dict[str, Any]:
        if channel not in self.state["channels"]:
            raise KeyError(f"channel not found: {channel}")
        return {"channel": channel, "users": self.state["channels"][channel]["members"]}

    def get_webpage(self, url: str) -> dict[str, Any]:
        domain = url.removeprefix("https://").removeprefix("http://").rstrip("/")
        if domain not in self.state["webpages"]:
            raise KeyError(f"webpage not found: {url}")
        return {"url": url, "content": self.state["webpages"][domain]}

    def send_channel_message(self, channel: str, message: str) -> dict[str, Any]:
        if channel not in self.state["channels"]:
            raise KeyError(f"channel not found: {channel}")
        row = {"id": f"m{sum(len(c['messages']) for c in self.state['channels'].values()) + 1}",
               "user": "emma", "text": message, "ts": "2026-05-15T09:00:00"}
        self.state["channels"][channel]["messages"].append(row)
        return row

    def send_direct_message(self, recipient: str, body: str) -> dict[str, Any]:
        row = {"id": f"dm{sum(len(v) for v in self.state['dms'].values()) + 1}",
               "from": "emma", "text": body, "ts": "2026-05-15T09:00:00"}
        self.state["dms"].setdefault(recipient, []).append(row)
        return {"recipient": recipient, "message": row}

    def invite_user(self, user: str, channel: str | None = None) -> dict[str, Any]:
        if channel:
            return self.add_user_to_channel(user, channel)
        if user not in self.state["users"]:
            self.state["users"].append(user)
        return {"user": user, "invited": True}

    def add_user_to_channel(self, user: str, channel: str) -> dict[str, Any]:
        if channel not in self.state["channels"]:
            raise KeyError(f"channel not found: {channel}")
        if user not in self.state["channels"][channel]["members"]:
            self.state["channels"][channel]["members"].append(user)
        return {"user": user, "channel": channel, "added": True}

    def remove_user(self, user: str) -> dict[str, Any]:
        self.state["users"] = [member for member in self.state["users"] if member != user]
        for channel in self.state["channels"].values():
            channel["members"] = [member for member in channel["members"] if member != user]
        return {"user": user, "removed": True}

    def specs(self) -> list[ToolSpec]:
        return [
            ToolSpec("slack.get_channels", "slack", self.get_channels, EmptyArgs, "read", output_trust={"channels": "trusted"}, description="List Slack channels"),
            ToolSpec("slack.read_channel_messages", "slack", self.read_channel_messages, ChannelArgs, "read", output_trust={"messages.*.text": "untrusted"}, sink_params={"channel": "identifier"}, description="Read channel messages"),
            ToolSpec("slack.read_inbox", "slack", self.read_inbox, UserArgs, "read", output_trust={"messages.*.text": "untrusted"}, sink_params={"user": "identifier"}, description="Read direct messages"),
            ToolSpec("slack.get_users_in_channel", "slack", self.get_users_in_channel, ChannelArgs, "read", output_trust={"users": "trusted"}, sink_params={"channel": "identifier"}, description="List channel members"),
            ToolSpec("slack.get_webpage", "slack", self.get_webpage, WebpageArgs, "read", output_trust={"content": "untrusted"}, sink_params={"url": "url"}, description="Fetch a mock webpage"),
            ToolSpec("slack.send_channel_message", "slack", self.send_channel_message, SendChannelArgs, "write", sink_params={"channel": "identifier", "message": "body"}, description="Post a channel message", intent_verbs=("post", "send", "message")),
            ToolSpec("slack.send_direct_message", "slack", self.send_direct_message, DirectMessageArgs, "high_impact", sink_params={"recipient": "recipient", "body": "body"}, description="Send a direct message", intent_verbs=("dm", "message")),
            ToolSpec("slack.invite_user", "slack", self.invite_user, InviteArgs, "high_impact", sink_params={"user": "recipient"}, description="Invite a Slack user", intent_verbs=("invite",)),
            ToolSpec("slack.add_user_to_channel", "slack", self.add_user_to_channel, AddUserArgs, "high_impact", sink_params={"user": "recipient", "channel": "identifier"}, description="Add a user to a channel", intent_verbs=("add", "invite")),
            ToolSpec("slack.remove_user", "slack", self.remove_user, UserArgs, "high_impact", sink_params={"user": "recipient"}, description="Remove a Slack user", intent_verbs=("remove",)),
        ]
