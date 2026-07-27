# Mafia — Master Plan

**Repo:** [eidos-agi/mafia](https://github.com/eidos-agi/mafia)  
**Sibling:** [eidos-agi/chrime](https://github.com/eidos-agi/chrime)  
**Linear:** project **[Mafia](https://linear.app/eidos-agi/project/mafia)** (Eidos AGI team)  
**Telos:** `TELOS.md`  
**HEAD:** see `git log -1` — continuity + suite/fleet + skin + Gmail runner  
**Reconcile note (2026-07-27):** chat vs software audited — Gmail speed claim unproven; login-wait fixes committed with this tree.  
**Status board:** §8 Linear mapping (source of execution IDs)

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
- Do not ship “Playwright with a logo” without **Knox + Hancock + session continuity + site learning**

**V1 product thesis (locked)**  
Mafia V1 = **tight wrapper around Chromium** for AI steering, differentiated by:

1. **Browser** — agent-native ops (sessions, settle, node-ids, SPA truth)  
2. **Knox** — password manager integration (browser-fill, no secret echo)  
3. **Hancock** — permission/request engine (no fake approval)  
4. **Session durability** — reloadable saves + profiles (cookies/URL survive death)  
5. **Usage ledger + reboot** — every use tracked; agent reboots prior work  
6. **Site learning** — landmarks/recipes so the next surf is easier  

Without 2–3, agents cannot log in or take consequential actions safely.  
Without 4–6, every run is cold start → **not compounding autonomy.**

---

## 1. Architecture (target + current)

```
  Agent clients
       │
       ▼
  ┌──────────────────────────────────────────────────────────┐
  │  Mafia control plane (JSONL :7430)                         │
  │  • browser ops (session, nav, DOM, click)                  │
  │  • knox_*  (secrets → page, never JSON)                    │
  │  • hancock_* (human sign before go)                        │
  │  • session_save/load/reboot + ledger                       │
  │  • learn_* (per-origin memory)                             │
  └───────┬──────────────┬──────────────┬────────────────────┘
          │              │              │
   ┌──────▼──────┐ ┌─────▼─────┐ ┌──────▼──────┐
   │ Chromium    │ │ Knox CLI  │ │ Disk jars   │
   │ pool        │ │ Hancock   │ │ sessions/   │
   │ (Playwright)│ │           │ │ profiles/   │
   │ contexts…   │ │           │ │ ledger/     │
   └─────────────┘ └───────────┘ │ learn/      │
                                 └─────────────┘
```

**Rules**
1. **One engine of record per session** = that session’s Chromium page/document.
2. **Agent I/O never requires a human window.** Headed is attach, not identity.
3. **Knox/Hancock are first-class ops**, not afterthoughts.
4. **Snapshot/click** always evaluate **in that page** (post-JS).
5. **Isolation** = BrowserContext (cookies, storage) per session.
6. **Durability** = named saves + profile jars; close auto-persists.
7. **Lineage** = every op → ledger; work index; `session_reboot`.
8. **Learning** = successful find/click/nav → per-origin memory; `learn_use` next time.
9. Chromium/Playwright is **substrate**; public product is Mafia ops + autonomy stack.

### Shipped surface (v0.x — master)

| Area | Ops / artifacts | Proof |
|------|-----------------|-------|
| Core browser | session_open/list/close, navigate, settle, snapshot, read, find_text, query, links, click, eval, fill, type, press, back, forward, status, help, quit | `scripts/smoke_spa.py` |
| Autonomy | knox_find, knox_fill, knox_use(dry-run), hancock_request/wait/pending | code + README |
| Durability | session_save/load/saves/delete, session_open profile=, auto-persist on close | `scripts/smoke_sessions.py` |
| Lineage | session_label, session_recent, session_history, session_reboot; `logs/ledger/` | `scripts/smoke_ledger.py` |
| Learning | learn_recall/suggest/use/recipe/note/list/forget; auto on find/click/nav | `scripts/smoke_learn.py` |
| Serve | `python3 -m mafia serve` :7430; `mafia api` stdio; `--headed` | README |

**Disk (gitignored under `logs/*`)**

| Path | Env override | Contents |
|------|--------------|----------|
| `logs/sessions/<name>/` | `MAFIA_SESSIONS_DIR` | storage_state + meta (named saves) |
| `logs/profiles/<name>/` | `MAFIA_PROFILES_DIR` | profile jars |
| `logs/ledger/` | `MAFIA_LEDGER_DIR` | events.jsonl + work.json |
| `logs/learn/` | `MAFIA_LEARN_DIR` | per-origin landmarks/recipes/notes |

---

## 2. Milestones

### M0 — Foundation — **DONE**
Linear: [EID-1061](https://linear.app/eidos-agi/issue/EID-1061) · milestone *M0 — Foundation*

- [x] Repo, TELOS, MIT, pyproject
- [x] Chromium engine of record
- [x] Multi-session contexts
- [x] Semantic walker + node_id click
- [x] SPA fixture proof (post-JS + click handler)
- [x] JSONL serve `:7430`

**Exit:** `scripts/smoke_spa.py` PASS.

---

### M0.5 — Autonomy stack (Knox + Hancock) — **DONE**
Linear: [EID-1077](https://linear.app/eidos-agi/issue/EID-1077)

| Work | Status | Notes |
|------|--------|-------|
| M0.5.1 knox_find | ✅ | Metadata only; secret_output suppressed |
| M0.5.2 knox_fill | ✅ | Unlock → fill page; password never in JSON |
| M0.5.3 knox_use dry-run | ✅ | Prove match without secret |
| M0.5.4 hancock_request/wait/pending | ✅ | STILL_PENDING ≠ go |
| M0.5.5 Optional gate | ✅ | knox_fill + require_hancock |
| M0.5.6 Docs | ✅ | README + TELOS + PLAN |

**Exit met:** first-class knox/hancock ops on Chromium session; no secret echo.

---

### M1 — Agent API hardened — **IN PROGRESS**
Linear milestone *M1 — Agent API hardened*

| Work | Linear | Status | Done when |
|------|--------|--------|-----------|
| M1.1 Op parity map vs Chrime | [EID-1062](https://linear.app/eidos-agi/issue/EID-1062) | Backlog | Doc: 1:1 / Pro-only / never |
| M1.2 Typed errors | [EID-1075](https://linear.app/eidos-agi/issue/EID-1075) | Backlog | All failures `{ok:false, code, error}` + suite |
| M1.3 Settle quality | [EID-1063](https://linear.app/eidos-agi/issue/EID-1063) | **Done** | networkidle/quiet; selector/text; honest quiescent; suite |
| M1.3b Node-id space | [EID-1092](https://linear.app/eidos-agi/issue/EID-1092) | **Done** | shared walk + ARIA roles; smoke_node_ids |
| M1.4 Wait helpers | [EID-1064](https://linear.app/eidos-agi/issue/EID-1064) | **Done** | wait text/selector/url_contains/ms + timeout code |
| M1.5 Fill / type / press | [EID-1065](https://linear.app/eidos-agi/issue/EID-1065) | **Done** | which + selector + node_id; suite; secret suppressed |
| M1.6 Breadcrumbs | [EID-1080](https://linear.app/eidos-agi/issue/EID-1080) | Backlog | Optional `_trace` hierarchy |
| M1.7 API suite ≥30 | [EID-1066](https://linear.app/eidos-agi/issue/EID-1066) | **Done** | run_api_suite.py 45 checks; dispatch + TCP modes |
| M1.8 Headed attach | [EID-1067](https://linear.app/eidos-agi/issue/EID-1067) | Backlog | `--headed` stable with API |
| M1.8b Portable monitor | [EID-1097](https://linear.app/eidos-agi/issue/EID-1097) | **Done** | headed boot suggests travel-class display; `~/eidos/mafia/settings.json` |

**Exit:** suite green; forms + SPA headless and headed.

---

### M2 — Session durability, lineage, learning — **CORE DONE** (polish open)
Linear milestone *M2 — Session & profile durability*

| Work | Linear | Status | Done when / proof |
|------|--------|--------|-------------------|
| M2.1 Persistent profiles | [EID-1068](https://linear.app/eidos-agi/issue/EID-1068) | **Done** | profile jars; smoke_sessions |
| M2.2 Session save/load | [EID-1076](https://linear.app/eidos-agi/issue/EID-1076) | **Done** | save/load/saves/delete; smoke_sessions |
| M2.3 Viewport / UA / device_scale | [EID-1069](https://linear.app/eidos-agi/issue/EID-1069) | **Partial** | open + live `viewport` op; device_scale/presets open |
| M2.4 Download / dialog policy | [EID-1081](https://linear.app/eidos-agi/issue/EID-1081) | **Partial** | dialog dismiss default (never hang); downloads accept; capture path open |
| M2.5 Clean shutdown | [EID-1082](https://linear.app/eidos-agi/issue/EID-1082) | **Partial** | quit flushes profiles; SIGTERM docs open |
| M2.6 Usage ledger + reboot | [EID-1078](https://linear.app/eidos-agi/issue/EID-1078) | **Done** | ledger + recent/history/reboot; smoke_ledger |
| M2.7 Site learning | [EID-1079](https://linear.app/eidos-agi/issue/EID-1079) | **Done** | learn_*; smoke_learn |

**Exit (durability core) — MET:** cookie+URL survive restart via save/profile.  
**Exit (lineage) — MET:** `session_recent` + `session_reboot` after process death.  
**Exit (learning) — MET:** second visit uses `learn_use` / recipes.  
**Still open:** viewport polish, dialog policy, SIGTERM docs, login-wall fixture polish.

---

### M3 — SPA acceptance (Gmail-class) — **OPEN**
Linear milestone *M3 — SPA acceptance (Gmail-class)*

| Work | Linear | Status | Done when |
|------|--------|--------|-----------|
| M3.1 Complex app fixture | [EID-1083](https://linear.app/eidos-agi/issue/EID-1083) | Backlog | Multi-route SPA + auth wall fixture |
| M3.2–M3.4 Gmail scour | [EID-1070](https://linear.app/eidos-agi/issue/EID-1070) | **Partial** | Runner shipped (`scripts/run_gmail_scour.py` + timing + profile + signal-file login wait). **Not green:** last run `auth=blocked_human_auth`, hits 0/6 — needs successful human login once. Speed vs Chrime **unproven**. |
| M3.5 Zero coordinate rule | (in EID-1070) | Partial | Runner uses only Mafia semantic ops (no xy) |

**Exit:** green report ≥5/6 themes with timing; human only for auth. **Not met yet.**

---

### M4 — Fleet (path to ~100) — **OPEN**
Linear milestone *M4 — Fleet path (~100)*

| Work | Linear | Status | Done when |
|------|--------|--------|-----------|
| M4.1 Session address model | [EID-1084](https://linear.app/eidos-agi/issue/EID-1084) | Backlog | Every op session-scoped; no global page footguns |
| M4.2 Concurrency model | [EID-1085](https://linear.app/eidos-agi/issue/EID-1085) | **Done** | Locked: single browser worker thread + op queue; client threads = sockets only; smoke_serve_n10 |
| M4.3 Fleet smoke N=10 | [EID-1071](https://linear.app/eidos-agi/issue/EID-1071) | **Done** | fleet_smoke.py N=10 distinct URLs + cookie isolation + close-one; smoke_serve_n10 |
| M4.4 Fleet smoke N=50 | [EID-1086](https://linear.app/eidos-agi/issue/EID-1086) | Backlog | Memory budget; no crash |
| M4.5 Fleet smoke N=100 | [EID-1072](https://linear.app/eidos-agi/issue/EID-1072) | Backlog | Green or dated budget+gap |
| M4.6 Kill/restart session | [EID-1087](https://linear.app/eidos-agi/issue/EID-1087) | **Partial** | close works; formalize + suite |
| M4.7 Resource limits | [EID-1088](https://linear.app/eidos-agi/issue/EID-1088) | **Done** | max_sessions (env MAFIA_MAX_SESSIONS); code max_sessions |

**Exit:** N=10 always green; N=100 green or written gap.

---

### M5 — Productization — **OPEN**
Linear milestone *M5 — Productization*

| Work | Linear | Status | Done when |
|------|--------|--------|-----------|
| M5.1 CLI polish | [EID-1089](https://linear.app/eidos-agi/issue/EID-1089) | Backlog | `mafia` on PATH; --help; version |
| M5.2 Install docs | [EID-1090](https://linear.app/eidos-agi/issue/EID-1090) | Backlog | Chrome channel vs bundled chromium |
| M5.3 CI | [EID-1073](https://linear.app/eidos-agi/issue/EID-1073) | **Done** | .github/workflows/ci.yml — smokes + suite + fleet + serve_n10 |
| M5.4 / WS-F Chrime boundary | [EID-1074](https://linear.app/eidos-agi/issue/EID-1074) | Backlog | SPA/Gmail claims → Mafia |
| M5.5 Linear/PLAN hygiene | [EID-1091](https://linear.app/eidos-agi/issue/EID-1091) | Backlog | PLAN §8 stays mirrored to Linear |
| M5.6 Optional Rust port | (defer) | Out | Only if Python is bottleneck |

**Exit:** cold machine install + all smokes in &lt;15 minutes from README.

---

## 3. Workstreams (parallelizable)

```
WS-A Control plane     M1 ops, suite, errors, settle/wait
WS-B Continuity        M2 remaining polish (viewport, dialogs, SIGTERM)
WS-C Real-app accept   M3 Gmail scour
WS-D Fleet             M4 concurrency
WS-E Packaging         M5 CI/docs
WS-F Chrime boundary   demote SPA claims; point to Mafia
```

**Shipped workstreams (do not re-open as greenfield):**
- WS-B core: durability + ledger + learning (M2.1–2.2, 2.6–2.7)
- Autonomy: Knox + Hancock (M0.5)

Agents can own WS-A/B-polish/D/E. Human-in-loop for WS-C (Gmail auth).

---

## 4. Technical decisions (locked unless amended)

| Decision | Choice | Why |
|----------|--------|-----|
| Browser | Chromium via Playwright | SPA now; system Chrome channel |
| Language (v0–M4) | Python 3.11+ | Speed of iteration; port later if needed |
| Public API | JSONL TCP + stdio | Matches agent habits / Chrime |
| Isolation | BrowserContext per session | Cookies isolated |
| Profile durability | storage_state jars (not full user_data_dir) | Multi-session one browser process |
| Headed | Optional flag | Attach, not product identity |
| Node-ids | In-page stamp `data-mafia-id` | Same walk for snapshot/click |
| Secrets | Never in responses/ledger/learn | Knox boundary |
| Continuity | saves + profiles + ledger + learn | Compounding autonomy |
| Port default | 7430 | Chrime keeps 7420 |

**Open decisions**
- One browser many contexts vs process-per-N-sessions (still open at N=100)
- Whether to expose raw CDP as escape hatch (default: no)

**Locked (M4.2)**  
- Sync Playwright + **one worker thread** owning the browser; TCP clients enqueue ops. Never multi-thread Playwright.

---

## 5. Risk register

| Risk | Impact | Mitigation |
|------|--------|------------|
| Gmail bot walls / 2FA | Blocks M3 | Human headed login; agent post-auth only |
| Playwright sync + multi-thread | Races | One browser thread; queue ops per process |
| Memory at N=100 | OOM | Context recycling; multi-browser; headless shell |
| Node-id instability after SPA re-render | Bad clicks | Re-walk before click; learn_use text fallback |
| Cold restarts waste agent time | No compounding | profiles + ledger reboot + site learn (shipped) |
| Scope creep into “own Blink” | Delay SPA | Chromium is intentional substrate |
| Chrime still claims SPA | Confusion | WS-F / EID-1074 |

---

## 6. Success metrics

| Metric | Now | M1 | M3 | M4 |
|--------|-----|----|----|-----|
| SPA fixture green | ✅ | required | required | required |
| Session save/reboot/learn smokes | ✅ | required | required | required |
| Real Chromium suite cases | 4 smokes | ≥30 | ≥50 | ≥50 |
| Gmail themes hit | — | — | ≥5 of 6 | ≥5 of 6 |
| Concurrent sessions smoke | 2 | 2 | 2 | 10 / 50 / 100 |
| Dual-brain ops | 0 | 0 | 0 | 0 |

---

## 7. Suggested execution order (next)

**Already shipped (do not re-plan as greenfield)**  
M0/M0.5, node-ids (1092), serve queue (1085), wait/settle (1063–1064), suite (1066), fleet N=10 (1071), max_sessions (1088), CI yaml (1073), continuity stack (1068/1076/1078/1079), chrome skin pack, Gmail **runner** (1070 partial).

**Immediate**
1. [EID-1070](https://linear.app/eidos-agi/issue/EID-1070) — **one successful human Gmail login** then re-run with profile; publish timing (speed claim only after this)  
2. Walker: iframes + shadow DOM (Gmail toolbar still incomplete without it)  
3. [EID-1074](https://linear.app/eidos-agi/issue/EID-1074) Chrime boundary docs  
4. Fleet N=50 / N=100 or dated gap (1086/1072)  

---

## 8. Linear mapping (execution board)

**Project:** [Mafia](https://linear.app/eidos-agi/project/mafia)  
**Rule:** This file is narrative source of truth; Linear holds IDs + status.  
**Do not file SPA/Gmail execution on Chrime** unless demotion/docs (WS-F).

### Milestone → issues

| Milestone | Issues |
|-----------|--------|
| M0 Foundation | EID-1061 ✅ |
| M0.5 Autonomy | EID-1077 ✅ |
| M1 API | EID-1062, **1063 ✅**, **1092 ✅**, **1064 ✅**, **1065 ✅**, **1066 ✅**, 1067, 1075, 1080, 1097 ✅ |
| M2 Continuity | EID-1068 ✅, 1076 ✅, 1069~, 1081~, 1082~, 1078 ✅, 1079 ✅ |
| M3 Gmail-class | EID-1083, **1070 ~** (runner only), 1093 ✅ ARIA |
| M4 Fleet | EID-1084, **1085 ✅**, **1071 ✅**, 1086, 1072, 1087~, **1088 ✅** |
| M5 Product | EID-1089, 1090, **1073 ✅**, 1074, 1091 |

`~` = partial / runner-not-green

### Done checklist (do not re-implement)

| ID | Title | Commit / proof |
|----|-------|----------------|
| EID-1061 | M0 foundation | smoke_spa |
| EID-1077 | Knox + Hancock | f8180eb |
| EID-1068 | Persistent profiles | 7453b80 + smoke_sessions |
| EID-1076 | Session save/load | 7453b80 + smoke_sessions |
| EID-1078 | Ledger + reboot | 18573d8 + smoke_ledger |
| EID-1079 | Site learning | 0477fd1 + smoke_learn |
| EID-1092 | Node-id unification | smoke_node_ids + login-wall |
| EID-1085 | Serve single-thread queue | smoke_serve_n10 |
| EID-1063–1066 | settle/wait/fill/suite | 0aceffa |
| EID-1071 / 1088 / 1073 | fleet N=10, max_sessions, CI | 0aceffa |
| EID-1093 | ARIA role walker | 0aceffa |
| (skin) | Chrome theme + NTP | 131679c |
| EID-1070 | Gmail runner only | 48594e4 + login-wait fix — **auth not green** |

### Agent continuity stack (product requirement — shipped)

| Need | Mechanism | Linear |
|------|-----------|--------|
| Reloadable sessions | save/load + profiles | EID-1068, EID-1076 |
| Track every use | ledger events + work index | EID-1078 |
| Reboot prior work | session_recent / session_reboot | EID-1078 |
| Next surf easier | learn_suggest / learn_use / recipes | EID-1079 |

---

## 9. Smokes (run before claiming green)

```sh
cd ~/repos-eidos-agi/mafia
python3 scripts/smoke_spa.py       # SPA + multi-session
python3 scripts/smoke_sessions.py  # save/load + profiles
python3 scripts/smoke_ledger.py    # history + reboot
python3 scripts/smoke_learn.py     # landmarks + learn_use
python3 scripts/smoke_node_ids.py  # find_text≡click with hidden inputs
python3 scripts/smoke_serve_n10.py # public TCP API N=10
python3 scripts/run_api_suite.py   # ≥30 / 45 checks
MAFIA_FLEET_N=10 python3 scripts/fleet_smoke.py
# Gmail (human login once; not green until auth passes):
#   MAFIA_SKIN=on python3 scripts/run_gmail_scour.py --headed --channel '' --profile gmail-work
#   touch logs/gmail-login-done   # after inbox visible
```
