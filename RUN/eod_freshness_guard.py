# -*- coding: utf-8 -*-
# EOD 데이터 신선도 가드 [2026-06-09 신규].
#   문제: nightly EOD수집(16:05) 한 번 실패하면 eod_daily_bars가 옛날에 멈춤(stale)
#         → 다음날 prev_day_summary(08:43 재생성)도 stale → regime 오판 → 매수 전면차단 (6/8 사고).
#   해결: eod_daily_bars 최신일이 "마지막 마감 거래일"인지 검사.
#         stale면 → EOD수집 재실행(--rerun). 저녁/밤에 여러번 돌려 08:43(prev_day_summary 생성) 전 복구.
#   ★READ-ONLY + 수집 재실행만. 매매 엔진(buy_sender/bridge/risk/execution/매도) 무수정·무연결.
import csv, json, os, sys, subprocess
from datetime import datetime, timedelta
from pathlib import Path

BASE = Path(r"C:\stock_bot")
EOD       = BASE / "DATA" / "eod_daily_bars.csv"
PREV      = BASE / "DATA" / "prev_day_summary.csv"
HOLIDAYS  = BASE / "data" / "krx_holidays.json"
DONE      = BASE / "LOG" / "collect_eod.done"
STATUS    = BASE / "DATA" / "eod_freshness_status.json"
COLLECTOR = BASE / "RUN" / "collect_eod_daily_bars_v2_4_SAFEPLUS_FINAL.py"
PY        = r"C:\Python310-32\python.exe"


def _load_holidays():
    s = set()
    try:
        d = json.loads(HOLIDAYS.read_text(encoding="utf-8-sig"))
        items = d if isinstance(d, list) else (d.get("holidays") or d.get("dates") or list(d.keys()))
        for x in items:
            s.add(str(x).replace("-", "").strip()[:8])
    except Exception:
        pass
    return s


def _is_trading(d, hol):
    return d.weekday() < 5 and d.strftime("%Y%m%d") not in hol


def expected_last_closed(now, hol):
    """마지막으로 '마감된' 거래일 (이게 eod_daily_bars 최신일이어야 정상)."""
    d = now.date()
    if _is_trading(d, hol) and now.hour >= 16:   # 오늘 마감 후 → 오늘
        return d.strftime("%Y%m%d")
    d = d - timedelta(days=1)                     # 그 전엔 직전 거래일
    while not _is_trading(d, hol):
        d = d - timedelta(days=1)
    return d.strftime("%Y%m%d")


def latest_eod_date():
    """eod_daily_bars date 컬럼 최대값 (270MB 스캔, 가드는 드물게 돔)."""
    mx = ""
    try:
        with EOD.open(encoding="utf-8-sig", errors="replace") as f:
            for r in csv.DictReader(f):
                dt = (r.get("date", "") or "").strip()
                if dt > mx:
                    mx = dt
    except Exception:
        pass
    return mx


def collector_running():
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "(Get-WmiObject Win32_Process -Filter \"Name='python.exe'\" | "
             "Where-Object { $_.CommandLine -like '*collect_eod_daily_bars*' }).Count"],
            capture_output=True, text=True, timeout=20)
        return (out.stdout or "0").strip() not in ("0", "")
    except Exception:
        return False


def main():
    rerun = "--rerun" in sys.argv
    now = datetime.now()
    hol = _load_holidays()
    expected = expected_last_closed(now, hol)
    actual = latest_eod_date()
    stale = bool(actual) and actual < expected
    if not actual:
        stale = True   # 못 읽음도 위험으로
    action = "none"
    running = collector_running()

    if stale and rerun:
        if running:
            action = "already_running"
        else:
            try:
                subprocess.Popen([PY, "-X", "utf8", str(COLLECTOR)],
                                 cwd=str(BASE / "RUN"),
                                 creationflags=0x00000008)  # DETACHED
                action = "rerun_triggered"
            except Exception as e:
                action = "rerun_fail:%s" % str(e)[:40]

    status = {
        "ts": now.strftime("%Y-%m-%d %H:%M:%S"),
        "expected_last_trading_day": expected,
        "eod_latest_date": actual or "(읽기실패)",
        "stale": stale,
        "collector_running": running,
        "action": action,
    }
    try:
        STATUS.write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass
    print("[EOD-GUARD] expected=%s eod=%s stale=%s running=%s action=%s"
          % (expected, actual, stale, running, action))


if __name__ == "__main__":
    main()
