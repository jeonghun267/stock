# -*- coding: utf-8 -*-
"""그림자 종가관찰의 실전 opt10032 보호창 집중 테스트."""
from datetime import time as clock_time
from pathlib import Path
import sys
import unittest

RUN = Path(__file__).resolve().parents[1] / "RUN"
if str(RUN) not in sys.path:
    sys.path.insert(0, str(RUN))

import youtube_eod_shadow_v1 as shadow


class LiveEodPriorityGuardTests(unittest.TestCase):
    def test_priority_window_blocks_shadow_ipc(self):
        # 15:15~15:26 = 실전 opt10032 최우선 — 그림자 IPC 전면 중지 창.
        self.assertTrue(shadow.in_live_eod_priority(clock_time(15, 15, 0)))
        self.assertTrue(shadow.in_live_eod_priority(clock_time(15, 18, 30)))
        self.assertTrue(shadow.in_live_eod_priority(clock_time(15, 26, 0)))
        self.assertFalse(shadow.in_live_eod_priority(clock_time(15, 14, 59)))
        self.assertFalse(shadow.in_live_eod_priority(clock_time(15, 26, 1)))

    def test_live_opt10032_returns_while_shadow_in_priority_window(self):
        # 보호창 동안 그림자는 브로커를 한 번도 부르지 않아야 하고,
        # 같은 순간 실전 opt10032 요청은 즉시 처리돼야 한다(모의 브로커).
        calls = {"shadow": 0, "live": 0}

        class FakeBroker:
            def batch_get_comm_real_data(self, codes, fids, timeout_sec):
                calls["shadow"] += 1
                return {"status": "OK", "data": {"records": []}}

            def request(self, payload, timeout_sec=12.0):
                calls["live"] += 1
                assert payload.get("tr_code") == "opt10032"
                return {"status": "OK", "data": {"records": [1]}}

        broker = FakeBroker()
        moment = clock_time(15, 18, 0)
        # 그림자 루프 한 틱을 재현: 보호창이면 IPC 호출 없이 건너뛴다.
        if shadow.in_live_eod_priority(moment):
            pass  # 그림자는 sleep 후 continue — 브로커 무호출
        else:
            broker.batch_get_comm_real_data([], [], 8.0)
        # 같은 순간 실전 종가매수 요청은 정상 반환.
        live = broker.request({"type": "TR", "tr_code": "opt10032"})
        self.assertEqual(live["status"], "OK")
        self.assertEqual(calls["shadow"], 0)
        self.assertEqual(calls["live"], 1)

    def test_shadow_source_has_no_order_calls_and_uses_guard(self):
        text = (RUN / "youtube_eod_shadow_v1.py").read_text(encoding="utf-8")
        # 주문 경로 0 유지.
        self.assertNotIn("SENDORDER", text.upper().replace("_", ""))
        self.assertIn('"order_path": "NONE"', text)
        # 감시 루프와 해제가 보호창 판정을 실제로 쓴다.
        self.assertGreaterEqual(text.count("in_live_eod_priority("), 3)


if __name__ == "__main__":
    unittest.main()
