#!/usr/bin/env python3
"""Public API concurrency: N clients via TCP against mafia serve.

Must not hang or greenlet.error. Ops serialize on one browser thread.
"""

from __future__ import annotations

import json
import socket
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
N = 10
PORT = 17430  # avoid clash with a human's :7430


def rpc(port: int, ops: list[dict], timeout: float = 60.0) -> list[dict]:
    s = socket.create_connection(("127.0.0.1", port), timeout=5)
    s.settimeout(timeout)
    f = s.makefile("rwb")
    out: list[dict] = []
    try:
        for op in ops:
            f.write((json.dumps(op) + "\n").encode())
            f.flush()
            line = f.readline()
            if not line:
                raise RuntimeError("server closed")
            out.append(json.loads(line.decode()))
    finally:
        try:
            s.close()
        except Exception:
            pass
    return out


def one_client(i: int, port: int) -> tuple[int, bool, str]:
    try:
        resps = rpc(
            port,
            [
                {"op": "session_open", "id": f"fleet-{i}"},
                {
                    "op": "navigate",
                    "session": f"fleet-{i}",
                    "url": "https://example.com",
                },
                {"op": "status", "session": f"fleet-{i}"},
            ],
            timeout=90.0,
        )
        ok = all(r.get("ok") for r in resps)
        return i, ok, json.dumps(resps)[:200]
    except Exception as e:
        return i, False, str(e)


def main() -> int:
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "mafia",
            "serve",
            "--host",
            "127.0.0.1",
            "--port",
            str(PORT),
            "--channel",
            "chrome",
        ],
        cwd=str(ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    # wait for listen
    t0 = time.time()
    ready = False
    while time.time() - t0 < 30:
        try:
            rpc(PORT, [{"op": "ping"}], timeout=2)
            ready = True
            break
        except Exception:
            if proc.poll() is not None:
                out = proc.stdout.read() if proc.stdout else ""
                print("FAIL: server exited early")
                print(out)
                return 1
            time.sleep(0.2)
    if not ready:
        proc.kill()
        print("FAIL: server not ready")
        return 1

    fails: list[str] = []
    t1 = time.time()
    with ThreadPoolExecutor(max_workers=N) as pool:
        futs = [pool.submit(one_client, i, PORT) for i in range(N)]
        for fut in as_completed(futs, timeout=180):
            i, ok, detail = fut.result()
            if not ok:
                fails.append(f"client {i}: {detail}")
    elapsed = time.time() - t1

    try:
        rpc(PORT, [{"op": "quit"}], timeout=10)
    except Exception:
        pass
    try:
        proc.wait(timeout=10)
    except Exception:
        proc.kill()

    log = ""
    if proc.stdout:
        try:
            log = proc.stdout.read() or ""
        except Exception:
            pass
    if "greenlet" in log.lower():
        fails.append(f"greenlet error in server log: {log[:500]}")

    if fails:
        print("FAIL")
        for f in fails:
            print(" -", f)
        print(f"elapsed={elapsed:.1f}s")
        if log:
            print("--- server log ---")
            print(log[-2000:])
        return 1
    print(f"PASS: serve N={N} concurrent clients ok in {elapsed:.1f}s (serialized browser thread)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
