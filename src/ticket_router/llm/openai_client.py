"""
llm/openai_client.py

The real AI provider, using OpenAI's API. Matches the exact same shape
as LLMClient (see client.py) -- one async `complete` method, text in,
text out -- so nothing else in the codebase needs to change now that a
real key exists.
"""

from openai import AsyncOpenAI

from ticket_router.domain.exceptions import LLMProviderError


class OpenAIClient:
    """Sends a prompt to a real OpenAI model and returns its answer."""

    def __init__(self, api_key: str, model: str) -> None:
        self._client = AsyncOpenAI(api_key=api_key)
        self._model = model

    async def complete(self, prompt: str) -> str:
        try:
            response = await self._client.chat.completions.create(
                model=self._model,
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
                # Deterministic, not creative -- a classification decision
                # (category/priority/team) should be as reproducible as
                # possible for the same input. temperature=0 minimizes
                # run-to-run sampling variance (mission criterion M4B1:
                # the same ticket submitted twice should get an
                # equivalent answer, not a coin-flip between categories).
                temperature=0,
            )
            return response.choices[0].message.content

        except Exception as error:
            raise LLMProviderError(f"OpenAI request failed: {error}") from error