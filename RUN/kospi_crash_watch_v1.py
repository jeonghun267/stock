# -*- coding: utf-8 -*-
"""🔭 코스피 급락 관찰층 — 기록만·주문 0  [2026-07-16 신설 · 친구님 "해봐"]

배경: 코스피 500억~2조 밴드는 112종목·급락(-4%) 후보 평균 62개/일 = 코스닥의 3.6배.
  EOD 기준 저점→종가 반등은 코스닥과 사실상 동일(+4.25% vs +4.34%·≥2% 회복 66%=66%).
  그러나 분봉·체결강도 수집이 코스닥 선별종목뿐이라 "아침 V자인지"를 검증할 데이터가 없었다.
  → 이 관찰기가 매일 장후에 코스피 급락주의 1분봉을 백필하고 아침 프레임 성적을 채점·누적한다.

동작(장후 16:25 · 오늘 실전과 무관):
  1) 가드: 평일 · 16:20 이후(KW_FORCE=YES면 무시) · 락 · trades.csv에 오늘자 있으면 멱등 종료
  2) 유니버스 = eod_daily_bars 최신일 코스피 · 전일대금 500억~2조 · 전일종가 1만원↑ · 당일저가 -4%↓
  3) 종목당 opt10080 1페이지(당일 1분봉) — 페이스 KW_PACE(0.35s) · 화면 3100~3119 · 상한 KW_MAX(120)
  4) 아카이브 data/shadow/kospi_crash/prices_1m_kospi_YYYYMMDD.csv (멱등)
  5) 채점 trades.csv 누적: 급락 첫 도달 시각 · A안=아침 프레임(진입 09:00~09:18 저점+0.5% 반등→09:20 청산)
     · B안=자유 진입(~14:20)→+60분 · 저점→종가 반등  ※체결강도는 실시간 전용이라 없음(가격턴만)
TR 예산: ≤120건×1페이지 ≈ 1분 미만(장후라 프리징 무관) · 끄기 = 태스크 Disabled / KW_DRY=YES(TR 0)
"""
import os
import sys
import csv
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

sys.path.insert(0, r"C:\stock_bot\RUN")

EOD_PATH = Path(r"C:\stock_bot\data\eod_daily_bars.csv")
OUT_DIR  = Path(r"C:\stock_bot\data\shadow\kospi_crash")
TRADES   = OUT_DIR / "trades.csv"
LOG_PATH = Path(r"C:\stock_bot\data\LOG\kospi_crash_watch.log")
LOCK     = OUT_DIR / "run.lock"

VAL_LO  = float(os.environ.get("KW_VAL_LO", "500"))     # 억
VAL_HI  = float(os.environ.get("KW_VAL_HI", "20000"))
PX_FLR  = float(os.environ.get("KW_PX_FLOOR", "10000"))
DROP    = float(os.environ.get("KW_DROP", "-4"))
PACE    = float(os.environ.get("KW_PACE", "0.35"))
KW_MAX  = int(os.environ.get("KW_MAX", "120"))
DRY     = os.environ.get("KW_DRY", "NO").strip().upper() == "YES"
FORCE   = os.environ.get("KW_FORCE", "NO").strip().upper() == "YES"

TR_FIELDS = ["체결시간", "시가", "고가", "저가", "현재가", "거래량", "거래대금"]
COLS = ["일자", "종목코드", "종목명", "전일종가", "전일대금억", "깊이퍼센트", "급락첫도달", "저점시각",
        "아침진입시각", "아침0920수익", "자유진입시각", "자유60분수익", "저점종가반등", "봉수"]


def log(m):
    line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {m}"
    print(line, flush=True)
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def _f(v):
    try:
        return abs(float(str(v).replace(",", "").strip() or 0))
    except Exception:
        return 0.0


def main():
    now = datetime.now()
    if now.weekday() >= 5 and not FORCE:
        log("주말 — 종료"); return
    if now.strftime("%H%M") < "1620" and not FORCE:
        log("16:20 이전 — 장중 실행 금지 가드, 종료"); return
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    if LOCK.exists() and (time.time() - LOCK.stat().st_mtime) < 3600:
        log("락 존재 — 종료"); return
    LOCK.write_text(str(os.getpid()), encoding="utf-8")
    try:
        # ── EOD에서 최신일(=오늘)·전일 로드 ──
        by_date = defaultdict(dict)
        with EOD_PATH.open(encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                d = r.get("date", "")
                if d < "20260701" or r.get("market") != "KOSPI":
                    continue
                try:
                    by_date[d][r["code"].zfill(6)] = (
                        _f(r.get("close")), _f(r.get("value")) / 100, _f(r.get("low")),
                        (r.get("name") or "")[:10])
                except Exception:
                    pass
        days = sorted(by_date)
        if len(days) < 2:
            log("코스피 EOD 부족 — 종료"); return
        today, prev = days[-1], days[-2]

        if TRADES.exists():
            with TRADES.open(encoding="utf-8-sig") as f:
                if any(row.get("일자") == today for row in csv.DictReader(f)):
                    log(f"{today} 이미 채점됨 — 멱등 종료"); return

        # ETF/ETN/ELW 상품 제외 — 코드에 영문자(0193L0 등) 또는 상품 브랜드명. 관찰 대상은 실제 기업만.
        ETF_KW = ("KODEX", "TIGER", "PLUS ", "ACE ", "SOL ", "KBSTAR", "HANARO", "ARIRANG",
                  "KOSEF", "KIWOOM", "레버리지", "인버스", "선물", "ETN", "액티브", "채권")
        crashers = []
        for code, (c, v, lo, nm) in by_date[today].items():
            p = by_date[prev].get(code)
            if not p:
                continue
            if not code.isdigit() or any(k in (nm or p[3] or "").upper() for k in ETF_KW):
                continue
            pc, pval = p[0], p[1]
            if pc < PX_FLR or not (VAL_LO <= pval <= VAL_HI) or lo <= 0 or pc <= 0:
                continue
            if abs(lo / pc - 1) > 0.4:
                continue
            depth = (lo / pc - 1) * 100
            if depth <= DROP:
                crashers.append((code, nm or by_date[prev][code][3], pc, pval, depth))
        crashers.sort(key=lambda x: x[4])
        crashers = crashers[:KW_MAX]
        log(f"{today} 코스피 급락 후보 {len(crashers)}종목 (밴드 {VAL_LO:.0f}~{VAL_HI:.0f}억·{PX_FLR:.0f}원↑)")
        if not crashers:
            return
        if DRY:
            log(f"[DRY] TR 없이 종료. 예시: {[(c, n, round(d,1)) for c, n, _, _, d in crashers[:8]]}")
            return

        from broker_client import BrokerClient
        bc = BrokerClient()
        if not bc.alive():
            log("브로커 죽음 — 수집 불가, 종료"); return

        arch = OUT_DIR / f"prices_1m_kospi_{today}.csv"
        new_arch = not arch.exists()
        results = []
        with arch.open("a", encoding="utf-8-sig", newline="") as af:
            aw = csv.writer(af)
            if new_arch:
                aw.writerow(["code", "ts", "open", "high", "low", "close", "volume", "value"])
            for i, (code, nm, pc, pval, depth) in enumerate(crashers):
                scr = str(3100 + (i % 20))
                r = bc.tr("opt10080", inputs={"종목코드": code, "틱범위": "1", "수정주가구분": "0"},
                          output_fields=TR_FIELDS, screen_no=scr, timeout_sec=10.0)
                time.sleep(PACE)
                if str((r or {}).get("status", "")).upper() != "OK":
                    log(f"  TR 실패 {nm}({code}) — 건너뜀")
                    continue
                bars = []
                for rec in ((r.get("data") or {}).get("records")) or []:
                    ts = (rec.get("체결시간") or "").strip()
                    if not (ts and ts.isdigit() and ts.startswith(today)):
                        continue
                    o, h, l, c = _f(rec.get("시가")), _f(rec.get("고가")), _f(rec.get("저가")), _f(rec.get("현재가"))
                    if c <= 0 or o <= 0 or h < l or abs(c / pc - 1) > 0.4:
                        continue
                    hm = ts[8:12]
                    if not ("0900" <= hm <= "1520"):
                        continue
                    bars.append((hm, o, h, l, c))
                    aw.writerow([code, ts, o, h, l, c, _f(rec.get("거래량")), _f(rec.get("거래대금"))])
                if len(bars) < 30:
                    continue
                bars.sort()
                # 채점 — 급락 첫 도달·저점·아침 프레임(09:20 청산)·자유 진입(+60분)
                t_first = next((hm for hm, o, h, l, c in bars if (l / pc - 1) * 100 <= DROP), "")
                lo_all = min(b[3] for b in bars)
                t_low = next(b[0] for b in bars if b[3] == lo_all)
                reb_close = (bars[-1][4] / lo_all - 1) * 100
                lowrun = None; ent_a = ehm_a = ent_b = ehm_b = None; r0920 = r60 = ""
                for idx, (hm, o, h, l, c) in enumerate(bars):
                    lowrun = l if lowrun is None else min(lowrun, l)
                    armed = (lowrun / pc - 1) * 100 <= DROP
                    if armed and c >= lowrun * 1.005:
                        if ent_a is None and "0900" <= hm <= "0918":
                            ent_a, ehm_a = c, hm
                        if ent_b is None and hm <= "1420":
                            ent_b, ehm_b, eidx_b = c, hm, idx
                    if ent_a is not None and ent_b is not None:
                        break
                if ent_a:
                    px0920 = next((c for hm, o, h, l, c in bars if hm >= "0920"), bars[-1][4])
                    r0920 = round((px0920 / ent_a - 1) * 100, 2)
                if ent_b:
                    em = int(ehm_b[:2]) * 60 + int(ehm_b[2:])
                    px60 = next((c for hm, o, h, l, c in bars
                                 if int(hm[:2]) * 60 + int(hm[2:]) >= em + 60), bars[-1][4])
                    r60 = round((px60 / ent_b - 1) * 100, 2)
                results.append({"일자": today, "종목코드": code, "종목명": nm, "전일종가": round(pc),
                                "전일대금억": round(pval), "깊이퍼센트": round(depth, 2),
                                "급락첫도달": t_first, "저점시각": t_low,
                                "아침진입시각": ehm_a or "", "아침0920수익": r0920,
                                "자유진입시각": ehm_b or "", "자유60분수익": r60,
                                "저점종가반등": round(reb_close, 2), "봉수": len(bars)})

        if results:
            new_tr = not TRADES.exists()
            with TRADES.open("a", encoding="utf-8-sig", newline="") as f:
                w = csv.DictWriter(f, fieldnames=COLS, extrasaction="ignore", restval="")
                if new_tr:
                    w.writeheader()
                w.writerows(results)
        am = [r for r in results if r["아침0920수익"] != ""]
        log(f"채점 {len(results)}종목 저장 (아침 프레임 진입 {len(am)}건"
            + (f" · 평균 {sum(float(r['아침0920수익']) for r in am)/len(am):+.2f}%" if am else "") + ")")
    except Exception as e:
        import traceback
        log(f"오류: {e}\n{traceback.format_exc()}")
    finally:
        try:
            LOCK.unlink()
        except Exception:
            pass


if __name__ == "__main__":
    main()
