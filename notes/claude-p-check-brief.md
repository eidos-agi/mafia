# Claude-P brief — Mafia check only (do not fix around)

**Mode:** review / estimate / challenge. **Not** implement. **Not** patch. **Not** refactor.

If something is wrong, **name it**. Do not invent a workaround, dual path, soft fail, or “good enough for now” that hides the bug. Daniel will decide what ships next.

---

## Repo

```
~/repos-eidos-agi/mafia
```

Read first:

1. `PLAN.md` — especially §0 thesis, §2 milestones, §7 next, **§8 Linear map**
2. `TELOS.md` — invariants (real-browser, durability, lineage, learning, knox, hancock)
3. `README.md` — ops surface
4. Smokes (run them if you can; report pass/fail honestly):
   - `python3 scripts/smoke_spa.py`
   - `python3 scripts/smoke_sessions.py`
   - `python3 scripts/smoke_ledger.py`
   - `python3 scripts/smoke_learn.py`

Linear project: **Mafia** (Eidos AGI). PLAN §8 has IDs.

---

## Hard rules

1. **Do not implement.** No code changes, no commits, no “quick fixes while I’m here.”
2. **Do not fix around.** No:
   - dual engines / static fallback for SPA
   - sleep-only settle pretending to be real
   - re-auth every run instead of profiles
   - coordinate/pixel clicks instead of node-ids
   - secret echo “just for debugging”
   - “STILL_PENDING means go”
   - papering over Playwright races with retries that hide root cause
3. **Do not replan shipped work** as greenfield:
   - M0 foundation — EID-1061
   - M0.5 Knox+Hancock — EID-1077
   - M2.1 profiles — EID-1068
   - M2.2 save/load — EID-1076
   - M2.6 ledger+reboot — EID-1078
   - M2.7 site learning — EID-1079  
   Challenge only if you find a **real hole** in the claim (smoke fails, invariant violated, secret leak, etc.).
4. **Chrime is out of scope** for SPA/Gmail green. Boundary only: WS-F / EID-1074.

---

## What to answer

1. **Is the next-order right** for daily agent use?  
   PLAN §7: suite (EID-1066) → wait (EID-1064) → settle polish (EID-1063) → CI (EID-1073) → Chrime boundary (EID-1074) → fleet N=10 (EID-1071) → Gmail (EID-1070).  
   Reorder only with a reason grounded in risk.

2. **Honest person-days** (one senior agent/dev, this machine, no heroics) for:
   - “daily usable” (suite + wait + CI + N=10)
   - “Gmail-class green” (EID-1070 + human auth)
   - “fleet N=100 or written gap” (EID-1072)

3. **Under-scoped / missing** for real agent autonomy — only real gaps, not feature tourism. Examples of the kind of thing that matters: concurrency races, headed deadlock, cookie jar security, learn memory poisoning, ledger not enough to reboot, Gmail 2FA wall.

4. **Cut list** — what to drop or defer without lying about green.

5. **Broken claims** — if PLAN or README claims something the code does not do, say so with file:line. Do not “fix around” the claim; flag it.

---

## Output format (keep it short)

```
## Verdict
one paragraph: ready for daily agents? yes/no/partial — why

## Smoke results
pass/fail each

## Next order (yours)
numbered; only if different from PLAN §7 say why

## Person-days
table: daily usable | gmail-class | fleet-100

## Real holes
- bullet: claim vs reality, file refs

## Do not do (anti-workarounds)
- bullets if you see temptation in the plan

## Cut / defer
- bullets
```

No architecture redesign. No new product name. No dual-brain. End when the check is done.
