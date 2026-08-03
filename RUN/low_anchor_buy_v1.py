# -*- coding: utf-8 -*-
"""🕳️📈 저점 앵커 매수 판정 — 순수 판정 모듈 (주문 없음·브로커 연결 없음)
   [2026-07-16 백테스트로 최초 확정 → 7/17 아침 개편: 키움 누적체결강도 → 저점구간 매수/매도 체결량 비율
    → 7/18 밤 재정리: 최초저점도 90초 검증 적용·비율 스케일을 체결강도와 동일하게 통일(105)·2차하락 필터 삭제]

목적: 급락주가 저점을 찍고 반등할 때 "지금 사도 되는가"를 판정만 한다. 매도·주문·슬롯 관리는
      이 파일 책임이 아니다(crash_flow_live_v1.py가 그 역할을 계속 맡는다).

■ 확정된 절차 (2026-07-18 밤 친구님 지시로 재정리)
  1. 진입 대기(armed)   : 전일종가 대비 -5% 이하로 빠질 때까지 아무것도 안 한다.
  2. 후보저점 관찰       : -5%를 뚫는 순간부터(최초 지점 포함) 신저가가 나올 때마다 "후보"로만 기록한다
                          (카운터는 아직 안 건드림). 최초 지점도 예외 없이 아래 3단계 검증을 거친다.
  3. 저점 확정(CAND_HOLD): 후보저점이 90초(기본) 이상 안 깨지면 그제서야 "진짜 저점"으로 확정하고
                          매수/매도 체결량 카운터를 0으로 리셋한다. ★이 순간이 90초 관찰시계(WATCH_MAX)의
                          시작점이다(친구님 "90초 관찰은 저점에서 시작되어야 돼").
  4. 매수구간            : 저점 대비 +1%~+1.5%(OBS_PCT_LO~HI) 구간이 "매수 가능 구간"이다.
  5. 판정               : 저점 확정 이후 쌓인 매수체결량÷매도체결량×100 = buy_ratio로 판정
                          (키움 체결강도와 동일한 스케일 — 100이면 매수매도 동일, 105면 매수가 5% 더 많음).
       · 매수구간(+1~1.5%) 안에서 buy_ratio ≥ BUY_RATIO(105) → 그 즉시 BUY
       · 90초(WATCH_MAX) 다 채우도록 못 사면 그 시점 buy_ratio로 최종 1회 판정(timeout)
       · 90초 관찰 도중 저점이 다시 깨지면(더 낮은 후보가 90초 안 안 깨짐) 저점을 그 값으로 재확정하고
         카운터·시계를 리셋해서 처음부터 다시 관찰한다(2~3단계 반복).
  6. 매수 후 재관찰      : 매수가 대비 -2%(LA_REBUY_STOP) 떨어지면 즉시 매도하고, 같은 방법(1~5)으로
                          신저점을 다시 찾는다. 재매수는 종목당 최대 LA_REBUY_MAX(2)회까지만 허용
                          (친구님 "2번까지만 재매수") — 배선은 crash_flow_live_v1.py 쪽에서 한다.
  ⚠️ 매수/매도 체결량 자체는 "이번 폴링 사이 늘어난 누적거래량을, 가격이 오르면 매수/내리면 매도로
     분류"하는 근사(그림자 crash_lowflow_shadow_v1과 동일 방식)다. 체결가 대 최우선호가 비교(정밀분류)는
     하지 않는다 — 그건 브로커 공유 프로세스(broker_gateway_v1.py) 수정이 필요해 보류했다.
  ⚠️ 임계값(105/90초/90초/-2%/2회)은 전부 원칙 기반 추정치다. 진짜 검증은 실전 로그(low_anchor_buy_live.csv)로 한다.

■ 사용법 (실전 엔진에 붙일 때)
    la = LowAnchor(code, prev_close)
    ...매 폴링마다(2초 권장)...
    ev = la.feed(hm, cur, cum_vol, now_ts)
    if ev and ev["signal"] == "BUY":
        ...매수 주문은 호출측(crash_flow_live_v1 등)이 처리...

■ 스위치 (환경변수)
  LA_ARM_PCT=-5           진입 대기 문턱(전일종가 대비 %)
  LA_OBS_PCT_LO=1         매수구간 하한(%) — 저점 대비 반등폭
  LA_OBS_PCT_HI=1.5       매수구간 상한(%) — 1.5% 넘으면 매수 금지
  LA_CAND_HOLD=90         후보저점이 이만큼(초) 안 깨져야 진짜 저점으로 확정 (최초 저점도 동일 적용)
  LA_WATCH_MAX=90         저점 확정 후 판정 최대 시간(초) — 넘으면 그 시점 buy_ratio로 최종판정
  LA_BUY_RATIO=105        매수 확정 buy_ratio 문턱(매수÷매도×100 스케일, 매수구간 안에서만 유효)
                          [2026-07-18 밤] 51.2%(매수÷전체 스케일) → 105(매수÷매도 스케일)로 통일.
                          51.2%를 매수÷매도 스케일로 환산하면 104.9 ≈ 105라 백테 근거(놓침률 19%→12%)는 유지됨.
  LA_REBUY_STOP=-2        매수가 대비 이만큼(%) 떨어지면 즉시 매도 후 재관찰(crash_flow_live_v1.py 배선)
  LA_REBUY_MAX=2          종목당 재매수 최대 허용 횟수(crash_flow_live_v1.py 배선)
  LA_ENTRY=0900 LA_ENTRY_END=0930   판정을 허용하는 시각 구간
"""
import os, sys, csv, json, time
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass, field
from typing import Optional, Dict

try:                                     # 콘솔 코드페이지(cp949)가 —/≥ 같은 문자를 못 받아 죽는 것 방지
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ARM_PCT      = float(os.environ.get("LA_ARM_PCT", "-5"))
OBS_PCT_LO   = float(os.environ.get("LA_OBS_PCT_LO", "1"))    # ★[7/17 낮] 매수구간 하한(%) — 1.2 단일점 → 1~2% 밴드
OBS_PCT_HI   = float(os.environ.get("LA_OBS_PCT_HI", "1.5"))  # ★[7/18] 2 → 1.5로 좁힘(친구님 지시: 1.5%초과 매수금지)
OBS_PCT      = OBS_PCT_LO   # 하위호환(예전 코드가 obs_pct 필드 하나만 참조하던 흔적)
CAND_HOLD    = float(os.environ.get("LA_CAND_HOLD", "90"))    # ★[7/18] 25 → 90으로 상향(친구님 지시)
WATCH_MAX    = float(os.environ.get("LA_WATCH_MAX", "90"))
BUY_RATIO    = float(os.environ.get("LA_BUY_RATIO", "105"))   # ★[7/18 밤] 51.2%(매수÷전체) → 105(매수÷매도, 체결강도와 동일스케일)로 통일. 51.2%=104.9와 사실상 동일값이라 백테 근거 유지
ENTRY_HM     = os.environ.get("LA_ENTRY", "0900")
ENTRY_END    = os.environ.get("LA_ENTRY_END", "0930")
REBUY_STOP   = float(os.environ.get("LA_REBUY_STOP", "-2"))   # ★[7/17] crash_flow_live_v1.py 배선용
REBUY_MAX    = int(os.environ.get("LA_REBUY_MAX", "2"))       # ★[7/17] crash_flow_live_v1.py 배선용


@dataclass
class LowAnchor:
    """종목 1개짜리 저점 앵커 매수 판정 상태기계. 주문 없음 — 판정만 반환한다."""
    code: str
    prev_close: float
    arm_pct: float = ARM_PCT
    obs_pct: float = OBS_PCT
    obs_pct_lo: float = OBS_PCT_LO
    obs_pct_hi: float = OBS_PCT_HI
    buy_ratio_th: float = BUY_RATIO

    armed: bool = field(default=False, init=False)
    cand_low: Optional[float] = field(default=None, init=False)
    cand_low_t: Optional[float] = field(default=None, init=False)
    obs_low: Optional[float] = field(default=None, init=False)
    seg_buy: float = field(default=0.0, init=False)
    seg_sell: float = field(default=0.0, init=False)
    last_cum_vol: Optional[float] = field(default=None, init=False)
    last_px: Optional[float] = field(default=None, init=False)
    last_dir: int = field(default=0, init=False)
    obs_low_t: Optional[float] = field(default=None, init=False)   # ★저점 확정 시각 — 90초 시계의 시작점
    decided: bool = field(default=False, init=False)   # 이번 저점에서 이미 판정을 냈는가
    done: bool = field(default=False, init=False)       # 매수 확정 후에는 더 이상 판정 안 함(한 종목 1회)

    def _reset_seg(self, cur, cum_vol, now_ts):
        self.seg_buy = self.seg_sell = 0.0
        self.last_cum_vol = cum_vol
        self.last_px = cur
        self.last_dir = 0
        self.decided = False
        self.obs_low_t = now_ts

    def _seg_update(self, cur, cum_vol):
        """매 폴링마다 저점 구간 매수/매도 체결량(근사) 누적 — 그림자(LowFlow)와 동일한 틱룰 근사.
           이번 폴링 사이 늘어난 누적거래량을, 가격이 오르면 매수/내리면 매도로 분류한다."""
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

    def _buy_ratio(self) -> Optional[float]:
        """매수÷매도×100 — 키움 체결강도와 동일한 스케일(105=매수가 매도보다 5% 많음).
        ★[7/18 밤] 매수÷전체×100(0~100%) 방식은 105 문턱과 스케일이 안 맞아 매수÷매도로 교체."""
        if self.seg_sell <= 0:
            return None   # 매도체결 아직 없음 — 비교 불가, 관찰 지속
        return self.seg_buy / self.seg_sell * 100.0

    def feed(self, hm: str, cur: float, cum_vol: Optional[float], now_ts: float) -> Optional[Dict]:
        """매 폴링(권장 2초)마다 호출. hm="HHMM", cur=현재가, cum_vol=누적거래량(방향분류용),
        now_ts=time.time() 계열 실수 초(초 단위 타이머용 — hm은 분 단위라 못 씀).
        반환: None(관망 지속·판정대상 아님) 또는 이벤트 dict
        {"signal": "BUY"|"WAIT", "obs_low", "entry_px", "buy_ratio",
         "seg_buy", "seg_sell", "reason", "hm"}"""
        if self.done or cur <= 0:
            return None
        if hm < ENTRY_HM or hm > ENTRY_END:
            return None

        if not self.armed:
            if cur <= self.prev_close * (1 + self.arm_pct / 100.0):
                self.armed = True
                self.cand_low, self.cand_low_t = cur, now_ts
                self.obs_low = None   # ★[7/18 밤] 최초 저점도 다른 후보와 동일하게 CAND_HOLD(90초) 검증을 거쳐야 확정 — 즉시확정 버그 수정
            return None

        # ① 후보저점 갱신 — 신저가가 나와도 아직 카운터는 안 건드린다(즉시확정 금지)
        if cur < self.cand_low:
            self.cand_low = cur
            self.cand_low_t = now_ts

        # ② 후보저점이 CAND_HOLD초 이상 안 깨지면 진짜 저점으로 확정 → 구간 카운터+90초 시계 리셋
        #    ★친구님 "90초 관찰은 저점에서 시작되어야 돼" — 이 순간이 시계 시작점. 최초 저점도 예외 없이 이 검증을 거친다.
        if (self.obs_low is None or self.cand_low < self.obs_low) and (now_ts - self.cand_low_t) >= CAND_HOLD:
            self.obs_low = self.cand_low
            self._reset_seg(cur, cum_vol, now_ts)

        if self.obs_low is None:
            return None   # 아직 확정 저점 없음 — 첫 90초 검증 중

        self._seg_update(cur, cum_vol)

        if self.decided:
            return None

        br = self._buy_ratio()
        elapsed = now_ts - self.obs_low_t   # ★저점 확정 시점부터 흐른 시간(90초 예산 공유)

        # ★친구님 "저점 반등 1~2% 구간이 매수구간" — 이 구간 안에서만 매수 확정
        # ★[7/18] 매수구간 = 저점 대비 +1%~+1.5% 밴드 — 1.5% 넘으면 놓친 반등으로 보고 매수 안 함
        in_zone = (br is not None
                   and self.obs_low * (1 + self.obs_pct_lo / 100.0) <= cur <= self.obs_low * (1 + self.obs_pct_hi / 100.0))
        if in_zone and br >= self.buy_ratio_th:
            self.decided = True; self.done = True
            return {"signal": "BUY", "obs_low": self.obs_low, "entry_px": cur,
                    "buy_ratio": round(br, 1), "seg_buy": round(self.seg_buy), "seg_sell": round(self.seg_sell),
                    "reason": "confirmed", "hm": hm}

        if elapsed >= WATCH_MAX:
            self.decided = True
            signal = "WAIT"
            if in_zone and br is not None and br >= self.buy_ratio_th:
                signal = "BUY"; self.done = True
            return {"signal": signal, "obs_low": self.obs_low, "entry_px": cur,
                    "buy_ratio": (round(br, 1) if br is not None else None),
                    "seg_buy": round(self.seg_buy), "seg_sell": round(self.seg_sell),
                    "reason": "timeout_90s", "hm": hm}

        return None   # 관찰 지속(아직 미확정)


# ────────────────────────────────────────────────────────────────────────
# ★급락주 실전 유니버스에 붙는 live 모드 — 판정만 로그, 주문 없음
# ────────────────────────────────────────────────────────────────────────
LEDGER   = Path(os.environ.get("LA_LEDGER") or r"C:\stock_bot\data\low_anchor_buy_ledger.json")
CSVLOG   = Path(os.environ.get("LA_CSV") or r"C:\stock_bot\LOG\low_anchor_buy_live.csv")
LOG      = Path(r"C:\stock_bot\data\LOG\low_anchor_buy_live.log")
LOOP_SEC = float(os.environ.get("LA_LOOP_SEC", "2"))
RUN_SEC  = float(os.environ.get("LA_RUN_SEC", "55"))

COLS = ["일자", "시각", "종목코드", "종목명", "판정", "저점", "진입가", "매수비율", "매수량", "매도량", "사유", "깊이"]


def _log(m):
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8") as f:
            f.write(f"[{datetime.now():%H:%M:%S}] {m}\n")
    except Exception:
        pass
    print(m, flush=True)


def _jload(p, d=None):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8-sig"))
    except Exception:
        return d if d is not None else {}


def _jsave(p, d):
    p = Path(p); p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, p)


def _csv_row(r):
    try:
        CSVLOG.parent.mkdir(parents=True, exist_ok=True)
        new = not CSVLOG.exists()
        with CSVLOG.open("a", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=COLS, extrasaction="ignore", restval="")
            if new:
                w.writeheader()
            w.writerow(r)
    except Exception as e:
        _log(f"CSV 실패: {e}")


LEDGER_FIELDS = ["armed", "cand_low", "cand_low_t", "obs_low", "obs_low_t", "seg_buy", "seg_sell",
                  "last_cum_vol", "last_px", "last_dir", "decided", "done"]


def la_from_ledger(code, entry, prev_close):
    """crash_flow_live_v1.py 등 호출측이 재사용하는 헬퍼 — 장부(dict)에서 LowAnchor 복원."""
    la = LowAnchor(code=code, prev_close=prev_close)
    for k in LEDGER_FIELDS:
        if k in entry:
            setattr(la, k, entry[k])
    return la


def la_to_ledger(la):
    """crash_flow_live_v1.py 등 호출측이 재사용하는 헬퍼 — LowAnchor 상태를 장부(dict)로 저장."""
    d = {k: getattr(la, k) for k in LEDGER_FIELDS}
    d["prev_close"] = la.prev_close
    return d


def _la_from_ledger(code, entry, prev_close):   # 하위호환 별칭(이 파일 안 live_main 용)
    return la_from_ledger(code, entry, prev_close)


def _la_to_ledger(la):
    return la_to_ledger(la)


def live_main():
    """★급락주 실전 유니버스(crash_flow_live_v1._crash_map)에 저점앵커 판정을 붙인다.
       매수/매도 주문은 절대 내지 않는다 — 로그만 남긴다. crash_flow_live_v1.py 자체가 이미
       실전 주문을 내므로, 이 함수는 예약작업으로 따로 돌리지 않는 독립 확인용이다."""
    sys.path.insert(0, r"C:\stock_bot\RUN")
    from crash_flow_live_v1 import _crash_map, _cur, _cum_vol   # ★관문 이중구현 방지 — 실전 엔진 함수 재사용

    now = datetime.now(); hm = now.strftime("%H%M"); today = now.strftime("%Y%m%d")
    if hm < ENTRY_HM or hm > ENTRY_END:
        return
    _log("=" * 70)
    _log(f"🕳️📈 저점 앵커 매수 판정(그림자·주문0) — 관찰폭+{OBS_PCT:.1f}% "
         f"매수비율{BUY_RATIO:.0f}(매수÷매도×100) 관찰{WATCH_MAX:.0f}초")

    L = _jload(LEDGER, {})
    if L.get("date") != today:
        L = {"date": today, "codes": {}}
        _jsave(LEDGER, L)

    deadline = time.monotonic() + RUN_SEC
    while time.monotonic() < deadline:
        now = datetime.now(); hm = now.strftime("%H%M")
        if hm > ENTRY_END:
            break
        dirty = False
        cm = _crash_map()
        t = time.time()
        for code, info in cm.items():
            entry = L["codes"].get(code)
            if entry and entry.get("done"):
                continue
            if entry is None:
                entry = {"prev_close": info["pc"]}
            la = _la_from_ledger(code, entry, info["pc"])
            cur = _cur(code); cv = _cum_vol(code)
            if cur <= 0:
                continue
            ev = la.feed(hm, cur, cv, t)
            L["codes"][code] = _la_to_ledger(la)
            dirty = True
            if ev:
                nm = info.get("name", code)
                _log(f"  {'💰' if ev['signal'] != 'WAIT' else '⏳'}{ev['signal']} {nm}({code}) "
                     f"저점{ev['obs_low']:,.0f}→{ev['entry_px']:,.0f} "
                     f"매수비율{(ev['buy_ratio'] if ev['buy_ratio'] is not None else 0):.0f}% "
                     f"(매수{ev['seg_buy']:,.0f}/매도{ev['seg_sell']:,.0f}) [{ev['reason']}]")
                _csv_row({"일자": today, "시각": now.strftime("%H:%M:%S"), "종목코드": code,
                          "종목명": nm, "판정": ev["signal"], "저점": round(ev["obs_low"]),
                          "진입가": round(ev["entry_px"]),
                          "매수비율": ev["buy_ratio"], "매수량": ev["seg_buy"], "매도량": ev["seg_sell"],
                          "사유": ev["reason"], "깊이": info.get("depth")})
        if dirty:
            _jsave(LEDGER, L)
        time.sleep(LOOP_SEC)


def _replay_check():
    print("⚠️ [7/17 개편 이후 이 자체검증은 더 이상 유효하지 않습니다.]")
    print("   저점구간 매수/매도 비율(buy_ratio)은 누적거래량(cum_vol) 변화가 있어야 계산되는데,")
    print("   과거 9거래일 아카이브(data/shadow/che_timeseries)에는 che_str만 있고 cum_vol이 없습니다.")
    print("   진짜 검증은 오늘(7/17) 이후 실전 로그(low_anchor_buy_live.csv)로 해야 합니다.")


if __name__ == "__main__":
    mode = os.environ.get("LA_MODE", "live").strip().lower()
    if mode == "replay":
        _replay_check()
    else:
        try:
            live_main()
        except KeyboardInterrupt:
            pass
        except Exception as e:
            _log(f"🚨 치명 오류: {e}")
            sys.exit(1)
