#!/usr/bin/env python3
"""Guard the public workflows against accidental order-entry unlocks or feed drift."""
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
BOT = (ROOT / ".github/workflows/bot.yml").read_text(encoding="utf-8")
MONITOR = (ROOT / ".github/workflows/position-monitor.yml").read_text(encoding="utf-8")

def require(pattern: str, source: str, description: str) -> None:
    if not re.search(pattern, source, re.MULTILINE):
        raise SystemExit("[FAIL] " + description)
    print("[PASS] " + description)

require(r"^\s*TRADING_ENABLED:\s*'false'(?:\s+#.*)?$", BOT, "Bot order-entry lock is hardcoded false")
require(r"^\s*LIVE_TRADING:\s*'false'(?:\s+#.*)?$", BOT, "Bot mainnet lock is hardcoded false")
require(r"^\s*TRADING_ENABLED:\s*'false'(?:\s+#.*)?$", MONITOR, "Position Monitor order-entry lock is hardcoded false")
require(r"^\s*LIVE_TRADING:\s*'false'(?:\s+#.*)?$", MONITOR, "Position Monitor mainnet lock is hardcoded false")
require(r"^\s*ANALYZE_TOP_COINS:\s*'false'(?:\s+#.*)?$", MONITOR, "Position Monitor cannot scan the market")
require(r"^\s*TRADE_TOP_COINS:\s*'false'(?:\s+#.*)?$", MONITOR, "Position Monitor cannot trade the top-coin universe")
require(r"^\s*SIGNAL_DATA_SOURCE:\s*'bitget_linear'\s*$", MONITOR, "Position Monitor uses the same Bitget Futures candle feed as the Bot")
require(r"scripts/test_apps_script\.js", BOT, "Bot workflow runs Apps Script reporting regression tests")
require(r"scripts/verify_report\.py", BOT, "Bot workflow verifies the persisted final report")
require(r"scripts/verify_report\.py", MONITOR, "Position Monitor verifies the persisted final report")
require(r"scripts/sanitize_runner_log\.py", BOT, "Bot workflow publishes only sanitized runtime diagnostics")
require(r"scripts/sanitize_runner_log\.py", MONITOR, "Position Monitor publishes only sanitized runtime diagnostics")

print("PASS: workflow safety and reporting assertions completed.")
