#!/usr/bin/env python3
"""Redact sensitive material and publish a bounded runtime log for GitHub Actions."""
from __future__ import annotations

import argparse
import re
from pathlib import Path

ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
APPS_SCRIPT_URL_RE = re.compile(
    r"(?i)https?://script\.google\.com/macros/s/[^/\s]+/exec(?:\?[^\s]*)?"
)
SECRET_ASSIGNMENT_RE = re.compile(
    r"""(?i)(["']?\b(?:BITGET_DEMO_API_KEY|BITGET_DEMO_API_SECRET|BITGET_DEMO_API_PASSPHRASE|BOT_BUNDLE_PASSPHRASE|GOOGLE_APPS_SCRIPT_URL|CONTROL_PLANE_TOKEN|TELEGRAM_BOT_TOKEN|TELEGRAM_CHAT_ID|B1D_GITHUB_TOKEN|ACCESS-KEY|ACCESS-SIGN|ACCESS-PASSPHRASE|API[_-]?KEY|API[_-]?SECRET|CLIENT[_-]?(?:KEY|SECRET)|PRIVATE[_-]?KEY|SECRET|SIGNATURE|AUTHORIZATION|PASSWORD|PASSPHRASE|ACCESS[_-]?TOKEN)\b["']?\s*[:=]\s*)"""
    r"""(?:"[^"]*"|'[^']*'|[^\s,;&}\]]+)"""
)
TELEGRAM_URL_RE = re.compile(r"(?i)(https?://api\.telegram\.org/bot)[^/\s]+")
QUERY_SECRET_RE = re.compile(
    r"(?i)([?&](?:sign|signature|api[_-]?key|api[_-]?secret|access[_-]?key|access[_-]?secret|client[_-]?key|private[_-]?key|user_content_key|user_content_signature|webhook_secret|hook|passphrase|token|key|secret)=)[^&#\s]+"
)
BEARER_RE = re.compile(r"(?i)(\bBearer\s+)[A-Za-z0-9._~+/=-]+")
LONG_CREDENTIAL_RE = re.compile(
    r"(?i)\b(?:api[_-]?secret|access[_-]?sign|client[_-]?secret)\b\s*[:=]\s*[A-Za-z0-9+/=_-]{16,}"
)

def sanitize_line(line: str) -> str:
    value = ANSI_RE.sub("", line).replace("\x00", "")
    value = TELEGRAM_URL_RE.sub(r"\1[REDACTED]", value)
    value = APPS_SCRIPT_URL_RE.sub("https://script.google.com/macros/s/[REDACTED]/exec", value)
    value = QUERY_SECRET_RE.sub(r"\1[REDACTED]", value)
    value = BEARER_RE.sub(r"\1[REDACTED]", value)
    value = SECRET_ASSIGNMENT_RE.sub(r"\1[REDACTED]", value)
    value = LONG_CREDENTIAL_RE.sub("[REDACTED_CREDENTIAL]", value)
    return value[:1200]

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--emit", action="store_true")
    parser.add_argument("--max-lines", type=int, default=1800)
    args = parser.parse_args()

    source = Path(args.input)
    if source.exists():
        raw = source.read_text(encoding="utf-8", errors="replace")
    else:
        raw = "[LOG] Runtime log file was not created.\n"

    lines = [sanitize_line(line) for line in raw.splitlines()]
    omitted = 0
    if len(lines) > max(100, args.max_lines):
        keep = max(100, args.max_lines)
        head = min(100, keep // 4)
        tail = keep - head
        omitted = len(lines) - keep
        lines = lines[:head] + [f"[LOG] {omitted} middle lines omitted by the display limit."] + lines[-tail:]

    safe_text = "\n".join(lines) + ("\n" if lines else "")
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(safe_text, encoding="utf-8")

    print(f"[LOG] Sanitized runtime log: {len(lines)} displayed lines; {len(safe_text)} characters.")
    if args.emit:
        for line in lines:
            # Prefix every untrusted line so it cannot be interpreted as a workflow command.
            print("[RUNTIME] " + line)

    return 0

if __name__ == "__main__":
    raise SystemExit(main())
