#!/usr/bin/env python3
"""Learning: first surf records landmarks; second surf reuses via learn_use."""

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
    td = tempfile.mkdtemp(prefix="mafia-learn-")
    os.environ["MAFIA_LEARN_DIR"] = str(Path(td) / "learn")
    os.environ["MAFIA_SESSIONS_DIR"] = str(Path(td) / "sessions")
    os.environ["MAFIA_PROFILES_DIR"] = str(Path(td) / "profiles")
    os.environ["MAFIA_LEDGER_DIR"] = str(Path(td) / "ledger")

    fails: list[str] = []
    fixture = (ROOT / "cases/fixtures/js-render.html").resolve().as_uri()

    # ---- first visit: explore, learn from find + click ----
    b = MafiaBrowser(headed=False, channel="chrome")
    try:
        s = call(b, {"op": "session_open", "label": "learn-smoke"})
        sid = s["session"]
        call(b, {"op": "navigate", "url": fixture, "session": sid})
        call(b, {"op": "settle", "session": sid})

        found = call(b, {"op": "find_text", "text": "GROW", "session": sid})
        matches = found.get("matches") or []
        if not matches:
            fails.append(f"first find GROW: {found}")
        else:
            click = call(
                b,
                {
                    "op": "click",
                    "node_id": matches[0]["node_id"],
                    "session": sid,
                },
            )
            if not click.get("ok"):
                fails.append(f"first click: {click}")
            read = call(b, {"op": "read", "session": sid})
            if "CLICK-HANDLER-RAN" not in (read.get("text") or ""):
                fails.append("first click handler did not run")

        call(
            b,
            {
                "op": "learn_note",
                "session": sid,
                "note": "Click GROW to prove SPA handler; look for CLICK-HANDLER-RAN",
            },
        )

        rec = call(b, {"op": "learn_recall", "session": sid})
        if not rec.get("landmarks"):
            fails.append(f"no landmarks after first surf: {rec}")
        if not rec.get("recipes"):
            fails.append(f"no recipes after find→click: {rec}")
        if not rec.get("notes"):
            fails.append(f"no notes: {rec}")

        listed = call(b, {"op": "learn_list"})
        if listed.get("count", 0) < 1:
            fails.append(f"learn_list empty: {listed}")

    finally:
        b.stop()

    # ---- second visit (new browser): suggest + learn_use should be easy ----
    b2 = MafiaBrowser(headed=False, channel="chrome")
    try:
        s = call(b2, {"op": "session_open"})
        sid = s["session"]
        call(b2, {"op": "navigate", "url": fixture, "session": sid})
        call(b2, {"op": "settle", "session": sid})

        sug = call(b2, {"op": "learn_suggest", "session": sid})
        if not sug.get("suggestions"):
            fails.append(f"no suggestions on second visit: {sug}")

        # Easier path: learn_use known landmark without manual find/node_id
        use = call(b2, {"op": "learn_use", "text": "GROW", "session": sid})
        if not use.get("ok"):
            fails.append(f"learn_use GROW: {use}")
        if not use.get("clicked"):
            fails.append(f"learn_use did not click: {use}")

        read = call(b2, {"op": "read", "session": sid})
        if "CLICK-HANDLER-RAN" not in (read.get("text") or ""):
            fails.append(f"second visit handler missing: {(read.get('text') or '')[:200]}")

        # recipe path
        rec = call(b2, {"op": "learn_recall", "session": sid})
        recipes = rec.get("recipes") or []
        if recipes:
            # re-nav clean page for recipe re-run
            call(b2, {"op": "navigate", "url": fixture, "session": sid})
            call(b2, {"op": "settle", "session": sid})
            rname = recipes[0].get("name")
            rr = call(b2, {"op": "learn_recipe", "name": rname, "session": sid})
            if not rr.get("ok"):
                fails.append(f"learn_recipe: {rr}")
            read2 = call(b2, {"op": "read", "session": sid})
            if "CLICK-HANDLER-RAN" not in (read2.get("text") or ""):
                fails.append("recipe did not trigger handler")

    finally:
        b2.stop()

    if fails:
        print("FAIL")
        for f in fails:
            print(" -", f)
        return 1
    print("PASS: site learning — first surf teaches, second learn_use is easy")
    print(f"  (disk: {td})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
