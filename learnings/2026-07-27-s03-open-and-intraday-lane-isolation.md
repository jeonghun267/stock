# 2026-07-27 Capture intraday crash rebounds in S03 without changing the proven opening-crash behavior

## Approach
1. Replayed 043260 from the 2026-07-27 one-second raw capture and separated previous-close drop from rolling intraday drawdown.
2. Confirmed that the existing OPEN_CRASH detector arms only at -4% versus previous close and exits its signal process at 09:21.
3. Added an independent INTRADAY_CRASH state machine with a 15-minute high-to-low drawdown, stable-low rebound, exact buy-flow persistence, spread, and microprice gates.
4. Kept both lanes in one S03 signal process but tagged every row with entry_lane and validated each lane's time and fields again in the signal contract.
5. Reused the existing S03 rotation and common hold/sell engine, with the two-entry-per-code and six-distinct-code limits shared across lanes.
6. Verified the 17,410 KRW raw-flow candidate, five new tests, ten existing S03 tests, and 139 cross-strategy/common/preflight tests while confirming real order attempts remained zero.

## What was not done + why
- Did not merely extend the existing OPEN_CRASH ENTRY_END. Reason: 043260 fell only -0.86% versus previous close, so the old -4% arming rule would still miss it and changing that rule would alter proven morning behavior.
- Did not copy Strategy 05's base-breakout detector. Reason: this event is a rolling intraday crash and low reclaim, not a 30-minute base breakout and retest.
- Did not invent historical best-bid/ask data. Reason: the old one-second capture has exact buy/sell counters but no top-of-book prices or quantities, so the final 35bp and microprice gate must remain live-only and fail-closed.
- Did not change the common hold/sell engine or approval/OFF flags. Reason: the user approved only the buy path, and real-account authority was outside scope.

## Reusable rule
When extending a validated time-specific strategy, add a separate lane state machine and make the signal contract revalidate lane-specific time and fields; do not widen the old detector in place.

## Related files/commits
- RUN/strategy_03_intraday_rebound_v1.py
- RUN/???_???.py
- RUN/strategy_03_signal_contract_v1.py
- RUN/strategy_03_rotation_engine_v1.py
- tests/test_strategy_03_intraday_rebound_v1.py
- DOCS/???_??.md
