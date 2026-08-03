from __future__ import annotations

import json
import multiprocessing
import sys
import tempfile
import unittest
from pathlib import Path


RUN_DIR = Path(__file__).resolve().parents[1] / "RUN"
if str(RUN_DIR) not in sys.path:
    sys.path.insert(0, str(RUN_DIR))


def _acquire_worker(path: str, owner: str, start, output) -> None:
    import shared_slots

    shared_slots.FILE = Path(path)
    start.wait(5)
    output.put((owner, shared_slots.acquire("123450", owner, "20260727")))


class SharedSlotConcurrencyTests(unittest.TestCase):
    def test_two_strategies_cannot_acquire_same_code(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path = str(Path(raw) / "shared_slots.json")
            context = multiprocessing.get_context("spawn")
            start = context.Event()
            output = context.Queue()
            workers = [
                context.Process(
                    target=_acquire_worker,
                    args=(path, owner, start, output),
                )
                for owner in ("STRATEGY01", "STRATEGY03")
            ]
            for worker in workers:
                worker.start()
            start.set()
            results = [output.get(timeout=10) for _ in workers]
            for worker in workers:
                worker.join(10)
                self.assertEqual(worker.exitcode, 0)

            self.assertEqual(sum(bool(result) for _, result in results), 1)
            ledger = json.loads(Path(path).read_text(encoding="utf-8"))
            self.assertEqual(len(ledger["slots"]), 1)
            self.assertIn(
                ledger["slots"]["123450"]["strat"],
                {"STRATEGY01", "STRATEGY03"},
            )


if __name__ == "__main__":
    unittest.main()
