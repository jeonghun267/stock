# -*- coding: utf-8 -*-
"""🕳📡 저점 체결강도 그림자 수집기 — 주문0·TR0  [2026-07-16 친구님 "그림자 수집 배선해·저점 체결강도로"]

목적: 급락주 진입 게이트를 [당일 누적 체결강도 105] → [저점 이후 구간 매수/매도 우위]로 바꾸기 전 표본 수집.
  7/15~16 틱룰 검증(30개): 저점+150초 시점 매도우위(<100)는 4/4 전멸(붕괴100%·+2.5%반등 0%),
  매수우위는 필요조건(돈 된 반등 전부 매수우위)이지만 충분조건 아님(58% 붕괴) → 표본 더 쌓아 확정.

방식 (매일 09:00~09:32 · 1초 폴링 · live_micro_snapshot 읽기전용):
  · 유니버스 = 돈맥_전일상위풀에서 전일종가 1만↑·전일대금 700억~2조 (급락주 엔진과 동일)
  · 틱룰 근사: 폴링 간 누적거래량 증가분을 가격 방향(↑=매수/↓=매도/보합=직전방향)으로 분류
  · ★저점 앵커: 신저점 갱신 시 매수/매도 카운터 리셋. 저점+150초 생존 시점에
    [저점 체결강도(구간)] vs [현행 누적 체결강도(che_str)] 동시 동결 기록 → A/B 비교 재료
  · 저점 붕괴 or 09:32 종료 시 채점행 저장: 생존초·이후 최대반등·붕괴여부
산출: data\shadow\lowflow_verdicts.csv (누적) · data\shadow\lowflow_raw_YYYYMMDD.csv (1초 원본)
스위치: LF_START=0900 LF_END=0932 LF_POLL=1.0 (리허설용 LF_SNAP/LF_POOL/LF_OUTDIR 주입구)
"""
import os, sys, csv, json, time
from pathlib import Path
from datetime import datetime

SNAP   = Path(os.environ.get("LF_SNAP") or r"C:\stock_bot\IPC\live_micro_snapshot.json")
POOL   = Path(os.environ.get("LF_POOL") or r"C:\stock_bot\data\돈맥_전일상위풀.json")
OUTDIR = Path(os.environ.get("LF_OUTDIR") or r"C:\stock_bot\data\shadow")
LOG    = Path(r"C:\stock_bot\data\LOG\crash_lowflow_shadow.log")
START  = os.environ.get("LF_START", "0900")
END    = os.environ.get("LF_END", "0932")
POLL   = float(os.environ.get("LF_POLL", "1.0"))
PXMIN, PVAL_LO, PVAL_HI = 10000.0, 700.0, 20000.0
FREEZE_S = float(os.environ.get("LF_FREEZE", "150"))   # 저점 후 판정 동결 시점(초·리허설용 주입구)

REB_TH = float(os.environ.get("LF_REB_TH", "2.4"))     # ★친구님 "+2.4% 반등 도달 시점" 판정(%)

VCOLS = ["일자", "종목코드", "저점가", "저점시각", "생존초", "저점체결강도150", "누적체결강도150",
         "반등24체결강도", "반등24도달초",
         "이후최대반등퍼센트", "150초내붕괴", "최종붕괴", "판정가능"]


def _log(m):
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8") as f:
            f.write(f"[{datetime.now():%H:%M:%S}] {m}\n")
    except Exception:
        pass
    print(m, flush=True)


class LowFlow:
    """종목 하나의 저점 앵커 수급 집계기."""

    def __init__(self, code):
        self.code = code
        self.last_p = None
        self.last_v = None
        self.last_che = None
        self.last_dir = 0
        self.low = None
        self.low_t = None
        self.buy = 0.0
        self.sell = 0.0
        self.k150 = None          # 저점+150초 동결 저점체결강도
        self.cum150 = None        # 동시점 누적 체결강도(현행)
        self.k24 = None           # ★저점 대비 +REB_TH% 반등 도달 시점의 저점체결강도
        self.t24 = None           # 그 도달까지 걸린 초
        self.peak_after = None
        self.rows = []

    def _close_seg(self, t, broke):
        if self.low is None:
            return
        surv = round(t - self.low_t, 1)
        reb = (self.peak_after / self.low - 1) * 100 if self.peak_after else 0.0
        self.rows.append({
            "종목코드": self.code, "저점가": self.low,
            "저점시각": datetime.fromtimestamp(self.low_t).strftime("%H:%M:%S"),
            "생존초": surv,
            "저점체결강도150": round(self.k150, 1) if self.k150 is not None else "",
            "누적체결강도150": (round(self.cum150, 1) if isinstance(self.cum150, (int, float)) else "") ,
            "반등24체결강도": round(self.k24, 1) if self.k24 is not None else "",
            "반등24도달초": round(self.t24, 1) if self.t24 is not None else "",
            "이후최대반등퍼센트": round(reb, 2),
            "150초내붕괴": 1 if (broke and surv < FREEZE_S) else 0,
            "최종붕괴": 1 if broke else 0,
            "판정가능": 1 if self.k150 is not None else 0,
        })

    def freeze_check(self, t):
        """★매 폴링마다 호출 — 저점+FREEZE_S초 생존 시점의 저점체결강도/누적체결강도 동결.
           (데이터 변경이 없어도 시간은 흐르므로 update()가 아니라 여기서 판정)"""
        if self.low is not None and self.k150 is None and (t - self.low_t) >= FREEZE_S:
            self.k150 = (self.buy / self.sell * 100.0) if self.sell > 0 else 999.0
            self.cum150 = self.last_che if self.last_che else ""

    def update(self, t, p, cum_vol, che_cum):
        if p <= 0:
            return
        self.last_che = che_cum
        if self.last_p is not None and cum_vol is not None and self.last_v is not None:
            dv = max(0.0, cum_vol - self.last_v)
            d = self.last_dir
            if p > self.last_p:
                d = 1
            elif p < self.last_p:
                d = -1
            if d > 0:
                self.buy += dv
            elif d < 0:
                self.sell += dv
            self.last_dir = d
        self.last_p, self.last_v = p, (cum_vol if cum_vol is not None else self.last_v)

        if self.low is None:
            self.low, self.low_t = p, t
            self.buy = self.sell = 0.0
            self.k150 = self.cum150 = self.k24 = self.t24 = None
            self.peak_after = None
            return
        if p < self.low:                      # 신저점 → 직전 저점 채점·카운터 리셋
            self._close_seg(t, broke=True)
            self.low, self.low_t = p, t
            self.buy = self.sell = 0.0
            self.k150 = self.cum150 = self.k24 = self.t24 = None
            self.peak_after = None
            return
        self.peak_after = p if self.peak_after is None else max(self.peak_after, p)
        # ★[친구님] 저점 대비 +REB_TH% 반등 도달 순간의 저점 체결강도 동결(매도우위면 안 사는 규칙 검증용)
        if self.k24 is None and p >= self.low * (1 + REB_TH / 100.0):
            self.k24 = (self.buy / self.sell * 100.0) if self.sell > 0 else 999.0
            self.t24 = t - self.low_t

    def finish(self, t):
        self._close_seg(t, broke=False)


def universe():
    try:
        d = json.loads(POOL.read_text(encoding="utf-8-sig"))
        if d.get("date") != datetime.now().strftime("%Y%m%d"):
            return []
        return [r[0] for r in d.get("rows", [])
                if len(r) >= 3 and float(r[1]) >= PXMIN and PVAL_LO <= float(r[2]) <= PVAL_HI]
    except Exception:
        return []


def main():
    hm = datetime.now().strftime("%H%M")
    if hm > END:
        return
    uni = universe()
    if not uni:
        _log("전일풀 없음/오늘자 아님 — 종료")
        return
    _log("=" * 60)
    _log(f"📡 저점 체결강도 그림자 — 유니버스 {len(uni)}종목 (주문0·TR0·{POLL:.1f}s 폴링)")
    flows = {c: LowFlow(c) for c in uni}
    today = datetime.now().strftime("%Y%m%d")
    OUTDIR.mkdir(parents=True, exist_ok=True)
    raw_fp = OUTDIR / f"lowflow_raw_{today}.csv"
    raw_new = not raw_fp.exists()
    raw = raw_fp.open("a", encoding="utf-8-sig", newline="")
    rw = csv.writer(raw)
    if raw_new:
        rw.writerow(["시각", "종목코드", "현재가", "누적거래량", "누적체결강도"])

    last_seen = {}
    n_samples = 0
    while True:
        now = datetime.now()
        if now.strftime("%H%M") >= END:
            break
        if now.strftime("%H%M") < START:
            time.sleep(1.0)
            continue
        try:
            snap = json.loads(SNAP.read_text(encoding="utf-8-sig")).get("codes", {})
        except Exception:
            time.sleep(POLL)
            continue
        t = time.time()
        for c in uni:
            v = snap.get(c) or {}
            ts = str(v.get("ts") or "")
            if not ts or ts[:10] != now.strftime("%Y-%m-%d"):
                continue
            key = (ts, v.get("cur"), v.get("cum_vol"))
            if last_seen.get(c) == key:
                continue
            last_seen[c] = key
            cur = float(v.get("cur") or 0)
            cv = v.get("cum_vol")
            cv = float(cv) if cv is not None else None
            che = float(v.get("che_str") or 0)
            flows[c].update(t, cur, cv, che)
            rw.writerow([now.strftime("%H:%M:%S"), c, cur, cv if cv is not None else "", che])
            n_samples += 1
        for c in uni:                      # ★변경 없어도 시간 경과 판정(150초 동결)은 매 폴링 수행
            flows[c].freeze_check(t)
        time.sleep(POLL)

    tend = time.time()
    for c in uni:
        flows[c].finish(tend)
    raw.close()

    vfp = OUTDIR / "lowflow_verdicts.csv"
    vnew = not vfp.exists()
    n_rows = 0
    with vfp.open("a", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=VCOLS, extrasaction="ignore", restval="")
        if vnew:
            w.writeheader()
        for c in uni:
            for r in flows[c].rows:
                r["일자"] = today
                w.writerow(r)
                n_rows += 1
    judged = sum(1 for c in uni for r in flows[c].rows if r["판정가능"])
    _log(f"종료 — 샘플 {n_samples}개 · 저점 채점행 {n_rows}개(판정가능 {judged}) → {vfp}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
    except Exception as e:
        _log(f"🚨 치명 오류: {e}")
        sys.exit(1)
