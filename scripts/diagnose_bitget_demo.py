#!/usr/bin/env python3
"""Run the encrypted runtime's read-only Bitget check and expose safe API error codes.

This wrapper never prints request headers, signatures, query parameters, or raw
response bodies. It prints only the HTTP status, Bitget API code/message, and
endpoint path after redacting configured credential values.
"""
from __future__ import annotations

import os
import runpy
import sys
from pathlib import Path
from urllib.parse import urlsplit

def redact(value: object) -> str:
    text = str(value)
    for name in ("BITGET_DEMO_API_KEY", "BITGET_DEMO_API_SECRET", "BITGET_DEMO_API_PASSPHRASE"):
        secret = os.environ.get(name, "")
        if secret:
            text = text.replace(secret, "[REDACTED]")
    # Avoid accidentally printing key-like long tokens in API error strings.
    return text[:500]

def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: diagnose_bitget_demo.py RUNTIME_DIRECTORY", file=sys.stderr)
        return 2
    runtime = Path(sys.argv[1]).resolve()
    check_script = runtime / "scripts" / "check_bitget_demo.py"
    if not check_script.is_file():
        print("[FAIL] Encrypted runtime does not contain scripts/check_bitget_demo.py")
        return 2

    try:
        import requests
    except Exception as exc:
        print("[FAIL] Diagnostic dependency unavailable: " + type(exc).__name__)
        return 2

    original_get = requests.Session.get
    original_request = requests.Session.request

    def inspect_response(response, url):
        try:
            if int(response.status_code) >= 400:
                try:
                    body = response.json()
                except Exception:
                    body = {}
                code = body.get("code", "unavailable") if isinstance(body, dict) else "unavailable"
                message = body.get("msg", "No JSON error message returned") if isinstance(body, dict) else "Unexpected response format"
                endpoint = urlsplit(str(url)).path
                print(
                    "[FAIL] Bitget API response: HTTP "
                    + str(response.status_code)
                    + "; code=" + redact(code)
                    + "; message=" + redact(message)
                    + "; endpoint=" + endpoint,
                    flush=True,
                )
        except Exception:
            print("[FAIL] Could not safely decode the Bitget HTTP error response.", flush=True)
        return response

    def patched_get(session, url, *args, **kwargs):
        response = original_get(session, url, *args, **kwargs)
        return inspect_response(response, url)

    def patched_request(session, method, url, *args, **kwargs):
        response = original_request(session, method, url, *args, **kwargs)
        return inspect_response(response, url)

    requests.Session.get = patched_get
    requests.Session.request = patched_request
    sys.path.insert(0, str(runtime))
    try:
        runpy.run_path(str(check_script), run_name="__main__")
    except SystemExit as exc:
        return int(exc.code or 0) if isinstance(exc.code, int) or exc.code is None else 1
    finally:
        requests.Session.get = original_get
        requests.Session.request = original_request
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
