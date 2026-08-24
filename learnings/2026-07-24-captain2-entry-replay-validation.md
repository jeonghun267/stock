# 2026-07-24 Captain2 early entries were either blocked or noisy

## Approach
1. Trace the EARLY call path and confirm that the 10-billion-KRW common gate was accidentally restored with the reverse-MA gate.
2. Inspect both the selector publication count and the broker subscription cap instead of treating the 200-code file as proof of 200 fresh streams.
3. Replay the July 23 and July 24 one-second captures under identical entry rules.
4. Compare the old 10-billion gate, an unrestricted bypass, and a 1-billion minimum-liquidity gate.
5. Count PULL RESET, BUY_READY, and RESET_FAILED events and compare their elapsed times with the configured lane window.
6. Evaluate EARLY for 20 minutes, other scalp lanes for 60 minutes, and exclude end-of-day returns.

## Not done and why
- Did not restart Captain2 or the broker gateway automatically during market hours because that affects live orders and other strategies' feeds.
- Did not duplicate the box-break strategy inside Captain2 because GAPTUKI_FLOW already owns that state machine.
- Did not change sells, hard cuts, the daily buy cap, or the six-slot policy because the defect was confined to entry discovery and subscriptions.

## Reuse rule
When relaxing an opening-auction liquidity gate, replay multiple days with the real scalp holding window and verify stream freshness separately before enabling it live.

## Related files
- RUN/CAPTAIN2_MONEYFLOW_ENGINE_V1.py
- RUN/money_flow_board_v1.py
- RUN/broker_gateway_v1.py

## Theme-leader priority follow-up
- Use RUN/theme_leader.py as the single canonical source; do not depend on a stale board crown field.
- Treat both canonical signals as one priority group, never as a mandatory entry gate.
- Rank inside that group by recent signed net-buy money per second, then buy dominance.
- Keep non-theme stocks eligible and preserve the EARLY liquidity bypass and normal 10-billion-KRW gate.
- Validate both the live source overlap and synthetic selection order before restart.
