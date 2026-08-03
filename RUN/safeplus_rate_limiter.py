"""
safeplus_rate_limiter.py
Kiwoom TR 요청 속도 제한기 — 공유 유틸리티

파일 기반 슬라이딩 윈도우. 여러 프로세스에서 동일 STATE_FILE 공유.

사용법:
    import sys
    sys.path.insert(0, r"C:\stock_bot\RUN")
    from safeplus_rate_limiter import KiwoomRateLimiter

    _limiter = KiwoomRateLimiter()

    def some_tr_call():
        _limiter.acquire()   # TR 호출 직전 반드시 호출
        kiwoom.CommRqData(...)
"""
import json
import random
import time
from pathlib import Path

DATA_DIR   = Path(r"C:\stock_bot\DATA")
STATE_FILE = DATA_DIR / "kiwoom_tr_rate_state.json"

MAX_CALLS_PER_SEC = 2      # 1초 슬라이딩 윈도우 내 최대 TR 호출
MIN_GAP_SEC       = 0.55   # [PATCH-HARDGAP] 직전 호출과 최소 간격(초) — 초당 2회 초과 절대 차단
BACKOFF_MIN_SEC   = 0.6    # burst 감지 시 최소 backoff sleep (0.5→0.6 안정화)
BACKOFF_MAX_SEC   = 1.5    # burst 감지 시 최대 backoff sleep


class KiwoomRateLimiter:
    """
    Kiwoom TR API 1초당 호출 제한기.

    · MAX_CALLS_PER_SEC 초과 시 BACKOFF_MIN~MAX_SEC 범위에서 랜덤 sleep.
    · 파일 기반 상태: 동일 PC 내 여러 프로세스가 공유 가능.
    · acquire() 는 블로킹 호출이므로 TR 직전에만 사용할 것.
    """

    def acquire(self) -> None:
        now    = time.time()
        recent = self._recent_calls(now)

        # [PATCH-HARDGAP] 직전 호출과 최소 간격 보장 → 1초 내 3번째 호출 자체가 발생 불가
        if recent:
            last_call = max(recent)
            gap       = now - last_call
            if gap < MIN_GAP_SEC:
                time.sleep(MIN_GAP_SEC - gap)
                now    = time.time()
                recent = self._recent_calls(now)

        if len(recent) >= MAX_CALLS_PER_SEC:
            sleep_s = random.uniform(BACKOFF_MIN_SEC, BACKOFF_MAX_SEC)
            print(
                f"[RATELIMIT] TR burst {len(recent)}/{MAX_CALLS_PER_SEC}/s"
                f" — backoff {sleep_s:.2f}s",
                flush=True,
            )
            time.sleep(sleep_s)
            now    = time.time()
            recent = self._recent_calls(now)

        recent.append(now)
        self._save(recent[-50:])  # 최근 50개 타임스탬프만 보관

    # ── internals ──────────────────────────────────────────────────────

    def _recent_calls(self, now: float) -> list:
        try:
            if STATE_FILE.exists():
                data = json.loads(STATE_FILE.read_text(encoding="utf-8-sig"))
                return [t for t in data.get("calls", []) if now - t < 1.0]
        except (json.JSONDecodeError, OSError):
            pass
        return []

    def _save(self, calls: list) -> None:
        """임시 파일에 쓴 뒤 rename — atomic write."""
        try:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            tmp = STATE_FILE.with_suffix(".tmp")
            tmp.write_text(json.dumps({"calls": calls}), encoding="utf-8")
            if STATE_FILE.exists():
                STATE_FILE.unlink()
            tmp.rename(STATE_FILE)
        except OSError:
            pass
