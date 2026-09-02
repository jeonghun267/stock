from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch


RUN = Path(__file__).resolve().parents[1] / "RUN"
if str(RUN) not in sys.path:
    sys.path.insert(0, str(RUN))

import s03_s06_crash_claim_v1 as claim


KST = timezone(timedelta(hours=9))


def test_claim_does_not_consume_capital_and_same_low_cannot_reclaim() -> None:
    now = datetime(2026, 8, 31, 9, 1, 0)
    with tempfile.TemporaryDirectory() as folder, patch.dict(
        os.environ, {"S03_S06_CRASH_CLAIM_ENABLED": "YES"}
    ):
        directory = Path(folder)
        assert claim.try_claim_s03(
            "123456", "low-1", now, directory=directory, ttl_sec=2
        ) == "CLAIMED"
        assert claim.s03_claim_status(
            "123456", now, directory=directory) == "CLAIMED"

        expired_at = now + timedelta(seconds=3)
        assert claim.s03_claim_status(
            "123456", expired_at, directory=directory) == "FREE"
        assert claim.try_claim_s03(
            "123456", "low-1", expired_at, directory=directory, ttl_sec=2
        ) == "EXPIRED"
        assert claim.try_claim_s03(
            "123456", "low-2", expired_at, directory=directory, ttl_sec=2
        ) == "CLAIMED"
        assert claim.mark_ordering(
            "123456", expired_at, order_id="order-1", directory=directory)
        assert claim.s03_claim_status(
            "123456", expired_at, directory=directory) == "ORDERING"
        assert claim.release_s03(
            "123456", expired_at, reason="TEST_RELEASE", directory=directory)
        assert claim.s03_claim_status(
            "123456", expired_at, directory=directory) == "FREE"

        payload = json.loads(
            claim.claim_path(now, directory).read_text(encoding="utf-8"))
        assert set(payload) == {"schema", "date", "claims"}
        assert "slots" not in payload
        audit_path = directory / "s03_s06_crash_claim_audit_20260831.jsonl"
        audit_events = [
            json.loads(line)["event"]
            for line in audit_path.read_text(encoding="utf-8").splitlines()
        ]
        assert "CLAIM_CREATED" in audit_events
        assert "CLAIM_ORDERING" in audit_events
        assert "CLAIM_RELEASED" in audit_events


def test_naive_claim_expiry_accepts_timezone_aware_s06_clock() -> None:
    naive_now = datetime(2026, 8, 31, 9, 1, 0)
    with tempfile.TemporaryDirectory() as folder, patch.dict(
        os.environ, {"S03_S06_CRASH_CLAIM_ENABLED": "YES"}
    ):
        directory = Path(folder)
        assert claim.try_claim_s03(
            "123456", "low-1", naive_now, directory=directory, ttl_sec=120
        ) == "CLAIMED"

        aware_now = datetime(2026, 8, 31, 9, 1, 1, tzinfo=KST)
        assert claim.s03_claim_status(
            "123456", aware_now, directory=directory
        ) == "CLAIMED"

def test_claim_expires_at_0920_and_bought_survives_ttl() -> None:
    now = datetime(2026, 8, 31, 9, 19, 59)
    with tempfile.TemporaryDirectory() as folder, patch.dict(
        os.environ, {"S03_S06_CRASH_CLAIM_ENABLED": "YES"}
    ):
        directory = Path(folder)
        assert claim.try_claim_s03(
            "123456", "low-1", now, directory=directory) == "CLAIMED"
        assert claim.s03_claim_status(
            "123456", now + timedelta(seconds=1), directory=directory
        ) == "FREE"

        earlier = datetime(2026, 8, 31, 9, 10, 0)
        assert claim.try_claim_s03(
            "654321", "low-2", earlier, directory=directory) == "CLAIMED"
        assert claim.mark_ordering("654321", earlier, directory=directory)
        assert claim.mark_bought("654321", earlier, directory=directory)
        assert claim.s03_claim_status(
            "654321", earlier + timedelta(minutes=20), directory=directory
        ) == "BOUGHT"


def test_audit_failure_is_best_effort() -> None:
    now = datetime(2026, 8, 31, 9, 1, 0)
    with tempfile.TemporaryDirectory() as folder, patch.object(
        Path, "open", side_effect=OSError("audit unavailable")
    ):
        claim._audit(
            Path(folder) / "authority.json",
            {"code": "123456", "owner": "S03", "state": "CLAIMED"},
            now,
            "CLAIM_CREATED",
        )


def test_active_claims_returns_only_live_rows() -> None:
    now = datetime(2026, 8, 31, 9, 1, 0)
    with tempfile.TemporaryDirectory() as folder, patch.dict(
        os.environ, {"S03_S06_CRASH_CLAIM_ENABLED": "YES"}
    ):
        directory = Path(folder)
        assert claim.try_claim_s03(
            "123456", "low-1", now, directory=directory) == "CLAIMED"
        rows = claim.active_s03_claims(now, directory=directory)
        assert rows["123456"]["state"] == "CLAIMED"


def test_signal_release_cannot_release_bought_or_resurrect_released() -> None:
    now = datetime(2026, 8, 31, 9, 1, 0)
    with tempfile.TemporaryDirectory() as folder, patch.dict(
        os.environ, {"S03_S06_CRASH_CLAIM_ENABLED": "YES"}
    ):
        directory = Path(folder)
        assert claim.try_claim_s03(
            "123456", "low-1", now, directory=directory) == "CLAIMED"
        assert claim.mark_ordering("123456", now, directory=directory)
        assert claim.mark_bought("123456", now, directory=directory)
        assert not claim.release_claimed_s03(
            "123456", now, reason="CODE_DAILY_ENTRY_LIMIT_2",
            directory=directory)
        assert claim.s03_claim_status(
            "123456", now, directory=directory) == "BOUGHT"

        assert claim.try_claim_s03(
            "654321", "low-2", now, directory=directory) == "CLAIMED"
        assert claim.release_claimed_s03(
            "654321", now, reason="GIVEUP", directory=directory)
        assert not claim.mark_ordering(
            "654321", now, directory=directory)
        assert claim.s03_claim_status(
            "654321", now, directory=directory) == "FREE"
