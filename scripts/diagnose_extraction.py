#!/usr/bin/env python3
"""Reproduce the real extraction call and reveal the underlying error.

Run in your project venv:

    python scripts/diagnose_extraction.py

Unlike the generic connection probe, this exercises the exact code path the
app uses for /extractions — a long-running messages.create with structured
output — and prints the *full* exception chain, which the Anthropic SDK
collapses into a bare "APIConnectionError". It also retries the same request
with streaming enabled, since a long blocking request dropped by a network
middlebox/idle-timeout is the usual cause and streaming is the fix.
"""
from __future__ import annotations

import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import get_settings  # noqa: E402
from app.schemas.treaty_fields import TreatyExtraction  # noqa: E402

SAMPLE = Path(__file__).resolve().parent.parent / "samples" / "sample_treaty.txt"


def print_chain(exc: BaseException) -> None:
    print("\n--- full exception chain (real cause is usually the last one) ---")
    seen = []
    cur: BaseException | None = exc
    while cur is not None and cur not in seen:
        seen.append(cur)
        print(f"  {type(cur).__module__}.{type(cur).__name__}: {cur}")
        cur = cur.__cause__ or cur.__context__
    print("\n--- full traceback ---")
    traceback.print_exception(type(exc), exc, exc.__traceback__)


def main() -> int:
    s = get_settings()
    if not s.anthropic_api_key:
        print("ANTHROPIC_API_KEY not set (env or .env)."); return 2
    key = s.anthropic_api_key
    key = key.get_secret_value() if hasattr(key, "get_secret_value") else str(key)
    text = SAMPLE.read_text()

    from langchain_anthropic import ChatAnthropic

    # 1. Blocking call — the current app behavior.
    print(f"=== Attempt 1: blocking extraction ({s.anthropic_model}) ===")
    t0 = time.time()
    try:
        llm = ChatAnthropic(model=s.anthropic_model, api_key=key, max_tokens=s.llm_max_tokens)
        result = llm.with_structured_output(TreatyExtraction).invoke(text)
        print(f"  OK in {time.time()-t0:.1f}s — extracted treaty '{result.treaty_name.value}'")
        print("  Your network handles the blocking request fine.")
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"  FAILED after {time.time()-t0:.1f}s: {type(exc).__name__}: {exc}")
        print_chain(exc)

    # 2. Streaming call — keeps the connection active with continuous data.
    print(f"\n=== Attempt 2: same extraction with streaming=True ===")
    t0 = time.time()
    try:
        llm = ChatAnthropic(model=s.anthropic_model, api_key=key,
                            max_tokens=s.llm_max_tokens, streaming=True)
        result = llm.with_structured_output(TreatyExtraction).invoke(text)
        print(f"  OK in {time.time()-t0:.1f}s — extracted treaty '{result.treaty_name.value}'")
        print("\n  >>> Streaming works where blocking failed. The fix is to stream the")
        print("  >>> extraction (a network middlebox is dropping the long blocking POST).")
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"  FAILED after {time.time()-t0:.1f}s: {type(exc).__name__}: {exc}")
        print_chain(exc)
        print("\n  Both failed. Paste this whole output back — the exception chain above")
        print("  identifies the real cause (proxy, TLS, HTTP/2, timeout).")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
