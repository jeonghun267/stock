# -*- coding: utf-8 -*-
"""Append-only, hash-chained audit records for the production sell boundary."""
from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import asdict, is_dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional


AUDIT_SCHEMA = "hold_sell_audit_v1"
POST_EXIT_OBSERVATION_SCHEMA = "post_exit_observation_audit_v1"
ZERO_HASH = "0" * 64


class AuditError(RuntimeError):
    """An audit stream is missing, corrupt, or cannot be written."""


def json_value(value: Any) -> Any:
    if is_dataclass(value):
        return json_value(asdict(value))
    if isinstance(value, Mapping):
        return {str(key): json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_value(item) for item in value]
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Path):
        return str(value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def canonical_bytes(payload: Mapping[str, Any]) -> bytes:
    return json.dumps(
        json_value(payload),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def sha256_files(paths: Iterable[Path]) -> str:
    resolved = sorted({Path(path).resolve() for path in paths}, key=str)
    if not resolved:
        raise AuditError("engine file list is empty")
    if len(resolved) == 1:
        return sha256_file(resolved[0])
    digest = hashlib.sha256()
    for path in resolved:
        digest.update(str(path).encode("utf-8"))
        digest.update(b"\0")
        digest.update(sha256_file(path).encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest().upper()


def row_hash(payload_without_hash: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_bytes(payload_without_hash)).hexdigest().upper()


def _safe_name(value: Any) -> str:
    text = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value or "unknown"))
    return text.strip("._")[:120] or "unknown"


class HoldSellAuditRecorder:
    def __init__(
        self,
        root: Path,
        engine_path: Path | Iterable[Path],
        *,
        enabled: bool = True,
        strict: bool = False,
        runtime_profile: Optional[Mapping[str, Any]] = None,
    ) -> None:
        self.root = Path(root)
        raw_paths = (
            [engine_path]
            if isinstance(engine_path, (str, Path))
            else list(engine_path)
        )
        self.engine_paths = sorted(
            {Path(path).resolve() for path in raw_paths}, key=str
        )
        self.engine_path = self.engine_paths[0] if self.engine_paths else Path(".")
        self.enabled = bool(enabled)
        self.strict = bool(strict)
        self.runtime_profile = json_value(runtime_profile or {})
        self.engine_hash = (
            sha256_files(self.engine_paths)
            if self.enabled and all(path.exists() for path in self.engine_paths)
            else ""
        )
        self._tails: dict[Path, tuple[int, str]] = {}
        self.last_error = ""

    @classmethod
    def disabled(cls) -> "HoldSellAuditRecorder":
        return cls(Path("."), Path("."), enabled=False)

    def _target(self, state: Any, observation: Any) -> Path:
        date_text = observation.observed_at.strftime("%Y%m%d")
        strategy = _safe_name(getattr(state.strategy_id, "value", state.strategy_id))
        code = _safe_name(state.code)
        position = _safe_name(state.position_id)
        return self.root / date_text / strategy / f"{code}__{position}.jsonl"

    def _tail(self, path: Path) -> tuple[int, str]:
        cached = self._tails.get(path)
        if cached is not None:
            return cached
        sequence = 0
        previous = ZERO_HASH
        if path.exists():
            try:
                with path.open("r", encoding="utf-8") as handle:
                    for line in handle:
                        if not line.strip():
                            continue
                        payload = json.loads(line)
                        sequence = int(payload["sequence"])
                        previous = str(payload["row_hash"])
            except (OSError, ValueError, KeyError, TypeError) as exc:
                raise AuditError(f"cannot resume corrupt audit stream: {path}: {exc}")
        self._tails[path] = (sequence, previous)
        return sequence, previous

    def record(
        self,
        *,
        state_before: Mapping[str, Any],
        observation: Any,
        decision: Any,
        state_after: Mapping[str, Any],
    ) -> Optional[Path]:
        if not self.enabled:
            return None
        try:
            target = self._target_from_values(state_before, observation)
            target.parent.mkdir(parents=True, exist_ok=True)
            sequence, previous = self._tail(target)
            payload = {
                "schema": AUDIT_SCHEMA,
                "sequence": sequence + 1,
                "captured_at": datetime.now().astimezone().isoformat(),
                "engine_path": str(self.engine_path),
                "engine_paths": [str(path) for path in self.engine_paths],
                "engine_sha256": self.engine_hash,
                "runtime_profile": self.runtime_profile,
                "initial_state_complete": bool(
                    sequence > 0 or not state_before.get("last_observed_at")
                ),
                "state_before": json_value(state_before),
                "observation": json_value(observation),
                "decision": json_value(decision),
                "state_after": json_value(state_after),
                "prev_hash": previous,
            }
            payload["row_hash"] = row_hash(payload)
            encoded = canonical_bytes(payload) + b"\n"
            descriptor = os.open(
                str(target),
                os.O_APPEND | os.O_CREAT | os.O_WRONLY | getattr(os, "O_BINARY", 0),
            )
            try:
                os.write(descriptor, encoded)
            finally:
                os.close(descriptor)
            self._tails[target] = (sequence + 1, payload["row_hash"])
            self.last_error = ""
            return target
        except Exception as exc:
            self.last_error = str(exc)
            if self.strict:
                raise
            return None

    def _target_from_values(
        self,
        state_before: Mapping[str, Any],
        observation: Any,
    ) -> Path:
        observed_at = getattr(observation, "observed_at", None)
        if not isinstance(observed_at, datetime):
            raise AuditError("observation timestamp missing")
        date_text = observed_at.strftime("%Y%m%d")
        strategy = _safe_name(state_before.get("strategy_id"))
        code = _safe_name(state_before.get("code"))
        position = _safe_name(state_before.get("position_id"))
        return self.root / date_text / strategy / f"{code}__{position}.jsonl"


class PostExitObservationAuditRecorder:
    """Preserve production observations after exit without evaluating or ordering."""

    def __init__(
        self,
        root: Path,
        adapter_paths: Path | Iterable[Path],
        *,
        enabled: bool = True,
        strict: bool = False,
    ) -> None:
        self.root = Path(root)
        raw_paths = (
            [adapter_paths]
            if isinstance(adapter_paths, (str, Path))
            else list(adapter_paths)
        )
        self.adapter_paths = sorted(
            {Path(path).resolve() for path in raw_paths}, key=str
        )
        self.enabled = bool(enabled)
        self.strict = bool(strict)
        self.adapter_hash = (
            sha256_files(self.adapter_paths)
            if self.enabled and all(path.exists() for path in self.adapter_paths)
            else ""
        )
        self._tails: dict[Path, tuple[int, str]] = {}
        self.last_error = ""

    def _target(self, position: Mapping[str, Any], observation: Any) -> Path:
        date_text = observation.observed_at.strftime("%Y%m%d")
        strategy = _safe_name(position.get("strategy_id"))
        code = _safe_name(position.get("code"))
        position_id = _safe_name(position.get("position_id"))
        return self.root / date_text / strategy / f"{code}__{position_id}.jsonl"

    def _tail(self, path: Path) -> tuple[int, str]:
        cached = self._tails.get(path)
        if cached is not None:
            return cached
        sequence = 0
        previous = ZERO_HASH
        if path.exists():
            rows = load_verified_post_exit_rows(path)
            sequence = int(rows[-1]["sequence"])
            previous = str(rows[-1]["row_hash"])
        self._tails[path] = (sequence, previous)
        return sequence, previous

    def record(
        self,
        *,
        position: Mapping[str, Any],
        observation: Any,
        exit_at: datetime,
    ) -> Optional[Path]:
        if not self.enabled:
            return None
        try:
            target = self._target(position, observation)
            target.parent.mkdir(parents=True, exist_ok=True)
            sequence, previous = self._tail(target)
            payload = {
                "schema": POST_EXIT_OBSERVATION_SCHEMA,
                "sequence": sequence + 1,
                "captured_at": datetime.now().astimezone().isoformat(),
                "adapter_paths": [str(path) for path in self.adapter_paths],
                "adapter_sha256": self.adapter_hash,
                "strategy_id": str(position.get("strategy_id") or ""),
                "code": str(position.get("code") or "").zfill(6),
                "position_id": str(position.get("position_id") or ""),
                "entry_at": str(position.get("entry_at") or ""),
                "entry_price": str(position.get("entry_price") or ""),
                "exit_at": exit_at.isoformat(),
                "observation": json_value(observation),
                "prev_hash": previous,
            }
            payload["row_hash"] = row_hash(payload)
            encoded = canonical_bytes(payload) + b"\n"
            descriptor = os.open(
                str(target),
                os.O_APPEND | os.O_CREAT | os.O_WRONLY | getattr(os, "O_BINARY", 0),
            )
            try:
                os.write(descriptor, encoded)
            finally:
                os.close(descriptor)
            self._tails[target] = (sequence + 1, payload["row_hash"])
            self.last_error = ""
            return target
        except Exception as exc:
            self.last_error = str(exc)
            if self.strict:
                raise
            return None


def load_verified_rows(path: Path) -> list[dict[str, Any]]:
    source = Path(path)
    if not source.exists():
        raise AuditError(f"audit file missing: {source}")
    rows: list[dict[str, Any]] = []
    previous = ZERO_HASH
    with source.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except ValueError as exc:
                raise AuditError(f"invalid JSON at line {line_number}: {exc}")
            if payload.get("schema") != AUDIT_SCHEMA:
                raise AuditError(f"schema mismatch at line {line_number}")
            if int(payload.get("sequence") or 0) != len(rows) + 1:
                raise AuditError(f"sequence mismatch at line {line_number}")
            if payload.get("prev_hash") != previous:
                raise AuditError(f"previous hash mismatch at line {line_number}")
            stored_hash = str(payload.get("row_hash") or "")
            unhashed = dict(payload)
            unhashed.pop("row_hash", None)
            if stored_hash != row_hash(unhashed):
                raise AuditError(f"row hash mismatch at line {line_number}")
            previous = stored_hash
            rows.append(payload)
    if not rows:
        raise AuditError("audit stream is empty")
    if not rows[0].get("initial_state_complete"):
        raise AuditError("capture started mid-position")
    engine_hashes = {str(row.get("engine_sha256") or "") for row in rows}
    if len(engine_hashes) != 1 or "" in engine_hashes:
        raise AuditError("capture engine hash changed inside stream")
    return rows


def load_verified_post_exit_rows(path: Path) -> list[dict[str, Any]]:
    source = Path(path)
    if not source.exists():
        raise AuditError(f"post-exit audit file missing: {source}")
    rows: list[dict[str, Any]] = []
    previous = ZERO_HASH
    identity: Optional[tuple[str, str, str]] = None
    adapter_hash = ""
    prior_observed_at: Optional[datetime] = None
    with source.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except ValueError as exc:
                raise AuditError(
                    f"invalid post-exit JSON at line {line_number}: {exc}"
                )
            if payload.get("schema") != POST_EXIT_OBSERVATION_SCHEMA:
                raise AuditError(f"post-exit schema mismatch at line {line_number}")
            if int(payload.get("sequence") or 0) != len(rows) + 1:
                raise AuditError(f"post-exit sequence mismatch at line {line_number}")
            if payload.get("prev_hash") != previous:
                raise AuditError(f"post-exit previous hash mismatch at line {line_number}")
            stored_hash = str(payload.get("row_hash") or "")
            unhashed = dict(payload)
            unhashed.pop("row_hash", None)
            if stored_hash != row_hash(unhashed):
                raise AuditError(f"post-exit row hash mismatch at line {line_number}")
            current_identity = (
                str(payload.get("strategy_id") or ""),
                str(payload.get("code") or ""),
                str(payload.get("position_id") or ""),
            )
            if identity is None:
                identity = current_identity
                adapter_hash = str(payload.get("adapter_sha256") or "")
            elif current_identity != identity:
                raise AuditError("post-exit position identity changed inside stream")
            if str(payload.get("adapter_sha256") or "") != adapter_hash:
                raise AuditError("post-exit adapter hash changed inside stream")
            observed_at = datetime.fromisoformat(
                str((payload.get("observation") or {}).get("observed_at") or "")
            )
            if prior_observed_at is not None and observed_at <= prior_observed_at:
                raise AuditError("post-exit timestamps are not strictly increasing")
            prior_observed_at = observed_at
            previous = stored_hash
            rows.append(payload)
    if not rows:
        raise AuditError("post-exit audit stream is empty")
    if not adapter_hash:
        raise AuditError("post-exit adapter hash missing")
    return rows
