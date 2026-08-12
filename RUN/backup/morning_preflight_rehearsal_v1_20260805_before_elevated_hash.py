# -*- coding: utf-8 -*-
"""아침 기동 리허설 — 08:30 자동 실행. 읽기 전용. 주문·깃발·TR 전부 0.

★왜 만들었나 (2026-08-05 친구님 지시)
  8/5 아침 S01 매수 0건. 원인 4건이 전부 "8/4 에 고친 것이 다음날 첫 기동에서만
  터진" 경우였다. 고친 날은 이미 떠 있던 프로세스가 옛 코드를 물고 있어 멀쩡해
  보이고, 다음날 08:28~08:59 에 새로 뜨면서 죽는다. 그때는 장이 열려 있어 고칠
  시간이 없다. 8/4 밤 테스트 388개가 통과했는데도 4건을 하나도 못 잡았다.

★이 검사가 잡는 것 (오늘 4건 전부 여기서 걸렸을 것)
  1) 진입점 sys.path 부트스트랩 누락  -> 기록기·중계판 즉사 (오늘 ③④)
  2) order_prefix 미등록              -> preflight 8ms 즉사 (오늘 ①)
  3) 산출물 갱신 정지                 -> 돈맥_1분봉·중계판 멈춤 감지
  4) 로그의 ModuleNotFoundError       -> 조용히 죽은 것 색출
  5) 문법 오류 / import 대상 실종
  6) 필수 태스크 비활성화

★안 하는 것: 실제 preflight 실행(깃발을 건드려 08:59 정규 절차를 깨뜨린다).
  브로커 조회(TR 0 유지). 엔진 모듈 import(최상단 코드가 돌아버린다).

되돌리기: 태스크 SAFEPLUS_MORNING_REHEARSAL 삭제 + 이 파일 삭제.
"""
from __future__ import annotations

import ast
import json
import re
import sys
import py_compile
from datetime import datetime
from pathlib import Path

# ★이 스크립트 자신도 부트스트랩이 필요하다(python._pth 때문). 없으면 아래
#   strategy_broker_live_guard import 에서 이 검사기가 먼저 죽는다.
RUN_DIR = Path(__file__).resolve().parent
if str(RUN_DIR) not in sys.path:
    sys.path.insert(0, str(RUN_DIR))

ROOT = Path(r"C:\stock_bot")
RUN = ROOT / "RUN"
DATA = ROOT / "data"
REPORT_DIR = ROOT / "보고서"
FAIL_FLAG = ROOT / "config" / "morning_rehearsal_fail.flag"

BOOT_RE = re.compile(r"sys\.path\.insert|sys\.path\.append")
IMP_RE = re.compile(
    r"^\s*(?:from\s+([A-Za-z_]\w*)\s+import|import\s+([A-Za-z_]\w*))", re.M)
PYCALL_RE = re.compile(r"python\.exe[^\r\n]*?([A-Za-z0-9_]+\.py)", re.I)
PREFIX_RE = re.compile(r"order_prefix\s*=\s*[\"']([A-Za-z0-9_]+)[\"']")

results: list[tuple[str, str, str]] = []   # (level, name, detail)


def add(level: str, name: str, detail: str) -> None:
    results.append((level, name, detail))


def local_modules() -> set[str]:
    return {p.stem for p in RUN.glob("*.py")}


def entry_points() -> dict[str, set[str]]:
    """.cmd 가 직접 실행하는 .py -> 그 .cmd 들"""
    out: dict[str, set[str]] = {}
    for cmd in RUN.rglob("*.cmd"):
        if "\\backup\\" in str(cmd):
            continue
        try:
            txt = cmd.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for m in PYCALL_RE.finditer(txt):
            out.setdefault(m.group(1), set()).add(cmd.name)
    return out


def check_syntax() -> None:
    bad = []
    for p in sorted(RUN.glob("*.py")):
        try:
            py_compile.compile(str(p), doraise=True, quiet=2)
        except Exception as exc:              # noqa: BLE001
            bad.append(f"{p.name}: {str(exc)[:90]}")
    if bad:
        add("FAIL", "문법", f"{len(bad)}개 - " + " | ".join(bad[:4]))
    else:
        add("PASS", "문법", f"RUN\\*.py 전부 통과")


def check_bootstrap(mods: set[str], entries: dict[str, set[str]]) -> None:
    bad = []
    for name in sorted(entries):
        p = RUN / name
        if not p.exists():
            continue
        src = p.read_text(encoding="utf-8", errors="replace")
        uses = {m.group(1) or m.group(2) for m in IMP_RE.finditer(src)}
        uses = {u for u in uses if u and u in mods and u != p.stem}
        if uses and not BOOT_RE.search(src):
            bad.append(f"{name}(<-{','.join(sorted(uses))[:40]})")
    if bad:
        add("FAIL", "sys.path 부트스트랩",
            f"진입점 {len(bad)}개 누락 - " + " | ".join(bad[:5]))
    else:
        add("PASS", "sys.path 부트스트랩", f"진입점 {len(entries)}개 정상")


def check_import_targets(mods: set[str]) -> None:
    missing = []
    for p in sorted(RUN.glob("*.py")):
        src = p.read_text(encoding="utf-8", errors="replace")
        for m in IMP_RE.finditer(src):
            n = m.group(1) or m.group(2)
            if not n or n == p.stem:
                continue
            # RUN 안 모듈처럼 생겼는데 파일이 없는 경우만
            if n.startswith(("strategy_", "ma3_", "captain2_", "broker_",
                             "approval_", "hold_sell_", "valley_")) \
                    and n not in mods:
                missing.append(f"{p.name} -> {n}")
    if missing:
        add("FAIL", "import 대상 실종",
            f"{len(missing)}건 - " + " | ".join(sorted(set(missing))[:4]))
    else:
        add("PASS", "import 대상", "전부 존재")


def check_prefix() -> None:
    try:
        from strategy_broker_live_guard import PREFIX_TO_STRATEGY
    except Exception as exc:                  # noqa: BLE001
        add("FAIL", "order_prefix", f"가드 import 실패: {exc}")
        return
    used: dict[str, set[str]] = {}
    for p in sorted(RUN.glob("*.py")):
        if "backup" in str(p):
            continue
        src = p.read_text(encoding="utf-8", errors="replace")
        for m in PREFIX_RE.finditer(src):
            used.setdefault(m.group(1), set()).add(p.name)
    bad = {k: v for k, v in used.items() if k not in PREFIX_TO_STRATEGY}
    if bad:
        detail = " | ".join(f"{k}({','.join(sorted(v))[:36]})"
                            for k, v in sorted(bad.items()))
        add("FAIL", "order_prefix 미등록",
            f"{len(bad)}개 - 가드가 조용히 전부 차단함 - {detail}")
    else:
        add("PASS", "order_prefix", f"사용 {len(used)}종 전부 등록됨")


def _age(path: Path) -> float | None:
    try:
        return (datetime.now()
                - datetime.fromtimestamp(path.stat().st_mtime)).total_seconds()
    except OSError:
        return None


def check_freshness() -> None:
    now = datetime.now()
    # 08:28 기록기 기동 후에만 의미가 있다
    if (now.hour, now.minute) < (8, 32):
        add("SKIP", "산출물 신선도", "08:32 이전이라 건너뜀")
        return
    targets = [("돈맥_1분봉.json", DATA / "돈맥_1분봉.json", 300)]
    bad, ok = [], []
    for label, p, limit in targets:
        a = _age(p)
        if a is None:
            bad.append(f"{label}: 파일없음")
        elif a > limit:
            bad.append(f"{label}: {a / 60:.0f}분째 정지")
        else:
            ok.append(f"{label}: {a:.0f}초")
    if bad:
        add("FAIL", "산출물 신선도", " | ".join(bad))
    else:
        add("PASS", "산출물 신선도", " | ".join(ok))


def check_logs() -> None:
    """★'마지막 출력이 실패인가'만 본다.

    처음엔 로그 전체에서 ModuleNotFoundError 를 찾았더니, 이미 고친 옛 흔적까지
    잡아 매일 FAIL 이 떴다. 그러면 결국 무시하게 되고 검사가 죽는다(8/5 실측:
    3건 전부 고치기 전 흔적이었고 마지막 줄은 다 정상이었다).
    지금은 마지막 비어있지 않은 6줄만 본다 = '지금도 죽어 있나'.
    """
    hits = []
    now = datetime.now()
    for p in list((DATA / "LOG").glob("*.log")) + list((ROOT / "LOG").glob("*.log")):
        try:
            # ★최근 20분 내에 쓰인 로그만 본다. 스크립트가 되살아나면 그 로그에는
            #   더 이상 아무것도 안 쓰이므로, 마지막 줄은 영원히 옛 에러로 남는다
            #   (8/5 실측: 기록기를 고쳤는데도 stderr 로그 마지막 줄은 계속 에러).
            #   기동 직후 죽으면 mtime 이 방금이라 정상적으로 잡힌다.
            age_min = (now - datetime.fromtimestamp(p.stat().st_mtime)).total_seconds() / 60
            if age_min > 20:
                continue
            raw = p.read_bytes()[-4000:].decode("utf-8", errors="replace")
        except OSError:
            continue
        tail = [ln for ln in raw.splitlines() if ln.strip()][-6:]
        mods = re.findall(r"ModuleNotFoundError: No module named .(\w+).",
                          "\n".join(tail))
        if mods:
            hits.append(f"{p.name}({','.join(sorted(set(mods))[:2])})")
    if hits:
        add("FAIL", "로그 import 오류",
            f"{len(hits)}개(마지막 출력이 실패) - " + " | ".join(hits[:5]))
    else:
        add("PASS", "로그 import 오류", "마지막 출력이 실패인 로그 없음")


def check_lowfind_contract() -> None:
    """★[계약 2026-08-05 친구님] 저점 찾는 법이 정한 값 그대로인지 대조.

    코드만 고치고 계약서를 안 고치면(또는 그 반대면) 여기서 걸린다.
    8/3 에 S03 만 개편되고 S02 가 안 따라간 일이 다시 없게 하는 장치다.
    """
    path = ROOT / "config" / "lowfind_contract_v1.json"
    try:
        c = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        add("FAIL", "저점찾기 계약", f"계약서를 못 읽음 ({exc})")
        return
    try:
        import importlib
        s2 = importlib.import_module("strategy_02_low_buy_signal_v1")
        s3 = importlib.import_module("골짜기_급반등")
        s6 = importlib.import_module("strategy_06_crash_low_chase_v1")
        c3, c6 = s3.RapidReboundConfig, s6.Config
    except Exception as exc:                   # noqa: BLE001
        add("FAIL", "저점찾기 계약", f"전략 모듈 import 실패: {exc}")
        return

    live = {
        "S02": {"1차반등문턱": s2.SIX_FIRST_REBOUND_PCT, "추격상한": s2.SIX_CHASE_CAP_PCT,
                "진입하한": s2.SIX_ENTRY_FLOOR_PCT, "눌림최소": s2.SIX_PULLBACK_MIN_PCT,
                "직전저점버퍼": s2.SIX_HIGHER_LOW_BUFFER_PCT,
                "2차반등": s2.SIX_SECOND_REBOUND_PCT, "재무장깊이": s2.SIX_REARM_DEEPER_PCT,
                "흐름가속창초": s2.SIX_FLOW_ACCEL_WINDOW_SEC,
                "관찰최대초": s2.SIX_OBSERVE_MAX_SEC, "관찰시간초": s2.SIX_OBSERVE_SEC},
        "S03": {"1차반등문턱": s3.FIRST_REBOUND_PCT, "추격상한": c3.chase_cap_pct,
                "진입하한": c3.entry_floor_pct, "눌림최소": s3.MIN_PULLBACK_PCT,
                "직전저점버퍼": s3.MIN_HIGHER_LOW_PCT,
                "2차반등": s3.MIN_SECOND_REBOUND_PCT, "재무장깊이": c3.rearm_deeper_pct,
                "흐름가속창초": c3.flow_accel_window_sec,
                "관찰최대초": c3.observe_max_sec, "관찰시간초": s3.MIN_OBSERVE_SEC},
        "S06": {"1차반등문턱": c6.rebound_pct, "추격상한": c6.chase_cap_pct,
                "진입하한": c6.entry_floor_pct, "눌림최소": c6.pullback_min_pct,
                "직전저점버퍼": c6.higher_low_buffer_pct,
                "2차반등": c6.second_rebound_pct, "재무장깊이": c6.rearm_deeper_pct,
                "흐름가속창초": c6.flow_accel_window_sec,
                "관찰최대초": c6.observe_max_sec, "관찰시간초": c6.observe_sec},
    }

    bad = []
    common = {k: v for k, v in c.get("공통값", {}).items() if not k.startswith("_")}
    for key, want in common.items():
        for sid in ("S02", "S03", "S06"):
            got = live[sid].get(key)
            if got is None or abs(float(got) - float(want)) > 1e-9:
                bad.append(f"{sid}.{key} 계약 {want} != 실제 {got}")

    base = {k: v for k, v in c.get("기본값", {}).items() if not k.startswith("_")}
    exc_map = c.get("인정된예외", {})
    for key, want in base.items():
        for sid in ("S02", "S03", "S06"):
            target = exc_map.get(sid, {}).get(key, want)
            got = live[sid].get(key)
            if got is None or abs(float(got) - float(target)) > 1e-9:
                tag = "예외값" if sid in exc_map and key in exc_map[sid] else "기본값"
                bad.append(f"{sid}.{key} {tag} {target} != 실제 {got}")

    obs = c.get("전략정체성", {}).get("관찰시간초", {})
    for sid in ("S02", "S03", "S06"):
        if sid not in obs:
            continue
        got = live[sid].get("관찰시간초")
        if got is None or abs(float(got) - float(obs[sid])) > 1e-9:
            bad.append(f"{sid}.관찰시간 계약 {obs[sid]} != 실제 {got}")

    if bad:
        add("FAIL", "저점찾기 계약",
            f"{len(bad)}건 어긋남 - " + " | ".join(bad[:5]))
    else:
        n = len(common) + len(base) + len(obs)
        add("PASS", "저점찾기 계약",
            f"S02·S03·S06 {n}개 항목 계약대로 (S06 예외 2건 포함)")


# ★[CONTRACT-GAP 2026-08-05] 상승보유 계약의 세 검사. check_sellhold_contract 가 부른다.
#   전부 ast 로 본다 - 문자열 검색은 주석에 남은 이름까지 잡아 거짓 경보를 낸다.

#   살아 있는 상승보유 경로만 본다. CAPTAIN2 는 은퇴한 엔진이라 뺀다
#   (거기엔 진짜 _load_daily_ma 가 아직 있지만 지금 매매에 관여하지 않는다).
_RIDER_FILES = (
    "strategy_01_rotation_engine_v2.py",
    "strategy_02_rotation_engine_v1.py",
    "strategy_03_rotation_engine_v1.py",
    "strategy_04_rotation_engine_v1.py",
    "strategy_05_rotation_engine_v1.py",
    "strategy_06_crash_low_chase_v1.py",   # ⚠️S06 만 이름이 다르다(rotation_engine 아님)
    "strategy_common_hold_sell_v1.py",
    "ma3_common_v1.py",
)


def _rider_trees() -> tuple[dict, list[str]]:
    """_RIDER_FILES 를 ast 로 읽어 {이름: 트리} 와 못 읽은 목록을 함께 돌려준다.

    ⚠️못 읽은 것을 조용히 건너뛰면 안 된다. 처음엔 그렇게 짰는데, 변조 시험에서
      파일을 문법 오류 나게 만들자 검사가 그냥 '통과'해버렸다(파일이 사라지거나
      이름이 바뀌어도 마찬가지다). 그래서 못 읽은 것 자체를 어긋남으로 올린다.
    """
    trees, unread = {}, []
    for name in _RIDER_FILES:
        path = ROOT / "RUN" / name
        try:
            trees[name] = ast.parse(path.read_text(encoding="utf-8"))
        except OSError:
            unread.append(f"{name} 없음")
        except SyntaxError as exc:
            unread.append(f"{name} 문법오류 {exc.lineno}행")
    return trees, unread


def _is_true_kw(node: ast.Call, arg: str) -> bool:
    return any(
        isinstance(k, ast.keyword) and k.arg == arg
        and isinstance(k.value, ast.Constant) and k.value.value is True
        for k in node.keywords)


def _check_ma20_call_sites(rider: dict) -> list[str]:
    """호출부에서 allow_ma20=True 로 뒤집는 전략이 계약서 '인정된예외' 와 같은가.

    ⚠️손실방어 전용 배선은 세면 안 된다. S02 는 ma20_defense_permit=<...allow_ma20=True>
      로 부르는데 그건 손실방어 국면 전용이라 '20선보유허용' 과 다른 항목이다.
      그래서 ma20_defense_permit= 에 대입되는 호출은 빼고 센다.
    """
    want = {
        sid for sid, v in (rider.get("인정된예외") or {}).items()
        if isinstance(v, dict) and v.get("20선보유허용")
    }
    trees, unread = _rider_trees()
    if unread:
        return [f"상승보유.인정된예외 - 파일을 못 읽어 검사 못 함: {', '.join(unread)}"]
    got: set[str] = set()
    for name, tree in trees.items():
        skip = {
            id(k.value) for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            for k in node.keywords
            if k.arg == "ma20_defense_permit" and isinstance(k.value, ast.Call)
        }
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and id(node) not in skip
                    and _is_true_kw(node, "allow_ma20")):
                m = re.match(r"strategy_(\d\d)_", name)
                got.add(f"S{m.group(1)}" if m else name)
                break
    if got != want:
        return [f"상승보유.인정된예외 계약 {sorted(want) or '없음'} "
                f"!= 실제 allow_ma20=True 로 부르는 전략 {sorted(got) or '없음'}"]
    return []


def _check_rising_hold_single_gate(want: bool) -> list[str]:
    """상승보유 판정이 daily_ma_permit '하나'인가 - 매수세 관문 우회가 없는가.

    COMMON_RISING_HOLD 를 내주는 if 를 찾아 그 조건식을 본다. 8/5 이전에는
    `if (daily_ma_permit or (ma10_support and ma20_rising)):` 였고 뒤쪽 가지가
    매수세를 안 봤다. 조건식이 BoolOp(or/and)면 그 우회가 돌아온 것이다.
    """
    trees, unread = _rider_trees()
    tree = trees.get("strategy_common_hold_sell_v1.py")
    if tree is None:
        return [f"상승보유.매수세관문우회금지 - 공용 매도엔진을 못 읽음"
                f" ({', '.join(unread) or '이유 불명'})"]
    hits = [
        node for node in ast.walk(tree) if isinstance(node, ast.If)
        and any(isinstance(s, ast.Constant) and s.value == "COMMON_RISING_HOLD"
                for s in ast.walk(node))
    ]
    if not hits:
        return ["상승보유.매수세관문우회금지 - COMMON_RISING_HOLD 분기를 못 찾음"]
    # 감싸는 if 도 같이 걸리므로 가장 안쪽(줄번호가 가장 큰 것)을 고른다.
    test = max(hits, key=lambda node: node.lineno).test
    single = isinstance(test, ast.Attribute) and test.attr == "daily_ma_permit"
    if single is not want:
        shape = type(test).__name__
        return [f"상승보유.매수세관문우회금지 계약 {want} != 실제 {single} "
                f"(조건식이 {shape} - 8/3 의 2단 판정을 우회하는 가지가 생겼다)"]
    return []


def _check_no_daily_bar_rider(want: bool) -> list[str]:
    """살아 있는 전략에 일봉 상승보유 경로가 없는가.

    이름이 주석에는 남아 있다(왜 지웠는지 적어 뒀다). 그래서 def 와 호출만 센다.
    """
    dead = ("_load_daily_ma", "_daily_ma_permit_legacy")
    trees, unread = _rider_trees()
    if unread:
        return [f"상승보유.일봉경로금지 - 파일을 못 읽어 검사 못 함: {', '.join(unread)}"]
    found: list[str] = []
    for name, tree in trees.items():
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name in dead:
                    found.append(f"{name}:{node.lineno} def {node.name}")
            elif isinstance(node, ast.Call):
                fn = node.func
                nm = fn.attr if isinstance(fn, ast.Attribute) else (
                    fn.id if isinstance(fn, ast.Name) else "")
                if nm in dead:
                    found.append(f"{name}:{node.lineno} {nm}() 호출")
    gone = not found
    if gone is not want:
        return [f"상승보유.일봉경로금지 계약 {want} != 실제 {gone} "
                f"({' / '.join(found[:3]) if found else '일봉 경로 없음'})"]
    return []


def check_sellhold_contract() -> None:
    """★[계약 2026-08-05 친구님 지시 "진행해"] 상승보유·매도가 정한 값 그대로인지 대조.

    저점 찾기 계약(lowfind)의 짝이다. 친구님 원칙 "매수·상승보유·매도 3개는
    변하면 안 된다" 중 나머지 둘을 여기서 잠근다.
    되돌리기: main() 에서 이 호출 한 줄을 빼면 끝.
    """
    path = ROOT / "config" / "sellhold_contract_v1.json"
    try:
        c = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        add("FAIL", "매도 계약", f"계약서를 못 읽음 ({exc})")
        return
    try:
        import importlib
        import inspect
        m = importlib.import_module("strategy_common_hold_sell_v1")
        ma3 = importlib.import_module("ma3_common_v1")
        cfg = m.HoldSellConfig()
        prof = m.STRATEGY_PROFILES
        SID = m.StrategyId
    except Exception as exc:                   # noqa: BLE001
        add("FAIL", "매도 계약", f"매도 엔진 import 실패: {exc}")
        return

    # 계약서 이름 -> 실제 설정 이름
    FIELD = {
        "꼭지무장수익": "common_peak_arm_return_pct",
        "꼭지되돌림": "common_peak_watch_drop_pct",
        "방어되돌림": "common_peak_defense_drop_pct",
        "꼭지점수": "common_peak_score",
        "방어점수": "common_peak_strict_score",
        "꼭지확인초": "common_peak_partial_confirm_sec",
        "손실방어확인초": "flow_reversal_confirm_sec",
        "이익방어확인초": "common_defense_confirm_sec",
        "매수회복확인초": "common_peak_recovery_confirm_sec",
    }
    # 계약서 전략 이름 -> StrategyId (S03 은 골짜기 경로라 id 가 다르다)
    SMAP = {
        "S01": "S01_OPEN_SURGE",
        "S02": "S02_LOW_BUY_SELL_EXHAUSTION",
        "S03": "VALLEY_MORNING_CRASH",
        "S04": "S04_PULLBACK",
        "S05": "S05_BASE_BREAKOUT",
    }

    bad = []
    n = 0
    for key, want in (c.get("공용값") or {}).items():
        if key.startswith("_"):
            continue
        attr = FIELD.get(key)
        if attr is None:
            bad.append(f"공용값.{key} 는 계약서에만 있고 대조할 설정이 없다")
            continue
        got = getattr(cfg, attr, None)
        n += 1
        if got is None or abs(float(got) - float(want)) > 1e-9:
            bad.append(f"공용.{key} 계약 {want} != 실제 {got}")

    for sid, want in (c.get("전략별손절") or {}).items():
        if sid.startswith("_"):
            continue
        p = prof.get(getattr(SID, SMAP.get(sid, ""), None)) if SMAP.get(sid) else None
        if p is None:
            bad.append(f"{sid} 전략 설정을 못 찾음")
            continue
        n += 2
        if abs(float(p.hard_stop_pct) - float(want["기본"])) > 1e-9:
            bad.append(f"{sid}.손절 계약 {want['기본']} != 실제 {p.hard_stop_pct}")
        if abs(float(p.strong_flow_hard_stop_pct) - float(want["매수우위"])) > 1e-9:
            bad.append(f"{sid}.매수우위손절 계약 {want['매수우위']} "
                       f"!= 실제 {p.strong_flow_hard_stop_pct}")

    for sid, want in (c.get("전략별스위치") or {}).items():
        if sid.startswith("_"):
            continue
        p = prof.get(getattr(SID, SMAP.get(sid, ""), None)) if SMAP.get(sid) else None
        if p is None:
            bad.append(f"{sid} 전략 설정을 못 찾음")
            continue
        n += 3
        if p.ma3_mode.value != want["선이탈매도"]:
            bad.append(f"{sid}.선이탈매도 계약 {want['선이탈매도']} != 실제 {p.ma3_mode.value}")
        if bool(p.profit_trail_enabled) is not bool(want["트레일"]):
            bad.append(f"{sid}.트레일 계약 {want['트레일']} != 실제 {p.profit_trail_enabled}"
                       " (트레일 매도 절대 금지 - 8/4 확정)")
        if bool(p.flow_reversal_exit_enabled) is not bool(want["수급역전"]):
            bad.append(f"{sid}.수급역전 계약 {want['수급역전']} "
                       f"!= 실제 {p.flow_reversal_exit_enabled}")

    rider = c.get("상승보유") or {}
    if "20선보유허용" in rider:
        n += 1
        try:
            got = inspect.signature(ma3.rider_permit).parameters["allow_ma20"].default
        except (AttributeError, KeyError, ValueError):
            got = None
        if got is None or bool(got) is not bool(rider["20선보유허용"]):
            bad.append(f"상승보유.20선보유허용 계약 {rider['20선보유허용']} != 실제 {got}")

    # ★[MA20-DEFENSE 2026-08-05] 손실방어 국면에서만 20선 지지를 보유로 인정한다.
    #   위 '20선보유허용' 은 rider_permit 의 기본값(=꼭지 국면)을 본다. 이건 그 짝으로
    #   '손실방어 국면에서 20선을 인정하는 배선이 살아 있나'를 본다.
    #   왜 두 개인가 — 친구님 정정이 "해제는 꼭지 상황에서만"이라 국면마다 답이 다르다.
    #   소스에서 확인한다: 손실방어 분기 안에 그 검사와 사유가 있어야 한다.
    if "손실방어20선보유" in rider:
        n += 1
        want_defense = bool(rider["손실방어20선보유"])
        try:
            src = (ROOT / "RUN" / "strategy_common_hold_sell_v1.py").read_text(
                encoding="utf-8")
        except OSError:
            src = ""
        # ⚠️부분 문자열로 보면 안 된다. 처음엔 `"COMMON_MA20_DEFENSE_HOLD" in src`
        #   로 썼는데, 사유를 `..._X` 로 바꿔도 그 안에 원래 이름이 들어 있어서
        #   검사가 통과해버렸다(변조 시험에서 실제로 안 잡혔다).
        #   따옴표와 쉼표까지 붙여 정확히 그 줄만 맞도록 한다.
        wired = (
            "if defensive_loss_setup and observation.ma20_defense_permit:" in src
            and '"COMMON_MA20_DEFENSE_HOLD",' in src
        )
        if wired is not want_defense:
            bad.append(f"상승보유.손실방어20선보유 계약 {want_defense} != 실제 {wired}")

    # ★[CONTRACT-GAP 2026-08-05 친구님 지시 "ⓐ로 해"] 아래 세 검사를 신설한다.
    #   왜 — 8/5 밤에 계약서를 다시 읽다가 계약서가 현실과 다른 것을 찾았다.
    #   계약서에는 "20선보유허용: false" 라 적혀 있는데 S01 은 호출부에서
    #   allow_ma20=True 로 뒤집고 있었고, 위 검사는 rider_permit 의 '기본값'만
    #   보기 때문에 그걸 못 잡았다. 값이 안 적힌 계약서보다 틀리게 적힌 계약서가
    #   더 나쁘다 - 다음 사람이 "20선은 안 준다"고 믿고 판단한다.
    #   ⚠️세 검사 모두 ast(파이썬이 코드를 읽는 방식)로 본다. 문자열 검색으로는
    #     주석에 적힌 이름과 진짜 코드를 구분하지 못한다(실제로 전부 주석에 남아 있다).

    if "인정된예외" in rider:
        n += 1
        bad += _check_ma20_call_sites(rider)

    if "매수세관문우회금지" in rider:
        n += 1
        bad += _check_rising_hold_single_gate(bool(rider["매수세관문우회금지"]))

    if "일봉경로금지" in rider:
        n += 1
        bad += _check_no_daily_bar_rider(bool(rider["일봉경로금지"]))

    want_t = ((c.get("시간청산") or {}).get("시각") or "").strip()
    if want_t:
        n += 1
        got_t = None
        try:
            got_t = prof[SID.S02_LOW_BUY_SELL_EXHAUSTION].force_exit_at.strftime("%H:%M")
        except Exception:                      # noqa: BLE001
            for attr in ("force", "force_exit", "time_exit_at"):
                v = getattr(prof[SID.S02_LOW_BUY_SELL_EXHAUSTION], attr, None)
                if v is not None and hasattr(v, "strftime"):
                    got_t = v.strftime("%H:%M")
                    break
        if got_t != want_t:
            bad.append(f"시간청산 계약 {want_t} != 실제 {got_t}")

    if bad:
        add("FAIL", "매도 계약", f"{len(bad)}건 어긋남 - " + " | ".join(bad[:5]))
    else:
        add("PASS", "매도 계약",
            f"공용·전략별·상승보유 {n}개 항목 계약대로")


def check_tasks() -> None:
    import subprocess
    required = [
        "SAFEPLUS_STRATEGY_ALL_PREFLIGHT", "SAFEPLUS_STRATEGY_COMMON_CONTEXT",
        "SAFEPLUS_STRATEGY01_SIGNAL", "SAFEPLUS_STRATEGY01_LIVE",
        "SAFEPLUS_STRATEGY02_SIGNAL", "SAFEPLUS_STRATEGY02_LIVE",
        "SAFEPLUS_STRATEGY03_SIGNAL", "SAFEPLUS_STRATEGY03_LIVE",
        "SAFEPLUS_PREFLIGHT_SELFTEST_HIGH", "SAFEPLUS_WATCHDOG_BROKER",
        "SAFEPLUS_DEEP_SIGNAL_REC", "SAFEPLUS_CAPTAIN2_BROADCAST",
    ]
    off = []
    for name in required:
        try:
            out = subprocess.run(
                ["schtasks", "/query", "/tn", name, "/fo", "list"],
                capture_output=True, text=True, errors="replace",
                timeout=20).stdout
        except Exception:                      # noqa: BLE001
            off.append(f"{name}(조회실패)")
            continue
        if not out.strip():
            off.append(f"{name}(없음)")
        elif re.search(r"(Disabled|사용 안 함|사용안함)", out):
            off.append(f"{name}(비활성)")
    if off:
        add("WARN", "필수 태스크", f"{len(off)}개 - " + " | ".join(off[:6]))
    else:
        add("PASS", "필수 태스크", f"{len(required)}개 전부 활성")


def main() -> int:
    started = datetime.now()
    check_syntax()
    mods = local_modules()
    entries = entry_points()
    check_bootstrap(mods, entries)
    check_import_targets(mods)
    check_prefix()
    check_freshness()
    check_logs()
    check_lowfind_contract()
    check_sellhold_contract()
    check_tasks()

    fails = [r for r in results if r[0] == "FAIL"]
    warns = [r for r in results if r[0] == "WARN"]
    verdict = "FAIL" if fails else ("WARN" if warns else "PASS")

    lines = [
        "=" * 72,
        f"아침 기동 리허설  {started:%Y-%m-%d %H:%M:%S}   판정: {verdict}",
        "=" * 72,
    ]
    for level, name, detail in results:
        mark = {"PASS": "  OK  ", "FAIL": "!!FAIL", "WARN": " WARN ",
                "SKIP": " skip "}[level]
        lines.append(f"{mark} {name:<22} {detail}")
    if fails:
        lines += ["", "★조치 필요 — 08:59 정규 사전점검 전에 고쳐야 한다."]
    body = "\n".join(lines)
    print(body)

    try:
        REPORT_DIR.mkdir(parents=True, exist_ok=True)
        (REPORT_DIR / f"아침점검_{started:%Y%m%d}.txt").write_text(
            body + "\n", encoding="utf-8")
        (REPORT_DIR / "아침점검_최신.json").write_text(json.dumps({
            "ts": started.isoformat(timespec="seconds"),
            "verdict": verdict,
            "results": [{"level": a, "name": b, "detail": c}
                        for a, b, c in results],
        }, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass

    # 실패 깃발 — 조용한 실패를 막는 장치. 소비자가 없어도 눈에 보인다.
    try:
        if fails:
            FAIL_FLAG.write_text(
                f"{started:%Y-%m-%d %H:%M:%S}\n"
                + "\n".join(f"{n}: {d}" for _, n, d in fails) + "\n",
                encoding="utf-8")
        elif FAIL_FLAG.exists():
            FAIL_FLAG.unlink()
    except OSError:
        pass

    # ★실패하면 화면에 띄운다. 8/5 사고의 핵심이 "조용한 실패"였다 — 태스크는
    #   result=0 으로 성공이라 찍는데 스크립트는 죽어 있었고 아무도 몰랐다.
    #   파일만 남기면 같은 함정에 다시 빠진다. 09:00 장 시작까지 30분 남은
    #   시점이라 이때 눈에 보여야 고칠 수 있다.
    #   --no-popup 으로 끌 수 있다(수동 점검·자동화용).
    if fails and "--no-popup" not in sys.argv:
        try:
            import ctypes
            msg = (f"아침 기동 리허설 실패 ({started:%H:%M})\n\n"
                   + "\n\n".join(f"[{n}]\n{d}" for _, n, d in fails[:4])
                   + "\n\n09:00 장 시작 전에 조치가 필요합니다.\n"
                     f"자세히: {REPORT_DIR}\\아침점검_{started:%Y%m%d}.txt")
            # 0x30 = MB_ICONWARNING, 0x1000 = MB_SYSTEMMODAL(항상 위)
            ctypes.windll.user32.MessageBoxW(
                None, msg, "SAFEPLUS 아침 점검 - 실패", 0x30 | 0x1000)
        except Exception:                      # noqa: BLE001
            pass

    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
