# -*- coding: utf-8 -*-
"""[대장주 우선 필터 2026-06-30 친구님 "대장주는 안 사고 잡주를 48개나 샀다"]
   거래대금 상위 N위(코스닥) = 대장주 universe. opt10032(거래대금상위요청) 레코드 순서 = 거래대금 내림차순.
   is_leader(bc, code) = 거래대금 상위 LEADER_TOP_N 안에 들면 True → 매수 허용. 밖이면 소형주로 보고 차단.
   ★소형주 제한 + 대장주 우선을 한 게이트로 처리(거래대금 상위 = 자연히 대형·유동 풍부).
   ★fail-open: opt10032 조회 실패/데이터없음/broker없음이면 True(거래 안 막음)·중앙 잡주게이트가 별도 안전망.
   env: LEADER_FILTER=YES(켜기) · LEADER_TOP_N=60 · LEADER_CACHE_SEC=120. 끄기 setx LEADER_FILTER NO.
   brk_realtime·golden_cross 두 매수엔진에서만 호출(다른 전략 무영향)."""
import os, time, json
from pathlib import Path
from datetime import datetime, timedelta

ENABLED   = os.environ.get("LEADER_FILTER", "YES").strip().upper() == "YES"
TOP_N     = int(os.environ.get("LEADER_TOP_N", "60"))
CACHE_SEC = int(os.environ.get("LEADER_CACHE_SEC", "120"))

# ★[2026-07-01 친구님] 전날 종가 기준 '대장주 순위표'(daily_leader_board_v1) 우선 참조.
#   장중 실시간 opt10032 대신 아침에 고정된 순위표를 봄 → 9시 정각부터 브로커 없이 대장 판정.
#   순위표 없거나 오래되면(스케줄 실패) 기존 실시간 opt10032 로 자동 폴백.
USE_BOARD   = os.environ.get("LEADER_USE_BOARD", "YES").strip().upper() == "YES"
BOARD_FILE  = Path(r"C:\stock_bot\data\daily_leader_board.json")
BOARD_MAXAGE_DAYS = int(os.environ.get("LEADER_BOARD_MAXAGE_DAYS", "5"))  # 기준일이 이보다 오래되면 폴백
# ★[2026-07-01 실시간 갱신] 매수 판정 대장 = 아침 순위표 ∪ 오늘 실시간 거래대금 대장.
#   오늘 새로 뜬 대장(어제 순위표엔 없던)도 매수 허용. 롤백 setx LEADER_LIVE_MERGE NO
LIVE_MERGE  = os.environ.get("LEADER_LIVE_MERGE", "YES").strip().upper() == "YES"
LIVE_TOP_N  = int(os.environ.get("LEADER_LIVE_TOP_N", "60"))       # 실시간 거래대금 상위 N 을 대장에 합침
# ★[2026-07-01 점수 우선순위] 순위표에 점수 있으면 그 점수, 없으면(실시간 대장) 이 기본값
LIVE_DEFAULT_PRIORITY = float(os.environ.get("LEADER_LIVE_DEFAULT_PRIORITY", "50"))

_codes = None     # 거래대금 내림차순 코드 리스트(상위 TOP_N)
_ts = 0.0
_board = None
_board_mtime = 0.0


def _z(c):
    return str(c).lstrip("A").zfill(6)


def _load_board():
    """daily_leader_board.json 로드(파일 mtime 캐시). 기준일이 너무 오래되면 None."""
    global _board, _board_mtime
    try:
        m = BOARD_FILE.stat().st_mtime
        if _board is None or m != _board_mtime:
            _board = json.loads(BOARD_FILE.read_text(encoding="utf-8"))
            _board_mtime = m
        # 기준일 신선도 체크(스케줄 죽어 오래된 표 방지)
        d = str((_board or {}).get("date", ""))
        if len(d) == 8:
            age = (datetime.now() - datetime.strptime(d, "%Y%m%d")).days
            if age > BOARD_MAXAGE_DAYS:
                return None
        return _board
    except Exception:
        return None


def board_codes():
    """순위표 대장 코드 리스트(거래대금 순). 없음/오래됨=None."""
    b = _load_board()
    if not b:
        return None
    codes = b.get("codes_by_value") or b.get("codes") or []
    out = [_z(c) for c in codes if len(_z(c)) == 6]
    return out or None


def scalp_rank(code):
    """단타 점수 등수(1=최상). 순위표에 없으면 None."""
    b = _load_board()
    if not b:
        return None
    c = _z(code)
    for row in b.get("board", []):
        if _z(row.get("code", "")) == c:
            return int(row.get("scalp_rank", 0)) or None
    return None


LIVE_FILE = Path(r"C:\stock_bot\data\live_leaders.json")   # 실시간 대장 공유(브로커 없는 엔진용)
LIVE_FILE_MAXAGE_SEC = int(os.environ.get("LEADER_LIVE_FILE_MAXAGE", "900"))  # 15분 넘으면 무시


def _live_codes(bc):
    """오늘 실시간 거래대금 상위 LIVE_TOP_N 코스닥(opt10032). 실패=None. CACHE_SEC 캐시.
       성공 시 live_leaders.json 에 기록 → 브로커 없는 엔진(눌림 등)도 실시간 층 공유."""
    global _codes, _ts
    now = time.time()
    if _codes is not None and (now - _ts) < CACHE_SEC:
        return _codes
    if bc is None:
        return None
    try:
        res = bc.tr("opt10032", inputs={"시장구분": "101", "관리종목포함": "0"},
                    output_fields=["종목코드", "종목명", "거래대금"], screen_no="9719", timeout_sec=8.0)
        recs = (((res or {}).get("data") or {}).get("records") or [])
        out = []
        for r in recs:                          # opt10032 레코드 = 거래대금 내림차순
            c = _z(str(r.get("종목코드", "")))
            if len(c) == 6 and c not in out:
                out.append(c)
        if not out:
            return None
        _codes = out[:LIVE_TOP_N]
        _ts = now
        try:                                     # 실시간 대장 파일 공유(best-effort)
            tmp = LIVE_FILE.with_suffix(".json.tmp")
            tmp.write_text(json.dumps({"ts": now, "codes": _codes}, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, LIVE_FILE)
        except Exception:
            pass
        return _codes
    except Exception:
        return None


def _live_file_codes():
    """live_leaders.json 의 실시간 대장(브로커 없는 엔진용). 오래되면(>MAXAGE) None."""
    try:
        d = json.loads(LIVE_FILE.read_text(encoding="utf-8"))
        if (time.time() - float(d.get("ts", 0))) > LIVE_FILE_MAXAGE_SEC:
            return None
        out = [_z(c) for c in (d.get("codes") or []) if len(_z(c)) == 6]
        return out or None
    except Exception:
        return None


def leader_list(bc):
    """대장주 코드(정렬 리스트). ①전날 종가 순위표 우선 ②없으면 실시간 opt10032 폴백.
       실패/없음=None(판정불가·fail-open). board 는 거래대금 100억+ 전체 인정(친구님 "100등까지")."""
    if USE_BOARD:
        bl = board_codes()
        if bl:
            return bl
    return _live_codes(bc)


def leader_set(bc):
    """★매수 판정용 대장 집합 = 아침 순위표 ∪ 오늘 실시간 거래대금 대장(LIVE_MERGE).
       실시간 층이 있어 오늘 새로 뜬 대장도 매수 허용. 둘 다 없으면 None(fail-open).
       브로커 있으면 opt10032 직접, 없으면 live_leaders.json(다른 엔진이 갱신) 사용."""
    s = set()
    bl = board_codes()
    if bl:
        s.update(bl)
    if LIVE_MERGE:
        lv = _live_codes(bc) if bc is not None else _live_file_codes()
        if lv:
            s.update(lv)
    if not s:                              # 순위표 없음(스케줄 실패) → 실시간만이라도
        lv = _live_codes(bc) if bc is not None else _live_file_codes()
        if lv:
            s.update(lv)
    return s or None


def is_leader(bc, code):
    """대장(아침 순위표 ∪ 실시간 거래대금 대장) 안이면 True.
       필터OFF/데이터없음/broker없음=True(fail-open=거래 안 막음)."""
    if not ENABLED:
        return True
    s = leader_set(bc)
    if not s:
        return True            # fail-open
    return _z(code) in s


def scalp_score(code):
    """단타 점수(0~100). 순위표에 있으면 그 점수, 없으면 None."""
    b = _load_board()
    if not b:
        return None
    c = _z(code)
    for row in b.get("board", []):
        if _z(row.get("code", "")) == c:
            return float(row.get("scalp_score", 0.0))
    return None


def priority(code):
    """★매수 우선순위 점수(높을수록 먼저). 아침 순위표 단타점수 우선,
       없으면(오늘 실시간만 대장) LIVE_DEFAULT_PRIORITY. 여러 후보 정렬용."""
    s = scalp_score(code)
    return s if s is not None else LIVE_DEFAULT_PRIORITY


def eod_score(code):
    """종가매수 점수(0~100·마감강도·상승·우상향 중심). 순위표에 없으면 None."""
    b = _load_board()
    if not b:
        return None
    c = _z(code)
    for row in b.get("board", []):
        if _z(row.get("code", "")) == c:
            v = row.get("eod_score")
            return None if v is None else float(v)
    return None


def eod_priority(code):
    """종가매수 우선순위(높을수록 먼저). 순위표 종가점수 우선, 없으면 LIVE_DEFAULT_PRIORITY."""
    s = eod_score(code)
    return s if s is not None else LIVE_DEFAULT_PRIORITY


def rank_of(bc, code):
    """거래대금 순위(1=최상위). 없으면 None(디버그/로그용)."""
    lst = leader_list(bc)
    if not lst:
        return None
    c = _z(code)
    return (lst.index(c) + 1) if c in lst else None


if __name__ == "__main__":
    import sys, io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    sys.path.insert(0, r"C:\stock_bot\RUN")
    print("LEADER_FILTER =", ENABLED, "· TOP_N =", TOP_N, "· CACHE_SEC =", CACHE_SEC)
    try:
        from broker_client import BrokerClient, is_broker_alive
        bc = BrokerClient() if is_broker_alive() else None
    except Exception as e:
        bc = None; print("broker 연결 실패:", e)
    lst = leader_list(bc)
    if lst is None:
        print("거래대금 상위 조회 실패/데이터없음 → fail-open(전부 허용)")
    else:
        print(f"거래대금 상위 {len(lst)}종목(대장주 set):")
        print("  ", ", ".join(lst[:30]))
        for c in ["222800", "254120", "153890", "036930"]:
            print(f"  {c}: is_leader={is_leader(bc, c)} rank={rank_of(bc, c)}")
