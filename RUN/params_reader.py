# -*- coding: utf-8 -*-
"""
params_reader.py — params_reader_v1_13_final 래퍼
모든 모듈이 이 파일을 import 한다. 버전 파일이 바뀌어도 이 파일만 수정하면 된다.
"""
from params_reader_v1_13_final import *   # get_rt_sell, get_kelly 등 전체 재노출

import json
from pathlib import Path

_PARAMS_PATH = Path(__file__).resolve().parent.parent / "DATA" / "params.json"


def get(key: str, default=None):
    """
    params.json 에서 flat key 조회.
    kiwoom_buy_order_sender _params_get("exec_max_slip_bps", None) 등에 사용.
    섹션 불문하고 키 이름으로 직접 검색, 없으면 default 반환.
    """
    import logging as _lg
    try:
        with open(_PARAMS_PATH, encoding="utf-8-sig") as f:
            d = json.load(f)
        if key in d:
            return d[key]
        for v in d.values():
            if isinstance(v, dict) and key in v:
                return v[key]
        return default
    except FileNotFoundError:
        _lg.getLogger("params_reader").debug("params.json 없음, key=%s → default", key)
        return default
    except json.JSONDecodeError as e:
        _lg.getLogger("params_reader").error("params.json 파싱 오류: %s, key=%s → default", e, key)
        return default
    except Exception as e:
        _lg.getLogger("params_reader").error("params.json 읽기 실패: %s, key=%s → default", e, key)
        return default
