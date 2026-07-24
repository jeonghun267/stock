# -*- coding: utf-8 -*-
"""
깊은바닥 '바닥 확인' 신호 기록기 (그림자·주문 0) — 2026-07-13 신설
[친구님 지시] "매도자가 폭락시키다가 바닥 가까이 오면 슬금슬금 내려오다가 바닥이 되냐,
              매수자가 위를 차지하나 보면 되지" / "양봉이라도 매도자가 쌓여 있으면 대기"

깊은바닥 후보가 진입창(저점 +REB_MIN~CHASE_BAND%)에 들어오는 '그 순간'의 판정 재료를 통째로 기록.
  ① 매도 소진   : 하락 감속비(저점 직전 3분 속도 ÷ 그 앞 5분 속도) — <1이면 매도 힘 빠짐
  ② 매수 우위   : 체결강도(che_str)·체결강도 저점 대비 반등폭
  ③ 매도벽 두께 : 호가 매도총잔량(ask_tot)·매수총잔량(bid_tot)·잔량비율(imb=bid/ask)
  ④ 봉 모양     : 자체 구성 1분봉의 아래꼬리(종가위치)·양봉 여부
그리고 30분·60분 뒤 성적과 '저점 재이탈(가짜바닥)' 여부를 같은 행에 채운다.

★주문 없음. TR 0 (전부 기존 파일 읽기). 실패해도 매매에 무해.
소비처 없음 — 며칠 쌓아 검증 후 진입조건 배선 판단.
"""
import os, sys, csv, json, time
from pathlib import Path
from datetime import datetime

SNAP      = Path(r"C:\stock_bot\IPC\live_micro_snapshot.json")      # 실시간(TR 0): cur·che_str·ask_tot·bid_tot·imb
CHE_STATE = Path(r"C:\stock_bot\data\돈흐름_che_state.json")         # 보드 누적: lo·lo_ts·min(체결강도 저점)
BOARD     = Path(r"C:\stock_bot\data\돈흐름_선별판.json")             # rows[].deep = 깊은바닥 등재
PREV_POOL = Path(r"C:\stock_bot\data\돈맥_전일상위풀.json")           # 전일종가
OUT       = Path(r"C:\stock_bot\data\shadow\deep_bottom_signals.csv")
LOG       = Path(r"C:\stock_bot\data\LOG\deep_bottom_signal_recorder.log")
# [7/13 친구님 "가격을 넣고 꼬리 양봉을 넣으면 되지"] ★매매기 진입 관문용 1분봉 공급.
#   매매기는 55초마다 프로세스가 죽어(RUN_SEC) 자체 봉 누적이 불가 → 상주하는 이 기록기가 봉을 만들어 넘긴다.
#   매 루프(5초) 갱신. 매매기는 pos(종가위치=꼬리)를 읽어 MF_DEEP_ENTRY_POS 관문에 사용.
BARS_OUT  = Path(r"C:\stock_bot\data\돈맥_1분봉.json")
BARS3_OUT = Path(r"C:\stock_bot\data\돈맥_3분봉.json")   # ★[7/14] 꼭지매도 판정용 3분봉(진입은 1분봉)


def _grid3(hm):
    """HHMM → 그 시각이 속한 3분 블록의 시작 HHMM (09:00 기준 격자). 09:04 → '0903'."""
    try:
        m = int(hm[:2]) * 60 + int(hm[2:])
        b = m - (m - 540) % 3          # 09:00을 격자 원점으로
        return f"{b // 60:02d}{b % 60:02d}"
    except Exception:
        return hm

REB_MIN    = float(os.environ.get("MF_DEEP_REB_MIN", "1.0"))
CHASE_BAND = float(os.environ.get("MF_CHASE_BAND", "2.0"))
DROP_PCT   = float(os.environ.get("MF_DEEP_DROP_PCT", "-4"))
MIN_DEPTH  = float(os.environ.get("MF_DEEP_MIN_DEPTH", "-6"))
GAP_FREE   = float(os.environ.get("MF_DEEP_GAP_FREE", "-3"))
LOOP_SEC   = float(os.environ.get("DBSR_LOOP_SEC", "5"))
END_HM     = os.environ.get("DBSR_END", "1510")

COLS = ["date", "time", "code", "name", "prev_close", "cur", "lo", "lo_ts", "depth", "gap",
        "band_pos", "che_str", "che_min", "che_reb", "ask_tot", "bid_tot", "imb",
        "m1_open", "m1_high", "m1_low", "m1_close", "m1_pos", "m1_bull",
        "decel", "spd", "ret15", "ret30", "ret60", "broke", "max_up", "max_dn"]


def _log(m):
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8") as f:
            f.write(f"[{datetime.now():%H:%M:%S}] {m}\n")
    except Exception:
        pass


def _jload(p, default=None):
    try:
        return json.loads(p.read_text(encoding="utf-8-sig"))
    except Exception:
        return default if default is not None else {}


def _prev_close_map():
    """전일종가 맵 — money_flow_exec_v1._prev_close_map()과 동일 구조(rows = [code, px, val])."""
    d = _jload(PREV_POOL)
    m = {}
    for row in d.get("rows", []):
        try:
            m[str(row[0]).zfill(6)] = float(row[1])
        except Exception:
            pass
    return m


def main():
    today = datetime.now().strftime("%Y%m%d")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    if not OUT.exists():
        with OUT.open("w", encoding="utf-8-sig", newline="") as f:
            csv.writer(f).writerow(COLS)

    bars = {}       # code -> {"hm":분, "o","h","l","c","v0"}  자체 1분봉 (진입=바닥확인용)
    bars_hist = {}  # code -> [[o,h,l,c], ...] 최근 완성 1분봉 5개 ★'양봉 N개 연속' 관문용
    vols_hist = {}  # ★[7/14 밤] code -> [v, ...] 최근 완성봉 거래량 5개 (아침대장 '분당 대금'용)
    v_open = {}     # ★[7/14 밤] code -> 09:00 봉 시작 누적거래량 (아침 누적대금 계산용)
    bars3 = {}      # code -> {"hm":3분블록 시작, "o","h","l","c"}  ★자체 3분봉 (매도=꼭지판정용)
    hist = {}       # code -> [(초, 가격)]  감속 계산용 가격 시계열
    seen = {}       # code -> row(dict)  이미 기록한 종목(종목당 1회)
    done = set()    # 결과까지 채운 종목
    pcm = {}
    n_rec = 0
    _log(f"기동 — 진입창 저점 +{REB_MIN}~{CHASE_BAND}% · 등재 {DROP_PCT}% · 낙폭 {MIN_DEPTH}% (주문 0)")

    while True:
        now = datetime.now()
        hm = now.strftime("%H%M")
        if hm > END_HM:
            break
        if hm < "0900":
            time.sleep(LOOP_SEC)
            continue

        if not pcm:
            pcm = _prev_close_map()

        snap = _jload(SNAP)
        cs = _jload(CHE_STATE)
        board = _jload(BOARD)
        codes = snap.get("codes") or {}
        deep_set = {str(r.get("code")).zfill(6) for r in (board.get("rows") or []) if r.get("deep")}
        name_map = {str(r.get("code")).zfill(6): r.get("name", "") for r in (board.get("rows") or [])}
        sec = now.hour * 3600 + now.minute * 60 + now.second

        for code, sc in codes.items():
            code = str(code).zfill(6)
            try:
                cur = float(sc.get("cur") or 0)
            except Exception:
                continue
            if cur <= 0:
                continue

            # ★[7/14 밤 아침대장] 누적거래량 — 1분봉 거래량(=분당 대금) 계산용.
            #   선별기 🔥아침대장이 "직전 3분 평균 분당 대금 ≥1억"(1,000만원 슬리피지 안전선)을 판정한다.
            #   실측 근거: 분당 대금 1억이면 1,000만원 주문 = 10% → 호가 1~2틱. 그 아래는 내가 호가를 만든다.
            try:
                _cv = float(sc.get("cum_vol") or 0)
            except Exception:
                _cv = 0.0

            # ---- 자체 1분봉 구성 ----
            b = bars.get(code)
            if b is None or b["hm"] != hm:
                if b is not None:
                    b["done"] = True
                    # ★[7/14] 완성된 봉을 버리지 말고 남긴다 — 매매기 '양봉 N개 연속' 관문용.
                    #   매매기는 55초마다 죽어 과거 봉을 못 들고 있다 → 여기서 최근 5개를 넘긴다.
                    _bh = bars_hist.setdefault(code, [])
                    _bh.append([b["o"], b["h"], b["l"], b["c"]])
                    del _bh[:-5]
                    # ★[7/14 밤] 완성봉의 거래량도 같은 순서로 남긴다(별도 리스트 = 기존 prev 구조 불변).
                    _vh = vols_hist.setdefault(code, [])
                    _vh.append(max(0.0, _cv - float(b.get("v0") or _cv)))
                    del _vh[:-5]
                bars[code] = {"hm": hm, "o": cur, "h": cur, "l": cur, "c": cur, "done": False,
                              "v0": _cv}      # ★봉 시작 시점의 누적거래량
                # ★[7/14 밤 아침대장] 09:00 봉의 시가를 붙잡아 둔다.
                #   "시가 대비 상승률"이 아침대장 1번 신호다(대장률 4.6% → 47%, 10.2배).
                #   ⚠️"전일종가 대비 등락률"과 완전히 다른 값이다. 혼동 금지.
                #   ⚠️스냅샷엔 시가 필드가 없다 → 09:00 첫 관측가로 근사(동시호가 직후라 오차 미미).
                if hm == "0900" and code not in v_open:
                    v_open[code] = cur
            else:
                b["h"] = max(b["h"], cur); b["l"] = min(b["l"], cur); b["c"] = cur
            # ---- ★[7/14 친구님 "깊은바닥 그대로 이식하고 바닥 잡는 것만 1분봉으로"] 자체 3분봉 구성 ----
            #   매도(꼭지)는 3분봉 꼬리로 판정해야 한다. 1분봉 꼬리는 너무 자주 떠서 꼭지가 아닌데도 판다.
            #   1분봉 207종목×43일 실측: 꼭지매도 수익 1분봉 +2.24% vs 3분봉 +2.88% (하루 +15,038원).
            #   진입(바닥 확인)은 1분봉 그대로 — 봉 두 개를 나란히 공급한다.
            _hm3 = _grid3(hm)
            b3 = bars3.get(code)
            if b3 is None or b3["hm"] != _hm3:
                bars3[code] = {"hm": _hm3, "o": cur, "h": cur, "l": cur, "c": cur}
            else:
                b3["h"] = max(b3["h"], cur); b3["l"] = min(b3["l"], cur); b3["c"] = cur
            # ---- 가격 시계열(감속용·최근 15분) ----
            hs = hist.setdefault(code, [])
            hs.append((sec, cur))
            if len(hs) > 200:
                del hs[:len(hs) - 200]

            # ================= 결과 채움 (이미 기록한 종목) =================
            if code in seen and code not in done:
                r = seen[code]
                el = (sec - r["_sec"]) / 60.0
                ep = r["_px"]
                r["max_up"] = max(float(r.get("max_up") or 0), (cur / ep - 1) * 100)
                r["max_dn"] = min(float(r.get("max_dn") or 0), (cur / ep - 1) * 100)
                if cur < r["_lo"]:
                    r["broke"] = 1
                for mins, key in ((15, "ret15"), (30, "ret30"), (60, "ret60")):
                    if el >= mins and r.get(key) in (None, ""):
                        r[key] = round((cur / ep - 1) * 100, 2)
                if el >= 60:
                    done.add(code)
                    _flush(seen, done)
                continue
            if code in seen:
                continue

            # ================= 진입창 판정 =================
            if code not in deep_set:
                continue
            st = cs.get(code) or {}
            try:
                lo = float(st.get("lo") or 0)
            except Exception:
                continue
            pc = pcm.get(code)
            if not pc or pc <= 0 or lo <= 0:
                continue
            depth = (lo / pc - 1) * 100
            if depth > DROP_PCT:
                continue
            o_px = float(st.get("o") or 0)
            gap = bool(o_px > 0 and (o_px / pc - 1) * 100 <= GAP_FREE)
            if depth > MIN_DEPTH and not gap:
                continue
            if not (lo * (1 + REB_MIN / 100) <= cur <= lo * (1 + CHASE_BAND / 100)):
                continue

            # ---- 이 순간의 판정 재료 ----
            che = sc.get("che_str")
            che_min = st.get("min")
            che_reb = (float(che) - float(che_min)) if (che is not None and che_min is not None) else None
            ask = sc.get("ask_tot")
            bid = sc.get("bid_tot")
            imb = sc.get("imb")
            bb = bars[code]
            rng = bb["h"] - bb["l"]
            m1_pos = round((bb["c"] - bb["l"]) / rng, 3) if rng > 0 else 0.5
            m1_bull = 1 if bb["c"] > bb["o"] else 0
            lo_ts = str(st.get("lo_ts") or "")
            lo_min = (int(lo_ts[:2]) * 60 + int(lo_ts[2:]) - 540) if (len(lo_ts) == 4 and lo_ts.isdigit()) else None
            spd = round(abs(depth) / max(lo_min, 3), 3) if lo_min is not None else None
            # 감속비: 저점 직전 3분 속도 ÷ 그 앞 5분 속도 (가격 시계열)
            decel = None
            try:
                def px_at(back_sec):
                    tgt = sec - back_sec
                    cand = [p for s, p in hs if s <= tgt]
                    return cand[-1] if cand else None
                p0, p3, p8 = cur, px_at(180), px_at(480)
                if p3 and p8 and p3 > 0 and p8 > 0:
                    v_recent = (p0 / p3 - 1) * 100 / 3
                    v_prior = (p3 / p8 - 1) * 100 / 5
                    if v_prior < -0.05:
                        decel = round(v_recent / v_prior, 3)
            except Exception:
                pass

            row = {"date": today, "time": now.strftime("%H%M%S"), "code": code,
                   "name": name_map.get(code, ""), "prev_close": pc, "cur": cur, "lo": lo,
                   "lo_ts": lo_ts, "depth": round(depth, 2), "gap": 1 if gap else 0,
                   "band_pos": round((cur / lo - 1) * 100, 2),
                   "che_str": che, "che_min": che_min,
                   "che_reb": round(che_reb, 2) if che_reb is not None else None,
                   "ask_tot": ask, "bid_tot": bid, "imb": imb,
                   "m1_open": bb["o"], "m1_high": bb["h"], "m1_low": bb["l"], "m1_close": bb["c"],
                   "m1_pos": m1_pos, "m1_bull": m1_bull, "decel": decel, "spd": spd,
                   "ret15": None, "ret30": None, "ret60": None, "broke": 0,
                   "max_up": 0.0, "max_dn": 0.0,
                   "_sec": sec, "_px": cur, "_lo": lo}
            seen[code] = row
            n_rec += 1
            _log(f"기록 {code} {name_map.get(code,'')} @{cur:,.0f} 낙폭{depth:+.1f}% "
                 f"저점+{(cur/lo-1)*100:.1f}% 체결강도{che} 매도벽{ask} 매수벽{bid} imb{imb} "
                 f"꼬리{m1_pos} 감속{decel}")
            _flush(seen, done)

        # ---- ★매매기 진입 관문용 1분봉 공급 (매 루프 갱신·주문 무관) ----
        #   매매기는 55초마다 프로세스가 죽어 자체 봉 누적이 불가 → 상주하는 여기서 만들어 넘긴다.
        #   pos = 종가위치(꼬리) = (종가-저가)/(고가-저가) · 1에 가까울수록 밑에서 받아 올린 것.
        try:
            _bo = {"ts": now.strftime("%Y-%m-%d %H:%M:%S"), "hm": hm, "m": {}}
            for _c, _b in bars.items():
                if _b["hm"] != hm:
                    continue
                _rng = _b["h"] - _b["l"]
                # ★[7/14 밤 아침대장] 진행 중인 봉의 거래량 = 현재 누적 - 봉 시작 누적
                _cvn = 0.0
                try:
                    _cvn = float((codes.get(_c) or {}).get("cum_vol") or 0)
                except Exception:
                    pass
                _vnow = max(0.0, _cvn - float(_b.get("v0") or _cvn))
                _bo["m"][_c] = {"o": _b["o"], "h": _b["h"], "l": _b["l"], "c": _b["c"],
                                "pos": round((_b["c"] - _b["l"]) / _rng, 3) if _rng > 0 else 0.5,
                                "bull": 1 if _b["c"] > _b["o"] else 0,
                                # ★[7/14] 직전 완성봉(오래된 것 → 최근 순). 매매기가 '양봉 N개 연속'을 판정한다.
                                "prev": (bars_hist.get(_c) or [])[-4:],
                                # ★[7/14 밤 아침대장] 아래 3개는 **추가만** — 기존 소비자(매매기) 무영향.
                                #   v   = 현재 봉 거래량        (분당 대금 계산)
                                #   pv  = 직전 완성봉 거래량들   (직전 3분 평균 분당 대금)
                                #   op  = ★09:00 봉의 시가      (시가 대비 상승률 = 대장 1번 신호)
                                "v": _vnow,
                                "pv": (vols_hist.get(_c) or [])[-4:],
                                "op": v_open.get(_c)}
            _tmp = BARS_OUT.with_suffix(".tmp")
            _tmp.write_text(json.dumps(_bo, ensure_ascii=False), encoding="utf-8")
            os.replace(_tmp, BARS_OUT)
        except Exception:
            pass

        # ---- ★[7/14] 매매기 꼭지매도용 3분봉 공급 (진입은 위의 1분봉·매도는 이것) ----
        #   hm = 그 3분 블록의 시작 시각. 매매기는 "지금이 어느 블록인지"를 같은 규칙으로 계산해 대조한다.
        try:
            _h3 = _grid3(hm)
            _b3o = {"ts": now.strftime("%Y-%m-%d %H:%M:%S"), "hm": _h3, "m": {}}
            for _c, _b in bars3.items():
                if _b["hm"] != _h3:
                    continue
                _rng3 = _b["h"] - _b["l"]
                _b3o["m"][_c] = {"o": _b["o"], "h": _b["h"], "l": _b["l"], "c": _b["c"],
                                 "pos": round((_b["c"] - _b["l"]) / _rng3, 3) if _rng3 > 0 else 0.5,
                                 "bull": 1 if _b["c"] > _b["o"] else 0}
            _tmp3 = BARS3_OUT.with_suffix(".tmp")
            _tmp3.write_text(json.dumps(_b3o, ensure_ascii=False), encoding="utf-8")
            os.replace(_tmp3, BARS3_OUT)
        except Exception:
            pass

        time.sleep(LOOP_SEC)

    _flush(seen, done, final=True)
    _log(f"종료 — 총 {n_rec}건 기록")


def _flush(seen, done, final=False):
    """전체 행을 CSV로 다시 씀(행 수 적음·안전)."""
    try:
        rows = list(seen.values())
        with OUT.open("w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=COLS, extrasaction="ignore")
            w.writeheader()
            for r in rows:
                w.writerow(r)
    except Exception as e:
        if final:
            _log(f"flush 실패: {e}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
    except Exception as e:
        _log(f"치명 오류: {e}")
        sys.exit(1)
