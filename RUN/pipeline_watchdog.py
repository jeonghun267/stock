"""
pipeline_watchdog.py  [2026-04-29]
SAFEPLUS PIPELINE WATCHDOG

pipeline_heartbeat.txt 파일의 최종 갱신 시각을 감시한다.
HEARTBEAT_TIMEOUT_SEC 이상 갱신이 없으면 pipeline_runner 프로세스를
강제 종료 후 재시작한다.

실행 방법:
  Task Scheduler (SAFEPLUS_WATCHDOG) 에서 독립 프로세스로 시작.
  run_pipeline_watchdog.ps1 을 통해 중복 실행 방지 후 실행.

감시 범위:
  MARKET_OPEN_HHMM - 5분 ~ MARKET_CLOSE_HHMM + 5분
  (범위 밖에서는 대기만 수행)
"""
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

BASE           = Path(r"C:\stock_bot")
DATA_DIR       = BASE / "DATA"
LOG_DIR        = DATA_DIR / "LOG"
HEARTBEAT_FILE = LOG_DIR / "pipeline_heartbeat.txt"
PYTHON_EXE     = Path(r"C:\Python310-32\python.exe")
PIPELINE_PY    = BASE / "RUN" / "pipeline_runner.py"

HEARTBEAT_TIMEOUT_SEC = 240   # [HB-240 2026-05-08] 120→240 — 사이클 75~85초이고 임계 빠듯해 중복 spawn 발생
CHECK_INTERVAL_SEC    = 30    # watchdog 체크 주기 (초)
MARKET_OPEN_HHMM      = 855   # 감시 시작 (장 시작 5분 전)
MARKET_CLOSE_HHMM     = 1535  # 감시 종료 (장 마감 5분 후)


def _ts() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _hhmm() -> int:
    return int(datetime.now().strftime("%H%M"))


def _is_pipeline_running() -> bool:
    result = subprocess.run(
        [
            "powershell.exe", "-NonInteractive", "-Command",
            "(Get-WmiObject Win32_Process -Filter \"Name='python.exe'\" | "
            "Where-Object { $_.CommandLine -like '*pipeline_runner*' }).Count"
        ],
        capture_output=True, text=True,
    )
    try:
        return int(result.stdout.strip()) > 0
    except ValueError:
        return False


def _kill_pipeline() -> None:
    subprocess.run(
        [
            "powershell.exe", "-NonInteractive", "-Command",
            "Get-WmiObject Win32_Process -Filter \"Name='python.exe'\" | "
            "Where-Object { $_.CommandLine -like '*pipeline_runner*' } | "
            "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
        ],
        capture_output=True,
    )
    print(f"[WATCHDOG] pipeline_runner 프로세스 종료.  [{_ts()}]", flush=True)


def _restart_pipeline() -> None:
    # pipeline_runner.py 단독 재시작 — 전체 ps1 재호출 금지 (중복 기동 방지)
    subprocess.Popen(
        [str(PYTHON_EXE), "-X", "utf8", str(PIPELINE_PY)],
        cwd=str(PIPELINE_PY.parent),
        creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
    )
    print(f"[WATCHDOG] pipeline_runner 단독 재시작.  [{_ts()}]", flush=True)


def main() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    print(f"[WATCHDOG] 시작.  감시범위: {MARKET_OPEN_HHMM:04d}~{MARKET_CLOSE_HHMM:04d}"
          f"  timeout: {HEARTBEAT_TIMEOUT_SEC}s  [{_ts()}]", flush=True)

    while True:
        now = _hhmm()

        # 감시 범위 밖이면 대기
        if now < MARKET_OPEN_HHMM or now > MARKET_CLOSE_HHMM:
            time.sleep(CHECK_INTERVAL_SEC)
            continue

        # heartbeat 파일 미존재 → pipeline 미시작 상태
        if not HEARTBEAT_FILE.exists():
            print(f"[WATCHDOG] heartbeat 파일 없음 — pipeline 미실행 상태.  [{_ts()}]",
                  flush=True)
            time.sleep(CHECK_INTERVAL_SEC)
            continue

        heartbeat_age = time.time() - HEARTBEAT_FILE.stat().st_mtime

        if heartbeat_age > HEARTBEAT_TIMEOUT_SEC:
            print(
                f"[WATCHDOG] ALERT — heartbeat {heartbeat_age:.0f}s 없음 "
                f"(한도 {HEARTBEAT_TIMEOUT_SEC}s). 재시작 시작.  [{_ts()}]",
                flush=True,
            )
            if _is_pipeline_running():
                _kill_pipeline()
                time.sleep(3)
            _restart_pipeline()
            # 재시작 안정화 대기 (launcher의 중복체크 + startup 시간 고려)
            time.sleep(15)
        else:
            print(
                f"[WATCHDOG] OK — heartbeat {heartbeat_age:.0f}s 전.  [{_ts()}]",
                flush=True,
            )

        time.sleep(CHECK_INTERVAL_SEC)


if __name__ == "__main__":
    main()
