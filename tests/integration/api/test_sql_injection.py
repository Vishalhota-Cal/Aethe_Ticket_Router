"""
tests/integration/api/test_sql_injection.py

Turns the manual curl-based SQL injection proof (done live in a
sandbox, once) into a permanent, automated check. Every field a
customer can type into gets a classic injection payload; the test
passes only if the payload comes back as plain, inert text and nothing
else in the database was disturbed. All persistence goes through
SQLAlchemy's ORM (bound parameters), so none of this should ever be
able to reach the database as an actual SQL command -- this is what
proves that, permanently, instead of trusting it stays true forever.
"""

CLASSIC_PAYLOAD = "'; DROP TABLE tickets; --"
TAUTOLOGY_PAYLOAD = "x' OR '1'='1"
STACKED_PAYLOAD = "Robert'); DROP TABLE tickets;--"


def test_injection_in_subject_and_description_is_stored_as_literal_text(client):
    payload = {
        "id": "sqli-subject-desc",
        "subject": CLASSIC_PAYLOAD,
        "description": TAUTOLOGY_PAYLOAD,
    }
    response = client.post("/tickets/route", json=payload)
    # A real injection vulnerability would either 500 (broken query) or
    # silently corrupt the database -- 200 alone is already a good sign,
    # but the real proof is in what comes back below.
    assert response.status_code == 200

    get_response = client.get(f"/tickets/{payload['id']}")
    assert get_response.status_code == 200
    body = get_response.json()
    # If this were vulnerable, the payload would have altered the query
    # instead of being saved -- getting the exact same string back,
    # untouched, proves it was only ever treated as data.
    assert body["subject"] == CLASSIC_PAYLOAD
    assert body["description"] == TAUTOLOGY_PAYLOAD


def test_injection_in_customer_name_and_email_is_stored_as_literal_text(client):
    payload = {
        "id": "sqli-customer-fields",
        "subject": "Normal subject",
        "description": "Normal description.",
        "customer_name": STACKED_PAYLOAD,
        "customer_email": TAUTOLOGY_PAYLOAD,
    }
    response = client.post("/tickets/route", json=payload)
    assert response.status_code == 200

    body = client.get(f"/tickets/{payload['id']}").json()
    assert body["customer_name"] == STACKED_PAYLOAD
    assert body["customer_email"] == TAUTOLOGY_PAYLOAD


def test_injection_in_ticket_id_does_not_break_lookup(client):
    malicious_id = "1' OR '1'='1"
    payload = {
        "id": malicious_id,
        "subject": "id injection attempt",
        "description": "trying to break the id field itself",
    }
    response = client.post("/tickets/route", json=payload)
    assert response.status_code == 200

    # The exact malicious string has to work as a literal primary key --
    # not match every row, not error out.
    get_response = client.get(f"/tickets/{malicious_id}")
    assert get_response.status_code == 200
    assert get_response.json()["id"] == malicious_id


def test_injection_attempt_does_not_disturb_other_tickets(client, sample_ticket):
    """The real-world danger of SQL injection isn't just "does this one
    request behave oddly" -- it's "did it reach outside its own row and
    touch other data." This creates a normal, unrelated ticket first,
    fires an injection payload, then confirms the original ticket is
    still exactly as it was.
    """
    canary_id = "sqli-canary-ticket"
    canary_payload = sample_ticket.model_dump()
    canary_payload["id"] = canary_id
    assert client.post("/tickets/route", json=canary_payload).status_code == 200

    injection_payload = {
        "id": "sqli-attack-alongside-canary",
        "subject": CLASSIC_PAYLOAD,
        "description": STACKED_PAYLOAD,
    }
    client.post("/tickets/route", json=injection_payload)

    canary_after = client.get(f"/tickets/{canary_id}")
    assert canary_after.status_code == 200
    assert canary_after.json()["subject"] == canary_payload["subject"]
    assert canary_after.json()["description"] == canary_payload["description"]