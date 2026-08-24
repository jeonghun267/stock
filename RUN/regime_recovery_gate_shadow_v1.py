# -*- coding: utf-8 -*-
"""Order-zero RED/AMBER/YELLOW/GREEN market recovery state machine."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from statistics import median
from typing import Any, Mapping


@dataclass(frozen=True)
class RecoveryGateConfig:
    stop_pct: float = -3.0
    reduce_pct: float = -2.0
    max_market_age_sec: float = 360.0
    max_stock_age_sec: float = 4.0
    min_breadth_universe: int = 30
    min_proxy_rebound_pct: float = 0.40
    min_no_new_proxy_low_sec: float = 30.0
    fast_confirm_sec: float = 15.0
    min_advancer_share_improvement: float = 0.10
    min_new_low_share_improvement: float = 0.05
    near_low_bps: float = 10.0
    amber_fail_cycles: int = 2


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(str(value or "").replace(",", ""))
    except (TypeError, ValueError):
        return default


def _parse_dt(value: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value or "").replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def _age(now: datetime, value: Any) -> float:
    stamp = _parse_dt(value)
    return max(0.0, (now - stamp).total_seconds()) if stamp else 999999.0


def breadth_metrics(
    snapshot: Mapping[str, Any], now: datetime, config: RecoveryGateConfig,
    previous_close_by_code: Mapping[str, float],
) -> dict[str, Any]:
    usable = []
    for raw_code, point in (snapshot.get("codes") or {}).items():
        if not isinstance(point, Mapping) or _age(now, point.get("ts")) > config.max_stock_age_sec:
            continue
        price, low = (_num(point.get(key)) for key in ("cur", "lo"))
        previous_close = _num(previous_close_by_code.get(str(raw_code).zfill(6)))
        if min(price, previous_close, low) > 0:
            usable.append((price, previous_close, low))
    total = len(usable)
    if not total:
        return {"universe": 0, "advancer_share": 0.0, "new_low_share": 1.0}
    near_low_mult = 1.0 + config.near_low_bps / 10000.0
    return {
        "universe": total,
        "advancer_share": sum(price >= previous for price, previous, _ in usable) / total,
        "new_low_share": sum(price <= low * near_low_mult for price, _, low in usable) / total,
        "median_return_pct": median(
            (price / previous - 1.0) * 100.0 for price, previous, _ in usable),
    }


class RegimeRecoveryGateShadow:
    def __init__(self, config: RecoveryGateConfig | None = None) -> None:
        self.config = config or RecoveryGateConfig()
        self.day = ""
        self.state = "RED"
        self.market_low_price = 0.0
        self.market_low_at: datetime | None = None
        self.advancer_share_at_low = 0.0
        self.new_low_share_at_low = 1.0
        self.amber_fail_count = 0
        self.amber_since: datetime | None = None
        self.minute_prices: list[tuple[str, float]] = []
        self.proxy_low_return_pct = 999.0
        self.proxy_low_at: datetime | None = None
        self.fast_condition_since: datetime | None = None

    def restore(self, payload: Mapping[str, Any]) -> None:
        self.day = str(payload.get("day") or "")
        self.state = str(payload.get("state") or "RED")
        self.market_low_price = _num(payload.get("market_low_price"))
        self.market_low_at = _parse_dt(payload.get("market_low_at"))
        self.advancer_share_at_low = _num(
            payload.get("advancer_share_at_low", payload.get("open_breadth_at_low")))
        self.new_low_share_at_low = _num(payload.get("new_low_share_at_low"), 1.0)
        self.amber_fail_count = int(_num(payload.get("amber_fail_count")))
        self.amber_since = _parse_dt(payload.get("amber_since"))
        self.minute_prices = [
            (str(row[0]), _num(row[1]))
            for row in (payload.get("minute_prices") or [])
            if isinstance(row, list) and len(row) == 2
        ][-4:]
        self.proxy_low_return_pct = _num(payload.get("proxy_low_return_pct"), 999.0)
        self.proxy_low_at = _parse_dt(payload.get("proxy_low_at"))
        self.fast_condition_since = _parse_dt(payload.get("fast_condition_since"))

    def export(self) -> dict[str, Any]:
        return {
            "day": self.day,
            "state": self.state,
            "market_low_price": self.market_low_price,
            "market_low_at": self.market_low_at.isoformat() if self.market_low_at else "",
            "advancer_share_at_low": self.advancer_share_at_low,
            "new_low_share_at_low": self.new_low_share_at_low,
            "amber_fail_count": self.amber_fail_count,
            "amber_since": self.amber_since.isoformat() if self.amber_since else "",
            "minute_prices": self.minute_prices,
            "proxy_low_return_pct": self.proxy_low_return_pct,
            "proxy_low_at": self.proxy_low_at.isoformat() if self.proxy_low_at else "",
            "fast_condition_since": (
                self.fast_condition_since.isoformat() if self.fast_condition_since else ""),
        }

    def evaluate(
        self,
        now: datetime,
        market: Mapping[str, Any],
        snapshot: Mapping[str, Any],
        previous_close_by_code: Mapping[str, float],
    ) -> dict[str, Any]:
        now = now.replace(tzinfo=None)
        cfg = self.config
        day = now.strftime("%Y%m%d")
        if self.day != day:
            self.__init__(cfg)
            self.day = day

        market_pct = _num(market.get("chg"), 999.0)
        price = _num(market.get("price"))
        previous = _num(market.get("prev"))
        market_age = _age(now, market.get("ts"))
        breadth = breadth_metrics(snapshot, now, cfg, previous_close_by_code)
        data_ready = (
            market_age <= cfg.max_market_age_sec
            and price > 0 and previous > 0
            and breadth["universe"] >= cfg.min_breadth_universe
        )

        new_low = False
        if data_ready and (self.market_low_price <= 0 or price < self.market_low_price):
            new_low = self.market_low_price > 0
            self.market_low_price = price
            self.market_low_at = now
            self.advancer_share_at_low = breadth["advancer_share"]
            self.new_low_share_at_low = breadth["new_low_share"]
            self.amber_fail_count = 0
            self.amber_since = None

        proxy_return = _num(breadth.get("median_return_pct"), 999.0)
        new_proxy_low = False
        if data_ready and (
            self.proxy_low_return_pct >= 900.0
            or proxy_return < self.proxy_low_return_pct
        ):
            new_proxy_low = self.proxy_low_return_pct < 900.0
            self.proxy_low_return_pct = proxy_return
            self.proxy_low_at = now
            self.advancer_share_at_low = breadth["advancer_share"]
            self.new_low_share_at_low = breadth["new_low_share"]
            self.fast_condition_since = None
            self.amber_since = None

        minute_key = now.strftime("%Y%m%d%H%M")
        if price > 0:
            if self.minute_prices and self.minute_prices[-1][0] == minute_key:
                self.minute_prices[-1] = (minute_key, price)
            else:
                self.minute_prices.append((minute_key, price))
                self.minute_prices = self.minute_prices[-4:]
        rising_steps_3m = sum(
            current[1] > previous_point[1]
            for previous_point, current in zip(self.minute_prices, self.minute_prices[1:])
        ) if len(self.minute_prices) >= 4 else 0

        no_new_proxy_low_sec = (
            max(0.0, (now - self.proxy_low_at).total_seconds())
            if self.proxy_low_at else 0.0
        )
        proxy_rebound_pct = max(0.0, proxy_return - self.proxy_low_return_pct)
        breadth_improvement = breadth["advancer_share"] - self.advancer_share_at_low
        new_low_improvement = self.new_low_share_at_low - breadth["new_low_share"]
        fast_base_ready = all((
            data_ready,
            market_pct <= cfg.stop_pct,
            proxy_rebound_pct >= cfg.min_proxy_rebound_pct,
            no_new_proxy_low_sec >= cfg.min_no_new_proxy_low_sec,
            breadth_improvement >= cfg.min_advancer_share_improvement,
            new_low_improvement >= cfg.min_new_low_share_improvement,
        ))
        if fast_base_ready:
            self.fast_condition_since = self.fast_condition_since or now
        else:
            self.fast_condition_since = None
        fast_condition_age = (
            max(0.0, (now - self.fast_condition_since).total_seconds())
            if self.fast_condition_since else 0.0
        )
        fast_ready = fast_base_ready and fast_condition_age >= cfg.fast_confirm_sec

        reasons: list[str] = []
        if not data_ready:
            reasons.append("DATA_NOT_READY")
        if market_pct > cfg.reduce_pct:
            self.state, self.amber_fail_count = "GREEN", 0
            self.amber_since = None
        elif market_pct > cfg.stop_pct:
            self.state, self.amber_fail_count = "YELLOW", 0
            self.amber_since = None
        elif new_low or new_proxy_low:
            self.state = "RED"
        elif self.state not in {"FAST_AMBER", "AMBER"}:
            if fast_ready:
                self.state = "FAST_AMBER"
                self.amber_since = now
            else:
                self.state = "RED"
                self.amber_since = None
        else:
            fail_back = (
                not data_ready
                or proxy_rebound_pct < cfg.min_proxy_rebound_pct * 0.5
                or breadth_improvement < cfg.min_advancer_share_improvement * 0.5
                or new_low_improvement < cfg.min_new_low_share_improvement * 0.5
            )
            self.amber_fail_count = self.amber_fail_count + 1 if fail_back else 0
            if self.amber_fail_count >= cfg.amber_fail_cycles:
                self.state, self.amber_fail_count = "RED", 0
                self.amber_since = None
            elif (
                self.state == "FAST_AMBER" and self.amber_since
                and (_parse_dt(market.get("ts")) or now) > self.amber_since
                and price > self.market_low_price > 0
            ):
                self.state = "AMBER"

        if market_pct <= cfg.stop_pct and self.state == "RED" and data_ready:
            checks = {
                "PROXY_REBOUND_WAIT": proxy_rebound_pct < cfg.min_proxy_rebound_pct,
                "PROXY_PERSISTENCE_WAIT": (
                    no_new_proxy_low_sec < cfg.min_no_new_proxy_low_sec),
                "FAST_CONFIRM_WAIT": fast_condition_age < cfg.fast_confirm_sec,
                "BREADTH_WAIT": breadth_improvement < cfg.min_advancer_share_improvement,
                "NEW_LOW_CONTRACTION_WAIT": new_low_improvement < cfg.min_new_low_share_improvement,
            }
            reasons.extend(name for name, failed in checks.items() if failed)

        return {
            "schema": "regime_recovery_gate_shadow_v1",
            "provenance": "[HYPOTHETICAL]",
            "mode": "SHADOW_ORDER_ZERO",
            "live_eligible": False,
            "order_qty": 0,
            "observed_at": now.isoformat(timespec="milliseconds"),
            "state": self.state,
            "amber_age_sec": round(
                max(0.0, (now - self.amber_since).total_seconds())
                if self.amber_since else 0.0, 1),
            "reason": "READY" if self.state in {"FAST_AMBER", "AMBER", "YELLOW", "GREEN"} else "|".join(reasons),
            "market_pct": round(market_pct, 4),
            "market_age_sec": round(market_age, 3),
            "market_low_price": self.market_low_price,
            "proxy_median_return_pct": round(proxy_return, 4),
            "proxy_low_return_pct": round(self.proxy_low_return_pct, 4),
            "proxy_rebound_pct": round(proxy_rebound_pct, 4),
            "no_new_proxy_low_sec": round(no_new_proxy_low_sec, 1),
            "fast_condition_age_sec": round(fast_condition_age, 1),
            "breadth_universe": breadth["universe"],
            "advancer_share": round(breadth["advancer_share"], 4),
            "advancer_share_improvement": round(breadth_improvement, 4),
            "new_low_share": round(breadth["new_low_share"], 4),
            "new_low_share_improvement": round(new_low_improvement, 4),
            "config": asdict(cfg),
        }
