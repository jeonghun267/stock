# -*- coding: utf-8 -*-
r"""[공통배관 2026-08-07 친구님 지시 "시가 대비 저점을 실시간으로 알고 있어야 돼.
전 전략이 다 같이 써야 돼. 공통으로 넣어."]

시가·당일저가·당일고가를 어떤 종목이든 실시간으로 주는 배관.

★왜 만들었나 — 8/7 실측
  S06 은 기준가·저점을 실황판(30종목)에서만 받아, 명단 밖 종목은 "감시 시작 시점부터
  자기가 본 것"으로 저점을 만들었다(그 전에 찍힌 진짜 당일 저가를 모른다).
  8/7 장중에 명단을 48개로 넓히자 추가 18개의 기준가가 시가가 아니라 "넣은 시점 가격"이
  되어 무장이 하나도 안 됐다 — "눈은 늘렸는데 자를 잘못 줬다."
  그런데 스냅샷에는 8/4~8/5 에 배선한 거래소 시가/저가/고가(op/lo/hi = FID 16/18/17)가
  1,000+ 종목에 이미 실려 있다. 그 통로를 전 전략이 같이 쓰게 한다.

★선 긋기(8/5 원칙): 공통으로 올리는 건 "배관"(시가·저가·고가를 아는 것)뿐이다.
  판정(무장 낙폭·매수구간·문턱)은 각 전략의 것을 그대로 둔다.

소스 우선순위 — 값이 있는 첫 소스를 쓴다(필드별로 따로 판단):
  ① 실황판 common_high_range_live_state.json  (30종목 · 오늘 날짜일 때만)
  ② 스냅샷 live_micro_snapshot.json 의 op/lo/hi (1,000+종목 · 0 이면 없는 것)
  ③ 자체 관측 — 이 모듈은 0.0 을 돌려주고, 폴백은 호출자(각 엔진)가 한다.
  (①이 먼저인 이유: 원래 30종목의 종전 동작을 그대로 보존하고, 모듈은 "없던 종목의
   구멍"만 메운다. 기존 성적과의 비교 기준선을 지키기 위해서다.)

읽기는 json_cache_v1 경유(mtime+크기·0.5초 TTL) — 큰 JSON 재읽기 사고(8/5) 반복 금지.
경로는 인자로 받는다 — 시험이 임시 파일을 쓸 수 있고, 엔진 설정과 어긋나지 않는다.

되돌리기: 각 전략에서 이 모듈 호출을 지우면 종전 동작(실황판/자체 관측)이다.
⚠️계약서 config\lowfind_contract_v1.json "공통배관" 절이 이 배선을 잠근다 —
  모듈·임포트·우선순위·필드명을 바꾸면 아침 08:30 리허설이 FAIL 을 띄운다.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Optional

from json_cache_v1 import read_json_cached

HR_STATE_PATH = Path(r"C:\stock_bot\data\common_high_range_live_state.json")
SNAPSHOT_PATH = Path(r"C:\stock_bot\IPC\live_micro_snapshot.json")

# 계약서 잠금 대상. 순서·이름을 바꾸면 아침 리허설이 잡는다.
SOURCE_ORDER = ("실황판", "스냅샷", "자체관측")
SNAPSHOT_FIELDS = ("op", "lo", "hi")          # 거래소 시가/저가/고가 (FID 16/18/17)
HR_FIELDS = ("first_price", "low", "high")    # 실황판 첫관측가/누적저점/누적고점


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _row_date(ts: Any) -> str:
    return str(ts or "").replace("-", "")[:8]


@dataclass(frozen=True)
class DayAnchor:
    """시가·당일저가·당일고가. 0.0 = 아직 모름(호출자가 자체 관측으로 폴백)."""
    open: float
    low: float
    high: float
    source_open: str
    source_low: str
    source_high: str


def day_anchor(
    code: str,
    *,
    today: Optional[str] = None,
    hr_state_path: Path = HR_STATE_PATH,
    snapshot_path: Path = SNAPSHOT_PATH,
) -> DayAnchor:
    """종목코드 → (시가, 당일저가, 당일고가). today("YYYYMMDD")를 주면 날짜가
    어긋난 소스(전일 잔존 파일)는 없는 것으로 친다 — 아침 첫 기동 오염 방지."""
    code = str(code).zfill(6)

    hr_row: Mapping[str, Any] = {}
    hr = read_json_cached(hr_state_path, {})
    if isinstance(hr, Mapping):
        if not today or _row_date(hr.get("date")) == today:
            hr_row = (hr.get("codes") or {}).get(code) or {}

    snap_row: Mapping[str, Any] = {}
    snap = read_json_cached(snapshot_path, {})
    if isinstance(snap, Mapping):
        row = (snap.get("codes") or {}).get(code) or {}
        if isinstance(row, Mapping) and (not today or _row_date(row.get("ts")) == today):
            snap_row = row

    # ★[정합성 2026-08-07 보안검사 지적] 소스를 통째로 검사한 뒤에 쓴다.
    #   여기서 나온 값은 S06 의 무장 판정(drop = 저가/시가 - 1)과 매수구간 계산에
    #   그대로 들어간다. 그런데 읽는 두 파일은 UserK 가 쓸 수 있다. 검사 없이 쓰면
    #   시가를 현재가의 2배로 적어 두는 것만으로 안 빠진 종목이 즉시 무장하고,
    #   저가를 아주 낮게 적으면 그 종목이 하루 종일 매수 대상에서 빠진다.
    #   앞뒤가 안 맞는 소스(저가>고가, 시가가 저가~고가 밖)는 통째로 버리고
    #   다음 소스로 내려간다 — 한 필드만 버리면 짝이 안 맞는 조합이 남는다.
    #   ⚠️abs() 를 쓰지 않는다. 음수를 양수로 바꾸면 이상값이 정상으로 보인다.
    def _sane(row: Mapping[str, Any], keys: tuple) -> tuple[float, float, float] | None:
        o, lo, hi = (_f(row.get(k)) for k in keys)
        if not (lo > 0 and hi > 0 and lo <= hi):
            return None
        if o > 0 and not (lo <= o <= hi):
            return None
        return o, lo, hi

    for row, keys, source in ((hr_row, HR_FIELDS, SOURCE_ORDER[0]),
                              (snap_row, SNAPSHOT_FIELDS, SOURCE_ORDER[1])):
        got = _sane(row, keys)
        if got is None:
            continue
        o, lo, hi = got
        return DayAnchor(open=o, low=lo, high=hi,
                         source_open=(source if o > 0 else SOURCE_ORDER[2]),
                         source_low=source, source_high=source)
    return DayAnchor(open=0.0, low=0.0, high=0.0,
                     source_open=SOURCE_ORDER[2], source_low=SOURCE_ORDER[2],
                     source_high=SOURCE_ORDER[2])
