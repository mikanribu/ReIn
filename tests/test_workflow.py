"""End-to-end workflow test:

upload -> extract -> review (edit) -> approve -> amend by document ->
approve -> amend manually -> approve -> audit trail integrity.

Tests run in order within this module and share one database (session-scoped
client fixture), mirroring the real lifecycle of a single treaty.
"""
from pathlib import Path

SAMPLES = Path(__file__).resolve().parent.parent / "samples"

state: dict = {}  # ids shared across ordered tests


def _upload(client, path: Path, kind: str) -> dict:
    with path.open("rb") as fh:
        resp = client.post(
            "/documents",
            files={"file": (path.name, fh, "text/plain")},
            data={"kind": kind, "actor": "clementine"},
        )
    assert resp.status_code == 201, resp.text
    return resp.json()


# --------------------------------------------------------------------------
# 1. Upload & extraction
# --------------------------------------------------------------------------

def test_upload_treaty_document(client):
    doc = _upload(client, SAMPLES / "sample_treaty.txt", "treaty")
    assert doc["kind"] == "treaty"
    assert doc["text_length"] > 100
    state["treaty_doc_id"] = doc["id"]


def test_extraction_creates_reviewable_draft(client):
    resp = client.post(
        "/extractions",
        json={"document_id": state["treaty_doc_id"], "actor": "clementine"},
    )
    assert resp.status_code == 201, resp.text
    version = resp.json()
    assert version["version_number"] == 1
    assert version["status"] == "draft"
    assert version["origin"] == "extraction"

    points = {p["field_key"]: p for p in version["data_points"]}
    # Every catalog field is present, found or not.
    catalog = client.get("/catalog").json()
    assert set(points) == set(catalog)

    # Transparency: extracted values carry provenance.
    limit = points["limit"]
    assert limit["value"] == 40_000_000
    assert "40,000,000" in limit["source_quote"]
    assert limit["source_location"] == "Article 3"
    assert limit["confidence"] > 0.9

    # Fields the document doesn't address are visibly not_found, not silently dropped.
    assert points["cession_percentage"]["status"] == "not_found"
    assert points["cession_percentage"]["value"] is None

    treaties = client.get("/treaties").json()
    assert len(treaties) == 1
    state["treaty_id"] = treaties[0]["id"]
    assert treaties[0]["reference"] == "CAT-XL-2026-001"


def test_duplicate_extraction_is_rejected(client):
    resp = client.post(
        "/extractions",
        json={"document_id": state["treaty_doc_id"], "actor": "clementine"},
    )
    assert resp.status_code == 409
    assert "already exists" in resp.json()["detail"]


# --------------------------------------------------------------------------
# 2. Review: manual correction on the draft, then approval
# --------------------------------------------------------------------------

def test_edit_data_point_on_draft(client):
    tid = state["treaty_id"]
    resp = client.patch(
        f"/treaties/{tid}/versions/1/data-points/broker",
        json={"value": "Meridian Reinsurance Brokers Ltd, London",
              "note": "Added domicile per slip", "actor": "clementine"},
    )
    assert resp.status_code == 200, resp.text
    dp = resp.json()
    assert dp["status"] == "edited"
    assert dp["value"].endswith("London")


def test_edit_unknown_field_rejected(client):
    tid = state["treaty_id"]
    resp = client.patch(
        f"/treaties/{tid}/versions/1/data-points/nonexistent_field",
        json={"value": 1, "actor": "clementine"},
    )
    assert resp.status_code == 422


def test_no_current_values_before_approval(client):
    resp = client.get(f"/treaties/{state['treaty_id']}/current")
    assert resp.status_code == 404


def test_approve_version_1(client):
    tid = state["treaty_id"]
    resp = client.post(
        f"/treaties/{tid}/versions/1/approve",
        json={"actor": "clementine", "note": "Checked against signed slip"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "approved"
    assert resp.json()["reviewed_by"] == "clementine"

    current = client.get(f"/treaties/{tid}/current").json()
    assert current["version_number"] == 1
    assert current["values"]["limit"] == 40_000_000
    assert current["values"]["broker"] == "Meridian Reinsurance Brokers Ltd, London"


def test_approved_version_is_immutable(client):
    tid = state["treaty_id"]
    resp = client.patch(
        f"/treaties/{tid}/versions/1/data-points/limit",
        json={"value": 1, "actor": "mallory"},
    )
    assert resp.status_code == 409
    assert "immutable" in resp.json()["detail"]


# --------------------------------------------------------------------------
# 3. Amendment from an adjustment document
# --------------------------------------------------------------------------

def test_amendment_from_document_creates_draft_v2(client):
    doc = _upload(client, SAMPLES / "sample_amendment.txt", "amendment")
    tid = state["treaty_id"]
    resp = client.post(
        f"/treaties/{tid}/amendments/from-document",
        json={"document_id": doc["id"], "actor": "clementine"},
    )
    assert resp.status_code == 201, resp.text
    version = resp.json()
    assert version["version_number"] == 2
    assert version["status"] == "draft"
    assert version["origin"] == "amendment_document"
    assert version["effective_date"] == "2026-07-01"

    points = {p["field_key"]: p for p in version["data_points"]}
    assert points["limit"]["value"] == 50_000_000
    assert points["limit"]["status"] == "amended_by_document"
    assert points["retention"]["value"] == 10_000_000
    assert points["retention"]["status"] == "carried_forward"

    # Diff shows exactly what the amendment changed.
    diff = client.get(f"/treaties/{tid}/versions/2/diff").json()
    changed = {c["field_key"]: c for c in diff["changes"]}
    assert set(changed) == {"limit", "aggregate_limit", "premium_rate", "minimum_premium"}
    assert changed["limit"]["old_value"] == 40_000_000
    assert changed["limit"]["new_value"] == 50_000_000

    # Downstream values are untouched until the amendment is approved.
    assert client.get(f"/treaties/{tid}/current").json()["version_number"] == 1


def test_wrong_document_kind_rejected(client):
    tid = state["treaty_id"]
    resp = client.post(
        f"/treaties/{tid}/amendments/from-document",
        json={"document_id": state["treaty_doc_id"], "actor": "clementine"},
    )
    assert resp.status_code == 422


def test_approve_v2_supersedes_v1(client):
    tid = state["treaty_id"]
    resp = client.post(f"/treaties/{tid}/versions/2/approve", json={"actor": "clementine"})
    assert resp.status_code == 200

    treaty = client.get(f"/treaties/{tid}").json()
    statuses = {v["version_number"]: v["status"] for v in treaty["versions"]}
    assert statuses == {1: "superseded", 2: "approved"}

    current = client.get(f"/treaties/{tid}/current").json()
    assert current["version_number"] == 2
    assert current["values"]["limit"] == 50_000_000
    assert current["values"]["premium_rate"] == 3.10


# --------------------------------------------------------------------------
# 4. Manual amendment
# --------------------------------------------------------------------------

def test_manual_amendment(client):
    tid = state["treaty_id"]
    resp = client.post(
        f"/treaties/{tid}/amendments/manual",
        json={
            "changes": {"broker": "Meridian Re Brokers (Europe) GmbH"},
            "reason": "Broker entity novated to EU subsidiary",
            "effective_date": "2026-09-01",
            "actor": "clementine",
        },
    )
    assert resp.status_code == 201, resp.text
    version = resp.json()
    assert version["version_number"] == 3
    assert version["origin"] == "manual_amendment"
    points = {p["field_key"]: p for p in version["data_points"]}
    assert points["broker"]["status"] == "amended_manually"
    assert points["broker"]["rationale"] == "Broker entity novated to EU subsidiary"

    resp = client.post(f"/treaties/{tid}/versions/3/approve", json={"actor": "clementine"})
    assert resp.status_code == 200
    current = client.get(f"/treaties/{tid}/current").json()
    assert current["version_number"] == 3
    assert current["values"]["broker"] == "Meridian Re Brokers (Europe) GmbH"
    # Prior amendment still in force.
    assert current["values"]["limit"] == 50_000_000


def test_manual_amendment_unknown_key_rejected(client):
    tid = state["treaty_id"]
    resp = client.post(
        f"/treaties/{tid}/amendments/manual",
        json={"changes": {"bogus": 1}, "reason": "x", "actor": "clementine"},
    )
    assert resp.status_code == 422


# --------------------------------------------------------------------------
# 5. Audit trail
# --------------------------------------------------------------------------

def test_audit_trail_records_everything(client):
    tid = state["treaty_id"]
    entries = client.get(f"/treaties/{tid}/audit").json()
    actions = [e["action"] for e in entries]
    for expected in [
        "treaty.extracted",
        "data_point.edited",
        "version.approved",
        "treaty.amendment_extracted",
        "version.superseded",
        "treaty.amended_manually",
    ]:
        assert expected in actions, f"missing audit action {expected}"

    edit = next(e for e in entries if e["action"] == "data_point.edited")
    assert edit["details"]["field_key"] == "broker"
    assert edit["details"]["old_value"] == "Meridian Reinsurance Brokers Ltd"
    assert edit["actor"] == "clementine"


def test_audit_chain_verifies(client):
    resp = client.get("/audit/verify").json()
    assert resp["valid"] is True
    assert resp["entries_checked"] > 5


def test_audit_chain_detects_tampering(client):
    # Tamper with a historical entry directly in the database, bypassing the API.
    from sqlalchemy import text

    from app.database import get_engine

    with get_engine().begin() as conn:
        conn.execute(text("UPDATE audit_log SET actor = 'attacker' WHERE id = 2"))

    resp = client.get("/audit/verify").json()
    assert resp["valid"] is False
    assert resp["first_broken_entry_id"] == 2

    # Restore so other assertions (if re-run) aren't affected.
    with get_engine().begin() as conn:
        conn.execute(text("UPDATE audit_log SET actor = 'clementine' WHERE id = 2"))


# --------------------------------------------------------------------------
# 6. Web UI is served
# --------------------------------------------------------------------------

def test_ui_is_served(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "TreatyIQ" in resp.text
    for asset in ("/static/app.js", "/static/style.css"):
        assert client.get(asset).status_code == 200
