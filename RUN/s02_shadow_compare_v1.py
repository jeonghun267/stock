# -*- coding: utf-8 -*-
"""S02 저점찾기 그림자 비교 보고 — 매일 15:45 자동. 읽기 전용, 주문 0.

비교 대상 (전부 같은 실시간 자료를 읽는다)
  실전   하한 1.0 · 상한 1.5 · 관찰 60초 · 수급 ON
  A      하한 0.5 · 상한 1.5 · 관찰  0초 · 수급 ON
  B      하한 0.5 · 상한 1.5 · 관찰  0초 · 수급 OFF (가격만)
  C      낙폭 구간별 사다리   · 관찰  0초 · 수급 ON

핵심 지표 = entry_gap_pct (저점 대비 몇 % 위에서 잡았나). 낮을수록 저점에 가깝다.
※ 이건 '신호가 난 자리'다. 실제 체결·수익은 별개다.

3거래일치가 모이면 한 번만 화면으로 알린다(그 뒤엔 파일로만).
되돌리기: schtasks /delete /tn SAFEPLUS_S02_SHADOW_REPORT /f
"""
from __future__ import annotations

import csv
import glob
import statistics as st
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

RUN_DIR = Path(__file__).resolve().parent
if str(RUN_DIR) not in sys.path:
    sys.path.insert(0, str(RUN_DIR))

DATA = Path(r"C:\stock_bot\data")
REPORT_DIR = Path(r"C:\stock_bot\보고서")
DONE_MARK = DATA / "_s02_shadow_3day_reported.flag"

PATHS = [
    ("실전", DATA / "strategy_02_signal_v1"),
    ("A 고정", DATA / "shadow_s02_A"),
    ("B 가격만", DATA / "shadow_s02_B"),
    ("C 사다리", DATA / "shadow_s02_C"),
]


def num(v, d=None):
    try:
        return float(str(v).replace(",", "").strip())
    except (TypeError, ValueError):
        return d


def load(dirpath: Path):
    """{날짜: [행,...]}"""
    out = defaultdict(list)
    # ★같은 파일을 두 번 읽지 않는다(처음엔 두 glob 이 겹쳐 실전 신호가 2배로 세졌다)
    files = sorted(set(glob.glob(str(dirpath / "*.csv"))))
    for f in files:
        p = Path(f)
        day = "".join(ch for ch in p.stem if ch.isdigit())[-8:]
        if len(day) != 8:
            continue
        try:
            rows = list(csv.DictReader(
                p.read_text(encoding="utf-8-sig", errors="replace").splitlines()))
        except OSError:
            continue
        for r in rows:
            gap = num(r.get("entry_gap_pct"))
            if gap is None:
                continue
            out[day].append({
                "ts": (r.get("ts") or "")[11:19],
                "name": r.get("name") or r.get("code") or "",
                "gap": gap,
                "drop": num(r.get("dip_drop_pct"), 0.0) or 0.0,
                "price": num(r.get("price"), 0.0) or 0.0,
                "low": num(r.get("anchor_low"), 0.0) or 0.0,
            })
    return out


def main() -> int:
    now = datetime.now()
    data = {name: load(d) for name, d in PATHS}
    days = sorted({d for v in data.values() for d in v})

    L = []
    L.append("=" * 78)
    L.append(f"S02 저점찾기 그림자 비교   {now:%Y-%m-%d %H:%M}")
    L.append("=" * 78)
    L.append("지표 = entry_gap_pct (저점 대비 몇 % 위에서 신호가 났나). 낮을수록 저점에 가깝다.")
    L.append("")
    L.append(f"수집된 거래일 {len(days)}일: {', '.join(days) if days else '없음'}")
    L.append("")
    L.append("경로        신호수   저점대비 평균   중앙값    최저     최고   낙폭평균")
    L.append("-" * 78)
    for name, _ in PATHS:
        rows = [r for v in data[name].values() for r in v]
        if not rows:
            L.append(f"  {name:<10} {0:>5}       (신호 없음)")
            continue
        g = [r["gap"] for r in rows]
        dr = [r["drop"] for r in rows if r["drop"]]
        L.append(f"  {name:<10} {len(rows):>5}   {sum(g)/len(g):>+9.3f}%  "
                 f"{st.median(g):>+7.3f}% {min(g):>+7.3f}% {max(g):>+7.3f}%   "
                 f"{(sum(dr)/len(dr) if dr else 0):>6.2f}%")
    L.append("")

    if len(days) > 1:
        L.append("날짜별 신호 수")
        L.append("  날짜        " + "".join(f"{n:<11}" for n, _ in PATHS))
        for d in days:
            L.append(f"  {d}    " + "".join(f"{len(data[n].get(d, [])):<11}" for n, _ in PATHS))
        L.append("")

    last = days[-1] if days else None
    if last:
        L.append(f"[{last}] 신호 상세 (경로별 앞 8건)")
        for name, _ in PATHS:
            rows = sorted(data[name].get(last, []), key=lambda r: r["ts"])
            L.append(f"  --- {name} ({len(rows)}건)")
            for r in rows[:8]:
                L.append(f"      {r['ts']}  {r['name'][:12]:<13} "
                         f"진입 {r['price']:>9,.0f}  저점 {r['low']:>9,.0f}  "
                         f"{r['gap']:>+7.3f}%  낙폭 {r['drop']:>5.2f}%")
            if not rows:
                L.append("      (없음)")
        L.append("")

    L.append("해석 도움말")
    L.append("  실전 대비 A 의 gap 이 낮으면  -> 하한/관찰을 푼 것이 저점에 더 붙었다는 뜻")
    L.append("  A 대비 B 의 gap 이 낮으면    -> 수급 확인이 진입을 늦추고 있다는 뜻")
    L.append("  A 대비 C 의 gap 이 낮으면    -> 낙폭 구간별 사다리가 유리하다는 뜻")
    L.append("  ※ 신호 수가 너무 적어지면 gap 이 낮아도 의미가 없다(못 사는 것과 같다)")

    body = "\n".join(L)
    print(body)
    try:
        REPORT_DIR.mkdir(parents=True, exist_ok=True)
        (REPORT_DIR / f"S02_그림자비교_{now:%Y%m%d}.txt").write_text(
            body + "\n", encoding="utf-8")
        (REPORT_DIR / "S02_그림자비교_최신.txt").write_text(
            body + "\n", encoding="utf-8")
    except OSError:
        pass

    # ★3거래일 판정은 '그림자 A' 기준이다. 실전은 8/5 이전 이력이 이미 있어서
    #   전체 날짜로 세면 첫날부터 3일을 넘겨 팝업이 미리 터진다.
    shadow_days = sorted(data.get("A 고정", {}))
    L.append("")
    L.append(f"그림자 수집일 {len(shadow_days)}일: "
             f"{', '.join(shadow_days) if shadow_days else '아직 없음'}")
    body = "\n".join(L)
    try:
        (REPORT_DIR / "S02_그림자비교_최신.txt").write_text(body + "\n", encoding="utf-8")
    except OSError:
        pass

    if len(shadow_days) >= 3 and not DONE_MARK.exists() and "--no-popup" not in sys.argv:
        try:
            import ctypes
            head = [ln for ln in L if ln.strip().startswith(("실전", "A ", "B ", "C ", "  실전", "  A", "  B", "  C"))]
            msg = (f"S02 저점찾기 그림자 3일치가 모였습니다 ({len(shadow_days)}일)\n\n"
                   + "\n".join(head[:6])
                   + f"\n\n자세히: {REPORT_DIR}\\S02_그림자비교_최신.txt")
            ctypes.windll.user32.MessageBoxW(
                None, msg, "SAFEPLUS S02 그림자 비교 - 3일치 완료", 0x40 | 0x1000)
            DONE_MARK.write_text(f"{now:%Y-%m-%d %H:%M}\n", encoding="utf-8")
        except Exception:                      # noqa: BLE001
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
