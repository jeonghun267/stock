r"""자료원 조기 경보 — board(08:45) / preopen(08:55) / live(09:00:20). 읽기 전용.

★[2026-08-17 친구님 지시] 8/14 사고 재발 방지용.
  8/14 09:00:16 정규 사전점검이 SOURCE_EMPTY:high_range_top30 으로 실패했고
  자동복구 시한(09:05)을 넘겨 S01 매수창(entry_end 09:20)이 통째로 날아갔다.
  근본 구멍은 "08:40 판 생성 ~ 08:59 정규 사전점검" 사이를 아무도 안 본다는 것.
  이 파일은 세 번 들여다보고, 실패면 화면에 띄우기만 한다.

★설계 계약 — 절대 금지(어기면 이 파일의 존재 이유가 사라진다):
  - OFF/승인/수동차단 플래그를 만들거나 지우지 않는다.
  - 프로세스·태스크를 재기동하지 않는다. 정규 사전점검을 대신 돌리지 않는다.
  - 브로커를 조회하지 않는다. 주문·전략 엔진 모듈을 import 하지 않는다.
  - 쓰는 파일은 아래 둘뿐이다.
      보고서\자료원_조기경보_YYYYMMDD.json   (실행마다 runs 에 누적)
      data\LOG\sched_SOURCE_EARLY_WARN.log
  즉 이 검사는 무엇도 고치지 않는다. 사람에게 알리기만 한다.

★단계는 시계로 추측하지 않는다. --phase 로 못 박는다.
  늦게 기동해도 엉뚱한 검사를 돌리지 않도록 단계마다 유효 시간창을 두고,
  창을 벗어나면 SKIP 한다(--force 로 무시 가능, 수동 점검용).

★판정 등급
  FAIL  즉시 사람이 봐야 한다 → 팝업 + 종료코드 1
  WARN  기록만 한다 → 팝업 없음, 종료코드 0
  장 시작 전(preopen)에는 실시간 3종이 비어 있는 게 정상일 수 있어 WARN 이고,
  장이 열린 뒤(live)에는 같은 상태가 곧 사전점검 실패이므로 FAIL 이다.

★어떤 자료가 깨져 있어도 예외로 죽지 않는다. 죽으면 아무도 모른다(8/5 교훈).
  숫자가 아닌 값·못 읽는 JSON·못 읽는 휴장일 파일 전부 FAIL 로 적고 계속 간다.
"""
from __future__ import annotations

import json
import sys
import time as time_module
from datetime import datetime, time as day_time
from pathlib import Path
from typing import Any

RUN_DIR = Path(__file__).resolve().parent
if str(RUN_DIR) not in sys.path:
    sys.path.insert(0, str(RUN_DIR))

ROOT = Path(r"C:\stock_bot")
CONFIG = ROOT / "config"
DATA = ROOT / "data"
REPORT_DIR = ROOT / "보고서"
LOG_PATH = DATA / "LOG" / "sched_SOURCE_EARLY_WARN.log"

BOARD = DATA / "common_high_range_top30.json"
CONTEXT = DATA / "strategy_common_candidate_context_v1.json"
PREFLIGHT_AUDIT = DATA / "strategy_all_auto_live_preflight_v1.json"
HOLIDAYS = CONFIG / "krx_holidays.txt"

# 정규 사전점검과 동일해야 한다. 여기만 늘리면 08:59 에 새로 죽는다.
REQUIRED_SOURCES = (
    "captain_money_rank",
    "moneyflow_selector",
    "moneyflow_watch",
    "high_range_top30",
)
# 장 시작 전에는 비어 있는 게 정상일 수 있는 실시간 자료원.
REALTIME_SOURCES = frozenset({
    "captain_money_rank",
    "moneyflow_selector",
    "moneyflow_watch",
})
# 정규 사전점검의 source_ts 최대 나이(초). high_range_top30 은 08:40 산출물이라 면제.
SOURCE_MAX_AGE_SEC = {
    "captain_money_rank": 30,
    "moneyflow_selector": 60,
    "moneyflow_watch": 60,
}
CONTEXT_MAX_AGE_SEC = 5          # 정규 사전점검의 CONTEXT_STALE 기준과 동일

# 단계별 유효 시간창. 벗어나 기동하면 검사하지 않는다.
PHASE_WINDOWS = {
    "board": (day_time(8, 30), day_time(8, 54)),
    "preopen": (day_time(8, 50), day_time(8, 59)),
    "live": (day_time(9, 0), day_time(9, 20)),   # S01 entry_end 09:20
}
# 단계별 재확인 마감.
PHASE_DEADLINES = {
    "preopen": day_time(8, 56, 30),
    "live": day_time(9, 1, 0),
}
RETRY_SEC = 0.25

FAIL, WARN, PASS, INFO = "FAIL", "WARN", "PASS", "INFO"
UNVERIFIED = "[UNVERIFIED]"

Result = tuple[str, str, str]


def _read_json(path: Path) -> tuple[dict[str, Any], str]:
    """(내용, 오류사유). 못 읽으면 ({}, 사유) — 예외를 올리지 않는다."""
    try:
        loaded = json.loads(path.read_text(encoding="utf-8-sig"))
    except OSError as exc:
        return {}, f"파일을 못 읽음({type(exc).__name__})"
    except ValueError as exc:
        return {}, f"JSON 형식이 깨짐({exc})"
    if not isinstance(loaded, dict):
        return {}, f"최상위가 사전이 아님({type(loaded).__name__})"
    return loaded, ""


def _as_int(raw: Any) -> tuple[bool, int]:
    """(성공, 값). bool·None·문자열 쓰레기를 전부 걸러낸다."""
    if isinstance(raw, bool) or raw is None:
        return False, 0
    if isinstance(raw, int):
        return True, raw
    if isinstance(raw, float):
        return (True, int(raw)) if raw == int(raw) else (False, 0)
    if isinstance(raw, str):
        try:
            return True, int(raw.strip())
        except ValueError:
            return False, 0
    return False, 0


def _age_seconds(now: datetime, raw: Any) -> float:
    """ISO('T' 구분)와 '2026-08-17 14:20:58' 두 형식을 모두 받는다.

    못 읽으면 무한대를 돌려 '낡음'으로 본다(fail-closed).
    """
    text = str(raw or "").strip()
    if not text:
        return float("inf")
    try:
        return (now - datetime.fromisoformat(text)).total_seconds()
    except (ValueError, TypeError):
        return float("inf")


def _age_text(age: float) -> str:
    return "읽기실패" if age == float("inf") else f"{age:.1f}초"


def trading_day_results(now: datetime) -> tuple[bool, list[Result]]:
    """(검사할 것인가, 결과줄). 휴장일 파일을 못 읽어도 죽지 않고 FAIL 로 적는다."""
    if now.weekday() >= 5:
        return False, [(INFO, "거래일", "주말(NOT_A_WEEKDAY) — 검사하지 않는다")]
    try:
        holidays = {
            line.strip()
            for line in HOLIDAYS.read_text(encoding="utf-8-sig").splitlines()
            if line.strip() and not line.strip().startswith("#")
        }
    except OSError as exc:
        # 휴장일인지 알 수 없다. 검사는 계속하되 사람이 알아야 한다.
        return True, [(FAIL, "휴장일 파일",
                       f"{HOLIDAYS} 를 못 읽음({type(exc).__name__})"
                       " — 휴장 여부를 확인하지 못한 채 검사했다")]
    if now.strftime("%Y%m%d") in holidays:
        return False, [(INFO, "거래일", "휴장일(KRX_HOLIDAY) — 검사하지 않는다")]
    return True, []


def check_board(now: datetime, board: dict[str, Any], error: str = "") -> list[Result]:
    """08:40 에 만들어졌어야 할 고저폭판이 오늘 것이고 비어있지 않은가."""
    today = now.strftime("%Y%m%d")
    results: list[Result] = []

    if error or not board:
        return [(FAIL, "고저폭판 파일", error or f"내용이 비었음: {BOARD}")]

    for_date = str(board.get("for_date") or "")
    if for_date != today:
        results.append((FAIL, "고저폭판 날짜",
                        f"for_date={for_date or '(없음)'} != 오늘({today})"))
    else:
        results.append((PASS, "고저폭판 날짜", f"for_date={for_date}"))

    stale = board.get("source_stale")
    if not isinstance(stale, bool):
        results.append((FAIL, "고저폭판 원본",
                        f"source_stale 이 참/거짓이 아님({stale!r})"))
    elif stale:
        results.append((FAIL, "고저폭판 원본",
                        "source_stale=True — 원본 일봉이 낡았다"
                        f" (source_date={board.get('source_date')},"
                        f" expected={board.get('expected_source_date')})"))
    else:
        results.append((PASS, "고저폭판 원본",
                        f"source_stale=False (source_date={board.get('source_date')})"))

    ok, count = _as_int(board.get("candidate_count"))
    if not ok:
        results.append((FAIL, "고저폭판 후보수",
                        f"candidate_count 가 숫자가 아님"
                        f"({board.get('candidate_count')!r})"))
    elif count <= 0:
        results.append((FAIL, "고저폭판 후보수",
                        "candidate_count=0 — 8/14 와 같은 상태다."
                        " 이대로면 08:59 사전점검이"
                        " SOURCE_EMPTY:high_range_top30 으로 죽는다"))
    else:
        results.append((PASS, "고저폭판 후보수", f"candidate_count={count}"))

    return results


def check_context(
    now: datetime,
    context: dict[str, Any],
    *,
    realtime_level: str,
    error: str = "",
) -> list[Result]:
    """정규 사전점검이 볼 자료를 같은 기준으로 미리 본다.

    realtime_level 은 실시간 3종의 결핍을 어떤 등급으로 볼지 정한다.
    장 시작 전이면 WARN(정상일 수 있다), 장이 열린 뒤면 FAIL(곧 사전점검 실패).
    """
    today = now.strftime("%Y%m%d")
    results: list[Result] = []

    if error or not context:
        return [(FAIL, "통합자료 파일", error or f"내용이 비었음: {CONTEXT}")]

    for_date = str(context.get("for_date") or "")
    if for_date != today:
        results.append((FAIL, "통합자료 날짜",
                        f"for_date={for_date or '(없음)'} != 오늘({today})"
                        " — 사전점검 CONTEXT_DATE_MISMATCH 사유"))
    else:
        results.append((PASS, "통합자료 날짜", f"for_date={for_date}"))

    age = _age_seconds(now, context.get("ts"))
    if age > CONTEXT_MAX_AGE_SEC:
        results.append((realtime_level, "통합자료 신선도",
                        f"ts 나이 {_age_text(age)} > {CONTEXT_MAX_AGE_SEC}초"
                        " — 사전점검 CONTEXT_STALE 사유"))
    else:
        results.append((PASS, "통합자료 신선도", f"ts 나이 {age:.1f}초"))

    ok, capability = _as_int(context.get("order_capability"))
    if not ok:
        results.append((FAIL, "주문권한 0",
                        "order_capability 가 숫자가 아님"
                        f"({context.get('order_capability')!r})"))
    elif capability != 0:
        results.append((FAIL, "주문권한 0", f"order_capability={capability} != 0"))
    else:
        results.append((PASS, "주문권한 0", "order_capability=0"))

    status = context.get("source_status")
    if not isinstance(status, dict):
        results.append((FAIL, "자료원 목록",
                        f"source_status 가 사전이 아님({type(status).__name__})"))
        return results

    for source in REQUIRED_SOURCES:
        # 고저폭판은 08:40 산출물이라 장 시작 전에도 차 있어야 한다 → 항상 FAIL.
        level = realtime_level if source in REALTIME_SOURCES else FAIL
        row = status.get(source)
        if not isinstance(row, dict):
            results.append((level, f"자료원 {source}",
                            f"항목이 사전이 아님({type(row).__name__})"))
            continue
        if not row.get("fresh"):
            results.append((level, f"자료원 {source}",
                            "fresh=False — 사전점검 SOURCE_STALE 사유"))
            continue
        ok, accepted = _as_int(row.get("accepted_count"))
        if not ok:
            results.append((level, f"자료원 {source}",
                            "accepted_count 가 숫자가 아님"
                            f"({row.get('accepted_count')!r})"))
            continue
        if accepted <= 0:
            results.append((level, f"자료원 {source}",
                            "accepted_count=0 — 사전점검 SOURCE_EMPTY 사유"))
            continue
        max_age = SOURCE_MAX_AGE_SEC.get(source)
        if max_age is not None:
            src_age = _age_seconds(now, row.get("source_ts"))
            if src_age > max_age:
                results.append((level, f"자료원 {source}",
                                f"accepted={accepted} 이지만 source_ts 나이"
                                f" {_age_text(src_age)} > {max_age}초"
                                " — 사전점검 SOURCE_TIMESTAMP_STALE 사유"))
                continue
        results.append((PASS, f"자료원 {source}", f"accepted_count={accepted}"))

    return results


def preflight_note() -> list[Result]:
    """정규 사전점검이 이미 통과했는지 정보로만 덧붙인다(판정에는 영향 없음).

    09:00 이후 팝업을 본 사람이 "이미 승인 났는데?" 를 즉시 알 수 있어야 한다.
    """
    audit, error = _read_json(PREFLIGHT_AUDIT)
    if error or not audit:
        return [(INFO, "정규 사전점검", error or "기록 없음")]
    return [(INFO, "정규 사전점검",
             f"passed={audit.get('passed')} activated={audit.get('activated')}"
             f" reason={audit.get('reason')}")]


def _phase_deadline(now: datetime, phase: str) -> datetime | None:
    limit = PHASE_DEADLINES.get(phase)
    if limit is None:
        return None
    return datetime.combine(now.date(), limit)


def run_checks_until_deadline(
    now: datetime,
    phase: str,
    *,
    reader=None,
    clock=datetime.now,
    sleeper=time_module.sleep,
) -> tuple[list[Result], int]:
    """마감까지 읽기 전용으로 다시 본다. FAIL 이 사라지면 즉시 멈춘다.

    WARN 은 재시도 사유가 아니다(장 시작 전 실시간 자료는 원래 늦게 찬다).
    """
    realtime_level = FAIL if phase == "live" else WARN
    read = reader or (lambda: _read_json(CONTEXT))

    def evaluate(at: datetime) -> list[Result]:
        payload, error = read()
        return check_context(at, payload, realtime_level=realtime_level,
                             error=error)

    deadline = _phase_deadline(now, phase)
    results = evaluate(now)
    attempts = 1
    while any(level == FAIL for level, _, _ in results):
        current = clock()
        if deadline is None or current > deadline:
            break
        sleeper(RETRY_SEC)
        results = evaluate(clock())
        attempts += 1
    return results, attempts


def phase_window_ok(now: datetime, phase: str) -> tuple[bool, str]:
    window = PHASE_WINDOWS.get(phase)
    if window is None:
        return False, f"알 수 없는 단계: {phase}"
    start, end = window
    if start <= now.time() <= end:
        return True, ""
    return False, (f"유효 시간창 {start:%H:%M}~{end:%H:%M} 밖에서 기동"
                   f"({now:%H:%M:%S}) — 늦은 기동이라 검사하지 않는다")


def _emit(now: datetime, phase: str, results: list[Result],
          *, attempts: int = 1, skipped: str = "") -> int:
    fails = [r for r in results if r[0] == FAIL]
    warns = [r for r in results if r[0] == WARN]
    if skipped:
        verdict = "SKIP"
    elif fails:
        verdict = FAIL
    elif warns:
        verdict = WARN
    else:
        verdict = PASS

    header = (f"자료원 조기 경보 [{phase}]  {now:%Y-%m-%d %H:%M:%S}"
              f"  판정: {verdict}  {UNVERIFIED}")
    lines = ["=" * 72, header, "=" * 72]
    if skipped:
        lines.append(f" skip  {skipped}")
    marks = {FAIL: "!!FAIL", WARN: " WARN ", PASS: "  OK  ", INFO: " info "}
    for level, name, detail in results:
        lines.append(f"{marks.get(level, '  ?   ')} {name:<24} {detail}")
    if attempts > 1:
        lines.append(f"       (재확인 {attempts}회)")
    if fails:
        lines.append("")
        if phase == "live":
            lines.append("★S01 매수창은 09:20 에 닫힌다."
                         " 정규 사전점검 자동복구는 09:05 까지만 시도한다.")
        else:
            lines.append("★조치 필요 — 08:59 정규 사전점검 전에 고쳐야 한다.")
        lines.append("  이 검사는 아무것도 고치지 않는다. 알리기만 한다.")
    body = "\n".join(lines)
    print(body)

    payload = {
        "schema": "strategy_source_early_warning_v1",
        "verified": UNVERIFIED,
        "ts": now.isoformat(timespec="seconds"),
        "phase": phase,
        "verdict": verdict,
        "skipped_reason": skipped,
        "attempts": attempts,
        "fail_count": len(fails),
        "warn_count": len(warns),
        "results": [{"level": a, "name": b, "detail": c} for a, b, c in results],
    }
    try:
        REPORT_DIR.mkdir(parents=True, exist_ok=True)
        report = REPORT_DIR / f"자료원_조기경보_{now:%Y%m%d}.json"
        previous, _ = _read_json(report)
        history = previous.get("runs")
        if not isinstance(history, list):
            history = []
        history.append(payload)
        report.write_text(
            json.dumps({"schema": payload["schema"], "verified": UNVERIFIED,
                        "for_date": now.strftime("%Y%m%d"), "runs": history},
                       ensure_ascii=False, indent=2),
            encoding="utf-8")
    except OSError:
        pass
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LOG_PATH.open("a", encoding="utf-8") as handle:
            handle.write(body + "\n")
    except OSError:
        pass

    # ★FAIL 만 화면에 띄운다. 파일만 남기면 8/5·8/14 와 똑같이 아무도 모른다.
    #   WARN 으로 팝업을 띄우면 매일 뜨고, 매일 뜨면 무시하게 되고, 검사가 죽는다.
    #   --no-popup 으로 끌 수 있다(수동 점검·테스트용).
    if fails and "--no-popup" not in sys.argv:
        try:
            import ctypes
            tail = ("S01 매수창 09:20 마감 전에 조치가 필요합니다."
                    if phase == "live"
                    else "08:59 정규 사전점검 전에 조치가 필요합니다.")
            msg = (f"자료원 조기 경보 실패 [{phase}] ({now:%H:%M:%S})\n\n"
                   + "\n\n".join(f"[{n}]\n{d}" for _, n, d in fails[:4])
                   + f"\n\n{tail}\n"
                     f"자세히: {REPORT_DIR}\\자료원_조기경보_{now:%Y%m%d}.json")
            # 0x30 = MB_ICONWARNING, 0x1000 = MB_SYSTEMMODAL(항상 위)
            ctypes.windll.user32.MessageBoxW(
                None, msg, "SAFEPLUS 자료원 조기 경보 - 실패", 0x30 | 0x1000)
        except Exception:                      # noqa: BLE001
            pass

    return 1 if fails else 0


def _argument(name: str) -> str:
    for index, arg in enumerate(sys.argv):
        if arg == name and index + 1 < len(sys.argv):
            return sys.argv[index + 1]
    return ""


def main() -> int:
    now = datetime.now()
    phase = _argument("--phase").strip().lower()
    if phase not in PHASE_WINDOWS:
        print("--phase board|preopen|live 를 명시해야 한다"
              f" (받은 값: {phase or '(없음)'})")
        return 2

    if "--force" not in sys.argv:
        ok, why = phase_window_ok(now, phase)
        if not ok:
            return _emit(now, phase, [], skipped=why)

    trading, notes = trading_day_results(now)
    if not trading:
        return _emit(now, phase, notes, skipped=notes[0][2] if notes else "")

    if phase == "board":
        payload, error = _read_json(BOARD)
        return _emit(now, phase, notes + check_board(now, payload, error))

    board_payload, board_error = _read_json(BOARD)
    results = notes + check_board(now, board_payload, board_error)
    context_results, attempts = run_checks_until_deadline(now, phase)
    results += context_results
    if phase == "live":
        results += preflight_note()
    return _emit(now, phase, results, attempts=attempts)


if __name__ == "__main__":
    raise SystemExit(main())
