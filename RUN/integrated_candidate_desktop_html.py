# -*- coding: utf-8 -*-
"""[2026-07-21 친구님 "그림자도 검증하고 내 눈으로도 확인하고 싶다"] 바탕화면 통합후보판 —
   integrated_candidate_board.json(4점수 관찰용 그림자 엔진) → Desktop\\통합후보판.html
   (읽기전용·주문0·TR 0). mflow_desktop_html.py와 동일 패턴(1분 태스크 재생성+15초 자동새로고침).
   ★이 엔진 자체가 어젯밤(7/20) 신설된 순수 관찰 시스템 — 실전 매매(캡틴·골짜기)와 무접촉.
"""
import json
import html
from pathlib import Path
from datetime import datetime

BOARD = Path(r"C:\stock_bot\data\integrated_candidate_board.json")
OUT = Path(r"C:\Users\UserK\Desktop\통합후보판.html")


def num(v, d=0):
    try:
        return float(v)
    except Exception:
        return d


def _market_day():
    now = datetime.now()
    if now.weekday() >= 5:
        return False
    try:
        t = now.strftime("%Y%m%d")
        for line in Path(r"C:\stock_bot\config\holidays_kr.txt").read_text(encoding="utf-8").splitlines():
            if line.split("#")[0].strip() == t:
                return False
    except Exception:
        pass
    return True


STRAT_LABEL = {"valley": "저점반등", "breakout": "돌파", "ma_pullback": "이평눌림"}
STRAT_CLASS = {"valley": "s-valley", "breakout": "s-breakout", "ma_pullback": "s-mapb"}


def row_html(r):
    code = str(r.get("code", "")).zfill(6)
    name = html.escape(str(r.get("name", "")))
    strat = r.get("primary_strategy") or ""
    strat_label = STRAT_LABEL.get(strat, strat or "-")
    strat_cls = STRAT_CLASS.get(strat, "")
    grade = str(r.get("grade", ""))
    theme = html.escape(str(r.get("theme_name") or "-"))
    leader = " 👑" if r.get("is_theme_leader") else ""
    reasons = html.escape(" · ".join(r.get("reasons") or []))
    risks = html.escape(" · ".join(r.get("risks") or []))
    outlier = "🔥" if r.get("outlier_flag") else ""

    def score_td(v):
        v = num(v)
        cls = "hi" if v >= 80 else ("mid" if v >= 50 else "")
        return f"<td class='{cls}'>{v:.0f}</td>"

    # ── [2026-07-21 신규 자금유입 — 친구님 지시] 통합후보엔진이 이미 계산해 놓은 값을
    #    표시만 한다(재계산 없음). 없는 종목(구형 캐시 등)은 공란 처리.
    mf_state = r.get("money_flow_state")
    mf_cls = {"START": "mf-start", "ACCEL": "mf-accel", "PEAK": "mf-peak",
              "WATCH": "mf-watch", "WEAK": "mf-weak", "END": "mf-end"}.get(mf_state, "")
    mf_state_html = f"<td class='{mf_cls}'>{html.escape(str(mf_state or '-'))}</td>"
    mf_score_html = score_td(r.get("money_flow_score")) if r.get("money_flow_score") is not None else "<td>-</td>"

    def eok_td(v, signed=False):
        v = num(v)
        if v == 0 and r.get("money_30s_now") is None:
            return "<td>-</td>"
        cls = "pos" if v > 0 else ("neg" if v < 0 else "")
        sign = "+" if (signed and v > 0) else ""
        if abs(v) >= 100_000_000:
            txt = f"{sign}{v/100_000_000:.1f}억"
        else:
            txt = f"{sign}{v/10_000:.0f}만"
        return f"<td class='{cls}'>{txt}</td>"

    def delta_td(v):
        v = num(v)
        cls = "pos" if v > 0 else ("neg" if v < 0 else "")
        return f"<td class='{cls}'>{v:+.1f}</td>"

    money30_td = eok_td(r.get("money_30s_now"))
    ratio30 = r.get("money_ratio_30s")
    ratio30_html = f"<td>{num(ratio30):.2f}배</td>" if ratio30 is not None else "<td>-</td>"
    add30_td = eok_td(r.get("money_add_30s"), signed=True)
    accel30 = r.get("money_accel_30s")
    accel30_html = (f"<td class='{'pos' if num(accel30)>0 else ('neg' if num(accel30)<0 else '')}'>"
                     f"{num(accel30)/10000:+,.0f}만/초</td>") if accel30 is not None else "<td>-</td>"
    ched10_html = delta_td(r.get("che_delta_10s")) if r.get("che_delta_10s") is not None else "<td>-</td>"
    cheaccel10_html = delta_td(r.get("che_accel_10s")) if r.get("che_accel_10s") is not None else "<td>-</td>"

    return (f"<tr>"
            f"<td>{r.get('rank','')}</td>"
            f"<td class='nm'>{outlier}{name}</td><td class='cd'>{code}</td>"
            f"{score_td(r.get('attention_score'))}"
            f"{score_td(r.get('valley_score'))}"
            f"{score_td(r.get('breakout_score'))}"
            f"{score_td(r.get('ma_pullback_score'))}"
            f"<td class='{strat_cls}'>{strat_label}</td>"
            f"<td class='gr'>{grade}</td>"
            f"<td>{num(r.get('che')):.0f}</td>"
            f"{money30_td}{ratio30_html}{add30_td}{accel30_html}{ched10_html}{cheaccel10_html}{mf_score_html}{mf_state_html}"
            f"<td class='td2'>{theme}{leader}</td>"
            f"<td class='td2'>{reasons}</td>"
            f"<td class='risk'>{risks}</td>"
            f"</tr>")


def main():
    if not _market_day():
        return
    try:
        d = json.loads(BOARD.read_text(encoding="utf-8-sig"))
    except Exception:
        d = {}

    ts = d.get("ts", "?")
    status = d.get("status", "?")
    univ = d.get("universe_count", "?")
    valid = d.get("valid_count", "?")
    top40 = (d.get("views") or {}).get("top40") or []
    outliers = d.get("outlier_alerts") or []
    strat_top10 = d.get("strategy_top10") or {}

    top_rows = "\n".join(row_html(r) for r in top40)
    outlier_rows = "\n".join(row_html(r) for r in outliers[:15])

    strat_counts = {k: len(v or []) for k, v in strat_top10.items()}
    strat_boxes = "".join(
        f"<div class='fbox'>{STRAT_LABEL.get(k,k)}<b>{c}</b></div>"
        for k, c in strat_counts.items())

    doc = f"""<!DOCTYPE html>
<html lang="ko"><head><meta charset="utf-8">
<meta http-equiv="refresh" content="15">
<title>🎯 통합후보판 (그림자·관찰전용)</title>
<style>
 body {{ font-family:'Malgun Gothic',sans-serif; background:#111722; color:#e8ecf3; margin:0; padding:16px; }}
 h1 {{ font-size:1.25em; margin:4px 0 2px; }}
 .sub {{ color:#9fb0c8; font-size:0.85em; margin-bottom:12px; }}
 .warn {{ color:#ffd54f; font-size:0.85em; margin-bottom:14px; border:1px solid #4a3f1a; background:#241f0d; padding:6px 10px; border-radius:6px; }}
 .flow {{ display:flex; align-items:center; gap:6px; flex-wrap:wrap; margin:12px 0 18px; }}
 .fbox {{ background:#1c2636; border:1px solid #33425c; border-radius:8px; padding:8px 12px; text-align:center; font-size:0.85em; }}
 .fbox b {{ display:block; font-size:1.25em; color:#7cc4ff; }}
 table {{ border-collapse:collapse; width:100%; font-size:0.82em; margin-bottom:22px; }}
 th,td {{ border-bottom:1px solid #26324a; padding:4px 7px; text-align:right; }}
 th {{ background:#1c2636; color:#9fb0c8; position:sticky; top:0; }}
 td.nm {{ text-align:left; font-weight:bold; }}
 td.cd {{ color:#9fb0c8; font-weight:bold; }}
 td.td2 {{ text-align:left; font-size:0.85em; color:#7cc4ff; }}
 td.risk {{ text-align:left; font-size:0.85em; color:#ff8a80; }}
 td.gr {{ text-align:left; }}
 td.hi {{ color:#69f0ae; font-weight:bold; }}
 td.mid {{ color:#ffd54f; }}
 td.s-valley {{ color:#7cc4ff; }}
 td.s-breakout {{ color:#ffab40; }}
 td.s-mapb {{ color:#b39ddb; }}
 td.pos {{ color:#ff8a80; }} td.neg {{ color:#82b1ff; }}
 td.mf-start {{ color:#ffd54f; font-weight:bold; }}
 td.mf-accel {{ color:#69f0ae; font-weight:bold; }}
 td.mf-peak {{ color:#7cc4ff; font-weight:bold; }}
 td.mf-watch {{ color:#9fb0c8; }}
 td.mf-weak {{ color:#8a93a5; }}
 td.mf-end {{ color:#5b6c85; }}
 h2 {{ font-size:1.0em; margin:20px 0 6px; color:#9fb0c8; }}
 .note {{ color:#6b7a92; font-size:0.78em; margin-top:14px; }}
</style></head><body>
<h1>🎯 통합후보판 <span style="font-size:0.7em;color:#9fb0c8">{ts} · status={html.escape(str(status))}</span></h1>
<div class="sub">15초마다 자동 새로고침 · 1분마다 데이터 재생성 (읽기전용) · 유니버스 {univ} → 유효 {valid}종목</div>
<div class="warn">⚠️ 이 시스템은 어젯밤(7/20) 신설된 순수 관찰용 그림자 엔진입니다. 캡틴·골짜기 실전 매매와 전혀 연결되어 있지 않고, 아직 며칠 검증 전이라 점수 신뢰도가 확인되지 않았습니다. 참고용으로만 보세요.</div>

<div class="flow">
 {strat_boxes}
 <div class="fbox">🔥아웃라이어(복합상위)<b>{len(outliers)}</b></div>
</div>

<h2>🔥 아웃라이어 — 여러 전략 점수가 동시에 높은 복합상위 (최대 15)</h2>
<table>
<tr><th>순위</th><th style="text-align:left">종목</th><th>코드</th><th>관심도</th><th>저점반등</th><th>돌파</th><th>이평눌림</th><th>주전략</th><th>등급</th><th>체결</th><th>돈30초</th><th>직전比</th><th>추가유입</th><th>돈가속</th><th>체결Δ10초</th><th>체결가속</th><th>유입점수</th><th>유입상태</th><th style="text-align:left">테마</th><th style="text-align:left">근거</th><th style="text-align:left">위험</th></tr>
{outlier_rows}
</table>

<h2>📊 관심도 TOP40 (4점수 전체 랭킹)</h2>
<table>
<tr><th>순위</th><th style="text-align:left">종목</th><th>코드</th><th>관심도</th><th>저점반등</th><th>돌파</th><th>이평눌림</th><th>주전략</th><th>등급</th><th>체결</th><th>돈30초</th><th>직전比</th><th>추가유입</th><th>돈가속</th><th>체결Δ10초</th><th>체결가속</th><th>유입점수</th><th>유입상태</th><th style="text-align:left">테마</th><th style="text-align:left">근거</th><th style="text-align:left">위험</th></tr>
{top_rows}
</table>

<div class="note">관심도=슬롯경쟁용 종합순위(4점수 가중합) · 저점반등/돌파/이평눌림=독립 전략점수(하나로 안 뭉갬, 친구님 지시) · 🔥=여러 점수 동시 상위 이상치 · 👑=테마 리더.<br>
데이터 출처: integrated_candidate_engine_v1.py(micro_rank_engine_v1.py 위 2차 선별층) — 전부 주문0·TR0 관찰 전용.</div>
</body></html>"""
    OUT.write_text(doc, encoding="utf-8")
    print(f"통합후보판 생성: {OUT} (top40={len(top40)}행·아웃라이어={len(outliers)})")


if __name__ == "__main__":
    main()
