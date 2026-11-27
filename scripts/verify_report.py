#!/usr/bin/env python3
"""Read back and validate the final snapshot written by the encrypted runtime."""
from __future__ import annotations

import argparse
import math
import os
import sys
from pathlib import Path
from typing import Any

def as_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return -1

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-root", required=True)
    parser.add_argument("--expected-mode", choices=("four_hour_analysis_and_execution", "position_monitor"), required=True)
    args = parser.parse_args()

    runtime_root = Path(args.runtime_root).resolve()
    if not runtime_root.is_dir():
        print("[VERIFY][FAIL] Decrypted runtime directory is missing.")
        return 1

    sys.path.insert(0, str(runtime_root))
    try:
        from control_plane import ControlPlane
        state = ControlPlane().get_state()
    except Exception as exc:
        print("[VERIFY][FAIL] Could not read Apps Script state (" + type(exc).__name__ + ").")
        return 1

    snapshot = state.get("snapshot") if isinstance(state, dict) else None
    if not isinstance(snapshot, dict):
        print("[VERIFY][FAIL] Apps Script returned no structured snapshot.")
        return 1

    status = str(snapshot.get("run_status") or "missing")
    mode = str(snapshot.get("run_mode") or "missing")
    finished = snapshot.get("run_finished_at")
    report = snapshot.get("report_delivery")
    market = snapshot.get("market_scan") if isinstance(snapshot.get("market_scan"), dict) else {}

    print(f"[VERIFY] run_status={status}; run_mode={mode}; run_finished_at={finished or 'missing'}")
    print(
        "[VERIFY] trading_enabled=" + str(bool(snapshot.get("trading_enabled"))).lower() +
        "; effective_trading_enabled=" + str(bool(snapshot.get("effective_trading_enabled"))).lower() +
        "; new_entries_this_run=" + str(snapshot.get("new_entries_this_run", 0))
    )

    print(
        "[VERIFY] bot_trading_enabled_configured=" +
        str(bool(snapshot.get("bot_trading_enabled_configured", snapshot.get("trading_enabled")))).lower()
    )
    if args.expected_mode == "four_hour_analysis_and_execution":
        print(
            "[SCAN] requested=" + str(market.get("requested_count", "missing")) +
            "; analyzed=" + str(market.get("analyzed_count", "missing")) +
            "; errors=" + str(market.get("error_count", "missing")) +
            "; complete=" + str(market.get("complete", "missing"))
        )
    else:
        print("[MONITOR] analysis_performed=" + str(snapshot.get("analysis_performed", "missing")))

    issues: list[str] = []
    limits = snapshot.get("portfolio_limits")
    if not isinstance(limits, dict):
        issues.append("portfolio_limits is missing from the saved runtime snapshot")
    else:
        required_limits = {
            "max_new_entries_per_run": (0, 80),
            "portfolio_max_notional_x": (0.000001, 21),
            "risk_per_position_pct": (0.000001, 100 / max(1, as_int(limits.get("max_open_positions", 7)))),
            "portfolio_margin_budget_pct": (0.000001, 100),
            "max_exchange_leverage_cap": (1, 125),
        }
        print(
            "[LIMITS] max_new_entries_per_run=" + str(limits.get("max_new_entries_per_run", "missing")) +
            "; portfolio_max_notional_x=" + str(limits.get("portfolio_max_notional_x", "missing")) +
            "; risk_per_position_pct=" + str(limits.get("risk_per_position_pct", "missing")) +
            "; portfolio_margin_budget_pct=" + str(limits.get("portfolio_margin_budget_pct", "missing")) +
            "; max_exchange_leverage_cap=" + str(limits.get("max_exchange_leverage_cap", "missing"))
        )
        for key, (minimum, maximum) in required_limits.items():
            try:
                value = float(limits.get(key))
            except (TypeError, ValueError):
                issues.append("saved portfolio limit " + key + " is missing or non-numeric")
                continue
            if not math.isfinite(value) or value < minimum or value > maximum:
                issues.append("saved portfolio limit " + key + " is outside its validated range")
        try:
            entries = float(limits.get("max_new_entries_per_run"))
            if not entries.is_integer():
                issues.append("max_new_entries_per_run must be an integer")
        except (TypeError, ValueError):
            pass
    if mode != args.expected_mode:
        issues.append("snapshot run_mode does not match the workflow")
    if status not in {"success", "failed"}:
        issues.append("final run_status is missing; the final report may not have been persisted")
    if not finished:
        issues.append("run_finished_at is missing")
    configured_order_entry = snapshot.get(
        "bot_trading_enabled_configured",
        snapshot.get("trading_enabled", False),
    )
    if args.expected_mode == "position_monitor":
        if snapshot.get("trading_enabled") is True:
            issues.append("Position Monitor must keep its own trading_enabled flag false")
        if snapshot.get("effective_trading_enabled") is True:
            issues.append("Position Monitor must keep effective_trading_enabled false")
        if as_int(snapshot.get("new_entries_this_run", 0)) > 0:
            issues.append("Position Monitor reported a new entry even though its entry path is disabled")
    else:
        if bool(snapshot.get("trading_enabled")) != bool(configured_order_entry):
            issues.append("Bot trading_enabled does not match the configured TRADING_ENABLED value")
        if bool(snapshot.get("effective_trading_enabled")) and not bool(configured_order_entry):
            issues.append("effective trading is true while the configured Bot order-entry switch is false")
        maximum_entries = as_int(limits.get("max_new_entries_per_run")) if isinstance(limits, dict) else -1
        entries_this_run = as_int(snapshot.get("new_entries_this_run", 0))
        if entries_this_run < 0 or (maximum_entries >= 0 and entries_this_run > maximum_entries):
            issues.append("new_entries_this_run is outside the configured MAX_NEW_ENTRIES_PER_RUN limit")
        if not bool(configured_order_entry) and entries_this_run > 0:
            issues.append("Bot opened a new entry while TRADING_ENABLED is false")

    if args.expected_mode == "four_hour_analysis_and_execution":
        if snapshot.get("analyze_top_coins") is True:
            if not market:
                issues.append("market_scan result is missing")
            elif as_int(market.get("analyzed_count")) > as_int(market.get("requested_count")):
                issues.append("market_scan analyzed_count exceeds requested_count")
            elif market.get("complete") is True and as_int(market.get("analyzed_count")) != as_int(market.get("requested_count")):
                issues.append("market_scan marks complete with inconsistent counts")
    elif snapshot.get("analysis_performed") is not False:
        issues.append("position monitor unexpectedly reports market analysis")

    if not isinstance(report, dict):
        issues.append("report_delivery telemetry is missing; deploy the latest Code.gs Web App version")
    else:
        received = as_int(report.get("events_received"))
        saved = as_int(report.get("events_saved"))
        print(
            "[REPORT] events_received=" + str(received) +
            "; events_saved=" + str(saved) +
            "; run_end_saved=" + str(report.get("run_end_events_saved")) +
            "; positions_updated=" + str(report.get("positions_updated"))
        )
        print(
            "[TELEGRAM] status=" + str(report.get("notification_status")) +
            "; attempted=" + str(report.get("notifications_attempted")) +
            "; errors=" + str(report.get("notification_errors"))
        )
        if received < 0 or saved != received:
            issues.append("persisted event count does not match received event count")
        if as_int(report.get("run_end_events_received")) < 1 or as_int(report.get("run_end_events_saved")) < 1:
            issues.append("run_end event was not confirmed in the saved report")
        if as_int(report.get("notifications_attempted")) < 1:
            issues.append("no Telegram report notification was attempted")
        if as_int(report.get("notification_errors")) != 0 or report.get("notification_status") != "sent":
            issues.append("Telegram notification did not complete successfully")

    runner_exit = as_int(os.environ.get("RUNNER_EXIT_CODE", "999"))
    print("[VERIFY] runner_exit_code=" + str(runner_exit))
    if runner_exit != 0:
        issues.append("runner.py exited with code " + str(runner_exit))
    if status != "success":
        issues.append("the runner's final snapshot reports a non-success status")

    if issues:
        for issue in issues:
            print("[VERIFY][FAIL] " + issue)
        return 1

    print("[VERIFY][PASS] Final snapshot, event persistence, run_end, Telegram delivery, and safety flags are consistent.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
