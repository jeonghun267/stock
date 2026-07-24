# -*- coding: utf-8 -*-
"""[친구님 2026-06-28] ★거래원 외국계 수급 게이트 — 전 전략 공통 헬퍼. broker 호출0(그림자 CSV만 읽음).
친구님 "거래원 외국계 수급을 프로그램에 연결해줘".
소스: foreign_trader_shadow가 5분마다 쌓는 data/shadow/foreign_trader/ft_<date>.csv (종목별 최신 외국계 순매수).
판정: dumping = 외국계 순매도(fnet<0) AND 매도1위가 외국계 창구(fsell_flag=1) = 명백히 외국계가 던지는 중.
모드(env FOREIGN_GATE): OFF=미적용 · LOG=기록만(매수강행·검증) · BLOCK=매수보류. ★검증0이라 기본 LOG.
fail-safe: 데이터 없으면(후보가 거래원 관찰풀 밖·장외) not dumping=통과. broker 무관(파일만)."""
import csv, os
from datetime import datetime
from pathlib import Path

FT_DIR = Path(r"C:\stock_bot\data\shadow\foreign_trader")
_cache = {"date": None, "rows": {}, "mtime": 0}


def gate_mode():
    return os.environ.get("FOREIGN_GATE", "LOG").strip().upper()   # OFF / LOG / BLOCK


def _latest_rows():
    """종목별 최신 거래원 행. ft_<오늘>.csv mtime 캐시."""
    today = datetime.now().strftime("%Y%m%d")
    f = FT_DIR / f"ft_{today}.csv"
    try:
        mt = f.stat().st_mtime
    except OSError:
        return {}
    if _cache["date"] == today and _cache["mtime"] == mt:
        return _cache["rows"]
    out = {}
    try:
        with open(f, encoding="utf-8-sig") as fp:
            for row in csv.DictReader(fp):
                out[str(row.get("code", "")).zfill(6)] = row   # 뒤(최신)가 덮어씀
    except Exception:
        return _cache["rows"] if _cache["date"] == today else {}
    _cache.update(date=today, rows=out, mtime=mt)
    return out


def check(code):
    """(dumping:bool, fnet:int|None, info:str). 데이터없음=not dumping(통과)."""
    r = _latest_rows().get(str(code).zfill(6))
    if not r:
        return (False, None, "")
    try:
        fnet = int(float(r.get("fnet", 0) or 0))
        fsell_flag = int(r.get("fsell_flag", 0) or 0)
    except (ValueError, TypeError):
        return (False, None, "")

    def _opt(key):
        v = r.get(key, "")
        try:
            return int(float(v)) if str(v).strip() not in ("", "nan") else None
        except (ValueError, TypeError):
            return None
    inst = _opt("inst_net")   # 기관 순매수(opt10059 당일추정)
    frgn = _opt("frgn_net")   # 외국인 순매수(opt10059 당일추정)

    # ① 외국계 명백 던짐 = 외국계 순매도 + 매도1위 외국계 창구
    foreign_dump = (fnet < 0 and fsell_flag == 1)
    # ② 기관 게이트(친구님 "기관도 연결") = 기관+외국인 동반 순매도(양대 큰손 이탈)=명백할 때만(기관 단독은 흔해서 과차단).
    inst_gate_on = os.environ.get("FOREIGN_INST_GATE", "YES").strip().upper() == "YES"
    inst_dump = inst_gate_on and (inst is not None and inst < 0) and (frgn is not None and frgn < 0)
    dumping = foreign_dump or inst_dump

    why = []
    if foreign_dump: why.append("외국계던짐")
    if inst_dump: why.append("기관+외인동반순매도")
    info = (f"외국계fnet={fnet:+,}·매도1위외국계={fsell_flag}"
            + (f"·기관={inst:+,}" if inst is not None else "")
            + (f"·외인={frgn:+,}" if frgn is not None else "")
            + (f" [{'/'.join(why)}]" if why else ""))
    return (dumping, fnet, info)


def buy_gate(code, log=None, tag=""):
    """매수 직전 호출. 반환 True=매수진행 / False=보류(BLOCK에서 dumping시).
    LOG모드: dumping이어도 True(기록만). OFF: 항상 True."""
    mode = gate_mode()
    if mode == "OFF":
        return True
    dmp, fnet, info = check(code)
    if not dmp:
        return True
    if mode == "BLOCK":
        if log:
            log(f"{tag} {code} 외국계 매도우세({info}) → 매수보류[FOREIGN-BLOCK]")
        return False
    # LOG 모드
    if log:
        log(f"{tag} {code} ⚠외국계 매도중({info}) — 매수강행[FOREIGN-LOG·검증]")
    return True


if __name__ == "__main__":
    print("FOREIGN_GATE =", gate_mode())
    rows = _latest_rows()
    print(f"오늘 거래원 데이터 {len(rows)}종목")
    for c in list(rows)[:5]:
        print(" ", c, check(c))
