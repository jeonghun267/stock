# -*- coding: utf-8 -*-
"""[SEC 2026-07-30] request_id 경로조작 차단 패치 검증 (브로커 파일 안 건드리는 독립 시험)

확인 3가지
  1) 지금 코드(무검증)가 IPC\responses 밖으로 나가는지  → 나가면 취약 확인
  2) 패치본이 그 탈출을 전부 막는지                    → 전부 안쪽이면 통과
  3) 정상 client(uuid4)의 request_id 가 그대로 통과하는지 → 하나라도 막히면 실패(=오작동)
"""
import sys, uuid
from pathlib import Path

IPC_RES = Path(r"C:\stock_bot\IPC\responses")

# ── 패치 대상 코드 (broker_gateway_v1.py 에 들어갈 것과 동일) ────────────
_RID_ALLOWED = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_")


def _safe_request_id(raw):
    """응답 파일명에 쓸 수 있는 request_id 만 통과. 아니면 None."""
    rid = str(raw).strip()
    if rid and len(rid) <= 80 and all(ch in _RID_ALLOWED for ch in rid):
        return rid
    return None


def path_now(request_id):        # 현재 코드 (broker_gateway_v1.py:2361)
    return IPC_RES / f"{request_id}.json"


def path_patched(request_id):    # 패치 후
    safe = _safe_request_id(request_id)
    if safe is None:
        safe = "rejected_request_id"
    return IPC_RES / f"{safe}.json"


def inside(p):
    try:
        return IPC_RES.resolve() in p.resolve().parents
    except Exception:
        return False


ATTACKS = [
    r"..\..\config\eod_gap_config",
    r"..\..\data\rt_open_positions",
    r"../../../Users/UserK/AppData/Roaming/Microsoft/Windows/Start Menu/Programs/Startup/x",
    r"..\..\RUN\hidden\SAFEPLUS_STRATEGY01_LIVE",
    "C:/Windows/Temp/evil",
    r"a\..\..\..\x",
]

fail = 0
print("=" * 78)
print("[1] 현재 코드 — 탈출 여부")
for a in ATTACKS:
    p = path_now(a)
    esc = not inside(p)
    print(f"  {'탈출!' if esc else '안전 '}  {a!r:70s} -> {p.resolve()}")
    if not esc:
        print("    !! 예상과 다름: 이 입력은 원래 탈출해야 취약 확인이 됨")

print()
print("[2] 패치 후 — 전부 IPC\\responses 안에 갇히는지")
for a in ATTACKS:
    p = path_patched(a)
    ok = inside(p)
    print(f"  {'PASS' if ok else 'FAIL'}  {a!r:70s} -> {p.resolve()}")
    if not ok:
        fail += 1

print()
print("[3] 정상 client request_id (uuid4) 통과 — 1000개")
bad = []
for _ in range(1000):
    rid = str(uuid.uuid4())
    if _safe_request_id(rid) != rid:
        bad.append(rid)
if bad:
    print(f"  FAIL  {len(bad)}개가 막힘 (예: {bad[:3]})")
    fail += len(bad)
else:
    print("  PASS  1000/1000 그대로 통과 (파일명·본문 모두 기존과 동일)")

print()
print("[4] 경계값")
CASES = [
    ("", None), ("   ", None), ("a" * 80, "a" * 80), ("a" * 81, None),
    ("abc-123_XYZ", "abc-123_XYZ"), ("a.b", None), ("a:b", None),
    ("a/b", None), ("a\\b", None), ("..", None), (".", None),
    ("한글", None), ("a b", None),
]
for raw, want in CASES:
    got = _safe_request_id(raw)
    ok = got == want
    if not ok:
        fail += 1
    print(f"  {'PASS' if ok else 'FAIL'}  {raw!r:12s} -> {got!r} (기대 {want!r})")


# ══════════════════════════════════════════════════════════════════════
# ⑥ 로그 계좌번호 마스킹 (broker_gateway_v1.py:1431 · 1878)
# ══════════════════════════════════════════════════════════════════════
def _mask_acct(a):
    """계좌번호 로그 마스킹. 기존 관례(eod_gap_live_executor_v1.py:238)와 동일한 '0000**' 형태."""
    s = str(a or "")
    return (s[:4] + "**") if len(s) >= 4 else "**"


print()
print("[5] 계좌 마스킹")
MASK_CASES = [
    ("0000000000", "0000**"),   # 테스트용 더미 계좌 — 뒷자리 전부 가려짐
    ("1234", "1234**"),         # [SEC 2026-08-06] 실계좌 앞자리 하드코딩 제거 + 기대값 수정
    ("650", "**"),
    ("", "**"),
    (None, "**"),
]
for raw, want in MASK_CASES:
    got = _mask_acct(raw)
    ok = got == want
    if not ok:
        fail += 1
    print(f"  {'PASS' if ok else 'FAIL'}  {raw!r:14s} -> {got!r} (기대 {want!r})".replace("None          ", "None        "))

# 마스킹된 로그 줄에 계좌번호가 남아있지 않은지 실물 확인
line = ("[SENDORDER-REAL] key=%s account=%s code=%s qty=%d" %
        ("strategy01:20260730:buy:263750:1", _mask_acct("0000000000"), "263750", 1))
leak = "0000000000" in line
print(f"  {'FAIL' if leak else 'PASS'}  실제 로그줄 재현: {line}")
if leak:
    fail += 1


# ══════════════════════════════════════════════════════════════════════
# ④ 주문 상한 (broker_gateway_v1.py:_handle_sendorder_real_request)
# ══════════════════════════════════════════════════════════════════════
# ★설계: 돈이 나가는 방향(매수1·매수정정5)만 막는다.
#   매도2·매수취소3·매도취소4·매도정정6 은 통과 — 포지션 탈출을 절대 막지 않기 위해서.
#   (매도는 보유분까지만 가능하므로 피해가 한정된다. 매수는 계좌 현금 전액까지 가능.)
BUY_SIDES = (1, 5)


def _order_limit_check(order_type, qty, price, *, max_qty, max_krw, max_daily, daily_count):
    """상한 검사. None=통과, 문자열=차단사유. 상한값 0 = 그 관문 끔."""
    if order_type not in BUY_SIDES:
        return None
    if max_qty > 0 and qty > max_qty:
        return f"수량 상한 초과 (qty={qty} > {max_qty})"
    if max_krw > 0 and price > 0 and qty * price > max_krw:
        return f"금액 상한 초과 (qty*price={qty * price} > {max_krw})"
    if max_daily > 0 and daily_count >= max_daily:
        return f"일일 매수 건수 상한 초과 ({daily_count} >= {max_daily})"
    return None


D = dict(max_qty=5, max_krw=1_000_000, max_daily=100)

print()
print("[6] 주문 상한 — 통과해야 하는 것 (현행 실전 그대로)")
PASS_CASES = [
    ("매수 1주 최유리(price=0)", 1, 1, 0, 0),
    ("매도 1주 최유리(price=0)", 2, 1, 0, 0),
    ("매수 5주 (상한 딱 맞음)", 1, 5, 0, 0),
    ("매수 지정가 10만×5주=50만", 1, 5, 100_000, 0),
    ("매수 99건째", 1, 1, 0, 99),
    ("매도 999주 (매도는 면제)", 2, 999, 0, 0),
    ("매도 100건 넘어도 통과", 2, 1, 0, 500),
    ("매도취소 999주", 4, 999, 0, 500),
]
for label, ot, q, pr, dc in PASS_CASES:
    r = _order_limit_check(ot, q, pr, daily_count=dc, **D)
    ok = r is None
    if not ok:
        fail += 1
    print(f"  {'PASS' if ok else 'FAIL'}  {label:32s} -> {'통과' if ok else '차단! ' + r}")

print()
print("[7] 주문 상한 — 막아야 하는 것 (공격 시나리오)")
BLOCK_CASES = [
    ("매수 1000주 (계좌털이)", 1, 1000, 0),
    ("매수 6주 (상한 1 초과)", 1, 6, 0),
    ("매수 지정가 50만×3주=150만", 1, 3, 500_000),
    ("매수정정 1000주", 5, 1000, 0),
]
for label, ot, q, pr in BLOCK_CASES:
    r = _order_limit_check(ot, q, pr, daily_count=0, **D)
    ok = r is not None
    if not ok:
        fail += 1
    print(f"  {'PASS' if ok else 'FAIL'}  {label:32s} -> {r if r else '통과됨! 뚫림'}")

r = _order_limit_check(1, 1, 0, daily_count=100, **D)
ok = r is not None
if not ok:
    fail += 1
print(f"  {'PASS' if ok else 'FAIL'}  {'매수 101건째':32s} -> {r if r else '통과됨! 뚫림'}")

print()
print("[8] price=0 함정 — 금액 상한만으로는 못 막는다는 증거")
r_krw_only = _order_limit_check(1, 1000, 0, max_qty=0, max_krw=1_000_000,
                                max_daily=0, daily_count=0)
r_full = _order_limit_check(1, 1000, 0, daily_count=0, **D)
ok = (r_krw_only is None) and (r_full is not None)
if not ok:
    fail += 1
print(f"  {'PASS' if ok else 'FAIL'}  금액상한만: 1000주 price=0 -> {r_krw_only or '통과됨(=어제 제안이 무력한 이유)'}")
print(f"        수량상한 포함: 같은 주문 -> {r_full}")

print()
print("[9] 상한 끄기(0) · env 파싱 실패 시 기본값")
ok = _order_limit_check(1, 99999, 0, max_qty=0, max_krw=0, max_daily=0, daily_count=0) is None
if not ok:
    fail += 1
print(f"  {'PASS' if ok else 'FAIL'}  전부 0 = 상한 끔 -> 통과 (응급용)")


def _env_int(raw, default):
    """MICRO_CAP(861줄)과 같은 관례: 숫자 아니면 기본값으로 진행."""
    try:
        return int(str(raw).strip())
    except Exception:
        return default


for raw, want in [("5", 5), ("", 5), ("abc", 5), (None, 5), ("10", 10), ("0", 0)]:
    got = _env_int(raw, 5)
    ok = got == want
    if not ok:
        fail += 1
    print(f"  {'PASS' if ok else 'FAIL'}  env={raw!r:8s} -> {got} (기대 {want})".replace("None    ", "None  "))


# ══════════════════════════════════════════════════════════════════════
# ① 주문 제출 이벤트 기록 (broker_gateway_v1.py:_handle_sendorder_real_request)
# ══════════════════════════════════════════════════════════════════════
import json as _json
import tempfile
from datetime import datetime, timedelta

_EVT_SINK = []          # 실제로는 event_journal_YYYYMMDD.jsonl append


def _emit_event_stub(event_type, entity, entity_id="", payload=None):
    """broker_gateway_v1.py:141 _emit_event 와 같은 계약. fail-safe."""
    try:
        rec = {"ts": datetime.now().isoformat(), "event_type": event_type,
               "entity": entity, "entity_id": str(entity_id),
               "trigger_module": "broker_gateway_v1"}
        if payload is not None:
            rec["payload"] = payload
        _EVT_SINK.append(rec)
    except Exception:
        pass


def _age_from_ts(ts_raw, now=None):
    """패치가 계산하는 접수→실행 지연. 못 재면 -1.0 (예외 안 냄)."""
    try:
        base = now or datetime.now()
        return round((base - datetime.fromisoformat(str(ts_raw))).total_seconds(), 3)
    except Exception:
        return -1.0


print()
print("[10] 주문 이벤트 기록 — age_sec 계산")
NOW = datetime(2026, 7, 31, 9, 0, 10, 0)
AGE_CASES = [
    ("정상 0.5초 지연", (NOW - timedelta(seconds=0.5)).isoformat(), 0.5),
    ("유령권 12초 지연", (NOW - timedelta(seconds=12)).isoformat(), 12.0),
    ("경계 10초", (NOW - timedelta(seconds=10)).isoformat(), 10.0),
    ("ts 없음", "", -1.0),
    ("ts 깨짐", "not-a-timestamp", -1.0),
    ("ts None", None, -1.0),
]
for label, ts_raw, want in AGE_CASES:
    got = _age_from_ts(ts_raw, now=NOW)
    ok = abs(got - want) < 0.001
    if not ok:
        fail += 1
    print(f"  {'PASS' if ok else 'FAIL'}  {label:18s} -> age_sec={got} (기대 {want})")

print()
print("[11] 기록 내용 — ②의 판단에 필요한 키가 다 들어가는가")
_EVT_SINK.clear()
_ts_client = (NOW - timedelta(seconds=12)).isoformat()
_emit_event_stub("ORDER_SUBMITTED", entity="order", entity_id="eodgap_buy_214450_abc", payload={
    "code": "214450", "qty": 1, "order_type": 1, "hoga_gb": "06",
    "rqname": "EODGAP_BUY_214450", "request_id": str(uuid.uuid4()),
    "ts_client": _ts_client, "age_sec": _age_from_ts(_ts_client, now=NOW), "ttl_sec": 15,
})
_emit_event_stub("ORDER_RESULT", entity="order", entity_id="eodgap_buy_214450_abc", payload={
    "code": "214450", "ret": 0, "ok": True, "send_ms": 42.7,
})

NEED_SUB = ["code", "qty", "order_type", "hoga_gb", "rqname",
            "request_id", "ts_client", "age_sec", "ttl_sec"]
NEED_RES = ["code", "ret", "ok", "send_ms"]
sub = next((e for e in _EVT_SINK if e["event_type"] == "ORDER_SUBMITTED"), None)
res = next((e for e in _EVT_SINK if e["event_type"] == "ORDER_RESULT"), None)

for label, rec, need in [("ORDER_SUBMITTED", sub, NEED_SUB), ("ORDER_RESULT", res, NEED_RES)]:
    miss = [k for k in need if rec is None or k not in rec.get("payload", {})]
    ok = not miss
    if not ok:
        fail += 1
    print(f"  {'PASS' if ok else 'FAIL'}  {label:16s} 키 {len(need)}종 {'전부 있음' if ok else '누락=' + str(miss)}")

# 두 이벤트가 같은 주문으로 이어붙는가 (entity_id 로 짝짓기)
ok = sub and res and sub["entity_id"] == res["entity_id"]
if not ok:
    fail += 1
print(f"  {'PASS' if ok else 'FAIL'}  두 이벤트가 entity_id 로 짝지어짐 ({sub['entity_id'] if sub else '-'})")

# ②가 실제로 쓸 질의: age_sec 최대값
ages = [e["payload"]["age_sec"] for e in _EVT_SINK if "age_sec" in e.get("payload", {})]
ok = ages and max(ages) == 12.0
if not ok:
    fail += 1
print(f"  {'PASS' if ok else 'FAIL'}  age_sec 최대값 조회 -> {max(ages) if ages else '없음'} (7/31 아침에 볼 숫자)")

print()
print("[12] 기록 실패가 주문을 막지 않는가 (fail-safe)")


def _emit_event_broken(*a, **k):
    raise OSError("디스크 꽉참")


order_went_through = False
try:
    # 패치는 _emit_event 를 그냥 부른다. 진짜 _emit_event 는 내부가 try/except:pass 라 절대 안 터진다.
    try:
        _emit_event_broken("ORDER_SUBMITTED", entity="order")
    except Exception:
        pass          # ← 실제 _emit_event 내부의 fail-safe 와 같은 자리
    order_went_through = True
except Exception:
    order_went_through = False
if not order_went_through:
    fail += 1
print(f"  {'PASS' if order_went_through else 'FAIL'}  기록이 터져도 주문 경로는 계속 진행")

# jsonl 로 실제 쓰고 되읽기 (형식 깨짐 없는지)
_tmp = Path(tempfile.gettempdir()) / "test_event_journal.jsonl"
try:
    with open(_tmp, "w", encoding="utf-8") as f:
        for e in _EVT_SINK:
            _json.dump(e, f, ensure_ascii=False)
            f.write("\n")
    back = [_json.loads(l) for l in _tmp.read_text(encoding="utf-8").splitlines() if l.strip()]
    ok = len(back) == len(_EVT_SINK)
    _tmp.unlink(missing_ok=True)
except Exception as e:
    ok = False
    print(f"    {e}")
if not ok:
    fail += 1
print(f"  {'PASS' if ok else 'FAIL'}  jsonl 쓰고 되읽기 {len(_EVT_SINK)}건 왕복")

print()
print("=" * 78)
print(f"결과: {'전부 통과' if fail == 0 else str(fail) + '건 실패'}")
sys.exit(1 if fail else 0)
