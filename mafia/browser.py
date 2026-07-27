"""Chromium session pool — engine of record for every agent op."""

from __future__ import annotations

import itertools
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from playwright.sync_api import Browser, BrowserContext, Page, Playwright, sync_playwright

from mafia import learn as learn_mod
from mafia import session_ledger
from mafia import sessions_store
from mafia.snapshot import CLICK_JS, FIND_TEXT_JS, WALKER_JS


@dataclass
class Session:
    id: str
    context: BrowserContext
    page: Page
    created_at: float = field(default_factory=time.time)
    # Named profile: auto-persist storage on close/quit
    profile: str | None = None
    # Last explicit save name (metadata only)
    last_save: str | None = None
    # Agent-facing work label (rolls into ledger + auto-save jar)
    label: str | None = None
    op_count: int = 0
    # Short-term trail for learning (last find_text query on this page)
    last_find_query: str | None = None

    @property
    def work_key(self) -> str:
        return (
            session_ledger.work_key(
                profile=self.profile,
                save=self.last_save,
                label=self.label,
                session_id=self.id,
            )
            or f"live-{self.id}"
        )


class MafiaBrowser:
    """One Playwright browser; many isolated contexts (sessions)."""

    def __init__(self, *, headed: bool = False, channel: str | None = "chrome") -> None:
        self.headed = headed
        self.channel = channel  # system Chrome when available; else bundled chromium
        self._pw: Playwright | None = None
        self._browser: Browser | None = None
        self.sessions: dict[str, Session] = {}
        self._default_session: str | None = None
        self._id_counter = itertools.count(1)

    def start(self) -> None:
        if self._browser:
            return
        self._pw = sync_playwright().start()
        launch_kwargs: dict[str, Any] = {
            "headless": not self.headed,
        }
        # Prefer system Chrome for macOS "real browser" feel; fall back to bundled.
        try:
            if self.channel:
                launch_kwargs["channel"] = self.channel
            self._browser = self._pw.chromium.launch(**launch_kwargs)
        except Exception:
            launch_kwargs.pop("channel", None)
            self._browser = self._pw.chromium.launch(headless=not self.headed)

    def stop(self) -> None:
        # Flush profiles before teardown so cookies survive process exit
        for sid in list(self.sessions):
            self.close_session(sid, persist=True)
        if self._browser:
            self._browser.close()
            self._browser = None
        if self._pw:
            self._pw.stop()
            self._pw = None

    def open_session(
        self,
        *,
        session_id: str | None = None,
        profile: str | None = None,
        storage_state: str | dict[str, Any] | Path | None = None,
        restore_url: str | None = None,
        viewport: dict[str, int] | None = None,
        user_agent: str | None = None,
        label: str | None = None,
    ) -> Session:
        """Open an isolated BrowserContext.

        profile: named durable jar under logs/profiles/<name> (load if present, save on close).
        storage_state: path or dict (Playwright format) — also used by session_load.
        restore_url: navigate after open (from save meta or caller).
        label: work label for ledger + auto-save on close (agent reboot handle).
        """
        self.start()
        assert self._browser is not None
        sid = session_id or f"s{next(self._id_counter):04d}-{uuid.uuid4().hex[:6]}"
        if sid in self.sessions:
            raise ValueError(f"session exists: {sid}")

        state: str | dict[str, Any] | Path | None = storage_state
        url_from_profile: str | None = None
        prof = (profile or "").strip() or None
        lab = (label or "").strip() or None
        if prof and state is None:
            bundle = sessions_store.profile_path(prof)
            st, meta, err = sessions_store.read_bundle(bundle)
            if not err and st is not None:
                state = st
                url_from_profile = meta.get("url")

        ctx_kwargs: dict[str, Any] = {}
        if state is not None:
            ctx_kwargs["storage_state"] = state
        if viewport:
            ctx_kwargs["viewport"] = viewport
        if user_agent:
            ctx_kwargs["user_agent"] = user_agent

        ctx = self._browser.new_context(**ctx_kwargs)
        page = ctx.new_page()
        sess = Session(id=sid, context=ctx, page=page, profile=prof, label=lab)
        self.sessions[sid] = sess
        self._default_session = sid

        go = restore_url or url_from_profile
        if go:
            try:
                page.goto(go, wait_until="domcontentloaded", timeout=60_000)
            except Exception:
                # Still return session; caller sees partial restore via status/url
                pass
        return sess

    def close_session(self, session_id: str, *, persist: bool = True) -> bool:
        sess = self.sessions.pop(session_id, None)
        if not sess:
            return False
        if persist:
            try:
                self._auto_persist(sess)
            except Exception:
                pass
        try:
            sess.context.close()
        except Exception:
            pass
        if self._default_session == session_id:
            self._default_session = next(iter(self.sessions), None)
        return True

    def _auto_persist(self, sess: Session) -> dict[str, Any] | None:
        """Persist cookies/URL so work can reboot after process death."""
        if sess.profile:
            info = self._persist_session(sess, sessions_store.profile_path(sess.profile))
            session_ledger.touch_work(
                sess.profile,
                op="auto_persist",
                session_id=sess.id,
                url=info.get("url"),
                title=info.get("title"),
                profile=sess.profile,
                label=sess.label,
            )
            return info
        # Named save or work label → durable save jar
        name = sess.last_save or sess.label
        if name:
            info = self._persist_session(sess, sessions_store.save_path(name))
            sess.last_save = name
            session_ledger.touch_work(
                name,
                op="auto_persist",
                session_id=sess.id,
                url=info.get("url"),
                title=info.get("title"),
                save=name,
                label=sess.label,
            )
            return info
        # Ephemeral live session: checkpoint under live-<id> so reboot still works
        key = f"live-{sess.id}"
        try:
            info = self._persist_session(sess, sessions_store.save_path(key))
            sess.last_save = key
            session_ledger.touch_work(
                key,
                op="auto_persist",
                session_id=sess.id,
                url=info.get("url"),
                title=info.get("title"),
                save=key,
            )
            return info
        except ValueError:
            # invalid jar name — skip
            return None

    def _persist_session(self, sess: Session, dir_path: Path) -> dict[str, Any]:
        state = sess.context.storage_state()
        try:
            url = sess.page.url
            title = sess.page.title()
        except Exception:
            url, title = None, None
        return sessions_store.write_bundle(
            dir_path,
            storage_state=state,
            url=url,
            title=title,
            session_id=sess.id,
            extra={
                "label": sess.label,
                "profile": sess.profile,
                "last_save": sess.last_save,
                "op_count": sess.op_count,
            },
        )

    def set_label(self, label: str, session_id: str | None = None) -> dict[str, Any]:
        sess = self.get(session_id)
        lab = (label or "").strip()
        if not lab:
            return {"ok": False, "error": "label required", "code": "bad_args", "session": sess.id}
        sess.label = lab
        try:
            url = sess.page.url
            title = sess.page.title()
        except Exception:
            url, title = None, None
        entry = session_ledger.touch_work(
            lab,
            op="session_label",
            session_id=sess.id,
            url=url,
            title=title,
            profile=sess.profile,
            save=sess.last_save,
            label=lab,
        )
        return {
            "ok": True,
            "action": "session_label",
            "session": sess.id,
            "label": lab,
            "work": entry.get("key"),
            "url": url,
            "title": title,
        }

    def reboot(
        self,
        name: str | None = None,
        *,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        """Resume prior work: load profile/save from work index or name.

        If name omitted, reboots the most recently used durable work unit.
        """
        entry: dict[str, Any] | None = None
        if name:
            entry = session_ledger.get_work(name)
            # Also accept raw profile/save names not yet in index
            if not entry:
                # try profile then save
                for from_profile in (True, False):
                    r = self.load_session(
                        name, session_id=session_id, from_profile=from_profile
                    )
                    if r.get("ok"):
                        r["action"] = "session_reboot"
                        r["work"] = name
                        r["rebooted_from"] = "bundle"
                        return r
                return {
                    "ok": False,
                    "error": f"no work/profile/save named {name!r}",
                    "code": "not_found",
                    "hint": "session_recent lists rebootable work",
                }
        else:
            recent = session_ledger.list_recent(limit=50)
            for e in recent:
                if e.get("resume") or e.get("profile") or e.get("save") or e.get("label"):
                    entry = e
                    break
            if not entry:
                return {
                    "ok": False,
                    "error": "no recent work to reboot",
                    "code": "empty",
                    "hint": "open a labeled/profile session and use it first",
                }

        key = entry.get("key") or name
        resume = entry.get("resume") or {}
        kind = resume.get("kind")
        res_name = resume.get("name") or entry.get("profile") or entry.get("save") or entry.get("label") or key

        if kind == "profile" or entry.get("profile"):
            r = self.load_session(
                str(entry.get("profile") or res_name),
                session_id=session_id,
                from_profile=True,
            )
        else:
            r = self.load_session(
                str(res_name),
                session_id=session_id,
                from_profile=False,
            )
            # If save missing, try profile
            if not r.get("ok") and entry.get("profile"):
                r = self.load_session(
                    str(entry["profile"]),
                    session_id=session_id,
                    from_profile=True,
                )

        if r.get("ok"):
            # re-attach label for continued tracking
            sess = self.sessions.get(r["session"])
            if sess:
                if entry.get("label"):
                    sess.label = entry["label"]
                elif key and not str(key).startswith("live"):
                    sess.label = str(key)
            r["action"] = "session_reboot"
            r["work"] = key
            r["rebooted_from"] = "work_index"
            r["prior"] = {
                "last_url": entry.get("last_url"),
                "last_title": entry.get("last_title"),
                "last_op": entry.get("last_op"),
                "last_used_iso": entry.get("last_used_iso"),
                "op_count": entry.get("op_count"),
            }
        return r

    def recent_work(self, limit: int = 20) -> dict[str, Any]:
        items = session_ledger.list_recent(limit=limit)
        return {
            "ok": True,
            "work": items,
            "count": len(items),
            "ledger_dir": str(session_ledger.ledger_dir()),
            "hint": 'session_reboot with name, or session_reboot alone for most recent',
        }

    def history(
        self,
        *,
        work: str | None = None,
        session: str | None = None,
        op: str | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        rows = session_ledger.history(
            work=work, session=session, op=op, limit=limit
        )
        return {
            "ok": True,
            "events": rows,
            "count": len(rows),
            "work": work,
            "session": session,
            "path": str(session_ledger.events_path()),
        }

    def save_session(
        self,
        name: str,
        session_id: str | None = None,
        *,
        as_profile: bool = False,
    ) -> dict[str, Any]:
        """Export storage_state + URL to a named save (or profile jar)."""
        try:
            safe = name.strip()
            if not safe:
                return {"ok": False, "error": "name required", "code": "bad_args"}
        except Exception:
            return {"ok": False, "error": "name required", "code": "bad_args"}
        sess = self.get(session_id)
        try:
            if as_profile:
                path = sessions_store.profile_path(safe)
                kind = "profile"
            else:
                path = sessions_store.save_path(safe)
                kind = "save"
            info = self._persist_session(sess, path)
            sess.last_save = safe if not as_profile else sess.last_save
            if as_profile:
                sess.profile = safe
            session_ledger.touch_work(
                safe,
                op="session_save",
                session_id=sess.id,
                url=info.get("url"),
                title=info.get("title"),
                profile=sess.profile if as_profile else None,
                save=None if as_profile else safe,
                label=sess.label,
            )
            return {
                **info,
                "ok": True,
                "action": "session_save",
                "kind": kind,
                "session": sess.id,
                "label": sess.label,
                "work": safe,
            }
        except ValueError as e:
            return {"ok": False, "error": str(e), "code": "bad_args", "session": sess.id}
        except Exception as e:
            return {"ok": False, "error": str(e), "session": sess.id}

    def load_session(
        self,
        name: str,
        *,
        session_id: str | None = None,
        from_profile: bool = False,
        restore_url: bool = True,
    ) -> dict[str, Any]:
        """Open a new live session from a named save or profile."""
        try:
            path = (
                sessions_store.profile_path(name)
                if from_profile
                else sessions_store.save_path(name)
            )
        except ValueError as e:
            return {"ok": False, "error": str(e), "code": "bad_args"}
        state, meta, err = sessions_store.read_bundle(path)
        if err or state is None:
            return {
                "ok": False,
                "error": err or "empty state",
                "code": "not_found",
                "name": name,
                "path": str(path),
            }
        url = meta.get("url") if restore_url else None
        try:
            sess = self.open_session(
                session_id=session_id,
                storage_state=state,
                restore_url=url,
                profile=name if from_profile else None,
            )
            if not from_profile:
                sess.last_save = name
            extra = meta.get("extra") if isinstance(meta.get("extra"), dict) else {}
            if extra.get("label") and not sess.label:
                sess.label = extra.get("label")
            return {
                "ok": True,
                "action": "session_load",
                "session": sess.id,
                "name": name,
                "kind": "profile" if from_profile else "save",
                "url": sess.page.url,
                "title": sess.page.title(),
                "restored_url": url,
                "saved_at": meta.get("saved_at"),
                "path": str(path),
                "label": sess.label,
                "work": name,
                "session_count": len(self.sessions),
            }
        except Exception as e:
            return {"ok": False, "error": str(e), "name": name}

    def list_saves(self) -> dict[str, Any]:
        return {
            "ok": True,
            "saves": sessions_store.list_bundles(sessions_store.sessions_dir()),
            "dir": str(sessions_store.sessions_dir()),
        }

    def list_profiles(self) -> dict[str, Any]:
        return {
            "ok": True,
            "profiles": sessions_store.list_bundles(sessions_store.profiles_dir()),
            "dir": str(sessions_store.profiles_dir()),
        }

    def delete_save(self, name: str, *, profile: bool = False) -> dict[str, Any]:
        try:
            path = (
                sessions_store.profile_path(name)
                if profile
                else sessions_store.save_path(name)
            )
        except ValueError as e:
            return {"ok": False, "error": str(e), "code": "bad_args"}
        ok = sessions_store.delete_bundle(path)
        return {
            "ok": ok,
            "action": "session_delete",
            "name": name,
            "kind": "profile" if profile else "save",
            "path": str(path),
        }

    def get(self, session_id: str | None = None) -> Session:
        """Resolve session.

        - No id + no default → auto-open (first call ergonomics).
        - Explicit unknown id → error (never silently open a blank context).
        """
        if session_id is not None and str(session_id).strip():
            sid = str(session_id).strip()
            if sid not in self.sessions:
                raise KeyError(f"unknown session: {sid}")
            return self.sessions[sid]
        if self._default_session and self._default_session in self.sessions:
            return self.sessions[self._default_session]
        return self.open_session()

    def navigate(self, url: str, session_id: str | None = None) -> dict[str, Any]:
        sess = self.get(session_id)
        try:
            resp = sess.page.goto(url, wait_until="domcontentloaded", timeout=60_000)
            status = resp.status if resp else None
            title = sess.page.title()
            final = sess.page.url
            learn_mod.remember_navigate(final, title)
            sess.last_find_query = None  # new page — trail resets
            return {
                "ok": True,
                "url": final,
                "status": status,
                "title": title,
                "session": sess.id,
                "engine": "chromium",
                "origin": learn_mod.origin_key(final),
            }
        except Exception as e:
            return {
                "ok": False,
                "error": str(e),
                "url": url,
                "session": sess.id,
                "engine": "chromium",
            }

    def settle(self, session_id: str | None = None, quiet_ms: int = 300) -> dict[str, Any]:
        """Wait for load + short network idle-ish pause. Real engine, not a sleep-only lie."""
        sess = self.get(session_id)
        t0 = time.time()
        try:
            sess.page.wait_for_load_state("domcontentloaded", timeout=30_000)
        except Exception:
            pass
        try:
            sess.page.wait_for_load_state("networkidle", timeout=10_000)
            reason = "networkidle"
            quiescent = True
        except Exception:
            sess.page.wait_for_timeout(quiet_ms)
            reason = "quiet_ms"
            # quiet_ms is a fallback sleep — not network-quiescent
            quiescent = False
        ms = int((time.time() - t0) * 1000)
        return {
            "ok": True,
            "engine": "chromium",
            "session": sess.id,
            "ms": ms,
            "quiescent": quiescent,
            "reason": reason,
            "url": sess.page.url,
            "spins": 0,
        }

    def snapshot(self, session_id: str | None = None) -> dict[str, Any]:
        sess = self.get(session_id)
        data = sess.page.evaluate(WALKER_JS)
        data["session"] = sess.id
        data["engine"] = "chromium"
        return data

    def read(self, session_id: str | None = None) -> dict[str, Any]:
        sess = self.get(session_id)
        text = sess.page.inner_text("body")
        return {
            "ok": True,
            "text": text,
            "chars": len(text),
            "session": sess.id,
            "engine": "chromium",
        }

    def find_text(self, q: str, session_id: str | None = None) -> list[dict[str, Any]]:
        sess = self.get(session_id)
        matches = sess.page.evaluate(FIND_TEXT_JS, q)
        sess.last_find_query = q if matches else sess.last_find_query
        if matches:
            learn_mod.remember_find(sess.page.url, q, matches)
        elif q:
            learn_mod.remember_miss(sess.page.url, kind="text", value=q)
        return matches

    def click(self, node_id: int, session_id: str | None = None) -> dict[str, Any]:
        sess = self.get(session_id)
        # Re-stamp ids then click (same walk order as snapshot)
        sess.page.evaluate(WALKER_JS)
        result = sess.page.evaluate(CLICK_JS, node_id)
        result["session"] = sess.id
        result["url"] = sess.page.url
        result["title"] = sess.page.title()
        result["engine"] = "chromium"
        if result.get("ok"):
            learn_mod.remember_click(
                sess.page.url,
                text=result.get("text"),
                tag=result.get("tag"),
                href=result.get("href"),
                find_query=sess.last_find_query,
            )
        return result

    def learn_use(
        self,
        text: str,
        *,
        session_id: str | None = None,
        click: bool = True,
    ) -> dict[str, Any]:
        """Reuse a known landmark: find text, optionally click first match.

        This is the 'easier next time' path — prefer over blind thrashing.
        """
        sess = self.get(session_id)
        q = (text or "").strip()
        if not q:
            return {"ok": False, "error": "text required", "code": "bad_args", "session": sess.id}
        matches = self.find_text(q, sess.id)
        if not matches:
            learn_mod.remember_miss(sess.page.url, kind="click_text", value=q)
            return {
                "ok": False,
                "action": "learn_use",
                "error": f"no match for {q!r}",
                "text": q,
                "session": sess.id,
                "url": sess.page.url,
                "origin": learn_mod.origin_key(sess.page.url),
            }
        top = matches[0]
        out: dict[str, Any] = {
            "ok": True,
            "action": "learn_use",
            "text": q,
            "matched": top,
            "match_count": len(matches),
            "session": sess.id,
            "url": sess.page.url,
            "origin": learn_mod.origin_key(sess.page.url),
            "clicked": False,
        }
        can_click = bool(top.get("clickable")) or top.get("tag") in (
            "a",
            "button",
            "input",
        )
        if click and can_click:
            nid = top.get("node_id")
            if nid is not None:
                cr = self.click(int(nid), sess.id)
                out["clicked"] = bool(cr.get("ok"))
                out["click"] = cr
                out["ok"] = bool(cr.get("ok"))
                if not cr.get("ok"):
                    out["error"] = cr.get("error")
        elif click:
            # found non-clickable — still useful for verification
            out["clicked"] = False
            out["note"] = "match found but not clickable; set click=false to only locate"
        return out

    def learn_recipe(
        self,
        name: str | None = None,
        *,
        session_id: str | None = None,
        steps: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Run a named recipe for current origin, or provided steps."""
        sess = self.get(session_id)
        url = sess.page.url
        origin = learn_mod.origin_key(url)
        run_steps = steps
        if not run_steps and name:
            mem = learn_mod.recall(url)
            for r in mem.get("recipes") or []:
                if r.get("name") == name or name in (r.get("name") or ""):
                    run_steps = r.get("steps") or []
                    name = r.get("name")
                    break
        if not run_steps:
            return {
                "ok": False,
                "error": "recipe not found — pass name or steps",
                "code": "not_found",
                "origin": origin,
                "session": sess.id,
            }
        results = []
        for step in run_steps:
            sop = (step.get("op") or "").strip()
            if sop == "find_text":
                m = self.find_text(step.get("text") or "", sess.id)
                results.append({"op": sop, "ok": bool(m), "count": len(m)})
                if not m:
                    return {
                        "ok": False,
                        "action": "learn_recipe",
                        "name": name,
                        "error": f"find_text failed: {step.get('text')}",
                        "results": results,
                        "session": sess.id,
                    }
            elif sop in ("click_text", "learn_use"):
                r = self.learn_use(
                    step.get("text") or "",
                    session_id=sess.id,
                    click=True,
                )
                results.append({"op": sop, "ok": r.get("ok"), "detail": r})
                if not r.get("ok"):
                    return {
                        "ok": False,
                        "action": "learn_recipe",
                        "name": name,
                        "error": r.get("error"),
                        "results": results,
                        "session": sess.id,
                    }
            elif sop == "navigate":
                r = self.navigate(step.get("url") or "", sess.id)
                results.append({"op": sop, "ok": r.get("ok")})
                if not r.get("ok"):
                    return {
                        "ok": False,
                        "action": "learn_recipe",
                        "name": name,
                        "error": r.get("error"),
                        "results": results,
                        "session": sess.id,
                    }
            elif sop == "settle":
                r = self.settle(sess.id)
                results.append({"op": sop, "ok": r.get("ok")})
            else:
                results.append({"op": sop, "ok": False, "error": "unsupported step"})
        return {
            "ok": True,
            "action": "learn_recipe",
            "name": name,
            "steps_run": len(results),
            "results": results,
            "session": sess.id,
            "url": sess.page.url,
            "origin": origin,
        }
    def eval_js(self, expr: str, session_id: str | None = None) -> dict[str, Any]:
        sess = self.get(session_id)
        try:
            # Wrap expression so bare expressions work
            result = sess.page.evaluate(f"() => ({expr})")
            return {
                "ok": True,
                "result": result,
                "session": sess.id,
                "engine": "chromium",
            }
        except Exception as e:
            try:
                result = sess.page.evaluate(expr)
                return {
                    "ok": True,
                    "result": result,
                    "session": sess.id,
                    "engine": "chromium",
                }
            except Exception as e2:
                return {
                    "ok": False,
                    "error": str(e2) or str(e),
                    "session": sess.id,
                    "engine": "chromium",
                }

    def back(self, session_id: str | None = None) -> dict[str, Any]:
        sess = self.get(session_id)
        sess.page.go_back(wait_until="domcontentloaded")
        return {"ok": True, "url": sess.page.url, "session": sess.id}

    def forward(self, session_id: str | None = None) -> dict[str, Any]:
        sess = self.get(session_id)
        sess.page.go_forward(wait_until="domcontentloaded")
        return {"ok": True, "url": sess.page.url, "session": sess.id}

    def status(self, session_id: str | None = None) -> dict[str, Any]:
        sess = None
        if session_id is not None and str(session_id).strip():
            sess = self.get(session_id)  # raises if unknown
        elif self._default_session and self._default_session in self.sessions:
            sess = self.sessions[self._default_session]
        return {
            "ok": True,
            "engine": "chromium",
            "headed": self.headed,
            "session_count": len(self.sessions),
            "sessions": list(self.sessions.keys()),
            "default_session": self._default_session,
            "url": sess.page.url if sess else None,
            "title": sess.page.title() if sess else None,
        }

    def fill(
        self,
        *,
        text: str,
        selector: str | None = None,
        which: str | None = None,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        """Fill a form field. `text` must not be logged by API layer as a secret path."""
        sess = self.get(session_id)
        sel = selector
        if not sel:
            w = (which or "login").lower()
            if w in ("login", "user", "username", "email"):
                sel = (
                    'input[type="email"], input[name*="user" i], input[name*="email" i], '
                    'input[id*="user" i], input[id*="email" i], input[type="text"]'
                )
            elif w in ("password", "pass"):
                sel = 'input[type="password"]'
            else:
                sel = which  # treat as CSS
        try:
            loc = sess.page.locator(sel).first
            loc.fill(text, timeout=10_000)
            return {
                "ok": True,
                "action": "fill",
                "which": which or selector,
                "session": sess.id,
                "secret_output": "suppressed",
            }
        except Exception as e:
            return {
                "ok": False,
                "action": "fill",
                "error": str(e),
                "session": sess.id,
                "secret_output": "suppressed",
            }

    def press(self, key: str = "Enter", session_id: str | None = None) -> dict[str, Any]:
        sess = self.get(session_id)
        try:
            sess.page.keyboard.press(key)
            return {"ok": True, "key": key, "session": sess.id}
        except Exception as e:
            return {"ok": False, "error": str(e), "session": sess.id}
