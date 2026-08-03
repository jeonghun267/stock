# -*- coding: utf-8 -*-
"""[테마 지도 v1 — 친구님 2026-07-04 "테마 대장주"] 키움 분류(지도) + 우리 대장 기준(거래대금) 하이브리드.
- 유니버스(대장 순위표) 각 종목의 소속 테마를 브로커에서 역조회(opt90001 검색구분=2).
- 전체 테마의 당일 등락율/5일 수익률(검색구분=0)로 '뜨거운 테마' 산출.
- 테마별 우리 종목 묶음에서 전일 거래대금 1위 = 그 테마의 "테마대장" 마킹.
- ★점수 미반영·표시 전용(검증 먼저). 출력: data/테마지도.json + 테마지도.txt
- env: THEME_BOARD(순위표 경로 오버라이드), THEME_HOT_N(뜨거운 테마 표시 수, 기본 15)
"""
import os, sys, json, time
from pathlib import Path
from datetime import datetime
sys.path.insert(0, r"C:\stock_bot\RUN")

BOARD = Path(os.environ.get("THEME_BOARD", r"C:\stock_bot\data\daily_leader_board.json"))
OUT_J = Path(r"C:\stock_bot\data\테마지도.json")
OUT_T = Path(r"C:\stock_bot\data\테마지도.txt")
LOG   = Path(r"C:\stock_bot\data\LOG\테마지도.log")
HOT_N = int(os.environ.get("THEME_HOT_N", "15"))


def _log(m):
    s = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {m}"
    print(s, flush=True)
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        open(LOG, "a", encoding="utf-8").write(s + "\n")
    except Exception:
        pass


def _f(x):
    try: return float(str(x).replace(",", "").replace("+", ""))
    except Exception: return 0.0


def build():
    from broker_client import BrokerClient, is_broker_alive
    if not is_broker_alive():
        _log("broker dead → skip"); return None
    bc = BrokerClient()
    try:
        board = json.loads(BOARD.read_text(encoding="utf-8"))
    except Exception as e:
        _log(f"순위표 없음({e}) → skip"); return None
    stocks = {str(b["code"]).zfill(6): b for b in board.get("board", [])}
    _log(f"유니버스 {len(stocks)}종목 (순위표 {board.get('date')})")

    # ① 종목 → 소속 테마 (역조회)
    code2themes = {}
    for i, code in enumerate(stocks):
        try:
            r = bc.tr("opt90001", inputs={"검색구분": "2", "종목코드": code, "날짜구분": "5"},
                      output_fields=["테마명"], timeout_sec=6.0, screen_no="9766")
            ts = [str(z.get("테마명", "")).strip() for z in (((r or {}).get("data") or {}).get("records") or [])]
            code2themes[code] = [t for t in ts if t]
        except Exception:
            code2themes[code] = []
        time.sleep(0.25)
    _log(f"테마 역조회 완료 (평균 {sum(len(v) for v in code2themes.values())/max(1,len(code2themes)):.1f}개/종목)")

    # ② 전체 테마 열기(당일 등락율·5일 수익률)
    heat = {}
    pn = 0
    for _ in range(5):
        r = bc.tr("opt90001", inputs={"검색구분": "0", "날짜구분": "5"},
                  output_fields=["테마명", "종목수", "등락율", "기간수익률"],
                  rqname="theme_all", screen_no="9767", next_flag=pn, timeout_sec=8.0)
        d = (r or {}).get("data") or {}
        for z in d.get("records") or []:
            nm = str(z.get("테마명", "")).strip()
            if nm:
                heat[nm] = {"today": _f(z.get("등락율")), "d5": _f(z.get("기간수익률")), "n": int(_f(z.get("종목수")))}
        if str(d.get("prev_next", "")).strip() != "2":
            break
        pn = 2; time.sleep(0.3)
    _log(f"테마 열기 {len(heat)}개 수집")

    # ③ 테마 → 우리 종목 묶음 + 테마대장(전일 거래대금 1위)
    theme2codes = {}
    for c, ts in code2themes.items():
        for t in ts:
            theme2codes.setdefault(t, []).append(c)
    themes = []
    for t, cs in theme2codes.items():
        cs2 = sorted(cs, key=lambda c: -float(stocks[c].get("value_eok", 0)))
        h = heat.get(t, {})
        themes.append({"theme": t, "today": h.get("today", 0.0), "d5": h.get("d5", 0.0),
                       "total_n": h.get("n", 0), "ours": cs2, "leader": cs2[0]})
    themes.sort(key=lambda x: -x["today"])
    # 종목별 태그(자기가 대장인 테마 목록)
    stock_tags = {}
    for th in themes:
        for c in th["ours"]:
            e = stock_tags.setdefault(c, {"themes": [], "leader_of": []})
            e["themes"].append(th["theme"])
            if c == th["leader"] and len(th["ours"]) >= 2:
                e["leader_of"].append(th["theme"])

    out = {"date": board.get("date"), "generated": datetime.now().isoformat(timespec="seconds"),
           "themes": themes, "stocks": stock_tags}
    tmp = OUT_J.with_suffix(".json.tmp"); tmp.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, OUT_J)

    lines = [f"=== 테마 지도 (기준 {board.get('date')} · 생성 {datetime.now():%m/%d %H:%M}) ==="]
    lines.append(f"-- 뜨거운 테마 TOP{HOT_N} (당일 등락율순 · ★=우리 유니버스 내 거래대금 1위 대장) --")
    for th in themes[:HOT_N]:
        mem = " ".join(("★" if c == th["leader"] and len(th["ours"]) >= 2 else "") + stocks[c]["name"] for c in th["ours"][:5])
        lines.append(f"  [{th['today']:+5.1f}%·5일 {th['d5']:+6.1f}%] {th['theme']} ({len(th['ours'])}/{th['total_n']}종목): {mem}")
    lines.append("-- 복수테마 대장 종목 --")
    multi = sorted(((c, e) for c, e in stock_tags.items() if len(e["leader_of"]) >= 2),
                   key=lambda x: -len(x[1]["leader_of"]))
    for c, e in multi[:15]:
        lines.append(f"  {stocks[c]['name']}({c}): {len(e['leader_of'])}개 테마 대장 — {', '.join(e['leader_of'][:4])}")
    OUT_T.write_text("\n".join(lines) + "\n", encoding="utf-8")
    _log(f"테마지도 저장: 테마 {len(themes)}개 · 대장마킹 {sum(1 for e in stock_tags.values() if e['leader_of'])}종목")
    return out


if __name__ == "__main__":
    try:
        build()
    except Exception as ex:
        _log(f"[FATAL] {ex}"); import traceback; traceback.print_exc()
