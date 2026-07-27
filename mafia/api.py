"""JSONL dispatch — one engine of record (Chromium session)."""

from __future__ import annotations

import json
import time
from typing import Any

from mafia import __version__
from mafia import hancock as hancock_mod
from mafia import knox as knox_mod
from mafia import learn as learn_mod
from mafia import session_ledger
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
    "session_save",
    "session_load",
    "session_saves",
    "session_profiles",
    "session_delete",
    "session_label",
    "session_recent",
    "session_history",
    "session_reboot",
    "navigate",
    "settle",
    "snapshot",
    "read",
    "find_text",
    "query",
    "links",
    "click",
    "fill",
    "type",
    "press",
    "eval",
    "back",
    "forward",
    "learn_recall",
    "learn_suggest",
    "learn_use",
    "learn_recipe",
    "learn_note",
    "learn_list",
    "learn_forget",
    "knox_find",
    "knox_fill",
    "knox_use",
    "hancock_request",
    "hancock_wait",
    "hancock_pending",
    "quit",
]


def _err(code: str, msg: str) -> dict[str, Any]:
    return {"ok": False, "code": code, "error": msg}


def dispatch(browser: MafiaBrowser, line: str) -> tuple[dict[str, Any], bool]:
    """Returns (response, should_quit). Every op is ledger-recorded (secrets stripped)."""
    try:
        v = json.loads(line)
    except json.JSONDecodeError as e:
        return _err("bad_json", str(e)), False

    op = (v.get("op") or "").strip()
    t0 = time.time()
    try:
        resp, should_quit = _dispatch_body(browser, v, op)
    except KeyError as e:
        # Explicit unknown session id — never silent open (M4.1 footgun)
        resp, should_quit = _err("unknown_session", str(e)), False
    except ValueError as e:
        resp, should_quit = _err("bad_args", str(e)), False
    ms = int((time.time() - t0) * 1000)

    # Bump live session op counter
    sid = resp.get("session") or v.get("session") or browser._default_session
    if isinstance(sid, str) and sid in browser.sessions:
        browser.sessions[sid].op_count += 1

    try:
        profile = None
        save = None
        label = None
        work = None
        if isinstance(resp, dict):
            profile = resp.get("profile") if isinstance(resp.get("profile"), str) else None
            save = resp.get("save") if isinstance(resp.get("save"), str) else None
            label = resp.get("label") if isinstance(resp.get("label"), str) else None
            work = resp.get("work") if isinstance(resp.get("work"), str) else None
        if isinstance(sid, str) and sid in browser.sessions:
            s = browser.sessions[sid]
            profile = profile or s.profile
            save = save or s.last_save
            label = label or s.label
            work = work or s.work_key
        session_ledger.record_op(
            op=op or "unknown",
            request=v,
            response=resp if isinstance(resp, dict) else {"ok": False},
            session_id=sid if isinstance(sid, str) else None,
            work=work,
            profile=profile,
            save=save,
            label=label,
            url=resp.get("url") if isinstance(resp, dict) else None,
            title=resp.get("title") if isinstance(resp, dict) else None,
            ms=ms,
        )
    except Exception:
        pass

    return resp, should_quit


def _dispatch_body(
    browser: MafiaBrowser, v: dict[str, Any], op: str
) -> tuple[dict[str, Any], bool]:
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
        profile = v.get("profile")
        viewport = v.get("viewport") if isinstance(v.get("viewport"), dict) else None
        label = v.get("label") or v.get("work")
        try:
            sess = browser.open_session(
                session_id=v.get("id") or (None if profile else v.get("name")),
                profile=str(profile) if profile else None,
                restore_url=v.get("url") or v.get("restore_url"),
                viewport=viewport,
                user_agent=v.get("user_agent") or v.get("userAgent"),
                label=str(label) if label else None,
            )
        except ValueError as e:
            return _err("bad_args", str(e)), False
        return {
            "ok": True,
            "action": "session_open",
            "session": sess.id,
            "profile": sess.profile,
            "label": sess.label,
            "work": sess.work_key,
            "url": sess.page.url if sess.page else None,
            "session_count": len(browser.sessions),
        }, False

    if op == "session_list":
        live = []
        for s in browser.sessions.values():
            try:
                url = s.page.url
                title = s.page.title()
            except Exception:
                url, title = None, None
            live.append(
                {
                    "id": s.id,
                    "profile": s.profile,
                    "last_save": s.last_save,
                    "label": s.label,
                    "work": s.work_key,
                    "op_count": s.op_count,
                    "url": url,
                    "title": title,
                }
            )
        return {
            "ok": True,
            "sessions": list(browser.sessions.keys()),
            "live": live,
            "default_session": browser._default_session,
        }, False

    if op == "session_close":
        target = sid or v.get("id")
        if not target:
            return _err("bad_args", "session_close requires session or id"), False
        persist = v.get("persist")
        if persist is None:
            persist = True
        # Capture identity before close (session is removed)
        prior = browser.sessions.get(target)
        meta = {
            "label": prior.label if prior else None,
            "profile": prior.profile if prior else None,
            "save": prior.last_save if prior else None,
            "work": prior.work_key if prior else None,
        }
        ok = browser.close_session(target, persist=bool(persist))
        return {
            "ok": ok,
            "action": "session_close",
            "session": target,
            "label": meta["label"],
            "profile": meta["profile"],
            "save": meta["save"],
            "work": meta["work"],
            "session_count": len(browser.sessions),
        }, False

    if op == "session_save":
        name = v.get("name") or v.get("save") or v.get("id")
        if not name:
            return _err("bad_args", "session_save requires name"), False
        as_profile = bool(v.get("as_profile") or v.get("profile") is True)
        # allow {"op":"session_save","name":"x","profile":true} or as_profile
        if isinstance(v.get("profile"), str) and not as_profile:
            # save into that profile jar
            return browser.save_session(
                str(v.get("profile")), sid, as_profile=True
            ), False
        return browser.save_session(str(name), sid, as_profile=as_profile), False

    if op == "session_load":
        name = v.get("name") or v.get("save") or v.get("id")
        if not name:
            return _err("bad_args", "session_load requires name"), False
        from_profile = bool(v.get("from_profile") or v.get("profile") is True)
        if isinstance(v.get("profile"), str):
            name = v.get("profile")
            from_profile = True
        restore = v.get("restore_url")
        if restore is None:
            restore = True
        return browser.load_session(
            str(name),
            session_id=v.get("session_id") or (sid if sid and sid not in browser.sessions else None),
            from_profile=from_profile,
            restore_url=bool(restore),
        ), False

    if op == "session_saves":
        return browser.list_saves(), False

    if op == "session_profiles":
        return browser.list_profiles(), False

    if op == "session_delete":
        name = v.get("name") or v.get("save") or v.get("id")
        if not name:
            return _err("bad_args", "session_delete requires name"), False
        is_profile = bool(v.get("profile") is True or v.get("from_profile"))
        if isinstance(v.get("profile"), str):
            name = v.get("profile")
            is_profile = True
        return browser.delete_save(str(name), profile=is_profile), False

    if op == "session_label":
        lab = v.get("label") or v.get("name") or v.get("work")
        if not lab:
            return _err("bad_args", "session_label requires label"), False
        return browser.set_label(str(lab), sid), False

    if op == "session_recent":
        return browser.recent_work(limit=int(v.get("limit") or 20)), False

    if op == "session_history":
        return browser.history(
            work=v.get("work") or v.get("name") or v.get("label"),
            session=sid or v.get("id"),
            op=v.get("filter_op") or v.get("which_op"),
            limit=int(v.get("limit") or 50),
        ), False

    if op == "session_reboot":
        name = v.get("name") or v.get("work") or v.get("label") or v.get("id")
        return browser.reboot(
            str(name) if name else None,
            session_id=v.get("session_id"),
        ), False

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

    if op in ("fill", "type"):
        text = v.get("text") or v.get("value") or ""
        which = v.get("which") or v.get("field") or v.get("selector")
        selector = v.get("selector") if v.get("which") or v.get("field") else None
        if v.get("selector") and not v.get("which"):
            selector = v.get("selector")
            which = None
        return (
            browser.fill(
                text=text,
                selector=selector if isinstance(selector, str) else None,
                which=str(which) if which else "login",
                session_id=sid,
            ),
            False,
        )

    if op == "press":
        return browser.press(v.get("key") or "Enter", sid), False

    # ---- Learn (site memory — next surf is easier) ----
    if op == "learn_recall":
        url = v.get("url")
        if not url:
            try:
                st = browser.status(sid)
                url = st.get("url")
            except Exception:
                url = None
        return learn_mod.recall(url, origin=v.get("origin")), False

    if op == "learn_suggest":
        url = v.get("url")
        if not url:
            try:
                st = browser.status(sid)
                url = st.get("url")
            except Exception:
                url = None
        return learn_mod.suggest(
            url, origin=v.get("origin"), limit=int(v.get("limit") or 8)
        ), False

    if op == "learn_use":
        text = v.get("text") or v.get("target") or v.get("name") or ""
        if not text:
            return _err("bad_args", "learn_use requires text"), False
        click = v.get("click")
        if click is None:
            click = True
        return browser.learn_use(str(text), session_id=sid, click=bool(click)), False

    if op == "learn_recipe":
        return browser.learn_recipe(
            v.get("name"),
            session_id=sid,
            steps=v.get("steps") if isinstance(v.get("steps"), list) else None,
        ), False

    if op == "learn_note":
        note = v.get("note") or v.get("text") or ""
        url = v.get("url")
        if not url:
            try:
                st = browser.status(sid)
                url = st.get("url")
            except Exception:
                url = None
        return learn_mod.add_note(url, str(note), origin=v.get("origin")), False

    if op == "learn_list":
        sites = learn_mod.list_sites()
        return {
            "ok": True,
            "sites": sites,
            "count": len(sites),
            "dir": str(learn_mod.learn_dir()),
        }, False

    if op == "learn_forget":
        origin = v.get("origin")
        if not origin:
            try:
                st = browser.status(sid)
                origin = learn_mod.origin_key(st.get("url"))
            except Exception:
                origin = None
        if not origin:
            return _err("bad_args", "learn_forget requires origin or live session url"), False
        return learn_mod.forget(
            origin=str(origin),
            kind=v.get("kind"),
            value=v.get("value") or v.get("text"),
            all_memory=bool(v.get("all")),
        ), False

    # ---- Knox (secrets never in response) ----
    if op == "knox_find":
        q = v.get("query") or ""
        if not q:
            # default from current session URL
            try:
                st = browser.status(sid)
                q = knox_mod.query_from_url(st.get("url"))
            except Exception:
                q = ""
        limit = int(v.get("limit") or 10)
        return knox_mod.find(q, limit=limit), False

    if op == "knox_fill":
        q = v.get("query") or ""
        if not q:
            try:
                st = browser.status(sid)
                q = knox_mod.query_from_url(st.get("url"))
            except Exception:
                q = ""
        fields = (v.get("fields") or v.get("field") or "both").lower()
        # Optional Hancock gate when risk is high
        if v.get("hancock") or v.get("require_hancock"):
            hr = hancock_mod.request(
                "knox_fill",
                v.get("why") or f"Fill credentials for {q}",
                risk=v.get("risk") or "high",
                wait=bool(v.get("wait")),
                detail={"query": q, "fields": fields},
            )
            if hr.get("outcome") not in (
                "APPROVED_AND_RAN",
                "AUTO_APPROVED_AND_RAN",
            ):
                return {
                    **hr,
                    "ok": False,
                    "blocked": True,
                    "english": hr.get("english")
                    or "Hancock did not approve — not filling credentials.",
                    "secret_output": "suppressed",
                }, False

        want_login = fields in ("login", "both", "user", "username", "email", "")
        want_password = fields in ("password", "both", "pass", "")
        done = []
        record = None
        if want_login:
            title, value, err = knox_mod.unlock_field(q, "login")
            if err and not want_password:
                return {
                    "ok": False,
                    "error": err,
                    "secret_output": "suppressed",
                }, False
            if value is not None:
                r = browser.fill(text=value, which="login", session_id=sid)
                # drop value
                value = None  # noqa: F841
                if not r.get("ok"):
                    return {
                        "ok": False,
                        "error": r.get("error"),
                        "record": title,
                        "secret_output": "suppressed",
                    }, False
                record = title
                done.append("login")
        if want_password:
            title, value, err = knox_mod.unlock_field(q, "password")
            if err:
                return {
                    "ok": False,
                    "error": err,
                    "record": record or title,
                    "secret_output": "suppressed",
                }, False
            if value is not None:
                r = browser.fill(text=value, which="password", session_id=sid)
                value = None
                if not r.get("ok"):
                    return {
                        "ok": False,
                        "error": r.get("error"),
                        "record": title,
                        "secret_output": "suppressed",
                    }, False
                record = title or record
                done.append("password")
        return {
            "ok": bool(done),
            "action": "knox_fill",
            "record": record,
            "field": "+".join(done) if done else None,
            "error": None if done else "nothing filled",
            "secret_output": "suppressed",
            "session": sid or browser._default_session,
        }, False

    if op == "knox_use":
        q = v.get("query") or ""
        field = v.get("field") or "password"
        via = v.get("via") or "dry-run"
        if via in ("dry-run", "dry_run"):
            return knox_mod.dry_run_use(q, field), False
        return {
            "ok": False,
            "error": "knox_use on Mafia prefers knox_fill into the page; use via=dry-run or knox_fill",
            "secret_output": "suppressed",
        }, False

    # ---- Hancock (human sign-off) ----
    if op == "hancock_request":
        return (
            hancock_mod.request(
                v.get("action") or "navigate",
                v.get("why") or "Mafia agent request",
                risk=v.get("risk") or "high",
                wait=bool(v.get("wait")),
                timeout=int(v.get("timeout") or 600),
                detail=v.get("detail") if isinstance(v.get("detail"), dict) else None,
            ),
            False,
        )

    if op == "hancock_wait":
        hid = v.get("id") or v.get("hancock_id") or ""
        return hancock_mod.wait_for(hid, timeout=int(v.get("timeout") or 600)), False

    if op == "hancock_pending":
        return hancock_mod.pending(), False

    if op == "quit":
        browser.stop()
        return {
            "ok": True,
            "action": "quit",
            "note": "browser stopped",
        }, True

    return _err("unknown_op", f"unknown op {op!r} — try help"), False
