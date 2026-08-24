# -*- coding: utf-8 -*-
"""📋 그림자 엔진 일일 보고서 — 주문0·TR0. micro_rank_engine·integrated_candidate_engine
읽기전용 관찰 결과를 매일 텍스트로 정리(친구님 "매일매일 보고해줘야 된다" 2026-07-20).

읽기: micro_rank_history.csv·integrated_candidate_history.csv·각 engine.log(오늘자만)
씀: C:\\stock_bot\\data\\LOG\\daily_shadow_report_YYYYMMDD.txt

실전 매매 엔진(골짜기·돌파·캡틴)은 전혀 참조하지 않음 — 이 두 그림자 엔진 관찰결과만 보고.
"""
import csv
from collections import Counter
from datetime import datetime
from pathlib import Path

TODAY = datetime.now().strftime("%Y-%m-%d")
TODAY_C = datetime.now().strftime("%Y%m%d")

MRE_HIST = Path(r"C:\stock_bot\data\micro_rank_history.csv")
ICE_HIST = Path(r"C:\stock_bot\data\integrated_candidate_history.csv")
MFW_HIST = Path(r"C:\stock_bot\data\moneyflow_watch_history.csv")
MRE_LOG  = Path(r"C:\stock_bot\data\LOG\micro_rank_engine.log")
ICE_LOG  = Path(r"C:\stock_bot\data\LOG\integrated_candidate_engine.log")
TL_LOG     = Path(r"C:\stock_bot\data\shadow\true_leader_check.csv")
SUPPLY_LOG = Path(r"C:\stock_bot\data\shadow\money_flow_supply_check.csv")
OUT      = Path(rf"C:\stock_bot\data\LOG\daily_shadow_report_{TODAY_C}.txt")


def _today_rows(path):
    if not path.exists():
        return []
    rows = []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            if row.get("ts", "").startswith(TODAY):
                rows.append(row)
    return rows


def _log_first_last(path):
    """로그엔 시각(HH:MM:SS)만 찍혀 날짜 매칭이 안 돼 오늘자만 못 거름 — 전체 줄수/처음·끝줄로 대체 판단."""
    if not path.exists():
        return None, None, 0
    lines = [l for l in path.read_text(encoding="utf-8", errors="ignore").splitlines() if l.strip()]
    return (lines[0] if lines else None), (lines[-1] if lines else None), len(lines)


def main():
    lines = [f"=== 그림자 엔진 일일 보고 {TODAY} ===", ""]

    mre_rows = _today_rows(MRE_HIST)
    ice_rows = _today_rows(ICE_HIST)

    lines.append(f"[micro_rank_engine] 오늘 이벤트 {len(mre_rows)}건")
    mre_ev = Counter(r["event"] for r in mre_rows)
    for ev, n in mre_ev.most_common():
        lines.append(f"  · {ev}: {n}건")
    s_enters = [r for r in mre_rows if r["event"] == "S_ENTER"]
    if s_enters:
        lines.append(f"  · S등급 진입 종목: {', '.join(sorted(set(r['code']+'('+r['name']+')' for r in s_enters)))}")
    mre_stale = [r for r in mre_rows if "STALE" in r["event"]]
    if mre_stale:
        lines.append(f"  ⚠️ STALE/복구 이벤트 {len(mre_stale)}건 — 상세는 로그 확인 필요")
    lines.append("")

    lines.append(f"[integrated_candidate_engine] 오늘 이벤트 {len(ice_rows)}건")
    ice_ev = Counter(r["event"] for r in ice_rows)
    for ev, n in ice_ev.most_common():
        lines.append(f"  · {ev}: {n}건")
    outlier_ev = [r for r in ice_rows if r["event"] == "OUTLIER_ALERT"]
    if outlier_ev:
        codes = sorted(set(r["code"] + "(" + r["name"] + ")" for r in outlier_ev))
        lines.append(f"  · 이상치 조기경보 종목: {', '.join(codes)}")
    prim_changes = [r for r in ice_rows if r["event"] == "PRIMARY_CHANGE"]
    lines.append(f"  · primary_strategy 변경 {len(prim_changes)}건 (흔들림 방지 없음 — 참고용 지표)")
    lines.append("")

    mfw_rows = _today_rows(MFW_HIST)
    lines.append(f"[moneyflow_watch] 오늘 이벤트 {len(mfw_rows)}건 (돈맥 선별기 관찰)")
    mfw_ev = Counter(r["event"] for r in mfw_rows)
    for ev, n in mfw_ev.most_common():
        lines.append(f"  · {ev}: {n}건")
    lines.append("")

    # ★선행시간(micro가 돈맥 선별기보다 몇 초 먼저 잡았는지) — 같은 종목이 오늘 양쪽에 다 뜬 경우만 비교
    mre_first = {}
    for r in mre_rows:
        if r["event"] == "TOP20_IN" and r["code"] not in mre_first:
            mre_first[r["code"]] = r["ts"]
    mfw_first = {}
    for r in mfw_rows:
        if r["event"] == "FIRST_SEEN" and r["code"] not in mfw_first:
            mfw_first[r["code"]] = r["ts"]
    common = set(mre_first) & set(mfw_first)
    if common:
        lines.append(f"[선행시간 비교] 오늘 양쪽에 다 뜬 종목 {len(common)}개")
        fmt = "%Y-%m-%d %H:%M:%S"
        diffs = []
        for c in common:
            try:
                t_mre = datetime.strptime(mre_first[c], fmt)
                t_mfw = datetime.strptime(mfw_first[c], fmt)
                diffs.append((c, (t_mfw - t_mre).total_seconds()))
            except Exception:
                continue
        for c, d in sorted(diffs, key=lambda x: -x[1])[:10]:
            tag = "micro가 먼저" if d > 0 else ("돈맥이 먼저" if d < 0 else "동시")
            lines.append(f"  · {c}: {abs(d):.0f}초 {tag} (micro={mre_first[c]} / 돈맥={mfw_first[c]})")
        lines.append("")
    elif mre_first or mfw_first:
        lines.append("[선행시간 비교] 오늘 양쪽에 겹치는 종목 없음(유니버스 차이 또는 미포착)")
        lines.append("")

    for tag, log_path in (("micro_rank_engine.log", MRE_LOG), ("integrated_candidate_engine.log", ICE_LOG)):
        first, last, n = _log_first_last(log_path)
        lines.append(f"[{tag}] 총 {n}줄")
        if first:
            lines.append(f"  · 첫 줄: {first}")
        if last:
            lines.append(f"  · 마지막 줄: {last}")
        fatal = "🚨 치명 오류" in (log_path.read_text(encoding="utf-8", errors="ignore") if log_path.exists() else "")
        if fatal:
            lines.append("  🚨 치명 오류 로그 발견 — 반드시 확인 필요")
        lines.append("")

    # [2026-07-21 오사장님 "그림자로만 두면 잊고 버린다"] 오늘 새로 넣은 관찰용 검증로그 3종
    # 요약 — 이 보고서에 매일 자동으로 포함시켜서 확인을 잊지 않게 한다. 실전 매매엔진 무접촉.
    tl_rows = []
    if TL_LOG.exists():
        with TL_LOG.open("r", encoding="utf-8-sig", newline="") as f:
            tl_rows = [r for r in csv.DictReader(f) if r.get("일자") == TODAY_C]   # ★"ts" 아니라 "일자"(YYYYMMDD) 컬럼
    lines.append(f"[TRUE_LEADER 검증] 오늘 판정 {len(tl_rows)}건")
    if tl_rows:
        tl_true = [r for r in tl_rows if str(r.get("TRUE_LEADER")).strip() == "True"]
        lines.append(f"  · TRUE_LEADER=True {len(tl_true)}건 / 전체 {len(tl_rows)}건")
        for r in tl_true[:10]:
            lines.append(f"  · {r.get('테마')} {r.get('종목명')}({r.get('종목코드')}) "
                         f"1등{r.get('1등거래대금억')}억 vs 2등{r.get('2등거래대금억')}억 "
                         f"(차이{r.get('차이%')}%) 체결강도{r.get('체결강도')} "
                         f"동반{r.get('동반종목수', '?')}종목")
        lines.append("  ※실제 수익률 자동추적 미구현 — 캡틴/골짜기 우선검토 연결 여부는 수동 판단 필요")
    lines.append("")

    sc_rows = _today_rows(SUPPLY_LOG)
    lines.append(f"[Money Flow 매수종목 수급검증] 오늘 실제 매수 {len(sc_rows)}건")
    if sc_rows:
        def _pos(v):
            try:
                return float(v) > 0
            except Exception:
                return False
        inst_n = sum(1 for r in sc_rows if _pos(r.get("inst")))
        frgn_n = sum(1 for r in sc_rows if _pos(r.get("frgn")))
        prog_n = sum(1 for r in sc_rows if _pos(r.get("prog")))
        lines.append(f"  · 기관순매수 있음 {inst_n}/{len(sc_rows)} · 외국인 {frgn_n}/{len(sc_rows)} "
                     f"· 프로그램 {prog_n}/{len(sc_rows)}")
    lines.append("")

    lines.append("(이 보고는 그림자 관찰용 — 실전 매매 엔진 골짜기·돌파·캡틴과는 무관)")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"🚨 일일보고 생성 실패: {e}")
