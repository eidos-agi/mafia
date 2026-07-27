# Mafia — Telos

## Philosophy

**Mafia is a real Chromium browser wrapped for AI steering** — not a Playwright tutorial,
not agent-browser with a new name.

Sibling of **Chrime** (light document API). Mafia is the heavy path: SPA, cookies, real apps,
many sessions. Chromium is the engine; **Mafia is the control plane** — agent-native ops
**plus** the autonomy stack that makes steering possible on the real web:

1. **Browser control** — navigate / settle / snapshot / click(node_id) on a real document  
2. **Knox** — credentials without secrets in agent transcripts  
3. **Hancock** — human sign-off before consequential actions  

Without (2) and (3), agents cannot safely log in or take irreversible actions → **not
autonomous, just automated clicking.** V1 deliberately uses Chromium as substrate (wrapper);
tightness comes from integration and policy, not from reimplementing Blink.

## Invariants

### real-browser
must: Engine of record executes JS; agent snapshot sees post-JS DOM.
case: navigate JS fixture; find_text sees POST-JS-MARKER.

### one-engine-of-record
must: Agent ops hit the same Chromium document the session owns — no parallel static fetch.
case: JS click mutates DOM; subsequent snapshot shows mutation.

### agent-native-interface
must: Primary control is semantic DOM + node-ids, not pixels/coordinates.
case: click by node_id completes without mouse coordinates.

### multi-session
must: Multiple isolated sessions (contexts) concurrently.
case: open 2 sessions; cookies/state do not leak.

### session-durability
must: Sessions are easily stored and reloadable — cookies, storage, and URL survive
process restart via named saves and profile jars (no re-login from scratch every run).
case: set cookie → session_save → close → session_load (or profile close → new process
→ session_open with profile) restores cookie + URL.

### session-lineage
must: Every use of a session is tracked so an agent can discover and reboot prior work
without tribal knowledge (history + recent work index + one-shot reboot).
case: labeled session ops → session_history shows navigate/close; new process
session_reboot restores cookies + URL for that work.

### knox-autonomy
must: Agents can find/fill credentials into the session document without secrets appearing in
API responses or logs; Touch ID remains Knox's unlock boundary.
case: knox_find returns metadata only (secret_output suppressed); knox_fill injects into page
without password in JSON.

### hancock-autonomy
must: Consequential actions can require Hancock; STILL_PENDING is not approval; only
APPROVED_AND_RAN / AUTO_APPROVED_AND_RAN (or wait exit 0) is go.
case: hancock_request returns id; wait does not invent approval; denied/pending blocks knox_fill when gated.

### api-complete-control
must: Steer via JSONL alone (browser + knox + hancock ops).
case: multi-op script without human clicks on the page (human may only sign Hancock / Touch ID).

## Requirements

### spa-snapshot — open → green when fixture case passes
### multi-session-api — open → green when 2 contexts isolated
### session-durability — open → green (`scripts/smoke_sessions.py`)
### session-lineage — open → green (`scripts/smoke_ledger.py`)
### fleet-path — open (path to ~100 sessions)
### gmail-scour — open (acceptance on Mafia, not Chrime)

## Anti-requirements

- Dual StaticEngine + browser truth for one session
- Claiming SPA green on Chrime
