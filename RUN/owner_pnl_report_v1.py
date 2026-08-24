# -*- coding: utf-8 -*-
"""주인별 손익표 (읽기 전용 → 보고서 파일 생성만).

★[OWNER-PNL 2026-08-19 친구님 승인 "주인별 손익표 자동화"] 발단: 8/19 실측 —
하루 이익의 99.7%를 돈맥이 벌었는데, 체결 기록만으로는 주인이 안 보였다.
"어느 전략이 실제로 버는가"를 매일 쌓아야 5거래일 검증이 가능하다.

주인 판별 = LOG\broker_journal.log 의 SENDORDER-REAL 주문 key/rqname 접두어
(8/19 12종목 전건 판별 검증). 손익 = fills CSV 선입선출(FIFO) 왕복.
⚠️세금·수수료 반영 전 가격차 손익이다. 같은 종목을 두 주인이 같은 날 산 경우
먼저 판별된 주인으로 귀속된다(8/19 기준 중복 소유 0건).

출력: 보고서\주인별손익_YYYYMMDD.txt (그날 상세)
      보고서\주인별손익_이력.csv (하루 한 줄씩 누적 — 5거래일 집계용)
"""
from __future__ import annotations

import csv
import io
import json
import re
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:                              # noqa: BLE001
    pass

BASE = Path(r"C:\stock_bot")
LOG_DIR = BASE / "LOG"
REPORT_DIR = BASE / "보고서"

LABEL = {"mflow": "돈맥", "STRATEGY01": "S01", "STRATEGY02": "S02",
         "STRATEGY03": "S03", "STRATEGY04": "S04", "STRATEGY05": "S05",
         "STRATEGY06": "S06", "EODGAP": "종가매수"}


def owner_map(now: datetime) -> dict[str, str]:
    day_dash = now.strftime("%Y-%m-%d")
    key_re = re.compile(
        r"key=([A-Za-z0-9]+?)_(?:buy|sell|BUY|SELL)_?(\d{6})")
    rq_re = re.compile(r"rqname=([A-Z0-9]+)_[A-Z]*_?(\d{6})")
    owners: dict[str, str] = {}
    for path in sorted(LOG_DIR.glob("broker_journal.log*")):
        try:
            if datetime.fromtimestamp(path.stat().st_mtime).date() < now.date():
                continue
            with path.open(encoding="utf-8", errors="replace") as handle:
                for line in handle:
                    if day_dash not in line or "SENDORDER-REAL" not in line:
                        continue
                    matched = key_re.search(line) or rq_re.search(line)
                    if matched:
                        owners.setdefault(matched.group(2), matched.group(1))
        except OSError:
            continue
    return owners


def name_map() -> dict[str, str]:
    try:
        cache = json.loads(
            (BASE / "data" / "_code_name_cache.json").read_text(
                encoding="utf-8-sig"))
        return dict(cache.get("map") or {})
    except (OSError, ValueError):
        return {}


def main() -> int:
    now = datetime.now()
    today = now.strftime("%Y%m%d")
    fills_path = LOG_DIR / f"fills_{today}.csv"
    if not fills_path.exists():
        print(f"[owner-pnl] {fills_path.name} 없음 — 오늘 체결 0")
        return 0
    owners = owner_map(now)
    names = name_map()

    def who(code: str) -> str:
        return LABEL.get(owners.get(code, ""), "공통/기존")

    rows = []
    try:
        with fills_path.open(encoding="utf-8-sig", errors="replace",
                             newline="") as handle:
            for row in csv.reader(handle):
                if row and not row[0].startswith("ts") and len(row) >= 7:
                    rows.append(row)
    except OSError:
        return 0

    queues: dict[str, list] = defaultdict(list)
    trips: dict[str, list] = defaultdict(list)   # 주인 → [(수익액, 수익률, 보유분)]
    for row in rows:
        ts, code, _, _, otype, qty, px = row[:7]
        try:
            price = float(px)
            quantity = max(1, int(float(qty)))
        except ValueError:
            continue
        if "+" in otype or "매수" in otype:
            queues[code].append((ts, price, quantity))
        else:
            while quantity > 0 and queues[code]:
                buy_ts, buy_px, buy_qty = queues[code][0]
                matched = min(quantity, buy_qty)
                pnl = (price - buy_px) * matched
                pct = (price / buy_px - 1.0) * 100.0 if buy_px > 0 else 0.0
                hold_min = 0.0
                try:
                    hold_min = (datetime.fromisoformat(ts)
                                - datetime.fromisoformat(buy_ts)
                                ).total_seconds() / 60.0
                except ValueError:
                    pass
                trips[who(code)].append((pnl, pct, hold_min, code))
                if matched >= buy_qty:
                    queues[code].pop(0)
                else:
                    queues[code][0] = (buy_ts, buy_px, buy_qty - matched)
                quantity -= matched

    holding = [(who(c), c, q) for c, q in queues.items() if q]

    lines = ["=" * 64,
             f"주인별 손익표 {now:%Y-%m-%d %H:%M} (세금·수수료 전) [UNVERIFIED]",
             "=" * 64,
             f"{'주인':<8}{'왕복':>4}{'승':>4}{'금액(원)':>12}{'평균수익률':>10}{'평균보유(분)':>12}"]
    total = 0.0
    summary = []
    for owner, items in sorted(trips.items(),
                               key=lambda kv: -sum(t[0] for t in kv[1])):
        amount = sum(t[0] for t in items)
        wins = sum(1 for t in items if t[0] > 0)
        avg_pct = sum(t[1] for t in items) / len(items)
        avg_hold = sum(t[2] for t in items) / len(items)
        total += amount
        lines.append(f"{owner:<8}{len(items):>4}{wins:>4}{amount:>+12,.0f}"
                     f"{avg_pct:>+9.2f}%{avg_hold:>11.1f}")
        summary.append((owner, len(items), wins, round(amount),
                        round(avg_pct, 3)))
    lines.append("-" * 64)
    lines.append(f"{'합계':<8}{'':>8}{total:>+12,.0f}")
    if holding:
        lines.append("")
        lines.append("미청산 보유:")
        for owner, code, queue in sorted(holding):
            qty_sum = sum(q[2] for q in queue)
            lines.append(f"  {owner} {names.get(code, code)}({code}) "
                         f"{qty_sum}주 @{queue[0][1]:,.0f}")
    body = "\n".join(lines)
    print(body)

    try:
        REPORT_DIR.mkdir(parents=True, exist_ok=True)
        (REPORT_DIR / f"주인별손익_{today}.txt").write_text(
            body + "\n", encoding="utf-8")
        if now.hour < 15 or (now.hour == 15 and now.minute < 35):
            return 0  # 이력 CSV 는 마감 후(15:35+) 실행만 쓴다 — 부분 하루 오염 방지
        history = REPORT_DIR / "주인별손익_이력.csv"
        is_new = not history.exists()
        already = False
        if not is_new:
            with history.open(encoding="utf-8-sig", newline="") as handle:
                already = any(row and row[0] == today
                              for row in csv.reader(handle))
        if not already:
            with history.open("a", encoding="utf-8-sig", newline="") as handle:
                writer = csv.writer(handle)
                if is_new:
                    writer.writerow(
                        ["날짜", "주인", "왕복", "승", "금액", "평균수익률"])
                for owner, cnt, wins, amount, pct in summary:
                    writer.writerow([today, owner, cnt, wins, amount, pct])
    except OSError:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
