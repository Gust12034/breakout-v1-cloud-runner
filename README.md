# Breakout V1 Dynamic — encrypted cloud runner

This public repository contains deployment workflows, a decryptor, the Google Apps Script dispatcher, and an encrypted runtime payload. Trading source code is not stored in plaintext.

**Before any workflow can run, upload `private_bundle/bot_payload.bin` from the supplied deployment ZIP.** Do not upload `BOT_BUNDLE_PASSPHRASE.txt`, exchange credentials, GitHub PATs, or Google tokens.

Read `DEPLOYMENT_FA.md` for the full Persian setup procedure. The bot is locked to Bitget Classic Futures Demo and `LIVE_TRADING=false`; `TRADING_ENABLED` must remain `false` until read-only validation and a controlled Demo test pass.
