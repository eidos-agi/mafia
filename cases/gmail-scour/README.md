# Gmail scour on Mafia

Acceptance for **real Chromium** (not Chrime StaticEngine). Six unrelated themes.

Spec lineage: chrime `cases/gmail-scour` / EID-1059 → Mafia **EID-1070**.

## Run

```sh
cd ~/repos-eidos-agi/mafia
source .venv/bin/activate

# First time — headed window; complete Google login / 2FA
python3 scripts/run_gmail_scour.py --headed --profile gmail-work

# Later — profile jar should skip re-login
python3 scripts/run_gmail_scour.py --headed --profile gmail-work --skip-login-prompt
```

Or server + client:

```sh
python3 -m mafia serve --headed --port 7430
python3 scripts/run_gmail_scour.py --port 7430 --profile gmail-work
```

Report: `logs/gmail-scour-report.json` (includes **timing** phases for Chrime comparison).

## Pass bar

- Auth: inbox visible (not login wall)
- Hits: default **≥5 of 6** themes (`--min-hits 6` for full bar)
- Engine of record: Mafia Chromium `read` / `snapshot` after `navigate` + `settle`
- Zero coordinate/pixel ops
