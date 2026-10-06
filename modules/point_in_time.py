"""
point_in_time.py -- freeze the inputs behind each published set of lines.

Why this exists
---------------
The retro-simulation cannot check a single published betting line from any
season before 2026-27, because nobody saved what the engine was looking at
when it produced them. Yahoo's projectedFPPG and projected games, the hand-kept
INJURY_OVERRIDES.json and the live injury statuses are all overwritten in
place every week. Once overwritten they are gone: none of them can be rebuilt
from the logs afterwards.

This module copies them, once per report week, at the moment Step 6 uses
them. It is called from generate_stats_report.py, not run by hand, so it
advances every week the newsletter does. verify_project_integrity warns when a
report exists without a capture.

What a capture is
-----------------
config/snapshots/point_in_time/report_weekNN/ holds the inputs to
output/stats_report_weekNN.json. That report is built after week NN has been
played, and its looking_ahead block -- the betting lines -- covers week NN+1.
So report_week03 holds what the engine knew when it priced week 4.

A later normal run of the same week replaces the capture: the last run before
publishing is the one that was published. --repro, --dry-run and --fast never
write one. --fast skips the live injury fetch and the simulators, so its
inputs are not the inputs to any line anyone read.

The whole snapshots/ directory is per-season. start_new_season archives it
into archive/<season>/config/snapshots/ and clears it.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Optional

SNAPSHOT_SUBDIR = Path("config") / "snapshots" / "point_in_time"
MANIFEST_NAME = "manifest.json"
INJURY_STATUSES_NAME = "INJURY_STATUSES.json"

# Inputs copied verbatim. Relative to the project root. The NBA schedule is
# added at call time because its filename comes from league_config.
CAPTURED_FILES = [
    "data/PLAYERLIST.xlsx",
    "config/INJURY_OVERRIDES.json",
    "config/ROSTERS.json",
    "config/SCHEDULE.json",
]


def capture_dir(base_path: Path, week: int) -> Path:
    return Path(base_path) / SNAPSHOT_SUBDIR / f"report_week{int(week):02d}"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def _git_commit(base_path: Path) -> Optional[str]:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(base_path), capture_output=True, text=True, timeout=5,
        )
        if out.returncode != 0:
            return None
        return out.stdout.strip() or None
    except Exception:
        return None


def _overrides_last_updated(path: Path) -> Optional[str]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f).get("last_updated") or None
    except Exception:
        return None


def capture_week_inputs(
    base_path: Path,
    week: int,
    season: str,
    injury_statuses: Optional[dict],
    injury_fetch_attempted: bool,
    nba_schedule_file: Optional[str] = None,
    total_weeks: Optional[int] = None,
    run_info: Optional[dict] = None,
    now: Optional[datetime] = None,
) -> Path:
    """Copy this week's engine inputs into report_weekNN/ and write a manifest.

    A missing input is recorded as missing in the manifest rather than
    skipped silently: "there was no ROSTERS.json" is itself the point-in-time
    fact. Returns the capture directory.
    """
    base_path = Path(base_path)
    now = now or datetime.now()
    dest = capture_dir(base_path, week)

    previous_count = 0
    old_manifest = dest / MANIFEST_NAME
    if old_manifest.is_file():
        try:
            with open(old_manifest, "r", encoding="utf-8") as f:
                previous_count = int(json.load(f).get("capture_count", 0))
        except Exception:
            previous_count = 0
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)

    sources = list(CAPTURED_FILES)
    if nba_schedule_file:
        sources.append(str(nba_schedule_file).replace("\\", "/"))

    files = {}
    for rel in sources:
        src = base_path / rel
        if not src.is_file():
            files[rel] = {"present": False}
            continue
        shutil.copy2(src, dest / Path(rel).name)
        files[rel] = {
            "present": True,
            "stored_as": Path(rel).name,
            "sha256": _sha256(src),
            "bytes": src.stat().st_size,
            "modified": datetime.fromtimestamp(src.stat().st_mtime).isoformat(timespec="seconds"),
        }

    statuses = dict(injury_statuses or {})
    with open(dest / INJURY_STATUSES_NAME, "w", encoding="utf-8") as f:
        json.dump(statuses, f, indent=2, sort_keys=True)

    lines_cover = week + 1
    if total_weeks is not None and lines_cover > total_weeks:
        lines_cover = None

    manifest = {
        "season": season,
        "report_week": int(week),
        "lines_cover_week": lines_cover,
        "captured_at": now.isoformat(timespec="seconds"),
        "capture_count": previous_count + 1,
        "git_commit": _git_commit(base_path),
        "injury_overrides_last_updated": _overrides_last_updated(
            base_path / "config" / "INJURY_OVERRIDES.json"),
        "injury_statuses": {
            "fetch_attempted": bool(injury_fetch_attempted),
            # An attempted fetch that returned nothing is NOT "everyone healthy".
            "available": bool(statuses),
            "count": len(statuses),
            "non_healthy": sum(1 for v in statuses.values() if v != "HEALTHY"),
        },
        "files": files,
        "run": dict(run_info or {}),
    }
    with open(dest / MANIFEST_NAME, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    return dest


def load_manifest(base_path: Path, week: int) -> Optional[dict]:
    path = capture_dir(base_path, week) / MANIFEST_NAME
    if not path.is_file():
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def report_weeks(base_path: Path) -> list:
    """Weeks with a generated stats report in output/."""
    weeks = []
    for p in (Path(base_path) / "output").glob("stats_report_week*.json"):
        tail = p.stem[len("stats_report_week"):]
        if tail.isdigit():
            weeks.append(int(tail))
    return sorted(weeks)


def missing_captures(base_path: Path) -> list:
    """Report weeks whose inputs were never captured.

    Each one is a week of point-in-time record that cannot be recovered.
    """
    return [w for w in report_weeks(base_path)
            if load_manifest(base_path, w) is None]
