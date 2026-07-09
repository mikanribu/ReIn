"""Test fixtures: isolated SQLite database + a fake LLM.

The fake LLM returns canned extraction results, so the whole workflow
(upload -> extract -> review -> approve -> amend -> audit) is tested
end-to-end without an API key or network access.
"""
import os
import tempfile

import pytest
from fastapi.testclient import TestClient

from app.schemas.treaty_fields import (
    AmendedField,
    AmendmentExtraction,
    ExtractedField,
    TreatyExtraction,
)


def _f(value=None, quote=None, location=None, confidence=0.0, rationale=None) -> ExtractedField:
    return ExtractedField(
        value=value,
        source_quote=quote,
        source_location=location,
        confidence=confidence if value is not None else 0.0,
        rationale=rationale,
    )


def make_fake_extraction() -> TreatyExtraction:
    """A canned extraction mirroring samples/sample_treaty.txt."""
    fields = {key: _f() for key in TreatyExtraction.model_fields}
    fields.update(
        treaty_name=_f("Property Catastrophe Excess of Loss Reinsurance Agreement",
                       quote="PROPERTY CATASTROPHE EXCESS OF LOSS REINSURANCE AGREEMENT",
                       location="Title", confidence=0.99),
        treaty_reference=_f("CAT-XL-2026-001", quote="Contract Reference: CAT-XL-2026-001",
                            location="Header", confidence=0.99),
        treaty_type=_f("cat_xl", quote="each and every loss occurrence", location="Article 3",
                       confidence=0.95, rationale="Per-occurrence property cat cover."),
        form=_f("non_proportional", confidence=0.95),
        cedent=_f("Alpine Insurance Company S.A.", quote="ALPINE INSURANCE COMPANY S.A., Zurich",
                  location="Preamble", confidence=0.99),
        reinsurers=_f(["Helvetia Re (60%)", "Nordic Re (40%)"],
                      quote="Helvetia Re (60%), Nordic Re (40%)", location="Preamble", confidence=0.98),
        broker=_f("Meridian Reinsurance Brokers Ltd", confidence=0.97),
        inception_date=_f("2026-01-01", quote="from 1 January 2026", location="Article 2", confidence=0.99),
        expiry_date=_f("2026-12-31", quote="to 31 December 2026", location="Article 2", confidence=0.99),
        attachment_basis=_f("losses_occurring", quote="losses occurring during the period",
                            location="Article 2", confidence=0.97),
        territory=_f("Switzerland, Germany and Austria", location="Article 1", confidence=0.97),
        lines_of_business=_f(["Property", "Fire", "Engineering", "Allied Perils"],
                             location="Article 1", confidence=0.9),
        currency=_f("CHF", quote="expressed in Swiss Francs (CHF)", location="Article 6", confidence=0.99),
        retention=_f(10_000_000, quote="in excess of CHF 10,000,000 (the \"Priority\")",
                     location="Article 3", confidence=0.98),
        limit=_f(40_000_000, quote="up to a limit of CHF 40,000,000 each and every loss occurrence",
                 location="Article 3", confidence=0.98),
        aggregate_limit=_f(120_000_000, quote="shall not exceed CHF 120,000,000 in the annual period",
                           location="Article 3", confidence=0.97),
        reinstatements=_f("2 @ 100% additional premium pro rata to amount",
                          quote="reinstated twice, each reinstatement at 100% additional premium",
                          location="Article 4", confidence=0.95),
        premium_rate=_f(2.85, quote="a rate of 2.85% of the Company's Gross Net Premium Income",
                        location="Article 5", confidence=0.98),
        minimum_premium=_f(10_500_000, quote="a minimum premium of CHF 10,500,000",
                           location="Article 5", confidence=0.98),
        deposit_premium=_f("CHF 12,000,000 in four equal quarterly instalments",
                           location="Article 5", confidence=0.95),
        estimated_premium_income=_f(450_000_000, quote="GNPI, estimated at CHF 450,000,000",
                                    location="Article 5", confidence=0.97),
        cash_loss_limit=_f(5_000_000, quote="exceeding CHF 5,000,000 (cash loss limit)",
                           location="Article 7", confidence=0.97),
        claims_notification=_f("Notify when UNL estimated to exceed 50% of the Priority",
                               location="Article 8", confidence=0.9),
        exclusions=_f(["War and civil war", "Nuclear energy risks", "Cyber (LMA 5455)",
                       "Pollution unless from covered peril", "Terrorism (NMA 2930)"],
                      location="Article 9", confidence=0.95),
        governing_law=_f("Switzerland", location="Article 11", confidence=0.98),
        arbitration=_f("Zurich, Swiss Rules of International Arbitration",
                       location="Article 11", confidence=0.97),
        special_termination=_f("Loss of 50% paid-up capital, insolvency, rating below A- (AM Best)",
                               location="Article 10", confidence=0.93),
    )
    return TreatyExtraction(**fields)


def make_fake_amendment() -> AmendmentExtraction:
    """A canned amendment mirroring samples/sample_amendment.txt."""
    return AmendmentExtraction(
        summary="Addendum No. 1: limit increased to CHF 50m, aggregate to CHF 150m, "
                "premium rate to 3.10%, minimum premium to CHF 11.5m, effective 1 July 2026.",
        effective_date="2026-07-01",
        changes=[
            AmendedField(field_key="limit", new_value=50_000_000,
                         source_quote="increased from CHF 40,000,000 to CHF 50,000,000",
                         source_location="Clause 1", confidence=0.98,
                         rationale="Occurrence limit increased."),
            AmendedField(field_key="aggregate_limit", new_value=150_000_000,
                         source_quote="aggregate limit is increased from CHF 120,000,000 to CHF 150,000,000",
                         source_location="Clause 1", confidence=0.98,
                         rationale="Annual aggregate increased."),
            AmendedField(field_key="premium_rate", new_value=3.10,
                         source_quote="premium rate is increased from 2.85% to 3.10%",
                         source_location="Clause 2", confidence=0.98,
                         rationale="Rate increase for the larger limit."),
            AmendedField(field_key="minimum_premium", new_value=11_500_000,
                         source_quote="minimum premium is increased to CHF 11,500,000",
                         source_location="Clause 2", confidence=0.97,
                         rationale="Minimum premium increased."),
        ],
    )


class FakeStructuredRunnable:
    def __init__(self, result):
        self._result = result

    def invoke(self, _messages):
        return self._result


class FakeAIMessage:
    def __init__(self, content):
        self.content = content


class FakeChatModel:
    """Duck-typed stand-in for a LangChain chat model. Implements
    with_structured_output (used by extraction) and invoke (used by chat)."""

    def with_structured_output(self, schema):
        from app.schemas.treaty_fields import AmendmentExtraction as AE
        from app.schemas.treaty_fields import TreatyExtraction as TE

        if schema is TE:
            return FakeStructuredRunnable(make_fake_extraction())
        if schema is AE:
            return FakeStructuredRunnable(make_fake_amendment())
        raise AssertionError(f"Unexpected schema: {schema}")

    def invoke(self, messages):
        # Echo back whether treaty context was injected, so chat tests can
        # assert grounding without a real model.
        system = messages[0].content if messages else ""
        last_user = next((m.content for m in reversed(messages)
                          if type(m).__name__ == "HumanMessage"), "")
        grounded = "TREATY CONTEXT" in system
        return FakeAIMessage(
            f"[fake reply|grounded={grounded}] You asked: {last_user}"
        )


@pytest.fixture(scope="module")
def client() -> TestClient:
    # Point the app at a throwaway SQLite file BEFORE anything imports settings.
    # Module scope + a fresh engine give each test file an isolated database, so
    # treaties created in one module don't perturb another's counts.
    tmpdir = tempfile.mkdtemp(prefix="rein-test-")
    os.environ["DATABASE_URL"] = f"sqlite:///{tmpdir}/test.db"

    from app import database
    from app.config import get_settings
    from app.main import create_app
    from app.services.llm import get_chat_model

    get_settings.cache_clear()
    database._engine = None
    database._SessionLocal = None
    app = create_app()
    app.dependency_overrides[get_chat_model] = lambda: FakeChatModel()

    with TestClient(app) as c:
        yield c
