"""Forward, order-zero paper ledger for high-range quality comparisons.

It watches the existing S01-S06 signal outputs, opens one-share virtual
positions, and runs the current common hold/sell engine.  No broker object is
imported and no order intent is submitted.  Results remain [HYPOTHETICAL]
because the shared micro snapshot does not contain every production-derived
exit observation.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, time as wall_time, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping

RUN_DIR = Path(__file__).resolve().parent
if str(RUN_DIR) not in sys.path:
    sys.path.insert(0, str(RUN_DIR))

from strategy_common_hold_sell_v1 import (
    HoldSellObservation, HoldSellState, StrategyId, UnifiedHoldSellEngine,
)
from strategy_high_range_quality_policy_v1 import (
    enrich_candidates, load_quality_maps, rank_candidates,
)

ROOT = Path(__file__).resolve().parents[1]
KST = timezone(timedelta(hours=9))
STATE_PATH = ROOT / "data" / "shadow" / "high_range_paper_ledger_state.json"
EVENT_DIR = ROOT / "data" / "shadow"
SNAPSHOT_PATH = ROOT / "IPC" / "live_micro_snapshot.json"
SOURCES = {
    "S01": ROOT / "data" / "strategy_01_open_surge_signal_v2.json",
    "S02": ROOT / "data" / "strategy_02_low_buy_signal_v1.json",
    "S03": ROOT / "data" / "strategy_03_골짜기_급반등_signal_v1.json",
    "S04": ROOT / "data" / "strategy_04_pullback_signal_v1.json",
    "S05": ROOT / "data" / "strategy_05_base_breakout_signal_v1.json",
    "S06": ROOT / "data" / "strategy_06_crash_low_chase_state_v1.json",
}
EXIT_IDS = {
    "S01": StrategyId.S01_OPEN_SURGE,
    "S02": StrategyId.S02_LOW_BUY_SELL_EXHAUSTION,
    "S03": StrategyId.VALLEY,
    "S04": StrategyId.S04_PULLBACK,
    "S05": StrategyId.S05_BASE_BREAKOUT,
    "S06": StrategyId.VALLEY_MORNING_CRASH,
}


def _read(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def _atomic(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


def _append(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(dict(value), ensure_ascii=False, sort_keys=True) + "\n")


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _code(value: Any) -> str:
    text = str(value or "").strip()
    return text.zfill(6) if text.isdigit() else text


def _signal_rows(strategy: str, payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    pools: list[Any] = []
    for key in ("signals", "entry_v3_signals", "shadow_signals"):
        pools.extend(payload.get(key) or [])
    if strategy == "S06":
        pools.extend(payload.get("history") or [])
        pools.extend((payload.get("chase") or {}).values())
    rows: list[dict[str, Any]] = []
    for raw in pools:
        if not isinstance(raw, Mapping):
            continue
        action = str(raw.get("action") or raw.get("event") or raw.get("phase") or "").upper()
        if not any(token in action for token in ("BUY_READY", "ENTRY_READY", "BUY_FILLED", "ENTERED")):
            continue
        code = _code(raw.get("code"))
        price = _number(raw.get("price") or raw.get("entry_price"))
        ts = str(raw.get("ts") or raw.get("observed_at") or raw.get("entry_at") or "")
        if code and price > 0 and ts:
            row = dict(raw)
            row.update({"code": code, "price": price, "signal_ts": ts})
            rows.append(row)
    return rows


class PaperLedger:
    def __init__(self, root: Path = ROOT) -> None:
        self.root = root
        self.state_path = root / "data" / "shadow" / "high_range_paper_ledger_state.json"
        self.event_dir = root / "data" / "shadow"
        self.snapshot_path = root / "IPC" / "live_micro_snapshot.json"
        self.sources = {key: root / path.relative_to(ROOT) for key, path in SOURCES.items()}
        self.state = _read(self.state_path) or {
            "schema": "high_range_paper_ledger_v1",
            "date": "",
            "seen_signals": [],
            "positions": {},
        }
        self.engine = UnifiedHoldSellEngine()

    def _reset_day(self, now: datetime) -> None:
        day = now.strftime("%Y%m%d")
        if self.state.get("date") != day:
            self.state = {
                "schema": "high_range_paper_ledger_v1",
                "date": day,
                "provenance": "[HYPOTHETICAL]",
                "performance_scope": "SHADOW_FORWARD_ENTRY_EXIT_INCOMPLETE_INPUTS",
                "mode": "SHADOW_ORDER_ZERO",
                "order_qty": 0,
                "live_eligible": False,
                "seen_signals": [],
                "positions": {},
            }

    def process_once(self, now: datetime | None = None) -> list[dict[str, Any]]:
        now = now or datetime.now(KST)
        if now.tzinfo is None:
            now = now.replace(tzinfo=KST)
        self._reset_day(now)
        day = now.strftime("%Y%m%d")
        events: list[dict[str, Any]] = []
        snapshot = _read(self.snapshot_path)
        points = snapshot.get("codes") or {}
        quality, quality_status = load_quality_maps(self.root, now)
        seen = set(self.state.get("seen_signals") or [])
        positions: dict[str, Any] = self.state.setdefault("positions", {})

        for strategy, source_path in self.sources.items():
            payload = _read(source_path)
            signals = _signal_rows(strategy, payload)
            enriched = enrich_candidates(strategy, signals, quality, quality_status)
            ranked = rank_candidates(strategy, enriched)
            for row in ranked:
                signal_key = f"{strategy}:{row['code']}:{row['signal_ts']}"
                if signal_key in seen:
                    continue
                seen.add(signal_key)
                code = row["code"]
                point = points.get(code) or {}
                entry_price = _number(point.get("best_ask_px") or point.get("cur") or row.get("price"))
                if entry_price <= 0:
                    continue
                position_id = signal_key
                hold = HoldSellState(
                    position_id=position_id,
                    strategy_id=EXIT_IDS[strategy],
                    code=code,
                    quantity=1,
                    entry_price=Decimal(str(entry_price)),
                    entry_at=now,
                    entry_lane=str(row.get("entry_lane") or row.get("lane") or ""),
                )
                positions[position_id] = {
                    "strategy": strategy,
                    "code": code,
                    "quantity": 1,
                    "hold_state": hold.to_dict(),
                    "quality": {key: value for key, value in row.items() if key.startswith("hr_")},
                    "original_position": row.get("original_position"),
                    "shadow_position": row.get("shadow_position"),
                    "source_signal": str(source_path),
                    "status": "OPEN",
                }
                events.append({
                    "event": "VIRTUAL_BUY", "ts": now.isoformat(timespec="milliseconds"),
                    "strategy": strategy, "code": code, "price": entry_price, "quantity": 1,
                    "position_id": position_id, "mode": "SHADOW_ORDER_ZERO",
                    "provenance": "[HYPOTHETICAL]", "live_eligible": False, "order_qty": 0,
                    "quality": positions[position_id]["quality"],
                })

        for position_id, saved in list(positions.items()):
            if saved.get("status") != "OPEN":
                continue
            point = points.get(saved.get("code")) or {}
            price = _number(point.get("best_bid_px") or point.get("cur"))
            if price <= 0:
                continue
            buy_cum = _number(point.get("buy_money_cum"))
            sell_cum = _number(point.get("sell_money_cum"))
            total = buy_cum + sell_cum
            buy_ratio = buy_cum / total if total > 0 else 0.60
            hold = HoldSellState.from_dict(saved["hold_state"])
            decision = self.engine.evaluate(hold, HoldSellObservation(
                observed_at=now,
                price=Decimal(str(price)),
                buy_ratio_recent=Decimal(str(max(0.0, min(1.0, buy_ratio)))),
                che_str=Decimal(str(max(0.0, _number(point.get("che_str"))))),
            ))
            saved["hold_state"] = hold.to_dict()
            saved["last_price"] = price
            saved["last_observed_at"] = now.isoformat(timespec="milliseconds")
            if decision.should_sell:
                saved.update({
                    "status": "CLOSED", "exit_price": price,
                    "exit_at": now.isoformat(timespec="milliseconds"),
                    "exit_reason": decision.reason,
                    "gross_return_pct": round((price / float(hold.entry_price) - 1.0) * 100.0, 6),
                    "net_return_pct_after_0_47_cost": round((price / float(hold.entry_price) - 1.0) * 100.0 - 0.47, 6),
                })
                events.append({
                    "event": "VIRTUAL_SELL", "ts": saved["exit_at"],
                    "strategy": saved["strategy"], "code": saved["code"],
                    "price": price, "quantity": 1, "reason": decision.reason,
                    "position_id": position_id, "mode": "SHADOW_ORDER_ZERO",
                    "provenance": "[HYPOTHETICAL]", "live_eligible": False, "order_qty": 0,
                    "performance_scope": "SHADOW_FORWARD_ENTRY_EXIT_INCOMPLETE_INPUTS",
                })

        self.state["seen_signals"] = sorted(seen)
        self.state["updated_at"] = now.isoformat(timespec="milliseconds")
        _atomic(self.state_path, self.state)
        for event in events:
            _append(self.event_dir / f"high_range_paper_events_{day}.jsonl", event)
        return events


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--interval", type=float, default=2.0)
    args = parser.parse_args()
    ledger = PaperLedger()
    while True:
        now = datetime.now(KST)
        ledger.process_once(now)
        if args.once or now.time() >= wall_time(15, 36):
            return 0
        time.sleep(max(0.5, args.interval))


if __name__ == "__main__":
    raise SystemExit(main())
