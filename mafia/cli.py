"""CLI: mafia serve | mafia api

Concurrency model (locked): one Playwright browser owned by one worker thread.
TCP client threads only do socket I/O and enqueue ops. Never call Playwright
from multiple threads (greenlet.error / silent hangs).
"""

from __future__ import annotations

import argparse
import json
import queue
import socket
import sys
import threading
from typing import Any, TextIO

from mafia import __version__
from mafia import skin as skin_mod
from mafia.api import dispatch
from mafia.browser import MafiaBrowser


class BrowserOpQueue:
    """Serialize all browser ops onto a single thread."""

    def __init__(self, browser: MafiaBrowser, *, default_timeout: float = 120.0) -> None:
        self.browser = browser
        self.default_timeout = default_timeout
        self._q: queue.Queue[tuple[str, threading.Event, list[Any]] | None] = queue.Queue()
        self._thread = threading.Thread(target=self._worker, name="mafia-browser", daemon=True)
        self._thread.start()

    def _worker(self) -> None:
        while True:
            item = self._q.get()
            if item is None:
                return
            line, done, box = item
            try:
                resp, should_quit = dispatch(self.browser, line)
                box.append((resp, should_quit))
            except Exception as e:
                box.append(
                    (
                        {
                            "ok": False,
                            "code": "dispatch_error",
                            "error": str(e),
                        },
                        False,
                    )
                )
            finally:
                done.set()

    def call(self, line: str, timeout: float | None = None) -> tuple[dict[str, Any], bool]:
        done = threading.Event()
        box: list[Any] = []
        self._q.put((line, done, box))
        t = self.default_timeout if timeout is None else timeout
        if not done.wait(t):
            return (
                {
                    "ok": False,
                    "code": "timeout",
                    "error": f"browser op timed out after {t}s",
                },
                False,
            )
        if not box:
            return (
                {"ok": False, "code": "internal", "error": "empty browser result"},
                False,
            )
        return box[0]

    def stop(self) -> None:
        self._q.put(None)
        self._thread.join(timeout=5.0)
        try:
            self.browser.stop()
        except Exception:
            pass


def _handle_line(browser: MafiaBrowser, line: str, out: TextIO) -> bool:
    line = line.strip()
    if not line:
        return False
    resp, should_quit = dispatch(browser, line)
    out.write(json.dumps(resp, ensure_ascii=False) + "\n")
    out.flush()
    return should_quit


def run_stdio(browser: MafiaBrowser) -> int:
    # stdio is single-threaded — dispatch directly
    for line in sys.stdin:
        if _handle_line(browser, line, sys.stdout):
            return 0
    browser.stop()
    return 0


def run_server(browser: MafiaBrowser, host: str, port: int) -> int:
    opq = BrowserOpQueue(browser)
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((host, port))
    sock.listen(64)
    print(
        skin_mod.cli_banner(
            host=host,
            port=port,
            headed=browser.headed,
            version=__version__,
            skin=getattr(browser, "skin", False),
        ),
        flush=True,
    )
    print(
        f"  concurrency=single-browser-thread  sessions=open-on-demand  "
        f"skin_ext={skin_mod.extension_dir() if getattr(browser, 'skin', False) else 'off'}",
        flush=True,
    )

    quit_flag = threading.Event()

    def client(conn: socket.socket) -> None:
        try:
            f = conn.makefile("rwb")
            while not quit_flag.is_set():
                raw = f.readline()
                if not raw:
                    break
                line = raw.decode("utf-8", errors="replace")
                resp, should_quit = opq.call(line)
                f.write((json.dumps(resp, ensure_ascii=False) + "\n").encode("utf-8"))
                f.flush()
                if should_quit:
                    quit_flag.set()
                    break
        except Exception as e:
            try:
                err = json.dumps(
                    {"ok": False, "code": "connection_error", "error": str(e)}
                )
                conn.sendall((err + "\n").encode("utf-8"))
            except Exception:
                pass
        finally:
            try:
                conn.close()
            except Exception:
                pass

    try:
        while not quit_flag.is_set():
            sock.settimeout(1.0)
            try:
                conn, _addr = sock.accept()
            except socket.timeout:
                continue
            threading.Thread(target=client, args=(conn,), daemon=True).start()
    except KeyboardInterrupt:
        print("\nmafia: shutting down", flush=True)
    finally:
        quit_flag.set()
        opq.stop()
        sock.close()
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="mafia",
        description="Mafia — Chromium browser AIs steer (sibling to Chrime)",
    )
    sub = p.add_subparsers(dest="cmd")

    serve = sub.add_parser("serve", help="JSONL TCP server (default command)")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=7430)
    serve.add_argument("--headed", action="store_true", help="Show Chromium window")
    serve.add_argument(
        "--channel",
        default="chrome",
        help="Playwright channel (chrome|chromium|msedge). Empty = bundled chromium",
    )

    api = sub.add_parser("api", help="JSONL on stdin/stdout")
    api.add_argument("--headed", action="store_true")
    api.add_argument("--channel", default="chrome")

    args = p.parse_args(argv)
    cmd = args.cmd or "serve"

    channel = getattr(args, "channel", "chrome") or None
    if channel == "":
        channel = None
    headed = bool(getattr(args, "headed", False))
    browser = MafiaBrowser(headed=headed, channel=channel)

    if cmd == "api":
        return run_stdio(browser)

    host = getattr(args, "host", "127.0.0.1")
    port = getattr(args, "port", 7430)
    return run_server(browser, host, port)


if __name__ == "__main__":
    raise SystemExit(main())
