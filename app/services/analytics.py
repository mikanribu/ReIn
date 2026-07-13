"""Deterministic portfolio analytics.

Aggregate questions ("how many treaties per type?", "total limit by currency?")
are answered here with plain aggregation over the extracted structured fields —
never by the LLM, which cannot be trusted to count. The Knowledge Base's
natural-language summary is fed *these* numbers so it can't invent figures.

Analytics read the latest version of every treaty (approved or not), so a
freshly-ingested corpus shows up immediately.
"""
from collections import Counter, defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import Treaty, TreatyVersion
from app.schemas.treaty_fields import field_label

# Categorical fields we group by. Extend this when a classification field is
# added (e.g. product / segment tags).
CATEGORICAL_DIMENSIONS = ("treaty_type", "currency", "treaty_settlement_exchange_rate_type")

# Numeric fields we total. Summed *within a currency* only (cross-currency sums
# are meaningless), so these appear on the per-currency breakdown.
NUMERIC_MEASURES = ("limit", "aggregate_limit", "estimated_premium_income")


def _display(value) -> str:
    if value is None or value == "":
        return "Unspecified"
    if isinstance(value, list):
        return ", ".join(str(v) for v in value) or "Unspecified"
    if isinstance(value, str):
        return value.replace("_", " ")
    return str(value)


def _as_number(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.replace(",", "").strip())
        except ValueError:
            return None
    return None


def _latest_versions(db: Session):
    treaties = db.scalars(
        select(Treaty).options(
            selectinload(Treaty.versions).selectinload(TreatyVersion.data_points)
        )
    ).all()
    for t in treaties:
        if t.versions:
            yield t, max(t.versions, key=lambda v: v.version_number)


def portfolio_analytics(db: Session) -> dict:
    """Counts per categorical dimension + numeric totals per currency."""
    dim_counts = {dim: Counter() for dim in CATEGORICAL_DIMENSIONS}
    by_currency: dict[str, dict] = defaultdict(
        lambda: {"count": 0, **{m: 0.0 for m in NUMERIC_MEASURES}}
    )

    total = 0
    for _treaty, version in _latest_versions(db):
        total += 1
        values = {dp.field_key: dp.value for dp in version.data_points}
        for dim in CATEGORICAL_DIMENSIONS:
            dim_counts[dim][_display(values.get(dim))] += 1
        currency = _display(values.get("currency"))
        row = by_currency[currency]
        row["count"] += 1
        for measure in NUMERIC_MEASURES:
            n = _as_number(values.get(measure))
            if n is not None:
                row[measure] += n

    breakdowns = [
        {
            "key": dim,
            "label": field_label(dim),
            "buckets": [
                {"value": value, "count": count}
                for value, count in counts.most_common()
            ],
        }
        for dim, counts in dim_counts.items()
    ]

    currency_rows = [
        {
            "currency": currency,
            "count": data["count"],
            **{m: round(data[m], 2) for m in NUMERIC_MEASURES},
        }
        for currency, data in sorted(
            by_currency.items(), key=lambda kv: kv[1]["count"], reverse=True
        )
    ]

    return {
        "total_treaties": total,
        "breakdowns": breakdowns,
        "by_currency": currency_rows,
    }
