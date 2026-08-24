# -*- coding: utf-8 -*-
"""전략 조용사/신호 미소비 감지 장치 (읽기 전용).

★[QUIET-GUARD 2026-08-19 친구님 지시 "5번 계속 진행해"] 발단 두 사고:
  8/18 S06 09:24 CSV 헤더 오류로 죽음 → 아무도 모름 → 오후 폭락 때 부재
  8/19 S03 신호 3건을 못 먹는 상태로 방치 → 아무도 모름 → 전건 유실
  공통점: 전략이 일을 안 해도 알려주는 장치가 없다(heartbeat 는 있는데 아무도 안 봄).

무엇을 본다 (전부 읽기 전용 — 아무것도 고치지 않는다):
  1) S01·02·03·05·06 상태파일: 오늘 날짜인가 / heartbeat 나이 / last_error
     (S04 는 수동 전략이라 제외)
  2) S03 신호 미소비: 최근 45분 내 BUY_READY 가 있는데 소비 0 이면
     엔진 탈락기록(s03_engine_drop)을 대조 — 기록이 있으면 "사유 남기며 거부 중"(WARN),
     기록조차 없으면 "신호를 보지도 않음"(FAIL)
  3) S06 트리거 미집행: 최근 45분 내 CHASE_TRIGGER 가 있는데 주문시도 0 이면 WARN
  4) 돈맥 감시기 heartbeat (WARN 등급 — 실행기는 1분 태스크라 별도)

팝업은 FAIL 만 띄운다(자료원 조기경보와 같은 규율 — WARN 팝업은 매일 뜨고,
매일 뜨면 무시하게 되고, 검사가 죽는다). --no-popup 으로 끈다(수동 점검용).
장시간(09:05~15:25) 밖이면 SKIP — 엔진 종료 후 오탐 방지.
"""
from __future__ import annotations

import glob
import json
import sys
from datetime import datetime, time as day_time
from pathlib import Path

try:  # cp949 콘솔/리다이렉트에서도 한글·기호 출력이 죽지 않게
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:                              # noqa: BLE001
    pass

BASE = Path(r"C:\stock_bot")
DATA = BASE / "data"
REPORT_DIR = BASE / "보고서"
LOG_PATH = BASE / "LOG" / "quiet_guard_v1.log"

FAIL, WARN, PASS, INFO = "FAIL", "WARN", "PASS", "info"
UNVERIFIED = "[UNVERIFIED]"

HB_MAX_AGE_SEC = 180.0        # 엔진 루프는 1~2초 주기 — 3분 침묵이면 조용사
FRESH_SIGNAL_MIN = 45         # 이 분수 안의 신호만 "지금 문제"로 본다(아침 잔해 오탐 방지)

STATE_FILES = {
    "S01": DATA / "strategy_01_rotation_state_v2.json",
    "S02": DATA / "strategy_02_rotation_state_v1.json",
    "S03": DATA / "strategy_03_rotation_state_v1.json",
    "S05": DATA / "strategy_05_rotation_state_v1.json",
    "S06": DATA / "strategy_06_crash_low_chase_state_v1.json",
}
S03_SIGNAL = DATA / "strategy_03_골짜기_급반등_signal_v1.json"
S03_DROP_DIR = DATA / "audit" / "s03_engine_drop"
MFLOW_WATCH_STATE = DATA / "moneyflow_watch_state.json"


def _read_json(path: Path) -> dict:
    try:
        loaded = json.loads(path.read_text(encoding="utf-8-sig"))
        return loaded if isinstance(loaded, dict) else {}
    except (OSError, ValueError):
        return {}


def _parse_local(value) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value or ""))
    except ValueError:
        return None
    return parsed.astimezone().replace(tzinfo=None) if parsed.tzinfo else parsed


def _age_sec(now: datetime, value) -> float:
    ts = _parse_local(value)
    return (now - ts).total_seconds() if ts else -1.0


def check_engines(now: datetime) -> list[tuple[str, str, str]]:
    today = now.strftime("%Y%m%d")
    results = []
    for name, path in STATE_FILES.items():
        state = _read_json(path)
        if not state:
            results.append((FAIL, f"{name} 상태파일", f"읽기 실패 {path.name}"))
            continue
        if str(state.get("date") or "") != today:
            results.append(
                (FAIL, f"{name} 미기동", f"상태 날짜 {state.get('date')} != 오늘"))
            continue
        age = _age_sec(now, state.get("heartbeat"))
        attempts = state.get("order_attempts_total")
        if age < 0:
            results.append((FAIL, f"{name} 조용사", "heartbeat 해석 불가"))
        elif age > HB_MAX_AGE_SEC:
            results.append(
                (FAIL, f"{name} 조용사",
                 f"heartbeat {age:.0f}초 침묵 (한도 {HB_MAX_AGE_SEC:.0f}초)"))
        else:
            results.append(
                (PASS, f"{name}", f"hb {age:.0f}초 · 주문시도 {attempts}"))
        last_error = str(state.get("last_error") or "")
        if last_error:
            results.append((WARN, f"{name} last_error", last_error[:120]))
    return results


def check_s03_signals(now: datetime) -> list[tuple[str, str, str]]:
    payload = _read_json(S03_SIGNAL)
    if str(payload.get("date") or "") != now.strftime("%Y%m%d"):
        return [(INFO, "S03 신호판", "오늘 신호판 없음")]
    fresh = []
    for sig in payload.get("signals") or []:
        if not isinstance(sig, dict) or str(sig.get("action")) != "BUY_READY":
            continue
        age = _age_sec(now, sig.get("ts"))
        if 0 <= age <= FRESH_SIGNAL_MIN * 60:
            fresh.append(str(sig.get("code") or ""))
    if not fresh:
        return [(PASS, "S03 신호소비", f"최근 {FRESH_SIGNAL_MIN}분 신규 BUY_READY 없음")]
    state = _read_json(STATE_FILES["S03"])
    consumed = state.get("consumed_signals") or []
    attempts = int(state.get("order_attempts_total") or 0)
    if consumed or attempts > 0:
        return [(PASS, "S03 신호소비",
                 f"신선 신호 {len(fresh)}건 · 소비 {len(consumed)} · 시도 {attempts}")]
    drop_path = S03_DROP_DIR / f"s03_engine_drop_{now:%Y%m%d}.jsonl"
    drops = 0
    try:
        drops = sum(1 for _ in drop_path.open(encoding="utf-8"))
    except OSError:
        drops = 0
    if drops > 0:
        return [(WARN, "S03 거부 중",
                 f"신선 BUY_READY {len(fresh)}건({','.join(fresh[:5])}) 소비 0 — "
                 f"엔진이 탈락사유 {drops}건 기록 중(살아서 거부). 사유 확인 필요")]
    return [(FAIL, "S03 신호 미소비",
             f"신선 BUY_READY {len(fresh)}건({','.join(fresh[:5])}) 소비 0 · 시도 0 · "
             f"탈락기록 0 — 엔진이 신호를 보지도 않음(8/19 사고 유형)")]


def check_s06_trigger(now: datetime) -> list[tuple[str, str, str]]:
    pattern = str(DATA / "*" / f"*06*events_{now:%Y%m%d}.csv")
    paths = glob.glob(pattern) or glob.glob(
        str(DATA / f"*06*events_{now:%Y%m%d}.csv"))
    if not paths:
        return [(INFO, "S06 트리거", "오늘 이벤트 파일 없음")]
    fresh_triggers = 0
    try:
        for line in open(paths[0], encoding="utf-8-sig", errors="replace"):
            if "CHASE_TRIGGER" not in line:
                continue
            ts = line.split(",", 1)[0]
            age = _age_sec(now, ts)
            if 0 <= age <= FRESH_SIGNAL_MIN * 60:
                fresh_triggers += 1
    except OSError:
        return [(INFO, "S06 트리거", "이벤트 파일 읽기 실패")]
    if fresh_triggers <= 0:
        return [(PASS, "S06 트리거", f"최근 {FRESH_SIGNAL_MIN}분 신규 트리거 없음")]
    state = _read_json(STATE_FILES["S06"])
    attempts = int(state.get("order_attempts_total") or 0)
    if attempts > 0:
        return [(PASS, "S06 트리거", f"트리거 {fresh_triggers}건 · 시도 {attempts}")]
    return [(WARN, "S06 트리거 미집행",
             f"최근 {FRESH_SIGNAL_MIN}분 CHASE_TRIGGER {fresh_triggers}건인데 "
             f"주문시도 0 — 관문/조건 탈락인지 사유 확인 필요")]


def check_moneyflow(now: datetime) -> list[tuple[str, str, str]]:
    state = _read_json(MFLOW_WATCH_STATE)
    age = _age_sec(now, state.get("heartbeat") or state.get("ts"))
    if age < 0:
        return [(WARN, "돈맥 감시기", "heartbeat 해석 불가")]
    if age > HB_MAX_AGE_SEC:
        return [(WARN, "돈맥 감시기", f"heartbeat {age:.0f}초 침묵")]
    return [(PASS, "돈맥 감시기", f"hb {age:.0f}초")]


def main() -> int:
    now = datetime.now()
    in_session = (now.weekday() < 5
                  and day_time(9, 5) <= now.time() <= day_time(15, 25))
    if not in_session and "--force" not in sys.argv:
        print(f"[quiet-guard] 장시간 밖({now:%H:%M:%S}) — SKIP (엔진 종료 후 오탐 방지)")
        return 0

    results = (check_engines(now) + check_s03_signals(now)
               + check_s06_trigger(now) + check_moneyflow(now))
    fails = [r for r in results if r[0] == FAIL]
    warns = [r for r in results if r[0] == WARN]
    verdict = FAIL if fails else (WARN if warns else PASS)

    lines = ["=" * 72,
             f"전략 조용사 감지 {now:%Y-%m-%d %H:%M:%S}  판정: {verdict}  {UNVERIFIED}",
             "=" * 72,
             " info  S04                      수동 전략 — 감시 제외"]
    marks = {FAIL: "!!FAIL", WARN: " WARN ", PASS: "  OK  ", INFO: " info "}
    for level, name, detail in results:
        lines.append(f"{marks.get(level, '  ?   ')} {name:<20} {detail}")
    if fails:
        lines.append("")
        lines.append("★이 검사는 아무것도 고치지 않는다. 알리기만 한다.")
    body = "\n".join(lines)
    print(body)

    payload = {
        "schema": "strategy_quiet_guard_v1",
        "verified": UNVERIFIED,
        "ts": now.isoformat(timespec="seconds"),
        "verdict": verdict,
        "results": [{"level": a, "name": b, "detail": c} for a, b, c in results],
    }
    try:
        REPORT_DIR.mkdir(parents=True, exist_ok=True)
        report = REPORT_DIR / f"조용사감지_{now:%Y%m%d}.json"
        previous = _read_json(report)
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

    # FAIL 만 팝업 (자료원 조기경보와 같은 규율). 0x30 경고 아이콘 · 0x1000 항상 위.
    if fails and "--no-popup" not in sys.argv:
        try:
            import ctypes
            msg = (f"전략 조용사 감지 ({now:%H:%M:%S})\n\n"
                   + "\n\n".join(f"[{n}]\n{d}" for _, n, d in fails[:4])
                   + f"\n\n자세히: {REPORT_DIR}\\조용사감지_{now:%Y%m%d}.json")
            ctypes.windll.user32.MessageBoxW(
                None, msg, "SAFEPLUS 전략 조용사 감지", 0x30 | 0x1000)
        except Exception:                      # noqa: BLE001
            pass
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
