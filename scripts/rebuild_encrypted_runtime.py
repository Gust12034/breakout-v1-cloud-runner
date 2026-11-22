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
        if len(config_candidates) != 1 or len(test_candidates) != 1:
            raise RuntimeError("Required portfolio settings/test files were not found uniquely in the payload.")
        config_name = config_candidates[0]
        tests_name = test_candidates[0]

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
    print("[PASS] Portfolio limits: 7 concurrent positions; 4 new entries per analysis run.")
    print("[INFO] Portfolio risk ceiling derived from existing 6.5% per-position setting: 45.5% equity.")
    print("[INFO] Aggregate notional ceiling remains 9.0x equity (shared average 1.2857x per slot).")
    print("[PASS] Updated offline test expectations included; runtime extracted only to temporary runner storage.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        # Deliberately omit exception contents to avoid exposing any decrypted data.
        print(f"[FAIL] Encrypted runtime rebuild aborted ({type(exc).__name__}).")
        raise SystemExit(1)
