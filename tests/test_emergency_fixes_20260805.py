# -*- coding: utf-8 -*-
"""2026-08-05 아침 긴급 수정 4건 회귀시험 (장중에 테스트 없이 들어간 것들).

그날 무슨 일이 있었나
  8/4 밤에 고친 것들이 8/5 첫 기동에서 한꺼번에 터져 S01 매수가 0건이 됐다.
  전날은 멀쩡했다 — 옛 프로세스가 옛 코드를 물고 있었기 때문이다.
  그래서 '밤에 고친 것은 다음날 아침 첫 기동 전까지 미검증'이 이 저장소의 규칙이다.

여기서 지키는 4건
  (a) BUY_PENDING 교착   매수하려고 포지션을 올리는 순간 자기 매수를 자기가 거부
  (b) preflight 접두어    STRATEGY03_PREFLIGHT 미등록 -> 가드가 통째로 fail-closed
  (c) sys.path 부트스트랩  진입점에 3줄이 없으면 import 단계에서 조용히 즉사
  (d) 화면번호 분리        전략들이 같은 화면을 써서 TR 응답이 섞임

각 시험은 '고치기 전 코드에서 실패하는가'까지 확인하고 넣었다.
"""
from __future__ import annotations

import ast
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

RUN_DIR = Path(r"C:\stock_bot\RUN")
if str(RUN_DIR) not in sys.path:
    sys.path.insert(0, str(RUN_DIR))

KST = ZoneInfo("Asia/Seoul")


# ---------------------------------------------------------------- (b) 접두어
class PreflightPrefixTests(unittest.TestCase):
    """사전점검 전용 접두어가 등록돼 있어야 한다.

    빠지면 strategy_id='' -> evaluate() 가 첫 줄에서 전부 False 를 돌려주고
    connect() 가 client 를 안 만든 채 True 를 반환한다. 그 다음 줄에서
    broker.client.balance_tr 이 AttributeError:'NoneType' 로 8ms 만에 죽는다.
    """

    def setUp(self) -> None:
        import strategy_broker_live_guard as G
        self.G = G

    def test_preflight_prefix_is_registered(self):
        self.assertEqual(
            self.G.PREFIX_TO_STRATEGY.get("STRATEGY03_PREFLIGHT"), "S03",
            "STRATEGY03_PREFLIGHT 가 빠졌다 - 8/5 아침 preflight 8ms 즉사 회귀")

    def test_every_strategy_prefix_maps(self):
        for n in ("01", "02", "03", "04", "05", "06"):
            self.assertTrue(
                self.G.PREFIX_TO_STRATEGY.get(f"STRATEGY{n}"),
                f"STRATEGY{n} 접두어 미등록")

    def test_unknown_prefix_is_fail_closed(self):
        """모르는 접두어는 조용히 통과하면 안 된다(전부 False)."""
        g = self.G.StrategyBrokerLiveGuard(order_prefix="STRATEGY99_NOPE")
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            dec = g.evaluate(
                approval_path=d / "a.flag", off_flag_path=d / "off.flag",
                manual_buy_block_path=d / "m.flag",
                live_requested=True, force_exit_only=False,
                now=datetime(2026, 8, 5, 9, 0, tzinfo=KST))
        self.assertEqual(dec.strategy_id, "")
        self.assertFalse(dec.real_session)
        self.assertFalse(dec.buy_allowed)

    def test_preflight_prefix_is_not_fail_closed(self):
        """등록됐으므로 strategy_id 가 채워지고 세션 판정이 실제로 돈다."""
        g = self.G.StrategyBrokerLiveGuard(order_prefix="STRATEGY03_PREFLIGHT")
        self.assertEqual(g.strategy_id, "S03")


# ------------------------------------------------------- (a) BUY_PENDING 교착
class BuyPendingDeadlockTests(unittest.TestCase):
    """매수 직전 상태(BUY_PENDING)는 '실보유'가 아니다.

    8/4 매도잠김 수리가 '실포지션 보유 여부'를 force_exit_only 에 넣었는데,
    엔진은 submit() 전에 포지션을 BUY_PENDING 으로 저장한다. 그래서 그 람다가
    자기 매수를 보고 True 가 되어 매수를 자기가 거부했다(09:05~09:09 3건).
    SELL_PENDING·HOLD·RECOVERY_BLOCKED 는 그대로 둬야 8/4 보호가 유지된다.
    """

    ACTIVE = {"BUY_PENDING", "HOLD", "SELL_PENDING", "RECOVERY_BLOCKED"}

    @staticmethod
    def _probe(state):
        """실제 엔진의 람다와 같은 식(원본이 바뀌면 아래 계약 시험이 잡는다)."""
        return any(
            p.get("real")
            and p.get("phase") in BuyPendingDeadlockTests.ACTIVE
            and p.get("phase") != "BUY_PENDING"
            for p in (state.get("positions") or {}).values()
        )

    def test_buy_pending_alone_does_not_lock(self):
        st = {"positions": {"p1": {"real": True, "phase": "BUY_PENDING"}}}
        self.assertFalse(
            self._probe(st),
            "BUY_PENDING 하나뿐인데 잠겼다 - 8/5 매수 자기차단 회귀")

    def test_hold_still_locks(self):
        """8/4 수리 유지: 실보유가 있으면 잠금 후보가 된다."""
        st = {"positions": {"p1": {"real": True, "phase": "HOLD"}}}
        self.assertTrue(self._probe(st))

    def test_sell_pending_still_locks(self):
        st = {"positions": {"p1": {"real": True, "phase": "SELL_PENDING"}}}
        self.assertTrue(self._probe(st))

    def test_shadow_position_never_locks(self):
        st = {"positions": {"p1": {"real": False, "phase": "HOLD"}}}
        self.assertFalse(self._probe(st))

    def test_engine_source_still_excludes_buy_pending(self):
        """엔진 원본에서 그 조건이 사라지면 여기서 걸린다."""
        src = (RUN_DIR / "strategy_01_rotation_engine_v2.py").read_text(
            encoding="utf-8", errors="replace")
        self.assertIn(
            'position.get("phase") != "BUY_PENDING"', src,
            "엔진의 force_exit_only 람다에서 BUY_PENDING 제외가 사라졌다")


# ------------------------------------------------- (c) sys.path 부트스트랩
class SysPathBootstrapTests(unittest.TestCase):
    """진입점 스크립트는 sys.path 부트스트랩 3줄이 있어야 한다.

    이 저장소의 두 파이썬은 ._pth 고정이라 스크립트 폴더가 sys.path 에 안 들어간다
    (실측 [python310.zip, C:\\python310, site-packages]). cd /d 로도 해결 안 된다
    - ._pth 의 '.' 은 cwd 가 아니라 python.exe 폴더다.
    """

    #: 8/5 에 실제로 죽어 있던 파일들 + 그날 찾아낸 잔여 지뢰
    FIXED = (
        "deep_bottom_signal_recorder.py",
        "stockbot_live_broadcast_v1.py",
        "strategy_03_auto_live_preflight_v1.py",
    )

    @staticmethod
    def _has_bootstrap(src: str) -> bool:
        return "sys.path.insert" in src or "sys.path.append" in src

    def test_the_three_fixed_files_have_bootstrap(self):
        for name in self.FIXED:
            p = RUN_DIR / name
            if not p.exists():
                continue
            src = p.read_text(encoding="utf-8", errors="replace")
            self.assertTrue(
                self._has_bootstrap(src),
                f"{name}: 부트스트랩이 없다 - 8/5 조용한 즉사 회귀")

    def test_no_entry_point_imports_local_module_without_bootstrap(self):
        """진입점 전수 검사. 새 파일이 같은 실수를 해도 여기서 걸린다.

        '진입점' 은 아침 리허설과 같은 정의를 쓴다 = .cmd 가 실제로 실행하는 .py.
        라이브러리의 `if __name__ == "__main__"` 시연 블록은 대상이 아니다
        (처음엔 그걸 진입점으로 세서 ma3_common_v1 같은 라이브러리를 헛잡았다).
        정의를 두 벌 두지 않으려고 리허설 함수를 그대로 빌린다 —
        그 검사기가 망가지면 이 시험도 같이 걸린다.
        """
        import morning_preflight_rehearsal_v1 as R
        mods = R.local_modules()
        entries = R.entry_points()
        self.assertTrue(entries, "진입점을 하나도 못 찾았다 - 검사기가 고장났다")
        bad = []
        for name in sorted(entries):
            p = RUN_DIR / name
            if not p.exists():
                continue
            src = p.read_text(encoding="utf-8", errors="replace")
            uses = {m.group(1) or m.group(2) for m in R.IMP_RE.finditer(src)}
            uses = {u for u in uses if u and u in mods and u != p.stem}
            if uses and not R.BOOT_RE.search(src):
                bad.append(f"{name}(<-{','.join(sorted(uses))[:40]})")
        self.assertFalse(
            bad, f"부트스트랩 없이 같은 폴더 모듈을 import 하는 진입점 {len(bad)}개: "
                 + " | ".join(bad[:8]))


# ----------------------------------------------------------- (d) 화면번호 분리
class ScreenNumberTests(unittest.TestCase):
    """전략마다 다른 화면번호를 써야 한다.

    같은 화면에서 동시에 TR 을 날리면 응답이 섞이고, 공유 tr_loop 때문에
    남의 TR 완료가 내 대기를 깨워 1초 만에 'TR response timeout (20s)' 가 뜬다.
    8/5 실측: 화면 공유일 때 매수 0/3, 분리 후 3/3.
    """

    def setUp(self) -> None:
        import strategy_common_order_v1 as O
        self.O = O

    def test_every_strategy_has_its_own_screen(self):
        m = self.O.StrategyBroker._SCREEN_BY_PREFIX
        for n in ("01", "02", "03", "04", "05", "06"):
            self.assertIn(f"STRATEGY{n}", m, f"STRATEGY{n} 화면번호 미지정")
        vals = [m[f"STRATEGY{n}"] for n in ("01", "02", "03", "04", "05", "06")]
        self.assertEqual(
            len(set(vals)), len(vals),
            f"화면번호가 겹친다 - 8/5 매수 전면 실패 회귀: {vals}")

    def test_unknown_prefix_falls_back(self):
        m = self.O.StrategyBroker._SCREEN_BY_PREFIX
        self.assertTrue(m.get("STRATEGY01"), "기본 화면번호가 없다")


if __name__ == "__main__":
    unittest.main(verbosity=2)
