# -*- coding: utf-8 -*-
"""★[SELL-LOCK 2026-08-04] 승인 깃발이 장중에 깨져도 실포지션은 실매도된다.

막으려는 사고: 8/4 에 real_session 을 '깃발 존재'에서 '내용·날짜 유효'로 조인 뒤,
깃발이 장중에 깨지면(BOM·재작성 중 빈 파일·시계 역행) real_session 이 False 가 되고
holdings() 가 None 이 아니라 {} 를 돌려준다. _start_sell 은 그걸
'BROKER_ALREADY_FLAT' 으로 읽어 실제로 팔지 않은 채 포지션을 장부에서 지운다
= 7/14 유령 잔량 재현.
"""
from __future__ import annotations

import logging
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path


RUN_DIR = Path(__file__).resolve().parents[1] / "RUN"
if str(RUN_DIR) not in sys.path:
    sys.path.insert(0, str(RUN_DIR))

from strategy_common_order_v1 import StrategyBroker  # noqa: E402


ACTIVE_PHASES = {"HOLDING", "SELL_PENDING"}


class _NoBrokerStrategyBroker(StrategyBroker):
    """브로커 접속만 차단해 holdings() 의 분기를 결정적으로 관찰한다."""

    def connect(self) -> bool:
        return False


class SellLockRegressionTests(unittest.TestCase):
    def setUp(self) -> None:
        self._folder = tempfile.TemporaryDirectory()
        self.root = Path(self._folder.name)
        self.state: dict = {"positions": {}}
        self.addCleanup(self._folder.cleanup)

    def broker(self, *, force_exit_only, cls=StrategyBroker):
        return cls(
            live_requested=True,
            approval_path=self.root / "approval.flag",
            off_flag_path=self.root / "off.flag",
            manual_buy_block_path=self.root / "manual.flag",
            logger=logging.getLogger("sell-lock"),
            order_prefix="STRATEGY01",
            force_exit_only=force_exit_only,
        )

    def holds_real_position(self) -> bool:
        return any(
            position.get("real") and position.get("phase") in ACTIVE_PHASES
            for position in (self.state.get("positions") or {}).values()
        )

    def approve(self) -> None:
        (self.root / "approval.flag").write_text(
            f"APPROVED_BY_OWNER {datetime.now():%Y%m%d %H:%M:%S}\n",
            encoding="ascii",
        )

    def break_approval_with_bom(self) -> None:
        """가장 현실적인 파손 경로. PowerShell 기본 인코딩이 BOM 을 붙인다."""
        (self.root / "approval.flag").write_bytes(
            b"\xef\xbb\xbf"
            + f"APPROVED_BY_OWNER {datetime.now():%Y%m%d %H:%M:%S}\n".encode("ascii")
        )

    def buy_real_position(self) -> None:
        self.state["positions"]["005930"] = {"real": True, "phase": "HOLDING"}

    # ── 핵심 회귀 ──────────────────────────────────────────────────────────

    def test_position_bought_after_startup_survives_broken_approval(self):
        """기동 시 포지션 0 -> 장중 실매수 -> 깃발 파손. 매도 경로가 살아야 한다."""
        self.approve()
        broker = self.broker(force_exit_only=self.holds_real_position)
        self.assertTrue(broker.buy_allowed, "정상 상태에서는 매수가 열려 있어야 한다")

        self.buy_real_position()
        self.break_approval_with_bom()

        self.assertTrue(
            broker.real_session, "실포지션이 있으면 깃발이 깨져도 실매도가 가능해야 한다")
        self.assertFalse(broker.buy_allowed, "깃발이 깨졌으면 매수는 막혀야 한다")
        self.assertEqual("LIVE_EXIT_ONLY", broker.mode)

    def test_stale_snapshot_was_the_bug(self):
        """고정 bool(옛 방식)이면 같은 상황에서 매도가 그림자로 떨어진다."""
        self.approve()
        broker = self.broker(force_exit_only=False)   # __init__ 시점 스냅샷
        self.buy_real_position()
        self.break_approval_with_bom()

        self.assertFalse(broker.real_session)
        self.assertEqual("SHADOW", broker.mode)

    def test_holdings_returns_none_not_empty_dict(self):
        """유령 삭제의 실제 통로. {} 는 'BROKER_ALREADY_FLAT' 으로 오독된다."""
        self.approve()
        broken = self.broker(
            force_exit_only=False, cls=_NoBrokerStrategyBroker)
        fixed = self.broker(
            force_exit_only=self.holds_real_position, cls=_NoBrokerStrategyBroker)
        self.buy_real_position()
        self.break_approval_with_bom()

        # 옛 방식: 잔고가 비었다고 답한다 -> 팔지 않고 장부에서 삭제
        self.assertEqual({}, broken.holdings())
        # 고친 방식: 확인 불가를 알린다 -> _start_sell 이 재시도한다
        self.assertIsNone(fixed.holdings())

    # ── 반대 방향(과잉 허용) 방지 ─────────────────────────────────────────

    def test_no_position_stays_shadow(self):
        self.break_approval_with_bom()
        broker = self.broker(force_exit_only=self.holds_real_position)
        self.assertFalse(broker.real_session)
        self.assertEqual("SHADOW", broker.mode)

    def test_shadow_position_does_not_open_real_session(self):
        self.break_approval_with_bom()
        self.state["positions"]["005930"] = {"real": False, "phase": "HOLDING"}
        broker = self.broker(force_exit_only=self.holds_real_position)
        self.assertFalse(
            broker.real_session, "모의 진입은 실매도 주문을 만들면 안 된다")

    def test_closed_position_does_not_open_real_session(self):
        self.break_approval_with_bom()
        self.state["positions"]["005930"] = {"real": True, "phase": "CLOSED"}
        broker = self.broker(force_exit_only=self.holds_real_position)
        self.assertFalse(broker.real_session)

    def test_shadow_run_never_becomes_real(self):
        """live_requested=NO 면 보유가 있어도 실주문은 나가지 않는다."""
        self.approve()
        self.buy_real_position()
        broker = StrategyBroker(
            live_requested=False,
            approval_path=self.root / "approval.flag",
            off_flag_path=self.root / "off.flag",
            manual_buy_block_path=self.root / "manual.flag",
            logger=logging.getLogger("sell-lock"),
            order_prefix="STRATEGY01",
            force_exit_only=self.holds_real_position,
        )
        self.assertFalse(broker.real_session)

    def test_exit_only_never_enables_buy(self):
        self.break_approval_with_bom()
        self.buy_real_position()
        broker = self.broker(force_exit_only=self.holds_real_position)
        self.assertFalse(broker.buy_allowed)

    # ── 판정 실패 시 방향 ─────────────────────────────────────────────────

    def test_provider_failure_allows_exit(self):
        """보유 판정 자체가 실패하면 '보유 중'으로 본다 - 못 파는 쪽이 더 위험하다."""
        def explode() -> bool:
            raise RuntimeError("state file unreadable")

        self.break_approval_with_bom()
        broker = self.broker(force_exit_only=explode)
        self.assertTrue(broker.real_session)
        self.assertFalse(broker.buy_allowed)

    def test_static_bool_still_supported(self):
        self.break_approval_with_bom()
        self.assertTrue(self.broker(force_exit_only=True).real_session)
        self.assertFalse(self.broker(force_exit_only=False).real_session)


if __name__ == "__main__":
    unittest.main()
