"""Knowledge Base RAG: index, retrieve, and answer with citations."""


def _seed(client):
    from pathlib import Path
    samples = Path(__file__).resolve().parent.parent / "samples"
    with (samples / "sample_treaty.txt").open("rb") as fh:
        doc = client.post(
            "/documents",
            files={"file": ("sample_treaty.txt", fh, "text/plain")},
            data={"kind": "treaty", "actor": "demo"},
        ).json()
    client.post("/extractions", json={"document_id": doc["id"], "actor": "demo"})


def test_reindex_then_status(client):
    _seed(client)
    r = client.post("/kb/reindex")
    assert r.status_code == 200, r.text
    assert r.json()["indexed_chunks"] >= 1

    s = client.get("/kb/status").json()
    assert s["ready"] is True
    assert s["indexed_chunks"] >= 1
    assert s["embedding_model"] == "fake:test"


def test_ask_is_grounded_with_sources(client):
    _seed(client)
    client.post("/kb/reindex")
    r = client.post("/kb/ask", json={"question": "Which treaties exclude cyber?"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["answer"].strip() != ""
    # The sample treaty (CAT-XL-2026-001) mentions cyber in its exclusions, so it
    # should be retrieved and cited.
    assert any("CAT-XL-2026-001" == s["reference"] for s in body["sources"])


def test_ask_rejects_empty_question(client):
    r = client.post("/kb/ask", json={"question": ""})
    assert r.status_code == 422


def test_retrieve_ranks_relevant_chunk_first():
    """Cosine retrieval with the fake embedder ranks the more relevant chunk
    higher — a real ranking check independent of the API."""
    from sqlalchemy.orm import Session

    from app.database import get_engine
    from app.models import Treaty, TreatyChunk
    from app.services import rag
    from tests.conftest import FakeEmbeddings

    emb = FakeEmbeddings()
    with Session(get_engine()) as db:
        t = Treaty(reference="RAG-RANK-TEST", name="Ranking fixture")
        db.add(t)
        db.flush()
        cyber = "Treaty AAA: exclusions War, Cyber, Nuclear terrorism"
        marine = "Treaty BBB: marine hull cargo premium currency USD"
        for i, text in enumerate([cyber, marine]):
            db.add(TreatyChunk(
                treaty_id=t.id, treaty_reference=f"RANK-{i}", treaty_name="x",
                content=text, embedding=emb.embed_query(text), embedding_model=emb.model_id,
            ))
        db.commit()
        hits = rag.retrieve(db, emb, "cyber exclusion", k=5)
    # Only compare the two fixtures we inserted (other tests may add chunks).
    ranked = [h for h in hits if h["reference"].startswith("RANK-")]
    assert "Cyber" in ranked[0]["content"]
