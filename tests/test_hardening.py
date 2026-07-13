"""Input-safety guards: upload size limit, sample loader, chat history caps."""


def test_load_sample_treaty(client):
    resp = client.post("/documents/sample", data={"kind": "treaty", "actor": "demo"})
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["kind"] == "treaty"
    assert body["text_length"] > 100


def test_load_sample_rejects_unknown_kind(client):
    resp = client.post("/documents/sample", data={"kind": "bogus"})
    assert resp.status_code == 422


def test_upload_too_large_is_rejected(client):
    from app.config import get_settings
    settings = get_settings()
    original = settings.max_upload_bytes
    settings.max_upload_bytes = 10  # 10 bytes
    try:
        resp = client.post(
            "/documents",
            files={"file": ("big.txt", b"x" * 50, "text/plain")},
            data={"kind": "treaty", "actor": "demo"},
        )
        assert resp.status_code == 413, resp.text
        assert "too large" in resp.json()["detail"].lower()
    finally:
        settings.max_upload_bytes = original


def test_chat_rejects_invalid_role(client):
    resp = client.post("/chat", json={
        "messages": [{"role": "system", "content": "hi"}],
    })
    assert resp.status_code == 422  # role must be 'user' or 'assistant'


def test_trim_history_caps_count_and_size():
    from app.schemas.api import ChatMessage
    from app.services.chat import (
        _MAX_HISTORY_MESSAGES,
        _MAX_MESSAGE_CHARS,
        _trim_history,
    )
    history = [ChatMessage(role="user", content="x" * (_MAX_MESSAGE_CHARS + 500))
               for _ in range(_MAX_HISTORY_MESSAGES + 10)]
    trimmed = _trim_history(history)
    assert len(trimmed) == _MAX_HISTORY_MESSAGES
    assert all(len(m.content) <= _MAX_MESSAGE_CHARS + len("… [truncated]") for m in trimmed)
