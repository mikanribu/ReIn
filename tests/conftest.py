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
    """A canned life-reinsurance extraction for the current catalogue."""
    fields = {key: _f() for key in TreatyExtraction.model_fields}
    fields.update(
        treaty_code=_f("QS-LIFE-2027-01", quote="Treaty Reference: QS-LIFE-2027-01",
                       location="Header", confidence=0.99),
        treaty_name=_f("Quota Share Life Reinsurance Agreement",
                       quote="QUOTA SHARE LIFE REINSURANCE AGREEMENT", location="Title", confidence=0.99),
        treaty_type=_f("quota_share", quote="on a quota share basis", location="Article 1",
                       confidence=0.97, rationale="Proportional quota share cover."),
        reinsurance_basis=_f("automatic", quote="automatic reinsurance", location="Article 1", confidence=0.96),
        cedant_name=_f("Alpine Life Assurance S.A.", quote="ALPINE LIFE ASSURANCE S.A.",
                       location="Preamble", confidence=0.99),
        reinsurer_name=_f("Helvetia Re", quote="HELVETIA RE", location="Preamble", confidence=0.99),
        lead_reinsurer_indicator=_f(True, location="Preamble", confidence=0.9),
        party_share_percentage=_f(60, quote="60% share", location="Preamble", confidence=0.95),
        treaty_effective_start_date=_f("2027-01-01", quote="effective 1 January 2027",
                                       location="Article 2", confidence=0.99),
        new_business_start_date=_f("2027-01-01", quote="new business from 1 January 2027",
                                   location="Article 2", confidence=0.98),
        contract_currency_code=_f("USD", quote="expressed in US Dollars (USD)", location="Article 6", confidence=0.99),
        settlement_currency_code=_f("USD", quote="settled in USD", location="Article 6", confidence=0.98),
        product_code=_f("TL-100", location="Schedule A", confidence=0.9),
        product_name=_f("Term Life 20", location="Schedule A", confidence=0.95),
        product_type=_f("term_life", quote="term life product", location="Schedule A", confidence=0.95),
        product_scope_status=_f("included", location="Schedule A", confidence=0.95),
        benefit_name=_f("Death Benefit", location="Schedule B", confidence=0.96),
        benefit_type=_f("death", quote="death benefit", location="Schedule B", confidence=0.96),
        country_code=_f("PH", quote="Philippines", location="Article 1", confidence=0.95),
        cession_effective_start_date=_f("2027-01-01", location="Article 3", confidence=0.95),
        policy_inception_start_date=_f("2027-01-01", location="Article 3", confidence=0.93),
        cession_basis=_f("quota_share", quote="ceded on a quota share basis", location="Article 3", confidence=0.97),
        layer_number=_f(1, location="Article 3", confidence=0.95),
        layer_name=_f("Base quota share layer", location="Article 3", confidence=0.9),
        layer_1_ceding_ratio=_f(60, quote="60% ceded to the Reinsurer", location="Article 3", confidence=0.97),
        cedant_retention_ratio=_f(40, quote="the Company shall retain 40%", location="Article 3", confidence=0.98),
        reinsurer_cession_ratio=_f(60, quote="the Reinsurer's share shall be 60%",
                                   location="Article 3", confidence=0.98),
        layer_attachment_amount=_f(0, location="Article 3", confidence=0.9),
        layer_limit_amount=_f(5_000_000, quote="up to USD 5,000,000 per life", location="Article 3", confidence=0.97),
        maximum_cedant_retention_amount=_f(1_000_000, quote="maximum retention of USD 1,000,000",
                                           location="Article 4", confidence=0.98),
        aggregation_basis=_f("per_life", quote="aggregated per life", location="Article 4", confidence=0.95),
        priority_order=_f(1, location="Article 3", confidence=0.9),
    )
    return TreatyExtraction(**fields)


def make_fake_amendment() -> AmendmentExtraction:
    """A canned amendment for the current catalogue."""
    return AmendmentExtraction(
        summary="Addendum No. 1: reinsurer cession increased to 70% (retention 30%), "
                "layer limit to USD 7.5m, maximum retention to USD 1.25m, effective 1 July 2027.",
        effective_date="2027-07-01",
        changes=[
            AmendedField(field_key="reinsurer_cession_ratio", new_value=70,
                         source_quote="the Reinsurer's share is increased from 60% to 70%",
                         source_location="Clause 1", confidence=0.98,
                         rationale="Cession share increased."),
            AmendedField(field_key="cedant_retention_ratio", new_value=30,
                         source_quote="the Company's retention is reduced to 30%",
                         source_location="Clause 1", confidence=0.98,
                         rationale="Retention reduced accordingly."),
            AmendedField(field_key="layer_limit_amount", new_value=7_500_000,
                         source_quote="the layer limit is increased to USD 7,500,000",
                         source_location="Clause 2", confidence=0.97,
                         rationale="Layer limit increased."),
            AmendedField(field_key="maximum_cedant_retention_amount", new_value=1_250_000,
                         source_quote="maximum retention is increased to USD 1,250,000",
                         source_location="Clause 2", confidence=0.97,
                         rationale="Maximum retention increased."),
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
        # assert grounding without a real model. When grounded, append a
        # SOURCES line naming a real field label so citation parsing is exercised.
        system = messages[0].content if messages else ""
        last_user = next((m.content for m in reversed(messages)
                          if type(m).__name__ == "HumanMessage"), "")
        grounded = "TREATY CONTEXT" in system
        portfolio = "PORTFOLIO OVERVIEW" in system
        reply = f"[fake reply|grounded={grounded}|portfolio={portfolio}] You asked: {last_user}"
        if grounded:
            # 'Reinsurer Cession Ratio' is a real field label in the seeded
            # treaty; 'Bogus Field' is not and must be filtered out.
            reply += "\nSOURCES: Reinsurer Cession Ratio; Bogus Field"
        return FakeAIMessage(reply)


class FakeEmbeddings:
    """Deterministic bag-of-words hashing embedder — no server needed. Texts
    that share words get similar vectors, so retrieval ordering is meaningful."""

    model_id = "fake:test"
    DIM = 128

    def _vec(self, text: str) -> list[float]:
        import hashlib
        import re
        v = [0.0] * self.DIM
        for tok in re.findall(r"[a-z0-9]+", text.lower()):
            idx = int(hashlib.md5(tok.encode()).hexdigest(), 16) % self.DIM
            v[idx] += 1.0
        return v

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._vec(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vec(text)


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
    from app.services.embeddings import get_embeddings
    from app.services.llm import get_chat_model, get_extraction_model

    get_settings.cache_clear()
    database._engine = None
    database._SessionLocal = None
    app = create_app()
    app.dependency_overrides[get_chat_model] = lambda: FakeChatModel()
    app.dependency_overrides[get_extraction_model] = lambda: FakeChatModel()
    app.dependency_overrides[get_embeddings] = lambda: FakeEmbeddings()

    with TestClient(app) as c:
        yield c
