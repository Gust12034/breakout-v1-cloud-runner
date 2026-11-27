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

require(r"^\s*TRADING_ENABLED:\s*\$\{\{\s*vars\.TRADING_ENABLED\s*\|\|\s*'false'\s*\}\}\s*$", BOT, "Bot Demo order entry is configurable via repository variable with a false default")
require(r"^\s*LIVE_TRADING:\s*\$\{\{\s*vars\.LIVE_TRADING\s*\|\|\s*'false'\s*\}\}\s*$", BOT, "Bot reads LIVE_TRADING variable with a false default")
require(r"TRADING_ENABLED must be exactly 'true' or 'false'", BOT, "Bot workflow rejects ambiguous order-entry settings")
require(r"LIVE_TRADING must remain false", BOT, "Bot workflow rejects LIVE_TRADING=true")
require(r"LIVE_TRADING must remain false", MONITOR, "Position Monitor rejects LIVE_TRADING=true")
require(r"^\s*TRADING_ENABLED:\s*'false'(?:\s+#.*)?$", MONITOR, "Position Monitor order-entry lock is hardcoded false")
require(r"^\s*LIVE_TRADING:\s*\$\{\{\s*vars\.LIVE_TRADING\s*\|\|\s*'false'\s*\}\}\s*$", MONITOR, "Position Monitor reads LIVE_TRADING variable with a false default")
require(r"^\s*ANALYZE_TOP_COINS:\s*'false'(?:\s+#.*)?$", MONITOR, "Position Monitor cannot scan the market")
require(r"^\s*TRADE_TOP_COINS:\s*'false'(?:\s+#.*)?$", MONITOR, "Position Monitor cannot trade the top-coin universe")
require(r"^\s*SIGNAL_DATA_SOURCE:\s*'bitget_linear'\s*$", MONITOR, "Position Monitor uses the same Bitget Futures candle feed as the Bot")
require(r"scripts/test_apps_script\.js", BOT, "Bot workflow runs Apps Script reporting regression tests")
require(r"scripts/verify_report\.py", BOT, "Bot workflow verifies the persisted final report")
require(r"scripts/verify_report\.py", MONITOR, "Position Monitor verifies the persisted final report")
require(r"scripts/sanitize_runner_log\.py", BOT, "Bot workflow publishes only sanitized runtime diagnostics")
require(r"scripts/sanitize_runner_log\.py", MONITOR, "Position Monitor publishes only sanitized runtime diagnostics")
require(r"scripts/test_log_sanitizer\.py", BOT, "Bot workflow runs secret-redaction regression tests")
require(r"scripts/test_log_sanitizer\.py", MONITOR, "Position Monitor runs secret-redaction regression tests")
require(r"uses:\s*actions/upload-artifact@v7\.0\.2", BOT, "Bot workflow uses the Node 24 compatible upload-artifact release")
require(r"uses:\s*actions/upload-artifact@v7\.0\.2", MONITOR, "Position Monitor uses the Node 24 compatible upload-artifact release")
require(r"BOT_TRADING_ENABLED:\s*\$\{\{\s*vars\.TRADING_ENABLED\s*\|\|\s*'false'\s*\}\}", BOT, "Bot records the configured order-entry variable in its snapshot")
require(r"BOT_TRADING_ENABLED:\s*\$\{\{\s*vars\.TRADING_ENABLED\s*\|\|\s*'false'\s*\}\}", MONITOR, "Position Monitor reports Bot order-entry configuration without enabling entries")

require(r"^\s*MAX_NEW_ENTRIES_PER_RUN:\s*\$\{\{\s*vars\.MAX_NEW_ENTRIES_PER_RUN\s*\|\|\s*'4'\s*\}\}\s*$", BOT, "Bot uses repository Variable MAX_NEW_ENTRIES_PER_RUN")
require(r"^\s*MAX_NEW_ENTRIES_PER_RUN:\s*\$\{\{\s*vars\.MAX_NEW_ENTRIES_PER_RUN\s*\|\|\s*'4'\s*\}\}\s*$", MONITOR, "Position Monitor uses repository Variable MAX_NEW_ENTRIES_PER_RUN")
require(r"^\s*PORTFOLIO_MAX_NOTIONAL_X:\s*\$\{\{\s*vars\.PORTFOLIO_MAX_NOTIONAL_X\s*\|\|\s*'9.0'\s*\}\}\s*$", BOT, "Bot uses repository Variable PORTFOLIO_MAX_NOTIONAL_X")
require(r"^\s*PORTFOLIO_MAX_NOTIONAL_X:\s*\$\{\{\s*vars\.PORTFOLIO_MAX_NOTIONAL_X\s*\|\|\s*'9.0'\s*\}\}\s*$", MONITOR, "Position Monitor uses repository Variable PORTFOLIO_MAX_NOTIONAL_X")
require(r"^\s*RISK_PER_POSITION_PCT:\s*\$\{\{\s*vars\.RISK_PER_POSITION_PCT\s*\|\|\s*'6.5'\s*\}\}\s*$", BOT, "Bot uses repository Variable RISK_PER_POSITION_PCT")
require(r"^\s*RISK_PER_POSITION_PCT:\s*\$\{\{\s*vars\.RISK_PER_POSITION_PCT\s*\|\|\s*'6.5'\s*\}\}\s*$", MONITOR, "Position Monitor uses repository Variable RISK_PER_POSITION_PCT")
require(r"^\s*PORTFOLIO_MARGIN_BUDGET_PCT:\s*\$\{\{\s*vars\.PORTFOLIO_MARGIN_BUDGET_PCT\s*\|\|\s*'100.0'\s*\}\}\s*$", BOT, "Bot uses repository Variable PORTFOLIO_MARGIN_BUDGET_PCT")
require(r"^\s*PORTFOLIO_MARGIN_BUDGET_PCT:\s*\$\{\{\s*vars\.PORTFOLIO_MARGIN_BUDGET_PCT\s*\|\|\s*'100.0'\s*\}\}\s*$", MONITOR, "Position Monitor uses repository Variable PORTFOLIO_MARGIN_BUDGET_PCT")
require(r"^\s*MAX_EXCHANGE_LEVERAGE_CAP:\s*\$\{\{\s*vars\.MAX_EXCHANGE_LEVERAGE_CAP\s*\|\|\s*'10.0'\s*\}\}\s*$", BOT, "Bot uses repository Variable MAX_EXCHANGE_LEVERAGE_CAP")
require(r"^\s*MAX_EXCHANGE_LEVERAGE_CAP:\s*\$\{\{\s*vars\.MAX_EXCHANGE_LEVERAGE_CAP\s*\|\|\s*'10.0'\s*\}\}\s*$", MONITOR, "Position Monitor uses repository Variable MAX_EXCHANGE_LEVERAGE_CAP")

print("PASS: workflow safety and reporting assertions completed.")
