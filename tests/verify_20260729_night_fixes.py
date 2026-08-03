# -*- coding: utf-8 -*-
"""7/29 밤 수정분 전체 재검증. 읽기 전용(임시 폴더에만 씀)."""
import sys, os, io, csv, json, glob, time, runpy, py_compile, threading, contextlib, importlib
from pathlib import Path
from datetime import datetime

RUN = r"C:\stock_bot\RUN"
sys.path.insert(0, RUN)
sys.path.insert(0, r"C:\stock_bot\tests")
TMP = Path(r"C:\Users\UserK\AppData\Local\Temp\claude\C--Users-UserK\d8a76606-7e00-4f02-8da5-c9b16d394cd5\scratchpad\verify")
TMP.mkdir(parents=True, exist_ok=True)

results = []
def check(name, ok, detail=""):
    results.append((name, bool(ok), detail))
    print(f"  {'통과' if ok else '★실패'}  {name}" + (f"  |  {detail}" if detail else ""))

MODIFIED = [
    "strategy_05_base_breakout_signal_v1.py", "s05_signal_guard_v1.py", "골짜기_급반등.py",
    "strategy_01_open_surge_signal_v2.py", "strategy_02_low_buy_signal_v1.py",
    "strategy_04_pullback_signal_v1.py", "strategy_common_hold_sell_v1.py",
    "strategy_common_candidate_context_v1.py", "money_flow_board_v1.py",
    "cvd_history_recorder_v1.py", "eod_gap_live_executor_v1.py", "broker_gateway_v1.py",
]

print("\n[1] 문법 검사 — 오늘 밤 수정한 파이썬 전부")
for fn in MODIFIED:
    p = os.path.join(RUN, fn)
    try:
        py_compile.compile(p, doraise=True)
        check(f"문법 {fn}", True)
    except Exception as e:
        check(f"문법 {fn}", False, f"{type(e).__name__}: {str(e)[:60]}")
p_test = r"C:\stock_bot\tests\test_strategy_01_open_surge_buy_v1.py"
try:
    py_compile.compile(p_test, doraise=True); check("문법 test_strategy_01_open_surge_buy_v1.py", True)
except Exception as e:
    check("문법 test_strategy_01_open_surge_buy_v1.py", False, str(e)[:60])

print("\n[2] 저장 충돌 재시도 — S05 / S03 (오늘 11:29 사고 재현)")
for label, modname in [("S05", "strategy_05_base_breakout_signal_v1"), ("S03", "골짜기_급반등")]:
    m = importlib.import_module(modname)
    tgt = TMP / f"retry_{label}.json"
    tgt.write_text('{"old":1}', encoding="utf-8")
    h = open(tgt, "r")
    threading.Thread(target=lambda: (time.sleep(0.3), h.close())).start()
    t0 = time.time()
    try:
        m._write_json_atomic(tgt, {"new": 2})
        el = time.time() - t0
        ok = json.loads(tgt.read_text(encoding="utf-8")) == {"new": 2} and el >= 0.15
        check(f"{label} 잠금 풀린 뒤 저장 성공", ok, f"{el:.2f}초 소요(재시도 작동)")
    except Exception as e:
        check(f"{label} 잠금 풀린 뒤 저장 성공", False, str(e)[:60])
    h2 = open(tgt, "r")
    try:
        m._write_json_atomic(tgt, {"x": 3}); check(f"{label} 계속 잠기면 예외 유지", False, "예외가 안 남")
    except PermissionError:
        check(f"{label} 계속 잠기면 예외 유지", True, "원인 은폐 안 함")
    finally:
        h2.close()

print("\n[3] CSV 열 고정 — 고저폭 유무가 섞인 배치 (종전엔 즉사)")
for label, modname in [("S01", "strategy_01_open_surge_signal_v2"), ("S02", "strategy_02_low_buy_signal_v1"),
                       ("S03", "골짜기_급반등"), ("S04", "strategy_04_pullback_signal_v1"),
                       ("S05", "strategy_05_base_breakout_signal_v1")]:
    m = importlib.import_module(modname)
    p = TMP / f"cols_{label}.csv"
    if p.exists(): p.unlink()
    try:
        m._append_events(p, [{"code": "111111", "score": 10},
                             {"code": "222222", "score": 20, "hr_pct": 12.5, "hr_rank": 3}])
        m._append_events(p, [{"code": "333333", "score": 30, "hr_pct": 9.9, "hr_rank": 7}])
        m._append_events(p, [{"code": "444444", "score": 40, "mf_grade": "A"}])
        rows = list(csv.DictReader(open(p, encoding="utf-8-sig", newline="")))
        hdr = list(rows[0].keys())
        ok = (hdr == ["code", "score", "hr_pct", "hr_rank", "mf_grade"] and len(rows) == 4
              and rows[0]["hr_pct"] == "" and rows[1]["hr_rank"] == "3"
              and rows[2]["code"] == "333333" and rows[3]["mf_grade"] == "A")
        check(f"{label} 열 정렬 유지·크래시 없음", ok, f"{len(rows)}행 / 열 {len(hdr)}개")
    except Exception as e:
        check(f"{label} 열 정렬 유지·크래시 없음", False, f"{type(e).__name__}: {str(e)[:50]}")

print("\n[4] 공통매도 VWAP — 결손은 보류, 진짜 이탈만 매도")
from types import SimpleNamespace as NS
from strategy_common_hold_sell_v1 import UnifiedHoldSellEngine
fake = NS(config=NS(early_trend_min_buy_ratio=0.5))
def fails(vwap, price, ratio=0.9):
    return UnifiedHoldSellEngine._early_trend_failures(fake, None, NS(vwap=vwap, price=price, buy_ratio_recent=ratio))
check("VWAP 결손(0) → 보류", fails(0, 100) == [])
check("가격 결손(0) → 보류", fails(100, 0) == [])
check("진짜 이탈(가격<=VWAP) → 매도", fails(100, 99) == ["VWAP"])
check("정상(가격>VWAP) → 보유", fails(100, 101) == [])
check("매수비율 미달은 종전대로 FLOW", fails(100, 101, 0.1) == ["FLOW"])

print("\n[5] 통합후보판 — 지표는 배달, 감시목록엔 미편입")
import strategy_common_candidate_context_v1 as ctx
now = datetime.now(); today = now.strftime("%Y%m%d"); iso = now.isoformat()
BASE, BOARD_ONLY, RANK = "000001", "000003", "000004"
shared, _v, _a = ctx.build_context(
    now=now, shared_base={"codes": [BASE], "all_meta": {}}, valley_base={"codes": []},
    profiles={BOARD_ONLY: {"p": 1.0}, RANK: {"p": 2.0}},
    money_rank={"date": today, "ts": iso, "all_items": [{"code": RANK, "money_start": True}], "top20": []},
    selector={}, money_watch={}, high_range={},
    board={"date": today, "ts": iso, "attention_rank": [{"code": BOARD_ONLY, "rank": 1}, {"code": RANK, "rank": 2}]})
check("통합후보판 단독종목 미편입", BOARD_ONLY not in shared["codes"])
check("다른 소스 종목은 종전대로 편입", RANK in shared["codes"])
check("ic_* 지표 배달 유지", len([k for k in shared["all_meta"].get(RANK, {}) if k.startswith("ic_")]) >= 5,
      f"{len([k for k in shared['all_meta'].get(RANK, {}) if k.startswith('ic_')])}개 키")

print("\n[6] 돈흐름판 창 복원 — 최근 4봉만 사용")
src = open(os.path.join(RUN, "money_flow_board_v1.py"), encoding="utf-8").read()
check("prev 슬라이스 [-4:] 적용", '(b.get("prev") or [])[-4:]' in src)
check("pv 슬라이스 [-4:] 적용", '(b.get("pv") or [])[-4:]' in src)

print("\n[7] CVD 날짜 가드")
mc = importlib.import_module("cvd_history_recorder_v1")
fake_sig = TMP / "s03_fake.json"; fake_log = TMP / "cvd.log"
if fake_log.exists(): fake_log.unlink()
mc.S03_SIGNAL = fake_sig; mc.LOG = fake_log; mc._stale_logged.clear()
cands = [{"code": "000660", "name": "T", "ts": "T1", "drop_from_previous_close_pct": -8.0}]
def wr(dv):
    pl = {"candidates": cands}
    if dv is not None: pl["date"] = dv
    fake_sig.write_text(json.dumps(pl, ensure_ascii=False), encoding="utf-8")
wr(today); check("오늘 날짜 → 기록함", len(mc._targets()) == 1)
wr("20260728"); check("어제 날짜 → 기록 안 함", mc._targets() == [])
mc._targets()
nlog = len(fake_log.read_text(encoding="utf-8").strip().splitlines()) if fake_log.exists() else 0
check("경고 로그는 1회만", nlog == 1, f"{nlog}줄")
wr(None); check("날짜 없음 → fail-open 진행", len(mc._targets()) == 1)

print("\n[8] S01 고저폭 — 출력 JSON signals 에 실림")
m01 = importlib.import_module("strategy_01_open_surge_signal_v2")
mon = m01.OpenSurgeShadowMonitor(max_signals_per_code=2)
mon.process_point = lambda point: ({"code": "000660", "name": "T", "action": "BUY_READY"}, True)
ret = mon.process_points([NS(code="000660")])
for r in ret: r.update({"hr_rank": 3, "hr_crown": True, "hr_streak": 2})
outrow = mon.signals[0]
check("출력 JSON 쪽에 hr_* 실림", all(k in outrow for k in ("hr_rank", "hr_crown", "hr_streak")))
check("두 목록이 같은 객체 공유", mon.signals[0] is ret[0])

print("\n[9] 일봉 전일종가 — 오늘 행 제외")
me = importlib.import_module("eod_gap_live_executor_v1")
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    prev = me._prev_eod()
exp = {"0039P0": 4560, "455900": 15900, "900300": 1561}
for code, want in exp.items():
    got = (prev.get(code) or {}).get("close_prev")
    check(f"{code} 전일종가 = {want}", got == want, f"실제 {got}")
check("종목 수 정상", len(prev) > 1000, f"{len(prev)}개")

print("\n[10] MICRO_CAP 파싱 폴백")
class F: pass
def parse(val, obj):
    if val is None: os.environ.pop("MICRO_CAP", None)
    else: os.environ["MICRO_CAP"] = val
    try:
        return max(1, int(os.environ.get("MICRO_CAP", "200")))
    except (TypeError, ValueError):
        obj._w = getattr(obj, "_w", 0) + 1
        return 200
o = F()
check("정상값 150 → 150", parse("150", o) == 150)
check("미설정 → 200", parse(None, o) == 200)
check("잘못된 값 → 200 폴백(죽지 않음)", parse('"200"', o) == 200)
check("공백 → 200 폴백", parse("", o) == 200)
os.environ.pop("MICRO_CAP", None)
gw = open(os.path.join(RUN, "broker_gateway_v1.py"), encoding="utf-8").read()
check("게이트웨이에 try/except 배선됨", "_micro_cap_warned" in gw)

print("\n[11] 전체 단위테스트 묶음")
paths = sorted(glob.glob(r"C:\stock_bot\tests\test_*.py"))
ok_n = bad_n = 0; bad_names = []
for path in paths:
    b = io.StringIO()
    try:
        with contextlib.redirect_stderr(b), contextlib.redirect_stdout(b):
            runpy.run_path(path, run_name="__main__")
    except SystemExit:
        pass
    except Exception as e:
        bad_n += 1; bad_names.append(f"{os.path.basename(path)}({type(e).__name__})"); continue
    lines = [l for l in b.getvalue().strip().splitlines() if l.strip()]
    v = next((l for l in reversed(lines) if l.startswith(("OK", "FAILED"))), "?")
    if v.startswith("OK"): ok_n += 1
    else: bad_n += 1; bad_names.append(os.path.basename(path))
check(f"테스트 파일 {len(paths)}개 전부 통과", bad_n == 0, f"통과 {ok_n} / 실패 {bad_n}" + (f" → {bad_names}" if bad_names else ""))

total = len(results); passed = sum(1 for _n, o, _d in results if o)
print("\n" + "=" * 62)
print(f"최종: 검증 {total}건 중 통과 {passed} / 실패 {total - passed}")
if total != passed:
    print("실패 목록:")
    for n, o, d in results:
        if not o: print(f"  ★ {n}  {d}")
print("=" * 62)
sys.exit(0 if total == passed else 1)
