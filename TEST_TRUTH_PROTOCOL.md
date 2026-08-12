# Shared Test Truth Protocol

This file is the single truth policy shared by Codex, Claude, scripts, and
people working in this repository.

## Allowed provenance labels

- `[BROKER_FILL]`: an order/fill read directly from the broker journal.
- `[PROD_REPLAY]`: the current production engine replayed from a complete,
  hash-verified audit stream captured at the production decision boundary.
- `[HYPOTHETICAL]`: synthetic inputs, reconstructed indicators, handwritten
  simulations, chart inference, or proposed conditions.
- `[UNVERIFIED]`: missing inputs, broken hashes, conflicting runs, or an
  incomplete production path.

## Non-negotiable rules

1. A replay or reconstruction is never an actual fill.
2. A production replay must import the production engine and use only the
   captured observation fields; indicators may not be reconstructed.
3. Missing fields, time disorder, a broken hash chain, or a mid-position
   capture must fail closed as `[UNVERIFIED]`.
4. Every report records the source audit hash, capture-engine hash,
   replay-engine hash, exact command, code, date, and whether code changed.
5. A strategy condition may not normally be connected live from
   `[HYPOTHETICAL]` evidence. The repository owner may approve a fast live
   canary for immediate confirmation only when each approval explicitly names
   one strategy and the exact condition. A canary is limited to one share,
   one strategy/condition at a time, and the current trading day; it expires
   at process end. Existing hard stops, force exit, shadow comparison, and
   audit recording must remain enabled. The result stays `[UNVERIFIED]` until
   a passing `[PROD_REPLAY]` exists and must never be described as validated.
6. Any production-code change invalidates reports made for an older code hash.
7. AI assistants quote generated reports; they do not manually calculate or
   rewrite performance numbers.

No evidence, no verified result. A fast live canary changes deployment
authority only and never upgrades evidence provenance.

## Storage and reproducible commands

- Raw decision audit:
  `C:\stock_bot\data\audit\hold_sell\YYYYMMDD\STRATEGY\CODE__POSITION.jsonl`
- Verified replay report:
  `C:\stock_bot\reports\verified_replay\YYYYMMDD\*.json`
- Replay:
  `python RUN\verified_hold_sell_replay_v1.py --audit "<audit.jsonl>"`
- Approval validation:
  `python RUN\verified_replay_gate_v1.py --approval "<approval.json>"`

An approval file is created only after the user explicitly approves a specific
report hash. Data not captured at the production boundary cannot be recreated
later as `[PROD_REPLAY]`.
