# -*- coding: utf-8 -*-
"""[전날 종가 기준 '오늘의 대장주 순위표' — 친구님 2026-07-01 설계]
   친구님: "종가매수용으로 거래대금 1~100등 리스트를 만들었더니 대장이 다 들어오고
            100등도 거래대금 100억 넘어서 잡주가 들어올 틈이 없었다.
            근데 내 주력은 장중 단타다. 단타에 맞는 종목을 점수·등수로 골라서
            매일 아침 봇이 전날 상황을 체크해 이걸 활용하게 하고 싶다.
            종가매수도 하니까 종가매수용(거래대금 순위)도 같이."
   → 전날(가장 최근) 종가 EOD 데이터에서 코스닥 거래대금 100억+ 를 universe 로 잡고:
       · value_rank  = 거래대금 순위 (종가매수/유동성용)
       · scalp_score = 단타 적합 점수 (0~100) · scalp_rank = 그 등수 (장중 단타용)
   ★단타 점수 = 아래 5요소를 '해당일 universe 내 백분위'로 환산해 가중합 (절대값 스케일 무관·robust):
       유동성(거래대금) · 일중변동폭(단타 핵심·움직여야 먹음) · 우상향(trend_score) ·
       거래량활발(vol_ratio) · 마감강도(close_position)
   ★거래대금 100억 하한이 잡주를 원천 차단. ★브로커 불필요(EOD CSV만) → 9시 정각부터 참조.
   ★주문 0. 매일 장전(또는 EOD 수집 직후) 1회 실행. 봇 내부용(사람 뷰어 아님).
   출력: data/daily_leader_board.json  (leader_filter 가 이걸 우선 참조)
   env: DLB_TOP_N=100 · DLB_MIN_VALUE_EOK=100(억) · DLB_MARKET=KOSDAQ|ALL
        가중치(합 100 권장): DLB_W_LIQ=30 DLB_W_RANGE=30 DLB_W_TREND=20 DLB_W_VOL=12 DLB_W_CLOSE=8
"""
import os, sys, json
from pathlib import Path
from datetime import datetime

sys.path.insert(0, r"C:\stock_bot\RUN")

EOD_CSV  = Path(r"C:\stock_bot\data\eod_daily_bars.csv")
OUT_JSON = Path(r"C:\stock_bot\data\daily_leader_board.json")
OUT_TXT  = Path(r"C:\stock_bot\data\daily_leader_board.txt")
LOG      = Path(r"C:\stock_bot\data\LOG\daily_leader_board.log")

TOP_N         = int(os.environ.get("DLB_TOP_N", "100"))
MIN_VALUE_EOK = float(os.environ.get("DLB_MIN_VALUE_EOK", "100"))   # 거래대금 하한(억). 100=100억
# ★eod_daily_bars.value 단위 = 백만원 → 억(億) = value / 100.
MIN_VALUE     = MIN_VALUE_EOK * 100                                  # value(백만원) 기준 하한
MARKET        = os.environ.get("DLB_MARKET", "KOSDAQ").strip().upper()

# 단타 점수 가중치
W_LIQ   = float(os.environ.get("DLB_W_LIQ",   "30"))   # 유동성(거래대금)
W_RANGE = float(os.environ.get("DLB_W_RANGE", "30"))   # 일중 변동폭(단타 핵심)
W_TREND = float(os.environ.get("DLB_W_TREND", "20"))   # 우상향 강도
W_VOL   = float(os.environ.get("DLB_W_VOL",   "12"))   # 거래량 활발
W_CLOSE = float(os.environ.get("DLB_W_CLOSE", "8"))    # 마감 강도

# 종가매수 점수 가중치(오버나잇=오늘 종가 사서 내일 아침 팖 → '내일 이어질 강함'.
#   단타와 달리 변동폭 대신 마감강도·상승모멘텀·우상향 중심)
E_CLOSE = float(os.environ.get("DLB_E_CLOSE", "25"))   # 마감 강도(종가 강하게 = 익일지속)
E_MOM   = float(os.environ.get("DLB_E_MOM",   "25"))   # 당일 상승 모멘텀(daily_return)
E_TREND = float(os.environ.get("DLB_E_TREND", "20"))   # 우상향 추세
E_VOL   = float(os.environ.get("DLB_E_VOL",   "15"))   # 거래량 급증(관심 유입)
E_LIQ   = float(os.environ.get("DLB_E_LIQ",   "15"))   # 유동성(대장)
# [D-2 수급 2026-07-02 친구님] ★2일전(D-2) 기관 순매수 = 익일 상승 최강 신호(친구님 직접백테).
#   종가매수 선별 점수에도 반영: universe 내 D-2 기관순매수 백분위 × 가중치(없으면 0=중립).
#   실행기(eod_gap)는 이미 D-2로 최종정렬 → 선별점수도 같은 신호로 통일. 0=끄기. 롤백 setx DLB_E_SUPPLY 0.
E_SUPPLY     = float(os.environ.get("DLB_E_SUPPLY", "20"))    # D-2 기관수급 가중치(강신호)
E_SUPPLY_LAG = int(os.environ.get("DLB_E_SUPPLY_LAG", "2"))   # 2=2일전(백테 최강)


def _log(m):
    s = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {m}"
    print(s, flush=True)
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(s + "\n")
    except Exception:
        pass


def _is_kosdaq(mkt):
    s = str(mkt).upper()
    return ("닥" in str(mkt)) or ("KOSDAQ" in s) or (s == "101") or (s == "Q")


def build():
    import pandas as pd
    if not EOD_CSV.exists():
        _log(f"[중단] EOD 파일 없음: {EOD_CSV}")
        return None
    # ★32bit 파이썬 메모리 보호 — 필요한 컬럼만 로드
    cols = ["date", "code", "name", "market", "high", "low", "close",
            "value", "vol_ratio", "trend_score", "close_position", "daily_return"]
    df = pd.read_csv(EOD_CSV, usecols=cols, dtype={"code": str})
    df["date"] = df["date"].astype(str)
    last_date = df["date"].max()
    d = df[df["date"] == last_date].copy()

    for c in ["high", "low", "close", "value", "vol_ratio", "trend_score", "close_position", "daily_return"]:
        d[c] = pd.to_numeric(d[c], errors="coerce")
    d = d[d["value"] > 0]
    total_day = len(d)

    if MARKET == "KOSDAQ":
        d = d[d["market"].map(_is_kosdaq)]
    kosdaq_n = len(d)

    d["value_eok"] = d["value"] / 100.0
    d = d[d["value_eok"] >= MIN_VALUE_EOK].copy()      # 거래대금 하한 → 잡주 차단
    # [7/4 친구님 "변동폭 커도 저가주는 들어오면 안 돼, 돈 물린다"] 가격 하한 — 브로커 매수게이트(SAFEPLUS_MIN_PRICE)와
    #   동일 기준을 유니버스 단계에서 선차단(랭킹표에 아예 미등재). 롤백 setx DLB_MIN_PRICE 0.
    _minp = float(os.environ.get("DLB_MIN_PRICE", os.environ.get("SAFEPLUS_MIN_PRICE", "3000")) or 0)
    if _minp > 0:
        _b4 = len(d); d = d[d["close"] >= _minp].copy()
        if len(d) < _b4:
            _log(f"[가격하한] {_minp:,.0f}원 미만 {_b4 - len(d)}종목 유니버스 제외")
    if d.empty:
        _log(f"[중단] 하한통과 0종목 (기준일 {last_date})")
        return None

    # 일중 변동폭(%) — 단타 핵심
    d["range_pct"] = (d["high"] - d["low"]) / d["close"] * 100.0

    # ── 단타 점수: 각 요소를 universe 내 백분위(0~1)로 환산해 가중합 ──
    def pr(col):   # 높을수록 좋음 → 백분위
        return d[col].rank(pct=True, na_option="bottom")
    liq_r   = pr("value_eok")
    range_r = pr("range_pct")
    trend_r = pr("trend_score")
    vol_r   = pr("vol_ratio")
    close_r = pr("close_position")
    wsum = (W_LIQ + W_RANGE + W_TREND + W_VOL + W_CLOSE) or 1.0
    d["scalp_score"] = ((liq_r * W_LIQ + range_r * W_RANGE + trend_r * W_TREND
                         + vol_r * W_VOL + close_r * W_CLOSE) / wsum * 100.0).round(1)

    # ── 종가매수 점수: 변동폭 대신 마감강도·상승모멘텀·우상향 + ★D-2 기관수급(익일 최강신호) ──
    mom_r = pr("daily_return")
    # [D-2 수급] universe 각 종목의 2일전 기관 순매수 → 컬럼화(데이터없으면 0=중립) → universe내 백분위
    sup_map = {}
    if E_SUPPLY > 0:
        try:
            import supply_signal as _ss
            sup_map = _ss.aged_supply_map(list(d["code"]), as_of=str(last_date), lag=E_SUPPLY_LAG) or {}
        except Exception as _e:
            _log(f"[D-2수급] 헬퍼 실패 fail-open(수급요소 0점): {_e}")
    d["supply_d2"] = d["code"].map(lambda c: sup_map.get(str(c).zfill(6), 0) or 0)
    sup_r = pr("supply_d2") if E_SUPPLY > 0 else 0.0
    esum = (E_CLOSE + E_MOM + E_TREND + E_VOL + E_LIQ + E_SUPPLY) or 1.0
    d["eod_score"] = ((close_r * E_CLOSE + mom_r * E_MOM + trend_r * E_TREND
                       + vol_r * E_VOL + liq_r * E_LIQ + sup_r * E_SUPPLY) / esum * 100.0).round(1)
    d["eod_rank"] = d["eod_score"].rank(ascending=False, method="first").astype(int)
    if E_SUPPLY > 0:
        _log(f"[D-2수급] as_of={last_date} lag={E_SUPPLY_LAG} · universe {len(d)} 중 데이터 {len(sup_map)}종목 반영(가중치 {E_SUPPLY:g})")

    # 순위: 거래대금(유동성) · 단타점수(장중 단타) · 종가점수(오버나잇) — ★셋 다 universe 전체 기준(절단 전)
    d["value_rank"] = d["value_eok"].rank(ascending=False, method="first").astype(int)
    d["scalp_rank"] = d["scalp_score"].rank(ascending=False, method="first").astype(int)
    # eod_rank 는 위에서 이미 universe 전체로 계산됨.
    # ★[2026-07-02 버그수정] 예전엔 scalp 상위 TOP_N 만 남기고(head) 그 잘린 board 에서
    #   codes_by_eod/codes_by_value 를 뽑아 → '종가매수 100·거래대금 100'이 단타점수 낮은 대형주를
    #   조용히 누락했다(universe 116 → 종가 상위100 중 9종목 클래시스·펄어비스·휴젤·HLB 등 탈락).
    #   → board = 세 랭킹(단타/종가/거래대금) 각 상위 TOP_N 의 '합집합'. 각 리스트가 자기 랭킹으로 온전해짐.
    #   (universe 작아 비용 무시. 아래 codes/codes_by_value/codes_by_eod 는 각자 [:TOP_N] 로 절단.)
    _keep = (set(d.sort_values("scalp_score", ascending=False).head(TOP_N)["code"])
             | set(d.sort_values("eod_score",   ascending=False).head(TOP_N)["code"])
             | set(d.sort_values("value_eok",   ascending=False).head(TOP_N)["code"]))
    d = d[d["code"].isin(_keep)].sort_values("scalp_score", ascending=False).reset_index(drop=True)

    board, codes = [], []
    for _, r in d.iterrows():
        code = str(r["code"]).lstrip("A").zfill(6)
        codes.append(code)
        board.append({
            "scalp_rank":  int(r["scalp_rank"]),
            "scalp_score": float(r["scalp_score"]),
            "eod_rank":    int(r["eod_rank"]),
            "eod_score":   float(r["eod_score"]),
            "value_rank":  int(r["value_rank"]),
            "code": code,
            "name": str(r["name"]),
            "value_eok": round(float(r["value_eok"]), 1),
            "range_pct": round(float(r["range_pct"]), 1),
            "trend_score": (None if pd.isna(r["trend_score"]) else round(float(r["trend_score"]), 2)),
            "supply_d2": int(r["supply_d2"]) if ("supply_d2" in d.columns and pd.notna(r["supply_d2"])) else 0,  # 2일전 기관 순매수(주)
            "close": float(r["close"]),
        })

    out = {
        "date": last_date,
        "generated": datetime.now().isoformat(timespec="seconds"),
        "market": MARKET,
        "min_value_eok": MIN_VALUE_EOK,
        "top_n": TOP_N,
        "weights": {"liq": W_LIQ, "range": W_RANGE, "trend": W_TREND, "vol": W_VOL, "close": W_CLOSE},
        "eod_weights": {"close": E_CLOSE, "mom": E_MOM, "trend": E_TREND, "vol": E_VOL, "liq": E_LIQ, "supply_d2": E_SUPPLY},
        "count": len(board),
        # ★board 는 세 랭킹의 합집합(≥TOP_N)이므로 각 리스트를 자기 랭킹으로 정렬 후 [:TOP_N] 로 온전히 절단.
        "codes":          [b["code"] for b in sorted(board, key=lambda x: x["scalp_rank"])][:TOP_N],  # 단타점수 순
        "codes_by_value": [b["code"] for b in sorted(board, key=lambda x: x["value_rank"])][:TOP_N],  # 거래대금 순
        "codes_by_eod":   [b["code"] for b in sorted(board, key=lambda x: x["eod_rank"])][:TOP_N],    # 종가매수 순
        "board": board,
    }
    tmp = OUT_JSON.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, OUT_JSON)

    # 사람이 필요시 열어보는 요약(바탕화면 아님·data 폴더)
    lines = [f"# 단타 대장주 순위표 (전날 종가 {last_date} · {MARKET} · 거래대금 {MIN_VALUE_EOK:.0f}억↑ · {len(board)}종목)",
             f"# 단타점수 = 유동성{W_LIQ:.0f}+변동폭{W_RANGE:.0f}+우상향{W_TREND:.0f}+거래량{W_VOL:.0f}+마감{W_CLOSE:.0f}",
             "# 단타순위 점수  거래대금순위  종목            거래대금  일중변동", ""]
    for b in board:
        lines.append(f"{b['scalp_rank']:>3}  {b['scalp_score']:>5.1f}  (대금{b['value_rank']:>3})  "
                     f"{b['code']} {b['name']:<14} {b['value_eok']:>6.0f}억  변동{b['range_pct']:>4.1f}%")
    OUT_TXT.write_text("\n".join(lines) + "\n", encoding="utf-8")

    _log(f"순위표 생성: 기준일={last_date} {MARKET} · 전체{total_day}→코스닥{kosdaq_n}→100억+ {len(board)}종목 "
         f"· 단타1위 {board[0]['name']}({board[0]['scalp_score']:.0f}점) · 대금1위 {out['codes_by_value'][0]}")
    return out


if __name__ == "__main__":
    try:
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    except Exception:
        pass
    o = build()
    if o:
        print(f"\n=== 단타 점수 상위 15 (전날 {o['date']} 기준 · {o['count']}종목) ===")
        print("  순위  점수  (거래대금순위)  종목           거래대금  일중변동  우상향")
        for b in o["board"][:15]:
            print(f"  {b['scalp_rank']:>3}  {b['scalp_score']:>5.1f}  (대금{b['value_rank']:>3}위)  "
                  f"{b['code']} {b['name']:<12} {b['value_eok']:>6.0f}억  {b['range_pct']:>4.1f}%  {b['trend_score']}")
