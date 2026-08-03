# -*- coding: utf-8 -*-
"""👑고저폭 TOP30 실시간 관찰판.

공통 후보와 기존 broker의 읽기전용 live_micro_snapshot을 합쳐 바탕화면
HTML과 왕관 후보의 주문 0 관찰기록을 만든다. 주문 API는 호출하지 않는다.
"""
from __future__ import annotations

import argparse
import csv
import html
import json
import os
import sys
import time
from datetime import datetime, time as clock_time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common_high_range_watchlist_v1 import build_and_publish


DEFAULT_BASE = Path(r"C:\stock_bot")
DEFAULT_DESKTOP = Path(r"C:\Users\UserK\Desktop")
POLL_SECONDS = 2.0
LIVE_MAX_AGE_SECONDS = 15.0
MARKET_OPEN = clock_time(9, 0)
MARKET_CLOSE = clock_time(15, 30)
LOOP_STOP = clock_time(15, 35)


def _read_json(path: Path, default: dict) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return default


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(text, encoding="utf-8")
    # ★[2026-07-30 친구님 승인 "고저폭 보강 ①"] 읽는 쪽(브라우저·백신)이 파일을 잡으면
    #   os.replace 가 WinError 5 로 죽는다 — 7/29 11:29 S05 사망과 같은 계열. S05 와
    #   동일하게 0.2초 간격 재시도 3회. 그래도 실패면 종전대로 예외(원인 은폐 방지).
    for attempt in range(4):
        try:
            os.replace(temp, path)
            return
        except PermissionError:
            if attempt == 3:
                raise
            time.sleep(0.2)


_LAST_ERROR_LOG_TS = 0.0


def _log_error(base: Path, message: str) -> None:
    """오류를 로그로 남긴다. 60초에 1줄 — 지속 장애 시 로그 폭주 방지."""
    global _LAST_ERROR_LOG_TS
    now_ts = time.time()
    if now_ts - _LAST_ERROR_LOG_TS < 60.0:
        return
    _LAST_ERROR_LOG_TS = now_ts
    try:
        path = base / "data" / "LOG" / "sched_HIGH_RANGE_BOARD.log"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {message}\n")
    except OSError:
        pass  # 로그 실패가 관찰판을 죽이면 본말전도


def _number(value, default=0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _parse_time(value) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def _is_fresh(live_time: datetime | None, now: datetime) -> tuple[bool, float | None]:
    if live_time is None:
        return False, None
    age = (now - live_time).total_seconds()
    return live_time.date() == now.date() and -2.0 <= age <= LIVE_MAX_AGE_SECONDS, age


def _new_state(now: datetime) -> dict:
    return {
        "date": now.strftime("%Y%m%d"),
        "updated_at": now.isoformat(),
        "last_shadow_minute": "",
        "codes": {},
    }


def _update_extrema(row: dict, current: float, live_time: datetime) -> None:
    stamp = live_time.strftime("%H:%M:%S")
    if _number(row.get("first_price")) <= 0:
        row["first_price"] = current
        row["first_time"] = stamp
    if _number(row.get("low")) <= 0 or current < _number(row.get("low")):
        row["low"] = current
        row["low_time"] = stamp
        row["later_high"] = current
        row["later_high_time"] = stamp
    elif current > _number(row.get("later_high")):
        row["later_high"] = current
        row["later_high_time"] = stamp
    if _number(row.get("high")) <= 0 or current > _number(row.get("high")):
        row["high"] = current
        row["high_time"] = stamp


def update_live_state(
    candidates: list[dict],
    snapshot: dict,
    previous: dict,
    now: datetime,
) -> dict:
    state = previous if previous.get("date") == now.strftime("%Y%m%d") else _new_state(now)
    state["updated_at"] = now.isoformat()
    live_codes = snapshot.get("codes") or {}
    market_time = now.weekday() < 5 and MARKET_OPEN <= now.time() <= MARKET_CLOSE

    for candidate in candidates:
        code = candidate["code"]
        row = state["codes"].setdefault(code, {})
        live = live_codes.get(code) or {}
        current = abs(_number(live.get("cur")))
        live_time = _parse_time(live.get("ts"))
        fresh, age = _is_fresh(live_time, now)
        if fresh and market_time and current > 0 and live_time is not None:
            _update_extrema(row, current, live_time)
        money = _number(live.get("buy_money_cum")) + _number(
            live.get("sell_money_cum")
        )
        if money <= 0 and current > 0:
            money = current * _number(live.get("cum_vol"))
        buy_money = _number(live.get("buy_money_cum"))
        row.update(
            {
                "current": current,
                "live_ts": str(live.get("ts") or ""),
                "age_sec": None if age is None else round(age, 1),
                "status": "LIVE" if fresh and market_time else ("WAIT" if fresh else "STALE"),
                "live_value_eok": round(money / 100_000_000.0, 2),
                "che_str": round(_number(live.get("che_str")), 2),
                "buy_ratio_pct": round(buy_money / money * 100.0, 1)
                if money > 0
                else 0.0,
            }
        )
    return state


def _pct(current: float, base: float) -> float | None:
    if current <= 0 or base <= 0:
        return None
    return (current / base - 1.0) * 100.0


def _fmt_number(value, digits=0, suffix="") -> str:
    number = _number(value)
    return f"{number:,.{digits}f}{suffix}" if number else "-"


def _fmt_pct(value) -> str:
    if value is None:
        return "-"
    return f"{value:+.2f}%"


def _row_html(candidate: dict, live: dict) -> str:
    current = _number(live.get("current"))
    low = _number(live.get("low"))
    high = _number(live.get("high"))
    change = _pct(current, _number(candidate.get("prev_close")))
    rebound = _pct(current, low)
    status = str(live.get("status") or "STALE")
    crown = "👑고저폭" if candidate.get("crown") else ""
    row_class = "crown" if candidate.get("crown") else ""
    return (
        f"<tr class='{row_class}'>"
        f"<td>{candidate['rank']}</td><td>{crown}</td>"
        f"<td>{html.escape(candidate['stage'])}</td>"
        f"<td class='name'>{html.escape(candidate['name'])}</td>"
        f"<td>{html.escape(candidate['code'])}</td>"
        f"<td>{candidate['streak']}일</td>"
        # ★[2026-07-30 "NaN 결측 고치기"] 상장 5일 미만은 5일 지표가 null — "신규"로 표시
        f"<td>{'신규' if candidate.get('avg_5d_range_pct') is None else format(candidate['avg_5d_range_pct'], '.2f') + '%'}</td>"
        f"<td>{candidate['prev_value_eok']:,.2f}억</td>"
        f"<td>{'신규' if candidate.get('avg_5d_value_eok') is None else format(candidate['avg_5d_value_eok'], ',.2f') + '억'}</td>"
        f"<td>{_fmt_number(current)}</td><td>{_fmt_pct(change)}</td>"
        f"<td>{_fmt_number(low)}</td><td>{html.escape(str(live.get('low_time') or '-'))}</td>"
        f"<td>{_fmt_pct(rebound)}</td><td>{_fmt_number(high)}</td>"
        f"<td>{html.escape(str(live.get('high_time') or '-'))}</td>"
        f"<td>{_fmt_number(live.get('live_value_eok'), 2, '억')}</td>"
        f"<td>{_fmt_number(live.get('che_str'), 1)}</td>"
        f"<td>{_fmt_number(live.get('buy_ratio_pct'), 1, '%')}</td>"
        f"<td class='{status.lower()}'>{status}</td></tr>"
    )


def render_html(payload: dict, state: dict, now: datetime) -> str:
    rows = "\n".join(
        _row_html(candidate, state.get("codes", {}).get(candidate["code"], {}))
        for candidate in payload.get("candidates", [])
    )
    filters = payload.get("filters") or {}
    # ★[2026-07-30 친구님 승인 "⑤도 해줘"] 일봉이 낡은 채 만들어진 유니버스는 빨간 경고
    alert = "" if not payload.get("source_stale") else (
        "<div class='alert'>⚠ 일봉이 낡았습니다 — 기준일 "
        f"{payload.get('source_date','-')} (직전 거래일 {payload.get('expected_source_date','-')} 아님). "
        "어젯밤 일봉 수집(16:05) 실패 여부를 확인하세요. 아래 목록은 낡은 일봉 기준입니다.</div>")
    return f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8">
<meta http-equiv="refresh" content="3">
<title>고저폭 왕관 후보</title>
<style>
body{{margin:16px;background:#071018;color:#e8eef5;font-family:"Malgun Gothic",sans-serif;font-size:18px}}
h1{{margin:0 0 10px;color:#ffd54a}} .summary{{color:#a9bacb;margin-bottom:12px}}
.alert{{background:#4a1010;color:#ffb3b3;border:1px solid #7a2626;border-radius:8px;
padding:12px 14px;margin:10px 0;font-weight:700;font-size:19px}}
.rules{{display:grid;grid-template-columns:repeat(4,minmax(180px,1fr));gap:8px;margin:12px 0}}
.rule{{background:#122333;border:1px solid #365269;border-radius:7px;padding:10px}}
.wrap{{overflow:auto;border:1px solid #365269}} table{{border-collapse:collapse;width:100%;white-space:nowrap}}
th,td{{border-bottom:1px solid #25394a;padding:8px 9px;text-align:right}}
th{{position:sticky;top:0;background:#173047;color:#d9ecff}} td.name,th.name{{text-align:left}}
tr.crown{{background:#3a2f05;color:#fff4b0;font-weight:700}}
.live{{color:#57e389}} .wait{{color:#f4c95d}} .stale{{color:#ff6b6b}}
.foot{{margin-top:10px;color:#9fb0c8;font-size:15px}}
</style></head><body>
<h1>👑고저폭 1~30위 실시간 관찰판</h1>
{alert}
<div class="summary">화면 {now:%Y-%m-%d %H:%M:%S} · 후보 기준일 {payload.get('source_date','-')}
 · 후보 {payload.get('candidate_count',0)}개 · 👑 {payload.get('crown_count',0)}개 · 주문 0 관찰모드</div>
<div class="rules">
<div class="rule">주가 <b>{filters.get('price_min_krw',0):,.0f}원 이상</b></div>
<div class="rule">전일 고저폭 <b>{filters.get('daily_range_min_pct',0):.0f}% 이상</b></div>
<div class="rule">전일 거래대금 <b>{filters.get('daily_value_min_eok',0):.0f}억 이상</b></div>
<div class="rule">👑 5일 이상 + 5일 평균대금 <b>{filters.get('core_avg_5d_value_min_eok',0):.0f}억 이상</b></div>
</div>
<div class="wrap"><table><thead><tr>
<th>순위</th><th>왕관</th><th>단계</th><th class="name">종목명</th><th>종목코드</th>
<th>연속</th><th>5일평균폭</th><th>전일대금</th><th>5일평균대금</th>
<th>현재가</th><th>전일대비</th><th>오늘저점</th><th>저점시각</th><th>저점대비</th>
<th>오늘고점</th><th>고점시각</th><th>실시간대금</th><th>체결강도</th><th>매수비</th><th>상태</th>
</tr></thead><tbody>{rows}</tbody></table></div>
<div class="foot">최저·최고는 이 관찰기가 09:00 이후 실제로 받은 현재가 기준입니다.
왕관은 매수신호가 아니며 각 전략의 고유 매수조건을 통과해야 합니다.</div>
</body></html>"""


def append_range_shadow(
    base: Path,
    payload: dict,
    state: dict,
    now: datetime,
) -> None:
    # ★[2026-07-30 친구님 승인 "고저폭 보강 ③"] 왕관만 분당 기록 → 30종목 전수 기록.
    #   저점매수 설계(DOCS\저점매수_익일매도_설계_20260730.md 8-①)의 재료:
    #   시가 대비 문턱(-3~-13%) 도달시각·저점시각은 이 분당 누적저점(low)으로 계산하고,
    #   first_price(09:00 이후 첫 관측가 = 시가 근사)·crown 컬럼을 새로 실었다.
    #   구독이 안 된 종목도 STALE 줄로 남긴다(구독 구멍의 증거 = 보강 ② 재료).
    #   기존 high_range_crown_shadow_*.csv 는 역사 기록으로 그대로 둔다(더 안 씀).
    minute = now.strftime("%Y%m%d%H%M")
    if now.weekday() >= 5 or not (MARKET_OPEN <= now.time() <= MARKET_CLOSE):
        return
    if state.get("last_shadow_minute") == minute:
        return
    path = base / "data" / f"high_range_shadow_{now:%Y%m%d}.csv"
    columns = [
        "ts", "rank", "crown", "code", "name", "prev_close",
        "first_price", "first_time", "current", "low", "low_time",
        "high", "high_time", "change_pct", "rebound_from_low_pct",
        "live_value_eok", "che_str", "buy_ratio_pct", "status",
    ]
    exists = path.exists()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        if not exists:
            writer.writeheader()
        for candidate in payload.get("candidates", []):
            live = state.get("codes", {}).get(candidate["code"], {})
            current = _number(live.get("current"))
            low = _number(live.get("low"))
            writer.writerow(
                {
                    "ts": now.isoformat(),
                    "rank": candidate["rank"],
                    "crown": 1 if candidate.get("crown") else 0,
                    "code": candidate["code"],
                    "name": candidate["name"],
                    "prev_close": candidate["prev_close"],
                    "first_price": _number(live.get("first_price")),
                    "first_time": live.get("first_time", ""),
                    "current": current,
                    "low": low,
                    "low_time": live.get("low_time", ""),
                    "high": _number(live.get("high")),
                    "high_time": live.get("high_time", ""),
                    "change_pct": _pct(current, candidate["prev_close"]),
                    "rebound_from_low_pct": _pct(current, low),
                    "live_value_eok": _number(live.get("live_value_eok")),
                    "che_str": _number(live.get("che_str")),
                    "buy_ratio_pct": _number(live.get("buy_ratio_pct")),
                    "status": live.get("status", "STALE"),
                }
            )
    state["last_shadow_minute"] = minute


def run_once(base: Path, desktop: Path, now: datetime | None = None) -> tuple[dict, dict, Path]:
    now = now or datetime.now()
    board_path = base / "data" / "common_high_range_top30.json"
    eod_path = base / "data" / "eod_daily_bars.csv"
    existing_payload = _read_json(board_path, {}) if board_path.exists() else {}
    needs_build = not board_path.exists()
    needs_build = needs_build or existing_payload.get("for_date") != now.strftime("%Y%m%d")
    if board_path.exists() and eod_path.exists():
        needs_build = needs_build or eod_path.stat().st_mtime > board_path.stat().st_mtime
    if needs_build:
        build_and_publish(base=base, eod_path=eod_path, now=now)
    payload = _read_json(board_path, {})
    snapshot = _read_json(base / "IPC" / "live_micro_snapshot.json", {})
    state_path = base / "data" / "common_high_range_live_state.json"
    previous = _read_json(state_path, _new_state(now))
    state = update_live_state(payload.get("candidates", []), snapshot, previous, now)
    # ★[2026-07-30 친구님 승인 "고저폭 보강 ①"] CSV 를 엑셀 등이 잡고 있어도
    #   실황판(상태 JSON·바탕화면 HTML) 갱신은 계속한다. 실패는 로그로만.
    try:
        append_range_shadow(base, payload, state, now)
    except Exception as exc:
        _log_error(base, f"분당기록 실패 — {type(exc).__name__}: {exc}")
    _atomic_write(state_path, json.dumps(state, ensure_ascii=False, indent=2))
    html_path = desktop / "고저폭_왕관후보.html"
    _atomic_write(html_path, render_html(payload, state, now))
    return payload, state, html_path


def _acquire_lock(base: Path):
    import msvcrt

    path = base / "data" / "common_high_range_board.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+")
    handle.seek(0)
    if handle.read(1) == "":
        handle.write("1")
        handle.flush()
    handle.seek(0)
    try:
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        handle.close()
        return None
    return handle


def run_loop(base: Path, desktop: Path, open_board: bool) -> int:
    lock = _acquire_lock(base)
    if lock is None:
        return 0
    opened = False
    try:
        while True:
            now = datetime.now()
            # ★[2026-07-30 친구님 승인 "고저폭 보강 ①"] 한 바퀴 실패(일봉 읽기 오류·
            #   저장 충돌 등)가 관찰판 전체를 죽이지 않게 — 7/29 S05 가 예외 1번으로
            #   마감까지 방치된 사고의 재발 방지. 실패 바퀴는 로그 남기고 건너뛴다.
            #   프로세스 완전 사망은 s05_signal_guard_v1(HR30 감시)이 되살린다.
            #   롤백: try 블록 제거 = backup\high_range_live_board_v1_20260730_deathproof_fullshadow.py
            try:
                _, _, html_path = run_once(base, desktop, now)
                if open_board and not opened:
                    os.startfile(html_path)
                    opened = True
            except Exception as exc:
                _log_error(base, f"run_once 실패 — {type(exc).__name__}: {exc}")
            if (now.weekday() >= 5 or now.time() < clock_time(8, 30)
                    or now.time() >= LOOP_STOP):
                return 0
            time.sleep(POLL_SECONDS)
    finally:
        lock.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", type=Path, default=DEFAULT_BASE)
    parser.add_argument("--desktop", type=Path, default=DEFAULT_DESKTOP)
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--open", action="store_true")
    args = parser.parse_args()
    if args.loop:
        return run_loop(args.base, args.desktop, args.open)
    payload, _, html_path = run_once(args.base, args.desktop)
    if args.open:
        os.startfile(html_path)
    print(
        f"HIGH_RANGE_BOARD source={payload.get('source_date')} "
        f"count={payload.get('candidate_count')} html={html_path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
