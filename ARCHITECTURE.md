# AI Smart Ticket Router — Architecture (v1, pending approval)

## 1. Scope confirmed with stakeholder (you)

- LLM backend: provider-agnostic. Built against an `LLMClient` abstraction with a `MockClient` (deterministic, no key needed) usable today, plus `AnthropicClient` / `OpenAIClient` adapters ready to activate the moment Calfus hands you a key — a one-line config change, zero code changes.
- Interface: FastAPI service + a thin Streamlit demo UI that calls the API (never the orchestrator directly).
- Persistence: SQLite via SQLAlchemy — every routed ticket and every agent's trace is stored.
- Resilience: full agentic resilience — retries, self-repair of malformed LLM output, safe fallback to human review rather than crashing.

## 2. Folder structure

```
ai-smart-ticket-router/
├── README.md
├── ARCHITECTURE.md
├── pyproject.toml
├── .env.example
├── src/ticket_router/
│   ├── domain/                  # Framework-free core: Pydantic models, enums, exceptions
│   │   ├── models.py             # Ticket, TicketContext, RoutingResult
│   │   ├── enums.py               # Category, Priority, Team
│   │   └── exceptions.py
│   ├── llm/                      # LLM abstraction layer
│   │   ├── client.py              # LLMClient Protocol + LLMResponse
│   │   ├── mock_client.py         # deterministic stub (works with no API key)
│   │   ├── anthropic_client.py
│   │   ├── openai_client.py
│   │   └── factory.py             # picks adapter from Settings.LLM_PROVIDER
│   ├── agents/                   # One class per responsibility
│   │   ├── base.py                # BaseAgent Protocol, AgentResult
│   │   ├── triage_agent.py        # classification + priority + assignment (see §4)
│   │   ├── validation_agent.py    # schema check + repair loop
│   │   └── review_agent.py        # needs_human_review decision
│   ├── orchestration/
│   │   ├── orchestrator.py        # TicketRoutingOrchestrator
│   │   └── resilience.py          # retry/backoff/timeout decorators
│   ├── persistence/
│   │   ├── database.py            # SQLAlchemy engine/session
│   │   ├── models.py              # ORM: TicketRecord, AgentTrace
│   │   └── repository.py          # TicketRepository interface + impl
│   ├── api/
│   │   ├── main.py                # create_app() factory
│   │   ├── routes/tickets.py
│   │   ├── routes/health.py
│   │   └── dependencies.py        # DI: get_orchestrator, get_db
│   ├── observability/
│   │   └── logging_config.py      # structured JSON logs, correlation ID
│   ├── config/
│   │   └── settings.py            # pydantic-settings, .env driven
│   └── ui/
│       └── streamlit_app.py       # calls the FastAPI endpoint only
├── tests/
│   ├── unit/{agents,orchestration,llm}/
│   ├── integration/api/
│   └── conftest.py
└── scripts/run_dev.sh
```

## 3. Core contracts

```python
# domain/models.py
class Ticket(BaseModel):
    id: str
    subject: str
    description: str
    customer_tier: Literal["free", "pro", "enterprise"] | None = None

class RoutingResult(BaseModel):
    category: Category
    priority: Priority
    assigned_team: Team
    reason: str
    confidence_score: int = Field(ge=0, le=100)
    needs_human_review: bool

# agents/base.py
class BaseAgent(Protocol):
    async def execute(self, context: TicketContext) -> AgentResult: ...
```

Agents depend only on `LLMClient` (a Protocol) and domain models — never on FastAPI or SQLAlchemy. This is the Dependency Inversion piece: orchestrator and agents are testable with a `MockClient` and no network at all.

## 4. Decision I want to flag before you approve: agent count vs LLM call count

The assignment names five agents (Classification, Priority, Assignment, Validation, Review). Implemented literally, that's up to 5 separate LLM round-trips per ticket — 5x the latency and 5x the token cost for analysis that mostly reads the *same* ticket text.

Recommendation: keep five agent **responsibilities**, but only two of them talk to the LLM:

- `TriageAgent` — one LLM call, one structured-output schema, returns category + priority + assigned_team + reason + a raw confidence signal. Classification/Priority/Assignment become three internal methods (or three thin sub-agents sharing one prompt/response) rather than three network calls. This is the single biggest cost/latency lever in the whole system.
- `ValidationAgent` — no LLM call in the common case (pure Pydantic validation of TriageAgent's output). Only re-invokes the LLM if the output fails schema validation, to ask it to repair the specific error — capped at 2 repair attempts.
- `ReviewAgent` — deterministic rule engine (confidence threshold, category-specific rules e.g. "Security" always reviewed, validation-failure count). No LLM call. Cheap, fast, fully unit-testable, auditable to compliance in a way "the LLM decided" isn't.

Net effect: 1 LLM call per ticket in the happy path, up to 2 more only on malformed output. The five-agent *interface* (five classes, five responsibilities, independently swappable/testable) stays exactly as specified — I'm only changing how many of them hit the network. If you'd rather keep them as five fully independent LLM calls for stricter separation of concerns, say so and I'll build it that way instead; it's a config flag either way (`PIPELINE_MODE=single_call | multi_call`), so we don't have to lock in permanently.

## 5. Orchestration flow

```
Ticket
  → TriageAgent.execute()        (1 LLM call, structured output)
  → ValidationAgent.execute()    (schema check; repair-retry loop if invalid, max 2 attempts)
  → ReviewAgent.execute()        (deterministic rules → needs_human_review)
  → RoutingResult                (persisted with full AgentTrace)
```

Each step wrapped in a resilience decorator: timeout, retry with exponential backoff (`tenacity`), and structured error capture. If an agent exhausts retries, the orchestrator does not raise to the caller — it returns a `RoutingResult` with `needs_human_review=True`, a low `confidence_score`, and a `reason` explaining the fallback. A support ticket router must never 500 just because an LLM call glitched.

## 6. Persistence

`TicketRecord` (ticket + final RoutingResult) and `AgentTrace` (per-agent raw input/output, latency, retry count) in separate tables, behind a `TicketRepository` interface. Orchestrator and API code never import SQLAlchemy directly — only the repository interface. This buys us: swappable storage later (Postgres in prod), and a debugging trail for every misclassification, which is what actually gets asked for in a production AI system review.

## 7. API + UI

- `create_app(settings)` factory (not a global `app`), so tests can spin up an app with an in-memory DB and a `MockClient`, independent of the real config.
- `POST /tickets/route` — main endpoint. `GET /tickets/{id}` — fetch a past trace. `GET /health`.
- Streamlit app is a pure HTTP client of the API — no business logic duplicated there.

## 8. Config & observability

- `Settings` (pydantic-settings) reads `LLM_PROVIDER`, `LLM_MODEL`, `LLM_API_KEY`, `DATABASE_URL`, `MAX_REPAIR_ATTEMPTS`, `CONFIDENCE_THRESHOLD`, `PIPELINE_MODE`, `LOG_LEVEL` from `.env`. Nothing hardcoded.
- Structured JSON logs with a correlation ID generated per request and threaded through orchestrator → agents → repository, so one ticket's full lifecycle is greppable.

## 9. Testing strategy

- Agents: unit-tested against `MockClient`, no network.
- Orchestrator: tested with fake agents to verify retry/fallback logic in isolation.
- API: `TestClient` + in-memory SQLite.
- This is what makes "AI service" defensible in review — deterministic tests around a nondeterministic model.

---

**Waiting on your approval before writing any code.** Also tell me: keep the single-call `TriageAgent` design in §4, or force five independent LLM calls? And which module should I implement first — I'd suggest `domain/` → `llm/` → `agents/` in that order since everything else depends on them.
