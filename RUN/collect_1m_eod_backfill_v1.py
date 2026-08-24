# -*- coding: utf-8 -*-
"""[수집기 재설계 2026-07-11] 장후 1분봉 풀백필 — collect_1m_eod_backfill_v1

배경(친구님 "수집기도 재설계해봐"):
  장중 수집기는 TR 페이스 한계로 포화 가동(1,100/h)인데 실제 커버는 코어 ~55종목뿐
  (C버킷 700 중 하루 164종목만 회전). 장중 다이어트(-49%)와 세트로,
  "전 종목 데이터 완결성"을 이 스크립트(장후 1회·한도 여유 시간대)로 이관.

동작:
  1) 15:35 이후에만(가드) — 평일·브로커 생존 확인
  2) 유니버스 = eod_daily_bars.csv 최신일 코스닥 거래대금 상위 BF1M_TOPN(700)
  3) prices_1m.csv에서 오늘 봉수 >= BF1M_SKIP_BARS(330)인 종목은 skip(수집기가 이미 커버)
  4) 나머지 종목당 opt10080 1페이지(900봉=당일 전체) — 페이스 BF1M_PACE(0.35s)·화면 3000~3019 회전
  5) 당일 봉만 골라 8개 기본컬럼으로 prices_1m.csv에 멱등 병합
     (기존 행 우선·피처 컬럼 0 채움 — 3분봉 빌더(23:02)는 OHLCV+value만 사용 확인됨)

TR 예산: 최대 BF1M_TOPN(700)건 × 1페이지 ≈ 실측 ~550건·4분 (장후라 프리징 무관)
저널 식별: broker_client TR-CALLER 태그(rqname=opt10080_collect_1m_eod_backfill_v1)
끄기: 태스크 SAFEPLUS_COLLECT_1M_EOD_BACKFILL Disabled / 테스트: BF1M_DRY=YES(TR 0)
"""
import os
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, r"C:\stock_bot\RUN")

from ma3_seed_v1 import DEFAULT_SEED_PATH, build_opening_seed

DATA_DIR = Path(r"C:\stock_bot\data")
OUT_PATH = DATA_DIR / "prices_1m.csv"
EOD_PATH = DATA_DIR / "eod_daily_bars.csv"
LOG_PATH = DATA_DIR / "LOG" / "collect_1m_eod_backfill.log"
LOCK_PATH = DATA_DIR / "collect_1m_eod_backfill.lock"

TOPN      = int(os.environ.get("BF1M_TOPN", "700"))
SKIP_BARS = int(os.environ.get("BF1M_SKIP_BARS", "330"))   # 오늘 이 봉수 이상이면 완결로 간주(381이 만봉)
PACE      = float(os.environ.get("BF1M_PACE", "0.35"))     # TR 간격(초)
MIN_PRICE = int(os.environ.get("BF1M_MIN_PRICE", "500"))   # 수집기 MIN_PRICE_FILTER(500)와 동일
DRY       = os.environ.get("BF1M_DRY", "NO").strip().upper() == "YES"
FORCE     = os.environ.get("BF1M_FORCE", "NO").strip().upper() == "YES"   # 시간가드 무시(테스트용)
DEADLINE_HM = os.environ.get("BF1M_DEADLINE", "1700")      # 이 시각 넘으면 중단(폭주 방지)

OUT_FIELDS = ["체결시간", "시가", "고가", "저가", "현재가", "거래량", "거래대금"]


def log(msg: str):
    line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
    print(line, flush=True)
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def _refresh_ma3_seed(session_date: str) -> None:
    try:
        stats = build_opening_seed(
            prices_path=OUT_PATH,
            seed_path=DEFAULT_SEED_PATH,
            max_session_date=session_date,
        )
        log(
            "MA3 opening seed "
            f"date={stats['session_date']} ready={stats['ready_codes']} "
            f"skipped={stats['skipped_codes']}"
        )
    except Exception as exc:
        log(f"MA3 opening seed failed: {exc}")

def _safe_int(v):
    try:
        return abs(int(str(v).replace(",", "").strip() or 0))
    except Exception:
        return 0


def load_universe(pd):
    """eod_daily_bars 최신일 코스닥 거래대금 상위 TOPN 종목코드 리스트."""
    df = pd.read_csv(EOD_PATH, dtype={"code": str}, encoding="utf-8-sig",
                     usecols=["date", "code", "market", "value"])
    df = df[(df["date"] == df["date"].max()) & (df["market"] == "KOSDAQ")]
    df["value"] = pd.to_numeric(df["value"], errors="coerce").fillna(0)
    df = df.sort_values("value", ascending=False).head(TOPN)
    return [str(c).zfill(6) for c in df["code"].tolist()]


def load_today_counts(pd, today):
    """prices_1m.csv의 오늘 종목별 봉수. 파일 없으면 {}."""
    if not OUT_PATH.exists() or OUT_PATH.stat().st_size == 0:
        return {}, None
    old = pd.read_csv(OUT_PATH, dtype={"code": str, "ts": str})
    today_rows = old[old["ts"].astype(str).str.startswith(today)]
    return today_rows.groupby("code")["ts"].count().to_dict(), old


def main():
    now = datetime.now()
    today = now.strftime("%Y%m%d")
    if now.weekday() >= 5 and not FORCE:
        log("주말 — 종료"); return
    if now.strftime("%H%M") < "1535" and not FORCE:
        log("15:35 이전 — 장중 실행 금지 가드, 종료"); return

    # 단일 실행 락 (1시간 이상 지난 락은 고아로 간주)
    if LOCK_PATH.exists() and (time.time() - LOCK_PATH.stat().st_mtime) < 3600:
        log("락 존재(다른 실행 중) — 종료"); return
    LOCK_PATH.write_text(str(os.getpid()), encoding="utf-8")

    try:
        import pandas as pd
        uni = load_universe(pd)
        counts, old_df = load_today_counts(pd, today)
        targets = [c for c in uni if counts.get(c, 0) < SKIP_BARS]
        log(f"유니버스 {len(uni)} · 오늘 완결 skip {len(uni) - len(targets)} · 백필 대상 {len(targets)}")
        if DRY:
            log(f"[DRY] TR 없이 종료. 대상 예시: {targets[:10]}"); return
        if not targets:
            log("No EOD targets; refresh MA3 seed from existing prices_1m")
            _refresh_ma3_seed(today)
            return

        from broker_client import BrokerClient
        bc = BrokerClient()
        if not bc.alive():
            log("브로커 죽음 — 백필 불가, 종료"); return

        rows = []
        ok = to = err = 0
        for i, code in enumerate(targets):
            if datetime.now().strftime("%H%M") > DEADLINE_HM:
                log(f"마감시각({DEADLINE_HM}) 초과 — {i}/{len(targets)}에서 중단"); break
            scr = str(3000 + (i % 20))
            r = bc.tr("opt10080",
                      inputs={"종목코드": code, "틱범위": "1", "수정주가구분": "0"},
                      output_fields=OUT_FIELDS, screen_no=scr, timeout_sec=10.0)
            st = str((r or {}).get("status", "")).upper()
            if st != "OK":
                to += 1 if st == "TIMEOUT" else 0
                err += 0 if st == "TIMEOUT" else 1
                time.sleep(PACE)
                continue
            recs = ((r.get("data") or {}).get("records")) or []
            n_new = 0
            for rec in recs:
                ts = (rec.get("체결시간") or "").strip()
                if not (ts and ts.isdigit() and ts.startswith(today)):
                    continue
                row = {
                    "code": code, "ts": ts,
                    "open": _safe_int(rec.get("시가")), "high": _safe_int(rec.get("고가")),
                    "low": _safe_int(rec.get("저가")), "close": _safe_int(rec.get("현재가")),
                    "volume": _safe_int(rec.get("거래량")), "value": _safe_int(rec.get("거래대금")),
                }
                if row["value"] == 0 and row["close"] > 0 and row["volume"] > 0:
                    row["value"] = row["close"] * row["volume"]
                if row["close"] < MIN_PRICE or row["open"] <= 0 or row["high"] < row["low"]:
                    continue
                rows.append(row)
                n_new += 1
            ok += 1
            if i % 100 == 0:
                log(f"진행 {i}/{len(targets)} · 신규봉 누적 {len(rows)}")
            time.sleep(PACE)

        log(f"조회 완료 ok={ok} timeout={to} err={err} · 백필 봉 {len(rows)}")
        if not rows:
            log("No new EOD rows; refresh MA3 seed from existing prices_1m")
            _refresh_ma3_seed(today)
            return

        new_df = pd.DataFrame(rows)
        if old_df is not None:
            # 기존 컬럼 스키마 유지: 백필에 없는 피처 컬럼은 0으로(수집기 관행과 동일)
            for col in old_df.columns:
                if col not in new_df.columns:
                    new_df[col] = 0
            new_df = new_df[old_df.columns]
            merged = pd.concat([old_df, new_df], ignore_index=True)
        else:
            merged = new_df
        before = len(merged)
        merged = (merged.drop_duplicates(subset=["code", "ts"], keep="first")  # 기존(수집기 피처 포함) 행 우선
                        .sort_values(["code", "ts"]).reset_index(drop=True))
        tmp = OUT_PATH.with_suffix(".bf_tmp")
        merged.to_csv(tmp, index=False, encoding="utf-8-sig")
        os.replace(str(tmp), str(OUT_PATH))
        _refresh_ma3_seed(today)
        log(f"병합 저장 완료: 총 {len(merged)}행 (중복제거 {before - len(merged)}) → {OUT_PATH.name}")
    except Exception as e:
        import traceback
        log(f"오류: {e}\n{traceback.format_exc()}")
    finally:
        try:
            LOCK_PATH.unlink(missing_ok=True)
        except Exception:
            pass


if __name__ == "__main__":
    main()
