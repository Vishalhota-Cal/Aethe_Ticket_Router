"""
tests/integration/api/test_tickets_route.py

End-to-end tests through the actual FastAPI app (TestClient) -- this
exercises the real route, dependency injection, orchestrator, and
persistence layer together, still against the mock LLM.
"""


def test_route_ticket_endpoint_returns_full_shape(client, sample_ticket):
    response = client.post("/tickets/route", json=sample_ticket.model_dump())

    assert response.status_code == 200
    body = response.json()

    assert "result" in body
    assert "trace" in body
    assert body["result"]["category"] in [
        "Technical", "Billing", "Account", "Security", "General",
    ]
    assert body["result"]["needs_human_review"] in [True, False]


def test_get_ticket_after_routing_returns_saved_record(client, sample_ticket):
    post_response = client.post("/tickets/route", json=sample_ticket.model_dump())
    assert post_response.status_code == 200

    get_response = client.get(f"/tickets/{sample_ticket.id}")
    assert get_response.status_code == 200
    body = get_response.json()
    assert body["id"] == sample_ticket.id
    assert len(body["trace"]) == 4


def test_health_check(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}