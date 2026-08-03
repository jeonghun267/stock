# -*- coding: utf-8 -*-
"""👁 돈맥 선별기 워처 — 주문0·TR0. money_flow_board_v1.py(돈맥 선별기)의 출력을
읽기전용으로 지켜보다가 "몇 시에 이 종목이 처음/마지막으로 떴는지"만 기록.

목적(2026-07-20 밤 친구님 "기존 프로그램 최초 포착 시각 비교 기준 = 돈맥 선별기"):
  micro_rank_engine의 TOP20 진입 시각과, 돈맥 선별기(기존 프로그램)가 같은 종목을
  처음 잡은 시각을 나중에 비교해서 "몇 초 먼저 잡았는지"(선행시간) 계산하는 재료.
  워처 자신은 판단·매매·전략 변경을 전혀 하지 않는다 — 순수 타임스탬프 기록기.

읽기: C:\\stock_bot\\data\\돈흐름_선별판.json (money_flow_board_v1.py가 이미 쓰는 파일, 무수정)
씀: moneyflow_watch_history.csv(이벤트: FIRST_SEEN·DROPPED) · moneyflow_watch_state.json(현재 상태) · LOG

돈맥 선별기의 "rows"(순매수 우위 순위표, 핵심 선별 리스트) 기준으로 추적한다.
"captain"(아침대장)은 같은 파일의 다른 신호라 이번엔 포함하지 않음 — 필요하면 별도 추가.

리허설 주입구(env): MFW_SRC·MFW_HIST·MFW_STATE·MFW_LOG·MFW_POLL(1.0)
"""
import os
import csv
import json
import time
from datetime import datetime
from pathlib import Path

SRC   = Path(os.environ.get("MFW_SRC")   or r"C:\stock_bot\data\돈흐름_선별판.json")
HIST  = Path(os.environ.get("MFW_HIST")  or r"C:\stock_bot\data\moneyflow_watch_history.csv")
STATE = Path(os.environ.get("MFW_STATE") or r"C:\stock_bot\data\moneyflow_watch_state.json")
LOG   = Path(os.environ.get("MFW_LOG")   or r"C:\stock_bot\data\LOG\moneyflow_watch.log")
POLL_SEC = float(os.environ.get("MFW_POLL", "1.0"))

_HIST_HEADER = ["ts", "event", "code", "name", "detail"]


def _log(m):
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8") as f:
            f.write(f"[{datetime.now():%H:%M:%S}] {m}\n")
    except Exception:
        pass
    print(m, flush=True)


def _hist_write(event, code, name, detail=""):
    try:
        HIST.parent.mkdir(parents=True, exist_ok=True)
        new = not HIST.exists()
        with HIST.open("a", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            if new:
                w.writerow(_HIST_HEADER)
            w.writerow([datetime.now().strftime("%Y-%m-%d %H:%M:%S"), event, code, name, detail])
    except Exception as e:
        _log(f"[HIST] 기록 실패(무시): {e}")


def _atomic_write_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def main():
    _log("moneyflow_watch_v1 시작 — 읽기전용 · TR 0 · 주문 0 (money_flow_board_v1.py 무수정)")
    _log(f"입력={SRC} 폴링={POLL_SEC}s")

    last_mtime = None
    last_good = {}
    stale = False
    first_seen = {}   # code -> {"ts": iso, "name":, "rank":}
    currently_in = set()

    while True:
        loop_t0 = time.time()

        try:
            mtime = SRC.stat().st_mtime
        except Exception as e:
            if not stale:
                _hist_write("SRC_STALE", "-", "-", f"파일 접근 실패: {e}")
                _log(f"[STALE] 접근 실패(직전 정상 데이터 유지): {e}")
                stale = True
            mtime = None

        if mtime is not None and mtime != last_mtime:
            try:
                parsed = json.loads(SRC.read_text(encoding="utf-8-sig"))
                last_good = parsed
                last_mtime = mtime
                if stale:
                    _hist_write("SRC_RECOVER", "-", "-", "")
                    _log("[RECOVER] 정상 회복")
                    stale = False
            except Exception as e:
                if not stale:
                    _hist_write("SRC_STALE", "-", "-", f"파싱 실패: {e}")
                    _log(f"[STALE] 파싱 실패(직전 정상 데이터 유지): {e}")
                    stale = True

        rows = last_good.get("rows") or []
        now_codes = {}
        for r in rows:
            c = r.get("code")
            if not c:
                continue
            now_codes[c] = r

        now_set = set(now_codes.keys())

        for c in now_set - currently_in:
            r = now_codes[c]
            ts_now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            first_seen[c] = {"ts": ts_now, "name": r.get("name", ""), "rank": r.get("rank")}
            _hist_write("FIRST_SEEN", c, r.get("name", ""), f"rank={r.get('rank')} grade={r.get('grade')}")

        for c in currently_in - now_set:
            prev = first_seen.get(c, {})
            _hist_write("DROPPED", c, prev.get("name", ""), "")

        currently_in = now_set

        try:
            _atomic_write_json(STATE, {
                "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "board_ts": last_good.get("ts"),
                "currently_in_count": len(currently_in),
                "first_seen": first_seen,
            })
        except Exception as e:
            _log(f"[WRITE] 상태 저장 실패: {e}")

        elapsed = time.time() - loop_t0
        time.sleep(max(0.05, POLL_SEC - elapsed))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
    except Exception as e:
        _log(f"🚨 치명 오류: {e}")
