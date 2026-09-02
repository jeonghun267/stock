# -*- coding: utf-8 -*-
"""Fail closed when a live strategy file differs from the owner-approved hash."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(r"C:\stock_bot")
MANIFEST = ROOT / "config" / "live_approved_hashes_v1.json"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_live_hashes(
    strategy: str,
    *,
    root: Path = ROOT,
    manifest_path: Path = MANIFEST,
) -> tuple[bool, list[str]]:
    strategy = str(strategy or "").strip().upper()
    errors: list[str] = []
    try:
        manifest: dict[str, Any] = json.loads(
            manifest_path.read_text(encoding="utf-8-sig")
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return False, [f"MANIFEST_UNAVAILABLE:{type(exc).__name__}"]

    if manifest.get("schema") != "live_approved_hashes_v1":
        return False, ["MANIFEST_SCHEMA_INVALID"]
    common_records = manifest.get("common") or []
    strategy_records = (manifest.get("strategies") or {}).get(strategy)
    if not isinstance(common_records, list):
        return False, ["MANIFEST_COMMON_INVALID"]
    if not isinstance(strategy_records, list) or not strategy_records:
        return False, [f"STRATEGY_NOT_APPROVED:{strategy}"]
    records = [*common_records, *strategy_records]

    for record in records:
        relative = str((record or {}).get("path") or "").strip()
        expected = str((record or {}).get("sha256") or "").strip().lower()
        if not relative or len(expected) != 64:
            errors.append(f"MANIFEST_RECORD_INVALID:{relative or '?'}")
            continue
        candidate = (root / relative).resolve()
        try:
            candidate.relative_to(root.resolve())
        except ValueError:
            errors.append(f"PATH_OUTSIDE_ROOT:{relative}")
            continue
        if not candidate.is_file():
            errors.append(f"FILE_MISSING:{relative}")
            continue
        actual = _sha256(candidate)
        if actual.lower() != expected:
            errors.append(f"HASH_MISMATCH:{relative}")
    return not errors, errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--strategy", choices=("S01", "S02", "S03", "S06"), required=True)
    args = parser.parse_args()
    passed, errors = verify_live_hashes(args.strategy)
    if passed:
        print(f"LIVE_OWNER_APPROVAL_HASH_PASS strategy={args.strategy}", flush=True)
        return 0
    print(
        f"LIVE_OWNER_APPROVAL_HASH_FAIL strategy={args.strategy} "
        + " | ".join(errors),
        flush=True,
    )
    return 3


if __name__ == "__main__":
    raise SystemExit(main())
