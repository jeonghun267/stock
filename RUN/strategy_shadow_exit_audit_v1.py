# -*- coding: utf-8 -*-
"""새전략 01~05 매도품질 그림자 계측 — 관측 전용(브로커 import 0·TR 0·주문 0).

[목적] 친구님 필수 기록표를 매일 자동 축적한다.
  전략·종목·신호시간·매수가·MFE·MAE·매도가·매도사유·비용후 수익률·후보순위

[원리] 실거래 로직에는 손대지 않는다. 장 마감 뒤 아래 3개를 읽어서 계산만 한다.
  1) data\strategy_0N_signal_v1\*_signals_YYYYMMDD.csv   — 그날 낸 신호 전건(후보순위 포함)
  2) data\strategy_0N_rotation_v1\*_events_YYYYMMDD.csv  — 실제 체결·매도사유
  3) data\shadow\mf_1s_capture\mf_1s_YYYYMMDD.csv        — 1초 가격경로(MFE/MAE·대안매도)

[가상진입] 신호는 났지만 슬롯·차단으로 못 산 건도 가상 진입으로 함께 기록한다.
  (실제 매수 슬리피지 실측 평균 +0.10%를 얹어 불리하게 잡는다)

[출력] data\shadow_exit_audit\exit_audit_all.csv 에 누적 append(중복 키는 건너뜀)
       C:\stock_bot\보고서\매도품질_그림자_YYYYMMDD.txt 요약

[안전] 브로커 import 없음. 주문 함수 없음. 기존 파일 수정 없음. 실패해도 실거래 영향 0.
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
from array import array
from datetime import datetime
from pathlib import Path

ROOT = Path(r"C:\stock_bot")
DATA = ROOT / "data"
CAP_DIR = DATA / "shadow" / "mf_1s_capture"
OUT_DIR = DATA / "shadow_exit_audit"
LEDGER = OUT_DIR / "exit_audit_all.csv"
REPORT_DIR = ROOT / "보고서"

COST_PCT = 0.21          # 왕복 수수료 0.03 + 세금 0.18
VIRTUAL_SLIP_PCT = 0.10  # 미진입 신호에 얹는 매수 슬리피지 실측치
MIN_PRICE = 10000.0

# 1초 캡처 열 위치
I_TS, I_CODE, I_PX = 0, 1, 2

STRATEGIES = {
    "01": ("S01_OPEN_SURGE", "장초반 급상승 초입"),
    "02": ("S02_LOW_BUY_SELL_EXHAUSTION", "저점매수·매도소진"),
    "03": ("S03_VALLEY_RAPID_REBOUND", "골짜기 급반등"),
    "04": ("S04_PULLBACK", "눌림목"),
    "05": ("S05_BASE_BREAKOUT", "장중 베이스 돌파"),
}

# 대안 매도규칙 — 한 번에 하나만 바꿔 비교하기 위한 후보들
VARIANTS = (
    ("트레일현행_60분", dict(trail=((2.0, 1.5), (4.0, 2.0), (7.0, 2.5)), hold_min=60)),
    ("익절1.5_20분", dict(target=1.5, hold_min=20)),
    ("익절2.0_20분", dict(target=2.0, hold_min=20)),
    ("익절2.5_20분", dict(target=2.5, hold_min=20)),
    ("익절2.0_30분", dict(target=2.0, hold_min=30)),
    ("무익절_20분", dict(hold_min=20)),
    ("무익절_60분", dict(hold_min=60)),
)

FIELDS = [
    "날짜", "전략", "전략명", "종목", "종목명", "신호시각", "후보순위", "진입종류",
    "매수가", "매도가", "매도사유", "보유초", "실현수익률", "비용후수익률",
    "MFE5", "MAE5", "MFE15", "MAE15", "MFE30", "MAE30", "MFE60", "MAE60",
    "최고점도달_분", "매도후15분고점", "파동수", "저점대비진입", "호가불균형",
] + [name for name, _ in VARIANTS]


def _f(value, default=0.0):
    try:
        return float(str(value or "").replace(",", "").strip())
    except (TypeError, ValueError):
        return default


def load_price_paths(day: str, codes: set[str]):
    """1초 캡처에서 필요한 종목의 (경과초, 가격) 경로만 뽑는다."""
    path = CAP_DIR / f"mf_1s_{day}.csv"
    if not path.exists() or not codes:
        return {}
    base = datetime.strptime(day, "%Y%m%d").replace(hour=9)
    tmap: dict[str, array] = {}
    pmap: dict[str, array] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        fh.readline()
        for line in fh:
            hh = line[11:13]
            if hh < "09" or hh > "15":
                continue
            head = line.split(",", 3)
            if len(head) < 3:
                continue
            code = head[I_CODE]
            if code not in codes:
                continue
            try:
                px = float(head[I_PX])
                ts = datetime.fromisoformat(head[I_TS])
            except ValueError:
                continue
            off = int((ts - base).total_seconds())
            if code not in tmap:
                tmap[code] = array("i")
                pmap[code] = array("f")
            if not tmap[code] or tmap[code][-1] != off:
                tmap[code].append(off)
                pmap[code].append(px)
    return {c: (tmap[c], pmap[c]) for c in tmap}


def _start_index(ts_arr: array, start_off: int) -> int:
    lo, hi = 0, len(ts_arr)
    while lo < hi:
        mid = (lo + hi) // 2
        if ts_arr[mid] < start_off:
            lo = mid + 1
        else:
            hi = mid
    return lo


def mfe_mae(path, start_off: int, entry: float, minutes: int):
    ts_arr, px_arr = path
    i = _start_index(ts_arr, start_off)
    end = start_off + minutes * 60
    hi = lo = entry
    peak_at = start_off
    while i < len(ts_arr) and ts_arr[i] <= end:
        px = px_arr[i]
        if px > hi:
            hi, peak_at = px, ts_arr[i]
        if px < lo:
            lo = px
        i += 1
    return ((hi / entry - 1) * 100, (lo / entry - 1) * 100,
            (peak_at - start_off) / 60.0)


def simulate(path, start_off: int, entry: float, *, stop=-2.0, target=None,
             hold_min=None, trail=None):
    ts_arr, px_arr = path
    i = _start_index(ts_arr, start_off)
    limit = start_off + hold_min * 60 if hold_min else 10 ** 9
    peak = entry
    last = entry
    while i < len(ts_arr):
        if ts_arr[i] > limit:
            return (last / entry - 1) * 100
        px = last = px_arr[i]
        ret = (px / entry - 1) * 100
        if ret <= stop:
            return stop
        if target is not None and ret >= target:
            return target
        if px > peak:
            peak = px
        if trail:
            peak_ret = (peak / entry - 1) * 100
            th = 0.0
            for arm, drop in trail:
                if peak_ret >= arm:
                    th = drop
            if th > 0 and (peak - px) / peak * 100 >= th:
                return ret
        i += 1
    return (last / entry - 1) * 100


def read_csv(path: Path):
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def collect(day: str):
    """전략별 (신호 전건, 실체결 왕복) 수집."""
    trades = []
    for num, (sid, sname) in STRATEGIES.items():
        sig_rows = read_csv(
            DATA / f"strategy_{num}_signal_v1" / f"strategy_{num}_signals_{day}.csv")
        evt_rows = read_csv(
            DATA / f"strategy_{num}_rotation_v1" / f"strategy_{num}_events_{day}.csv")
        buys = [r for r in sig_rows if str(r.get("action") or "") == "BUY_READY"]
        # 후보순위 = 그날 그 전략 안에서 신호가 나온 순서
        for rank, sig in enumerate(buys, start=1):
            sig["_rank"] = rank
        # 실체결 매칭: BUY_CONFIRMED / SELL_CONFIRMED 짝짓기
        opened: dict[str, dict] = {}
        fills: list[dict] = []
        for e in evt_rows:
            ev = str(e.get("event") or "")
            code = str(e.get("code") or "").zfill(6)
            if ev == "BUY_CONFIRMED":
                opened[code] = e
            elif ev == "SELL_CONFIRMED" and code in opened:
                fills.append({"buy": opened.pop(code), "sell": e})
        used = set()
        for fill in fills:
            code = str(fill["buy"].get("code") or "").zfill(6)
            btime = str(fill["buy"].get("ts") or "")[11:19]
            match = None
            for sig in buys:
                if (str(sig.get("code") or "").zfill(6) == code
                        and id(sig) not in used
                        and str(sig.get("ts") or "")[11:19] <= btime):
                    match = sig
            if match is not None:
                used.add(id(match))
            trades.append({
                "num": num, "sid": sid, "sname": sname, "code": code,
                "name": str(fill["buy"].get("name") or code),
                "sig": match, "kind": "실체결",
                "buy_ts": btime, "buy_px": _f(fill["buy"].get("price")),
                "sell_ts": str(fill["sell"].get("ts") or "")[11:19],
                "sell_px": _f(fill["sell"].get("price")),
                "reason": str(fill["sell"].get("reason") or "")[:60],
            })
        for sig in buys:
            if id(sig) in used:
                continue
            px = _f(sig.get("price"))
            if px < MIN_PRICE:
                continue
            trades.append({
                "num": num, "sid": sid, "sname": sname,
                "code": str(sig.get("code") or "").zfill(6),
                "name": str(sig.get("name") or ""), "sig": sig, "kind": "가상",
                "buy_ts": str(sig.get("ts") or "")[11:19],
                "buy_px": px * (1 + VIRTUAL_SLIP_PCT / 100),
                "sell_ts": "", "sell_px": 0.0, "reason": "미진입",
            })
    return trades


def build(day: str) -> list[dict]:
    trades = collect(day)
    if not trades:
        return []
    paths = load_price_paths(day, {t["code"] for t in trades})
    base = datetime.strptime(day, "%Y%m%d").replace(hour=9)
    rows = []
    for t in trades:
        path = paths.get(t["code"])
        if not path or not t["buy_px"]:
            continue
        try:
            btime = datetime.strptime(f"{day} {t['buy_ts']}", "%Y%m%d %H:%M:%S")
        except ValueError:
            continue
        off = int((btime - base).total_seconds())
        entry = t["buy_px"]
        sig = t["sig"] or {}
        realized = ((t["sell_px"] / entry - 1) * 100) if t["sell_px"] else None
        hold_sec = ""
        after_high = ""
        if t["sell_ts"]:
            try:
                stime = datetime.strptime(f"{day} {t['sell_ts']}", "%Y%m%d %H:%M:%S")
                hold_sec = int((stime - btime).total_seconds())
                soff = int((stime - base).total_seconds())
                hi, _, _ = mfe_mae(path, soff, t["sell_px"], 15)
                after_high = round(hi, 2)
            except ValueError:
                pass
        row = {
            "날짜": day, "전략": t["num"], "전략명": t["sname"],
            "종목": t["code"], "종목명": t["name"], "신호시각": t["buy_ts"],
            "후보순위": sig.get("_rank", ""), "진입종류": t["kind"],
            "매수가": round(entry, 1), "매도가": t["sell_px"] or "",
            "매도사유": t["reason"], "보유초": hold_sec,
            "실현수익률": round(realized, 3) if realized is not None else "",
            "비용후수익률": round(realized - COST_PCT, 3) if realized is not None else "",
            "매도후15분고점": after_high,
            "파동수": sig.get("wave_count", ""),
            "저점대비진입": sig.get("entry_gap_pct", ""),
            "호가불균형": sig.get("book_imbalance", ""),
        }
        for m in (5, 15, 30, 60):
            hi, lo, peak_min = mfe_mae(path, off, entry, m)
            row[f"MFE{m}"] = round(hi, 3)
            row[f"MAE{m}"] = round(lo, 3)
            if m == 60:
                row["최고점도달_분"] = round(peak_min, 1)
        for name, kw in VARIANTS:
            row[name] = round(simulate(path, off, entry, **kw) - COST_PCT, 3)
        rows.append(row)
    return rows


def append_ledger(rows: list[dict]) -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    seen = set()
    if LEDGER.exists():
        for old in read_csv(LEDGER):
            seen.add((old.get("날짜"), old.get("전략"), old.get("종목"),
                      old.get("신호시각")))
    fresh = [r for r in rows
             if (r["날짜"], r["전략"], r["종목"], r["신호시각"]) not in seen]
    if not fresh:
        return 0
    new_file = not LEDGER.exists()
    with LEDGER.open("a", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDS)
        if new_file:
            writer.writeheader()
        writer.writerows(fresh)
    return len(fresh)


def summarize(day: str, rows: list[dict]) -> str:
    out = [f"■ 매도품질 그림자 계측 — {day}", ""]
    if not rows:
        out.append("  신호 없음 (또는 1초 캡처 없음)")
        return "\n".join(out)
    real = [r for r in rows if r["진입종류"] == "실체결"]
    out.append(f"  신호 {len(rows)}건 (실체결 {len(real)} / 가상 {len(rows)-len(real)})")
    out.append("")
    if real:
        net = [r["비용후수익률"] for r in real if r["비용후수익률"] != ""]
        if net:
            out.append(f"  ▸ 실제 비용후: 합계 {sum(net):+.2f}%p · 건당 {sum(net)/len(net):+.2f}%p")
        early = [r for r in real if r["매도후15분고점"] not in ("", None)
                 and float(r["매도후15분고점"]) > 0.5]
        out.append(f"  ▸ 매도 후 15분 안에 0.5% 넘게 더 오른 건: {len(early)}/{len(real)}건 (조기매도 의심)")
        peaks = [float(r["최고점도달_분"]) for r in real]
        holds = [int(r["보유초"]) for r in real if r["보유초"] != ""]
        if peaks and holds:
            out.append(f"  ▸ 최고점 도달 평균 {sum(peaks)/len(peaks):.1f}분 vs "
                       f"실제 보유 평균 {sum(holds)/len(holds)/60:.1f}분")
    out.append("")
    out.append("  ▸ 대안 매도규칙 (신호 전건 가상적용, 비용후 건당):")
    for name, _ in VARIANTS:
        vals = [r[name] for r in rows if isinstance(r.get(name), (int, float))]
        if vals:
            out.append(f"      {name:16s} {sum(vals)/len(vals):+6.2f}%p  (합계 {sum(vals):+7.2f}%p)")
    out.append("")
    out.append(f"  누적 장부: {LEDGER}")
    out.append("  ※ 관측 전용 — 주문 0건, TR 0건, 실거래 로직 무수정")
    return "\n".join(out)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default=datetime.now().strftime("%Y%m%d"))
    args = parser.parse_args()
    day = args.date
    rows = build(day)
    added = append_ledger(rows)
    text = summarize(day, rows)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / f"매도품질_그림자_{day}.txt").write_text(text, encoding="utf-8")
    print(text)
    print(f"\n누적 장부에 {added}건 추가")
    return 0


if __name__ == "__main__":
    sys.exit(main())
