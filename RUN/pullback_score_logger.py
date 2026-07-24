# -*- coding: utf-8 -*-
# 추세눌림(PULLBACK) 점수 <-> 수익 로거.
# [2026-06-09] ★READ-ONLY: 로그/eod 파싱만. 매매 로직(buy_sender/bridge/risk/execution/매도) 무수정·무연결.
# 하는 일:
#   1) 매수 체결된 PULLBACK 건의 [진입 score + 진입가]를 pullback_score_log.csv 에 누적(중복 방지).
#   2) 그날 종가/고가가 eod_daily_bars 에 들어오면 수익률(종가比·고가比)·승패를 backfill.
#   3) 누적 건수가 목표(기본 30) 도달하면 "분석 준비 완료" 자동 인지 + 점수구간 승률/수익 분석 출력.
#   4) 아직이면 누적 속도로 "예상 준비 날짜"를 자동 추정.
import csv, re, os, sys
from pathlib import Path
from datetime import datetime

BASE = Path(r"C:\stock_bot")
LOG_ORDER  = BASE / "LOG" / "order_sender_live.log"
LOG_BROKER = BASE / "LOG" / "broker_journal.log"
LOG_CHEJAN = BASE / "LOG" / "timeout_trace_buy.log"
EOD        = BASE / "DATA" / "eod_daily_bars.csv"
OUT        = BASE / "DATA" / "pullback_score_log.csv"
TARGET     = int(os.environ.get("PB_LOG_TARGET", "30"))
EOD_BUY_FROM = 1450   # 이 시각 이후 매수는 EOD_PICK(종가매수)로 보고 PULLBACK 로거서 제외

FIELDS = ["date", "code", "time", "score", "entry_price",
          "day_close", "day_high", "close_ret_pct", "high_ret_pct", "win", "filled"]


def _read_csv(p, enc="utf-8-sig"):
    if not p.exists():
        return [], []
    with p.open(encoding=enc, errors="replace") as f:
        r = csv.DictReader(f)
        return list(r), (r.fieldnames or [])


def load_log():
    rows, _ = _read_csv(OUT)
    return rows


def save_log(rows):
    with OUT.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in FIELDS})


def parse_today_pullback(day):
    """broker_journal에서 day(yyyymmdd) PULLBACK 매수체결(code,time) + chejan 진입가 + order_log score."""
    # 1) 매수 체결 code+time (type=1, EOD_BUY_FROM 이전 = PULLBACK)
    buys = {}   # code6 -> time(HH:MM:SS)
    if LOG_BROKER.exists():
        with LOG_BROKER.open(encoding="utf-8", errors="replace") as f:
            for ln in f:
                if "SENDORDER-REAL" not in ln or "type=1" not in ln:
                    continue
                md = re.search(r"\[(\d{4})-(\d{2})-(\d{2}) (\d{2}):(\d{2}):(\d{2})\]", ln)
                if not md:
                    continue
                d = md.group(1) + md.group(2) + md.group(3)
                if d != day:
                    continue
                hhmm = int(md.group(4) + md.group(5))
                if hhmm >= EOD_BUY_FROM:
                    continue   # 종가매수 시간대 → PULLBACK 아님
                mc = re.search(r"code=(\d+)", ln)
                if mc:
                    buys.setdefault(mc.group(1).zfill(6), md.group(4) + ":" + md.group(5) + ":" + md.group(6))
    if not buys:
        return []
    # 2) 진입가 (chejan 910), code별 마지막 체결가
    entry = {}
    if LOG_CHEJAN.exists():
        with LOG_CHEJAN.open(encoding="utf-8", errors="replace") as f:
            for ln in f:
                if "CHEJAN_RT_OPEN" not in ln or day not in ln.replace("-", ""):
                    continue
                mc = re.search(r"code=A?(\d+)", ln)
                mp = re.search(r"910\(?체결가\)?=(\d+)", ln)  # 910(체결가)=
                if mc and mp:
                    entry[mc.group(1).zfill(6)] = float(mp.group(1))
    # 3) score (order_log CONV_GATE PULLBACK 통과 score=Y code=X), code별 마지막
    score = {}
    if LOG_ORDER.exists():
        with LOG_ORDER.open(encoding="utf-8", errors="replace") as f:
            for ln in f:
                if "CONV_GATE" not in ln or "PULLBACK" not in ln or "score=" not in ln:
                    continue
                if day not in ln.replace("-", ""):
                    continue
                if "BLOCK" in ln:   # 통과만 (차단 제외)
                    continue
                ms = re.search(r"score=([\d.]+)", ln)
                mc = re.search(r"code=(\d+)", ln)
                if ms and mc:
                    score[mc.group(1).zfill(6)] = float(ms.group(1))
    out = []
    for c, t in buys.items():
        out.append({"date": day, "code": c, "time": t,
                    "score": score.get(c, ""), "entry_price": entry.get(c, ""),
                    "day_close": "", "day_high": "", "close_ret_pct": "",
                    "high_ret_pct": "", "win": "", "filled": "0"})
    return out


def load_eod():
    """code -> {date: (close, high)}"""
    bars = {}
    if not EOD.exists():
        return bars
    with EOD.open(encoding="utf-8-sig", errors="replace") as f:
        for r in csv.DictReader(f):
            c = (r.get("code", "") or "").strip().zfill(6)
            d = (r.get("date", "") or "").strip()
            try:
                bars.setdefault(c, {})[d] = (float(r.get("close") or 0), float(r.get("high") or 0))
            except (TypeError, ValueError):
                pass
    return bars


def backfill_outcomes(rows, bars):
    n = 0
    for r in rows:
        if str(r.get("filled")) == "1":
            continue
        try:
            ep = float(r.get("entry_price") or 0)
        except (TypeError, ValueError):
            ep = 0
        if ep <= 0:
            continue
        c = r["code"]; d = r["date"]
        if c in bars and d in bars[c]:
            cl, hi = bars[c][d]
            if cl > 0:
                r["day_close"] = cl; r["day_high"] = hi
                r["close_ret_pct"] = round((cl / ep - 1) * 100, 2)
                r["high_ret_pct"] = round((hi / ep - 1) * 100, 2) if hi > 0 else ""
                r["win"] = "1" if cl > ep else "0"
                r["filled"] = "1"
                n += 1
    return n


def analyze(rows):
    done = [r for r in rows if str(r.get("filled")) == "1" and r.get("score") not in ("", None)]
    print("\n=== 점수 구간별 성과 (수익 확정 %d건) ===" % len(done))
    if not done:
        print("  아직 수익 확정된 건 없음(eod 데이터 대기).")
        return
    buckets = {"65-75": [], "75-85": [], "85+": []}
    for r in done:
        try:
            s = float(r["score"]); cr = float(r["close_ret_pct"])
        except (TypeError, ValueError):
            continue
        b = "65-75" if s < 75 else "75-85" if s < 85 else "85+"
        buckets[b].append((cr, r.get("win") == "1"))
    print("  %-8s %5s %8s %12s" % ("구간", "건수", "승률%", "평균수익%"))
    for b in ["65-75", "75-85", "85+"]:
        v = buckets[b]
        if not v:
            print("  %-8s %5d        -" % (b, 0)); continue
        win = sum(1 for _, w in v if w) / len(v) * 100
        avg = sum(x for x, _ in v) / len(v)
        print("  %-8s %5d %8.1f %12.2f" % (b, len(v), win, avg))


def status(rows):
    total = len(rows)
    filled = len([r for r in rows if str(r.get("filled")) == "1"])
    print("\n=== 추세눌림 점수로거 상태 ===")
    print("  누적 매수기록: %d건  |  수익확정: %d건  |  목표: %d건" % (total, filled, TARGET))
    # 누적 속도로 예상 준비일 추정 (거래일 기준)
    days = sorted(set(r["date"] for r in rows))
    if total >= TARGET and filled >= TARGET:
        print("  ★ 분석 준비 완료! (목표 도달) → 아래 구간분석 신뢰도 상승")
    elif len(days) >= 1:
        rate = total / max(1, len(days))   # 거래일당 매수건수
        remain = max(0, TARGET - total)
        if rate > 0:
            need_days = remain / rate
            print("  진행: 거래일당 평균 %.1f건 → 목표까지 약 %.0f 거래일 더 필요" % (rate, need_days))
            print("  (현재 속도 유지 시. 매수가 늘면 빨라지고, 줄면 늦어짐 — 자동 갱신됨)")
        if remain > 0:
            print("  남은 %d건 모이면 자동으로 '준비 완료' 표시됩니다." % remain)
    else:
        print("  아직 기록 없음 — 추세눌림 매수가 나오면 자동 누적 시작.")


def main():
    rows = load_log()
    seen = set((r["date"], r["code"]) for r in rows)
    # 오늘(+인자로 날짜 지정 가능) 신규 PULLBACK 매수 추가
    days = [a for a in sys.argv[1:] if re.match(r"^\d{8}$", a)] or [datetime.now().strftime("%Y%m%d")]
    added = 0
    for day in days:
        for rec in parse_today_pullback(day):
            if (rec["date"], rec["code"]) not in seen:
                rows.append(rec); seen.add((rec["date"], rec["code"])); added += 1
    # 수익 backfill
    bars = load_eod()
    filled = backfill_outcomes(rows, bars)
    save_log(rows)
    print("[PB-LOG] 신규 %d건 추가 / 수익 backfill %d건 / 총 %d건" % (added, filled, len(rows)))
    status(rows)
    analyze(rows)


if __name__ == "__main__":
    main()
