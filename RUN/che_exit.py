# -*- coding: utf-8 -*-
"""[친구님 2026-06-28] ★공통 체결강도 매도 판단 — 전 전략 통합(눌림/돌파/깊은V/MBB/스윙).
친구님 "체결강도로 매도 타이밍 잡을수 있으면 눌림이든 돌파든 다 적용해야 제대로 매도".
원본=NEW_PB의 검증된 CHE_EXIT(2026-06-25) 로직을 순수함수로 추출·파라미터화.

원리(전 전략 공통): 체결강도 강하면 끌고(더먹기)·약해지거나 급락(전분대비 X%↓)하면 빠진다.
  우선순위 ①하드손절 ②+TP만족(강→타이트끌기/약·급락→즉시익절) ③되밀림(강=넓게/약=타이트).
전략차이는 params로 흡수(깊은V 단타=타이트, 돌파 runner=넓게, 스윙=아주 느슨).
fail-safe: che=None(데이터없음)이면 강/급락판정 안함(약으로 취급=보수적). 호출측이 기존 폴백 유지.

순수함수 — 파일/주문 부작용 없음. 반환만. 호출측이 주문·기록."""
import os


def default_params(strategy="GENERIC"):
    """전략별 기본 파라미터. env로 덮어쓸 수 있게 호출측에서 조정."""
    base = {
        "hard_pct": 5.0,        # 하드손절 -%
        "tp_cap": 10.0,         # 이 수익%↑면 '만족구간'(강→끌기/약→익절)
        "che_strong": 120.0,    # 이 체결강도↑ = 강(끌기)
        "retr_wide": 4.0,       # 강일때 되밀림 허용폭(고점-%)
        "retr_tight": 1.5,      # 약일때 되밀림 허용폭(고점-%)
        "retr_arm": 1.0,        # 고점이익 이%↑부터 되밀림 트레일 작동
        "che_drop_frac": 0.35,  # 전분대비 이비율↓ = 급락(매수세 꺾임)
    }
    s = (strategy or "").upper()
    if s == "DEEPV":            # 깊은V=아침 단타·빨리먹고빠짐
        base.update(tp_cap=5.0, che_strong=115.0, retr_wide=3.0, retr_tight=1.2)
    elif s == "MBB":            # 베이스돌파=단기·단계트레일 대체
        base.update(tp_cap=10.0, che_strong=120.0, retr_wide=4.0, retr_tight=1.5)
    elif s == "BREAKOUT":       # 돌파 runner=강하면 끝까지
        base.update(tp_cap=10.0, che_strong=100.0, retr_wide=6.0, retr_tight=2.0)
    elif s == "SWING":          # ★스윙=며칠보유·분단위노이즈에 일찍 안팔게 아주 느슨(나중 튜닝)
        base.update(tp_cap=20.0, che_strong=130.0, retr_wide=10.0, retr_tight=5.0,
                    retr_arm=5.0, che_drop_frac=0.5)
    return base


def decide(cur, buy, peak, pnl, che, che_prev, p, bar=None, ma5=0.0, ma20=0.0):
    """체결강도 기반 매도 판단. NEW_PB CHE_EXIT 일반화.
    cur=현재가 buy=매수가 peak=고점 pnl=수익% che=현재체결강도(None가능) che_prev=직전체결강도 p=params.
    bar=(o,h,l,c) 현재 1분봉(있을때만)·p['wick_min']>0이면 음봉+긴윗꼬리=천장반전 매도(2026-06-29 친구님).
    반환 (sell:bool, reason:str|None, tag:str, drop:bool, strong:bool)."""
    if buy <= 0:
        return False, None, "", False, False
    ppk = (peak / buy - 1) * 100
    hard_line = buy * (1 - p["hard_pct"] / 100)

    drop = False
    if che is not None and che_prev:
        try:
            if che <= float(che_prev) * (1 - p["che_drop_frac"]):
                drop = True
        except (TypeError, ValueError):
            pass
    strong = (che is not None and che >= p["che_strong"]) and not drop

    # [2026-06-29 친구님] 음봉(종가<시가)+긴윗꼬리(고가 거부)=천장 반전 → 매도. p['wick_min']>0이고 bar 있을때만.
    wick_sell = False; wick_r = 0.0
    if bar and p.get("wick_min", 0) > 0:
        try:
            o, h, l, c = (float(x) for x in bar)
            rng = h - l
            if rng > 0:
                wick_r = (h - max(o, c)) / rng
                if c < o and wick_r >= p["wick_min"] and pnl >= p.get("wick_arm", 0.0):
                    wick_sell = True
        except (TypeError, ValueError):
            pass

    sell = False; reason = None; tag = ""
    # [MA-EXIT 공통 2026-06-29 친구님 "매도 전부 똑같이·5% 토함 싫어·고수 구조기반"] EXIT_MA_LAYER=YES + ma5/ma20 전달시:
    #   실제 평가순서: ①하드손절 → ①.3 20일선이탈(하드) → ①.4 5일선이탈+체결약 → ①.5 윗꼬리 → ②TP → ③되밀림.
    #   MA선은 가격이 그 아래로 깨졌을 때만 발화(상승 종목은 가격>MA라 ②③ 체결강도 로직이 지배=구조청산과 양립).
    #   ★ma5=ma20=0(deep_v 면제 등)이면 ma>0 가드로 MA층 전부 skip — 위 critical 안전속성.
    _ma_on = os.environ.get("EXIT_MA_LAYER", "NO").strip().upper() == "YES"
    # ① 하드손절(최우선)
    if cur <= hard_line:
        sell = True; reason = "STOP"; tag = f"하드-{p['hard_pct']:g}%"
    elif _ma_on and ma20 > 0 and cur < ma20:
        sell = True; reason = "STOP"; tag = "20일선이탈(하드)"
    elif _ma_on and ma5 > 0 and cur < ma5 and not strong:
        sell = True; reason = "TRAIL"; tag = "5일선이탈+추세깸"
    # ①.5 음봉+긴윗꼬리 천장반전(하드손절 다음 우선)
    elif wick_sell:
        sell = True; reason = "WICK"; tag = f"음봉+윗꼬리{wick_r*100:.0f}%·{pnl:+.0f}%"
    # ② +TP 만족구간
    elif pnl >= p["tp_cap"]:
        if strong:   # 강 → 끌되 타이트(조금 빠지면 익절)
            if cur <= peak * (1 - p["retr_tight"] / 100):
                sell = True; reason = "TP"; tag = f"+{ppk:.0f}%끌다익절·체결{che:.0f}강"
        else:        # 약/급락 → 만족하고 익절
            sell = True; reason = "TP"
            tag = (f"+{pnl:.0f}%만족·체결{che:.0f}약" if che is not None
                   else f"+{pnl:.0f}%만족") + ("·급락" if drop else "")
    # ③ 일반 되밀림(체결 게이트: 강=넓게·약=타이트)
    elif ppk > p["retr_arm"]:
        retr = p["retr_wide"] if strong else p["retr_tight"]
        if cur <= peak * (1 - retr / 100):
            sell = True; reason = "TRAIL"
            tag = (f"체결{che:.0f}{'강' if strong else '약'}" if che is not None
                   else "체결?") + ("·급락" if drop else "") + f"·고점-{retr:g}%"
    return sell, reason, tag, drop, strong


if __name__ == "__main__":
    # 자가검증: 강(끌기) vs 약(즉시익절) vs 급락
    P = default_params("DEEPV")
    print("DEEPV params:", P)
    # +6% 도달, 체결강 → 안팔고 끌기(고점근처)
    print("강·고점근처:", decide(106, 100, 106, 6.0, 130, 125, P))   # sell False(끌기)
    # +6% 도달, 체결약 → 즉시익절
    print("약·만족:", decide(106, 100, 106, 6.0, 80, 90, P))          # sell True TP
    # 체결 급락(125→70) → 약취급
    print("급락:", decide(104, 100, 107, 4.0, 70, 125, P))           # 되밀림 타이트
    # 하드손절
    print("하드손절:", decide(94, 100, 102, -6.0, 130, 130, P))       # sell True STOP
