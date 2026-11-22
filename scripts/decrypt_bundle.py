#!/usr/bin/env python3
"""Decrypt the private Breakout V1 runtime bundle in GitHub Actions.

The passphrase must be provided only through BOT_BUNDLE_PASSPHRASE.
Decrypted source is written to the ephemeral runner temp directory, not the repo.
"""
from __future__ import annotations
import argparse
import os
from pathlib import Path, PurePosixPath
import zipfile
from io import BytesIO

MAGIC = b"B1DYNENC1"
AAD = b"Breakout-V1-Demo-Encrypted-Bundle-v1"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    phrase = os.environ.get("BOT_BUNDLE_PASSPHRASE", "")
    if len(phrase) < 32:
        raise SystemExit("BOT_BUNDLE_PASSPHRASE is missing or too short")
    raw = Path(args.input).read_bytes()
    if len(raw) < len(MAGIC) + 16 + 12 + 16 or raw[:len(MAGIC)] != MAGIC:
        raise SystemExit("Encrypted bundle format is invalid")
    salt_start = len(MAGIC)
    salt = raw[salt_start:salt_start+16]
    nonce = raw[salt_start+16:salt_start+28]
    ciphertext = raw[salt_start+28:]
    try:
        from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=600_000)
        key = kdf.derive(phrase.encode("utf-8"))
        plain = AESGCM(key).decrypt(nonce, ciphertext, AAD)
    except Exception:
        raise SystemExit("Bundle decryption failed: check BOT_BUNDLE_PASSPHRASE and the encrypted file")
    out = Path(args.output).resolve()
    out.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(BytesIO(plain), "r") as archive:
        for info in archive.infolist():
            rel = PurePosixPath(info.filename)
            if rel.is_absolute() or ".." in rel.parts or not rel.parts:
                raise SystemExit("Bundle contains an unsafe path")
            target = (out / Path(*rel.parts)).resolve()
            if out not in target.parents and target != out:
                raise SystemExit("Bundle path escaped the runtime directory")
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(archive.read(info))
    print("Encrypted runtime bundle decrypted successfully.")
    return 0

if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
