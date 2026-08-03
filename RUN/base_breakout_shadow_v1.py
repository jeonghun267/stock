# -*- coding: utf-8 -*-
"""💥 응집 베이스 폭발 그림자 관찰기 — 주문0·TR0·읽기전용  [2026-07-19 친구님 승인]

가설(친구님): 횡보=응집(에너지 축적) → 거래량 폭발+상단 돌파 → 단, 추격이 아니라 돌파선
리테스트 지정가로 잡는다. 백테(26일): 추격=전 설정 마이너스 / 리테스트 지정가+목표2%/손절-1.5%
= 48건 승률54% PF1.18 (+18,838원). 이 관찰기는 그 로직을 실시간 그림자로 돌리며, 백테로
검증 불가능했던 "폭발 순간의 체결강도 변화"까지 기록한다 — 며칠 실측 후 실전 여부 결정.

로직(1-pass·완성봉):
  베이스   = 직전 BB_BASE_N(30)개 완성 1분봉 진폭 ≤ BB_TIGHT(3.0)%
  폭발     = 방금 완성봉이 양봉 ∧ 종가>베이스 최고가 ∧ 거래량 ≥ 베이스평균×BB_VOLX(5.0)
  진입     = 폭발 후 BB_WAIT(10)봉 안에 현재가가 돌파선(베이스 최고가)까지 눌리면 지정가 가상체결
  청산     = 목표 +BB_TGT(2.0)% / 손절 BB_STP(-1.5)% / 15:10 (실시간 2초 판정 — 실전과 동일 프레임)
  종목당 최대 2회. 유니버스 = 골짜기 감시풀(전일 일봉 직접·코스닥·1만↑·700억~2조)과 동일 함수.
기록: 💥폭발(진폭·거래량배수·체결강도) → 🎯리테스트 체결(대기봉수·체결강도 변화) → 청산(수익률·사유)
  전부 LOG\\base_breakout_shadow.csv. 재기동 이어받기 = 장부(봉 이력 포함).
"""
import os, sys, csv, json, time
from pathlib import Path
from datetime import datetime

sys.path.insert(0, r"C:\stock_bot\RUN")
from valley_hunter_live_v1 import (_prev_eod_map, _build_morning_pool, _jload, _jsave,
                                   SNAP, BARS1M, NAMEC, _che_info)

LEDGER = Path(r"C:\stock_bot\data\base_breakout_shadow_ledger.json")
CSVP = Path(r"C:\stock_bot\LOG\base_breakout_shadow.csv")
LOG = Path(r"C:\stock_bot\data\LOG\base_breakout_shadow.log")

BASE_N = int(os.environ.get("BB_BASE_N", "30"))
TIGHT = float(os.environ.get("BB_TIGHT", "3.0"))
VOLX = float(os.environ.get("BB_VOLX", "5.0"))
WAIT_N = int(os.environ.get("BB_WAIT", "10"))
TGT = float(os.environ.get("BB_TGT", "2.0"))
STP = float(os.environ.get("BB_STP", "-1.5"))
MAX_TR = int(os.environ.get("BB_MAX_TRADES", "2"))
ENTRY_HM = os.environ.get("BB_ENTRY", "0930")     # 폭발 탐지 시작(봉 수집은 09:00부터)
ENTRY_END = os.environ.get("BB_ENTRY_END", "1430")
EXIT_HM = os.environ.get("BB_EXIT", "1510")
END_HM = os.environ.get("BB_END", "1512")
LOOP_SEC = float(os.environ.get("BB_LOOP_SEC", "2"))
RUN_SEC = float(os.environ.get("BB_RUN_SEC", "1190"))

COLS = ["일자", "시각", "종목코드", "종목명", "이벤트", "베이스상단", "베이스진폭", "거래량배수",
        "체결강도", "폭발시체결강도", "대기봉수", "가상진입가", "가상청산가", "수익률", "사유"]


def _log(m):
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8") as f:
            f.write(f"[{datetime.now():%H:%M:%S}] {m}\n")
    except Exception:
        pass
    print(m, flush=True)


def _csv(r):
    try:
        CSVP.parent.mkdir(parents=True, exist_ok=True)
        new = not CSVP.exists()
        with CSVP.open("a", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=COLS, extrasaction="ignore", restval="")
            if new:
                w.writeheader()
            w.writerow(r)
    except Exception as e:
        _log(f"CSV 실패: {e}")


def detect_breakout(hist, base_n=BASE_N, tight=TIGHT, volx=VOLX):
    """순수 판정(단위시험용): hist=[(hm,o,h,l,c,v)] 완성봉. 마지막 봉이 폭발이면
    (base_hi, 진폭%, 거래량배수) 아니면 None. 베이스=마지막 봉을 제외한 직전 base_n봉."""
    if len(hist) < base_n + 1:
        return None
    base = hist[-(base_n + 1):-1]
    hm, o, h, l, c, v = hist[-1]
    bhi = max(b[2] for b in base)
    blo = min(b[3] for b in base)
    if blo <= 0:
        return None
    rng = (bhi / blo - 1) * 100
    if rng > tight:
        return None
    av = sum(b[5] for b in base) / len(base)
    if not (c > o and c > bhi and av > 0 and v >= av * volx):
        return None
    return bhi, round(rng, 2), round(v / av, 1)


def main():
    now = datetime.now(); hm = now.strftime("%H%M"); today = now.strftime("%Y%m%d")
    if hm < "0900" or hm > END_HM:
        return
    _log("=" * 74)
    _log(f"💥 응집폭발 그림자(주문0) — 베이스{BASE_N}봉 진폭≤{TIGHT}%·거래량{VOLX}배·상단돌파 → "
         f"돌파선 리테스트 지정가({WAIT_N}봉 대기) → 목표+{TGT}%/손절{STP}%/{EXIT_HM[:2]}:{EXIT_HM[2:]} · "
         f"종목당 {MAX_TR}회 · 탐지 {ENTRY_HM[:2]}:{ENTRY_HM[2:]}~{ENTRY_END[:2]}:{ENTRY_END[2:]}")

    prev_d, prev_map = _prev_eod_map(today)
    if not prev_map:
        _log("🚨 전일 일봉 읽기 실패 — 관찰 불가")
        return
    try:
        names = json.loads(NAMEC.read_text(encoding="utf-8")).get("map", {})
    except Exception:
        names = {}
    try:
        snap0 = json.loads(SNAP.read_text(encoding="utf-8-sig")).get("codes", {})
    except Exception:
        snap0 = {}
    pool = _build_morning_pool(prev_map, names, snap0)
    _log(f"👀 관찰풀 = {len(pool)}종목 (골짜기 감시풀과 동일·전일 {prev_d})")

    L = _jload(LEDGER, {})
    if L.get("date") != today:
        L = {"date": today, "codes": {}}
        _jsave(LEDGER, L)

    deadline = time.monotonic() + RUN_SEC
    iso = now.strftime("%Y-%m-%d")
    while time.monotonic() < deadline:
        now = datetime.now(); hm = now.strftime("%H%M")
        if hm > END_HM:
            break
        try:
            snap = json.loads(SNAP.read_text(encoding="utf-8-sig")).get("codes", {})
        except Exception:
            snap = {}
        try:
            bars_now = json.loads(BARS1M.read_text(encoding="utf-8-sig"))
            bars_ok = str(bars_now.get("hm", "")) == hm
        except Exception:
            bars_now, bars_ok = {}, False
        dirty = False
        for code, info in pool.items():
            s = L["codes"].setdefault(code, {"hist": [], "cap_hm": None, "state": "SCAN",
                                             "trades": 0})
            if s.get("trades", 0) >= MAX_TR and s.get("state") not in ("POS",):
                continue
            v = snap.get(code) or {}
            ts = str(v.get("ts") or "")
            cur = float(v.get("cur", 0) or 0) if (not ts or ts[:10] == iso) else 0.0
            # ── 완성봉 수집(분 변경 시 직전 완성봉 적재·최근 45개) ──
            if bars_ok and s.get("cap_hm") != hm:
                m = (bars_now.get("m") or {}).get(code)
                if m:
                    prev = m.get("prev") or []
                    pv = m.get("pv") or []
                    if prev and pv:
                        try:
                            o_, h_, l_, c_ = [float(x) for x in prev[-1][:4]]
                            mm = int(hm[:2]) * 60 + int(hm[2:]) - 1
                            ph = f"{mm // 60:02d}{mm % 60:02d}"
                            if not s["hist"] or s["hist"][-1][0] != ph:
                                s["hist"].append([ph, o_, h_, l_, c_, float(pv[-1])])
                                s["hist"] = s["hist"][-45:]
                                dirty = True
                                # ── 새 완성봉 → 폭발 탐지(SCAN 상태·탐지창 안) ──
                                if (s["state"] == "SCAN" and ENTRY_HM <= hm <= ENTRY_END
                                        and s.get("trades", 0) < MAX_TR):
                                    det = detect_breakout(s["hist"])
                                    if det:
                                        bhi, rng, vx = det
                                        st_c, che, _a = _che_info(code)
                                        s.update({"state": "WAIT", "limit": bhi, "wait_left": WAIT_N,
                                                  "bo_che": che, "bo_hm": hm, "bo_rng": rng, "bo_vx": vx})
                                        _log(f"💥폭발 {info['name']}({code}) 베이스상단{bhi:,.0f} "
                                             f"진폭{rng}% 거래량{vx}배 체결강도{che:.0f}({st_c}) "
                                             f"→ 리테스트 {WAIT_N}봉 대기(추격 금지)")
                                        _csv({"일자": today, "시각": now.strftime("%H:%M:%S"),
                                              "종목코드": code, "종목명": info["name"], "이벤트": "BREAKOUT",
                                              "베이스상단": round(bhi), "베이스진폭": rng, "거래량배수": vx,
                                              "체결강도": round(che, 1)})
                                elif s["state"] == "WAIT":
                                    s["wait_left"] = int(s.get("wait_left", 0)) - 1
                                    if s["wait_left"] <= 0:
                                        s["state"] = "SCAN"
                                        _log(f"  ⌛리테스트 미도달 {info['name']}({code}) — 사이클 포기·재탐색")
                                        _csv({"일자": today, "시각": now.strftime("%H:%M:%S"),
                                              "종목코드": code, "종목명": info["name"], "이벤트": "EXPIRE",
                                              "베이스상단": round(float(s.get("limit", 0))),
                                              "사유": "리테스트미도달"})
                        except Exception:
                            pass
                s["cap_hm"] = hm

            if cur <= 0:
                continue
            # ── 리테스트 체결(실시간 지정가) ──
            if s["state"] == "WAIT" and cur <= float(s.get("limit", 0)):
                st_c, che, _a = _che_info(code)
                s.update({"state": "POS", "entry": float(s["limit"]), "peakhm": hm,
                          "fill_che": che})
                d_che = che - float(s.get("bo_che", 0) or 0)
                _log(f"🎯리테스트 체결 {info['name']}({code}) @{s['entry']:,.0f} "
                     f"체결강도 {float(s.get('bo_che', 0)):.0f}→{che:.0f}({d_che:+.0f}) — 가상 보유 시작")
                _csv({"일자": today, "시각": now.strftime("%H:%M:%S"), "종목코드": code,
                      "종목명": info["name"], "이벤트": "FILL", "베이스상단": round(s["entry"]),
                      "체결강도": round(che, 1), "폭발시체결강도": round(float(s.get("bo_che", 0)), 1),
                      "대기봉수": WAIT_N - int(s.get("wait_left", 0)), "가상진입가": round(s["entry"])})
                dirty = True
                continue
            # ── 가상 청산(실시간) ──
            if s["state"] == "POS":
                ent = float(s["entry"])
                ret = (cur / ent - 1) * 100
                why, px = None, cur
                if hm >= EXIT_HM:
                    why = "시간청산"
                elif ret <= STP:
                    why, px = "손절", ent * (1 + STP / 100)
                elif ret >= TGT:
                    why, px = "목표익절", ent * (1 + TGT / 100)
                if why:
                    r2 = (px / ent - 1) * 100
                    s["state"] = "SCAN"
                    s["trades"] = int(s.get("trades", 0)) + 1
                    _log(f"  💰가상청산 {info['name']}({code}) {why} @{px:,.0f} ({r2:+.2f}%) "
                         f"[{s['trades']}/{MAX_TR}회]")
                    _csv({"일자": today, "시각": now.strftime("%H:%M:%S"), "종목코드": code,
                          "종목명": info["name"], "이벤트": "EXIT", "가상진입가": round(ent),
                          "가상청산가": round(px), "수익률": round(r2, 2), "사유": why,
                          "폭발시체결강도": round(float(s.get("bo_che", 0)), 1)})
                    dirty = True
        if dirty:
            _jsave(LEDGER, L)
        time.sleep(LOOP_SEC)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
    except Exception as e:
        _log(f"🚨 치명 오류: {e}")
        sys.exit(1)
