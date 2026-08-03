# -*- coding: utf-8 -*-
"""실시간 시세 지연 실측기 ② — 우리가 보는 가격이 몇 초 낡았나 (읽기 전용 · 주문 0).

★[2026-08-01 친구님 승인 "①② 둘 다 만들어줘"]
발단: 매도 실측 25건에서 체결가가 신호가보다 평균 -0.136% (최악 -1.084%).
      플러스도 10건 섞여 있어 = 스프레드만이 아니라 '시간이 흘렀다'는 증거.

무엇을 재나 (이 파일이 재는 것 / 못 재는 것을 분명히 한다)
  ✅ 잰다  broker 가 IPC\live_micro_snapshot.json 을 쓴 뒤 전략이 그 값을 보기까지의 지연
           = flush 주기(1000ms) + 종목별 스로틀(200ms) + 파일 폴링이 만드는 '우리 집 안' 지연
  ❌ 못 잰다 거래소→키움서버→우리 PC 구간. 그건 ①(broker_gateway FID 20 계측)이 담당한다.

핵심 지표 (upd_*)
  종목의 누적거래량·현재가가 직전 폴링 대비 '실제로 변한' 경우만 골라
  now - rec["ts"] 를 잰다. 값이 안 변한 종목은 지연이 아니라 '거래가 없는 것'이라
  섞으면 헛수가 된다(메모: rec["ts"]는 호가 이벤트만으로도 갱신돼 신선도 지표로 부적절).

산출물
  data\latency_probe\snapshot_lag_YYYYMMDD.csv   1초 1행 요약

읽기 전용 — 어떤 파일도 고치지 않고 주문 경로와 무관하다.
롤백: 이 파일 삭제 (다른 파일 수정 없음).
"""
from __future__ import annotations

import argparse
import csv
import json
import time
from datetime import datetime, time as clock_time
from pathlib import Path

BASE = Path(r"C:\stock_bot")
SNAPSHOT_FILE = BASE / "IPC" / "live_micro_snapshot.json"
HR_TOP30_FILE = BASE / "data" / "common_high_range_top30.json"
OUT_DIR = BASE / "data" / "latency_probe"

POLL_SECONDS = 1.0
LOOP_STOP = clock_time(15, 40)

COLUMNS = [
    "ts_local", "file_lag_sec", "n_codes",
    "upd_n", "upd_p50", "upd_p90", "upd_max",
    "stale_over2s", "stale_over4s",
    "worst_code", "worst_lag_sec",
    "hr_n", "hr_upd_n", "hr_p50", "hr_p90", "hr_max",
    "note",
]


def _read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return default


def _parse_ts(raw):
    try:
        return datetime.fromisoformat(str(raw))
    except (TypeError, ValueError):
        return None


def _pct(sorted_values, ratio):
    if not sorted_values:
        return ""
    idx = min(len(sorted_values) - 1, int(len(sorted_values) * ratio))
    return round(sorted_values[idx], 3)


def _hr_codes() -> set:
    payload = _read_json(HR_TOP30_FILE, {})
    codes = set()
    # 실제 키는 candidates (rank/code/name…). items/codes 는 형식이 바뀔 때를 위한 보조.
    items = payload.get("candidates") or payload.get("items") or payload.get("codes") or []
    for item in items:
        if isinstance(item, dict):
            code = item.get("code")
        else:
            code = item
        if code:
            codes.add(str(code).zfill(6))
    return codes


def sample(previous: dict, hr_codes: set) -> dict:
    """스냅샷 1회 관측 → 요약 1행. previous 는 code -> (cur, cum_vol) 직전값."""
    now = datetime.now()
    row = {key: "" for key in COLUMNS}
    row["ts_local"] = now.isoformat(timespec="milliseconds")

    payload = _read_json(SNAPSHOT_FILE, {})
    codes = payload.get("codes")
    if not isinstance(codes, dict) or not codes:
        row["note"] = "SNAPSHOT_EMPTY_OR_UNREADABLE"
        return row

    file_ts = _parse_ts(payload.get("ts"))
    if file_ts is not None:
        row["file_lag_sec"] = round((now - file_ts).total_seconds(), 3)
    row["n_codes"] = len(codes)

    updated_lags, hr_updated_lags = [], []
    stale2 = stale4 = 0
    worst_code, worst_lag = "", -1.0
    current = {}

    for code, rec in codes.items():
        if not isinstance(rec, dict):
            continue
        code = str(code).zfill(6)
        cur = rec.get("cur")
        cum = rec.get("cum_vol")
        current[code] = (cur, cum)

        rec_ts = _parse_ts(rec.get("ts"))
        if rec_ts is None:
            continue
        lag = (now - rec_ts).total_seconds()

        if lag > 2.0:
            stale2 += 1
        if lag > 4.0:
            stale4 += 1

        # ★값이 실제로 변한 종목만 = 순수 파이프라인 지연.
        #   안 변한 종목은 '거래가 없는 것'이지 지연이 아니다.
        if previous.get(code) not in (None, (cur, cum)):
            updated_lags.append(lag)
            if code in hr_codes:
                hr_updated_lags.append(lag)
            if lag > worst_lag:
                worst_lag, worst_code = lag, code

    previous.clear()
    previous.update(current)

    updated_lags.sort()
    hr_updated_lags.sort()
    row["upd_n"] = len(updated_lags)
    row["upd_p50"] = _pct(updated_lags, 0.50)
    row["upd_p90"] = _pct(updated_lags, 0.90)
    row["upd_max"] = round(updated_lags[-1], 3) if updated_lags else ""
    row["stale_over2s"] = stale2
    row["stale_over4s"] = stale4
    row["worst_code"] = worst_code
    row["worst_lag_sec"] = round(worst_lag, 3) if worst_lag >= 0 else ""
    row["hr_n"] = len(hr_codes & set(current))
    row["hr_upd_n"] = len(hr_updated_lags)
    row["hr_p50"] = _pct(hr_updated_lags, 0.50)
    row["hr_p90"] = _pct(hr_updated_lags, 0.90)
    row["hr_max"] = round(hr_updated_lags[-1], 3) if hr_updated_lags else ""
    return row


def append_row(path: Path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    new = not path.exists()
    with path.open("a", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS)
        if new:
            writer.writeheader()
        writer.writerow(row)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true", help="1회 관측 후 종료(동작 확인용)")
    parser.add_argument("--minutes", type=float, default=0.0, help="N분만 돌고 종료(0=15:40까지)")
    args = parser.parse_args()

    hr_codes = _hr_codes()
    out_path = OUT_DIR / f"snapshot_lag_{datetime.now():%Y%m%d}.csv"
    previous: dict = {}
    deadline = time.time() + args.minutes * 60 if args.minutes > 0 else None

    # 태스크로 돌면 로그가 append 라 '언제 시작했나'가 없으면 날짜별 구분이 안 된다
    started = datetime.now().isoformat(timespec="seconds")
    print(f"[지연실측②] {started} 시작 · 스냅샷={SNAPSHOT_FILE}")
    print(f"[지연실측②] 고저폭30 {len(hr_codes)}종목 · 출력={out_path}")

    while True:
        try:
            row = sample(previous, hr_codes)
            append_row(out_path, row)
            if args.once:
                print(json.dumps(row, ensure_ascii=False, indent=2))
                return 0
        except Exception as exc:                       # 관찰기가 죽어도 아무 데도 영향이 없게
            print(f"[지연실측②] 관측 오류(계속 진행): {type(exc).__name__}: {exc}")

        if deadline is not None and time.time() >= deadline:
            print("[지연실측②] --minutes 도달 종료")
            return 0
        if deadline is None and datetime.now().time() >= LOOP_STOP:
            print(f"[지연실측②] {datetime.now():%H:%M:%S} 15:40 도달 종료")
            return 0
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    raise SystemExit(main())
