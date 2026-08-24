# -*- coding: utf-8 -*-
"""Money Flow 1초 원시데이터 캡처 + 리셋형 매수우위 계측
[2026-07-21 최초 작성] [2026-07-22 리셋형 계측 추가]

읽기전용·검증 전용. 매매 로직(캡틴/골짜기/BUY/SELL/MONEY_START/상태머신) 무접촉. 새 TR 없음·
새 SetRealReg 없음·새 실시간등록 없음 — 이미 1초마다 갱신되는 기존 파일 2개만 읽는다.

읽기: C:\\stock_bot\\IPC\\live_micro_snapshot.json      (broker가 1초마다 작성 — cur/cum_vol/che_str/ask_tot/bid_tot/imb)
      C:\\stock_bot\\data\\micro_rank_board.json         (micro_rank_engine_v1이 1초마다 계산 — money_add_*/money_speed_*/che_delta_*/money_start)
씀:   C:\\stock_bot\\data\\shadow\\mf_1s_capture\\mf_1s_{YYYYMMDD}.csv        (초당 원시, 기존 필드 + 리셋 필드)
      C:\\stock_bot\\data\\shadow\\mf_reset_events\\mf_reset_events_{YYYYMMDD}.csv  (리셋 이벤트 1건당 요약 1행)

money_start_raw = micro_rank_engine_v1.py 761~763행의 원시조건(유지시간 확정 전)을 그대로 재현한
                  것뿐 — 새 조건 발명이 아니라 이미 있는 식을 진단용으로 한 번 더 계산.

[2026-07-22 리셋형 계측 — 중요한 기술적 한계]
broker_gateway_v1.py를 직접 확인한 결과(추측 아님, RUN/broker_gateway_v1.py:926-969 _micro_update),
실시간으로 실제 수신 중인 값은 che_str(체결강도, FID228 — 장중 누적 매수/매도 비율)·cur(현재가)·
cum_vol(누적거래량) 뿐이며, 틱 단위 체결량이나 매수/매도 방향을 구분하는 FID는 현재 전혀 읽지
않는다(FID 15=거래량은 SetRealReg만 되어 있고 실제 GetCommRealData 호출은 안 함). 또한
_micro_update는 종목당 MICRO_THROTTLE_MS(기본 200ms) 안에 여러 틱이 와도 첫 틱만 반영하고
나머지는 버린다 — 즉 진짜 틱 단위 매수/매도 스트림은 이 시스템 어디에도 보존되지 않는다.
따라서 아래 buy_exec_vol_reset 등 매수/매도 관련 필드는 전부 "근사치"다: 장중 누적거래량과
장중 누적체결강도(che_str = 매수체결누적/매도체결누적*100 이라는 키움 표준 정의를 그대로 가정)를
T0 시점과 현재 시점 두 지점에서 차분(differencing)해서 그 구간의 신규 매수/매도 체결량을 역산한
값이다. 실제 틱 방향 원시값이 아니다 — che_str의 정확한 계산창(장중 누적인지 다른 롤링구간인지)도
키움 공식 문서로 재확인된 바 없다(코드 주석상의 통용 정의를 근거로 함).

[2026-07-22 저점 소급 리셋 — 용어 정정] 이 스크립트는 1분봉·3분봉 등 봉(캔들) 데이터를 전혀 안 쓴다.
LOW_SEARCH/LOW_CONFIRMED가 보는 "저점 이후 상승"은 "음봉→양봉 전환"이 아니라, POLL_SEC(기본 1초)
간격으로 찍히는 현재가(cur) 틱 값이 candidate_low보다 높아지는 초단위 가격 반전이다. 봉의 시가·종가
개념 자체가 이 스크립트에는 없다 — _tick_size()로 정의한 최소 호가단위 이상 오르고, 그 뒤 몇 초
동안 신저점이 안 나오면 확정한다(LOW_CONFIRM_SEC).
"""
import os
import sys
import json
import csv
import time
import traceback
from collections import deque
from pathlib import Path
from datetime import datetime

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

SNAP = Path(r"C:\stock_bot\IPC\live_micro_snapshot.json")
BOARD = Path(r"C:\stock_bot\data\micro_rank_board.json")
OUT_DIR = Path(r"C:\stock_bot\data\shadow\mf_1s_capture")
RESET_DIR = Path(r"C:\stock_bot\data\shadow\mf_reset_events")
LOG = Path(r"C:\stock_bot\data\LOG\mf_1s_capture.log")
LOCK = Path(r"C:\stock_bot\data\mf_1s_capture.lock")

POLL_SEC = float(os.environ.get("MF1S_POLL", "1.0"))
END_HM = os.environ.get("MF1S_END", "1035")            # 안전상한 — 이 시각 지나면 자동 종료(무한실행 방지)
LOCK_STALE_SEC = float(os.environ.get("MF1S_LOCK_STALE_SEC", "120"))   # 이 시간 넘게 안 갱신된 락은 죽은 것으로 간주
RESET_MAX_SEC = float(os.environ.get("MF1S_RESET_MAX_SEC", "60"))     # T0(저점 확정시각) 이후 관측 최대 길이
# [2026-07-22 저점 소급 리셋] MONEY_START_RAW는 저점 탐색 시작 신호일 뿐, T0가 아니다.
LOW_CONFIRM_SEC = float(os.environ.get("MF1S_LOW_CONFIRM_SEC", "2"))       # 저점 이후 이만큼 신저점 미갱신 + 상승해야 확정
LOW_SEARCH_MAX_SEC = float(os.environ.get("MF1S_LOW_SEARCH_MAX_SEC", "30"))  # 이 시간 안에 저점확정 못 하면 탐색 포기(IDLE 복귀)
# [2026-07-22 실측 성능보정] live_micro_snapshot.json은 broker가 종목을 지워주지 않아 당일 한 번이라도
# 등록됐던 종목이 전부 누적된다(실측 09:00 CAP=120인데 파일엔 1,559개). 루프 자체는 밀리지 않지만
# (실측 1559종목/루프 평균 28ms = POLL_SEC의 2.8%) raw CSV가 95분에 ~1.1GB로 불어난다(실측 투영).
# 캡틴/Money Flow가 실제로 보는 종목은 broker가 "방금" 갱신한(=지금 SetRealReg로 살아있는) 종목뿐이므로,
# 신선도(초 단위 ts 나이)로 걸러 죽은 과거 종목을 raw CSV에서 뺀다. 0=필터 끔(전체 기록, 예전 동작).
# 단, 이미 LOW_SEARCH/RESET 중인 종목은 신선도와 무관하게 무조건 계속 추적한다(중간에 놓치면 안 됨).
FRESH_SEC = float(os.environ.get("MF1S_FRESH_SEC", "60"))

# ── 기존 필드(값 계산 로직 무변경) ──
BASE_FIELDS = ["ts", "code", "current_price", "cum_vol", "che_str", "ask_tot", "bid_tot", "imb",
               "money_add_5s", "money_add_10s", "money_add_30s",
               "money_speed_5s", "money_speed_10s", "money_speed_30s",
               "che_delta_5s", "che_delta_10s", "money_start", "money_start_raw",
               # ★[REAL-SIDE 2026-07-22] 브로커 부호체결(FID15) 실측 누계 4필드 — Money Score
               #   소급 채점용 원자료(친구님 승인). 스냅샷에 없으면(브로커 구코드) 빈 값.
               "buy_vol_cum", "sell_vol_cum", "buy_money_cum", "sell_money_cum"]

# ── [2026-07-22 신규] 리셋형 매수우위 계측 필드 ──
RESET_FIELDS = [
    # [2026-07-22 저점 소급 리셋] 3개 시각 구분: 폭증최초감지 / 실제저점 / 저점상승전환확인
    "flow_detect_ts", "low_search_started",
    "candidate_low_ts", "candidate_low_price", "candidate_low_cum_vol", "candidate_low_che_str",
    "candidate_low_ask_tot", "candidate_low_bid_tot", "candidate_low_imb", "candidate_low_age_sec",
    "low_update_count", "low_confirm_ts", "low_confirm_delay_sec", "low_confirm_reason", "reset_backdated",
    "delta_cum_vol_from_low", "delta_che_str_from_low",
    "reset_id", "reset_ts", "elapsed_sec",
    "reset_price", "reset_low", "reset_high", "reset_cum_vol", "reset_che_str",
    "reset_ask_tot", "reset_bid_tot", "reset_imb",
    "burst_ratio_5s_30s", "burst_ratio_5s_10s",
    "money_ratio_5s_prev5s", "money_ratio_10s_prev10s", "money_ratio_30s_prev30s",
    "buy_exec_vol_reset", "sell_exec_vol_reset", "total_exec_vol_reset", "net_buy_exec_vol",
    "buy_exec_ratio", "sell_exec_ratio", "buy_sell_ratio",
    "buy_exec_value_reset", "sell_exec_value_reset", "total_exec_value_reset", "net_buy_exec_value",
    "buy_value_ratio", "buy_sell_value_ratio",
    "price_response_from_reset", "price_response_from_low", "mfe_from_reset", "mae_from_reset",
    "reset_low_break", "first_price_up_ts", "first_high_break_ts",
    "ask_tot_delta_reset", "bid_tot_delta_reset", "ask_depletion_ratio", "bid_support_ratio", "imb_reset_delta",
    "buy_dominance_sec", "sell_dominance_sec", "price_rising_sec", "ask_depletion_sec", "money_accel_sec",
    "reset_state", "dominance_class", "price_confirmed", "absorb_suspected", "failure_reason",
]
FIELDS = BASE_FIELDS + RESET_FIELDS

RESET_EVENT_FIELDS = [
    "date", "code", "reset_id", "reset_ts", "end_ts", "duration_sec", "reset_price",
    "flow_detect_ts", "low_confirm_ts", "low_confirm_delay_sec", "low_update_count",
    "burst_ratio_max", "money_add_5s_max", "money_add_10s_max", "money_add_30s_max",
    "buy_exec_vol_total", "sell_exec_vol_total", "buy_exec_ratio_max", "buy_sell_ratio_max",
    "net_buy_exec_vol_max", "buy_value_ratio_max", "buy_sell_value_ratio_max",
    "price_response_5s", "price_response_10s", "price_response_30s", "price_response_60s",
    "mfe_30s", "mae_30s", "mfe_60s", "mae_60s",
    "ask_depletion_max", "bid_support_max", "buy_dominance_max_sec",
    "price_confirmed", "absorb_suspected", "final_state", "failure_reason",
]

# ── per-code 계측 상태(프로세스 메모리 전용). micro_rank_engine의 money_flow 상태머신과 완전 별개. ──
_SEARCH = {}        # code -> 저점 탐색 중 dict (IDLE 다음 단계, 아직 리셋 아님)
_RESET = {}         # code -> 활성 리셋 1건 dict (저점 확정 후에만 존재)
_RESET_SEQ = {}     # code -> 누적 reset_id 카운터(당일)
_MONEY_HIST = {}    # code -> deque[(epoch, money_add_5s, money_add_10s, money_add_30s)], maxlen=40
_LAST_CUMVOL = {}   # code -> 마지막으로 관측된 cum_vol(역행 감지용)

_STATS = {"loops": 0, "codes_seen": set(), "resets_started": 0, "resets_closed": 0,
          "missing_board": 0, "buy_agg": 0, "sell_agg": 0, "raw_rows": 0, "event_rows": 0,
          "exceptions": 0, "vol_regress": 0, "search_started": 0, "search_confirmed": 0, "search_timeout": 0,
          "stale_skipped": 0}


# [2026-07-22 저점 소급 리셋] 한국 주식 최소 호가단위(2023년 개편 기준 — 공식문서 실시간 재검증은
# 못 했음, 통용 지식 기준이라는 한계를 명시). "저점보다 1틱 이상 상승"의 "1틱" 판정에 사용.
_TICK_TABLE = [(2000, 1), (5000, 5), (20000, 10), (50000, 50), (200000, 100), (500000, 500), (float("inf"), 1000)]


def _tick_size(price):
    if price is None or price <= 0:
        return 1.0
    for ceiling, tick in _TICK_TABLE:
        if price < ceiling:
            return float(tick)
    return 1000.0


def _log(m):
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8") as f:
            f.write(f"[{datetime.now():%H:%M:%S}] {m}\n")
    except Exception:
        pass
    print(m, flush=True)


def _safe_float(v, default=None):
    """None·문자열숫자·NaN·비정상값 방어 변환."""
    if v is None:
        return default
    try:
        f = float(v)
        if f != f or f in (float("inf"), float("-inf")):
            return default
        return f
    except Exception:
        return default


def _should_skip_stale(code, sc, now_epoch):
    """[2026-07-22 성능보정] True면 이번 틱은 raw CSV 기록을 건너뛴다.
    활성 추적 중(_SEARCH/_RESET)인 종목은 신선도와 무관하게 절대 스킵하지 않는다."""
    if FRESH_SEC <= 0 or code in _SEARCH or code in _RESET:
        return False
    age = _snap_age_sec(sc.get("ts"), now_epoch)
    return age is not None and age > FRESH_SEC


def _snap_age_sec(ts_str, now_epoch):
    """live_micro_snapshot.json 종목별 ts(마지막 실시간 갱신시각) 나이(초). 파싱 실패시 None(=신선 취급하지 않음)."""
    if not ts_str:
        return None
    try:
        return now_epoch - datetime.fromisoformat(ts_str).timestamp()
    except Exception:
        return None


def _money_start_raw(it):
    """micro_rank_engine_v1.py 761~763행 원시조건 재현(유지시간 확정 전 순간값). [기존, 무변경]"""
    try:
        a5 = it.get("money_add_5s")
        s5, s10, s30 = it.get("money_speed_5s"), it.get("money_speed_10s"), it.get("money_speed_30s")
        c5, c10 = it.get("che_delta_5s"), it.get("che_delta_10s")
        if a5 is None or s5 is None or s10 is None or s30 is None or c5 is None or c10 is None:
            return False
        return bool(a5 > 0 and s5 >= s10 >= s30 and c5 > 0 and c10 > 0)
    except Exception:
        return False


def _split_buy_sell(cum_vol, che_str):
    """[근사치] 장중 누적거래량 x 장중 누적체결강도로 누적 매수/매도 체결량을 역산.
    가정: che_str = 매수체결누적/매도체결누적*100 (통용 정의, 키움 공식문서로 재검증되지 않음).
    틱 단위 원시 매수/매도 방향 값이 아니다 — 모듈 docstring 참고."""
    cum_vol = _safe_float(cum_vol)
    che_str = _safe_float(che_str)
    if cum_vol is None or cum_vol < 0 or che_str is None or che_str < 0:
        return None, None
    denom = 100.0 + che_str
    if denom <= 0:
        return None, None
    return cum_vol * che_str / denom, cum_vol * 100.0 / denom


def _dominance_class(buy_exec_ratio):
    """[사후 분류 전용 — 실전 매수조건 아님] 지시서 8항 구간표 그대로."""
    if buy_exec_ratio is None:
        return ""
    if buy_exec_ratio < 0.50:
        return "매도우위"
    if buy_exec_ratio < 0.55:
        return "경계"
    if buy_exec_ratio < 0.60:
        return "약한매수우위"
    if buy_exec_ratio < 0.70:
        return "강한매수우위"
    return "매우강한매수우위"


def _start_search(now_epoch, now_iso):
    """[2026-07-22] FLOW_DETECTED(money_start_raw True) 발생 -> 저점 탐색 시작.
    아직 T0가 아니다. candidate_low_*는 첫 _update_search 호출에서 채워진다."""
    return {
        "flow_detect_ts": now_iso, "flow_detect_epoch": now_epoch,
        "candidate_low_ts": None, "candidate_low_epoch": None, "candidate_low_price": None,
        "candidate_low_cum_vol": None, "candidate_low_che_str": None,
        "candidate_low_ask_tot": None, "candidate_low_bid_tot": None, "candidate_low_imb": None,
        "low_update_count": 0, "no_new_low_streak": 0,
        "buffer": deque(maxlen=int(LOW_SEARCH_MAX_SEC) + 5),
    }


def _update_search(s, now_epoch, now_iso, cur, cum_vol, che, ask_tot, bid_tot, imb):
    """저점 탐색 매초 갱신. 반환: (row_fields, confirm_reason_or_None, expired_bool).
    가격만 최저값으로 갱신하고 cum_vol/che_str는 다른 시점 값을 섞는 일이 없도록
    candidate_low_* 전부를 항상 같은 틱에서 함께 갱신한다.
    ★용어: "상승 전환"은 봉(캔들)의 음봉->양봉 전환이 아니라 POLL_SEC 간격 틱 가격이
    candidate_low보다 최소 호가단위 이상 올라간 뒤 LOW_CONFIRM_SEC초 동안 신저점이 없는,
    순수 초단위 가격 반전이다. 이 스크립트에는 봉 시가/종가 개념이 없다."""
    out = {"flow_detect_ts": s["flow_detect_ts"], "low_search_started": True, "reset_state": "LOW_SEARCH"}
    if cur is not None:
        s["buffer"].append((now_epoch, now_iso, cur, cum_vol, che, ask_tot, bid_tot, imb))
        if s["candidate_low_price"] is None or cur < s["candidate_low_price"]:
            s.update(candidate_low_ts=now_iso, candidate_low_epoch=now_epoch, candidate_low_price=cur,
                     candidate_low_cum_vol=cum_vol, candidate_low_che_str=che,
                     candidate_low_ask_tot=ask_tot, candidate_low_bid_tot=bid_tot, candidate_low_imb=imb)
            s["low_update_count"] += 1
            s["no_new_low_streak"] = 0
        else:
            s["no_new_low_streak"] += 1

    low_price = s["candidate_low_price"]
    out.update(candidate_low_ts=s["candidate_low_ts"], candidate_low_price=low_price,
               candidate_low_cum_vol=s["candidate_low_cum_vol"], candidate_low_che_str=s["candidate_low_che_str"],
               candidate_low_ask_tot=s["candidate_low_ask_tot"], candidate_low_bid_tot=s["candidate_low_bid_tot"],
               candidate_low_imb=s["candidate_low_imb"], low_update_count=s["low_update_count"],
               candidate_low_age_sec=(round(now_epoch - s["candidate_low_epoch"], 1) if s["candidate_low_epoch"] is not None else None))

    confirm_reason = None
    if (cur is not None and low_price is not None
            and cur >= low_price + _tick_size(low_price)
            and s["no_new_low_streak"] >= LOW_CONFIRM_SEC):
        confirm_reason = f"no_new_low_{int(LOW_CONFIRM_SEC)}s_and_price_up_ge_1tick"

    expired = (confirm_reason is None) and ((now_epoch - s["flow_detect_epoch"]) >= LOW_SEARCH_MAX_SEC)
    return out, confirm_reason, expired


def _new_reset(code, s, confirm_epoch, confirm_iso, confirm_reason):
    """[2026-07-22 저점 소급 리셋] T0는 지금(confirm 시점)이 아니라 s에 보존된 candidate_low
    시점이다. reset_*는 전부 candidate_low 시점의 값으로 소급(backdate)한다 — 저점 확정은
    지금 확인했어도 계산 기준점은 실제 저점 시점 값을 그대로 쓴다."""
    _RESET_SEQ[code] = _RESET_SEQ.get(code, 0) + 1
    low_price = s["candidate_low_price"]
    low_epoch = s["candidate_low_epoch"]
    # [2026-07-22 보정] candidate_low ~ LOW_CONFIRMED 사이 buffer 전체를 samples로 이관(요약 안 함) —
    # 이전엔 high_since_low 하나로 뭉뚱그려 그 구간의 틱별 흐름을 잃었다. 이제 5초/10초 MFE/MAE 등
    # 사후 분석이 이 구간의 실제 초당 경로를 그대로 쓸 수 있다.
    samples = []
    running_high = running_low = low_price
    for (ep, _iso, px, *_rest) in s["buffer"]:
        if ep < low_epoch or px is None:
            continue
        if px > running_high:
            running_high = px
        if px < running_low:
            running_low = px
        samples.append((round(ep - low_epoch, 1), px, running_high, running_low))
    if not samples:
        samples = [(0.0, low_price, low_price, low_price)]
    high_since_low = running_high
    return {
        "reset_id": f"{code}_{_RESET_SEQ[code]}",
        "reset_ts": s["candidate_low_ts"], "reset_epoch": s["candidate_low_epoch"],
        "reset_price": low_price, "reset_low": low_price, "reset_high": high_since_low,
        "reset_cum_vol": s["candidate_low_cum_vol"], "reset_che_str": s["candidate_low_che_str"],
        "reset_ask_tot": s["candidate_low_ask_tot"], "reset_bid_tot": s["candidate_low_bid_tot"], "reset_imb": s["candidate_low_imb"],
        "flow_detect_ts": s["flow_detect_ts"], "low_confirm_ts": confirm_iso,
        "low_confirm_delay_sec": round(confirm_epoch - s["candidate_low_epoch"], 1),
        "low_confirm_reason": confirm_reason, "low_update_count": s["low_update_count"],
        # LOW_CONFIRMED 자체가 "저점보다 상승"을 조건으로 하므로 리셋 생성 시점엔 이미 recovered 상태다.
        "recovered": True, "pre_recover_low": low_price, "low_break": False,
        "first_price_up_ts": confirm_iso, "first_high_break_ts": None,
        "ever_buy_dominant": False,
        "buy_dominance_sec": 0, "sell_dominance_sec": 0, "price_rising_sec": 0,
        "ask_depletion_sec": 0, "money_accel_sec": 0,
        "prev_price": high_since_low,
        "burst_ratio_max": 0.0, "money_add_5s_max": 0.0, "money_add_10s_max": 0.0, "money_add_30s_max": 0.0,
        "buy_exec_ratio_max": 0.0, "buy_sell_ratio_max": 0.0, "net_buy_exec_vol_max": None,
        "buy_value_ratio_max": 0.0, "buy_sell_value_ratio_max": 0.0,
        "ask_depletion_max": 0.0, "bid_support_max": 0.0,
        "price_confirmed": False, "absorb_suspected": False, "failure_reason": "",
        "last_state": "RESET_STARTED",
        # (elapsed_sec, price, running_high, running_low) — 저점~확정 사이 buffer 전체 이관(위에서 구성).
        "samples": samples,
        "buy_exec_vol_reset": 0.0, "sell_exec_vol_reset": 0.0,
    }


def _update_reset(code, r, now_epoch, now_iso, cur, cum_vol, che, ask_tot, bid_tot, imb,
                   money_add_5s, money_add_10s, money_add_30s,
                   money_speed_5s, money_speed_10s, money_speed_30s):
    """T0(r) 대비 현재 시점 값 계산 + 상태 갱신. 반환: (row_fields_dict, still_active)."""
    out = {}
    elapsed = round(now_epoch - r["reset_epoch"], 1)
    out["reset_id"] = r["reset_id"]
    out["reset_ts"] = r["reset_ts"]
    out["elapsed_sec"] = elapsed
    out["reset_price"] = r["reset_price"]

    prev_high = r["reset_high"]
    if cur is not None:
        if r["reset_high"] is None or cur > r["reset_high"]:
            r["reset_high"] = cur
        if r["reset_low"] is None or cur < r["reset_low"]:
            r["reset_low"] = cur
    out["reset_low"] = r["reset_low"]
    out["reset_high"] = r["reset_high"]
    out["reset_cum_vol"] = r["reset_cum_vol"]
    out["reset_che_str"] = r["reset_che_str"]
    out["reset_ask_tot"] = r["reset_ask_tot"]
    out["reset_bid_tot"] = r["reset_bid_tot"]
    out["reset_imb"] = r["reset_imb"]

    # [2026-07-22 저점 소급 리셋] 검색단계 메타 그대로 전달 — candidate_low == reset_*(소급됐으므로 동일값)
    out["flow_detect_ts"] = r.get("flow_detect_ts")
    out["low_search_started"] = True
    out["candidate_low_ts"] = r["reset_ts"]
    out["candidate_low_price"] = r["reset_price"]
    out["candidate_low_cum_vol"] = r["reset_cum_vol"]
    out["candidate_low_che_str"] = r["reset_che_str"]
    out["candidate_low_ask_tot"] = r["reset_ask_tot"]
    out["candidate_low_bid_tot"] = r["reset_bid_tot"]
    out["candidate_low_imb"] = r["reset_imb"]
    out["candidate_low_age_sec"] = elapsed
    out["low_update_count"] = r.get("low_update_count")
    out["low_confirm_ts"] = r.get("low_confirm_ts")
    out["low_confirm_delay_sec"] = r.get("low_confirm_delay_sec")
    out["low_confirm_reason"] = r.get("low_confirm_reason")
    out["reset_backdated"] = True
    out["delta_cum_vol_from_low"] = (cum_vol - r["reset_cum_vol"]) if (cum_vol is not None and r["reset_cum_vol"] is not None) else None
    out["delta_che_str_from_low"] = (che - r["reset_che_str"]) if (che is not None and r["reset_che_str"] is not None) else None

    # 서지 배율(이미 board가 계산해준 money_speed_*를 그대로 조합만 — 새 계산 아님)
    eps = 1e-9
    burst_5_30 = (money_speed_5s / max(money_speed_30s, eps)) if (money_speed_5s is not None and money_speed_30s is not None) else None
    burst_5_10 = (money_speed_5s / max(money_speed_10s, eps)) if (money_speed_5s is not None and money_speed_10s is not None) else None
    out["burst_ratio_5s_30s"] = burst_5_30
    out["burst_ratio_5s_10s"] = burst_5_10
    if burst_5_30 is not None:
        r["burst_ratio_max"] = max(r["burst_ratio_max"], burst_5_30)
    for key, val in (("money_add_5s_max", money_add_5s), ("money_add_10s_max", money_add_10s), ("money_add_30s_max", money_add_30s)):
        if val is not None:
            r[key] = max(r[key], val)

    # 직전 동일길이 구간 대비 배율 — 이 스크립트 자체 히스토리로 계산(money_flow_board/micro_rank_engine 무접촉)
    hist = _MONEY_HIST.get(code)
    m5p = m10p = m30p = None
    if hist:
        for (ep, h5, h10, h30) in hist:
            age = now_epoch - ep
            if h5 is not None and 4.5 <= age < 5.5:
                m5p = h5
            if h10 is not None and 9.5 <= age < 10.5:
                m10p = h10
            if h30 is not None and 29.5 <= age < 30.5:
                m30p = h30
    out["money_ratio_5s_prev5s"] = (money_add_5s / max(m5p, eps)) if (money_add_5s is not None and m5p is not None) else None
    out["money_ratio_10s_prev10s"] = (money_add_10s / max(m10p, eps)) if (money_add_10s is not None and m10p is not None) else None
    out["money_ratio_30s_prev30s"] = (money_add_30s / max(m30p, eps)) if (money_add_30s is not None and m30p is not None) else None

    # ── [근사치] T0 이후 신규 매수/매도 체결량 (cum_vol x che_str 역산 차분) ──
    buy_now, sell_now = _split_buy_sell(cum_vol, che)
    buy_t0, sell_t0 = _split_buy_sell(r["reset_cum_vol"], r["reset_che_str"])
    buy_vol, sell_vol = r.get("buy_exec_vol_reset"), r.get("sell_exec_vol_reset")
    if buy_now is not None and buy_t0 is not None:
        buy_vol = max(0.0, buy_now - buy_t0)
        sell_vol = max(0.0, sell_now - sell_t0)
        r["buy_exec_vol_reset"], r["sell_exec_vol_reset"] = buy_vol, sell_vol
        if buy_vol > 0:
            _STATS["buy_agg"] += 1
        if sell_vol > 0:
            _STATS["sell_agg"] += 1

    total_vol = buy_ratio = sell_ratio = buy_sell_ratio = net_buy_vol = None
    if buy_vol is not None and sell_vol is not None:
        total_vol = buy_vol + sell_vol
        net_buy_vol = buy_vol - sell_vol
        if total_vol > 0:
            buy_ratio = buy_vol / total_vol
            sell_ratio = sell_vol / total_vol
        buy_sell_ratio = buy_vol / max(sell_vol, 1.0)
    out["buy_exec_vol_reset"] = buy_vol
    out["sell_exec_vol_reset"] = sell_vol
    out["total_exec_vol_reset"] = total_vol
    out["net_buy_exec_vol"] = net_buy_vol
    out["buy_exec_ratio"] = buy_ratio
    out["sell_exec_ratio"] = sell_ratio
    out["buy_sell_ratio"] = buy_sell_ratio

    # 거래대금(원) — [근사치] 체결량 역산치 x 현재가(구간 평균가 대용, 별도 원천 없음)
    buy_val = sell_val = total_val = net_buy_val = buy_vratio = buy_sell_vratio = None
    if buy_vol is not None and sell_vol is not None and cur:
        buy_val, sell_val = buy_vol * cur, sell_vol * cur
        total_val = buy_val + sell_val
        net_buy_val = buy_val - sell_val
        if total_val > 0:
            buy_vratio = buy_val / total_val
        buy_sell_vratio = buy_val / max(sell_val, 1.0)
    out["buy_exec_value_reset"] = buy_val
    out["sell_exec_value_reset"] = sell_val
    out["total_exec_value_reset"] = total_val
    out["net_buy_exec_value"] = net_buy_val
    out["buy_value_ratio"] = buy_vratio
    out["buy_sell_value_ratio"] = buy_sell_vratio
    if buy_ratio is not None:
        r["buy_exec_ratio_max"] = max(r["buy_exec_ratio_max"], buy_ratio)
    if buy_sell_ratio is not None:
        r["buy_sell_ratio_max"] = max(r["buy_sell_ratio_max"], buy_sell_ratio)
    if buy_vratio is not None:
        r["buy_value_ratio_max"] = max(r["buy_value_ratio_max"], buy_vratio)
    if buy_sell_vratio is not None:
        r["buy_sell_value_ratio_max"] = max(r["buy_sell_value_ratio_max"], buy_sell_vratio)
    if net_buy_vol is not None:
        r["net_buy_exec_vol_max"] = net_buy_vol if r["net_buy_exec_vol_max"] is None else max(r["net_buy_exec_vol_max"], net_buy_vol)

    # ── 가격 반응 ──
    rp = r["reset_price"]
    price_resp = (cur / rp - 1) if (cur and rp) else None
    price_resp_low = (cur / r["reset_low"] - 1) if (cur and r["reset_low"]) else None
    mfe = (r["reset_high"] / rp - 1) if (r["reset_high"] and rp) else None
    mae = (r["reset_low"] / rp - 1) if (r["reset_low"] and rp) else None
    out["price_response_from_reset"] = price_resp
    out["price_response_from_low"] = price_resp_low
    out["mfe_from_reset"] = mfe
    out["mae_from_reset"] = mae

    if cur is not None and rp is not None and cur > rp:
        if not r["recovered"]:
            r["recovered"] = True
            r["first_price_up_ts"] = now_iso
        if prev_high is not None and cur > prev_high and r["first_high_break_ts"] is None:
            r["first_high_break_ts"] = now_iso
    if r["recovered"] and cur is not None and cur <= r["pre_recover_low"]:
        if not r["low_break"]:
            # [2026-07-22 사례C 보정] 재이탈 발견 시점까지 우연히 스쳤던 PRICE_CONFIRMED도 소급 취소
            # ("가짜 반등 또는 FAILED, PRICE_CONFIRMED 금지" — 나중에 가짜였다고 밝혀지면 이전 확정도 무효).
            r["price_confirmed"] = False
        r["low_break"] = True
    if not r["recovered"] and cur is not None:
        r["pre_recover_low"] = min(r["pre_recover_low"], cur)
    out["reset_low_break"] = r["low_break"]
    out["first_price_up_ts"] = r["first_price_up_ts"]
    out["first_high_break_ts"] = r["first_high_break_ts"]
    r["prev_price"] = cur if cur is not None else r["prev_price"]

    # ── 호가 반응 ──
    ask_delta = (ask_tot - r["reset_ask_tot"]) if (ask_tot is not None and r["reset_ask_tot"] is not None) else None
    bid_delta = (bid_tot - r["reset_bid_tot"]) if (bid_tot is not None and r["reset_bid_tot"] is not None) else None
    ask_deplete = ((r["reset_ask_tot"] - ask_tot) / max(r["reset_ask_tot"], 1.0)) if (ask_tot is not None and r["reset_ask_tot"] is not None) else None
    bid_support = (bid_tot / max(r["reset_bid_tot"], 1.0)) if (bid_tot is not None and r["reset_bid_tot"] is not None) else None
    imb_delta = (imb - r["reset_imb"]) if (imb is not None and r["reset_imb"] is not None) else None
    out["ask_tot_delta_reset"] = ask_delta
    out["bid_tot_delta_reset"] = bid_delta
    out["ask_depletion_ratio"] = ask_deplete
    out["bid_support_ratio"] = bid_support
    out["imb_reset_delta"] = imb_delta
    if ask_deplete is not None:
        r["ask_depletion_max"] = max(r["ask_depletion_max"], ask_deplete)
    if bid_support is not None:
        r["bid_support_max"] = max(r["bid_support_max"], bid_support)

    # ── 지속시간(이번 초가 조건을 만족하면 +1) ──
    if buy_ratio is not None and buy_ratio >= 0.5:
        r["buy_dominance_sec"] += 1
    if sell_ratio is not None and sell_ratio > 0.5:
        r["sell_dominance_sec"] += 1
    if price_resp is not None and price_resp > 0:
        r["price_rising_sec"] += 1
    if ask_deplete is not None and ask_deplete > 0:
        r["ask_depletion_sec"] += 1
    if money_add_5s is not None and money_add_10s is not None and money_add_5s > money_add_10s / 2.0:
        r["money_accel_sec"] += 1
    out["buy_dominance_sec"] = r["buy_dominance_sec"]
    out["sell_dominance_sec"] = r["sell_dominance_sec"]
    out["price_rising_sec"] = r["price_rising_sec"]
    out["ask_depletion_sec"] = r["ask_depletion_sec"]
    out["money_accel_sec"] = r["money_accel_sec"]

    # ── 상태(현재 순간 재분류, 매초 갱신) ──
    # [2026-07-22 사례C 보정] 저점 재이탈(가짜반등)이 한 번이라도 일어나면 이 리셋은 영구 FAILED로
    # 잠근다 — 이후 틱에서 buy_sell_ratio가 우연히 다시 좋아 보여도 PRICE_CONFIRMED로 되돌아가지 않는다.
    if r["low_break"]:
        state = "FAILED"
        if not r["failure_reason"]:
            r["failure_reason"] = "low_break"
        absorb_now = False
    else:
        absorb_now = bool(buy_sell_ratio is not None and buy_sell_ratio >= 1.2
                           and price_resp is not None and price_resp <= 0
                           and ask_delta is not None and ask_delta >= 0)
        r["absorb_suspected"] = r["absorb_suspected"] or absorb_now
        price_confirmed_now = bool(buy_sell_ratio is not None and buy_sell_ratio >= 1.2
                                    and price_resp is not None and price_resp > 0
                                    and ask_deplete is not None and ask_deplete > 0)
        r["price_confirmed"] = r["price_confirmed"] or price_confirmed_now
        if price_confirmed_now:
            state = "PRICE_CONFIRMED"
            r["ever_buy_dominant"] = True
        elif buy_sell_ratio is not None and buy_sell_ratio >= 1.2:
            state = "BUY_DOMINANT"
            r["ever_buy_dominant"] = True
        elif buy_sell_ratio is not None and buy_sell_ratio < 1.0:
            if r["ever_buy_dominant"]:
                state = "FAILED"
                if not r["failure_reason"]:
                    r["failure_reason"] = "buy_dominance_lost"
            else:
                state = "SELL_DOMINANT"
        elif buy_sell_ratio is not None:
            state = "BALANCED"
        else:
            state = r["last_state"]
    r["last_state"] = state
    out["reset_state"] = state
    out["dominance_class"] = _dominance_class(buy_ratio)
    out["price_confirmed"] = r["price_confirmed"]
    out["absorb_suspected"] = r["absorb_suspected"]
    out["failure_reason"] = r["failure_reason"]

    r["samples"].append((elapsed, cur, r["reset_high"], r["reset_low"]))
    return out, elapsed < RESET_MAX_SEC


def _finalize_reset(r, now_iso, now_epoch):
    """RESET_MAX_SEC 도달(또는 장 종료) 시 mf_reset_events 요약 1행 생성.
    duration_sec은 호출측이 넘긴 now_epoch 기준(실시간 time.time()을 여기서 다시 부르지 않음
    - main() 루프가 쓰는 now_epoch과 동일 기준으로 맞춰야 값이 일관됨)."""
    def _price_at(mark):
        best = None
        for (el, px, hi, lo) in r["samples"]:
            if el <= mark:
                best = px
            else:
                break
        return best

    def _mfe_mae(window):
        pts = [(hi, lo) for (el, px, hi, lo) in r["samples"] if el <= window]
        if not pts or not r["reset_price"]:
            return None, None
        highs = [p[0] for p in pts if p[0] is not None]
        lows = [p[1] for p in pts if p[1] is not None]
        if not highs or not lows:
            return None, None
        return (max(highs) / r["reset_price"] - 1), (min(lows) / r["reset_price"] - 1)

    rp = r["reset_price"]
    p5, p10, p30, p60 = (_price_at(5), _price_at(10), _price_at(30), _price_at(60))
    pr5 = (p5 / rp - 1) if (p5 and rp) else None
    pr10 = (p10 / rp - 1) if (p10 and rp) else None
    pr30 = (p30 / rp - 1) if (p30 and rp) else None
    pr60 = (p60 / rp - 1) if (p60 and rp) else None
    mfe30, mae30 = _mfe_mae(30)
    mfe60, mae60 = _mfe_mae(60)

    return {
        "date": datetime.now().strftime("%Y%m%d"), "code": None, "reset_id": r["reset_id"],
        "reset_ts": r["reset_ts"], "end_ts": now_iso,
        "duration_sec": round(now_epoch - r["reset_epoch"], 1), "reset_price": rp,
        "flow_detect_ts": r.get("flow_detect_ts"), "low_confirm_ts": r.get("low_confirm_ts"),
        "low_confirm_delay_sec": r.get("low_confirm_delay_sec"), "low_update_count": r.get("low_update_count"),
        "burst_ratio_max": r["burst_ratio_max"],
        "money_add_5s_max": r["money_add_5s_max"], "money_add_10s_max": r["money_add_10s_max"],
        "money_add_30s_max": r["money_add_30s_max"],
        "buy_exec_vol_total": r.get("buy_exec_vol_reset"), "sell_exec_vol_total": r.get("sell_exec_vol_reset"),
        "buy_exec_ratio_max": r["buy_exec_ratio_max"], "buy_sell_ratio_max": r["buy_sell_ratio_max"],
        "net_buy_exec_vol_max": r["net_buy_exec_vol_max"],
        "buy_value_ratio_max": r["buy_value_ratio_max"], "buy_sell_value_ratio_max": r["buy_sell_value_ratio_max"],
        "price_response_5s": pr5, "price_response_10s": pr10, "price_response_30s": pr30, "price_response_60s": pr60,
        "mfe_30s": mfe30, "mae_30s": mae30, "mfe_60s": mfe60, "mae_60s": mae60,
        "ask_depletion_max": r["ask_depletion_max"], "bid_support_max": r["bid_support_max"],
        "buy_dominance_max_sec": r["buy_dominance_sec"],
        "price_confirmed": r["price_confirmed"], "absorb_suspected": r["absorb_suspected"],
        "final_state": r["last_state"], "failure_reason": r["failure_reason"],
    }


def _acquire_lock():
    try:
        if LOCK.exists() and (time.time() - LOCK.stat().st_mtime) < LOCK_STALE_SEC:
            return False
    except Exception:
        pass
    try:
        LOCK.parent.mkdir(parents=True, exist_ok=True)
        LOCK.write_text(str(os.getpid()), encoding="utf-8")
    except Exception:
        pass
    return True


def _touch_lock():
    try:
        LOCK.write_text(str(os.getpid()), encoding="utf-8")
    except Exception:
        pass


def _release_lock():
    try:
        LOCK.unlink()
    except Exception:
        pass


def _process_code(code, sc, board_map, now_epoch, now_iso, raw_writer, event_writer):
    """종목 1개 처리: 기존 필드 + 리셋형 계측 필드 계산 후 raw csv 1행 기록.
    리셋이 이번에 종료됐으면 event csv에도 1행 기록. 예외는 이 함수 밖으로 전파하지 않는다."""
    it = board_map.get(code)
    if it is None:
        _STATS["missing_board"] += 1
        it = {}

    cur = _safe_float(sc.get("cur"))
    cum_vol = _safe_float(sc.get("cum_vol"))
    che = _safe_float(sc.get("che_str"))
    ask_tot = _safe_float(sc.get("ask_tot"))
    bid_tot = _safe_float(sc.get("bid_tot"))
    imb = _safe_float(sc.get("imb"))

    # cum_vol 역행(장중리셋/오류) 방어 — 새로 리셋을 걸지 않고 이번 틱만 스킵 표시
    last_cv = _LAST_CUMVOL.get(code)
    vol_regressed = bool(last_cv is not None and cum_vol is not None and cum_vol < last_cv)
    if vol_regressed:
        _STATS["vol_regress"] += 1
        _log(f"[VOL-REGRESS] {code} 누적거래량 역행({last_cv:.0f}->{cum_vol:.0f}) - 이번 틱 매수/매도 역산 스킵")
    if cum_vol is not None:
        _LAST_CUMVOL[code] = cum_vol

    money_add_5s = _safe_float(it.get("money_add_5s"))
    money_add_10s = _safe_float(it.get("money_add_10s"))
    money_add_30s = _safe_float(it.get("money_add_30s"))
    money_speed_5s = _safe_float(it.get("money_speed_5s"))
    money_speed_10s = _safe_float(it.get("money_speed_10s"))
    money_speed_30s = _safe_float(it.get("money_speed_30s"))
    che_delta_5s = _safe_float(it.get("che_delta_5s"))
    che_delta_10s = _safe_float(it.get("che_delta_10s"))
    money_start_raw_now = _money_start_raw(it)

    row = {
        "ts": now_iso, "code": code, "current_price": cur, "cum_vol": cum_vol, "che_str": che,
        "ask_tot": ask_tot, "bid_tot": bid_tot, "imb": imb,
        "money_add_5s": money_add_5s, "money_add_10s": money_add_10s, "money_add_30s": money_add_30s,
        "money_speed_5s": money_speed_5s, "money_speed_10s": money_speed_10s, "money_speed_30s": money_speed_30s,
        "che_delta_5s": che_delta_5s, "che_delta_10s": che_delta_10s,
        "money_start": it.get("money_start"), "money_start_raw": money_start_raw_now,
        # ★[REAL-SIDE 2026-07-22] 실체결 방향별 누계(브로커 FID15) — 있으면 그대로, 없으면 None
        "buy_vol_cum": _safe_float(sc.get("buy_vol_cum")),
        "sell_vol_cum": _safe_float(sc.get("sell_vol_cum")),
        "buy_money_cum": _safe_float(sc.get("buy_money_cum")),
        "sell_money_cum": _safe_float(sc.get("sell_money_cum")),
    }
    for k in RESET_FIELDS:
        row[k] = None

    # ── 히스토리 버퍼 갱신(직전 동일길이 구간 대비 배율용) ──
    hist = _MONEY_HIST.setdefault(code, deque(maxlen=40))
    hist.append((now_epoch, money_add_5s, money_add_10s, money_add_30s))

    # ── [2026-07-22 저점 소급 리셋] IDLE -> LOW_SEARCH -> (LOW_CONFIRMED로 소급 리셋) -> RESET_STARTED ──
    # MONEY_START_RAW 발생 즉시 T0로 확정하지 않는다 — 저점 탐색부터 시작하고, 저점이 확정되면
    # 그 저점 시점 값으로 소급(backdate)해서 리셋을 만든다.
    r = _RESET.get(code)
    if r is None:
        s = _SEARCH.get(code)
        if s is None and money_start_raw_now and not vol_regressed and cur is not None:
            s = _start_search(now_epoch, now_iso)
            _SEARCH[code] = s
            _STATS["search_started"] += 1
        if s is not None:
            try:
                search_out, confirm_reason, expired = _update_search(
                    s, now_epoch, now_iso, cur, cum_vol, che, ask_tot, bid_tot, imb)
                row.update(search_out)
                if confirm_reason:
                    r = _new_reset(code, s, now_epoch, now_iso, confirm_reason)
                    _RESET[code] = r
                    del _SEARCH[code]
                    _STATS["resets_started"] += 1
                    _STATS["search_confirmed"] += 1
                elif expired:
                    _log(f"[LOW-SEARCH-TIMEOUT] {code} {LOW_SEARCH_MAX_SEC:.0f}초 안에 저점 미확정 "
                         f"(폭증최초감지={s['flow_detect_ts']}, 최종후보저점={s['candidate_low_price']}) - IDLE 복귀")
                    del _SEARCH[code]
                    _STATS["search_timeout"] += 1
            except Exception as e:
                _STATS["exceptions"] += 1
                _log(f"[SEARCH-ERR] {code} 저점탐색 예외(이 종목 이번 틱만 스킵): {e}")

    if r is not None:
        try:
            reset_out, still_active = _update_reset(
                code, r, now_epoch, now_iso, cur, cum_vol, che, ask_tot, bid_tot, imb,
                money_add_5s, money_add_10s, money_add_30s, money_speed_5s, money_speed_10s, money_speed_30s)
            row.update(reset_out)
            if not still_active:
                ev = _finalize_reset(r, now_iso, now_epoch)
                ev["code"] = code
                event_writer.writerow(ev)
                _STATS["event_rows"] += 1
                _STATS["resets_closed"] += 1
                del _RESET[code]
        except Exception as e:
            _STATS["exceptions"] += 1
            _log(f"[RESET-ERR] {code} 리셋 계측 예외(이 종목 이번 틱만 스킵): {e}")

    raw_writer.writerow(row)
    _STATS["raw_rows"] += 1


def main():
    if not _acquire_lock():
        _log("mf_1s_capture 이미 실행중(lock) -> 이번 기동 skip(중복실행 차단)")
        return

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    RESET_DIR.mkdir(parents=True, exist_ok=True)
    today = datetime.now().strftime("%Y%m%d")
    out_path = OUT_DIR / f"mf_1s_{today}.csv"
    event_path = RESET_DIR / f"mf_reset_events_{today}.csv"
    is_new_raw = not out_path.exists()
    is_new_ev = not event_path.exists()

    f_raw = out_path.open("a", encoding="utf-8-sig", newline="")
    w_raw = csv.DictWriter(f_raw, fieldnames=FIELDS, extrasaction="ignore")
    if is_new_raw:
        w_raw.writeheader()

    f_ev = event_path.open("a", encoding="utf-8-sig", newline="")
    w_ev = csv.DictWriter(f_ev, fieldnames=RESET_EVENT_FIELDS, extrasaction="ignore")
    if is_new_ev:
        w_ev.writeheader()

    _log(f"mf_1s_capture(+리셋형계측) 시작 - 읽기전용.TR0.SetRealReg0. "
         f"raw={out_path} event={event_path} 자동종료={END_HM} RESET_MAX_SEC={RESET_MAX_SEC}")

    try:
        while True:
            loop_t0 = time.time()
            hm_now = datetime.now().strftime("%H%M")
            if hm_now > END_HM:
                _log(f"종료시각({END_HM}) 도달 - 캡처 종료(장종료후 데이터 정지)")
                break

            try:
                snap = json.loads(SNAP.read_text(encoding="utf-8-sig"))
            except Exception as e:
                _STATS["exceptions"] += 1
                _log(f"[SNAP] 읽기 실패(이번 초 스킵): {e}")
                snap = None

            board_map = {}
            try:
                board = json.loads(BOARD.read_text(encoding="utf-8-sig"))
                for it in (board.get("all_items") or []):
                    c = it.get("code")
                    if c:
                        board_map[c] = it
            except Exception as e:
                _STATS["exceptions"] += 1
                if _STATS["loops"] % 60 == 0:
                    _log(f"[BOARD] 읽기 실패(money_flow 필드 없이 진행): {e}")

            if snap:
                now_iso = snap.get("ts") or datetime.now().isoformat()
                now_epoch = time.time()
                codes = snap.get("codes") or {}
                for code, sc in codes.items():
                    if not code or not isinstance(sc, dict):
                        continue
                    # [2026-07-22 실측 성능보정] 신선도 필터 — broker가 더 이상 실시간 갱신 안 하는
                    # (=CAP 밖으로 빠진) 종목은 raw CSV에서 제외. 실전 캡틴/Money Flow 로직은 무접촉.
                    if _should_skip_stale(code, sc, now_epoch):
                        _STATS["stale_skipped"] += 1
                        continue
                    _STATS["codes_seen"].add(code)
                    try:
                        _process_code(code, sc, board_map, now_epoch, now_iso, w_raw, w_ev)
                    except Exception as e:
                        _STATS["exceptions"] += 1
                        _log(f"[CODE-ERR] {code} 처리 예외(스킵): {e}\n{traceback.format_exc(limit=2)}")
                f_raw.flush()
                f_ev.flush()

            _STATS["loops"] += 1
            if _STATS["loops"] % 60 == 0:
                _touch_lock()
                _log(f"[진행] loop={_STATS['loops']} 종목수={len(_STATS['codes_seen'])} "
                     f"신선도필터skip={_STATS['stale_skipped']} "
                     f"raw행={_STATS['raw_rows']} 저점탐색시작={_STATS['search_started']} "
                     f"저점확정={_STATS['search_confirmed']} 저점탐색포기={_STATS['search_timeout']} "
                     f"리셋시작={_STATS['resets_started']} 리셋종료={_STATS['event_rows']} 예외={_STATS['exceptions']}")

            elapsed = time.time() - loop_t0
            time.sleep(max(0.05, POLL_SEC - elapsed))
    except Exception as e:
        _STATS["exceptions"] += 1
        _log(f"[FATAL] 메인루프 예외: {e}\n{traceback.format_exc(limit=4)}")
    finally:
        # 장 종료/예외 종료 시 아직 안 끝난 리셋들도 요약 1행씩 강제 flush
        now_iso = datetime.now().isoformat()
        now_epoch = time.time()
        for code, r in list(_RESET.items()):
            try:
                ev = _finalize_reset(r, now_iso, now_epoch)
                ev["code"] = code
                ev["failure_reason"] = ev["failure_reason"] or "flush_on_shutdown"
                w_ev.writerow(ev)
                _STATS["event_rows"] += 1
            except Exception:
                _STATS["exceptions"] += 1
        try:
            f_raw.close()
        except Exception:
            pass
        try:
            f_ev.close()
        except Exception:
            pass
        _log(f"[종료요약] loop={_STATS['loops']} 처리종목수={len(_STATS['codes_seen'])} "
             f"신선도필터skip={_STATS['stale_skipped']} "
             f"raw행={_STATS['raw_rows']} board누락={_STATS['missing_board']} "
             f"저점탐색시작={_STATS['search_started']} 저점확정={_STATS['search_confirmed']} "
             f"저점탐색포기={_STATS['search_timeout']} "
             f"리셋시작={_STATS['resets_started']} 리셋종료={_STATS['event_rows']} "
             f"매수집계>0={_STATS['buy_agg']} 매도집계>0={_STATS['sell_agg']} "
             f"누적거래량역행={_STATS['vol_regress']} 예외={_STATS['exceptions']}")
        _release_lock()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
    except Exception as e:
        _log(f"[FATAL-TOP] 치명 오류: {e}\n{traceback.format_exc(limit=4)}")
        _release_lock()
