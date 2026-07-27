"""JSONL dispatch — one engine of record (Chromium session)."""

from __future__ import annotations

import json
from typing import Any

from mafia import __version__
from mafia.browser import MafiaBrowser

OPS = [
    "ping",
    "hello",
    "help",
    "ops",
    "status",
    "session_open",
    "session_list",
    "session_close",
    "navigate",
    "settle",
    "snapshot",
    "read",
    "find_text",
    "query",
    "links",
    "click",
    "eval",
    "back",
    "forward",
    "quit",
]


def _err(code: str, msg: str) -> dict[str, Any]:
    return {"ok": False, "code": code, "error": msg}


def dispatch(browser: MafiaBrowser, line: str) -> tuple[dict[str, Any], bool]:
    """Returns (response, should_quit)."""
    try:
        v = json.loads(line)
    except json.JSONDecodeError as e:
        return _err("bad_json", str(e)), False

    op = (v.get("op") or "").strip()
    sid = v.get("session")

    if op in ("ping", "hello"):
        return {
            "ok": True,
            "mafia": __version__,
            "api": "jsonl",
            "engine": "chromium",
            "product": "mafia",
            "sibling": "chrime",
            "session_count": len(browser.sessions),
        }, False

    if op in ("help", "ops"):
        return {
            "ok": True,
            "ops": OPS,
            "note": "Mafia = Chromium engine of record. Pass session id for multi-session.",
            "default_port": 7430,
        }, False

    if op == "status":
        return browser.status(sid), False

    if op == "session_open":
        sess = browser.open_session(session_id=v.get("id") or v.get("name"))
        return {
            "ok": True,
            "action": "session_open",
            "session": sess.id,
            "session_count": len(browser.sessions),
        }, False

    if op == "session_list":
        return {
            "ok": True,
            "sessions": list(browser.sessions.keys()),
            "default_session": browser._default_session,
        }, False

    if op == "session_close":
        target = sid or v.get("id")
        if not target:
            return _err("bad_args", "session_close requires session or id"), False
        ok = browser.close_session(target)
        return {
            "ok": ok,
            "action": "session_close",
            "session": target,
            "session_count": len(browser.sessions),
        }, False

    if op == "navigate":
        url = v.get("url") or ""
        if not url:
            return _err("bad_args", "url required"), False
        return browser.navigate(url, sid), False

    if op == "settle":
        quiet = int(v.get("quiet_ms") or 300)
        return browser.settle(sid, quiet_ms=quiet), False

    if op == "snapshot":
        return browser.snapshot(sid), False

    if op == "read":
        return browser.read(sid), False

    if op == "find_text":
        return {"ok": True, "matches": browser.find_text(v.get("text") or "", sid)}, False

    if op == "links":
        snap = browser.snapshot(sid)
        links = [n for n in snap.get("nodes", []) if n.get("href")]
        return {"ok": True, "links": links, "count": len(links)}, False

    if op == "query":
        # CSS via page; map to stamped ids when possible
        sel = v.get("selector") or v.get("css") or ""
        if not sel:
            return _err("bad_args", "selector required"), False
        sess = browser.get(sid)
        browser.snapshot(sid)  # stamp data-mafia-id
        try:
            handles = sess.page.query_selector_all(sel)
        except Exception as e:
            return _err("bad_selector", str(e)), False
        nodes = []
        for h in handles:
            mid = h.get_attribute("data-mafia-id")
            tag = h.evaluate("el => el.tagName.toLowerCase()")
            text = h.inner_text()[:200] if True else ""
            nodes.append(
                {
                    "node_id": int(mid) if mid and mid.isdigit() else 0,
                    "tag": tag,
                    "text": (text or "").replace("\n", " ").strip(),
                    "href": h.get_attribute("href"),
                }
            )
        return {
            "ok": True,
            "selector": sel,
            "count": len(nodes),
            "nodes": nodes,
        }, False

    if op == "click":
        nid = v.get("node_id")
        if nid is None:
            return _err("bad_args", "node_id required"), False
        return browser.click(int(nid), sid), False

    if op == "eval":
        js = v.get("js") or v.get("script") or v.get("expr") or ""
        if not js:
            return _err("bad_args", "js required"), False
        return browser.eval_js(js, sid), False

    if op == "back":
        return browser.back(sid), False

    if op == "forward":
        return browser.forward(sid), False

    if op == "quit":
        browser.stop()
        return {
            "ok": True,
            "action": "quit",
            "note": "browser stopped",
        }, True

    return _err("unknown_op", f"unknown op {op!r} — try help"), False
