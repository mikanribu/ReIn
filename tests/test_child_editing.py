"""Draft editing of child collections (products / benefits / cession rules):
per-row edit, add and delete, with validation, immutability and audit checks.

Tests run in order within this module and share one isolated database.
"""
from pathlib import Path

SAMPLES = Path(__file__).resolve().parent.parent / "samples"

state: dict = {}


def _draft(client) -> str:
    """Upload + extract a treaty, returning the (draft v1) treaty id."""
    with (SAMPLES / "sample_treaty.txt").open("rb") as fh:
        doc = client.post(
            "/documents",
            files={"file": ("sample_treaty.txt", fh, "text/plain")},
            data={"kind": "treaty", "actor": "clementine"},
        ).json()
    version = client.post(
        "/extractions", json={"document_id": doc["id"], "actor": "clementine"}
    ).json()
    assert version["status"] == "draft"
    tid = client.get("/treaties").json()[0]["id"]
    return tid


def test_setup_draft(client):
    state["tid"] = _draft(client)
    # The premium rate table is extracted as tidy cells (one row per cell).
    rates = client.get(f"/treaties/{state['tid']}/versions/1").json()["rates"]
    assert len(rates) == 3
    assert {r["rate_class"] for r in rates} == {"Preferred NS", "Standard Smoker"}
    assert rates[0]["rate_value"] == 0.72


def test_add_and_edit_rate_cell(client):
    tid = state["tid"]
    # Add a new cell with a numeric rate coerced from a string.
    added = client.post(
        f"/treaties/{tid}/versions/1/children/rates",
        json={"values": {"age_band": "40-49", "rate_class": "Preferred NS",
                         "rate_value": "1.87"}, "actor": "clementine"},
    )
    assert added.status_code == 200, added.text
    row = added.json()
    assert row["rate_value"] == 1.87

    # Edit that cell's value.
    edited = client.patch(
        f"/treaties/{tid}/versions/1/children/rates/{row['id']}",
        json={"changes": {"rate_value": "1.90"}, "actor": "clementine"},
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["rate_value"] == 1.90
    assert len(client.get(f"/treaties/{tid}/versions/1").json()["rates"]) == 4


def test_edit_child_row_fills_missing_field(client):
    tid = state["tid"]
    version = client.get(f"/treaties/{tid}/versions/1").json()
    benefit = version["benefits"][0]
    assert benefit["benefit_code"] is None  # missing in the fake extraction

    resp = client.patch(
        f"/treaties/{tid}/versions/1/children/benefits/{benefit['id']}",
        json={"changes": {"benefit_code": "BEN-1"},
              "note": "fill missing code", "actor": "clementine"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["benefit_code"] == "BEN-1"

    # Only the changed field is touched; others are preserved.
    again = client.get(f"/treaties/{tid}/versions/1").json()["benefits"][0]
    assert again["benefit_code"] == "BEN-1"
    assert again["benefit_name"] == "Death Benefit"


def test_edit_child_coerces_numeric(client):
    tid = state["tid"]
    rule = client.get(f"/treaties/{tid}/versions/1").json()["cession_rules"][0]
    resp = client.patch(
        f"/treaties/{tid}/versions/1/children/cession-rules/{rule['id']}",
        json={"changes": {"reinsurer_cession_ratio": "55", "layer_number": "1"},
              "actor": "clementine"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["reinsurer_cession_ratio"] == 55.0
    assert body["layer_number"] == 1


def test_add_child_row(client):
    tid = state["tid"]
    resp = client.post(
        f"/treaties/{tid}/versions/1/children/benefits",
        json={"values": {"benefit_name": "Waiver of premium", "benefit_type": "waiver",
                         "benefit_code": "BEN-2"}, "actor": "clementine"},
    )
    assert resp.status_code == 200, resp.text
    row = resp.json()
    assert row["benefit_name"] == "Waiver of premium"
    state["added_benefit_id"] = row["id"]

    benefits = client.get(f"/treaties/{tid}/versions/1").json()["benefits"]
    assert len(benefits) == 2


def test_delete_child_row(client):
    tid = state["tid"]
    bid = state["added_benefit_id"]
    resp = client.request(
        "DELETE",
        f"/treaties/{tid}/versions/1/children/benefits/{bid}",
        json={"actor": "clementine", "note": "remove test benefit"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["deleted"] == bid
    assert len(client.get(f"/treaties/{tid}/versions/1").json()["benefits"]) == 1


def test_unknown_collection_rejected(client):
    tid = state["tid"]
    resp = client.post(
        f"/treaties/{tid}/versions/1/children/widgets", json={"values": {}}
    )
    assert resp.status_code == 404


def test_unknown_child_field_rejected(client):
    tid = state["tid"]
    resp = client.post(
        f"/treaties/{tid}/versions/1/children/products",
        json={"values": {"bogus_field": "x"}},
    )
    assert resp.status_code == 422
    assert "bogus_field" in resp.json()["detail"]


def test_bad_numeric_value_rejected(client):
    tid = state["tid"]
    resp = client.post(
        f"/treaties/{tid}/versions/1/children/cession-rules",
        json={"values": {"layer_number": "not-a-number"}},
    )
    assert resp.status_code == 422


def test_missing_row_rejected(client):
    tid = state["tid"]
    resp = client.patch(
        f"/treaties/{tid}/versions/1/children/products/does-not-exist",
        json={"changes": {"product_code": "X"}},
    )
    assert resp.status_code == 404


def test_child_edit_audited(client):
    tid = state["tid"]
    actions = [e["action"] for e in client.get(f"/treaties/{tid}/audit").json()]
    for expected in ("child_row.edited", "child_row.added", "child_row.deleted"):
        assert expected in actions, f"missing audit action {expected}"


def test_child_edit_blocked_after_approval(client):
    tid = state["tid"]
    assert client.post(f"/treaties/{tid}/versions/1/approve",
                       json={"actor": "clementine"}).status_code == 200
    product = client.get(f"/treaties/{tid}/versions/1").json()["products"][0]
    resp = client.patch(
        f"/treaties/{tid}/versions/1/children/products/{product['id']}",
        json={"changes": {"product_code": "NOPE"}, "actor": "mallory"},
    )
    assert resp.status_code == 409
    assert "immutable" in resp.json()["detail"]
