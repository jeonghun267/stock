# -*- coding: utf-8 -*-
"""S02 관찰창 리셋 규칙 그림자 (2026-07-28 친구님 지시, 3거래일 관찰).

목적: S02 신호기의 '10초 공백 시 관찰창 전량 폐기' 규칙이 실제로 파동 관찰을
      얼마나 방해하는지 측정한다. 임계값 4종을 동시에 돌려 비교한다.

성격: 순수 관찰. 실전 코드·상태·주문에 일절 손대지 않는다.
      입력은 엔진과 같은 live_micro_snapshot(읽기 전용)이고 TR은 0건이다.

산출: data\s02_window_shadow_YYYYMMDD.json (일별)
"""
import json
import os
import time
from collections import deque
from datetime import datetime
from pathlib import Path

ROOT = Path(r"C:\stock_bot")
SNAP = ROOT / "IPC" / "live_micro_snapshot.json"
WATCH = ROOT / "IPC" / "micro_watch_strategy_shared.json"
DATA = ROOT / "data"
LOCK = DATA / "s02_window_shadow_v1.lock"

# 엔진(strategy_02_low_buy_signal_v1)과 동일한 상수
WINDOW_SEC = 300
MAX_AGE = float(os.environ.get("S02_SNAPSHOT_MAX_AGE", "4"))
MIN_PRICE = float(os.environ.get("S02_MIN_PRICE", "10000"))
LOOP_SEC = float(os.environ.get("S02_LOOP_SEC", "1"))

END_HM = int(os.environ.get("S02WS_END_HM", "1530"))
THRESHOLDS = {"10s_current": 10.0, "20s": 20.0, "30s": 30.0, "unlimited": 10.0 ** 9}


def _num(v, default=0.0):
    try:
        return float(str(v).replace(",", ""))
    except Exception:
        return default


def _dt(v):
    if not v:
        return None
    try:
        return datetime.fromisoformat(str(v))
    except Exception:
        return None


def _read(p):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _acquire_lock():
    """단일 인스턴스 보장. 살아 있는 주인이 있으면 즉시 종료."""
    if LOCK.exists():
        try:
            pid = int(LOCK.read_text(encoding="utf-8").strip() or "0")
        except Exception:
            pid = 0
        if pid > 0:
            try:
                os.kill(pid, 0)
                return False
            except OSError:
                pass
    LOCK.write_text(str(os.getpid()), encoding="utf-8")
    return True


def _pct(vals, q):
    if not vals:
        return 0.0
    s = sorted(vals)
    return s[min(len(s) - 1, int(len(s) * q))]


def _save(resets, spans, dup, evals, started, loops):
    today = datetime.now().strftime("%Y%m%d")
    out = DATA / ("s02_window_shadow_%s.json" % today)
    summary = {
        "schema": "s02_window_shadow_v1",
        "date": today,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "started_at": started,
        "loops": loops,
        "eval_count": evals,
        "duplicate_skips": dup,
        "window_sec": WINDOW_SEC,
        "by_threshold": {},
    }
    for label in THRESHOLDS:
        sp = spans[label]
        n = len(sp)
        summary["by_threshold"][label] = {
            "resets": resets[label],
            "observations": n,
            "span_p50": round(_pct(sp, 0.5), 1),
            "span_p90": round(_pct(sp, 0.9), 1),
            "span_max": round(max(sp), 1) if sp else 0.0,
            "pct_ge_60s": round(100.0 * sum(1 for x in sp if x >= 60) / n, 1) if n else 0.0,
            "pct_ge_180s": round(100.0 * sum(1 for x in sp if x >= 180) / n, 1) if n else 0.0,
            "pct_ge_300s": round(100.0 * sum(1 for x in sp if x >= 300) / n, 1) if n else 0.0,
        }
    tmp = out.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, out)
    return out


def main():
    if not _acquire_lock():
        print("already running -> exit")
        return 0

    states = {k: {} for k in THRESHOLDS}
    resets = {k: 0 for k in THRESHOLDS}
    spans = {k: [] for k in THRESHOLDS}
    dup = 0
    evals = 0
    loops = 0
    started = datetime.now().isoformat(timespec="seconds")
    last_save = time.time()

    try:
        while True:
            now = datetime.now()
            if now.hour * 100 + now.minute >= END_HM:
                break
            loops += 1

            codes = {str(c).zfill(6) for c in (_read(WATCH).get("codes") or [])}
            rows = (_read(SNAP).get("codes") or {})

            for raw_code, raw in rows.items():
                code = str(raw_code).zfill(6)
                if code not in codes or not isinstance(raw, dict):
                    continue
                ts = _dt(raw.get("ts"))
                if ts is None or not (-2 <= (now - ts).total_seconds() <= MAX_AGE):
                    continue
                ob_ts = _dt(raw.get("ob_ts") or raw.get("book_ts") or raw.get("hoga_ts"))
                if ob_ts is not None and not (-2 <= (now - ob_ts).total_seconds() <= MAX_AGE):
                    continue
                if abs(_num(raw.get("cur"))) < MIN_PRICE:
                    continue

                tse = ts.timestamp()
                buy_cum = _num(raw.get("buy_money_cum"), -1.0)
                sell_cum = _num(raw.get("sell_money_cum"), -1.0)
                evals += 1

                for label, th in THRESHOLDS.items():
                    dq = states[label].setdefault(code, deque(maxlen=360))
                    if dq:
                        l_ts, l_buy, l_sell = dq[-1]
                        if tse <= l_ts:
                            if label == "10s_current":
                                dup += 1
                            continue
                        if buy_cum < l_buy or sell_cum < l_sell or (tse - l_ts) > th:
                            dq.clear()
                            resets[label] += 1
                    dq.append((tse, buy_cum, sell_cum))
                    cutoff = tse - WINDOW_SEC
                    while dq and dq[0][0] < cutoff:
                        dq.popleft()
                    spans[label].append(dq[-1][0] - dq[0][0])

            if time.time() - last_save >= 300:
                _save(resets, spans, dup, evals, started, loops)
                last_save = time.time()
            time.sleep(LOOP_SEC)
    finally:
        out = _save(resets, spans, dup, evals, started, loops)
        print("saved:", out)
        try:
            LOCK.unlink()
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
