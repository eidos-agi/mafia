# Mafia — Telos

## Philosophy

**Mafia is a real Chromium browser built so AIs can steer it — including many sessions at once.**

Sibling of Chrime: Chrime stays the light agent document surface. Mafia is the heavy that
runs the real web (SPA, cookies, Gmail-class work). One engine of record per session. Agent
API primary. Human may attach a headed window; humans are not the control path.

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

### api-complete-control
must: Steer via JSONL alone.
case: multi-op script without human clicks.

## Requirements

### spa-snapshot — open → green when fixture case passes
### multi-session-api — open → green when 2 contexts isolated
### fleet-path — open (path to ~100 sessions)
### gmail-scour — open (acceptance on Mafia, not Chrime)

## Anti-requirements

- Dual StaticEngine + browser truth for one session
- Claiming SPA green on Chrime
