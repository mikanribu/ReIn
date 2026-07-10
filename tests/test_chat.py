"""The chat assistant answers, and grounds in a treaty when given its id."""


def _make_treaty(client) -> str:
    from pathlib import Path
    samples = Path(__file__).resolve().parent.parent / "samples"
    with (samples / "sample_treaty.txt").open("rb") as fh:
        doc = client.post(
            "/documents",
            files={"file": ("sample_treaty.txt", fh, "text/plain")},
            data={"kind": "treaty", "actor": "clementine"},
        ).json()
    # Extraction may already exist from other tests (shared DB); tolerate 409.
    client.post("/extractions", json={"document_id": doc["id"], "actor": "clementine"})
    return client.get("/treaties").json()[0]["id"]


def test_chat_general_without_treaty(client):
    resp = client.post("/chat", json={
        "messages": [{"role": "user", "content": "What is a quota share treaty?"}],
    })
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["grounded_in_treaty"] is False
    assert "grounded=False" in body["reply"]


def test_chat_grounded_in_treaty(client):
    tid = _make_treaty(client)
    resp = client.post("/chat", json={
        "messages": [{"role": "user", "content": "What is the limit?"}],
        "treaty_id": tid,
    })
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["grounded_in_treaty"] is True
    assert "grounded=True" in body["reply"]
    # The fake model appends "SOURCES: Limit; Bogus Field"; the service keeps
    # the real label, drops the fabricated one, and strips the line from the reply.
    assert body["citations"] == ["Limit"]
    assert "SOURCES" not in body["reply"]


def test_chat_general_has_no_citations(client):
    resp = client.post("/chat", json={
        "messages": [{"role": "user", "content": "What is a treaty?"}],
    })
    assert resp.json()["citations"] == []


def test_extract_sources_filters_and_strips():
    from app.services.chat import _extract_sources
    reply = "The limit is CHF 40m and retention CHF 10m.\nSOURCES: Limit; Retention; Made Up"
    clean, cites = _extract_sources(reply, ["Limit", "Retention", "Currency"])
    assert cites == ["Limit", "Retention"]
    assert "SOURCES" not in clean
    assert clean.endswith("CHF 10m.")


def test_extract_sources_absent_line_is_noop():
    from app.services.chat import _extract_sources
    reply = "A general answer with no sources line."
    clean, cites = _extract_sources(reply, ["Limit"])
    assert clean == reply
    assert cites == []


def test_chat_empty_messages_rejected(client):
    resp = client.post("/chat", json={"messages": []})
    assert resp.status_code == 422


def test_chat_unknown_treaty_falls_back_to_general(client):
    resp = client.post("/chat", json={
        "messages": [{"role": "user", "content": "hi"}],
        "treaty_id": "does-not-exist",
    })
    assert resp.status_code == 200, resp.text
    assert resp.json()["grounded_in_treaty"] is False
