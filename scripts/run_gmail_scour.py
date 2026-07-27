#!/usr/bin/env python3
"""Gmail scour on Mafia — six unrelated themes (PLAN M3 / EID-1070).

Port of chrime/scripts/run_gmail_scour.py to real Chromium + Mafia ops.
Measures wall times so we can compare vs Chrime.

  # one-shot headed (recommended first run — human logs in once)
  python3 scripts/run_gmail_scour.py --headed --profile gmail-work

  # later runs reuse cookies in the profile jar
  python3 scripts/run_gmail_scour.py --headed --profile gmail-work --skip-login-prompt

  # or attach to an already-running server
  python3 -m mafia serve --headed --port 7430
  python3 scripts/run_gmail_scour.py --port 7430 --profile gmail-work
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import socket
import sys
import time
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

THEMES: list[dict[str, str]] = [
    {
        "id": "commerce",
        "label": "Commerce",
        "query": "subject:(order OR shipped OR delivery OR tracking OR receipt OR package)",
        "positive": r"\b(order|shipped|shipping|delivery|tracking|package|parcel|bought|purchase)\b",
    },
    {
        "id": "security",
        "label": "Security",
        "query": 'subject:(security OR "sign-in" OR "signed in" OR password OR unusual OR verify OR "2-step" OR 2FA)',
        "positive": r"\b(security|sign[- ]?in|password|unusual|verify|verification|2-?step|2fa|suspicious|alert)\b",
    },
    {
        "id": "calendar",
        "label": "Calendar",
        "query": "subject:(invitation OR invited OR meeting OR calendar OR RSVP OR Zoom OR Meet)",
        "positive": r"\b(invitation|invited|meeting|calendar|rsvp|zoom|google meet|teams|webinar)\b",
    },
    {
        "id": "finance",
        "label": "Finance",
        "query": "subject:(invoice OR statement OR payment OR bank OR tax OR payroll OR wire OR refund)",
        "positive": r"\b(invoice|statement|payment|bank|tax|payroll|wire|refund|balance|card ending)\b",
    },
    {
        "id": "travel",
        "label": "Travel",
        "query": "subject:(flight OR boarding OR hotel OR itinerary OR booking OR airline OR Airbnb)",
        "positive": r"\b(flight|boarding|hotel|itinerary|booking|airline|airbnb|check-?in|departure|arrival)\b",
    },
    {
        "id": "social_product",
        "label": "Social/product",
        "query": 'subject:(newsletter OR digest OR "new feature" OR announcement OR update OR unfollow)',
        "positive": r"\b(newsletter|digest|feature|announcement|unsubscribe|product update|what's new|whats new)\b",
    },
]

INBOX_MARKERS = ("inbox", "primary", "compose", "search mail", "mail.google.com", "gmail")
LOGIN_MARKERS = (
    "sign in",
    "forgot email",
    "enter your password",
    "verify it’s you",
    "verify it's you",
    "2-step verification",
    "account recovery",
    "choose an account",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Timing:
    def __init__(self) -> None:
        self.marks: dict[str, float] = {}
        self.t0 = time.perf_counter()

    def mark(self, name: str) -> float:
        now = time.perf_counter()
        self.marks[name] = now - self.t0
        return self.marks[name]

    def phase(self, name: str, t_start: float) -> float:
        dt = time.perf_counter() - t_start
        self.marks[f"phase_{name}_s"] = round(dt, 3)
        return dt

    def report(self) -> dict[str, float]:
        out = {k: round(v, 3) for k, v in self.marks.items()}
        out["total_s"] = round(time.perf_counter() - self.t0, 3)
        return out


class MafiaClient:
    """JSONL client — TCP or in-process dispatch."""

    def __init__(self, call: Callable[[dict[str, Any]], dict[str, Any]]) -> None:
        self._call = call
        self.ops_used: list[str] = []
        self.sid: str | None = None

    def call(self, op: dict[str, Any]) -> dict[str, Any]:
        name = str(op.get("op", "?"))
        self.ops_used.append(name)
        if self.sid and "session" not in op and name not in (
            "ping",
            "help",
            "ops",
            "session_open",
            "session_load",
            "session_reboot",
            "session_saves",
            "session_profiles",
            "session_recent",
            "quit",
        ):
            op = {**op, "session": self.sid}
        return self._call(op)


def make_tcp_call(host: str, port: int, timeout: float) -> Callable[[dict], dict]:
    def call(op: dict) -> dict:
        line = json.dumps(op, separators=(",", ":")) + "\n"
        with socket.create_connection((host, port), timeout=timeout) as sock:
            sock.settimeout(timeout)
            sock.sendall(line.encode("utf-8"))
            buf = b""
            while b"\n" not in buf:
                chunk = sock.recv(65536)
                if not chunk:
                    break
                buf += chunk
        raw = buf.decode("utf-8", errors="replace").strip().splitlines()
        if not raw:
            return {"ok": False, "code": "empty_response"}
        try:
            return json.loads(raw[0])
        except json.JSONDecodeError as e:
            return {"ok": False, "code": "bad_json", "error": str(e)}

    return call


def make_local_call(browser: Any) -> Callable[[dict], dict]:
    from mafia.api import dispatch

    def call(op: dict) -> dict:
        resp, _ = dispatch(browser, json.dumps(op))
        return resp

    return call


def text_looks_inbox(text: str) -> bool:
    t = text.lower()
    return any(m in t for m in INBOX_MARKERS)


def text_looks_login(text: str) -> bool:
    t = text.lower()
    return any(m in t for m in LOGIN_MARKERS)


def extract_hit(theme: dict[str, str], text: str) -> dict[str, Any] | None:
    if not text or len(text.strip()) < 20:
        return None
    pos = re.compile(theme["positive"], re.I)
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    candidates: list[tuple[int, str]] = []
    for i, ln in enumerate(lines):
        if len(ln) < 8 or len(ln) > 220:
            continue
        if ln.lower() in {"inbox", "primary", "social", "promotions", "compose", "search mail"}:
            continue
        if pos.search(ln):
            candidates.append((i, ln))
    if not candidates:
        if not pos.search(text):
            return None
        for i, ln in enumerate(lines):
            if 20 <= len(ln) <= 180 and not ln.startswith("http"):
                candidates.append((i, ln))
                break
    if not candidates:
        return None
    idx, subject = candidates[0]
    from_ = lines[idx - 1] if idx > 0 and len(lines[idx - 1]) < 80 else ""
    snippet = lines[idx + 1] if idx + 1 < len(lines) and len(lines[idx + 1]) < 200 else ""
    key = hashlib.sha256(f"{subject}|{from_}".encode()).hexdigest()[:16]
    return {
        "status": "hit",
        "subject": subject,
        "from": from_,
        "snippet": snippet,
        "query": theme["query"],
        "message_key": key,
        "evidence": " · ".join(x for x in (from_, subject, snippet) if x)[:400],
    }


def search_url(query: str) -> str:
    q = urllib.parse.quote(query, safe="")
    return f"https://mail.google.com/mail/u/0/#search/{q}"


def read_page(client: MafiaClient) -> str:
    """Mafia: short settle + read body text (real Chromium post-JS).

    Never raises — closed window / flaky SPA returns empty string.
    """
    try:
        client.call({"op": "settle", "quiet_ms": 200})
        client.call({"op": "wait", "ms": 400})
        r = client.call({"op": "read"})
        if not r.get("ok"):
            return ""
        return str(r.get("text") or "")
    except Exception as e:
        print(f"  (read_page soft-fail: {type(e).__name__}: {e})", flush=True)
        return ""


def _login_signal_path() -> Path:
    return ROOT / "logs" / "gmail-login-done"


def wait_for_inbox(
    client: MafiaClient,
    timeout: int,
    prompt: bool,
    timing: Timing,
) -> tuple[str, str]:
    """Wait for human login without thrashing the page.

    Critical: do **not** re-navigate every poll — that kills mid-login / 2FA.
    Navigate once, then only read until inbox, Enter, or signal file.
    """
    t_auth = time.perf_counter()
    last = ""
    signal = _login_signal_path()
    try:
        if signal.is_file():
            signal.unlink()
    except OSError:
        pass

    # Land once — leave the window alone for the human
    # Prefer real mail app URL (not marketing workspace.google.com)
    for url in (
        "https://mail.google.com/mail/u/0/#inbox",
        "https://mail.google.com/",
    ):
        nav = client.call({"op": "navigate", "url": url})
        if nav.get("ok"):
            break
    client.call({"op": "settle", "quiet_ms": 500})
    last = read_page(client)

    if text_looks_inbox(last) and not text_looks_login(last):
        timing.phase("auth", t_auth)
        print("Already in inbox — no login needed.", flush=True)
        return "passed", last

    print(
        "\n"
        "╔══════════════════════════════════════════════════════════════╗\n"
        "║  STOP — YOUR TURN                                            ║\n"
        "║  1. Log into Gmail in the Chrome window (password / 2FA).    ║\n"
        "║  2. When you see Inbox / Primary, signal done:               ║\n"
        "║       touch ~/repos-eidos-agi/mafia/logs/gmail-login-done    ║\n"
        "║     or press Enter in this terminal (if interactive).        ║\n"
        "║  Window is NOT reloaded while you log in.                    ║\n"
        "╚══════════════════════════════════════════════════════════════╝\n",
        flush=True,
    )

    deadline = time.time() + timeout
    n = 0
    enter_pressed = False

    # Non-blocking Enter if TTY; otherwise signal-file / auto-detect only
    import select

    has_tty = False
    try:
        has_tty = sys.stdin.isatty()
    except Exception:
        has_tty = False

    if prompt and has_tty:
        print(">>> Press Enter AFTER inbox is visible (or create signal file)…", flush=True)
    elif prompt:
        print(
            f"(no TTY — use signal file or wait for auto-detect; timeout {timeout}s)\n"
            f"  touch {signal}",
            flush=True,
        )

    while time.time() < deadline:
        n += 1
        # Signal file from human / another terminal
        if signal.is_file():
            print("Signal file seen — checking inbox…", flush=True)
            try:
                signal.unlink()
            except OSError:
                pass
            last = read_page(client)
            if text_looks_inbox(last) and not text_looks_login(last):
                timing.phase("auth", t_auth)
                print("Auth OK (signal file).", flush=True)
                return "passed", last
            client.call({"op": "navigate", "url": "https://mail.google.com/mail/u/0/#inbox"})
            last = read_page(client)
            if text_looks_inbox(last) and not text_looks_login(last):
                timing.phase("auth", t_auth)
                print("Auth OK (signal + inbox nav).", flush=True)
                return "passed", last
            print("Still not inbox after signal — keep logging in…", flush=True)

        # Enter key if interactive TTY
        if prompt and has_tty and not enter_pressed:
            try:
                r, _, _ = select.select([sys.stdin], [], [], 0)
                if r:
                    sys.stdin.readline()
                    enter_pressed = True
                    print("Enter received — checking inbox…", flush=True)
                    last = read_page(client)
                    if text_looks_inbox(last) and not text_looks_login(last):
                        timing.phase("auth", t_auth)
                        print("Auth OK (Enter).", flush=True)
                        return "passed", last
                    client.call(
                        {"op": "navigate", "url": "https://mail.google.com/mail/u/0/#inbox"}
                    )
                    last = read_page(client)
                    if text_looks_inbox(last) and not text_looks_login(last):
                        timing.phase("auth", t_auth)
                        print("Auth OK (Enter + inbox nav).", flush=True)
                        return "passed", last
                    print("Still not inbox after Enter — keep logging in…", flush=True)
            except Exception:
                pass

        # Soft poll: read only
        last = read_page(client)
        state = (
            "login_wall"
            if text_looks_login(last)
            else ("inbox" if text_looks_inbox(last) else f"other({len(last)} chars)")
        )
        if n == 1 or n % 5 == 0:
            print(f"  auth poll #{n}: {state}", flush=True)
        if text_looks_inbox(last) and not text_looks_login(last):
            timing.phase("auth", t_auth)
            print("Auth OK (auto-detect).", flush=True)
            return "passed", last

        st = client.call({"op": "status"})
        url = str(st.get("url") or "")
        # Only re-nav if we left Google entirely (never during accounts.google.com 2FA)
        if url and "google." not in url and "gmail" not in url.lower():
            client.call({"op": "navigate", "url": "https://mail.google.com/mail/u/0/#inbox"})
        time.sleep(3.0)

    timing.phase("auth", t_auth)
    if text_looks_login(last):
        return "blocked_human_auth", last
    return "failed", last


def scour_themes(
    client: MafiaClient,
    search_wait_ms: int,
    timing: Timing,
) -> tuple[dict[str, Any], int, int, list[str]]:
    themes_out: dict[str, Any] = {}
    hits = misses = 0
    notes: list[str] = []
    used_keys: set[str] = set()
    t_scour = time.perf_counter()

    for theme in THEMES:
        tid = theme["id"]
        t_one = time.perf_counter()
        url = search_url(theme["query"])
        client.call({"op": "navigate", "url": url})
        client.call({"op": "settle", "quiet_ms": 300})
        client.call({"op": "wait", "ms": search_wait_ms})
        # try wait for any dense content
        client.call({"op": "wait", "text": "Inbox", "timeout_ms": 4000})
        text = read_page(client)
        # also try snapshot for role-based compose etc (debug density)
        snap = client.call({"op": "snapshot"})
        node_count = snap.get("node_count") or len(snap.get("nodes") or [])

        hit = extract_hit(theme, text)
        if hit and hit["message_key"] in used_keys:
            hit = None
            notes.append(f"{tid}: discarded duplicate message_key")
        dt = time.perf_counter() - t_one
        if hit:
            used_keys.add(hit["message_key"])
            hit["seconds"] = round(dt, 3)
            hit["node_count"] = node_count
            themes_out[tid] = hit
            hits += 1
            print(f"  [HIT]  {theme['label']:14} {dt:5.1f}s  {hit['subject'][:70]}", flush=True)
        else:
            themes_out[tid] = {
                "status": "miss",
                "query": theme["query"],
                "excerpt": text[:400],
                "seconds": round(dt, 3),
                "node_count": node_count,
            }
            misses += 1
            print(f"  [MISS] {theme['label']:14} {dt:5.1f}s  nodes={node_count} chars={len(text)}", flush=True)

    timing.phase("scour_all", t_scour)
    return themes_out, hits, misses, notes


def write_report(path: str, report: dict[str, Any]) -> Path:
    p = Path(path)
    if not p.is_absolute():
        p = ROOT / p
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return p


def run(args: argparse.Namespace) -> int:
    timing = Timing()
    report: dict[str, Any] = {
        "test": "gmail-scour-complex",
        "engine": "mafia",
        "eid": "EID-1070",
        "started_at": utc_now(),
        "finished_at": None,
        "auth": "unknown",
        "themes": {},
        "hits": 0,
        "misses": 0,
        "passed": False,
        "ops_used": [],
        "notes": [],
        "timing": {},
        "mode": "tcp" if args.port else "in-process",
        "profile": args.profile,
    }

    browser = None
    server = None
    client: MafiaClient

    try:
        if args.port:
            # attach to existing mafia serve
            call = make_tcp_call(args.host, args.port, args.socket_timeout)
            client = MafiaClient(call)
            ping = client.call({"op": "ping"})
            if not ping.get("ok"):
                print("FAIL: cannot reach Mafia TCP — start: python3 -m mafia serve --headed", file=sys.stderr)
                return 2
            report["notes"].append(f"ping engine={ping.get('engine')} product={ping.get('product')}")
        else:
            from mafia.browser import MafiaBrowser

            channel = args.channel if args.channel != "" else None
            # Skin: respect MAFIA_SKIN env (on|off|auto). Headed+auto → theme pack on
            # bundled Chromium. Use --channel chrome + MAFIA_SKIN=off for system Chrome.
            print(
                f"boot: headed={args.headed} channel={channel!r} "
                f"MAFIA_SKIN={os.environ.get('MAFIA_SKIN', 'auto')!r}",
                flush=True,
            )
            browser = MafiaBrowser(headed=args.headed, channel=channel)
            print(
                f"browser ready: skin={getattr(browser, 'skin', None)} "
                f"persistent={getattr(browser, '_persistent', None) is not None}",
                flush=True,
            )
            client = MafiaClient(make_local_call(browser))
            report["notes"].append(
                f"in-process headed={args.headed} skin={getattr(browser, 'skin', None)} channel={channel!r}"
            )

        timing.mark("ready")

        # open / reboot durable profile
        t_open = time.perf_counter()
        if args.profile:
            # try load profile first for speed on re-run
            open_r = client.call(
                {
                    "op": "session_open",
                    "profile": args.profile,
                    "label": "gmail-scour",
                }
            )
            if not open_r.get("ok"):
                open_r = client.call({"op": "session_open", "label": "gmail-scour"})
        else:
            open_r = client.call({"op": "session_open", "label": "gmail-scour"})
        if not open_r.get("ok"):
            print(f"FAIL: session_open {open_r}", file=sys.stderr)
            return 2
        client.sid = open_r.get("session")
        report["session"] = client.sid
        report["notes"].append(f"session_open: {open_r.get('url')}")
        timing.phase("session_open", t_open)
        print(f"session={client.sid} open_url={open_r.get('url')}", flush=True)

        # navigate gmail
        t_nav = time.perf_counter()
        client.call({"op": "navigate", "url": "https://mail.google.com/"})
        client.call({"op": "settle", "quiet_ms": 500})
        timing.phase("nav_gmail", t_nav)

        auth, last = wait_for_inbox(
            client,
            timeout=args.login_timeout,
            prompt=not args.skip_login_prompt,
            timing=timing,
        )
        report["auth"] = auth
        if auth != "passed":
            report["notes"].append(f"auth={auth} excerpt={last[:300]!r}")
            report["timing"] = timing.report()
            report["finished_at"] = utc_now()
            path = write_report(args.report, report)
            print(f"FAIL: auth={auth}  report={path}", file=sys.stderr)
            print(
                "If this is first run, re-run without --skip-login-prompt and complete login in the window.",
                file=sys.stderr,
            )
            return 1

        print(f"\nAuth OK in {timing.marks.get('phase_auth_s', '?')}s — scouring 6 themes…\n")

        themes, hits, misses, notes = scour_themes(
            client, args.search_wait_ms, timing
        )
        report["themes"] = themes
        report["hits"] = hits
        report["misses"] = misses
        report["notes"].extend(notes)

        # persist profile jar for next run speed
        if args.profile:
            save = client.call({"op": "session_save", "name": args.profile, "as_profile": True})
            report["notes"].append(f"profile save: ok={save.get('ok')}")

        # learn landmarks for gmail
        client.call({"op": "learn_note", "note": "Gmail scour: use #search/ URLs; profile=gmail-work"})
        sug = client.call({"op": "learn_suggest"})
        report["notes"].append(f"learn_suggest count={sug.get('count')}")

        report["ops_used"] = list(dict.fromkeys(client.ops_used))
        report["passed"] = report["auth"] == "passed" and hits >= args.min_hits
        report["timing"] = timing.report()
        report["finished_at"] = utc_now()
        path = write_report(args.report, report)

        print(
            f"\nResult: hits={hits}/6 misses={misses} passed={report['passed']}\n"
            f"Timing: {json.dumps(report['timing'], indent=2)}\n"
            f"Report: {path}"
        )
        return 0 if report["passed"] else 1

    finally:
        if browser is not None:
            try:
                client.call({"op": "quit"})
            except Exception:
                browser.stop()
        if server is not None:
            server.terminate()


def main() -> int:
    ap = argparse.ArgumentParser(description="Mafia Gmail scour — 6 themes on real Chromium")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument(
        "--port",
        type=int,
        default=None,
        help="If set, attach to mafia serve on this port; else in-process",
    )
    ap.add_argument("--headed", action="store_true", default=True, help="Headed Chromium (default on)")
    ap.add_argument("--headless", action="store_true", help="Force headless (usually fails Gmail login)")
    ap.add_argument("--channel", default="chrome", help="Playwright channel (chrome|'' for bundled)")
    ap.add_argument("--profile", default="gmail-work", help="Durable profile name for cookie jar")
    ap.add_argument("--login-timeout", type=int, default=300)
    ap.add_argument("--search-wait-ms", type=int, default=2500)
    ap.add_argument("--socket-timeout", type=float, default=60.0)
    ap.add_argument(
        "--skip-login-prompt",
        action="store_true",
        help="Do not wait for Enter (soft-poll only). Default waits for you to finish login.",
    )
    ap.add_argument("--min-hits", type=int, default=5, help="Pass bar (default ≥5 of 6; full is 6)")
    ap.add_argument("--report", default="logs/gmail-scour-report.json")
    args = ap.parse_args()
    if args.headless:
        args.headed = False
    if args.channel == "":
        args.channel = ""
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
