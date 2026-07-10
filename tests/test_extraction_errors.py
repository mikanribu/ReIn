"""Extraction failures surface as clean HTTP errors, not raw 500s."""
import os
import tempfile

import pytest
from fastapi.testclient import TestClient


class _ConnErrorLLM:
    """Stand-in chat model that fails the way the SDK does on a network drop."""

    class APIConnectionError(Exception):
        pass

    def with_structured_output(self, schema):
        raise self.APIConnectionError("Connection error.")


@pytest.fixture()
def failing_client() -> TestClient:
    tmpdir = tempfile.mkdtemp(prefix="rein-err-")
    os.environ["DATABASE_URL"] = f"sqlite:///{tmpdir}/err.db"

    from app.config import get_settings
    from app.main import create_app
    from app.services.llm import get_extraction_model

    get_settings.cache_clear()
    app = create_app()
    app.dependency_overrides[get_extraction_model] = lambda: _ConnErrorLLM()
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


def test_extraction_connection_failure_is_clean(failing_client):
    # Upload a treaty document (does not touch the LLM).
    doc = failing_client.post(
        "/documents",
        files={"file": ("t.txt", b"Some treaty text long enough to store.", "text/plain")},
        data={"kind": "treaty", "actor": "clementine"},
    ).json()

    resp = failing_client.post("/extractions", json={"document_id": doc["id"], "actor": "clementine"})
    # Not a 500 — a clean, actionable gateway timeout.
    assert resp.status_code == 504, resp.text
    detail = resp.json()["detail"]
    assert "Could not extract the treaty" in detail
    assert "network" in detail.lower()
