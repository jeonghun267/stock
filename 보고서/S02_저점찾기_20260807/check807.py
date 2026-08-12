# -*- coding: utf-8 -*-
"""8/7 검산: 넓은 우주 재생 중 기존 22종목 부분집합이 아까의 27건과 맞는지."""
import json
import pathlib

HERE = pathlib.Path(__file__).parent
known = json.loads((HERE / "fires_gateoff.json").read_text(encoding="utf-8"))
kc = {str(f["_code"]).zfill(6) for f in known}
kset = {(str(f["_code"]).zfill(6), f["_t"]) for f in known}

rows = [json.loads(x) for x in
        (HERE / "multi12_fires.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
d7 = [r for r in rows if r["date"] == "20260807"]
sub = [r for r in d7 if r["code"] in kc]
match = sum(1 for r in sub if (r["code"], r["t"]) in kset)
print(f"8/7 채점 전체 {len(d7)}건 / 기존 22종목 위 신호 {len(sub)}건"
      f" / 기존 27건과 시각까지 일치 {match}건")

W = [r for r in sub if r["res"] == 1]
L = [r for r in sub if r["res"] == -1]
if W and L:
    print(f"22종목 부분집합: 승 {len(W)} 패 {len(L)}"
          f" · 패자꼭지최대 {max(r['peak'] for r in L):+.2f}%"
          f" · 승자꼭지최소 {min(r['peak'] for r in W):+.2f}%")

WA = [r for r in d7 if r["res"] == 1]
LA = [r for r in d7 if r["res"] == -1]
bad_l = sorted([r for r in LA if r["peak"] > 2.4], key=lambda r: -r["peak"])[:8]
bad_w = sorted([r for r in WA if r["peak"] < 2.4], key=lambda r: r["peak"])[:8]
print("선(2.4%) 위까지 갔는데 진 놈:",
      [(r["code"], r["t"][:5], round(r["peak"], 2)) for r in bad_l])
print("선 아래인데 이긴 놈:",
      [(r["code"], r["t"][:5], round(r["peak"], 2)) for r in bad_w])
