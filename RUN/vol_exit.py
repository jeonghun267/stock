# -*- coding: utf-8 -*-
"""[친구님 2026-07-01] ★공통 매도 — 1차=수급(체결강도 매수/매도 우위), 안전장치=20일선 무조건.
철학(친구님): "가격만 빠졌다고 팔지 말고, 수급(매수/매도 누가 위인가) 봐라. 단 20일선 꺾이면 무조건 매도."

매도 우선순위:
  1. (호출측) 하드손절 — 여기 아님
  2. ★20일선 이탈 → 무조건 매도(수급 무관 안전장치). ma20_hard=False면 skip(딥V=역배열 매수라 제외).
  3. 수급 판단(체결강도): 매수 우위(che≥che_dom) → 보유(5일선 깨져도 버팀·승자끌기)
                          매도 우위 → 5일선이탈 / 고점-pkdrop% / 장대음봉 / 직전저점이탈 시 매도
  4. (호출측) EOD

체결강도(che_str) 없으면 폴백=거래량 방향 proxy(거래량 살아있고 양봉=매수우위 추정).
순수 판단 함수 — 파일/주문 부작용 없음(중앙 CSV/스냅샷 읽기만). 반환 (sell:bool, reason:str|None).
"""
import os, json
from pathlib import Path

PRICES_1M = r"C:\stock_bot\data\prices_1m.csv"
SNAP = Path(r"C:\stock_bot\IPC\live_micro_snapshot.json")

VOL_WIN   = int(os.environ.get("VEXIT_VOL_WIN", "5"))       # 거래량 평균 봉수
CHE_DOM   = float(os.environ.get("VEXIT_CHE_DOM", "100"))   # 체결강도 매수우위 판정선(100=동율). ★홀드는 che>100(엄격)만·100이하=매도쪽
SHAKEOUT_CHE = float(os.environ.get("VEXIT_SHAKEOUT_CHE", "120"))  # ★몸털기 생존: 20선 이탈이라도 체결강도 이 값↑(강한 흡수=세력털기)면 안 팜(버팀)
PKDROP    = float(os.environ.get("VEXIT_PKDROP", "2.5"))    # 매도우위+고점대비 하락% 매도
BIGRED    = float(os.environ.get("VEXIT_BIGRED", "3.0"))    # ★[7/2 과민완화 친구님] 장대음봉 몸통% 2.0→3.0(정상 변동성 음봉엔 안 털림). 롤백 setx VEXIT_BIGRED 2.0
# ★[7/2 저점이탈 과민완화 친구님] 직전저점 1틱 이탈에도 팔던것→최근N봉 최저를 버퍼%만큼 '확실히' 깨야 매도(노이즈 제거).
LOWBREAK_N   = int(os.environ.get("VEXIT_LOWBREAK_N", "2"))     # 저점 기준 봉수(최근 N봉 최저). 1=기존(직전봉만)
LOWBREAK_BUF = float(os.environ.get("VEXIT_LOWBREAK_BUF", "0.3"))  # 이탈 버퍼%(이만큼 더 깨야 진짜 붕괴). 0=기존(1틱)
TRAIL_PCT = float(os.environ.get("VEXIT_TRAIL", "4.0"))     # ★트레일 백스톱: 고점 대비 이만큼 되밀리면 매도(수급무관·승자 되돌림 방어)
TRAIL_ARM = float(os.environ.get("VEXIT_TRAIL_ARM", "3.0")) # 고점이익 이%↑부터 트레일 작동(초반 노이즈 방지)
# ★[하이브리드 2026-07-01 친구님] 트렌드전략: 일봉 20일선 위면 매도금지(추세 끝까지 홀드) + 넓은 트레일 백스톱만 예외.
#   백테(7/1 5종목): 일봉20선 홀드가 평균 최고(+5.11%·강한추세 036930 +20% 끝까지). 롤백 setx VEXIT_HYBRID NO.
HYBRID       = os.environ.get("VEXIT_HYBRID", "YES").strip().upper() == "YES"
HYBRID_TRAIL = float(os.environ.get("VEXIT_HYBRID_TRAIL", "8.0"))   # 하이브리드 넓은 트레일(고점-%·최악 되돌림만 방어)
# ★[7/2 큰수익 되돌림 방어 친구님 #3] 매수우위라도 크게 오른뒤(+BIGRUN_TP%) 고점서 BIGRUN_TRAIL% 되밀리면 매도(반납 방지·1주도 적용).
BIGRUN_TP    = float(os.environ.get("VEXIT_BIGRUN_TP", "8.0"))      # 이 %↑(고점이익) 오른 뒤부터 작동. 0=끔
BIGRUN_TRAIL = float(os.environ.get("VEXIT_BIGRUN_TRAIL", "4.0"))   # 큰상승 후 고점 대비 이만큼 되밀리면 매도
# ★[7/2 진짜 부분익절(반 나누기) 친구님 #3] 자금 크면(1억) 수량 충분→+PARTIAL_TP%서 절반 익절하고 나머지 끌기. 30만 1주는 qty<2라 자동 무동작.
PARTIAL_TP    = float(os.environ.get("VEXIT_PARTIAL_TP", "10.0"))   # 이 %↑ 수익서 부분익절 1회. 0=끔
PARTIAL_RATIO = float(os.environ.get("VEXIT_PARTIAL_RATIO", "0.5")) # 부분익절 비율(0.5=절반)


def _recent_bars(code, k=8):
    """최근 k개 1분봉 (o,h,l,c,v). prices_1m.csv 중앙파일. 없으면 []."""
    try:
        import pandas as pd
        df = pd.read_csv(PRICES_1M, dtype={"code": str, "ts": str},
                         usecols=["code", "ts", "open", "high", "low", "close", "volume"])
        g = df[df["code"] == str(code).zfill(6)].sort_values("ts").tail(k)
        out = []
        for r in g.itertuples(index=False):
            out.append((float(r.open), float(r.high), float(r.low), float(r.close), float(r.volume)))
        return out
    except Exception:
        return []


def _che(code):
    """실시간 체결강도(매수/매도 체결 우위). live_micro_snapshot. 없으면 None."""
    try:
        d = json.load(open(SNAP, encoding="utf-8"))
        v = (d.get("codes", {}) or {}).get(str(code).zfill(6), {}).get("che_str")
        return float(v) if isinstance(v, (int, float)) else None
    except Exception:
        return None


def _ma(code):
    """3분봉(or일봉) ma5, ma20. exit_ma 공통. 실패시 (0,0)."""
    try:
        import exit_ma as _DMA
        return float(_DMA.ma5(code) or 0.0), float(_DMA.ma20(code) or 0.0)
    except Exception:
        return 0.0, 0.0


def _ma20_daily(code):
    """일봉 20일선(daily_ma 캐시). 하이브리드 홀드 판정용. 실패시 0."""
    try:
        import daily_ma
        return float(daily_ma.ma20(code) or 0.0)
    except Exception:
        return 0.0


def decide(code, entry, peak, cur, ma20_hard=True, che=None, params=None):
    """공통 매도 판단. 반환 (sell, reason). 하드손절/EOD는 호출측.
       ma20_hard=True(트렌드전략)=20일선 이탈 무조건 매도. False(딥V)=20선 skip.
       che 넘기면 그걸 씀(호출측이 이미 읽었으면)·아니면 스냅샷에서 읽음."""
    p = params or {}
    che_dom = float(p.get("che_dom", CHE_DOM)); pkdrop = float(p.get("pkdrop", PKDROP))
    bigred = float(p.get("bigred", BIGRED)); volwin = int(p.get("vol_win", VOL_WIN))
    bars = _recent_bars(code, volwin + 2)
    # [2026-07-07] ★봉 없어도(prices_1m 미수집 종목·돈흐름이 47종목 밖 대장 매수) 체결강도·고점-2.5%·이평 기반 매도는 동작.
    #   예전엔 bars<2면 무조건 홀드→매도판단 전체 스킵(하드-3%만 방어). 봉 필요한 장대음봉/저점이탈만 have_bars로 가드.
    have_bars = len(bars) >= 2
    if have_bars:
        o, h, l, c, v = bars[-1]
        prev_l = bars[-2][2]
    else:
        o = h = l = c = v = prev_l = 0.0
    ma5, ma20 = _ma(code)
    trail = float(p.get("trail", TRAIL_PCT)); trail_arm = float(p.get("trail_arm", TRAIL_ARM))
    # 체결강도(수급) 읽기 — 이게 주 매도판단
    if che is None:
        che = _che(code)
    dma = _ma20_daily(code) if (HYBRID and ma20_hard) else 0.0
    # 1. ★추세 이탈 = 매도(backstop). 하이브리드=일봉20선 / 비하이브리드=3분20선.
    #    ★일봉20선은 '한번 위로 올라간 뒤(peak>dma)' 이탈해야 매도 = 20선 아래서 산 종목 즉시청산 churn 방지.
    #    ★[몸털기 생존 2026-07-01 친구님] 20선 깨져도 체결강도≥SHAKEOUT_CHE(강한 흡수=세력털기)면 안 팔고 버팀(60선까지 탐).
    if dma > 0:
        if peak and peak > dma and cur < dma:
            if not (che is not None and che >= SHAKEOUT_CHE):   # 흡수 아니면(매도우위/약) = 진짜 붕괴 → 매도
                return True, "일봉20일선이탈(붕괴)"
            # else 흡수 → 홀드(아래 수급 끌기 + 하드손절/트레일이 최종 방어 = 60선 갈아탄 셈)
    elif ma20_hard and ma20 > 0 and cur < ma20:
        if not (che is not None and che >= SHAKEOUT_CHE):
            return True, "20일선이탈(무조건)"
    # 2. ★수급 매도 프로그램(우리 공통 매도전략) — 매수우위=계속 끌고 올라감 / 매도우위=매도.
    #    [2026-07-07 친구님] 동율(=che_dom=100)은 매도쪽 → 매수우위 홀드는 che>che_dom(엄격히 위)만. 롤백: > → >=.
    if che is not None:
        if che > che_dom:
            # ★[7/2 큰수익 되돌림 방어] 매수우위라도 큰상승(+BIGRUN_TP%) 후 고점서 BIGRUN_TRAIL% 되밀리면 매도(반납 방지).
            _btp = float(p.get("bigrun_tp", BIGRUN_TP)); _btr = float(p.get("bigrun_trail", BIGRUN_TRAIL))
            if _btp > 0 and entry and peak and (peak / entry - 1) * 100 >= _btp and cur <= peak * (1 - _btr / 100.0):
                return True, f"큰수익되돌림(고점-{_btr:g}%)"
            return False, "매수우위=끌기"             # ★체결강도 살아있으면 계속 홀드(끌고 올라감)
        if ma5 > 0 and cur < ma5:
            return True, "매도우위+5일선이탈"
        if peak and (cur / peak - 1) * 100 <= -pkdrop:
            return True, f"매도우위+고점-{pkdrop:g}%"
        if have_bars and c < o and o > 0 and (o - c) / o * 100 >= bigred:
            return True, f"매도우위+장대음봉{(o-c)/o*100:.1f}%"
        # ★[7/2 과민완화] 최근 LOWBREAK_N봉 최저를 버퍼%만큼 확실히 깨야 매도(직전봉 1틱 이탈 노이즈 제거).
        if have_bars:
            lb_n = int(p.get("lowbreak_n", LOWBREAK_N)); lb_buf = float(p.get("lowbreak_buf", LOWBREAK_BUF))
            low_ref = min(b[2] for b in bars[-1 - lb_n:-1]) if len(bars) > lb_n else prev_l
            if cur < low_ref * (1 - lb_buf / 100.0):
                return True, "매도우위+저점이탈"
        return False, None
    # 3. 체결강도 없을 때만 → 고정 트레일 백스톱(하이브리드=넓게·아니면 기본). 빨간봉마다 컷 안함.
    bt = float(p.get("hybrid_trail", HYBRID_TRAIL)) if (HYBRID and ma20_hard) else trail
    if peak and entry and (peak / entry - 1) * 100 >= trail_arm and cur <= peak * (1 - bt / 100):
        return True, f"트레일(고점-{bt:g}%·체결강도없음)"
    return False, "체결강도없음→홀드"


def partial_tp(entry, cur, qty, trimmed, params=None):
    """[7/2 부분익절 친구님 #3] 반환 (부분익절할까:bool, 매도수량:int).
       조건: 아직 안했고(trimmed=False)·수량≥2(나눠짐)·수익≥PARTIAL_TP%. 30만 1주(qty<2)면 (False,0)=무동작.
       ★전량매도(vol_exit.decide)와 별개 — 호출측이 이걸 먼저 확인해 절반 매도 후 나머지는 decide로 관리."""
    p = params or {}
    tp = float(p.get("partial_tp", PARTIAL_TP)); ratio = float(p.get("partial_ratio", PARTIAL_RATIO))
    try:
        qty = int(float(qty or 0)); entry = float(entry or 0); cur = float(cur or 0)
    except Exception:
        return False, 0
    if trimmed or tp <= 0 or qty < 2 or entry <= 0 or cur <= 0:
        return False, 0
    if (cur / entry - 1) * 100 < tp:
        return False, 0
    sell_qty = max(1, int(qty * ratio))
    if sell_qty >= qty:                      # 전량이 되면 부분익절 의미없음(전량은 decide가 담당)
        return False, 0
    return True, sell_qty


def do_partial(p, cur, order_fn, rt_open_path=None, log_fn=None, params=None):
    """[7/2 #3] 부분익절 실행 원스톱: 판정→절반매도(order_fn)→p['qty']감소·p['trimmed']=True·rt_open qty동기.
       order_fn(qty:int, tag:str)->bool. 각 엔진 manage에서 decide 전에 1줄 호출. 무동작/예외=False(fail-safe).
       ※30만 1주(qty<2)면 partial_tp가 (False,0) → 자동 무동작. 1억(수량많음)서만 실효."""
    try:
        if p.get("trimmed"):
            return False
        buy = float(p.get("buy_price", 0) or 0); qty = int(float(p.get("qty", 0) or 0))
        dt, sq = partial_tp(buy, cur, qty, False, params)
        if not dt:
            return False
        if not order_fn(sq, "부분익절"):
            return False
        p["qty"] = qty - sq; p["trimmed"] = True
        if rt_open_path:
            try:
                import json, os as _os
                rt = json.loads(open(str(rt_open_path), encoding="utf-8").read())
                code = str(p.get("code", ""))
                if code in rt and isinstance(rt[code], dict):
                    rt[code]["qty"] = p["qty"]
                    tmp = str(rt_open_path) + ".tmp"
                    open(tmp, "w", encoding="utf-8").write(json.dumps(rt, ensure_ascii=False))
                    _os.replace(tmp, str(rt_open_path))
            except Exception:
                pass
        if log_fn:
            log_fn(f"★부분익절 {p.get('code')} {sq}주 @{cur:,.0f} (+{(cur/buy-1)*100:.1f}%)·잔여 {p['qty']}주 끌기")
        return True
    except Exception:
        return False


if __name__ == "__main__":
    # 자가검증: 20선 이탈 무조건 / 매수우위 보유 / 매도우위 매도 (실데이터 code 인자)
    import sys
    c = sys.argv[1] if len(sys.argv) > 1 else "005930"
    print("recent_bars:", _recent_bars(c, 7)[-3:])
    print("che:", _che(c), " ma5/ma20:", _ma(c))
    print("decide(trend):", decide(c, 1000, 1050, 1020, ma20_hard=True))
    print("decide(deepV) :", decide(c, 1000, 1050, 1020, ma20_hard=False))
