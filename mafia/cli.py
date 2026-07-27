"""CLI: mafia serve | mafia api"""

from __future__ import annotations

import argparse
import json
import socket
import sys
import threading
from typing import TextIO

from mafia.api import dispatch
from mafia.browser import MafiaBrowser


def _handle_line(browser: MafiaBrowser, line: str, out: TextIO) -> bool:
    line = line.strip()
    if not line:
        return False
    resp, should_quit = dispatch(browser, line)
    out.write(json.dumps(resp, ensure_ascii=False) + "\n")
    out.flush()
    return should_quit


def run_stdio(browser: MafiaBrowser) -> int:
    for line in sys.stdin:
        if _handle_line(browser, line, sys.stdout):
            return 0
    browser.stop()
    return 0


def run_server(browser: MafiaBrowser, host: str, port: int) -> int:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((host, port))
    sock.listen(64)
    print(f"mafia listening on {host}:{port} (JSONL, engine=chromium)", flush=True)
    print(f"  headed={browser.headed}  sessions=open-on-demand", flush=True)

    def client(conn: socket.socket) -> None:
        try:
            f = conn.makefile("rwb")
            while True:
                raw = f.readline()
                if not raw:
                    break
                line = raw.decode("utf-8", errors="replace")
                resp, should_quit = dispatch(browser, line)
                f.write((json.dumps(resp, ensure_ascii=False) + "\n").encode("utf-8"))
                f.flush()
                if should_quit:
                    break
        except Exception as e:
            try:
                err = json.dumps({"ok": False, "code": "connection_error", "error": str(e)})
                conn.sendall((err + "\n").encode("utf-8"))
            except Exception:
                pass
        finally:
            try:
                conn.close()
            except Exception:
                pass

    try:
        while True:
            conn, _addr = sock.accept()
            threading.Thread(target=client, args=(conn,), daemon=True).start()
    except KeyboardInterrupt:
        print("\nmafia: shutting down", flush=True)
    finally:
        browser.stop()
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

    # serve
    host = getattr(args, "host", "127.0.0.1")
    port = getattr(args, "port", 7430)
    # bare `mafia` with no subcommand
    if args.cmd is None and argv is None and len(sys.argv) > 1:
        # if first arg looks like flag, re-parse as serve
        pass
    return run_server(browser, host, port)


if __name__ == "__main__":
    raise SystemExit(main())
