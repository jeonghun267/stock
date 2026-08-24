# -*- coding: utf-8 -*-
"""Persistent order-zero recorder for crash-regime S01/S02/S03 candidates.

This process only reads shared boards and signal outputs.  It never imports a
broker, never creates an order intent, and writes only under data\shadow.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from dataclasses import replace
from datetime import datetime, time as day_time
from pathlib import Path
from typing import Any, Mapping

RUN_DIR = Path(__file__).resolve().parent
if str(RUN_DIR) not in sys.path:
    sys.path.insert(0, str(RUN_DIR))

from regime_exception_role_shadow_v1 import (  # noqa: E402
    RegimeExceptionShadowLedger,
    RegimeRoleObservation,
    classify_regime_role,
)
from regime_recovery_gate_shadow_v1 import RegimeRecoveryGateShadow  # noqa: E402


ROOT = Path(r"C:\stock_bot")
KOSDAQ = ROOT / "data" / "kosdaq_index.json"
SNAPSHOT = ROOT / "IPC" / "live_micro_snapshot.json"
FLOW_BOARD = ROOT / "data" / "micro_rank_board.json"
HIGH_RANGE = ROOT / "data" / "common_high_range_top30.json"
HIGH_RANGE_LIVE = ROOT / "data" / "common_high_range_live_state.json"
SIGNALS = {
    "S01": ROOT / "data" / "strategy_01_open_surge_signal_v2.json",
    "S02": ROOT / "data" / "strategy_02_low_buy_signal_v1.json",
    "S03": ROOT / "data" / "strategy_03_골짜기_급반등_signal_v1.json",
}
OUTPUT_DIR = ROOT / "data" / "shadow"
START_AT = day_time(8, 59)
END_AT = day_time(15, 11)
LOOP_SEC = 1.0
SIGNAL_MAX_AGE_SEC = 5.0


def _read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_bytes().decode("utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}


def _atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _append_jsonl(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(
            payload, ensure_ascii=False, separators=(",", ":"), default=str))
        handle.write("\n")


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(str(value or "").replace(",", ""))
    except (TypeError, ValueError):
        return default


def _code(value: Any) -> str:
    text = str(value or "").strip()
    return text.zfill(6) if text.isdigit() else ""


def _parse_dt(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def _age(now: datetime, value: Any, fallback: float = 999999.0) -> float:
    parsed = _parse_dt(value)
    return max(0.0, (now - parsed).total_seconds()) if parsed else fallback


def _hash(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return "MISSING"


def _signal_ready(payload: Mapping[str, Any], now: datetime) -> dict[str, bool]:
    latest: dict[str, datetime] = {}
    for row in payload.get("signals") or []:
        if not isinstance(row, Mapping) or row.get("action") != "BUY_READY":
            continue
        code = _code(row.get("code"))
        stamp = _parse_dt(row.get("ts"))
        if code and stamp and (code not in latest or stamp > latest[code]):
            latest[code] = stamp
    return {
        code: 0.0 <= (now - stamp).total_seconds() <= SIGNAL_MAX_AGE_SEC
        for code, stamp in latest.items()
    }


def _low_age(now: datetime, live: Mapping[str, Any]) -> float:
    stamp = _parse_dt(live.get("low_time"))
    if stamp:
        return max(0.0, (now - stamp).total_seconds())
    clock = str(live.get("low_time") or "")
    try:
        parsed = datetime.combine(now.date(), datetime.strptime(clock, "%H:%M:%S").time())
        return max(0.0, (now - parsed).total_seconds())
    except ValueError:
        return 0.0


def _flow_rows(payload: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    return {
        _code(row.get("code")): row
        for row in (payload.get("all_items") or payload.get("top20") or [])
        if isinstance(row, Mapping) and _code(row.get("code"))
    }


class RegimeExceptionShadowRecorder:
    def __init__(self, root: Path = ROOT) -> None:
        self.root = root
        self.paths = {
            "market": root / "data" / "kosdaq_index.json",
            "snapshot": root / "IPC" / "live_micro_snapshot.json",
            "flow": root / "data" / "micro_rank_board.json",
            "high_range": root / "data" / "common_high_range_top30.json",
            "high_range_live": root / "data" / "common_high_range_live_state.json",
            "breadth_context": root / "IPC" / "micro_watch_strategy_shared.json",
            "S01": root / "data" / "strategy_01_open_surge_signal_v2.json",
            "S02": root / "data" / "strategy_02_low_buy_signal_v1.json",
            "S03": root / "data" / "strategy_03_골짜기_급반등_signal_v1.json",
        }
        self.output_dir = root / "data" / "shadow"
        self.ledger = RegimeExceptionShadowLedger()
        self.recovery_gate = RegimeRecoveryGateShadow()
        self.selected: dict[str, Any] = {}
        self.latches: dict[str, dict[str, Any]] = {}
        self._restore(datetime.now())

    def _state_path(self, day: str) -> Path:
        return self.output_dir / f"regime_exception_shadow_state_{day}.json"

    def _obs_path(self, day: str) -> Path:
        return self.output_dir / f"regime_exception_observations_{day}.jsonl"

    def _events_path(self, day: str) -> Path:
        return self.output_dir / f"regime_exception_events_{day}.jsonl"

    def _restore(self, now: datetime) -> None:
        day = now.strftime("%Y%m%d")
        state = _read_json(self._state_path(day))
        if state.get("date") != day:
            return
        self.ledger.day = day
        self.ledger.selected_code = str(state.get("selected_code") or "")
        self.ledger.entered_codes = set(state.get("entered_codes") or [])
        self.ledger.owner_by_code = dict(state.get("owner_by_code") or {})
        self.recovery_gate.restore(state.get("recovery_gate") or {})
        self.selected = dict(state.get("selected") or {})
        self.latches = dict(state.get("latches") or {})

    def _save_state(self, now: datetime, status: str) -> None:
        day = now.strftime("%Y%m%d")
        _atomic_json(self._state_path(day), {
            "schema": "regime_exception_shadow_recorder_state_v1",
            "date": day,
            "updated_at": now.isoformat(timespec="seconds"),
            "status": status,
            "mode": "SHADOW_ORDER_ZERO",
            "live_eligible": False,
            "order_qty": 0,
            "selected_code": self.ledger.selected_code,
            "entered_codes": sorted(self.ledger.entered_codes),
            "owner_by_code": self.ledger.owner_by_code,
            "recovery_gate": self.recovery_gate.export(),
            "selected": self.selected,
            "latches": self.latches,
        })

    def _metadata(self, now: datetime) -> None:
        day = now.strftime("%Y%m%d")
        path = self.output_dir / f"regime_exception_metadata_{day}.json"
        if path.exists():
            return
        files = [
            RUN_DIR / "regime_exception_role_shadow_v1.py",
            RUN_DIR / "regime_exception_shadow_recorder_v1.py",
            RUN_DIR / "regime_recovery_gate_shadow_v1.py",
            RUN_DIR / "strategy_common_hold_sell_v1.py",
            RUN_DIR / "strategy_01_open_surge_signal_v2.py",
            RUN_DIR / "strategy_02_low_buy_signal_v1.py",
            RUN_DIR / "골짜기_급반등.py",
        ]
        _atomic_json(path, {
            "schema": "regime_exception_shadow_metadata_v1",
            "date": day,
            "created_at": now.isoformat(timespec="seconds"),
            "provenance": "[HYPOTHETICAL]",
            "performance_scope": "DECISION_AND_OBSERVATION_ONLY",
            "mode": "SHADOW_ORDER_ZERO",
            "live_eligible": False,
            "order_qty": 0,
            "file_sha256": {str(path): _hash(path) for path in files},
        })

    def process_once(self, now: datetime | None = None) -> list[dict[str, Any]]:
        now = (now or datetime.now()).replace(tzinfo=None)
        day = now.strftime("%Y%m%d")
        self._metadata(now)
        market = _read_json(self.paths["market"])
        snapshot = _read_json(self.paths["snapshot"])
        breadth_context = _read_json(self.paths["breadth_context"])
        previous_close_by_code = {
            _code(code): _num(row.get("prev_close"))
            for code, row in (breadth_context.get("all_meta") or {}).items()
            if isinstance(row, Mapping) and _code(code) and _num(row.get("prev_close")) > 0
        }
        recovery = self.recovery_gate.evaluate(
            now, market, snapshot, previous_close_by_code)
        _atomic_json(
            self.output_dir / f"regime_recovery_gate_state_{day}.json",
            recovery,
        )
        market_pct = _num(market.get("chg"), 999.0)
        regime_active = market_pct <= -3.0
        if not regime_active and not self.selected:
            self._save_state(now, f"MARKET_{recovery['state']}")
            return []

        flow_payload = _read_json(self.paths["flow"])
        high_range = _read_json(self.paths["high_range"])
        high_live = _read_json(self.paths["high_range_live"])
        signal_ready = {
            role: _signal_ready(_read_json(self.paths[role]), now)
            for role in ("S01", "S02", "S03")
        }
        stocks = snapshot.get("codes") or {}
        flows = _flow_rows(flow_payload)
        live_codes = high_live.get("codes") or {}
        candidates = high_range.get("candidates") or []
        observations: list[RegimeRoleObservation] = []
        compact_inputs: list[dict[str, Any]] = []

        if regime_active:
            for static in candidates:
                if not isinstance(static, Mapping):
                    continue
                code = _code(static.get("code"))
                point = stocks.get(code) or {}
                flow = flows.get(code) or {}
                live = live_codes.get(code) or {}
                price = _num(point.get("cur"))
                previous_close = _num(static.get("prev_close"))
                open_price = _num(point.get("op"))
                day_low = _num(point.get("lo") or live.get("low"))
                if min(price, previous_close, open_price, day_low) <= 0:
                    continue
                ask = _num(point.get("best_ask_px"))
                bid = _num(point.get("best_bid_px"))
                spread = ((ask / bid - 1.0) * 10000.0) if ask > 0 and bid > 0 else 9999.0
                ask_total = _num(point.get("ask_tot"))
                bid_total = _num(point.get("bid_tot"))
                bid_share = bid_total / (ask_total + bid_total) if ask_total + bid_total > 0 else 0.0
                money_now = _num(flow.get("money_5s_now"))
                money_prev = _num(flow.get("money_5s_prev"))
                quality = str(flow.get("money_flow_data_quality") or "")
                observation = RegimeRoleObservation(
                    ts=now,
                    code=code,
                    market_pct=market_pct,
                    market_age_sec=_age(now, market.get("ts")),
                    price=price,
                    open_price=open_price,
                    previous_close=previous_close,
                    day_low=day_low,
                    rebound_pct=(price / day_low - 1.0) * 100.0,
                    no_new_low_sec=_low_age(now, live),
                    flow_turn=bool(money_now > 0 and money_now >= money_prev),
                    che_rising=_num(flow.get("che_delta_5s")) > 0,
                    order_book_fresh=_age(now, point.get("ob_ts")) <= 4.0,
                    spread_bps=spread,
                    best_bid_share=bid_share,
                    vi_suspect=bool(point.get("vi_active") or point.get("vi_suspect")),
                    high_range_rank=int(_num(static.get("rank"), 999)),
                    money_speed_ratio=_num(live.get("money_speed_vs_daily_avg")),
                    turnover_pct=_num(live.get("listed_turnover_pct")),
                    volatility_quality=str(live.get("volatility_quality") or ""),
                    stock_age_sec=_age(now, point.get("ts")),
                    flow_age_sec=_num(flow.get("snapshot_age_sec"), 999999.0),
                    high_range_age_sec=_num(live.get("age_sec"), 999999.0),
                    exact_flow=bool(flow and quality.upper() != "STALE"),
                    s01_strategy_ready=signal_ready["S01"].get(code, False),
                    s02_strategy_ready=signal_ready["S02"].get(code, False),
                    s03_strategy_ready=signal_ready["S03"].get(code, False),
                    market_recovery_state=str(recovery.get("state") or "RED"),
                    market_recovery_age_sec=_num(recovery.get("amber_age_sec")),
                    market_source=str(self.paths["market"]),
                    stock_source=str(self.paths["snapshot"]),
                    flow_source=str(self.paths["flow"]),
                    high_range_source=str(self.paths["high_range_live"]),
                )
                observations.append(observation)
                compact_inputs.append({
                    "code": code, "market_pct": market_pct,
                    "market_age_sec": observation.market_age_sec,
                    "price": price, "open_price": open_price,
                    "previous_close": previous_close, "day_low": day_low,
                    "rebound_pct": observation.rebound_pct,
                    "no_new_low_sec": observation.no_new_low_sec,
                    "flow_turn": observation.flow_turn,
                    "che_rising": observation.che_rising,
                    "order_book_fresh": observation.order_book_fresh,
                    "spread_bps": spread, "best_bid_share": bid_share,
                    "vi_suspect": observation.vi_suspect,
                    "high_range_rank": observation.high_range_rank,
                    "money_speed_ratio": observation.money_speed_ratio,
                    "turnover_pct": observation.turnover_pct,
                    "stock_age_sec": observation.stock_age_sec,
                    "flow_age_sec": observation.flow_age_sec,
                    "high_range_age_sec": observation.high_range_age_sec,
                    "exact_flow": observation.exact_flow,
                    "s01_strategy_ready": observation.s01_strategy_ready,
                    "s02_strategy_ready": observation.s02_strategy_ready,
                    "s03_strategy_ready": observation.s03_strategy_ready,
                    "market_recovery_state": observation.market_recovery_state,
                    "market_recovery_age_sec": observation.market_recovery_age_sec,
                })

        preview = [classify_regime_role(row) for row in observations]
        for observation, result in zip(observations, preview):
            if (
                recovery.get("state") == "RED"
                and result.get("raw_role_candidate")
                and result.get("role") in {
                    "S02_SLOW_CRASH_RECOVERY", "S03_DEEP_CRASH_REVERSAL"}
                and observation.code not in self.latches
            ):
                latch = {
                    "provenance": "[HYPOTHETICAL]",
                    "code": observation.code,
                    "role": result["role"],
                    "latched_at": now.isoformat(timespec="milliseconds"),
                    "day_low": observation.day_low,
                    "expires_after_sec": 300,
                }
                self.latches[observation.code] = latch
                _append_jsonl(self._events_path(day), {
                    "event": "CANDIDATE_LATCH_ARMED",
                    "mode": "SHADOW_ORDER_ZERO", "live_eligible": False,
                    "order_qty": 0, "observed_at": now.isoformat(timespec="milliseconds"),
                    "latch": latch, "decision": result,
                })

        decorated: list[RegimeRoleObservation] = []
        for observation in observations:
            latch = self.latches.get(observation.code)
            if not latch:
                decorated.append(observation)
                continue
            latched_at = _parse_dt(latch.get("latched_at"))
            age = (now - latched_at).total_seconds() if latched_at else 999999.0
            latched_low = _num(latch.get("day_low"))
            valid = bool(
                0.0 <= age <= 300.0
                and latched_low > 0
                and observation.day_low >= latched_low
                and observation.price > latched_low
            )
            if not valid:
                self.latches.pop(observation.code, None)
                decorated.append(observation)
                continue
            decorated.append(replace(
                observation,
                latched_role=str(latch.get("role") or ""),
                latched_day_low=latched_low,
                latch_age_sec=age,
                latch_valid=True,
            ))

        decisions = self.ledger.select(decorated) if decorated else []
        for decision in decisions:
            if decision.get("shadow_selected"):
                source = next(row for row in compact_inputs if row["code"] == decision["code"])
                self.selected = {
                    "provenance": "[HYPOTHETICAL]",
                    "code": decision["code"],
                    "role": decision["role"],
                    "virtual_entry_at": now.isoformat(timespec="milliseconds"),
                    "virtual_entry_price": source["price"],
                    "peak_observed_price": source["price"],
                    "last_observed_price": source["price"],
                    "last_observed_at": now.isoformat(timespec="milliseconds"),
                }
                _append_jsonl(self._events_path(day), {
                    "event": "VIRTUAL_ENTRY_SELECTED", "mode": "SHADOW_ORDER_ZERO",
                    "live_eligible": False, "order_qty": 0,
                    "observed_at": now.isoformat(timespec="milliseconds"),
                    "decision": decision, "input": source,
                })
                self.latches.pop(str(decision.get("code") or ""), None)

        if self.selected:
            code = str(self.selected.get("code") or "")
            point = stocks.get(code) or {}
            price = _num(point.get("cur"))
            if price > 0:
                self.selected["peak_observed_price"] = max(
                    _num(self.selected.get("peak_observed_price")), price)
                self.selected["last_observed_price"] = price
                self.selected["last_observed_at"] = now.isoformat(timespec="milliseconds")

        if regime_active:
            by_code = {row["code"]: row for row in decisions}
            _append_jsonl(self._obs_path(day), {
                "schema": "regime_exception_observation_batch_v1",
                "provenance": "[HYPOTHETICAL]",
                "performance_scope": "DECISION_AND_OBSERVATION_ONLY",
                "mode": "SHADOW_ORDER_ZERO", "live_eligible": False, "order_qty": 0,
                "observed_at": now.isoformat(timespec="milliseconds"),
                "source_versions": {
                    "market_ts": market.get("ts"), "snapshot_ts": snapshot.get("ts"),
                    "flow_ts": flow_payload.get("ts"),
                    "high_range_generated_at": high_range.get("generated_at"),
                    "high_range_live_updated_at": high_live.get("updated_at"),
                },
                "rows": [{"input": row, "decision": by_code.get(row["code"], {})}
                         for row in compact_inputs],
            })
        self._save_state(now, "REGIME_RECORDING" if regime_active else "TRACK_SELECTED")
        return decisions


def run_loop(recorder: RegimeExceptionShadowRecorder) -> int:
    while True:
        now = datetime.now()
        if now.weekday() >= 5 or now.time() >= END_AT:
            return 0
        if now.time() < START_AT:
            time.sleep(min(30.0, LOOP_SEC))
            continue
        recorder.process_once(now)
        time.sleep(LOOP_SEC)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    recorder = RegimeExceptionShadowRecorder(args.root)
    if args.once:
        recorder.process_once()
        return 0
    return run_loop(recorder)


if __name__ == "__main__":
    raise SystemExit(main())
