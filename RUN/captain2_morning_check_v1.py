# -*- coding: utf-8 -*-
"""캡틴2 아침 자동점검 v1 — 2026-07-22 친구님 "내일 아침 확인할 것들 자동으로" 지시.

무엇을 확인하나 (7/22 밤 수술 6·7건의 아침 검증 항목):
  ① 브로커 부호체결(FID15) 실수신 — broker_journal.log의 [REAL-SIDE-VERIFY]
  ② 스냅샷에 실체결 4필드(buy_vol_cum 등) 실림 + 신선도
  ③ MF1S 전체시장 1초 캡처 가동 + 새 필드 헤더
  ④ 캡틴2 엔진 생존(락 신선도) + 오늘 기동 스탬프(crash log)
  ⑤ 캡틴2가 정확모드로 판정 중인지(이벤트 side_exact=1)

주문 0 · TR 0 · 파일 읽기만. 결과는 LOG와 바탕화면(캡틴2_아침점검.txt)에 기록.
태스크: SAFEPLUS_CAPTAIN2_MORNING_CHECK 월~금 09:06 + 10분 반복 3회(늦게 뜨는 항목 재확인).
"""
import csv
import json
import os
from datetime import datetime
from pathlib import Path

BASE = Path(r"C:\stock_bot")
TODAY = datetime.now().strftime("%Y%m%d")
NOW = datetime.now()

BROKER_LOG = BASE / "LOG" / "broker_journal.log"
SNAPSHOT = BASE / "IPC" / "live_micro_snapshot.json"
MF1S_CSV = BASE / "data" / "shadow" / "mf_1s_capture" / f"mf_1s_{TODAY}.csv"
C2_LOCK = BASE / "data" / "captain2.lock"
C2_LOG = BASE / "LOG" / "captain2_moneyflow.log"
C2_CRASH = BASE / "LOG" / "captain2_crash.log"
C2_EVENTS = BASE / "data" / "shadow" / f"captain2_events_{TODAY}.csv"

OUT_LOG = BASE / "data" / "LOG" / f"captain2_morning_check_{TODAY}.txt"
OUT_DESKTOP = Path(r"C:\Users\UserK\Desktop") / "캡틴2_아침점검.txt"

results = []  # (상태, 제목, 상세)


def check(ok, title, detail, pending=False):
    mark = "대기" if pending else ("정상" if ok else "문제")
    results.append((mark, title, detail))


def tail_lines(path: Path, max_bytes: int = 2_000_000):
    try:
        size = path.stat().st_size
        with path.open("rb") as fh:
            fh.seek(max(0, size - max_bytes))
            return fh.read().decode("utf-8-sig", errors="replace").splitlines()
    except Exception:
        return []


# ── ⓪ 매수차단·킬스위치 깃발 (7/22 사고: 깃발이 장중 내내 있어 골짜기·갑툭이 매수 전멸) ──
try:
    flags = []
    for f, desc in (("manual_buy_block.flag", "전 엔진 신규매수 차단"),
                    ("captain2_off.flag", "캡틴2 그림자 강등"),
                    ("valley_off.flag", "골짜기 그림자 강등"),
                    ("flat_off.flag", "최후FLAT 비활성")):
        if (BASE / "config" / f).exists():
            flags.append(f"{f}({desc})")
    if flags:
        check(False, "차단 깃발", "⚠️존재: " + " · ".join(flags)
              + " — 의도한 게 아니면 config에서 삭제해야 오늘 매수가 정상 작동")
    else:
        check(True, "차단 깃발", "없음 — 실전 매수 경로 열림")
except Exception as e:
    check(False, "차단 깃발", f"점검 실패: {e}")

# ── ① 브로커 FID15 실수신 ────────────────────────────────────────
try:
    lines = [ln for ln in tail_lines(BROKER_LOG) if "[REAL-SIDE-VERIFY]" in ln]
    today_tag = NOW.strftime("%Y-%m-%d")
    todays = [ln for ln in lines if today_tag in ln]
    if todays:
        check(True, "브로커 부호체결(FID15) 실수신", f"{len(todays)}건 확인 · 예: {todays[0][-120:]}")
    else:
        # 09:01 전이면 아직 정규장 체결 전일 수 있다
        pend = NOW.strftime("%H%M") < "0902"
        check(False, "브로커 부호체결(FID15) 실수신",
              "[REAL-SIDE-VERIFY] 오늘 로그 없음 — 브로커 수술(7/22) 미작동 의심. broker_journal.log 확인",
              pending=pend)
except Exception as e:
    check(False, "브로커 부호체결(FID15) 실수신", f"점검 실패: {e}")

# ── ② 스냅샷 4필드 + 신선도 ─────────────────────────────────────
try:
    snap = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    ts = datetime.fromisoformat(snap.get("ts"))
    age = (NOW - ts).total_seconds()
    codes = snap.get("codes") or {}
    with_side = sum(1 for v in codes.values() if isinstance(v, dict) and "buy_vol_cum" in v)
    fresh = age <= 60
    if fresh and with_side > 0:
        check(True, "스냅샷 실체결 4필드", f"{with_side}/{len(codes)}종목에 필드 존재 · 신선도 {age:.0f}초")
    elif not fresh:
        check(False, "스냅샷 실체결 4필드", f"스냅샷이 낡음({age:.0f}초 전) — 브로커/실시간 구독 확인")
    else:
        pend = NOW.strftime("%H%M") < "0902"
        check(False, "스냅샷 실체결 4필드",
              f"신선하지만 4필드 종목 0/{len(codes)} — 체결 이벤트 대기 중이거나 브로커 구코드", pending=pend)
except Exception as e:
    check(False, "스냅샷 실체결 4필드", f"점검 실패: {e}")

# ── ③ MF1S 전체시장 캡처 ────────────────────────────────────────
try:
    if not MF1S_CSV.exists():
        check(False, "MF1S 1초 캡처", f"오늘 파일 없음: {MF1S_CSV.name} — 태스크/캡처 확인")
    else:
        age = (NOW - datetime.fromtimestamp(MF1S_CSV.stat().st_mtime)).total_seconds()
        with MF1S_CSV.open(encoding="utf-8-sig") as fh:
            header = fh.readline()
        has_side = "buy_vol_cum" in header
        ok = age <= 120 and has_side
        check(ok, "MF1S 1초 캡처",
              f"갱신 {age:.0f}초 전 · 실체결 필드 {'있음' if has_side else '없음(헤더 확인 필요)'} · 크기 {MF1S_CSV.stat().st_size/1e6:.0f}MB")
except Exception as e:
    check(False, "MF1S 1초 캡처", f"점검 실패: {e}")

# ── ④ 캡틴2 생존 + 기동 스탬프 ──────────────────────────────────
try:
    alive = C2_LOCK.exists() and (NOW - datetime.fromtimestamp(C2_LOCK.stat().st_mtime)).total_seconds() <= 90
    stamp = ""
    for ln in tail_lines(C2_CRASH, 200_000):
        if "CAPTAIN2 기동" in ln and NOW.strftime("%Y-%m-%d") in ln:
            stamp = ln.strip()
    start_lines = [ln for ln in tail_lines(C2_LOG, 500_000)
                   if "CAPTAIN2 시작" in ln and NOW.strftime("%Y-%m-%d") in ln]
    started = bool(start_lines)
    # ★[7/22 실전전환] 모드 확인 — 킬스위치(captain2_off.flag) 존재 시엔 SHADOW가 '정상'
    mode = "LIVE" if any("live=True" in ln for ln in start_lines) else ("SHADOW" if started else "?")
    expect = "SHADOW" if (BASE / "config" / "captain2_off.flag").exists() else "LIVE"
    if alive and started:
        check(mode == expect, "캡틴2 엔진 생존",
              f"모드={mode}(기대={expect}) · 락 신선 · 오늘 기동 확인 · {stamp[-50:] if stamp else ''}"
              + ("" if mode == expect else " — 킬스위치/cmd 상태와 불일치, 확인 필요"))
    else:
        check(False, "캡틴2 엔진 생존",
              f"락 신선={alive} · 오늘 시작로그={started} — 태스크 SAFEPLUS_CAPTAIN2_SHADOW 확인")
except Exception as e:
    check(False, "캡틴2 엔진 생존", f"점검 실패: {e}")

# ── ⑤ 정확모드 판정 여부 ────────────────────────────────────────
try:
    if not C2_EVENTS.exists():
        check(False, "캡틴2 정확모드(side_exact)", "오늘 이벤트 CSV 아직 없음(추적 전이면 정상)", pending=True)
    else:
        exact = total = 0
        with C2_EVENTS.open(encoding="utf-8-sig") as fh:
            for r in csv.DictReader(fh):
                if "side_exact" in r:
                    total += 1
                    if str(r.get("side_exact")).strip() == "1":
                        exact += 1
        if total == 0:
            check(False, "캡틴2 정확모드(side_exact)", "이벤트 행 없음 — 추적 대기 중", pending=True)
        elif exact > 0:
            check(True, "캡틴2 정확모드(side_exact)", f"{exact}/{total}행 정확모드 — FID15 실체결로 판정 중")
        else:
            check(False, "캡틴2 정확모드(side_exact)",
                  f"{total}행 전부 틱룰 폴백 — 브로커 4필드 미수신 의심(①② 항목과 함께 볼 것)")
except Exception as e:
    check(False, "캡틴2 정확모드(side_exact)", f"점검 실패: {e}")

# ── 결과 기록 ───────────────────────────────────────────────────
bad = [r for r in results if r[0] == "문제"]
pend = [r for r in results if r[0] == "대기"]
head = ("✅ 전부 정상" if not bad and not pend
        else (f"❌ 문제 {len(bad)}건" + (f" · 대기 {len(pend)}건" if pend else "")) if bad
        else f"⏳ 대기 {len(pend)}건(다음 회차 재확인)")
lines_out = [
    f"════ 캡틴2 아침 자동점검 {NOW:%Y-%m-%d %H:%M:%S} ════",
    f"종합: {head}",
    "",
]
for mark, title, detail in results:
    icon = {"정상": "✅", "문제": "❌", "대기": "⏳"}[mark]
    lines_out.append(f"{icon} [{title}] {detail}")
lines_out.append("")
lines_out.append("(이 점검은 09:06부터 10분 간격 3회 자동 실행 — 마지막 회차 기준으로 판단)")
text = "\n".join(lines_out) + "\n"

OUT_LOG.parent.mkdir(parents=True, exist_ok=True)
with OUT_LOG.open("a", encoding="utf-8-sig") as fh:
    fh.write(text + "\n")
try:
    OUT_DESKTOP.write_text(text, encoding="utf-8-sig")
except Exception:
    pass
print(text)
