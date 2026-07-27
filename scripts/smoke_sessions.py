#!/usr/bin/env python3
"""Session durability: save/load + named profile survive close/restart."""

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
    # Isolate disk so CI/local don't pollute default jars
    td = tempfile.mkdtemp(prefix="mafia-sess-")
    os.environ["MAFIA_SESSIONS_DIR"] = str(Path(td) / "sessions")
    os.environ["MAFIA_PROFILES_DIR"] = str(Path(td) / "profiles")

    fails: list[str] = []
    marker = f"mafia-smoke-{os.getpid()}"

    # ---- M2.2 save / load ----
    b = MafiaBrowser(headed=False, channel="chrome")
    try:
        s = call(b, {"op": "session_open"})
        assert s.get("ok"), s
        sid = s["session"]

        nav = call(b, {"op": "navigate", "url": "https://example.com", "session": sid})
        if not nav.get("ok"):
            fails.append(f"navigate: {nav}")
        else:
            # cookie + localStorage into real browser storage
            set_state = call(
                b,
                {
                    "op": "eval",
                    "session": sid,
                    "js": (
                        f"document.cookie='mafia_marker={marker}; path=/';"
                        f"localStorage.setItem('mafia_marker','{marker}');"
                        "true"
                    ),
                },
            )
            if not set_state.get("ok"):
                fails.append(f"set state: {set_state}")

            save = call(b, {"op": "session_save", "name": "smoke-save", "session": sid})
            if not save.get("ok"):
                fails.append(f"session_save: {save}")

            close = call(b, {"op": "session_close", "session": sid})
            if not close.get("ok"):
                fails.append(f"session_close: {close}")

            if sid in b.sessions:
                fails.append("session still live after close")

            load = call(b, {"op": "session_load", "name": "smoke-save"})
            if not load.get("ok"):
                fails.append(f"session_load: {load}")
            else:
                sid2 = load["session"]
                if "example.com" not in str(load.get("url") or ""):
                    fails.append(f"load url not restored: {load}")

                cookie = call(
                    b,
                    {
                        "op": "eval",
                        "session": sid2,
                        "js": "document.cookie",
                    },
                )
                ls = call(
                    b,
                    {
                        "op": "eval",
                        "session": sid2,
                        "js": "localStorage.getItem('mafia_marker')",
                    },
                )
                if marker not in str(cookie.get("result") or ""):
                    fails.append(f"cookie not restored: {cookie}")
                if ls.get("result") != marker:
                    fails.append(f"localStorage not restored: {ls}")

            listed = call(b, {"op": "session_saves"})
            names = [x.get("name") for x in (listed.get("saves") or [])]
            if "smoke-save" not in names:
                fails.append(f"session_saves missing smoke-save: {listed}")

    finally:
        b.stop()

    # ---- M2.1 profile jar survives full process restart (new browser) ----
    b1 = MafiaBrowser(headed=False, channel="chrome")
    try:
        s = call(b1, {"op": "session_open", "profile": "smoke-prof"})
        if not s.get("ok"):
            fails.append(f"profile open: {s}")
        else:
            sid = s["session"]
            call(b1, {"op": "navigate", "url": "https://example.com", "session": sid})
            call(
                b1,
                {
                    "op": "eval",
                    "session": sid,
                    "js": (
                        f"document.cookie='mafia_prof={marker}; path=/';"
                        f"localStorage.setItem('mafia_prof','{marker}');true"
                    ),
                },
            )
            # close persists profile automatically
            call(b1, {"op": "session_close", "session": sid})
    finally:
        b1.stop()

    b2 = MafiaBrowser(headed=False, channel="chrome")
    try:
        s = call(b2, {"op": "session_open", "profile": "smoke-prof"})
        if not s.get("ok"):
            fails.append(f"profile reopen: {s}")
        else:
            sid = s["session"]
            if "example.com" not in str(s.get("url") or ""):
                # open_session restores url from meta — surface in response
                st = call(b2, {"op": "status", "session": sid})
                if "example.com" not in str(st.get("url") or ""):
                    fails.append(f"profile url not restored: open={s} status={st}")

            cookie = call(
                b2,
                {"op": "eval", "session": sid, "js": "document.cookie"},
            )
            ls = call(
                b2,
                {
                    "op": "eval",
                    "session": sid,
                    "js": "localStorage.getItem('mafia_prof')",
                },
            )
            if marker not in str(cookie.get("result") or ""):
                fails.append(f"profile cookie lost after restart: {cookie}")
            if ls.get("result") != marker:
                fails.append(f"profile localStorage lost after restart: {ls}")

        profs = call(b2, {"op": "session_profiles"})
        pnames = [x.get("name") for x in (profs.get("profiles") or [])]
        if "smoke-prof" not in pnames:
            fails.append(f"session_profiles missing smoke-prof: {profs}")

    finally:
        b2.stop()

    if fails:
        print("FAIL")
        for f in fails:
            print(" -", f)
        return 1
    print("PASS: session save/load + profile survives restart")
    print(f"  (disk: {td})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
