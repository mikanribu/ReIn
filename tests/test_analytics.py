"""Portfolio analytics aggregate the latest version of every treaty."""


def _seed_treaty(client):
    from pathlib import Path
    samples = Path(__file__).resolve().parent.parent / "samples"
    with (samples / "sample_treaty.txt").open("rb") as fh:
        doc = client.post(
            "/documents",
            files={"file": ("sample_treaty.txt", fh, "text/plain")},
            data={"kind": "treaty", "actor": "demo"},
        ).json()
    client.post("/extractions", json={"document_id": doc["id"], "actor": "demo"})


def test_portfolio_analytics_shape_and_counts(client):
    _seed_treaty(client)
    body = client.get("/analytics/portfolio").json()

    assert body["total_treaties"] >= 1

    dims = {b["key"]: b for b in body["breakdowns"]}
    assert {"treaty_type", "reinsurance_basis", "contract_currency_code",
            "product_type", "cession_basis"} <= set(dims)

    # The fake extraction is a USD quota-share treaty, so those buckets exist.
    type_values = {b["value"] for b in dims["treaty_type"]["buckets"]}
    assert any("quota share" in v for v in type_values)

    # Per-currency totals sum only within a currency; USD carries the sample's
    # layer limit (5,000,000) and max cedant retention (1,000,000).
    usd = next((r for r in body["by_currency"] if r["currency"] == "USD"), None)
    assert usd is not None
    assert usd["count"] >= 1
    assert usd["layer_limit_amount"] >= 5_000_000
    assert usd["maximum_cedant_retention_amount"] >= 1_000_000


def test_bucket_counts_sum_to_total(client):
    _seed_treaty(client)
    body = client.get("/analytics/portfolio").json()
    total = body["total_treaties"]
    for breakdown in body["breakdowns"]:
        assert sum(b["count"] for b in breakdown["buckets"]) == total


def test_portfolio_summary(client):
    _seed_treaty(client)
    resp = client.post("/analytics/summary", json={})
    assert resp.status_code == 200, resp.text
    assert resp.json()["summary"].strip() != ""


def test_summary_brief_is_grounded_in_analytics(client):
    # The brief handed to the model must carry the real figures, so the model
    # can't invent them. Check the brief directly.
    _seed_treaty(client)
    from sqlalchemy.orm import Session

    from app.database import get_engine
    from app.services.summary import _brief
    with Session(get_engine()) as db:
        brief, total = _brief(db)
    assert total >= 1
    assert "Total treaties:" in brief
    assert "Totals by currency" in brief
    assert "USD" in brief
