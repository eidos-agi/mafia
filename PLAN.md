# Mafia — Master Plan

**Repo:** [eidos-agi/mafia](https://github.com/eidos-agi/mafia)  
**Sibling:** [eidos-agi/chrime](https://github.com/eidos-agi/chrime)  
**Linear:** project **Mafia** (Eidos AGI team)  
**Telos:** `TELOS.md`

---

## 0. Product split (non-negotiable)

| Product | Contract | SPA / Gmail |
|---------|----------|-------------|
| **Chrime** | Light agent document API (static/light runner). Leave as-is. | **Out of green** |
| **Mafia** | Real Chromium browser AIs steer. Session = unit. Fleet path. | **Required** |

Same *op vocabulary ideas* where it maps. **Different engine of record.** Never dual-brain.

**Anti-goals for Mafia**
- Do not become “Chrime with a WebView”
- Do not block agent API on a GUI event loop
- Do not mark SPA green via static HTML
- Do not use CDP as the *public* product API (internal adapter OK)
- Do not ship “Playwright with a logo” without **Knox + Hancock** — autonomy stack is load-bearing

**V1 product thesis (locked)**  
Mafia V1 = **tight wrapper around Chromium** for AI steering, differentiated by:
1. Agent-native browser ops (sessions, settle, node-ids)  
2. **Knox** — password manager integration (browser-fill, no secret echo)  
3. **Hancock** — permission/request engine (no fake approval)  

Without 2+3, agents cannot log in or take consequential actions safely → **not steerable to true autonomy.**

---

## 1. Architecture (target)

```
  Agent clients
       │
       ▼
  ┌────────────────────────────────────────────┐
  │  Mafia control plane (JSONL :7430)           │
  │  • browser ops (session, nav, DOM, click)  │
  │  • knox_*  (secrets → page, never JSON)    │
  │  • hancock_* (human sign before go)        │
  └───────────────┬───────────────┬────────────┘
                  │               │
         ┌────────▼──────┐  ┌─────▼──────┐
         │ Chromium pool │  │ Knox CLI/  │
         │ (Playwright   │  │ lib +      │
         │  adapter)     │  │ Hancock    │
         │ sessions…     │  │ CLI        │
         └───────────────┘  └────────────┘
```

**Rules**
1. **One engine of record per session** = that session’s Chromium page/document.
2. **Agent I/O never requires a human window.** Headed is attach, not identity.
3. **Knox/Hancock are first-class ops**, not afterthoughts.
4. **Snapshot/click** always evaluate **in that page** (post-JS).
5. **Isolation** = BrowserContext (cookies, storage) per session.
6. Chromium/Playwright is **substrate**; public product is Mafia ops + autonomy stack.

**Current v0.1–0.2**
- Playwright + system Chrome / bundled Chromium
- session_*, navigate, settle, snapshot, read, find_text, query, links, click, eval, fill, press
- knox_find / knox_fill / knox_use(dry-run); hancock_request / wait / pending
- SPA smoke green (`scripts/smoke_spa.py`)
- TCP serve + stdio api

---

## 2. Milestones

### M0 — Foundation (done)
- [x] Repo, TELOS, MIT, pyproject
- [x] Chromium engine of record
- [x] Multi-session contexts
- [x] Semantic walker + node_id click
- [x] SPA fixture proof (post-JS + click handler)
- [x] JSONL serve `:7430`

**Exit:** smoke_spa.py PASS.

---

### M0.5 — Autonomy stack (Knox + Hancock) — **priority**
Without this, Mafia cannot be steered for real logins / gated actions.

| Work | Done when |
|------|-----------|
| M0.5.1 knox_find | Metadata only; secret_output suppressed |
| M0.5.2 knox_fill | Unlock via Knox → fill into Chromium page; password never in JSON |
| M0.5.3 knox_use dry-run | Prove match without secret |
| M0.5.4 hancock_request/wait/pending | STILL_PENDING ≠ go; wait exit 0 only on approval |
| M0.5.5 Optional gate | knox_fill with require_hancock blocks until signed |
| M0.5.6 Docs | README autonomy section; policy text |

**Exit:** agent script can knox_find + (with Touch ID) knox_fill into a form page; hancock_request returns id and does not invent approval.

### M1 — Agent API hardened (next)
Make the control plane trustworthy for daily agent use.

| Work | Done when |
|------|-----------|
| M1.1 Op parity map vs Chrime | Doc: which ops map 1:1, which Pro-only, which never |
| M1.2 Typed errors | All errors `{ok:false, code, error}` consistently |
| M1.3 Settle quality | Settle returns real signals (load + networkidle + optional selector); not sleep-only |
| M1.4 Wait helpers | `wait` for text/selector/url/timeout |
| M1.5 Fill / type / press | Form ops on live document (no secret echo) — **partial via knox_fill path** |
| M1.6 Breadcrumbs | Optional `_trace` hierarchy (Chrime-compatible or `MAFIA.*`) |
| M1.7 API suite | ≥30 plain-English cases against real Chromium (not static) |
| M1.8 Headed attach | `--headed` stable; API still works while window open |

**Exit:** suite green; agent can drive forms + SPA fixture end-to-end headless and headed.

---

### M2 — Session & profile durability
| Work | Done when |
|------|-----------|
| M2.1 Persistent profiles | ✅ `session_open` with `profile`; jar under `logs/profiles/`; cookies+URL survive restart (`scripts/smoke_sessions.py`) |
| M2.2 Session save/load | ✅ `session_save` / `session_load` / `session_saves` / `session_delete`; storage_state + URL under `logs/sessions/` |
| M2.3 User-agent / viewport | Partial: `viewport` + `user_agent` on `session_open`; device_scale later |
| M2.4 Download / dialog policy | Explicit deny or capture; never block agent forever |
| M2.5 Clean shutdown | Partial: `quit` / `stop` flushes profile jars; SIGTERM docs later |
| M2.6 Usage ledger + reboot | ✅ every op → `logs/ledger/events.jsonl`; work index; `session_recent` / `session_history` / `session_reboot`; auto-persist on close (`scripts/smoke_ledger.py`) |
| M2.7 Site learning | ✅ auto landmarks/recipes from find/click/nav; `learn_recall` / `suggest` / `use` / `recipe` / `note`; `scripts/smoke_learn.py` |

**Exit (durability core):** open → set cookie → save/close or profile close → new process → load/open profile → cookie+URL restored. Login-wall fixture still nice-to-have for suite polish.

**Exit (lineage):** agent can `session_recent` after process death and `session_reboot` the work it was doing.

**Exit (learning):** second visit on same origin uses `learn_suggest` / `learn_use` instead of rediscovering node_ids from scratch.

---

### M3 — SPA acceptance (Gmail-class)
| Work | Done when |
|------|-----------|
| M3.1 Complex app fixture | Multi-route SPA fixture (client router + auth wall) |
| M3.2 Gmail scour protocol | Port/adapt `chrime/cases/gmail-scour` → Mafia |
| M3.3 Human login path | Headed attach; agent waits for inbox marker; no fake 2FA |
| M3.4 Six-theme scour | Report JSON with 6 unrelated themes or explicit misses |
| M3.5 Zero coordinate rule | Suite forbids pixel/xy ops |

**Exit:** `scripts/run_gmail_scour.py` against Mafia produces report; human login only for auth.

---

### M4 — Fleet (path to ~100)
| Work | Done when |
|------|-----------|
| M4.1 Session address model | Every op requires or defaults session; no global page |
| M4.2 Concurrency model | Document: threads vs async Playwright; pick one |
| M4.3 Fleet smoke N=10 | Open 10 sessions, navigate distinct URLs, snapshot all |
| M4.4 Fleet smoke N=50 | Memory budget documented; no crash |
| M4.5 Fleet smoke N=100 | Target; may be multi-browser process if needed |
| M4.6 Kill/restart session | Close one session without killing browser pool |
| M4.7 Resource limits | Max sessions config; reject with clear code |

**Exit:** N=10 green always; N=100 green or written budget+gap with date.

---

### M5 — Productization
| Work | Done when |
|------|-----------|
| M5.1 CLI polish | `mafia` on PATH; `--help`; version |
| M5.2 Install docs | Chrome channel vs bundled chromium |
| M5.3 CI | GitHub Actions: smoke_spa + suite |
| M5.4 Chrime cross-link | Chrime README: SPA/Gmail → Mafia |
| M5.5 Linear hygiene | Milestones/issues stay source of execution |
| M5.6 Optional Rust port | Only if Python becomes the bottleneck — not blocking |

**Exit:** cold machine can install + smoke in &lt;15 minutes from README.

---

## 3. Workstreams (parallelizable)

```
WS-A Control plane     M1 ops, suite, errors, settle
WS-B Session/profile   M2 durability, viewport
WS-C Real-app accept   M3 Gmail scour
WS-D Fleet             M4 concurrency
WS-E Packaging         M5 CI/docs
WS-F Chrime boundary   demote SPA claims; point to Mafia
```

Agents can own WS-A/B/D/E. Human-in-loop for WS-C (Gmail auth).

---

## 4. Technical decisions (locked unless amended)

| Decision | Choice | Why |
|----------|--------|-----|
| Browser | Chromium via Playwright | SPA now; system Chrome channel |
| Language (v0–M4) | Python 3.11+ | Speed of iteration; port later if needed |
| Public API | JSONL TCP + stdio | Matches agent habits / Chrime |
| Isolation | BrowserContext per session | Cookies isolated |
| Headed | Optional flag | Attach, not product identity |
| Node-ids | In-page stamp `data-mafia-id` | Same walk for snapshot/click |
| Secrets | Never in responses | Knox later if needed |
| Port default | 7430 | Chrime keeps 7420 |

**Open decisions (pick when hitting M4)**
- One browser many contexts vs process-per-N-sessions
- Async Playwright loop vs sync + thread pool
- Whether to expose raw CDP as escape hatch (default: no)

---

## 5. Risk register

| Risk | Impact | Mitigation |
|------|--------|------------|
| Gmail bot walls / 2FA | Blocks M3 | Human headed login; agent post-auth only |
| Playwright sync + multi-thread | Races | One browser thread; queue ops per process |
| Memory at N=100 | OOM | Context recycling; multi-browser; headless shell |
| Node-id instability after SPA re-render | Bad clicks | Re-walk before click; optional role+text fallback |
| Scope creep into “own Blink” | Delay SPA | Chromium is intentional substrate for Mafia |
| Chrime still claims SPA | Confusion | Update Chrime docs/telos boundary (WS-F) |

---

## 6. Success metrics

| Metric | M1 | M3 | M4 |
|--------|----|----|-----|
| SPA fixture green | required | required | required |
| Real Chromium suite cases | ≥30 | ≥50 | ≥50 |
| Gmail themes hit | — | ≥5 of 6 | ≥5 of 6 |
| Concurrent sessions smoke | 2 | 2 | 10 / 50 / 100 |
| Dual-brain ops | 0 | 0 | 0 |

---

## 7. Suggested execution order (first 2 weeks)

**Week 1**
1. M1.3 settle + M1.4 wait  
2. M1.5 fill/type/press  
3. M1.7 suite skeleton + 30 cases  
4. M2.3 viewport  
5. WS-F Chrime README boundary  

**Week 2**
1. M2.1–M2.2 profiles  
2. M3.1–M3.2 Gmail protocol on Mafia  
3. M4.3 fleet N=10  
4. M5.3 CI smoke  

---

## 8. Linear mapping

Milestones in Linear project **Mafia** match M0–M5.  
Each row in §2 becomes issues with `Done when` checklists.  
This file is the narrative source of truth; Linear is the execution board.

**Do not file SPA/Gmail work on Chrime project** unless it is “demote claim / point to Mafia.”
