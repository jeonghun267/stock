# -*- coding: utf-8 -*-
"""[3분봉 5/10/20선 + 수급 우위 공통모듈 2026-08-03 친구님 지시] 상승보유의 유일한 기준.

친구님 규칙(원문):
    "3분봉이 5일선을 횡보하고 10일선이 받쳐주면 매도하지 않고, 설혹 10일선을
     침범했더라도 20일선이 뒤를 받쳐주면 매도하지 않는다. 이때는 매수세·매도세의
     우위를 확실하게 계산해야 한다. 매수세·매도세는 체결량·거래대금·속도를 꼭
     계산해서, 매수세가 꺾였을 때는 매도해야 한다."
    "20선은 우상향이면 돼"

  → 상승보유(=트레일 매도 보류) = ①선 지지  AND  ②매수세 우위, 둘 다 참일 때만.
     ① 선 지지 : 20선 우상향  AND  (현재가 >= 10선  또는  10선 침범해도 현재가 >= 20선)
     ② 수급    : 매수 대금속도 >= 매도 대금속도  AND  매수세가 꺾이지 않았을 것
                 (꺾임 = 매수 대금속도 식음 + 매도 대금속도 가열 + 매도 체결량 가속)
     ★ 둘 중 하나라도 아니면 상승보유 없음 → 트레일이 정상 작동해서 판다.

★8/3 이전에 무엇이 틀렸나 — S01~S06 이 전부 '일봉' 5/10/20선을 쓰고 있었다.
  일봉 5일선은 장중에 움직이지 않는 고정값이라 하루 안에 깨질 수가 없다.
  8/3 실측: 에스피지 058610 손절가 109,500 이 일봉 5일선 79,240 보다 +38.2% 위.
  2%를 잃고 손절나는 순간까지 "5일선 위"라 상승보유가 100% 참 → 트레일 매도가
  478번 판정 중 124번 통째로 막혔다(엔젤로보틱스는 고점 대비 -6.06% 방치).
  이름만 같고 완전히 다른 선이었다. 이 모듈이 그 혼선을 끝낸다.

자료원: data\돈맥_1분봉.json (deep_bottom_signal_recorder 가 완성 1분봉 70봉 보관)
  1분봉 3개 = 3분봉 1개. 20선끼리 비교하려면 3분봉 21개 = 1분봉 63개가 필요해서
  같은 날 보관 봉수를 60 → 70 으로 늘렸다. 장전 08:30 부터 봉을 쌓아 장초에도
  20선이 서게 했다(신호·CSV 기록은 종전대로 09:00 부터).

★fail-open 원칙: 봉이 모자라거나 수급 자료가 없으면 상승보유를 주지 않는다(False).
  상승보유가 없으면 트레일이 정상 작동한다. 8/3 사고는 "못 파는" 방향이었으므로
  판단 불가일 때는 막지 않는 쪽이 안전하다.

되돌리기: 각 엔진의 backup\*_20260803_ma3common.py 복원.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

BARS_PATH = Path(r"C:\stock_bot\data\돈맥_1분봉.json")

# 3분봉 21개 = 20선 + 직전 20선 비교에 필요한 최소치
MIN_BLOCKS = 21


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def load_payload(path: Path = BARS_PATH) -> Dict[str, Any]:
    """돈맥_1분봉.json 통째로. 읽기 실패는 빈 dict(=판정 불가)."""
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {}


def three_minute_closes(code: str, payload: Dict[str, Any]) -> List[float]:
    """완성된 3분봉 종가 리스트(오래된 → 최근).

    prev 는 완성 1분봉 [o,h,l,c] 의 오래된→최근 배열이다.
    ★시각은 같은 순서의 pm(["0903", ...])에서 읽는다. 기록기가 스냅샷에 안 잡힌
      분을 건너뛰기 때문에 prev 는 연속이 아니고, 시각 없이 역산하면 3분 격자가
      어긋나 5/10/20선이 통째로 틀린다(특히 08:30~09:00 동시호가는 듬성듬성).
      pm 이 없는 옛 자료면 연속 가정으로 역산한다(종전 동작·fail-open).
    · 1분봉이 1개라도 있으면 그 블록을 인정하고, 그 안의 마지막 종가를 3분봉
      종가로 쓴다. ★HTS 차트가 그렇게 그린다 — 체결이 뜸한 3분도 봉을 건너뛰지
      않는다. 3개를 다 요구하면 친구님이 보는 차트와 선이 달라지고, 특히
      08:30~09:00 동시호가는 대부분 버려져 20선이 아예 안 선다.
    · 진행 중인 블록은 제외한다(완성봉만 이평에 넣는다).
    """
    source = payload.get("m") if isinstance(payload.get("m"), dict) else payload
    row = (source or {}).get(str(code).zfill(6)) or {}
    previous = row.get("prev") or []
    hm = str(payload.get("hm") or "")
    if len(hm) != 4 or not hm.isdigit() or not previous:
        return []
    current_minute = int(hm[:2]) * 60 + int(hm[2:])
    labels = row.get("pm") or []
    use_labels = len(labels) == len(previous)

    groups: Dict[int, List[tuple]] = {}
    total = len(previous)
    for index, bar in enumerate(previous):
        if not bar or len(bar) < 4:
            continue
        close = _number(bar[3])
        if close <= 0:
            continue
        if use_labels:
            tag = str(labels[index] or "")
            if len(tag) != 4 or not tag.isdigit():
                continue
            minute = int(tag[:2]) * 60 + int(tag[2:])
            if minute >= current_minute:          # 미래/진행중 봉은 버린다
                continue
        else:
            minute = current_minute - (total - index)
        groups.setdefault(minute // 3, []).append((minute, close))

    closes: List[float] = []
    for block in sorted(groups):
        if block == current_minute // 3:      # 진행 중 블록 제외
            continue
        bars = sorted(groups[block])
        closes.append(bars[-1][1])            # 블록의 마지막 1분봉 종가 = 3분봉 종가
    return closes


def ma3_rows(code: str, payload: Optional[Dict[str, Any]] = None
             ) -> Optional[Dict[str, float]]:
    """3분봉 5/10/20선과 직전 20선. 봉이 모자라면 None(=판정 불가)."""
    closes = three_minute_closes(code, payload if payload is not None
                                 else load_payload())
    if len(closes) < MIN_BLOCKS:
        return None
    return {
        "ma5": sum(closes[-5:]) / 5,
        "ma10": sum(closes[-10:]) / 10,
        "ma20": sum(closes[-20:]) / 20,
        "ma20_prev": sum(closes[-21:-1]) / 20,
        "blocks": float(len(closes)),
    }


def line_support(code: str, price: float,
                 payload: Optional[Dict[str, Any]] = None) -> bool:
    """①선 지지 — 20선 우상향이고, 10선(침범 시 20선)이 받쳐주는가.

    친구님: "10선이 받쳐주면 매도 안 하고, 10선을 침범했더라도 20선이 뒤를
    받쳐주면 매도 안 한다." → 눌림 허용 하한은 20선이다.
    판정 불가면 False.
    """
    row = ma3_rows(code, payload)
    if not row or price <= 0:
        return False
    if not row["ma20"] > row["ma20_prev"]:          # 20선 우상향이 대전제
        return False
    return bool(price >= row["ma10"] or price >= row["ma20"])


def buy_side_alive(
    buy_money_per_sec_10s: float,
    buy_money_per_sec_30s: float,
    sell_money_per_sec_10s: float,
    sell_money_per_sec_30s: float,
    sell_volume_per_sec_5s: float = 0.0,
    sell_volume_per_sec_previous_10s: float = 0.0,
) -> Optional[bool]:
    """②매수세 우위 — 체결량·거래대금·속도로 계산. 자료 없으면 None(판정 불가).

    · 우위   : 매수 대금속도 >= 매도 대금속도 (지금 누가 세냐)
    · 꺾임   : 매수 대금속도 식음(10s<30s) + 매도 대금속도 가열(10s>30s)
               + 매도 체결량 가속(5s > 직전 10s)  ← 셋 다일 때만 '꺾였다'
    친구님: "매수세가 꺾였을 때는 매도해야 한다."

    ★체결량 속도는 S02·S05 만 관측한다(S01·S03·S06 회전엔진엔 그 통로가 없다).
      체결량이 없으면 거래대금 속도 2종만으로 꺾임을 본다. 조건이 하나 줄면
      '꺾였다'가 더 쉽게 성립 = 더 잘 판다 → 안전한 방향이라 그대로 둔다.
    """
    if not (buy_money_per_sec_30s > 0 and sell_money_per_sec_30s > 0):
        return None
    leads = buy_money_per_sec_10s >= sell_money_per_sec_10s
    fading = (
        buy_money_per_sec_10s < buy_money_per_sec_30s
        and sell_money_per_sec_10s > sell_money_per_sec_30s
    )
    if sell_volume_per_sec_previous_10s > 0:      # 체결량 통로가 있는 전략만
        fading = fading and (
            sell_volume_per_sec_5s > sell_volume_per_sec_previous_10s
        )
    return bool(leads and not fading)


def rider_permit(code: str, price: float,
                 payload: Optional[Dict[str, Any]] = None,
                 buy_side: Optional[bool] = None) -> bool:
    """상승보유 허가 — 전 전략 공통. ①선 지지 AND ②매수세 우위.

    buy_side 는 호출측이 buy_side_alive() 로 구한 값. None(판정 불가)이면
    허가하지 않는다 = 트레일 정상 작동(fail-open).
    """
    if buy_side is not True:
        return False
    return line_support(code, price, payload)


def ma5_broken(code: str, price: float,
               payload: Optional[Dict[str, Any]] = None) -> bool:
    """3분봉 5선을 깼는가 — 흐름역전 민감도 조절용(관문 아님).

    판정 불가면 False(=안 깨짐 취급) → 종전 엄격 기준 유지.
    """
    row = ma3_rows(code, payload)
    if not row or price <= 0:
        return False
    return bool(price < row["ma5"])


if __name__ == "__main__":
    import sys

    data = load_payload()
    src = data.get("m") or {}
    print(f"돈맥_1분봉.json  hm={data.get('hm')}  ts={data.get('ts')}  종목 {len(src)}")
    targets = sys.argv[1:] or list(src)[:8]
    ok = 0
    for target in targets:
        target = str(target).zfill(6)
        row = ma3_rows(target, data)
        if not row:
            blocks = len(three_minute_closes(target, data))
            print(f"  {target}  판정불가 (완성 3분봉 {blocks}개 / 필요 {MIN_BLOCKS})")
            continue
        ok += 1
        print(f"  {target}  5선 {row['ma5']:>10,.0f}  10선 {row['ma10']:>10,.0f}  "
              f"20선 {row['ma20']:>10,.0f}  "
              f"{'우상향' if row['ma20'] > row['ma20_prev'] else '우하향'}  "
              f"(3분봉 {int(row['blocks'])}개)")
    print(f"판정 가능 {ok}/{len(targets)}")
