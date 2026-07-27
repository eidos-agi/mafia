"""Append-only usage ledger + work index so agents can reboot prior work.

Every op is recorded (secrets stripped). Work units roll up by profile / save /
label so `session_recent` + `session_reboot` recover what was in flight.
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
_lock = threading.Lock()

# Keys never written to the ledger (request or response).
_SECRET_KEYS = frozenset(
    {
        "text",
        "value",
        "password",
        "pass",
        "secret",
        "token",
        "cookie",
        "storage_state",
        "js",
        "script",
        "expr",
    }
)

# Ops that are noise at high volume — still counted on work unit, logged thin.
_THIN_OPS = frozenset({"ping", "hello", "help", "ops", "status", "session_list"})


def ledger_dir() -> Path:
    env = os.environ.get("MAFIA_LEDGER_DIR")
    if env:
        p = Path(env).expanduser()
    else:
        p = _REPO_ROOT / "logs" / "ledger"
    p.mkdir(parents=True, exist_ok=True)
    return p


def events_path() -> Path:
    return ledger_dir() / "events.jsonl"


def work_index_path() -> Path:
    return ledger_dir() / "work.json"


def _now() -> float:
    return time.time()


def _iso(ts: float | None = None) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts or _now()))


def _scrub_url(url: str | None) -> str | None:
    """Strip OAuth/token query fragments from URLs before logging."""
    if not url or not isinstance(url, str):
        return url
    import re
    from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

    try:
        p = urlparse(url)
    except Exception:
        return url[:200] + "…" if len(url) > 200 else url
    # fragment often holds #access_token=
    frag = p.fragment or ""
    if any(x in frag.lower() for x in ("token", "access_", "id_token", "code=")):
        frag = "[redacted]"
    q = parse_qs(p.query, keep_blank_values=True)
    dirty = (
        "code",
        "token",
        "access_token",
        "refresh_token",
        "id_token",
        "client_secret",
        "password",
        "session_state",
    )
    changed = False
    for k in list(q.keys()):
        if k.lower() in dirty or "token" in k.lower() or "secret" in k.lower():
            q[k] = ["[redacted]"]
            changed = True
    query = urlencode({k: v[0] if len(v) == 1 else v for k, v in q.items()}, doseq=True) if q else ""
    if changed or frag == "[redacted]":
        return urlunparse((p.scheme, p.netloc, p.path, p.params, query, frag))
    # still drop bare secrets in path-ish strings
    if re.search(r"(access_token|refresh_token|id_token)=", url, re.I):
        return re.sub(
            r"(access_token|refresh_token|id_token|code)=[^&\s#]+",
            r"\1=[redacted]",
            url,
            flags=re.I,
        )
    return url


def _scrub(obj: Any, *, depth: int = 0) -> Any:
    if depth > 4:
        return "…"
    if isinstance(obj, dict):
        out: dict[str, Any] = {}
        for k, v in obj.items():
            lk = str(k).lower()
            if lk in _SECRET_KEYS or "password" in lk or "secret" in lk:
                out[k] = "[suppressed]"
            elif lk in ("url", "href", "restored_url") and isinstance(v, str):
                out[k] = _scrub_url(v)
            elif lk in ("nodes", "matches", "links", "text") and isinstance(v, (list, str)):
                if isinstance(v, list):
                    out[k] = f"[{len(v)} items]"
                else:
                    out[k] = f"[{len(v)} chars]"
            else:
                out[k] = _scrub(v, depth=depth + 1)
        return out
    if isinstance(obj, list):
        if len(obj) > 8:
            return [_scrub(x, depth=depth + 1) for x in obj[:5]] + [f"…+{len(obj)-5}"]
        return [_scrub(x, depth=depth + 1) for x in obj]
    if isinstance(obj, str) and len(obj) > 240:
        return obj[:200] + "…"
    return obj


def _load_work() -> dict[str, Any]:
    path = work_index_path()
    if not path.is_file():
        return {"version": 1, "work": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {"version": 1, "work": {}}
        data.setdefault("version", 1)
        data.setdefault("work", {})
        return data
    except Exception:
        return {"version": 1, "work": {}}


def _save_work(data: dict[str, Any]) -> None:
    path = work_index_path()
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)


def work_key(
    *,
    profile: str | None = None,
    save: str | None = None,
    label: str | None = None,
    session_id: str | None = None,
) -> str | None:
    for candidate in (profile, save, label):
        if candidate and str(candidate).strip():
            return str(candidate).strip()
    if session_id:
        # dash not colon — must be a valid save jar name (_safe_name)
        return f"live-{session_id}"
    return None


def resume_hint(
    *,
    profile: str | None = None,
    save: str | None = None,
    label: str | None = None,
) -> dict[str, Any] | None:
    if profile:
        return {"kind": "profile", "name": profile}
    if save:
        return {"kind": "save", "name": save}
    if label:
        return {"kind": "save", "name": label}
    return None


def touch_work(
    key: str,
    *,
    op: str,
    session_id: str | None = None,
    url: str | None = None,
    title: str | None = None,
    profile: str | None = None,
    save: str | None = None,
    label: str | None = None,
    ok: bool | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    """Update work index entry for key. Returns the entry."""
    with _lock:
        data = _load_work()
        work = data["work"]
        entry = work.get(key) or {
            "key": key,
            "created_at": _now(),
            "created_at_iso": _iso(),
            "op_count": 0,
        }
        entry["key"] = key
        entry["last_used"] = _now()
        entry["last_used_iso"] = _iso()
        entry["last_op"] = op
        entry["op_count"] = int(entry.get("op_count") or 0) + 1
        if session_id:
            entry["last_session_id"] = session_id
        if url is not None:
            entry["last_url"] = url
        if title is not None:
            entry["last_title"] = title
        if profile:
            entry["profile"] = profile
        if save:
            entry["save"] = save
        if label:
            entry["label"] = label
        if ok is not None:
            entry["last_ok"] = ok
        if note:
            entry["note"] = note
        # Prefer durable resume target
        entry["resume"] = resume_hint(
            profile=entry.get("profile"),
            save=entry.get("save"),
            label=entry.get("label"),
        ) or entry.get("resume")
        # kind for agents
        if entry.get("profile"):
            entry["kind"] = "profile"
        elif entry.get("save") or entry.get("label"):
            entry["kind"] = "save"
        else:
            entry["kind"] = "ephemeral"
        work[key] = entry
        data["work"] = work
        _save_work(data)
        return dict(entry)


def append_event(event: dict[str, Any]) -> dict[str, Any]:
    """Append one scrubbed event to events.jsonl."""
    row = {
        "ts": _now(),
        "ts_iso": _iso(),
        **event,
    }
    line = json.dumps(row, ensure_ascii=False)
    with _lock:
        with events_path().open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    return row


def record_op(
    *,
    op: str,
    request: dict[str, Any] | None = None,
    response: dict[str, Any] | None = None,
    session_id: str | None = None,
    work: str | None = None,
    profile: str | None = None,
    save: str | None = None,
    label: str | None = None,
    url: str | None = None,
    title: str | None = None,
    ms: float | None = None,
) -> dict[str, Any]:
    """Log one API use and update work index when we have a key."""
    req = request or {}
    resp = response or {}
    ok = resp.get("ok") if "ok" in resp else None
    sid = session_id or resp.get("session") or req.get("session")
    if isinstance(sid, str) and not sid:
        sid = None

    # Prefer durable names from response/request
    prof = profile or resp.get("profile") or (
        req.get("profile") if isinstance(req.get("profile"), str) else None
    )
    sav = save or (
        resp.get("name")
        if resp.get("action") in ("session_save", "session_load")
        and resp.get("kind") == "save"
        else None
    )
    if not sav and resp.get("kind") == "save" and resp.get("name"):
        sav = resp.get("name")
    lab = label or req.get("label") or resp.get("label")

    key = work or work_key(profile=prof, save=sav, label=lab, session_id=sid)

    thin = op in _THIN_OPS
    raw_url = url or resp.get("url") or req.get("url")
    event: dict[str, Any] = {
        "op": op,
        "ok": ok,
        "session": sid,
        "work": key,
        "profile": prof,
        "save": sav,
        "label": lab,
        "url": _scrub_url(raw_url) if isinstance(raw_url, str) else raw_url,
        "title": title or resp.get("title"),
        "ms": ms,
    }
    if not thin:
        event["request"] = _scrub(
            {
                k: v
                for k, v in req.items()
                if k not in ("op",)
            }
        )
        # compact response (no full snapshot nodes)
        event["response"] = _scrub(
            {
                k: v
                for k, v in resp.items()
                if k
                not in (
                    "nodes",
                    "matches",
                    "links",
                    "text",
                    "result",
                )
            }
        )
        if "result" in resp:
            r = resp.get("result")
            event["response"]["result_type"] = type(r).__name__
        if "node_count" in resp:
            event["response"]["node_count"] = resp.get("node_count")
        if "chars" in resp:
            event["response"]["chars"] = resp.get("chars")

    row = append_event(event)

    if key and op not in ("session_history", "session_recent", "session_saves", "session_profiles"):
        touch_work(
            key,
            op=op,
            session_id=sid if isinstance(sid, str) else None,
            url=event.get("url"),
            title=event.get("title"),
            profile=prof if isinstance(prof, str) else None,
            save=sav if isinstance(sav, str) else None,
            label=lab if isinstance(lab, str) else None,
            ok=bool(ok) if ok is not None else None,
        )
    return row


def list_recent(limit: int = 20) -> list[dict[str, Any]]:
    with _lock:
        data = _load_work()
    items = list(data.get("work", {}).values())
    items.sort(key=lambda e: float(e.get("last_used") or 0), reverse=True)
    return items[: max(1, min(limit, 200))]


def get_work(key: str) -> dict[str, Any] | None:
    with _lock:
        data = _load_work()
    entry = data.get("work", {}).get(key)
    return dict(entry) if entry else None


def history(
    *,
    work: str | None = None,
    session: str | None = None,
    op: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Read recent events from JSONL (tail scan)."""
    path = events_path()
    if not path.is_file():
        return []
    limit = max(1, min(int(limit), 500))
    # Read last ~2MB or whole file if small
    try:
        size = path.stat().st_size
        with path.open("rb") as f:
            if size > 2_000_000:
                f.seek(max(0, size - 2_000_000))
                f.readline()  # drop partial
            raw = f.read().decode("utf-8", errors="replace")
    except Exception:
        return []

    rows: list[dict[str, Any]] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if work and row.get("work") != work and row.get("profile") != work and row.get("save") != work and row.get("label") != work:
            continue
        if session and row.get("session") != session:
            continue
        if op and row.get("op") != op:
            continue
        rows.append(row)
    return rows[-limit:]
