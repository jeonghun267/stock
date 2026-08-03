# -*- coding: utf-8 -*-
"""[전략용 감시 유니버스 2026-07-01 친구님] EOD 거래대금 상위 100(우리 데이터) → micro_watch_strategy.json.
목적: 키움 라이브 movers(들락날락)에 의존 말고, 전일 EOD 스코어로 우리가 고른 100종목을 9시부터 '연속' 감시.
그럼 043260처럼 급락하는 바닥 시간에도 체결강도가 계속 찍힘(라이브 movers는 오른 뒤에야 들어옴).
broker는 IPC/micro_watch_*.json 을 glob 자동구독(체결강도 FID228). 잡주 배제: 가격≥3000.
2026-07-24: 골짜기 Gate1 전용 파일도 함께 발행한다. 코스닥 보통주·1만원↑·전일대금
100억~2조·시총1000억↑만 담고 broker에서 최우선 등록한다.
2026-07-24: 캡틴2 EARLY 전용 파일도 함께 발행한다. 코스닥 보통주·1만원↑ 중
전일 거래대금 상위 100을 장전 등록해 당일 급등 뒤에야 실시간 수신이 시작되는 누락을 막는다.
장전 08:50 실행. 주문 0.
"""
import os, csv, json
from collections import defaultdict, deque
from datetime import datetime
from pathlib import Path

EOD = Path(r"C:\stock_bot\data\eod_daily_bars.csv")
SHARES = Path(r"C:\stock_bot\data\shares_outstanding.csv")
OUT = Path(r"C:\stock_bot\IPC\micro_watch_strategy.json")
VALLEY_OUT = Path(r"C:\stock_bot\IPC\micro_watch_valley.json")
CAPTAIN2_OUT = Path(r"C:\stock_bot\IPC\micro_watch_captain2.json")
STRATEGY01_OUT = Path(r"C:\stock_bot\IPC\micro_watch_strategy_shared.json")
LOG = Path(r"C:\stock_bot\data\LOG\strategy_watchlist.log")
TOPN      = int(os.environ.get("STRAT_WATCH_TOPN", "100"))
MIN_PRICE = float(os.environ.get("STRAT_WATCH_MIN_PRICE", "3000"))
KOSDAQ_ONLY = os.environ.get("STRAT_WATCH_KOSDAQ_ONLY", "YES").strip().upper() == "YES"  # ★기본 코스닥(전략 유니버스·KOSPI대형주/ETF 배제)
CAPTAIN2_TOPN = int(os.environ.get("CAPTAIN2_PREWATCH_TOPN", "100"))
CAPTAIN2_MIN_PRICE = float(os.environ.get("CAPTAIN2_MIN_PRICE", "10000"))
CAPTAIN2_MIN_5D_RETURN_PCT = float(os.environ.get("CAPTAIN2_MIN_5D_RETURN_PCT", "-10"))
CAPTAIN2_MIN_HIGH_CLOSE_PCT = float(os.environ.get("CAPTAIN2_MIN_HIGH_CLOSE_PCT", "10"))
CAPTAIN2_MIN_VALUE_RATIO_20D = float(os.environ.get("CAPTAIN2_MIN_VALUE_RATIO_20D", "6"))
VALLEY_MIN_PRICE = float(os.environ.get("VH_PX_FLOOR", "10000"))
VALLEY_PVAL_MIN = float(os.environ.get("VH_MORNING_PVAL_MIN", "100"))
VALLEY_PVAL_MAX = float(os.environ.get("VH_PVAL_MAX", "20000"))
VALLEY_MCAP_MIN = float(os.environ.get("VH_MORNING_MCAP_MIN", "1000"))
VALLEY_MCAP_MAX_AGE_DAYS = float(os.environ.get("VH_MORNING_MCAP_MAX_AGE_DAYS", "7"))


def _log(m):
    s = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {m}"
    print(s, flush=True)
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8") as handle:
            handle.write(s + "\n")
    except Exception:
        pass


def _market_caps():
    """최근 시총 캐시 {code: 억}. 오래됐거나 비어 있으면 빈 dict로 fail-closed."""
    try:
        age_days = (datetime.now().timestamp() - SHARES.stat().st_mtime) / 86400.0
        if age_days < 0 or age_days > VALLEY_MCAP_MAX_AGE_DAYS:
            _log(f"[ERR] shares_outstanding stale age={age_days:.1f}d")
            return {}
        out = {}
        with SHARES.open(encoding="utf-8-sig", newline="") as fh:
            for row in csv.DictReader(fh):
                code = str(row.get("code") or "").zfill(6)
                try:
                    cap = float(row.get("market_cap_eok") or 0)
                except (TypeError, ValueError):
                    cap = 0.0
                if len(code) == 6 and cap > 0:
                    out[code] = cap
        return out
    except Exception as e:
        _log(f"[ERR] shares_outstanding read {e}")
        return {}


def _write_watch(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def _captain2_metrics(hist):
    """전일까지만 확정된 EOD로 캡틴2 장전 압축 지표를 계산한다."""
    rows = list(hist)
    if len(rows) < 21:
        return None
    _date, close, high, value = rows[-1]
    close_5d = rows[-6][1]
    prior_values = [row[3] for row in rows[-21:-1]]
    if close <= 0 or close_5d <= 0 or len(prior_values) != 20 or any(v <= 0 for v in prior_values):
        return None
    avg20 = sum(prior_values) / 20.0
    return {
        "prev_close": close,
        "ret_5d_pct": (close / close_5d - 1.0) * 100.0,
        "high_close_pct": (high / close - 1.0) * 100.0 if high > 0 else -999.0,
        "value_ratio_20d": value / avg20 if avg20 > 0 else 0.0,
        "prev_value": value,
    }

def main():
    # 최신 일자 = 마지막 데이터행의 date
    with open(EOD, encoding="utf-8-sig") as f:
        header = f.readline().rstrip("\n").split(",")
        last = deque(f, maxlen=1)
    di = header.index("date"); ci = header.index("code"); mi = header.index("market")
    pi = header.index("close"); hi = header.index("high"); vi = header.index("value")
    ni = header.index("name")
    maxd = last[0].split(",")[di] if last else ""
    if not maxd:
        _log("[ERR] eod_daily_bars 비어있음"); return

    rows, valley_rows, captain2_rows = [], [], []
    history = defaultdict(lambda: deque(maxlen=21))
    caps = _market_caps()
    with open(EOD, encoding="utf-8-sig") as f:
        r = csv.reader(f); next(r)
        for x in r:
            if len(x) <= vi:
                continue
            mkt = str(x[mi]).upper()
            if KOSDAQ_ONLY and "KOSDAQ" not in mkt:
                continue
            try:
                close = float(x[pi] or 0); high = float(x[hi] or 0); val = float(x[vi] or 0)
            except ValueError:
                continue
            code = str(x[ci]).zfill(6)
            if "KOSDAQ" in mkt and len(code) == 6 and code.isdigit():
                history[code].append((str(x[di]), close, high, val))
            if x[di] != maxd:
                continue
            if close < MIN_PRICE or val <= 0:
                continue
            rows.append((val, code))
            pval_eok = val / 100.0
            name = str(x[ni] or "")
            if (close >= CAPTAIN2_MIN_PRICE and len(code) == 6 and code.isdigit() and code[-1] == "0"
                    and "스팩" not in name):
                captain2_rows.append((val, code))
            if ("KOSDAQ" in mkt and close >= VALLEY_MIN_PRICE
                    and VALLEY_PVAL_MIN <= pval_eok <= VALLEY_PVAL_MAX
                    and len(code) == 6 and code[-1] == "0" and "스팩" not in name
                    and caps.get(code, 0.0) >= VALLEY_MCAP_MIN):
                valley_rows.append((val, code))
    rows.sort(reverse=True)               # 거래대금 내림차순
    codes = [c for _, c in rows[:TOPN]]
    valley_rows.sort(reverse=True)
    valley_codes = [c for _, c in valley_rows]
    captain2_rows.sort(reverse=True)
    captain2_codes = [c for _, c in captain2_rows[:CAPTAIN2_TOPN]]
    captain2_qualified = []
    captain2_meta = {}
    captain2_all_meta = {}
    for code in captain2_codes:
        metrics = _captain2_metrics(history.get(code, ()))
        if not metrics:
            continue
        captain2_all_meta[code] = metrics
        if (metrics["ret_5d_pct"] >= CAPTAIN2_MIN_5D_RETURN_PCT
                and metrics["high_close_pct"] >= CAPTAIN2_MIN_HIGH_CLOSE_PCT
                and metrics["value_ratio_20d"] >= CAPTAIN2_MIN_VALUE_RATIO_20D):
            captain2_qualified.append(code)
            captain2_meta[code] = metrics
    now = datetime.now()
    try:
        _write_watch(OUT, {"codes": codes, "ts": now.isoformat(), "src": "strategy"})
        _write_watch(
            VALLEY_OUT,
            {"codes": valley_codes, "ts": now.isoformat(), "for_date": now.strftime("%Y%m%d"),
             "source_date": maxd, "src": "valley_gate1",
             "filters": {"market": "KOSDAQ", "price_min": VALLEY_MIN_PRICE,
                         "pval_min_eok": VALLEY_PVAL_MIN, "pval_max_eok": VALLEY_PVAL_MAX,
                         "mcap_min_eok": VALLEY_MCAP_MIN, "ordinary_only": True}},
        )
        _write_watch(
            CAPTAIN2_OUT,
            {"codes": captain2_codes, "ts": now.isoformat(),
             "for_date": now.strftime("%Y%m%d"), "source_date": maxd,
             "src": "captain2_early", "qualified_codes": captain2_qualified,
             "meta": captain2_meta,
             "all_meta": captain2_all_meta,
             "filters": {"market": "KOSDAQ", "price_min": CAPTAIN2_MIN_PRICE,
                         "min_5d_return_pct": CAPTAIN2_MIN_5D_RETURN_PCT,
                         "min_high_close_pct": CAPTAIN2_MIN_HIGH_CLOSE_PCT,
                         "min_value_ratio_20d": CAPTAIN2_MIN_VALUE_RATIO_20D,
                         "topn_by_prev_value": CAPTAIN2_TOPN, "ordinary_only": True}},
        )
        _write_watch(
            STRATEGY01_OUT,
            {"codes": captain2_codes, "ts": now.isoformat(),
             "for_date": now.strftime("%Y%m%d"), "source_date": maxd,
             "src": "strategy_01_open_surge", "qualified_codes": captain2_qualified,
             "meta": captain2_meta,
             "all_meta": captain2_all_meta,
             "filters": {"market": "KOSDAQ", "price_min": CAPTAIN2_MIN_PRICE,
                         "min_5d_return_pct": CAPTAIN2_MIN_5D_RETURN_PCT,
                         "min_high_close_pct": CAPTAIN2_MIN_HIGH_CLOSE_PCT,
                         "min_value_ratio_20d": CAPTAIN2_MIN_VALUE_RATIO_20D,
                         "topn_by_prev_value": CAPTAIN2_TOPN, "ordinary_only": True}},
        )
    except Exception as e:
        _log(f"[ERR] write {e}"); return
    _log(f"전략 감시 유니버스 {len(codes)}종목 (기준일 {maxd}·거래대금상위·가격≥{MIN_PRICE:.0f}) → {OUT.name}")
    _log("상위10: " + " ".join(codes[:10]))
    _log(f"골짜기 Gate1 전용 {len(valley_codes)}종목 (대금≥{VALLEY_PVAL_MIN:.0f}억·"
         f"시총≥{VALLEY_MCAP_MIN:.0f}억·1만원↑·보통주) → {VALLEY_OUT.name}")
    _log("골짜기 상위10: " + " ".join(valley_codes[:10]))
    _log(f"캡틴2 EARLY 전용 {len(captain2_codes)}종목 "
         f"(전일대금 상위{CAPTAIN2_TOPN}·{CAPTAIN2_MIN_PRICE:.0f}원↑·보통주) → {CAPTAIN2_OUT.name}")
    _log("캡틴2 상위10: " + " ".join(captain2_codes[:10]))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        _log(f"[FATAL] {e}"); raise
