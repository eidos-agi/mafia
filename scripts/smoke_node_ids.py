#!/usr/bin/env python3
"""Node-id space must be shared: find_text → click hits the intended control.

Regression for hidden-input id drift (find_text vs walker).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from mafia.api import dispatch
from mafia.browser import MafiaBrowser


def call(b: MafiaBrowser, op: dict) -> dict:
    resp, _ = dispatch(b, json.dumps(op))
    return resp


def main() -> int:
    fixture = (ROOT / "cases/fixtures/login-wall.html").resolve().as_uri()
    b = MafiaBrowser(headed=False, channel="chrome")
    fails: list[str] = []

    try:
        s = call(b, {"op": "session_open"})
        sid = s["session"]
        call(b, {"op": "navigate", "url": fixture, "session": sid})
        call(b, {"op": "settle", "session": sid})

        found = call(b, {"op": "find_text", "text": "Log in", "session": sid})
        matches = found.get("matches") or []
        if not matches:
            fails.append(f"no Log in match: {found}")
        else:
            nid = matches[0]["node_id"]
            snap = call(b, {"op": "snapshot", "session": sid})
            nodes = {n["node_id"]: n for n in (snap.get("nodes") or [])}
            if nid not in nodes:
                fails.append(f"find_text node_id {nid} missing from snapshot: {list(nodes)}")
            elif "log in" not in (nodes[nid].get("text") or "").lower():
                fails.append(
                    f"snapshot node {nid} is not Log in: {nodes[nid]}"
                )

            click = call(b, {"op": "click", "node_id": nid, "session": sid})
            if not click.get("ok"):
                fails.append(f"click failed: {click}")
            text = (click.get("text") or "").lower()
            if "log in" not in text and "login" not in text:
                fails.append(f"click text not Log in: {click}")

            read = call(b, {"op": "read", "session": sid})
            body = read.get("text") or ""
            if "LOGIN-CLICKED" not in body:
                fails.append(f"expected LOGIN-CLICKED, got: {body[:300]}")
            if "DELETE-CLICKED" in body:
                fails.append("wrong control: Delete was clicked")

        # learn_use path too
        call(b, {"op": "navigate", "url": fixture, "session": sid})
        use = call(b, {"op": "learn_use", "text": "Log in", "session": sid})
        if not use.get("ok") or not use.get("clicked"):
            fails.append(f"learn_use: {use}")
        read2 = call(b, {"op": "read", "session": sid})
        if "LOGIN-CLICKED" not in (read2.get("text") or ""):
            fails.append(f"learn_use wrong target: {read2.get('text', '')[:200]}")

        # unknown session must not silent-open
        bad = call(b, {"op": "navigate", "url": fixture, "session": "no-such-session"})
        if bad.get("ok") or bad.get("code") != "unknown_session":
            fails.append(f"expected unknown_session, got: {bad}")

    finally:
        b.stop()

    if fails:
        print("FAIL")
        for f in fails:
            print(" -", f)
        return 1
    print("PASS: node-id space unified; Log in click correct with hidden inputs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
