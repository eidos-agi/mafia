"""Portable / USB-like display picker (brand-agnostic).

Primary class signal: physical diagonal from EDID (CGDisplayScreenSize) —
external panels ~12.5–18.5\" with 16:9/16:10 aspect are travel-class.
Soft boost: USB-C DP / DisplayLink / DP→DP without HDMI branch (IOKit).

Settings live under ``~/eidos/<app>/settings.json`` (preferred_display).
On boot, if nothing is stored, we *suggest* the best travel-class display,
print it, and persist it so the next boot uses the stored preference.

No LLM. Works for unknown future brands that report honest EDID size.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

# Travel-class physical diagonal (inches) from EDID — brand-agnostic.
TRAVEL_DIAG_MIN = 12.5
TRAVEL_DIAG_MAX = 18.5
# 16:9 … 16:10; kill ultrawide (≥ ~2.0).
ASPECT_MIN = 1.50
ASPECT_MAX = 1.90

SETTINGS_KEY = "preferred_display"


@dataclass
class DisplayInfo:
    cg_id: int
    name: str
    builtin: bool
    main: bool
    origin_x: float
    origin_y: float
    width: float  # points (UI)
    height: float
    pixel_w: int
    pixel_h: int
    diagonal_in: float
    aspect: float
    ppi: float | None
    vendor_id: str | None = None
    product_id: str | None = None
    serial: str | None = None
    persistent_id: str | None = None
    transport: str | None = None  # e.g. "DP->DP", "DP->HDMI"
    usbish: float = 0.0
    travel_score: float | None = None
    virtual: bool = False

    @property
    def online_key(self) -> str:
        if self.vendor_id and self.product_id:
            return f"vp:{self.vendor_id}:{self.product_id}"
        if self.name:
            return f"name:{self.name}"
        return f"cg:{self.cg_id}"


@dataclass
class Placement:
    """Where to open a headed window."""

    display: DisplayInfo
    reason: str  # stored | suggested | env
    source: str  # auto_travel | pin | env
    settings_path: Path | None = None
    window_x: int = 0
    window_y: int = 0
    window_w: int = 1280
    window_h: int = 800
    notes: list[str] = field(default_factory=list)

    def chrome_args(self) -> list[str]:
        return [
            f"--window-position={self.window_x},{self.window_y}",
            f"--window-size={self.window_w},{self.window_h}",
        ]

    def as_dict(self) -> dict[str, Any]:
        d = asdict(self.display)
        return {
            "reason": self.reason,
            "source": self.source,
            "settings_path": str(self.settings_path) if self.settings_path else None,
            "window": {
                "x": self.window_x,
                "y": self.window_y,
                "w": self.window_w,
                "h": self.window_h,
            },
            "display": d,
            "chrome_args": self.chrome_args(),
            "notes": self.notes,
        }


def eidos_app_dir(app: str) -> Path:
    override = os.environ.get(f"{app.upper()}_EIDOS_DIR") or os.environ.get("EIDOS_APP_DIR")
    if override:
        return Path(override).expanduser()
    return Path.home() / "eidos" / app


def settings_path(app: str) -> Path:
    return eidos_app_dir(app) / "settings.json"


def load_settings(app: str) -> dict[str, Any]:
    path = settings_path(app)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_settings(app: str, data: dict[str, Any]) -> Path:
    path = settings_path(app)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def preferred_from_settings(app: str) -> dict[str, Any] | None:
    pref = load_settings(app).get(SETTINGS_KEY)
    return pref if isinstance(pref, dict) and pref else None


def _list_displays_cg() -> list[DisplayInfo]:
    """Enumerate active displays via CoreGraphics (macOS)."""
    import ctypes
    import ctypes.util

    cg_path = ctypes.util.find_library("CoreGraphics")
    cf_path = ctypes.util.find_library("CoreFoundation")
    if not cg_path or not cf_path:
        return []
    cg = ctypes.CDLL(cg_path)
    cf = ctypes.CDLL(cf_path)

    CGDirectDisplayID = ctypes.c_uint32
    CGDisplayCount = ctypes.c_uint32

    class CGSize(ctypes.Structure):
        _fields_ = [("width", ctypes.c_double), ("height", ctypes.c_double)]

    class CGRect(ctypes.Structure):
        _fields_ = [
            ("x", ctypes.c_double),
            ("y", ctypes.c_double),
            ("w", ctypes.c_double),
            ("h", ctypes.c_double),
        ]

    cg.CGGetActiveDisplayList.argtypes = [
        CGDisplayCount,
        ctypes.POINTER(CGDirectDisplayID),
        ctypes.POINTER(CGDisplayCount),
    ]
    cg.CGGetActiveDisplayList.restype = ctypes.c_int32
    cg.CGDisplayIsBuiltin.argtypes = [CGDirectDisplayID]
    cg.CGDisplayIsBuiltin.restype = ctypes.c_bool
    cg.CGDisplayIsMain.argtypes = [CGDirectDisplayID]
    cg.CGDisplayIsMain.restype = ctypes.c_bool
    cg.CGDisplayScreenSize.argtypes = [CGDirectDisplayID]
    cg.CGDisplayScreenSize.restype = CGSize
    cg.CGDisplayBounds.argtypes = [CGDirectDisplayID]
    cg.CGDisplayBounds.restype = CGRect
    cg.CGDisplayCopyDisplayMode.argtypes = [CGDirectDisplayID]
    cg.CGDisplayCopyDisplayMode.restype = ctypes.c_void_p
    cg.CGDisplayModeGetPixelWidth.argtypes = [ctypes.c_void_p]
    cg.CGDisplayModeGetPixelWidth.restype = ctypes.c_size_t
    cg.CGDisplayModeGetPixelHeight.argtypes = [ctypes.c_void_p]
    cg.CGDisplayModeGetPixelHeight.restype = ctypes.c_size_t
    cf.CFRelease.argtypes = [ctypes.c_void_p]

    max_d = 16
    ids = (CGDirectDisplayID * max_d)()
    count = CGDisplayCount()
    if cg.CGGetActiveDisplayList(max_d, ids, ctypes.byref(count)) != 0:
        return []

    out: list[DisplayInfo] = []
    for i in range(count.value):
        did = int(ids[i])
        size = cg.CGDisplayScreenSize(did)
        bounds = cg.CGDisplayBounds(did)
        mode = cg.CGDisplayCopyDisplayMode(did)
        pw = ph = 0
        if mode:
            pw = int(cg.CGDisplayModeGetPixelWidth(mode))
            ph = int(cg.CGDisplayModeGetPixelHeight(mode))
            cf.CFRelease(mode)
        diag_mm = math.hypot(size.width, size.height)
        diag_in = diag_mm / 25.4 if diag_mm else 0.0
        ppi = None
        if size.width and size.height and pw and ph and diag_in:
            ppi = math.hypot(pw, ph) / diag_in
        aspect = (pw / ph) if ph else (bounds.w / bounds.h if bounds.h else 0.0)
        out.append(
            DisplayInfo(
                cg_id=did,
                name="",  # filled from SPDisplays
                builtin=bool(cg.CGDisplayIsBuiltin(did)),
                main=bool(cg.CGDisplayIsMain(did)),
                origin_x=float(bounds.x),
                origin_y=float(bounds.y),
                width=float(bounds.w),
                height=float(bounds.h),
                pixel_w=pw,
                pixel_h=ph,
                diagonal_in=round(diag_in, 2),
                aspect=round(aspect, 3) if aspect else 0.0,
                ppi=round(ppi, 1) if ppi else None,
            )
        )
    return out


def _enrich_spdisplays(displays: list[DisplayInfo]) -> None:
    """Attach product names + vendor/product ids from system_profiler."""
    try:
        import plistlib

        raw = subprocess.check_output(
            ["system_profiler", "SPDisplaysDataType", "-xml"],
            stderr=subprocess.DEVNULL,
        )
        data = plistlib.loads(raw)
    except Exception:
        return

    by_id: dict[int, dict[str, Any]] = {}

    def walk(obj: Any) -> None:
        if isinstance(obj, dict):
            did = obj.get("_spdisplays_displayID")
            if did is not None:
                try:
                    by_id[int(str(did), 0) if isinstance(did, str) else int(did)] = obj
                except Exception:
                    pass
            for v in obj.values():
                walk(v)
        elif isinstance(obj, list):
            for x in obj:
                walk(x)

    walk(data)

    for d in displays:
        node = by_id.get(d.cg_id)
        if not node:
            continue
        name = node.get("_name")
        if isinstance(name, str) and name:
            d.name = name
        if node.get("spdisplays_connection_type") == "spdisplays_internal":
            d.builtin = True
        vid = node.get("_spdisplays_display-vendor-id")
        pid = node.get("_spdisplays_display-product-id")
        ser = node.get("_spdisplays_display-serial-number")
        if vid is not None:
            d.vendor_id = str(vid).lower()
        if pid is not None:
            d.product_id = str(pid).lower()
        if ser is not None:
            d.serial = str(ser)


def _enrich_displayplacer(displays: list[DisplayInfo]) -> None:
    """Stable persistent UUID when displayplacer is installed."""
    try:
        out = subprocess.check_output(["displayplacer", "list"], text=True, stderr=subprocess.DEVNULL)
    except Exception:
        return
    # Blocks start with Persistent screen id
    blocks = re.split(r"\n(?=Persistent screen id:)", out)
    # Map contextual id -> persistent
    ctx_map: dict[int, str] = {}
    for b in blocks:
        pid = re.search(r"Persistent screen id:\s*(\S+)", b)
        cid = re.search(r"Contextual screen id:\s*(\S+)", b)
        if pid and cid:
            try:
                ctx_map[int(cid.group(1))] = pid.group(1)
            except ValueError:
                pass
    for d in displays:
        if d.cg_id in ctx_map:
            d.persistent_id = ctx_map[d.cg_id]


def _enrich_usbish(displays: list[DisplayInfo]) -> None:
    """Soft USB / USB-C / DisplayLink signals from IOKit + USB tree."""
    displaylink = False
    try:
        usb = subprocess.check_output(
            ["system_profiler", "SPUSBDataType"],
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=8,
        )
        if re.search(r"(?i)displaylink|usb.?graphics|display\s*adapter", usb):
            displaylink = True
    except Exception:
        pass

    transports: dict[str, str] = {}
    try:
        ioreg = subprocess.check_output(
            ["ioreg", "-lw0"],
            text=True,
            errors="replace",
            timeout=12,
        )
        # ProductName + nearby Transport
        for m in re.finditer(
            r'"ProductName"\s*=\s*"([^"]+)".{0,800}?"Transport"\s*=\s*\{([^}]+)\}',
            ioreg,
            flags=re.DOTALL,
        ):
            name, tr = m.group(1), m.group(2)
            up = re.search(r'Upstream"="(\w+)"', tr)
            down = re.search(r'Downstream"="(\w+)"', tr)
            if up and down:
                transports[name] = f"{up.group(1)}->{down.group(1)}"
        # Also reverse order variants
        for m in re.finditer(
            r'"Transport"\s*=\s*\{([^}]+)\}.{0,800}?"ProductName"\s*=\s*"([^"]+)"',
            ioreg,
            flags=re.DOTALL,
        ):
            tr, name = m.group(1), m.group(2)
            if name in transports:
                continue
            up = re.search(r'Upstream"="(\w+)"', tr)
            down = re.search(r'Downstream"="(\w+)"', tr)
            if up and down:
                transports[name] = f"{up.group(1)}->{down.group(1)}"
        has_usbc_dp = bool(re.search(r"Port-USB-C@\d+/DisplayPort", ioreg))
        has_hdmi_branch = bool(re.search(r'BranchDeviceID"\s*=\s*"cHDMIb"', ioreg))
    except Exception:
        has_usbc_dp = False
        has_hdmi_branch = False

    for d in displays:
        if d.builtin:
            d.usbish = 0.0
            continue
        score = 0.0
        tr = transports.get(d.name) if d.name else None
        if tr:
            d.transport = tr
            if tr.upper() == "DP->HDMI":
                score -= 15.0  # adapter / dock HDMI conversion
            elif tr.upper() == "DP->DP":
                score += 8.0
        if displaylink and not d.builtin:
            score += 25.0
        if has_usbc_dp and d.diagonal_in and TRAVEL_DIAG_MIN <= d.diagonal_in <= TRAVEL_DIAG_MAX:
            score += 6.0
        if has_hdmi_branch and d.transport and "HDMI" in d.transport.upper():
            score -= 5.0
        # Cheap portables often lack serial
        if d.serial in (None, "", "0"):
            score += 3.0
        d.usbish = score


def list_displays() -> list[DisplayInfo]:
    """All active displays with enrichment."""
    if sys.platform != "darwin":
        return []
    displays = _list_displays_cg()
    if not displays:
        return []
    _enrich_spdisplays(displays)
    _enrich_displayplacer(displays)
    _enrich_usbish(displays)
    for d in displays:
        if not d.name:
            d.name = "Built-in" if d.builtin else f"Display-{d.cg_id}"
        d.travel_score = travel_score(d)
    return displays


def travel_score(d: DisplayInfo) -> float | None:
    """Higher = more portable-like. None = not travel-class."""
    if d.builtin or d.virtual:
        return None
    if not (TRAVEL_DIAG_MIN <= d.diagonal_in <= TRAVEL_DIAG_MAX):
        return None
    if d.aspect and not (ASPECT_MIN <= d.aspect <= ASPECT_MAX):
        return None
    # Prefer smaller in-band; USB soft boost secondary.
    size_pts = TRAVEL_DIAG_MAX - d.diagonal_in  # 0..~6
    score = 40.0 + size_pts * 5.0 + float(d.usbish or 0.0)
    if not d.main:
        score += 2.0
    # Mild preference for FHD-class pixel modes (common on travel panels)
    if d.pixel_w and d.pixel_h:
        if (d.pixel_w, d.pixel_h) in ((1920, 1080), (1920, 1200), (2560, 1440), (2560, 1600)):
            score += 4.0
    return score


def pick_portable(displays: list[DisplayInfo] | None = None) -> DisplayInfo | None:
    displays = displays if displays is not None else list_displays()
    ranked = [(d.travel_score, d) for d in displays if d.travel_score is not None]
    if not ranked:
        return None
    ranked.sort(key=lambda x: (-(x[0] or 0.0), x[1].diagonal_in))
    return ranked[0][1]


def match_preferred(pref: dict[str, Any], displays: list[DisplayInfo]) -> DisplayInfo | None:
    """Match a stored preference to an online display (bounds may have moved)."""
    pid = pref.get("persistent_id")
    if pid:
        for d in displays:
            if d.persistent_id == pid:
                return d
    vid, product = pref.get("vendor_id"), pref.get("product_id")
    if vid and product:
        for d in displays:
            if d.vendor_id == str(vid).lower() and d.product_id == str(product).lower():
                return d
    name = pref.get("name")
    if name:
        for d in displays:
            if d.name == name:
                return d
    cg = pref.get("cg_id")
    if cg is not None:
        try:
            cg_i = int(cg)
        except Exception:
            cg_i = None
        if cg_i is not None:
            for d in displays:
                if d.cg_id == cg_i:
                    return d
    return None


def preferred_blob(d: DisplayInfo, *, source: str) -> dict[str, Any]:
    return {
        "name": d.name,
        "cg_id": d.cg_id,
        "vendor_id": d.vendor_id,
        "product_id": d.product_id,
        "serial": d.serial,
        "persistent_id": d.persistent_id,
        "diagonal_in": d.diagonal_in,
        "origin_x": d.origin_x,
        "origin_y": d.origin_y,
        "width": d.width,
        "height": d.height,
        "pixel_w": d.pixel_w,
        "pixel_h": d.pixel_h,
        "transport": d.transport,
        "usbish": d.usbish,
        "travel_score": d.travel_score,
        "source": source,
        "saved_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


def _window_geometry(d: DisplayInfo, *, margin: int = 0) -> tuple[int, int, int, int]:
    """Maximize within the target display (fill its bounds).

    EID-1098: when we pick a travel-class / USB-like monitor, the window should
    own that whole panel — not a floating 1600×1000 box. ``margin`` is optional
    edge inset (default 0 = true fill of that monitor only, not OS fullscreen).
    """
    w = max(800, int(round(d.width)) - margin * 2)
    h = max(600, int(round(d.height)) - margin * 2)
    x = int(round(d.origin_x)) + margin
    y = int(round(d.origin_y)) + margin
    return x, y, w, h


def _env_override(app: str) -> str | None:
    for key in (
        f"{app.upper()}_DISPLAY",
        f"{app.upper()}_PREFERRED_DISPLAY",
        "EIDOS_PREFERRED_DISPLAY",
    ):
        v = os.environ.get(key)
        if v and v.strip():
            return v.strip()
    return None


def resolve_for_app(
    app: str,
    *,
    persist_suggestion: bool = True,
    window_margin: int = 0,
) -> Placement | None:
    """Boot-time resolve: stored preferred, else suggest travel-class portable.

    Placement maximizes within the selected monitor (EID-1098).
    Returns None if no suitable display (caller falls back to OS default).
    """
    app = app.strip().lower()
    displays = list_displays()
    notes: list[str] = []
    path = settings_path(app)

    env = _env_override(app)
    if env:
        # Match by name substring or persistent id or cg id
        hit = None
        for d in displays:
            if env == d.persistent_id or env == str(d.cg_id) or env.lower() in d.name.lower():
                hit = d
                break
        if hit:
            x, y, w, h = _window_geometry(hit, margin=window_margin)
            return Placement(
                display=hit,
                reason="env",
                source="env",
                settings_path=path if path.is_file() else None,
                window_x=x,
                window_y=y,
                window_w=w,
                window_h=h,
                notes=[f"env override matched {hit.name}"],
            )
        notes.append(f"env override {env!r} not online; continuing")

    pref = preferred_from_settings(app)
    if pref:
        hit = match_preferred(pref, displays)
        if hit:
            x, y, w, h = _window_geometry(hit, margin=window_margin)
            return Placement(
                display=hit,
                reason="stored",
                source=str(pref.get("source") or "stored"),
                settings_path=path,
                window_x=x,
                window_y=y,
                window_w=w,
                window_h=h,
                notes=notes + [f"using stored preferred_display → {hit.name}"],
            )
        notes.append(
            f"stored preferred_display not online ({pref.get('name') or pref.get('persistent_id')}); re-suggesting"
        )

    # No usable stored preference → suggest
    pick = pick_portable(displays)
    if not pick:
        notes.append("no travel-class external display online")
        return None

    source = "auto_travel"
    if persist_suggestion:
        data = load_settings(app)
        data[SETTINGS_KEY] = preferred_blob(pick, source=source)
        path = save_settings(app, data)
        notes.append(f"suggested + saved preferred_display → {path}")
    else:
        notes.append("suggested (not saved)")

    x, y, w, h = _window_geometry(pick, margin=window_margin)
    return Placement(
        display=pick,
        reason="suggested",
        source=source,
        settings_path=path if persist_suggestion else None,
        window_x=x,
        window_y=y,
        window_w=w,
        window_h=h,
        notes=notes,
    )


def boot_message(placement: Placement | None, *, app: str) -> str:
    if placement is None:
        return (
            f"{app}: portable_display — no travel-class monitor online; "
            f"using OS default window placement "
            f"(settings {settings_path(app)})"
        )
    d = placement.display
    return (
        f"{app}: portable_display [{placement.reason}] "
        f"{d.name}  {d.diagonal_in:.1f}\"  "
        f"{int(d.width)}x{int(d.height)} @ ({placement.window_x},{placement.window_y})  "
        f"usbish={d.usbish:.0f} score={d.travel_score}  "
        f"transport={d.transport or '-'}  "
        f"→ {placement.settings_path or 'no save'}"
    )


def chromium_launch_args_for_app(app: str, *, headed: bool) -> list[str]:
    """Args to pass Chromium/Playwright when headed; empty if headless or no pick."""
    if not headed:
        return []
    if os.environ.get("EIDOS_DISABLE_PORTABLE_DISPLAY", "").lower() in ("1", "true", "yes"):
        return []
    p = resolve_for_app(app, persist_suggestion=True)
    msg = boot_message(p, app=app)
    print(msg, file=sys.stderr, flush=True)
    if not p:
        return []
    return p.chrome_args()


# ---- CLI ----


def _cmd_list(_: argparse.Namespace) -> int:
    for d in list_displays():
        print(
            json.dumps(
                {
                    "cg_id": d.cg_id,
                    "name": d.name,
                    "builtin": d.builtin,
                    "main": d.main,
                    "diagonal_in": d.diagonal_in,
                    "aspect": d.aspect,
                    "points": [d.width, d.height],
                    "origin": [d.origin_x, d.origin_y],
                    "pixels": [d.pixel_w, d.pixel_h],
                    "vendor_id": d.vendor_id,
                    "product_id": d.product_id,
                    "persistent_id": d.persistent_id,
                    "transport": d.transport,
                    "usbish": d.usbish,
                    "travel_score": d.travel_score,
                },
                ensure_ascii=False,
            )
        )
    return 0


def _cmd_resolve(ns: argparse.Namespace) -> int:
    p = resolve_for_app(ns.app, persist_suggestion=not ns.no_save)
    print(boot_message(p, app=ns.app), file=sys.stderr)
    if ns.json:
        print(json.dumps(p.as_dict() if p else None, indent=2, ensure_ascii=False))
    elif p:
        print(
            f"{p.display.name}\t{p.window_x},{p.window_y}\t{p.window_w}x{p.window_h}\t{p.reason}"
        )
    return 0 if p else 1


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="portable_display", description=__doc__)
    sub = p.add_subparsers(dest="cmd")

    sub.add_parser("list", help="List active displays with scores")

    r = sub.add_parser("resolve", help="Resolve preferred/suggested placement for an app")
    r.add_argument("--app", required=True, choices=("mafia", "chrime"))
    r.add_argument("--json", action="store_true")
    r.add_argument("--no-save", action="store_true", help="Suggest without writing settings")

    ns = p.parse_args(argv)
    if ns.cmd == "list":
        return _cmd_list(ns)
    if ns.cmd == "resolve":
        return _cmd_resolve(ns)
    p.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
