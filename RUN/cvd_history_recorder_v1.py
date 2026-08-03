# -*- coding: utf-8 -*-
"""CVD 이력 기록기 — 급락 종목의 체결·호가 시계열을 남긴다 (그림자·주문 0·TR 0).

[2026-07-29 친구님 지시] "진짜 저점을 찾아낼 수 있느냐가 제일 중요한 과제다.
급락하면서 계단식으로 떨어지는데 이걸 어떻게 피해서 저점 반등을 확인하느냐."

전문가들이 쓰는 저점 판별식은 CVD(Cumulative Volume Delta) 다이버전스다.
    CVD = 누적매수체결량 - 누적매도체결량
    가격이 새 저점을 만드는데 CVD는 이전 저점보다 높다  ->  진짜 바닥 신호
    가격도 CVD도 같이 새 저점                          ->  가짜 (계단이 이어진다)

계산 재료(buy_vol_cum·sell_vol_cum·호가)는 live_micro_snapshot.json 에 이미 있으나
현재값만 남고 덮어써져 이력이 없다. 이 기록기가 그 시계열을 남긴다.

★주문 없음. TR 0 (기존 파일 읽기 전용). 실패해도 매매에 무해.
소비처 없음 — 며칠 쌓아 CVD 다이버전스 검증 후 S03 진입조건 배선 판단.
"""
import csv
import json
import os
import time
from datetime import datetime
from pathlib import Path

SNAP = Path(r"C:\stock_bot\IPC\live_micro_snapshot.json")
S03_SIGNAL = Path(r"C:\stock_bot\data\strategy_03_골짜기_급반등_signal_v1.json")
OUT_DIR = Path(r"C:\stock_bot\data\shadow")
LOG = Path(r"C:\stock_bot\data\LOG\cvd_history_recorder.log")

LOOP_SEC = float(os.environ.get("CVD_LOOP_SEC", "3"))
DROP_PCT = float(os.environ.get("CVD_DROP_PCT", "-3.0"))   # 이 이하로 빠진 종목만
MAX_CODES = int(os.environ.get("CVD_MAX_CODES", "60"))     # 낙폭 큰 순 상한
END_HM = os.environ.get("CVD_END", "1535")

COLS = ["ts", "code", "name", "drop_pct", "cur",
        "buy_vol_cum", "sell_vol_cum", "cvd",
        "buy_money_cum", "sell_money_cum", "che_str",
        "ask_tot", "bid_tot", "best_ask_px", "best_bid_px",
        "best_ask_qty", "best_bid_qty", "imb", "snap_ts"]


def _log(msg):
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8") as f:
            f.write("[%s] %s\n" % (datetime.now().strftime("%H:%M:%S"), msg))
    except OSError:
        pass


def _jload(path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return default if default is not None else {}


_stale_logged = set()


def _targets():
    """S03 신호 파일에서 급락 종목을 뽑는다(낙폭 큰 순). 전일종가 재조회 불필요."""
    d = _jload(S03_SIGNAL)
    # ★[2026-07-29 친구님 승인 "CVD 날짜 가드도 고쳐"] 신호 파일이 오늘 것이 아니면 기록하지 않는다.
    #   S03 신호기가 못 뜬 날(7/27·7/28 실제 발생)에는 어제 후보 목록이 그대로 남아 있어,
    #   가드가 없으면 하루 종일 '어제 급락주'를 오늘 자료로 적어 연구 자료가 오염된다.
    #   날짜 필드가 없으면(구버전·형식변경) 종전대로 진행 = fail-open. 롤백: 이 블록 삭제.
    file_date = str(d.get("date") or "")
    if file_date and file_date != datetime.now().strftime("%Y%m%d"):
        if file_date not in _stale_logged:
            _stale_logged.add(file_date)
            _log("⛔ S03 신호 파일이 오늘 것이 아님(date=%s) — 기록 중단(S03 신호기 확인 필요)" % file_date)
        return []
    latest = {}
    for row in (d.get("candidates") or []):
        code = row.get("code")
        if not code:
            continue
        if code not in latest or str(row.get("ts") or "") > str(latest[code].get("ts") or ""):
            latest[code] = row
    picked = []
    for code, row in latest.items():
        drop = row.get("drop_from_previous_close_pct")
        if drop is None:
            continue
        try:
            drop = float(drop)
        except (TypeError, ValueError):
            continue
        if drop <= DROP_PCT:
            picked.append((drop, code, row.get("name") or ""))
    picked.sort()
    return picked[:MAX_CODES]


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / ("cvd_history_%s.csv" % datetime.now().strftime("%Y%m%d"))
    new_file = not out.exists()
    fh = out.open("a", encoding="utf-8-sig", newline="")
    writer = csv.writer(fh)
    if new_file:
        writer.writerow(COLS)
    _log("기동 — 낙폭 %.1f%% 이하 상위 %d종목 · %.0f초 주기 · 종료 %s (주문 0)"
         % (DROP_PCT, MAX_CODES, LOOP_SEC, END_HM))

    last_snap_ts = {}
    rows_written = 0
    while True:
        now = datetime.now()
        if now.strftime("%H%M") > END_HM:
            break
        try:
            targets = _targets()
            if targets:
                codes = (_jload(SNAP) or {}).get("codes") or {}
                stamp = now.isoformat(timespec="milliseconds")
                batch = []
                for drop, code, name in targets:
                    rec = codes.get(code)
                    if not rec:
                        continue
                    snap_ts = str(rec.get("ts") or "")
                    if snap_ts and last_snap_ts.get(code) == snap_ts:
                        continue          # 갱신 없으면 건너뛴다(중복 제거)
                    last_snap_ts[code] = snap_ts
                    bv = rec.get("buy_vol_cum")
                    sv = rec.get("sell_vol_cum")
                    try:
                        cvd = float(bv) - float(sv)
                    except (TypeError, ValueError):
                        cvd = ""
                    batch.append([
                        stamp, code, name, round(drop, 3), rec.get("cur"),
                        bv, sv, cvd,
                        rec.get("buy_money_cum"), rec.get("sell_money_cum"),
                        rec.get("che_str"), rec.get("ask_tot"), rec.get("bid_tot"),
                        rec.get("best_ask_px"), rec.get("best_bid_px"),
                        rec.get("best_ask_qty"), rec.get("best_bid_qty"),
                        rec.get("imb"), snap_ts,
                    ])
                if batch:
                    writer.writerows(batch)
                    fh.flush()
                    rows_written += len(batch)
        except Exception as exc:
            _log("루프 오류(계속): %s" % exc)
        time.sleep(LOOP_SEC)

    fh.close()
    _log("종료 — 기록 %d행 → %s" % (rows_written, out.name))


if __name__ == "__main__":
    main()
