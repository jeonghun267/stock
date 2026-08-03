# -*- coding: utf-8 -*-
"""저점매수→익일 오전 매도 그림자 기록기 (주문 0 · 조회만).

★[2026-07-30 친구님 지시 "그림자로 먼저 돌려줘 + 바탕화면에도 만들어줘"]
설계 원본: DOCS\저점매수_익일매도_설계_20260730.md (8-① 그림자 기록기).

무엇을 하나
  · 고저폭 TOP30(data\common_high_range_top30.json)을 실시간 스냅샷으로 관찰
  · 진입창 11:00~14:30 에서 두 방식의 가상 체결을 기록 (실제 주문 0)
      고정지정가: 시가 대비 -3/-5/-7/-10/-13% 각 문턱 최초 도달 시각·가격
      반등확인(저점추적 근사): 당일저점 대비 +1.0% 회복 & 시가 대비 -3% 이하일 때 1회 체결
  · 익일 09:00/09:05/09:10/09:15 가격을 잡아 전날 가상 체결의 아침 성과를 기록
    (어제 급락주는 고저폭 기준상 오늘도 TOP30 에 남아 전용 통로로 시세가 온다)
  · 바탕화면 저점매수_그림자.html 실황판 (친구님 열람용)

산출물
  data\lowbuy_shadow\lowbuy_shadow_state.json      오늘 작업 상태(감시 대상·2초 갱신)
  data\lowbuy_shadow\lowbuy_shadow_YYYYMMDD.json   날짜별 보관(다음날 아침 성과 계산 재료)
  바탕화면\저점매수_그림자.html

사망 내성: os.replace 재시도 + 바퀴 예외 방어(고저폭 실황판과 동일 계열)
  + s05_signal_guard_v1 의 LBSH 감시로 재기동.
롤백: 태스크 SAFEPLUS_LOWBUY_SHADOW Disable + 이 파일 삭제(다른 파일 수정 없음).
"""
from __future__ import annotations

import argparse
import html
import json
import os
import time
from datetime import datetime, time as clock_time
from pathlib import Path

DEFAULT_BASE = Path(r"C:\stock_bot")
DEFAULT_DESKTOP = Path(r"C:\Users\UserK\Desktop")
POLL_SECONDS = 2.0
LIVE_MAX_AGE_SECONDS = 15.0

OPEN_TRACK_START = clock_time(9, 0)      # 시가 근사·저점 추적 시작
ENTRY_START = clock_time(11, 0)          # 진입창(친구님 확정: 11:00~14:30, 13:00 경계는 시각으로 사후 구분)
ENTRY_END = clock_time(14, 30)
LOOP_STOP = clock_time(14, 40)
FIXED_LEVELS = (3.0, 5.0, 7.0, 10.0, 13.0)   # 시가 대비 -X% 고정지정가(미확정 문턱 전부 병행 기록)
REBOUND_PCT = 1.0                             # 저점 대비 +1.0% 회복 = 반등확인 가상 체결
REBOUND_MIN_DEPTH_PCT = 3.0                   # 시가 대비 최소 -3% 는 빠져 있어야 자격
MORNING_MARKS = ("0900", "0905", "0910", "0915")


def _read_json(path: Path, default: dict) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return default


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(text, encoding="utf-8")
    # 읽는 쪽이 잡은 순간의 WinError 5 대비 — 고저폭 실황판·S05 와 동일한 재시도.
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
    global _LAST_ERROR_LOG_TS
    now_ts = time.time()
    if now_ts - _LAST_ERROR_LOG_TS < 60.0:
        return
    _LAST_ERROR_LOG_TS = now_ts
    try:
        path = base / "data" / "LOG" / "sched_LOWBUY_SHADOW.log"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {message}\n")
    except OSError:
        pass


def _number(value, default=0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _fresh_price(live: dict, now: datetime) -> float | None:
    """스냅샷 한 종목에서 '오늘·15초 이내' 현재가만 신뢰."""
    try:
        ts = datetime.fromisoformat(str(live.get("ts")))
    except (TypeError, ValueError):
        return None
    age = (now - ts).total_seconds()
    if ts.date() != now.date() or not (-2.0 <= age <= LIVE_MAX_AGE_SECONDS):
        return None
    current = abs(_number(live.get("cur")))
    return current if current > 0 else None


def _new_state(now: datetime, universe: dict) -> dict:
    codes = {}
    for row in universe.get("candidates") or []:
        codes[row["code"]] = {
            "rank": row.get("rank"),
            "crown": bool(row.get("crown")),
            "name": row.get("name"),
            "prev_close": _number(row.get("prev_close")),
            "open_px": 0.0, "open_time": "",
            "low": 0.0, "low_time": "",
            "current": 0.0, "status": "대기",
            "fills_fixed": {},          # {"5": {"px":..,"time":..,"depth":..}}
            "fill_rebound": None,       # {"px","time","low","low_time","premium_pct","depth"}
        }
    return {
        "date": now.strftime("%Y%m%d"),
        "updated_at": now.isoformat(),
        "universe_date": str(universe.get("for_date") or ""),
        "codes": codes,
        "sell_leg": {"prev_date": "", "marks": {}},
    }


def _track_and_fill(row: dict, price: float, now: datetime) -> None:
    stamp = now.strftime("%H:%M:%S")
    if row["open_px"] <= 0 and now.time() >= OPEN_TRACK_START:
        row["open_px"] = price
        row["open_time"] = stamp
    if row["open_px"] <= 0:
        return
    if row["low"] <= 0 or price < row["low"]:
        row["low"] = price
        row["low_time"] = stamp
    depth = (price / row["open_px"] - 1.0) * 100.0
    in_window = ENTRY_START <= now.time() <= ENTRY_END
    if not in_window:
        return
    # 고정지정가: 시가 -X% 이하로 처음 내려온 순간의 가격으로 가상 체결
    for level in FIXED_LEVELS:
        key = f"{level:g}"
        if key in row["fills_fixed"]:
            continue
        if price <= row["open_px"] * (1.0 - level / 100.0):
            row["fills_fixed"][key] = {
                "px": price, "time": stamp, "depth_pct": round(depth, 2),
            }
    # 반등확인(저점추적 근사): 시가 대비 -3% 이하 & 저점 대비 +1.0% 회복 시 1회 체결
    if row["fill_rebound"] is None and depth <= -REBOUND_MIN_DEPTH_PCT:
        low = row["low"]
        if low > 0 and price >= low * (1.0 + REBOUND_PCT / 100.0):
            row["fill_rebound"] = {
                "px": price, "time": stamp,
                "low": low, "low_time": row["low_time"],
                "premium_pct": round((price / low - 1.0) * 100.0, 2),
                "depth_pct": round(depth, 2),
            }


def _morning_marks(state: dict, prev_day: dict, snapshot: dict, now: datetime) -> None:
    """어제 가상 체결 종목의 09:00/05/10/15 가격 채집(그 시각 이후 첫 신선가)."""
    if not prev_day:
        return
    if not (clock_time(9, 0) <= now.time() <= clock_time(9, 20)):
        return
    leg = state["sell_leg"]
    leg["prev_date"] = str(prev_day.get("date") or "")
    hhmm = now.strftime("%H%M")
    live_codes = snapshot.get("codes") or {}
    for code, row in (prev_day.get("codes") or {}).items():
        if not row.get("fills_fixed") and not row.get("fill_rebound"):
            continue
        price = _fresh_price(live_codes.get(code) or {}, now)
        if price is None:
            continue
        marks = leg["marks"].setdefault(code, {})
        for mark in MORNING_MARKS:
            if mark not in marks and hhmm >= mark:
                marks[mark] = {"px": price, "time": now.strftime("%H:%M:%S")}


def _load_prev_day(data_dir: Path, today: str) -> dict:
    files = sorted(
        f for f in data_dir.glob("lowbuy_shadow_2*.json")
        if f.stem.split("_")[-1] < today
    )
    return _read_json(files[-1], {}) if files else {}


def _fmt(value, digits=0, suffix="") -> str:
    number = _number(value)
    return f"{number:,.{digits}f}{suffix}" if number else "-"


def _fmt_pct(value) -> str:
    return "-" if value in (None, "") else f"{_number(value):+.2f}%"


def _ret_pct(sell, buy) -> float | None:
    sell = _number(sell)
    buy = _number(buy)
    if sell <= 0 or buy <= 0:
        return None
    return (sell / buy - 1.0) * 100.0


def _today_rows_html(state: dict) -> str:
    rows = []
    items = sorted(
        state.get("codes", {}).items(),
        key=lambda kv: (kv[1]["open_px"] <= 0 or kv[1]["current"] <= 0,
                        (kv[1]["current"] / kv[1]["open_px"] - 1.0)
                        if kv[1]["open_px"] > 0 and kv[1]["current"] > 0 else 0.0),
    )
    for code, row in items:
        open_px = row["open_px"]
        current = row["current"]
        depth = _ret_pct(current, open_px)
        low_vs = _ret_pct(current, row["low"]) if row["low"] > 0 else None
        rebound = row.get("fill_rebound") or {}
        fixed_cells = []
        for level in FIXED_LEVELS:
            fill = row["fills_fixed"].get(f"{level:g}")
            fixed_cells.append(
                f"<td>{fill['time'][:5]}<br>{_fmt(fill['px'])}</td>" if fill else "<td>-</td>"
            )
        cls = "hit" if rebound else ""
        status = str(row.get("status") or "대기")
        status_cls = {"수신중": "live", "대기": "stale", "장외": "closed"}.get(status, "stale")
        rows.append(
            f"<tr class='{cls}'><td>{row.get('rank') or '-'}</td>"
            f"<td>{'👑' if row.get('crown') else ''}</td>"
            f"<td class='name'>{html.escape(str(row.get('name') or ''))}</td>"
            f"<td>{html.escape(code)}</td>"
            f"<td>{_fmt(row.get('prev_close'))}</td>"
            f"<td>{_fmt(open_px)}</td><td>{_fmt(current)}</td>"
            f"<td>{_fmt_pct(depth)}</td>"
            f"<td>{_fmt(row['low'])}</td><td>{row.get('low_time','')[:5] or '-'}</td>"
            f"<td>{_fmt_pct(low_vs)}</td>"
            f"<td>{(rebound.get('time') or '')[:5] or '-'}<br>{_fmt(rebound.get('px'))}"
            f"{'' if not rebound else ' (저점+' + format(rebound.get('premium_pct') or 0, '.1f') + '%)'}</td>"
            + "".join(fixed_cells)
            + f"<td class='{status_cls}'>{status}</td></tr>"
        )
    return "\n".join(rows)


def _morning_rows_html(state: dict, prev_day: dict) -> str:
    rows = []
    marks_all = (state.get("sell_leg") or {}).get("marks") or {}
    for code, row in (prev_day.get("codes") or {}).items():
        marks = marks_all.get(code) or {}
        variants = []
        rebound = row.get("fill_rebound")
        if rebound:
            variants.append(("반등확인", rebound))
        for level in FIXED_LEVELS:
            fill = (row.get("fills_fixed") or {}).get(f"{level:g}")
            if fill:
                variants.append((f"고정 -{level:g}%", fill))
        for label, fill in variants:
            buy = _number(fill.get("px"))
            cells = []
            for mark in MORNING_MARKS:
                px = _number((marks.get(mark) or {}).get("px"))
                ret = _ret_pct(px, buy)
                cells.append(f"<td>{_fmt(px)}<br>{_fmt_pct(ret)}</td>")
            rows.append(
                f"<tr><td class='name'>{html.escape(str(row.get('name') or ''))}</td>"
                f"<td>{html.escape(code)}</td><td>{label}</td>"
                f"<td>{fill.get('time','')[:5]}</td><td>{_fmt(buy)}</td>"
                + "".join(cells) + "</tr>"
            )
    return "\n".join(rows)


def render_html(state: dict, prev_day: dict, now: datetime, observing: bool) -> str:
    codes = state.get("codes", {})
    live_n = sum(1 for r in codes.values() if r.get("status") == "수신중")
    rebound_n = sum(1 for r in codes.values() if r.get("fill_rebound"))
    fixed_head = "".join(f"<th>-{lv:g}%</th>" for lv in FIXED_LEVELS)
    morning = _morning_rows_html(state, prev_day)
    notice = "" if observing else (
        "<div class='notice'>지금은 관찰 시간이 아닙니다 — 수집은 거래일 09:00~14:40"
        " (진입 기록은 11:00~14:30). 빈 칸은 고장이 아니라 정상이며,"
        " 다음 거래일 09:00부터 자동으로 채워집니다.</div>")
    return f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8">
<meta http-equiv="refresh" content="3">
<title>저점매수 그림자</title>
<style>
body{{margin:16px;background:#071018;color:#e8eef5;font-family:"Malgun Gothic",sans-serif;font-size:18px}}
h1{{margin:0 0 10px;color:#ffd54a}} h2{{margin:18px 0 8px;color:#ffd54a}}
.summary{{color:#a9bacb;margin-bottom:12px}}
.notice{{background:#3a2f05;color:#ffe08a;border:1px solid #6b5b1a;border-radius:8px;
padding:12px 14px;margin:10px 0;font-weight:700;font-size:19px}}
.rules{{display:grid;grid-template-columns:repeat(4,minmax(180px,1fr));gap:8px;margin:12px 0}}
.rule{{background:#122333;border:1px solid #365269;border-radius:7px;padding:10px}}
.wrap{{overflow:auto;border:1px solid #365269}} table{{border-collapse:collapse;width:100%;white-space:nowrap}}
th,td{{border-bottom:1px solid #25394a;padding:8px 9px;text-align:right}}
th{{position:sticky;top:0;background:#173047;color:#d9ecff}} td.name,th.name{{text-align:left}}
tr.hit{{background:#0e3320;color:#c9ffd8;font-weight:700}}
.live{{color:#57e389}} .stale{{color:#ff6b6b}} .closed{{color:#8a97a8}}
.foot{{margin-top:10px;color:#9fb0c8;font-size:15px}}
</style></head><body>
<h1>저점매수 그림자 — 주문 0 관찰</h1>
{notice}
<div class="summary">화면 {now:%Y-%m-%d %H:%M:%S} · 유니버스(고저폭 TOP30) 기준일 {state.get('universe_date','-')}
 · 수신중 {live_n}/{len(codes)} · 반등확인 가상체결 {rebound_n}건</div>
<div class="rules">
<div class="rule">진입창 <b>11:00~14:30</b></div>
<div class="rule">반등확인 = 저점 <b>+1.0% 회복</b> 시 체결 간주</div>
<div class="rule">고정지정가 <b>-3~-13%</b> 5문턱 병행</div>
<div class="rule"><b>주문 0</b> 그림자 관찰</div>
</div>
<h2>어제 가상체결 → 오늘 아침 성과 (09:00 / 09:05 / 09:10 / 09:15)</h2>
<div class="wrap"><table><thead><tr>
<th class="name">종목명</th><th>코드</th><th>방식</th><th>체결시각</th><th>체결가</th>
<th>09:00</th><th>09:05</th><th>09:10</th><th>09:15</th>
</tr></thead><tbody>{morning or '<tr><td colspan=9>어제 가상체결 없음 (또는 첫날)</td></tr>'}</tbody></table></div>
<h2>오늘 관찰 (시가 대비 깊은 순)</h2>
<div class="wrap"><table><thead><tr>
<th>순위</th><th>왕관</th><th class="name">종목명</th><th>코드</th><th>전일종가</th>
<th>시가(근사)</th><th>현재가</th><th>시가대비</th><th>저점</th><th>저점시각</th><th>저점대비</th>
<th>반등확인 체결</th>{fixed_head}<th>상태</th>
</tr></thead><tbody>{_today_rows_html(state)}</tbody></table></div>
<div class="foot">가상 체결이며 실제 주문은 0건입니다. 고정 -X% 칸 = 시가 대비 그 깊이에 걸어둔 지정가가
처음 닿은 시각·그때 가격. 문턱·진입방식 확정 후 종가매수(EOD_GAP)에 연결 예정 —
설계: DOCS\\저점매수_익일매도_설계_20260730.md</div>
</body></html>"""


def run_once(base: Path, desktop: Path, now: datetime | None = None) -> Path:
    now = now or datetime.now()
    data_dir = base / "data" / "lowbuy_shadow"
    state_path = data_dir / "lowbuy_shadow_state.json"
    today = now.strftime("%Y%m%d")
    universe = _read_json(base / "data" / "common_high_range_top30.json", {})
    state = _read_json(state_path, {})
    if state.get("date") != today:
        # 전일 상태는 날짜 파일로 보관(아침 성과 계산 재료) 후 새로 시작
        if state.get("date"):
            _atomic_write(data_dir / f"lowbuy_shadow_{state['date']}.json",
                          json.dumps(state, ensure_ascii=False, indent=1))
        state = _new_state(now, universe)
    if not state.get("codes") and universe.get("candidates"):
        state = _new_state(now, universe)
    prev_day = _load_prev_day(data_dir, today)
    snapshot = _read_json(base / "IPC" / "live_micro_snapshot.json", {})
    live_codes = snapshot.get("codes") or {}
    # ★[2026-07-30 친구님 "이상한 그림만 나와"] 관찰창(거래일 09:00~14:40) 밖에서는 기록하지
    #   않는다 — 장외에 실행하면 시간외 가격을 시가·저점으로 오인해 화면이 엉킨다(7/30 실제 발생).
    observing = now.weekday() < 5 and OPEN_TRACK_START <= now.time() <= LOOP_STOP
    for code, row in state["codes"].items():
        if not observing:
            row["status"] = "장외"
            continue
        price = _fresh_price(live_codes.get(code) or {}, now)
        if price is None:
            row["status"] = "대기"
            continue
        row["status"] = "수신중"
        row["current"] = price
        _track_and_fill(row, price, now)
    _morning_marks(state, prev_day, snapshot, now)
    state["updated_at"] = now.isoformat()
    _atomic_write(state_path, json.dumps(state, ensure_ascii=False, indent=1))
    # 날짜 파일도 함께 최신화(장중 사망해도 당일 기록 보존)
    _atomic_write(data_dir / f"lowbuy_shadow_{today}.json",
                  json.dumps(state, ensure_ascii=False, indent=1))
    html_path = desktop / "저점매수_그림자.html"
    _atomic_write(html_path, render_html(state, prev_day, now, observing))
    return html_path


def _acquire_lock(base: Path):
    import msvcrt

    path = base / "data" / "lowbuy_shadow" / "lowbuy_shadow.lock"
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


def run_loop(base: Path, desktop: Path) -> int:
    lock = _acquire_lock(base)
    if lock is None:
        return 0
    try:
        while True:
            now = datetime.now()
            try:
                run_once(base, desktop, now)
            except Exception as exc:
                _log_error(base, f"run_once 실패 — {type(exc).__name__}: {exc}")
            if now.weekday() >= 5 or now.time() >= LOOP_STOP:
                return 0
            time.sleep(POLL_SECONDS)
    finally:
        lock.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", type=Path, default=DEFAULT_BASE)
    parser.add_argument("--desktop", type=Path, default=DEFAULT_DESKTOP)
    parser.add_argument("--loop", action="store_true")
    args = parser.parse_args()
    if args.loop:
        return run_loop(args.base, args.desktop)
    html_path = run_once(args.base, args.desktop)
    print(f"LOWBUY_SHADOW html={html_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
