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
