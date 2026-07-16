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
    FIELD_KEYS,
    AmendedField,
    AmendmentExtraction,
    BenefitExtraction,
    CessionRuleExtraction,
    ExtractedField,
    ProductExtraction,
    RateExtraction,
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
    """A canned life-reinsurance extraction: treaty-level fields + child rows."""
    fields = {key: _f() for key in FIELD_KEYS}
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
    )
    return TreatyExtraction(
        products=[ProductExtraction(
            product_code="TL-100", product_name="Term Life 20", product_type="term_life",
            product_scope_status="included", source_location="Schedule A", confidence=0.95)],
        benefits=[BenefitExtraction(
            benefit_name="Death Benefit", benefit_type="death",
            source_quote="death benefit", source_location="Schedule B", confidence=0.96)],
        cession_rules=[CessionRuleExtraction(
            country_code="PH", cession_effective_start_date="2027-01-01",
            policy_inception_start_date="2027-01-01", cession_basis="quota_share",
            layer_number=1, layer_name="Base quota share layer",
            cedant_retention_ratio=40, reinsurer_cession_ratio=60,
            layer_attachment_amount=0, layer_limit_amount=5_000_000,
            maximum_cedant_retention_amount=1_000_000, aggregation_basis="per_life",
            priority_order=1, source_quote="the Reinsurer's share shall be 60%",
            source_location="Article 3", confidence=0.98)],
        rates=[
            RateExtraction(age_band="18-29", rate_class="Preferred NS", rate_value=0.72,
                           source_location="Rate table", confidence=0.95),
            RateExtraction(age_band="18-29", rate_class="Standard Smoker", rate_value=1.49,
                           source_location="Rate table", confidence=0.95),
            RateExtraction(age_band="30-39", rate_class="Preferred NS", rate_value=1.29,
                           source_location="Rate table", confidence=0.95),
        ],
        **fields,
    )


def make_fake_amendment() -> AmendmentExtraction:
    """A canned amendment: a treaty-level change + a wholesale-replaced cession layer."""
    return AmendmentExtraction(
        summary="Addendum No. 1: reinsurer share to 70% (retention 30%), layer limit to "
                "USD 7.5m, maximum retention to USD 1.25m, effective 1 July 2027.",
        effective_date="2027-07-01",
        changes=[
            AmendedField(field_key="party_share_percentage", new_value=70,
                         source_quote="the Reinsurer's participation is increased from 60% to 70%",
                         source_location="Clause 1", confidence=0.98,
                         rationale="Participation share increased."),
        ],
        # Cession rules changed → the full new list replaces the old one wholesale.
        cession_rules=[CessionRuleExtraction(
            country_code="PH", cession_effective_start_date="2027-07-01",
            policy_inception_start_date="2027-01-01", cession_basis="quota_share",
            layer_number=1, layer_name="Base quota share layer",
            cedant_retention_ratio=30, reinsurer_cession_ratio=70,
            layer_attachment_amount=0, layer_limit_amount=7_500_000,
            maximum_cedant_retention_amount=1_250_000, aggregation_basis="per_life",
            priority_order=1, source_quote="the layer limit is increased to USD 7,500,000",
            source_location="Clause 2", confidence=0.98)],
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
