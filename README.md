# Mafia

> 🎭 Fraude family sibling of **[Chrime](https://github.com/eidos-agi/chrime)**.  
> Chrime = light agent document API. **Mafia = real Chromium browser AIs steer.**

**A real browser runtime for agents.** One engine of record per session (Chromium). JS runs.
Cookies stick. SPA is the point. Optional headed window. JSONL API so agents steer without
pixels as the primary path.

Not dual-brain. Not StaticEngine theater. Not CDP-as-the-product — **your ops**, Chromium underneath.

## Run

```sh
cd ~/repos-eidos-agi/mafia
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
# browsers: system Chrome via channel=chrome, or: python3 -m playwright install chromium

# JSONL on 127.0.0.1:7430 (headless Chromium by default)
mafia serve

# See the browser (human attach)
mafia serve --headed

# One-shot stdio
printf '%s\n' '{"op":"ping"}' '{"op":"session_open"}' \
  '{"op":"navigate","url":"https://example.com"}' '{"op":"snapshot"}' | mafia api
```

## Agent API (JSONL)

Every line is one op. Multi-session: pass `"session":"<id>"` (default = last opened).

| op | purpose |
|----|---------|
| `ping` / `help` / `status` | health |
| `session_open` / `session_list` / `session_close` | fleet unit |
| `navigate` | go (real browser) |
| `settle` | wait for load + short network quiet |
| `snapshot` | semantic DOM + stable node-ids (post-JS) |
| `read` | body innerText |
| `find_text` / `query` / `links` | locate |
| `click` | click by node_id (real JS click) |
| `eval` | run JS, return JSON result |
| `back` / `forward` | history |
| `quit` | shut down browser + server |

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
