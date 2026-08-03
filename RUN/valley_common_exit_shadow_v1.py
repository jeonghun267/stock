# -*- coding: utf-8 -*-
"""Compare the shared Captain2 exit against Valley MORNING_CRASH, order-free.

The active Valley strategy remains the control.  This observer mirrors only
confirmed MORNING_CRASH positions from its ledger, evaluates StrategyId.BASE,
and records a hypothetical exit no later than 09:30 KST.  It never imports a
broker or sends an order.
"""

from __future__ import annotations

import csv
import json
import sys
import time
from collections import defaultdict, deque
from datetime import datetime, time as day_time
from decimal import Decimal
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

RUN_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(RUN_DIR))

from captain2_common_hold_sell_v1 import (  # noqa: E402
    HoldSellAction,
    HoldSellObservation,
    HoldSellState,
    StrategyId,
    UnifiedHoldSellEngine,
)


ROOT = Path(r"C:\stock_bot")
LEDGER = ROOT / "data" / "valley_hunter_live_ledger.json"
SNAPSHOT = ROOT / "IPC" / "live_micro_snapshot.json"
BOARD = ROOT / "data" / "micro_rank_board.json"
BARS_1M = ROOT / "data" / "돈맥_1분봉.json"
VALLEY_LOG = ROOT / "LOG" / "valley_hunter_live.csv"
STATE_PATH = ROOT / "data" / "shadow" / "valley_common_exit_shadow_state.json"
OUTPUT_DIR = ROOT / "data" / "shadow"
FORCE_EXIT = day_time(9, 30)
END_TIME = day_time(9, 31)
STALE_SEC = 8.0
LOOP_SEC = 2.0
KST = ZoneInfo("Asia/Seoul")

BUY_FEE = Decimal("0.00015")
SELL_FEE = Decimal("0.00015")
SELL_TAX = Decimal("0.0018")

OUTPUT_COLUMNS = [
    "date", "entry_id", "event", "code", "name", "entry_at", "entry_price",
    "observed_at", "signal_price", "gross_return_pct",
    "net_before_slippage_pct", "reason", "data_quality", "order_sent",
]


def read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return default


def write_json_atomic(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    tmp.replace(path)


def output_path(day: str) -> Path:
    return OUTPUT_DIR / f"valley_common_exit_shadow_{day}.csv"


def append_output(day: str, row: dict[str, Any]) -> None:
    path = output_path(day)
    path.parent.mkdir(parents=True, exist_ok=True)
    is_new = not path.exists()
    with path.open("a", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_COLUMNS)
        if is_new:
            writer.writeheader()
        writer.writerow({key: row.get(key, "") for key in OUTPUT_COLUMNS})


def parse_local(day: str, clock: str) -> datetime:
    return datetime.strptime(f"{day} {clock}", "%Y%m%d %H:%M:%S").replace(tzinfo=KST)

def as_kst(value: datetime) -> datetime:
    return value.replace(tzinfo=KST) if value.tzinfo is None else value.astimezone(KST)


def latest_entry_times(day: str) -> dict[str, datetime]:
    found: dict[str, datetime] = {}
    if not VALLEY_LOG.exists():
        return found
    with VALLEY_LOG.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            if (
                row.get("일자") == day
                and row.get("방향") == "BUY"
                and row.get("진입출처") == "MORNING_CRASH"
                and row.get("주문결과") != "GHOST"
            ):
                code = str(row.get("종목코드") or "").zfill(6)
                found[code] = parse_local(day, str(row.get("시각")))
    return found


def active_morning_positions(day: str) -> list[dict[str, Any]]:
    ledger = read_json(LEDGER, {})
    if str(ledger.get("date") or "") != day:
        return []
    entry_times = latest_entry_times(day)
    positions = []
    for raw_code, slot in (ledger.get("slots") or {}).items():
        if not isinstance(slot, dict):
            continue
        if slot.get("entry_gate") != "MORNING_CRASH" or not slot.get("pos"):
            continue
        code = str(raw_code).zfill(6)
        entry_price = float(slot.get("entry") or 0)
        quantity = int(slot.get("qty") or 0)
        if entry_price <= 0 or quantity <= 0:
            continue
        positions.append({
            "code": code,
            "name": str(slot.get("name") or code),
            "entry_price": entry_price,
            "quantity": quantity,
            "entry_at": entry_times.get(code) or datetime.now(KST),
            "re": int(slot.get("re") or 0),
        })
    return positions


def entry_id(day: str, position: dict[str, Any]) -> str:
    stamp = position["entry_at"].strftime("%H%M%S")
    return f"{day}-{position['code']}-{stamp}-R{position['re']}"


class SideWindows:
    def __init__(self) -> None:
        self.rows: dict[str, deque[tuple[datetime, float, float]]] = defaultdict(deque)

    def add(self, code: str, observed_at: datetime, buy_money: float, sell_money: float) -> None:
        rows = self.rows[code]
        if rows and (buy_money < rows[-1][1] or sell_money < rows[-1][2]):
            rows.clear()
        rows.append((observed_at, buy_money, sell_money))
        while rows and (observed_at - rows[0][0]).total_seconds() > 40:
            rows.popleft()

    def rates(self, code: str, seconds: int) -> tuple[float, float] | None:
        rows = self.rows.get(code)
        if not rows or len(rows) < 2:
            return None
        end = rows[-1]
        eligible = [row for row in rows if (end[0] - row[0]).total_seconds() >= seconds]
        if not eligible:
            return None
        start = eligible[-1]
        elapsed = (end[0] - start[0]).total_seconds()
        if elapsed <= 0:
            return None
        return (
            max(0.0, end[1] - start[1]) / elapsed,
            max(0.0, end[2] - start[2]) / elapsed,
        )


def board_items(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(row.get("code") or "").zfill(6): row
        for row in (payload.get("all_items") or [])
        if row.get("code")
    }


def completed_structure_low(bars: dict[str, Any], code: str) -> float:
    source = bars.get("m") if isinstance(bars.get("m"), dict) else bars
    row = source.get(code) or {}
    previous = row.get("prev") or []
    lows = [float(bar[2]) for bar in previous[-3:] if len(bar) >= 3 and float(bar[2]) > 0]
    return min(lows) if len(lows) == 3 else 0.0


def side_vwap(point: dict[str, Any]) -> float:
    money = float(point.get("buy_money_cum") or 0) + float(point.get("sell_money_cum") or 0)
    volume = float(point.get("buy_vol_cum") or 0) + float(point.get("sell_vol_cum") or 0)
    return money / volume if money > 0 and volume > 0 else 0.0


def choose_rates(
    ten: tuple[float, float] | None,
    thirty: tuple[float, float] | None,
) -> tuple[float, float, float, str]:
    chosen = thirty or ten
    if chosen is None:
        return 0.0, 0.0, 0.60, "FLOW_WARMUP"
    buy, sell = chosen
    total = buy + sell
    ratio = buy / total if total > 0 else 0.60
    quality = "EXACT_30S" if thirty else "EXACT_10S"
    return buy, sell, ratio, quality


def build_observation(
    code: str,
    point: dict[str, Any],
    board: dict[str, Any],
    bars: dict[str, Any],
    windows: SideWindows,
) -> tuple[HoldSellObservation, str]:
    observed_at = as_kst(datetime.fromisoformat(str(point["ts"])))
    buy_cum = float(point.get("buy_money_cum") or 0)
    sell_cum = float(point.get("sell_money_cum") or 0)
    windows.add(code, observed_at, buy_cum, sell_cum)
    rate10 = windows.rates(code, 10)
    rate30 = windows.rates(code, 30)
    buy30, sell30, buy_ratio, quality = choose_rates(rate10, rate30)
    buy10, sell10 = rate10 or (buy30, sell30)
    price = float(point["cur"])
    structure_low = completed_structure_low(bars, code)
    speed5 = float(board.get("money_speed_5s") or 0)
    speed10 = float(board.get("money_speed_10s") or 0)
    speed30 = float(board.get("money_speed_30s") or 0)
    observation = HoldSellObservation(
        observed_at=observed_at,
        price=Decimal(str(price)),
        vwap=Decimal(str(side_vwap(point))),
        buy_ratio_recent=Decimal(str(buy_ratio)),
        money_speed_5s=Decimal(str(max(0.0, speed5))),
        money_speed_10s=Decimal(str(max(0.0, speed10))),
        money_speed_30s=Decimal(str(max(0.0, speed30))),
        buy_money_per_sec_10s=Decimal(str(buy10)),
        sell_money_per_sec_10s=Decimal(str(sell10)),
        buy_money_per_sec_30s=Decimal(str(buy30)),
        sell_money_per_sec_30s=Decimal(str(sell30)),
        structure_broken=bool(structure_low > 0 and price < structure_low),
        money_accelerating=bool(speed10 > 0 and speed5 >= speed10),
        recent_buy_money_rising=bool(rate10 and rate30 and rate10[0] >= rate30[0]),
    )
    return observation, quality


def net_before_slippage(entry_price: Decimal, exit_price: Decimal) -> Decimal:
    paid = entry_price * (Decimal("1") + BUY_FEE)
    received = exit_price * (Decimal("1") - SELL_FEE - SELL_TAX)
    return (received / paid - Decimal("1")) * Decimal("100")


def force_0930(state: HoldSellState, observation: HoldSellObservation) -> bool:
    if observation.observed_at.time() < FORCE_EXIT or state.sell_latched:
        return False
    state.sell_latched = True
    state.sell_action = HoldSellAction.EMERGENCY_SELL
    state.sell_reason = "TIME_EXIT_0930"
    state.sell_latched_at = observation.observed_at
    state.sell_latched_price = observation.price
    return True


def serialize(states: dict[str, dict[str, Any]], day: str) -> dict[str, Any]:
    return {
        "date": day,
        "positions": {
            key: {
                "name": item["name"],
                "closed": item["closed"],
                "state": item["state"].to_dict(),
            }
            for key, item in states.items()
        },
    }


def restore(day: str) -> dict[str, dict[str, Any]]:
    payload = read_json(STATE_PATH, {})
    if str(payload.get("date") or "") != day:
        return {}
    restored = {}
    for key, item in (payload.get("positions") or {}).items():
        try:
            restored[key] = {
                "name": str(item.get("name") or ""),
                "closed": bool(item.get("closed")),
                "state": HoldSellState.from_dict(item["state"]),
            }
        except Exception:
            continue
    return restored


def register_new_positions(states: dict[str, dict[str, Any]], day: str) -> bool:
    changed = False
    for position in active_morning_positions(day):
        key = entry_id(day, position)
        if key in states:
            continue
        state = HoldSellState(
            position_id=f"valley-common-shadow:{key}",
            strategy_id=StrategyId.BASE,
            code=position["code"],
            quantity=position["quantity"],
            entry_price=Decimal(str(position["entry_price"])),
            entry_at=position["entry_at"],
        )
        states[key] = {"name": position["name"], "closed": False, "state": state}
        append_output(day, {
            "date": day, "entry_id": key, "event": "COMMON_ENTRY",
            "code": state.code, "name": position["name"],
            "entry_at": state.entry_at.isoformat(), "entry_price": state.entry_price,
            "observed_at": datetime.now(KST).isoformat(), "reason": "SAME_VALLEY_ENTRY",
            "data_quality": "LEDGER_CONFIRMED", "order_sent": 0,
        })
        changed = True
    return changed


def record_exit(
    day: str,
    key: str,
    item: dict[str, Any],
    observation: HoldSellObservation,
    quality: str,
) -> None:
    state: HoldSellState = item["state"]
    gross = (observation.price / state.entry_price - Decimal("1")) * Decimal("100")
    append_output(day, {
        "date": day, "entry_id": key, "event": "COMMON_EXIT",
        "code": state.code, "name": item["name"],
        "entry_at": state.entry_at.isoformat(), "entry_price": state.entry_price,
        "observed_at": observation.observed_at.isoformat(),
        "signal_price": observation.price,
        "gross_return_pct": f"{gross:.4f}",
        "net_before_slippage_pct": f"{net_before_slippage(state.entry_price, observation.price):.4f}",
        "reason": state.sell_reason,
        "data_quality": quality,
        "order_sent": 0,
    })
    item["closed"] = True


def evaluate_once(
    states: dict[str, dict[str, Any]],
    day: str,
    engine: UnifiedHoldSellEngine,
    windows: SideWindows,
) -> bool:
    snapshot = read_json(SNAPSHOT, {})
    board = read_json(BOARD, {})
    bars = read_json(BARS_1M, {})
    board_by_code = board_items(board)
    now = datetime.now(KST)
    changed = False
    for key, item in states.items():
        if item["closed"]:
            continue
        state: HoldSellState = item["state"]
        point = (snapshot.get("codes") or {}).get(state.code)
        if not isinstance(point, dict) or not point.get("ts") or not point.get("cur"):
            continue
        observed_at = as_kst(datetime.fromisoformat(str(point["ts"])))
        if abs((now - observed_at).total_seconds()) > STALE_SEC:
            continue
        observation, quality = build_observation(
            state.code, point, board_by_code.get(state.code, {}), bars, windows,
        )
        decision = engine.evaluate(state, observation)
        forced = force_0930(state, observation)
        if decision.should_sell or forced:
            record_exit(day, key, item, observation, quality)
            changed = True
    return changed


def run() -> None:
    day = datetime.now(KST).strftime("%Y%m%d")
    states = restore(day)
    engine = UnifiedHoldSellEngine()
    windows = SideWindows()
    while datetime.now(KST).time() < END_TIME:
        changed = register_new_positions(states, day)
        changed = evaluate_once(states, day, engine, windows) or changed
        if changed:
            write_json_atomic(STATE_PATH, serialize(states, day))
        time.sleep(LOOP_SEC)


if __name__ == "__main__":
    run()
