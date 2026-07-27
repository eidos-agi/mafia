#!/usr/bin/env python3
"""Open headed Chromium with the Mafia browser chrome theme.

Shows the noir/gold tab strip + Mafia new-tab page, then a demo fixture.
Hold open until Ctrl-C or timeout (default 30s).
"""

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


def call(b: MafiaBrowser, op: dict) -> dict:
    resp, _ = dispatch(b, json.dumps(op))
    return resp


def main() -> int:
    hold = int(os.environ.get("MAFIA_SKIN_HOLD", "30"))
    # bundled chromium so the theme pack applies
    b = MafiaBrowser(headed=True, channel=None)
    try:
        s = call(b, {"op": "session_open", "label": "skin-demo"})
        sid = s["session"]
        print("♠ MAFIA browser skin")
        print(f"  skin={b.skin}  persistent={b._persistent is not None}")
        print(f"  ntp={b.ntp_url}")

        if b.ntp_url:
            r = call(b, {"op": "navigate", "url": b.ntp_url, "session": sid})
            print(f"  new tab page: ok={r.get('ok')} title={r.get('title')!r}")
            time.sleep(3)

        fixture = (ROOT / "cases/fixtures/login-wall.html").resolve().as_uri()
        r = call(b, {"op": "navigate", "url": fixture, "session": sid})
        print(f"  fixture: {r.get('title')}")
        print()
        print("Look at the Chromium window:")
        print("  • tab strip / toolbar tint (noir + gold)")
        print("  • Mafia NTP if extension id resolved")
        print(f"  Holding {hold}s (MAFIA_SKIN_HOLD)…")
        time.sleep(hold)
    finally:
        try:
            call(b, {"op": "quit"})
        except Exception:
            b.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
