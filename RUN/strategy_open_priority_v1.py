# -*- coding: utf-8 -*-
"""Atomic S01/S03 opening-priority gate.

S01 waits one three-second batch so the strongest currently-fresh S01 signal
is used.  S03 never waits for S01; a fresh S03 candidate observed during the
same window is recorded as having priority.  SHADOW is the safe default.
"""
from __future__ import annotations

import json
import msvcrt
import os
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Sequence


S01 = "S01_OPEN_SURGE"
S03 = "VALLEY_MORNING_CRASH"


@dataclass(frozen=True)
class PriorityDecision:
    rows: tuple[Mapping[str, Any], ...]
    applies: bool
    waiting: bool
    s03_priority_seen: bool
    reason: str
    elapsed_sec: float


class OpenPriorityGate:
    def __init__(
        self,
        path: Path,
        *,
        wait_sec: float = 3.0,
        mode: str = "SHADOW",
        lock_timeout_sec: float = 1.0,
    ) -> None:
        self.path = Path(path)
        self.wait_sec = float(wait_sec)
        self.mode = str(mode).strip().upper()
        self.lock_timeout_sec = float(lock_timeout_sec)
        if self.wait_sec <= 0:
            raise ValueError("wait_sec must be positive")
        if self.mode not in {"OFF", "SHADOW", "LIVE"}:
            raise ValueError("mode must be OFF, SHADOW, or LIVE")

    @contextmanager
    def _lock(self):
        lock_path = self.path.with_suffix(self.path.suffix + ".lock")
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with lock_path.open("a+b") as handle:
            handle.seek(0, 2)
            if handle.tell() == 0:
                handle.write(b"0")
                handle.flush()
            deadline = time.monotonic() + self.lock_timeout_sec
            while True:
                try:
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise TimeoutError("open-priority lock timeout")
                    time.sleep(0.01)
            try:
                yield
            finally:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)

    def _load(self, session: str) -> dict[str, Any]:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8-sig"))
            if payload.get("date") == session:
                return payload
        except (OSError, ValueError, TypeError):
            pass
        return {"date": session, "batches": {}}

    def _save(self, payload: Mapping[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(
            json.dumps(payload, ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
        )
        os.replace(tmp, self.path)

    @staticmethod
    def _top(rows: Sequence[Mapping[str, Any]]) -> Mapping[str, Any] | None:
        return rows[0] if rows else None

    def evaluate(
        self,
        *,
        strategy_id: str,
        rows: Sequence[Mapping[str, Any]],
        now: datetime,
    ) -> PriorityDecision:
        original = tuple(rows)
        if self.mode == "OFF" or strategy_id not in {S01, S03} or not rows:
            return PriorityDecision(
                original, False, False, False, "NOT_APPLICABLE", 0.0
            )
        top = self._top(rows)
        assert top is not None
        now_epoch = now.timestamp()
        session = now.date().isoformat()
        try:
            with self._lock():
                payload = self._load(session)
                batches = payload.setdefault("batches", {})
                batch = batches.get(strategy_id)
                if not isinstance(batch, dict):
                    batch = {}
                opened = float(batch.get("opened_epoch") or now_epoch)
                if now_epoch < opened or now_epoch - opened > self.wait_sec * 2:
                    opened = now_epoch
                batch.update({
                    "opened_epoch": opened,
                    "last_seen_epoch": now_epoch,
                    "signal_id": str(top.get("signal_id") or ""),
                    "code": str(top.get("code") or "").zfill(6),
                })
                batches[strategy_id] = batch
                elapsed = max(0.0, now_epoch - opened)
                s03 = batches.get(S03)
                s03_seen = bool(
                    strategy_id == S01
                    and isinstance(s03, dict)
                    and float(s03.get("last_seen_epoch") or 0.0) >= opened
                    and now_epoch - float(s03.get("last_seen_epoch") or 0.0)
                    <= self.wait_sec
                )
                waiting = strategy_id == S01 and elapsed < self.wait_sec
                if strategy_id == S01 and not waiting:
                    # The next still-fresh S01 candidate starts a new batch.
                    batches[strategy_id] = {}
                self._save(payload)
        except (OSError, TimeoutError, ValueError, TypeError):
            # A live arbitration failure must fail closed for S01.  S03 keeps
            # its priority path so a broken coordinator cannot invert priority.
            if self.mode == "LIVE" and strategy_id == S01:
                return PriorityDecision(
                    (), True, True, False, "ARBITER_UNAVAILABLE", 0.0
                )
            return PriorityDecision(
                original, True, False, False, "ARBITER_UNAVAILABLE_SHADOW", 0.0
            )

        chosen = (top,)
        reason = "S03_IMMEDIATE_PRIORITY" if strategy_id == S03 else (
            "S03_PRIORITY_OBSERVED" if s03_seen else "S01_WINDOW_COMPLETE"
        )
        if self.mode == "SHADOW":
            return PriorityDecision(
                original, True, waiting, s03_seen, f"SHADOW_{reason}", elapsed
            )
        if waiting:
            return PriorityDecision(
                (), True, True, s03_seen, "S01_WAIT_3S_FOR_S03", elapsed
            )
        return PriorityDecision(chosen, True, False, s03_seen, reason, elapsed)
