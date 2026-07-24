# -*- coding: utf-8 -*-
"""
[가격동조 클러스터링 v1 2026-06-10] — T2 완전해소: 네이버 멤버십 없이 '오늘 같이 움직이는 무리' 탐지.
목적: 네이버에 아직 등록 안 된 '오늘 태어난 테마'(동반 급등 클러스터)를 장중 포착.
방법: 오늘 강세 종목(시가대비 +3%+, 거래대금 50억+)의 5분 수익률 상관행렬 → 그리디 클러스터(corr>0.55, 크기>=3)
     → 네이버 테마와 대조: 멤버 과반 공유 테마 있으면 기존테마, 없으면 NEW(신규 무리).
출력: data/theme/theme_cluster_intraday.csv (+로그). ★매매 무연결 SHADOW — 며칠 관찰 후 익일성과 검증되면 주입 연결.
스케줄: SAFEPLUS_THEME_CLUSTER 매일 14:45.
"""
import csv, io, os, sys, logging
from datetime import datetime
from pathlib import Path
from collections import defaultdict

import pandas as pd
import numpy as np

BASE = Path(r"C:\stock_bot")
P1M = Path(os.environ.get("CLUSTER_P1M", str(BASE / "data" / "prices_1m.csv")))  # 검증용 override
MEMBERSHIP = BASE / "data" / "theme" / "theme_membership_naver.csv"
OUT = BASE / "data" / "theme" / "theme_cluster_intraday.csv"
LOG = BASE / "data" / "LOG" / "theme_cluster_intraday.log"

MIN_RET = float(os.environ.get("CLUSTER_MIN_RET", "3.0"))        # 당일수익 하한 %
MIN_VALUE_EOK = float(os.environ.get("CLUSTER_MIN_VALUE_EOK", "50"))  # 거래대금 하한(억)
CORR_TH = float(os.environ.get("CLUSTER_CORR_TH", "0.55"))
MIN_SIZE = int(os.environ.get("CLUSTER_MIN_SIZE", "3"))

logging.basicConfig(level=logging.INFO, format="[%(asctime)s][cluster][%(levelname)s] %(message)s",
                    handlers=[logging.FileHandler(LOG, encoding="utf-8"), logging.StreamHandler()])
log = logging.getLogger("cluster")

def main():
    today = datetime.now().strftime("%Y%m%d")
    if len(sys.argv) > 1 and sys.argv[1].isdigit():   # 검증용: 날짜 지정(YYYYMMDD)
        today = sys.argv[1]
    if not P1M.exists():
        log.warning("prices_1m 없음 → skip"); return 0
    df = pd.read_csv(P1M, dtype={"code": str, "ts": str}, low_memory=False)
    df["code"] = df["code"].str.zfill(6)
    df = df[df["ts"].str[:8] == today]
    if df.empty:
        log.warning(f"오늘({today}) 분봉 없음 → skip"); return 0
    df = df[~df["code"].isin(["U001", "U201"])]
    df["hm"] = df["ts"].str[8:12].astype(int)
    df = df[(df["hm"] >= 930) & (df["hm"] <= 1440)]
    for c in ("open", "close", "value", "volume"):
        if c in df.columns: df[c] = pd.to_numeric(df[c], errors="coerce")

    # 종목 필터: 당일수익 +3%+, 거래대금 50억+, 분봉 40개+
    df["_pv"] = df["close"] * df.get("volume", 0)   # value=0 데이터(history 등) 근사용
    g = df.sort_values("hm").groupby("code")
    meta = g.agg(first_open=("open", "first"), last_close=("close", "last"),
                 val=("value", "sum"), pv=("_pv", "sum"), n=("close", "size"))
    meta["ret"] = (meta["last_close"] / meta["first_open"] - 1) * 100
    meta["val_eok"] = np.where(meta["val"] > 0, meta["val"], meta["pv"]) / 1e8
    pool = meta[(meta["ret"] >= MIN_RET) & (meta["val_eok"] >= MIN_VALUE_EOK) & (meta["n"] >= 40)]
    codes = list(pool.index)
    log.info(f"강세풀: {len(codes)}종목 (ret>={MIN_RET}% & {MIN_VALUE_EOK}억+ & 40분+)")
    if len(codes) < MIN_SIZE:
        log.info("풀 부족 → 클러스터 없음(정상)"); _write([], today); return 0

    # 5분 수익률 상관
    sub = df[df["code"].isin(codes)].copy()
    sub["bucket"] = (sub["hm"] // 100) * 12 + (sub["hm"] % 100) // 5   # 5분 버킷
    px = sub.pivot_table(index="bucket", columns="code", values="close", aggfunc="last").ffill()
    ret5 = px.pct_change().dropna(how="all")
    corr = ret5.corr(min_periods=20)

    # 그리디 클러스터
    unassigned = set(codes); clusters = []
    while unassigned:
        prev_n = len(unassigned)
        # 씨앗 = 미배정 중 (미배정과의) 평균상관 최고
        best_seed, best_avg = None, -9
        unassigned = {c for c in unassigned if c in corr.columns}
        for c in unassigned:
            others = [o for o in unassigned if o != c]
            if not others: continue
            avg = corr.loc[c, others].mean()
            if pd.notna(avg) and avg > best_avg: best_seed, best_avg = c, avg
        if best_seed is None:
            # [LOOP-FIX] 잔여 1개/상관계산 불가 — 줄지 않으면 탈출(무한루프 방지)
            if len(unassigned) >= prev_n:
                break
            continue
        members = [best_seed] + [o for o in unassigned
                                 if o != best_seed and o in corr.columns
                                 and pd.notna(corr.loc[best_seed, o]) and corr.loc[best_seed, o] >= CORR_TH]
        unassigned -= set(members)
        if len(members) >= MIN_SIZE:
            mc = corr.loc[members, members]
            avg_corr = mc.values[np.triu_indices(len(members), 1)].mean()
            clusters.append((members, round(float(avg_corr), 3)))

    # 네이버 테마 대조
    code2themes = defaultdict(set)
    try:
        for r in csv.DictReader(io.open(MEMBERSHIP, encoding="utf-8-sig", errors="replace")):
            code2themes[str(r["code"]).zfill(6)].add(str(r["theme_name"]).strip())
    except Exception as e:
        log.warning(f"멤버십 로드 실패(NEW 판정 불가, 계속): {e}")

    out_rows = []
    for i, (members, avg_corr) in enumerate(sorted(clusters, key=lambda x: -len(x[0])), 1):
        tc = defaultdict(int)
        for m in members:
            for t in code2themes.get(m, ()): tc[t] += 1
        if tc:
            t_best, t_n = max(tc.items(), key=lambda x: x[1])
        else:
            t_best, t_n = "", 0
        is_new = t_n < (len(members) + 1) // 2          # 과반 공유 테마 없으면 NEW
        rets = pool.loc[[m for m in members if m in pool.index], "ret"]
        vals = pool.loc[[m for m in members if m in pool.index], "val_eok"]
        leader = rets.add(vals.rank(pct=True), fill_value=0).idxmax() if len(rets) else ""
        tag = "NEW" if is_new else t_best
        log.info(f"[C{i}] {'🆕' if is_new else '  '} {tag[:20]:20s} n={len(members)} corr={avg_corr} "
                 f"평균수익={rets.mean():.1f}% leader={leader} members={','.join(members[:8])}")
        for m in members:
            out_rows.append({"date": today, "cluster_id": i, "is_new": int(is_new),
                             "matched_theme": "" if is_new else t_best,
                             "code": m, "ret_pct": round(float(pool.loc[m, 'ret']), 2) if m in pool.index else "",
                             "value_eok": round(float(pool.loc[m, 'val_eok'])) if m in pool.index else "",
                             "avg_corr": avg_corr, "n_members": len(members),
                             "is_leader": int(m == leader)})
    _write(out_rows, today)
    n_new = len(set(r["cluster_id"] for r in out_rows if r["is_new"]))
    log.info(f"[DONE] 클러스터 {len(clusters)}개 (🆕신규무리 {n_new}개) → {OUT.name}")
    return 0

def _write(rows, today):
    OUT.parent.mkdir(parents=True, exist_ok=True)
    cols = ["date", "cluster_id", "is_new", "matched_theme", "code", "ret_pct",
            "value_eok", "avg_corr", "n_members", "is_leader"]
    with io.open(OUT, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=cols); w.writeheader()
        for r in rows: w.writerow(r)

if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        log.error(f"[FATAL] {e} (무크래시 종료)")
        sys.exit(0)
