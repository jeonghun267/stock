# -*- coding: utf-8 -*-
"""최초 DAILY MA TREND BOARD 조건 재현 및 일봉 차트 QA. 생산/주문 미연결."""
from __future__ import annotations

import json, math
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
import pandas as pd

plt.rcParams["font.family"] = "Malgun Gothic"
plt.rcParams["axes.unicode_minus"] = False

ROOT = Path(r"C:\stock_bot")
SOURCE = ROOT / "data" / "eod_daily_bars.csv"
OUT_JSON = ROOT / "reports" / "initial_ma_board_chart_check_20260827.json"
OUT_PNG = ROOT / "reports" / "initial_ma_board_chart_check_20260827.png"
DAY = "20260827"
MA_WINDOWS = (5, 10, 20, 60, 120, 200)


def ma(close, window, end=None):
    end = len(close) if end is None else end
    start = end - window
    return float(close.iloc[start:end].mean()) if start >= 0 else 0.0


def pct(current, previous):
    return (current / previous - 1.0) * 100.0 if previous > 0 else 0.0


def recent_compression(close):
    best = math.inf
    for days_ago in range(5, 61):
        end, start = len(close) - days_ago, len(close) - days_ago - 30
        if start < 0 or end < 30:
            continue
        window = close.iloc[start:end]
        center = float(window.mean())
        spread = (float(window.max()) - float(window.min())) / center * 100.0
        m5, m10, m20 = (ma(close, w, end) for w in (5, 10, 20))
        ma_spread = (max(m5, m10, m20) - min(m5, m10, m20)) / center * 100.0
        slope20 = abs(pct(m20, ma(close, 20, end - 10)))
        best = min(best, spread)
        if spread <= 18.0 and ma_spread <= 5.0 and slope20 <= 3.0:
            return True, round(spread, 3), days_ago
    return False, round(best, 3) if math.isfinite(best) else 0.0, 0


def classify(frame):
    close = frame["close"].astype(float).reset_index(drop=True)
    last = frame.iloc[-1]
    if len(close) < 210 or float(last["volume"]) <= 0 or float(last["value"]) / 100.0 < 20.0:
        return None
    current = float(close.iloc[-1])
    mas = {w: ma(close, w) for w in MA_WINDOWS}
    slopes = {5: pct(mas[5], ma(close, 5, len(close)-5)),
              10: pct(mas[10], ma(close, 10, len(close)-5)),
              20: pct(mas[20], ma(close, 20, len(close)-10)),
              60: pct(mas[60], ma(close, 60, len(close)-10)),
              120: pct(mas[120], ma(close, 120, len(close)-20)),
              200: pct(mas[200], ma(close, 200, len(close)-20))}
    compressed, compression_pct, compression_days_ago = recent_compression(close)
    short_stack = current > mas[5] > mas[10] > mas[20]
    mid_stack = short_stack and mas[20] > mas[60] and current > mas[120]
    full_stack = mid_stack and mas[60] > mas[120] > mas[200]
    short_rising = all(slopes[w] > 0 for w in (5, 10, 20))
    mid_rising = short_rising and slopes[60] > 0
    long_rising = mid_rising and slopes[120] > 0 and slopes[200] >= 0
    breakout20 = current > float(close.iloc[-21:-1].max())
    breakout60 = current > float(close.iloc[-61:-1].max())
    if compressed and full_stack and long_rising: state = "TREND_STRONG"
    elif compressed and mid_stack and mid_rising: state = "TREND_UP"
    elif compressed and short_stack and short_rising and breakout20 and current > mas[60]: state = "TREND_START"
    else: return None
    order = [current, *(mas[w] for w in MA_WINDOWS)]
    score = min(100, sum(5 for a, b in zip(order, order[1:]) if a > b)
                + sum(5 for w in (5, 10, 20, 60, 120) if slopes[w] > 0)
                + 20 + (15 if breakout20 else 0) + (10 if breakout60 else 0))
    return {"code": str(last["code"]).zfill(6), "name": str(last["name"]), "trend_state": state,
            "trend_score": int(score), "compression_pct": compression_pct,
            "compression_days_ago": compression_days_ago,
            "ma20_distance_pct": round(pct(current, mas[20]), 3)}


def candle_panel(ax, frame, title):
    view = frame.tail(120).copy().reset_index(drop=True)
    x = range(len(view))
    for i, row in view.iterrows():
        up = row["close"] >= row["open"]
        color = "#d95f59" if up else "#356aa0"
        ax.vlines(i, row["low"], row["high"], color=color, linewidth=0.6, alpha=0.75)
        bottom, height = min(row["open"], row["close"]), abs(row["close"] - row["open"])
        ax.add_patch(Rectangle((i-0.3, bottom), 0.6, max(height, 0.01), facecolor=color, edgecolor=color, linewidth=0.4))
    colors = {5:"#e69f00", 10:"#cc79a7", 20:"#009e73", 60:"#0072b2", 120:"#7f7f7f", 200:"#111111"}
    full = frame.copy()
    for w in MA_WINDOWS:
        series = full["close"].rolling(w).mean().tail(120).reset_index(drop=True)
        ax.plot(x, series, label=f"MA{w}", color=colors[w], linewidth=1.2 if w <= 20 else 0.9)
    ax.set_title(title, fontsize=10, loc="left")
    ax.grid(axis="y", color="#dddddd", linewidth=0.5)
    ax.tick_params(labelsize=7); ax.legend(ncol=6, fontsize=6, loc="upper left", frameon=False)


def main():
    cols = ["date", "code", "name", "market", "open", "high", "low", "close", "volume", "value"]
    data = pd.read_csv(SOURCE, dtype={"date":str, "code":str}, usecols=cols, low_memory=False)
    data = data[(data["market"].isin(["KOSPI", "KOSDAQ"])) & (data["date"] <= DAY)].copy()
    for col in ("open", "high", "low", "close", "volume", "value"):
        data[col] = pd.to_numeric(data[col], errors="coerce")
    data = data.dropna(subset=["open", "high", "low", "close"]).sort_values(["code", "date"])
    candidates, frames = [], {}
    for code, frame in data.groupby("code", sort=False):
        if str(frame.iloc[-1]["date"]) != DAY: continue
        result = classify(frame)
        if result:
            candidates.append(result); frames[result["code"]] = frame
    candidates.sort(key=lambda row: (-row["trend_score"], row["code"]))
    fig, axes = plt.subplots(max(1, len(candidates)), 1, figsize=(14, max(4, 3.5*len(candidates))), squeeze=False)
    if candidates:
        for ax, row in zip(axes[:,0], candidates):
            candle_panel(ax, frames[row["code"]], f'{row["code"]} {row["name"]} | {row["trend_state"]} | MA20 distance {row["ma20_distance_pct"]:+.2f}%')
    else:
        axes[0,0].text(0.5, 0.5, "No candidates", ha="center", va="center")
    fig.suptitle("Initial DAILY MA TREND BOARD candidates — 2026-08-27", fontsize=14)
    fig.tight_layout(rect=(0,0,1,0.98)); fig.savefig(OUT_PNG, dpi=150, bbox_inches="tight"); plt.close(fig)
    report = {"provenance":"HYPOTHETICAL", "date":DAY, "source":str(SOURCE), "candidate_count":len(candidates),
              "candidates":candidates, "chart":str(OUT_PNG)}
    OUT_JSON.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__": main()
