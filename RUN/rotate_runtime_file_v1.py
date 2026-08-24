# -*- coding: utf-8 -*-
"""Rotate oversized append-only runtime files without deleting evidence."""
from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
from typing import Iterable


def rotate(
    paths: Iterable[Path], max_bytes: int, stamp: str | None = None,
    archive_root: Path | None = None,
) -> list[Path]:
    moved: list[Path] = []
    stamp = stamp or datetime.now().strftime("%Y%m%d_%H%M%S")
    for path in paths:
        path = Path(path)
        try:
            if path.stat().st_size < max_bytes:
                continue
        except OSError:
            continue
        archive = (Path(archive_root) if archive_root else path.parent / "archive") / stamp[:8]
        archive.mkdir(parents=True, exist_ok=True)
        target = archive / f"{path.stem}_{stamp}{path.suffix}"
        index = 1
        while target.exists():
            target = archive / f"{path.stem}_{stamp}_{index}{path.suffix}"
            index += 1
        path.replace(target)
        moved.append(target)
    return moved


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", action="append", type=Path, required=True)
    parser.add_argument("--max-mb", type=int, default=256)
    parser.add_argument("--archive-root", type=Path)
    args = parser.parse_args()
    for target in rotate(
        args.path, args.max_mb * 1024 * 1024,
        archive_root=args.archive_root,
    ):
        print(f"ROTATED {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
