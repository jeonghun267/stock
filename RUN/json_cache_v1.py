# -*- coding: utf-8 -*-
"""[읽기 캐시 공통모듈 2026-08-05 친구님 지시 "모든 전략들이 공동으로 사용하게 해줘"]

같은 JSON 파일을 한 틱 안에서 여러 번, 그리고 종목마다 다시 읽는 것을 막는다.

★왜 만들었나 — 8/5 실측
  자료(스냅샷)는 초당 1회 오는데 엔진은 2.34초마다 판정했다. 절반 이상을 버린 셈이다.
  범인은 전략이 아니라 파일 재읽기였다.
    · 돈맥_1분봉.json 5.56MB 를 한 틱에 5번          (112.6ms x 5)
    · ma3_common_v1.load_payload() 가 종목마다 또 통째로 (payload 를 안 넘기고 부르는 경로)
    · 봉이 모자라면 2.58MB 시드까지 종목마다
    · 149바이트짜리 보드도 16ms — read_json 안의 time.sleep(0.003) 이
      윈도우에서 실제로 15.5ms 걸리기 때문이다(타이머 분해능).
  그 결과 매도 확인창 3초가 표본을 1~2개밖에 못 받아 "3초 확인"이 사실상 즉시 매도였다.
  (감사기록 근거: data\audit\hold_sell\ · memory.md 8/5 저녁 항목)

★안전장치 2겹
  ① mtime + 크기가 그대로일 때만 재사용한다. 파일이 바뀌면 즉시 다시 읽는다.
  ② 그래도 0.5초가 지나면 무조건 다시 읽는다. mtime 이 잘 안 도는 파일계에서도
     오래된 자료를 들고 있지 않게 하는 마지막 방어선이다.

⚠️돌려주는 객체를 공유한다 — 내용을 고치는 소비처에는 절대 쓰면 안 된다.
  쓰기 전에 소비처가 .get() 만 하는지 확인할 것. 엔진이 직접 쓰는 상태파일
  (state_path)·선별기 콜백이 손대는 신호파일(signal_path)은 일부러 제외했다.

되돌리기: 각 파일에서 read_json_cached -> read_json 으로 되돌리면 끝.
  백업 RUN\backup\*_20260805_before_readcache.py
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict

CACHE_TTL_SEC = 0.5

# key: str(path) -> (mtime_ns, size, monotonic, payload)
_CACHE: Dict[str, Any] = {}


def read_json_cached(path: Path, default: Any) -> Any:
    """읽기 전용 JSON. mtime+크기가 같고 0.5초 안이면 직전 결과를 그대로 돌려준다.

    읽기 실패는 default. 실패는 캐시하지 않는다(다음 호출에서 다시 시도한다).
    """
    key = str(path)
    try:
        stat = path.stat()
    except OSError:
        return default
    hit = _CACHE.get(key)
    now = time.monotonic()
    if (
        hit is not None
        and hit[0] == stat.st_mtime_ns
        and hit[1] == stat.st_size
        and (now - hit[2]) < CACHE_TTL_SEC
    ):
        return hit[3]
    # ★원본 read_json 의 이중 읽기 방어를 그대로 유지한다(쓰는 중인 파일을 반쯤 읽는 것 차단).
    #   캐시가 붙어 한 틱에 한 번만 미스가 나므로 이 비용은 거의 없다.
    try:
        first = path.read_bytes()
        time.sleep(0.003)
        second = path.read_bytes()
        if first != second:
            return default
        payload = json.loads(second.decode("utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return default
    _CACHE[key] = (stat.st_mtime_ns, stat.st_size, now, payload)
    return payload


def clear() -> None:
    """시험용 — 캐시를 비운다."""
    _CACHE.clear()
