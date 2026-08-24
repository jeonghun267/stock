# -*- coding: utf-8 -*-

from __future__ import annotations

import unittest
from datetime import datetime, timedelta

from captain2_strategy_01_live_bridge_v1 import select_fresh_signals


NOW = datetime(2026, 7, 27, 9, 3, 5)


def payload(*rows: dict) -> dict:
    return {
        "schema": "captain2_c2_01_shadow_v1",
        "date": "20260727",
        "updated_at": NOW.isoformat(timespec="seconds"),
        "mode": "SHADOW_ORDER_ZERO",
        "signals": list(rows),
    }


def signal(code: str, *, seconds_ago: int = 1, speed: float = 2_000_000,
           ratio: float = 0.72, theme: int = 0) -> dict:
    return {
        "ts": (NOW - timedelta(seconds=seconds_ago)).isoformat(timespec="seconds"),
        "code": code,
        "action": "BUY_READY",
        "mode": "SHADOW_ORDER_ZERO",
        "money_speed_5s": speed,
        "buy_ratio": ratio,
        "theme_bonus": theme,
    }


class LiveBridgeTests(unittest.TestCase):
    def test_accepts_fresh_signal_and_adds_strategy_identity(self) -> None:
        rows = select_fresh_signals(payload(signal("123456")), now=NOW, max_age_sec=5)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["strategy_id"], "C2_01_OPEN_SURGE")
        self.assertEqual(rows[0]["strategy_name"], "장초반 급상승 초입")

    def test_rejects_stale_payload_or_signal(self) -> None:
        stale_payload = payload(signal("123456"))
        stale_payload["updated_at"] = (NOW - timedelta(seconds=6)).isoformat(timespec="seconds")
        self.assertEqual(
            select_fresh_signals(stale_payload, now=NOW, max_age_sec=5), [])
        self.assertEqual(
            select_fresh_signals(
                payload(signal("123456", seconds_ago=6)), now=NOW, max_age_sec=5),
            [],
        )

    def test_rejects_wrong_schema_mode_and_date(self) -> None:
        for key, value in (
            ("schema", "wrong"),
            ("mode", "LIVE"),
            ("date", "20260726"),
        ):
            bad = payload(signal("123456"))
            bad[key] = value
            self.assertEqual(select_fresh_signals(bad, now=NOW, max_age_sec=5), [])

    def test_consumed_signal_is_not_returned(self) -> None:
        raw = signal("123456")
        signal_id = f"20260727:123456:{raw['ts']}"
        rows = select_fresh_signals(
            payload(raw), now=NOW, max_age_sec=5, consumed={signal_id})
        self.assertEqual(rows, [])

    def test_theme_then_speed_then_ratio_priority(self) -> None:
        rows = select_fresh_signals(
            payload(
                signal("111111", speed=9_000_000, theme=0),
                signal("222222", speed=2_000_000, theme=1),
                signal("333333", speed=3_000_000, theme=1),
            ),
            now=NOW,
            max_age_sec=5,
        )
        self.assertEqual([row["code"] for row in rows], ["333333", "222222", "111111"])


if __name__ == "__main__":
    unittest.main()
