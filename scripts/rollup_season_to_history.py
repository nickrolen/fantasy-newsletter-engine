#!/usr/bin/env python3
"""
rollup_season_to_history.py -- Append a finished season's per-game player log
to the permanent historical record.

WHY THIS EXISTS
---------------
The project deliberately keeps the current season OUT of data/historical/.
Working files (PLAYERLOG.xlsx, LINEUPS.xlsx) accumulate all season; between
seasons the finished season is rolled into history and the working files are
reset.

Most of that roll-in is automated: pull_historical_data.py re-fetches
standings, matchups, drafts and trades from Yahoo. But HISTORICAL_PLAYERLOG
.json -- 76k rows of per-game, per-slot player detail built up daily by
update_fantasy_logs.py -- cannot be re-fetched. Yahoo does not serve
day-by-day historical rosters for a closed league. Every script that touches
that file only READS it.

So this was the one step with no tooling, and it is also the only
irreversible one: start_new_season.py Phase 2 truncates PLAYERLOG.xlsx to a
header row. Miss this step and the season's per-game detail survives only as
an archived spreadsheet.

It also rolls the season's DRAFT into data/historical/all_drafts.json.
config/DRAFT_PICKS_CURRENT.json already carries exactly the schema
all_drafts.json uses -- season, pick_number, round, manager, player_key,
player_name, is_keeper -- so this needs no Yahoo call. That matters when the
Fantasy API is unavailable: pull_historical_data.py is the usual route and it
is blocked, but the draft data is sitting on disk. Phase 2 of the reset
empties DRAFT_PICKS_CURRENT.json, so this has to happen first either way.

WHAT IT DOES
------------
PLAYERLOG.xlsx does not have the historical schema. Four fields have to be
supplied, and this script derives all four rather than asking a human to:

  season_key   "2025-2026" -> "2025-26"
  slot         joined from LINEUPS.xlsx on (date, manager, player_name)
  had_game     True when nba_opponent is set
               (verified: 0 disagreements across all 76,098 historical rows)
  player_id    looked up by name from existing history
               (verified: no player has ever had two ids)

Three xlsx-only columns (source, notes, opponent_manager) are dropped -- they
are weekly-workflow bookkeeping and are not part of the historical schema.

It also canonicalizes player names against the existing record. A single row
spelled "Lebron James" instead of "LeBron James" would append as a separate
player: career totals split in two, records understated, and nothing would
ever flag it. Names that match an existing player after normalization
(case, accents, punctuation) are rewritten to the historical spelling and
reported. Ambiguous matches are left alone and reported instead.

SAFETY
------
Dry-run by default, same as start_new_season.py. Refuses to append a season
that is already present. Backs up before writing, then re-reads and verifies
the result. Run this BEFORE start_new_season.py.

USAGE
    py scripts/rollup_season_to_history.py                # preview (default)
    py scripts/rollup_season_to_history.py --skip-drafts  # player log only
    py scripts/rollup_season_to_history.py --execute      # do it
    py scripts/rollup_season_to_history.py --execute --force   # replace a
                                                          # season already in
                                                          # the record
    py scripts/rollup_season_to_history.py --season 2025-26    # override
    py scripts/rollup_season_to_history.py --tables-only --execute
                                        # repair a season whose player log
                                        # went in but whose matchups,
                                        # standings, team keys and trades
                                        # did not

EXIT CODES
    0 = success (or a clean dry run)
    1 = refused or failed; nothing was written
"""

import argparse
import json
import re
import shutil
import sys
import unicodedata
from collections import Counter
from pathlib import Path

import pandas as pd

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(PROJECT_ROOT))

from modules.data_loader import (CURRENT_SEASON, CURRENT_SEASON_LONG,  # noqa: E402
                                 is_regular_season_week, stage_weeks)
# Who won what is defined once, in modules/season_outcomes.py, because two
# scripts used to answer it differently and one of them was wrong.
from modules.season_outcomes import (  # noqa: E402
    build_matchups, build_standings, league_champion, playoff_champion,
)

PLAYERLOG_XLSX = PROJECT_ROOT / "data" / "PLAYERLOG.xlsx"
LINEUPS_XLSX = PROJECT_ROOT / "data" / "LINEUPS.xlsx"
HISTORY_JSON = PROJECT_ROOT / "data" / "historical" / "HISTORICAL_PLAYERLOG.json"
DRAFTS_JSON = PROJECT_ROOT / "data" / "historical" / "all_drafts.json"
DRAFT_PICKS_CURRENT = PROJECT_ROOT / "config" / "DRAFT_PICKS_CURRENT.json"

DRAFT_FIELDS = [
    "season", "pick_number", "round", "manager", "player_key",
    "player_name", "is_keeper",
]

# The historical schema, in order. Rows are written with exactly these keys.
HISTORY_FIELDS = [
    "season_year", "season_key", "week", "date", "manager", "fantasy_team",
    "player_name", "player_id", "positions", "slot", "fantasy_points",
    "started", "nba_team", "nba_opponent", "had_game", "is_injured",
]

JOIN_KEY = ["date", "manager", "player_name"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def header(title):
    print()
    print("=" * 62)
    print(f"  {title}")
    print("=" * 62)


def rel(path):
    """Display path relative to the project when possible, absolute otherwise.

    Purely cosmetic -- but it runs between the backup and the write, so it
    must never raise.
    """
    try:
        return str(Path(path).relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


def fail(msg):
    print(f"\nREFUSED: {msg}")
    print("Nothing was written.")
    return 1


def season_key_from_long(season_long):
    """'2025-2026' -> '2025-26'."""
    s = str(season_long).strip()
    if "-" not in s:
        return s
    start, end = s.split("-", 1)
    return f"{start}-{end[-2:]}"


def normalize_name(name):
    """Collapse case, accents and punctuation so spelling variants collide."""
    n = unicodedata.normalize("NFKD", str(name))
    n = n.encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z]", "", n.lower())


def clean_str(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ""
    return str(v).strip()


def to_date_str(v):
    ts = pd.to_datetime(v, errors="coerce")
    return "" if pd.isna(ts) else ts.strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------

def load_slot_lookup():
    """Map (date, manager, player_name) -> roster slot, from LINEUPS.xlsx."""
    lineups = pd.read_excel(LINEUPS_XLSX)
    missing = [c for c in JOIN_KEY + ["slot"] if c not in lineups.columns]
    if missing:
        raise ValueError(f"LINEUPS.xlsx is missing columns: {missing}")
    lineups = lineups[JOIN_KEY + ["slot"]].copy()
    lineups["date"] = lineups["date"].map(to_date_str)
    lineups["manager"] = lineups["manager"].map(clean_str)
    lineups["player_name"] = lineups["player_name"].map(clean_str)
    lineups = lineups.dropna(subset=["slot"]).drop_duplicates(subset=JOIN_KEY)
    return {
        (r.date, r.manager, r.player_name): clean_str(r.slot)
        for r in lineups.itertuples(index=False)
    }


def load_player_ids(history):
    """Map player_name -> player_id using ids already in the record."""
    ids = {}
    for row in history:
        name = row.get("player_name")
        pid = row.get("player_id")
        if name and pid is not None and name not in ids:
            ids[name] = pid
    return ids


def load_canonical_names(history):
    """Map normalized name -> set of spellings used in the record."""
    by_norm = {}
    for row in history:
        name = row.get("player_name")
        if name:
            by_norm.setdefault(normalize_name(name), set()).add(name)
    return by_norm


def build_rows(season_key, history):
    """Transform PLAYERLOG.xlsx into historical-schema rows. Returns (rows, report)."""
    log = pd.read_excel(PLAYERLOG_XLSX)
    if log.empty:
        raise ValueError(
            "PLAYERLOG.xlsx has no data rows. If start_new_season.py has "
            "already run, recover the season's log from archive/<season>/data/."
        )

    slots = load_slot_lookup()
    known_ids = load_player_ids(history)
    canonical = load_canonical_names(history)

    rows = []
    report = {
        "no_slot_match": [],
        "new_players": set(),
        "is_injured_disagreements": [],
        "renamed": {},
        "ambiguous_names": {},
        "weeks": Counter(),
    }

    for r in log.to_dict("records"):
        date = to_date_str(r.get("date"))
        manager = clean_str(r.get("manager"))
        name = clean_str(r.get("player_name"))

        # Canonicalize against the record before anything keys off the name.
        if name and name not in canonical.get(normalize_name(name), set()):
            variants = canonical.get(normalize_name(name), set())
            if len(variants) == 1:
                official = next(iter(variants))
                report["renamed"].setdefault(name, official)
                name = official
            elif len(variants) > 1:
                report["ambiguous_names"][name] = sorted(variants)

        opponent = clean_str(r.get("nba_opponent"))

        try:
            fp = float(r.get("fantasy_points") or 0.0)
        except (TypeError, ValueError):
            fp = 0.0

        had_game = bool(opponent)
        derived_injured = had_game and fp == 0.0

        # PLAYERLOG carries its own is_injured; cross-check rather than trust.
        if "is_injured" in r and not pd.isna(r.get("is_injured")):
            if bool(r["is_injured"]) != derived_injured:
                report["is_injured_disagreements"].append(
                    f"{date} {manager} {name}: file={bool(r['is_injured'])} derived={derived_injured}"
                )

        slot = slots.get((date, manager, name))
        if slot is None:
            slot = ""
            report["no_slot_match"].append(f"{date} {manager} {name}")

        pid = known_ids.get(name)
        if pid is None:
            report["new_players"].add(name)

        try:
            week = int(r.get("week"))
        except (TypeError, ValueError):
            week = 0
        report["weeks"][week] += 1

        rows.append({
            "season_year": clean_str(r.get("season_year")) or CURRENT_SEASON_LONG,
            "season_key": season_key,
            "week": week,
            "date": date,
            "manager": manager,
            "fantasy_team": clean_str(r.get("fantasy_team")),
            "player_name": name,
            "player_id": pid,
            "positions": clean_str(r.get("positions")),
            "slot": slot,
            "fantasy_points": fp,
            "started": bool(r.get("started")),
            "nba_team": clean_str(r.get("nba_team")),
            "nba_opponent": opponent,
            "had_game": had_game,
            "is_injured": derived_injured,
        })

    return rows, report


def rollup_drafts(season_key, execute, force):
    """Append the season's draft picks to all_drafts.json.

    Returns (status, message). status is one of: "done", "skipped", "error".
    """
    if not DRAFT_PICKS_CURRENT.exists():
        return "skipped", f"{rel(DRAFT_PICKS_CURRENT)} not found"
    if not DRAFTS_JSON.exists():
        return "error", f"{rel(DRAFTS_JSON)} not found"

    with open(DRAFT_PICKS_CURRENT, "r", encoding="utf-8") as f:
        current = json.load(f)
    picks = current.get("picks", [])
    if not picks:
        return "skipped", "DRAFT_PICKS_CURRENT.json has no picks"

    with open(DRAFTS_JSON, "r", encoding="utf-8") as f:
        drafts = json.load(f)

    existing = sum(1 for d in drafts if d.get("season") == season_key)
    if existing and not force:
        return "skipped", (f"{season_key} already has {existing} picks in "
                           f"all_drafts.json (use --force to replace)")

    # Normalize to the historical schema, dropping anything extra.
    new_rows = []
    for p in picks:
        missing = [k for k in DRAFT_FIELDS if k not in p]
        if missing:
            return "error", f"pick {p.get('pick_number')} missing {missing}"
        new_rows.append({k: p[k] for k in DRAFT_FIELDS})

    keepers = sum(1 for r in new_rows if r["is_keeper"])
    msg = (f"{len(new_rows)} picks ({len(new_rows) - keepers} drafted, "
           f"{keepers} keepers)")

    if not execute:
        return "done", f"would append {msg}"

    base = [d for d in drafts if d.get("season") != season_key] if force else drafts
    shutil.copy2(DRAFTS_JSON, DRAFTS_JSON.with_suffix(".json.bak"))
    merged = base + new_rows
    with open(DRAFTS_JSON, "w", encoding="utf-8") as f:
        json.dump(merged, f, indent=2)

    with open(DRAFTS_JSON, "r", encoding="utf-8") as f:
        check = json.load(f)
    landed = sum(1 for d in check if d.get("season") == season_key)
    if landed != len(new_rows) or len(check) != len(merged):
        return "error", (f"verification failed: {landed} picks for {season_key}, "
                         f"{len(check)} total")
    return "done", f"appended {msg}; all_drafts.json now {len(check)} picks"


# ---------------------------------------------------------------------------
# Season tables -- matchups, standings, teams, trades
# ---------------------------------------------------------------------------
# These four files were being missed. rollup_drafts() and the player log
# rollup ran; nothing rolled the season's matchups, standings, team keys or
# trades, so all four sat a season behind while the other two moved on. That
# is invisible until something reads them -- the all-time h2h tables, the
# historical standings grid and the record book all build off all_matchups
# and all_standings.
#
# Sources are resolved live-first, archive-second, because the reset empties
# config/ and this may well be run after it.

MATCHUPS_JSON = PROJECT_ROOT / "data" / "historical" / "all_matchups.json"
STANDINGS_JSON = PROJECT_ROOT / "data" / "historical" / "all_standings.json"
TEAMS_JSON = PROJECT_ROOT / "data" / "historical" / "all_teams.json"
TRADES_HISTORY_JSON = PROJECT_ROOT / "data" / "historical" / "all_trades.json"
SUMMARY_JSON = PROJECT_ROOT / "data" / "historical" / "historical_summary.json"
ARCHIVE_DIR = PROJECT_ROOT / "archive"


def season_config_dir(season_key):
    """Where `season_key`'s config files live: config/ or archive/<season>/config/.

    After start_new_season.py has run, config/ describes the NEXT season and
    the finished one survives only in the archive. Checking which is which by
    content rather than by date avoids rolling up the wrong season entirely.
    """
    live = PROJECT_ROOT / "config"
    live_records = live / "RECORDS.json"
    if live_records.is_file():
        try:
            rec = json.loads(live_records.read_text(encoding="utf-8"))
            if rec.get("weekly_scores") and rec.get("season_records", {}).get(
                    "season", season_key) == season_key:
                return live
            # A live RECORDS.json with scores but no season stamp: trust it
            # only if the archive does not have this season.
            if rec.get("weekly_scores") and not (
                    ARCHIVE_DIR / season_key / "config" / "RECORDS.json").is_file():
                return live
        except (OSError, json.JSONDecodeError):
            pass
    archived = ARCHIVE_DIR / season_key / "config"
    return archived if (archived / "RECORDS.json").is_file() else live


def _load_season_sources(season_key):
    """(records, schedule, trades, league_config) for a season, or raises."""
    cfg_dir = season_config_dir(season_key)
    out = []
    for name, required in (("RECORDS.json", True), ("SCHEDULE.json", True),
                           ("TRADES.json", False), ("league_config.json", False)):
        path = cfg_dir / name
        if not path.is_file():
            if required:
                raise ValueError(f"{season_key}: {rel(path)} not found")
            out.append({})
            continue
        out.append(json.loads(path.read_text(encoding="utf-8")))
    return (*out, cfg_dir)


def build_teams(season_key, records):
    """{team_key: {manager, team_name}} from RECORDS.team_name_history."""
    hist = records.get("team_name_history", {})
    entry = hist.get(season_key)
    return entry if isinstance(entry, dict) and entry else {}


def build_trades(season_key, trades_cfg, league_config):
    """Rows in the all_trades.json schema, plus the picks this league trades.

    all_trades.json only ever held players. This league trades draft picks
    constantly and they decide draft order, so they are carried through in an
    additive `picks` field rather than dropped.
    """
    name_of = (league_config or {}).get("manager_to_team", {})
    out = []
    for t in trades_cfg.get("trades", []) or []:
        a, b = t.get("side_a") or {}, t.get("side_b") or {}
        ma, mb = a.get("manager"), b.get("manager")
        if not ma or not mb:
            continue
        ta, tb = name_of.get(ma, ma), name_of.get(mb, mb)
        players = []
        for src, dst, src_team, dst_team in ((a, b, ta, tb), (b, a, tb, ta)):
            for p in src.get("sent_players", []) or []:
                players.append({
                    "player_name": p,
                    "from_team": src_team, "to_team": dst_team,
                    "from_manager": src.get("manager"),
                    "to_manager": dst.get("manager"),
                })
        out.append({
            "season": season_key,
            "timestamp": None,
            "date": t.get("date"),
            "week": t.get("week"),
            "trader_team": ta, "tradee_team": tb,
            "trader_manager": ma, "tradee_manager": mb,
            "players": players,
            "picks": {
                ma: a.get("sent_picks", []) or [],
                mb: b.get("sent_picks", []) or [],
            },
        })
    return out


def _write_list(path, season_key, new_rows, force, label):
    """Replace/append a season in a list-shaped history file. Returns message."""
    existing_rows = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else []
    existing = sum(1 for r in existing_rows if r.get("season") == season_key)
    if existing and not force:
        return "skipped", f"{season_key} already has {existing} {label} (use --force)"
    base = [r for r in existing_rows if r.get("season") != season_key]
    merged = base + new_rows
    shutil.copy2(path, path.with_suffix(".json.bak")) if path.is_file() else None
    path.write_text(json.dumps(merged, indent=2), encoding="utf-8")

    check = json.loads(path.read_text(encoding="utf-8"))
    landed = sum(1 for r in check if r.get("season") == season_key)
    if landed != len(new_rows) or len(check) != len(merged):
        return "error", f"verification failed: {landed} landed, {len(check)} total"
    return "done", f"{len(new_rows)} {label}; {path.name} now {len(check)} rows"


def rollup_season_tables(season_key, execute, force):
    """Roll matchups, standings, team keys and trades into data/historical/.

    Returns a list of (name, status, message).
    """
    results = []
    try:
        records, schedule, trades_cfg, league_config, cfg_dir = \
            _load_season_sources(season_key)
    except ValueError as e:
        # Not an error: there is simply nothing to read for this season, here.
        # It IS worth saying loudly, because a season whose tables never got
        # rolled is invisible afterwards -- that is the bug this exists for.
        return [("sources", "skipped",
                 f"{e}. THE SEASON TABLES DID NOT ROLL. Re-run with "
                 f"--tables-only once config/ or archive/{season_key}/config/ "
                 "has that season.")]

    results.append(("sources", "done", f"read from {rel(cfg_dir)}"))

    rows = build_matchups(season_key, records, schedule)
    if not rows:
        return results + [("matchups", "error",
                           "RECORDS.json and SCHEDULE.json are both present "
                           "but produced no matchups -- they disagree about "
                           "this season")]

    standings = build_standings(season_key, rows)
    teams = build_teams(season_key, records)
    trades = build_trades(season_key, trades_cfg, league_config)

    if not execute:
        results.append(("matchups", "done", f"would write {len(rows)} rows"))
        champ = next((s["manager"] for s in standings
                      if s["regular_season_rank"] == 1), "?")
        bracket = next((s["manager"] for s in standings
                        if s.get("playoff_rank") == 1), None)
        results.append(("standings", "done",
                        f"would write {len(standings)} rows; League Champion "
                        f"{champ}" + (f", Playoff Champion {bracket}"
                                      if bracket else ", no bracket")))
        results.append(("teams", "done" if teams else "skipped",
                        f"would write {len(teams)} team keys" if teams
                        else "no team_name_history for this season"))
        results.append(("trades", "done", f"would write {len(trades)} trades"))
        return results

    results.append(("matchups", *_write_list(MATCHUPS_JSON, season_key, rows,
                                             force, "matchups")))
    results.append(("standings", *_write_list(STANDINGS_JSON, season_key,
                                              standings, force, "standings")))
    results.append(("trades", *_write_list(TRADES_HISTORY_JSON, season_key,
                                           trades, force, "trades")))

    if teams:
        all_teams = json.loads(TEAMS_JSON.read_text(encoding="utf-8")) \
            if TEAMS_JSON.is_file() else {}
        if season_key in all_teams and not force:
            results.append(("teams", "skipped",
                            f"{season_key} already in {TEAMS_JSON.name}"))
        else:
            if TEAMS_JSON.is_file():
                shutil.copy2(TEAMS_JSON, TEAMS_JSON.with_suffix(".json.bak"))
            all_teams[season_key] = teams
            TEAMS_JSON.write_text(json.dumps(all_teams, indent=2), encoding="utf-8")
            results.append(("teams", "done",
                            f"{len(teams)} team keys; {TEAMS_JSON.name} now "
                            f"{len(all_teams)} seasons"))
    else:
        results.append(("teams", "skipped", "no team_name_history for this season"))

    results.append(("summary", *refresh_summary()))
    return results


def repair_standings_fields(execute):
    """Add the explicit rank fields to seasons already in all_standings.json.

    Only ADDS fields. Before touching a season it recomputes rank, wins,
    losses and points_for from all_matchups.json and refuses unless every one
    of them already agrees with what is stored -- so a season whose stored
    numbers came from somewhere this cannot reproduce is left alone and said
    so, rather than quietly overwritten with a reconstruction.
    """
    if not (STANDINGS_JSON.is_file() and MATCHUPS_JSON.is_file()):
        return "skipped", "all_standings.json or all_matchups.json missing"

    stored = json.loads(STANDINGS_JSON.read_text(encoding="utf-8"))
    matchups = json.loads(MATCHUPS_JSON.read_text(encoding="utf-8"))
    by_season = {}
    for r in matchups:
        by_season.setdefault(r["season"], []).append(r)

    NEW = ("rank_basis", "reg_wins", "reg_losses", "regular_season_rank",
           "playoff_rank")
    # Integers must match exactly. points_for is a sum of ~23 weekly scores
    # that were each rounded to two places, so it drifts from the season
    # total Yahoo reported by a rounding unit or so -- six of the 32 stored
    # rows are off by exactly 0.1. That is arithmetic, not disagreement.
    EXACT = ("rank", "wins", "losses")
    TOLERANT = {"points_for": 0.5}

    patched, skipped, disagreed = 0, 0, []
    for row in stored:
        if all(k in row for k in NEW):
            skipped += 1
            continue
        rows = by_season.get(row["season"])
        if not rows:
            disagreed.append(f"{row['season']} {row['manager']}: no matchups on file")
            continue
        computed = {c["manager"]: c for c in build_standings(row["season"], rows)}
        want = computed.get(row["manager"])
        if not want:
            disagreed.append(f"{row['season']} {row['manager']}: not in recount")
            continue
        off = [f for f in EXACT if int(row.get(f, -1)) != int(want[f])]
        off += [f for f, tol in TOLERANT.items()
                if abs(float(row.get(f, 0)) - float(want[f])) > tol]
        if off:
            disagreed.append(
                f"{row['season']} {row['manager']}: stored and recomputed "
                f"disagree on {', '.join(off)}")
            continue
        for k in NEW:
            row.setdefault(k, want[k])
        patched += 1

    msg = f"{patched} rows would gain the explicit rank fields"
    if skipped:
        msg += f"; {skipped} already had them"
    if disagreed:
        msg += f"; {len(disagreed)} LEFT ALONE"
    if not execute:
        for d in disagreed:
            msg += f"\n                  - {d}"
        return ("done" if patched or skipped else "skipped"), msg
    if patched:
        shutil.copy2(STANDINGS_JSON, STANDINGS_JSON.with_suffix(".json.bak"))
        STANDINGS_JSON.write_text(json.dumps(stored, indent=2), encoding="utf-8")
    return "done", msg


def refresh_summary():
    """Rebuild historical_summary.json from the files it summarises.

    It is a derived file. Left alone it keeps reporting the season count and
    totals it had when it was last generated, which is how a stale roll-up
    stays invisible.
    """
    if not MATCHUPS_JSON.is_file():
        return "skipped", "no all_matchups.json"
    from datetime import datetime
    matchups = json.loads(MATCHUPS_JSON.read_text(encoding="utf-8"))
    trades = json.loads(TRADES_HISTORY_JSON.read_text(encoding="utf-8")) \
        if TRADES_HISTORY_JSON.is_file() else []
    drafts = json.loads(DRAFTS_JSON.read_text(encoding="utf-8")) \
        if DRAFTS_JSON.is_file() else []

    previous = json.loads(SUMMARY_JSON.read_text(encoding="utf-8")) \
        if SUMMARY_JSON.is_file() else {}

    decided = [m for m in matchups if m.get("winner")]
    blowout = max(decided, key=lambda m: m["margin"], default=None)
    closest = min(decided, key=lambda m: m["margin"], default=None)
    highest = None
    for m in matchups:
        for side in ("a", "b"):
            cand = {"season": m["season"], "week": m["week"],
                    "manager": m[f"manager_{side}"], "score": m[f"score_{side}"]}
            if highest is None or cand["score"] > highest["score"]:
                highest = cand

    seasons = sorted({m["season"] for m in matchups})
    summary = dict(previous)
    summary.update({
        "generated_at": datetime.now().isoformat(),
        "seasons_processed": seasons,
        "total_matchups": len(matchups),
        "total_trades": len(trades),
        "total_draft_picks": len(drafts),
        "all_time_biggest_blowout": blowout,
        "all_time_closest_game": closest,
        "all_time_highest_weekly_score": highest,
        # Derived, not carried over. The previous version of this file kept a
        # hand-written note saying "2017-18 through 2024-25" long after that
        # stopped being true -- the same staleness the rest of this rollup
        # exists to prevent, in prose.
        "notes": (f"Historical data, {seasons[0]} through {seasons[-1]}. "
                  "Standings computed from matchups. The season in progress "
                  "lives in config/RECORDS.json until it is rolled in here."
                  if seasons else "No seasons on file."),
    })
    if SUMMARY_JSON.is_file():
        shutil.copy2(SUMMARY_JSON, SUMMARY_JSON.with_suffix(".json.bak"))
    SUMMARY_JSON.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return "done", (f"{len(summary['seasons_processed'])} seasons, "
                    f"{len(matchups)} matchups, {len(drafts)} picks")


def print_report(season_key, rows, report, history_len):
    header(f"ROLLUP PREVIEW -- {season_key}")
    weeks = sorted(w for w in report["weeks"] if w)
    print(f"\n  Rows to append:     {len(rows):,}")
    print(f"  Weeks covered:      {min(weeks)}-{max(weeks)} ({len(weeks)} weeks)")
    print(f"  Distinct players:   {len({r['player_name'] for r in rows})}")
    print(f"  Managers:           {', '.join(sorted({r['manager'] for r in rows}))}")
    print(f"\n  History before:     {history_len:,} rows")
    print(f"  History after:      {history_len + len(rows):,} rows")

    slot_counts = Counter(r["slot"] or "(none)" for r in rows)
    print(f"\n  Slots: {dict(slot_counts.most_common(8))}")
    print(f"  Games lost to injury (had_game + 0.0 FP): "
          f"{sum(1 for r in rows if r['is_injured']):,}")

    if report["no_slot_match"]:
        print(f"\n  WARNING: {len(report['no_slot_match'])} row(s) had no LINEUPS "
              f"match; slot left empty:")
        for line in report["no_slot_match"][:5]:
            print(f"    {line}")
        if len(report["no_slot_match"]) > 5:
            print(f"    ... and {len(report['no_slot_match']) - 5} more")

    if report["renamed"]:
        print(f"\n  CORRECTED {len(report['renamed'])} player name(s) to the "
              f"spelling already in the record:")
        for wrong, right in sorted(report["renamed"].items()):
            n = sum(1 for r in rows if r["player_name"] == right)
            print(f"    '{wrong}' -> '{right}'  ({n} row(s) now under '{right}')")
        print("    Left uncorrected, each variant would have become a separate")
        print("    player, silently splitting career totals.")

    if report["ambiguous_names"]:
        print(f"\n  WARNING: {len(report['ambiguous_names'])} name(s) matched more "
              f"than one existing spelling and were NOT changed:")
        for wrong, opts in sorted(report["ambiguous_names"].items()):
            print(f"    '{wrong}' -> {opts}")

    if report["new_players"]:
        print(f"\n  NOTE: {len(report['new_players'])} player(s) new to the record; "
              f"player_id left null:")
        for n in sorted(report["new_players"])[:8]:
            print(f"    {n}")
        if len(report["new_players"]) > 8:
            print(f"    ... and {len(report['new_players']) - 8} more")
        print("    (player_id is archival -- no engine module reads it from history)")

    if report["is_injured_disagreements"]:
        print(f"\n  WARNING: is_injured in PLAYERLOG.xlsx disagreed with the "
              f"derived value on {len(report['is_injured_disagreements'])} row(s).")
        print("    The derived value was used. Investigate if this count is large:")
        for line in report["is_injured_disagreements"][:5]:
            print(f"    {line}")


def verify_written(season_key, expected_total, expected_new):
    """Re-read the file from disk and confirm what landed."""
    with open(HISTORY_JSON, "r", encoding="utf-8") as f:
        data = json.load(f)

    problems = []
    if len(data) != expected_total:
        problems.append(f"row count is {len(data):,}, expected {expected_total:,}")

    season_rows = [r for r in data if r.get("season_key") == season_key]
    if len(season_rows) != expected_new:
        problems.append(
            f"{season_key} has {len(season_rows):,} rows, expected {expected_new:,}"
        )

    bad_schema = [r for r in season_rows if set(r.keys()) != set(HISTORY_FIELDS)]
    if bad_schema:
        problems.append(f"{len(bad_schema)} appended row(s) have the wrong field set")

    return problems


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Append a finished season's player log to HISTORICAL_PLAYERLOG.json"
    )
    parser.add_argument("--execute", action="store_true",
                        help="actually write (default is a dry run)")
    parser.add_argument("--force", action="store_true",
                        help="replace the season if it is already in the record")
    parser.add_argument("--skip-drafts", action="store_true",
                        help="do not roll DRAFT_PICKS_CURRENT.json into "
                             "all_drafts.json")
    parser.add_argument("--skip-tables", action="store_true",
                        help="do not roll matchups, standings, team keys and "
                             "trades into data/historical/")
    parser.add_argument("--repair-standings", action="store_true",
                        help="add the explicit rank fields to seasons already "
                             "in all_standings.json, then stop")
    parser.add_argument("--tables-only", action="store_true",
                        help="roll ONLY those four tables. Use this to repair "
                             "a season whose player log already went in but "
                             "whose tables did not.")
    parser.add_argument("--season", default=None,
                        help=f"season key to roll up (default: {CURRENT_SEASON})")
    args = parser.parse_args()

    season_key = args.season or CURRENT_SEASON

    if args.repair_standings:
        header("REPAIR all_standings.json")
        status, msg = repair_standings_fields(execute=args.execute)
        print(f"    [{status}] {msg}")
        if not args.execute:
            print("\n  [DRY-RUN] Nothing written. Re-run with --execute.")
        return 1 if status == "error" else 0

    if args.tables_only:
        header(f"SEASON TABLES -- {season_key}")
        results = rollup_season_tables(season_key, execute=args.execute,
                                       force=args.force)
        for name, status, msg in results:
            print(f"    {name:11} [{status}] {msg}")
        if not args.execute:
            print("\n  [DRY-RUN] Nothing written. Re-run with --execute.")
        return 1 if any(st == "error" for _, st, _ in results) else 0

    for path in (PLAYERLOG_XLSX, LINEUPS_XLSX, HISTORY_JSON):
        if not path.exists():
            return fail(f"required file not found: {rel(path)}")

    with open(HISTORY_JSON, "r", encoding="utf-8") as f:
        history = json.load(f)

    existing = sum(1 for r in history if r.get("season_key") == season_key)
    if existing and not args.force:
        return fail(
            f"{season_key} is already in HISTORICAL_PLAYERLOG.json "
            f"({existing:,} rows).\n         Use --force to replace those rows."
        )

    try:
        rows, report = build_rows(season_key, history)
    except (ValueError, KeyError) as e:
        return fail(str(e))

    if not rows:
        return fail("no rows built from PLAYERLOG.xlsx")

    base = [r for r in history if r.get("season_key") != season_key] if args.force else history
    print_report(season_key, rows, report, len(base))

    if not args.skip_drafts:
        status, msg = rollup_drafts(season_key, execute=False, force=args.force)
        print(f"\n  DRAFT ROLLUP -> {rel(DRAFTS_JSON)}")
        print(f"    [{status}] {msg}")
        if status == "done":
            print("    No Yahoo call needed -- DRAFT_PICKS_CURRENT.json already")
            print("    uses the all_drafts.json schema.")

    if not args.skip_tables:
        print(f"\n  SEASON TABLES -> {rel(MATCHUPS_JSON.parent)}")
        for name, status, msg in rollup_season_tables(season_key, execute=False,
                                                      force=args.force):
            print(f"    {name:11} [{status}] {msg}")

    if not args.execute:
        print("\n  [DRY-RUN] Nothing written. Re-run with --execute to append.")
        print("  Run this BEFORE scripts/start_new_season.py -- Phase 2 truncates")
        print("  PLAYERLOG.xlsx to a header row.")
        return 0

    header("WRITING")
    backup = HISTORY_JSON.with_suffix(".json.bak")
    shutil.copy2(HISTORY_JSON, backup)
    print(f"\n  Backup:  {rel(backup)}")

    if args.force and existing:
        print(f"  Removed  {existing:,} existing {season_key} rows (--force)")

    merged = base + rows
    with open(HISTORY_JSON, "w", encoding="utf-8") as f:
        json.dump(merged, f, indent=2)
    print(f"  Wrote    {len(merged):,} rows to {rel(HISTORY_JSON)}")

    problems = verify_written(season_key, len(merged), len(rows))
    if problems:
        print("\n  VERIFICATION FAILED:")
        for p in problems:
            print(f"    - {p}")
        print(f"\n  The previous file is intact at {backup.name}. Restore it, "
              f"then investigate.")
        return 1

    print(f"  Verified {len(rows):,} {season_key} rows on disk, schema matches")

    if not args.skip_drafts:
        status, msg = rollup_drafts(season_key, execute=True, force=args.force)
        print(f"\n  Drafts:  [{status}] {msg}")
        if status == "error":
            print("  Draft rollup FAILED. The player log is fine; all_drafts.json")
            print("  is restorable from all_drafts.json.bak.")
            return 1
    if not args.skip_tables:
        print(f"\n  SEASON TABLES -> {rel(MATCHUPS_JSON.parent)}")
        failed = False
        for name, status, msg in rollup_season_tables(season_key, execute=True,
                                                      force=args.force):
            print(f"    {name:11} [{status}] {msg}")
            failed = failed or status == "error"
        if failed:
            print("\n  One or more season tables FAILED. Each file has a .bak")
            print("  beside it from before this run.")
            return 1

    print("\n  Next: update data/LEAGUEHISTORY.xlsx, then run")
    print("        py scripts/start_new_season.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
