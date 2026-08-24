# -*- coding: utf-8 -*-
"""고저폭판과 돈흐름판의 종목선별 품질을 점검하는 읽기전용 내부 도구.

주문·전략 모듈을 import하지 않으며 입력 JSON 두 개를 읽어 JSON/HTML 진단서를 만든다.
이 도구의 점수는 수익률이 아니라 '선별 근거의 완전성' 점수다.
"""
from __future__ import annotations

import argparse
import html
import json
from datetime import datetime
from pathlib import Path
from typing import Any


BASE = Path(r"C:\stock_bot")


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def _age_hours(value: Any, now: datetime) -> float | None:
    parsed = _parse_time(value)
    if parsed is None:
        return None
    return round(max(0.0, (now - parsed).total_seconds()) / 3600.0, 2)


def audit(high_range: dict[str, Any], money_flow: dict[str, Any], now: datetime) -> dict[str, Any]:
    hr_rows = high_range.get("candidates") or []
    mf_rows = money_flow.get("rows") or []
    hr_codes = {str(row.get("code", "")).zfill(6) for row in hr_rows if row.get("code")}
    mf_codes = {str(row.get("code", "")).zfill(6) for row in mf_rows if row.get("code")}
    overlap = sorted(hr_codes & mf_codes)
    mf_names = {str(row.get("code", "")).zfill(6): str(row.get("name", "")) for row in mf_rows}
    hr_names = {str(row.get("code", "")).zfill(6): str(row.get("name", "")) for row in hr_rows}

    personal_present = sum(1 for row in mf_rows if row.get("indiv") not in (None, 0, 0.0))
    null_program = sum(1 for row in mf_rows if row.get("prog") is None)
    null_trend = sum(1 for row in mf_rows if row.get("trend") is None)
    filters = high_range.get("filters") or {}

    checks = [
        {
            "area": "변동성",
            "status": "PARTIAL",
            "evidence": f"전일 고저폭 {filters.get('daily_range_min_pct', '?')}% 및 5일 지속성 사용",
            "gap": "ATR/가격대 정규화, 갭과 장중 진폭 분리, 시장 대비 초과변동성 없음",
        },
        {
            "area": "자금유입",
            "status": "PARTIAL",
            "evidence": "기관·외인·프로그램 순매수 절대액과 합의 개수 사용",
            "gap": "시총·유통주식·평균거래대금 대비 순매수 강도와 지속시간 보정 없음",
        },
        {
            "area": "중복계상",
            "status": "RISK",
            "evidence": "프로그램을 기관·외인과 별도 스마트 주체로 합산",
            "gap": "프로그램은 주문 경로라 투자자 주체와 겹칠 수 있어 3표 합의가 독립 신호가 아닐 수 있음",
        },
        {
            "area": "시장범위",
            "status": "RISK",
            "evidence": "돈흐름판이 코스닥(MF_MARKET_GB=101)에 고정",
            "gap": "코스피 주도주와 시장 간 자금이동을 비교하지 못함",
        },
        {
            "area": "리스크/체결",
            "status": "MISSING",
            "evidence": "가격·거래대금·시총 하한만 존재",
            "gap": "호가 스프레드, 예상 슬리피지, VI/상한가 근접, 섹터 쏠림, 이벤트 위험의 선별단계 통제가 없음",
        },
        {
            "area": "검증구조",
            "status": "MISSING",
            "evidence": "현재 두 판에는 후보가 탈락한 이유와 이후 비교군 기록이 없음",
            "gap": "선정/미선정 전 종목의 시점별 스냅샷과 walk-forward 비교가 없어 선별 자체의 기여도를 분리하기 어려움",
        },
    ]
    completeness = round(100 * sum(c["status"] == "OK" for c in checks) / len(checks))

    priorities = [
        "순매수 절대액 대신 net_buy / 20일 평균거래대금과 net_buy / 유통시총을 함께 저장·순위화",
        "기관·외인만 독립 주체로 보고 프로그램은 보조 실행강도 지표로 분리해 중복계상 제거",
        "고저폭은 ATR20%, 갭%, 장중 실현변동성으로 분해하고 동일 섹터 최대 종목 수를 제한",
        "후보마다 스프레드·호가잔량·예상 슬리피지·데이터 나이를 기록해 오래되거나 체결 불리한 종목 차단",
        "매일 선정군과 동일 유동성 비선정 대조군을 함께 저장해 walk-forward로 선별 기여도만 검증",
    ]
    remove_or_demote = [
        "고저폭 TOP 고정등수 자체를 매수 우선순위로 사용: 변동성이 큰 종목과 좋은 종목은 같은 뜻이 아님",
        "개인 값이 전부 0인 상태의 개인 방향 표시: 현재 판별력이 없으므로 데이터 복구 전 점수에서 제외",
        "테마/잡주 보장석을 품질점수와 혼합: 발견용 보조 풀로 분리하고 핵심 순위에는 직접 가산하지 않기",
    ]

    return {
        "report_type": "SELECTION_EVIDENCE_AUDIT",
        "generated_at": now.isoformat(timespec="seconds"),
        "performance_claim": "NONE",
        "evidence_completeness_score": completeness,
        "inputs": {
            "high_range_generated_at": high_range.get("generated_at"),
            "high_range_age_hours": _age_hours(high_range.get("generated_at"), now),
            "high_range_source_stale": high_range.get("source_stale"),
            "money_flow_ts": money_flow.get("ts"),
            "money_flow_age_hours": _age_hours(money_flow.get("ts"), now),
        },
        "snapshot": {
            "high_range_count": len(hr_codes),
            "money_flow_count": len(mf_codes),
            "overlap_count": len(overlap),
            "overlap": [
                {"code": code, "name": mf_names.get(code) or hr_names.get(code, "")}
                for code in overlap
            ],
            "money_flow_personal_nonzero_rows": personal_present,
            "money_flow_program_null_rows": null_program,
            "money_flow_trend_null_rows": null_trend,
        },
        "verdict": "현재 구조는 '움직이는 종목 발견'에는 유용하지만 '살 만한 종목 선별'에는 불완전하다.",
        "checks": checks,
        "priorities": priorities,
        "remove_or_demote": remove_or_demote,
    }


def _render_html(report: dict[str, Any]) -> str:
    esc = html.escape
    snap = report["snapshot"]
    rows = "".join(
        f"<tr><td>{esc(c['area'])}</td><td class='{c['status'].lower()}'>{c['status']}</td>"
        f"<td>{esc(c['evidence'])}</td><td>{esc(c['gap'])}</td></tr>"
        for c in report["checks"]
    )
    overlap = ", ".join(f"{x['name']}({x['code']})" for x in snap["overlap"]) or "없음"
    priorities = "".join(f"<li>{esc(x)}</li>" for x in report["priorities"])
    removals = "".join(f"<li>{esc(x)}</li>" for x in report["remove_or_demote"])
    return f"""<!doctype html><html lang='ko'><meta charset='utf-8'>
<title>스톡봇 종목선별 품질 진단</title><style>
body{{font-family:Segoe UI,Malgun Gothic,sans-serif;max-width:1180px;margin:36px auto;padding:0 20px;color:#172033}}
.card{{background:#f5f7fb;border:1px solid #dfe5ef;border-radius:12px;padding:18px;margin:14px 0}}
table{{border-collapse:collapse;width:100%}}th,td{{border:1px solid #dfe5ef;padding:10px;text-align:left;vertical-align:top}}
.risk,.missing{{color:#b42318;font-weight:700}}.partial{{color:#b54708;font-weight:700}}small{{color:#667085}}
</style><h1>스톡봇 종목선별 품질 진단</h1>
<div class='card'><b>판단:</b> {esc(report['verdict'])}<br><small>이 보고서는 수익률 평가가 아닌 선별 근거 완전성 점검입니다.</small></div>
<div class='card'>고저폭 {snap['high_range_count']}종목 · 돈흐름 {snap['money_flow_count']}종목 · 교집합 {snap['overlap_count']}종목<br>{esc(overlap)}</div>
<h2>부족한 근거</h2><table><tr><th>영역</th><th>상태</th><th>현재 근거</th><th>빈틈</th></tr>{rows}</table>
<h2>보강 우선순위</h2><ol>{priorities}</ol><h2>제외·강등 권고</h2><ul>{removals}</ul>
<small>생성시각 {esc(report['generated_at'])} · performance_claim=NONE</small></html>"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--high-range", type=Path, default=BASE / "data" / "common_high_range_top30.json")
    parser.add_argument("--money-flow", type=Path, default=BASE / "data" / "돈흐름_선별판.json")
    parser.add_argument("--output", type=Path, default=BASE / "data" / "reports" / "selection_quality_audit_latest.json")
    args = parser.parse_args()
    report = audit(_read_json(args.high_range), _read_json(args.money_flow), datetime.now())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    html_path = args.output.with_suffix(".html")
    html_path.write_text(_render_html(report), encoding="utf-8")
    print(f"OK {args.output}")
    print(f"OK {html_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
