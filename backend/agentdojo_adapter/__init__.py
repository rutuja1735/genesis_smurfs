"""Optional AgentDojo Track B bridge. AgentDojo is never imported at package import time."""

from .profile import AGENTDOJO_PROFILE
from .tool_specs import build_tool_specs

__all__ = ["AGENTDOJO_PROFILE", "build_tool_specs"]
