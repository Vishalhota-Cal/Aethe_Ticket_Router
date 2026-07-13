"""
agents/base.py

Defines the shared contract every agent (TriageAgent, ValidationAgent,
ReviewAgent) must follow. The orchestrator will call every agent the
exact same way, regardless of what each one actually does internally.
"""

from typing import Any, Protocol

from ticket_router.domain.models import TicketContext


class AgentResult:
    """What every agent hands back after running once."""

    def __init__(self, success: bool, data: Any, agent_name: str) -> None:
        self.success = success
        self.data = data
        self.agent_name = agent_name


class BaseAgent(Protocol):
    """Any class acting as an agent must implement this one method."""

    async def execute(self, context: TicketContext) -> AgentResult:
        """Do this agent's one job using `context`, and return the result."""
        ...