"""
llm/client.py

Defines the contract every AI provider in this project must follow.
Nothing else in the codebase is allowed to know whether it's actually
talking to the mock, Anthropic, or OpenAI -- it only knows it's talking
to something shaped like an LLMClient.
"""

from typing import Protocol


class LLMClient(Protocol):
    """Any class acting as an AI provider must implement this one
    method, with exactly this shape.
    """

    async def complete(self, prompt: str) -> str:
        """Send `prompt` to the AI and return its raw text response."""
        ...