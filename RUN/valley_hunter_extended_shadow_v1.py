# -*- coding: utf-8 -*-
"""🏔️🔬 골짜기 확장 그림자(100억~1000억) — 2026-07-20 신설. 주문 0 · 실전 무접촉 · 영구 그림자.

목적: 과거 1분봉 리플레이로는 재현 못 하는 "2초 단위 체결강도·매수체결·매도체결·거래량 변화 추세"를
     실시간으로 수집해 100억~1000억 구간의 실제 BUY 전환율·수익성을 검증한다(친구님 승인·2026-07-20).

★격리 보장(친구님 지시 그대로) — 이 파일이 절대 하지 않는 것:
  - valley_hunter_live_v1.py / valley_low_buy_v1.py / SAFEPLUS_VALLEY_HUNTER_LIVE.cmd /
    shared_slots.py 를 단 1바이트도 수정하지 않는다(읽기전용 import만).
  - broker_client / send_order_real / BrokerClient 를 이 파일 어디서도 import·호출하지 않는다
    (실주문 함수 호출 경로 자체가 없음 — grep으로 0건 확인 가능).
  - shared_slots를 import하지 않는다 — 실전 공유슬롯을 절대 안 건드림.
  - 실전 ledger(valley_hunter_live_ledger.json 등) 파일명을 이 파일 어디서도 언급하지 않는다.

★실전 함수 재사용(재구현 아님) — 이 파일이 "복제"하는 게 아니라 "그대로 호출"하는 것:
  - valley_hunter_live_v1: _gate1_candidates, _crash_map, _cur, _che_info, _cum_vol, _bar1m,
    _ma5_daily/_ma10_daily/_ma20_daily/_ma60_daily, _ready_verdict, _refresh_market_cache,
    INSURE_PCT, PEAK_WATCH_SEC, SELL_SCORE_TH, SELL_TREND_MARGIN_PCT, SLOTS(기본6, 가상풀 크기용)
  - valley_low_buy_v1: LowAnchor, la_from_ledger, la_to_ledger, judge_trend, direction_persists,
    trend_pct_changes, _trend_desc, GATE1_START, GATE1_END, REBUY_STOP, REBUY_MAX
  → PVAL_MIN/MAX만 이 프로세스 환경변수로 100/1000 오버라이드(다른 프로세스인 실전 엔진에는
    영향 0 — 환경변수는 프로세스별). 매도 산식(하드손절~시간청산)만 실전 파일이 main() 루프
    안에 인라인이라 import 불가 → 위 상수·판정함수를 그대로 재사용해 동일 산식으로 미러링.

★가상 슬롯: shared_slots 대신 이 파일 전용 카운터(기본 6개, 실전과 동일 크기로만 맞춤 —
  실전 슬롯과는 완전히 별개 변수, 파일도 안 건드림). READY 재검증 메커니즘을 재현하기 위함.

★EXT_LOW(100~700억) / CONTROL(700~1000억) 두 구간을 모든 카운터·로그·CSV에서 항상 분리 기록.

★5거래일 또는 BUY_SHADOW 30건 누적 전까지 이 파일의 전략 관련 수치(연결 안 함 — 애초에 이
  파일엔 전략 파라미터가 없음, 전부 import) 변경 금지 — 운영 규칙.
"""
import os, sys, csv, json, time, collections
from pathlib import Path
from datetime import datetime, timedelta

sys.path.insert(0, r"C:\stock_bot\RUN")

# ★이 프로세스에서만 유효 — 실전 프로세스(다른 OS 프로세스)의 환경변수는 전혀 안 건드림.
os.environ["VH_PVAL_MIN"] = os.environ.get("VH_EXT_PVAL_MIN", "100")
os.environ["VH_PVAL_MAX"] = os.environ.get("VH_EXT_PVAL_MAX", "1000")
# VH_LIVE는 절대 설정하지 않는다 — 이 모듈 사본은 항상 LIVE=False(기본값 NO).

import valley_hunter_live_v1 as VHL   # 읽기전용 함수만 사용(아래 참고) — main()/Broker는 절대 호출 안 함
from valley_low_buy_v1 import (LowAnchor, la_from_ledger, la_to_ledger, judge_trend,
                                direction_persists, trend_pct_changes, _trend_desc,
                                GATE1_START, GATE1_END, REBUY_STOP, REBUY_MAX)

# ── 실전 상수 재사용(재정의 아님 — VHL 모듈에서 그대로 읽음) ──
INSURE_PCT = VHL.INSURE_PCT
PEAK_WATCH_SEC = VHL.PEAK_WATCH_SEC
SELL_SCORE_TH = VHL.SELL_SCORE_TH
SELL_TREND_MARGIN_PCT = VHL.SELL_TREND_MARGIN_PCT
HARD_STOP = REBUY_STOP   # -2.5% 단일 하드손절(valley_low_buy_v1 상수 그대로)

# ── 전용 스위치 ──
EXT_SLOTS = int(os.environ.get("VH_EXT_SLOTS", "6"))      # 가상 슬롯(shared_slots 아님)
LOOP_SEC = float(os.environ.get("VH_EXT_LOOP_SEC", "2"))  # 실전과 동일 2초 폴링 — 이 실험의 핵심
RUN_SEC = float(os.environ.get("VH_EXT_RUN_SEC", "23700"))  # 09:00~15:35 하루 통짜(재시작 없음)
ENTRY_HM = os.environ.get("VH_EXT_ENTRY", "0900")
END_HM = os.environ.get("VH_EXT_END", "1535")
DIAG_SEC = float(os.environ.get("VH_EXT_DIAG_SEC", "300"))   # 5분 진단 카운터

# ★[친구님 지시 2] LIVE 전환 기능 자체를 안 만든다 — 이 상수는 배너 로그 표기용일 뿐,
#   이 값을 읽어 분기하는 코드가 어디에도 없다(항상 그림자).
_EXT_LIVE_BANNER = os.environ.get("VH_EXT_LIVE", "NO")

LEDGER = Path(r"C:\stock_bot\data\valley_hunter_extended_shadow_ledger.json")
CSVLOG = Path(r"C:\stock_bot\LOG\valley_hunter_extended_shadow.csv")
LOG = Path(r"C:\stock_bot\data\LOG\valley_hunter_extended_shadow.log")
SELLWATCH = Path(r"C:\stock_bot\LOG\valley_extended_sell_watch.csv")

TRADE_COLS = ["일자", "시각", "종목코드", "종목명", "구간", "게이트",
              "무장시각", "무장가", "신저가리셋횟수", "관찰시작시각",
              "BUY시각", "BUY가", "체결강도변화율", "매수체결변화율", "매도체결변화율", "거래량변화율",
              "MFE", "MAE", "EXIT시각", "EXIT가", "수익률", "매도사유", "rqname"]

SELLWATCH_COLS = ["일자", "종목코드", "종목명", "구간", "음봉발생시각", "관찰시작", "관찰종료",
                  "관찰시간초", "체결강도변화율", "매수체결변화율", "매도체결변화율", "거래량변화율",
                  "고점재돌파", "결과", "매도사유"]


def _log(m):
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8") as f:
            f.write(f"[{datetime.now():%H:%M:%S}] {m}\n")
    except Exception:
        pass
    print(m, flush=True)


def _jload(p, d=None):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8-sig"))
    except Exception:
        return d if d is not None else {}


def _jsave(p, d):
    p = Path(p); p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, p)


def _csv_row(path, cols, r):
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        new = not path.exists()
        with path.open("a", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore", restval="")
            if new:
                w.writeheader()
            w.writerow(r)
    except Exception as e:
        _log(f"CSV 실패({path.name}): {e}")


def _order_shadow(code, qty, side, rqname_tag):
    """★[친구님 지시 2] Broker.order()까지 도달해도 실주문 함수는 호출하지 않는다.
       broker_client/send_order_real import 자체가 이 파일에 없음(grep으로 검증 가능)."""
    _log(f"  [EXT_SHADOW] {side} {code} x{qty} rqname={rqname_tag}")
    return "SHADOW"


def _bucket(pv):
    return "EXT_LOW" if 100 <= pv < 700 else ("CONTROL" if 700 <= pv <= 1000 else None)


def _new_stats():
    keys = ["WATCHLIST", "SNAP_OK", "SNAP_MISSING", "CHE_OK", "CHE_FAIL", "BAR_STALE",
            "ARMED", "LOW_RESET", "WATCH_START", "WAIT", "READY", "BUY_SHADOW", "EXIT_SHADOW"]
    return {"EXT_LOW": {k: 0 for k in keys}, "CONTROL": {k: 0 for k in keys}}


def main():
    now = datetime.now(); hm = now.strftime("%H%M"); today = now.strftime("%Y%m%d")
    if hm < ENTRY_HM or hm > END_HM:
        return
    _log("=" * 90)
    _log(f"🏔️🔬 골짜기 확장 그림자(100억~1000억) — 영구 SHADOW(VH_EXT_LIVE={_EXT_LIVE_BANNER}, 무시됨·"
         f"이 파일엔 실주문 코드 자체가 없음) · 가상슬롯 {EXT_SLOTS} · 실전 700억~2조와 완전 격리")
    _log(f"   PVAL(이 프로세스 전용)={os.environ['VH_PVAL_MIN']}~{os.environ['VH_PVAL_MAX']}억 "
         f"· EXT_LOW=100~700억 · CONTROL=700~1000억")

    L = _jload(LEDGER, {})
    if L.get("date") != today:
        L = {"date": today, "anchors": {}, "holdings": {}, "cum_stats": _new_stats(),
             "lowreset_cnt": {}, "armed_seen": {}}
        _jsave(LEDGER, L)

    ma5d = VHL._ma5_daily(); ma10d = VHL._ma10_daily()
    ma20d = VHL._ma20_daily(); ma60d = VHL._ma60_daily()

    slots_used = sum(1 for h in L["holdings"].values() if h.get("pos"))
    buy_shadow_total = sum(1 for h in L["holdings"].values() if h.get("done"))

    deadline = time.monotonic() + RUN_SEC
    last_diag = time.monotonic()
    cycle_stats = _new_stats()

    def _dump_diag(tag, stats):
        for bucket in ("EXT_LOW", "CONTROL"):
            s = stats[bucket]
            rng = "100~700억" if bucket == "EXT_LOW" else "700~1000억"
            _log(f"[진단·{tag}] {bucket} {rng}  " + " ".join(f"{k}={v}" for k, v in s.items()))

    while time.monotonic() < deadline:
        now = datetime.now(); hm = now.strftime("%H%M")
        if hm > END_HM:
            break
        dirty = False
        VHL._refresh_market_cache()   # 실전과 동일 — 이번 루프 스냅샷 1회 고정(실전 함수 재사용)

        cm = VHL._gate1_candidates() if hm < GATE1_END else VHL._crash_map()
        t = time.time()

        for code, info in cm.items():
            bucket = _bucket(float(info.get("pv") or 0))
            if bucket is None:
                continue
            cycle_stats[bucket]["WATCHLIST"] += 1
            L["cum_stats"][bucket]["WATCHLIST"] += 1

            cur = VHL._cur(code)
            if cur > 0:
                cycle_stats[bucket]["SNAP_OK"] += 1; L["cum_stats"][bucket]["SNAP_OK"] += 1
            else:
                cycle_stats[bucket]["SNAP_MISSING"] += 1; L["cum_stats"][bucket]["SNAP_MISSING"] += 1
                continue

            che_st, che, _age = VHL._che_info(code)
            if che_st == "OK":
                cycle_stats[bucket]["CHE_OK"] += 1; L["cum_stats"][bucket]["CHE_OK"] += 1
            else:
                cycle_stats[bucket]["CHE_FAIL"] += 1; L["cum_stats"][bucket]["CHE_FAIL"] += 1
                che = 0.0

            b1 = VHL._bar1m(code)
            if b1 is None:
                cycle_stats[bucket]["BAR_STALE"] += 1; L["cum_stats"][bucket]["BAR_STALE"] += 1

            cv = VHL._cum_vol(code)

            h = L["holdings"].get(code)
            if h and h.get("pos"):
                _sell_tick(L, code, h, cur, che, cv, ma10d, bucket, today, now)
                dirty = True
                continue
            if h and h.get("done"):
                continue   # 이미 매수1회+재매수 소진 — 이 종목은 오늘 끝

            a = L["anchors"].get(code) or {}
            la = la_from_ledger(code, a)
            was_armed = bool(a.get("gate1_armed"))
            prev_low = a.get("observation_low")

            ev = la.feed(hm, cur, cv, t, ma5d.get(code, 0), b1,
                         ma10d.get(code, 0), ma20d.get(code, 0), ma60d.get(code, 0), che,
                         prev_close=info.get("pc"))
            L["anchors"][code] = la_to_ledger(la)
            dirty = True

            if la.gate1_armed and not was_armed:
                cycle_stats[bucket]["ARMED"] += 1; L["cum_stats"][bucket]["ARMED"] += 1
                L["armed_seen"][code] = {"hm": hm, "px": cur}
                _log(f"  ⚡무장[{bucket}] {info.get('name',code)}({code}) {cur:,.0f} ({hm[:2]}:{hm[2:]})")

            if (la.state == "WATCHING_LOW" and prev_low and la.observation_low
                    and la.observation_low < float(prev_low)):
                L["lowreset_cnt"][code] = L["lowreset_cnt"].get(code, 0) + 1
                cycle_stats[bucket]["LOW_RESET"] += 1; L["cum_stats"][bucket]["LOW_RESET"] += 1

            if not ev:
                continue
            if ev["signal"] == "WATCH_START":
                cycle_stats[bucket]["WATCH_START"] += 1; L["cum_stats"][bucket]["WATCH_START"] += 1
                _log(f"  🏁관찰시작[{bucket}] {info.get('name',code)}({code}) 저점{ev['observation_low']:,.0f} "
                     f"[{ev.get('entry_gate')}] {ev.get('reason','')}")
            elif ev["signal"] == "WAIT":
                cycle_stats[bucket]["WAIT"] += 1; L["cum_stats"][bucket]["WAIT"] += 1
            elif ev["signal"] == "BUY":
                if slots_used >= EXT_SLOTS:
                    cycle_stats[bucket]["READY"] += 1; L["cum_stats"][bucket]["READY"] += 1
                    L.setdefault("ready", {})[code] = {"ev": ev, "bucket": bucket, "info": info,
                                                        "ts": time.time(), "cyc": la.reset_ts}
                    _log(f"  🕗READY[{bucket}] {info.get('name',code)}({code}) — 가상슬롯 만원({slots_used}/{EXT_SLOTS})")
                else:
                    _open_position(L, code, info, ev, cur, bucket, today, now)
                    slots_used += 1; buy_shadow_total += 1
                    cycle_stats[bucket]["BUY_SHADOW"] += 1; L["cum_stats"][bucket]["BUY_SHADOW"] += 1

        # READY 재검증(실전 _ready_verdict 재사용) — 가상슬롯 빌 때만 실행 시도
        for rc in list((L.get("ready") or {}).keys()):
            if slots_used >= EXT_SLOTS:
                break
            r = L["ready"][rc]
            curr = VHL._cur(rc)
            st_r, _cv_r, ag_r = VHL._che_info(rc)
            wait_s = time.time() - float(r.get("ts") or 0)
            anchor = L["anchors"].get(rc)
            verdict, why_r = VHL._ready_verdict(r["ev"], hm, curr, anchor, st_r, wait_s,
                                                 False, GATE1_END, 1.0, 1.5)
            if verdict == "DROP":
                L["ready"].pop(rc); dirty = True
                continue
            if verdict == "EXEC":
                _open_position(L, rc, r["info"], r["ev"], curr, r["bucket"], today, now)
                slots_used += 1; buy_shadow_total += 1
                cycle_stats[r["bucket"]]["BUY_SHADOW"] += 1
                L["cum_stats"][r["bucket"]]["BUY_SHADOW"] += 1
                L["ready"].pop(rc); dirty = True

        if time.monotonic() - last_diag >= DIAG_SEC:
            _dump_diag("5분누적", L["cum_stats"])
            last_diag = time.monotonic()
            cycle_stats = _new_stats()

        if dirty:
            _jsave(LEDGER, L)
        time.sleep(LOOP_SEC)

    _dump_diag("장마감", L["cum_stats"])
    _log(f"★오늘 누적 BUY_SHADOW={buy_shadow_total} — 5거래일 또는 30건 전까지 파라미터 변경 금지(운영규칙)")


def _open_position(L, code, info, ev, cur, bucket, today, now):
    nm = info.get("name", code)
    armed = L.get("armed_seen", {}).get(code, {})
    tr = ev.get("trend") or {}
    pct = {"che_pct": None, "buy_pct": None, "sell_pct": None, "vol_pct": None}
    la = la_from_ledger(code, L["anchors"].get(code, {}))
    if la.trend_log:
        pct = trend_pct_changes(la.trend_log)
    L["holdings"][code] = {"pos": True, "done": False, "name": nm, "bucket": bucket,
                            "gate": ev.get("entry_gate"), "entry_px": ev["entry_px"],
                            "entry_hm": ev.get("hm", now.strftime("%H%M")),
                            "entry_ts": now.strftime("%H:%M:%S"),
                            "peak": ev["entry_px"], "low": ev["entry_px"],
                            "armed_hm": armed.get("hm"), "armed_px": armed.get("px"),
                            "lowreset_n": L["lowreset_cnt"].get(code, 0),
                            "watch_start_ts": None,
                            "che_pct": pct["che_pct"], "buy_pct": pct["buy_pct"],
                            "sell_pct": pct["sell_pct"], "vol_pct": pct["vol_pct"],
                            "peak_watch_start": None, "sw_log": [], "ma10_reclaimed": False,
                            "sw_recovered": False, "rqname": f"VALLEY_EXT_SHADOW_BUY_{code}"}
    _order_shadow(code, 1, "BUY", f"VALLEY_EXT_SHADOW_BUY_{code}")
    _log(f"  💰BUY_SHADOW[{bucket}][{ev.get('entry_gate')}] {nm}({code}) @{cur:,.0f} "
         f"저점{ev['observation_low']:,.0f} 반등{ev.get('rebound_pct',0):+.2f}%")


def _sell_tick(L, code, h, cur, che, cv, ma10d, bucket, today, now):
    if cur > h["peak"]:
        h["peak"] = cur
    if cur < h["low"] or h["low"] == 0:
        h["low"] = cur
    ret = (cur / h["entry_px"] - 1) * 100
    why = None
    if ret <= HARD_STOP:
        why = "하드손절"
    else:
        drop_pk = (cur / h["peak"] - 1) * 100 if h["peak"] > 0 else 0.0
        if drop_pk <= INSURE_PCT:
            why = "보험선"
        else:
            ma10v = ma10d.get(code, 0)
            if h.get("ma10_reclaimed") and ma10v and cur < ma10v:
                why = "10일선최종보험"
            elif ma10v and cur > ma10v:
                h["ma10_reclaimed"] = True
    if why is None:
        # 음봉관찰 점수제 — judge_trend/direction_persists 실함수 재사용
        b1 = VHL._bar1m(code)
        hmv = now.strftime("%H%M")
        if b1 and b1.get("prev") and h.get("sw_last_hm") != hmv:
            try:
                bo, bh, bl, bc = [float(x) for x in b1["prev"][-1][:4]]
                if bc < bo and h.get("peak_watch_start") is None:
                    h["peak_watch_start"] = time.time(); h["sw_log"] = []
                    h["sw_start_px"] = cur; h["sw_recovered"] = False
            except Exception:
                pass
            h["sw_last_hm"] = hmv
        if h.get("peak_watch_start") is not None:
            if cur > float(h.get("sw_start_px") or cur):
                h["sw_recovered"] = True
            h["sw_log"].append((time.time(), che, 0.0, 0.0, cv if cv is not None else 0.0))
            elapsed = time.time() - h["peak_watch_start"]
            if elapsed >= PEAK_WATCH_SEC:
                tr = judge_trend(h["sw_log"], SELL_TREND_MARGIN_PCT)
                pts = {"che": bool(tr and tr["che"] < 0),
                       "buy": bool(tr and tr["buy"] < 0) or direction_persists(h["sw_log"], 2, -1),
                       "sell": bool(tr and tr["sell"] > 0) or direction_persists(h["sw_log"], 3, 1),
                       "reclaim": not h.get("sw_recovered", False)}
                score = sum(1 for v in pts.values() if v)
                if score >= SELL_SCORE_TH:
                    why = f"고점앙커매도(점수{score}/4)"
                else:
                    h["peak_watch_start"] = None
    if now.strftime("%H%M") >= "1530":
        why = why or "시간청산"
    if not why:
        return
    mfe = (h["peak"] / h["entry_px"] - 1) * 100
    mae = (h["low"] / h["entry_px"] - 1) * 100
    _order_shadow(code, 1, "SELL", f"VALLEY_EXT_SHADOW_SELL_{code}")
    _log(f"  🔚EXIT_SHADOW[{bucket}] {h['name']}({code}) @{cur:,.0f} ({ret:+.2f}%) 사유={why}")
    _csv_row(CSVLOG, TRADE_COLS, {
        "일자": today, "시각": now.strftime("%H:%M:%S"), "종목코드": code, "종목명": h["name"],
        "구간": bucket, "게이트": h.get("gate"), "무장시각": h.get("armed_hm"), "무장가": h.get("armed_px"),
        "신저가리셋횟수": h.get("lowreset_n"), "관찰시작시각": h.get("entry_ts"),
        "BUY시각": h.get("entry_hm"), "BUY가": h["entry_px"],
        "체결강도변화율": h.get("che_pct"), "매수체결변화율": h.get("buy_pct"),
        "매도체결변화율": h.get("sell_pct"), "거래량변화율": h.get("vol_pct"),
        "MFE": round(mfe, 2), "MAE": round(mae, 2),
        "EXIT시각": now.strftime("%H:%M:%S"), "EXIT가": cur, "수익률": round(ret, 2),
        "매도사유": why, "rqname": f"VALLEY_EXT_SHADOW_SELL_{code}"})
    h["pos"] = False; h["done"] = True
    L["anchors"].pop(code, None)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
    except Exception as e:
        _log(f"🚨 치명 오류: {e}")
        sys.exit(1)
