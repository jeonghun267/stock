# -*- coding: utf-8 -*-
"""[CAPITAL-SSOT 2026-06-04] 운용 자본금/한도 단일 소스(Single Source Of Truth).

모든 매수 모듈(buy_sender / eod_pickup 등)이 자본금·한도를 여기서 읽는다.
config/capital.json 의 capital_krw 한 줄만 바꾸면 모든 매수 한도가 자동 비례한다.

⚠ 중요: capital_krw 는 '시스템 운용 허용액'이지 '통장 잔고'가 아니다.
   통장에 2600만이 있어도 capital_krw=2000000 이면 시스템은 200만만 운용한다(통장 자동반영 금지).

우선순위: env SAFEPLUS_CAPITAL > config/capital.json(capital_krw) > 기본값(2,000,000).
read-only 로더. 매수/broker/주문 호출 없음.
"""
import os
import json
from pathlib import Path

_CONFIG_FILE = Path(__file__).resolve().parent.parent / "config" / "capital.json"
_DEFAULT_CAPITAL = 2_000_000
_DEFAULT_ORDER_QUANTITY = 1
_DEFAULT_RATIOS = {
    "order_max": 0.98,          # 한 주문 최대 = 자본 × 0.98
    "daily_total_max": 1.0,     # 오늘 발주 누적 총액 상한 = 자본 × 1.0 (200만 묶기 자물쇠)
    "account_usage_max": 0.75,  # 계좌 사용 상한 = 자본 × 0.75
}


def _load() -> dict:
    try:
        if _CONFIG_FILE.exists():
            return json.loads(_CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def get_capital() -> int:
    """운용 자본금(원). env SAFEPLUS_CAPITAL 우선 → config → 기본값."""
    env = os.environ.get("SAFEPLUS_CAPITAL")
    if env:
        try:
            return int(float(env))
        except (TypeError, ValueError):
            pass
    try:
        return int(_load().get("capital_krw", _DEFAULT_CAPITAL))
    except (TypeError, ValueError):
        return _DEFAULT_CAPITAL


def get_order_quantity() -> int:
    """Return the common maximum shares for one position/order.

    This value deliberately has no strategy-specific environment override.
    Every buy engine and the broker's final gate must read the same setting.
    """
    try:
        quantity = int(_load().get("order_quantity", _DEFAULT_ORDER_QUANTITY))
    except (TypeError, ValueError):
        quantity = _DEFAULT_ORDER_QUANTITY
    return max(1, quantity)


def get_ratio(name: str) -> float:
    """한도 비율(0~1). config ratios → 기본값."""
    r = (_load().get("ratios") or {}).get(name)
    if r is None:
        r = _DEFAULT_RATIOS.get(name, 1.0)
    try:
        return float(r)
    except (TypeError, ValueError):
        return _DEFAULT_RATIOS.get(name, 1.0)


def get_limit(name: str) -> int:
    """자본금 × 비율 = 절대 한도(원). 예: get_limit('daily_total_max')=200만."""
    return int(get_capital() * get_ratio(name))


if __name__ == "__main__":
    print(f"capital_krw       = {get_capital():,}")
    print(f"order_quantity    = {get_order_quantity():,}")
    for _k in ("order_max", "daily_total_max", "account_usage_max"):
        print(f"  {_k:18s} ratio={get_ratio(_k):.2f} → limit={get_limit(_k):,}")
