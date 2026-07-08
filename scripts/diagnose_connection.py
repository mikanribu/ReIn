#!/usr/bin/env python3
"""Diagnose why the Anthropic API can't be reached from this machine.

Run inside your project venv:

    python scripts/diagnose_connection.py

It probes each layer (config -> DNS -> TCP -> TLS -> httpx -> Anthropic SDK)
and prints the *real* underlying error plus a suggested fix. The Anthropic
SDK reports every low-level failure as a generic "APIConnectionError", which
hides the actual cause (SSL cert problem, proxy, DNS, firewall); this script
unwraps it.
"""
from __future__ import annotations

import os
import platform
import socket
import ssl
import sys

HOST = "api.anthropic.com"
PORT = 443
GREEN, RED, YEL, DIM, RST = "\033[32m", "\033[31m", "\033[33m", "\033[2m", "\033[0m"


def ok(msg): print(f"{GREEN}  OK{RST}  {msg}")
def bad(msg): print(f"{RED} FAIL{RST} {msg}")
def info(msg): print(f"{DIM}      {msg}{RST}")
def fix(msg): print(f"{YEL}  FIX{RST} {msg}")


def section(title): print(f"\n=== {title} ===")


def main() -> int:
    section("Environment")
    info(f"Python {sys.version.split()[0]} ({platform.python_implementation()})")
    info(f"Platform {platform.platform()}")
    info(f"OpenSSL {ssl.OPENSSL_VERSION}")

    section("1. Configuration")
    key = os.environ.get("ANTHROPIC_API_KEY")
    # Also look in a local .env (the app reads it; a plain shell does not).
    if not key and os.path.exists(".env"):
        for line in open(".env"):
            if line.strip().startswith("ANTHROPIC_API_KEY="):
                key = line.split("=", 1)[1].strip()
                info("found ANTHROPIC_API_KEY in .env")
                break
    if key:
        ok(f"ANTHROPIC_API_KEY present ({key[:12]}…, {len(key)} chars)")
    else:
        bad("ANTHROPIC_API_KEY not set (env or .env)")
        fix("export ANTHROPIC_API_KEY=sk-ant-... or put it in .env")

    base = os.environ.get("ANTHROPIC_BASE_URL")
    if base:
        info(f"ANTHROPIC_BASE_URL={base}  (custom endpoint — make sure it's correct)")

    proxies = {k: v for k, v in os.environ.items() if k.lower() in
               ("https_proxy", "http_proxy", "all_proxy", "no_proxy")}
    if proxies:
        info(f"proxy env vars: {proxies}")
        info("A VPN/corporate proxy is a common cause — it may block or MITM the TLS connection.")

    section("2. CA certificate bundle")
    paths = ssl.get_default_verify_paths()
    cafile = paths.cafile
    capath = paths.capath
    have_certs = (cafile and os.path.exists(cafile)) or (capath and os.path.isdir(capath) and os.listdir(capath))
    info(f"default cafile: {cafile}")
    info(f"default capath: {capath}")
    try:
        import certifi
        info(f"certifi bundle: {certifi.where()} ({'exists' if os.path.exists(certifi.where()) else 'MISSING'})")
    except ImportError:
        info("certifi not installed")
    if have_certs:
        ok("a CA bundle is present")
    else:
        bad("no usable CA bundle found — TLS verification will fail")
        fix("pip install certifi   (and see the macOS fix under section 4 if on python.org build)")

    section("3. DNS + TCP")
    try:
        ip = socket.gethostbyname(HOST)
        ok(f"DNS: {HOST} -> {ip}")
    except Exception as exc:  # noqa: BLE001
        bad(f"DNS resolution failed: {exc!r}")
        fix("Check your network/VPN/DNS. If offline, connect first.")
        return 1
    try:
        with socket.create_connection((HOST, PORT), timeout=10):
            ok(f"TCP connect to {HOST}:{PORT} succeeded")
    except Exception as exc:  # noqa: BLE001
        bad(f"TCP connect failed: {exc!r}")
        fix("A firewall/VPN is likely blocking outbound 443 to Anthropic.")
        return 1

    section("4. TLS handshake")
    try:
        ctx = ssl.create_default_context()
        with socket.create_connection((HOST, PORT), timeout=10) as sock:
            with ctx.wrap_socket(sock, server_hostname=HOST) as ssock:
                ok(f"TLS handshake OK (cipher {ssock.cipher()[0]})")
    except ssl.SSLCertVerificationError as exc:
        bad(f"TLS certificate verification failed: {exc}")
        print()
        fix("This is the usual Python-3.14-on-macOS cause. Do ONE of:")
        info('  • If you installed Python from python.org, run the bundled installer:')
        info('      /Applications/Python\\ 3.14/Install\\ Certificates.command')
        info("  • Or install certifi and point Python at it:")
        info("      pip install certifi")
        info('      export SSL_CERT_FILE="$(python -c \'import certifi;print(certifi.where())\')"')
        info("  • Or (Homebrew Python) reinstall certificates: brew reinstall ca-certificates")
        return 1
    except ssl.SSLError as exc:
        bad(f"TLS error: {exc}")
        fix("If behind a corporate proxy that re-signs TLS, install its root CA "
            "into your trust store and set SSL_CERT_FILE to it.")
        return 1
    except Exception as exc:  # noqa: BLE001
        bad(f"TLS connect failed: {exc!r}")
        return 1

    section("5. httpx (the client the SDK uses)")
    try:
        import httpx
        r = httpx.get(f"https://{HOST}/v1/models",
                      headers={"x-api-key": key or "none", "anthropic-version": "2023-06-01"},
                      timeout=20)
        ok(f"httpx GET /v1/models -> HTTP {r.status_code} "
           f"({'auth reached' if r.status_code in (200, 401) else 'unexpected'})")
    except Exception as exc:  # noqa: BLE001
        bad(f"httpx failed: {type(exc).__name__}: {exc}")
        fix("If this is an SSL error but section 4 passed, httpx may be using a "
            "different bundle. Try: pip install -U certifi httpx")
        return 1

    section("6. Anthropic SDK")
    if not key:
        info("skipped (no API key) — layers above already prove connectivity.")
        return 0
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=key)
        model = client.models.list().data[0].id
        ok(f"SDK connected — first model id: {model}")
        print(f"\n{GREEN}All good — the app should be able to extract now.{RST}")
        return 0
    except Exception as exc:  # noqa: BLE001
        bad(f"SDK call failed: {type(exc).__name__}: {exc}")
        cause = exc.__cause__ or exc.__context__
        if cause:
            info(f"underlying cause: {type(cause).__name__}: {cause}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
