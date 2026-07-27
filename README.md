# Mafia

> 🎭 Fraude family sibling of **[Chrime](https://github.com/eidos-agi/chrime)**.  
> Chrime = light agent document API. **Mafia = real Chromium browser AIs steer.**

**A real browser runtime for agents** — Chromium underneath, **Mafia control plane** on top.

Not “rebuild Blink.” Not bare Playwright/agent-browser. The product is **tight steering**:

1. **Browser** — sessions, settle, snapshot (post-JS), click by node-id  
2. **Knox** — passwords into the page; secrets never in agent JSON  
3. **Hancock** — human must sign before consequential actions  
4. **Learn** — site memory so the next surf reuses what worked  

Without Knox + Hancock, agents cannot safely log in or take irreversible steps → not autonomous.  
Without learn + session durability, every run is cold start → not compounding.

SPA works (real Chromium). ARIA roles (`div[role=button]`) in snapshot. Optional headed attach. JSONL on `:7430`.

## Run

```sh
cd ~/repos-eidos-agi/mafia
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
# browsers: system Chrome via channel=chrome, or: python3 -m playwright install chromium

# JSONL on 127.0.0.1:7430 (headless Chromium by default)
python3 -m mafia serve
# or: mafia serve   (if pip install -e . put scripts on PATH)

# See the browser (human attach) — Mafia chrome theme (tabs/toolbar/NTP)
python3 -m mafia serve --headed
# or: python3 scripts/demo_skin.py
# skin: auto on headed (bundled Chromium + theme pack + MV3 NTP); MAFIA_SKIN=off to disable
# macOS: system titlebar stays native; branding is tab strip + new-tab page
# EID-1099: NTP pack is Manifest V3 (MV2 is rejected by modern Chromium with a modal)

# Portable / USB-like monitor (headed boot)
# Places window via Chromium --window-position/--window-size only (no mouse grab).
# Default: floating ~85% window on that display (does not fill panel / steal focus).
# Headed pages use no_viewport so OS resize reflows the page.
# python3 -m mafia.portable_display list
# EIDOS_DISABLE_PORTABLE_DISPLAY=1  skip placement
# MAFIA_FILL_DISPLAY=1              fill whole panel (aggressive; old behavior)
# MAFIA_DISPLAY=<name|id>           force a monitor

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
| `session_label` / `session_recent` / `session_history` | usage ledger — every op tracked (secrets stripped) |
| `session_reboot` | resume last (or named) work from ledger + jar |
| `navigate` | go (real browser) |
| `settle` | load + networkidle; optional `text` / `selector` |
| `wait` | text / selector / url_contains / ms |
| `viewport` | set width×height on live session |
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

### Usage ledger + reboot (required for agent continuity)

Every op is append-logged to `logs/ledger/events.jsonl` (secrets/`text`/`js` stripped). Work units roll up in `logs/ledger/work.json` by **profile / save / label**. Close auto-persists jars so a later agent can reboot.

```json
{"op":"session_open","label":"gmail-inbox-scour"}
{"op":"navigate","url":"https://mail.google.com"}
{"op":"session_close","session":"…"}

{"op":"session_recent"}
{"op":"session_history","work":"gmail-inbox-scour","limit":40}
{"op":"session_reboot"}
{"op":"session_reboot","name":"gmail-inbox-scour"}
```

`session_reboot` without a name resumes the most recently used durable work.

### Learning (next surf is easier)

Successful `find_text` / `click` / `navigate` auto-write **per-origin** memory under `logs/learn/` (override `MAFIA_LEARN_DIR`). Secrets never stored. Next agent on the same site should **recall/suggest first**, not thrash the DOM cold.

```json
{"op":"navigate","url":"https://example.com"}
{"op":"find_text","text":"More information"}
{"op":"click","node_id":3}
// … memory written …

{"op":"learn_recall"}
{"op":"learn_suggest"}
{"op":"learn_use","text":"More information"}
{"op":"learn_recipe","name":"click:More information"}
{"op":"learn_note","note":"Footer link goes to IANA"}
{"op":"learn_list"}
```

| op | purpose |
|----|---------|
| `learn_recall` | landmarks, recipes, notes, paths for current origin |
| `learn_suggest` | ranked next actions from memory |
| `learn_use` | find known text + click if clickable (easy path) |
| `learn_recipe` | replay a prior successful sequence |
| `learn_note` | agent tip for this site |
| `learn_list` / `learn_forget` | inventory / prune |

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

## Verify

```sh
python3 scripts/smoke_spa.py
python3 scripts/smoke_node_ids.py
python3 scripts/smoke_sessions.py
python3 scripts/smoke_ledger.py
python3 scripts/smoke_learn.py
python3 scripts/smoke_serve_n10.py
python3 scripts/run_api_suite.py          # ≥30 checks
MAFIA_SUITE_MODE=tcp python3 scripts/run_api_suite.py
MAFIA_FLEET_N=10 python3 scripts/fleet_smoke.py
```

## Telos

See [`TELOS.md`](TELOS.md). Plan + Linear: [`PLAN.md`](PLAN.md).

## License

MIT
