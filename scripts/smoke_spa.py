#!/usr/bin/env python3
"""SPA smoke: post-JS DOM + click handler + multi-session isolation."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from mafia.api import dispatch
from mafia.browser import MafiaBrowser


def call(b, op: dict) -> dict:
    resp, _ = dispatch(b, json.dumps(op))
    return resp


def main() -> int:
    fixture = (ROOT / "cases/fixtures/js-render.html").resolve().as_uri()
    b = MafiaBrowser(headed=False, channel="chrome")
    fails: list[str] = []

    try:
        s1 = call(b, {"op": "session_open"})
        assert s1.get("ok"), s1
        sid1 = s1["session"]

        nav = call(b, {"op": "navigate", "url": fixture, "session": sid1})
        assert nav.get("ok"), nav
        call(b, {"op": "settle", "session": sid1})

        title = call(b, {"op": "eval", "js": "document.title", "session": sid1})
        if title.get("result") != "post-js title":
            fails.append(f"title want post-js title got {title}")

        found = call(b, {"op": "find_text", "text": "POST-JS-MARKER", "session": sid1})
        matches = found.get("matches") or []
        if not matches:
            fails.append(f"no POST-JS-MARKER: {found}")

        snap = call(b, {"op": "snapshot", "session": sid1})
        if snap.get("node_count", 0) < 1:
            fails.append(f"empty snapshot: {snap}")

        # click GROW
        grow = call(b, {"op": "find_text", "text": "GROW", "session": sid1})
        gm = grow.get("matches") or []
        if not gm:
            fails.append("no GROW button")
        else:
            click = call(b, {"op": "click", "node_id": gm[0]["node_id"], "session": sid1})
            if not click.get("ok"):
                fails.append(f"click failed: {click}")
            read = call(b, {"op": "read", "session": sid1})
            if "CLICK-HANDLER-RAN" not in (read.get("text") or ""):
                fails.append(f"click handler not visible: {read.get('text', '')[:200]}")

        # multi-session isolation
        s2 = call(b, {"op": "session_open"})
        sid2 = s2["session"]
        call(b, {"op": "navigate", "url": "https://example.com", "session": sid2})
        r1 = call(b, {"op": "eval", "js": "location.href", "session": sid1})
        r2 = call(b, {"op": "eval", "js": "location.href", "session": sid2})
        if "js-render" not in str(r1.get("result", "")):
            fails.append(f"session1 lost fixture: {r1}")
        if "example.com" not in str(r2.get("result", "")):
            fails.append(f"session2 not example: {r2}")

        st = call(b, {"op": "status"})
        if st.get("session_count", 0) < 2:
            fails.append(f"want >=2 sessions: {st}")

    finally:
        b.stop()

    if fails:
        print("FAIL")
        for f in fails:
            print(" -", f)
        return 1
    print("PASS: SPA post-JS + click + multi-session isolation")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
