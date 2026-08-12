# -*- coding: utf-8 -*-
"""새전략 01~05 통합 중계방송.

읽기 전용 입력만 사용한다. 브로커 import, TR, 주문 기능은 없다.
출력은 바탕화면의 스톡봇_중계.txt/html/기록.txt이며, 기존 사용자를 위해
캡틴2_중계.html도 같은 내용으로 갱신한다.
"""
from __future__ import annotations

import collections
import csv
import datetime as dt
import html
import json
import os
import sys
from pathlib import Path
from typing import Any

# ★[SYSPATH-FIX 2026-08-05 09:54] 중계판이 8/4 15:30 이후 멈춰 있던 원인.
#   python._pth 때문에 sys.path 에 스크립트 폴더가 안 들어간다
#   (실측: python310.zip / C:\python310 / site-packages). 그래서 아래
#   approval_settings_guard import 가 ModuleNotFoundError 로 죽었고,
#   태스크는 매분 정상 실행되는데(result=0) HTML 만 갱신이 멈춰 있었다.
#   같은 패턴을 strategy_all_live_gate_launcher_v1.py:12-14 가 쓰고 있다.
#   되돌리기: backup\stockbot_live_broadcast_v1_20260805_before_syspath_fix.py
RUN_DIR = Path(__file__).resolve().parent
if str(RUN_DIR) not in sys.path:
    sys.path.insert(0, str(RUN_DIR))

from approval_settings_guard import KST, legacy_daily_approval_valid


BASE = Path(os.environ.get("STOCKBOT_BASE", r"C:\stock_bot"))
DESKTOP = Path(
    os.environ.get(
        "STOCKBOT_DESKTOP",
        str(Path(os.environ.get("USERPROFILE", r"C:\Users\UserK")) / "Desktop"),
    )
)
DATA = BASE / "data"
CONFIG = BASE / "config"
LOG_DIR = BASE / "LOG"
# [2026-07-27 친구님 지시] 바탕화면에는 스톡봇_중계.html 하나만 유지.
#   txt·기록·캡틴2 레거시는 C:\stock_bot\보고서 폴더로 이동.
REPORT_DIR = BASE / "보고서"
SNAP_TEXT = REPORT_DIR / "스톡봇_중계.txt"
SNAP_HTML = DESKTOP / "스톡봇_중계.html"
TAPE = REPORT_DIR / "스톡봇_중계_기록.txt"
LEGACY_HTML = REPORT_DIR / "캡틴2_중계.html"
SHARED_SLOTS = DATA / "shared_slots.json"
NAME_CACHE = DATA / "_code_name_cache.json"
PREFLIGHT_SELFTESTS = (
    ("HIGH", "S01~S03", "preflight_context_selftest_high_v1.json"),
    ("LIMITED", "S04", "preflight_context_selftest_limited_v1.json"),
)

ACTIVE_PHASES = {
    "BUY_PENDING",
    "HOLD",
    "SELL_PENDING",
    "RECOVERY_BLOCKED",
}

STRATEGIES = (
    {
        "number": "01",
        "id": "S01_OPEN_SURGE",
        "name": "장초반 급상승 초입",
        "state": "strategy_01_rotation_state_v2.json",
        "signal": "strategy_01_open_surge_signal_v2.json",
        "events": "strategy_01_rotation_v2",
        "event_prefix": "strategy_01",
    },
    {
        "number": "02",
        "id": "S02_LOW_BUY_SELL_EXHAUSTION",
        "name": "저점매수·매도소진",
        "state": "strategy_02_rotation_state_v1.json",
        "signal": "strategy_02_low_buy_signal_v1.json",
        "events": "strategy_02_rotation_v1",
        "event_prefix": "strategy_02",
        "daily_cap": 15,
    },
    {
        "number": "03",
        "id": "S03_VALLEY_RAPID_REBOUND",
        "name": "골짜기 급반등",
        "state": "strategy_03_rotation_state_v1.json",
        "signal": "strategy_03_골짜기_급반등_signal_v1.json",
        "events": "strategy_03_rotation_v1",
        "event_prefix": "strategy_03",
    },
    {
        "number": "04",
        "id": "S04_PULLBACK",
        "name": "눌림목",
        "state": "strategy_04_rotation_state_v1.json",
        "signal": "strategy_04_pullback_signal_v1.json",
        "events": "strategy_04_rotation_v1",
        "event_prefix": "strategy_04",
    },
    {
        "number": "05",
        "id": "S05_BASE_BREAKOUT",
        "name": "장중 베이스 돌파",
        "state": "strategy_05_rotation_state_v1.json",
        "signal": "strategy_05_base_breakout_signal_v1.json",
        "events": "strategy_05_rotation_v1",
        "event_prefix": "strategy_05",
    },
    {
        "number": "06",
        "id": "S06_CRASH_LOW_CHASE",
        "name": "급락 저점",
        "state": "strategy_06_crash_low_chase_state_v1.json",
        "signal": "strategy_06_crash_low_chase_state_v1.json",
        "events": "strategy_06_crash_low_chase",
        "event_prefix": "strategy_06",
        "daily_cap": 20,
    },
)


def now_local() -> dt.datetime:
    return dt.datetime.now()


def read_json(path: Path, fallback: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return fallback


def parse_local(value: Any) -> dt.datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = dt.datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone().replace(tzinfo=None)
    return parsed


def number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def integer(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def fmt_number(value: Any) -> str:
    return f"{number(value):,.0f}"


def load_names() -> dict[str, str]:
    payload = read_json(NAME_CACHE, {})
    if isinstance(payload, dict) and isinstance(payload.get("names"), dict):
        payload = payload["names"]
    if not isinstance(payload, dict):
        return {}
    names: dict[str, str] = {}
    for raw_code, raw_value in payload.items():
        code = str(raw_code or "").zfill(6)
        if isinstance(raw_value, dict):
            name = str(raw_value.get("name") or raw_value.get("종목명") or "")
        else:
            name = str(raw_value or "")
        if code.isdigit() and len(code) == 6 and name:
            names[code] = name
    return names


def _heartbeat(state: dict[str, Any], now: dt.datetime) -> tuple[float | None, str]:
    stamp = parse_local(state.get("heartbeat"))
    if stamp is None:
        return None, "심장박동 없음"
    age = max(0.0, (now - stamp).total_seconds())
    if age <= 20:
        return age, f"정상 {age:.0f}초전"
    if age <= 90:
        return age, f"느림 {age:.0f}초전"
    return age, f"멈춤 의심 {age / 60:.0f}분전"


def _approval_gate(path: Path, now: dt.datetime) -> str:
    """주문 관문(StrategyBroker.real_session)과 똑같은 판정을 쓴다.

    ★[APPROVAL-DISPLAY 2026-08-04] 예전엔 파일 존재만 봤다. 깃발이 있어도 내용·날짜가
    무효면 실제 주문은 전부 그림자로 나가는데 중계판만 LIVE 로 떠 있었다.
    더 나쁜 건 아래 BUY_BLOCKED/APPROVAL_OR_OFF_FLAG 억제 규칙(게이트가 LIVE 면
    그 사건을 화면에서 숨긴다)까지 겹쳐서, "승인 때문에 매수가 막혔다"는 증거마저
    지워졌다는 점이다. 켜진 줄 알고 하루를 날리는 경로였다.

    깃발 없음(승인대기)과 깃발이 깨짐(승인무효)을 구분해서 보여준다 — 원인이 다르다.
    되돌리기: backup/stockbot_live_broadcast_v1_20260804_before_approval_display.py
    """
    if not path.exists():
        return "승인대기"
    try:
        text = path.read_text(encoding="ascii", errors="strict")
    except (OSError, UnicodeError):
        return "승인무효"
    moment = now if now.tzinfo else now.replace(tzinfo=KST)
    if legacy_daily_approval_valid(text, moment.astimezone(KST)):
        return "LIVE"
    return "승인무효"


def load_strategy(meta: dict[str, str], now: dt.datetime, names: dict[str, str]) -> dict[str, Any]:
    day = now.strftime("%Y%m%d")
    state = read_json(DATA / meta["state"], {})
    signal = read_json(DATA / meta["signal"], {})
    current_state = isinstance(state, dict) and str(state.get("date") or "") == day
    age, heartbeat = _heartbeat(state, now) if current_state else (None, "시작 전")

    off = (CONFIG / f"strategy_{meta['number']}_off.flag").exists()
    gate = "OFF" if off else _approval_gate(
        CONFIG / f"strategy_{meta['number']}_live_approved.flag", now)
    approved = gate == "LIVE"

    positions = state.get("positions") if current_state else {}
    if not isinstance(positions, dict):
        positions = {}
    held: list[dict[str, Any]] = []
    for raw_code, raw_position in positions.items():
        if not isinstance(raw_position, dict):
            continue
        phase = str(raw_position.get("phase") or "")
        if phase not in ACTIVE_PHASES:
            continue
        code = str(raw_position.get("code") or raw_code or "").zfill(6)
        pending = raw_position.get("pending") or {}
        qty = integer(raw_position.get("qty"))
        if qty <= 0 and phase == "BUY_PENDING":
            qty = integer(pending.get("requested_qty"), 1)
        entry = number(raw_position.get("entry_price"))
        current = number(raw_position.get("last_price"), entry)
        pnl = (current / entry - 1.0) * 100.0 if entry > 0 and current > 0 else 0.0
        held.append(
            {
                "code": code,
                "name": str(raw_position.get("name") or names.get(code) or code),
                "phase": phase,
                "qty": qty,
                "entry": entry,
                "current": current,
                "pnl": pnl,
            }
        )

    entered_codes = state.get("entered_codes") if current_state else []
    if not isinstance(entered_codes, list):
        entered_codes = []
    cycles = state.get("cycles_by_code") if current_state else {}
    if not isinstance(cycles, dict):
        cycles = {}
    if not entered_codes:
        entered_codes = [code for code, count in cycles.items() if integer(count) > 0]

    ready_signals = 0
    if isinstance(signal, dict) and str(signal.get("date") or "") == day:
        rows = signal.get("signals") or []
        if isinstance(rows, list):
            ready_signals = sum(
                1 for row in rows
                if isinstance(row, dict) and row.get("action") == "BUY_READY"
            )

    return {
        **meta,
        "daily_cap": integer(meta.get("daily_cap"), 6),
        "gate": gate,
        "off": off,
        "approved": approved,
        "current_state": current_state,
        "heartbeat": heartbeat,
        "heartbeat_age": age,
        "held": held,
        "entered_count": len({str(code).zfill(6) for code in entered_codes}),
        "cycles_total": sum(max(0, integer(value)) for value in cycles.values()),
        "order_attempts": integer(state.get("order_attempts_total")) if current_state else 0,
        "ready_signals": ready_signals,
        "recovery_blocked": bool(state.get("recovery_blocked")) if current_state else False,
        "last_error": str(state.get("last_error") or "") if current_state else "",
    }


def load_strategy_events(now: dt.datetime) -> tuple[list[dict[str, str]], dict[str, str]]:
    day = now.strftime("%Y%m%d")
    events: list[dict[str, str]] = []
    source_by_code: dict[str, str] = {}
    for meta in STRATEGIES:
        path = DATA / meta["events"] / f"{meta['event_prefix']}_events_{day}.csv"
        if not path.exists():
            continue
        try:
            with path.open(encoding="utf-8-sig", errors="replace", newline="") as handle:
                for row in csv.DictReader(handle):
                    if not isinstance(row, dict):
                        continue
                    tagged = {key: str(value or "") for key, value in row.items()}
                    tagged["strategy_number"] = meta["number"]
                    tagged["strategy_name"] = meta["name"]
                    events.append(tagged)
                    if tagged.get("code") and tagged.get("event") in {
                        "BUY_SUBMITTED",
                        "BUY_CONFIRMED",
                        "SHADOW_BUY",
                    }:
                        source_by_code[tagged["code"].zfill(6)] = f"전략 {meta['number']}"
        except Exception:
            continue
    events.sort(key=lambda row: row.get("ts", ""))
    return events[-20:], source_by_code


def filter_current_events(
    events: list[dict[str, str]],
    strategies: list[dict[str, Any]],
) -> list[dict[str, str]]:
    gates = {
        str(strategy.get("number") or ""): str(strategy.get("gate") or "")
        for strategy in strategies
    }
    output: list[dict[str, str]] = []
    seen_blocks: set[tuple[str, str, str]] = set()
    for event in reversed(events):
        if str(event.get("event") or "") == "BUY_BLOCKED":
            number = str(event.get("strategy_number") or "")
            reason = str(event.get("reason") or "")
            if reason == "APPROVAL_OR_OFF_FLAG" and gates.get(number) == "LIVE":
                continue
            key = (number, str(event.get("code") or ""), reason)
            if key in seen_blocks:
                continue
            seen_blocks.add(key)
        output.append(event)
    return list(reversed(output))


def load_shared_slots(now: dt.datetime) -> list[dict[str, str]]:
    payload = read_json(SHARED_SLOTS, {})
    if not isinstance(payload, dict) or str(payload.get("date") or "") != now.strftime("%Y%m%d"):
        return []
    slots = payload.get("slots") or {}
    if not isinstance(slots, dict):
        return []
    return [
        {
            "code": str(raw_code or "").zfill(6),
            "owner": str(raw_value.get("strat") or "?")
            if isinstance(raw_value, dict)
            else "?",
        }
        for raw_code, raw_value in slots.items()
    ]


def load_fills(
    now: dt.datetime,
    names: dict[str, str],
    source_by_code: dict[str, str],
) -> dict[str, Any]:
    path = LOG_DIR / f"fills_{now:%Y%m%d}.csv"
    result = {
        "ok": False,
        "reason": "개장 전(오늘 체결파일 없음)",
        "buys": 0,
        "sells": 0,
        "realized": 0.0,
        "net": [],
        "roundtrips": [],
        "events": [],
    }
    if not path.exists():
        return result
    try:
        with path.open(encoding="utf-8-sig", errors="replace", newline="") as handle:
            rows = [
                row for row in csv.DictReader(handle)
                if isinstance(row, dict) and row.get("state") == "체결"
            ]
    except Exception as exc:
        result["reason"] = f"체결파일 읽기 실패: {exc}"
        return result

    queues: dict[str, collections.deque[dict[str, Any]]] = collections.defaultdict(
        collections.deque
    )
    realized = 0.0
    roundtrips: list[dict[str, Any]] = []
    recent: list[str] = []
    for row in rows:
        code = str(row.get("code") or "").zfill(6)
        qty = max(0, integer(row.get("fill_qty")))
        price = max(0.0, number(row.get("fill_px")))
        if qty <= 0 or price <= 0:
            continue
        stamp = str(row.get("ts") or "")
        side = "매수" if "매수" in str(row.get("otype") or "") else "매도"
        name = names.get(code, code)
        source = source_by_code.get(code, "공통/기존")
        recent.append(f"{stamp[11:19]} {side} [{source}] {name}({code}) {fmt_number(price)}×{qty}")
        if side == "매수":
            result["buys"] += 1
            queues[code].append(
                {"qty": qty, "price": price, "ts": stamp[11:19], "source": source}
            )
            continue
        result["sells"] += 1
        remaining = qty
        while remaining > 0 and queues[code]:
            buy = queues[code][0]
            matched = min(remaining, buy["qty"])
            cash_pnl = (price - buy["price"]) * matched
            realized += cash_pnl
            roundtrips.append(
                {
                    "code": code,
                    "name": name,
                    "source": buy["source"],
                    "buy_ts": buy["ts"],
                    "sell_ts": stamp[11:19],
                    "buy_price": buy["price"],
                    "sell_price": price,
                    "qty": matched,
                    "pnl_pct": (price / buy["price"] - 1.0) * 100.0,
                    "cash_pnl": cash_pnl,
                }
            )
            buy["qty"] -= matched
            remaining -= matched
            if buy["qty"] <= 0:
                queues[code].popleft()

    net = []
    for code, queue in queues.items():
        qty = sum(item["qty"] for item in queue)
        if qty <= 0:
            continue
        cost = sum(item["price"] * item["qty"] for item in queue) / qty
        net.append(
            {
                "code": code,
                "name": names.get(code, code),
                "qty": qty,
                "entry": cost,
                "source": queue[-1]["source"],
            }
        )
    result.update(
        {
            "ok": True,
            "reason": "",
            "realized": realized,
            "net": net,
            "roundtrips": roundtrips,
            "events": recent[-12:],
        }
    )
    return result


def load_preflight_selftests(current: dt.datetime) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for profile, strategies, filename in PREFLIGHT_SELFTESTS:
        payload = read_json(DATA / filename, {})
        stages = payload.get("stages") or {}
        stage_values = [
            (stages.get(name) or {}).get("passed") is True
            for name in (
                "stage1_mock",
                "stage2_real_fallback",
                "stage3_scheduled_context",
            )
        ]
        same_day = str(payload.get("for_date") or "") == current.strftime("%Y%m%d")
        passed = payload.get("passed") is True and same_day and all(stage_values)
        if not payload:
            reason = "감사 없음"
        elif not same_day:
            reason = "오늘 결과 없음"
        else:
            reason = str(payload.get("reason") or "UNKNOWN")
        results.append({
            "profile": profile,
            "strategies": strategies,
            "passed": passed,
            "stages": stage_values,
            "finished_at": str(payload.get("finished_at") or ""),
            "reason": reason,
        })
    return results


def build_snapshot(now: dt.datetime | None = None) -> dict[str, Any]:
    current = now or now_local()
    names = load_names()
    strategies = [load_strategy(meta, current, names) for meta in STRATEGIES]
    events, source_by_code = load_strategy_events(current)
    events = filter_current_events(events, strategies)
    return {
        "now": current,
        "strategies": strategies,
        "slots": load_shared_slots(current),
        "fills": load_fills(current, names, source_by_code),
        "events": events,
        "preflight_selftests": load_preflight_selftests(current),
        "manual_block": (CONFIG / "manual_buy_block.flag").exists(),
    }


def render_text(snapshot: dict[str, Any]) -> str:
    now = snapshot["now"]
    lines = [
        "=" * 64,
        f"  스톡봇 통합 중계  {now:%Y-%m-%d %H:%M:%S}",
        "=" * 64,
        "",
        "[전략 1·2·3·4·5·6 상태]",
    ]
    for strategy in snapshot["strategies"]:
        held = len(strategy["held"])
        alert = " 복구차단" if strategy["recovery_blocked"] else ""
        lines.append(
            f"  전략 {strategy['number']} {strategy['name']:<12} "
            f"{strategy['gate']:<5} | {strategy['heartbeat']} | "
            f"신호 {strategy['ready_signals']} | 당일종목 "
            f"{strategy['entered_count']}/{strategy['daily_cap']} | "
            f"완료회전 {strategy['cycles_total']} | 보유 {held}{alert}"
        )
        if strategy["last_error"]:
            lines.append(f"    오류: {strategy['last_error']}")
        for position in strategy["held"]:
            sign = "+" if position["pnl"] >= 0 else ""
            lines.append(
                f"    {position['name']}({position['code']}) {position['phase']} "
                f"{position['qty']}주 {fmt_number(position['entry'])}→"
                f"{fmt_number(position['current'])} {sign}{position['pnl']:.2f}%"
            )
    lines.extend(["", f"[공용 슬롯] {len(snapshot['slots'])}/6 점유"])
    if snapshot["slots"]:
        for slot in snapshot["slots"]:
            lines.append(f"  {slot['code']} — {slot['owner']}")
    else:
        lines.append("  점유 없음")

    lines.extend(["", "[장전 3단계 검증]"])
    for result in snapshot["preflight_selftests"]:
        stage_text = "/".join("PASS" if value else "FAIL" for value in result["stages"])
        status = "PASS" if result["passed"] else "FAIL"
        finished = result["finished_at"][11:19] or "--:--:--"
        lines.append(
            f"  {result['profile']:<7} {result['strategies']:<7} {status} "
            f"({stage_text}) {finished} {result['reason']}"
        )

    fills = snapshot["fills"]
    lines.extend(["", "[오늘 실제 체결]"])
    if fills["ok"]:
        sign = "+" if fills["realized"] >= 0 else ""
        lines.append(
            f"  매수 {fills['buys']}건 / 매도 {fills['sells']}건 | "
            f"가격차 손익(세금·수수료 전) {sign}{fmt_number(fills['realized'])}원"
        )
        lines.append(f"  순보유 {len(fills['net'])}종목")
    else:
        lines.append(f"  {fills['reason']}")

    lines.extend(["", "[완결 매매]"])
    if fills["roundtrips"]:
        for trade in fills["roundtrips"][-20:]:
            sign = "+" if trade["pnl_pct"] >= 0 else ""
            lines.append(
                f"  [{trade['source']}] {trade['buy_ts']}→{trade['sell_ts']} "
                f"{trade['name']}({trade['code']}) {fmt_number(trade['buy_price'])}→"
                f"{fmt_number(trade['sell_price'])} {sign}{trade['pnl_pct']:.2f}%"
            )
    else:
        lines.append("  없음")

    lines.extend(["", "[최근 전략 이벤트]"])
    if snapshot["events"]:
        for event in snapshot["events"][-12:]:
            lines.append(
                f"  {event.get('ts', '')[11:19]} 전략 {event['strategy_number']} "
                f"{event.get('event', '')} {event.get('name') or event.get('code') or ''} "
                f"{event.get('reason', '')}"
            )
    else:
        lines.append("  없음")
    if snapshot["manual_block"]:
        lines.extend(["", "  ⚠ 수동 신규매수 차단 플래그 ON"])
    return "\n".join(lines) + "\n"


def _status_class(strategy: dict[str, Any]) -> str:
    if strategy["recovery_blocked"] or strategy["last_error"]:
        return "down"
    if strategy["gate"] == "LIVE" and (strategy["heartbeat_age"] or 999) <= 20:
        return "up"
    if strategy["gate"] == "OFF":
        return "down"
    return "warn"


def render_html(snapshot: dict[str, Any]) -> str:
    now = snapshot["now"]
    parts = [
        f'<div class="clock">스톡봇 통합 중계 <b>{now:%Y-%m-%d %H:%M:%S}</b></div>',
        "<h2>전략 1·2·3·4·5·6 상태</h2>",
        "<table><tr><th>전략</th><th>게이트</th><th>심장박동</th>"
        "<th>신호</th><th>당일종목</th><th>완료회전</th><th>보유</th></tr>",
    ]
    for strategy in snapshot["strategies"]:
        cls = _status_class(strategy)
        parts.append(
            f"<tr><td class=\"nm\">전략 {strategy['number']} "
            f"{html.escape(strategy['name'])}</td>"
            f"<td class=\"{cls}\">{strategy['gate']}</td>"
            f"<td class=\"{cls}\">{html.escape(strategy['heartbeat'])}</td>"
            f"<td>{strategy['ready_signals']}</td>"
            f"<td>{strategy['entered_count']}/{strategy['daily_cap']}</td>"
            f"<td>{strategy['cycles_total']}</td>"
            f"<td>{len(strategy['held'])}</td></tr>"
        )
        if strategy["last_error"]:
            parts.append(
                f'<tr><td></td><td colspan="6" class="down">'
                f'{html.escape(strategy["last_error"])}</td></tr>'
            )
    parts.append("</table>")

    parts.append("<h2>장전 3단계 검증</h2>")
    parts.append("<table><tr><th>권한</th><th>대상</th><th>결과</th>"
                 "<th>1·2·3단계</th><th>완료</th><th>사유</th></tr>")
    for result in snapshot["preflight_selftests"]:
        cls = "up" if result["passed"] else "down"
        stage_text = "/".join("PASS" if value else "FAIL" for value in result["stages"])
        finished = result["finished_at"][11:19] or "--:--:--"
        parts.append(
            f'<tr><td>{result["profile"]}</td><td>{result["strategies"]}</td>'
            f'<td class="{cls}">{"PASS" if result["passed"] else "FAIL"}</td>'
            f'<td class="{cls}">{stage_text}</td><td>{finished}</td>'
            f'<td>{html.escape(result["reason"])}</td></tr>'
        )
    parts.append("</table>")

    parts.append(f"<h2>공용 슬롯 — {len(snapshot['slots'])}/6</h2>")
    if snapshot["slots"]:
        parts.append("<table>")
        for slot in snapshot["slots"]:
            parts.append(
                f"<tr><td class=\"nm\">{html.escape(slot['code'])}</td>"
                f"<td>{html.escape(slot['owner'])}</td></tr>"
            )
        parts.append("</table>")
    else:
        parts.append('<div class="dim">점유 없음</div>')

    fills = snapshot["fills"]
    parts.append("<h2>오늘 실제 체결</h2>")
    if fills["ok"]:
        pnl_cls = "up" if fills["realized"] >= 0 else "down"
        sign = "+" if fills["realized"] >= 0 else ""
        parts.append(
            f'<div>매수 <b>{fills["buys"]}</b>건 / 매도 <b>{fills["sells"]}</b>건</div>'
            f'<div>가격차 손익(세금·수수료 전) '
            f'<span class="{pnl_cls} big">{sign}{fmt_number(fills["realized"])}원</span></div>'
            f'<div class="dim">순보유 {len(fills["net"])}종목</div>'
        )
    else:
        parts.append(f'<div class="dim">{html.escape(fills["reason"])}</div>')

    parts.append("<h2>전략별 보유</h2>")
    held_rows = [
        (strategy, position)
        for strategy in snapshot["strategies"]
        for position in strategy["held"]
    ]
    if held_rows:
        parts.append("<table>")
        for strategy, position in held_rows:
            pnl_cls = "up" if position["pnl"] >= 0 else "down"
            sign = "+" if position["pnl"] >= 0 else ""
            parts.append(
                f"<tr><td>전략 {strategy['number']}</td>"
                f"<td class=\"nm\">{html.escape(position['name'])}</td>"
                f"<td class=\"dim\">{html.escape(position['code'])}</td>"
                f"<td>{position['qty']}주</td>"
                f"<td>{fmt_number(position['entry'])}→{fmt_number(position['current'])}</td>"
                f"<td class=\"{pnl_cls} big\">{sign}{position['pnl']:.2f}%</td>"
                f"<td class=\"dim\">{html.escape(position['phase'])}</td></tr>"
            )
        parts.append("</table>")
    else:
        parts.append('<div class="dim">보유 없음</div>')

    parts.append("<h2>완결 매매</h2>")
    if fills["roundtrips"]:
        parts.append("<table>")
        for trade in fills["roundtrips"][-20:]:
            pnl_cls = "up" if trade["pnl_pct"] >= 0 else "down"
            sign = "+" if trade["pnl_pct"] >= 0 else ""
            parts.append(
                f"<tr><td>{html.escape(trade['source'])}</td>"
                f"<td class=\"dim\">{trade['buy_ts']}→{trade['sell_ts']}</td>"
                f"<td class=\"nm\">{html.escape(trade['name'])}</td>"
                f"<td class=\"dim\">{html.escape(trade['code'])}</td>"
                f"<td>{fmt_number(trade['buy_price'])}→{fmt_number(trade['sell_price'])}</td>"
                f"<td class=\"{pnl_cls} big\">{sign}{trade['pnl_pct']:.2f}%</td></tr>"
            )
        parts.append("</table>")
    else:
        parts.append('<div class="dim">없음</div>')

    parts.append("<h2>최근 전략 이벤트</h2>")
    if snapshot["events"]:
        parts.append('<div class="events">')
        for event in snapshot["events"][-12:]:
            event_name = event.get("event", "")
            event_cls = "up" if "BUY" in event_name else ("down" if "SELL" in event_name else "")
            text = (
                f"{event.get('ts', '')[11:19]} 전략 {event['strategy_number']} "
                f"{event_name} {event.get('name') or event.get('code') or ''} "
                f"{event.get('reason', '')}"
            )
            parts.append(f'<div class="{event_cls}">{html.escape(text)}</div>')
        parts.append("</div>")
    else:
        parts.append('<div class="dim">없음</div>')

    if snapshot["manual_block"]:
        parts.append('<div class="alert">⚠ 수동 신규매수 차단 플래그 ON</div>')
    body = "\n".join(parts)
    return f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8">
<meta http-equiv="refresh" content="20">
<title>스톡봇 통합 중계</title>
<style>
html,body{{margin:0;background:#000;color:#e2e2e2;
font-family:'Consolas','D2Coding','Malgun Gothic',monospace;font-size:18px;line-height:1.55;}}
.wrap{{max-width:1160px;margin:0 auto;padding:22px 26px 60px;}}
.clock{{font-size:25px;color:#a9c7ff;border-bottom:1px solid #333;padding-bottom:10px;}}
.clock b{{color:#fff;float:right;}}
h2{{font-size:16px;color:#7fb2ff;margin:22px 0 7px;}}
table{{border-collapse:collapse;width:100%;}}
th{{color:#8a8a8a;text-align:left;font-size:14px;border-bottom:1px solid #333;}}
td,th{{padding:5px 12px 5px 0;white-space:nowrap;}}
.nm{{color:#fff;}} .up{{color:#3ddc84;}} .down{{color:#ff6b6b;}}
.warn{{color:#ffcf5c;}} .dim{{color:#888;}} .big{{font-size:20px;font-weight:700;}}
.events div{{margin:2px 0;}} .alert{{margin-top:20px;padding:10px;color:#ffcf5c;border:1px solid #7b6225;}}
</style></head><body><div class="wrap">{body}</div></body></html>"""


def write_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(content, encoding="utf-8")
    os.replace(temp, path)


def main() -> int:
    try:
        snapshot = build_snapshot()
        text = render_text(snapshot)
        page = render_html(snapshot)
        write_atomic(SNAP_TEXT, text)
        write_atomic(SNAP_HTML, page)
        write_atomic(LEGACY_HTML, page)
        fills = snapshot["fills"]
        line = (
            f"{snapshot['now']:%Y-%m-%d %H:%M} | "
            f"게이트 {' '.join(s['number'] + ':' + s['gate'] for s in snapshot['strategies'])} | "
            f"슬롯 {len(snapshot['slots'])}/6 | 매수 {fills['buys']} 매도 {fills['sells']} | "
            f"가격차손익 {fmt_number(fills['realized'])}원\n"
        )
        TAPE.parent.mkdir(parents=True, exist_ok=True)
        with TAPE.open("a", encoding="utf-8") as handle:
            handle.write(line)
        print(text, end="")
        return 0
    except Exception as exc:
        error = f"[스톡봇 중계 생성 오류] {type(exc).__name__}: {exc}\n"
        try:
            write_atomic(SNAP_TEXT, error)
        except Exception:
            pass
        print(error, end="")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
