# -*- coding: utf-8 -*-
"""추세추종 보드 v1 — 전체 종목에서 "횡보 후 확실한 일봉 상승 전환" 종목을 선별한다.

[2026-08-28 친구님 지시] "전체 종목에서 나쁜 것들은 원천배제하고, 일봉 이평선
5/10/20/60/120/200을 이용해서 횡보 후에 일봉이 확실한 오름세에 올라왔음을
확인하고, 우리 전략들이 이걸 쓰게 하고 싶다."

설계 원칙:
  - 독립 보드(DRY-RUN): 어떤 전략·주문 경로도 건드리지 않는다. 산출물은
    data\trend_follow_board_v1.json 과 바탕화면 추세추종판.html 뿐이다.
  - 자료원: data\eod_daily_bars.csv (수집기가 스팩·ETF를 이미 제외한 상태,
    2025-08-14부터 252거래일 — MA200 계산 가능[실측]).
  - 관리종목·거래정지 표식은 이 자료에 없어 거래대금 하한으로 대신 거른다.

상태 정의(일봉 종가 단순이평):
  BEAR         종가<MA20<MA60, MA20 하락 — 제외
  COMPRESSION  MA5~MA60 밀집(<=4%) — 관찰만
  TREND_START  최근 횡보(25~3일 전 밀집<=5% 5일 이상) 후 정배열 진입 +
               20일 박스 상단 돌파 = "횡보 후 확실한 오름세" (핵심 상태)
  TREND_UP     정배열 + MA20 상승
  TREND_STRONG 완전 정배열(MA120/200 위) + MA60까지 상승
  NEUTRAL      그 외 — 제외

사용: C:\python310\python.exe C:\stock_bot\RUN\trend_follow_board_v1.py [--top 200]
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime
from pathlib import Path

RUN_DIR = str(Path(__file__).resolve().parent)
if RUN_DIR not in sys.path:
    sys.path.insert(0, RUN_DIR)

from flow_trend_selector_v1 import build_flow_trend

ROOT = Path(r"C:\stock_bot")
SOURCE = ROOT / "data" / "eod_daily_bars.csv"
OUT_JSON = ROOT / "data" / "trend_follow_board_v1.json"
OUT_HTML = Path(r"C:\Users\UserK\Desktop\추세추종판.html")
MONEY_FLOW_JSON = ROOT / "data" / "돈흐름_선별판.json"
FLOW_TREND_JSON = ROOT / "data" / "flow_trend_intraday_board_v1.json"
FLOW_TREND_STATE = ROOT / "data" / "flow_trend_intraday_state_v1.json"
MICRO_SNAPSHOT_JSON = ROOT / "IPC" / "live_micro_snapshot.json"

MIN_BARS = 60                  # MA60까지는 필수
MIN_VALUE_20D_MKRW = 3_000     # 20일 평균 거래대금 하한: 30억원(백만원 단위, 8/28 친구님 지정)
MIN_PRICE = 10_000             # 프로젝트 관례(SAFEPLUS_MIN_PRICE)와 동일 — 저가주 제외
COMPRESSION_NOW_PCT = 4.0      # 오늘 밀집 판정
COMPRESSION_PAST_PCT = 5.0     # 과거 횡보 판정
PAST_WINDOW = (40, 3)          # 횡보를 찾는 과거 구간 [t-40, t-3]
PAST_MIN_DAYS = 5              # 그 구간에서 밀집이 5일 이상이면 "횡보 있었다"


def is_preferred_name(name: str) -> bool:
    """우선주 이름 판별(1우B·우선 포함)."""
    return name.endswith("우") or name.endswith("우B") or "우선" in name


def load_series() -> dict:
    """code -> {name, market, closes[], highs[], values[]} (날짜 오름차순)."""
    rows: dict[str, dict] = {}
    with SOURCE.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            code = str(row.get("code") or "").zfill(6)
            try:
                close = float(row.get("close") or 0)
                high = float(row.get("high") or 0)
                value = float(row.get("value") or 0)
            except (TypeError, ValueError):
                continue
            if close <= 0:
                continue
            entry = rows.setdefault(code, {
                "name": row.get("name") or code,
                "market": row.get("market") or "",
                "dates": [], "closes": [], "highs": [], "values": [],
            })
            entry["dates"].append(str(row.get("date")))
            entry["closes"].append(close)
            entry["highs"].append(high)
            entry["values"].append(value)
    for entry in rows.values():
        order = sorted(range(len(entry["dates"])), key=lambda i: entry["dates"][i])
        for key in ("dates", "closes", "highs", "values"):
            entry[key] = [entry[key][i] for i in order]
    return rows


def sma(closes: list, index: int, period: int):
    if index + 1 < period:
        return None
    return sum(closes[index + 1 - period:index + 1]) / period


def compression_at(closes: list, index: int):
    mas = [sma(closes, index, p) for p in (5, 10, 20, 60)]
    if any(m is None for m in mas) or closes[index] <= 0:
        return None
    return (max(mas) - min(mas)) / closes[index] * 100.0


def judge(entry: dict, latest_date: str = "") -> dict | None:
    closes, highs, values = entry["closes"], entry["highs"], entry["values"]
    last = len(closes) - 1
    if len(closes) < MIN_BARS:
        return None
    if latest_date and entry["dates"][-1] != latest_date:
        return None                      # 최신일 미거래 = 거래정지 근사 — 제외
    if is_preferred_name(entry["name"]):
        return None                      # 우선주 제외
    value20 = sum(values[-20:]) / min(20, len(values))
    if value20 < MIN_VALUE_20D_MKRW:
        return None
    close = closes[last]
    if close <= MIN_PRICE:
        return None                      # 저가주 제외(프로젝트 관례 1만원)
    ma = {p: sma(closes, last, p) for p in (5, 10, 20, 60, 120, 200)}
    ma20_prev = sma(closes, last - 5, 20)
    ma60_prev = sma(closes, last - 5, 60)
    comp_now = compression_at(closes, last)
    if ma[20] is None or ma[60] is None or ma20_prev is None or comp_now is None:
        return None

    # 과거 횡보: [t-25, t-3] 구간에서 밀집일 수
    past_tight = 0
    for back in range(PAST_WINDOW[1], PAST_WINDOW[0] + 1):
        past = compression_at(closes, last - back)
        if past is not None and past <= COMPRESSION_PAST_PCT:
            past_tight += 1
    had_compression = past_tight >= PAST_MIN_DAYS
    box_high20 = max(highs[-21:-1]) if len(highs) > 21 else max(highs[:-1] or [close])
    breakout = close >= box_high20 * 0.99
    aligned = close > ma[5] > ma[10] > ma[20]
    ma20_up = ma[20] > ma20_prev
    ma60_up = ma60_prev is not None and ma[60] > ma60_prev

    stretch_now = (close / ma[20] - 1) * 100
    ret20 = (close / closes[-21] - 1) * 100 if len(closes) > 21 else 0.0
    if close < ma[20] < ma[60] and not ma20_up:
        state = "BEAR"
    elif stretch_now > 30 or ret20 > 60:
        # ★과열 컷 — "횡보 후 초기 오름세"가 목적이므로 MA20 이격 30% 초과
        #   또는 20일 수익률 +60% 초과(단기 과속) 급등주는 후보에서 뺀다.
        #   [8/28 친구님 점검 "너무 고점인지 봐" → 상위 10 중 6개가 과속으로 드러나 추가]
        state = "OVERHEATED"
    elif had_compression and aligned and ma[20] >= ma20_prev and breakout:
        state = "TREND_START"
    elif (aligned and ma[20] > ma[60] and ma20_up and ma60_up
          and (ma[120] is None or close > ma[120])
          and (ma[200] is None or close > ma[200])):
        state = "TREND_STRONG"
    elif aligned and ma20_up and close > ma[60]:
        state = "TREND_UP"
    elif comp_now <= COMPRESSION_NOW_PCT:
        state = "COMPRESSION"
    else:
        state = "NEUTRAL"

    # 점수(0~100): 배열 30 + 기울기 20 + 신선도 20 + 수급 15 + 장기 15 - 과열
    score = 0.0
    for cond in (close > ma[5], ma[5] > ma[10], ma[10] > ma[20],
                 ma[20] > ma[60] if ma[60] else False,
                 (ma[60] or 0) > (ma[120] or float("inf"))):
        score += 6.0 if cond else 0.0
    slope20 = (ma[20] / ma20_prev - 1) * 100 if ma20_prev else 0.0
    slope60 = (ma[60] / ma60_prev - 1) * 100 if ma60_prev else 0.0
    score += max(0.0, min(10.0, slope20 * 4))
    score += max(0.0, min(10.0, slope60 * 6))
    score += {"TREND_START": 20.0, "TREND_UP": 10.0, "TREND_STRONG": 5.0}.get(state, 0.0)
    value5 = sum(values[-5:]) / 5
    score += max(0.0, min(15.0, (value5 / value20 - 1) * 15)) if value20 else 0.0
    if ma[120] and close > ma[120]:
        score += 7.0
    if ma[200] and close > ma[200]:
        score += 8.0
    stretch = (close / ma[20] - 1) * 100
    if stretch > 15:
        score -= min(15.0, stretch - 15)
    score = round(max(0.0, min(100.0, score)), 1)

    return {
        "code": entry_code(entry), "name": entry["name"], "market": entry["market"],
        "close": close, "state": state, "trend_score": score,
        "ma5": r0(ma[5]), "ma10": r0(ma[10]), "ma20": r0(ma[20]),
        "ma60": r0(ma[60]), "ma120": r0(ma[120]), "ma200": r0(ma[200]),
        "compression_pct": round(comp_now, 2), "had_compression": had_compression,
        "breakout20": breakout, "value_20d_avg_mkrw": round(value20),
        "stretch_vs_ma20_pct": round(stretch, 2), "last_date": entry["dates"][-1],
    }


def entry_code(entry):
    return entry.get("_code", "")


def r0(value):
    return round(value, 1) if value is not None else None


def build_html(meta: dict, rows: list, flow_trend: dict | None = None) -> str:
    color = {"TREND_START": "#4ade80", "TREND_UP": "#60a5fa",
             "TREND_STRONG": "#c084fc", "COMPRESSION": "#d6a15a"}
    body = []
    for row in rows[:60]:
        body.append(
            "<tr><td>{code}</td><td>{name}</td>"
            "<td style='color:{c};font-weight:bold'>{state}</td>"
            "<td>{score}</td><td>{close:,.0f}</td><td>{comp}</td><td>{stretch}</td>"
            "<td>{value:,}</td></tr>".format(
                code=row["code"], name=row["name"], c=color.get(row["state"], "#333"),
                state=row["state"], score=row["trend_score"], close=row["close"],
                comp=row["compression_pct"], stretch=row["stretch_vs_ma20_pct"],
                value=row["value_20d_avg_mkrw"]))
    flow_trend = flow_trend or {}
    flow_rows = flow_trend.get("display") or flow_trend.get("watch") or []
    early_rows = flow_trend.get("early_rebounds") or []
    early_body = []
    for row in early_rows[:30]:
        low_time = str(row.get("session_low_time") or "")
        low_time = low_time[11:19] if len(low_time) >= 19 else "-"
        early_body.append(
            "<tr><td>{code}</td><td>{name}</td><td>{low_time}</td>"
            "<td>{rebound:+.2f}%</td><td>{speed_1m:+.2f}%</td><td>{speed_3m:+.2f}%</td>"
            "<td>{accel:+,.1f}</td><td>{vwap_gap:+.2f}%</td>"
            "<td class='{liq_class}'>{liquidity}</td><td class='{vol_class}'>{volatility}</td></tr>".format(
                code=row.get("code", ""), name=row.get("name", ""), low_time=low_time,
                rebound=float(row.get("rebound_pct") or 0),
                speed_1m=float(row.get("rebound_speed_1m_pct") or 0),
                speed_3m=float(row.get("rebound_speed_3m_pct") or 0),
                accel=float(row.get("flow_accel_mkrw_per_min") or 0),
                vwap_gap=float(row.get("vwap_gap_pct") or 0),
                liquidity=row.get("liquidity_status", "WAIT"),
                liq_class=str(row.get("liquidity_status", "WAIT")).lower(),
                volatility=row.get("volatility_status", "WAIT"),
                vol_class=str(row.get("volatility_status", "WAIT")).lower(),
            )
        )
    early_section = (
        "<h3>초기반등 감지 — SHADOW_ORDER_ZERO</h3>"
        f"<p>현재 감지 {len(early_rows)}종목 · 새 저점 후 반등속도+유입전환+VWAP회복</p>"
        "<div class='table-wrap'><table><tr><th>코드</th><th>종목</th><th>저점확인</th>"
        "<th>반등률</th><th>1분속도</th><th>3분속도</th><th>유입가속</th>"
        "<th>VWAP이격</th><th>유동성</th><th>변동성</th></tr>"
        + ("".join(early_body) if early_body else "<tr><td colspan='10'>감지 대기 중</td></tr>")
        + "</table></div>"
    )
    priority_rows = [
        row for row in flow_rows
        if row.get("liquidity_status") == "PASS"
        and row.get("volatility_status") == "PASS"
    ][:10]
    priority_rank = {
        str(row.get("code") or ""): rank
        for rank, row in enumerate(priority_rows, start=1)
    }
    flow_body = []
    for rank, row in enumerate(flow_rows[:30], start=1):
        low_time = str(row.get("session_low_time") or "")
        low_time = low_time[11:19] if len(low_time) >= 19 else "-"
        liquidity = row.get("liquidity_status", "WAIT")
        volatility = row.get("volatility_status", "WAIT")
        entry_phase = row.get("entry_phase", "FLOW_FOUND")
        phase_label = {
            "FLOW_FOUND": "돈유입발견",
            "OVERHEAT_WAIT": "과열대기",
            "PULLBACK_READY": "눌림확인",
            "REACCEL_TRIGGER": "재가속완료",
        }.get(entry_phase, entry_phase)
        phase_class = {
            "FLOW_FOUND": "phase-flow",
            "OVERHEAT_WAIT": "phase-overheat",
            "PULLBACK_READY": "phase-pullback",
            "REACCEL_TRIGGER": "phase-trigger",
        }.get(entry_phase, "")
        eligible_rank = priority_rank.get(str(row.get("code") or ""), 0)
        medal = (
            "🥇1" if eligible_rank == 1 else
            "🥈2" if eligible_rank == 2 else
            "🥉3" if eligible_rank == 3 else
            f"🏅{eligible_rank}" if eligible_rank else "-"
        )
        flow_body.append(
            "<tr><td>{rank}</td><td>{medal}</td><td>{code}</td><td>{name}</td><td>{state}</td>"
            "<td>{score:.1f}</td><td>{abs_flow:.1f}</td><td class='{phase_class}'>{phase_label}</td>"
            "<td>{vwap_gap:+.2f}%</td><td>{peak_pullback:+.2f}%</td>"
            "<td>{accel:+,.1f}</td><td>{streak}</td>"
            "<td>{chg:+.2f}%</td><td>{rs:+.2f}%</td><td>{low_time}</td>"
            "<td>{rebound_pct:+.2f}%</td>"
            "<td>{depth:.2f}</td><td>{value_1m:.2f}</td><td>{spread:.2f}%</td>"
            "<td>{slice_cap:,}만원</td><td class='{liq_class}'>{liquidity}</td>"
            "<td>{recent_range:.2f}%</td><td>{required_range:.2f}%</td>"
            "<td>{pattern}</td><td class='{vol_class}'>{volatility}</td><td>{status}</td></tr>".format(
                rank=rank, medal=medal, code=row.get("code", ""), name=row.get("name", ""),
                state=row.get("trend_state", ""), score=float(row.get("flow_score") or 0),
                abs_flow=float(row.get("absolute_flow_percentile") or 0),
                phase_class=phase_class, phase_label=phase_label,
                vwap_gap=float(row.get("vwap_gap_pct") or 0),
                peak_pullback=float(row.get("peak_pullback_pct") or 0),
                accel=float(row.get("flow_accel_mkrw_per_min") or 0),
                streak=int(row.get("positive_streak") or 0),
                chg=float(row.get("change_pct") or 0),
                rs=float(row.get("relative_strength_pct") or 0),
                low_time=low_time,
                rebound_pct=float(row.get("rebound_pct") or 0),
                depth=float(row.get("two_way_depth_eok") or 0),
                value_1m=float(row.get("one_min_value_eok") or 0),
                spread=float(row.get("spread_pct") or 0),
                slice_cap=int(row.get("slice_cap_manwon") or 0),
                liquidity=liquidity, liq_class=liquidity.lower(),
                recent_range=float(row.get("recent_range_pct") or 0),
                required_range=float(row.get("required_volatility_pct") or 0),
                pattern=row.get("volatility_pattern", "-"),
                volatility=volatility, vol_class=volatility.lower(),
                status=row.get("status", "WATCH")))
    flow_section = early_section + (
        "<h3>FLOW_TREND 장중 돈유입 상위 30 — SHADOW_ORDER_ZERO</h3>"
        f"<p>상태 {flow_trend.get('status', 'NO_DATA')} · "
        f"수급시각 {flow_trend.get('source_ts', '-')} · "
        "3회 연속 유입+가격반응 후 READY · [HYPOTHETICAL] 2천만원 유동성 참고</p>"
        "<div class='table-wrap'><table><tr><th>순위</th><th>우선</th><th>코드</th><th>종목</th><th>추세</th><th>점수</th><th>절대유입%</th>"
        "<th>진입단계</th><th>VWAP이격</th><th>고점눌림</th>"
        "<th>유입가속(백만원/분)</th><th>연속</th><th>등락</th><th>상대강도</th>"
        "<th>저점확인</th><th>반등률</th>"
        "<th>양방향호가(억원)</th><th>1분거래(억원)</th><th>스프레드</th>"
        "<th>1회한도</th><th>유동성</th><th>5분변동</th><th>필요변동</th>"
        "<th>변동패턴</th><th>변동성</th><th>상태</th></tr>"
        + "".join(flow_body) + "</table></div>"
    )
    return (
        "<html><head><meta charset='utf-8'><title>추세추종판</title>"
        "<meta http-equiv='refresh' content='300'>"
        "<style>body{font-family:'Malgun Gothic';font-size:17px;line-height:1.4;margin:16px;background:#080b10;color:#aeb7c4;overflow-x:auto}"
        "h2{font-size:28px;margin:6px 0 12px;color:#d5dbe4}h3{font-size:22px;margin:20px 0 6px;color:#cbd5e1}p{font-size:16px;margin:5px 0 12px;color:#8f9aaa}"
        ".table-wrap{overflow-x:auto;border:1px solid #263142;border-radius:12px;background:#0b1017;box-shadow:0 8px 24px rgba(0,0,0,.28)}"
        "table{border-collapse:separate;border-spacing:0;font-size:16px;line-height:1.35;background:#0b1017;width:max-content;min-width:100%}"
        "th{position:sticky;top:0;z-index:2;background:#151d29;color:#c4ccd7;font-weight:700}"
        "td,th{border-right:1px solid #263142;border-bottom:1px solid #263142;padding:7px 10px;text-align:right;white-space:nowrap}"
        "tr:nth-child(even) td{background:#0e141d}tr:hover td{background:#17202c}"
        "td:nth-child(4){text-align:left;font-weight:600;color:#c6ced9}"
        "td.pass{color:#72d39a;font-weight:800;background:#0d2118}td.wait{color:#d7ad67;font-weight:700;background:#241d10}"
        "td.phase-flow{color:#8fb8e8}td.phase-overheat{color:#ef8f82;font-weight:800}"
        "td.phase-pullback{color:#e5c26f;font-weight:800}td.phase-trigger{color:#70d99a;font-weight:900;background:#0d2118}"
        "</style></head><body>"
        f"<h2>추세추종판 — {meta['source_date']} 일봉 기준 (DRY-RUN, 참고용)</h2>"
        + ("<p style='color:#c62828;font-weight:bold'>⛔ 시장 하락세(레짐 휴면) — "
           f"중앙값 {meta['market_breadth_median_pct']}% : 신규진입 비권장</p>"
           if meta.get("market_regime") == "DOWN_DORMANT" else
           f"<p style='color:#2e7d32'>시장 레짐 양호 (중앙값 +{meta['market_breadth_median_pct']}%)</p>")
        + f"<p>생성 {meta['generated_at']} · 유니버스 {meta['universe']} · "
        f"START {meta['states'].get('TREND_START', 0)} / UP {meta['states'].get('TREND_UP', 0)} / "
        f"STRONG {meta['states'].get('TREND_STRONG', 0)} / 관찰 {meta['states'].get('COMPRESSION', 0)}"
        "</p>" + flow_section
        + "<h3>일봉 추세 후보</h3><table><tr><th>코드</th><th>종목</th><th>상태</th><th>점수</th>"
        "<th>종가</th><th>밀집%</th><th>MA20이격%</th><th>20일대금(백만)</th></tr>"
        + "".join(body) + "</table>"
        "<p style='color:#888'>이 판은 주문·전략과 연결되지 않은 관찰 전용이다.</p>"
        "</body></html>")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--top", type=int, default=200)
    args = parser.parse_args()

    series = load_series()
    latest_date = max((entry["dates"][-1] for entry in series.values()
                       if entry["dates"]), default="")
    # ★시장 레짐 — 종목별 (종가/MA20-1) 중앙값. 음수면 시장 하락세 = 보드 휴면 권고.
    #   걸어가기 검증(8/28): 이 필터로 하락 5구간 회피, 활성 4구간 초과수익 전부 양수.
    breadth = []
    for entry in series.values():
        if len(entry["closes"]) >= 21 and entry["dates"][-1] == latest_date:
            ma20 = sum(entry["closes"][-20:]) / 20
            if ma20 > 0:
                breadth.append((entry["closes"][-1] / ma20 - 1) * 100)
    breadth.sort()
    breadth_median = breadth[len(breadth) // 2] if breadth else 0.0
    regime = "UP" if breadth_median >= 0 else "DOWN_DORMANT"
    results = []
    states: dict[str, int] = {}
    for code, entry in series.items():
        entry["_code"] = code
        verdict = judge(entry, latest_date)
        if verdict is None:
            continue
        states[verdict["state"]] = states.get(verdict["state"], 0) + 1
        results.append(verdict)

    candidates = sorted(
        (row for row in results
         if row["state"] in ("TREND_START", "TREND_UP", "TREND_STRONG")),
        key=lambda row: (-row["trend_score"], row["code"]))[:args.top]
    observe = sorted(
        (row for row in results if row["state"] == "COMPRESSION"),
        key=lambda row: (-row["trend_score"], row["code"]))[:50]

    meta = {
        "schema": "trend_follow_board_v1",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "source_date": candidates[0]["last_date"] if candidates else "",
        "universe": len(series), "judged": len(results), "states": states,
        "market_regime": regime,
        "market_breadth_median_pct": round(breadth_median, 2),
        "mode": "DRY_RUN_OBSERVE_ONLY",
    }
    base_payload = {**meta, "candidates": candidates, "observe": observe}
    try:
        flow_payload = json.loads(MONEY_FLOW_JSON.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        flow_payload = {}
    try:
        flow_state = json.loads(FLOW_TREND_STATE.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        flow_state = {}
    try:
        micro_snapshot = json.loads(
            MICRO_SNAPSHOT_JSON.read_text(encoding="utf-8-sig")
        )
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        micro_snapshot = {}
    flow_trend, next_flow_state = build_flow_trend(
        base_payload, flow_payload, flow_state, micro_snapshot,
    )
    for path, data in ((FLOW_TREND_JSON, flow_trend),
                       (FLOW_TREND_STATE, next_flow_state)):
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        temporary.replace(path)
    payload = {**base_payload, "flow_trend": flow_trend}
    tmp = OUT_JSON.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(OUT_JSON)
    OUT_HTML.write_text(build_html(meta, candidates, flow_trend), encoding="utf-8")

    print(json.dumps({"universe": len(series), "judged": len(results),
                      "states": states, "candidates": len(candidates),
                      "json": str(OUT_JSON), "html": str(OUT_HTML)},
                     ensure_ascii=False, indent=1))
    for row in candidates[:12]:
        print(f"  {row['state']:<12} {row['trend_score']:>5} {row['code']} "
              f"{row['name']} (밀집 {row['compression_pct']}% 이격 {row['stretch_vs_ma20_pct']}%)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
