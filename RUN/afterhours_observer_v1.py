# -*- coding: utf-8 -*-
"""장외(시간외) 공통 관찰기 — 2026-07-28 친구님 지시. 읽기전용·주문 0·TR 0.

목적
  정규장 밖(장전·장후)에 종목이 실제로 얼마나 거래되는지 기록해 둔다.
  1차 용도는 "종가 상한가로 잠긴 종목을 시간외에 살 수 있는가" 검증이고,
  산출물은 특정 전략 전용이 아니라 전 전략 공통 참고자료로 쓴다.

관찰 구간 (한국거래소)
  PRE_OFFHOURS  08:30~08:40  장전 시간외 종가 (전일 종가로 거래)
  PRE_AUCTION   08:40~09:00  장전 동시호가 (접수만·09:00 체결)
  POST_GAP      15:30~15:40  공백(주문 접수 불가)
  POST_CLOSE    15:40~16:00  장후 시간외 종가 (당일 종가로만 거래)
  POST_SINGLE   16:00~18:00  시간외 단일가 (당일 종가 ±10%, 단 당일 가격제한폭 내
                             → 상한가 마감주는 상한가가 천장이라 프리미엄 없음)

입력  IPC\live_micro_snapshot.json (브로커 실시간 구독 산출물·읽기만)
산출  data\afterhours\afterhours_YYYYMMDD.json  ← 다른 전략이 읽는 표준 파일
      data\afterhours\afterhours_YYYYMMDD.csv   ← 사람이 보는 용도(체결 있던 것만)

읽는 쪽 스키마
  codes[종목코드] = {
    "name", "day_close_px"(정규장 마지막 관찰가=종가 근사), "day_close_vol",
    "phases": { 구간명: {
        "vol_delta"  그 구간에서 늘어난 누적거래량 = 구간 체결량,
        "px_first","px_last","px_high","px_low","che_last","samples",
        "ts_first","ts_last" }}}
  ★vol_delta > 0 = 그 구간에 실제 체결이 있었다 = 같은 값에 주문을 걸었다면
    체결될 여지가 있었다는 근거. 0 = 완전히 잠김.
"""
import json
import os
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(r"C:\stock_bot")
SNAP = ROOT / "IPC" / "live_micro_snapshot.json"
NAME_CACHE = ROOT / "data" / "_code_name_cache.json"
OUT_DIR = ROOT / "data" / "afterhours"
LOCK = ROOT / "data" / "afterhours_observer_v1.lock"

SAMPLE_SEC = float(os.environ.get("AH_SAMPLE_SEC", "5"))
END_HM = int(os.environ.get("AH_END_HM", "1805"))
SAVE_EVERY_SEC = 60.0

PHASES = (
    ("PRE_OFFHOURS", 830, 840),
    ("PRE_AUCTION", 840, 900),
    ("POST_GAP", 1530, 1540),
    ("POST_CLOSE", 1540, 1600),
    ("POST_SINGLE", 1600, 1800),
)


def _phase(now):
    hm = now.hour * 100 + now.minute
    for name, lo, hi in PHASES:
        if lo <= hm < hi:
            return name
    return None


def _in_regular(now):
    hm = now.hour * 100 + now.minute
    return 900 <= hm < 1530


def _num(v, d=0.0):
    try:
        s = str(v).strip()
        return d if s == "" else float(s)
    except Exception:
        return d


def _read_json(p):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _acquire_lock():
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
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    LOCK.write_text(str(os.getpid()), encoding="utf-8")
    return True


def _save(state, names, started):
    today = datetime.now().strftime("%Y%m%d")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": "afterhours_observer_v1",
        "date": today,
        "started_at": started,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "note": "vol_delta>0 = 그 구간에 실제 체결 있었음. 전 전략 공통 참고자료.",
        "phase_windows": {n: "%04d~%04d" % (lo, hi) for n, lo, hi in PHASES},
        "code_count": len(state),
        "codes": {},
    }
    for code, st in state.items():
        ph = {}
        for pname, d in st.get("phases", {}).items():
            ph[pname] = {
                "vol_delta": int(max(0.0, d["vol_last"] - d["vol_first"])),
                "px_first": d["px_first"],
                "px_last": d["px_last"],
                "px_high": d["px_high"],
                "px_low": d["px_low"],
                "che_last": d.get("che_last"),
                "samples": d["samples"],
                "ts_first": d["ts_first"],
                "ts_last": d["ts_last"],
            }
        payload["codes"][code] = {
            "name": names.get(code) or "",
            "day_close_px": st.get("day_close_px"),
            "day_close_vol": (int(st["day_close_vol"]) if st.get("day_close_vol") else None),
            "phases": ph,
        }
    out = OUT_DIR / ("afterhours_%s.json" % today)
    tmp = out.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, out)

    csv_path = OUT_DIR / ("afterhours_%s.csv" % today)
    lines = ["code,name,phase,vol_delta,px_first,px_last,px_high,px_low,che_last,samples"]
    for code, rec in payload["codes"].items():
        for pname, d in rec["phases"].items():
            if d["vol_delta"] <= 0:
                continue
            lines.append("%s,%s,%s,%d,%s,%s,%s,%s,%s,%d" % (
                code, str(rec["name"]).replace(",", " "), pname, d["vol_delta"],
                d["px_first"], d["px_last"], d["px_high"], d["px_low"],
                d["che_last"], d["samples"]))
    tmp2 = csv_path.with_suffix(".csv.tmp")
    tmp2.write_text("\n".join(lines), encoding="utf-8-sig")
    os.replace(tmp2, csv_path)
    return out


def main():
    if not _acquire_lock():
        print("already running -> exit")
        return 0

    names = {}
    nc = _read_json(NAME_CACHE)
    if isinstance(nc, dict):
        for k, v in nc.items():
            names[str(k).zfill(6)] = v if isinstance(v, str) else (
                v.get("name", "") if isinstance(v, dict) else "")

    state = {}
    started = datetime.now().isoformat(timespec="seconds")
    last_save = 0.0
    last_ts_seen = {}

    try:
        while True:
            now = datetime.now()
            if now.hour * 100 + now.minute >= END_HM:
                break
            ph = _phase(now)
            reg = _in_regular(now)

            if ph or reg:
                rows = (_read_json(SNAP).get("codes") or {})
                for raw_code, raw in rows.items():
                    if not isinstance(raw, dict) or "cur" not in raw:
                        continue
                    code = str(raw_code).zfill(6)
                    ts = str(raw.get("ts") or "")
                    if not ts or last_ts_seen.get(code) == ts:
                        continue        # 체결이 있을 때만 ts가 바뀐다
                    last_ts_seen[code] = ts
                    px = abs(_num(raw.get("cur")))
                    vol = abs(_num(raw.get("cum_vol")))
                    che = raw.get("che_str")
                    if px <= 0:
                        continue
                    st = state.setdefault(code, {"phases": {}})

                    if reg:
                        st["day_close_px"] = px
                        st["day_close_vol"] = vol
                        continue

                    d = st["phases"].get(ph)
                    if d is None:
                        d = {"vol_first": vol, "vol_last": vol,
                             "px_first": px, "px_last": px,
                             "px_high": px, "px_low": px,
                             "che_last": che, "samples": 0,
                             "ts_first": ts, "ts_last": ts}
                        st["phases"][ph] = d
                    d["vol_last"] = max(d["vol_last"], vol)
                    d["px_last"] = px
                    d["px_high"] = max(d["px_high"], px)
                    d["px_low"] = min(d["px_low"], px)
                    d["che_last"] = che
                    d["samples"] += 1
                    d["ts_last"] = ts

            if time.time() - last_save >= SAVE_EVERY_SEC and state:
                _save(state, names, started)
                last_save = time.time()
            time.sleep(SAMPLE_SEC)
    finally:
        if state:
            print("saved:", _save(state, names, started))
        else:
            print("no data collected")
        try:
            LOCK.unlink()
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
