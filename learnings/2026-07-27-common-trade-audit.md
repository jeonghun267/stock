# 2026-07-27 Shared strategies lacked durable trade-quality evidence

## Approach
1. Inspect the shared rotation state lifecycle from signal selection through archive cleanup.
2. Reuse the existing position history and event CSV instead of adding another live process.
3. Persist entry candidate rank, running MFE/MAE, and post-exit 15/30/60-minute snapshots.
4. Verify the shared change against every S02-S05 strategy and shared-slot tests.

## Deliberately not changed
- Buy and sell thresholds were not changed. Reason: measurement must not alter live decisions.
- A separate observer process was not added. Reason: the shared engine already owns exact fills and snapshots.

## Reusable rule
When several strategies share execution, add passive metrics at the shared fill lifecycle and keep decision logic untouched.

## Related files
- RUN/strategy_01_rotation_engine_v2.py
- tests/test_strategy_01_rotation_v2.py
- RUN/hidden/SAFEPLUS_STRATEGY03_SIGNAL_ASCII.cmd
