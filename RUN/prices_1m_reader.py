# -*- coding: utf-8 -*-
# [CENTRAL-1M 2026-06-24] ★중앙 1분봉 공유 — 돌파/NEW_PB/신고가 스캐너가 opt10080 직접호출 대신 이 모듈로 DATA/prices_1m.csv를 읽음.
#   친구님 지시: opt10080 직접호출은 collect_prices_1m 한 곳만. 나머지는 파일읽기. 해상도(1분봉) 그대로·매수로직 무수정(데이터 출처만 교체).
#   반환 형식 = 기존 _gate_bars/_today_bars 와 동일: [(hm, o, h, l, c, v)] (오늘분·시각오름차순·정수).
#   mtime 캐시: 한 사이클에 파일 1회만 파싱(여러 종목 조회해도 빠름). 검증로그: 최신봉 age·종목별 bar_count·누락.
import os, csv, time, json
from datetime import datetime

PRICES_1M = r"C:\stock_bot\DATA\prices_1m.csv"
SNAPSHOT  = r"C:\stock_bot\IPC\live_micro_snapshot.json"   # [LOCKMSG 2026-06-25] 상한가잠김 판별용(ask_tot)

_cache = {"mtime": -1.0, "day": "", "data": {}}   # code -> [(hm,o,h,l,c,v)]
_miss_log = {}                                     # code -> last miss log epoch (스로틀)
_snap_cache = {"mtime": -1.0, "codes": {}}         # [LOCKMSG] 실시간 호가 스냅샷 캐시(mtime 1회 파싱)


def _is_locked_up(code):
    """[LOCKMSG 2026-06-25] 상한가 잠김(매도총잔량 0)인지. True=잠김(단일가봉이라 수집기가 정상 거부).
    스냅샷 없음/판별불가 → None(원인 미상, 기존 '누락의심' 메시지). 실패→None(fail-safe)."""
    try:
        mt = os.path.getmtime(SNAPSHOT)
    except Exception:
        return None
    if mt != _snap_cache["mtime"]:
        try:
            with open(SNAPSHOT, encoding="utf-8-sig") as f:
                _snap_cache["codes"] = (json.load(f).get("codes") or {})
            _snap_cache["mtime"] = mt
        except Exception:
            return None
    v = _snap_cache["codes"].get(str(code).zfill(6))
    if not isinstance(v, dict):
        return None
    ask = v.get("ask_tot")
    bid = v.get("bid_tot")
    if ask is None:
        return None
    # 매도잔량 0 + 매수잔량 존재 = 상한가 잠김(매도호가 비어 단일가). 하한가/거래정지와 구분.
    return (float(ask) == 0.0) and (bid is not None and float(bid) > 0.0)


def _parse_all():
    """DATA/prices_1m.csv 전체를 오늘분만 code별 1분봉 dict로. mtime 동일하면 캐시 재사용."""
    today = datetime.now().strftime("%Y%m%d")
    try:
        mt = os.path.getmtime(PRICES_1M)
    except Exception:
        return {}
    if mt == _cache["mtime"] and _cache["day"] == today:
        return _cache["data"]
    bycode = {}
    try:
        with open(PRICES_1M, encoding="utf-8-sig", newline="") as f:
            r = csv.reader(f)
            header = next(r, None)
            if not header:
                return _cache["data"]
            ix = {h: i for i, h in enumerate(header)}
            ci, ti = ix.get("code"), ix.get("ts")
            oi, hi, li, cli, vi = ix.get("open"), ix.get("high"), ix.get("low"), ix.get("close"), ix.get("volume")
            if None in (ci, ti, oi, hi, li, cli, vi):
                return _cache["data"]
            for row in r:
                if len(row) <= vi:
                    continue
                ts = row[ti]
                if not ts.startswith(today):
                    continue
                try:
                    bar = (ts[8:12],
                           int(float(row[oi])), int(float(row[hi])), int(float(row[li])),
                           int(float(row[cli])), int(float(row[vi])))
                except Exception:
                    continue
                bycode.setdefault(row[ci], []).append(bar)
    except Exception:
        return _cache["data"]
    for c in bycode:
        bycode[c].sort()
    _cache.update({"mtime": mt, "day": today, "data": bycode})
    return bycode


def bars(code, log=None, tag=""):
    """code의 오늘 1분봉 [(hm,o,h,l,c,v)] 반환. 없으면 [](누락). log 주면 누락/age 경고 기록."""
    code = str(code).zfill(6)
    out = _parse_all().get(code, [])
    if not out and log is not None:
        now = time.time()
        if now - _miss_log.get(code, 0) > 60:   # 종목당 60s 스로틀
            _miss_log[code] = now
            try:
                # [LOCKMSG 2026-06-25] 상한가잠김(매도0)은 단일가봉이라 is_valid_bar가 정상 거부 → 0줄.
                #   '수집기 누락'이 아니라 '못 사는 잠긴 종목'이므로 메시지 분기(오경보 제거).
                if _is_locked_up(code):
                    log(f"[CENTRAL-1M] {tag} {code} 0봉 — 상한가잠김(매도0)·단일가봉 정상거부(수집정상, 매수불가)")
                else:
                    log(f"[CENTRAL-1M] {tag} {code} 미수집(prices_1m.csv에 없음) — 수집기 universe 누락 의심")
            except Exception:
                pass
    return out


def latest_age_sec():
    """파일 내 가장 최신 봉의 age(초). 데이터 없으면 None. (검증: 최신봉 age 정상 확인용)"""
    d = _parse_all()
    if not d:
        return None
    last_hm = None
    for v in d.values():
        if v:
            hm = v[-1][0]
            if last_hm is None or hm > last_hm:
                last_hm = hm
    if last_hm is None:
        return None
    try:
        now = datetime.now()
        bar_t = now.replace(hour=int(last_hm[:2]), minute=int(last_hm[2:]), second=0, microsecond=0)
        return (now - bar_t).total_seconds()
    except Exception:
        return None


def coverage():
    """(종목수, 종목별 bar_count dict) — 검증용."""
    d = _parse_all()
    return len(d), {c: len(v) for c, v in d.items()}
