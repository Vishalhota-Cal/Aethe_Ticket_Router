"""
agents/retrieval_agent.py

The "R" in RAG, wired in as a real pipeline step -- runs before
TriageAgent. Embeds the incoming ticket, looks up similar past tickets
already saved in the database, and stashes both the embedding (so it
can be saved for future tickets to find) and the similar-ticket list
(so TriageAgent can use them as reference context) on the shared
TicketContext.
"""

from ticket_router.agents.base import AgentResult
from ticket_router.domain.models import TicketContext
from ticket_router.llm.embeddings_factory import get_embeddings_client
from ticket_router.persistence.repository import TicketRepository
from ticket_router.rag.retriever import find_similar_tickets


class RetrievalAgent:
    """Looks up similar previously-routed tickets before triage runs."""

    def __init__(self, repository: TicketRepository, top_k: int = 3) -> None:
        self.repository = repository
        self.top_k = top_k

    async def execute(self, context: TicketContext) -> AgentResult:
        ticket = context.ticket
        text = f"{ticket.subject}. {ticket.description}"

        embeddings_client = get_embeddings_client()
        embedding = await embeddings_client.embed(text)
        context.ticket_embedding = embedding

        similar = find_similar_tickets(
            query_embedding=embedding,
            repository=self.repository,
            top_k=self.top_k,
            exclude_ticket_id=ticket.id,
        )
        context.retrieved_context = similar

        return AgentResult(success=True, data=similar, agent_name="RetrievalAgent")