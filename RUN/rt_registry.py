# -*- coding: utf-8 -*-
"""
[rt_registry 2026-07-05] 공용 실보유 장부(rt_open_positions.json) 등록/제거 헬퍼.

배경(7/5 사전점검): 3형제(바닥·돌파·눌림사냥꾼)가 매수를 rt_open에 등록하지 않아
  ①같은 분(0~2분 창)에 다른 엔진이 같은 종목을 중복매수 가능
  ②전역 200만한도·일일상한 집계가 계좌대조(2분 주기) 시차만큼 늦게 잡히는 구멍.
계좌대조(reconcile --write·2분)가 결국 실계좌 진실로 rt_open을 덮어쓰므로,
이 등록은 그 시차를 없애는 "선반영"이다(장부의 주인은 여전히 계좌대조).

원칙:
  ①실주문일 때만 호출(그림자/페이퍼는 등록 금지 — 호출측에서 live 확인)
  ②어떤 실패도 엔진을 죽이지 않음(전부 삼키고 False)
  ③임시파일→원자교체(os.replace)로 동시쓰기에도 파일 안 깨짐
  ④끄기 = setx RT_REGISTRY NO (기본 YES·롤백 한 줄)

사용: import rt_registry as RT
  매수 성공 직후: RT.register(code, qty, 체결가, "BRKUNI")
  전량매도 직후: RT.remove(code)
"""
import json, os

RT_OPEN = r"C:\stock_bot\data\rt_open_positions.json"
_ON = os.environ.get("RT_REGISTRY", "YES").strip().upper() == "YES"


def _load():
    try:
        with open(RT_OPEN, encoding="utf-8-sig") as f:
            d = json.loads(f.read())
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _save(d):
    tmp = RT_OPEN + ".tmp_reg"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(json.dumps(d, ensure_ascii=False))
    os.replace(tmp, RT_OPEN)


def register(code, qty, entry_price, strategy, peak_price=None):
    """매수 성공 직후 호출(실주문만). 성공 True / 실패·꺼짐 False(무해)."""
    if not _ON:
        return False
    try:
        code = str(code).zfill(6)
        d = _load()
        d[code] = {"qty": int(qty), "entry_price": float(entry_price), "code": code,
                   "strategy": str(strategy), "peak_price": float(peak_price or entry_price)}
        _save(d)
        return True
    except Exception:
        return False


def remove(code):
    """전량매도 성공 직후 호출. 항목 없어도/실패해도 False(무해)."""
    if not _ON:
        return False
    try:
        code = str(code).zfill(6)
        d = _load()
        if code in d:
            d.pop(code, None)
            _save(d)
        return True
    except Exception:
        return False
