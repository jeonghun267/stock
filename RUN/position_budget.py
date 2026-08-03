# -*- coding: utf-8 -*-
"""[친구님 2026-06-28] ★전역 동시보유 예산 — 전 전략 합산 실보유가 상한 넘으면 신규매수 차단.
친구님 우려 해결: '자본 키우면(200만→1억) 한번에 너무 많이 사서 봇 무리·잡주까지 산다'.
  → 자본 증가는 '건당 캡(SAFEPLUS_CAP_KRW)'으로 흡수하고, '동시 종목 수'는 이걸로 상한(기본10).
  → 종목 수 상한 = 부하(보유감시) 천장 + 선별질 필터(상위 강한 신호만 채워짐).
원리: 실자본 쓰는 live=True OPEN만 카운트(페이퍼 제외 → 페이퍼가 실매매 막지않음, 실보유가 실신규를 막음).
      rt_open은 per-strategy 파일과 중복이라 스킵. 종목코드 합집합(중복제거)으로 카운트.
env: SAFEPLUS_GLOBAL_MAX_POS(기본10) · SAFEPLUS_GLOBAL_BUDGET(기본YES·NO면 비활성=기존동작).
★시간 reserve 없음(친구님: 당일회전이라 종가쯤 현금회수됨 → 현금잔고+이 상한이면 충분)."""
import os, json, time
from pathlib import Path
from datetime import datetime, timedelta

_D = Path(r"C:\stock_bot\DATA")
# 전략별 포지션 파일(live 필드 있음). rt_open은 중복이라 제외.
_FILES = [_D / "new_pb_positions.json", _D / "brk_positions.json", _D / "deepv_positions.json",
          _D / "mbb_positions.json", _D / "eod_gap_positions.json"]
_PICKUP = _D / "eod_pickup" / "rt_eod_pickup_positions.json"   # nested {date:{code:rec}} · live daemon
_RT_OPEN = _D / "rt_open_positions.json"   # [2026-06-30 친구님] 전 전략 통합 live 레지스트리(돌파/골든 포함·reconcile로 계좌동기) — 합집합 카운트


def global_max():
    # [2026-06-29 친구님 "개수는 레짐으로 조절 안함 — 금액(사이즈)로만"] 동시보유 개수는 레짐 무관 고정.
    #   레짐은 건당 사이즈(CAP)로만 조절(market_regime.cap_mult, 각 실행기 적용). 개수 차등 폐기(AI는 폭 살려야).
    try: return int(os.environ.get("SAFEPLUS_GLOBAL_MAX_POS", "10"))
    except ValueError: return 10


def budget_on():
    return os.environ.get("SAFEPLUS_GLOBAL_BUDGET", "YES").strip().upper() == "YES"


def budget_krw():
    """[2026-06-30 친구님 '200만 한도 안에서만 운영'] 전 전략 합산 보유원가 상한(원).
    0 = 비활성(개수 상한만). 예: 2000000 = 보유원가 합계 200만 넘으면 신규매수 차단."""
    try:
        return float(os.environ.get("SAFEPLUS_GLOBAL_BUDGET_KRW", "0") or 0)
    except ValueError:
        return 0.0


def daily_max():
    """[2026-07-02 친구님 과다매매 방지] 하루에 '서로 다른 종목'을 최대 몇 개까지 신규 진입할지 상한.
    0 = 비활성. 기존 상한(동시보유/노출액)은 '한 순간'만 제한 → 빨리 팔고 또 사면 하루 21종목까지 감(7/2 사건).
    이 상한은 '하루 누적 서로 다른 종목 수'를 제한 → 개장 직후 난장판 매매(over-trading) 차단.
    같은 종목 재매수는 각 엔진 자체 재매수금지가 담당(여긴 '서로 다른 종목 폭'만)."""
    try:
        return int(os.environ.get("SAFEPLUS_GLOBAL_DAILY_MAX", "0"))
    except ValueError:
        return 0


_DAILY_SEEN = _D / "daily_open_codes.json"


def daily_seen_count():
    """오늘 한 번이라도 보유(live OPEN)했던 서로 다른 종목 수. 현재 보유를 누적셋에 병합 후 반환.
    동시성: 여러 엔진이 호출 → 재시도 없이 합집합 저장이라, 경합으로 유실돼도 '과소집계'(permissive)뿐 = 안전.
    실패 시 예외 삼키고 현재 보유수만 반환(fail-open: 새 상한이 기존 매매흐름을 못 깨게)."""
    today = datetime.now().strftime("%Y%m%d")
    try:
        cur, _deg = _scan()
        seen = set(cur)
        d = _load(_DAILY_SEEN)
        if isinstance(d, dict) and d.get("date") == today:
            seen |= set(_z(c) for c in (d.get("codes") or []))
        try:
            tmp = _DAILY_SEEN.with_suffix(".tmp")
            tmp.write_text(json.dumps({"date": today, "codes": sorted(seen)}, ensure_ascii=False),
                           encoding="utf-8")
            os.replace(str(tmp), str(_DAILY_SEEN))
        except Exception:
            pass
        return len(seen)
    except Exception:
        return 0


def _load(p):
    """반환: dict=정상 · {}=파일없음(정상·흔함) · None=파일있는데 파싱실패(위험→보수처리).
    ★fail-safe: '없음'과 '못읽음'을 구분. 쓰기중 일시 잠김/half-write는 재시도로 흡수."""
    pth = Path(p)
    if not pth.exists():
        return {}
    for _ in range(3):                       # 전환윈도우(다른 프로세스 쓰기중) 흡수
        try:
            return json.loads(pth.read_text(encoding="utf-8"))
        except Exception:
            time.sleep(0.03)
    return None                              # 3회 재시도후도 실패 = 진짜 손상


def _z(c): return str(c).strip().zfill(6)


def _open(rec, assume_live=False):
    """status OPEN(기본) + qty>0 + (live=True or assume_live)."""
    if not isinstance(rec, dict): return False
    # ★[2026-07-30 친구님 "저점매수 10개는 여기 구애받지 말고"] 저점매수(route=LOWBUY·1주×10)는
    #   전역 종목수/예산 계산에서 제외 — 안 빼면 저점매수 10개가 상한 10을 채워
    #   15:18 종가매수·돈흐름 신규매수가 전멸한다. 저점매수 자체 한도는 진입기의
    #   EOD_GAP_LOWBUY_BUDGET_KRW(200만)가 담당. 롤백: backup\position_budget_20260730_lowbuyfree.py
    if str(rec.get("route", "")) == "LOWBUY": return False
    if rec.get("status", "OPEN") != "OPEN": return False
    if float(rec.get("qty", 0) or 0) <= 0: return False
    return True if assume_live else bool(rec.get("live", False))


def _scan():
    """(보유코드 집합, degraded) — degraded=존재하지만 못읽은 파일이 있어 카운트 불완전."""
    codes = set(); degraded = False
    for f in _FILES:
        d = _load(f)
        if d is None:                        # 파일 있는데 파싱실패 → 보유 누락 위험
            degraded = True; continue
        if isinstance(d, dict):
            for code, rec in d.items():
                if _open(rec): codes.add(_z(code))
        else:                                # [BUGFIX 2026-06-30] 유효JSON이지만 dict아님(list 등)=형식손상 → 보수처리(미집계로 과매수 방지)
            degraded = True
    d = _load(_PICKUP)   # eod_pickup: 최근7일 날짜키 · live daemon(=assume_live)
    if d is None:
        degraded = True
    elif isinstance(d, dict):
        cutoff = (datetime.now() - timedelta(days=7)).strftime("%Y%m%d")
        for dk, sub in d.items():
            if not (isinstance(sub, dict) and str(dk) >= cutoff): continue
            for code, rec in sub.items():
                if _open(rec, assume_live=True): codes.add(_z(code))
    else:                                    # [BUGFIX 2026-06-30] 형식손상 → 보수처리
        degraded = True
    # ★[2026-06-30 친구님 근본수술] rt_open(전 전략 통합 SoT) 합집합 — per-strategy파일 누락(brk_realtime·golden_cross) 보강.
    #   set이라 중복 자동제거. rt_open은 reconcile로 실계좌와 동기 → 실보유 완전 반영(전역상한 진짜 enforce).
    d = _load(_RT_OPEN)
    if d is None:
        degraded = True
    elif isinstance(d, dict):
        for code, rec in d.items():
            if isinstance(rec, dict) and float(rec.get("qty", 0) or 0) > 0:
                if str(rec.get("route", "")) == "LOWBUY":   # ★저점매수 제외(위 _open 주석)
                    continue
                codes.add(_z(code))
    return codes, degraded


def open_codes():
    return _scan()[0]


def total_open():
    return len(open_codes())


def _rec_krw(rec):
    """보유 원가 = qty × 매입가. 필드명 다양(buy_price/entry_price/buy)."""
    if not isinstance(rec, dict): return 0.0
    try:
        qty = float(rec.get("qty", 0) or 0)
        px = float(rec.get("buy_price", rec.get("entry_price", rec.get("buy", 0))) or 0)
        return qty * px if (qty > 0 and px > 0) else 0.0
    except Exception:
        return 0.0


def total_open_krw():
    """전 전략 합산 보유원가(원). 코드 중복은 1개로(max) — count 로직과 동일하게 합집합 dedup."""
    m = {}
    def _put(code, krw):
        if krw > 0:
            z = _z(code); m[z] = max(m.get(z, 0.0), krw)
    for f in _FILES:
        d = _load(f)
        if isinstance(d, dict):
            for code, rec in d.items():
                if _open(rec): _put(code, _rec_krw(rec))
    d = _load(_PICKUP)
    if isinstance(d, dict):
        cutoff = (datetime.now() - timedelta(days=7)).strftime("%Y%m%d")
        for dk, sub in d.items():
            if isinstance(sub, dict) and str(dk) >= cutoff:
                for code, rec in sub.items():
                    if _open(rec, assume_live=True): _put(code, _rec_krw(rec))
    d = _load(_RT_OPEN)
    if isinstance(d, dict):
        for code, rec in d.items():
            if isinstance(rec, dict) and float(rec.get("qty", 0) or 0) > 0:
                if str(rec.get("route", "")) == "LOWBUY":   # ★저점매수 제외(위 _open 주석)
                    continue
                _put(code, _rec_krw(rec))
    return sum(m.values())


def remaining():
    """전역 상한까지 남은 신규 가능 종목 수. budget_on()=False면 큰수(무제한).
    ★fail-safe: 포지션파일이 손상돼 카운트가 불완전이면 신규매수 차단(0) = 초과매수 방지."""
    if not budget_on(): return 9999
    codes, degraded = _scan()
    if degraded:                             # 못읽은 파일 있음 → 보수적으로 차단 + 진단로그
        try:
            _lg = _D / "LOG"; _lg.mkdir(parents=True, exist_ok=True)
            with open(_lg / "position_budget.log", "a", encoding="utf-8") as fh:
                fh.write(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] DEGRADED: 포지션파일 손상/잠김 → 신규매수 차단(fail-safe)\n")
        except Exception:
            pass
        return 0
    # [2026-07-02 친구님 과다매매 방지] 하루 누적 '서로 다른 종목' 상한. 넘으면 신규매수 차단(빨리 팔고 또 사기=over-trading 차단).
    dm = daily_max()
    if dm > 0:
        try:
            dsc = daily_seen_count()
            if dsc >= dm:
                try:
                    _lg = _D / "LOG"; _lg.mkdir(parents=True, exist_ok=True)
                    with open(_lg / "position_budget.log", "a", encoding="utf-8") as fh:
                        fh.write(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] DAILY_CAP: 오늘 서로다른종목 {dsc} >= 상한 {dm} → 신규매수 차단\n")
                except Exception:
                    pass
                return 0
        except Exception:
            pass  # fail-open: 하루상한 계산 실패시 기존 흐름 유지
    # [2026-06-30 친구님 "200만 한도 안에서만 운영"] 보유원가 합계 상한(KRW). 넘으면 신규매수 차단(개수와 무관).
    bk = budget_krw()
    if bk > 0:
        held_krw = total_open_krw()
        if held_krw >= bk:
            try:
                _lg = _D / "LOG"; _lg.mkdir(parents=True, exist_ok=True)
                with open(_lg / "position_budget.log", "a", encoding="utf-8") as fh:
                    fh.write(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] KRW_CAP: 보유원가 {held_krw:,.0f} >= 상한 {bk:,.0f} → 신규매수 차단\n")
            except Exception:
                pass
            return 0
    return max(0, global_max() - len(codes))


def eod_reserve():
    """종가매수(EOD)용으로 예약해둘 슬롯 수. 오전 전략은 이만큼 빼고 본다(SAFEPLUS_EOD_RESERVE·기본0)."""
    try: return int(os.environ.get("SAFEPLUS_EOD_RESERVE", "0"))
    except ValueError: return 0


def reserve_from_hm():
    """종가매수 예약을 켜기 시작하는 시각(HHMM). 이 시각 전엔 예약없이 낮 동안 전역상한까지 자유롭게."""
    return os.environ.get("SAFEPLUS_EOD_RESERVE_FROM", "1430").strip()


def remaining_intraday():
    """장중 전략용 잔여 슬롯. ★친구님: 낮(오전·오후 구분없이)엔 전역상한(예: 10)까지 자유롭게 쓰고,
    마감 직전(SAFEPLUS_EOD_RESERVE_FROM·기본1430)부터만 종가매수 몫(reserve)을 비워둠 → 종가매수 3자리 보장.
    eod_gap은 remaining()(전체)을 그대로 써서 자기 몫을 항상 확보."""
    r = remaining()
    if r >= 9999: return r          # budget off → 무제한
    if datetime.now().strftime("%H%M") < reserve_from_hm():
        return r                    # 마감 전: 예약 없이 전체(낮엔 10까지)
    return max(0, r - eod_reserve())  # 마감 즈음~: 종가매수 예약분 차감


if __name__ == "__main__":
    print(f"SAFEPLUS_GLOBAL_BUDGET={budget_on()} GLOBAL_MAX={global_max()} BUDGET_KRW={budget_krw():,.0f} EOD_RESERVE={eod_reserve()}")
    print(f"현재 전역 실보유(live OPEN) = {total_open()}종목 · 보유원가합계 = {total_open_krw():,.0f}원")
    print(f"  → 종가매수 신규가능 {remaining()} · 오전전략 신규가능 {remaining_intraday()}")
    print(f"보유 코드: {sorted(open_codes())}")
