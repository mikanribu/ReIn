"""Translate LLM/extraction failures into clean HTTP errors.

The extraction endpoints call an external service (Claude via LangChain).
Network drops, bad/missing keys, rate limits, overloads and malformed
model output should surface to the user as an actionable message and an
appropriate status code — never a raw 500 with a stack trace.
"""
import logging
from contextlib import contextmanager

from fastapi import HTTPException

logger = logging.getLogger("rein.extraction")


@contextmanager
def translate_llm_errors(action: str):
    """Run an extraction call, mapping known failure modes to HTTPException.

    ``action`` is a short phrase for the message, e.g. "extract the treaty".
    """
    try:
        yield
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001 — deliberately broad; re-raised as HTTP
        status, hint = _classify(exc)
        logger.warning("LLM failure while trying to %s: %s", action, exc, exc_info=True)
        raise HTTPException(
            status_code=status,
            detail=f"Could not {action}: {hint}",
        ) from exc


def _classify(exc: Exception) -> tuple[int, str]:
    """Map an exception to (http_status, human hint) without importing the
    anthropic SDK (kept optional). Classification is by type/attribute names."""
    name = type(exc).__name__
    msg = str(exc)

    # Authentication / configuration
    if name in {"AuthenticationError", "PermissionDeniedError"} or "authentication" in msg.lower():
        return 502, (
            "the extraction service rejected the API credentials. Check that "
            "ANTHROPIC_API_KEY is set correctly (environment or .env)."
        )
    if "could not resolve authentication" in msg.lower() or "api_key" in msg.lower() and "expected" in msg.lower():
        return 502, "no API key is configured for the extraction service. Set ANTHROPIC_API_KEY."

    # Connectivity
    if name in {"APIConnectionError", "APITimeoutError"} or "connection error" in msg.lower():
        return 504, (
            "could not reach the extraction service (network error). "
            "Check connectivity, proxy settings and TLS trust, then retry."
        )

    # Load / rate limiting
    if name == "RateLimitError" or "rate limit" in msg.lower():
        return 429, "the extraction service is rate limited. Wait a moment and retry."
    if name in {"InternalServerError", "OverloadedError"} or "overloaded" in msg.lower():
        return 503, "the extraction service is temporarily overloaded. Retry shortly."

    # Model returned something we couldn't validate into the schema
    if name in {"ValidationError", "OutputParserException"}:
        return 502, "the extracted data did not match the expected schema. Retry, or review the document."

    # Fallback — still a clean 502 rather than a 500 stack trace
    return 502, f"the extraction service returned an unexpected error ({name})."
