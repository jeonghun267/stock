# -*- coding: utf-8 -*-
"""[2026-07-07 친구님 대개편] 돈맥 선별기 v2 — 거래대금·시총·주가 깔때기 + 4주체 방향/합의 순위 + 실시간 2층.
   ① 코스닥(코스피 제외) 거래대금상위(opt10032) → 거래대금 ≥ 50억 · 주가 ≥ 20,000원
   ② 시가총액 ≥ 1,000억 (opt10001·기존 시총 프로그램과 통일·일1회 롤테이션 캐시)
   ③ 매수/매도 방향(기관·외인·프로그램·개인) — opt10059 + opt90013
   ④ 매수합의(스마트 3주체 순매수 개수)로 1~OUT_TOPN등 순위 → data\돈흐름_선별판.json
   ★[실시간 2층] 수급(TR·종목당 ~1.3초)은 백그라운드 폴러가 쉬지 않고 갱신(들어오는 즉시 _SUP 반영) +
     등수 재계산·보드 저장은 빠른 루프(MF_LOOP_SEC·기본 5초·TR 0). 매초 갱신은 푸시(가격/체결강도)만 가능한 물리적 한계.
     프로세스는 MF_RUN_SEC(기본 55초) 돌고 종료 → 1분 태스크가 재기동(자동복구·단일락).
   철학: "각 주체 자금이 매수/매도 어느 쪽에 몰렸나 → 매수합의 많으면 등타기·매도합의/개미흡수면 회피."
   ★수퍼개미는 키움이 개인을 하나로만 줘서 개미와 분리 불가 → 개인 전체 방향으로만.
   선별기 = 읽기전용·주문0. 소비 = 돈맥/돌파/종가매수가 이 순위표를 후보로 사용.
   안전: broker/데이터 실패 = 빈 보드(fail·매매 안 함). 롤백: money_flow_board_v1.py.bak_pre_funnel_20260707.
"""
import os
import sys
import json
import time
import threading
from pathlib import Path
from datetime import datetime
sys.path.insert(0, r"C:\stock_bot\RUN")

MODE = os.environ.get("MF_BOARD_MODE", "SHADOW").strip().upper()   # 라벨(OFF면 미실행)

# ── 깔때기(유니버스) 조건 — 친구님 2026-07-07: 코스닥만·거래대금50억·시총1000억·주가2만 ──
MARKET_GB    = os.environ.get("MF_MARKET_GB", "101")            # opt10032 시장구분 101=코스닥(★코스피 제외)
VAL_MIN_EOK  = float(os.environ.get("MF_VAL_MIN_EOK", "50"))    # 거래대금 하한(억)
VAL_DIV      = float(os.environ.get("MF_VAL_DIV", "100"))       # opt10032 거래대금 → 억 변환(백만원=100). ★첫 라이브서 단위 검증
PRICE_MIN    = float(os.environ.get("MF_PRICE_MIN", "20000"))   # 주가 하한(원)
MCAP_MIN_EOK = float(os.environ.get("MF_MCAP_MIN_EOK", "1000")) # 시가총액 하한(억)·기존 시총프로그램(1000억)과 통일

# [7/13 밤 친구님 "잡주도 정배열 위주로 사고… 1만원 이상도 후순위로 넣으면 할 수 있는 종목이 많지 않을까"] ★잡주 개방 —
#   3분봉 43일×207종목 실측: 잡주(3천~1만원)를 넣으면 하루 14,243원 → 29,008원(2배).
#   ★단 시총 1000억을 그대로 두면 잡주 건당 -0.031%로 무의미 → 잡주만 500억으로 완화해야 +0.939%가 됨(친구님 승인 "500억").
#   ★잡주 1순위(친구님 최초안)는 기각 — 매수가 2배로 늘지만 늘어난 건 전부 손실이고 좋은 1만원↑까지 슬롯에서 밀어냄(-6,441원).
#     → 매수 우선순위는 현행 유지(시간→정배열→깊이). 잡주는 "슬롯 남을 때 줍는" 형태가 최적.
#   ★2천원까지 열면 40,396원으로 보이나 12건 중 상위 3건 빼면 -1.327% = 한 방 의존 → 하한 3천원.
#   롤백: setx MF_PRICE_MIN 10000  (잡주 경계/시총/대금/쿼터는 자동 무력화)
LOW_PX_EDGE   = float(os.environ.get("MF_LOW_PX_EDGE", "10000"))  # 잡주 경계(원) — 이 미만이 '잡주'
LOW_MCAP_EOK  = float(os.environ.get("MF_LOW_MCAP_EOK", "500"))   # ★잡주 시총 하한(억) — 1만원↑는 MCAP_MIN_EOK(1000) 그대로
LOW_VAL_EOK   = float(os.environ.get("MF_LOW_VAL_EOK", "30"))     # ★잡주 거래대금 하한(억) — 1만원↑는 VAL_MIN_EOK(50) 그대로
LOW_QUOTA     = int(os.environ.get("MF_LOW_QUOTA", "40"))         # ★정원(UNIV_TOPN) 중 잡주 보장석 — 없으면 거래대금 컷에 전멸
# ★[7/14 친구님 "선별기가 테마대장을 잘 뽑을 수 있는 조건이 만들어져 있나 확인 — 제대로 선별해야 돼"]
#   👑테마 주도주 보장석 — 테마주는 **초반에 거래대금이 아직 안 붙어도 폭발한다**(상한가 친 미래생명자원·
#   아이에이도 val_eok=0이었다). 정원 컷이 거래대금 순이라 그냥 두면 밀려난다(잡주 보장석과 같은 논리).
#   ★테마대장 전략(DOCS/테마대장_설계도.md)의 유니버스를 이 보장석이 만든다.
#   롤백: setx MF_CROWN_QUOTA 0  (=보장석 끔 = 옛 동작)
CROWN_QUOTA   = int(os.environ.get("MF_CROWN_QUOTA", "20"))       # ★정원 중 👑테마 주도주 보장석

def _mcap_min(px):
    """가격대별 시총 하한 — 잡주는 완화(500억)."""
    return LOW_MCAP_EOK if (px and px < LOW_PX_EDGE) else MCAP_MIN_EOK

def _val_min(px):
    """가격대별 거래대금 하한 — 잡주는 완화(30억)."""
    return LOW_VAL_EOK if (px and px < LOW_PX_EDGE) else VAL_MIN_EOK
UNIV_MAX     = int(os.environ.get("MF_UNIV_MAX", "700"))        # [친구님 700/200 깔때기] opt10032 거래대금상위 몇 종목까지 스캔(1차 컷·거래대금 순)
UNIV_TOPN    = int(os.environ.get("MF_UNIV_TOPN", "200"))       # [친구님 700/200 깔때기] 품질필터 후 거래대금 상위 몇 개만 정원으로 남길지(2차 컷·수급 폴링 대상)
PREV_TOPN    = int(os.environ.get("MF_PREV_TOPN", "700"))       # [친구님 보충풀] 전일 거래대금 상위 몇 개를 후보로 보충(opt10032가 실시간 ~200개만 줘서 700을 못 채움·0=끔)
OUT_TOPN     = int(os.environ.get("MF_OUT_TOPN", "60"))         # 최종 순위표 크기(1~60등·돈 몰림순)

# ── 방향/합의 ──
BUY_CONS  = int(os.environ.get("MF_BUY_CONSENSUS", "2"))            # 🟢 매수합의(스마트 3주체 중 순매수 개수) 최소
SELL_CONS = int(os.environ.get("MF_SELL_CONSENSUS", "2"))          # 🔴 매도합의(피한다) 최소
SUBJ_MIN  = float(os.environ.get("MF_SUBJ_MIN_EOK", "0")) * 100.0  # 주체 매수/매도 판정 최소 순매수(백만원)·0=순부호
BIG_MIN   = float(os.environ.get("MF_BIG_MIN_EOK", "10")) * 100.0  # 🟢 큰손합 최소(백만원)·노이즈 컷(기본 10억)
# [2026-07-08 친구님 "기관·외인은 서로 싸운다·이기는 쪽에 걸어라"] 2주체 매도합의는 매수가 이 금액 이상
#   우위면 무시(예 HPSP 기관-2·외인-6 vs 프로+136 = +128억 우위 → 던짐 아님). 대량던짐(-80억)·개미흡수는 별개 유지.
WINNER_MARGIN = float(os.environ.get("MF_WINNER_MARGIN_EOK", "10")) * 100.0  # 매수 우위 인정 기준(백만원·기본 10억)

# ── 실시간 2층 루프 ──
LOOP_SEC  = float(os.environ.get("MF_LOOP_SEC", "5"))              # 등수 재계산·보드 저장 주기(초·TR 0)
RUN_SEC   = float(os.environ.get("MF_RUN_SEC", "55"))             # 프로세스 수명(초)·이후 1분 태스크가 재기동


def _eod_close_quiet_window(now=None):
    """14:58~15:19에는 종가매수용 브로커 통로를 비워 둔다."""
    now = now or datetime.now()
    return (14, 58) <= (now.hour, now.minute) < (15, 20)

# ── TR 페이스/캐시 ──
MCAP_REFRESH_N = int(os.environ.get("MF_MCAP_REFRESH_N", "25"))    # 사이클당 시총 TR 신규조회 종목수(일1회면 됨)
CACHE_MAX_AGE  = float(os.environ.get("MF_CACHE_MAX_AGE", "3600"))  # 초. 수급이 이보다 오래되면 grade 제외. [700/200] 정원200·TR예산 600/h이면 한바퀴 ~40분 → 900이면 대부분 탈락해서 3600으로(보드에 ts 표시됨)
PACE           = float(os.environ.get("MF_PACE", "0.25"))          # TR 페이스(브로커 보호)

SNAP       = Path(r"C:\stock_bot\IPC\live_micro_snapshot.json")
NAMEC      = Path(r"C:\stock_bot\data\_code_name_cache.json")
US         = Path(r"C:\stock_bot\data\us_overnight.json")
KOSDAQ     = Path(r"C:\stock_bot\data\kosdaq_index.json")
OUT_JSON   = Path(r"C:\stock_bot\data\돈흐름_선별판.json")
OUT_TXT    = Path(r"C:\stock_bot\data\돈흐름_관찰.txt")
CACHE      = Path(r"C:\stock_bot\data\돈흐름_수급캐시.json")     # 수급 캐시(code→수급+ts)·워밍스타트/영속
CHE_STATE  = Path(r"C:\stock_bot\data\돈흐름_che_state.json")   # 저점반등 재진입용 che 저점(min)/표본(n)·당일저점(lo) 누적
MCAP_CACHE = Path(r"C:\stock_bot\data\돈맥_시총캐시.json")       # 시총 일1회 캐시(code→억)
PREV_POOL  = Path(r"C:\stock_bot\data\돈맥_전일상위풀.json")     # [보충풀] 전일 거래대금 상위 700(코스닥) 일1회 캐시(TR 0·CSV는 하루 1번만 읽음)

# ── 실시간 공유 상태(백그라운드 폴러 ↔ 빠른 루프·GIL 보호) ──
_SUP = {}            # 수급 캐시(code→{inst,frgn,prog,indiv,chg,ts})
_UNIV = ([], {})     # (codes, meta{code:{price,val_eok,cap}})
_STOP = False


def _num(x):
    try:
        return float(str(x).replace(",", "").replace("+", "").strip() or 0)
    except Exception:
        return 0.0


def _z(c):
    return str(c).lstrip("A").zfill(6)


def _regime():
    """급락장? → (ok, tag). 오버나잇 SOX/나스닥 or 코스닥 급락이면 위험."""
    try:
        u = json.loads(US.read_text(encoding="utf-8"))
        d = u.get("data", {}) or {}
        sox = (d.get("sox", {}) or {}).get("chg")
        nq = (d.get("nasdaq", {}) or {}).get("chg")
        if (sox is not None and sox <= -4) or (nq is not None and nq <= -4):
            return False, f"위험(SOX{sox}·NQ{nq})"
    except Exception:
        pass
    try:
        k = json.loads(KOSDAQ.read_text(encoding="utf-8"))
        if str(k.get("ts", ""))[:10] == datetime.now().strftime("%Y-%m-%d") and float(k.get("chg", 0)) <= -1.5:
            return False, f"코스닥{k.get('chg')}%"
    except Exception:
        pass
    return True, "정상"


def _fetch_mcap(bc, code):
    """시가총액(억) — opt10001(주식기본정보). 기존 시총 프로그램(eod_pickup_market_cap_v1)과 동일 TR·필드.
       실패/0 = None(보류·다음 사이클 재시도). 시가총액 단위 = 억원(키움 표준)."""
    try:
        res = bc.tr("opt10001", inputs={"종목코드": code}, output_fields=["종목명", "시가총액"],
                    rqname=f"mf_mcap_{code}", screen_no="0802", timeout_sec=5.0)
        rec = (((res or {}).get("data") or {}).get("records") or [{}])[0]
        v = _num(rec.get("시가총액"))
        return v if v > 0 else None
    except Exception:
        return None


def _prev_top_pool(today):
    """[친구님 보충풀] 전일 거래대금 상위 PREV_TOPN(코스닥) — eod_daily_bars.csv를 하루 1번만 읽어
       소형 JSON 캐시(돈맥_전일상위풀.json)로 영속(1분 재기동 대응·TR 0). 반환 [[code, 전일종가, 전일거래대금억], ...]."""
    try:
        if PREV_POOL.exists():
            d = json.loads(PREV_POOL.read_text(encoding="utf-8"))
            if d.get("date") == today and isinstance(d.get("rows"), list):
                return d["rows"]
    except Exception:
        pass
    rows = []
    try:
        import pandas as pd
        p = Path(r"C:\stock_bot\DATA\eod_daily_bars.csv")
        if p.exists() and p.stat().st_size > 0:
            df = pd.read_csv(p, dtype={"code": str}, encoding="utf-8-sig",
                             usecols=["date", "code", "market", "close", "value"])
            df = df[(df["date"] == df["date"].max()) & (df["market"] == "KOSDAQ")]
            df = df.sort_values("value", ascending=False).head(PREV_TOPN)
            for _, r in df.iterrows():
                c = _z(r.get("code"))
                if len(c) == 6:
                    rows.append([c, float(_num(r.get("close"))), float(_num(r.get("value")) / 100.0)])   # 백만원→억
    except Exception as e:
        print(f"[깔때기·보충] 전일풀 로드 실패(무시·보충 없이 진행): {e}")
        return rows
    try:
        t = PREV_POOL.with_suffix(".tmp"); t.write_text(json.dumps({"date": today, "rows": rows}, ensure_ascii=False), encoding="utf-8"); os.replace(t, PREV_POOL)
    except Exception:
        pass
    return rows


def _seed_from_yesterday(today):
    """[2026-07-08 친구님 '기관/외인 달고 날아가는 놈 1분 포착'] 09시 초반 수급 공백을 어제 확정
       큰손(외인+기관·investor_daily 오늘아침 수집분)으로 시드 — 실측 폴이 도착하면 자연히 덮임(TR 0).
       ts를 4분 전으로 찍어 폴러가 곧(60초 내) 실측으로 교체하게 함. 롤백: setx MF_MORNING_SEED NO."""
    if os.environ.get("MF_MORNING_SEED", "YES").strip().upper() != "YES":
        return
    try:
        import csv
        seeded = 0
        with open(r"C:\stock_bot\DATA\investor_daily.csv", encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                if str(row.get("date", "")) != today:
                    continue
                c = _z(row.get("code"))
                if len(c) != 6 or c in _SUP:
                    continue
                fn = _num(row.get("foreign_net")); it = _num(row.get("inst_net"))
                if fn == 0 and it == 0:
                    continue
                _SUP[c] = {"inst": it, "frgn": fn, "prog": None, "indiv": None, "chg": None,
                           "ts": time.time() - 240, "seed": 1}
                seeded += 1
        if seeded:
            print(f"[아침시드] 어제 확정 큰손(외인+기관) {seeded}종목 시드 — 실측 폴 도착시 교체")
    except Exception as e:
        print(f"[아침시드] 실패(무시·시드 없이 진행): {e}")


def _universe(bc):
    """[깔때기] 코스닥 거래대금상위 → 거래대금·주가·시총 필터 → (codes, meta).
       meta[code] = {"price", "val_eok", "cap", "crown"}. 시총은 일1회 롤테이션 캐시."""
    today = datetime.now().strftime("%Y%m%d")
    _CROWN = set()   # ★[7/14] 이 사이클의 👑테마 주도주 (정원 보장석 판정용)
    # ── 1) opt10032 코스닥 거래대금상위 → 거래대금/주가 컷 ──
    try:
        res = bc.tr("opt10032", inputs={"시장구분": MARKET_GB, "관리종목포함": "0"},
                    output_fields=["종목코드", "종목명", "현재가", "거래대금"], screen_no="9719", timeout_sec=10.0)
        recs = (((res or {}).get("data") or {}).get("records") or [])
    except Exception:
        recs = []
    cand = []   # (code, price, val_eok) — 거래대금 내림차순(opt10032 레코드 순서)
    _dbg = []
    for r in recs[:UNIV_MAX]:
        code = _z(r.get("종목코드"))
        if len(code) != 6:
            continue
        price = abs(_num(r.get("현재가")))
        val_eok = _num(r.get("거래대금")) / VAL_DIV
        if len(_dbg) < 3:
            _dbg.append((code, round(val_eok, 1), price))
        if price < PRICE_MIN or val_eok < _val_min(price):   # [7/13] 잡주는 대금 30억·1만원↑는 50억
            continue
        cand.append((code, price, val_eok))
    if _dbg:
        print(f"[깔때기] opt10032 코스닥 {len(recs)}건·상위샘플(거래대금억/주가): {_dbg} → 거래대금≥{VAL_MIN_EOK:.0f}억·주가≥{PRICE_MIN:.0f} 통과 {len(cand)}")

    # ── 1.5) [친구님 보충풀 2026-07-08] 전일 거래대금 상위 PREV_TOPN(코스닥)으로 후보 보충 — TR 0(CSV캐시).
    #    이유: opt10032는 실시간 ~200개만 줘서 1차컷 700을 못 채움 + 장초엔 당일 거래대금 미형성이라
    #    어제 돈 몰렸던 종목을 놓침. 전일 종가/거래대금으로 같은 필터 적용해 뒤에 붙임(실시간 통과분 우선).
    #    opt10032 전체 실패시엔 이 풀이 전량 대체(fail-open). 롤백: setx MF_PREV_TOPN 0.
    if PREV_TOPN > 0:
        _seen = {c for c, _, _ in cand}
        _sup_n = 0
        for c, _ppx, _pval in _prev_top_pool(today):
            if c in _seen or _ppx < PRICE_MIN or _pval < _val_min(_ppx):   # [7/13] 잡주 대금 30억
                continue
            cand.append((c, _ppx, _pval))
            _sup_n += 1
        if _sup_n:
            print(f"[깔때기·보충] 전일 거래대금 상위 {PREV_TOPN} 풀 +{_sup_n}종목 보충(실시간 {len(_seen)} 우선·TR 0)")

    # [7/10 장중 친구님 "0184·0168 활용 — 계속하자"] 거래량급증(opt10023) 입구 — 평소 조용하다 오늘 거래 터진 종목
    #   (펌텍코리아형: 전일풀·실시간 대금상위 둘 다 밖 → 깔때기 사각) 실시간 편입. 급증률 상위 중 주가≥PRICE_MIN만,
    #   거래대금은 현재가×현재거래량 근사(이후 시총 1000억 필터·정원 컷은 기존 그대로). 비용 1TR/사이클(~60/h).
    #   ※당일거래량상위(opt10030·화면0184)는 거래대금상위(opt10032)와 중복 커서 미배선(급증이 사각을 커버).
    #   롤백: setx MF_VOLSURGE_TOP 0
    _vs_top = int(os.environ.get("MF_VOLSURGE_TOP", "30"))
    if _vs_top > 0:
        try:
            _vr = bc.tr("opt10023", inputs={"시장구분": "101", "정렬구분": "2", "시간구분": "2",
                                            "거래량구분": "5", "시간": "", "종목조건": "0", "가격구분": "0"},
                        output_fields=["종목코드", "현재가", "현재거래량"], rqname="volsurge_in", screen_no="9790", timeout_sec=8.0)
            _seen2 = {c for c, _, _ in cand}
            _vn = 0
            for z in (((_vr or {}).get("data") or {}).get("records") or []):
                c = _z(str(z.get("종목코드", "")).lstrip("A"))
                _px = abs(_num(z.get("현재가")))
                if len(c) != 6 or c in _seen2 or _px < PRICE_MIN:
                    continue
                _vv = abs(_num(z.get("현재거래량"))) * _px / 1e8   # 억 근사
                cand.append((c, _px, _vv))
                _seen2.add(c); _vn += 1
                if _vn >= _vs_top:
                    break
            if _vn:
                print(f"[깔때기·급증] 거래량급증 +{_vn}종목 편입(opt10023·1TR·주가≥{PRICE_MIN:,.0f})")
        except Exception as _ve:
            print(f"[깔때기·급증] 실패(무시): {_ve}")

    # [7/13 밤 친구님 "왜 낙폭이 큰 걸 못 보는 거지? 이게 제일 중요해"] ★하락률 상위 입구 —
    #   🚨우리 유니버스는 '거래대금 상위'(opt10032)로만 뽑혀서 정작 노리는 급락 종목을 못 봤다.
    #     급락주는 팔려는 사람만 있고 사려는 사람이 없어 거래대금이 안 붙는다 → 상위 200위 밖으로 밀림.
    #   ★7/13 실측: 코스닥 낙폭 -4% 이하 200종목 중 우리가 본 건 26종목(13%)뿐. 174종목(87%)을 놓쳤다.
    #     그중 33종목은 주가 1만↑인데도 못 봤다(=거래대금 상위 밖). 주가 하한만 낮춰선 해결 안 됨.
    #   → opt10027(전일대비등락률상위·정렬구분3=하락률)로 코스닥 하락률 상위를 직접 편입.
    #   거래대금은 현재가×현재거래량 근사(급증 입구와 동일). 이후 시총 1000억·대금 50억·주가 하한·
    #   정원 200 컷은 기존 그대로 적용 = 품질필터 유지. 급락했다고 무조건 사는 게 아니라 '볼 기회'를 주는 것.
    #   비용 1TR/사이클(~60/h). 롤백: setx MF_DOWN_TOP 0
    _dn_top = int(os.environ.get("MF_DOWN_TOP", "50"))
    if _dn_top > 0:
        try:
            _dr = bc.tr("opt10027", inputs={"시장구분": MARKET_GB, "정렬구분": "3", "거래량조건": "0000",
                                            "종목조건": "0", "신용조건": "0", "가격조건": "0", "상하한포함": "1"},
                        output_fields=["종목코드", "현재가", "등락률", "현재거래량"],
                        rqname="down_in", screen_no="9793", timeout_sec=8.0)
            _seen3 = {c for c, _, _ in cand}
            _dn = 0
            for z in (((_dr or {}).get("data") or {}).get("records") or []):
                c = _z(str(z.get("종목코드", "")).lstrip("A"))
                _px = abs(_num(z.get("현재가")))
                if len(c) != 6 or c in _seen3 or _px < PRICE_MIN:
                    continue
                _dv = abs(_num(z.get("현재거래량"))) * _px / 1e8   # 억 근사(거래대금 필터는 아래 kept 루프서 안 씀 → 여기선 참고값)
                cand.append((c, _px, _dv))
                _seen3.add(c); _dn += 1
                if _dn >= _dn_top:
                    break
            if _dn:
                print(f"[깔때기·급락] 하락률상위 +{_dn}종목 편입(opt10027·1TR·주가≥{PRICE_MIN:,.0f})")
        except Exception as _de:
            print(f"[깔때기·급락] 실패(무시): {_de}")

    # [7/13 밤 친구님 "등락률상위하고 테마대장주 거래대금상위 종목들로 했으면 좋겠어"] ★테마 주도주 입구 —
    #   👑테마 주도주(data\테마주도주.json·theme_leader_shadow가 3분마다 갱신)는 지금까지 **배지·정렬가점으로만**
    #   쓰였다(L597). 즉 그 종목이 거래대금 상위 밖이면 애초에 유니버스에 없어 배지도 못 달았다.
    #   → 유니버스 입구로 승격. TR 0(파일 읽기). 시총·주가·정원 컷은 아래 기존 필터 그대로 적용.
    #   롤백: setx MF_CROWN_IN 0
    _cr_top = int(os.environ.get("MF_CROWN_IN", "30"))
    if _cr_top > 0:
        try:
            import theme_leader as _TL
            _lead = _TL.get_leaders() or {}      # {code: info} — 당일 테마 주도주(쌍끌이/대금2등)
            # 🚨★[7/14 친구님 "선별기가 테마대장을 잘 뽑을 수 있는 조건이 만들어져 있나 확인"] 버그 수정 —
            #   테마 주도주 43종목 중 **27종목(63%)이 val_eok=0**으로 온다(신호 시점에 대금 미집계).
            #   거래대금 0 → **정원 200 컷(거래대금 순)에서 맨 뒤로 밀려 전멸**.
            #   실측 7/14: 👑 43종목 중 유니버스 진입 **6종목**뿐 · 로그엔 "+1종목 편입"만 찍혔다.
            #   (상한가 친 미래생명자원·아이에이도 val_eok=0이라 탈락)
            #   → ★실시간 스냅샷(1,488종목·TR 0)의 누적거래량 × 현재가로 직접 계산해 채운다.
            try:
                _sn = json.loads(SNAP.read_text(encoding="utf-8-sig")).get("codes", {})
            except Exception:
                _sn = {}
            _seen4 = {c for c, _, _ in cand}
            _cn = 0; _fix = 0
            for c, _s in _lead.items():
                c = _z(str(c))
                if len(c) != 6:
                    continue
                _CROWN.add(c)                      # ★정원 보장석 판정용(이미 든 종목도 표시)
                if c in _seen4:
                    continue
                _px = abs(_num((_s or {}).get("entry")))
                _sc = _sn.get(c) or {}
                _cp = abs(_num(_sc.get("cur")))
                if _cp > 0:
                    _px = _cp                      # 현재가 우선(신호가는 과거값)
                if _px < PRICE_MIN:
                    continue
                _vv = abs(_num((_s or {}).get("val_eok")))
                if _vv <= 0 and _cp > 0:           # ★대금 0 → 실시간으로 계산
                    _cv = abs(_num(_sc.get("cum_vol")))
                    if _cv > 0:
                        _vv = _cv * _cp / 1e8
                        _fix += 1
                cand.append((c, _px, _vv))
                _seen4.add(c); _cn += 1
                if _cn >= _cr_top:
                    break
            if _cn:
                print(f"[깔때기·주도주] 👑테마 주도주 +{_cn}종목 편입"
                      f"(TR0·주가≥{PRICE_MIN:,.0f}·대금 실시간복원 {_fix}건)")
        except Exception as _ce:
            print(f"[깔때기·주도주] 실패(무시): {_ce}")

    # ── 2) 시총 ≥ MCAP_MIN 필터 (일1회 롤테이션 캐시) ──
    try:
        mc = json.loads(MCAP_CACHE.read_text(encoding="utf-8")) if MCAP_CACHE.exists() else {}
    except Exception:
        mc = {}
    if mc.get("date") != today:
        mc = {"date": today, "caps": {}}
    caps = mc.get("caps", {})
    fetched = 0
    kept, meta = [], {}
    for code, price, val_eok in cand:   # noqa: E501
        cap = caps.get(code)
        if cap is None and fetched < MCAP_REFRESH_N:
            cap = _fetch_mcap(bc, code)
            fetched += 1
            if cap is not None:
                caps[code] = cap
            time.sleep(PACE)
        if cap is None:              # 시총 미상 = 이번 사이클 보류(다음에 채워짐)
            continue
        if cap < _mcap_min(price):   # [7/13] 시총 미달 = 제외 — ★잡주는 500억·1만원↑는 1000억
            continue
        kept.append(code)
        meta[code] = {"price": price, "val_eok": val_eok, "cap": cap,
                      "crown": code in _CROWN}   # ★[7/14] 👑 보장석 판정용
    mc["caps"] = caps
    try:
        _t = MCAP_CACHE.with_suffix(".tmp"); _t.write_text(json.dumps(mc, ensure_ascii=False), encoding="utf-8"); os.replace(_t, MCAP_CACHE)
    except Exception:
        pass
    # ── 3) [친구님 700/200 깔때기·2차 컷] 품질통과분 → 거래대금 상위 UNIV_TOPN(기본 200)만 정원으로.
    #    수급(opt10059+opt90013) 폴링 대상이 이 정원 = TR 부하 상한. cand는 이미 거래대금 내림차순이라 순서 유지.
    #    ★[7/13] 잡주 보장석 — 정원 컷이 '거래대금 순'이라 잡주(대금 작음)는 그냥 두면 전멸한다.
    #    1만원↑는 상위 (정원-쿼터)개, 잡주는 상위 쿼터개를 각각 거래대금 순으로 확보.
    if len(kept) > UNIV_TOPN:
        if LOW_QUOTA > 0 or CROWN_QUOTA > 0:
            # ★[7/14] 👑 보장석 — 테마 주도주는 초반에 거래대금이 아직 안 붙어도 폭발한다.
            #   정원 컷이 '거래대금 순'이라 그냥 두면 밀려난다(잡주 보장석과 같은 논리).
            #   테마대장 전략의 유니버스 = 이 보장석이 만든다.
            _crown = sorted([c for c in kept if meta[c].get("crown")],
                            key=lambda c: meta[c]["val_eok"], reverse=True)[:CROWN_QUOTA]
            _cset = set(_crown)
            _rest = [c for c in kept if c not in _cset]
            _hi = sorted([c for c in _rest if meta[c]["price"] >= LOW_PX_EDGE],
                         key=lambda c: meta[c]["val_eok"], reverse=True)
            _lo = sorted([c for c in _rest if meta[c]["price"] < LOW_PX_EDGE],
                         key=lambda c: meta[c]["val_eok"], reverse=True)
            _q = min(LOW_QUOTA, len(_lo))
            _nhi = max(0, UNIV_TOPN - _q - len(_crown))
            kept = _crown + _hi[:_nhi] + _lo[:_q]
            print(f"[깔때기·2차] 품질통과 → 정원 {UNIV_TOPN} 컷 "
                  f"(👑주도주 보장석 {len(_crown)} + 1만원↑ {_nhi} + 잡주 보장석 {_q}) → {len(kept)}종목")
        else:
            kept = sorted(kept, key=lambda c: meta[c]["val_eok"], reverse=True)[:UNIV_TOPN]
            print(f"[깔때기·2차] 품질통과 → 거래대금 상위 {UNIV_TOPN} 정원 컷 → {len(kept)}종목")
        meta = {c: meta[c] for c in kept}
    return kept, meta


def _grade(big, regime_ok, dump):
    """[2026-07-07 친구님 재정의] ★등수는 순매수 우위 금액(큰손합)순 — 라벨은 색 표시용.
       🔴던짐 = 개미흡수/외인·프로 대량던짐(순매수 양수여도 함정·매수금지 경고).
       🟢매수세 = 순매수 우위 ≥ BIG_MIN & 레짐OK / 🟡=레짐위험 / 🔵매도세 = 순매도 우위 / ⚪중립.
       체결강도·등락률은 등급에서 제외(참고표시만) — 청산(vol_exit)에서만 사용."""
    if dump:
        return "🔴던짐"
    if big >= BIG_MIN:
        return "🟢매수세" if regime_ok else "🟡매수세(레짐위험)"
    if big <= -BIG_MIN:
        return "🔵매도세"
    return "⚪중립"


def _poll_one(bc, code, today):
    """수급 1종목 실측(opt10059 기관/외인/개인 + opt90013 프로그램) → _SUP 갱신.
    [7/11 🤝동반매집] 같은 TR 응답에 일별 이력이 통째로 오므로(TR 추가 0) 전일까지 10일을 롤업해
    외인&프로그램 동반 10일 매집 배지(acc10)를 계산. 백테(키움직접 217종목×100일·19,063표본):
    기준 익일 -0.49%/도달 42.6% → 조건 충족 +0.55%/58.3%·월별 전부 플러스. 끄기: setx MF_ACCUM10_BADGE NO"""
    inst = frgn = indiv = chg = prog = None
    f10 = []; p10 = []   # 전일까지 10일 시리즈(최신→과거·백만원)
    try:
        r = bc.tr("opt10059", inputs={"일자": today, "종목코드": code, "금액수량구분": "1", "매매구분": "0", "단위구분": "1"},
                  output_fields=["일자", "기관계", "외국인투자자", "개인투자자", "등락율"], timeout_sec=5.0, screen_no="9742")
        recs = (((r or {}).get("data") or {}).get("records") or [{}])
        rec = recs[0]
        if str(rec.get("기관계", "")).strip():
            inst = _num(rec.get("기관계")); frgn = _num(rec.get("외국인투자자"))
            indiv = _num(rec.get("개인투자자")); chg = _num(rec.get("등락율"))
        for _r in recs:
            _d = str(_r.get("일자", "")).strip().replace("-", "")
            if len(_d) == 8 and _d.isdigit() and _d < today:
                f10.append(_num(_r.get("외국인투자자")))
                if len(f10) >= 10:
                    break
    except Exception:
        pass
    try:
        r = bc.tr("opt90013", inputs={"시간일자구분": "1", "금액수량구분": "1", "종목코드": code},
                  output_fields=["일자", "프로그램순매수금액"], timeout_sec=5.0, screen_no="9743")
        for d in (((r or {}).get("data") or {}).get("records") or []):
            _d = str(d.get("일자", "")).strip().replace("-", "")
            if _d == today and prog is None:
                prog = _num(d.get("프로그램순매수금액"))
            elif len(_d) == 8 and _d.isdigit() and _d < today and len(p10) < 10:
                p10.append(_num(d.get("프로그램순매수금액")))
    except Exception:
        pass
    # [7/11 🤝] 외인&프로그램 동반 10일 매집 판정 — 둘 다 (누적>0 & 매수일>=7 & 최근3일>=0) & 합산 누적 >= 180억.
    #   프로그램 이력 없는 종목(대상 아님)은 자동 False(fail-open). 문턱: setx MF_ACCUM10_MIN_EOK (0=크기조건 끔).
    acc10 = False
    try:
        if (os.environ.get("MF_ACCUM10_BADGE", "YES").strip().upper() == "YES"
                and len(f10) >= 10 and len(p10) >= 10):
            _fs = sum(f10); _ps = sum(p10)
            _min = float(os.environ.get("MF_ACCUM10_MIN_EOK", "180")) * 100.0   # 억 → 백만원
            acc10 = (_fs > 0 and sum(1 for v in f10 if v > 0) >= 7 and sum(f10[:3]) >= 0
                     and _ps > 0 and sum(1 for v in p10 if v > 0) >= 7 and sum(p10[:3]) >= 0
                     and (_fs + _ps) >= _min)
    except Exception:
        acc10 = False
    if inst is not None or prog is not None:
        _SUP[code] = {"inst": inst, "frgn": frgn, "prog": prog, "indiv": indiv, "chg": chg,
                      "acc10": acc10, "ts": time.time()}


def _supply_poller(bc, today):
    """[백그라운드] 유니버스에서 가장 오래된 수급부터 갱신(_SUP). 유일한 TR 스레드.
       ★브로커 보호: 가장 오래된 것도 REPOLL_SEC(기본 60초)보다 신선하면 쉼(=유니버스 ~1분 주기 한 바퀴·과부하 방지).
       오늘(7/7) 브로커가 TR 과부하로 2번 사망 → 연속 폴링 상한 필수."""
    repoll = float(os.environ.get("MF_REPOLL_SEC", "300"))   # [700/200 깔때기] 정원 200까지 늘 수 있어 60→300s(수급은 3~5분 갱신이면 충분·설계도). TR 부하 상한.
    # ★[TR예산 2026-07-08] 정원 200이면 repoll만으론 시간당 ~4,800TR(끊김 재발 수준) → 시간당 예산으로 직접 상한.
    #   기본 600TR/h(어제 실측 수급 1,200/h의 절반) = 종목폴(2TR) 간 최소 12초 → 200종목 한바퀴 ~40분.
    #   수급은 원래 느리게 움직여서 충분·실시간(가격/체결강도)은 푸시(TR 0)가 담당. 롤백/조정: setx MF_POLL_BUDGET_TRH.
    budget_trh = float(os.environ.get("MF_POLL_BUDGET_TRH", "600"))
    min_gap = 7200.0 / max(budget_trh, 60.0)                 # 종목폴 1회=2TR → 간격(초)=2*3600/예산
    while not _STOP:
        if _eod_close_quiet_window():
            return
        _t0 = time.time()
        try:
            codes = list(_UNIV[0])
            if not codes:
                time.sleep(1.0); continue
            now = time.time()
            _age = lambda c: now - float((_SUP.get(c) or {}).get("ts", 0) or 0)
            # [7/10 장중 친구님 "선별기 최대한 빠르게 — 전략들이 큰 깔때기 안에서 수시로 체크"] 2층 폴링 —
            #   우선층 = 큰손합 상위 MF_PRIO_TOP(30) + 깊은바닥 등재 종목 → PRIO_REPOLL(90s) 목표로 먼저 폴링.
            #   나머지는 기존 repoll(300s). 예산(MF_POLL_BUDGET_TRH) 안에서 배분만 우선층 위주로 바꿈.
            #   기아현상 방지: 3폴 중 1폴은 일반층 최장 대기부터. 롤백: setx MF_PRIO_TOP 0 (구동작=oldest-first).
            _ptop = int(os.environ.get("MF_PRIO_TOP", "30"))
            _prepoll = float(os.environ.get("MF_PRIO_REPOLL_SEC", "90"))
            code = None
            if _ptop > 0:
                def _bigv(c):
                    s = _SUP.get(c) or {}
                    return sum(v for v in (s.get("inst"), s.get("frgn"), s.get("prog")) if v is not None)
                _prio = set(sorted((c for c in codes if _SUP.get(c)), key=lambda c: -_bigv(c))[:_ptop])
                try:
                    _prio |= (set((_DEEPM.get("m") or {}).keys()) & set(codes))
                except Exception:
                    pass
                _gen_turn = (int(now) % 3 == 0)   # 1/3 확률로 일반층 차례(기아 방지)
                if _prio and not _gen_turn:
                    _pc = max(_prio, key=_age)
                    if _age(_pc) >= _prepoll:
                        code = _pc
            if code is None:
                code = max(codes, key=_age)
                if _age(code) < repoll:   # 가장 오래된 것도 충분히 신선 → 쉬어서 브로커 보호
                    time.sleep(min(2.0, repoll - _age(code))); continue
            _poll_one(bc, code, today)
        except Exception:
            pass
        time.sleep(max(PACE, min_gap - (time.time() - _t0)))


def _update_che_state(snap, che_state, today, hmn):
    """che 저점(min)·당일저점(lo) 누적 — 매매기 저점반등/구조붕괴용(바닥사냥꾼 방식)·09:10 이후·일단위 리셋."""
    # DEEP은 선별판 밖 급락주도 관찰하므로 snapshot 전체의 상태를 누적한다.
    # 선별판 _UNIV는 순위/메타데이터 용도로만 유지한다.
    for code, sc in snap.items():
        code = str(code).zfill(6)
        if not isinstance(sc, dict):
            continue
        _cs = che_state.get(code) if isinstance(che_state.get(code), dict) else {}
        _px = sc.get("cur")
        if isinstance(_px, (int, float)) and _px > 0:
            # [7/12 친구님 "슬금슬금 피해야지·갭하락은 무조건 잡고"] 저점 갱신시각(lo_ts)=매매기 하락속도 판정용 ·
            #   시가근사(o)=09:05 이전 첫 관측가(갭하락 면제 판정용·보드 지각 기동시 미기록=면제 아님 fail-safe)
            if _cs.get("lo") is None or float(_px) < float(_cs["lo"]):
                _cs["lo"] = float(_px); _cs["lo_ts"] = hmn
            if _cs.get("o") is None and hmn <= "0905":
                _cs["o"] = float(_px)
        _c = sc.get("che_str")
        if isinstance(_c, (int, float)):
            _cs["last"] = _c
            if hmn >= "0910":
                _cs["min"] = _c if _cs.get("min") is None else min(float(_cs["min"]), _c)
                _cs["n"] = int(_cs.get("n", 0)) + 1
        che_state[code] = _cs
    try:
        _ct = CHE_STATE.with_suffix(".tmp"); _ct.write_text(json.dumps(che_state, ensure_ascii=False), encoding="utf-8"); os.replace(_ct, CHE_STATE)
    except Exception:
        pass


def _char_map():
    """[참고표기] 변동성(일중변동폭%)·우상향(추세점수) — daily_leader_board.json에서 읽기만(TR 0·계산 이미 됨).
       프로세스 캐시(1분 프로세스마다 1회·순위표는 장전 고정). 없으면 빈 맵(참고칸만 '-')."""
    if getattr(_char_map, "_c", None) is not None:
        return _char_map._c
    m = {}
    try:
        b = json.loads(Path(r"C:\stock_bot\data\daily_leader_board.json").read_text(encoding="utf-8"))
        for r in b.get("board", []):
            m[str(r.get("code", "")).zfill(6)] = (r.get("range_pct"), r.get("trend_score"))
    except Exception:
        pass
    _char_map._c = m
    return m


def _trend45_map():
    """[2026-07-09 밤 친구님 "①일봉 정배열45도 ②주봉5주선위 — 선별기에 넣어"] 추세배지 📐 — ★표시전용(주문·순위 무영향).
    조건 = A 일봉 정배열 45도(5>20>60 & 세 선 모두 5일전 대비 +1%↑) AND B 전일종가 > 주봉(진행주 포함) 5주 종가평균.
    근거(1년 백테·선별기 유니버스): 장중 고가+3% 도달 43→50%·시가→고가 +3.85→+4.55%(꾸준한 가점·차단 근거는 부족 → 배지만).
    ③골든크로스 압축조정은 기각(하루 0.7건·최근 60일 -1.19%). eod_daily_bars로 일1회 계산·파일캐시(TR 0)·이평은 5/20/60만.
    끄기: setx MF_TREND_BADGE NO. 며칠 실측 대조 후 정렬 가점 반영 여부는 친구님 결정."""
    if os.environ.get("MF_TREND_BADGE", "YES").strip().upper() != "YES":
        return {}
    today = datetime.now().strftime("%Y%m%d")
    if getattr(_trend45_map, "_d", None) == today:
        return _trend45_map._c
    cache = Path(r"C:\stock_bot\data\돈맥_추세배지.json")
    try:
        if cache.exists():
            d = json.loads(cache.read_text(encoding="utf-8"))
            if d.get("date") == today:
                _trend45_map._c = {str(k).zfill(6): 1 for k in d.get("codes", [])}
                _trend45_map._d = today
                return _trend45_map._c
    except Exception:
        pass
    m = {}; asof = ""
    try:
        import csv as _csv, io as _io, datetime as _dt
        closes = {}
        with _io.open(r"C:\stock_bot\data\eod_daily_bars.csv", encoding="utf-8-sig", newline="") as f:
            for r in _csv.DictReader(f):
                if r.get("market") != "KOSDAQ":
                    continue
                try:
                    closes.setdefault(str(r["code"]).zfill(6), []).append((r["date"], float(r["close"])))
                except Exception:
                    pass
        for c, lst in closes.items():
            lst.sort()
            if len(lst) < 65:
                continue
            cl = [x[1] for x in lst]
            m5 = sum(cl[-5:]) / 5; m20 = sum(cl[-20:]) / 20; m60 = sum(cl[-60:]) / 60
            m5p = sum(cl[-10:-5]) / 5; m20p = sum(cl[-25:-5]) / 20; m60p = sum(cl[-65:-5]) / 60
            if not (m5 > m20 > m60 and m5 >= m5p * 1.01 and m20 >= m20p * 1.01 and m60 >= m60p * 1.01):
                continue
            wk = {}
            for dd, cc in lst:            # 주봉 종가 = 그 주 마지막 일봉 종가(진행주 포함)
                iso = _dt.date(int(dd[:4]), int(dd[4:6]), int(dd[6:8])).isocalendar()
                wk[(iso[0], iso[1])] = cc
            wcl = [wk[k] for k in sorted(wk)][-5:]
            if len(wcl) == 5 and cl[-1] > sum(wcl) / 5:
                m[c] = 1
                if lst[-1][0] > asof:
                    asof = lst[-1][0]
        cache.write_text(json.dumps({"date": today, "asof": asof, "codes": sorted(m)}, ensure_ascii=False), encoding="utf-8")
    except Exception:
        m = {}
    _trend45_map._c = m; _trend45_map._d = today
    return m


def _gcross_map():
    """[2026-07-11 밤 친구님 "A안 고"] 골든크로스 배지 📈 — 최신 일봉에서 5/20 골든크로스 완성 + 우상향 + 거래량.
    조건 = A 최신일 5일선>20일선 & 직전일 5일선<=20일선(당일 크로스 완성) AND B 60일선이 5일 전보다 상승(우상향)
         AND C 최신일 거래량 >= 직전 20일 평균 x1.5(MF_GC_VOLX·거래량 안 실리면 가짜 — 검증에서 중앙값 마이너스).
    근거(7/11 키움직접 291종목×120일): 이 조합 크로스일 종가 진입 +1일 +1.46%·플러스 55.7% / +5일 +4.21%(기준선 +0.27%/+1.30%).
    진입지연 검증 = 수익이 크로스 직후 몰림(2일째부터 중앙값 마이너스) → ★최신 일봉의 크로스만 배지(묵은 크로스 제외).
    eod_daily_bars는 전일까지라 배지=전일 완성 크로스 → 아침 진입은 크로스 익일(검증 L=1: +5일 +3.06%·여전히 기준선 2.3배).
    stale 방어 = 종목 최신일이 파일 전체 최신일과 같아야 함. 일1회 계산·파일캐시(TR 0)·이평은 5/20/60만.
    끄기: setx MF_GC_BADGE NO (정렬가점은 MF_GC_SORT). 롤백: money_flow_board_v1.py.bak_gcbadge_20260711"""
    if os.environ.get("MF_GC_BADGE", "YES").strip().upper() != "YES":
        return {}
    today = datetime.now().strftime("%Y%m%d")
    if getattr(_gcross_map, "_d", None) == today:
        return _gcross_map._c
    cache = Path(r"C:\stock_bot\data\돈맥_골든크로스배지.json")
    try:
        if cache.exists():
            d = json.loads(cache.read_text(encoding="utf-8"))
            if d.get("date") == today:
                _gcross_map._c = {str(k).zfill(6): 1 for k in d.get("codes", [])}
                _gcross_map._d = today
                return _gcross_map._c
    except Exception:
        pass
    m = {}; asof = ""
    try:
        import csv as _csv, io as _io
        volx_min = float(os.environ.get("MF_GC_VOLX", "1.5"))
        bars = {}
        with _io.open(r"C:\stock_bot\data\eod_daily_bars.csv", encoding="utf-8-sig", newline="") as f:
            for r in _csv.DictReader(f):
                if r.get("market") != "KOSDAQ":
                    continue
                try:
                    bars.setdefault(str(r["code"]).zfill(6), []).append(
                        (r["date"], float(r["close"]), float(r["volume"] or 0)))
                except Exception:
                    pass
        maxd = max((lst[-1][0] for lst in bars.values() if lst), default="")
        for c, lst in bars.items():
            lst.sort()
            if len(lst) < 66 or lst[-1][0] != maxd:   # stale 종목의 묵은 크로스 차단
                continue
            cl = [x[1] for x in lst]; vv = [x[2] for x in lst]
            m5 = sum(cl[-5:]) / 5; m20 = sum(cl[-20:]) / 20
            m5p = sum(cl[-6:-1]) / 5; m20p = sum(cl[-21:-1]) / 20
            if not (m5 > m20 and m5p <= m20p):        # 최신일에 5/20 크로스 완성
                continue
            m60 = sum(cl[-60:]) / 60; m60p = sum(cl[-65:-5]) / 60
            if m60 <= m60p:                            # 우상향(60일선 상승)
                continue
            v20 = sum(vv[-21:-1]) / 20
            if v20 <= 0 or vv[-1] < v20 * volx_min:    # 거래량 실림
                continue
            m[c] = 1
            asof = maxd
        cache.write_text(json.dumps({"date": today, "asof": asof, "codes": sorted(m)}, ensure_ascii=False), encoding="utf-8")
    except Exception:
        m = {}
    _gcross_map._c = m; _gcross_map._d = today
    return m


def _crown_map():
    """[2026-07-12 친구님 "선별기에 넣어서 전략들이 공동으로 사용"] 👑 테마 주도주 배지 —
    theme_leader_shadow(3분 태스크)가 갱신하는 data\테마주도주.json을 theme_leader 헬퍼로 읽음(TR 0).
    신호 = 달리는 테마의 등락률 1등 & 대금 1~2등(쌍끌이/대금2등·7/11 밤 백테 근거·그림자 실측 병행중).
    신선도 30분 넘으면 표시 안 함. 끄기: setx MF_LEADER_BADGE NO (정렬은 MF_LEADER_SORT).
    롤백: money_flow_board_v1.py.bak_crownbadge_20260712"""
    if os.environ.get("MF_LEADER_BADGE", "YES").strip().upper() != "YES":
        return {}
    try:
        import theme_leader as TL
        return TL.get_leaders(max_age_min=30)
    except Exception:
        return {}


_MW = {"ts": 0.0, "n": 0}
def _publish_micro_watch(snap):
    """★[7/12 친구님 "매도 폭탄이 서서히 줄다가 바닥이 되고 매수세가 우위가 된다"] 급락 종목 실시간 호가 구독 발행.
    문제: 브로커 실시간 마이크로 구독은 CAP 120(broker_gateway `_read_micro_watch`)이고, 우선순위 1번이던
      `micro_watch_reversal.json`은 7/11 반전엔진 잠금으로 사라짐 + 돈맥은 micro_watch를 발행한 적이 없음
      → 120자리를 strategy(100)·premarket(66)·죽은 엔진 파일들이 차지 → **정작 우리가 사는 급락 종목의
      호가잔량(매도총잔량/매수총잔량)이 46~65% 결측**(7/06 23% → 7/10 65%). 눈 감고 사는 상태였음.
    처방: 하락 중(전일종가比 MF_MICRO_WATCH_DROP 이하) 종목을 낙폭 큰 순으로 N개 발행 →
      broker PRIOR 1번으로 등록 → 저점 형성 '이전부터' 매도잔량 소진 과정을 관측 가능.
    ★등재(-4%) 뒤가 아니라 -2%부터 미리 구독해야 '매도 소진 → 바닥' 전환을 볼 수 있다.
    TR 0(스냅 파일만 읽음)·30초 캐시. 끄기: setx MF_MICRO_WATCH NO"""
    if os.environ.get("MF_MICRO_WATCH", "YES").strip().upper() != "YES":
        return
    now = time.time()
    if now - _MW["ts"] < 30:
        return
    _MW["ts"] = now
    try:
        pcm = {c: px for c, px, _v in _prev_top_pool(datetime.now().strftime("%Y%m%d"))}
        thr = float(os.environ.get("MF_MICRO_WATCH_DROP", "-2.0"))
        rows = []
        for code in _UNIV[0]:
            pc = float(pcm.get(code, 0) or 0)
            cur = float(((snap.get(code) or {}).get("cur")) or 0)
            if pc <= 0 or cur <= 0:
                continue
            chg = (cur / pc - 1) * 100
            if chg <= thr:
                rows.append((chg, code))
        rows.sort()                                   # 많이 빠진 순
        ordered = [c for _, c in rows]
        seen = set(ordered)
        ordered.extend(c for c in _UNIV[0] if c not in seen)
        codes = ordered[:int(os.environ.get("MF_MICRO_WATCH_N", "200"))]
        if not codes:
            return
        p = Path(r"C:\stock_bot\IPC\micro_watch_moneyflow.json")
        t = p.with_suffix(".tmp")
        t.write_text(json.dumps({"codes": codes, "ts": datetime.now().isoformat()}, ensure_ascii=False),
                     encoding="utf-8")
        os.replace(t, p)
        _MW["n"] = len(codes)
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════════════════════════
# ★[2026-07-14 밤] 🔥 아침 대장 (Morning Captain) — 선별기가 뽑아서 전략들이 공용으로 쓴다
#
# 친구님: "아침 9시 땡 하면 30분 안에 사서 팔고 끝낸다. 하루 종일 대장 말고 아침 대장을 뽑는다."
#         "선별기에 안 들어가니? 모든 걸 여기 넣고 여기서 선별하면 되지 않니?"
#
# ★대장 = 시가 대비 +10% 이상 오르는 놈 (하루 1.9~2.3마리 · 기준 대장률 4.6%)
# ★조건 (09:03 판정 · 246일 백테 + 키움 TR 실측으로 확정)
#     ① 시가 대비 +4%↑     대장률 47%  (10.2배)  ← 압도적 1위 지표
#     ② 고가 갱신율 35%↑    대장 46.8% vs 비대장 23.3%  (되돌림 없이 계속 밀어올린다)
#     ③ 양봉 비율 60%↑     대장 59.3% vs 비대장 35.6%  (봉마다 매수가 이긴다)
#     ④ 누적 대금 50억↑     20~50억 구간은 승률 18%로 전체를 까먹음 → 50억이 커트라인
#     ⑤ 분당 대금 1억↑      1,000만원 주문 = 분당대금의 10% 이하 → 슬리피지 왕복 0.28%
#     ⑥ 시총 1,000억~2조    잡주(아이에이 301억) 배제 + 대형주 상한
#   → 조합 대장률 67.7% (14.7배)
#
# ★기각된 것 (넣지 말 것): 대금 가속도/폭증배수(대장 1.67 vs 비대장 1.67 = 차이 0) ·
#   테마주 여부(94.3% vs 94.1% = 차이 0) · 시가갭 · 위/아래꼬리 · 어제 지표 전부
#
# ★정렬: 시가 대비 상승률 순 (1등이 100% 대장 · 2등 90%)
# 설계도: DOCS/테마대장_설계도.md
# 끄기: setx MF_CAPTAIN NO
# ═══════════════════════════════════════════════════════════════════════════════════
BARS1 = Path(r"C:\stock_bot\data\돈맥_1분봉.json")   # deep_bottom_signal_recorder가 공급(o,h,l,c,v,pv,op,prev)

CAP_ON        = os.environ.get("MF_CAPTAIN", "YES").strip().upper() == "YES"
CAP_START     = os.environ.get("MF_CAP_START", "0902")     # 판정 시작(봉 3개 확보)
CAP_END       = os.environ.get("MF_CAP_END", "0906")       # 판정 종료(09:03 최적·여유 3분)
# ★[7/15 장중] 친구님 "4%가 되어야 산다는 조건은 너무 놓치는 게 많다" → 4% → 3%로 완화.
#   246일 스윕: 4% 하루 +25,831원(대장률65%·포획17.9%) → 3% 하루 +30,848원(대장률64%·포획19.6%)
#   2%는 +31,803원이나 대장률 58%로 떨어짐(쓰레기 섞임) → ★3%가 균형점.
#   ⚠️'상승 속도(분당 상승률)' 필터는 무효 — 09:03엔 봉이 4개뿐이라 속도 = 시가대비÷4 = 중복 조건.
#   ⚠️포획률 20%의 진짜 병목은 이 문턱이 아니라 **대금 50억**(1,000만원을 사기 위한 대가).
CAP_RISE      = float(os.environ.get("MF_CAP_RISE", "3"))      # 시가 대비 %
CAP_HH        = float(os.environ.get("MF_CAP_HH", "35"))       # 고가 갱신율 %
CAP_BULL      = float(os.environ.get("MF_CAP_BULL", "60"))     # 양봉 비율 %
# [2026-07-17 친구님] 고가갱신율·양봉비율(246일 백테 확정, captain_gate_ab_v51)은 그대로 두고
#   체결강도 하나만 추가 — 봉 모양과 무관하게 "지금 실제로 매수세가 우세한가"를 직접 확인.
#   체결속도·거래대금증가속도·호가지속 3개는 3일 백테 검토 후 기각(갱신율·양봉과 겹치거나 백테 불가능·
#   구현 복잡도만 높음 — captain_gate_backtest_3d.py 참조).
CAP_CHE_MIN   = float(os.environ.get("MF_CAP_CHE_MIN", "120")) # ★[7/17 추가] 체결강도(che_str, 매수체결/매도체결비율)
# ★[7/16 친구님 최종 관문 — A/B 백테(captain_gate_ab_v51·246일)로 확정. 데이터가 친구님 원안 승]
#   ① 주가 1만원↑  ② ★전일 거래대금 700억~2조 — 스윕 결과 전일대금 클수록 좋음
#      (300억 +0.85% → 500억 +1.42% → ★700억 +1.53%/승률52%/하루 +47,140원 → 1000억 +1.83%·건수급감)
#      vs 당일 30억안 +1.02%/+38,437원 · 당일 50억안 +1.30%/+44,640원 → 전일 700억이 최고.
#   ③ 분당 1억↑ 안전핀 유지(백테상 700억 종목은 전부 통과 = 성적 변화 0·무해)  ④ 당일 누적대금 관문 없음(표시용)
#   ⑤ 시총 관문 폐지(표시용). 갭 플라이어 검증: 갭+5~10% 중 시가대비3%↑는 20%뿐·관문 밖 추격은 -1.36%/28%
#      = 갭만 뜨고 시가대비 안 오르는 놈은 놓치는 게 정답(시가대비 기준 유지 근거).
#   사건: 7/16 env(MF_CAP_VAL=0 등)로 관문 전체가 꺼져 전일 2.3억 케이피엠테크 유입 → 슬리피지 -2.5%p.
#   ⚠️낡은 env MF_CAP_VAL·MF_CAP_PERMIN은 setx 삭제함. MF_CAP_MCAP_MIN/MAX는 코드가 더 안 읽음.
CAP_PXMIN     = float(os.environ.get("MF_CAP_PXMIN", "10000"))     # 주가 하한(원)
CAP_VAL       = float(os.environ.get("MF_CAP_VAL", "0"))           # 당일 누적대금 관문(0=끔·표시용만)
CAP_PERMIN    = float(os.environ.get("MF_CAP_PERMIN", "1.0"))      # 분당 대금 안전핀(억)
CAP_PVAL_MIN  = float(os.environ.get("MF_CAP_PVAL_MIN", "700"))    # ★전일 거래대금 하한(억·백테 확정)
CAP_PVAL_MAX  = float(os.environ.get("MF_CAP_PVAL_MAX", "20000"))  # 전일 거래대금 상한(억) = 2조
# ★[7/16 친구님 "캡틴 관문은 완화로 — 당일 폭발형도 들어오게"] OR 관문: 전일 700억~2조 '또는'
#   당일 누적대금 ≥ CAP_DVAL(억). 전일엔 조용했다가 개장 직후 돈이 몰리는 기가레인형(3분 67.8억) 입장 허용.
#   50억 = 원래 캡틴 검증 문턱(20~50억 구간은 승률 18%로 기각됐던 그 선). 롤백 setx MF_CAP_DVAL 999999.
CAP_DVAL      = float(os.environ.get("MF_CAP_DVAL", "50"))         # 당일 폭발형 누적대금 하한(억)
# [7/17 친구님 "최대 3종목 삭제 — 조건되면 매수"] 발행 종목수 상한 삭제. 조건①~⑥ 통과하는 만큼 전부 순위표에 올린다.
#   실제 매수 개수는 실행기(morning_captain_live_v1) 쪽 공용 슬롯(SHARED_MAX_SLOTS)·자본 풀이 정한다.

_CAPM = {"date": "", "m": {}, "logged": False, "win_entered": False, "win_summary": False,
         "calc_completed": False}
_CAP_PVM = {"date": "", "m": {}}    # ★[7/16] 전일 거래대금 맵(억) — 아침대장 관문용 일1회 캐시
_SHARES = {"loaded": False, "m": {}}


def _shares_map():
    """상장주식수 (DATA/shares_outstanding.csv · 1,668종목 · TR 0).
    ★[7/14] 시총캐시(돈맥_시총캐시.json)는 **유니버스 정원(200) 종목만** 조회돼 255개뿐이다.
      아침 09:03엔 거래대금이 아직 안 붙어 대장이 유니버스 밖에 있을 수 있고,
      그러면 시총을 몰라서 판정조차 못 하고 통째로 탈락한다.
      → 상장주식수 × 현재가로 시총을 직접 계산하는 폴백. 캐시에 있으면 캐시 우선."""
    if _SHARES["loaded"]:
        return _SHARES["m"]
    m = {}
    try:
        import csv as _csv
        with open(r"C:\stock_bot\DATA\shares_outstanding.csv", encoding="utf-8-sig") as f:
            for r in _csv.DictReader(f):
                try:
                    m[str(r["code"]).zfill(6)] = float(r["shares"])
                except Exception:
                    pass
    except Exception:
        pass
    _SHARES.update(loaded=True, m=m)
    return m


CAPTAIN_DIAG_CSV = Path(r"C:\stock_bot\data\shadow\captain_window_diag.csv")


def _log_captain_diag(hm, bars_hm, hm_match, window_entered, calc_completed, n_input,
                       n_rise_ok, n_hh_ok, n_bull_ok, n_che_ok,
                       n_money_ok, n_rise_after_money, n_hh_after_rise, n_bull_after_hh, n_che_after_bull,
                       n_final, reason):
    """★[진단로그 2026-07-22, 2026-07-22 보정] _captain_map 판정결과 계측 전용 —
    조건/임계값/BUY/SELL/시간창/continue순서 전부 무변경, 관찰만.
    사유: BOARD_COLD_START·BAR_HM_MISMATCH·BOARD_FRESH_CANDIDATE_ZERO·CAPTAIN_WINDOW_NO_VALID_CALC.
    calc_completed = bars·pvm 정상 확보 + 후보루프 끝까지 1회 실행 완료 시에만 True(win_entered보다 엄격)."""
    try:
        is_new = not CAPTAIN_DIAG_CSV.exists()
        line = ",".join(str(x) for x in [
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"), hm, bars_hm,
            "Y" if hm_match else "N", "Y" if window_entered else "N", "Y" if calc_completed else "N",
            n_input, n_rise_ok, n_hh_ok, n_bull_ok, n_che_ok,
            n_money_ok, n_rise_after_money, n_hh_after_rise, n_bull_after_hh, n_che_after_bull,
            n_final, reason])
        with open(CAPTAIN_DIAG_CSV, "a", encoding="utf-8-sig") as f:
            if is_new:
                f.write("ts,hm,bars_hm,hm_match,window_entered,calc_completed,n_input,"
                        "n_rise_ok,n_hh_ok,n_bull_ok,n_che_ok,"
                        "n_money_ok,n_rise_after_money,n_hh_after_rise,n_bull_after_hh,n_che_after_bull,"
                        "n_final,reason\n")
            f.write(line + "\n")
    except Exception:
        pass


def _captain_map(snap, caps):
    """🔥아침대장 — code → {rise, hh, bull, val, permin, mcap, rank}. TR 0.
    09:02~09:06에만 계산하고 그 결과를 하루 종일 유지(재기동돼도 파일이 아니라 재계산으로 복원).
    caps = 시총 캐시(억). snap = live_micro_snapshot codes."""
    if not CAP_ON:
        return {}
    today = datetime.now().strftime("%Y%m%d")
    hm = datetime.now().strftime("%H%M")
    if _CAPM["date"] != today:
        _CAPM.update(date=today, m={}, logged=False, win_entered=False, win_summary=False,
                     calc_completed=False)
    # 판정창 밖이면 기존 결과 유지(계산 안 함 = 부하 0)
    if not (CAP_START <= hm <= CAP_END):
        # ★[진단 2026-07-22 보정] 창이 방금 닫혔을 때 원인확정용 요약 1줄 —
        #   win_entered(시간대만 진입)가 아니라 calc_completed(실제 계산 완주) 기준으로 구분.
        if hm > CAP_END and not _CAPM.get("win_summary"):
            _CAPM["win_summary"] = True
            if not _CAPM.get("calc_completed"):
                _log_captain_diag(hm, "", False, _CAPM.get("win_entered", False), False, 0, 0, 0, 0, 0,
                                   0, 0, 0, 0, 0, len(_CAPM["m"]), "CAPTAIN_WINDOW_NO_VALID_CALC")
            elif not _CAPM["m"]:
                _log_captain_diag(hm, "", True, True, True, 0, 0, 0, 0, 0,
                                   0, 0, 0, 0, 0, 0, "BOARD_FRESH_CANDIDATE_ZERO")
            else:
                _log_captain_diag(hm, "", True, True, True, 0, 0, 0, 0, 0,
                                   0, 0, 0, 0, 0, len(_CAPM["m"]), "OK")
        return _CAPM["m"]
    _CAPM["win_entered"] = True

    try:
        b1 = json.loads(BARS1.read_text(encoding="utf-8-sig"))
    except Exception:
        _log_captain_diag(hm, "", False, True, False, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, "BOARD_COLD_START")
        return _CAPM["m"]
    bars_hm = str(b1.get("hm", ""))
    if bars_hm != hm:        # 봉이 아직 안 갱신됨
        _log_captain_diag(hm, bars_hm, False, True, False, len(b1.get("m") or {}),
                           0, 0, 0, 0, 0, 0, 0, 0, 0, 0, "BAR_HM_MISMATCH")
        return _CAPM["m"]
    bars = b1.get("m") or {}

    # ★[7/16 친구님 "09:20 전 판정은 전일 기준"] 전일 거래대금 맵 — 일1회 캐시. 없으면 판정 불가(fail-closed·돈 관문)
    if _CAP_PVM["date"] != today:
        _CAP_PVM.update(date=today,
                        m={r[0]: float(r[2]) for r in (_prev_top_pool(today) or []) if len(r) >= 3})
    pvm = _CAP_PVM["m"]
    if not pvm:
        _log_captain_diag(hm, bars_hm, True, True, False, len(bars),
                           0, 0, 0, 0, 0, 0, 0, 0, 0, 0, "BOARD_COLD_START")
        return _CAPM["m"]

    n_rise_ok = n_hh_ok = n_bull_ok = n_che_ok = 0
    n_money_ok = n_rise_after_money = n_hh_after_rise = n_bull_after_hh = n_che_after_bull = 0
    cands = []
    for code, b in bars.items():
        try:
            op = b.get("op")               # ★09:00 봉 시가
            if not op or float(op) <= 0:
                continue
            op = float(op)
            cur = float(b.get("c") or 0)
            if cur <= 0 or cur < CAP_PXMIN:    # ★[7/16 친구님] 주가 하한 1만원(아침대장 전용·전역 PRICE_MIN과 별개)
                continue
            # ★[7/16 친구님 "완화 — 당일 폭발형도"] OR 관문: 전일 700억~2조 '또는' 당일 누적대금 ≥ CAP_DVAL.
            #   여기선 전일 자격만 계산하고, 당일 대금(val)은 아래서 계산된 뒤 함께 판정.
            pval = pvm.get(code)
            pval_ok = pval is not None and (CAP_PVAL_MIN <= pval <= CAP_PVAL_MAX)
            # 시총 — 표시용으로만 계산(★[7/16] 관문 아님). 캐시 우선, 없으면 상장주식수 × 현재가
            cap = caps.get(code)
            if cap is None:
                _sh = _shares_map().get(code)
                if _sh:
                    cap = _sh * cur / 1e8       # 억

            # ★[2026-07-29 친구님 승인 "돈흐름판 한 줄 고쳐"] 최근 4봉만 사용(+현재봉=5봉).
            #   공급자(deep_bottom_signal_recorder)가 같은 날 S02용 3분봉 MA20·ATR14 때문에
            #   보관을 4→60봉으로 늘렸는데, 아래 hh_rate·bull·val 은 창 전체를 나누는 식이라
            #   창이 커질수록 관문이 구조적으로 빡빡해진다(09:30이면 봉 30개 → 통과 훨씬 어려움).
            #   지시 밖 파급이므로 소비 지점에서만 종전 창(4봉)으로 복원 — 공급 파일은 60봉 유지라
            #   S02는 영향 없다. 창 크기를 바꾸려면 검증 후 여기 숫자만 조정. 롤백: *.bak_20260729_prevslice
            prev = (b.get("prev") or [])[-4:]   # [[o,h,l,c], ...] 오래된 → 최근
            pv = (b.get("pv") or [])[-4:]       # [v, ...] 같은 순서
            # ★09:00부터 지금까지의 봉 = 완성봉들 + 현재봉
            ohlc = [[float(x[0]), float(x[1]), float(x[2]), float(x[3])] for x in prev]
            ohlc.append([float(b["o"]), float(b["h"]), float(b["l"]), float(b["c"])])
            vols = [float(x) for x in pv] + [float(b.get("v") or 0)]
            n = len(ohlc)
            if n < 3:                       # 봉 3개는 있어야 판정
                continue

            rise = (cur / op - 1) * 100                       # ★① 시가 대비 상승률
            hh, mx = 0, 0.0                                   # ★② 고가 갱신율
            for o_, h_, l_, c_ in ohlc:
                if h_ > mx:
                    hh += 1
                    mx = h_
            hh_rate = 100.0 * hh / n
            bull = 100.0 * len([1 for o_, _h, _l, c_ in ohlc if c_ > o_]) / n   # ★③ 양봉 비율
            val = sum(v * c[3] for v, c in zip(vols, ohlc)) / 1e8               # 누적 대금(억)
            permin = (sum(vols[-3:]) / min(3, len(vols))) * cur / 1e8           # 분당 대금(억)

            # ★[2026-07-17 추가] 체결강도(매수체결/매도체결비율) — 봉 모양과 무관하게 실시간 매수세 확인
            che = (snap.get(code) or {}).get("che_str")
            che_ok = che is not None and float(che) >= CAP_CHE_MIN

            # ★[진단 2026-07-22] 조건별 독립 통과 카운트(관찰용) — 아래 실제 관문/기존 로직은 그대로
            if rise >= CAP_RISE:
                n_rise_ok += 1
            if hh_rate >= CAP_HH:
                n_hh_ok += 1
            if bull >= CAP_BULL:
                n_bull_ok += 1
            if che_ok:
                n_che_ok += 1
            # ★[진단 2026-07-22 보정] 순차 퍼널 카운트(관찰용) — 기존 continue 순서와 동일한 순서로 누적만 셈.
            #   실제 게이트는 그대로 아래 두 if문이 수행(퍼널은 카운트만, continue엔 관여 안 함).
            _money_ok = pval_ok or val >= CAP_DVAL
            if _money_ok:
                n_money_ok += 1
                if rise >= CAP_RISE:
                    n_rise_after_money += 1
                    if hh_rate >= CAP_HH:
                        n_hh_after_rise += 1
                        if bull >= CAP_BULL:
                            n_bull_after_hh += 1
                            if che_ok:
                                n_che_after_bull += 1

            # ★[7/16 친구님 완화] 돈 관문 = 전일 700억~2조 OR 당일 누적대금 ≥ CAP_DVAL(폭발형)
            if not (pval_ok or val >= CAP_DVAL):
                continue
            if not (rise >= CAP_RISE and hh_rate >= CAP_HH and bull >= CAP_BULL and che_ok
                    and val >= CAP_VAL and permin >= CAP_PERMIN):   # ★[7/16] 당일대금 관문 복원(30억·1억)
                continue
            cands.append({"code": code, "rise": round(rise, 2), "hh": round(hh_rate),
                          "bull": round(bull), "che": round(float(che or 0)),
                          "val": round(val, 1), "permin": round(permin, 2), "mcap": round(float(cap or 0)),
                          "pval": round(float(pval or 0)),    # ★[7/16] 전일 거래대금(억) — 0=전일풀 밖(당일 폭발형 입장)
                          "hm": hm, "bars": n})
        except Exception:
            continue

    # ★[진단 2026-07-22 보정] 후보 루프를 끝까지 1회 실행 — 여기 도달하면 계산 완주로 확정
    _CAPM["calc_completed"] = True
    # ★[진단 2026-07-22] 창 안 판정 결과 1줄(매 호출마다) — 최종후보수는 cands 기준(m 병합 전)
    _log_captain_diag(hm, bars_hm, True, True, True, len(bars), n_rise_ok, n_hh_ok, n_bull_ok, n_che_ok,
                       n_money_ok, n_rise_after_money, n_hh_after_rise, n_bull_after_hh, n_che_after_bull,
                       len(cands), "OK" if cands else "BOARD_FRESH_CANDIDATE_ZERO")

    if not cands:
        return _CAPM["m"]
    # ★정렬 = 시가 대비 상승률 순 (1등이 100% 대장 · 2등 90%)
    cands.sort(key=lambda z: -z["rise"])
    m = dict(_CAPM["m"])
    for i, c in enumerate(cands, 1):
        if c["code"] in m:                 # 종목당 1회(먼저 뜬 신호 유지)
            continue
        c["rank"] = i
        m[c["code"]] = c
    _CAPM["m"] = m
    if cands and not _CAPM["logged"]:
        print(f"[🔥아침대장] {hm} 조건통과 {len(cands)}종목(상한 없음) "
              f"(시가대비 {CAP_RISE:.0f}%↑·갱신율 {CAP_HH:.0f}%↑·양봉 {CAP_BULL:.0f}%↑·체결강도 {CAP_CHE_MIN:.0f}↑·"
              f"★전일대금 {CAP_PVAL_MIN:,.0f}~{CAP_PVAL_MAX:,.0f}억 OR 당일 {CAP_DVAL:,.0f}억↑·주가 {CAP_PXMIN:,.0f}원↑·"
              f"분당 {CAP_PERMIN:.1f}억↑"
              + (f"·당일대금 {CAP_VAL:.0f}억↑" if CAP_VAL > 0 else "") + ")")
        for c in cands:
            print(f"          🔥{c['code']} 시가대비 {c['rise']:+.2f}% · 갱신율 {c['hh']}% · 양봉 {c['bull']}% · "
                  f"체결강도 {c['che']:.0f} · ★전일대금 {c.get('pval', 0):,}억 · "
                  f"당일대금 {c['val']:.0f}억 · 분당 {c['permin']:.2f}억 · 시총 {c['mcap']:,}억")
        _CAPM["logged"] = True
    return m


_DEEPM = {"ts": 0.0, "m": {}}
def _deep_map(snap):
    """[7/9 친구님 "저점공략도 ★처럼 실시간 표시·돈흐름도 선별기에"] 깊은바닥 등재 현황 — code→(저점등락%, 저점서반등%).
    등재 = 당일저점(che_state lo)이 전일종가(전일상위풀)比 -5%↓ (매매기 등재조건과 동일·표시전용·TR 0). 30s 캐시."""
    now = time.time()
    if now - _DEEPM["ts"] < 30:
        return _DEEPM["m"]
    m = {}
    try:
        cs = json.loads(CHE_STATE.read_text(encoding="utf-8-sig"))
        pcm = {c: px for c, px, _v in _prev_top_pool(datetime.now().strftime("%Y%m%d"))}
        drop = float(os.environ.get("MF_DEEP_DROP_PCT", "-5.0"))
        for code, st in cs.items():
            if not isinstance(st, dict):
                continue
            lo = float(st.get("lo", 0) or 0); pc = float(pcm.get(code, 0) or 0)
            if lo <= 0 or pc <= 0:
                continue
            lo_pct = (lo / pc - 1) * 100
            if lo_pct > drop:
                continue
            cur = float(((snap.get(code) or {}).get("cur")) or 0)
            m[code] = (lo_pct, ((cur / lo - 1) * 100) if cur > 0 else None)
    except Exception:
        pass
    _DEEPM.update(ts=now, m=m)
    return m


def _rank_and_save(snap, regime_ok, rtag):
    """_SUP(수급) + snapshot(체결강도/가격) → 방향/합의 등급·순위 → 보드 저장. TR 0(빠른 루프)."""
    import smart_money as SM
    codes, meta = _UNIV
    try:
        namemap = json.loads(NAMEC.read_text(encoding="utf-8")).get("map", {})
    except Exception:
        namemap = {}
    # ★[7/14 밤] 🔥아침대장 — 시총캐시 전체를 읽어 유니버스(정원 200) **밖** 종목도 본다.
    #   아침 09:03엔 거래대금이 아직 안 붙어서 정원 컷(대금순)에 대장이 밀려날 수 있다.
    try:
        _mc = json.loads(MCAP_CACHE.read_text(encoding="utf-8")) if MCAP_CACHE.exists() else {}
        _caps = _mc.get("caps", {}) if _mc.get("date") == datetime.now().strftime("%Y%m%d") else {}
    except Exception:
        _caps = {}
    _CAP = _captain_map(snap, _caps)
    now_ts = time.time()
    rows = []
    for code in codes:
        sup = _SUP.get(code)
        if not sup or (now_ts - float(sup.get("ts", 0) or 0)) > CACHE_MAX_AGE:   # 수급 없거나 너무 오래됨 → 제외
            continue
        inst = sup.get("inst"); frgn = sup.get("frgn"); prog = sup.get("prog")
        indiv = sup.get("indiv"); chg = sup.get("chg")
        buy_cnt = sum(1 for v in (inst, frgn, prog) if v is not None and v > SUBJ_MIN)     # 스마트 매수 주체 수
        sell_cnt = sum(1 for v in (inst, frgn, prog) if v is not None and v < -SUBJ_MIN)   # 스마트 매도 주체 수
        big = (inst or 0) + (frgn or 0) + (prog or 0)
        force = (inst or 0) + (frgn or 0)
        che = (snap.get(code) or {}).get("che_str")
        dump = ((inst is not None and inst <= SM.INST_TH) or (frgn is not None and frgn <= SM.FRGN_TH)
                or (prog is not None and prog <= SM.PROG_TH)
                or (sell_cnt >= SELL_CONS and big < WINNER_MARGIN)   # [7/8 친구님] 2주체 매도여도 매수 +10억↑ 우위면 무시 = 이기는 쪽에 건다
                or (indiv is not None and indiv >= SM.INDIV_TH and force < 0))
        m = meta.get(code) or {}
        _ch = _char_map().get(code) or (None, None)
        _dp = _deep_map(snap).get(code)   # [7/9] 깊은바닥 등재면 (저점등락%, 저점서반등%)
        rows.append({"code": code, "name": (namemap.get(code) or "")[:10] or code,
                     "inst": inst, "frgn": frgn, "prog": prog, "indiv": indiv,
                     "buy_cnt": buy_cnt, "sell_cnt": sell_cnt, "big": big, "chg": chg, "che": che,
                     "t45": bool(_trend45_map().get(code)),   # [7/9] 추세배지 📐(정배열45도+주봉5주선위·표시전용)
                     "acc10": bool(sup.get("acc10")),   # [7/11] 🤝 외인&프로그램 동반 10일 매집(전일까지·이탈없음·180억+)
                     "gc": bool(_gcross_map().get(code)),   # [7/11] 📈 전일 5/20골든크로스 완성+우상향+거래량1.5배
                     "crown": (_crown_map().get(code) or {}).get("signal", ""),   # [7/12] 👑 테마 주도주(쌍끌이/대금2등·당일)
                     "captain": _CAP.get(code),   # ★[7/14] 🔥아침대장(시가대비/갱신율/양봉/대금/분당/시총/등수)

                     "vola": _ch[0], "trend": _ch[1],
                     "price": m.get("price"), "val_eok": m.get("val_eok"), "cap": m.get("cap"),
                     "star": bool(big >= BIG_MIN and not dump),   # [친구님 7/8] ★ = +쪽으로 돈 몰림(큰손합 ≥ 10억·던짐 제외)
                     "deep": ({"lo_pct": round(_dp[0], 1), "reb": (round(_dp[1], 1) if _dp[1] is not None else None)} if _dp else None),
                     "grade": _grade(big, regime_ok, dump)})

    # ★순위 = 순매수 우위 금액(큰손합=기관+외인+프로그램 순매수, 억) 내림차순. 1등=매수세 최강 → 아래로 매도세.
    # [2026-07-09 밤 친구님 "지금 안 하면 잊어먹어 — 영향 없으면 해놔"] 추세배지 📐 정렬가점 —
    #   돈유입 5억(MF_TREND_SORT_BUCKET_EOK) 급이 같으면 📐 먼저·급이 다르면 돈이 우선(돈유입 1기준 불변).
    #   현재 폭락직후라 배지 1개=실효 0 → 시장 회복하면 자동 발동. 롤백: setx MF_TREND_SORT NO (표시는 MF_TREND_BADGE)
    # [7/11 🤝동반매집 정렬가점] 📐와 동일 원칙 — 같은 돈유입 급 안에서만 배지 수(📐+🤝)로 앞세움·급이 다르면 돈이 우선.
    #   롤백: setx MF_ACCUM10_SORT NO (표시는 MF_ACCUM10_BADGE)
    # [7/11 밤 📈골든크로스 정렬가점] 📐·🤝와 동일 원칙 — 같은 돈유입 급 안에서만 배지 수로 앞세움.
    #   롤백: setx MF_GC_SORT NO (표시는 MF_GC_BADGE)
    # [7/12 👑주도주 정렬가점] 동일 원칙. 롤백: setx MF_LEADER_SORT NO (표시는 MF_LEADER_BADGE)
    _ts_on = os.environ.get("MF_TREND_SORT", "YES").strip().upper() == "YES"
    _as_on = os.environ.get("MF_ACCUM10_SORT", "YES").strip().upper() == "YES"
    _gs_on = os.environ.get("MF_GC_SORT", "YES").strip().upper() == "YES"
    _cs_on = os.environ.get("MF_LEADER_SORT", "YES").strip().upper() == "YES"
    if _ts_on or _as_on or _gs_on or _cs_on:
        _bkt = float(os.environ.get("MF_TREND_SORT_BUCKET_EOK", "5")) * 100.0   # 억 → 백만원
        rows.sort(key=lambda x: (-int(x["big"] // _bkt),
                                 -((1 if (_ts_on and x.get("t45")) else 0)
                                   + (1 if (_as_on and x.get("acc10")) else 0)
                                   + (1 if (_gs_on and x.get("gc")) else 0)
                                   + (1 if (_cs_on and x.get("crown")) else 0)),
                                 -x["big"]))
    else:
        rows.sort(key=lambda x: -x["big"])
    for i, x in enumerate(rows, 1):
        x["rank"] = i
    # [7/10 장중 친구님 "선별기가 저점에서 매수세 들어오는 것도 봐야 — 지금 해"] 깊은바닥 등재 순간 주체별 수급 기준점 —
    #   '등재(저점) 이후 신규 유입'을 측정하기 위한 기록 전용(선별·매매 무영향·종목당 하루 1회 첫 관측시).
    #   저녁 검증 후 관문화 예정. 한계: 정원 rows에 든 종목만 기록(정원 밖 등재종목은 편입시 기록).
    try:
        _bl_path = r"C:\stock_bot\data\돈맥_깊은바닥_기준수급.json"
        _bl = json.loads(open(_bl_path, encoding="utf-8-sig").read() or "{}") if os.path.exists(_bl_path) else {}
        _bl_day = time.strftime("%Y%m%d"); _bl_chg = False
        for x in rows:
            if not x.get("deep"):
                continue
            _k = f"{_bl_day}:{x['code']}"
            if _k in _bl:
                continue
            _bl[_k] = {"hm": time.strftime("%H%M"), "name": x.get("name"),
                       "lo_pct": x["deep"].get("lo_pct"), "reb": x["deep"].get("reb"),
                       "inst": x.get("inst"), "frgn": x.get("frgn"), "prog": x.get("prog"),
                       "indiv": x.get("indiv"), "price": x.get("price")}
            _bl_chg = True
        if _bl_chg:
            open(_bl_path, "w", encoding="utf-8").write(json.dumps(_bl, ensure_ascii=False, indent=1))
    except Exception:
        pass
    OUT_JSON.write_text(json.dumps({"ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "regime": rtag,
                                    "mode": MODE, "univ": len(_UNIV[0]),
                                    # ★[7/12 친구님 "선별기에서 전체를 봐야 돼 — 던짐이나 선별된 거나 상관없어·
                                    #   모두가 급락 후보자야·여기는 테마 대장주들이 거의 많이 들어와"]
                                    #   깊은바닥 감시 유니버스로 매매기가 쓴다. 지금까지는 대장주 순위표(66종목)만 봐서
                                    #   선별기 정원(200)에 든 급락 테마주를 통째로 놓치고 있었음.
                                    #   등급/수급/던짐 무관 = 깔때기 통과 전체(코스닥·대금·시총1000억·주가2만).
                                    "univ_codes": list(_UNIV[0]),
                                    # ★[7/14 밤] 🔥아침대장 — 전략들이 공용으로 소비하는 신호.
                                    #   ⚠️유니버스(정원 200) 밖 종목도 들어있다. 아침엔 대금이 안 붙어
                                    #     정원 컷(대금순)에 대장이 밀리기 때문. rows가 아니라 여기를 볼 것.
                                    #   각 항목: {code, rise(시가대비%), hh(고가갱신율%), bull(양봉%),
                                    #            val(누적대금 억), permin(분당대금 억), mcap(시총 억),
                                    #            rank(시가대비 순위·1등이 100% 대장), hm(신호시각), bars(봉수)}
                                    "captain": _CAP,
                                    "rows": rows}, ensure_ascii=False), encoding="utf-8")

    def a(v):
        return f"{(v or 0) / 100:+.0f}" if v is not None else "NA"
    L = [f"=== 💰 돈맥 선별기  {datetime.now():%H:%M:%S}  [레짐:{rtag}]  (코스닥·주가≥{PRICE_MIN:,.0f}원 | 1만원↑=대금{VAL_MIN_EOK:.0f}억·시총{MCAP_MIN_EOK:.0f}억 · 잡주=대금{LOW_VAL_EOK:.0f}억·시총{LOW_MCAP_EOK:.0f}억·보장석{LOW_QUOTA}) — 순매수 우위(억) 순위 · 📐=추세배지 · 🤝=외인&프로 10일 동반매집(전일까지·이탈없음·180억+) · 📈=전일 5/20골든크로스+우상향+거래량1.5배 · 👑=테마 주도주(등락1등·대금1등, 👑2=대금2등·당일) ===",
         f"{'등수':>3} {'종목':<11}{'순매수우위':>10}{'기관':>6}{'외인':>6}{'프로':>6}{'개인':>6}{'등락':>7}{'변동':>6}{'우상향':>6}{'체결':>5}  등급"]
    for x in rows[:OUT_TOPN]:
        _net = x["big"] / 100
        _side = (f"매수+{_net:.0f}" if _net >= 0 else f"매도{_net:.0f}")
        _vola = x.get("vola"); _trend = x.get("trend")
        L.append(f"{x['rank']:>3} {x['name']:<11}{_side:>10}"
                 f"{a(x['inst']):>6}{a(x['frgn']):>6}{a(x['prog']):>6}{a(x['indiv']):>6}"
                 f"{(x['chg'] if x['chg'] is not None else 0):>+6.1f}%"
                 f"{(f'{_vola:.1f}' if _vola is not None else '-'):>6}"
                 f"{(f'{_trend:.2f}' if _trend is not None else '-'):>6}"
                 f"{(x['che'] or 0):>5.0f}  {x['grade']}{' ★' if x.get('star') else ''}"
                 + (" 📐" if x.get("t45") else "")
                 + (" 🤝" if x.get("acc10") else "")
                 + (" 📈" if x.get("gc") else "")
                 + ((" 👑" + ("2" if x.get("crown") == "대금2등" else "")) if x.get("crown") else "")
                 + (f" 🕳{x['deep']['lo_pct']:+.1f}%" if x.get("deep") else ""))
    # [7/9 친구님 "저점공략도 ★처럼 실시간·돈흐름도 선별기에"] 🕳 깊은바닥 감시 섹션 —
    #   등재 전 종목(순위 하단 포함)·저점깊이/저점서 반등/어느 주체가 돈 넣는 중(±3억 기준). 매매기 관문과 같은 데이터.
    _deeps = [x for x in rows if x.get("deep")]
    if _deeps:
        L.append("")
        # [7/10 장전점검] 등재 기준을 env 연동으로(-4 확장 반영·라벨-로직 불일치 방지). 아침1차는 체결강도 무관(가격만·MF_DEEP_R1_NOCHE).
        _ddrop = float(os.environ.get("MF_DEEP_DROP_PCT", "-5.0"))
        L.append(f"── 🕳 깊은바닥 감시 {len(_deeps)}종목 (당일저점 전일比 {_ddrop:.0f}%↓ · 매수관문[아침1차]: 저점+1.5%턴·저점+6%내·돈유입 — 체결강도 무관) ──")
        for x in sorted(_deeps, key=lambda z: z["deep"]["lo_pct"]):
            _d = x["deep"]
            _reb = f"반등{_d['reb']:+.1f}%" if _d.get("reb") is not None else "반등 -"
            _inflow = [nm for nm, k in (("기관", "inst"), ("외인", "frgn"), ("프로", "prog"), ("개인", "indiv"))
                       if x.get(k) is not None and x[k] >= 300]
            _out = [nm for nm, k in (("기관", "inst"), ("외인", "frgn"), ("프로", "prog"), ("개인", "indiv"))
                    if x.get(k) is not None and x[k] <= -300]
            L.append(f"   {x['name']:<11} 저점 {_d['lo_pct']:+.1f}% · {_reb} · "
                     f"돈유입 {('✓' + '/'.join(_inflow)) if _inflow else '✗없음'}"
                     + (f" · 던지는중 {'/'.join(_out)}" if _out else "")
                     + f" · 체결 {x['che'] or 0:.0f}")
    OUT_TXT.write_text("\n".join(L), encoding="utf-8")
    return rows


def _save_supply():
    """_SUP 영속(워밍스타트용). 유니버스 밖·너무 오래된 것 정리."""
    now_ts = time.time()
    keep = {c: v for c, v in _SUP.items() if c in _UNIV[0] and (now_ts - float((v or {}).get("ts", 0) or 0)) < CACHE_MAX_AGE * 2}
    try:
        _tmp = CACHE.with_suffix(".tmp"); _tmp.write_text(json.dumps(keep, ensure_ascii=False), encoding="utf-8"); os.replace(_tmp, CACHE)
    except Exception:
        pass


def run():
    global _SUP, _UNIV, _STOP
    if MODE == "OFF":
        return
    # 장중만. 수동테스트는 setx MF_BOARD_FORCE YES.
    if os.environ.get("MF_BOARD_FORCE", "").strip().upper() != "YES":
        _hm = datetime.now().strftime("%H%M")
        if _hm < "0855" or _hm > "1535":
            print(f"장외({_hm}) → skip"); return
        if _eod_close_quiet_window():
            print(f"종가매수 우선시간({_hm}) → 돈맥 TR skip"); return
    from broker_client import BrokerClient, is_broker_alive
    if not is_broker_alive():
        print("broker dead → skip"); return
    bc = BrokerClient()
    regime_ok, rtag = _regime()
    today = datetime.now().strftime("%Y%m%d")

    # 워밍스타트: 이전 프로세스가 남긴 수급 캐시 로드(신선한 것만)
    try:
        _c = json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() else {}
        now_ts = time.time()
        _SUP = {k: v for k, v in _c.items() if isinstance(v, dict) and (now_ts - float(v.get("ts", 0) or 0)) < CACHE_MAX_AGE}
    except Exception:
        _SUP = {}

    # [7/8 친구님] 아침(09:40 이전)엔 어제 확정 큰손으로 수급 시드 — 개장 1분 포착의 재료
    if datetime.now().strftime("%H%M") < "0940":
        _seed_from_yesterday(today)

    # 깔때기 유니버스(동기·시총 롤테이션 포함)
    _UNIV = _universe(bc)
    if not _UNIV[0]:
        OUT_JSON.write_text(json.dumps({"ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "regime": rtag,
                                        "mode": MODE, "rows": []}, ensure_ascii=False), encoding="utf-8")
        print(f"돈맥 선별기: 유니버스 0종목(거래대금/시총/주가 통과 없음·레짐 {rtag})")
        return

    # 백그라운드 수급 폴러(유일한 TR 스레드) 기동
    _STOP = False
    th = threading.Thread(target=_supply_poller, args=(bc, today), daemon=True)
    th.start()

    # che_state 로드(당일)
    try:
        che_state = json.loads(CHE_STATE.read_text(encoding="utf-8")) if CHE_STATE.exists() else {}
    except Exception:
        che_state = {}
    if che_state.get("date") != today:
        che_state = {"date": today}

    # ★빠른 루프: 등수 재계산 + 보드 저장(TR 0). 수급은 백그라운드가 계속 채움.
    deadline = time.monotonic() + RUN_SEC
    n = 0
    while True:
        if (os.environ.get("MF_BOARD_FORCE", "").strip().upper() != "YES"
                and _eod_close_quiet_window()):
            break
        try:
            snap = json.loads(SNAP.read_text(encoding="utf-8-sig")).get("codes", {})
        except Exception:
            snap = {}
        hmn = datetime.now().strftime("%H%M")
        _update_che_state(snap, che_state, today, hmn)
        _publish_micro_watch(snap)      # [7/12] 급락종목 실시간 호가 구독 발행(브로커 CAP120 우선순위 1번)
        _rank_and_save(snap, regime_ok, rtag)
        _save_supply()
        n += 1
        _force = os.environ.get("MF_BOARD_FORCE", "").strip().upper() == "YES"
        if time.monotonic() >= deadline or (not _force and datetime.now().strftime("%H%M") > "1535"):
            break
        time.sleep(LOOP_SEC)
    _STOP = True
    print(f"돈맥 선별기: 유니버스 {len(_UNIV[0])} · 루프 {n}회 · 레짐 {rtag}")


if __name__ == "__main__":
    # 단일 인스턴스 락 — 이미 돌고있으면(락<200s) skip(개장 TR혼잡시 보드 쌓임 방지).
    LOCK = Path(r"C:\stock_bot\data\돈흐름_보드.lock")
    _skip = False
    try:
        if LOCK.exists() and (time.time() - LOCK.stat().st_mtime) < 200:
            print("보드 이미 실행중(lock) → skip"); _skip = True
    except Exception:
        pass
    if not _skip:
        try:
            LOCK.write_text(str(os.getpid()), encoding="utf-8")
        except Exception:
            pass
        try:
            run()
        finally:
            _STOP = True
            try:
                LOCK.unlink()
            except Exception:
                pass
