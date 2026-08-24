from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
PRICES = ROOT / "data" / "prices_3m.csv"
DAILY = ROOT / "data" / "eod_daily_bars.csv"
OUTPUT = ROOT / "analysis" / "strategy04_w_pullback_backtest.json"
SIGNALS = ROOT / "analysis" / "strategy04_w_pullback_signals.csv"

START_TIME = "09:00:00"
LAST_ENTRY_TIME = "12:00:00"
MIN_PRICE = 10_000.0
MIN_DROP_PCT = -25.0
MAX_DROP_PCT = -10.0
MIN_REBOUND_PCT = 2.0
LOW_TOLERANCE_PCT = 2.0
MIN_SEPARATION_BARS = 2
MAX_CHASE_PCT = 5.0
FIXED_COST_PCT = 0.21


@dataclass(frozen=True)
class Signal:
    date: str
    code: str
    name: str
    variant: str
    entry_ts: str
    entry_price: float
    prev_close: float
    deepest_drop_pct: float
    first_low: float
    first_low_ts: str
    neckline: float
    second_low: float
    second_low_ts: str
    low_difference_pct: float
    rebound_pct: float
    chase_pct: float
    neckline_reclaimed: bool
    forward_15m_pct: float | None
    forward_30m_pct: float | None
    forward_60m_pct: float | None
    mfe_60m_pct: float | None
    mae_60m_pct: float | None
    net_forward_60m_pct: float | None


def load_daily() -> pd.DataFrame:
    daily = pd.read_csv(
        DAILY,
        usecols=["date", "code", "name", "market", "close"],
        dtype={"date": str, "code": str},
        low_memory=False,
    )
    daily["date"] = daily["date"].str.replace("-", "", regex=False).str[:8]
    daily["code"] = daily["code"].str.zfill(6)
    daily = daily[
        daily["market"].eq("KOSDAQ")
        & daily["code"].str.fullmatch(r"\d{6}", na=False)
    ].copy()
    daily = daily.sort_values(["code", "date"]).drop_duplicates(
        ["code", "date"], keep="last"
    )
    daily["prev_close"] = daily.groupby("code", sort=False)["close"].shift(1)
    return daily[["date", "code", "name", "prev_close"]]


def load_prices(valid_codes: set[str]) -> pd.DataFrame:
    chunks: list[pd.DataFrame] = []
    for chunk in pd.read_csv(
        PRICES,
        usecols=["ts", "code", "open", "high", "low", "close", "value"],
        dtype={"code": str},
        chunksize=300_000,
        low_memory=False,
    ):
        chunk["code"] = chunk["code"].str.zfill(6)
        chunk = chunk[chunk["code"].isin(valid_codes)]
        if not chunk.empty:
            chunks.append(chunk)
    prices = pd.concat(chunks, ignore_index=True)
    prices["ts"] = pd.to_datetime(prices["ts"], errors="coerce")
    prices = prices.dropna(subset=["ts", "open", "high", "low", "close"])
    prices["date"] = prices["ts"].dt.strftime("%Y%m%d")
    prices["clock"] = prices["ts"].dt.strftime("%H:%M:%S")
    return prices.sort_values(["date", "code", "ts"])


def future_return(frame: pd.DataFrame, entry_i: int, bars: int) -> float | None:
    target = entry_i + bars
    if target >= len(frame):
        return None
    entry = float(frame.iloc[entry_i]["close"])
    return (float(frame.iloc[target]["close"]) / entry - 1.0) * 100.0


def detect_variant(
    frame: pd.DataFrame,
    *,
    date: str,
    code: str,
    name: str,
    prev_close: float,
    variant: str,
) -> Signal | None:
    work = frame[
        frame["clock"].between(START_TIME, LAST_ENTRY_TIME, inclusive="both")
    ].copy()
    if len(work) < 20 or prev_close < MIN_PRICE:
        return None
    work = work.reset_index(drop=True)
    work["ma3"] = work["close"].rolling(3, min_periods=3).mean()
    work["ma20"] = work["close"].rolling(20, min_periods=20).mean()
    deepest_drop = (float(work["low"].min()) / prev_close - 1.0) * 100.0
    if not MIN_DROP_PCT <= deepest_drop <= MAX_DROP_PCT:
        return None

    for second_i in range(MIN_SEPARATION_BARS + 2, len(work) - 1):
        prefix = work.iloc[: second_i - MIN_SEPARATION_BARS]
        first_i = int(prefix["low"].idxmin())
        first_low = float(work.iloc[first_i]["low"])
        if not MIN_DROP_PCT <= (first_low / prev_close - 1.0) * 100 <= MAX_DROP_PCT:
            continue
        middle = work.iloc[first_i + 1 : second_i]
        if middle.empty:
            continue
        neckline_i = int(middle["high"].idxmax())
        neckline = float(work.iloc[neckline_i]["high"])
        rebound_pct = (neckline / first_low - 1.0) * 100.0
        if rebound_pct < MIN_REBOUND_PCT:
            continue
        second_low = float(work.iloc[second_i]["low"])
        low_difference = (second_low / first_low - 1.0) * 100.0
        if abs(low_difference) > LOW_TOLERANCE_PCT:
            continue
        if second_low >= neckline / 1.015:
            continue

        for entry_i in range(max(19, second_i + 1), len(work)):
            previous = work.iloc[entry_i - 1]
            current = work.iloc[entry_i]
            if variant == "PRICE_RECLAIM_MA20":
                crossed = (
                    float(previous["close"]) <= float(previous["ma20"])
                    and float(current["close"]) > float(current["ma20"])
                )
            else:
                crossed = (
                    float(previous["ma3"]) <= float(previous["ma20"])
                    and float(current["ma3"]) > float(current["ma20"])
                )
            if not crossed:
                continue
            entry = float(current["close"])
            chase_pct = (entry / second_low - 1.0) * 100.0
            if chase_pct > MAX_CHASE_PCT:
                break
            full_i = int(frame.index.get_indexer([work.index[entry_i]])[0])
            # The work frame was reset, so locate by timestamp in the full day.
            entry_ts = current["ts"]
            matches = frame.index[frame["ts"].eq(entry_ts)]
            if len(matches):
                full_i = int(frame.index.get_loc(matches[0]))
            window = frame.iloc[full_i + 1 : full_i + 21]
            mfe = (
                (float(window["high"].max()) / entry - 1.0) * 100.0
                if not window.empty
                else None
            )
            mae = (
                (float(window["low"].min()) / entry - 1.0) * 100.0
                if not window.empty
                else None
            )
            f60 = future_return(frame.reset_index(drop=True), full_i, 20)
            return Signal(
                date=date,
                code=code,
                name=name,
                variant=variant,
                entry_ts=entry_ts.isoformat(),
                entry_price=entry,
                prev_close=prev_close,
                deepest_drop_pct=round(deepest_drop, 4),
                first_low=first_low,
                first_low_ts=work.iloc[first_i]["ts"].isoformat(),
                neckline=neckline,
                second_low=second_low,
                second_low_ts=work.iloc[second_i]["ts"].isoformat(),
                low_difference_pct=round(low_difference, 4),
                rebound_pct=round(rebound_pct, 4),
                chase_pct=round(chase_pct, 4),
                neckline_reclaimed=entry >= neckline,
                forward_15m_pct=_round(future_return(frame.reset_index(drop=True), full_i, 5)),
                forward_30m_pct=_round(future_return(frame.reset_index(drop=True), full_i, 10)),
                forward_60m_pct=_round(f60),
                mfe_60m_pct=_round(mfe),
                mae_60m_pct=_round(mae),
                net_forward_60m_pct=_round(
                    f60 - FIXED_COST_PCT if f60 is not None else None
                ),
            )
    return None


def _round(value: float | None) -> float | None:
    return round(value, 4) if value is not None else None


def summarize(rows: list[Signal]) -> dict[str, object]:
    result: dict[str, object] = {}
    for variant in ("PRICE_RECLAIM_MA20", "MA3_CROSS_MA20"):
        selected = [row for row in rows if row.variant == variant]
        returns = [
            row.net_forward_60m_pct
            for row in selected
            if row.net_forward_60m_pct is not None
        ]
        result[variant] = {
            "signals": len(selected),
            "evaluated_60m": len(returns),
            "win_rate_after_fixed_cost": (
                round(sum(value > 0 for value in returns) / len(returns), 4)
                if returns
                else None
            ),
            "mean_net_60m_pct": _round(sum(returns) / len(returns)) if returns else None,
            "median_net_60m_pct": (
                _round(float(pd.Series(returns).median())) if returns else None
            ),
            "neckline_reclaim_share": (
                round(sum(row.neckline_reclaimed for row in selected) / len(selected), 4)
                if selected
                else None
            ),
        }
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--signals", type=Path, default=SIGNALS)
    args = parser.parse_args()

    daily = load_daily()
    prices = load_prices(set(daily["code"]))
    merged = prices.merge(daily, on=["date", "code"], how="inner")
    rows: list[Signal] = []
    candidates = 0
    for (date, code), frame in merged.groupby(["date", "code"], sort=False):
        prev_close = float(frame.iloc[0]["prev_close"])
        if not prev_close or pd.isna(prev_close):
            continue
        early = frame[frame["clock"].between(START_TIME, LAST_ENTRY_TIME)]
        if early.empty:
            continue
        drop = (float(early["low"].min()) / prev_close - 1.0) * 100.0
        if not MIN_DROP_PCT <= drop <= MAX_DROP_PCT:
            continue
        candidates += 1
        name = str(frame.iloc[0]["name"])
        day = frame.sort_values("ts").reset_index(drop=True)
        for variant in ("PRICE_RECLAIM_MA20", "MA3_CROSS_MA20"):
            signal = detect_variant(
                day,
                date=str(date),
                code=str(code),
                name=name,
                prev_close=prev_close,
                variant=variant,
            )
            if signal is not None:
                rows.append(signal)

    payload = {
        "method": {
            "bar": "3-minute",
            "entry_window": f"{START_TIME}-{LAST_ENTRY_TIME}",
            "drop_from_previous_close_pct": [MIN_DROP_PCT, MAX_DROP_PCT],
            "minimum_w_rebound_pct": MIN_REBOUND_PCT,
            "low_tolerance_pct": LOW_TOLERANCE_PCT,
            "maximum_entry_chase_pct": MAX_CHASE_PCT,
            "fixed_round_trip_cost_pct": FIXED_COST_PCT,
            "note": "Shape/MA feasibility only; historical book, news, and sector data absent.",
        },
        "price_rows": len(merged),
        "dates": [str(merged["date"].min()), str(merged["date"].max())],
        "deep_drop_candidate_days": candidates,
        "summary": summarize(rows),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    pd.DataFrame([asdict(row) for row in rows]).to_csv(
        args.signals, index=False, encoding="utf-8-sig"
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
