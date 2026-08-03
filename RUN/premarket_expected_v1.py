# -*- coding: utf-8 -*-
"""[장전 예상체결가 감시 — 친구님 2026-07-01 "8:30 장전 예상체결가 실전 사용"]
   한국장: 08:30~09:00 장 시작 동시호가 = 실제 체결은 09:00 한 번(연속거래X·진짜 분봉은 09:00부터).
   그러나 이 사이 '예상체결가(예상 시가)'가 계속 갱신됨 → 개장 전에 오늘 갭업/갭다운·수요를 미리 안다.
   이 엔진(주문0):
     ① 전날 대장주 순위표(daily_leader_board) 종목을 micro_watch_premarket.json 로 구독 요청
        → broker 가 실시간 구독 → live_micro_snapshot 의 cur = 동시호가 예상체결가.
     ② 예상시가 vs 전일종가 = 갭% 계산 → data/premarket_gap.json (갭 내림차순 랭킹·예상량).
     ③ ★실전 연결: 갭업 강한 대장(gap≥PREMARKET_GAP_MIN)을 live_leaders.json 에 합류
        → leader_filter 가 개장 즉시 '오늘 갭 대장'으로 인식(union·갭전략/순위표가 9시부터 활용).
   ★주문 0(데이터·구독만). 매수는 각 전략 자기 게이트로. 08:30~09:00 매분 실행.
   ★검증 포인트(내일): 예상시가가 실제 09:00 시가와 맞는지 → premarket_gap.json 기록으로 사후 확인.
   env: PREMARKET_GAP_MIN=3(%·live 합류 문턱) · PREMARKET_TOPN=100 · PREMARKET_MERGE_LIVE=YES
"""
import os, sys, json
from pathlib import Path
from datetime import datetime

sys.path.insert(0, r"C:\stock_bot\RUN")

BOARD   = Path(r"C:\stock_bot\data\daily_leader_board.json")
SNAP    = Path(r"C:\stock_bot\IPC\live_micro_snapshot.json")
WATCH   = Path(r"C:\stock_bot\IPC\micro_watch_premarket.json")
LIVEF   = Path(r"C:\stock_bot\data\live_leaders.json")     # leader_filter 가 읽는 실시간 대장 파일
OUT     = Path(r"C:\stock_bot\data\premarket_gap.json")
LOG     = Path(r"C:\stock_bot\data\LOG\premarket_expected.log")

GAP_MIN     = float(os.environ.get("PREMARKET_GAP_MIN", "3"))     # live 합류 갭 문턱(%)
TOPN        = int(os.environ.get("PREMARKET_TOPN", "100"))
MERGE_LIVE  = os.environ.get("PREMARKET_MERGE_LIVE", "YES").strip().upper() == "YES"


def _log(m):
    s = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {m}"
    print(s, flush=True)
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(s + "\n")
    except Exception:
        pass


def _jload(p):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception:
        return {}


def _jsave(p, d):
    p = Path(p); p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, p)


def _board():
    """순위표 → {code: {name, prev_close}}. 전일 종가=board 의 close."""
    b = _jload(BOARD)
    out = {}
    for row in (b.get("board", []) or [])[:TOPN]:
        c = str(row.get("code", "")).lstrip("A").zfill(6)
        if len(c) == 6:
            out[c] = {"name": str(row.get("name", "")), "prev_close": float(row.get("close", 0) or 0)}
    return out


def run():
    now = datetime.now()
    hm = now.strftime("%H%M")
    if hm < "0830" or hm > "0900":           # 장 시작 동시호가 창
        return
    codes = _board()
    if not codes:
        _log("순위표 없음 → 보류"); return

    # ① 대장 구독 요청(broker glob 자동 구독) — 매 사이클 갱신
    _jsave(WATCH, {"codes": list(codes.keys()), "ts": now.isoformat(timespec="seconds"), "src": "premarket"})

    # ② 스냅샷 cur(=동시호가 예상체결가) 읽어 갭 계산
    snap = (_jload(SNAP) or {}).get("codes", {})
    rows = []
    for c, meta in codes.items():
        v = snap.get(c) or snap.get(c.zfill(6))
        pc = meta["prev_close"]
        if not isinstance(v, dict) or pc <= 0:
            continue
        exp = float(v.get("cur", 0) or 0)               # 예상 시가
        if exp <= 0:
            continue
        gap = (exp / pc - 1.0) * 100.0
        rows.append({
            "code": c, "name": meta["name"],
            "exp_open": exp, "prev_close": pc,
            "gap_pct": round(gap, 2),
            "exp_vol": float(v.get("cum_vol", 0) or 0),   # 예상 체결량(누적)
            "che_str": float(v.get("che_str", 0) or 0),
        })
    if not rows:
        _log(f"{hm} 예상체결가 아직 없음(동시호가 초반이거나 미구독) — 구독요청만 갱신"); return

    rows.sort(key=lambda r: -r["gap_pct"])
    for i, r in enumerate(rows, 1):
        r["gap_rank"] = i

    up = [r for r in rows if r["gap_pct"] >= GAP_MIN]
    _jsave(OUT, {"date": now.strftime("%Y%m%d"), "ts": now.isoformat(timespec="seconds"),
                 "gap_min": GAP_MIN, "count": len(rows), "up_count": len(up), "rows": rows})

    # ③ ★실전 연결: 갭업 강한 대장을 live_leaders.json 에 합류(union·개장 즉시 인식)
    if MERGE_LIVE and up:
        cur = _jload(LIVEF) if LIVEF.exists() else {}
        base = list(cur.get("codes", [])) if isinstance(cur, dict) else []
        merged = list(dict.fromkeys(base + [r["code"] for r in up]))    # 중복제거·순서보존
        import time as _t
        _jsave(LIVEF, {"ts": _t.time(), "codes": merged, "src": "premarket+live"})
        _log(f"{hm} 예상갭 {len(rows)}종목 · 갭업≥{GAP_MIN:.0f}% {len(up)}개 live 합류 "
             f"(1위 {rows[0]['name']} {rows[0]['gap_pct']:+.1f}%)")
    else:
        _log(f"{hm} 예상갭 {len(rows)}종목 계산 (갭업≥{GAP_MIN:.0f}% 없음·1위 {rows[0]['name']} {rows[0]['gap_pct']:+.1f}%)")


if __name__ == "__main__":
    try:
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    except Exception:
        pass
    try:
        run()
    except Exception as ex:
        _log(f"[FATAL] {ex}")
        import traceback; traceback.print_exc()
