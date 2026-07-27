"""Mafia browser skin — real Chromium chrome theme + new-tab.

Loads the unpacked pack at mafia/chrome_skin/ into a persistent profile so
Chromium paints noir/gold *browser chrome* (tabs / toolbar / NTP).

Note (macOS): the traffic-light titlebar stays system-native; branding shows
on the tab strip, toolbar tint, and the Mafia new-tab page.

Toggle: MAFIA_SKIN=auto|on|off  (auto = headed only).
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from mafia import __version__

GOLD = "#d4af37"


def extension_dir() -> Path:
    """Legacy single-folder path (still used for icons/docs)."""
    return Path(__file__).resolve().parent / "chrome_skin"


def theme_dir() -> Path:
    return extension_dir() / "theme"


def ntp_ext_dir() -> Path:
    return extension_dir() / "ntp_ext"


def skin_mode() -> str:
    return (os.environ.get("MAFIA_SKIN") or "auto").strip().lower()


def should_skin(*, headed: bool) -> bool:
    """Chrome theme packs only apply in headed Chromium."""
    m = skin_mode()
    if m in ("0", "off", "false", "no", "none"):
        return False
    if m in ("1", "on", "true", "yes", "always"):
        return bool(headed)
    return bool(headed)


def launch_args(*, headed: bool) -> list[str]:
    """Load theme pack + NTP extension (comma-separated for Chromium)."""
    if not should_skin(headed=headed):
        return []
    packs: list[str] = []
    if (theme_dir() / "manifest.json").is_file():
        packs.append(str(theme_dir().resolve()))
    if (ntp_ext_dir() / "manifest.json").is_file():
        packs.append(str(ntp_ext_dir().resolve()))
    if not packs:
        # fall back to flat chrome_skin/
        flat = extension_dir()
        if (flat / "manifest.json").is_file():
            packs.append(str(flat.resolve()))
    if not packs:
        return ["--force-dark-mode"]
    joined = ",".join(packs)
    return [
        f"--disable-extensions-except={joined}",
        f"--load-extension={joined}",
        "--force-dark-mode",
        "--disable-default-apps",
        "--no-first-run",
    ]


def ignore_default_args(*, headed: bool) -> list[str]:
    """Playwright disables extensions by default — re-enable when skinning."""
    if not should_skin(headed=headed):
        return []
    return ["--disable-extensions"]


def unpacked_extension_id(path: Path | None = None) -> str:
    """Chrome's a-p encoding of SHA256(path) for unpacked extension ids."""
    p = str((path or extension_dir()).resolve())
    digest = hashlib.sha256(p.encode("utf-8")).digest()
    # map first 16 bytes → 32 chars in a-p
    out = []
    for b in digest[:16]:
        out.append(chr(ord("a") + (b >> 4)))
        out.append(chr(ord("a") + (b & 0x0F)))
    # actually Chrome uses a different mapping — prefer Preferences when present
    return "".join(out)[:32]


def theme_id_from_profile(user_data_dir: Path) -> str | None:
    pref = user_data_dir / "Default" / "Preferences"
    if not pref.is_file():
        return None
    try:
        data = json.loads(pref.read_text(encoding="utf-8"))
    except Exception:
        return None
    tid = ((data.get("extensions") or {}).get("theme") or {}).get("id")
    return tid if isinstance(tid, str) and tid else None


def ntp_extension_id_from_profile(user_data_dir: Path) -> str | None:
    """Find the Mafia New Tab *extension* id (not the theme pack id)."""
    pref = user_data_dir / "Default" / "Preferences"
    if not pref.is_file():
        return None
    try:
        data = json.loads(pref.read_text(encoding="utf-8"))
    except Exception:
        return None
    settings = (data.get("extensions") or {}).get("settings") or {}
    for eid, meta in settings.items():
        man = meta.get("manifest") or {}
        name = man.get("name") or ""
        path = str(meta.get("path") or "")
        if name == "Mafia New Tab" or "ntp_ext" in path:
            return eid
    return None


def ntp_url(user_data_dir: Path | None = None) -> str | None:
    """URL of the Mafia new-tab page (chrome-extension://…/ntp.html)."""
    if user_data_dir is not None:
        eid = ntp_extension_id_from_profile(user_data_dir)
        if eid:
            return f"chrome-extension://{eid}/ntp.html"
    # file fallback always works for demos
    ntp = ntp_ext_dir() / "ntp.html"
    if ntp.is_file():
        return ntp.resolve().as_uri()
    return None


def cli_banner(
    *,
    host: str,
    port: int,
    headed: bool,
    version: str | None = None,
    skin: bool | None = None,
) -> str:
    ver = version or __version__
    sk = should_skin(headed=headed) if skin is None else skin
    g = "\033[38;5;178m"
    d = "\033[38;5;240m"
    r = "\033[0m"
    w = "\033[38;5;252m"
    return "\n".join(
        [
            f"{d}╔══════════════════════════════════════════════════════╗{r}",
            f"{d}║{r}  {g}♠  M A F I A{r}   {d}v{ver}{r}                              {d}║{r}",
            f"{d}║{r}  {w}browser chrome skin · chromium engine{r}              {d}║{r}",
            f"{d}╠══════════════════════════════════════════════════════╣{r}",
            f"{d}║{r}  {w}JSONL{r}  {g}{host}:{port}{r}",
            f"{d}║{r}  {w}headed{r}={g}{str(headed).lower():<5}{r}  {w}skin{r}={g}{str(sk).lower():<5}{r}  {w}queue{r}={g}1-thread{r}",
            f"{d}╚══════════════════════════════════════════════════════╝{r}",
        ]
    )
