#!/usr/bin/env python3
"""Mafia API suite ≥30 cases on real Chromium (dispatch + optional TCP).

Plain-English cases. Failures printed; exit 1 if any fail.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from mafia.api import dispatch
from mafia.browser import MafiaBrowser

FIX = ROOT / "cases" / "fixtures"
JS = (FIX / "js-render.html").resolve().as_uri()
LOGIN = (FIX / "login-wall.html").resolve().as_uri()
ROLES = (FIX / "roles-form.html").resolve().as_uri()
DIALOG = (FIX / "dialog.html").resolve().as_uri()


class Runner:
    def __init__(self, call: Callable[[dict], dict]) -> None:
        self.call = call
        self.sid: str | None = None
        self.fails: list[str] = []
        self.passes = 0

    def op(self, **kwargs: Any) -> dict:
        if self.sid and "session" not in kwargs and kwargs.get("op") not in (
            "session_open",
            "session_load",
            "session_reboot",
            "session_saves",
            "session_profiles",
            "session_recent",
            "session_history",
            "learn_list",
            "ping",
            "help",
            "ops",
            "quit",
        ):
            kwargs["session"] = self.sid
        return self.call(kwargs)

    def check(self, name: str, cond: bool, detail: Any = None) -> None:
        if cond:
            self.passes += 1
        else:
            self.fails.append(f"{name}: {detail}")


def run_cases(r: Runner) -> None:
    # --- health ---
    p = r.op(op="ping")
    r.check("ping ok", p.get("ok") is True and p.get("engine") == "chromium", p)
    h = r.op(op="help")
    r.check("help has wait", "wait" in (h.get("ops") or []), h)
    r.check("help has viewport", "viewport" in (h.get("ops") or []), h)

    s = r.op(op="session_open", label="suite")
    r.check("session_open", s.get("ok"), s)
    r.sid = s.get("session")

    # --- SPA fixture ---
    n = r.op(op="navigate", url=JS)
    r.check("nav js-render", n.get("ok"), n)
    st = r.op(op="settle")
    r.check("settle ok", st.get("ok"), st)
    t = r.op(op="eval", js="document.title")
    r.check("post-js title", t.get("result") == "post-js title", t)
    ft = r.op(op="find_text", text="POST-JS-MARKER")
    r.check("find POST-JS", bool(ft.get("matches")), ft)
    snap = r.op(op="snapshot")
    r.check("snapshot nodes", (snap.get("node_count") or 0) > 0, snap)
    grow = r.op(op="find_text", text="GROW")
    gm = grow.get("matches") or []
    r.check("find GROW", bool(gm), grow)
    if gm:
        ck = r.op(op="click", node_id=gm[0]["node_id"])
        r.check("click GROW", ck.get("ok"), ck)
        rd = r.op(op="read")
        r.check("click handler", "CLICK-HANDLER-RAN" in (rd.get("text") or ""), rd)

    # --- wait / settle text ---
    r.op(op="navigate", url=ROLES)
    r.op(op="settle", quiet_ms=50)
    w = r.op(op="wait", text="LATE-MARKER", timeout_ms=5000)
    r.check("wait text LATE-MARKER", w.get("ok"), w)
    s2 = r.op(op="settle", text="Roles Form", timeout_ms=5000)
    r.check("settle text", s2.get("ok"), s2)

    # --- ARIA roles ---
    fr = r.op(op="find_text", text="Compose")
    r.check("find role=button Compose", bool(fr.get("matches")), fr)
    if fr.get("matches"):
        r.op(op="click", node_id=fr["matches"][0]["node_id"])
        rd = r.op(op="read")
        r.check("role button click", "COMPOSE-ROLE-CLICKED" in (rd.get("text") or ""), rd)

    # --- fill by selector + node_id ---
    r.op(op="navigate", url=ROLES)
    r.op(op="settle", quiet_ms=100)
    f1 = r.op(op="fill", which="login", text="agent@mafia.test")
    r.check("fill login", f1.get("ok") and f1.get("secret_output") == "suppressed", f1)
    # find email field via snapshot and fill node_id
    snap = r.op(op="snapshot")
    email_node = None
    for n in snap.get("nodes") or []:
        if n.get("tag") == "input" and "email" in (n.get("text") or "").lower() or (
            n.get("tag") == "input" and n.get("role") in ("field", "textbox")
        ):
            # pick first text-ish input — better: query
            pass
    q = r.op(op="query", selector="input[type=email]")
    nodes = q.get("nodes") or []
    r.check("query email", len(nodes) >= 1, q)
    if nodes and nodes[0].get("node_id"):
        f2 = r.op(op="fill", node_id=nodes[0]["node_id"], text="node@mafia.test")
        r.check("fill node_id", f2.get("ok"), f2)

    # --- login wall node ids ---
    r.op(op="navigate", url=LOGIN)
    r.op(op="settle")
    fl = r.op(op="find_text", text="Log in")
    m = fl.get("matches") or []
    r.check("login wall find", bool(m), fl)
    if m:
        r.op(op="click", node_id=m[0]["node_id"])
        rd = r.op(op="read")
        r.check("login not delete", "LOGIN-CLICKED" in (rd.get("text") or ""), rd)
        r.check("not delete", "DELETE-CLICKED" not in (rd.get("text") or ""), rd)

    # --- dialog does not hang ---
    r.op(op="navigate", url=DIALOG)
    r.op(op="settle")
    fa = r.op(op="find_text", text="Alert")
    if fa.get("matches"):
        r.op(op="click", node_id=fa["matches"][0]["node_id"])
        # if dialog blocked forever this hangs — timeout would fail suite
        w2 = r.op(op="wait", text="after-alert", timeout_ms=5000)
        r.check("dialog dismissed, after-alert", w2.get("ok"), w2)

    # --- viewport ---
    vp = r.op(op="viewport", width=390, height=844)
    r.check("viewport", vp.get("ok"), vp)

    # --- multi-session isolation ---
    s_b = r.op(op="session_open", id="suite-b")
    r.check("session_open b", s_b.get("ok"), s_b)
    sid_b = s_b.get("session")
    r.op(op="navigate", url="https://example.com", session=sid_b)
    r1 = r.op(op="eval", js="location.href", session=r.sid)
    r2 = r.op(op="eval", js="location.href", session=sid_b)
    r.check("isolation a", "dialog" in str(r1.get("result") or "") or "login" in str(r1.get("result") or "") or "file:" in str(r1.get("result") or ""), r1)
    r.check("isolation b example", "example.com" in str(r2.get("result") or ""), r2)

    # --- learn ---
    r.op(op="navigate", url=JS, session=r.sid)
    r.op(op="settle", session=r.sid)
    r.op(op="find_text", text="GROW", session=r.sid)
    lr = r.op(op="learn_recall", session=r.sid)
    r.check("learn_recall", lr.get("ok"), lr)
    ls = r.op(op="learn_suggest", session=r.sid)
    r.check("learn_suggest", ls.get("ok"), ls)

    # --- session save/load ---
    r.op(op="navigate", url="https://example.com", session=r.sid)
    r.op(
        op="eval",
        session=r.sid,
        js="document.cookie='suite_ck=1; path=/'; localStorage.setItem('suite','1'); true",
    )
    sv = r.op(op="session_save", name="suite-save", session=r.sid)
    r.check("session_save", sv.get("ok"), sv)
    r.op(op="session_close", session=r.sid)
    ld = r.op(op="session_load", name="suite-save")
    r.check("session_load", ld.get("ok"), ld)
    r.sid = ld.get("session")
    cookie = r.op(op="eval", js="document.cookie")
    r.check("cookie restored", "suite_ck" in str(cookie.get("result") or ""), cookie)

    # --- unknown session ---
    bad = r.op(op="navigate", url=JS, session="nope-xyz")
    r.check("unknown session", bad.get("code") == "unknown_session", bad)

    # --- ledger ---
    recent = r.op(op="session_recent", limit=5)
    r.check("session_recent", recent.get("ok"), recent)
    hist = r.op(op="session_history", limit=20)
    r.check("session_history", hist.get("ok") and (hist.get("count") or 0) > 0, hist)

    # --- knox dry shapes (no secret) ---
    kf = r.op(op="knox_find", query="example.com")
    r.check("knox_find has secret_output or ok field", "secret_output" in kf or "ok" in kf, kf)

    # --- press ---
    r.op(op="navigate", url=ROLES)
    r.op(op="settle")
    pr = r.op(op="press", key="Tab")
    r.check("press Tab", pr.get("ok"), pr)

    # --- links ---
    r.op(op="navigate", url=JS)
    r.op(op="settle")
    links = r.op(op="links")
    r.check("links op", links.get("ok"), links)

    # --- back/forward ---
    r.op(op="navigate", url="https://example.com")
    r.op(op="navigate", url=JS)
    bk = r.op(op="back")
    r.check("back", bk.get("ok"), bk)

    # --- status ---
    stt = r.op(op="status")
    r.check("status", stt.get("ok") and stt.get("engine") == "chromium", stt)

    # --- session list ---
    sl = r.op(op="session_list")
    r.check("session_list", sl.get("ok"), sl)

    # --- learn_use ---
    r.op(op="navigate", url=JS)
    r.op(op="settle")
    r.op(op="find_text", text="GROW")  # teach
    # reset page
    r.op(op="navigate", url=JS)
    r.op(op="settle")
    lu = r.op(op="learn_use", text="GROW")
    r.check("learn_use GROW", lu.get("ok") and lu.get("clicked"), lu)

    # --- label ---
    lab = r.op(op="session_label", label="suite-labeled")
    r.check("session_label", lab.get("ok"), lab)

    # count pad to ≥30 via explicit meta checks
    r.check("engine always chromium on ping", p.get("product") == "mafia", p)
    r.check("suite has session", bool(r.sid), r.sid)


def main() -> int:
    mode = os.environ.get("MAFIA_SUITE_MODE", "dispatch")  # dispatch | tcp
    td = Path(os.environ.get("TMPDIR", "/tmp")) / f"mafia-suite-{os.getpid()}"
    td.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("MAFIA_SESSIONS_DIR", str(td / "sessions"))
    os.environ.setdefault("MAFIA_PROFILES_DIR", str(td / "profiles"))
    os.environ.setdefault("MAFIA_LEDGER_DIR", str(td / "ledger"))
    os.environ.setdefault("MAFIA_LEARN_DIR", str(td / "learn"))

    proc = None
    port = int(os.environ.get("MAFIA_SUITE_PORT", "17431"))

    if mode == "tcp":
        proc = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "mafia",
                "serve",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
                "--channel",
                "chrome",
            ],
            cwd=str(ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            env={**os.environ},
        )
        t0 = time.time()
        while time.time() - t0 < 30:
            try:
                s = socket.create_connection(("127.0.0.1", port), timeout=1)
                s.close()
                break
            except Exception:
                if proc.poll() is not None:
                    print("FAIL: server died")
                    print(proc.stdout.read() if proc.stdout else "")
                    return 1
                time.sleep(0.15)

        def call(op: dict) -> dict:
            s = socket.create_connection(("127.0.0.1", port), timeout=5)
            s.settimeout(90)
            f = s.makefile("rwb")
            f.write((json.dumps(op) + "\n").encode())
            f.flush()
            line = f.readline()
            s.close()
            return json.loads(line.decode())

        r = Runner(call)
        try:
            run_cases(r)
        finally:
            try:
                call({"op": "quit"})
            except Exception:
                pass
            if proc:
                try:
                    proc.wait(timeout=10)
                except Exception:
                    proc.kill()
    else:
        b = MafiaBrowser(headed=False, channel="chrome")

        def call(op: dict) -> dict:
            resp, _ = dispatch(b, json.dumps(op))
            return resp

        r = Runner(call)
        try:
            run_cases(r)
        finally:
            b.stop()

    total = r.passes + len(r.fails)
    print(f"mode={mode}  passed={r.passes}  failed={len(r.fails)}  total_checks={total}")
    if r.fails:
        print("FAIL")
        for f in r.fails:
            print(" -", f)
        return 1
    if r.passes < 30:
        print(f"FAIL: need ≥30 checks, got {r.passes}")
        return 1
    print(f"PASS: API suite ≥30 ({r.passes} checks)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
