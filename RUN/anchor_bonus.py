# -*- coding: utf-8 -*-
"""
[코스피 앵커 상대강도 보너스 — 공용 모듈  2026-06-13]  (친구님 설계 + 백테검증)
종가매수 8→1 / 스윙이 공통으로 쓰는 '앵커 보너스' 계산.
원리(백테 1년 검증): 코스닥 후보가 같은 테마의 코스피 앵커보다 강하고(앵커도 상승) = 진짜 주도주.
  익일갭 +0.28%p / 4일 +0.55%p / ★앵커상승&후보강함 익일+0.98%·4일+0.87%.
보너스(소프트, 절대조건 아님):
  앵커 상승 & 후보>앵커  → +최대 MAX (rel 5%p에서 만점)
  앵커 약세              → 소폭 감점(-MAX×0.5 한도)
  앵커 없는 테마(정치·바이오·양자 등) → 0 (무시 — 친구님 지시)
입력: DATA/theme/kospi_anchor.csv (collect_kospi_anchors) + theme_membership_naver.csv
"""
import csv, io
from pathlib import Path

_TD = Path(r"C:\stock_bot") / "data" / "theme"


def load_anchor_ctx():
    """returns (anchor_chg{code:chg%}, theme_anchors{theme:set(anchor_code)}, code_themes{code:[anchored_themes]}).
    code_themes = 그 종목이 속한 '앵커 있는' 테마들(스윙이 후보 테마 조회용). 파일없음/빈값 → 빈 dict(보너스 0)."""
    anchor_chg = {}
    f = _TD / "kospi_anchor.csv"
    try:
        if f.exists():
            for r in csv.DictReader(io.open(f, encoding="utf-8-sig")):
                try:
                    anchor_chg[str(r["code"]).strip().zfill(6)] = float(r["chg_pct"])
                except (KeyError, ValueError, TypeError):
                    continue
    except Exception:
        return {}, {}, {}
    if not anchor_chg:
        return {}, {}, {}
    theme_anchors = {}
    code_themes = {}
    fm = _TD / "theme_membership_naver.csv"
    try:
        if fm.exists():
            rows = list(csv.DictReader(io.open(fm, encoding="utf-8-sig")))
            # 1차: 앵커가 속한 테마 집합
            for r in rows:
                c = str(r.get("code", "")).strip().zfill(6)
                if c in anchor_chg:
                    theme_anchors.setdefault(str(r.get("theme_name", "")).strip(), set()).add(c)
            # 2차: 각 종목이 속한 '앵커 있는' 테마들
            _anchored = set(theme_anchors.keys())
            for r in rows:
                t = str(r.get("theme_name", "")).strip()
                if t in _anchored:
                    code_themes.setdefault(str(r.get("code", "")).strip().zfill(6), []).append(t)
    except Exception:
        return anchor_chg, theme_anchors, {}
    return anchor_chg, theme_anchors, code_themes


def anchor_bonus(cand_themes, cand_ret, anchor_chg, theme_anchors, max_bonus=10.0):
    """후보의 테마들에 걸린 앵커 중 가장 센(등락 최고) 앵커로 상대강도 보너스.
    cand_themes: 후보가 속한 테마명 리스트(또는 1개). cand_ret: 후보 당일 등락(%).
    returns (bonus, detail)."""
    best_anc = None
    for t in (cand_themes or []):
        for ac in theme_anchors.get(t, ()):
            v = anchor_chg.get(ac)
            if v is not None and (best_anc is None or v > best_anc):
                best_anc = v
    if best_anc is None:
        return 0.0, "앵커없음(무시)"
    rel = cand_ret - best_anc
    if best_anc > 0 and rel > 0:          # 앵커 상승 + 후보가 더 강함 = 진짜 주도주
        return round(min(rel / 5.0, 1.0) * max_bonus, 2), f"앵커+{best_anc:.1f}%·후보더강함+{rel:.1f}%p"
    if best_anc < 0:                       # 앵커 약세 → 소폭 감점
        return round(-min(abs(best_anc) / 5.0, 1.0) * (max_bonus * 0.5), 2), f"앵커약세{best_anc:.1f}%"
    return 0.0, f"중립(앵커+{best_anc:.1f}%·후보약함)"
