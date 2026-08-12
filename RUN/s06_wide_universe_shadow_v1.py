# -*- coding: utf-8 -*-
"""S06 넓은 우주 그림자 — 고저폭30 명단 "밖" 급락주에 S06 매수규칙을 가상 적용한다.

배경(2026-08-07 친구님 지시 "그림자로 먼저 해보자 / 지금 배선해야 돼 6번"):
  S06 의 감시 대상은 `IPC\\micro_watch_high_range.json` 30종목인데, 이 명단은
  08:40 에 **과거 고저폭 이력** 기준으로 한 번 뽑히고 장중 재선정이 없다.
  그래서 "오늘 처음 급락한 종목"은 구조적으로 영원히 보이지 않는다.
  8/7 09:36 실측: 고가대비 저가 -8% 이하 92종목 중 87종목(95%)이 명단 밖.

무엇을 하나:
  명단 **밖** 종목만 골라 S06 매수규칙을 가상 적용하고 CSV 에 기록한다.
  **주문은 절대 내지 않는다.** 읽기 전용 + 자기 출력 파일만 쓴다.

⚠️ 정직 고지 — 이것은 S06 의 완전한 복제가 아니다(기회의 상한선이다):
  구현함   : 최소가 1만원 · 기준가(시가) 대비 -8% 무장 · 저점 추적 ·
             매수구간 저점 +1.5%~+2.0% · 천장 초과 시 죽은저점 낙인
  구현 안함: 수급 조건(매수속도·체결강도·매수우위) · 눌림/2차반등 ·
             관찰 60초의 정확한 판정 · 슬롯/자본 제약
  ⇒ 여기 잡힌 건수는 **실제 S06 라면 더 적게 잡혔을 것**이다. 성적 비교 시 이 점을 반드시 감안.

되돌리기: 이 파일을 지우면 끝. 다른 파일을 일절 건드리지 않는다.
"""
import csv
import json
import os
import time
from datetime import datetime
from pathlib import Path

SNAP = Path(r"C:\stock_bot\IPC\live_micro_snapshot.json")
WATCH = Path(r"C:\stock_bot\IPC\micro_watch_high_range.json")
OUT_DIR = Path(r"C:\stock_bot\data\shadow")

MIN_PRICE = float(os.environ.get("S06_MIN_PRICE_KRW", "10000"))
DROP_PCT = float(os.environ.get("S06_DROP_PCT", "8.0"))
REBOUND_PCT = float(os.environ.get("S06_REBOUND_PCT", "1.5"))
CHASE_CAP_PCT = float(os.environ.get("S06_CHASE_CAP_PCT", "2.0"))
POLL_SEC = float(os.environ.get("S06W_POLL_SEC", "2.0"))
STOP_HM = os.environ.get("S06W_STOP_HM", "1510")
MIN_MONEY_EOK = float(os.environ.get("S06W_MIN_MONEY_EOK", "0"))  # 0 = 제한 없음(기록만)

COLUMNS = [
    "ts", "event", "code", "price", "base_price", "day_high", "day_low",
    "chase_low", "drop_from_base_pct", "rebound_from_low_pct",
    "money_eok", "che_str", "note",
]


def _num(x):
    try:
        return float(str(x).replace(",", "").lstrip("+"))
    except Exception:
        return 0.0


def _jread(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return default


def main() -> int:
    today = datetime.now().strftime("%Y%m%d")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_csv = OUT_DIR / f"s06_wide_shadow_{today}.csv"
    out_json = OUT_DIR / "s06_wide_shadow_latest.json"

    if not out_csv.exists():
        with out_csv.open("w", encoding="utf-8", newline="") as fh:
            csv.writer(fh).writerow(COLUMNS)

    # code -> 추적 상태
    track = {}
    # 가상 매수 목록
    buys = []
    watch_codes = set()
    watch_mtime = 0.0

    def emit(event, code, st, price, row, note=""):
        rec = [
            datetime.now().strftime("%H:%M:%S"), event, code, price,
            st.get("base"), st.get("high"), st.get("low_day"), st.get("chase_low"),
            round(price / st["base"] * 100 - 100, 3) if st.get("base") else "",
            round(price / st["chase_low"] * 100 - 100, 3) if st.get("chase_low") else "",
            round(_num(row.get("buy_money_cum")) + _num(row.get("sell_money_cum")) , 0) / 1e8,
            row.get("che_str"), note,
        ]
        try:
            with out_csv.open("a", encoding="utf-8", newline="") as fh:
                csv.writer(fh).writerow(rec)
        except Exception:
            pass

    print(f"[S06-WIDE-SHADOW] start {datetime.now():%H:%M:%S} → {out_csv.name} "
          f"(drop -{DROP_PCT}% · band +{REBOUND_PCT}~{CHASE_CAP_PCT}% · stop {STOP_HM}) 주문 0건",
          flush=True)

    while datetime.now().strftime("%H%M") < STOP_HM:
        try:
            # 감시명단 갱신 감지
            if WATCH.exists():
                mt = WATCH.stat().st_mtime
                if mt != watch_mtime:
                    watch_mtime = mt
                    w = _jread(WATCH, {})
                    watch_codes = {str(c).zfill(6) for c in (w.get("codes") or [])}

            snap = _jread(SNAP, {})
            codes = snap.get("codes") or {}

            for code, row in codes.items():
                if not isinstance(row, dict):
                    continue
                code = str(code).zfill(6)
                if code in watch_codes:          # S06 가 이미 보는 종목은 제외
                    continue
                cur = _num(row.get("cur"))
                op = _num(row.get("op"))
                hi = _num(row.get("hi"))
                lo = _num(row.get("lo"))
                if cur < MIN_PRICE or op <= 0:
                    continue
                money_eok = (_num(row.get("buy_money_cum")) + _num(row.get("sell_money_cum"))) / 1e8
                if MIN_MONEY_EOK and money_eok < MIN_MONEY_EOK:
                    continue

                st = track.setdefault(code, {
                    "base": op, "high": hi, "low_day": lo,
                    "armed": False, "chase_low": None, "dead_low": None,
                    "bought": False, "buy_price": None, "peak_after": None, "trough_after": None,
                })
                st["high"] = max(st["high"] or 0, hi)
                st["low_day"] = lo or st["low_day"]

                drop = (cur / st["base"] - 1.0) * 100.0

                # ★[8/7] S03 골짜기 자격대(시가 대비 -4~-8%)도 함께 기록한다.
                #   10:13 실측에서 S03 조건 충족 35종목 중 20종목이 고저폭30 밖이었다.
                #   기록 전용 — 아래 S06 무장 로직에는 영향 없다.
                if not st.get("s03_noted") and -8.0 <= drop <= -4.0:
                    st["s03_noted"] = True
                    emit("S03_BAND", code, st, cur, row, f"S03 자격대 drop={drop:.2f}%")

                # ① 무장 (S06 기준)
                if not st["armed"] and drop <= -DROP_PCT:
                    st["armed"] = True
                    st["chase_low"] = cur
                    emit("TRIGGER", code, st, cur, row, f"drop={drop:.2f}%")
                    continue

                if not st["armed"]:
                    continue

                # ② 저점 갱신
                if st["chase_low"] is None or cur < st["chase_low"]:
                    # 죽은저점보다 낮은 새 저점이면 빗장 해제
                    if st["dead_low"] and cur < st["dead_low"]:
                        st["dead_low"] = None
                    st["chase_low"] = cur
                    continue

                # ③ 이미 가상매수한 종목은 사후 추적만
                if st["bought"]:
                    st["peak_after"] = max(st["peak_after"] or cur, cur)
                    st["trough_after"] = min(st["trough_after"] or cur, cur)
                    continue

                if st["dead_low"]:
                    continue

                floor_px = st["chase_low"] * (1.0 + REBOUND_PCT / 100.0)
                ceil_px = st["chase_low"] * (1.0 + CHASE_CAP_PCT / 100.0)

                if cur > ceil_px:
                    st["dead_low"] = st["chase_low"]
                    emit("DEAD_LOW", code, st, cur, row, "천장 초과 → 죽은저점")
                    continue

                if cur >= floor_px:
                    st["bought"] = True
                    st["buy_price"] = cur
                    st["peak_after"] = cur
                    st["trough_after"] = cur
                    buys.append(code)
                    emit("BUY_SHADOW", code, st, cur, row,
                         f"저점 {st['chase_low']:.0f} 대비 +{(cur/st['chase_low']-1)*100:.2f}%")
                    print(f"[S06-WIDE-SHADOW] 가상매수 {code} @{cur:.0f} "
                          f"(저점 {st['chase_low']:.0f} · 시가대비 {drop:.2f}% · 대금 {money_eok:.0f}억)",
                          flush=True)

            # 요약 저장
            done = []
            for c in buys:
                s = track.get(c) or {}
                bp = s.get("buy_price") or 0
                if bp:
                    done.append({
                        "code": c, "buy": bp, "peak": s.get("peak_after"),
                        "trough": s.get("trough_after"),
                        "mfe_pct": round((s.get("peak_after", bp) / bp - 1) * 100, 3),
                        "mae_pct": round((s.get("trough_after", bp) / bp - 1) * 100, 3),
                    })
            tmp = out_json.with_suffix(".tmp")
            tmp.write_text(json.dumps({
                "ts": datetime.now().isoformat(timespec="seconds"),
                "armed": sum(1 for v in track.values() if v.get("armed")),
                "buys": len(buys), "detail": done,
            }, ensure_ascii=False, indent=1), encoding="utf-8")
            os.replace(tmp, out_json)

        except Exception as exc:
            print(f"[S06-WIDE-SHADOW] 오류(계속): {type(exc).__name__}: {exc}", flush=True)

        time.sleep(POLL_SEC)

    print(f"[S06-WIDE-SHADOW] 종료 {datetime.now():%H:%M:%S} · 무장 "
          f"{sum(1 for v in track.values() if v.get('armed'))} · 가상매수 {len(buys)}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
