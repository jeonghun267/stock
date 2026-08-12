# -*- coding: utf-8 -*-
"""장세 관찰 기록기 (주문 0 · 전략 차단 없음).

★[2026-08-01 친구님 확정 원칙 "표시해놔 → 자동 판정해서 실행할 수 있게 해야지"]
  급상승하는 날  = 전략 1번이 우선권
  보통·급하락 날 = 전략 6번·3번이 우선권

판정(09:01 · 월~금):
  ★시각을 08:56 → 09:01 로 옮김(2026-08-01 밤 점검) — 깃발 생태계 때문이다:
    08:45 깃발리셋이 off깃발 생성 → 08:59:35 사전점검이 통과 시 off깃발 제거.
    그 전에 돌면 판정이 사전점검에 밟혀 무효가 된다. 09:01 은 그 뒤이며,
    예상가가 아니라 실제 체결가로 판정하니 더 정확하다.
    (남는 구멍: 09:00~09:01 사이 1번이 살 수 있는 약 60초 — 1번 규칙상
     그 안에 밀림+회복+확인까지 가긴 어렵다. 기록으로 감시.)
  고저폭30 종목의 현재가(스냅샷 cur) vs 전일 종가 → 갭% 30개의 중앙값.
  중앙값 >= REGIME_SURGE_GAP_MED(기본 3.0%) → 급상승일.
  문턱 근거: 6개월(121거래일) 고저폭30 시가갭 중앙값 분포의 상위 10% 경계(p90=+3.33%).
    7/31 전종목 폭등일은 +11.31%(6개월 2위)라 확실히 걸린다.

실행:
  모든 장세에서 전략 1~6은 각자 매수조건을 계속 평가한다. 이 프로그램은 장세를
  기록만 하고 전략 off깃발을 만들지 않는다. 과거 이 프로그램이 만든
  strategy_01_off.flag 는 제거하며, 사람이 만든 수동 깃발은 건드리지 않는다.
  장세 위험 조절은 주문 공통부의 수량축소·극단장 안전관문이 담당한다.

롤백: 과거 버전 복원 후 태스크 REGIME_PRIORITY_JUDGE 재실행.
"""
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

TOP30 = Path(r"C:\stock_bot\data\common_high_range_top30.json")
SNAP = Path(r"C:\stock_bot\IPC\live_micro_snapshot.json")
FLAG = Path(r"C:\stock_bot\config\strategy_01_off.flag")
RECORD = Path(r"C:\stock_bot\data\regime_priority.json")

SURGE_GAP_MED = float(os.environ.get("REGIME_SURGE_GAP_MED", "3.0"))
MIN_CODES = int(os.environ.get("REGIME_MIN_CODES", "15"))
SNAP_MAX_AGE_MIN = float(os.environ.get("REGIME_SNAP_MAX_AGE_MIN", "15"))
MARKER = "REGIME_JUDGE"


def log(msg: str) -> None:
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}", flush=True)


def read_json(path: Path):
    try:
        first = path.read_bytes()
        time.sleep(0.003)
        second = path.read_bytes()
        if first != second:
            return {}
        return json.loads(second.decode("utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}


def number(value, default=0.0):
    try:
        return float(str(value or "").replace(",", ""))
    except (TypeError, ValueError):
        return default


def flag_is_mine() -> bool:
    try:
        return FLAG.read_text(encoding="utf-8", errors="replace").startswith(MARKER)
    except OSError:
        return False


def flag_is_mine_today(today: str) -> bool:
    try:
        text = FLAG.read_text(encoding="utf-8", errors="replace")
        return text.startswith(MARKER) and today in text
    except OSError:
        return False


def save_record(payload: dict) -> None:
    RECORD.parent.mkdir(parents=True, exist_ok=True)
    temp = RECORD.with_suffix(".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                    encoding="utf-8")
    os.replace(temp, RECORD)


def main() -> int:
    now = datetime.now()
    today = now.strftime("%Y%m%d")

    top = read_json(TOP30)
    if str(top.get("for_date") or "") != today:
        log(f"판정 불가 — 고저폭30 목록이 오늘 것이 아님 "
            f"(for_date={top.get('for_date')}) → 변경 없음(1번 현상 유지)")
        if FLAG.exists() and flag_is_mine():
            FLAG.unlink()
            log("과거 장세판정 깃발 청소 — 전 전략 조건진입 유지")
        save_record({"date": today, "verdict": "UNKNOWN",
                     "reason": "TOP30_NOT_TODAY", "checked_at": now.isoformat()})
        return 0

    prev_close = {
        str(row.get("code")).zfill(6): number(row.get("prev_close"))
        for row in (top.get("candidates") or [])
    }
    snap_codes = (read_json(SNAP).get("codes") or {})
    gaps = []
    for code, prev in prev_close.items():
        raw = snap_codes.get(code)
        if not isinstance(raw, dict) or prev <= 0:
            continue
        cur = abs(number(raw.get("cur")))
        if cur <= 0:
            continue
        ts = str(raw.get("ts") or "")
        try:
            age_min = abs((now - datetime.fromisoformat(ts)).total_seconds()) / 60.0
        except ValueError:
            continue
        if age_min > SNAP_MAX_AGE_MIN:
            continue
        gaps.append((cur / prev - 1.0) * 100.0)

    if len(gaps) < MIN_CODES:
        log(f"판정 불가 — 예상체결가 확보 {len(gaps)}종목(<{MIN_CODES}) "
            f"→ 변경 없음(1번 현상 유지)")
        if FLAG.exists() and flag_is_mine():
            FLAG.unlink()
            log("과거 장세판정 깃발 청소 — 전 전략 조건진입 유지")
        save_record({"date": today, "verdict": "UNKNOWN",
                     "reason": f"ONLY_{len(gaps)}_CODES",
                     "checked_at": now.isoformat()})
        return 0

    gaps.sort()
    mid = len(gaps) // 2
    med = gaps[mid] if len(gaps) % 2 else (gaps[mid - 1] + gaps[mid]) / 2.0
    surge = med >= SURGE_GAP_MED
    verdict = "SURGE" if surge else "NORMAL_OR_CRASH"
    log(f"판정: {verdict} — 갭 중앙값 {med:+.2f}% (문턱 {SURGE_GAP_MED}%·{len(gaps)}종목)")

    if FLAG.exists() and flag_is_mine():
        FLAG.unlink()
        action = "ALL_STRATEGIES_OPEN(REGIME_JUDGE 깃발 제거)"
    elif FLAG.exists():
        action = "수동 깃발 존중 — 장세 판정은 기록만"
    else:
        action = "ALL_STRATEGIES_OPEN(장세 기록만)"
    log(f"실행: {action}")
    save_record({"date": today, "verdict": verdict, "gap_med_pct": round(med, 2),
                 "codes": len(gaps), "threshold_pct": SURGE_GAP_MED,
                 "action": action, "checked_at": now.isoformat()})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
