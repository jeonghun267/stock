# -*- coding: utf-8 -*-
"""상승보유 관문 일일 기록기 — 읽기 전용. 판정에 전혀 관여하지 않는다.

왜 만들었나 (2026-08-05 밤)
  "상승보유가 왜 안 켜지나"를 오늘 실전 감사기록으로 갈라봤더니
  ①선 지지에서 탈락 47%/42% ②매수세에서 탈락 32%/32% ③통과 22%/25% 였다.
  즉 선 지지를 통과한 것 중 약 60%를 매수세 관문이 떨어뜨린다 — 처음 잰 숫자다.
  그런데 "그 판단이 맞았나"는 오늘 표본(2건·1일)으로는 못 가렸다.
  중앙값 변화가 전부 1호가였고 S02 와 S05 가 반대 방향을 가리켰다.
  → 문턱을 손대기 전에 표본부터 쌓는다. 이 파일이 그 일을 한다.

무엇을 하나
  그날 감사기록(data\\audit\\hold_sell\\<날짜>)을 읽어 포지션마다 한 줄 남긴다.
  · 상승보유가 어디서 떨어졌나 (선 지지 / 매수세 / 통과)
  · 매수세 관문이 떨어뜨린 뒤 값이 실제로 어떻게 됐나 (+60초 중앙값 대조)

★스스로를 못 믿을 때를 대비한 자기검사
  기록된 daily_ma_permit 을 내 재구성이 재현하는지 매번 재서 같이 남긴다
  (`recon_pct`). 98% 미만이면 `trust=NO` 로 찍고 그 줄은 쓰지 말 것.
  오늘(8/5) 실측 재현율은 두 건 다 100.0% 였다.

한계 (정직 고지)
  · MA20 단계는 판정 못 한다 — `price >= ma20` 이 감사기록에 없다.
    5선/10선 지지만 "선 지지 있음"으로 센다. MA20 은 '지지없음'에 섞인다.
  · S06 는 공통 매도 엔진을 안 타서 감사기록이 없다.

사용: python rider_gate_daily_report_v1.py [YYYYMMDD]   (없으면 오늘)
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from statistics import median

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ma3_common_v1 import buy_side_alive  # noqa: E402

ROOT = Path(r"C:\stock_bot")
AUDIT = ROOT / "data" / "audit" / "hold_sell"
OUT = ROOT / "data" / "shadow" / "rider_gate_daily.csv"
COLUMNS = [
    "date", "strategy", "code", "ticks", "recon_pct", "trust",
    "stage_fail_pct", "flow_fail_pct", "pass_pct",
    "fwd60_pass", "fwd60_flowfail", "fwd60_gap",
    "entry", "peak", "last", "exit_reason",
]


def _number(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _stage_ok(observation) -> bool:
    """5선 또는 10선 지지. MA20 은 판정 불가라 여기 안 넣는다(위 한계 참조)."""
    if not observation.get("daily_ma5_broken"):
        return True
    return bool(observation.get("ma10_support"))


def _buy_side(observation):
    return buy_side_alive(
        _number(observation.get("buy_money_per_sec_10s")),
        _number(observation.get("buy_money_per_sec_30s")),
        _number(observation.get("sell_money_per_sec_10s")),
        _number(observation.get("sell_money_per_sec_30s")),
        _number(observation.get("sell_volume_per_sec_5s")),
        _number(observation.get("sell_volume_per_sec_previous_10s")),
    )


def _forward_pct(times, prices, index: int, seconds: int):
    """index 시점에서 seconds 초 뒤의 값 변화율(%). 자료가 끝나면 None."""
    target = times[index] + seconds
    for j in range(index + 1, len(times)):
        if times[j] >= target:
            return (prices[j] / prices[index] - 1) * 100
    return None


def analyse(path: Path) -> dict | None:
    rows = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if not rows:
        return None
    times = [datetime.fromisoformat(r["decision"]["observed_at"]).timestamp() for r in rows]
    prices = [float(r["decision"]["price"]) for r in rows]

    agree = 0
    stage_fail = flow_fail = passed = 0
    pass_idx: list[int] = []
    flow_fail_idx: list[int] = []
    for i, row in enumerate(rows):
        observation = row["observation"]
        gate1 = _stage_ok(observation)
        gate2 = _buy_side(observation) is True
        if gate1 and gate2:
            passed += 1
            pass_idx.append(i)
        elif gate1:
            flow_fail += 1
            flow_fail_idx.append(i)
        else:
            stage_fail += 1
        # 자기검사: 내 재구성이 엔진이 남긴 값을 재현하나
        if (gate1 and gate2) == bool(observation.get("daily_ma_permit")):
            agree += 1

    total = len(rows)
    recon = agree / total * 100

    def med(idxs):
        vals = [v for v in (_forward_pct(times, prices, i, 60) for i in idxs) if v is not None]
        return median(vals) if vals else None

    fwd_pass, fwd_fail = med(pass_idx), med(flow_fail_idx)
    entry = float(rows[0]["state_after"]["entry_price"])
    exits = [r for r in rows if r["decision"]["action"] == "SELL"]

    return {
        "date": path.parent.parent.name,
        "strategy": path.parent.name,
        "code": path.name.split("__")[0],
        "ticks": total,
        "recon_pct": f"{recon:.1f}",
        "trust": "YES" if recon >= 98.0 else "NO",
        "stage_fail_pct": f"{stage_fail / total * 100:.1f}",
        "flow_fail_pct": f"{flow_fail / total * 100:.1f}",
        "pass_pct": f"{passed / total * 100:.1f}",
        "fwd60_pass": "" if fwd_pass is None else f"{fwd_pass:.3f}",
        "fwd60_flowfail": "" if fwd_fail is None else f"{fwd_fail:.3f}",
        "fwd60_gap": ("" if None in (fwd_pass, fwd_fail)
                      else f"{fwd_pass - fwd_fail:.3f}"),
        "entry": f"{entry:.0f}",
        "peak": f"{max(prices):.0f}",
        "last": f"{prices[-1]:.0f}",
        "exit_reason": exits[-1]["decision"]["reason"] if exits else "",
    }


def main() -> int:
    day = sys.argv[1] if len(sys.argv) > 1 else datetime.now().strftime("%Y%m%d")
    folder = AUDIT / day
    if not folder.is_dir():
        print(f"[상승보유 관문] {day} 감사기록 폴더 없음 — 기록할 것 없음")
        return 0

    # 123456 은 시험용 가짜 종목이라 뺀다(시험이 실전 폴더에 남긴 것)
    files = [p for p in sorted(folder.rglob("*.jsonl")) if "123456" not in p.name]
    results = [r for r in (analyse(p) for p in files) if r]
    if not results:
        print(f"[상승보유 관문] {day} 포지션 0건")
        return 0

    OUT.parent.mkdir(parents=True, exist_ok=True)
    # ★같은 날을 두 번 돌려도 줄이 겹치지 않게 한다. 손으로 다시 돌리는 일이
    #   잦고, 겹친 줄은 나중에 평균을 조용히 왜곡한다(그러면 표본이 거짓말한다).
    already = set()
    new_file = not OUT.exists()
    if not new_file:
        for line in OUT.read_text(encoding="utf-8").splitlines()[1:]:
            parts = line.split(",")
            if len(parts) >= 3:
                already.add((parts[0], parts[1], parts[2]))

    fresh = [r for r in results
             if (r["date"], r["strategy"], r["code"]) not in already]
    skipped = len(results) - len(fresh)

    # ★PowerShell 로 쓰지 않는다(BOM 이 붙는다). 파이썬에서 utf-8 로 직접 쓴다.
    with OUT.open("a", encoding="utf-8", newline="") as handle:
        if new_file:
            handle.write(",".join(COLUMNS) + "\n")
        for row in fresh:
            handle.write(",".join(str(row[c]).replace(",", " ") for c in COLUMNS) + "\n")
    if skipped:
        print(f"[상승보유 관문] 이미 기록된 {skipped}건은 건너뜀(중복 방지)")

    print(f"[상승보유 관문] {day}  포지션 {len(results)}건 -> {OUT}")
    print(f"  {'전략':22s}{'종목':>8s}{'판정':>7s}{'재현':>7s}"
          f"{'선지지탈락':>11s}{'매수세탈락':>11s}{'통과':>8s}{'+60초차이':>10s}")
    for row in results:
        gap = row["fwd60_gap"]
        print(f"  {row['strategy'][:22]:22s}{row['code']:>8s}{row['ticks']:>7d}"
              f"{row['recon_pct']:>6s}%{row['stage_fail_pct']:>10s}%"
              f"{row['flow_fail_pct']:>10s}%{row['pass_pct']:>7s}%"
              f"{gap if gap else '-':>10s}")
        if row["trust"] == "NO":
            print(f"      ⚠️재현율 {row['recon_pct']}% — 이 줄은 쓰지 말 것")
    print("  ※ +60초차이 = (상승보유 통과 뒤 60초 변화) - (매수세 탈락 뒤 60초 변화)")
    print("     양수면 관문이 옳았다는 뜻. 며칠 쌓인 뒤에 보는 값이다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
