# -*- coding: utf-8 -*-
"""Publish one source-aware candidate context for independent strategies.

This process never evaluates a buy condition and never imports a broker.  It
only joins the existing EOD watch pools with current-day candidate sources:
captain money-rank, money-flow selector/watch, and high-range TOP30.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import time as time_module
from collections import defaultdict, deque
from datetime import datetime, time
from pathlib import Path
from typing import Any, Iterable, Mapping


ROOT = Path(r"C:\stock_bot")
DATA = ROOT / "data"
IPC = ROOT / "IPC"
EOD_PATH = Path(os.environ.get(
    "STRATEGY_CONTEXT_EOD", str(DATA / "eod_daily_bars.csv")))
SHARED_PATH = Path(os.environ.get(
    "STRATEGY_CONTEXT_SHARED", str(IPC / "micro_watch_strategy_shared.json")))
VALLEY_PATH = Path(os.environ.get(
    "STRATEGY_CONTEXT_VALLEY", str(IPC / "micro_watch_valley.json")))
MONEY_RANK_PATH = Path(os.environ.get(
    "STRATEGY_CONTEXT_MONEY_RANK", str(DATA / "micro_rank_board.json")))
MONEY_SELECTOR_PATH = Path(os.environ.get(
    "STRATEGY_CONTEXT_MONEY_SELECTOR",
    str(DATA / "\ub3c8\ud750\ub984_\uc120\ubcc4\ud310.json")))
MONEY_WATCH_PATH = Path(os.environ.get(
    "STRATEGY_CONTEXT_MONEY_WATCH", str(IPC / "micro_watch_moneyflow.json")))
HIGH_RANGE_PATH = Path(os.environ.get(
    "STRATEGY_CONTEXT_HIGH_RANGE", str(DATA / "common_high_range_top30.json")))
BOARD_PATH = Path(os.environ.get(
    "STRATEGY_CONTEXT_BOARD", str(DATA / "integrated_candidate_board.json")))
CONTEXT_PATH = Path(os.environ.get(
    "STRATEGY_CONTEXT_OUTPUT",
    str(DATA / "strategy_common_candidate_context_v1.json")))
LOOP_SEC = float(os.environ.get("STRATEGY_CONTEXT_LOOP_SEC", "1"))
END_AT = time(14, 21)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        first = path.read_bytes()
        time_module.sleep(0.003)
        second = path.read_bytes()
        if first != second:
            return {}
        return json.loads(second.decode("utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    os.replace(tmp, path)


def _code(value: Any) -> str:
    text = str(value or "").strip()
    return text.zfill(6) if text.isdigit() else ""


def _ordered_unique(values: Iterable[Any]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for value in values:
        code = _code(value)
        if len(code) == 6 and code not in seen:
            seen.add(code)
            output.append(code)
    return output


def _date_key(value: Any) -> str:
    return str(value or "").strip().replace("-", "")[:8]


def _payload_date(payload: Mapping[str, Any], *keys: str) -> str:
    for key in keys:
        value = payload.get(key)
        if value:
            return _date_key(value)
    return ""


def _captain_metrics(rows: Iterable[tuple[str, float, float, float]]) -> dict[str, float] | None:
    history = list(rows)
    if len(history) < 21:
        return None
    _date, close, high, value = history[-1]
    close_5d = history[-6][1]
    prior_values = [row[3] for row in history[-21:-1]]
    if (
        close <= 0
        or close_5d <= 0
        or len(prior_values) != 20
        or any(item <= 0 for item in prior_values)
    ):
        return None
    average = sum(prior_values) / 20.0
    return {
        "prev_close": close,
        "ret_5d_pct": (close / close_5d - 1.0) * 100.0,
        "high_close_pct": (high / close - 1.0) * 100.0 if high > 0 else -999.0,
        "value_ratio_20d": value / average if average > 0 else 0.0,
        "prev_value": value,
    }


def load_eod_profiles(path: Path = EOD_PATH) -> tuple[str, dict[str, dict[str, float]]]:
    histories: dict[str, deque[tuple[str, float, float, float]]] = defaultdict(
        lambda: deque(maxlen=21))
    latest_name: dict[str, str] = {}
    latest_market: dict[str, str] = {}
    latest_date = ""
    with path.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            code = _code(row.get("code"))
            market = str(row.get("market") or "").upper()
            if not code or code[-1] != "0" or "KOSDAQ" not in market:
                continue
            try:
                close = float(row.get("close") or 0)
                high = float(row.get("high") or 0)
                value = float(row.get("value") or 0)
            except (TypeError, ValueError):
                continue
            date = _date_key(row.get("date"))
            if not date:
                continue
            histories[code].append((date, close, high, value))
            latest_name[code] = str(row.get("name") or "")
            latest_market[code] = market
            latest_date = max(latest_date, date)

    profiles: dict[str, dict[str, float]] = {}
    for code, history in histories.items():
        name = latest_name.get(code, "")
        if "KOSDAQ" not in latest_market.get(code, ""):
            continue
        if "스팩" in name or "SPAC" in name.upper():
            continue
        metrics = _captain_metrics(history)
        if metrics and metrics["prev_close"] >= 10_000:
            profiles[code] = metrics
    return latest_date, profiles


def _num(value: Any) -> float | None:
    try:
        return round(float(value), 3)
    except (TypeError, ValueError):
        return None


def _extra_metrics(
    today: str,
    high_range: Mapping[str, Any],
    selector: Mapping[str, Any],
    board: Mapping[str, Any],
) -> dict[str, dict[str, Any]]:
    """Collect per-code display metrics from the three shared boards.

    고저폭·돈흐름·통합후보판의 값을 종목별로 모아 all_meta 에 얹는다.
    표시 전용이며 매수/매도 판정은 하지 않는다(전략이 스스로 쓴다).
    """
    extras: dict[str, dict[str, Any]] = defaultdict(dict)

    if _payload_date(high_range, "for_date", "generated_at") == today:
        for row in (high_range.get("candidates") or []):
            code = _code(row.get("code"))
            if code:
                extras[code].update({
                    "hr_prev_range": _num(row.get("prev_range_pct")),
                    "hr_avg5_range": _num(row.get("avg_5d_range_pct")),
                    "hr_min5_range": _num(row.get("min_5d_range_pct")),
                    "hr_streak": row.get("streak"),
                    "hr_rank": row.get("rank"),
                    "hr_crown": bool(row.get("crown")),
                })

    if _payload_date(selector, "ts") == today:
        for row in (selector.get("rows") or []):
            code = _code(row.get("code"))
            if code:
                extras[code].update({
                    "mf_inst": _num(row.get("inst")),
                    "mf_frgn": _num(row.get("frgn")),
                    "mf_prog": _num(row.get("prog")),
                    "mf_che": _num(row.get("che")),
                    "mf_chg": _num(row.get("chg")),
                })

    if _payload_date(board, "date", "ts") == today:
        for row in (board.get("attention_rank") or []):
            code = _code(row.get("code"))
            if code:
                extras[code].update({
                    "ic_attention": _num(row.get("attention_score")),
                    "ic_valley": _num(row.get("valley_score")),
                    "ic_breakout": _num(row.get("breakout_score")),
                    "ic_pullback": _num(row.get("ma_pullback_score")),
                    "ic_grade": row.get("grade"),
                    "ic_theme": row.get("theme_name"),
                    "ic_leader": bool(row.get("is_theme_leader")),
                })

    return {code: values for code, values in extras.items() if values}


def _source_codes(
    today: str,
    money_rank: Mapping[str, Any],
    selector: Mapping[str, Any],
    money_watch: Mapping[str, Any],
    high_range: Mapping[str, Any],
    board: Mapping[str, Any],
) -> tuple[dict[str, list[str]], dict[str, dict[str, Any]]]:
    raw: dict[str, list[str]] = {}
    status: dict[str, dict[str, Any]] = {}

    rank_current = _payload_date(money_rank, "date", "ts") == today
    rank_rows = list(money_rank.get("all_items") or [])
    active = [
        row.get("code") for row in rank_rows
        if row.get("money_start")
        or str(row.get("money_flow_state") or "").upper() in {"START", "ACCEL"}
    ]
    top = [row.get("code") for row in (money_rank.get("top20") or [])]
    raw["captain_money_rank"] = _ordered_unique(active + top) if rank_current else []
    status["captain_money_rank"] = {
        "fresh": rank_current,
        "source_ts": str(money_rank.get("ts") or ""),
        "raw_count": len(raw["captain_money_rank"]),
    }

    selector_current = _payload_date(selector, "ts") == today
    selector_codes = [row.get("code") for row in (selector.get("rows") or [])]
    raw["moneyflow_selector"] = (
        _ordered_unique(selector_codes) if selector_current else [])
    status["moneyflow_selector"] = {
        "fresh": selector_current,
        "source_ts": str(selector.get("ts") or ""),
        "raw_count": len(raw["moneyflow_selector"]),
    }

    watch_current = _payload_date(money_watch, "for_date", "ts") == today
    raw["moneyflow_watch"] = (
        _ordered_unique(money_watch.get("codes") or []) if watch_current else [])
    status["moneyflow_watch"] = {
        "fresh": watch_current,
        "source_ts": str(money_watch.get("ts") or ""),
        "raw_count": len(raw["moneyflow_watch"]),
    }

    high_current = _payload_date(high_range, "for_date", "generated_at") == today
    high_rows = sorted(
        list(high_range.get("candidates") or []),
        key=lambda row: (
            not bool(row.get("crown")),
            int(row.get("rank") or 9999),
        ),
    )
    raw["high_range_top30"] = (
        _ordered_unique(row.get("code") for row in high_rows)
        if high_current else [])
    status["high_range_top30"] = {
        "fresh": high_current,
        "source_ts": str(high_range.get("generated_at") or ""),
        "raw_count": len(raw["high_range_top30"]),
    }

    board_current = _payload_date(board, "date", "ts") == today
    board_rows = sorted(
        list(board.get("attention_rank") or []),
        key=lambda row: int(row.get("rank") or 9999),
    )
    raw["integrated_board"] = (
        _ordered_unique(row.get("code") for row in board_rows)
        if board_current else [])
    status["integrated_board"] = {
        "fresh": board_current,
        "source_ts": str(board.get("ts") or ""),
        "raw_count": len(raw["integrated_board"]),
    }
    return raw, status


def build_context(
    *,
    now: datetime,
    shared_base: Mapping[str, Any],
    valley_base: Mapping[str, Any],
    profiles: Mapping[str, Mapping[str, float]],
    money_rank: Mapping[str, Any],
    selector: Mapping[str, Any],
    money_watch: Mapping[str, Any],
    high_range: Mapping[str, Any],
    board: Mapping[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    today = now.strftime("%Y%m%d")
    shared_codes = _ordered_unique(
        shared_base.get("base_codes") or shared_base.get("codes") or [])
    valley_codes = _ordered_unique(
        valley_base.get("base_codes") or valley_base.get("codes") or [])
    base_meta = dict(
        shared_base.get("base_all_meta")
        or shared_base.get("all_meta")
        or {})
    sources, source_status = _source_codes(
        today, money_rank, selector, money_watch, high_range, board or {})

    source_tags: dict[str, list[str]] = defaultdict(list)
    accepted: dict[str, list[str]] = {}
    additions: list[str] = []
    for source_name, codes in sources.items():
        accepted[source_name] = []
        for code in codes:
            if code not in profiles:
                continue
            accepted[source_name].append(code)
            source_tags[code].append(source_name)
            # ★[2026-07-29 친구님 승인 "통합후보판 확장 롤백"] 통합후보판(integrated_board)은
            #   지표(ic_*)·태그 배달용으로만 쓰고 감시·매수 목록(codes)에는 종목을 보태지
            #   않는다 — 실시간 구독 200칸 경쟁을 키워 S02 시세공백을 가중시키는 원인이라
            #   목록 편입만 원복. 다른 소스의 편입과 지표 배달은 종전 그대로.
            #   롤백: 아래 조건에서 source_name 비교 제거. 백업 *.bak_20260729_review45
            if source_name != "integrated_board" and code not in shared_codes and code not in additions:
                additions.append(code)
        source_status[source_name]["accepted_count"] = len(accepted[source_name])

    extras = _extra_metrics(today, high_range, selector, board or {})

    all_codes = shared_codes + additions
    all_meta = dict(base_meta)
    for code in all_codes:
        if code in profiles:
            all_meta[code] = dict(profiles[code])
        if code in extras:
            all_meta.setdefault(code, {}).update(extras[code])

    stamp = now.isoformat(timespec="milliseconds")
    shared = dict(shared_base)
    shared.update({
        "codes": all_codes,
        "base_codes": shared_codes,
        "ts": stamp,
        "for_date": today,
        "src": "strategy_common_candidate_context_v1",
        "all_meta": all_meta,
        "base_all_meta": base_meta,
        "source_tags": dict(source_tags),
        "source_status": source_status,
        "source_counts": {
            name: len(codes) for name, codes in accepted.items()
        },
    })

    valley_tags = {
        code: source_tags[code]
        for code in valley_codes
        if source_tags.get(code)
    }
    valley_meta: dict[str, dict[str, Any]] = {}
    for code in valley_codes:
        if code in profiles:
            valley_meta[code] = dict(profiles[code])
        if code in extras:
            valley_meta.setdefault(code, {}).update(extras[code])
    valley = dict(valley_base)
    valley.update({
        "codes": valley_codes,
        "base_codes": valley_codes,
        "all_meta": valley_meta,
        "ts": stamp,
        "for_date": today,
        "src": "strategy_03_valley_with_common_context_v1",
        "source_tags": valley_tags,
        "source_status": source_status,
        "source_counts": {
            name: len(set(codes) & set(valley_codes))
            for name, codes in accepted.items()
        },
    })

    audit = {
        "schema": "strategy_common_candidate_context_v1",
        "ts": stamp,
        "for_date": today,
        "order_capability": 0,
        "shared_base_count": len(shared_codes),
        "shared_total_count": len(all_codes),
        "valley_base_count": len(valley_codes),
        "source_status": source_status,
        "source_counts": shared["source_counts"],
        "valley_source_counts": valley["source_counts"],
        "source_codes": accepted,
    }
    return shared, valley, audit


def publish_once(
    now: datetime | None = None,
    *,
    source_date: str | None = None,
    profiles: Mapping[str, Mapping[str, float]] | None = None,
) -> dict[str, Any]:
    now = now or datetime.now()
    if profiles is None:
        loaded_date, loaded_profiles = load_eod_profiles()
        source_date = source_date or loaded_date
        profiles = loaded_profiles
    shared_base = _read_json(SHARED_PATH)
    valley_base = _read_json(VALLEY_PATH)
    shared, valley, audit = build_context(
        now=now,
        shared_base=shared_base,
        valley_base=valley_base,
        profiles=profiles,
        money_rank=_read_json(MONEY_RANK_PATH),
        selector=_read_json(MONEY_SELECTOR_PATH),
        money_watch=_read_json(MONEY_WATCH_PATH),
        high_range=_read_json(HIGH_RANGE_PATH),
        board=_read_json(BOARD_PATH),
    )
    if source_date:
        shared["source_date"] = source_date
        valley["source_date"] = source_date
        audit["source_date"] = source_date
    _write_json(SHARED_PATH, shared)
    _write_json(VALLEY_PATH, valley)
    _write_json(CONTEXT_PATH, audit)
    return audit


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    if args.once:
        print(json.dumps(publish_once(), ensure_ascii=False), flush=True)
        return 0

    source_date, profiles = load_eod_profiles()
    while True:
        now = datetime.now()
        if now.weekday() >= 5 or now.time() > END_AT:
            return 0
        try:
            audit = publish_once(
                now, source_date=source_date, profiles=profiles)
            print(
                f"[{audit['ts']}] shared={audit['shared_total_count']} "
                f"valley={audit['valley_base_count']} "
                f"sources={audit['source_counts']}",
                flush=True,
            )
        except Exception as exc:
            print(f"[{now.isoformat()}] CONTEXT_ERROR {exc}", flush=True)
        time_module.sleep(max(0.2, LOOP_SEC))


if __name__ == "__main__":
    raise SystemExit(main())
