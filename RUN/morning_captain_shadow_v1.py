# -*- coding: utf-8 -*-
"""🔥 아침 대장 (Morning Captain) — 그림자 기록기  [주문 0 · TR 0]
2026-07-14 밤 신설 · 친구님 "아침 9시 땡 하면 30분 안에 사서 팔고 끝낸다"

■ 역할
  선별기(money_flow_board_v1)가 발행한 🔥아침대장 신호를 받아 **수익만 기록**한다.
  판정·선별은 선별기가 한다. 여기는 기록 전용(주문 0 · TR 0).

■ 매도 규칙 — ★두 가지를 동시에 기록해서 5일 뒤 직접 비교한다
  A안 [백테 최적]   09:20 전량청산 · 손절 -3%
  B안 [친구님 안]   10:20 전량청산 · 손절 -3% · 재난손절 -5% · 꼭지매도(3분봉 종가위치 ≤0.2) · 재진입 1회
  ⚠️백테(246일)에선 30분 시간청산이 최적이었고 트레일링·고정익절은 전부 더 나빴다.
    꼭지매도는 아침대장에 대해 **미검증** → 그림자로 실측해서 확정한다.

■ 데이터 (전부 TR 0)
  data/돈흐름_선별판.json      선별기의 🔥captain 신호 (code → rise/hh/bull/val/permin/mcap/rank)
  IPC/live_micro_snapshot.json 실시간 가격 (1,597종목)
  data/돈맥_3분봉.json         꼭지매도 판정용 3분봉 (기록기가 공급)

■ 출력  data/shadow/morning_captain.csv
■ 검증  5거래일 → A안/B안 비교 → 30분 수익 평균 +2%↑ AND 승률 60%↑ 이면 소액 실전
■ 끄기  MC_ON=NO
"""
import os, sys, csv, json, time, collections
from pathlib import Path
from datetime import datetime

BOARD = Path(r"C:\stock_bot\data\돈흐름_선별판.json")
SNAP  = Path(r"C:\stock_bot\IPC\live_micro_snapshot.json")
BARS3 = Path(r"C:\stock_bot\data\돈맥_3분봉.json")
NAMEC = Path(r"C:\stock_bot\data\_code_name_cache.json")
OUT   = Path(r"C:\stock_bot\data\shadow\morning_captain.csv")
LOG   = Path(r"C:\stock_bot\data\LOG\morning_captain_shadow.log")

LOOP_SEC   = float(os.environ.get("MC_LOOP_SEC", "5"))
END_HM     = os.environ.get("MC_END", "1030")        # 10:20 청산 + 여유
STOP_PCT   = float(os.environ.get("MC_STOP", "-3"))     # 손절
DISASTER   = float(os.environ.get("MC_DISASTER", "-5")) # 재난손절(유예 무시)
GRACE_MIN  = float(os.environ.get("MC_GRACE", "3"))     # 손절 유예(분)
TOP_POS    = float(os.environ.get("MC_TOP_POS", "0.2")) # 꼭지매도 3분봉 종가위치
TOP_GRACE  = float(os.environ.get("MC_TOP_GRACE", "9")) # 꼭지매도 유예(분)
EXIT_A     = os.environ.get("MC_EXIT_A", "0920")        # A안 청산
EXIT_B     = os.environ.get("MC_EXIT_B", "1020")        # B안 청산
REENTRY    = int(os.environ.get("MC_REENTRY", "1"))     # B안 재진입 횟수

COLS = ["일자", "신호시각", "종목코드", "종목명", "등수",
        # ── 선별기가 준 신호 지표 ──
        "진입가", "시가대비", "고가갱신율", "양봉비율", "누적대금억", "분당대금억", "시총억",
        # ── 결과: 공통 ──
        "시가", "당일최고", "당일최저", "★대장여부",
        "수익5분", "수익10분", "수익15분", "수익20분", "수익30분", "수익60분",
        "최고수익", "최고도달분", "최저수익",
        # ── A안 (09:20 청산 · 백테 최적) ──
        "A_수익", "A_사유", "A_시각",
        # ── B안 (10:20 + 꼭지매도 + 재진입 · 친구님 안) ──
        "B_수익", "B_사유", "B_시각", "B_재진입", "B_재진입가", "B_재진입수익", "B_합계"]


def _log(m):
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8") as f:
            f.write(f"[{datetime.now():%H:%M:%S}] {m}\n")
        print(m, flush=True)
    except Exception:
        pass


def _jload(p, d=None):
    try:
        return json.loads(p.read_text(encoding="utf-8-sig"))
    except Exception:
        return d if d is not None else {}


def _hm2m(hm):
    return int(hm[:2]) * 60 + int(hm[2:])


def main():
    if os.environ.get("MC_ON", "YES").strip().upper() != "YES":
        return
    today = datetime.now().strftime("%Y%m%d")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    if not OUT.exists():
        with OUT.open("w", encoding="utf-8-sig", newline="") as f:
            csv.writer(f).writerow(COLS)

    try:
        namemap = json.loads(NAMEC.read_text(encoding="utf-8")).get("map", {})
    except Exception:
        namemap = {}

    seen = {}          # code -> row (진입 기록)
    _log(f"기동 — 선별기 🔥아침대장 신호 대기 (주문 0 · TR 0) · "
         f"A안 {EXIT_A} 청산 / B안 {EXIT_B}+꼭지매도+재진입")

    while True:
        now = datetime.now()
        hm = now.strftime("%H%M")
        if hm > END_HM:
            break
        if hm < "0900":
            time.sleep(LOOP_SEC)
            continue
        mnow = _hm2m(hm)

        board = _jload(BOARD)
        snap = (_jload(SNAP) or {}).get("codes") or {}
        caps = board.get("captain") or {}
        b3 = (_jload(BARS3) or {}).get("m") or {}

        # ── ① 새 신호 기록 ──
        for code, c in caps.items():
            if code in seen:
                continue
            sc = snap.get(code)
            if not sc:
                continue
            try:
                px = float(sc.get("cur") or 0)
            except Exception:
                continue
            if px <= 0:
                continue
            rise = float(c.get("rise") or 0)
            op = px / (1 + rise / 100) if rise > -100 else px   # 시가 역산
            r = {"일자": today, "신호시각": c.get("hm") or hm, "종목코드": code,
                 "종목명": (namemap.get(code) or "")[:10] or code,
                 "등수": c.get("rank"), "진입가": px,
                 "시가대비": rise, "고가갱신율": c.get("hh"), "양봉비율": c.get("bull"),
                 "누적대금억": c.get("val"), "분당대금억": c.get("permin"), "시총억": c.get("mcap"),
                 "시가": round(op), "당일최고": px, "당일최저": px, "★대장여부": "",
                 "수익5분": None, "수익10분": None, "수익15분": None, "수익20분": None,
                 "수익30분": None, "수익60분": None,
                 "최고수익": 0.0, "최고도달분": 0, "최저수익": 0.0,
                 "A_수익": None, "A_사유": "", "A_시각": "",
                 "B_수익": None, "B_사유": "", "B_시각": "",
                 "B_재진입": 0, "B_재진입가": None, "B_재진입수익": None, "B_합계": None,
                 # 내부 상태
                 "_m0": mnow, "_ent": px, "_op": op,
                 "_b_open": True, "_b_ent": px, "_b_m0": mnow, "_b_re": 0, "_b_peak": px}
            seen[code] = r
            _log(f"🔥[{c.get('rank')}등] {code} {r['종목명']} @{px:,.0f} "
                 f"시가대비{rise:+.2f}% 갱신율{c.get('hh')}% 양봉{c.get('bull')}% 체결강도{c.get('che')} "
                 f"대금{c.get('val')}억 분당{c.get('permin')}억 시총{c.get('mcap'):,}억")
            _flush(seen)

        # ── ② 결과 추적 ──
        dirty = False
        for code, r in seen.items():
            sc = snap.get(code)
            if not sc:
                continue
            try:
                cur = float(sc.get("cur") or 0)
            except Exception:
                continue
            if cur <= 0:
                continue
            ent = r["_ent"]
            el = mnow - r["_m0"]
            ret = (cur / ent - 1) * 100

            if cur > r["당일최고"]:
                r["당일최고"] = cur; dirty = True
            if cur < r["당일최저"]:
                r["당일최저"] = cur; dirty = True
            if ret > r["최고수익"]:
                r["최고수익"] = round(ret, 2); r["최고도달분"] = el; dirty = True
            if ret < r["최저수익"]:
                r["최저수익"] = round(ret, 2); dirty = True
            # ★대장 여부 = 시가 대비 +10% 도달
            if not r["★대장여부"] and r["_op"] > 0 and (cur / r["_op"] - 1) * 100 >= 10:
                r["★대장여부"] = "Y"; dirty = True
            for mm, k in ((5, "수익5분"), (10, "수익10분"), (15, "수익15분"),
                          (20, "수익20분"), (30, "수익30분"), (60, "수익60분")):
                if el >= mm and r.get(k) is None:
                    r[k] = round(ret, 2); dirty = True

            # ── A안: 09:20 청산 · 손절 -3% (유예 3분) ──
            if r["A_수익"] is None:
                if el >= GRACE_MIN and ret <= STOP_PCT:
                    r.update(A_수익=round(STOP_PCT, 2), A_사유="손절", A_시각=hm); dirty = True
                elif hm >= EXIT_A:
                    r.update(A_수익=round(ret, 2), A_사유="시간", A_시각=hm); dirty = True

            # ── B안: 10:20 청산 + 재난손절 + 손절 + 꼭지매도 + 재진입 ──
            if r["B_수익"] is None and r["_b_open"]:
                b_ent = r["_b_ent"]
                b_el = mnow - r["_b_m0"]
                b_ret = (cur / b_ent - 1) * 100
                r["_b_peak"] = max(r["_b_peak"], cur)
                why = None
                if b_ret <= DISASTER:                       # ① 재난손절(유예 무시)
                    why = "재난손절"; val = DISASTER
                elif b_el >= GRACE_MIN and b_ret <= STOP_PCT:   # ② 손절
                    why = "손절"; val = STOP_PCT
                elif b_el >= TOP_GRACE:                     # ③ 꼭지매도(3분봉 위꼬리)
                    bb = b3.get(code) or {}
                    pos = bb.get("pos")
                    if pos is not None and float(pos) <= TOP_POS:
                        why = "꼭지매도"; val = b_ret
                if why is None and hm >= EXIT_B:            # ④ 10:20 전량청산
                    why = "시간"; val = b_ret

                if why:
                    if r["_b_re"] == 0:
                        r.update(B_수익=round(val, 2), B_사유=why, B_시각=hm)
                    else:
                        r.update(B_재진입수익=round(val, 2))
                        r["B_합계"] = round(float(r["B_수익"] or 0) + val, 2)
                    # ★재진입 — 꼭지로 판 경우에만 1회 (손절/재난/시간청산은 끝)
                    if why == "꼭지매도" and r["_b_re"] < REENTRY and hm < EXIT_B:
                        r["_b_open"] = False        # 재진입 대기
                        r["_b_exit_px"] = cur
                    else:
                        r["_b_open"] = False
                        r["_b_re"] = 99             # 종료
                    dirty = True

            # ── B안 재진입 판정 (꼭지로 판 뒤 다시 올라오면) ──
            if (not r["_b_open"] and r["_b_re"] < REENTRY
                    and r.get("_b_exit_px") and hm < EXIT_B):
                # 꼭지 매도가보다 +1% 위로 회복하면 재진입
                if cur >= r["_b_exit_px"] * 1.01:
                    r["_b_re"] += 1
                    r["_b_open"] = True
                    r["_b_ent"] = cur
                    r["_b_m0"] = mnow
                    r["_b_peak"] = cur
                    r["B_재진입"] = r["_b_re"]
                    r["B_재진입가"] = round(cur)
                    r.pop("_b_exit_px", None)
                    _log(f"  ↩️재진입 {code} @{cur:,.0f}")
                    dirty = True

        if dirty:
            _flush(seen)
        time.sleep(LOOP_SEC)

    # 마감
    for r in seen.values():
        if r["B_수익"] is not None and r["B_합계"] is None:
            r["B_합계"] = r["B_수익"]
    _flush(seen, final=True)
    n = len(seen)
    caps_n = len([r for r in seen.values() if r["★대장여부"] == "Y"])
    if n:
        a = [float(r["A_수익"]) for r in seen.values() if r["A_수익"] is not None]
        b = [float(r["B_합계"]) for r in seen.values() if r["B_합계"] is not None]
        _log(f"종료 — 신호 {n}건 · ★대장(시가대비+10%) {caps_n}건")
        if a:
            _log(f"  A안(09:20 청산)  평균 {sum(a)/len(a):+.2f}%  "
                 f"승률 {100*len([x for x in a if x>0])/len(a):.0f}%")
        if b:
            _log(f"  B안(10:20+꼭지+재진입) 평균 {sum(b)/len(b):+.2f}%  "
                 f"승률 {100*len([x for x in b if x>0])/len(b):.0f}%")
    else:
        _log("종료 — 신호 0건")


def _flush(seen, final=False):
    try:
        today = datetime.now().strftime("%Y%m%d")
        old = []
        if OUT.exists():
            with OUT.open(encoding="utf-8-sig") as f:
                old = [r for r in csv.DictReader(f) if r.get("일자") != today]
        with OUT.open("w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=COLS, extrasaction="ignore", restval="")
            w.writeheader()
            for r in old:
                w.writerow(r)
            for r in seen.values():
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
