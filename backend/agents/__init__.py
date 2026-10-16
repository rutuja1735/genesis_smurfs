"""JSON-backed mock environments for email, Slack, and banking tools."""

from .environment import MockEnvironment, create_mock_environment, snapshot_diff

__all__ = ["MockEnvironment", "create_mock_environment", "snapshot_diff"]
