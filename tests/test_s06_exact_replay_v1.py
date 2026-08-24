import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

RUN_DIR = Path(__file__).resolve().parents[1] / "RUN"
if str(RUN_DIR) not in sys.path:
    sys.path.insert(0, str(RUN_DIR))

import strategy_06_exact_input_recorder_v1 as recorder
from s06_capture_only_runner_v1 import _NoOrderBroker, _NoSlots
from s06_exact_replay_v1 import replay_one
from strategy_06_crash_low_chase_v1 import Config, Strategy06Engine

KST = ZoneInfo("Asia/Seoul")
CODE = "123450"


def write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


class S06ExactReplayTest(unittest.TestCase):
    def test_candidate_entry_tick_round_trips_through_real_chase_method(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            base = Path(tmp)
            record_dir = base / "records"
            config = Config(
                live_requested=False,
                rebound_pct=1.0,
                entry_floor_pct=1.0,
                chase_cap_pct=2.0,
                early_entry_cap_pct=1.8,
                watch_path=base / "watch.json",
                hr_state_path=base / "hr.json",
                snapshot_path=base / "snapshot.json",
                names_path=base / "names.json",
                state_path=base / "state.json",
                lock_path=base / "engine.lock",
                event_dir=base / "events",
                fills_dir=base / "fills",
                log_path=base / "engine.log",
                approval_path=base / "never.flag",
                off_flag_path=base / "off.flag",
                manual_buy_block_path=base / "block.flag",
            )
            now = datetime(2026, 8, 21, 9, 5, tzinfo=KST)
            write_json(config.watch_path, {
                "codes": [CODE], "crown_codes": [CODE],
                "for_date": now.strftime("%Y%m%d"), "source_stale": False,
            })
            write_json(config.names_path, {CODE: "TEST"})
            engine = Strategy06Engine(
                config, broker=_NoOrderBroker(), slots=_NoSlots())

            def tick(price: float, low: float, *, advance: int = 3,
                     buy: float = 1000, sell: float = 1000) -> None:
                nonlocal now
                now += timedelta(seconds=advance)
                write_json(config.hr_state_path, {
                    "codes": {CODE: {"first_price": 20000, "low": low}},
                })
                write_json(config.snapshot_path, {"codes": {CODE: {
                    "cur": price, "ts": now.isoformat(), "cum_vol": 10000,
                    "che_str": 60, "buy_money_cum": buy,
                    "sell_money_cum": sell,
                }}})
                engine._snapshot_cache = (0.0, {})
                engine._hr_cache = (0.0, {})
                engine.tick(now)

            with patch.dict("os.environ", {"S06_EXACT_RECORD": "YES"}), \
                    patch.object(recorder, "OUT_DIR", record_dir):
                tick(20000, 20000, advance=20, buy=1000, sell=1000)
                tick(19600, 19600, advance=20, buy=1100, sell=2500)
                tick(18200, 18200, advance=20, buy=1200, sell=4000)
                tick(18200 * 1.0154, 18200, advance=5, buy=1350, sell=4050)
                tick(18200 * 1.0099, 18200, advance=20, buy=1500, sell=4120)
                tick(18200 * 1.0104, 18200, advance=20, buy=1700, sell=4210)
                tick(18200 * 1.0121, 18200, advance=10, buy=2050, sell=4260)
                tick(18200 * 1.0154, 18200, advance=10, buy=2800, sell=4290)

            paths = list(record_dir.glob("s06_exact_input_*.jsonl"))
            self.assertEqual(len(paths), 1)
            path = paths[0]
            records = [json.loads(line) for line in path.read_text(
                encoding="utf-8").splitlines() if line.strip()]
            self.assertEqual(len(records), 8)
            self.assertTrue(records[-1]["entry_decision"])
            replay_dir = base / "replay"
            replay_dir.mkdir()
            result = replay_one(records[-1], replay_dir)
            self.assertTrue(result["match"], result)
            self.assertTrue(result["entry_decision"])

            for handler in list(engine.log.handlers):
                handler.close()
                engine.log.removeHandler(handler)


if __name__ == "__main__":
    unittest.main()
