"""Site learning — remember what worked so the next surf is easier.

Per-origin memory:
  landmarks  — text/selectors that successfully found or activated UI
  recipes    — short successful op sequences (find → click, etc.)
  notes      — agent-written tips for a site
  paths      — useful URLs visited on this origin

Scores rise on reuse success and fall on failure. Secrets never stored.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

_REPO_ROOT = Path(__file__).resolve().parents[1]
_lock = threading.Lock()

_MAX_LANDMARKS = 80
_MAX_RECIPES = 40
_MAX_NOTES = 40
_MAX_PATHS = 40


def learn_dir() -> Path:
    env = os.environ.get("MAFIA_LEARN_DIR")
    if env:
        p = Path(env).expanduser()
    else:
        p = _REPO_ROOT / "logs" / "learn"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _now() -> float:
    return time.time()


def _iso(ts: float | None = None) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts or _now()))


def origin_key(url: str | None) -> str | None:
    if not url:
        return None
    u = url.strip()
    if not u or u in ("about:blank", "chrome://newtab/"):
        return None
    try:
        p = urlparse(u)
    except Exception:
        return None
    if p.scheme == "file":
        name = Path(p.path or "").name or "file"
        safe = re.sub(r"[^A-Za-z0-9._-]+", "_", name)[:80]
        return f"file:{safe}" if safe else "file"
    host = (p.hostname or "").lower()
    if not host:
        return None
    # collapse www.
    if host.startswith("www."):
        host = host[4:]
    return host


def _safe_file_key(key: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", key)[:120] or "unknown"


def site_path(key: str) -> Path:
    return learn_dir() / f"{_safe_file_key(key)}.json"


def _empty_site(key: str) -> dict[str, Any]:
    return {
        "version": 1,
        "origin": key,
        "created_at": _now(),
        "created_at_iso": _iso(),
        "updated_at": _now(),
        "updated_at_iso": _iso(),
        "landmarks": [],
        "recipes": [],
        "notes": [],
        "paths": [],
        "stats": {"hits": 0, "misses": 0},
    }


def load_site(key: str) -> dict[str, Any]:
    path = site_path(key)
    if not path.is_file():
        return _empty_site(key)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return _empty_site(key)
        for field, default in (
            ("landmarks", []),
            ("recipes", []),
            ("notes", []),
            ("paths", []),
            ("stats", {"hits": 0, "misses": 0}),
        ):
            data.setdefault(field, default)
        data["origin"] = key
        return data
    except Exception:
        return _empty_site(key)


def save_site(data: dict[str, Any]) -> None:
    key = data.get("origin") or "unknown"
    data["updated_at"] = _now()
    data["updated_at_iso"] = _iso()
    path = site_path(str(key))
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)


def list_sites() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    root = learn_dir()
    for f in sorted(root.glob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        out.append(
            {
                "origin": data.get("origin") or f.stem,
                "landmarks": len(data.get("landmarks") or []),
                "recipes": len(data.get("recipes") or []),
                "notes": len(data.get("notes") or []),
                "paths": len(data.get("paths") or []),
                "updated_at": data.get("updated_at"),
                "updated_at_iso": data.get("updated_at_iso"),
                "stats": data.get("stats") or {},
            }
        )
    out.sort(key=lambda x: float(x.get("updated_at") or 0), reverse=True)
    return out


def _bump_landmark(
    data: dict[str, Any],
    *,
    kind: str,
    value: str,
    tag: str | None = None,
    role: str | None = None,
    href: str | None = None,
    success: bool = True,
) -> dict[str, Any]:
    value = (value or "").strip()
    if not value or len(value) > 200:
        return data
    # never store password-ish
    low = value.lower()
    if any(x in low for x in ("password", "passwd", "secret", "api_key", "token=")):
        return data

    marks: list[dict[str, Any]] = list(data.get("landmarks") or [])
    found = None
    for m in marks:
        if m.get("kind") == kind and (m.get("value") or "").lower() == value.lower():
            found = m
            break
    if found is None:
        found = {
            "kind": kind,
            "value": value,
            "tag": tag,
            "role": role,
            "href": href,
            "hits": 0,
            "misses": 0,
            "score": 0,
            "created_at": _now(),
        }
        marks.append(found)
    if success:
        found["hits"] = int(found.get("hits") or 0) + 1
        found["score"] = int(found.get("score") or 0) + 1
    else:
        found["misses"] = int(found.get("misses") or 0) + 1
        found["score"] = int(found.get("score") or 0) - 1
    found["last_used"] = _now()
    found["last_used_iso"] = _iso()
    if tag:
        found["tag"] = tag
    if role:
        found["role"] = role
    if href:
        found["href"] = href
    # prune lowest score if over cap
    marks.sort(key=lambda m: (int(m.get("score") or 0), float(m.get("last_used") or 0)), reverse=True)
    data["landmarks"] = marks[:_MAX_LANDMARKS]
    return data


def _add_path(data: dict[str, Any], url: str | None, title: str | None = None) -> dict[str, Any]:
    if not url:
        return data
    paths: list[dict[str, Any]] = list(data.get("paths") or [])
    for p in paths:
        if p.get("url") == url:
            p["hits"] = int(p.get("hits") or 0) + 1
            p["last_used"] = _now()
            p["last_used_iso"] = _iso()
            if title:
                p["title"] = title
            data["paths"] = paths
            return data
    paths.insert(
        0,
        {
            "url": url,
            "title": title,
            "hits": 1,
            "last_used": _now(),
            "last_used_iso": _iso(),
        },
    )
    data["paths"] = paths[:_MAX_PATHS]
    return data


def _add_recipe(
    data: dict[str, Any],
    *,
    name: str,
    steps: list[dict[str, Any]],
) -> dict[str, Any]:
    if not steps:
        return data
    recipes: list[dict[str, Any]] = list(data.get("recipes") or [])
    # merge same name
    for r in recipes:
        if r.get("name") == name:
            r["steps"] = steps
            r["hits"] = int(r.get("hits") or 0) + 1
            r["score"] = int(r.get("score") or 0) + 1
            r["last_used"] = _now()
            r["last_used_iso"] = _iso()
            data["recipes"] = recipes
            return data
    recipes.insert(
        0,
        {
            "name": name,
            "steps": steps,
            "hits": 1,
            "score": 1,
            "created_at": _now(),
            "last_used": _now(),
            "last_used_iso": _iso(),
        },
    )
    data["recipes"] = recipes[:_MAX_RECIPES]
    return data


def remember_find(
    url: str | None,
    query: str,
    matches: list[dict[str, Any]],
) -> dict[str, Any] | None:
    key = origin_key(url)
    if not key or not query or not matches:
        return None
    with _lock:
        data = load_site(key)
        data = _bump_landmark(data, kind="text", value=query, success=True)
        # also remember best match text if different
        top = matches[0]
        t = (top.get("text") or "").strip()
        if t and t.lower() != query.lower():
            data = _bump_landmark(
                data,
                kind="text",
                value=t[:120],
                tag=top.get("tag"),
                success=True,
            )
        data = _add_path(data, url)
        stats = data.setdefault("stats", {})
        stats["hits"] = int(stats.get("hits") or 0) + 1
        save_site(data)
        return {"origin": key, "learned": "find", "query": query, "match_count": len(matches)}


def remember_click(
    url: str | None,
    *,
    text: str | None,
    tag: str | None = None,
    href: str | None = None,
    find_query: str | None = None,
) -> dict[str, Any] | None:
    key = origin_key(url)
    if not key:
        return None
    with _lock:
        data = load_site(key)
        if text:
            data = _bump_landmark(
                data, kind="click_text", value=text[:120], tag=tag, href=href, success=True
            )
        if find_query:
            data = _bump_landmark(
                data, kind="click_text", value=find_query[:120], tag=tag, success=True
            )
            # recipe: find then click
            name = f"click:{find_query[:40]}"
            data = _add_recipe(
                data,
                name=name,
                steps=[
                    {"op": "find_text", "text": find_query},
                    {"op": "click_text", "text": find_query},
                ],
            )
        elif text:
            name = f"click:{text[:40]}"
            data = _add_recipe(
                data,
                name=name,
                steps=[{"op": "click_text", "text": text[:120]}],
            )
        data = _add_path(data, url)
        stats = data.setdefault("stats", {})
        stats["hits"] = int(stats.get("hits") or 0) + 1
        save_site(data)
        return {"origin": key, "learned": "click", "text": text, "find_query": find_query}


def remember_navigate(url: str | None, title: str | None = None) -> dict[str, Any] | None:
    key = origin_key(url)
    if not key or not url:
        return None
    with _lock:
        data = load_site(key)
        data = _add_path(data, url, title)
        save_site(data)
        return {"origin": key, "learned": "navigate", "url": url}


def remember_miss(url: str | None, *, kind: str, value: str) -> None:
    key = origin_key(url)
    if not key or not value:
        return
    with _lock:
        data = load_site(key)
        data = _bump_landmark(data, kind=kind, value=value, success=False)
        stats = data.setdefault("stats", {})
        stats["misses"] = int(stats.get("misses") or 0) + 1
        save_site(data)


def add_note(url: str | None, note: str, *, origin: str | None = None) -> dict[str, Any]:
    key = origin or origin_key(url)
    if not key:
        return {"ok": False, "error": "no origin (navigate first or pass origin)", "code": "bad_args"}
    note = (note or "").strip()
    if not note:
        return {"ok": False, "error": "note required", "code": "bad_args"}
    if len(note) > 2000:
        note = note[:2000]
    with _lock:
        data = load_site(key)
        notes: list[dict[str, Any]] = list(data.get("notes") or [])
        notes.insert(
            0,
            {"text": note, "created_at": _now(), "created_at_iso": _iso()},
        )
        data["notes"] = notes[:_MAX_NOTES]
        save_site(data)
    return {"ok": True, "action": "learn_note", "origin": key, "note": note}


def recall(url: str | None = None, *, origin: str | None = None) -> dict[str, Any]:
    key = origin or origin_key(url)
    if not key:
        return {
            "ok": True,
            "origin": None,
            "landmarks": [],
            "recipes": [],
            "notes": [],
            "paths": [],
            "hint": "no origin yet — navigate first",
        }
    with _lock:
        data = load_site(key)
    landmarks = sorted(
        data.get("landmarks") or [],
        key=lambda m: (int(m.get("score") or 0), float(m.get("last_used") or 0)),
        reverse=True,
    )
    recipes = sorted(
        data.get("recipes") or [],
        key=lambda m: (int(m.get("score") or 0), float(m.get("last_used") or 0)),
        reverse=True,
    )
    return {
        "ok": True,
        "origin": key,
        "landmarks": landmarks[:30],
        "recipes": recipes[:15],
        "notes": (data.get("notes") or [])[:15],
        "paths": (data.get("paths") or [])[:15],
        "stats": data.get("stats") or {},
        "updated_at_iso": data.get("updated_at_iso"),
    }


def suggest(
    url: str | None = None,
    *,
    origin: str | None = None,
    limit: int = 8,
) -> dict[str, Any]:
    """Ranked next actions for this origin — agent reads this before exploring blind."""
    mem = recall(url, origin=origin)
    if not mem.get("origin"):
        return {**mem, "suggestions": []}
    suggestions: list[dict[str, Any]] = []
    for m in (mem.get("landmarks") or [])[:limit]:
        kind = m.get("kind") or "text"
        val = m.get("value")
        if not val:
            continue
        if kind in ("click_text", "text"):
            suggestions.append(
                {
                    "action": "learn_use" if kind == "click_text" else "find_text",
                    "text": val,
                    "score": m.get("score"),
                    "hits": m.get("hits"),
                    "tag": m.get("tag"),
                    "why": f"known {kind} on {mem['origin']}",
                }
            )
    for r in (mem.get("recipes") or [])[: max(1, limit // 2)]:
        suggestions.append(
            {
                "action": "learn_recipe",
                "name": r.get("name"),
                "steps": r.get("steps"),
                "score": r.get("score"),
                "why": "prior successful sequence",
            }
        )
    for n in (mem.get("notes") or [])[:3]:
        suggestions.append(
            {
                "action": "note",
                "text": n.get("text"),
                "why": "agent tip for this site",
            }
        )
    return {
        "ok": True,
        "origin": mem.get("origin"),
        "suggestions": suggestions[: limit + 5],
        "count": len(suggestions),
        "hint": "prefer learn_use / known text before blind snapshot thrash",
    }


def forget(
    *,
    origin: str,
    kind: str | None = None,
    value: str | None = None,
    all_memory: bool = False,
) -> dict[str, Any]:
    key = origin
    with _lock:
        if all_memory:
            path = site_path(key)
            if path.is_file():
                path.unlink()
            return {"ok": True, "action": "learn_forget", "origin": key, "cleared": "all"}
        data = load_site(key)
        if kind == "note" and value:
            data["notes"] = [
                n for n in (data.get("notes") or []) if n.get("text") != value
            ]
        elif value:
            data["landmarks"] = [
                m
                for m in (data.get("landmarks") or [])
                if not (
                    (not kind or m.get("kind") == kind)
                    and (m.get("value") or "").lower() == value.lower()
                )
            ]
            data["recipes"] = [
                r
                for r in (data.get("recipes") or [])
                if value.lower() not in (r.get("name") or "").lower()
            ]
        save_site(data)
    return {"ok": True, "action": "learn_forget", "origin": key, "kind": kind, "value": value}
