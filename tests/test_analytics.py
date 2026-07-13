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
    assert {"treaty_type", "currency", "treaty_settlement_exchange_rate_type"} <= set(dims)

    # The fake extraction is a CHF cat_xl treaty, so those buckets exist.
    type_values = {b["value"] for b in dims["treaty_type"]["buckets"]}
    assert any("cat xl" in v for v in type_values)

    # Per-currency totals sum only within a currency; CHF should carry the
    # sample's limit (40,000,000) and EPI (450,000,000).
    chf = next((r for r in body["by_currency"] if r["currency"] == "CHF"), None)
    assert chf is not None
    assert chf["count"] >= 1
    assert chf["limit"] >= 40_000_000
    assert chf["estimated_premium_income"] >= 450_000_000


def test_bucket_counts_sum_to_total(client):
    _seed_treaty(client)
    body = client.get("/analytics/portfolio").json()
    total = body["total_treaties"]
    for breakdown in body["breakdowns"]:
        assert sum(b["count"] for b in breakdown["buckets"]) == total
