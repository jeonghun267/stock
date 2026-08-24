from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from hold_sell_audit_v1 import load_verified_post_exit_rows, load_verified_rows
from strategy_common_hold_sell_v1 import HoldSellConfig


ROOT = Path(__file__).resolve().parents[1]
DATE = "20260818"
STRATEGY = "S02_LOW_BUY_SELL_EXHAUSTION"
ARM_RETURN_PCT = Decimal("3")
CONFIRM_SECONDS = 3.0
ATR_MULTIPLIERS = (Decimal("1.5"), Decimal("2.0"))


def dec(value: object) -> Decimal:
    return Decimal(str(value or "0"))


def minute_atr10() -> dict[str, dict[str, Decimal]]:
    source = ROOT / "data" / "돈맥_1분봉.json"
    payload = json.loads(source.read_text(encoding="utf-8-sig"))
    result: dict[str, dict[str, Decimal]] = {}
    for code, item in payload.get("m", {}).items():
        bars = list(zip(item.get("pm", []), item.get("prev", [])))
        trs: list[Decimal] = []
        previous_close: Decimal | None = None
        atr_by_minute: dict[str, Decimal] = {}
        for minute, raw in bars:
            _open, high, low, close = map(dec, raw)
            tr = high - low
            if previous_close is not None:
                tr = max(tr, abs(high - previous_close), abs(low - previous_close))
            trs.append(tr)
            previous_close = close
            if len(trs) >= 10:
                atr_by_minute[str(minute)] = sum(trs[-10:]) / Decimal(10)
        result[str(code).zfill(6)] = atr_by_minute
    return result


def completed_atr(atrs: dict[str, Decimal], observed_at: datetime) -> Decimal | None:
    current_minute = observed_at.strftime("%Y%m%d%H%M")
    eligible = [minute for minute in atrs if minute < current_minute]
    if not eligible:
        return None
    return atrs[max(eligible)]


def flow_score(observation: dict[str, object], cfg: HoldSellConfig) -> int:
    buy10 = dec(observation.get("buy_money_per_sec_10s"))
    sell10 = dec(observation.get("sell_money_per_sec_10s"))
    buy30 = dec(observation.get("buy_money_per_sec_30s"))
    buyvol5 = dec(observation.get("buy_volume_per_sec_5s"))
    sellvol5 = dec(observation.get("sell_volume_per_sec_5s"))
    prevsell10 = dec(observation.get("sell_volume_per_sec_previous_10s"))
    sell_money_break = buy10 > 0 and sell10 >= buy10 * cfg.common_peak_sell_money_mult
    sell_volume_break = (
        buyvol5 > 0
        and prevsell10 > 0
        and sellvol5 >= buyvol5 * cfg.common_peak_sell_volume_mult
        and sellvol5 >= prevsell10 * cfg.common_peak_sell_volume_accel_mult
    )
    buy_fading = buy30 > 0 and buy10 <= buy30 * cfg.common_peak_buy_fade_mult
    che_falling = dec(observation.get("che_str_change_5s")) <= -cfg.common_peak_che_drop
    return sum((sell_money_break, sell_volume_break, buy_fading, che_falling))


def rows_for_position(pre_path: Path) -> tuple[dict[str, object], list[dict[str, object]]]:
    pre_rows = load_verified_rows(pre_path)
    first = pre_rows[0]
    position_id = str(first["state_before"]["position_id"])
    post_path = (
        ROOT
        / "data"
        / "audit"
        / "post_exit_observation"
        / DATE
        / STRATEGY
        / pre_path.name
    )
    combined: list[dict[str, object]] = []
    for row in pre_rows:
        combined.append({"observation": row["observation"], "source": str(pre_path)})
    if post_path.exists():
        for row in load_verified_post_exit_rows(post_path):
            combined.append({"observation": row["observation"], "source": str(post_path)})
    combined.sort(key=lambda row: datetime.fromisoformat(str(row["observation"]["observed_at"])))
    deduped: dict[str, dict[str, object]] = {}
    for row in combined:
        deduped[str(row["observation"]["observed_at"])] = row
    meta = {
        "position_id": position_id,
        "code": str(first["state_before"]["code"]).zfill(6),
        "entry_price": str(first["state_before"]["entry_price"]),
        "entry_at": str(first["state_before"]["entry_at"]),
        "engine_path": str(first["engine_path"]),
        "engine_sha256": str(first["engine_sha256"]),
        "pre_audit": str(pre_path),
        "post_audit": str(post_path) if post_path.exists() else "",
    }
    return meta, list(deduped.values())


def simulate(meta: dict[str, object], rows: list[dict[str, object]], atrs: dict[str, Decimal]) -> dict[str, object]:
    cfg = HoldSellConfig()
    entry = dec(meta["entry_price"])
    peak = entry
    since: dict[Decimal, datetime | None] = {multiplier: None for multiplier in ATR_MULTIPLIERS}
    exits: dict[str, object] = {}
    peak_at_end = entry
    last_observed_at = ""
    for row in rows:
        observation = row["observation"]
        ts = datetime.fromisoformat(str(observation["observed_at"]))
        last_observed_at = ts.isoformat()
        price = dec(observation["price"])
        peak = max(peak, price)
        peak_at_end = peak
        peak_return = (peak / entry - 1) * 100
        atr = completed_atr(atrs, ts)
        score = flow_score(observation, cfg)
        trend_released = not (
            bool(observation.get("price_above_ma5"))
            and bool(observation.get("ma5_rising"))
            and bool(observation.get("ma10_support"))
        )
        for multiplier in ATR_MULTIPLIERS:
            key = str(multiplier)
            if key in exits:
                continue
            qualifies = (
                peak_return >= ARM_RETURN_PCT
                and atr is not None
                and peak - price >= atr * multiplier
                and score >= 2
                and trend_released
            )
            if not qualifies:
                since[multiplier] = None
                continue
            if since[multiplier] is None:
                since[multiplier] = ts
                continue
            age = (ts - since[multiplier]).total_seconds()
            if age >= CONFIRM_SECONDS:
                exits[key] = {
                    "observed_at": ts.isoformat(),
                    "price": str(price),
                    "gross_return_pct": str((price / entry - 1) * 100),
                    "peak_price": str(peak),
                    "peak_return_pct": str(peak_return),
                    "giveback_pct_point": str((peak - price) / entry * 100),
                    "atr10": str(atr),
                    "drawdown_atr": str((peak - price) / atr),
                    "flow_score": score,
                    "trend_released": trend_released,
                    "confirm_seconds": age,
                    "source": row["source"],
                }
    return {
        **meta,
        "arm_return_pct": str(ARM_RETURN_PCT),
        "last_observed_at": last_observed_at,
        "peak_price_at_end": str(peak_at_end),
        "peak_return_pct_at_end": str((peak_at_end / entry - 1) * 100),
        "exits": exits,
    }


def main() -> None:
    audit_dir = ROOT / "data" / "audit" / "hold_sell" / DATE / STRATEGY
    atr_by_code = minute_atr10()
    results = []
    for path in sorted(audit_dir.glob("*.jsonl")):
        meta, rows = rows_for_position(path)
        results.append(simulate(meta, rows, atr_by_code.get(str(meta["code"]), {})))
    print(json.dumps({
        "provenance": "HYPOTHETICAL",
        "production_changed": "NOT_CHANGED",
        "date": DATE,
        "strategy": STRATEGY,
        "condition": "peak>=3%; drawdown>=ATR10*k; flow_score>=2/4; MA5+MA10 trend released; persistent>=3s",
        "atr_source": str(ROOT / "data" / "돈맥_1분봉.json"),
        "results": results,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
