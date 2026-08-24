# -*- coding: utf-8 -*-
"""🏔️⚡ [UNIVERSAL VALLEY SCALPING ENGINE] — 오전 스캘핑 전용 매수 판정 모듈  [2026-07-17 밤 친구님 스펙]

★★급락주(low_anchor_buy_v1)와 완전 분리 — 친구님 "스캘핑이라 급락주하고 같으면 안 돼".
   이 파일은 morning_scalp_live_v1.py 전용. 급락주 코드는 import도 안 하고 건드리지도 않는다.

친구님 스펙 그대로:
  1. 새로운 저점이 발생하면 즉시 매수하지 않는다.
  2. 저점 Anchor를 생성한다.
  3. Anchor 생성과 동시에 매수체결량·매도체결량·Delta·seg_che 전부 0 리셋.
  4. Anchor 이후 VS_OBS_SEC(기본30초) 동안 새 체결만 분석한다.
  5. 실시간 계산: seg_che·매수체결량·매도체결량·Delta·VEL(체결속도)·ACC(체결가속도)
     — VEL/ACC는 최근 10초 기준 실시간 계산(스펙 9).
  6. 매수 조건(전부 동시 충족):
     seg_che ≥ VS_SEG_CHE_TH(105) ∧ 매수체결량 ≥ 매도체결량 ∧ Delta 증가 ∧ VEL 증가 ∧ ACC 증가
     ∧ 저점 대비 +VS_ZONE_LO(0.8)% ~ +VS_ZONE_HI(1.5)% 반등
  7. 손절: 매수가 대비 -1.0% 즉시 전량 매도 (엔진 쪽 MS_STOP이 담당 — 이 모듈은 매수 판정만)
  9. 원칙: 첫 반등 추격 금지(관찰시간 경과 전 매수 금지) · 과거 체결량 사용 금지(앵커 이후만) ·
     문턱은 환경변수(코드수정 없이 100/105/110/115 튜닝).

⚠️체결량 분류는 틱룰 근사(폴링 사이 누적거래량 증가분을 가격 오르면 매수/내리면 매도로 분류).
⚠️VEL/ACC는 초단위 개념이라 과거 1분봉 백테로 검증 불가 — 그림자 2초 실데이터가 유일한 검증 수단.

■ 스위치 (전부 스캘핑 전용 — 급락주 LA_*와 무관)
  VS_SEG_CHE_TH=105    구간 체결강도 매수 문턱
  VS_ZONE_LO=0.8       반등존 하한(%)      VS_ZONE_HI=1.5   반등존 상한(%)
  VS_OBS_SEC=30        앵커 후 관찰시간(초) — 이 전엔 매수 금지(첫 반등 추격 금지)
  VS_VEL_WIN=10        VEL/ACC 계산 창(초)
"""
import os
from dataclasses import dataclass, field
from typing import Optional, Dict, List

SEG_CHE_TH = float(os.environ.get("VS_SEG_CHE_TH", "105"))
ZONE_LO    = float(os.environ.get("VS_ZONE_LO", "0.8"))
ZONE_HI    = float(os.environ.get("VS_ZONE_HI", "1.5"))
OBS_SEC    = float(os.environ.get("VS_OBS_SEC", "30"))
VEL_WIN    = float(os.environ.get("VS_VEL_WIN", "10"))


@dataclass
class ValleyAnchor:
    """종목 1개짜리 저점앵커 매수 판정 상태기계(스캘핑 전용) — 주문 없음, 판정만."""
    code: str
    seg_che_th: float = SEG_CHE_TH
    zone_lo: float = ZONE_LO
    zone_hi: float = ZONE_HI
    obs_sec: float = OBS_SEC
    vel_win: float = VEL_WIN

    low: Optional[float] = field(default=None, init=False)        # 현재 추적 저점(앵커)
    anchor_ts: Optional[float] = field(default=None, init=False)
    seg_buy: float = field(default=0.0, init=False)
    seg_sell: float = field(default=0.0, init=False)
    last_cum_vol: Optional[float] = field(default=None, init=False)
    last_px: Optional[float] = field(default=None, init=False)
    last_dir: int = field(default=0, init=False)
    samples: List = field(default_factory=list, init=False)        # [(ts, cum_vol)] 최근 창×2
    vel_hist: List = field(default_factory=list, init=False)       # [(ts, vel)] 최근 창×2
    last_delta: Optional[float] = field(default=None, init=False)
    last_vel: Optional[float] = field(default=None, init=False)
    last_acc: Optional[float] = field(default=None, init=False)
    done: bool = field(default=False, init=False)                  # 매수 확정 후 True(엔진이 재관찰 시 리셋)

    def _reset_anchor(self, cur, cum_vol, now_ts):
        """앵커 생성/리셋 — 절대규칙: 체결량·Delta·seg_che 전부 0."""
        self.low = cur
        self.anchor_ts = now_ts
        self.seg_buy = self.seg_sell = 0.0
        self.last_cum_vol = cum_vol
        self.last_px = cur
        self.last_dir = 0
        self.samples = [(now_ts, cum_vol)] if cum_vol is not None else []
        self.vel_hist = []
        self.last_delta = None
        self.last_vel = None
        self.last_acc = None

    def feed(self, cur: float, cum_vol: Optional[float], now_ts: float) -> Optional[Dict]:
        """매 폴링(2초 권장)마다 호출. 반환 None(관망) 또는
        {"signal":"BUY"|"STATUS", "low","entry_px","seg_che","buy_vol","sell_vol","delta",
         "vel_up","acc_up","delta_up","in_zone","elapsed"}"""
        if self.done or cur <= 0:
            return None

        # ① 신저점 → 앵커 생성/리셋 (첫 시세도 여기서 앵커가 됨)
        if self.low is None or cur < self.low:
            self._reset_anchor(cur, cum_vol, now_ts)
            return None

        # ② 앵커 이후 새 체결만 누적 (틱룰 근사)
        if self.last_px is not None and cum_vol is not None and self.last_cum_vol is not None:
            dv = max(0.0, cum_vol - self.last_cum_vol)
            d = self.last_dir
            if cur > self.last_px:
                d = 1
            elif cur < self.last_px:
                d = -1
            if d > 0:
                self.seg_buy += dv
            elif d < 0:
                self.seg_sell += dv
            self.last_dir = d
        self.last_px = cur
        if cum_vol is not None:
            self.last_cum_vol = cum_vol
            self.samples.append((now_ts, cum_vol))
            cutoff = now_ts - self.vel_win * 2.5
            self.samples = [s for s in self.samples if s[0] >= cutoff]

        # ③ 실시간 지표
        delta = self.seg_buy - self.seg_sell
        seg_che = (self.seg_buy / self.seg_sell * 100.0) if self.seg_sell > 0 else (999.0 if self.seg_buy > 0 else 0.0)
        vel = None
        if len(self.samples) >= 2:
            base = None
            for ts0, cv0 in self.samples:                 # 창(10초) 전 시점과 비교해 초당 체결량
                if now_ts - ts0 >= self.vel_win:
                    base = (ts0, cv0)
                else:
                    break
            if base is None and (now_ts - self.samples[0][0]) >= 2:
                base = self.samples[0]
            if base and now_ts > base[0]:
                vel = (self.samples[-1][1] - base[1]) / (now_ts - base[0])
        acc = None
        if vel is not None:
            self.vel_hist.append((now_ts, vel))
            self.vel_hist = [v for v in self.vel_hist if v[0] >= now_ts - self.vel_win * 2.5]
            vbase = None
            for ts0, v0 in self.vel_hist:
                if now_ts - ts0 >= self.vel_win:
                    vbase = v0
                else:
                    break
            if vbase is None and len(self.vel_hist) >= 2:
                vbase = self.vel_hist[0][1]
            if vbase is not None:
                acc = vel - vbase

        delta_up = self.last_delta is not None and delta > self.last_delta
        vel_up = vel is not None and self.last_vel is not None and vel > self.last_vel
        acc_up = acc is not None and self.last_acc is not None and acc > self.last_acc
        self.last_delta = delta
        if vel is not None:
            self.last_vel = vel
        if acc is not None:
            self.last_acc = acc

        elapsed = now_ts - (self.anchor_ts if self.anchor_ts is not None else now_ts)
        in_zone = self.low * (1 + self.zone_lo / 100.0) <= cur <= self.low * (1 + self.zone_hi / 100.0)

        out = {"signal": "STATUS", "low": self.low, "entry_px": cur,
               "seg_che": round(seg_che, 1), "buy_vol": round(self.seg_buy),
               "sell_vol": round(self.seg_sell), "delta": round(delta),
               "delta_up": delta_up, "vel_up": vel_up, "acc_up": acc_up,
               "in_zone": in_zone, "elapsed": round(elapsed, 1)}

        # ④ 매수 판정 — 6조건 전부 ∧ 관찰시간 경과(첫 반등 추격 금지)
        if (elapsed >= self.obs_sec and in_zone
                and seg_che >= self.seg_che_th
                and self.seg_buy >= self.seg_sell
                and delta_up and vel_up and acc_up):
            self.done = True
            out["signal"] = "BUY"
        return out


# ── 장부 직렬화 (morning_scalp_live_v1 ledger 저장용) ──
VA_FIELDS = ["low", "anchor_ts", "seg_buy", "seg_sell", "last_cum_vol", "last_px", "last_dir",
              "samples", "vel_hist", "last_delta", "last_vel", "last_acc", "done"]


def va_from_ledger(code, entry):
    va = ValleyAnchor(code=code)
    for k in VA_FIELDS:
        if k in entry:
            setattr(va, k, entry[k])
    return va


def va_to_ledger(va):
    return {k: getattr(va, k) for k in VA_FIELDS}
