"""On-disk session saves and named profiles (cookies/storage + URL).

Secrets never live here as Knox material — only browser storage_state
(cookies, localStorage) which agents need for reloadability.
"""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any

# Default under repo logs/; override with MAFIA_SESSIONS_DIR / MAFIA_PROFILES_DIR
_REPO_ROOT = Path(__file__).resolve().parents[1]


def _safe_name(name: str) -> str:
    n = (name or "").strip()
    if not n:
        raise ValueError("name required")
    # allow alnum, dash, underscore, dot — no path traversal
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", n):
        raise ValueError(
            f"invalid name {name!r}: use [A-Za-z0-9._-], start alnum, max 128"
        )
    return n


def sessions_dir() -> Path:
    env = os.environ.get("MAFIA_SESSIONS_DIR")
    if env:
        p = Path(env).expanduser()
    else:
        p = _REPO_ROOT / "logs" / "sessions"
    p.mkdir(parents=True, exist_ok=True)
    return p


def profiles_dir() -> Path:
    env = os.environ.get("MAFIA_PROFILES_DIR")
    if env:
        p = Path(env).expanduser()
    else:
        p = _REPO_ROOT / "logs" / "profiles"
    p.mkdir(parents=True, exist_ok=True)
    return p


def save_path(name: str) -> Path:
    return sessions_dir() / _safe_name(name)


def profile_path(name: str) -> Path:
    return profiles_dir() / _safe_name(name)


def write_bundle(
    dir_path: Path,
    *,
    storage_state: dict[str, Any],
    url: str | None,
    title: str | None = None,
    session_id: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    dir_path.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(dir_path, 0o700)
    except OSError:
        pass
    state_path = dir_path / "storage_state.json"
    meta_path = dir_path / "meta.json"
    state_path.write_text(json.dumps(storage_state, indent=2), encoding="utf-8")
    try:
        os.chmod(state_path, 0o600)
    except OSError:
        pass
    meta: dict[str, Any] = {
        "name": dir_path.name,
        "url": url,
        "title": title,
        "session_id": session_id,
        "saved_at": time.time(),
        "saved_at_iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "kind": "mafia_session_bundle",
        "version": 1,
    }
    if extra:
        meta["extra"] = extra
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    try:
        os.chmod(meta_path, 0o600)
    except OSError:
        pass
    return {
        "ok": True,
        "path": str(dir_path),
        "name": dir_path.name,
        "url": url,
        "title": title,
        "saved_at": meta["saved_at"],
        "storage_state_path": str(state_path),
    }


def read_bundle(dir_path: Path) -> tuple[dict[str, Any] | None, dict[str, Any], str | None]:
    """Returns (storage_state, meta, error)."""
    if not dir_path.is_dir():
        return None, {}, f"no bundle at {dir_path}"
    state_path = dir_path / "storage_state.json"
    meta_path = dir_path / "meta.json"
    if not state_path.is_file():
        return None, {}, f"missing storage_state.json in {dir_path}"
    try:
        storage_state = json.loads(state_path.read_text(encoding="utf-8"))
    except Exception as e:
        return None, {}, f"bad storage_state: {e}"
    meta: dict[str, Any] = {}
    if meta_path.is_file():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            meta = {}
    return storage_state, meta, None


def list_bundles(root: Path) -> list[dict[str, Any]]:
    if not root.is_dir():
        return []
    out: list[dict[str, Any]] = []
    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        if not (child / "storage_state.json").is_file():
            continue
        _, meta, err = read_bundle(child)
        if err:
            out.append({"name": child.name, "path": str(child), "ok": False, "error": err})
            continue
        out.append(
            {
                "name": child.name,
                "path": str(child),
                "ok": True,
                "url": meta.get("url"),
                "title": meta.get("title"),
                "saved_at": meta.get("saved_at"),
                "saved_at_iso": meta.get("saved_at_iso"),
                "session_id": meta.get("session_id"),
            }
        )
    return out


def delete_bundle(dir_path: Path) -> bool:
    if not dir_path.is_dir():
        return False
    for f in dir_path.iterdir():
        if f.is_file():
            f.unlink()
    try:
        dir_path.rmdir()
    except OSError:
        return False
    return True
