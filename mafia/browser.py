"""Chromium session pool — engine of record for every agent op."""

from __future__ import annotations

import itertools
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from playwright.sync_api import Browser, BrowserContext, Page, Playwright, sync_playwright

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
    ) -> Session:
        """Open an isolated BrowserContext.

        profile: named durable jar under logs/profiles/<name> (load if present, save on close).
        storage_state: path or dict (Playwright format) — also used by session_load.
        restore_url: navigate after open (from save meta or caller).
        """
        self.start()
        assert self._browser is not None
        sid = session_id or f"s{next(self._id_counter):04d}-{uuid.uuid4().hex[:6]}"
        if sid in self.sessions:
            raise ValueError(f"session exists: {sid}")

        state: str | dict[str, Any] | Path | None = storage_state
        url_from_profile: str | None = None
        prof = (profile or "").strip() or None
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
        sess = Session(id=sid, context=ctx, page=page, profile=prof)
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
        if persist and sess.profile:
            try:
                self._persist_session(sess, sessions_store.profile_path(sess.profile))
            except Exception:
                pass
        try:
            sess.context.close()
        except Exception:
            pass
        if self._default_session == session_id:
            self._default_session = next(iter(self.sessions), None)
        return True

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
        )

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
            return {
                **info,
                "ok": True,
                "action": "session_save",
                "kind": kind,
                "session": sess.id,
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
        sid = session_id or self._default_session
        if not sid or sid not in self.sessions:
            # Auto-open first session for ergonomics
            return self.open_session()
        return self.sessions[sid]

    def navigate(self, url: str, session_id: str | None = None) -> dict[str, Any]:
        sess = self.get(session_id)
        try:
            resp = sess.page.goto(url, wait_until="domcontentloaded", timeout=60_000)
            status = resp.status if resp else None
            return {
                "ok": True,
                "url": sess.page.url,
                "status": status,
                "title": sess.page.title(),
                "session": sess.id,
                "engine": "chromium",
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
        except Exception:
            sess.page.wait_for_timeout(quiet_ms)
            reason = "quiet_ms"
        ms = int((time.time() - t0) * 1000)
        return {
            "ok": True,
            "engine": "chromium",
            "session": sess.id,
            "ms": ms,
            "quiescent": True,
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
        return sess.page.evaluate(FIND_TEXT_JS, q)

    def click(self, node_id: int, session_id: str | None = None) -> dict[str, Any]:
        sess = self.get(session_id)
        # Re-stamp ids then click (same walk order as snapshot)
        sess.page.evaluate(WALKER_JS)
        result = sess.page.evaluate(CLICK_JS, node_id)
        result["session"] = sess.id
        result["url"] = sess.page.url
        result["title"] = sess.page.title()
        result["engine"] = "chromium"
        return result

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
        sess = self.get(session_id) if self.sessions or session_id else None
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
