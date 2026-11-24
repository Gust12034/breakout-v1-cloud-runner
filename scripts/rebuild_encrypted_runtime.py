#!/usr/bin/env python3
"""Safely update numeric portfolio limits inside the encrypted runtime bundle.

The plaintext bundle is only materialized in the Actions runner's temporary
workspace. Neither the passphrase nor decrypted source is written to the repo.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import os
import re
import shutil
import sys
import zipfile
from io import BytesIO
from pathlib import Path, PurePosixPath

MAGIC = b"B1DYNENC1"
AAD = b"Breakout-V1-Demo-Encrypted-Bundle-v1"
KDF_ITERATIONS = 600_000
MAX_OPEN_POSITIONS = 7
MAX_NEW_ENTRIES_PER_RUN = 4


def crypto_modules():
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    return hashes, AESGCM, PBKDF2HMAC


def derive_key(passphrase: str, salt: bytes) -> bytes:
    hashes, _, PBKDF2HMAC = crypto_modules()
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=KDF_ITERATIONS,
    )
    return kdf.derive(passphrase.encode("utf-8"))


def decrypt_bundle(raw: bytes, passphrase: str) -> bytes:
    if len(raw) < len(MAGIC) + 16 + 12 + 16 or not raw.startswith(MAGIC):
        raise RuntimeError("Encrypted runtime format/header validation failed.")
    salt_start = len(MAGIC)
    salt = raw[salt_start:salt_start + 16]
    nonce = raw[salt_start + 16:salt_start + 28]
    ciphertext = raw[salt_start + 28:]
    _, AESGCM, _ = crypto_modules()
    return AESGCM(derive_key(passphrase, salt)).decrypt(nonce, ciphertext, AAD)


def encrypt_bundle(plain: bytes, passphrase: str) -> bytes:
    _, AESGCM, _ = crypto_modules()
    salt = os.urandom(16)
    nonce = os.urandom(12)
    encrypted = AESGCM(derive_key(passphrase, salt)).encrypt(nonce, plain, AAD)
    return MAGIC + salt + nonce + encrypted


def set_integer_assignment(source: str, name: str, allowed_values: set[int], target: int) -> str:
    pattern = re.compile(rf"(?m)^({re.escape(name)}\s*=\s*)(\d+)(\s*)$")
    matches = list(pattern.finditer(source))
    if len(matches) != 1:
        raise RuntimeError(f"Expected exactly one {name} assignment in encrypted runtime.")
    current = int(matches[0].group(2))
    if current not in allowed_values:
        raise RuntimeError(f"Unexpected existing value for {name}; refusing to overwrite.")
    return pattern.sub(lambda m: f"{m.group(1)}{target}{m.group(3)}", source, count=1)


def replace_test_assertion(source: str, old: str, new: str) -> str:
    old_count = source.count(old)
    new_count = source.count(new)
    if old_count == 1 and new_count == 0:
        return source.replace(old, new, 1)
    if old_count == 0 and new_count == 1:
        return source
    raise RuntimeError("Portfolio test assertions did not match the expected old or new form.")



BITGET_MARKET_METHODS = r"""
    def get_usdt_perpetual_contracts(self) -> list[dict[str, Any]]:
        # Public USDT-M futures catalog: the analysis universe must not be limited
        # to instruments exposed by the Demo trading environment.
        data = self._request("GET", "/api/v2/mix/market/contracts", {
            "productType": PRODUCT_TYPE,
        }, demo_header=False)
        if not isinstance(data, list) or any(not isinstance(row, dict) for row in data):
            raise BitgetAPIError("Bitget public USDT-FUTURES contract catalog returned an unexpected response")
        return data

    def get_demo_usdt_perpetual_contracts(self) -> list[dict[str, Any]]:
        # Separate Demo catalog: used only to determine which public markets can
        # be considered for Classic Demo execution.
        data = self._request("GET", "/api/v2/mix/market/contracts", {
            "productType": PRODUCT_TYPE,
        }, demo_header=True)
        if not isinstance(data, list) or any(not isinstance(row, dict) for row in data):
            raise BitgetAPIError("Bitget Demo USDT-FUTURES contract catalog returned an unexpected response")
        return data

    def get_usdt_perpetual_tickers(self) -> list[dict[str, Any]]:
        # Public USDT-M futures tickers contain 24h quoteVolume in USDT.
        data = self._request("GET", "/api/v2/mix/market/tickers", {
            "productType": PRODUCT_TYPE,
        }, demo_header=False)
        if not isinstance(data, list) or any(not isinstance(row, dict) for row in data):
            raise BitgetAPIError("Bitget public USDT-FUTURES ticker catalog returned an unexpected response")
        return data

"""

BITGET_UNIVERSE_FUNCTION = r"""
def build_top_coin_universe(
    bitget_client: Any,
    signal_data_source: str = "binance_spot",
    top_n: int = 100,
    binance_spot_symbols: set[str] | None = None,
) -> dict[str, Any]:
    # Build either the legacy static Binance universe or a live Bitget Futures universe.
    source = str(signal_data_source).lower().strip()
    if source not in {"binance_spot", "bitget_linear"}:
        raise UniverseError("SIGNAL_DATA_SOURCE must be binance_spot or bitget_linear")
    if not 1 <= int(top_n) <= len(STATIC_TOP_100):
        raise UniverseError(f"TOP_COINS_COUNT must be between 1 and {len(STATIC_TOP_100)}")

    contract_map = _valid_contract_map(bitget_client.get_usdt_perpetual_contracts())
    if not contract_map:
        raise UniverseError("Bitget returned no active public USDT perpetual contracts")

    # Demo execution availability is a separate property from public market
    # availability. If the Demo catalog cannot be read, analysis still proceeds,
    # but no symbol is represented as Demo-orderable.
    demo_contract_map = contract_map
    demo_catalog_error = None
    demo_catalog_getter = getattr(bitget_client, "get_demo_usdt_perpetual_contracts", None)
    if callable(demo_catalog_getter):
        try:
            demo_contract_map = _valid_contract_map(demo_catalog_getter())
        except Exception as exc:
            demo_contract_map = {}
            demo_catalog_error = f"{type(exc).__name__}: Demo contract catalog unavailable"

    if source == "bitget_linear":
        ticker_rows = bitget_client.get_usdt_perpetual_tickers()
        ticker_by_symbol: dict[str, tuple[dict[str, Any], float]] = {}
        for row in ticker_rows:
            symbol = str(row.get("symbol") or "").upper()
            if not symbol:
                continue
            try:
                quote_volume = float(row.get("quoteVolume") or 0.0)
            except (TypeError, ValueError):
                continue
            if quote_volume > 0 and quote_volume == quote_volume and quote_volume not in (float("inf"), float("-inf")):
                ticker_by_symbol[symbol] = (row, quote_volume)

        candidates: list[dict[str, Any]] = []
        for base, contract in contract_map.items():
            if base in STABLECOIN_SYMBOLS or str(contract.get("isRwa") or "").upper() == "YES":
                continue
            symbol = str(contract.get("symbol") or f"{base}USDT").upper()
            ticker_data = ticker_by_symbol.get(symbol)
            if ticker_data is None:
                continue
            ticker, quote_volume = ticker_data
            demo_contract = demo_contract_map.get(base)
            demo_symbol = str(demo_contract.get("symbol") or symbol).upper() if demo_contract else None
            last_price = 0.0
            try:
                last_price = float(ticker.get("lastPr") or 0.0)
            except (TypeError, ValueError):
                pass
            candidates.append({
                "rank": 0,
                "market_cap_rank": None,
                "coin_id": base.lower(),
                "name": str(contract.get("baseCoin") or base),
                "coin_symbol": base,
                "symbol": symbol,
                "trade_eligible": bool(demo_symbol and demo_symbol == symbol),
                "execution_symbol": demo_symbol if demo_symbol == symbol else None,
                "market_cap_usd": None,
                "quote_volume_24h_usdt": quote_volume,
                "last_price": last_price,
                "source": "bitget_usdt_futures_quote_volume_24h",
            })

        candidates.sort(
            key=lambda row: (-float(row["quote_volume_24h_usdt"]), str(row["symbol"]))
        )
        if not candidates:
            raise UniverseError(
                "Bitget returned no active USDT perpetual contracts with valid positive 24h quote volume"
            )

        # TOP_COINS_COUNT is a ceiling, not a minimum: analyze all qualified
        # contracts when fewer than the cap are available.
        selected = candidates[:int(top_n)]
        for rank, row in enumerate(selected, start=1):
            row["rank"] = rank

        trade_symbols = [
            row["execution_symbol"] for row in selected
            if row.get("trade_eligible") and row.get("execution_symbol")
        ]
        non_tradeable = [row["symbol"] for row in selected if not row.get("trade_eligible")]
        return {
            "source": "Bitget USDT-M perpetual futures; up to top symbols by 24h quote volume",
            "signal_data_source": source,
            "requested_count": len(selected),
            "limit_count": int(top_n),
            "available_count": len(candidates),
            "selected_count": len(selected),
            "pages_fetched": 0,
            "symbols": [row["symbol"] for row in selected],
            "trade_symbols": trade_symbols,
            "trade_eligible_count": len(trade_symbols),
            "non_tradeable_symbols": non_tradeable,
            "trade_catalog_error": demo_catalog_error,
            "coins": selected,
            "universe_snapshot_date": None,
            "ranking_is_static": False,
            "ranking_metric": "24h quote volume (USDT)",
        }

    # Legacy Binance Spot mode remains supported, but Demo eligibility is
    # determined using the separate Demo catalog when the client exposes it.
    if binance_spot_symbols is None:
        binance_spot_symbols = BinanceSpotData().get_available_usdt_spot_symbols()
    spot_pairs = {str(x).upper() for x in binance_spot_symbols}

    selected: list[dict[str, Any]] = []
    trade_symbols: list[str] = []
    unavailable_spot: list[str] = []
    unavailable_bitget: list[str] = []
    for candidate in STATIC_TOP_100:
        ticker = candidate["symbol"]
        if ticker in STABLECOIN_SYMBOLS:
            continue
        pair = f"{ticker}USDT"
        if pair not in spot_pairs:
            unavailable_spot.append(pair)
            continue
        contract = demo_contract_map.get(ticker)
        if contract:
            execution_pair = str(contract.get("symbol") or pair).upper()
            trade_symbols.append(execution_pair)
        else:
            unavailable_bitget.append(pair)
            execution_pair = None
        selected.append({
            "rank": int(candidate["rank"]),
            "market_cap_rank": int(candidate["rank"]),
            "coin_id": ticker.lower(),
            "name": candidate["name"],
            "coin_symbol": ticker,
            "symbol": pair,
            "trade_eligible": bool(execution_pair),
            "execution_symbol": execution_pair,
            "market_cap_usd": None,
            "source": "binance_spot_usdt_top100_snapshot_2026-11-19",
        })
        if len(selected) == int(top_n):
            break

    if len(selected) != int(top_n):
        raise UniverseError(
            f"Static Top-100 list produced only {len(selected)}/{top_n} analysis symbols. "
            f"Missing Binance Spot USDT pairs: {', '.join(unavailable_spot[:12]) or 'none'}. "
            "No partial analysis universe is accepted."
        )

    return {
        "source": "Binance Spot USDT Top-100 snapshot (2026-11-19); Binance Spot USDT analysis; Bitget Classic Demo trade eligibility",
        "signal_data_source": source,
        "requested_count": int(top_n),
        "limit_count": int(top_n),
        "available_count": len(selected),
        "selected_count": len(selected),
        "pages_fetched": 0,
        "symbols": [row["symbol"] for row in selected],
        "trade_symbols": trade_symbols[:int(top_n)],
        "trade_eligible_count": len(trade_symbols[:int(top_n)]),
        "non_tradeable_symbols": unavailable_bitget,
        "trade_catalog_error": demo_catalog_error,
        "coins": selected,
        "universe_snapshot_date": "2026-11-19",
        "ranking_is_static": True,
        "ranking_metric": "static market-cap snapshot",
    }
"""

UNIVERSE_TESTS = r"""
import unittest

from universe import (
    STATIC_TOP_100, STABLECOIN_SYMBOLS, UniverseError,
    _valid_contract_map, build_top_coin_universe,
)


class FakeBitget:
    def __init__(self, contracts, tickers=None, demo_contracts=None):
        self.contracts = contracts
        self.tickers = list(tickers or [])
        self.demo_contracts = list(demo_contracts if demo_contracts is not None else contracts)
        self.calls = 0
        self.ticker_calls = 0
        self.demo_calls = 0

    def get_usdt_perpetual_contracts(self):
        self.calls += 1
        return self.contracts

    def get_demo_usdt_perpetual_contracts(self):
        self.demo_calls += 1
        return self.demo_contracts

    def get_usdt_perpetual_tickers(self):
        self.ticker_calls += 1
        return self.tickers


def make_contract(symbol):
    base = symbol[:-4]
    return {"symbol": symbol, "baseCoin": base, "quoteCoin": "USDT",
            "symbolStatus": "normal", "symbolType": "perpetual"}


class StaticUniverseTests(unittest.TestCase):
    def test_static_candidate_list_has_exactly_100_unique_symbols(self):
        symbols = [row["symbol"] for row in STATIC_TOP_100]
        self.assertEqual(len(symbols), 100)
        self.assertEqual(len(set(symbols)), 100)

    def test_static_binance_universe_uses_only_exchange_metadata(self):
        candidates = [row["symbol"] for row in STATIC_TOP_100 if row["symbol"] not in STABLECOIN_SYMBOLS]
        contracts = [make_contract(f"{s}USDT") for s in candidates[:5]]
        spot = {f"{s}USDT" for s in candidates[:5]}
        client = FakeBitget(contracts)
        result = build_top_coin_universe(client, top_n=5, binance_spot_symbols=spot)
        self.assertEqual(result["selected_count"], 5)
        self.assertEqual(result["symbols"], [f"{s}USDT" for s in candidates[:5]])
        self.assertTrue(result["ranking_is_static"])
        self.assertEqual(result["pages_fetched"], 0)
        self.assertEqual(client.calls, 1)
        self.assertEqual(client.ticker_calls, 0)

    def test_binance_spot_analysis_trades_only_if_demo_perpetual_exists(self):
        candidates = [row["symbol"] for row in STATIC_TOP_100 if row["symbol"] not in STABLECOIN_SYMBOLS]
        public_contracts = [make_contract(f"{s}USDT") for s in candidates[:3]]
        demo_contracts = [make_contract(f"{candidates[0]}USDT"), make_contract(f"{candidates[2]}USDT")]
        client = FakeBitget(public_contracts, demo_contracts=demo_contracts)
        result = build_top_coin_universe(
            client, top_n=2,
            binance_spot_symbols={f"{candidates[0]}USDT", f"{candidates[2]}USDT"},
        )
        self.assertEqual(result["symbols"], [f"{candidates[0]}USDT", f"{candidates[2]}USDT"])
        self.assertEqual(result["trade_symbols"], [f"{candidates[0]}USDT", f"{candidates[2]}USDT"])
        self.assertEqual(result["trade_eligible_count"], 2)

    def test_fails_closed_if_not_enough_binance_spot_analysis_pairs(self):
        candidates = [row["symbol"] for row in STATIC_TOP_100]
        contracts = [make_contract(f"{s}USDT") for s in candidates[:3]]
        with self.assertRaisesRegex(UniverseError, "only 2/3 analysis symbols"):
            build_top_coin_universe(
                FakeBitget(contracts), top_n=3,
                binance_spot_symbols={f"{s}USDT" for s in candidates[:2]},
            )

    def test_stablecoins_are_not_in_the_static_candidate_list(self):
        symbols = {row["symbol"] for row in STATIC_TOP_100}
        self.assertTrue(symbols.isdisjoint(STABLECOIN_SYMBOLS))

    def test_rejects_invalid_source_and_size(self):
        client = FakeBitget([make_contract("BTCUSDT")])
        with self.assertRaisesRegex(UniverseError, "SIGNAL_DATA_SOURCE"):
            build_top_coin_universe(client, signal_data_source="unknown", top_n=1,
                                    binance_spot_symbols={"BTCUSDT"})
        with self.assertRaisesRegex(UniverseError, "between 1 and 100"):
            build_top_coin_universe(client, top_n=101, binance_spot_symbols={"BTCUSDT"})


class BitgetFuturesUniverseTests(unittest.TestCase):
    def test_bitget_linear_selects_top_n_real_usdt_perpetuals_by_quote_volume(self):
        contracts = [make_contract(f"COIN{i:03d}USDT") for i in range(105)]
        tickers = [
            {"symbol": f"COIN{i:03d}USDT", "quoteVolume": str((i + 1) * 1000), "lastPr": "1"}
            for i in range(105)
        ]
        # Only 30 are available to Classic Demo; all 100 public markets remain
        # eligible for analysis.
        demo_contracts = [make_contract(f"COIN{i:03d}USDT") for i in range(30, 60)]
        client = FakeBitget(contracts, tickers, demo_contracts=demo_contracts)
        result = build_top_coin_universe(client, signal_data_source="bitget_linear", top_n=100)

        self.assertEqual(result["requested_count"], 100)
        self.assertEqual(result["limit_count"], 100)
        self.assertEqual(result["available_count"], 105)
        self.assertEqual(result["selected_count"], 100)
        self.assertEqual(result["trade_eligible_count"], 30)
        self.assertEqual(len(result["symbols"]), 100)
        self.assertEqual(len(result["trade_symbols"]), 30)
        self.assertEqual(result["symbols"][0], "COIN104USDT")
        self.assertEqual(result["symbols"][-1], "COIN005USDT")
        self.assertTrue(all(row["trade_eligible"] for row in result["coins"] if row["symbol"] in result["trade_symbols"]))
        self.assertEqual(result["ranking_metric"], "24h quote volume (USDT)")
        self.assertFalse(result["ranking_is_static"])
        self.assertEqual(client.calls, 1)
        self.assertEqual(client.demo_calls, 1)
        self.assertEqual(client.ticker_calls, 1)

    def test_bitget_linear_uses_all_available_markets_below_100_cap(self):
        contracts = [make_contract(f"COIN{i:03d}USDT") for i in range(42)]
        tickers = [
            {"symbol": f"COIN{i:03d}USDT", "quoteVolume": str((i + 1) * 1000), "lastPr": "1"}
            for i in range(42)
        ]
        client = FakeBitget(contracts, tickers)
        result = build_top_coin_universe(client, signal_data_source="bitget_linear", top_n=100)
        self.assertEqual(result["requested_count"], 42)
        self.assertEqual(result["limit_count"], 100)
        self.assertEqual(result["available_count"], 42)
        self.assertEqual(result["selected_count"], 42)
        self.assertEqual(len(result["symbols"]), 42)

    def test_bitget_linear_fails_only_when_no_valid_markets_are_available(self):
        contracts = [make_contract("BTCUSDT"), make_contract("USDCUSDT"), make_contract("ETHUSDT")]
        tickers = [
            {"symbol": "BTCUSDT", "quoteVolume": "0"},
            {"symbol": "USDCUSDT", "quoteVolume": "999999"},
            {"symbol": "ETHUSDT", "quoteVolume": "NaN"},
        ]
        with self.assertRaisesRegex(UniverseError, "no active USDT perpetual contracts"):
            build_top_coin_universe(
                FakeBitget(contracts, tickers),
                signal_data_source="bitget_linear",
                top_n=100,
            )


if __name__ == "__main__":
    unittest.main()
"""

def patch_bitget_demo(source: str) -> str:
    start = source.find("    def get_usdt_perpetual_contracts(")
    end = source.find("    @staticmethod\n    def _granularity", start)
    if start < 0 or end < 0:
        raise RuntimeError("Bitget market-method patch anchor not found.")
    updated = source[:start] + BITGET_MARKET_METHODS + source[end:]

    candle_old = '''            "granularity": self._granularity(interval), "limit": min(max(int(limit), 1), 1000),
        })'''
    candle_new = '''            "granularity": self._granularity(interval), "limit": min(max(int(limit), 1), 1000),
        }, demo_header=False)'''
    if candle_old in updated:
        updated = updated.replace(candle_old, candle_new, 1)
    elif candle_new not in updated:
        raise RuntimeError("Public futures-candle request patch anchor not found.")

    price_start = updated.find("    def get_last_price(")
    price_end = updated.find("    def _get_account_info(", price_start)
    if price_start < 0 or price_end < 0:
        raise RuntimeError("Public futures-price patch anchor not found.")
    price_block = updated[price_start:price_end]
    price_old = '''            "productType": PRODUCT_TYPE, "symbol": symbol.upper(),
        })'''
    price_new = '''            "productType": PRODUCT_TYPE, "symbol": symbol.upper(),
        }, demo_header=False)'''
    if price_old in price_block:
        price_block = price_block.replace(price_old, price_new, 1)
        updated = updated[:price_start] + price_block + updated[price_end:]
    elif price_new not in price_block:
        raise RuntimeError("Public futures-ticker request patch anchor not found.")

    compile(updated, "bitget_demo.py", "exec")
    return updated

def patch_bitget_tests(source: str) -> str:
    old_name = "def test_get_usdt_perpetual_contracts_uses_classic_v2_demo_market_route(self):"
    new_name = "def test_get_usdt_perpetual_contracts_uses_public_classic_v2_market_route(self):"
    source = source.replace(old_name, new_name, 1)

    start = source.find("    def test_get_usdt_perpetual_contracts_uses_public_classic_v2_market_route(")
    end = source.find("\n    def test_demo_header_is_kept_on_demo_market_requests(", start)
    if start < 0 or end < 0:
        raise RuntimeError("Bitget public-catalog test patch anchor not found.")
    block = source[start:end]
    block = block.replace('self.assertTrue(kwargs.get("demo_header"))',
                          'self.assertFalse(kwargs.get("demo_header"))', 1)
    source = source[:start] + block + source[end:]

    demo_test = '''    def test_get_demo_usdt_perpetual_contracts_uses_classic_v2_demo_market_route(self):
        self.client._request = Mock(return_value=[{"symbol": "BTCUSDT", "baseCoin": "BTC"}])
        rows = self.client.get_demo_usdt_perpetual_contracts()
        self.assertEqual(rows[0]["symbol"], "BTCUSDT")
        args, kwargs = self.client._request.call_args
        self.assertEqual(args[1], "/api/v2/mix/market/contracts")
        self.assertEqual(args[2]["productType"], "USDT-FUTURES")
        self.assertTrue(kwargs.get("demo_header"))

'''
    marker = "    def test_demo_header_is_kept_on_demo_market_requests(self):"
    if "def test_get_demo_usdt_perpetual_contracts_uses_classic_v2_demo_market_route(" not in source:
        if marker not in source:
            raise RuntimeError("Bitget Demo-catalog test insertion anchor not found.")
        source = source.replace(marker, demo_test + marker, 1)

    kstart = source.find("    def test_get_klines_normalizes_and_sorts_oldest_first(")
    kend = source.find("\n    def test_get_instrument_rules(", kstart)
    if kstart < 0 or kend < 0:
        raise RuntimeError("Bitget public-kline test patch anchor not found.")
    kblock = source[kstart:kend]
    expected = '        self.assertEqual(args[2]["productType"], "USDT-FUTURES")'
    if 'self.assertFalse(kwargs.get("demo_header"))' not in kblock:
        if expected not in kblock:
            raise RuntimeError("Bitget public-kline assertion anchor not found.")
        kblock = kblock.replace(
            expected,
            expected + '\n        self.assertFalse(kwargs.get("demo_header"))',
            1,
        )
        source = source[:kstart] + kblock + source[kend:]

    compile(source, "tests/test_bitget_demo.py", "exec")
    return source

def patch_universe(source: str) -> str:
    source = source.replace(
        '"""Static ranked candidate universe; no third-party ranking API is used."""',
        '"""Static Binance-spot or live Bitget USDT-perpetual ranked candidate universe."""',
    )
    start = source.find("def build_top_coin_universe(")
    if start < 0:
        raise RuntimeError("Universe function patch anchor not found.")
    updated = source[:start] + BITGET_UNIVERSE_FUNCTION
    compile(updated, "universe.py", "exec")
    return updated

def patch_runner(source: str) -> str:
    old_heading = 'f"📊 اسکن بازار بر اساس فهرست ثابت ۱۰۰ کوین انجام شد.\\n"'
    new_heading = 'f"📊 اسکن حداکثر ۱۰۰ قرارداد فعال Bitget USDT-Futures بر اساس حجم ۲۴ساعته انجام شد.\\n"'
    if old_heading in source:
        source = source.replace(old_heading, new_heading, 1)
    elif new_heading not in source:
        raise RuntimeError("Runner Telegram heading patch anchor not found.")

    old_trade_block = '''                    symbols = list(universe["trade_symbols"])
                    if not symbols:
                        raise RuntimeError("No Top-100 symbols have an active Bitget USDT perpetual contract")
                    strategy_state["active_trade_universe"] = list(symbols)
                    snapshot["symbols"] = list(symbols)
                    snapshot["trade_symbols"] = list(symbols)'''
    new_trade_block = '''                    trade_symbols = list(universe["trade_symbols"])
                    snapshot["analysis_symbols"] = list(universe.get("symbols", []))
                    snapshot["trade_symbols"] = list(trade_symbols)
                    if trade_symbols:
                        symbols = list(trade_symbols)
                        strategy_state["active_trade_universe"] = list(trade_symbols)
                    else:
                        saved_universe = strategy_state.get("active_trade_universe") or []
                        symbols = list(dict.fromkeys(str(x).upper() for x in saved_universe if x)) or configured_symbols
                    snapshot["symbols"] = list(symbols)
                    if universe.get("trade_catalog_error"):
                        scan_error = "Classic Demo tradable-market catalog could not be verified; new entries are blocked."
                        events.append(event(
                            "demo_execution_universe_unavailable",
                            "🚨 فهرست قراردادهای قابل سفارش در Bitget Classic Demo قابل بررسی نبود؛ تحلیل بازار انجام شد اما ورود جدید مسدود است.",
                            {"error": universe.get("trade_catalog_error"), "analysis_symbols": len(universe.get("symbols", []))},
                        ))
                    elif not trade_symbols:
                        scan_error = "No selected public futures contracts are available for Classic Demo execution; new entries are blocked."
                        events.append(event(
                            "demo_execution_universe_empty",
                            "⚠️ اسکن بازار انجام شد، اما هیچ‌یک از قراردادهای منتخب در Bitget Classic Demo قابل سفارش نبودند؛ ورود جدید مسدود است.",
                            {"analysis_symbols": len(universe.get("symbols", [])), "demo_trade_symbols": 0},
                        ))'''
    if old_trade_block in source:
        source = source.replace(old_trade_block, new_trade_block, 1)
    elif 'snapshot["analysis_symbols"] = list(universe.get("symbols", []))' not in source:
        raise RuntimeError("Runner analysis/trade-universe separation patch anchor not found.")

    old_meta = '"trade_eligible_count": universe.get("trade_eligible_count", 0),'
    if '"available_count": universe.get("available_count"' not in source:
        new_meta = old_meta + (
            '\n                        "available_count": universe.get("available_count", universe.get("selected_count", 0)),'
            '\n                        "limit_count": universe.get("limit_count", universe.get("requested_count", 0)),'
            '\n                        "trade_catalog_error": universe.get("trade_catalog_error"),'
        )
        if old_meta not in source:
            raise RuntimeError("Runner scan-metadata patch anchor not found.")
        source = source.replace(old_meta, new_meta, 1)

    source = source.replace(
        "قابل معامله در Bitget:",
        "قابل‌اجرا در Bitget Classic Demo:",
        1,
    )
    compile(source, "runner.py", "exec")
    return source

def safe_runtime_path(root: Path, archive_name: str) -> Path:
    rel = PurePosixPath(archive_name)
    if rel.is_absolute() or ".." in rel.parts or not rel.parts:
        raise RuntimeError("Encrypted bundle contains an unsafe archive path.")
    target = (root / Path(*rel.parts)).resolve()
    if root.resolve() not in target.parents and target != root.resolve():
        raise RuntimeError("Encrypted bundle path escaped the temporary runtime directory.")
    return target


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--checksum-file", required=True)
    parser.add_argument("--runtime-output", required=True)
    args = parser.parse_args()

    passphrase = os.environ.get("BOT_BUNDLE_PASSPHRASE", "")
    if len(passphrase) < 32:
        raise RuntimeError("Required bundle decryption secret is unavailable.")

    input_path = Path(args.input)
    checksum_path = Path(args.checksum_file)
    raw = input_path.read_bytes()

    checksum_line = checksum_path.read_text(encoding="utf-8").strip().split()
    if len(checksum_line) < 2 or checksum_line[1] != "bot_payload.bin":
        raise RuntimeError("Existing payload checksum manifest is invalid.")
    expected_hash = checksum_line[0].lower()
    if hashlib.sha256(raw).hexdigest() != expected_hash:
        raise RuntimeError("Existing encrypted runtime checksum does not match its manifest.")

    plain = decrypt_bundle(raw, passphrase)
    patched_config = None
    patched_tests = None
    config_name = None
    tests_name = None
    rebuilt_zip = BytesIO()

    with zipfile.ZipFile(BytesIO(plain), "r") as source_zip:
        names = source_zip.namelist()
        config_candidates = [n for n in names if PurePosixPath(n).name == "PORTFOLIO_RISK_SETTINGS.py"]
        test_candidates = [n for n in names if n.endswith("tests/test_portfolio_risk.py")]
        universe_candidates = [n for n in names if PurePosixPath(n).name == "universe.py"]
        bitget_candidates = [n for n in names if PurePosixPath(n).name == "bitget_demo.py"]
        runner_candidates = [n for n in names if PurePosixPath(n).name == "runner.py"]
        universe_test_candidates = [n for n in names if n.endswith("tests/test_universe.py")]
        bitget_test_candidates = [n for n in names if n.endswith("tests/test_bitget_demo.py")]
        if (len(config_candidates) != 1 or len(test_candidates) != 1
                or len(universe_candidates) != 1 or len(bitget_candidates) != 1
                or len(runner_candidates) != 1 or len(universe_test_candidates) != 1
                or len(bitget_test_candidates) != 1):
            raise RuntimeError("Required runtime source/test files were not found uniquely in the payload.")
        config_name = config_candidates[0]
        tests_name = test_candidates[0]
        universe_name = universe_candidates[0]
        bitget_name = bitget_candidates[0]
        runner_name = runner_candidates[0]
        universe_test_name = universe_test_candidates[0]
        bitget_test_name = bitget_test_candidates[0]

        with zipfile.ZipFile(rebuilt_zip, "w") as target_zip:
            for info in source_zip.infolist():
                data = source_zip.read(info.filename)
                if info.filename == config_name:
                    text = data.decode("utf-8")
                    text = set_integer_assignment(text, "MAX_OPEN_POSITIONS", {3, 7}, MAX_OPEN_POSITIONS)
                    text = set_integer_assignment(text, "MAX_NEW_ENTRIES_PER_RUN", {1, 4}, MAX_NEW_ENTRIES_PER_RUN)
                    text = text.replace(
                        "With MAX_OPEN_POSITIONS=3 and RISK_PER_POSITION_PCT=6.5",
                        "With MAX_OPEN_POSITIONS=7 and RISK_PER_POSITION_PCT=6.5",
                    )
                    text = text.replace("19.5% of equity", "45.5% of equity")
                    old_notional_comment = (
                        "# Aggregate notional ceiling. With 3 positions this permits up to 3x equity\n"
                        "# notional per slot, matching STRATEGY_MAX_NOTIONAL_X=3.0. This was raised\n"
                        "# from the prior 1.0x default because 1.0x aggregate would cap each of 3 slots\n"
                        "# at only 0.333x equity and make a 6.5% stop-risk target unattainable for most\n"
                        "# normal stop distances."
                    )
                    new_notional_comment = (
                        "# Aggregate notional ceiling, intentionally kept at 9x total equity.\n"
                        "# With 7 slots, the evenly shared average cap is 9/7 = 1.2857x equity per slot.\n"
                        "# This keeps total portfolio notional unchanged while allowing more positions;\n"
                        "# it can constrain realized stop-risk below the 6.5% per-position budget."
                    )
                    text = text.replace(old_notional_comment, new_notional_comment)
                    compile(text, config_name, "exec")
                    patched_config = text.encode("utf-8")
                    data = patched_config

                elif info.filename == tests_name:
                    text = data.decode("utf-8")
                    replacements = [
                        ('self.assertEqual(settings["max_open_positions"], 3)',
                         'self.assertEqual(settings["max_open_positions"], 7)'),
                        ('self.assertEqual(settings["max_new_entries_per_run"], 1)',
                         'self.assertEqual(settings["max_new_entries_per_run"], 4)'),
                        ('self.assertEqual(settings["portfolio_risk_pct"], 19.5)',
                         'self.assertEqual(settings["portfolio_risk_pct"], 45.5)'),
                        ('def test_requested_risk_is_6_5_percent_per_position_with_three_slots(self):',
                         'def test_requested_risk_is_6_5_percent_per_position_with_seven_slots(self):'),
                        ('self.assertAlmostEqual(per_position_notional, 3.0)',
                         'self.assertAlmostEqual(per_position_notional, 9.0 / 7.0)'),
                        ('self.assertAlmostEqual(per_trade_risk * settings["max_open_positions"], 19.5)',
                         'self.assertAlmostEqual(per_trade_risk * settings["max_open_positions"], 45.5)'),
                        ('def test_default_notional_cap_allows_three_times_equity_per_slot(self):',
                         'def test_default_notional_cap_is_shared_across_seven_slots(self):'),
                        ('self.assertAlmostEqual(per_slot, 3.0)',
                         'self.assertAlmostEqual(per_slot, 9.0 / 7.0)'),
                    ]
                    for old, new in replacements:
                        text = replace_test_assertion(text, old, new)
                    compile(text, tests_name, "exec")
                    patched_tests = text.encode("utf-8")
                    data = patched_tests

                elif info.filename == universe_name:
                    data = patch_universe(data.decode("utf-8")).encode("utf-8")

                elif info.filename == bitget_name:
                    data = patch_bitget_demo(data.decode("utf-8")).encode("utf-8")

                elif info.filename == runner_name:
                    data = patch_runner(data.decode("utf-8")).encode("utf-8")

                elif info.filename == universe_test_name:
                    compile(UNIVERSE_TESTS, "tests/test_universe.py", "exec")
                    data = UNIVERSE_TESTS.encode("utf-8")

                elif info.filename == bitget_test_name:
                    data = patch_bitget_tests(data.decode("utf-8")).encode("utf-8")

                target_zip.writestr(info, data)

    if patched_config is None or patched_tests is None:
        raise RuntimeError("The bundle was not fully patched.")

    zip_bytes = rebuilt_zip.getvalue()
    # Verify the rebuilt ZIP before encrypting it.
    with zipfile.ZipFile(BytesIO(zip_bytes), "r") as check_zip:
        if check_zip.testzip() is not None:
            raise RuntimeError("Rebuilt runtime ZIP failed integrity validation.")

    encrypted = encrypt_bundle(zip_bytes, passphrase)
    # Round-trip verification catches wrong format/AAD/passphrase/nonce issues.
    verified_plain = decrypt_bundle(encrypted, passphrase)
    if verified_plain != zip_bytes:
        raise RuntimeError("Encrypted runtime round-trip validation failed.")

    runtime_root = Path(args.runtime_output).resolve()
    if runtime_root.exists():
        shutil.rmtree(runtime_root)
    runtime_root.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(BytesIO(verified_plain), "r") as archive:
        for info in archive.infolist():
            target = safe_runtime_path(runtime_root, info.filename)
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(archive.read(info.filename))

    config_path = runtime_root / Path(*PurePosixPath(config_name).parts)
    spec = importlib.util.spec_from_file_location("PORTFOLIO_RISK_SETTINGS", config_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load the updated portfolio settings module.")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    settings = module.get_portfolio_risk_settings()
    expected = {
        "max_open_positions": 7,
        "max_new_entries_per_run": 4,
        "portfolio_risk_pct": 45.5,
        "portfolio_max_notional_x": 9.0,
    }
    for key, value in expected.items():
        if settings.get(key) != value:
            raise RuntimeError(f"Updated portfolio setting failed validation: {key}")

    temp_payload = input_path.with_suffix(input_path.suffix + ".tmp")
    temp_payload.write_bytes(encrypted)
    os.replace(temp_payload, input_path)
    digest = hashlib.sha256(encrypted).hexdigest()
    checksum_path.write_text(f"{digest}  bot_payload.bin\n", encoding="utf-8")

    print("[PASS] Encrypted runtime rebuilt and round-trip verified.")
    print("[PASS] Top-100 universe now selects active Bitget USDT-M perpetuals by 24h quote volume when SIGNAL_DATA_SOURCE=bitget_linear.")
    print("[PASS] Portfolio limits: 7 concurrent positions; 4 new entries per analysis run.")
    print("[INFO] Portfolio risk ceiling derived from existing 6.5% per-position setting: 45.5% equity.")
    print("[INFO] Aggregate notional ceiling remains 9.0x equity (shared average 1.2857x per slot).")
    print("[PASS] Updated offline tests included; runtime extracted only to temporary runner storage.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SyntaxError as exc:
        # Report only syntax location/message; never print source snippets from the decrypted payload.
        print(f"[FAIL] Runtime source syntax validation failed: line={exc.lineno}, column={exc.offset}, message={exc.msg}.")
        raise SystemExit(1)
    except Exception as exc:
        # Deliberately omit exception contents to avoid exposing any decrypted data.
        print(f"[FAIL] Encrypted runtime rebuild aborted ({type(exc).__name__}).")
        raise SystemExit(1)
