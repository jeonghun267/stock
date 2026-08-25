# -*- coding: utf-8 -*-
"""긴급 상태 점검판 — 한 방에 전부. 읽기 전용 (JSON은 복사본으로만 읽음, 8/10 교훈).

사용: C:\python310\python.exe -X utf8 C:\stock_bot\RUN\emergency_status_check_v1.py
만든 날: 2026-08-14 (아침 4겹 잠금 사건 후, 친구님 지시).
"""
import csv
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

BASE = Path(r"C:\stock_bot")
PY = r"C:\python310\python.exe"
TODAY = datetime.now().strftime("%Y%m%d")


def rj(path):
    """JSON을 복사본으로 읽는다 — 원본을 열면 엔진의 os.replace가 죽는다."""
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".json") as t:
            tmp = t.name
        shutil.copy2(path, tmp)
        with open(tmp, encoding="utf-8-sig") as f:
            data = json.load(f)
        os.unlink(tmp)
        return data
    except Exception:
        return None


def section(title):
    print()
    print("■ " + title)


def ok(label, good, detail=""):
    mark = "O" if good else "X"
    print(f"  [{mark}] {label}" + (f"  {detail}" if detail else ""))
    return good


def main():
    now = datetime.now()
    print(f"===== 긴급 점검판  {now:%Y-%m-%d %H:%M:%S} =====")
    problems = []

    # 1. 승인 관문 (해시)
    section("승인 관문 (파일 해시)")
    guard = BASE / "RUN" / "live_owner_approval_guard_v1.py"
    for s in ("S01", "S02", "S03", "S06"):
        r = subprocess.run([PY, "-X", "utf8", str(guard), "--strategy", s],
                           capture_output=True, text=True, timeout=30)
        if not ok(f"관문 {s}", r.returncode == 0,
                  (r.stdout or r.stderr).strip()[:60]):
            problems.append(f"관문 {s} FAIL")

    # 2. 플래그 (config)
    section("플래그 (config)")
    cfg = BASE / "config"
    for f in sorted(glob.glob(str(cfg / "*.flag"))):
        name = os.path.basename(f)
        body = ""
        try:
            body = open(f, encoding="utf-8", errors="replace").read().strip()[:50]
        except Exception:
            pass
        # 의도된 상시 OFF (은퇴/수동 전략) — 문제로 세지 않는다
        benign_off = {"captain2_off.flag", "valley_off.flag", "strategy_04_off.flag"}
        bad = (("_off." in name) or ("fail" in name.lower())) and name not in benign_off
        print(f"  [{'!' if bad else ' '}] {name}  {body}")
        if bad:
            problems.append(f"차단 플래그 존재: {name}")
    # 승인 플래그 유효성 (엔진과 같은 함수)
    sys.path.insert(0, str(BASE / "RUN"))
    try:
        from approval_settings_guard import legacy_daily_approval_valid, KST
        for n in ("01", "02", "03"):
            p = cfg / f"strategy_{n}_live_approved.flag"
            if p.exists():
                t = p.read_text(encoding="ascii", errors="ignore")
                valid = legacy_daily_approval_valid(t, datetime.now(KST))
                if not ok(f"승인 S{n} 유효", valid, repr(t.strip())[:50]):
                    problems.append(f"승인 S{n} 무효 형식")
            else:
                print(f"  [ ] 승인 S{n}: 파일 없음")
    except Exception as e:
        print(f"  (승인 검사 불가: {e})")

    # 3. 엔진 프로세스
    section("엔진 프로세스 (오늘 뜬 것)")
    ps = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "Get-WmiObject Win32_Process | Where-Object { $_.Name -match 'python' } | "
         "ForEach-Object { $_.ProcessId.ToString() + '|' + "
         "$_.ConvertToDateTime($_.CreationDate).ToString('HH:mm:ss') + '|' + "
         "($_.CommandLine -replace '\\|',' ') }"],
        capture_output=True, text=True, timeout=30)
    engines = 0
    for line in (ps.stdout or "").splitlines():
        parts = line.split("|", 2)
        if len(parts) < 3:
            continue
        pid, t, cmd = parts
        tag = None
        if "strategy_06" in cmd:
            tag = "S06"
        elif "strategy_0" in cmd and "engine" not in cmd and "SHADOW" not in cmd.upper():
            m = re.search(r"strategy_(\d\d)", cmd)
            tag = "S" + m.group(1) if m else None
        elif not cmd.strip():
            tag = "관리자권한(내용숨김)"
        if tag:
            engines += 1
            print(f"  PID {pid:>6}  {t}  {tag}")
    if engines == 0:
        print("  (전략 프로세스가 안 보임 — 관리자 권한이면 숨겨질 수 있음)")

    # 4. 일봉
    section("일봉 (eod_daily_bars)")
    eod = BASE / "data" / "eod_daily_bars.csv"
    last_date = ""
    try:
        # 뒤에서 몇 KB만 읽어 최신 날짜 추출 (123MB 전체 스캔 금지)
        with open(eod, "rb") as f:
            f.seek(max(0, os.path.getsize(eod) - 65536))
            tail = f.read().decode("utf-8", errors="replace")
        for line in tail.strip().splitlines()[1:]:
            d = line.split(",", 1)[0]
            if d.isdigit() and d > last_date:
                last_date = d
        mtime = datetime.fromtimestamp(os.path.getmtime(eod))
        fresh = last_date >= TODAY
        ok("일봉 최신일", fresh, f"{last_date} (파일 {mtime:%m-%d %H:%M})")
        if not fresh:
            problems.append(f"일봉이 {last_date}에 멈춤")
        # 당일 빈 껍데기 검사: 오늘 행이 있는데 장 마감 전이면 주의
        if last_date == TODAY and now.hour < 16:
            print("  [!] 오늘 행이 이미 있음 — 장중이면 빈 껍데기(고가=저가·거래량0)일 수 있음")
            print("      → 고저폭판이 이 행을 물면 후보 0건이 된다 (8/14 사건)")
    except Exception as e:
        problems.append("일봉 읽기 실패")
        print(f"  [X] 읽기 실패: {e}")

    # 5. 고저폭판 / 저점그림자
    section("고저폭판·저점그림자")
    t30 = rj(BASE / "data" / "common_high_range_top30.json") or {}
    cand = int(t30.get("candidate_count") or 0)
    src = str(t30.get("source_date") or "?")
    exp = str(t30.get("expected_source_date") or "?")
    if not ok("고저폭 TOP30 후보", cand > 0, f"{cand}건 (source {src} / 기대 {exp})"):
        problems.append("고저폭판 후보 0건")
    if src != exp and exp != "?":
        print(f"  [!] source_date({src}) != 기대({exp}) — 미래/과거 불일치")
        problems.append("고저폭판 날짜 불일치")
    sh = rj(BASE / "data" / "high_range_top5_low_shadow_state.json") or {}
    uni = len(sh.get("universe") or [])
    if not ok("저점그림자 universe", uni > 0, f"{uni}종목"):
        problems.append("저점그림자 universe 0")

    # 6. 그림자 신선도
    #   ★[2026-08-14] 종가매수 그림자가 8/12~8/14 3일간 멈춰 있었는데 아무도 몰랐다.
    #     원인은 일봉 결손(그림자가 계속 8/11 만 보고 "이미 기록됨"으로 건너뜀).
    #     그림자는 판단 근거를 쌓는 자산이다 — 멈추면 몇 주 뒤에야 표본 부족으로 안다.
    section("그림자 신선도")
    for label, path, datecol in (
            ("종가매수(eod_gap_track)",
             BASE / "data" / "shadow" / "eod_gap" / "eod_gap_track.csv", 0),
            ("S01 무눌림(above_open_rebreak)",
             BASE / "data" / "shadow" / f"strategy_01_above_open_rebreak_shadow_{TODAY}.csv", None),
            ("S02 봉전환(candle_block)",
             BASE / "data" / "shadow" / f"s02_candle_block_shadow_{TODAY}.csv", None)):
        try:
            if not path.exists():
                # 당일 파일형 그림자는 장 시작 전이면 없는 게 정상
                print(f"  [ ] {label}: 오늘 파일 아직 없음 (장 전이면 정상)")
                continue
            if datecol is None:
                n = sum(1 for _ in open(path, encoding="utf-8-sig")) - 1
                ok(label, n > 0, f"{n}행")
                if n <= 0:
                    problems.append(f"{label} 0행")
                continue
            last = ""
            with open(path, encoding="utf-8-sig", errors="replace") as f:
                next(f, None)
                for line in f:
                    v = line.split(",")[datecol].strip()[:8]
                    if len(v) == 8 and v.isdigit() and v > last:
                        last = v
            gap_ok = bool(last) and last >= TODAY
            if not ok(label, gap_ok, f"최신 {last or '?'}"):
                problems.append(f"{label} 최신 {last} (오늘 아님)")
        except OSError as e:
            print(f"  [X] {label}: 읽기 실패 {e}")

    # 7. 수집 상태
    section("수집 (done/heartbeat)")
    done = rj(BASE / "LOG" / "collect_eod.done") or {}
    st = str(done.get("status") or "?")
    ok("EOD 수집 status", st == "OK", f"{st}  done_at={str(done.get('done_at'))[:19]}")
    if st != "OK":
        problems.append(f"EOD 수집 {st}")

    # 결론
    print()
    print("=" * 46)
    if problems:
        print(f"결론: 문제 {len(problems)}건")
        for p in problems:
            print("  - " + p)
    else:
        print("결론: 전부 정상")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
