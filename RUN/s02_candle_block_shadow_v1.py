# -*- coding: utf-8 -*-
"""S02 봉전환 매수차단(B안) 그림자 — 주문 0. 기록만.

배경 (친구님 지시 2026-08-14):
  2026-08-14 네오오토(212560) 가 10:05 매수 → 9분 만에 -2.11% 하드스톱.
  친구님 지적: "양봉도 작고 바로 음봉으로 길게 떨어졌는데 왜 매수했나."
  S02 는 초 단위 체결흐름만 보고 1분봉 모양은 전혀 안 본다.
  2026-08-13 밤 감사 49건 실측에서 B안(음봉/양→음 전환 시 차단)은 차단율 8.2%,
  차단됐을 4건 중 2건이 하드스톱이었다. 표본이 4건뿐이라 실전 배선 대신
  그림자부터 쌓기로 했다. 네오오토가 5번째 사례다.

무엇을 하나:
  S02 신호파일의 BUY_READY 를 읽고, 그 시각의 1분봉 상태를 붙여 CSV 에 남긴다.
    - would_block = 지금 봉이 음봉이거나, 직전 양봉 → 현재 음봉으로 전환
  실제 매수/매도에는 아무 영향이 없다.

지켜야 할 것 (프로젝트 사고 이력):
  - 브로커 IPC 호출 0. 파일만 읽는다. (8/13 그림자가 브로커 독점해 일봉·종가매수 마비)
  - 주문 API import 금지. (아래 _assert_no_order_api 가 자기 소스를 검사)
  - JSON 은 복사본으로 읽는다. (8/10 저장잠금: 원본을 열면 엔진 os.replace 가 죽는다)
  - 자료 없으면 추정하지 말고 사유를 남긴다 (fail-closed).

사용:
  C:\python310\python.exe -X utf8 RUN\s02_candle_block_shadow_v1.py            # 1회
  C:\python310\python.exe -X utf8 RUN\s02_candle_block_shadow_v1.py --loop     # 장중 감시
출력:
  data\shadow\s02_candle_block_shadow_YYYYMMDD.csv
"""
import argparse
import csv
import json
import os
import shutil
import sys
import tempfile
import time
from datetime import datetime

BASE = r"C:\stock_bot"
SIGNAL = os.path.join(BASE, "data", "strategy_02_low_buy_signal_v1.json")
BARS = os.path.join(BASE, "data", "돈맥_1분봉.json")
OUT_DIR = os.path.join(BASE, "data", "shadow")

FIELDS = ["ts", "code", "name", "reason", "price", "dip_drop_pct", "rebound_pct",
          "bar_hm", "bar_open", "bar_high", "bar_low", "bar_close", "bar_bull",
          "prev_bull", "body_pct", "would_block", "block_reason", "note"]


def _assert_no_order_api():
    """이 파일이 주문 경로를 절대 안 부르는지 자기 소스로 확인한다."""
    src = open(os.path.abspath(__file__), encoding="utf-8").read()
    banned = ("SENDORDER", "send_order", "broker_client", "BrokerClient",
              "kiwoom_buy_order", "place_order")
    hit = [b for b in banned if b in src.replace("banned", "")]
    # 이 목록 자체가 문자열로 들어 있으므로 정의 줄은 제외하고 센다
    hit = [b for b in hit if src.count(b) > 1]
    if hit:
        raise SystemExit("[SAFETY] 주문 API 흔적 발견: %s" % hit)


def rj(path):
    try:
        fd, tmp = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        shutil.copy2(path, tmp)
        with open(tmp, encoding="utf-8-sig") as f:
            data = json.load(f)
        os.unlink(tmp)
        return data
    except Exception:
        return None


def judge(bar):
    """B안 판정: 음봉이거나 양→음 전환이면 차단 대상."""
    if not bar:
        return None, "", "1분봉 없음"
    o, h, l, c = bar.get("o"), bar.get("h"), bar.get("l"), bar.get("c")
    if None in (o, c) or not o:
        return None, "", "봉 값 결측"
    bull = 1 if c > o else (0 if c < o else -1)   # -1 = 보합
    prev = bar.get("prev") or []
    prev_bull = ""
    if prev and isinstance(prev[0], (list, tuple)) and len(prev[0]) >= 4:
        po, pc = prev[0][0], prev[0][3]
        if po and pc:
            prev_bull = 1 if pc > po else (0 if pc < po else -1)
    body = round((c / o - 1) * 100, 3)
    if bull == 0:
        return True, "음봉", ""
    if prev_bull == 1 and bull != 1:
        return True, "양→음 전환", ""
    return False, "", ""


def run_once(seen):
    sig = rj(SIGNAL)
    if not isinstance(sig, dict):
        return 0
    today = datetime.now().strftime("%Y%m%d")
    if str(sig.get("date") or "") != today:
        return 0
    bars_doc = rj(BARS) or {}
    bars = bars_doc.get("m") or {}
    bar_hm = bars_doc.get("hm") or ""
    rows = []
    for s in (sig.get("signals") or []):
        if s.get("action") != "BUY_READY":
            continue
        key = (s.get("ts"), s.get("code"))
        if key in seen:
            continue
        seen.add(key)
        bar = bars.get(str(s.get("code")))
        blocked, breason, note = judge(bar)
        o = (bar or {}).get("o")
        c = (bar or {}).get("c")
        prev = (bar or {}).get("prev") or []
        pb = ""
        if prev and isinstance(prev[0], (list, tuple)) and len(prev[0]) >= 4:
            po, pc = prev[0][0], prev[0][3]
            if po and pc:
                pb = 1 if pc > po else 0
        rows.append({
            "ts": s.get("ts"), "code": s.get("code"), "name": s.get("name"),
            "reason": s.get("reason"), "price": s.get("price"),
            "dip_drop_pct": s.get("dip_drop_pct"), "rebound_pct": s.get("rebound_pct"),
            "bar_hm": bar_hm,
            "bar_open": o, "bar_high": (bar or {}).get("h"),
            "bar_low": (bar or {}).get("l"), "bar_close": c,
            "bar_bull": (bar or {}).get("bull"), "prev_bull": pb,
            "body_pct": (round((c / o - 1) * 100, 3) if (o and c) else ""),
            "would_block": ("" if blocked is None else ("Y" if blocked else "N")),
            "block_reason": breason, "note": note,
        })
    if not rows:
        return 0
    os.makedirs(OUT_DIR, exist_ok=True)
    out = os.path.join(OUT_DIR, "s02_candle_block_shadow_%s.csv" % today)
    new = not os.path.exists(out)
    with open(out, "a", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if new:
            w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in FIELDS})
    for r in rows:
        print("[S02-CANDLE] %s %s %s -> would_block=%s %s"
              % (r["ts"], r["code"], r["name"], r["would_block"], r["block_reason"]))
    return len(rows)


def main():
    _assert_no_order_api()
    ap = argparse.ArgumentParser()
    ap.add_argument("--loop", action="store_true", help="장중 감시 (5초 주기)")
    ap.add_argument("--until", default="1430", help="loop 종료 시각 HHMM")
    args = ap.parse_args()
    seen = set()
    if not args.loop:
        n = run_once(seen)
        print("[S02-CANDLE] 신규 %d건 기록" % n)
        return 0
    total = 0
    while datetime.now().strftime("%H%M") < args.until:
        try:
            total += run_once(seen)
        except Exception as exc:              # noqa: BLE001
            print("[S02-CANDLE] 오류(계속): %s" % exc)
        time.sleep(5)
    print("[S02-CANDLE] 종료. 누적 %d건" % total)
    return 0


if __name__ == "__main__":
    sys.exit(main())
