"""Knox bridge — passwords without ever printing them.

Policy (same as Chrime/Knox):
- Touch ID unlock stays Knox's boundary.
- Secrets never appear in agent JSON, logs, or stdout of the Mafia API.
- Preferred: unlock via Knox Python lib, inject into the Chromium page (browser-fill).
- Fallback: knox CLI dry-run / find for metadata only.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from typing import Any
from urllib.parse import urlparse

SECRET_SUPPRESSED = "suppressed"


def _which_knox() -> str | None:
    return os.environ.get("KNOX_BIN") or shutil.which("knox")


def query_from_url(url: str | None) -> str:
    if not url:
        return ""
    try:
        host = urlparse(url).hostname or ""
        return host.removeprefix("www.")
    except Exception:
        return ""


def find(query: str, limit: int = 10) -> dict[str, Any]:
    """Metadata-only search. Never returns password values."""
    q = (query or "").strip()
    if not q:
        return {
            "ok": False,
            "query": q,
            "matches": [],
            "error": "empty query",
            "secret_output": SECRET_SUPPRESSED,
        }
    knox = _which_knox()
    if not knox:
        return {
            "ok": False,
            "query": q,
            "matches": [],
            "error": "knox CLI not found (install knox or set KNOX_BIN)",
            "secret_output": SECRET_SUPPRESSED,
        }
    try:
        proc = subprocess.run(
            [knox, "find", q, "--limit", str(limit)],
            capture_output=True,
            text=True,
            timeout=120,
        )
    except Exception as e:
        return {
            "ok": False,
            "query": q,
            "matches": [],
            "error": str(e),
            "secret_output": SECRET_SUPPRESSED,
        }
    out = (proc.stdout or "") + "\n" + (proc.stderr or "")
    # Parse human lines carefully — never trust a password-looking field into matches.
    matches: list[dict[str, Any]] = []
    # Typical knox find: title lines; also try JSON if present
    if out.strip().startswith("{") or out.strip().startswith("["):
        try:
            data = json.loads(out.strip().splitlines()[0])
            if isinstance(data, dict) and "matches" in data:
                for m in data["matches"]:
                    matches.append(
                        {
                            "title": str(m.get("title") or "(untitled)"),
                            "login": m.get("login"),
                            "url": m.get("url"),
                            "id": m.get("id"),
                        }
                    )
            elif isinstance(data, list):
                for m in data:
                    if isinstance(m, dict):
                        matches.append(
                            {
                                "title": str(m.get("title") or "(untitled)"),
                                "login": m.get("login"),
                                "url": m.get("url"),
                                "id": m.get("id"),
                            }
                        )
        except json.JSONDecodeError:
            pass
    if not matches:
        # Fallback: scrape "title:" style lines without capturing secrets
        for line in out.splitlines():
            line = line.strip()
            if not line or "password" in line.lower() and ":" in line:
                # skip anything that looks like a secret dump
                if re.search(r"password\s*[:=]", line, re.I):
                    continue
            m = re.match(r"^-?\s*title:\s*(.+)$", line, re.I)
            if m:
                matches.append({"title": m.group(1).strip(), "login": None, "url": None, "id": None})
            m = re.match(r"^\[?(\d+)\]?\s+(.+)$", line)
            if m and "match" not in line.lower() and len(m.group(2)) < 120:
                title = m.group(2).strip()
                if title and not title.startswith("query"):
                    matches.append({"title": title, "login": None, "url": None, "id": None})
    # Dedup titles
    seen: set[str] = set()
    uniq = []
    for m in matches:
        t = m.get("title") or ""
        if t in seen:
            continue
        seen.add(t)
        uniq.append(m)
    ok = proc.returncode == 0 or len(uniq) > 0
    return {
        "ok": ok,
        "query": q,
        "matches": uniq[:limit],
        "error": None if ok else (out.strip()[-400:] or f"exit {proc.returncode}"),
        "secret_output": SECRET_SUPPRESSED,
        "match_count": len(uniq[:limit]),
    }


def unlock_field(query: str, field: str) -> tuple[str | None, str | None, str | None]:
    """Return (title, value, error). Value must never be logged by caller into API JSON."""
    field = field if field in ("login", "password", "url") else "password"
    # Prefer in-process Knox library (same store as CLI)
    try:
        from knox.cli import (  # type: ignore
            DEFAULT_BIOMETRIC_KEYCHAIN_SERVICE,
            DEFAULT_KEYCHAIN_ACCOUNT,
            DEFAULT_STORE_PATH,
            DEFAULT_TOUCH_ID_CACHE_SECONDS,
            _read_unlocked_store,
            find_secret_records,
            secret_record_field,
        )

        store = _read_unlocked_store(
            DEFAULT_STORE_PATH,
            DEFAULT_BIOMETRIC_KEYCHAIN_SERVICE,
            DEFAULT_KEYCHAIN_ACCOUNT,
            DEFAULT_TOUCH_ID_CACHE_SECONDS,
            force_touchid=False,
        )
        recs = find_secret_records(store, query)
        if not recs:
            return None, None, f"no Knox records for {query!r}"
        rec = recs[0]
        title = str(rec.get("title") or "(untitled)")
        val = secret_record_field(rec, field) or rec.get(field)
        if not val:
            return title, None, f"record has no field {field}"
        return title, str(val), None
    except Exception as e:
        return None, None, f"knox unlock failed: {e}"


def dry_run_use(query: str, field: str = "password") -> dict[str, Any]:
    """Prove match without exposing secret."""
    knox = _which_knox()
    if not knox:
        return {
            "ok": False,
            "error": "knox not found",
            "secret_output": SECRET_SUPPRESSED,
        }
    try:
        proc = subprocess.run(
            [knox, "use", query, "--field", field, "--dry-run"],
            capture_output=True,
            text=True,
            timeout=120,
        )
        out = (proc.stdout or "") + (proc.stderr or "")
        # Redact anything after password-like tokens
        redacted = re.sub(
            r"(?i)(password|secret|token)\s*[:=]\s*\S+",
            r"\1: [suppressed]",
            out,
        )
        return {
            "ok": proc.returncode == 0,
            "query": query,
            "field": field,
            "action": "dry-run",
            "detail": redacted[-500:],
            "error": None if proc.returncode == 0 else redacted[-300:],
            "secret_output": SECRET_SUPPRESSED,
        }
    except Exception as e:
        return {
            "ok": False,
            "error": str(e),
            "secret_output": SECRET_SUPPRESSED,
        }
