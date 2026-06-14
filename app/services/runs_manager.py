"""
Runs Manager
=============
Handles auto-cleanup of the runs/ folder.
Keeps only the last MAX_RUNS run folders (by creation time).
The audit.db and auth.db files are preserved.
"""

from __future__ import annotations

import shutil
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]
RUNS_DIR = BASE_DIR / "runs"
MAX_RUNS = 50
PROTECTED_FILES = {"audit.db", "auth.db"}


def cleanup_old_runs(max_runs: int = MAX_RUNS) -> dict:
    """
    Delete oldest run folders if total exceeds max_runs.
    Returns info about what was cleaned up.
    """
    RUNS_DIR.mkdir(parents=True, exist_ok=True)

    run_folders = sorted(
        [d for d in RUNS_DIR.iterdir() if d.is_dir()],
        key=lambda d: d.stat().st_mtime,
    )

    total = len(run_folders)
    deleted = []

    if total > max_runs:
        to_delete = run_folders[:total - max_runs]
        for folder in to_delete:
            shutil.rmtree(folder)
            deleted.append(folder.name)

    return {
        "total_before": total,
        "deleted_count": len(deleted),
        "deleted_runs": deleted,
        "remaining": total - len(deleted),
    }


def get_runs_disk_usage() -> dict:
    """Return approximate disk usage of the runs folder."""
    RUNS_DIR.mkdir(parents=True, exist_ok=True)

    total_bytes = 0
    run_count = 0

    for item in RUNS_DIR.iterdir():
        if item.is_dir():
            run_count += 1
            for f in item.rglob("*"):
                if f.is_file():
                    total_bytes += f.stat().st_size
        elif item.is_file() and item.name not in PROTECTED_FILES:
            total_bytes += item.stat().st_size

    return {
        "run_count": run_count,
        "total_mb": round(total_bytes / (1024 * 1024), 2),
        "max_runs": MAX_RUNS,
        "at_limit": run_count >= MAX_RUNS,
    }
