# -*- coding: utf-8 -*-
"""🔬 골짜기 Gate1 진단 리포트 — 읽기전용(주문0·키움조회0·로컬 파일만)  [2026-07-19 친구님 승인]

친구님 진단 프로토콜 1~5를 장중(09:29·월~금) 실데이터로 실측한다:
  1) 고정 감시풀(코스닥·전일대금 700억~2조·전일종가 존재·현재가 1만↑) 종목 수
     ★[지침11] 전일 일봉(eod) 직접 구축 — 선별기 rows 미사용(엔진과 같은 함수 공유)
  2) 그중 live_micro_snapshot에 오늘 현재가 존재 수
  3) 그중 돈흐름_che_state 존재 수
  4) 09:00 이후 전일종가 -5% 터치 수 — 두 소스 교차(엔진 장부의 무장 실측 + che 당일저점)
  5) -5% 종목별 "옛 방식(_crash_map=che_state 순회)" 탈락 사유 전수
     (SNAP없음/CHE없음/CHE날짜불일치/거래량2배미달/가격미달/전일대금범위밖)
목적: 신규 고정 감시풀 방식(2026-07-19 배선)이 옛 방식 대비 뭘 더 보는지 숫자로 남긴다.
테스트용: env VG_DIAG_DATE=YYYYMMDD 지정 시 그 날짜 기준으로 판정(파일은 현재 것 사용).
"""
import os, sys, csv, json
from pathlib import Path
from datetime import datetime

sys.path.insert(0, r"C:\stock_bot\RUN")
from valley_hunter_live_v1 import (_prev_eod_map, _build_morning_pool, _jload, CHE, SNAP, NAMEC,
                                   LEDGER, PVAL_LO, PVAL_HI, PX_FLR,
                                   VOLSURGE_MULT, SESSION_MIN, _avg_daily_vol)

LOG = Path(r"C:\stock_bot\data\LOG\valley_gate1_diag.log")
CSVP = Path(r"C:\stock_bot\LOG\valley_gate1_diag.csv")
COLS = ["일자", "시각", "종목코드", "종목명", "전일종가", "전일대금억",
        "무장실측", "che저점교차", "스냅샷현재가", "옛방식탈락사유"]


def _log(m):
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8") as f:
            f.write(f"[{datetime.now():%H:%M:%S}] {m}\n")
    except Exception:
        pass
    print(m, flush=True)


def main():
    now = datetime.now()
    today = os.environ.get("VG_DIAG_DATE", "").strip() or now.strftime("%Y%m%d")
    iso = f"{today[:4]}-{today[4:6]}-{today[6:]}"
    che = _jload(CHE, {})
    try:
        snap = json.loads(SNAP.read_text(encoding="utf-8-sig")).get("codes", {})
    except Exception:
        snap = {}
    try:
        names = json.loads(NAMEC.read_text(encoding="utf-8")).get("map", {})
    except Exception:
        names = {}

    _log("=" * 74)
    _log(f"🔬 Gate1 진단({today}) — 읽기전용·주문0")
    prev_d, prev_map = _prev_eod_map(today)
    if not prev_map:
        _log("⛔ 전일 일봉(eod_daily_bars.csv) 읽기 실패 — 진단 중단")
        return
    fixed = _build_morning_pool(prev_map, names, snap)
    _log(f"1) MORNING WATCHLIST = {len(fixed)} (전일 {prev_d} 일봉 직접·rows 미사용)")

    def snap_cur(c):
        v = snap.get(c) or {}
        ts = str(v.get("ts") or "")
        if ts and ts[:10] != iso:
            return 0.0
        return float(v.get("cur", 0) or 0)

    has_snap = {c for c in fixed if snap_cur(c) > 0}
    no_snap = sorted(set(fixed) - has_snap)
    che_ok_date = str(che.get("date") or "") == today
    has_che = {c for c in fixed if isinstance(che.get(c), dict)}
    no_che = sorted(set(fixed) - has_che)
    _nm = lambda c: f"{c}({fixed[c]['name']})"
    _log(f"2) 스냅샷 현재가 존재: {len(has_snap)}/{len(fixed)}"
         + (" ⚠️없음: " + ", ".join(_nm(c) for c in no_snap) if no_snap else ""))
    _log(f"3) che_state 존재: {len(has_che)}/{len(fixed)} (che date {'오늘✓' if che_ok_date else '불일치⚠️'})"
         + (" 누락: " + ", ".join(_nm(c) for c in no_che) if no_che else ""))

    # 4) -5% 터치 — (a) 엔진 장부 무장 실측(신규 방식의 그라운드트루스) (b) che 당일저점 교차
    L = _jload(LEDGER, {})
    armed = set()
    if str(L.get("date") or "") == today:
        for c, a in (L.get("anchors") or {}).items():
            if isinstance(a, dict) and (a.get("gate1_armed") or a.get("gate1_armed_ts")
                                        or a.get("entry_gate") == "MORNING_CRASH"):
                armed.add(str(c).zfill(6))
        for c, s in (L.get("slots") or {}).items():
            if isinstance(s, dict) and s.get("entry_gate") == "MORNING_CRASH":
                armed.add(str(c).zfill(6))
    lo_hit = set()
    for c in fixed:
        cs = che.get(c) if isinstance(che.get(c), dict) else None
        lo = float((cs or {}).get("lo", 0) or 0)
        if lo > 0 and lo <= fixed[c]["pc"] * 0.95:
            lo_hit.add(c)
    hit = armed | lo_hit
    _log(f"4) 전일종가 -5% 터치: {len(hit)}종목 (엔진 무장실측 {len(armed)} · che저점 교차 {len(lo_hit)})")

    # 5) -5% 종목별 옛 방식(_crash_map) 탈락 사유 전수
    avgvol = _avg_daily_vol()
    elapsed = max(1.0, (now.hour - 9) * 60 + now.minute)
    n_dropped = 0
    rows = []
    for c in sorted(hit):
        b = fixed[c]
        why = []
        if snap_cur(c) <= 0:
            why.append("SNAP없음")
        if c not in has_che:
            why.append("CHE없음")
        elif not che_ok_date:
            why.append("CHE날짜불일치")
        if b["pc"] < PX_FLR:
            why.append("가격미달")
        if not (PVAL_LO <= b["pv"] <= PVAL_HI):
            why.append("전일대금범위밖")
        avd = avgvol.get(c)
        if avd and avd > 0:
            cv = float((snap.get(c) or {}).get("cum_vol") or 0)
            if cv < avd * (elapsed / SESSION_MIN) * VOLSURGE_MULT:
                why.append("거래량2배미달")
        tag = "+".join(why) if why else "통과(옛방식도 감시)"
        if why:
            n_dropped += 1
        _log(f"5)   {b['name']}({c}) 전일종가{b['pc']:,.0f} → 옛방식: {tag}")
        rows.append({"일자": today, "시각": now.strftime("%H:%M:%S"), "종목코드": c,
                     "종목명": b["name"], "전일종가": round(b["pc"]), "전일대금억": round(b["pv"]),
                     "무장실측": "Y" if c in armed else "", "che저점교차": "Y" if c in lo_hit else "",
                     "스냅샷현재가": round(snap_cur(c)), "옛방식탈락사유": tag if why else ""})
    try:
        CSVP.parent.mkdir(parents=True, exist_ok=True)
        new = not CSVP.exists()
        with CSVP.open("a", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=COLS, extrasaction="ignore", restval="")
            if new:
                w.writeheader()
            w.writerows(rows)
    except Exception as e:
        _log(f"CSV 실패: {e}")
    _log(f"★결론: -5% {len(hit)}종목 중 옛 che방식 탈락 {n_dropped}종목 / "
         f"신규 고정풀은 {len(fixed)}종목 전부 감시(스냅샷 없는 {len(no_snap)}종목만 시세공백) → {CSVP}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        _log(f"🚨 치명 오류: {e}")
        sys.exit(1)
