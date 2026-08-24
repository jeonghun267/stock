# -*- coding: utf-8 -*-
"""[POLL-SAFETY-PREEMPT 2026-08-19] poll 판 도중 도착한 안전조회 선점 검증.

배경: poll_requests 는 판 시작에 스냅샷을 1회 고정한다. 판 도중 도착한
잔고류 안전조회(우선순위 1)가 남은 일반 TR(5) 꼬리에 묶여 클라이언트
예산(매도 전 1.0s)을 넘겼다 — 8/19 BALANCE-RETRY 8회의 남은 원인.
수리: 일반 TR 처리 직전에 _pending_safety_query_paths() 를 드레인
(BATCH_TR 슬라이스 선점과 동일 패턴).
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest
import logging
import importlib
from pathlib import Path
from unittest.mock import patch


RUN_DIR = Path(__file__).resolve().parents[1] / "RUN"
if str(RUN_DIR) not in sys.path:
    sys.path.insert(0, str(RUN_DIR))


class _NoopRotatingHandler(logging.NullHandler):
    def __init__(self, *args, **kwargs):
        super().__init__()


with patch("logging.handlers.RotatingFileHandler", _NoopRotatingHandler):
    gateway = importlib.import_module("broker_gateway_v1")


def _write_request(path: Path, req_type: str, age_offset: float) -> None:
    path.write_text(json.dumps({"type": req_type}), encoding="utf-8")
    stamp = time.time() + age_offset
    os.utime(path, (stamp, stamp))


def _make_broker(processed: list, on_process=None):
    broker = object.__new__(gateway.BrokerGateway)
    broker.state = gateway.BrokerState.CONNECTED
    broker._poll_in_progress = False

    def process_request(path: Path):
        processed.append(path.name)
        path.unlink(missing_ok=True)
        if on_process:
            on_process(path)

    broker.process_request = process_request
    return broker


class BrokerPollSafetyPreemptTests(unittest.TestCase):
    def test_midpass_balance_preempts_remaining_general_tr(self):
        """첫 일반 TR 처리 중 도착한 BALANCE_TR 이 두 번째 일반 TR 보다 먼저."""
        with tempfile.TemporaryDirectory() as temp_dir:
            req_dir = Path(temp_dir)
            _write_request(req_dir / "tr1.json", "TR", -3)
            _write_request(req_dir / "tr2.json", "TR", -2)
            processed: list = []

            def arrive_balance(path: Path):
                if path.name == "tr1.json":
                    _write_request(req_dir / "balance.json", "BALANCE_TR", 0)

            broker = _make_broker(processed, on_process=arrive_balance)
            with patch.object(gateway, "IPC_REQ", req_dir):
                broker.poll_requests()

        self.assertEqual(processed, ["tr1.json", "balance.json", "tr2.json"])

    def test_no_safety_pending_keeps_snapshot_order(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            req_dir = Path(temp_dir)
            _write_request(req_dir / "tr1.json", "TR", -3)
            _write_request(req_dir / "tr2.json", "TR", -2)
            processed: list = []
            broker = _make_broker(processed)
            with patch.object(gateway, "IPC_REQ", req_dir):
                broker.poll_requests()

        self.assertEqual(processed, ["tr1.json", "tr2.json"])

    def test_snapshot_safety_query_not_processed_twice(self):
        """스냅샷에 이미 있던 안전조회는 정렬로 먼저 처리되고, 드레인이 중복 처리하지 않는다."""
        with tempfile.TemporaryDirectory() as temp_dir:
            req_dir = Path(temp_dir)
            _write_request(req_dir / "balance.json", "BALANCE_TR", -3)
            _write_request(req_dir / "tr1.json", "TR", -2)
            processed: list = []
            broker = _make_broker(processed)
            with patch.object(gateway, "IPC_REQ", req_dir):
                broker.poll_requests()

        self.assertEqual(processed, ["balance.json", "tr1.json"])


if __name__ == "__main__":
    unittest.main()
