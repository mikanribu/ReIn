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

# Treaty-level categorical fields (stored as flat data points).
TREATY_DIMENSIONS = ("treaty_type", "reinsurance_basis", "contract_currency_code")

# Child-collection categorical fields: (dimension key, version attribute, row attr).
# A treaty is counted once per *distinct* value across its child rows.
CHILD_DIMENSIONS = (
    ("product_type", "products", "product_type"),
    ("cession_basis", "cession_rules", "cession_basis"),
)

# The field that identifies a treaty's currency (used for per-currency totals).
CURRENCY_FIELD = "contract_currency_code"

# Numeric measures summed across a treaty's cession rules, grouped by currency
# (cross-currency sums are meaningless, so they live on the per-currency table).
NUMERIC_MEASURES = ("layer_limit_amount", "maximum_cedant_retention_amount")


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
            selectinload(Treaty.versions).selectinload(TreatyVersion.data_points),
            selectinload(Treaty.versions).selectinload(TreatyVersion.products),
            selectinload(Treaty.versions).selectinload(TreatyVersion.cession_rules),
        )
    ).all()
    for t in treaties:
        if t.versions:
            yield t, max(t.versions, key=lambda v: v.version_number)


def portfolio_analytics(db: Session) -> dict:
    """Counts per categorical dimension + numeric totals per currency."""
    dim_keys = list(TREATY_DIMENSIONS) + [d[0] for d in CHILD_DIMENSIONS]
    dim_counts = {dim: Counter() for dim in dim_keys}
    by_currency: dict[str, dict] = defaultdict(
        lambda: {"count": 0, **{m: 0.0 for m in NUMERIC_MEASURES}}
    )

    total = 0
    for _treaty, version in _latest_versions(db):
        total += 1
        values = {dp.field_key: dp.value for dp in version.data_points}
        for dim in TREATY_DIMENSIONS:
            dim_counts[dim][_display(values.get(dim))] += 1
        # Child dimensions: count the treaty once per distinct value it carries.
        for dim, attr, row_field in CHILD_DIMENSIONS:
            rows = getattr(version, attr)
            distinct = {_display(getattr(r, row_field)) for r in rows} or {_display(None)}
            for v in distinct:
                dim_counts[dim][v] += 1
        # Numeric measures: sum across the treaty's cession rules, by currency.
        currency = _display(values.get(CURRENCY_FIELD))
        row = by_currency[currency]
        row["count"] += 1
        for measure in NUMERIC_MEASURES:
            row[measure] += sum(_as_number(getattr(c, measure)) or 0.0
                                for c in version.cession_rules)

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
