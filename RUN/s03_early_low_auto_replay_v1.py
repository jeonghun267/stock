# -*- coding: utf-8 -*-
"""Run the S03 EARLY_LOW production replay and atomically write its report."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

RUN_DIR = Path(__file__).resolve().parent
if str(RUN_DIR) not in sys.path:
    sys.path.insert(0, str(RUN_DIR))

from strategy_03_signal_contract_v1 import EarlyLowAuditChain, early_low_audit_dir
from s03_early_low_release_v1 import CONDITION_ID, DURATION, QUANTITY

ROOT = Path(r"C:\stock_bot")
RUN = RUN_DIR
REPORT_ROOT = ROOT / "reports" / "verified_replay"
REPLAY = RUN / "s03_early_low_prod_replay_v1.py"
CAPTURE_FILES = {
    "골짜기_급반등.py": RUN / "골짜기_급반등.py",
    "strategy_03_signal_contract_v1.py": RUN / "strategy_03_signal_contract_v1.py",
    "strategy_03_rotation_engine_v1.py": RUN / "strategy_03_rotation_engine_v1.py",
    "strategy_03_flow_turn_fast_v1.py": RUN / "strategy_03_flow_turn_fast_v1.py",
    "s03_early_low_release_v1.py": RUN / "s03_early_low_release_v1.py",
}
REPLAY_FILES = {
    **CAPTURE_FILES,
    "s03_early_low_prod_replay_v1.py": REPLAY,
    "s03_early_low_auto_replay_v1.py": Path(__file__),
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _atomic_json(path: Path, data: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _audit_evidence(day: str, audit_dir: Path) -> tuple[
    dict[str, str], dict[str, list[str]], list[str], list[str]
]:
    source_hashes: dict[str, str] = {}
    captured: dict[str, set[str]] = {}
    codes: set[str] = set()
    errors: list[str] = []
    for stream in ("signal", "engine"):
        path = audit_dir / f"s03_early_low_{stream}_{day}.jsonl"
        if not path.is_file():
            errors.append(f"MISSING_AUDIT:{path}")
            continue
        source_hashes[str(path.resolve())] = _sha256(path)
        ok, reason, records = EarlyLowAuditChain.verify_file(path)
        if not ok:
            errors.append(f"CHAIN_INVALID:{stream}:{reason}")
            continue
        for record in records:
            code = str(record.get("code") or "").zfill(6)
            if code != "000000":
                codes.add(code)
            raw_hashes = record.get("prod_sha")
            if not isinstance(raw_hashes, Mapping):
                errors.append(f"MISSING_PROD_SHA:{stream}:seq={record.get('seq')}")
                continue
            for name, value in raw_hashes.items():
                captured.setdefault(str(name), set()).add(str(value).lower())
    return (
        source_hashes,
        {name: sorted(values) for name, values in captured.items()},
        sorted(codes),
        errors,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default=datetime.now().strftime("%Y%m%d"))
    parser.add_argument("--audit-dir", default="")
    parser.add_argument("--report", default="")
    args = parser.parse_args()
    day = str(args.date)
    audit_dir = Path(args.audit_dir) if args.audit_dir else early_low_audit_dir()
    report_path = (
        Path(args.report) if args.report
        else REPORT_ROOT / day / f"s03_early_low_{day}.json"
    )

    command = [
        sys.executable, "-B", "-X", "utf8", str(REPLAY),
        "--date", day, "--audit-dir", str(audit_dir),
    ]
    completed = subprocess.run(
        command, cwd=ROOT, capture_output=True, text=True, timeout=180,
    )
    stdout = completed.stdout
    stderr = completed.stderr
    source_hashes, capture_hashes, codes, evidence_errors = _audit_evidence(
        day, audit_dir,
    )
    current_capture = {
        name: _sha256(path) for name, path in CAPTURE_FILES.items()
    }
    for name, values in capture_hashes.items():
        current = current_capture.get(name)
        if current is None:
            evidence_errors.append(f"UNKNOWN_CAPTURE_FILE:{name}")
        elif values != [current]:
            evidence_errors.append(
                f"CAPTURE_HASH_MISMATCH:{name}:captured={values}:current={current}"
            )
    for name in CAPTURE_FILES:
        if name not in capture_hashes:
            evidence_errors.append(f"CAPTURE_HASH_MISSING:{name}")

    match = re.search(r"would_pass_if_live=(\d+)", stdout)
    candidate_passes = int(match.group(1)) if match else 0
    replay_pass = (
        completed.returncode == 0
        and "[PROD_REPLAY] PASS" in stdout
        and candidate_passes > 0
        and not evidence_errors
    )
    report = {
        "schema": "s03_early_low_verified_replay_v1",
        "provenance": "[PROD_REPLAY]" if replay_pass else "[UNVERIFIED]",
        "status": "PASS" if replay_pass else "UNVERIFIED",
        "performance_scope": "DECISION_ONLY",
        "strategy": "S03",
        "condition_id": CONDITION_ID,
        "quantity": QUANTITY,
        "duration": DURATION,
        "trade_date": day,
        "codes": codes,
        "source_audit_hash": source_hashes,
        "capture_engine_hash": capture_hashes,
        "replay_engine_hash": {
            name: _sha256(path) for name, path in REPLAY_FILES.items()
        },
        "code_changed": "NOT_CHANGED" if not evidence_errors else "CHANGED",
        "exact_command": subprocess.list2cmdline(command),
        "candidate_pass_count": candidate_passes,
        "replay_returncode": completed.returncode,
        "replay_stdout": stdout,
        "replay_stderr": stderr,
        "evidence_errors": evidence_errors,
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    _atomic_json(report_path, report)
    report_sha = _sha256(report_path)
    label = "[PROD_REPLAY]" if replay_pass else "[UNVERIFIED]"
    print(
        f"{label} report={report_path} sha256={report_sha} "
        f"status={report['status']}",
        flush=True,
    )
    return 0 if replay_pass else 2


if __name__ == "__main__":
    raise SystemExit(main())
