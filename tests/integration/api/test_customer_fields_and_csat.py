"""
tests/integration/api/test_customer_fields_and_csat.py

End-to-end tests through the actual FastAPI app (TestClient) for the
three features added this session that had only been verified manually
via curl before now: customer_name/customer_email on a ticket, the
post-resolution CSAT rating endpoint, and the "contact form" submission
path (which is really just the main route endpoint with those two
fields set and a generic subject).

Without these, a future refactor could silently break any of this and
nothing would catch it -- unlike the rest of the pipeline, which the
older test files already lock in.
"""


def test_customer_name_and_email_round_trip(client):
    payload = {
        "id": "customer-fields-test-1",
        "subject": "Cannot access dashboard",
        "description": "Getting a 500 error whenever I open the dashboard page.",
        "customer_name": "Alex Kim",
        "customer_email": "alex@example.com",
    }
    response = client.post("/tickets/route", json=payload)
    assert response.status_code == 200

    get_response = client.get(f"/tickets/{payload['id']}")
    assert get_response.status_code == 200
    body = get_response.json()
    assert body["customer_name"] == "Alex Kim"
    assert body["customer_email"] == "alex@example.com"
    assert body["satisfaction_rating"] is None

    list_response = client.get("/tickets?limit=200")
    assert list_response.status_code == 200
    matching = [t for t in list_response.json() if t["id"] == payload["id"]]
    assert len(matching) == 1
    assert matching[0]["customer_name"] == "Alex Kim"
    assert matching[0]["customer_email"] == "alex@example.com"


def test_customer_fields_are_optional(client):
    """The main ticket-submission path must keep working when nobody
    fills in a name or email -- these are informational only, never
    required to route a ticket."""
    payload = {
        "id": "customer-fields-test-2",
        "subject": "Password reset not working",
        "description": "The reset link in the email leads to a 404 page.",
    }
    response = client.post("/tickets/route", json=payload)
    assert response.status_code == 200

    get_response = client.get(f"/tickets/{payload['id']}")
    assert get_response.status_code == 200
    body = get_response.json()
    assert body["customer_name"] is None
    assert body["customer_email"] is None


def test_contact_form_style_submission(client):
    """The Contact Us modal doesn't call a separate endpoint -- it
    submits through the same /tickets/route pipeline with a generic
    subject and the name/contact fields set as customer_name/email.
    This proves that path produces a normal, fully-routed ticket."""
    payload = {
        "id": "contact-form-test-1",
        "subject": "Contact form submission",
        "description": "My invoice from last month looks wrong, can someone check it?",
        "customer_name": "Priya Shah",
        "customer_email": "priya@example.com",
    }
    response = client.post("/tickets/route", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert "result" in body
    assert body["result"]["category"] in [
        "Technical", "Billing", "Account", "Security", "General",
    ]

    get_response = client.get(f"/tickets/{payload['id']}")
    assert get_response.status_code == 200
    detail = get_response.json()
    assert detail["customer_name"] == "Priya Shah"
    assert detail["customer_email"] == "priya@example.com"


def test_satisfaction_rating_blocked_before_resolution(client, sample_ticket):
    ticket_id = "csat-test-unresolved"
    payload = sample_ticket.model_dump()
    payload["id"] = ticket_id
    assert client.post("/tickets/route", json=payload).status_code == 200

    response = client.post(f"/tickets/{ticket_id}/satisfaction", json={"rating": 5})
    assert response.status_code == 400


def test_satisfaction_rating_full_flow(client, sample_ticket):
    ticket_id = "csat-test-full-flow"
    payload = sample_ticket.model_dump()
    payload["id"] = ticket_id
    assert client.post("/tickets/route", json=payload).status_code == 200

    admin_update = client.patch(
        f"/tickets/{ticket_id}/admin",
        json={"status": "Resolved", "resolution_comment": "Fixed."},
    )
    assert admin_update.status_code == 200
    assert admin_update.json()["status"] == "Resolved"

    rate_response = client.post(f"/tickets/{ticket_id}/satisfaction", json={"rating": 4})
    assert rate_response.status_code == 200
    assert rate_response.json()["satisfaction_rating"] == 4

    get_response = client.get(f"/tickets/{ticket_id}")
    assert get_response.json()["satisfaction_rating"] == 4


def test_satisfaction_rating_rejects_out_of_range(client, sample_ticket):
    ticket_id = "csat-test-invalid-rating"
    payload = sample_ticket.model_dump()
    payload["id"] = ticket_id
    assert client.post("/tickets/route", json=payload).status_code == 200
    client.patch(f"/tickets/{ticket_id}/admin", json={"status": "Resolved"})

    too_high = client.post(f"/tickets/{ticket_id}/satisfaction", json={"rating": 6})
    assert too_high.status_code == 422

    too_low = client.post(f"/tickets/{ticket_id}/satisfaction", json={"rating": 0})
    assert too_low.status_code == 422


def test_satisfaction_rating_unknown_ticket_is_404(client):
    response = client.post("/tickets/does-not-exist-xyz/satisfaction", json={"rating": 3})
    assert response.status_code == 404


def test_resaving_a_ticket_does_not_wipe_an_existing_rating(client, sample_ticket):
    """Regression test for a real bug found this session: save() built a
    fresh TicketRecord on every call without carrying forward
    satisfaction_rating, so re-routing the same ticket id would silently
    reset any rating a customer had already given back to NULL."""
    ticket_id = "csat-test-resave-preserves-rating"
    payload = sample_ticket.model_dump()
    payload["id"] = ticket_id

    assert client.post("/tickets/route", json=payload).status_code == 200
    client.patch(f"/tickets/{ticket_id}/admin", json={"status": "Resolved"})
    assert client.post(f"/tickets/{ticket_id}/satisfaction", json={"rating": 5}).status_code == 200

    # Re-route the exact same ticket id -- simulates whatever might call
    # save() a second time for the same id.
    reroute = client.post("/tickets/route", json=payload)
    assert reroute.status_code == 200

    get_response = client.get(f"/tickets/{ticket_id}")
    assert get_response.json()["satisfaction_rating"] == 5