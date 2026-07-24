# -*- coding: utf-8 -*-
"""🚀📡 갑툭이 초입 그림자 수집기 — 주문0·TR0  [2026-07-20 친구님 "그림자 만들고 거기다가 지금 배선해"]

목적: "60분 횡보 중 돈이 몰리며 처음 튀는 순간(초입) 진입 + -2% 하드손절" 전략의 실전 표본 수집.
  근거(2026-07-20 오전, 1분봉 아카이브 26일):
  · 갑툭이 추격(스파이크 완성 후)은 2시간 시야 드리프트 0·-1.5% 눌림 터치 69.5% → 추격 기각
  · 눌림은 스파이크 후 중앙 12분에 오고 중앙 깊이 -1.53% → 초입 진입이면 -2% 손절이 눌림을 품음
  · 얕게 눌린 놈일수록 재돌파율 100%→50%로 층이 갈림(눌림 깊이=진위 판별기)

방식 (매일 09:00~15:19 · 1초 폴링 · live_micro_snapshot 읽기전용 · 주문/TR 없음):
  · 유니버스 = 스냅샷에 흐르는 전 종목 중 가격 3,000원↑ (신규 등장 종목 자동 편입)
  · 폴링 틱 → 완성 1분봉 조립(시고저종 + Δ거래량 + Δ대금근사=Δ거래량×체결가)
  · 신호 = 직전 60분(완성봉 45개↑) 밴드폭 ≤3% AND 완성봉이 60분 고점을 "처음" 돌파
           AND 그 봉 +0.5%↑ AND 그 봉 대금 ≥ 5×(60분 평균 분당대금) AND ≥0.5억
  · 진입가 = 신호 확정 직후 첫 새 틱 체결가(다음 봉 시가 근사) — 같은 종목 30분 중복 제거
  · 추적(가상·기록만): -2% 손절터치초 / +2%·+3% 익절터치초 / 30·60·120분 시점 수익 /
           최대반등·최대밀림 / 120분(또는 장끝) 종료수익
산출: data\shadow\gaptuki_onset_signals.csv (누적 채점행)
스위치: GS_START=0900 GS_END=1519 GS_POLL=1.0 GS_BAND_MAX=3.0 GS_ONSET_RET=0.5 GS_VOLX=5.0
        GS_MINVAL=50000000 GS_STOP=-2.0 GS_PXMIN=3000 GS_DEDUP_MIN=30 GS_RUN_SEC=0(무제한)
        리허설 주입구: GS_SNAP / GS_OUTDIR
"""
import os, sys, csv, json, time
from pathlib import Path
from datetime import datetime
from collections import deque

SNAP    = Path(os.environ.get("GS_SNAP") or r"C:\stock_bot\IPC\live_micro_snapshot.json")
OUTDIR  = Path(os.environ.get("GS_OUTDIR") or r"C:\stock_bot\data\shadow")
LOG     = Path(r"C:\stock_bot\data\LOG\gaptuki_onset_shadow.log")
START   = os.environ.get("GS_START", "0900")
END     = os.environ.get("GS_END", "1519")
POLL    = float(os.environ.get("GS_POLL", "1.0"))
BAND_MAX  = float(os.environ.get("GS_BAND_MAX", "3.0"))     # 60분 밴드폭 상한(%)
ONSET_RET = float(os.environ.get("GS_ONSET_RET", "0.5"))    # 돌파봉 최소 상승률(%)
VOLX      = float(os.environ.get("GS_VOLX", "5.0"))         # 분당대금 배수 하한
MINVAL    = float(os.environ.get("GS_MINVAL", "50000000"))  # 돌파봉 최소 대금(원)
STOP      = float(os.environ.get("GS_STOP", "-2.0"))        # 가상 하드손절(%)
TP1       = float(os.environ.get("GS_TP1", "2.0"))
TP2       = float(os.environ.get("GS_TP2", "3.0"))
PXMIN     = float(os.environ.get("GS_PXMIN", "3000"))
DEDUP_MIN = int(os.environ.get("GS_DEDUP_MIN", "30"))
COVER_MIN = int(os.environ.get("GS_COVER_MIN", "45"))       # 60분 창 최소 완성봉 수
RUN_SEC   = float(os.environ.get("GS_RUN_SEC", "0"))        # 0=무제한(END까지)
TRACK_SEC = 120 * 60                                        # 신호 후 추적 시간(2시간)

COLS = ["일자", "종목코드", "신호시각", "돌파가", "진입가", "밴드폭", "분당대금배수", "돌파봉상승",
        "손절터치초", "익절2터치초", "익절3터치초", "r30", "r60", "r120",
        "최대반등", "최대밀림", "종료수익", "종료사유"]


def _log(m):
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8") as f:
            f.write(f"[{datetime.now():%H:%M:%S}] {m}\n")
    except Exception:
        pass
    print(m, flush=True)


class Sig:
    """확정된 갑툭이 신호 1건의 가상 추적(기록만·주문 없음)."""

    def __init__(self, code, hm, brk_px, bandw, volx, onset_ret, t):
        self.code, self.hm = code, hm
        self.brk = brk_px
        self.bandw, self.volx, self.onset = bandw, volx, onset_ret
        self.t0 = t
        self.entry = None          # 신호 후 첫 새 틱에서 확정
        self.stop_s = self.tp1_s = self.tp2_s = None
        self.r30 = self.r60 = self.r120 = None
        self.hi = self.lo = None
        self.done = False
        self.why = ""
        self.last_px = brk_px

    def tick(self, t, px):
        if self.done or px <= 0:
            return
        if self.entry is None:
            self.entry = px                       # 다음 틱 = 진입가 근사
            self.hi = self.lo = px
            self.te = t
            return
        self.last_px = px
        self.hi, self.lo = max(self.hi, px), min(self.lo, px)
        el = t - self.te
        r = (px / self.entry - 1) * 100
        if self.stop_s is None and r <= STOP:
            self.stop_s = round(el)
        if self.tp1_s is None and r >= TP1:
            self.tp1_s = round(el)
        if self.tp2_s is None and r >= TP2:
            self.tp2_s = round(el)
        if self.r30 is None and el >= 1800:
            self.r30 = round(r, 2)
        if self.r60 is None and el >= 3600:
            self.r60 = round(r, 2)
        if self.r120 is None and el >= 7200:
            self.r120 = round(r, 2)
            self.finish("120분")

    def finish(self, why):
        if self.done:
            return
        self.done = True
        self.why = why

    def row(self, today):
        e = self.entry or 0
        fin = (self.last_px / e - 1) * 100 if e else ""
        return {"일자": today, "종목코드": self.code, "신호시각": self.hm,
                "돌파가": self.brk, "진입가": e or "",
                "밴드폭": round(self.bandw, 2), "분당대금배수": round(self.volx, 1),
                "돌파봉상승": round(self.onset, 2),
                "손절터치초": self.stop_s if self.stop_s is not None else "",
                "익절2터치초": self.tp1_s if self.tp1_s is not None else "",
                "익절3터치초": self.tp2_s if self.tp2_s is not None else "",
                "r30": self.r30 if self.r30 is not None else "",
                "r60": self.r60 if self.r60 is not None else "",
                "r120": self.r120 if self.r120 is not None else "",
                "최대반등": round((self.hi / e - 1) * 100, 2) if e else "",
                "최대밀림": round((self.lo / e - 1) * 100, 2) if e else "",
                "종료수익": round(fin, 2) if fin != "" else "",
                "종료사유": self.why or "장끝"}


class Book:
    """종목 하나 — 틱 → 완성 1분봉 조립 + 60분 창 신호 판정."""

    def __init__(self, code):
        self.code = code
        self.bars = deque(maxlen=70)   # (분번호, o, h, l, c, val)
        self.cur_min = None
        self.o = self.h = self.l = self.c = 0.0
        self.val = 0.0
        self.last_v = None
        self.last_sig_min = -9999

    def tick(self, minute_no, px, cum_vol):
        dv = 0.0
        if self.last_v is not None and cum_vol is not None:
            dv = max(0.0, cum_vol - self.last_v)
        if cum_vol is not None:
            self.last_v = cum_vol
        if self.cur_min is None or minute_no != self.cur_min:
            done = None
            if self.cur_min is not None:
                done = (self.cur_min, self.o, self.h, self.l, self.c, self.val)
                self.bars.append(done)
            self.cur_min = minute_no
            self.o = self.h = self.l = self.c = px
            self.val = dv * px
            return done
        self.h, self.l, self.c = max(self.h, px), min(self.l, px), px
        self.val += dv * px
        return None

    def check(self, bar):
        """완성봉 bar 에서 갑툭이 초입 판정. 신호면 (돌파가, 밴드폭, 배수, 상승률) 반환."""
        m, o, h, l, c, val = bar
        win = [b for b in self.bars if m - 60 <= b[0] < m]   # 직전 60분(이 봉 제외)
        if len(win) < COVER_MIN:
            return None
        H60 = max(b[2] for b in win)
        L60 = min(b[3] for b in win)
        if L60 <= 0:
            return None
        bandw = (H60 - L60) / L60 * 100
        if bandw > BAND_MAX:
            return None
        prev = win[-1]
        if not (c > H60 and prev[2] <= H60):                 # "처음" 돌파(직전봉은 고점 아래)
            return None
        onset = (c / prev[4] - 1) * 100 if prev[4] > 0 else 0
        if onset < ONSET_RET:
            return None
        vals = [b[5] for b in win if b[5] > 0]
        avg_v = sum(vals) / len(vals) if vals else 0
        if avg_v <= 0 or val < VOLX * avg_v or val < MINVAL:
            return None
        if m - self.last_sig_min < DEDUP_MIN:
            return None
        self.last_sig_min = m
        return (c, bandw, val / avg_v, onset)


def main():
    today = datetime.now().strftime("%Y%m%d")
    if datetime.now().strftime("%H%M") > END:
        _log("장 종료 후 기동 — 종료")
        return
    _log("=" * 60)
    _log(f"🚀📡 갑툭이 초입 그림자 — 주문0·TR0·{POLL:.1f}s 폴링 · 밴드≤{BAND_MAX}%·돌파봉+{ONSET_RET}%↑·대금{VOLX}배↑·가상손절{STOP}%")
    OUTDIR.mkdir(parents=True, exist_ok=True)
    books, sigs, closed = {}, [], []
    last_seen = {}
    t_start = time.time()
    n_sig = 0
    last_hb = time.time()

    while True:
        now = datetime.now()
        hm = now.strftime("%H%M")
        if hm >= END or (RUN_SEC and time.time() - t_start >= RUN_SEC):
            break
        if hm < START:
            time.sleep(1.0)
            continue
        try:
            snap = json.loads(SNAP.read_text(encoding="utf-8-sig")).get("codes", {})
        except Exception:
            time.sleep(POLL)
            continue
        t = time.time()
        for code, v in snap.items():
            ts = str(v.get("ts") or "")
            if len(ts) < 16 or ts[:10] != now.strftime("%Y-%m-%d"):
                continue
            px = float(v.get("cur") or 0)
            if px < PXMIN:
                continue
            key = (ts, v.get("cur"), v.get("cum_vol"))
            if last_seen.get(code) == key:
                continue
            last_seen[code] = key
            cv = v.get("cum_vol")
            cv = float(cv) if cv is not None else None
            hh, mm = int(ts[11:13]), int(ts[14:16])
            if not ("09" <= ts[11:13] <= "15"):
                continue
            minute_no = hh * 60 + mm
            bk = books.get(code)
            if bk is None:
                bk = books[code] = Book(code)
            done_bar = bk.tick(minute_no, px, cv)
            if done_bar is not None:
                hit = bk.check(done_bar)
                if hit:
                    brk, bandw, vx, onset = hit
                    s = Sig(code, f"{done_bar[0]//60:02d}{done_bar[0]%60:02d}", brk, bandw, vx, onset, t)
                    sigs.append(s)
                    n_sig += 1
                    _log(f"🚀신호 {code} {s.hm} 돌파가{brk:,.0f} 밴드{bandw:.2f}% 대금{vx:.0f}배 봉+{onset:.2f}%")
            for s in sigs:
                if s.code == code:
                    s.tick(t, px)
        for s in [x for x in sigs if x.done]:
            closed.append(s)
            sigs.remove(s)
        if time.time() - last_hb >= 1800:
            _log(f"💓 감시 {len(books)}종목 · 신호 {n_sig}건 · 추적중 {len(sigs)}")
            last_hb = time.time()
        time.sleep(POLL)

    for s in sigs:
        s.finish("장끝")
        closed.append(s)
    fp = OUTDIR / "gaptuki_onset_signals.csv"
    new = not fp.exists()
    with fp.open("a", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLS, extrasaction="ignore", restval="")
        if new:
            w.writeheader()
        for s in closed:
            w.writerow(s.row(today))
    _log(f"종료 — 감시 {len(books)}종목 · 신호 {n_sig}건 → {fp}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
    except Exception as e:
        _log(f"🚨 치명 오류: {e}")
        sys.exit(1)
