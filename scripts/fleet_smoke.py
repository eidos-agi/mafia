#!/usr/bin/env python3
"""Fleet smoke: N isolated sessions, distinct URLs, snapshots, no cookie leak."""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from mafia.api import dispatch
from mafia.browser import MafiaBrowser

URLS = [
    "https://example.com",
    "https://example.org",
    "https://www.iana.org/domains/reserved",
    "https://httpbin.org/html",
    "https://httpbin.org/links/5/0",
]


def call(b: MafiaBrowser, op: dict) -> dict:
    resp, _ = dispatch(b, json.dumps(op))
    return resp


def main() -> int:
    n = int(os.environ.get("MAFIA_FLEET_N", "10"))
    td = Path(os.environ.get("TMPDIR", "/tmp")) / f"mafia-fleet-{os.getpid()}"
    os.environ["MAFIA_SESSIONS_DIR"] = str(td / "sessions")
    os.environ["MAFIA_PROFILES_DIR"] = str(td / "profiles")
    os.environ["MAFIA_LEDGER_DIR"] = str(td / "ledger")

    b = MafiaBrowser(headed=False, channel="chrome", max_sessions=max(n + 5, 20))
    fails: list[str] = []
    sids: list[str] = []
    t0 = time.time()

    try:
        for i in range(n):
            url = URLS[i % len(URLS)]
            # unique path marker via query so cookies can be origin-scoped differently
            marker = f"fleet{i}"
            s = call(b, {"op": "session_open", "id": f"fleet-{i}", "label": f"fleet-{i}"})
            if not s.get("ok"):
                fails.append(f"open {i}: {s}")
                continue
            sid = s["session"]
            sids.append(sid)
            nav = call(b, {"op": "navigate", "url": url, "session": sid})
            if not nav.get("ok"):
                fails.append(f"nav {i}: {nav}")
            # set unique cookie per session on that origin
            call(
                b,
                {
                    "op": "eval",
                    "session": sid,
                    "js": f"document.cookie='fleet={marker}; path=/'; '{marker}'",
                },
            )
            snap = call(b, {"op": "snapshot", "session": sid})
            if (snap.get("node_count") or 0) < 1 and not snap.get("nodes"):
                # some pages may be sparse; require ok/url at least
                if not snap.get("url"):
                    fails.append(f"snapshot {i}: {snap}")

        # cookie isolation: each session only sees its own fleet cookie value
        for i, sid in enumerate(sids):
            marker = f"fleet{i}"
            ck = call(b, {"op": "eval", "session": sid, "js": "document.cookie"})
            val = str(ck.get("result") or "")
            if marker not in val:
                fails.append(f"cookie missing session {i}: {ck}")
            # other markers should not appear if same-origin shared — example.com
            # only check cross-session pollution for same URL base
            for j, other in enumerate(sids):
                if i == j:
                    continue
                if URLS[i % len(URLS)] != URLS[j % len(URLS)]:
                    continue
                other_m = f"fleet{j}"
                if other_m in val and other_m != marker:
                    fails.append(f"cookie leak: session {i} has {other_m}: {val}")

        # close one session without killing others
        if sids:
            victim = sids[0]
            call(b, {"op": "session_close", "session": victim})
            st = call(b, {"op": "status"})
            if victim in (st.get("sessions") or []):
                fails.append(f"session still listed after close: {st}")
            if len(sids) > 1:
                alive = sids[1]
                ev = call(b, {"op": "eval", "session": alive, "js": "1+1"})
                if ev.get("result") != 2:
                    fails.append(f"pool dead after close one: {ev}")

        elapsed = time.time() - t0
        # soft RSS if available
        rss = None
        try:
            import resource

            rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        except Exception:
            pass

    finally:
        b.stop()

    if fails:
        print("FAIL")
        for f in fails:
            print(" -", f)
        return 1
    print(f"PASS: fleet N={n} isolated sessions + snapshots + no cookie leak")
    print(f"  elapsed={elapsed:.1f}s  max_rss={rss}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
