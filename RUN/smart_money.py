# -*- coding: utf-8 -*-
"""[2026-07-06 친구님 "기관/외국인/프로그램 던지기는 피한다·전 전략에·실시간으로"]
★공용 스마트머니 던지기 감지 — 전 매수전략 공통 게이트.
  che 매수세여도 큰손(기관/외국인/프로그램)이 대량 순매도(던짐)면 = 세력 분산매도 함정 → 매수차단.

★3주체 실시간(진입 순간 온디맨드 조회·백만원 단위):
  ① 기관계 : opt10059 종목별투자자 기관계 (★일자 채워야 나옴·연기금/투신/금융투자/사모 세분도 있음)
  ② 외국인 : opt10059 외국인투자자 (같은 TR·한 번에)
  ③ 프로그램: opt90013 오늘 프로그램순매수금액 (누적)
  ④ 호가imb: live_micro_snapshot(REAL_MICRO 실시간 틱) 매도/매수벽 — 지금 던지는 중인지 (기록·규약검증 후 차단)

사용:  import smart_money
       blocked, info = smart_money.dumping(bc, code, price)   # price는 하위호환용(현재 미사용)
       if blocked: continue   # 이 종목 매수 스킵

안전: SMART_MONEY_MODE=BLOCK(기본)/LOG/OFF. 데이터 조회 실패시 fail-open(차단 안 함).
     60초 캐시(TR부하 최소). 3주체 중 하나라도 대량순매도(≤임계·백만원)면 던짐.
검증(7/6 opt10059 실측 심텍): 외국인−26,836·프로그램−24,964 던짐 / 기관+13,588(연기금+7,703·투신+5,549)은 매수.
"""
import os
import time
import json
from pathlib import Path
from datetime import datetime

MODE      = os.environ.get("SMART_MONEY_MODE", "BLOCK").strip().upper()      # OFF / LOG / BLOCK
INST_TH   = float(os.environ.get("SM_INST_TH", "-8000"))                     # 기관계 순매도(백만원) 이하=던짐 (기본 -80억)
FRGN_TH   = float(os.environ.get("SM_FRGN_TH", "-8000"))                     # 외국인 순매도(백만원)
PROG_TH   = float(os.environ.get("SM_PROG_TH", "-10000"))                    # 프로그램 순매도(백만원) (기본 -100억)
INDIV_TH  = float(os.environ.get("SM_INDIV_TH", "5000"))                     # ★[7/6] 개인 순매수(백만원)≥이값 + 세력(기관+외인) 순매도 = "세력→개미 넘김" 차단 (기본 +50억)
IMB_BLOCK = os.environ.get("SM_IMB_BLOCK", "NO").strip().upper() == "YES"    # 호가 imb 하드차단(기본 OFF·규약검증 후)·기록은 항상
IMB_TH    = float(os.environ.get("SM_IMB_TH", "0"))
TTL       = float(os.environ.get("SM_TTL", "60"))                           # 캐시 초
SNAP      = Path(r"C:\stock_bot\IPC\live_micro_snapshot.json")
_CACHE    = {}


def _num(x):
    try:
        return float(str(x).replace(",", "").replace("+", "").strip() or 0)
    except Exception:
        return 0.0


def probe(bc, code, price=0):
    """실시간 수급 조회 → (inst, frgn, prog, indiv, imb). inst/frgn/prog/indiv=백만원 순매수(음수=순매도). 60s 캐시. 실패항목 None."""
    code = str(code).zfill(6)
    e = _CACHE.get(code)
    if e and (time.time() - e[0] < TTL):
        return e[1]
    inst = frgn = prog = indiv = imb = None
    today = datetime.now().strftime("%Y%m%d")
    # ①②③ 기관계 + 외국인 + 개인 (opt10059·★일자 채움·백만원)
    try:
        r = bc.tr("opt10059", inputs={"일자": today, "종목코드": code, "금액수량구분": "1", "매매구분": "0", "단위구분": "1"},
                  output_fields=["기관계", "외국인투자자", "개인투자자"], timeout_sec=5.0, screen_no="9740")
        recs = ((r or {}).get("data") or {}).get("records") or []
        if recs and str(recs[0].get("기관계", "")).strip():
            inst = _num(recs[0].get("기관계"))
            frgn = _num(recs[0].get("외국인투자자"))
            indiv = _num(recs[0].get("개인투자자"))
    except Exception:
        pass
    # ③ 프로그램 (opt90013 오늘 누적·백만원)
    try:
        r = bc.tr("opt90013", inputs={"시간일자구분": "1", "금액수량구분": "1", "종목코드": code},
                  output_fields=["일자", "프로그램순매수금액"], timeout_sec=5.0, screen_no="9741")
        recs = ((r or {}).get("data") or {}).get("records") or []
        for d in recs:
            if str(d.get("일자")) == today:
                prog = _num(d.get("프로그램순매수금액"))
                break
    except Exception:
        pass
    # ④ 호가 imb (실시간 구독 스냅)
    try:
        sd = (json.loads(SNAP.read_text(encoding="utf-8-sig")).get("codes", {}) or {}).get(code) or {}
        v = sd.get("imb")
        imb = float(v) if isinstance(v, (int, float)) else None
    except Exception:
        pass
    res = (inst, frgn, prog, indiv, imb)
    _CACHE[code] = (time.time(), res)
    return res


def dumping(bc, code, price=0):
    """(blocked, info). 기관 or 외국인 or 프로그램 대량순매도 OR '세력 순매도+개미 대량흡수' 면 던짐.
       MODE=OFF면 (False,''). MODE=LOG면 판정하되 blocked=False. fail-open: 데이터 없으면 차단 안 함."""
    if MODE == "OFF":
        return (False, "")
    try:
        inst, frgn, prog, indiv, imb = probe(bc, code, price)
    except Exception:
        return (False, "수급조회실패")
    i_dump = inst is not None and inst <= INST_TH
    f_dump = frgn is not None and frgn <= FRGN_TH
    p_dump = prog is not None and prog <= PROG_TH
    i_imb = IMB_BLOCK and imb is not None and imb <= IMB_TH
    # ★[7/6] 세력→개미 넘김: 개인이 대량 매수(≥INDIV_TH) + 세력(기관+외인) 순매도 = 개미가 물량 받는 중 = 피함
    _force = ((inst or 0) + (frgn or 0)) if (inst is not None or frgn is not None) else 0
    r_absorb = (indiv is not None and indiv >= INDIV_TH and _force < 0)
    dump = i_dump or f_dump or p_dump or i_imb or r_absorb
    why = []
    if i_dump:
        why.append(f"기관{inst / 100:.0f}억")
    if f_dump:
        why.append(f"외국인{frgn / 100:.0f}억")
    if p_dump:
        why.append(f"프로그램{prog / 100:.0f}억")
    if r_absorb:
        why.append(f"개미흡수{indiv / 100:.0f}억(세력{_force / 100:.0f})")
    if i_imb:
        why.append(f"호가imb{imb}")
    if why:
        info = "던짐:" + "·".join(why)
    elif inst is not None or prog is not None:
        info = f"기관{(inst or 0) / 100:+.0f}·외인{(frgn or 0) / 100:+.0f}·개인{(indiv or 0) / 100:+.0f}·프로그램{(prog or 0) / 100:+.0f}억"
    else:
        info = "수급NA"
    blocked = dump and MODE == "BLOCK"
    return (blocked, info)


if __name__ == "__main__":
    import sys
    sys.path.insert(0, r"C:\stock_bot\RUN")
    from broker_client import BrokerClient
    bc = BrokerClient()
    for c in ["222800", "310210", "036930"]:
        print(c, dumping(bc, c))
