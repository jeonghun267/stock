# -*- coding: utf-8 -*-
"""[친구님 2026-06-28] shadow 안전 가드 — health_check가 위험 감지시 SHADOW_DISABLED.flag 생성→그림자들 자동 skip.
★실매도/매수/che_exit/주문 로직과 무관(그림자 기록만 중단). 부하/누수시 시스템 보호."""
import os

FLAG = r"C:\stock_bot\IPC\SHADOW_DISABLED.flag"


def is_disabled():
    return os.path.exists(FLAG)


def reason():
    try:
        with open(FLAG, encoding="utf-8") as f:
            return f.read().strip()
    except Exception:
        return ""
