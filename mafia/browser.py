"""Chromium session pool — engine of record for every agent op."""

from __future__ import annotations

import itertools
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from playwright.sync_api import Browser, BrowserContext, Page, Playwright, sync_playwright

from mafia.snapshot import CLICK_JS, FIND_TEXT_JS, WALKER_JS


@dataclass
class Session:
    id: str
    context: BrowserContext
    page: Page
    created_at: float = field(default_factory=time.time)


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
        for sid in list(self.sessions):
            self.close_session(sid)
        if self._browser:
            self._browser.close()
            self._browser = None
        if self._pw:
            self._pw.stop()
            self._pw = None

    def open_session(self, *, session_id: str | None = None) -> Session:
        self.start()
        assert self._browser is not None
        sid = session_id or f"s{next(self._id_counter):04d}-{uuid.uuid4().hex[:6]}"
        if sid in self.sessions:
            raise ValueError(f"session exists: {sid}")
        ctx = self._browser.new_context()
        page = ctx.new_page()
        sess = Session(id=sid, context=ctx, page=page)
        self.sessions[sid] = sess
        self._default_session = sid
        return sess

    def close_session(self, session_id: str) -> bool:
        sess = self.sessions.pop(session_id, None)
        if not sess:
            return False
        try:
            sess.context.close()
        except Exception:
            pass
        if self._default_session == session_id:
            self._default_session = next(iter(self.sessions), None)
        return True

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
