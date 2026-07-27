"""Hancock bridge — human must sign before consequential Mafia actions.

Rule: STILL_PENDING / QUEUED / DENIED is not go.
Only APPROVED_AND_RAN / AUTO_APPROVED_AND_RAN (or exit 0 from `hancock wait`) means proceed.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from typing import Any


def _which() -> str | None:
    return os.environ.get("HANCOCK_BIN") or shutil.which("hancock")


def request(
    action: str,
    why: str,
    *,
    risk: str = "high",
    wait: bool = False,
    timeout: int = 600,
    detail: dict[str, Any] | None = None,
) -> dict[str, Any]:
    bin_ = _which()
    if not bin_:
        return {
            "ok": False,
            "action": "hancock_request",
            "outcome": "HANCOCK_MISSING",
            "error": "hancock CLI not found (install or set HANCOCK_BIN)",
            "english": "Cannot request human signature — hancock not installed.",
        }

    # Represent the intended Mafia action as a gated command string for the tray.
    cmd = f"mafia:{action}"
    if detail:
        # keep short, no secrets
        bits = [f"{k}={v}" for k, v in list(detail.items())[:6] if v is not None]
        if bits:
            cmd += " " + " ".join(bits)

    try:
        proc = subprocess.run(
            [
                bin_,
                "add",
                cmd,
                "-why",
                why or f"Mafia agent wants: {action}",
                "-risk",
                risk,
                "--source",
                "mafia",
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
    except Exception as e:
        return {
            "ok": False,
            "action": "hancock_request",
            "outcome": "ERROR",
            "error": str(e),
            "english": f"hancock add failed: {e}",
        }

    raw = (proc.stdout or "") + "\n" + (proc.stderr or "")
    hid = None
    m = re.search(r"(req_[a-zA-Z0-9_]+)", raw)
    if m:
        hid = m.group(1)

    outcome = "QUEUED"
    if "already dead-ended" in raw.lower() or "aporia" in raw.lower():
        outcome = "HELD_APORIA"
    if proc.returncode not in (0, 3):  # 3 often = needs sign
        # still may have queued
        pass

    result: dict[str, Any] = {
        "ok": True,
        "action": "hancock_request",
        "outcome": outcome,
        "hancock_id": hid,
        "risk": risk,
        "mafia_action": action,
        "english": f"Queued Hancock request for `{action}` (risk={risk}). "
        f"STILL_PENDING is NOT approval. Use hancock_wait.",
        "raw_tail": raw[-600:],
        "secret_output": "suppressed",
    }

    if wait and hid:
        w = wait_for(hid, timeout=timeout)
        result.update(w)
        result["action"] = "hancock_request"
        result["hancock_id"] = hid
    return result


def wait_for(hancock_id: str, timeout: int = 600) -> dict[str, Any]:
    bin_ = _which()
    if not bin_:
        return {
            "ok": False,
            "outcome": "HANCOCK_MISSING",
            "error": "hancock not found",
            "english": "Cannot wait — hancock missing.",
        }
    if not hancock_id:
        return {
            "ok": False,
            "outcome": "bad_args",
            "error": "id required",
            "english": "hancock_wait needs id",
        }
    try:
        proc = subprocess.run(
            [bin_, "wait", hancock_id, "--timeout", str(timeout)],
            capture_output=True,
            text=True,
            timeout=timeout + 30,
        )
    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "outcome": "STILL_PENDING",
            "hancock_id": hancock_id,
            "english": "Timed out waiting for human signature. NOT approved.",
            "secret_output": "suppressed",
        }
    except Exception as e:
        return {
            "ok": False,
            "outcome": "ERROR",
            "error": str(e),
            "english": f"hancock wait failed: {e}",
        }

    raw = (proc.stdout or "") + "\n" + (proc.stderr or "")
    if proc.returncode == 0:
        return {
            "ok": True,
            "outcome": "APPROVED_AND_RAN",
            "hancock_id": hancock_id,
            "english": "Human signed; hancock wait exit 0.",
            "raw_tail": raw[-400:],
            "secret_output": "suppressed",
        }
    # Non-zero: still pending, denied, or failed run
    outcome = "STILL_PENDING"
    low = raw.lower()
    if "den" in low:
        outcome = "DENIED"
    if "fail" in low:
        outcome = "FAILED"
    return {
        "ok": False,
        "outcome": outcome,
        "hancock_id": hancock_id,
        "english": f"Not go (outcome={outcome}). Do not proceed as if approved.",
        "raw_tail": raw[-400:],
        "secret_output": "suppressed",
    }


def pending() -> dict[str, Any]:
    bin_ = _which()
    if not bin_:
        return {
            "ok": False,
            "action": "hancock_pending",
            "error": "hancock not found",
            "english": "No hancock CLI.",
            "items": [],
        }
    try:
        proc = subprocess.run(
            [bin_, "list"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        raw = (proc.stdout or "") + (proc.stderr or "")
        return {
            "ok": True,
            "action": "hancock_pending",
            "english": "Pending Hancock tray (text).",
            "detail": raw[-2000:],
            "secret_output": "suppressed",
        }
    except Exception as e:
        return {
            "ok": False,
            "action": "hancock_pending",
            "error": str(e),
            "english": f"list failed: {e}",
            "items": [],
        }
