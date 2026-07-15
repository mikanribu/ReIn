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
    # Every treaty-level catalog field is present as a flat data point, found or not.
    catalog = client.get("/catalog").json()
    assert set(points) == set(catalog)

    # Transparency: treaty-level values carry provenance.
    share = points["party_share_percentage"]
    assert share["value"] == 60
    assert "60%" in share["source_quote"]
    assert share["source_location"] == "Preamble"
    assert share["confidence"] > 0.9

    # Fields the document doesn't address are visibly not_found, not silently dropped.
    assert points["treaty_effective_end_date"]["status"] == "not_found"
    assert points["treaty_effective_end_date"]["value"] is None

    # Child collections are extracted as one-to-many rows.
    assert len(version["products"]) == 1
    assert version["products"][0]["product_type"] == "term_life"
    assert len(version["cession_rules"]) == 1
    assert version["cession_rules"][0]["reinsurer_cession_ratio"] == 60

    treaties = client.get("/treaties").json()
    assert len(treaties) == 1
    state["treaty_id"] = treaties[0]["id"]
    assert treaties[0]["reference"] == "QS-LIFE-2027-01"


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
        f"/treaties/{tid}/versions/1/data-points/reinsurer_name",
        json={"value": "Helvetia Re, Zurich",
              "note": "Added domicile per slip", "actor": "clementine"},
    )
    assert resp.status_code == 200, resp.text
    dp = resp.json()
    assert dp["status"] == "edited"
    assert dp["value"].endswith("Zurich")


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
    assert current["values"]["party_share_percentage"] == 60
    assert current["values"]["reinsurer_name"] == "Helvetia Re, Zurich"
    # Children are served under /current too.
    assert current["cession_rules"][0]["reinsurer_cession_ratio"] == 60


def test_approved_version_is_immutable(client):
    tid = state["treaty_id"]
    resp = client.patch(
        f"/treaties/{tid}/versions/1/data-points/party_share_percentage",
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
    assert version["effective_date"] == "2027-07-01"

    points = {p["field_key"]: p for p in version["data_points"]}
    assert points["party_share_percentage"]["value"] == 70
    assert points["party_share_percentage"]["status"] == "amended_by_document"
    assert points["contract_currency_code"]["value"] == "USD"
    assert points["contract_currency_code"]["status"] == "carried_forward"

    # The cession rules were replaced wholesale by the amendment.
    assert version["cession_rules"][0]["reinsurer_cession_ratio"] == 70
    assert version["cession_rules"][0]["layer_limit_amount"] == 7_500_000

    # Diff shows the treaty-level changes (children are replaced wholesale, MVP).
    diff = client.get(f"/treaties/{tid}/versions/2/diff").json()
    changed = {c["field_key"]: c for c in diff["changes"]}
    assert set(changed) == {"party_share_percentage"}
    assert changed["party_share_percentage"]["old_value"] == 60
    assert changed["party_share_percentage"]["new_value"] == 70

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
    assert current["values"]["party_share_percentage"] == 70
    assert current["cession_rules"][0]["reinsurer_cession_ratio"] == 70
    assert current["cession_rules"][0]["cedant_retention_ratio"] == 30


# --------------------------------------------------------------------------
# 4. Manual amendment
# --------------------------------------------------------------------------

def test_manual_amendment(client):
    tid = state["treaty_id"]
    resp = client.post(
        f"/treaties/{tid}/amendments/manual",
        json={
            "changes": {"reinsurer_name": "Helvetia Re Europe GmbH"},
            "reason": "Reinsurer entity novated to EU subsidiary",
            "effective_date": "2027-09-01",
            "actor": "clementine",
        },
    )
    assert resp.status_code == 201, resp.text
    version = resp.json()
    assert version["version_number"] == 3
    assert version["origin"] == "manual_amendment"
    points = {p["field_key"]: p for p in version["data_points"]}
    assert points["reinsurer_name"]["status"] == "amended_manually"
    assert points["reinsurer_name"]["rationale"] == "Reinsurer entity novated to EU subsidiary"

    resp = client.post(f"/treaties/{tid}/versions/3/approve", json={"actor": "clementine"})
    assert resp.status_code == 200
    current = client.get(f"/treaties/{tid}/current").json()
    assert current["version_number"] == 3
    assert current["values"]["reinsurer_name"] == "Helvetia Re Europe GmbH"
    # Prior amendment still in force (children carried forward through the manual amendment).
    assert current["cession_rules"][0]["reinsurer_cession_ratio"] == 70


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
    assert edit["details"]["field_key"] == "reinsurer_name"
    assert edit["details"]["old_value"] == "Helvetia Re"
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
