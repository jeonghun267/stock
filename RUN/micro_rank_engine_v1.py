# -*- coding: utf-8 -*-
"""📊 마이크로구조 랭킹보드 — 주문0·TR0·SetRealReg0 [2026-07-20 친구님 "이미 감시 중인 120종목을 더 똑똑하게"]

목적: broker_gateway_v1.py가 SetRealReg로 이미 실시간 구독 중인 종목의 live_micro_snapshot.json을
  읽기전용으로 재활용해 종목간 상대순위·S/A/B/C 등급을 계산. 새 실시간 구독·TR·주문 전부 0건.
  기존 전략(골짜기·돌파·캡틴)·broker_gateway·ledger·shared_slots 전부 무접촉.

★검증 결과(코드 작성 전 확인, 2026-07-20 20:4x 장마감 후):
  · 실제 경로는 IPC\\live_micro_snapshot.json (data\\ 아님 — IPC_DIR = C:\\stock_bot\\IPC)
  · 실제 종목 수 1488개(120 아님) — _micro_snapshot dict에 삭제 로직이 없어 하루 동안 실시간
    등록/해제된 종목이 전부 누적된 것으로 추정. 그래서 이 엔진은 "파일 안 종목 수"가 아니라
    "최근 STALE_SEC(기본 30s) 이내 갱신된 종목"만 유효 유니버스로 취급 — 사실상 "지금 살아있는
    감시종목"만 걸러내므로 친구님이 말한 "이미 감시 중인 120종목" 개념과 실질적으로 동일해짐.
  · 필드명 실제값: che_str(체결강도)·cur(현재가)·cum_vol(누적거래량,float)·ask_tot/bid_tot(호가총잔량)·
    imb(=bid_tot/ask_tot, 이미 계산되어 있어 재계산 불필요)·ts(체결 갱신시각)·ob_ts(호가 갱신시각)
  · 종목명(name) 필드는 스냅샷에 없음 → money_flow_board_v1.py와 동일 패턴으로
    C:\\stock_bot\\data\\_code_name_cache.json({"map":{code:name}})에서 조인
  · 최상위 "ts"는 1초마다 갱신(broker MICRO_FLUSH_MS=1000)되지만 개별 종목 ts는 실제 체결시에만 갱신

방식(1초 폴링·mtime 불변시 재계산 생략):
  · 종목별 최근 10분 롤링 버퍼(메모리) → 10s/30s/60s 시점 값 조회로 변화량·가속도 산출
  · 120(=유효)종목 전체 percentile rank → 5개 지표 가중합 100점 rank_score
  · S/A/B/C 등급은 즉시 반영 안 하고 승격/강등 지속시간 적용(흔들림 방지)
  · 출력은 임시파일+os.replace 원자적 쓰기. 이벤트(TOP20 진입/이탈·등급변경·급등·stale)만 CSV 기록.

리허설 주입구(env, 전부 미설정시 실서비스 경로 기본값 — 운영 파일 무접촉 리허설 가능):
  MRE_SNAP·MRE_NAMEC·MRE_OUT·MRE_LOG·MRE_HIST
  MRE_POLL(1.0)·MRE_WARMUP(60)·MRE_STALE(30)·MRE_BUFFER_MIN(10)·MRE_MIN_VALID(20)
  MRE_W_MONEY30(30)·MRE_W_MACCEL(25)·MRE_W_CHE(20)·MRE_W_CHEACCEL(15)·MRE_W_IMB(10) — 이번 작업 미튜닝
  MRE_S_MIN(85)·MRE_A_MIN(70)·MRE_B_MIN(50)
  MRE_HOLD_S(10)·MRE_HOLD_A(15)·MRE_HOLD_B(15, ※B 승격유예는 스펙 미명시 — A와 동일값 채택·가정)·MRE_HOLD_DEMOTE(20)
"""
import os
import csv
import json
import time
from bisect import bisect_left, bisect_right
from collections import deque
from datetime import datetime
from pathlib import Path

SNAP      = Path(os.environ.get("MRE_SNAP")  or r"C:\stock_bot\IPC\live_micro_snapshot.json")
NAMEC     = Path(os.environ.get("MRE_NAMEC") or r"C:\stock_bot\data\_code_name_cache.json")
OUT_BOARD = Path(os.environ.get("MRE_OUT")   or r"C:\stock_bot\data\micro_rank_board.json")
LOG       = Path(os.environ.get("MRE_LOG")   or r"C:\stock_bot\data\LOG\micro_rank_engine.log")
HIST      = Path(os.environ.get("MRE_HIST")  or r"C:\stock_bot\data\micro_rank_history.csv")

POLL_SEC   = float(os.environ.get("MRE_POLL", "1.0"))
STOP_HM    = os.environ.get("MRE_STOP_HM", "1535").zfill(4)
WARMUP_SEC = float(os.environ.get("MRE_WARMUP", "60"))
STALE_SEC  = float(os.environ.get("MRE_STALE", "30"))
BUFFER_MIN = float(os.environ.get("MRE_BUFFER_MIN", "10"))
MIN_VALID  = int(os.environ.get("MRE_MIN_VALID", "20"))

W_MONEY30  = float(os.environ.get("MRE_W_MONEY30", "30"))
W_MACCEL   = float(os.environ.get("MRE_W_MACCEL", "25"))
W_CHE      = float(os.environ.get("MRE_W_CHE", "20"))
W_CHEACCEL = float(os.environ.get("MRE_W_CHEACCEL", "15"))
W_IMB      = float(os.environ.get("MRE_W_IMB", "10"))

S_MIN = float(os.environ.get("MRE_S_MIN", "85"))
A_MIN = float(os.environ.get("MRE_A_MIN", "70"))
B_MIN = float(os.environ.get("MRE_B_MIN", "50"))

PROMOTE_HOLD = {
    "S": float(os.environ.get("MRE_HOLD_S", "10")),
    "A": float(os.environ.get("MRE_HOLD_A", "15")),
    "B": float(os.environ.get("MRE_HOLD_B", "15")),
}
DEMOTE_HOLD = float(os.environ.get("MRE_HOLD_DEMOTE", "20"))
GRADE_ORDER = {"C": 0, "B": 1, "A": 2, "S": 3}

# ══════════════════════════════════════════════════════════════════════════
# [2026-07-21 신규 자금유입 계산 — 친구님 지시] 기존 필드·스코어링·등급 로직 무접촉.
# 전부 새 함수·새 필드만 추가한다(기존 money_accel/money_30s/che_accel/score/grade 그대로 유지).
#
# 구현 전 검증 결과(임의 추측 없이 실측):
#   - live_micro_snapshot.json엔 누적거래대금(FID14) 필드가 없다 → 1순위(FID14 차분) 불가,
#     항상 2순위(FID13 누적거래량 차분 × 스냅샷별 당시가격 누적)로 계산한다.
#   - broker_gateway MICRO_FIDS엔 FID15(체결량)가 구독은 돼 있으나 _micro_update()가 실제로
#     읽지 않는다 — 매수/매도 부호 정보 자체가 파이프라인에 없다. buy_qty/sell_qty/tick_rule_*
#     계열은 이번 패치에 포함하지 않는다(부호 검증 전이라 사양 7번 규칙대로 미생성 — 필요시 별도 지시).
#   - broker_gateway `_num()`이 abs()를 적용해 저장 전 부호를 지운다(재확인).
# ══════════════════════════════════════════════════════════════════════════
MFD_FLOOR_10S = float(os.environ.get("MFD_FLOOR_10S", "3000000"))            # 10초창 최소기준 300만원
MFD_FLOOR_30S = float(os.environ.get("MFD_FLOOR_30S", "10000000"))           # 30초창 1,000만원
MFD_FLOOR_60S = float(os.environ.get("MFD_FLOOR_60S", "20000000"))           # 60초창 2,000만원
MFD_MIN_MONEY_30S = float(os.environ.get("MFD_MIN_MONEY_30S", "30000000"))   # START 최소 거래대금(30초) 3,000만원
MFD_MIN_MONEY_60S = float(os.environ.get("MFD_MIN_MONEY_60S", "70000000"))   # 참고용 7,000만원(현재 상태머신 미사용)

MFD_EVENTS_CSV = Path(os.environ.get("MFD_EVENTS_CSV") or r"C:\stock_bot\data\shadow\money_flow_events.csv")
MFD_LOG        = Path(os.environ.get("MFD_LOG")        or r"C:\stock_bot\data\LOG\money_flow_detect.log")

MFD_HOLD_WATCH_START = float(os.environ.get("MFD_HOLD_WATCH_START", "3"))    # WATCH→START 조건유지(초)
MFD_HOLD_START_ACCEL = float(os.environ.get("MFD_HOLD_START_ACCEL", "3"))    # START→ACCEL
MFD_HOLD_WEAK        = float(os.environ.get("MFD_HOLD_WEAK", "5"))           # *→WEAK
MFD_HOLD_END         = float(os.environ.get("MFD_HOLD_END", "10"))           # WEAK→END
MFD_COOLDOWN_SEC     = float(os.environ.get("MFD_COOLDOWN_SEC", "30"))       # [안정화패치] END 이후 재관찰(WATCH) 재개까지 쿨다운(초)
MFD_HOLD_MONEY_START = float(os.environ.get("MFD_HOLD_MONEY_START", "3"))    # [골짜기 연동 파이프라인] MONEY_START 원시조건 유지시간(2~3초)
MFD_RANK_HIST_SEC    = 15.0                                                  # 순위이력 보관(rank_velocity_10s용)
MFD_WARN_THROTTLE_SEC = 60.0

_PUBLIC_FIELDS = (
    "rank", "code", "name", "grade", "score", "che",
    "che_delta_10s", "che_delta_30s", "che_accel",
    "money_30s", "money_accel", "imbalance", "imbalance_delta_10s",
    "grade_since", "snapshot_age_sec",
    # ── [2026-07-21 신규 자금유입] 아래부터 전부 추가 필드(기존 필드 위는 무변경) ──
    "money_5s_now", "money_5s_prev",
    "money_10s_now", "money_10s_prev", "money_30s_now", "money_30s_prev",
    "money_60s_now", "money_60s_prev", "money_180s_now", "money_180s_prev",
    "money_add_5s", "money_add_10s", "money_add_30s", "money_add_60s", "money_add_180s",
    "money_ratio_10s", "money_ratio_30s", "money_ratio_60s",
    "money_speed_5s", "money_speed_10s", "money_speed_30s",
    "money_accel_10s", "money_accel_30s", "money_accel_pct_30s",
    "che_raw", "che_delta_5s", "che_accel_10s", "che_accel_30s",
    "money_flow_score", "money_flow_rank", "money_flow_state",
    "money_flow_since", "money_flow_reasons", "money_flow_data_quality",
    "money_start", "book_imbalance_up",
)


def _log(m):
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8") as f:
            f.write(f"[{datetime.now():%H:%M:%S}] {m}\n")
    except Exception:
        pass
    print(m, flush=True)


def _atomic_write_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


_HIST_HEADER = ["ts", "event", "code", "name", "detail"]


def _hist_write(event, code, name, detail=""):
    try:
        HIST.parent.mkdir(parents=True, exist_ok=True)
        new = not HIST.exists()
        with HIST.open("a", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            if new:
                w.writerow(_HIST_HEADER)
            w.writerow([datetime.now().strftime("%Y-%m-%d %H:%M:%S"), event, code, name, detail])
    except Exception as e:
        _log(f"[HIST] 기록 실패(무시): {e}")


_namemap = {}
_namemap_mtime = None


def _load_namemap():
    global _namemap, _namemap_mtime
    try:
        mt = NAMEC.stat().st_mtime
    except Exception:
        return
    if mt == _namemap_mtime:
        return
    try:
        d = json.loads(NAMEC.read_text(encoding="utf-8-sig"))
        _namemap = d.get("map", {}) or {}
        _namemap_mtime = mt
    except Exception as e:
        _log(f"[NAME] 캐시 읽기 실패(직전 매핑 유지): {e}")


def _percentiles(items, field):
    """mid-rank percentile(0~1) — 동률은 평균 순위로 처리."""
    vals = sorted(it[field] for it in items)
    n = len(vals)
    out = {}
    for it in items:
        v = it[field]
        lo = bisect_left(vals, v)
        hi = bisect_right(vals, v)
        out[it["code"]] = (lo + (hi - lo) / 2.0) / n
    return out


def _at_or_before(buf, target_epoch):
    for sample in reversed(buf):
        if sample[0] <= target_epoch:
            return sample
    return None


def _compute_derived(buf, now, code):
    """sample = (epoch, cur, cum_vol, che, ask_tot, bid_tot, imb)"""
    latest = buf[-1]
    s10 = _at_or_before(buf, now - 10)
    s20 = _at_or_before(buf, now - 20)
    s30 = _at_or_before(buf, now - 30)
    s60 = _at_or_before(buf, now - 60)

    che_now = latest[3] or 0.0
    che10 = (s10[3] if s10 and s10[3] is not None else che_now)
    che20 = (s20[3] if s20 and s20[3] is not None else che10)
    che30 = (s30[3] if s30 and s30[3] is not None else che_now)

    che_delta_10s = che_now - che10
    che_delta_30s = che_now - che30
    prior10 = che10 - che20
    che_accel = che_delta_10s - prior10

    cv_now = latest[2] or 0.0
    cv10 = (s10[2] if s10 and s10[2] is not None else cv_now)
    cv30 = (s30[2] if s30 and s30[2] is not None else cv_now)
    cv60 = (s60[2] if s60 and s60[2] is not None else cv30)

    vol10 = cv_now - cv10
    if vol10 < 0:
        _log(f"[VOL-REGRESS] {code} 10초창 누적거래량 역행 — 구간증분 0 처리")
        vol10 = 0.0
    vol30 = cv_now - cv30
    if vol30 < 0:
        _log(f"[VOL-REGRESS] {code} 30초창 누적거래량 역행 — 구간증분 0 처리")
        vol30 = 0.0
    prior_vol30 = cv30 - cv60
    if prior_vol30 < 0:
        prior_vol30 = 0.0

    px_now = latest[1] or 0.0
    px30 = (s30[1] if s30 and s30[1] is not None else px_now)
    money30 = vol30 * px_now
    prior_money30 = prior_vol30 * px30
    money_accel = money30 - prior_money30

    imb_now = latest[6] if latest[6] is not None else 0.0
    imb10 = (s10[6] if s10 and s10[6] is not None else imb_now)
    imbalance_delta_10s = imb_now - imb10

    return {
        "che": che_now,
        "che_delta_10s": che_delta_10s,
        "che_delta_30s": che_delta_30s,
        "che_accel": che_accel,
        "money_30s": money30,
        "money_accel": money_accel,
        "imbalance": imb_now,
        "imbalance_delta_10s": imbalance_delta_10s,
    }


def _grade_of(score, money_30s):
    if score >= S_MIN and money_30s > 0:
        return "S"
    if score >= A_MIN:
        return "A"
    if score >= B_MIN:
        return "B"
    return "C"


def _apply_hysteresis(gs, raw_grade, now):
    if gs["candidate"] != raw_grade:
        gs["candidate"] = raw_grade
        gs["candidate_since"] = now
    held = now - gs["candidate_since"]
    confirmed = gs["confirmed"]
    if raw_grade == confirmed:
        return confirmed
    if GRADE_ORDER[raw_grade] > GRADE_ORDER[confirmed]:
        need = PROMOTE_HOLD.get(raw_grade, 15.0)
    else:
        need = DEMOTE_HOLD
    if held >= need:
        gs["confirmed"] = raw_grade
        gs["since"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return gs["confirmed"]


def _public(it):
    return {k: it.get(k) for k in _PUBLIC_FIELDS}


# ══════════════════════════════════════════════════════════════════════════
# [2026-07-21 신규 자금유입 계산 블록] sample = (epoch, cur, cum_vol, che, ask_tot, bid_tot, imb)
# 기존 _compute_derived/_percentiles/_grade_of/_apply_hysteresis 전부 무접촉 — 별도 함수만 추가.
# ══════════════════════════════════════════════════════════════════════════

_vol_regress_warn_last = {}   # code -> epoch, 종목당 60초 1회 throttle(사양 3번)


def _mfd_warn(code, msg):
    now = time.time()
    last = _vol_regress_warn_last.get(code, 0.0)
    if now - last >= MFD_WARN_THROTTLE_SEC:
        _vol_regress_warn_last[code] = now
        _log(msg)


def _money_series(buf, now, code):
    """단일 순회로 시간경계(now-10..now-360)별 누적 신규거래대금을 구한다.
    각 스냅샷의 증분거래량 × '그 순간' 가격을 누적(사양 3번 — 구간 전체를 현재가 한 값으로
    근사하는 방식보다 정밀). 반환: (경계별 누적금액 dict, now 시점까지의 총 누적금액)."""
    boundaries = (5, 10, 20, 30, 60, 120, 180, 360)
    # target_epoch(now-b) 오름차순으로 훑되, 결과 dict는 "오프셋 b"로 키를 저장한다
    # (버그수정 2026-07-21: 절대시각으로 저장하면 _win()의 오프셋 조회와 안 맞아 전부 0이 나왔음
    #  — 합성 리허설 테스트1에서 실측 발견·수정).
    ordered = sorted(boundaries, key=lambda b: now - b)  # target_epoch 오름차순 = b 내림차순
    result = {}
    running = 0.0
    prev = None
    ti = 0
    for sample in buf:
        epoch, cur, cum_vol = sample[0], sample[1], sample[2]
        if prev is not None:
            pv = prev[2]
            dv = (cum_vol - pv) if (cum_vol is not None and pv is not None) else 0.0
            if dv < 0:
                _mfd_warn(code, f"[MFD-VOL-REGRESS] {code} 신규자금 계산 중 누적거래량 역행 "
                                 f"— 구간증분 0 처리(종목당 60초 1회만 로그)")
                dv = 0.0
            px = cur if cur is not None else (prev[1] or 0.0)
            running += dv * (px or 0.0)
        while ti < len(ordered) and epoch >= now - ordered[ti]:
            result[ordered[ti]] = running
            ti += 1
        prev = sample
    while ti < len(ordered):
        result[ordered[ti]] = running
        ti += 1
    return result, running


def _che_at(buf, target_epoch, fallback):
    s = _at_or_before(buf, target_epoch)
    return (s[3] if s and s[3] is not None else fallback)


def _moneyflow_raw(buf, now, code):
    """신규 자금유입 파생값 전부 계산 — 새 dict만 반환, 기존 필드/버퍼 구조 무변경."""
    latest = buf[-1]
    boundary_money, total_now = _money_series(buf, now, code)

    def _win(now_key, prev_lo, prev_hi):
        m_now = total_now - boundary_money.get(now_key, total_now)
        m_prev = boundary_money.get(prev_lo, 0.0) - boundary_money.get(prev_hi, 0.0)
        return round(m_now, 1), round(m_prev, 1)

    money_5s_now, money_5s_prev = _win(5, 5, 10)
    money_10s_now, money_10s_prev = _win(10, 10, 20)
    money_30s_now, money_30s_prev = _win(30, 30, 60)
    money_60s_now, money_60s_prev = _win(60, 60, 120)
    money_180s_now, money_180s_prev = _win(180, 180, 360)

    def _ratio(now_v, prev_v, floor_v):
        base = max(prev_v, floor_v)
        return round(now_v / base, 4) if base > 0 else 0.0

    money_ratio_10s = _ratio(money_10s_now, money_10s_prev, MFD_FLOOR_10S)
    money_ratio_30s = _ratio(money_30s_now, money_30s_prev, MFD_FLOOR_30S)
    money_ratio_60s = _ratio(money_60s_now, money_60s_prev, MFD_FLOOR_60S)
    low_base_30s = money_30s_prev < MFD_FLOOR_30S

    money_speed_5s = round(money_5s_now / 5.0, 1)
    money_speed_10s = round(money_10s_now / 10.0, 1)
    money_speed_30s = round(money_30s_now / 30.0, 1)
    money_speed_10s_prev = round(money_10s_prev / 10.0, 1)
    money_speed_30s_prev = round(money_30s_prev / 30.0, 1)
    money_accel_10s = round(money_speed_10s - money_speed_10s_prev, 1)
    money_accel_30s = round(money_speed_30s - money_speed_30s_prev, 1)
    floor_speed_30s = MFD_FLOOR_30S / 30.0
    denom = max(money_speed_30s_prev, floor_speed_30s)
    money_accel_pct_30s = round((money_speed_30s / denom - 1) * 100, 2) if denom > 0 else 0.0

    che_now = latest[3] or 0.0
    che5 = _che_at(buf, now - 5, che_now)
    che10 = _che_at(buf, now - 10, che_now)
    che20 = _che_at(buf, now - 20, che10)
    che30 = _che_at(buf, now - 30, che_now)
    che60 = _che_at(buf, now - 60, che30)
    che_speed_10s = (che_now - che10) / 10.0
    che_speed_10s_prev = (che10 - che20) / 10.0
    che_speed_30s = (che_now - che30) / 30.0
    che_speed_30s_prev = (che30 - che60) / 30.0

    return {
        "money_5s_now": money_5s_now, "money_5s_prev": money_5s_prev,
        "money_10s_now": money_10s_now, "money_10s_prev": money_10s_prev,
        "money_30s_now": money_30s_now, "money_30s_prev": money_30s_prev,
        "money_60s_now": money_60s_now, "money_60s_prev": money_60s_prev,
        "money_180s_now": money_180s_now, "money_180s_prev": money_180s_prev,
        "money_add_5s": round(money_5s_now - money_5s_prev, 1),
        "money_add_10s": round(money_10s_now - money_10s_prev, 1),
        "money_add_30s": round(money_30s_now - money_30s_prev, 1),
        "money_add_60s": round(money_60s_now - money_60s_prev, 1),
        "money_add_180s": round(money_180s_now - money_180s_prev, 1),
        "money_ratio_10s": money_ratio_10s, "money_ratio_30s": money_ratio_30s,
        "money_ratio_60s": money_ratio_60s,
        "money_speed_5s": money_speed_5s,
        "money_speed_10s": money_speed_10s, "money_speed_30s": money_speed_30s,
        "money_accel_10s": money_accel_10s, "money_accel_30s": money_accel_30s,
        "money_accel_pct_30s": money_accel_pct_30s,
        "che_raw": che_now, "che_delta_5s": round(che_now - che5, 2),
        "che_accel_10s": round(che_speed_10s - che_speed_10s_prev, 3),
        "che_accel_30s": round(che_speed_30s - che_speed_30s_prev, 3),
        "money_flow_data_quality": "LOW_BASE" if low_base_30s else "OK",
    }


def _moneyflow_score(it, pct):
    """MoneyFlowScore 100점 — 기존 score(랭킹용)와 완전 분리된 별도 점수(사양 10·3번)."""
    c = it["code"]
    s = (pct["money30now"].get(c, 0.0) * 20 + pct["madd30"].get(c, 0.0) * 20 +
         pct["mratio30"].get(c, 0.0) * 15 + pct["maccel30"].get(c, 0.0) * 15 +
         pct["chedelta10"].get(c, 0.0) * 10 + pct["cheaccel10"].get(c, 0.0) * 10 +
         pct["rankvel10"].get(c, 0.0) * 10)
    return round(s, 2)


def _advance_moneyflow(rec, now, it):
    """신규 자금유입 상태머신(사양 9번). IDLE/WATCH/START/ACCEL/PEAK/WEAK/END.
    ★스펙 미명시 보완(가정, 이 함수 안에서만 적용):
      - END는 WATCH 조건 재충족 시 IDLE 경유 없이 즉시 WATCH로(연속 관찰 유지 목적).
      - PEAK는 진단상태라 점수가 다시 오르면 ACCEL로 복귀 가능(왕복 허용).
      - WEAK 중 START/ACCEL 조건이 다시 강하게 충족되면 즉시 복귀(급반등 대응)."""
    ratio30, add30 = it["money_ratio_30s"], it["money_add_30s"]
    ched10 = it["che_delta_10s"]  # 기존 필드 재사용(사양 그대로)
    maccel30, maccel10 = it["money_accel_30s"], it["money_accel_10s"]
    ratio10 = it["money_ratio_10s"]
    cheaccel10 = it["che_accel_10s"]
    rankv10 = it.get("_rank_velocity_10s", 0.0)
    cur_px = it.get("_cur") or 0.0
    score = it["money_flow_score"]
    state = rec["state"]

    def _watch_ok():
        return sum([ratio30 >= 1.3, add30 > 0, ched10 > 0, maccel30 > 0]) >= 2

    def _start_ok():
        """[안정화패치 2026-07-21] 사양 4번 — percentile 기반 OR-조건 제거, 실측 자금유입
        3조건(추가유입>0 AND 증가배수>=1.5 AND 체결개선>0)을 전부 만족해야만 START(AND-only).
        임계값 자체는 계산식 변경 금지 원칙에 따라 기존 값 그대로(완화하지 않음)."""
        return (it["money_30s_now"] >= MFD_MIN_MONEY_30S and add30 > 0 and
                ratio30 >= 1.5 and ched10 > 0)

    def _accel_ok():
        return sum([ratio10 >= 1.5, ratio30 >= 2.0, maccel10 > 0, maccel30 > 0,
                    ched10 > 0, cheaccel10 > 0, rankv10 > 0]) >= 3

    def _weak_ok():
        return sum([add30 <= 0, maccel10 < 0, ched10 < 0, cheaccel10 < 0, rankv10 < 0]) >= 2

    def _end_ok():
        return ratio30 < 1.0 and add30 <= 0 and ched10 <= 0

    def _set_cand(flag, need_sec, target):
        if flag:
            if rec.get("cand") != target:
                rec["cand"] = target
                rec["cand_since"] = now
            if now - rec["cand_since"] >= need_sec:
                return target
        else:
            rec["cand"] = None
        return None

    def _weak_cand(rec, flag, now):
        """★[버그수정 2026-07-21] WEAK 진입도 사양대로 5초 연속 유지가 필요(START→ACCEL과
        동일한 원칙인데 최초 구현에서 빠져있었음 — 실전 그림자에서 여러 종목이 매초
        ACCEL↔WEAK를 왕복하는 걸 실측으로 발견해 수정). 'cand'(상승 후보) 슬롯과 섞이면
        서로 리셋시켜 카운트가 깨지므로 완전히 별도 슬롯(weak_cand_since)을 쓴다."""
        if flag:
            if rec.get("weak_cand_since") is None:
                rec["weak_cand_since"] = now
            if now - rec["weak_cand_since"] >= MFD_HOLD_WEAK:
                return True
        else:
            rec["weak_cand_since"] = None
        return False

    new_state, reasons = state, []

    # [안정화패치 2026-07-21] 종목별 MFE/MAE 추적 — START 진입가 대비 현재까지의 최대유리/최대불리
    # 변동폭. 계산식(START/ACCEL/...) 자체는 무접촉, 이벤트 검증용 부가 기록일 뿐(사양 6번).
    if state in ("START", "ACCEL", "WEAK", "PEAK") and cur_px > 0:
        if rec.get("mfe_price") is None or cur_px > rec["mfe_price"]:
            rec["mfe_price"] = cur_px
        if rec.get("mae_price") is None or cur_px < rec["mae_price"]:
            rec["mae_price"] = cur_px

    if state in ("IDLE", "END"):
        # [안정화패치] 사양 3번 — END 직후 30초 쿨다운 동안은 WATCH 재진입 금지(같은 종목 재START 방지)
        cooled = state != "END" or (now - rec.get("end_ts", 0.0)) >= MFD_COOLDOWN_SEC
        if cooled and _watch_ok():
            new_state = "WATCH"
            reasons.append("조건 2/4 이상 충족")
            rec["cand"] = None
    elif state == "WATCH":
        t = _set_cand(_start_ok(), MFD_HOLD_WATCH_START, "START")
        if t:
            new_state = "START"
            reasons.append(f"{MFD_HOLD_WATCH_START:.0f}초 연속 충족")
            rec["peak_score"] = score
            rec["entry_price"] = cur_px       # [안정화패치] 이벤트 단위 검증(사양 6번)
            rec["entry_ts"] = now
            rec["mfe_price"] = cur_px
            rec["mae_price"] = cur_px
        elif not _watch_ok():
            new_state = "IDLE"
            rec["cand"] = None
    elif state == "START":
        rec["peak_score"] = max(rec.get("peak_score", score), score)
        t = _set_cand(_accel_ok(), MFD_HOLD_START_ACCEL, "ACCEL")
        if t:
            new_state = "ACCEL"
            reasons.append(f"{MFD_HOLD_START_ACCEL:.0f}초 연속 충족(3개+)")
        elif _weak_cand(rec, _weak_ok(), now):
            new_state = "WEAK"
            rec["weak_since"] = now
            rec["cand"] = None
            reasons.append(f"{MFD_HOLD_WEAK:.0f}초 연속 약화(2/5 이상)")
    elif state == "ACCEL":
        rec["peak_score"] = max(rec.get("peak_score", score), score)
        if _weak_cand(rec, _weak_ok(), now):
            new_state = "WEAK"
            rec["weak_since"] = now
            reasons.append(f"{MFD_HOLD_WEAK:.0f}초 연속 약화(2/5 이상)")
        elif score < rec["peak_score"] - 1e-6 and ched10 > 0 and add30 > 0:
            new_state = "PEAK"
            reasons.append("최고점 갱신 후 둔화(유입은 유지)")
    elif state == "PEAK":
        if _weak_cand(rec, _weak_ok(), now):
            new_state = "WEAK"
            rec["weak_since"] = now
            reasons.append(f"{MFD_HOLD_WEAK:.0f}초 연속 약화(2/5 이상)")
        elif score > rec.get("peak_score", score) + 1e-6:
            new_state = "ACCEL"
            rec["peak_score"] = score
    elif state == "WEAK":
        since_weak = now - rec.get("weak_since", now)
        if since_weak < MFD_HOLD_WEAK:
            pass  # [안정화패치] 사양 2번 — WEAK 최소체류 5초 전엔 무조건 유지(ACCEL↔WEAK 왕복 방지)
        elif _accel_ok() or _start_ok():
            # [안정화패치] 사양 1번 — WEAK→START 제거. START는 한 이벤트(START~END)당 1회만 발생해야
            # 하므로 WEAK에서의 회복은 전부 ACCEL로만 복귀시킨다(END 전 재START 금지).
            new_state = "ACCEL"
            rec["cand"] = None
        elif _end_ok() and since_weak >= MFD_HOLD_END:
            new_state = "END"

    if new_state != state:
        rec["state"] = new_state
        rec["since"] = now
        if new_state == "END":
            # [안정화패치] 사양 3번(쿨다운 기준시각) + 사양 6번(이벤트 요약 로그)
            rec["end_ts"] = now
            ep = rec.get("entry_price")
            if ep:
                dur = now - rec.get("entry_ts", now)
                mfe = (rec.get("mfe_price", ep) / ep - 1) * 100
                mae = (rec.get("mae_price", ep) / ep - 1) * 100
                reasons.append(f"이벤트 지속 {dur:.0f}초 · MFE {mfe:+.2f}% · MAE {mae:+.2f}%")
        rec["reasons"] = reasons
    return reasons


def _mfd_won(v):
    """원 단위 → 억/만원 사람이 읽는 표기(로그 전용, 계산엔 원본 원 단위 사용)."""
    v = v or 0.0
    if abs(v) >= 100_000_000:
        return f"{v/100_000_000:.1f}억"
    return f"{v/10_000:.0f}만원"


def _mfd_log_transition(code, name, old_state, new_state, it, reasons):
    """사양 2번 — 사람이 검증 가능한 상세 로그(예시 포맷) + 사양 14번 CSV 이벤트 기록.
    [안정화패치 2026-07-21] 사양 5번 — 로그 스팸 감소를 위해 START/ACCEL/WEAK/END 전이만
    남긴다. WATCH/IDLE/PEAK는 내부 진단상태로만 쓰고 로그·CSV엔 기록하지 않는다."""
    if new_state not in ("START", "ACCEL", "WEAK", "END"):
        return
    ts_now = datetime.now()
    che_seq = f"{it.get('_che10_ago', it['che_raw']):.0f} → {it.get('_che5_ago', it['che_raw']):.0f} → {it['che_raw']:.0f}"
    _log(
        f"[MONEYFLOW] {ts_now:%H:%M:%S} {name}({code}) {old_state}→{new_state}\n"
        f"  직전30초: {_mfd_won(it['money_30s_prev'])} · 최근30초: {_mfd_won(it['money_30s_now'])} "
        f"· 추가유입: {it['money_add_30s']:+,.0f}원({_mfd_won(it['money_add_30s'])}) · 증가배수: {it['money_ratio_30s']:.2f}\n"
        f"  속도: {it['money_speed_30s']/10000:.0f}만원/초 · 가속도: {it['money_accel_30s']/10000:+.0f}만원/초\n"
        f"  체결강도 {che_seq} · 체결Δ10: {it['che_delta_10s']:+.1f} · 체결가속: {it['che_accel_10s']:+.2f}\n"
        f"  MoneyFlowScore: {it['money_flow_score']:.0f} · 사유: {', '.join(reasons) or '-'}"
    )
    event = f"MONEY_{new_state}"
    try:
        MFD_EVENTS_CSV.parent.mkdir(parents=True, exist_ok=True)
        new = not MFD_EVENTS_CSV.exists()
        with MFD_EVENTS_CSV.open("a", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            if new:
                w.writerow(["ts", "event", "code", "name", "old_state", "new_state",
                            "money_30s_now", "money_30s_prev", "money_add_30s",
                            "money_ratio_30s", "money_accel_30s", "che_raw",
                            "che_delta_10s", "che_accel_10s", "money_flow_score",
                            "money_flow_rank", "reason"])
            w.writerow([ts_now.strftime("%Y-%m-%d %H:%M:%S"), event, code, name,
                        old_state, new_state, it["money_30s_now"], it["money_30s_prev"],
                        it["money_add_30s"], it["money_ratio_30s"], it["money_accel_30s"],
                        it["che_raw"], it["che_delta_10s"], it["che_accel_10s"],
                        it["money_flow_score"], it.get("money_flow_rank", ""),
                        "; ".join(reasons)])
    except Exception as e:
        _log(f"[MFD-EVENT] 기록 실패(무시): {e}")


def main():
    _log("micro_rank_engine_v1 시작 — 읽기전용 · TR 0 · 주문 0 · SetRealReg 0")
    _log(f"입력={SNAP} 출력={OUT_BOARD} 폴링={POLL_SEC}s WARMUP={WARMUP_SEC}s STALE={STALE_SEC}s")

    buffers = {}       # code -> deque[(epoch,cur,cum_vol,che,ask_tot,bid_tot,imb)]
    first_seen = {}    # code -> engine epoch 최초 관측 시각(WARMUP 기준)
    grade_state = {}   # code -> {"confirmed","since","candidate","candidate_since"}
    prev_rank = {}
    prev_grade = {}
    prev_top20 = set()
    last_mtime = None
    last_good_codes = {}
    data_stale = False
    # [2026-07-21 신규 자금유입] 기존 상태와 완전 분리된 별도 상태 저장소
    moneyflow_state = {}   # code -> {"state","since","cand","cand_since","peak_score","weak_since","reasons"}
    rank_hist = {}         # code -> deque[(epoch, rank)] — rank_velocity_10s 계산용
    money_start_since = {}  # code -> epoch(MONEY_START 원시조건이 끊김없이 True가 된 시각) — 새 상태머신
    # 아님, 단순 유지시간 카운터 하나(2026-07-21 골짜기 연동 파이프라인: MONEY_START→2~3초 유지→TOP10)

    while True:
        if datetime.now().strftime("%H%M") >= STOP_HM:
            _log(f"[SHUTDOWN] stop_hm={STOP_HM}")
            break
        loop_t0 = time.time()
        now = loop_t0

        _load_namemap()

        mtime = None
        try:
            mtime = SNAP.stat().st_mtime
        except Exception as e:
            if not data_stale:
                _hist_write("DATA_STALE", "-", "-", f"파일 접근 실패: {e}")
                _log(f"[STALE] 스냅샷 파일 접근 실패(직전 정상 데이터 유지): {e}")
                data_stale = True

        if mtime is not None and mtime != last_mtime:
            try:
                raw = SNAP.read_text(encoding="utf-8-sig")
                parsed = json.loads(raw).get("codes", {})
                last_good_codes = parsed
                last_mtime = mtime
                if data_stale:
                    _hist_write("DATA_RECOVER", "-", "-", "")
                    _log("[RECOVER] 스냅샷 정상 회복")
                    data_stale = False
            except Exception as e:
                if not data_stale:
                    _hist_write("DATA_STALE", "-", "-", f"파싱 실패: {e}")
                    _log(f"[STALE] JSON 파싱 실패(직전 정상 데이터 유지): {e}")
                    data_stale = True

        codes_raw = last_good_codes

        for code, rec in codes_raw.items():
            try:
                rec_epoch = datetime.fromisoformat(str(rec.get("ts"))).timestamp()
            except Exception:
                continue
            buf = buffers.get(code)
            if buf is None:
                buf = deque()
                buffers[code] = buf
                first_seen[code] = now
            if not (buf and buf[-1][0] == rec_epoch):
                cur = rec.get("cur")
                cum_vol = rec.get("cum_vol")
                che = rec.get("che_str")
                ask = rec.get("ask_tot")
                bid = rec.get("bid_tot")
                imb = rec.get("imb")
                if buf and cum_vol is not None and buf[-1][2] is not None and cum_vol < buf[-1][2]:
                    _log(f"[VOL-REGRESS] {code} 누적거래량 역행({buf[-1][2]:.0f}→{cum_vol:.0f}) — 장중리셋/오류 간주")
                buf.append((rec_epoch, cur, cum_vol, che, ask, bid, imb))
            cutoff = now - BUFFER_MIN * 60
            while buf and buf[0][0] < cutoff:
                buf.popleft()

        for code in list(buffers.keys()):
            if not buffers[code]:
                del buffers[code]
                first_seen.pop(code, None)
                grade_state.pop(code, None)

        all_items = []
        for code, buf in buffers.items():
            if not buf:
                continue
            latest = buf[-1]
            age = now - latest[0]
            warm = (now - first_seen[code]) < WARMUP_SEC
            fresh = age <= STALE_SEC
            it = {
                "code": code, "name": _namemap.get(code, ""),
                "che": latest[3], "snapshot_age_sec": round(age, 1),
                "_valid": False, "_cur": latest[1],
            }
            if warm:
                it["grade"] = "WARMUP"
            elif not fresh:
                it["grade"] = "STALE"
            else:
                it.update(_compute_derived(buf, now, code))
                it["_valid"] = True
            all_items.append(it)

        valid_items = [it for it in all_items if it["_valid"]]
        valid_count = len(valid_items)
        universe_count = len(all_items)
        top20 = []

        if valid_count < MIN_VALID:
            status = "INSUFFICIENT_DATA"
        else:
            status = "OK"
            pct_che = _percentiles(valid_items, "che")
            pct_chea = _percentiles(valid_items, "che_accel")
            pct_m30 = _percentiles(valid_items, "money_30s")
            pct_ma = _percentiles(valid_items, "money_accel")
            pct_imb = _percentiles(valid_items, "imbalance")

            for it in valid_items:
                c = it["code"]
                it["che_rank"] = round(pct_che[c], 4)
                it["che_accel_rank"] = round(pct_chea[c], 4)
                it["money_30s_rank"] = round(pct_m30[c], 4)
                it["money_accel_rank"] = round(pct_ma[c], 4)
                it["imbalance_rank"] = round(pct_imb[c], 4)
                score = (it["money_30s_rank"] * W_MONEY30 + it["money_accel_rank"] * W_MACCEL +
                         it["che_rank"] * W_CHE + it["che_accel_rank"] * W_CHEACCEL +
                         it["imbalance_rank"] * W_IMB)
                it["score"] = round(score, 2)
                it["_raw_grade"] = _grade_of(score, it["money_30s"])

                gs = grade_state.get(c)
                if gs is None:
                    gs = {"confirmed": "C", "since": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                          "candidate": None, "candidate_since": now}
                    grade_state[c] = gs
                it["grade"] = _apply_hysteresis(gs, it["_raw_grade"], now)
                it["grade_since"] = gs["since"]

                # [2026-07-21 신규 자금유입] 기존 필드 뒤에 새 필드만 추가(재계산 없음, 새 함수)
                it.update(_moneyflow_raw(buffers[c], now, c))
                # [2026-07-21 Money Flow 감지 개선(최종)] MONEY_START — 새 점수·새 상태머신 아님,
                # 전부 기존/신규 원시필드의 단순 AND(TRUE/FALSE만). 누적거래량·체결강도 절대값은
                # 안 본다 — "지금 이 순간" 속도만: ①신규유입 증가(5초 add>0) ②신규유입 속도
                # 증가(5초→10초→30초로 갈수록 밀도(원/초)가 낮아짐=최근이 더 빠름) ③체결강도
                # 증가(5초·10초 변화량 둘 다 양수). FLOW_ALIVE(이전 버전)를 대체한다.
                raw_start = bool(
                    it["money_add_5s"] > 0
                    and it["money_speed_5s"] >= it["money_speed_10s"] >= it["money_speed_30s"]
                    and it["che_delta_5s"] > 0 and it["che_delta_10s"] > 0
                )
                # [골짜기 연동 파이프라인] Money Flow→MONEY_START→2~3초 유지→TOP10. 새 상태머신이
                # 아니라 단순 유지시간 카운터 — 원시조건이 끊김없이 MFD_HOLD_MONEY_START초 유지될
                # 때만 확정 True(순간 스파이크 배제). 조건이 한 번이라도 끊기면 즉시 리셋.
                if raw_start:
                    if money_start_since.get(c) is None:
                        money_start_since[c] = now
                    it["money_start"] = (now - money_start_since[c]) >= MFD_HOLD_MONEY_START
                else:
                    money_start_since[c] = None
                    it["money_start"] = False
                # [2026-07-21 아이디어#1 호가 불균형 — 오사장님 승인] 새 계산 아님, 이미 존재하는
                # imbalance(매수호가/매도호가 비율)·imbalance_delta_10s(그 비율의 10초 변화량)만
                # 재사용한 단순 AND(TRUE/FALSE). ★가정: MONEY_START 정의는 그대로 두고(매수조건
                # 추가 아님) 관찰용 보조 필드로만 노출 — 기관/외국인 수급과 동일하게 "검증 먼저,
                # 필터는 나중" 원칙 적용. money_start와 별개 필드라 기존 골짜기/캡틴 연동 무영향.
                it["book_imbalance_up"] = bool(it["imbalance"] > 1.0 and it["imbalance_delta_10s"] > 0)

            # [2026-07-21 신규 자금유입] 새 percentile 6종 — 기존 pct_che/pct_chea/pct_m30/pct_ma/pct_imb 무접촉
            pct_money30now = _percentiles(valid_items, "money_30s_now")
            pct_madd30 = _percentiles(valid_items, "money_add_30s")
            pct_mratio30 = _percentiles(valid_items, "money_ratio_30s")
            pct_maccel30 = _percentiles(valid_items, "money_accel_30s")
            pct_chedelta10 = _percentiles(valid_items, "che_delta_10s")
            pct_cheaccel10 = _percentiles(valid_items, "che_accel_10s")

            valid_items.sort(key=lambda x: -x["score"])
            for i, it in enumerate(valid_items, 1):
                it["rank"] = i
            top20 = valid_items[:20]
            top20_codes = {it["code"] for it in top20}

            # [2026-07-21 신규 자금유입] rank_velocity_10s → MoneyFlowScore → 상태머신
            # (기존 rank는 위에서 이미 확정됨 — 그 값을 그대로 재사용, 별도 랭킹 재계산 없음)
            for it in valid_items:
                c = it["code"]
                h = rank_hist.get(c)
                if h is None:
                    h = deque()
                    rank_hist[c] = h
                h.append((now, it["rank"]))
                while h and h[0][0] < now - MFD_RANK_HIST_SEC:
                    h.popleft()
                base = h[0] if h else (now, it["rank"])
                it["_rank_velocity_10s"] = float(base[1] - it["rank"])

            pct_rankvel10 = _percentiles(valid_items, "_rank_velocity_10s")
            _pct_all = {"money30now": pct_money30now, "madd30": pct_madd30,
                        "mratio30": pct_mratio30, "maccel30": pct_maccel30,
                        "chedelta10": pct_chedelta10, "cheaccel10": pct_cheaccel10,
                        "rankvel10": pct_rankvel10}
            for it in valid_items:
                it["money_flow_score"] = _moneyflow_score(it, _pct_all)

            _mf_sorted = sorted(valid_items, key=lambda x: -x["money_flow_score"])
            for i, it in enumerate(_mf_sorted, 1):
                it["money_flow_rank"] = i

            for it in valid_items:
                c = it["code"]
                rec = moneyflow_state.get(c)
                if rec is None:
                    rec = {"state": "IDLE", "since": now, "cand": None, "cand_since": now,
                            "peak_score": 0.0, "weak_since": now, "reasons": []}
                    moneyflow_state[c] = rec
                old_state = rec["state"]
                reasons = _advance_moneyflow(rec, now, it)
                it["money_flow_state"] = rec["state"]
                it["money_flow_since"] = datetime.fromtimestamp(rec["since"]).strftime("%Y-%m-%d %H:%M:%S")
                it["money_flow_reasons"] = reasons
                if rec["state"] != old_state:
                    _mfd_log_transition(c, it["name"], old_state, rec["state"], it, reasons)

            for it in top20:
                if it["code"] not in prev_top20:
                    _hist_write("TOP20_IN", it["code"], it["name"], f"rank={it['rank']} score={it['score']}")
            for code in prev_top20 - top20_codes:
                _hist_write("TOP20_OUT", code, prev_grade.get(code, ""), "")
            for it in valid_items:
                code = it["code"]
                pg = prev_grade.get(code)
                if pg is not None and pg != it["grade"]:
                    _hist_write("GRADE_CHANGE", code, it["name"], f"{pg}->{it['grade']}")
                if it["grade"] == "S" and pg != "S":
                    _hist_write("S_ENTER", code, it["name"], f"score={it['score']}")
                pr = prev_rank.get(code)
                if pr is not None and (pr - it["rank"]) >= 10:
                    _hist_write("RANK_SURGE", code, it["name"], f"{pr}->{it['rank']}")

            prev_rank = {it["code"]: it["rank"] for it in valid_items}
            prev_grade = {it["code"]: it["grade"] for it in valid_items}
            prev_top20 = top20_codes

        # [2026-07-21 신규 자금유입 사양15] WARMUP/STALE 종목은 새로 계산·확정하지 않고
        # 직전 정상 상태만 표시(신규 상태전이 금지·이벤트로그도 안 남김).
        for it in all_items:
            if it.get("_valid"):
                continue
            rec = moneyflow_state.get(it["code"])
            if rec:
                it["money_flow_state"] = rec["state"]
                it["money_flow_since"] = datetime.fromtimestamp(rec["since"]).strftime("%Y-%m-%d %H:%M:%S")
            it["money_flow_data_quality"] = "STALE" if it.get("grade") == "STALE" else "WARMUP"

        board = {
            "date": datetime.now().strftime("%Y%m%d"),
            "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "status": status,
            "universe_count": universe_count,
            "valid_count": valid_count,
            "top20": [_public(it) for it in top20],
            "all_items": [_public(it) for it in all_items],
        }
        try:
            _atomic_write_json(OUT_BOARD, board)
        except Exception as e:
            _log(f"[WRITE] 출력 실패: {e}")

        elapsed = time.time() - loop_t0
        time.sleep(max(0.05, POLL_SEC - elapsed))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
    except Exception as e:
        _log(f"🚨 치명 오류: {e}")
