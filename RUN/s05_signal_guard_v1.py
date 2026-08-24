"""신호기 생존 감시·재기동 (★2026-07-29 친구님 승인 "재기동 태스크도 만들어").

배경: 신호기(SAFEPLUS_STRATEGY0N_SIGNAL)는 1초마다 출력 JSON을 쓰는데,
  7/29 11:29 S05가 저장 순간 충돌(PermissionError)로 죽은 뒤 마감까지 방치됐다
  (재시도 패치는 같은 날 별도 배선). 크래시 자체를 되살리는 안전망이 이 감시기.

★[2026-07-30 친구님 지시 "감시 태스크 전략별로 다 붙여"] S05 전용 → 전략01~05 공통으로 확장.
  계기: 7/30 전략04 신호기가 11:22에 결과코드 1로 죽었는데 감시가 없어 2시간 7분 방치됐다.
  진입창 10:00~12:00 중 38분(32%)을 잃었고, 아무도 알지 못했다.
  친구님 선택 = A안(기존 파일 확장·태스크 신설 0건). 태스크 이름은 SAFEPLUS_S05_SIGNAL_GUARD
  그대로 쓰지만 실제로는 5개 전략을 모두 감시한다(이름과 범위가 다른 점 주의).

★[2026-07-30 친구님 승인 "고저폭 보강 ①"] 고저폭 실황판(HR30)도 같은 목록에서 감시.
  대상 파일 = data\common_high_range_live_state.json (실황판 생존 시 2초마다 갱신).

동작: 장중(월~금·휴장일 제외) 5분마다 태스크로 실행되어, 전략별 감시창 안에서
  출력 파일이 STALE_SEC(기본 180초·env S05_GUARD_STALE_SEC) 넘게 낡았거나 없으면
  `schtasks /run` 으로 그 전략의 신호기 태스크를 다시 켠다.
  - 신호기 태스크는 IgnoreNew 라 살아있으면 /run 이 무시됨 = 이중기동 없음.
  - 신호기 태스크가 꺼져(Enabled false) 있으면 존중하고 건드리지 않는다.
  - 주문능력 0 · 키움 조회 0 (파일 mtime 읽기 + 태스크 기동뿐).

감시창은 각 전략의 진입창(회전엔진 entry_start~entry_end)에 앞뒤 여유를 붙인 값이다.
  진입창 밖까지 감시하면 정상 종료한 신호기를 계속 되살려 쓸데없는 프로세스가 뜬다.
  전략01은 진입창이 09:00~09:20뿐이라 09:20에 정상 종료하는 것이 맞다.
  ⚠ 태스크 자체가 09:05~15:10 반복이라 그보다 이른 시각은 애초에 실행되지 않는다.

롤백: 태스크 SAFEPLUS_S05_SIGNAL_GUARD 를 Disable.
      파일 되돌리기 = RUN\backup\s05_signal_guard_v1_20260730_allstrategies.py 복원(=S05 전용).
"""
from __future__ import annotations

import os
import subprocess
from datetime import datetime
from pathlib import Path

DATA_DIR = Path(r"C:\stock_bot\data")
HOLIDAY_PATH = Path(r"C:\stock_bot\config\krx_holidays.txt")
STALE_SEC = float(os.environ.get("S05_GUARD_STALE_SEC", "180"))

# 하위호환: 종전 단일 감시 상수. env S05_OUTPUT 로 S05 경로를 바꾸던 운영을 유지한다.
SIG_PATH = Path(os.environ.get(
    "S05_OUTPUT", str(DATA_DIR / "strategy_05_base_breakout_signal_v1.json")))
TASK_NAME = "SAFEPLUS_STRATEGY05_SIGNAL"
WINDOW_START = "0905"
WINDOW_END = "1510"

# (라벨, 출력 JSON, 신호기 태스크, 감시 시작, 감시 끝)
#   진입창 — S01 09:00~09:20 / S02 09:30~14:20 / S03 09:00~14:30
#            S04 10:00~12:00 / S05 09:30~14:30
WATCHES = (
    ("S01", DATA_DIR / "strategy_01_open_surge_signal_v2.json",
     "SAFEPLUS_STRATEGY01_SIGNAL", "0905", "0922"),
    ("S02", DATA_DIR / "strategy_02_low_buy_signal_v1.json",
     "SAFEPLUS_STRATEGY02_SIGNAL", "0928", "1422"),
    ("S03", DATA_DIR / "strategy_03_골짜기_급반등_signal_v1.json",
     "SAFEPLUS_STRATEGY03_SIGNAL", "0905", "1432"),
    ("S04", DATA_DIR / "strategy_04_pullback_signal_v1.json",
     "SAFEPLUS_STRATEGY04_SIGNAL", "0958", "1202"),
    ("S05", SIG_PATH,
     TASK_NAME, "0928", "1432"),
    # ★[2026-07-30 친구님 승인 "고저폭 보강 ①"] 고저폭 실황판(바탕화면 HTML·저점 분당기록)도 감시.
    #   실황판은 살아있으면 상태 JSON 을 2초마다 갱신한다(08:40 기동~15:35 종료).
    #   태스크 트리거가 08:40 하루 1회뿐이라 장중 사망·아침 기동 실패 모두 여기서 되살린다.
    #   본체는 IgnoreNew + 파일락이라 /run 이중기동 없음. 롤백: 이 줄 삭제.
    ("HR30", DATA_DIR / "common_high_range_live_state.json",
     "SAFEPLUS_HIGH_RANGE_BOARD", "0905", "1510"),
    # ★[2026-07-30 친구님 지시 "그림자로 먼저 돌려줘"] 저점매수 그림자 기록기 감시.
    #   상태 파일은 생존 시 2초마다 갱신(08:58 기동~14:40 종료). 롤백: 이 줄 삭제.
    ("LBSH", DATA_DIR / "lowbuy_shadow" / "lowbuy_shadow_state.json",
     "SAFEPLUS_LOWBUY_SHADOW", "0905", "1425"),
    # ★[2026-07-30 친구님 확정 "-13%·-8%"] 저점매수 진입기(종가매수 매수경로) 감시.
    #   상태 파일은 생존 시 2초마다 갱신(10:55 기동~14:35 종료). 롤백: 이 줄 삭제.
    ("LBEN", DATA_DIR / "lowbuy_shadow" / "lowbuy_entry_state.json",
     "SAFEPLUS_EOD_GAP_LOWBUY", "1100", "1430"),
    # ★[2026-07-30 친구님 "우상향이면 끝까지 끌고 가"] 저점매수 추적 매도기 감시.
    #   [2026-07-31 친구님 "09:30 강제매각"] 매도창이 09:00~09:30 으로 축소 → 감시창도 0928 까지.
    #   상태 파일은 생존 시 2초마다 갱신(08:58 기동~09:32 종료). 매도기라 특히 중요 —
    #   죽으면 어제 산 포지션이 아침 창을 통째로 놓친다. 롤백: 이 줄 삭제.
    ("LBSL", DATA_DIR / "lowbuy_shadow" / "lowbuy_sell_state.json",
     "SAFEPLUS_EOD_GAP_LOWBUY_SELL", "0905", "0928"),
)


def _is_holiday(now: datetime) -> bool:
    try:
        today = now.strftime("%Y%m%d")
        for line in HOLIDAY_PATH.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and line == today:
                return True
    except OSError:
        pass  # 휴장일 파일 없음 = 평일 취급 (fail-open)
    return False


def decide(
    now: datetime,
    mtime_ts: float | None,
    window_start: str = WINDOW_START,
    window_end: str = WINDOW_END,
) -> tuple[str, str]:
    """(행동, 사유) 반환. 행동: SKIP / OK / RESTART. 부작용 없음(테스트용 분리).

    window_start/window_end 기본값은 종전 단일 감시값이라 기존 호출이 그대로 동작한다.
    """
    if now.weekday() >= 5:
        return "SKIP", "주말"
    if _is_holiday(now):
        return "SKIP", "휴장일"
    hhmm = now.strftime("%H%M")
    if not (window_start <= hhmm < window_end):
        return "SKIP", f"감시창 밖({hhmm} / {window_start}~{window_end})"
    if mtime_ts is None:
        return "RESTART", "출력 파일 없음"
    age = now.timestamp() - mtime_ts
    if age > STALE_SEC:
        return "RESTART", f"출력 {age:.0f}초 낡음(문턱 {STALE_SEC:g}초)"
    return "OK", f"출력 {age:.0f}초 전 = 생존"


def _task_enabled(task_name: str = TASK_NAME) -> bool:
    try:
        xml = subprocess.run(
            ["schtasks", "/query", "/tn", task_name, "/xml"],
            capture_output=True, text=True, timeout=15,
        ).stdout
        return "<Enabled>false</Enabled>" not in xml
    except (OSError, subprocess.TimeoutExpired):
        return True  # 조회 실패 = 켜진 것으로 취급(재기동 시도 쪽이 안전)


def _guard_one(label: str, sig_path: Path, task_name: str,
               win_start: str, win_end: str, now: datetime) -> None:
    mtime_ts = sig_path.stat().st_mtime if sig_path.exists() else None
    action, reason = decide(now, mtime_ts, win_start, win_end)
    stamp = now.strftime("%Y-%m-%d %H:%M:%S")
    if action != "RESTART":
        print(f"[{stamp}] {label} {action} — {reason}", flush=True)
        return
    if not _task_enabled(task_name):
        print(f"[{stamp}] {label} SKIP — {reason} 이나 태스크가 꺼져 있음(친구님 설정 존중)",
              flush=True)
        return
    r = subprocess.run(
        ["schtasks", "/run", "/tn", task_name],
        capture_output=True, text=True, timeout=30,
    )
    out = (r.stdout or r.stderr or "").strip().replace("\n", " ")[:120]
    print(f"[{stamp}] {label} RESTART — {reason} → schtasks /run rc={r.returncode} {out}",
          flush=True)


def main() -> int:
    now = datetime.now()
    for label, sig_path, task_name, win_start, win_end in WATCHES:
        try:
            _guard_one(label, Path(sig_path), task_name, win_start, win_end, now)
        except Exception as exc:          # 한 전략 실패가 나머지 감시를 막지 않게
            stamp = now.strftime("%Y-%m-%d %H:%M:%S")
            print(f"[{stamp}] {label} ERROR — {type(exc).__name__}: {exc}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
