# -*- coding: utf-8 -*-
"""유튜브 종가베팅 조건 전용 독립 그림자.

조건은 네 가지뿐이다.
1) 15:00 <= 시각 <= 15:20
2) LRL(20) > LRL(40)
3) 현재가 > MA200 이고 현재가 > MA400
4) 당일 누적거래량 > 키움 opt10001 유통주식수

생산 매매·계좌·포지션 모듈을 import하지 않는다. 조건 충족 시 최초 관측
가격만 기록하고 다음 거래일 일봉 시가로 채점한다.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import os
import sys
import time
from datetime import datetime, time as clock_time
from pathlib import Path
from typing import Any, Iterable


BASE = Path(r"C:\stock_bot")
RUN_DIR = BASE / "RUN"
EOD_PATH = BASE / "data" / "eod_daily_bars.csv"
OUT_DIR = BASE / "data" / "shadow" / "youtube_eod"
HISTORY_PATH = OUT_DIR / "history_450.json.gz"
FLOAT_PATH = OUT_DIR / "float_shares.json"
SIGNALS_PATH = OUT_DIR / "signals.jsonl"
GRADED_PATH = OUT_DIR / "graded.csv"
SESSION_DIR = OUT_DIR / "sessions"
LOG_PATH = BASE / "data" / "LOG" / "youtube_eod_shadow.log"
EOD_DONE_PATH = BASE / "LOG" / "collect_eod.done"

REGISTER_START = clock_time(14, 58, 0)
WATCH_START = clock_time(15, 0, 0)
WATCH_END = clock_time(15, 20, 0)
POLL_SEC = 6.0
# ★[2026-08-13 친구님 지시 "15:15~15:26 실전 종가매수 opt10032 최우선"]
#   8/13 실측: 이 그림자가 1,545종목 묶음읽기(8초 타임아웃)와 15:20 화면 16개
#   일괄해제를 돌리는 동안 실전 opt10032 가 같은 IPC 에서 굶었다.
#   보호창 동안 그림자는 IPC 호출(묶음읽기·해제)을 전부 멈춘다. 관찰 손실은
#   15:15~15:20 5분뿐이고 주문경로는 원래 없음(order_path=NONE).
LIVE_EOD_PRIORITY_START = clock_time(15, 15, 0)
LIVE_EOD_PRIORITY_END = clock_time(15, 26, 0)


def in_live_eod_priority(moment) -> bool:
    """실전 종가매수 보호창 판정 — 이 창에서는 그림자가 IPC 를 쓰지 않는다."""
    return LIVE_EOD_PRIORITY_START <= moment <= LIVE_EOD_PRIORITY_END
SCREEN_START = 9600
SCREEN_CHUNK = 100
REGISTER_RETRIES = 3
REGISTER_RETRY_SEC = 1.0
TR_CHUNK = 15
MIN_PREVIOUS_CLOSES = 399
MAX_HISTORY = 450
REAL_FIDS = [10, 13]  # 현재가, 누적거래량
EOD_WAIT_TIMEOUT_SEC = float(os.environ.get(
    "YOUTUBE_EOD_WAIT_TIMEOUT_SEC", "12000"
))
EOD_WAIT_POLL_SEC = 30.0


def _now() -> datetime:
    return datetime.now()


def _log(message: str) -> None:
    line = f"[{_now().isoformat(timespec='seconds')}] {message}"
    print(line, flush=True)
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LOG_PATH.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    except Exception:
        pass


def _atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _atomic_gzip_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with gzip.open(tmp, "wt", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, path)


def _load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return default


def _load_gzip_json(path: Path, default: Any) -> Any:
    try:
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            return json.load(handle)
    except Exception:
        return default


def _number(value: Any) -> float:
    text = str(value or "").strip().replace(",", "")
    if not text:
        return 0.0
    try:
        return abs(float(text))
    except (TypeError, ValueError):
        return 0.0


def _eod_done_for_date(payload: Any, day: str) -> bool:
    """Accept only today's successful collector done flag; never use mtime."""
    if not isinstance(payload, dict):
        return False
    done_day = str(payload.get("done_at") or "")[:10].replace("-", "")
    return (
        done_day == day
        and str(payload.get("status") or "").upper() == "OK"
        and float(payload.get("qa_score") or 0.0) >= 90.0
        and int(payload.get("codes") or 0) > 0
    )


def _wait_for_eod_done() -> bool:
    """Wait at most 200 minutes, then skip the nonessential shadow prepare."""
    day = _now().strftime("%Y%m%d")
    deadline = time.monotonic() + EOD_WAIT_TIMEOUT_SEC
    next_notice = 0.0
    while True:
        payload = _load_json(EOD_DONE_PATH, {})
        if _eod_done_for_date(payload, day):
            _log(
                "일봉 완료 확인: collect_eod.done "
                f"status=OK qa={payload.get('qa_score')} codes={payload.get('codes')}"
            )
            return True
        now_mono = time.monotonic()
        if now_mono >= deadline:
            _log(
                f"일봉 완료 대기 {int(EOD_WAIT_TIMEOUT_SEC / 60)}분 초과: "
                "youtube prepare 건너뜀 "
                "(브로커 TR 충돌 방지)"
            )
            return False
        if now_mono >= next_notice:
            remaining = int((deadline - now_mono) / 60)
            _log(f"일봉 완료 대기 중: collect_eod.done 미확인, 최대 {remaining}분")
            next_notice = now_mono + 600.0
        time.sleep(min(EOD_WAIT_POLL_SEC, max(0.0, deadline - now_mono)))


def _chunks(values: list[str], size: int) -> Iterable[list[str]]:
    for start in range(0, len(values), size):
        yield values[start:start + size]


def lrl_endpoint(values: list[float]) -> float:
    """최소제곱 선형회귀선의 마지막 x 지점 값."""
    count = len(values)
    if count < 2:
        raise ValueError("LRL requires at least two values")
    x_mean = (count - 1) / 2.0
    y_mean = sum(values) / count
    denominator = sum((index - x_mean) ** 2 for index in range(count))
    slope = sum(
        (index - x_mean) * (value - y_mean)
        for index, value in enumerate(values)
    ) / denominator
    return y_mean + slope * ((count - 1) - x_mean)


def evaluate_video_condition(
    previous_closes: list[float], current_price: float,
    cumulative_volume: float, float_shares: float,
) -> dict[str, Any]:
    """유튜브 네 조건을 그대로 계산한다. 자료 부족은 통과시키지 않는다."""
    if len(previous_closes) < MIN_PREVIOUS_CLOSES:
        return {"passed": False, "reason": "history_lt_399"}
    if current_price <= 0:
        return {"passed": False, "reason": "current_price_missing"}
    if cumulative_volume <= 0:
        return {"passed": False, "reason": "cumulative_volume_missing"}
    if float_shares <= 0:
        return {"passed": False, "reason": "float_shares_missing"}

    forming = [float(value) for value in previous_closes[-MIN_PREVIOUS_CLOSES:]]
    forming.append(float(current_price))
    lrl20 = lrl_endpoint(forming[-20:])
    lrl40 = lrl_endpoint(forming[-40:])
    ma200 = sum(forming[-200:]) / 200.0
    ma400 = sum(forming[-400:]) / 400.0
    gates = {
        "lrl_red": lrl20 > lrl40,
        "above_ma200": current_price > ma200,
        "above_ma400": current_price > ma400,
        "volume_over_float": cumulative_volume > float_shares,
    }
    return {
        "passed": all(gates.values()),
        "reason": "passed" if all(gates.values()) else "gate_failed",
        "gates": gates,
        "lrl20": round(lrl20, 6),
        "lrl40": round(lrl40, 6),
        "ma200": round(ma200, 6),
        "ma400": round(ma400, 6),
        "current_price": current_price,
        "cumulative_volume": cumulative_volume,
        "float_shares": float_shares,
        "turnover_float": round(cumulative_volume / float_shares, 6),
    }


def _read_local_eod() -> tuple[dict[str, str], dict[str, list[list[Any]]]]:
    names: dict[str, str] = {}
    histories: dict[str, list[list[Any]]] = {}
    if not EOD_PATH.exists():
        return names, histories
    with EOD_PATH.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            if str(row.get("market", "")).upper() != "KOSDAQ":
                continue
            code = str(row.get("code", "")).strip().zfill(6)
            date = str(row.get("date", "")).strip()
            close = _number(row.get("close"))
            if len(code) != 6 or len(date) != 8 or close <= 0:
                continue
            names[code] = str(row.get("name", "")).strip()
            histories.setdefault(code, []).append([date, close])
    for code in histories:
        histories[code] = _merge_history([], histories[code])
    return names, histories


def _merge_history(existing: list[list[Any]], incoming: list[list[Any]]) -> list[list[Any]]:
    merged: dict[str, float] = {}
    for item in list(existing or []) + list(incoming or []):
        try:
            date = str(item[0]).strip()
            close = _number(item[1])
        except Exception:
            continue
        if len(date) == 8 and close > 0:
            merged[date] = close
    return [[date, merged[date]] for date in sorted(merged)][-MAX_HISTORY:]


def _broker_client():
    if str(RUN_DIR) not in sys.path:
        sys.path.insert(0, str(RUN_DIR))
    from broker_client import BrokerClient
    return BrokerClient()


def _batch_collect(
    broker, codes: list[str], tr_code: str, input_template: dict[str, str],
    output_fields: list[str], rqname: str,
) -> Iterable[dict[str, Any]]:
    chunks = list(_chunks(codes, TR_CHUNK))
    for index, chunk in enumerate(chunks, start=1):
        response = broker.batch_tr(
            tr_code=tr_code,
            codes=chunk,
            input_template=input_template,
            output_fields=output_fields,
            rqname_template=rqname,
            screen_no_rotate=[str(2200 + (index % 40))],
            per_request_timeout_sec=10.0,
            batch_timeout_sec=120.0,
            client_timeout_sec=125.0,
        )
        if response.get("status") != "OK":
            _log(f"{tr_code} chunk {index}/{len(chunks)} 실패: {response.get('error')}")
            continue
        data = response.get("data") or {}
        for result in data.get("results") or []:
            yield result
        if index % 10 == 0 or index == len(chunks):
            summary = data.get("summary") or {}
            _log(
                f"{tr_code} {index}/{len(chunks)} chunks "
                f"OK={summary.get('ok', 0)} ERR={summary.get('error', 0)}"
            )


def mode_prepare() -> int:
    now = _now()
    if clock_time(9, 0) <= now.time() <= clock_time(15, 30):
        _log("장중 전수 TR 수집 금지: prepare 중단")
        return 2
    if not _wait_for_eod_done():
        return 2
    broker = _broker_client()
    if not broker.alive():
        _log("broker DEAD: prepare 중단")
        return 2

    names, local_histories = _read_local_eod()
    cache = _load_gzip_json(HISTORY_PATH, {"codes": {}})
    cached_codes = cache.get("codes") or {}
    universe = sorted(names)
    histories: dict[str, list[list[Any]]] = {}
    for code in universe:
        histories[code] = _merge_history(
            (cached_codes.get(code) or {}).get("closes") or [],
            local_histories.get(code) or [],
        )

    missing = [code for code in universe if len(histories.get(code) or []) < MIN_PREVIOUS_CLOSES]
    _log(f"prepare universe={len(universe)} history_missing={len(missing)}")
    processed = 0
    for result in _batch_collect(
        broker, missing, "opt10081",
        {"종목코드": "{CODE}", "기준일자": "", "수정주가구분": "1"},
        ["일자", "현재가"], "youtube_eod_history",
    ):
        processed += 1
        code = str(result.get("code", "")).zfill(6)
        if result.get("status") != "OK":
            continue
        records = ((result.get("data") or {}).get("records") or [])
        incoming = [[row.get("일자"), _number(row.get("현재가"))] for row in records]
        histories[code] = _merge_history(histories.get(code) or [], incoming)
        if processed % 150 == 0:
            _atomic_gzip_json(HISTORY_PATH, {
                "generated_at": _now().isoformat(),
                "source": "kiwoom_opt10081_adjusted_and_local_eod",
                "codes": {
                    item: {"name": names.get(item, ""), "closes": histories.get(item, [])}
                    for item in universe
                },
            })

    history_payload = {
        "generated_at": _now().isoformat(),
        "source": "kiwoom_opt10081_adjusted_and_local_eod",
        "codes": {
            code: {"name": names.get(code, ""), "closes": histories.get(code, [])}
            for code in universe
        },
    }
    _atomic_gzip_json(HISTORY_PATH, history_payload)

    floats: dict[str, dict[str, Any]] = {}
    for result in _batch_collect(
        broker, universe, "opt10001", {"종목코드": "{CODE}"},
        ["종목명", "유통주식", "유통비율"], "youtube_eod_float",
    ):
        if result.get("status") != "OK":
            continue
        code = str(result.get("code", "")).zfill(6)
        records = ((result.get("data") or {}).get("records") or [])
        if not records:
            continue
        row = records[0]
        float_kshares = _number(row.get("유통주식"))
        if float_kshares <= 0:
            continue
        floats[code] = {
            "name": str(row.get("종목명") or names.get(code, "")).strip(),
            "float_shares": int(float_kshares * 1000),
            "float_ratio_pct": _number(row.get("유통비율")),
        }
    float_payload = {
        "for_date": now.strftime("%Y%m%d"),
        "generated_at": _now().isoformat(),
        "source": "kiwoom_opt10001_유통주식_유통비율",
        "unit_conversion": "유통주식(천주) x 1000 = 주",
        "codes": floats,
    }
    _atomic_json(FLOAT_PATH, float_payload)
    history_ready = sum(1 for rows in histories.values() if len(rows) >= MIN_PREVIOUS_CLOSES)
    _log(f"prepare 완료 history_ready={history_ready}/{len(universe)} float={len(floats)}")
    return 0 if history_ready and floats else 2


def _wait_for_window() -> bool:
    now = _now()
    today = now.date()
    start = datetime.combine(today, REGISTER_START)
    end = datetime.combine(today, WATCH_END)
    if now > end:
        _log("15:20 이후: watch 중단")
        return False
    if now < start:
        wait = (start - now).total_seconds()
        if wait > 180:
            _log(f"15:00까지 {wait:.0f}초: 너무 일찍 실행되어 중단")
            return False
        time.sleep(max(0.0, wait))
    return True


def _register_realtime(broker, codes: list[str]) -> dict[str, list[str]]:
    screens: dict[str, list[str]] = {}
    for offset, chunk in enumerate(_chunks(codes, SCREEN_CHUNK)):
        screen = str(SCREEN_START + offset)
        response = {}
        for attempt in range(1, REGISTER_RETRIES + 1):
            response = broker.setreal_reg(
                screen, ";".join(chunk), "10;13", "0", timeout_sec=8.0,
            )
            if response.get("status") == "OK":
                break
            _log(
                f"실시간 등록 재시도 screen={screen} "
                f"attempt={attempt}/{REGISTER_RETRIES}: {response.get('error')}"
            )
            if attempt < REGISTER_RETRIES:
                time.sleep(REGISTER_RETRY_SEC)
        if response.get("status") != "OK":
            raise RuntimeError(f"SetRealReg {screen}: {response.get('error')}")
        screens[screen] = chunk
    return screens


def _remove_realtime(broker, screens: dict[str, list[str]]) -> None:
    for screen in screens:
        try:
            response = broker.set_real_remove(screen, "ALL", timeout_sec=5.0)
            if response.get("status") != "OK":
                _log(f"실시간 해제 실패 screen={screen}: {response.get('error')}")
        except Exception as exc:
            _log(f"실시간 해제 예외 screen={screen}: {exc}")


def _append_signal(signal: dict[str, Any]) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with SIGNALS_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(signal, ensure_ascii=False, separators=(",", ":")) + "\n")


def _existing_signal_ids() -> set[str]:
    ids: set[str] = set()
    try:
        with SIGNALS_PATH.open("r", encoding="utf-8-sig") as handle:
            for line in handle:
                try:
                    row = json.loads(line)
                    ids.add(str(row.get("signal_id", "")))
                except Exception:
                    continue
    except Exception:
        pass
    return ids


def float_cache_is_usable(cache: dict[str, Any], now: datetime) -> bool:
    """마감 후 준비한 유통주식 캐시를 다음 거래 세션까지 허용한다.

    금요일 마감 자료가 월요일에 쓰일 수 있도록 5일 이내만 인정한다.
    더 오래됐거나 미래 시각 자료면 대체 없이 실패한다.
    """
    try:
        generated = datetime.fromisoformat(str(cache.get("generated_at", "")))
        age_hours = (now - generated).total_seconds() / 3600.0
        source_date = str(cache.get("for_date", ""))
        return (
            0.0 <= age_hours <= 120.0
            and len(source_date) == 8
            and source_date <= now.strftime("%Y%m%d")
            and bool(cache.get("codes"))
        )
    except Exception:
        return False


def mode_watch() -> int:
    if not _wait_for_window():
        return 2
    broker = _broker_client()
    if not broker.alive():
        _log("broker DEAD: watch 중단")
        return 2
    today = _now().strftime("%Y%m%d")
    history = _load_gzip_json(HISTORY_PATH, {"codes": {}})
    float_cache = _load_json(FLOAT_PATH, {})
    if not float_cache_is_usable(float_cache, _now()):
        _log(f"유통주식 캐시가 없거나 5일 초과: asof={float_cache.get('for_date')}")
        return 2

    history_codes = history.get("codes") or {}
    float_codes = float_cache.get("codes") or {}
    prepared: dict[str, dict[str, Any]] = {}
    for code, float_row in float_codes.items():
        rows = (history_codes.get(code) or {}).get("closes") or []
        previous = [
            _number(item[1]) for item in rows
            if str(item[0]) < today and _number(item[1]) > 0
        ]
        float_shares = _number(float_row.get("float_shares"))
        if len(previous) >= MIN_PREVIOUS_CLOSES and float_shares > 0:
            prepared[code] = {
                "name": str(float_row.get("name") or (history_codes.get(code) or {}).get("name") or ""),
                "previous_closes": previous[-MIN_PREVIOUS_CLOSES:],
                "float_shares": float_shares,
                "float_ratio_pct": _number(float_row.get("float_ratio_pct")),
            }
    codes = sorted(prepared)
    if not codes:
        _log("정확 조건 계산 가능 종목 0: watch 중단")
        return 2

    screens: dict[str, list[str]] = {}
    signaled = _existing_signal_ids()
    new_signals = 0
    polls = 0
    evaluated_codes: set[str] = set()
    missing_real: set[str] = set(codes)
    try:
        try:
            screens = _register_realtime(broker, codes)
        except Exception as exc:
            summary = {
                "provenance": "[UNVERIFIED]",
                "strategy": "YOUTUBE_EOD_SHADOW",
                "trade_date": today,
                "finished_at": _now().isoformat(),
                "prepared_codes": len(codes),
                "evaluated_codes": 0,
                "missing_realtime_codes": len(codes),
                "polls": 0,
                "new_signals": 0,
                "order_path": "NONE",
                "status": "FAILED_REGISTER_REALTIME",
                "error": str(exc),
            }
            SESSION_DIR.mkdir(parents=True, exist_ok=True)
            _atomic_json(SESSION_DIR / f"{today}.json", summary)
            _log(f"watch 실패 기록: {exc}")
            return 2
        _log(f"watch 시작 codes={len(codes)} screens={len(screens)} 주문경로=없음")
        time.sleep(1.0)
        watch_start = datetime.combine(_now().date(), WATCH_START)
        if _now() < watch_start:
            time.sleep(max(0.0, (watch_start - _now()).total_seconds()))
        while _now().time() <= WATCH_END:
            loop_started = time.monotonic()
            # ★[2026-08-13] 실전 종가매수 보호창 — 그림자 IPC 호출 전면 중지.
            if in_live_eod_priority(_now().time()):
                time.sleep(POLL_SEC)
                continue
            response = broker.batch_get_comm_real_data(codes, REAL_FIDS, timeout_sec=8.0)
            polls += 1
            error_text = str(response.get("error") or "")
            if response.get("status") != "OK" and "WinError 5" in error_text:
                # ★[2026-08-13] 요청파일 접근경합(WinError 5)은 순간 잠금 — 1회만 재시도.
                time.sleep(0.5)
                response = broker.batch_get_comm_real_data(
                    codes, REAL_FIDS, timeout_sec=8.0)
                polls += 1
            if response.get("status") != "OK":
                _log(f"실시간 묶음 읽기 실패: {response.get('error')}")
            else:
                data = response.get("data") or {}
                for row in data.get("records") or []:
                    code = str(row.get("code", "")).zfill(6)
                    fid_data = row.get("fid_data") or {}
                    price = _number(fid_data.get("10"))
                    volume = _number(fid_data.get("13"))
                    if price <= 0 or volume <= 0 or code not in prepared:
                        continue
                    evaluated_codes.add(code)
                    missing_real.discard(code)
                    base = prepared[code]
                    result = evaluate_video_condition(
                        base["previous_closes"], price, volume, base["float_shares"]
                    )
                    if not result.get("passed"):
                        continue
                    signal_id = f"{today}:{code}"
                    if signal_id in signaled:
                        continue
                    signal = {
                        "provenance": "[UNVERIFIED]",
                        "strategy": "YOUTUBE_EOD_SHADOW",
                        "signal_id": signal_id,
                        "trade_date": today,
                        "detected_at": _now().isoformat(),
                        "code": code,
                        "name": base["name"],
                        "shadow_entry_price": price,
                        "float_ratio_pct": base["float_ratio_pct"],
                        "conditions": {
                            "time_window": "15:00:00-15:20:00",
                            "lrl20_gt_lrl40": True,
                            "price_gt_ma200_and_ma400": True,
                            "cumulative_volume_gt_float_shares": True,
                        },
                        "observations": result,
                        "sources": {
                            "daily_history": str(HISTORY_PATH),
                            "float_shares": str(FLOAT_PATH),
                            "realtime_fids": {"10": "현재가", "13": "누적거래량"},
                        },
                        "production_code_changed": "NOT_CHANGED",
                    }
                    _append_signal(signal)
                    signaled.add(signal_id)
                    new_signals += 1
                    _log(
                        f"그림자 신호 {code} {base['name']} @{price:,.0f} "
                        f"거래량/유통={result['turnover_float']:.2f}"
                    )
                if data.get("aborted_for_order"):
                    _log("실주문 대기 감지: 이번 실시간 읽기 조기중단")
            remaining = POLL_SEC - (time.monotonic() - loop_started)
            if remaining > 0:
                time.sleep(remaining)
    finally:
        # ★[2026-08-13] 해제 폭풍(화면 16개×5초)이 실전 매수창(15:18~15:25)과
        #   겹치지 않게, 보호창이 끝날 때까지 기다렸다가 해제한다.
        while in_live_eod_priority(_now().time()):
            time.sleep(5.0)
        _remove_realtime(broker, screens)

    summary = {
        "provenance": "[UNVERIFIED]",
        "strategy": "YOUTUBE_EOD_SHADOW",
        "trade_date": today,
        "finished_at": _now().isoformat(),
        "prepared_codes": len(codes),
        "evaluated_codes": len(evaluated_codes),
        "missing_realtime_codes": len(missing_real),
        "polls": polls,
        "new_signals": new_signals,
        "order_path": "NONE",
        "status": "COMPLETED",
    }
    SESSION_DIR.mkdir(parents=True, exist_ok=True)
    _atomic_json(SESSION_DIR / f"{today}.json", summary)
    _log(f"watch 종료 polls={polls} signals={new_signals} evaluated={len(evaluated_codes)}")
    return 0


def mode_grade() -> int:
    if not SIGNALS_PATH.exists() or not EOD_PATH.exists():
        _log("채점할 신호 또는 일봉 없음")
        return 0
    signals: dict[str, dict[str, Any]] = {}
    with SIGNALS_PATH.open("r", encoding="utf-8-sig") as handle:
        for line in handle:
            try:
                row = json.loads(line)
                signals[str(row["signal_id"])] = row
            except Exception:
                continue
    next_open: dict[tuple[str, str], tuple[str, float]] = {}
    by_code: dict[str, list[tuple[str, float]]] = {}
    with EOD_PATH.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            if str(row.get("market", "")).upper() != "KOSDAQ":
                continue
            code = str(row.get("code", "")).zfill(6)
            date = str(row.get("date", ""))
            open_price = _number(row.get("open"))
            if len(date) == 8 and open_price > 0:
                by_code.setdefault(code, []).append((date, open_price))
    for code, rows in by_code.items():
        rows.sort()
        for signal in signals.values():
            if signal.get("code") != code:
                continue
            trade_date = str(signal.get("trade_date", ""))
            later = [(date, price) for date, price in rows if date > trade_date]
            if later:
                next_open[(str(signal["signal_id"]), code)] = later[0]

    fields = [
        "provenance", "signal_id", "trade_date", "code", "name",
        "detected_at", "entry_price", "next_date", "next_open", "return_pct",
    ]
    graded_rows = []
    for signal_id, signal in sorted(signals.items()):
        code = str(signal.get("code", ""))
        outcome = next_open.get((signal_id, code))
        entry = _number(signal.get("shadow_entry_price"))
        if not outcome or entry <= 0:
            continue
        next_date, open_price = outcome
        graded_rows.append({
            "provenance": "[UNVERIFIED]",
            "signal_id": signal_id,
            "trade_date": signal.get("trade_date", ""),
            "code": code,
            "name": signal.get("name", ""),
            "detected_at": signal.get("detected_at", ""),
            "entry_price": entry,
            "next_date": next_date,
            "next_open": open_price,
            "return_pct": round((open_price / entry - 1.0) * 100.0, 4),
        })
    GRADED_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = GRADED_PATH.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(graded_rows)
    os.replace(tmp, GRADED_PATH)
    _log(f"grade 완료 signals={len(signals)} graded={len(graded_rows)}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["prepare", "watch", "grade"])
    args = parser.parse_args()
    if args.mode == "prepare":
        return mode_prepare()
    if args.mode == "watch":
        return mode_watch()
    return mode_grade()


if __name__ == "__main__":
    raise SystemExit(main())
