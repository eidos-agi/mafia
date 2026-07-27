# Mafia

> 🎭 Fraude family sibling of **[Chrime](https://github.com/eidos-agi/chrime)**.  
> Chrime = light agent document API. **Mafia = real Chromium browser AIs steer.**

**A real browser runtime for agents** — Chromium underneath, **Mafia control plane** on top.

Not “rebuild Blink.” Not bare Playwright/agent-browser. The product is **tight steering**:

1. **Browser** — sessions, settle, snapshot (post-JS), click by node-id  
2. **Knox** — passwords into the page; secrets never in agent JSON  
3. **Hancock** — human must sign before consequential actions  

Without Knox + Hancock, agents cannot safely log in or take irreversible steps → not autonomous.

SPA works (real Chromium). Optional headed attach. JSONL on `:7430`.

## Run

```sh
cd ~/repos-eidos-agi/mafia
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
# browsers: system Chrome via channel=chrome, or: python3 -m playwright install chromium

# JSONL on 127.0.0.1:7430 (headless Chromium by default)
python3 -m mafia serve
# or: mafia serve   (if pip install -e . put scripts on PATH)

# See the browser (human attach)
python3 -m mafia serve --headed

# One-shot stdio
printf '%s\n' '{"op":"ping"}' '{"op":"session_open"}' \
  '{"op":"navigate","url":"https://example.com"}' '{"op":"snapshot"}' \
  | python3 -m mafia api
```

## Agent API (JSONL)

Every line is one op. Multi-session: pass `"session":"<id>"` (default = last opened).

| op | purpose |
|----|---------|
| `ping` / `help` / `status` | health |
| `session_open` / `session_list` / `session_close` | live fleet unit |
| `session_save` / `session_load` / `session_saves` | named reloadable saves (cookies + URL) |
| `session_profiles` / `session_delete` | durable profile jars; delete save/profile |
| `navigate` | go (real browser) |
| `settle` | wait for load + short network quiet |
| `snapshot` | semantic DOM + stable node-ids (post-JS) |
| `read` | body innerText |
| `find_text` / `query` / `links` | locate |
| `click` | click by node_id (real JS click) |
| `eval` | run JS, return JSON result |
| `back` / `forward` | history |
| `fill` / `type` / `press` | forms |
| `knox_find` / `knox_fill` / `knox_use` | credentials (secret_output suppressed) |
| `hancock_request` / `hancock_wait` / `hancock_pending` | human sign-off; STILL_PENDING ≠ go |
| `quit` | shut down browser + server |

### Sessions you can reload (required for autonomy)

Live sessions die when the process dies. **Named saves** and **profiles** put cookies + storage + URL on disk under `logs/sessions/` and `logs/profiles/` (override with `MAFIA_SESSIONS_DIR` / `MAFIA_PROFILES_DIR`). Never commit those dirs.

```json
{"op":"session_open"}
{"op":"navigate","url":"https://example.com"}
{"op":"session_save","name":"work-gmail"}
{"op":"session_close","session":"s0001-…"}
{"op":"session_load","name":"work-gmail"}
{"op":"session_saves"}
```

**Profile jar** (auto-load on open, auto-save on close/quit):

```json
{"op":"session_open","profile":"gmail-work"}
{"op":"navigate","url":"https://mail.google.com"}
{"op":"session_close","session":"…"}
{"op":"session_open","profile":"gmail-work"}
```

### Autonomy (load-bearing)

```json
{"op":"knox_find","query":"github.com"}
{"op":"knox_fill","query":"github.com","fields":"both"}
{"op":"knox_fill","query":"bank","fields":"password","require_hancock":true,"why":"Pay invoice","wait":false}
{"op":"hancock_wait","id":"req_…"}
```

Only proceed on Hancock when outcome is `APPROVED_AND_RAN` / `AUTO_APPROVED_AND_RAN` (or `hancock wait` exit 0).

Drive a running server:

```sh
printf '%s\n' '{"op":"session_open"}' '{"op":"navigate","url":"file://…/js-render.html"}' \
  '{"op":"settle"}' '{"op":"find_text","text":"POST-JS"}' | nc -w 5 127.0.0.1 7430
```

## Chrime vs Mafia

| | **Chrime** | **Mafia** |
|--|------------|-----------|
| Engine | Static / light (no SPA claim) | **Chromium** (SPA required) |
| Scale unit | Single window/session story | **Many sessions** |
| Gmail / real apps | Out of product green | **In scope** |
| Role | Gym + CI document ops | Production web steer |

Same *ideas* (ops, node-ids, settle). Different contract.

## Telos

See [`TELOS.md`](TELOS.md).

## License

MIT
