# -*- coding: utf-8 -*-
"""S03 깊은 급락 그림자 후보의 지속 가능한 주문 0 결과 원장."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping


SCHEMA = "strategy_03_deep_crash_shadow_ledger_v1"


def _pct(current: float, base: float) -> float | None:
    if current <= 0 or base <= 0:
        return None
    return (current / base - 1.0) * 100.0


def _rounded(value: float | None) -> float | None:
    return round(value, 6) if value is not None else None


class DeepCrashShadowLedger:
    """READY 최초값을 보존하고 이후 가격경로만 갱신한다."""

    def __init__(self, day: str, records: Mapping[str, Any] | None = None) -> None:
        self.day = str(day)
        self.records: dict[str, dict[str, Any]] = {
            str(key): dict(value)
            for key, value in (records or {}).items()
            if isinstance(value, Mapping)
        }

    @classmethod
    def restore(cls, payload: Mapping[str, Any], day: str) -> "DeepCrashShadowLedger":
        if (
            str(payload.get("schema") or "") != SCHEMA
            or str(payload.get("date") or "") != str(day)
        ):
            return cls(day)
        return cls(day, payload.get("records") or {})

    def observe(
        self,
        *,
        code: str,
        name: str,
        ts: datetime,
        price: float,
        shadow: Mapping[str, Any],
    ) -> None:
        code = str(code).zfill(6)
        price = float(price)
        for record in self.records.values():
            if str(record.get("code") or "") != code or price <= 0:
                continue
            if price < float(record.get("post_candidate_low") or price):
                record["post_candidate_low"] = price
                record["post_candidate_low_ts"] = ts.isoformat(timespec="milliseconds")
            if price > float(record.get("post_candidate_high") or price):
                record["post_candidate_high"] = price
                record["post_candidate_high_ts"] = ts.isoformat(timespec="milliseconds")
            record["last_ts"] = ts.isoformat(timespec="milliseconds")
            record["last_price"] = price
            self._refresh_metrics(record)

        if not bool(shadow.get("dcr_shadow_candidate")):
            return
        anchor_ts = str(shadow.get("crs_observed_low_ts") or "UNKNOWN")
        key = f"{code}|{anchor_ts}"
        if key in self.records:
            return
        anchor_low = float(shadow.get("crs_observed_low") or 0.0)
        record = {
            "code": code,
            "name": str(name or code),
            "mode": "S03_DEEP_CRASH_SHADOW_ORDER_ZERO",
            "order_qty": 0,
            "live_eligible": False,
            "candidate_ts": ts.isoformat(timespec="milliseconds"),
            "candidate_price": price,
            "anchor_low": anchor_low,
            "anchor_low_ts": anchor_ts,
            "low_pct_at_candidate": shadow.get("dcr_low_pct"),
            "market_pct_at_candidate": shadow.get("crs_market_pct"),
            "relative_strength_pct_at_candidate": shadow.get(
                "crs_relative_strength_pct"
            ),
            "flow_turn_at_candidate": shadow.get("crs_flow_turn"),
            "spread_bps_at_candidate": shadow.get("crs_spread_bps"),
            "best_bid_share_at_candidate": shadow.get("crs_best_bid_share"),
            "vi_suspect_at_candidate": shadow.get("dcr_vi_suspect"),
            "post_candidate_low": price,
            "post_candidate_low_ts": ts.isoformat(timespec="milliseconds"),
            "post_candidate_high": price,
            "post_candidate_high_ts": ts.isoformat(timespec="milliseconds"),
            "last_ts": ts.isoformat(timespec="milliseconds"),
            "last_price": price,
            "tracking_status": "TRACKING_TO_1431",
            "post_close_source": (
                f"C:\\stock_bot\\data\\high_range_shadow_{self.day}.csv"
            ),
        }
        self._refresh_metrics(record)
        self.records[key] = record

    @staticmethod
    def _refresh_metrics(record: dict[str, Any]) -> None:
        candidate = float(record.get("candidate_price") or 0.0)
        anchor_low = float(record.get("anchor_low") or 0.0)
        high = float(record.get("post_candidate_high") or 0.0)
        low = float(record.get("post_candidate_low") or 0.0)
        last = float(record.get("last_price") or 0.0)
        record["max_favorable_pct"] = _rounded(_pct(high, candidate))
        record["max_adverse_pct"] = _rounded(_pct(low, candidate))
        record["anchor_low_to_post_high_pct"] = _rounded(_pct(high, anchor_low))
        record["last_from_candidate_pct"] = _rounded(_pct(last, candidate))

    def payload(self, now: datetime, *, finalize: bool = False) -> dict[str, Any]:
        if finalize:
            for record in self.records.values():
                record["tracking_status"] = "SIGNAL_TRACKING_FINAL_1431"
                record["finalized_at"] = now.isoformat(timespec="seconds")
        return {
            "schema": SCHEMA,
            "date": self.day,
            "updated_at": now.isoformat(timespec="seconds"),
            "mode": "SHADOW_ORDER_ZERO",
            "tracking_cutoff": "14:31:00",
            "close_note": (
                "last_price는 S03 신호기 14:31까지의 마지막 관측가이며 종가가 아니다. "
                "장마감 최고가·종가는 post_close_source로 별도 생산재생한다."
            ),
            "record_count": len(self.records),
            "records": self.records,
        }
