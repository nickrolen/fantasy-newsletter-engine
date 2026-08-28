"""Contract tests for the season-reset script.

The reset runs once a year, which is exactly why it drifts: a file gets added
to the project mid-season, nobody remembers to teach the reset about it, and
the following season silently starts with last season's state in it. That is
what happened to DRAFT_PICKS_CURRENT.json and LAST_WEEK_RECAP.md.

These tests pin two things:
  1. every per-season file the engine reads is either archived+reset, or is
     explicitly listed as intentionally untouched
  2. each reset writer emits a schema its readers actually tolerate
"""
import importlib.util
import json
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent


def _load_script():
    """Load scripts/start_new_season.py directly (scripts/ is not a package)."""
    spec = importlib.util.spec_from_file_location(
        "start_new_season", PROJECT_ROOT / "scripts" / "start_new_season.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def sns(tmp_path, monkeypatch):
    """The script pointed at a throwaway project root, never the real one."""
    mod = _load_script()
    monkeypatch.setattr(mod, "PROJECT_ROOT", tmp_path)
    (tmp_path / "config").mkdir()
    (tmp_path / "data").mkdir()
    return mod


# ---------------------------------------------------------------------------
# Coverage: per-season config files must not survive the reset
# ---------------------------------------------------------------------------

# Files under config/ that are per-season state and MUST be reset each year.
PER_SEASON_CONFIG = {
    "config/RECENT_CONTENT.json",
    "config/POTW_HISTORY.json",
    "config/INJURY_OVERRIDES.json",
    "config/ROSTERS.json",
    "config/TRADES.json",
    "config/RECORDS.json",
    "config/DRAFT_PICKS_CURRENT.json",
    "config/LAST_WEEK_RECAP.md",
}

# Files under config/ that deliberately carry across seasons.
CROSS_SEASON_CONFIG = {
    "config/league_config.json",        # league identity; edited by hand
    "config/league_config.json.example",
    "config/DRAFT_PICK_VALUES.json",    # rebuilt from history, not season state
    "config/ROOKIE_SEASONS.json",       # append-only reference data
    "config/SCHEDULE.json",             # replaced wholesale for the new season
    "config/.file_baselines.json",      # machine-specific integrity baseline
}


SCRIPT_SRC = (PROJECT_ROOT / "scripts" / "start_new_season.py").read_text(
    encoding="utf-8"
)


def test_every_per_season_config_file_is_archived():
    """A new per-season config file must be added to the archive list.

    get_archive_files() only returns paths that exist on disk, so this asserts
    against the script's own source rather than the filesystem.
    """
    missing = sorted(e for e in PER_SEASON_CONFIG if f'"{e}"' not in SCRIPT_SRC)
    assert missing == [], (
        "per-season config files not archived by start_new_season.py: "
        f"{missing}. Add them to get_archive_files() and give them a reset writer."
    )


def test_config_dir_has_no_unclassified_files():
    """Every real config/ file is knowingly per-season or knowingly not.

    Forces a decision when someone adds a file to config/ mid-season.
    """
    live = {
        f"config/{p.name}"
        for p in (PROJECT_ROOT / "config").iterdir()
        if p.is_file()
    }
    unclassified = sorted(live - PER_SEASON_CONFIG - CROSS_SEASON_CONFIG)
    assert unclassified == [], (
        f"config/ files not classified in this test: {unclassified}. "
        "Decide whether each is per-season (archive + reset it) or cross-season, "
        "then add it to the matching set here."
    )


# ---------------------------------------------------------------------------
# Reset writers emit schemas the readers tolerate
# ---------------------------------------------------------------------------

def test_draft_picks_reset_is_readable_and_empty(sns, tmp_path):
    sns.reset_draft_picks_current(execute=True)
    data = json.loads((tmp_path / "config" / "DRAFT_PICKS_CURRENT.json").read_text())
    # report_builder and player_card_builder both do .get("picks", [])
    assert data.get("picks") == []
    assert data.get("season") == ""
    assert data.get("league_key") == ""


def test_last_week_recap_reset_carries_no_stale_narrative(sns, tmp_path):
    sns.reset_last_week_recap(execute=True)
    text = (tmp_path / "config" / "LAST_WEEK_RECAP.md").read_text(encoding="utf-8")
    assert text.startswith("# Last Week Recap")
    # No manager names, scores, or week numbers left over from last season.
    for manager in ("Nick", "Hayden", "Benton", "Garrett"):
        assert manager not in text


def test_applied_weeks_ledger_reset_is_empty(sns, tmp_path):
    ledger = tmp_path / "config" / ".leaguehistory_applied_weeks.json"
    ledger.write_text(json.dumps({"2025-26": {"applied_weeks": [1, 2, 3]}}))
    sns.reset_applied_weeks_ledger(execute=True)
    assert json.loads(ledger.read_text()) == {}


def test_applied_weeks_ledger_reset_skips_when_absent(sns, tmp_path):
    sns.reset_applied_weeks_ledger(execute=True)
    assert not (tmp_path / "config" / ".leaguehistory_applied_weeks.json").exists()


# ---------------------------------------------------------------------------
# Dry run must never write
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "writer,filename",
    [
        ("reset_draft_picks_current", "DRAFT_PICKS_CURRENT.json"),
        ("reset_last_week_recap", "LAST_WEEK_RECAP.md"),
    ],
)
def test_dry_run_writes_nothing(sns, tmp_path, writer, filename):
    target = tmp_path / "config" / filename
    target.write_text("ORIGINAL", encoding="utf-8")
    getattr(sns, writer)(execute=False)
    assert target.read_text(encoding="utf-8") == "ORIGINAL"


# ---------------------------------------------------------------------------
# Protected paths stay protected
# ---------------------------------------------------------------------------

def test_historical_record_is_protected(sns):
    for p in (
        "data/historical/all_drafts.json",
        "data/historical/HISTORICAL_PLAYERLOG.json",
        "data/historical",
    ):
        assert sns.is_protected(p), f"{p} must never be touched by the reset"


def test_league_config_and_leaguehistory_are_protected(sns):
    assert sns.is_protected("config/league_config.json")
    assert sns.is_protected("data/LEAGUEHISTORY.xlsx")


def test_nba_schedule_is_never_reset(sns):
    assert sns.is_nba_schedule("data/nba_schedule_2026-27.json")
    assert not sns.is_nba_schedule("data/PLAYERLOG.xlsx")
