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
5. A strategy condition may not be connected live from `[HYPOTHETICAL]`
   evidence. Do not use an arbitrary five-trading-session exception. Require a
   passing `[PROD_REPLAY]` first. After it passes, an explicit owner approval
   naming the strategy, exact condition, quantity, and
   `permanent`/`always-on`/`상시` duration has no automatic expiry and requires
   no daily reapproval. A fixed duration applies only when the owner specified
   it. Existing hard stops, force exit, shadow comparison, and audit recording
   must remain enabled.
6. Any production-code change invalidates reports made for an older code hash.
7. AI assistants quote generated reports; they do not manually calculate or
   rewrite performance numbers.
8. Before quoting any trading result, run `RUN\trading_report_truth_gate_v1.py`.
   A nonzero result forbids quoting its numbers; report only its provenance and
   exact missing evidence. Performance is quotable from `[PROD_REPLAY]` only
   when the report explicitly proves `performance_scope=FULL_ENTRY_EXIT`.

No evidence, no verified result. Deployment authority never upgrades evidence
provenance.

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
