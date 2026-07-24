# -*- coding: utf-8 -*-
"""
[매도엔진 가동감시 2026-06-10] — "조용한 죽음" 재발방지 (PB엔진 5/22~6/10 3주 무감지 교훈)
역할: 장중 + PULLBACK 보유 존재 시, PB 매도엔진(collector 내장 UNIFIED-PB tick)이
      실제로 돌고 있는지 감시. N분 이상 무신호면 CRITICAL 알람 파일 + 로그.
READ-ONLY (rt_open/로그 읽기만). 매매·파일 무수정. 예외=무크래시.
스케줄: SAFEPLUS_SELL_LIVENESS_GUARD 장중 10분마다.
판정:
  - 장중(09:01~15:25) 아님 → OK(skip)
  - rt_open에 qty>0 보유 없음 → OK(매도할 것 없음)
  - 보유 있음 → pullback_sell_engine.log mtime + collector_1m.log [UNIFIED-PB] 최근시각
    둘 다 STALE_MIN(15분) 초과 → CRITICAL: data/LOG/sell_liveness_alert.flag 생성(보드/사람용)
"""
import json, os, sys, io, re
from datetime import datetime
from pathlib import Path

BASE = Path(r"C:\stock_bot")
RT_OPEN = BASE / "data" / "rt_open_positions.json"
PB_LOG = BASE / "data" / "LOG" / "pullback_sell_engine.log"
COLLECTOR_LOG = BASE / "LOG" / "collector_1m.log"
ALERT_FLAG = BASE / "data" / "LOG" / "sell_liveness_alert.flag"
GUARD_LOG = BASE / "data" / "LOG" / "sell_liveness_guard.log"
STALE_MIN = int(os.environ.get("SELL_LIVENESS_STALE_MIN", "15"))

def log(msg, level="INFO"):
    line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}][{level}] {msg}"
    print(line)
    try:
        with io.open(GUARD_LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass

def main():
    now = datetime.now()
    hhmm = now.hour * 100 + now.minute
    if not (901 <= hhmm <= 1525) or now.weekday() >= 5:
        log(f"장외(hhmm={hhmm:04d} wd={now.weekday()}) → skip")
        return 0

    # 보유 확인 (qty>0)
    held = []
    try:
        raw = RT_OPEN.read_text(encoding="utf-8-sig")
        d = json.loads(raw) if raw.strip() else {}
        for k, v in (d.items() if isinstance(d, dict) else []):
            try:
                q = float((v or {}).get("qty", 0) or 0)
            except (TypeError, ValueError):
                q = 0.0
            if q > 0:
                held.append((str(k).zfill(6), q, str((v or {}).get("strategy", ""))))
    except Exception as e:
        log(f"rt_open 읽기실패(판정불가→skip): {e}", "WARN")
        return 0
    if not held:
        # 보유 없음 = 매도엔진 할 일 없음 → 알람 있으면 해제
        if ALERT_FLAG.exists():
            try: ALERT_FLAG.unlink()
            except Exception: pass
            log("보유 0 → 기존 알람 해제")
        else:
            log("보유 0 → OK")
        return 0

    # PB 매도엔진 신호 신선도: ①PB 전용로그 mtime ②collector UNIFIED-PB 최근 로그시각
    ages = []
    try:
        ages.append((now.timestamp() - PB_LOG.stat().st_mtime) / 60.0)
    except Exception:
        ages.append(9e9)
    try:
        # collector 로그 끝 200KB에서 [UNIFIED-PB] 마지막 시각
        size = COLLECTOR_LOG.stat().st_size
        with io.open(COLLECTOR_LOG, "r", encoding="utf-8", errors="replace") as f:
            f.seek(max(0, size - 200_000))
            tail = f.read()
        ts = None
        for m in re.finditer(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}).*UNIFIED-PB", tail, re.M):
            ts = m.group(1)
        if ts:
            ages.append((now - datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")).total_seconds() / 60.0)
        else:
            ages.append(9e9)
    except Exception:
        ages.append(9e9)

    best_age = min(ages)
    if best_age > STALE_MIN:
        msg = (f"★★★ 매도엔진 무신호 {best_age:.0f}분(>{STALE_MIN}) — 보유 {held} 무방비 의심! "
               f"collector UNIFIED-PB tick / pullback_sell_engine.log 확인 필요 ★★★")
        log(msg, "CRITICAL")
        try:
            tmp = str(ALERT_FLAG) + ".tmp"
            with io.open(tmp, "w", encoding="utf-8") as f:
                f.write(f"{now.isoformat()} {msg}\n")
            os.replace(tmp, str(ALERT_FLAG))
        except Exception:
            pass
        return 1
    log(f"OK — 보유 {len(held)}건, 매도엔진 신호 age={best_age:.1f}분")
    if ALERT_FLAG.exists():
        try: ALERT_FLAG.unlink()
        except Exception: pass
        log("정상화 → 알람 해제")
    return 0

if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        log(f"[FATAL] {e} (무크래시 종료)", "ERROR")
        sys.exit(0)
