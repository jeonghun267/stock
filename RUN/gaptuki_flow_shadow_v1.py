# -*- coding: utf-8 -*-
"""🚀💰 횡보 후 갑툭이(자금유입) 독립 그림자 엔진 — 주문0·TR0
[2026-07-20 친구님 "통합 패치 지침서" — Shadow → 검증 → 실전 순서 유지]

지침서 요약(5단계 상태기계 — 가격이 아니라 "실시간 자금 유입의 지속성"으로 선별):
  1단계 횡보 감지  : 30~60분 박스권 + 변동폭 축소 + 거래량 감소 + 5/20일선 이격 축소
  2단계 갑툭이     : 대금 급증 ∧ 거래량 급증 ∧ 체결강도 급증 동시 (가격만/거래량만 급등 제외)
  3단계 자금 검증  : 체결강도 추세·거래량 유지·대금 증가속도 매분 채점 (급감=즉시 탈락)
  4단계 눌림 확인  : 저점 붕괴 금지 + 눌림 중에도 돈 유지 (깊이보다 돈)
  5단계 재출발     : 반등 확인 ∧ 거래량 재증가 ∧ 체결강도 재상승 → 매수 후보 확정 → FOLLOW 진입
  즉시 탈락       : 저점붕괴·체결강도 감소·대금 끊김·횡보 없는 급등 등 → rejects CSV에 사유 기록

용어(★2026-07-20 지침서2 — Shadow/Follow 구조 명확화):
  Shadow = 실주문 없이 신호 수집·가상 성과를 검증하는 **운영 모드**(이 파일 전체).
  FOLLOW = 후보 확정 이후 성과만 추적하는 **내부 상태(State)** — Shadow 자체가 아님. 혼용 금지.
  상태 전이: IDLE → SPIKE → PULLBACK → FOLLOW → DONE (구 TRACK을 FOLLOW로 개명 — 동작·조건 불변.
  FOLLOW에서는 새 매수조건 검사·후보 취소 없음, 추적만 수행.)

개발 원칙(지침서): 기존 엔진·함수·변수 일절 무수정. 독립 모듈. GF_ 접두어 전용(충돌 검사 완료).
데이터 한계(v1): 프로그램 순매수·호가 실시간 피드가 현재 배관에 없음(IPC 전수 확인 2026-07-20)
  → 지침서 ④⑤항은 0점 처리(아래 로그 1회 명시). 피드 신설 시 GF_USE_PROG/GF_USE_HOGA로 활성화 예정.
체결강도: 스냅샷 누적 che_str + 틱룰 분당 구간체결강도(폴링 간 Δ거래량을 가격방향으로 분류 —
  crash_lowflow_shadow_v1 검증 방식)를 병행. 급증/추세 판정은 구간체결강도 기준.

산출:
  data\shadow\gaptuki_flow_candidates.csv  매수 후보(점수·지표 + 가상 추적: -2%터치·r30/60/120·최대반등/밀림)
  data\shadow\gaptuki_flow_rejects.csv     단계별 탈락 사유(가짜 돌파 제거 검증용)
  data\LOG\gaptuki_flow_shadow.log         상태 전이 로그

스위치(전부 GF_ 전용): GF_START=0900 GF_END=1519 GF_POLL=1.0 GF_PXMIN=3000
  1단계: GF_BOX_MIN=45 GF_BAND_MAX=3.0 GF_DRY_RATIO=0.7 GF_MA_GAP=3.0 GF_COVER_MIN=34
  2단계: GF_VOLX=5.0 GF_MINVAL=50000000 GF_SPIKE_CHE=130 GF_SPIKE_RET_MIN=0.3
  3~5단계: GF_FLOW_CHE_BAD=100 GF_PB_DEEP=-2.5 GF_PB_CHE=90 GF_REB=0.4 GF_REB_CHE=110 GF_TIMEOUT=40
  리허설 주입구: GF_SNAP / GF_OUTDIR / GF_RUN_SEC
"""
import os, sys, csv, json, time
from pathlib import Path
from datetime import datetime
from collections import deque

SNAP   = Path(os.environ.get("GF_SNAP") or r"C:\stock_bot\IPC\live_micro_snapshot.json")
OUTDIR = Path(os.environ.get("GF_OUTDIR") or r"C:\stock_bot\data\shadow")
EODCSV = Path(r"C:\stock_bot\data\eod_daily_bars.csv")
LOG    = Path(r"C:\stock_bot\data\LOG\gaptuki_flow_shadow.log")

START  = os.environ.get("GF_START", "0900")
END    = os.environ.get("GF_END", "1519")
POLL   = float(os.environ.get("GF_POLL", "1.0"))
PXMIN  = float(os.environ.get("GF_PXMIN", "3000"))
BOX_MIN    = int(os.environ.get("GF_BOX_MIN", "45"))
BAND_MAX   = float(os.environ.get("GF_BAND_MAX", "3.0"))
DRY_RATIO  = float(os.environ.get("GF_DRY_RATIO", "0.7"))
MA_GAP     = float(os.environ.get("GF_MA_GAP", "3.0"))
COVER_MIN  = int(os.environ.get("GF_COVER_MIN", "34"))
VOLX       = float(os.environ.get("GF_VOLX", "5.0"))
MINVAL     = float(os.environ.get("GF_MINVAL", "50000000"))
SPIKE_CHE  = float(os.environ.get("GF_SPIKE_CHE", "130"))
SPIKE_RET  = float(os.environ.get("GF_SPIKE_RET_MIN", "0.3"))
CHE_BAD    = float(os.environ.get("GF_FLOW_CHE_BAD", "100"))
PB_DEEP    = float(os.environ.get("GF_PB_DEEP", "-2.5"))
PB_CHE     = float(os.environ.get("GF_PB_CHE", "90"))
REB        = float(os.environ.get("GF_REB", "0.4"))
REB_CHE    = float(os.environ.get("GF_REB_CHE", "110"))
TIMEOUT    = int(os.environ.get("GF_TIMEOUT", "40"))
RUN_SEC    = float(os.environ.get("GF_RUN_SEC", "0"))
VSTOP      = -2.0          # 가상 하드손절 기록(%·매도설계는 오프라인)

CAND_COLS = ["일자", "종목코드", "후보시각", "후보가", "무장시각", "돌파가", "밴드폭", "대금배수",
             "돌파체결강도", "눌림깊이", "자금점수", "체결강도추세", "프로그램", "호가",
             "손절터치초", "고점재돌파", "r5", "r15", "r30", "r60", "r120",
             "최대반등", "최대밀림", "종료수익", "종료사유"]
REJ_COLS = ["일자", "종목코드", "시각", "단계", "사유"]


def _log(m):
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8") as f:
            f.write(f"[{datetime.now():%H:%M:%S}] {m}\n")
    except Exception:
        pass
    print(m, flush=True)


def load_ma_gap():
    """일봉 5/20일선 이격(%) {code: gap%} — 마지막 거래일 기준. 실패 시 빈 dict(이격 조건 생략·로그)."""
    try:
        import pandas as pd
        df = pd.read_csv(EODCSV, usecols=["date", "code", "close"],
                         dtype={"date": str, "code": str}, low_memory=False)
        days = sorted(df["date"].unique())[-20:]
        df = df[df["date"].isin(days)]
        out = {}
        for code, g in df.groupby("code"):
            c = g.sort_values("date")["close"].values
            if len(c) < 20 or c[-1] <= 0:
                continue
            ma5, ma20 = c[-5:].mean(), c.mean()
            if ma20 > 0:
                out[code] = abs(ma5 - ma20) / ma20 * 100
        return out
    except Exception as e:
        _log(f"⚠️ 일봉 이격 로드 실패({e}) — 5/20이격 조건은 이번 세션 생략(fail-open)")
        return {}


class Flow:
    """종목 하나 — 분봉 조립 + 5단계 상태기계. 상태: IDLE→SPIKE→PULLBACK→FOLLOW(후보 성과추적)→DONE
    (FOLLOW = 내부 상태. Shadow 운영 모드와 혼용 금지 — 지침서2)"""

    def __init__(self, code, ma_gap_pct):
        self.code = code
        self.ma_ok = (ma_gap_pct is None) or (ma_gap_pct <= MA_GAP)
        self.bars = deque(maxlen=70)      # (분번호, o,h,l,c, val, vol, che_min)
        self.cur_min = None
        self.o = self.h = self.l = self.c = 0.0
        self.val = self.vol = 0.0
        self.buy = self.sell = 0.0        # 틱룰 분내 매수/매도량
        self.last_p = self.last_v = None
        self.last_dir = 0
        self.state = "IDLE"
        self.rej = None                    # (단계, 사유) — 1회 기록용
        # SPIKE 이후 상태
        self.arm_min = None
        self.brk_px = None                 # 돌파봉 종가
        self.brk_che = None
        self.bandw = None
        self.volx = None
        self.pre_avg_val = None            # 스파이크 전 분당대금 평균
        self.box_lo = None                 # 횡보밴드 하단(저점붕괴 기준)
        self.spike_peak = None
        self.pb_low = None
        self.score = 0.0
        self.che_hist = deque(maxlen=4)    # 최근 분 구간체결강도
        self.dry_cnt = 0
        # FOLLOW 상태(후보 성과 추적 전용 — 새 매수조건 검사·후보 취소 없음)
        self.cand_px = None
        self.cand_hm = None
        self.t_cand = None
        self.hi = self.lo = None
        self.stop_s = None
        self.rebreak = False           # 고점(스파이크피크) 재돌파 여부
        self.r5 = self.r15 = None
        self.r30 = self.r60 = self.r120 = None
        self.last_px = None
        self.done_why = ""

    # ---- 틱 → 분봉 조립(틱룰 포함) ----
    def tick(self, minute_no, px, cum_vol):
        dv = 0.0
        if self.last_v is not None and cum_vol is not None:
            dv = max(0.0, cum_vol - self.last_v)
        if cum_vol is not None:
            self.last_v = cum_vol
        if self.last_p is not None and dv > 0:
            d = self.last_dir
            if px > self.last_p:
                d = 1
            elif px < self.last_p:
                d = -1
            if d > 0:
                self.buy += dv
            elif d < 0:
                self.sell += dv
            self.last_dir = d
        self.last_p = px
        done = None
        if self.cur_min is None or minute_no != self.cur_min:
            if self.cur_min is not None:
                che = (self.buy / self.sell * 100.0) if self.sell > 0 else (999.0 if self.buy > 0 else 0.0)
                done = (self.cur_min, self.o, self.h, self.l, self.c, self.val, self.vol, che)
                self.bars.append(done)
            self.cur_min = minute_no
            self.o = self.h = self.l = self.c = px
            self.val = dv * px
            self.vol = dv
            self.buy = self.sell = 0.0
        else:
            self.h, self.l, self.c = max(self.h, px), min(self.l, px), px
            self.val += dv * px
            self.vol += dv
        # FOLLOW 성과 추적은 틱 단위
        if self.state == "FOLLOW" and self.cand_px:
            self.follow_tick(px)
        return done

    # ---- 1단계: 횡보 판정 ----
    def _box(self, m):
        win = [b for b in self.bars if m - BOX_MIN <= b[0] < m]
        if len(win) < COVER_MIN:
            return None
        hi = max(b[2] for b in win)
        lo = min(b[3] for b in win)
        if lo <= 0:
            return None
        bandw = (hi - lo) / lo * 100
        if bandw > BAND_MAX:
            return None
        # 변동폭 축소: 최근 15분 평균 레인지 ≤ 이전 30분 평균 레인지
        rec = [b for b in win if b[0] >= m - 15]
        old = [b for b in win if b[0] < m - 15]
        if not rec or not old:
            return None
        rng = lambda bs: sum((b[2] - b[3]) / b[3] for b in bs if b[3] > 0) / len(bs)
        if rng(rec) > rng(old):
            return None
        # 거래량 감소: 최근 15분 평균 분당대금 ≤ 전체 평균 × DRY_RATIO
        avg_all = sum(b[5] for b in win) / len(win)
        avg_rec = sum(b[5] for b in rec) / len(rec)
        if avg_all <= 0 or avg_rec > avg_all * DRY_RATIO:
            return None
        return (bandw, hi, lo, avg_all)

    # ---- 완성봉마다 상태기계 진행 ----
    def on_bar(self, bar, rejects, today):
        m, o, h, l, c, val, vol, che = bar
        hm = f"{m//60:02d}{m%60:02d}"
        try:
            if self.state == "IDLE":
                if not self.ma_ok:
                    return
                box = self._box(m)
                if box is None:
                    return
                bandw, bhi, blo, avg_val = box
                # 2단계: 갑툭이 동시 조건
                prev_c = self.bars[-2][4] if len(self.bars) >= 2 else 0
                ret = (c / prev_c - 1) * 100 if prev_c > 0 else 0
                avg_vol = sum(b[6] for b in self.bars if m - BOX_MIN <= b[0] < m) / max(1, len([b for b in self.bars if m - BOX_MIN <= b[0] < m]))
                if not (c > bhi and val >= VOLX * avg_val and val >= MINVAL):
                    return
                if vol < VOLX * avg_vol:
                    rejects.append({"일자": today, "종목코드": self.code, "시각": hm, "단계": "2", "사유": "대금만급증_거래량미달"})
                    return
                if che < SPIKE_CHE:
                    rejects.append({"일자": today, "종목코드": self.code, "시각": hm, "단계": "2", "사유": f"체결강도미달({che:.0f}<{SPIKE_CHE:.0f})"})
                    return
                if ret < SPIKE_RET:
                    rejects.append({"일자": today, "종목코드": self.code, "시각": hm, "단계": "2", "사유": "거래량만증가_가격미동행"})
                    return
                self.state = "SPIKE"
                self.arm_min, self.brk_px, self.brk_che = m, c, che
                self.bandw, self.volx = bandw, val / avg_val
                self.pre_avg_val, self.box_lo = avg_val, blo
                self.spike_peak, self.pb_low = h, None
                self.score = 0.0
                self.che_hist.clear()
                self.che_hist.append(che)
                self.dry_cnt = 0
                _log(f"🚀무장 {self.code} {hm} 돌파{c:,.0f} 밴드{bandw:.2f}% 대금{self.volx:.0f}배 체결{che:.0f}")
                return

            if self.state in ("SPIKE", "PULLBACK"):
                if m - self.arm_min > TIMEOUT:
                    self._reject(rejects, today, hm, "5", "시간만료(재출발없음)")
                    return
                self.spike_peak = max(self.spike_peak, h)
                self.che_hist.append(che)
                # 즉시 탈락 — 저점붕괴(횡보밴드 하단)
                if l < self.box_lo:
                    self._reject(rejects, today, hm, "4", "저점붕괴(밴드하단)")
                    return
                # 즉시 탈락 — 깊은 눌림(연구: 깊이=가짜 판별기)
                depth = (l / self.brk_px - 1) * 100
                if depth <= PB_DEEP:
                    self._reject(rejects, today, hm, "4", f"깊은눌림({depth:.1f}%≤{PB_DEEP}%)")
                    return
                # 즉시 탈락 — 돈 끊김(2분 연속 스파이크 전 평균 미만)
                self.dry_cnt = self.dry_cnt + 1 if val < self.pre_avg_val else 0
                if self.dry_cnt >= 2:
                    self._reject(rejects, today, hm, "3", "대금급감(2분연속)")
                    return
                # 즉시 탈락 — 체결강도 연속 하락 & 매도우위
                if len(self.che_hist) >= 3:
                    a, b2, c3 = list(self.che_hist)[-3:]
                    if a > b2 > c3 and c3 < CHE_BAD:
                        self._reject(rejects, today, hm, "3", f"체결강도추락({a:.0f}→{b2:.0f}→{c3:.0f})")
                        return
                # 3단계 매분 채점(가중: 체결강도3·대금속도2·거래량2 — 프로그램/호가 피드없음 0점)
                if che >= 120 or (len(self.che_hist) >= 2 and che >= list(self.che_hist)[-2]):
                    self.score += 3
                recent = [b for b in self.bars if b[0] > m - 3]
                older = [b for b in self.bars if m - 6 < b[0] <= m - 3]
                if older and recent and sum(b[5] for b in recent) >= sum(b[5] for b in older):
                    self.score += 2
                if val >= 2 * self.pre_avg_val:
                    self.score += 2
                # 4단계: 눌림 추적
                if c < self.brk_px:
                    self.state = "PULLBACK"
                    self.pb_low = l if self.pb_low is None else min(self.pb_low, l)
                    if che < PB_CHE:
                        self._reject(rejects, today, hm, "4", f"눌림중매도우위(체결{che:.0f}<{PB_CHE:.0f})")
                        return
                # 5단계: 재출발(눌림 겪은 뒤에만 — "즉시 추격매수하지 않는다")
                if self.state == "PULLBACK" and self.pb_low and self.pb_low > 0:
                    if c >= self.pb_low * (1 + REB / 100) and val >= 2 * self.pre_avg_val and che >= REB_CHE:
                        self.state = "FOLLOW"
                        self.cand_hm = hm
                        self.cand_px = None      # 다음 틱에서 확정
                        self.pb_depth = (self.pb_low / self.brk_px - 1) * 100
                        _log(f"✅후보 {self.code} {hm} 재출발(눌림{self.pb_depth:.2f}%·체결{che:.0f}·점수{self.score:.0f}) → FOLLOW START")
                return
        except Exception as e:
            _log(f"⚠️ {self.code} on_bar 오류: {e}")
            self.state = "DONE"

    def _reject(self, rejects, today, hm, stage, why):
        rejects.append({"일자": today, "종목코드": self.code, "시각": hm, "단계": stage, "사유": why})
        _log(f"❌탈락 {self.code} {hm} [{stage}단계] {why}")
        self.state = "IDLE"          # 처음부터 다시(새 횡보 형성 시 재도전 가능)
        self.arm_min = None

    # ---- FOLLOW: 후보 확정 이후 성과 추적만(매수조건 검사·후보 취소 없음 — 지침서2) ----
    def follow_tick(self, px):
        t = time.time()
        if self.cand_px is None:
            self.cand_px = px
            self.t_cand = t
            self.hi = self.lo = px
            return
        self.last_px = px
        self.hi, self.lo = max(self.hi, px), min(self.lo, px)
        if not self.rebreak and self.spike_peak and px > self.spike_peak:
            self.rebreak = True
        el = t - self.t_cand
        r = (px / self.cand_px - 1) * 100
        if self.stop_s is None and r <= VSTOP:
            self.stop_s = round(el)
        if self.r5 is None and el >= 300:
            self.r5 = round(r, 2)
        if self.r15 is None and el >= 900:
            self.r15 = round(r, 2)
        if self.r30 is None and el >= 1800:
            self.r30 = round(r, 2)
        if self.r60 is None and el >= 3600:
            self.r60 = round(r, 2)
        if self.r120 is None and el >= 7200:
            self.r120 = round(r, 2)
            self.state = "DONE"
            self.done_why = "120분"

    def cand_row(self, today):
        e = self.cand_px or 0
        return {"일자": today, "종목코드": self.code, "후보시각": self.cand_hm, "후보가": e or "",
                "무장시각": f"{self.arm_min//60:02d}{self.arm_min%60:02d}" if self.arm_min else "",
                "돌파가": self.brk_px, "밴드폭": round(self.bandw or 0, 2),
                "대금배수": round(self.volx or 0, 1), "돌파체결강도": round(self.brk_che or 0, 0),
                "눌림깊이": round(getattr(self, "pb_depth", 0), 2), "자금점수": round(self.score, 0),
                "체결강도추세": ">".join(f"{x:.0f}" for x in self.che_hist),
                "프로그램": "피드없음", "호가": "피드없음",
                "손절터치초": self.stop_s if self.stop_s is not None else "",
                "고점재돌파": 1 if self.rebreak else 0,
                "r5": self.r5 if self.r5 is not None else "",
                "r15": self.r15 if self.r15 is not None else "",
                "r30": self.r30 if self.r30 is not None else "",
                "r60": self.r60 if self.r60 is not None else "",
                "r120": self.r120 if self.r120 is not None else "",
                "최대반등": round((self.hi / e - 1) * 100, 2) if e else "",
                "최대밀림": round((self.lo / e - 1) * 100, 2) if e else "",
                "종료수익": round((self.last_px / e - 1) * 100, 2) if (e and self.last_px) else "",
                "종료사유": self.done_why or "장끝"}


def main():
    today = datetime.now().strftime("%Y%m%d")
    if datetime.now().strftime("%H%M") > END:
        _log("장 종료 후 기동 — 종료")
        return
    _log("=" * 64)
    _log(f"🚀💰 갑툭이 자금유입 그림자 — 주문0·TR0 · 박스{BOX_MIN}분≤{BAND_MAX}%·대금{VOLX}배·체결{SPIKE_CHE:.0f}↑·5단계 상태기계")
    _log("ℹ️ 프로그램 순매수·호가 피드 없음(IPC 확인) — 지침서 ④⑤항 0점 처리, 피드 신설 시 활성화")
    ma_gap = load_ma_gap()
    _log(f"일봉 5/20이격 로드: {len(ma_gap)}종목 (이격≤{MA_GAP}%만 감시)")
    OUTDIR.mkdir(parents=True, exist_ok=True)
    flows, rejects, cands = {}, [], []
    last_seen = {}
    t0 = time.time()
    last_hb = time.time()

    while True:
        now = datetime.now()
        hm = now.strftime("%H%M")
        if hm >= END or (RUN_SEC and time.time() - t0 >= RUN_SEC):
            break
        if hm < START:
            time.sleep(1.0)
            continue
        try:
            snap = json.loads(SNAP.read_text(encoding="utf-8-sig")).get("codes", {})
        except Exception:
            time.sleep(POLL)
            continue
        for code, v in snap.items():
            try:
                ts = str(v.get("ts") or "")
                if len(ts) < 16 or ts[:10] != now.strftime("%Y-%m-%d"):
                    continue
                px = float(v.get("cur") or 0)
                if px < PXMIN or not ("09" <= ts[11:13] <= "15"):
                    continue
                key = (ts, v.get("cur"), v.get("cum_vol"))
                if last_seen.get(code) == key:
                    continue
                last_seen[code] = key
                cv = v.get("cum_vol")
                cv = float(cv) if cv is not None else None
                fl = flows.get(code)
                if fl is None:
                    fl = flows[code] = Flow(code, ma_gap.get(code))
                bar = fl.tick(int(ts[11:13]) * 60 + int(ts[14:16]), px, cv)
                if bar is not None and fl.state in ("IDLE", "SPIKE", "PULLBACK"):
                    fl.on_bar(bar, rejects, today)
                if fl.state == "DONE" and fl.cand_px:
                    cands.append(fl.cand_row(today))
                    _log(f"🏁FOLLOW END {code} ({fl.done_why}) 종료수익{(fl.last_px / fl.cand_px - 1) * 100 if fl.last_px else 0:+.2f}%")
                    fl.state = "IDLE"; fl.cand_px = None; fl.arm_min = None
            except Exception as e:
                _log(f"⚠️ {code} 루프 오류: {e}")
        if time.time() - last_hb >= 1800:
            st = {}
            for f2 in flows.values():
                st[f2.state] = st.get(f2.state, 0) + 1
            _log(f"💓 감시 {len(flows)}종목 상태={st} 후보 {len(cands)} 탈락 {len(rejects)}")
            last_hb = time.time()
        time.sleep(POLL)

    for f2 in flows.values():
        if f2.state == "FOLLOW" and f2.cand_px:
            f2.done_why = "장끝"
            cands.append(f2.cand_row(today))
            _log(f"🏁FOLLOW END {f2.code} (장끝)")
    for name, cols, rows in (("gaptuki_flow_candidates.csv", CAND_COLS, cands),
                             ("gaptuki_flow_rejects.csv", REJ_COLS, rejects)):
        fp = OUTDIR / name
        # 컬럼 확장(r5·r15·고점재돌파) 시 옛 헤더 파일과 섞이지 않게 회전 보관
        if fp.exists():
            try:
                head = fp.open(encoding="utf-8-sig").readline().strip()
                if head and head.split(",") != cols:
                    fp.rename(fp.with_suffix(f".old_{datetime.now():%Y%m%d}.csv"))
                    _log(f"🗂 {name} 헤더 변경 — 기존 파일 회전 보관")
            except Exception:
                pass
        new = not fp.exists()
        with fp.open("a", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore", restval="")
            if new:
                w.writeheader()
            for r in rows:
                w.writerow(r)
    _log(f"종료 — 감시 {len(flows)}종목 · 후보 {len(cands)} · 탈락 {len(rejects)} → {OUTDIR}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
    except Exception as e:
        _log(f"🚨 치명 오류: {e}")
        sys.exit(1)
