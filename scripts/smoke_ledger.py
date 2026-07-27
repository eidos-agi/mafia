#!/usr/bin/env python3
"""Usage ledger + reboot: every op tracked; agent can resume prior work."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from mafia.api import dispatch
from mafia.browser import MafiaBrowser


def call(b: MafiaBrowser, op: dict) -> dict:
    resp, _ = dispatch(b, json.dumps(op))
    return resp


def main() -> int:
    td = tempfile.mkdtemp(prefix="mafia-ledger-")
    os.environ["MAFIA_SESSIONS_DIR"] = str(Path(td) / "sessions")
    os.environ["MAFIA_PROFILES_DIR"] = str(Path(td) / "profiles")
    os.environ["MAFIA_LEDGER_DIR"] = str(Path(td) / "ledger")

    fails: list[str] = []
    marker = f"ledger-{os.getpid()}"

    b = MafiaBrowser(headed=False, channel="chrome")
    try:
        s = call(
            b,
            {
                "op": "session_open",
                "label": "smoke-work",
            },
        )
        if not s.get("ok"):
            fails.append(f"open: {s}")
            print("FAIL early", fails)
            return 1
        sid = s["session"]
        if s.get("label") != "smoke-work":
            fails.append(f"label missing on open: {s}")

        call(b, {"op": "navigate", "url": "https://example.com", "session": sid})
        call(
            b,
            {
                "op": "eval",
                "session": sid,
                "js": (
                    f"document.cookie='mafia_ledger={marker}; path=/';"
                    f"localStorage.setItem('mafia_ledger','{marker}');true"
                ),
            },
        )
        call(b, {"op": "find_text", "text": "Example", "session": sid})
        call(b, {"op": "session_close", "session": sid})
    finally:
        b.stop()

    # New process — history + recent + reboot
    b2 = MafiaBrowser(headed=False, channel="chrome")
    try:
        hist = call(b2, {"op": "session_history", "work": "smoke-work", "limit": 100})
        if not hist.get("ok"):
            fails.append(f"history: {hist}")
        else:
            ops = [e.get("op") for e in (hist.get("events") or [])]
            for need in ("session_open", "navigate", "session_close"):
                if need not in ops:
                    fails.append(f"history missing {need}: {ops}")

        recent = call(b2, {"op": "session_recent", "limit": 10})
        if not recent.get("ok"):
            fails.append(f"recent: {recent}")
        else:
            keys = [w.get("key") for w in (recent.get("work") or [])]
            if "smoke-work" not in keys:
                fails.append(f"recent missing smoke-work: {recent}")

        # reboot most recent (should be smoke-work)
        rb = call(b2, {"op": "session_reboot"})
        if not rb.get("ok"):
            fails.append(f"reboot: {rb}")
        else:
            if "example.com" not in str(rb.get("url") or ""):
                fails.append(f"reboot url: {rb}")
            sid2 = rb["session"]
            cookie = call(
                b2, {"op": "eval", "session": sid2, "js": "document.cookie"}
            )
            ls = call(
                b2,
                {
                    "op": "eval",
                    "session": sid2,
                    "js": "localStorage.getItem('mafia_ledger')",
                },
            )
            if marker not in str(cookie.get("result") or ""):
                fails.append(f"reboot cookie: {cookie}")
            if ls.get("result") != marker:
                fails.append(f"reboot localStorage: {ls}")

        # named reboot
        call(b2, {"op": "session_close", "session": rb.get("session")})
        rb2 = call(b2, {"op": "session_reboot", "name": "smoke-work"})
        if not rb2.get("ok"):
            fails.append(f"named reboot: {rb2}")

        # secrets never land in ledger
        ledger_events = Path(td) / "ledger" / "events.jsonl"
        if ledger_events.is_file():
            blob = ledger_events.read_text(encoding="utf-8")
            if "mafia_ledger=" in blob and "document.cookie" in blob:
                # js is suppressed as [suppressed] — cookie string must not appear raw
                if f"mafia_ledger={marker}" in blob:
                    fails.append("secret-ish cookie value leaked into ledger")
            if '"text":' in blob and "password" in blob.lower():
                fails.append("unexpected secret field shape in ledger")

    finally:
        b2.stop()

    if fails:
        print("FAIL")
        for f in fails:
            print(" -", f)
        return 1
    print("PASS: ledger tracks use; session_reboot restores prior work")
    print(f"  (disk: {td})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
