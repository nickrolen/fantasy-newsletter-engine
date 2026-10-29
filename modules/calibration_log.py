"""
calibration_log.py -- E1: every line the newsletter publishes, logged at
publish time, settled when the week closes, and scored by engine version.

WHY NOT backtest_extract
------------------------
scripts/backtest_extract.py is RETROSPECTIVE: it parses published newsletter
HTML to recover lines that went out, because for 2025-26 the HTML is the only
immutable record (output/*.json gets overwritten by re-runs). It produced the
12 lines and the -120.8 level bias in data/backtest/.

This is the forward-looking twin. A line is logged as it is published, with
everything needed to reproduce and settle it, so the curve builds itself week
by week and nobody parses HTML again.

THE FIELD THAT MATTERS MOST: WHICH ENGINE PRODUCED THE LINE
-----------------------------------------------------------
The -120.8 baseline was measured on an engine that no longer exists.
output/live_lines_week1.json, generated 2026-10-20, still carries the caveat
"the 10% injury discount applies to the simulated remainder only" -- a
mechanism deleted on 10-21. In three days the betting path also gained
positional lineups, a baseline injury hazard, a new tag vocabulary and a
frozen durability prior, and the same week-1 matchup moved from +27 to +22 on
the spread and 3030 to 2830 on the total.

So a curve that pools lines from both sides of that is not a measurement of
anything. Every record carries its ENGINE VERSION (the git commit, plus
whether the tree was dirty) alongside the seed, the state hash and the as-of
timestamp, and `curve()` groups by engine version. Pooling across versions
takes an explicit mix_versions=True -- the mistake is impossible, not
discouraged, because this is the project's defining defect aimed at the one
artifact whose whole purpose is to stay true.

APPEND-ONLY
-----------
A line is never rewritten. A line re-issued mid-week by a B2 refresh
(scripts/refresh_lines.py) is a NEW record with its own as-of timestamp, so
the log says what was on the page when. The ONE field group that fills in
later is settlement, once and never again: re-running the same build appends
nothing (same line key -- see IDENTITY), and a settled line that disagrees with RECORDS.json
RAISES rather than being quietly corrected -- that disagreement means the log
and the records disagree about what happened.

ONE OUTCOME, ONE OBSERVATION (HANDOFF_CURVE_GROUPING, Nick 10-28)
----------------------------------------------------------------
The record's identity is the line key, which covers the whole week's inputs
including the as-of date, so every midnight refresh appends a record per
matchup, and a change to one manager re-logs both matchups. A seven-day week
ends with ~14 records describing two outcomes (28 in a 14-day week). They are
all kept -- they are the record of what was published and when -- but the
curve scores ONE line per (season, week, matchup) within each group: the one
with the latest as_of, ties going to the later-appended record. Pooled as
independent, the duplicates shrink the standard error by about the square
root of the duplication and the curve claims confidence it has not got.

A GROUP IS ENGINE x SOURCE (Nick 10-28), in the pooled-versions mode too. A
weekly-build line and a live-refresh line on the same matchup-week share one
outcome, so they cannot sit in one pool either: each product gets its own
curve -- the weekly build's is the newsletter's line, the live refresh's is
the live page's. Two engines on the same week stay apart as well: that is the
comparison the engine split exists to make.

THE METRICS ARE NOT HERE
------------------------
Every statistic comes from modules/backtest_metrics.py -- score_error_stats,
margin_error_stats, standardized_residuals, dispersion_ratio, implied_sigma,
brier_score, log_loss, brier_skill_score, hit_rate. There is no second
implementation of any of them in this module, and a test asserts it.

WHAT THIS IS NOT
----------------
All four managers see these lines, so a systematic bias gets arbitraged. The
statistical curve is one signal; who actually bets which side is the other,
and that is D2's ledger, not this. This is instrumentation: it reports to the
build's console, never into the newsletter, which has its own voice rules.
"""

from __future__ import annotations

import json
import subprocess
from datetime import date, datetime
from pathlib import Path
from typing import Iterable, Optional, Sequence

from . import backtest_metrics as bm
from .data_loader import CURRENT_SEASON, atomic_write_json

# WORK_BREAKDOWN.md says config/PUBLISHED_LINES.json. Overridden on purpose:
# config/ holds settings the code reads, not a growing append-only log, and
# tests/test_start_new_season.py::test_config_dir_has_no_unclassified_files
# requires every file there to be classified per-season or cross-season. This
# sits beside the retrospective data instead.
LOG_RELPATH = Path("data") / "calibration" / "published_lines.json"
SCHEMA = 1

# The source that produced a record, for reading the log by eye.
WEEKLY_BUILD = "weekly_build"          # generate_stats_report, the pre-week line
LIVE_REFRESH = "live_refresh"          # refresh_lines, a mid-week re-issue

# What makes two records the same published line: the LINE KEY, which is
# week_state.line_cache_key -- the same answer B3's refresh service uses to
# decide that nothing changed, over the played state, the tags, the
# projections used, the governing INJURY_OVERRIDES entries, the schedule, the
# assumptions, the seed, the simulation count and the engine. One definition:
# if the cache says the line is unchanged, the log does not append.
#
# It used to be a parallel tuple ending in `as_of`, and as_of is a wall-clock
# timestamp to the second -- so "idempotent" held only for a rerun inside the
# same second (two minutes apart on 2026-10-23: both kept), while the tuple
# could not see a tag or an override at all. Dropping as_of or truncating it to
# the day would have fixed the first and kept the second: a tag change the same
# day, same state and seed, would have been skipped as a duplicate.
#
# A dirty or unknown engine's key cannot vouch for the code (two uncommitted
# simulators share it), so for those records the published numbers join the
# identity: the same inputs and the same numbers are one record; different
# numbers from the "same" engine are two.
IDENTITY = ("season", "week", "matchup_id", "source", "line_key")
PUBLISHED = ("spread_a", "total", "moneyline_a", "moneyline_b", "win_prob_a", "win_prob_b",
             "projected_a", "projected_b", "banked_a", "banked_b")
# Records written before 2026-10-28 carry no line_key; they keep the old tuple.
LEGACY_IDENTITY = ("season", "week", "matchup_id", "engine_commit", "engine_dirty",
                   "seed", "num_simulations", "state_hash", "as_of", "source")

SETTLEMENT = ("actual_a", "actual_b", "actual_source", "settled_at")


class CalibrationConflict(RuntimeError):
    """The log and RECORDS.json disagree about what happened."""


class EngineVersionMix(ValueError):
    """Asked to pool lines from different engines without saying so."""


# =============================================================================
# the engine that produced a line
# =============================================================================

_ENGINE_VERSION: dict = {}


# WHAT "THE ENGINE" IS -- the paths whose changes change the simulator.
# Dirtiness is checked against these and nothing else (HANDOFF_ENGINE_KEY_SCOPE
# 2026-10-23). The whole tree was wrong in both directions of the build:
#   - a refresh writes output/live_lines_weekN*.json and
#     data/calibration/published_lines.json -- its OWN outputs -- so the render
#     that follows read "<commit>-dirty" and refused the payload just priced;
#   - the weekly workflow writes into config/ every week (fetch_playerlist ->
#     PLAYER_AGES.json, check_playerlist --snapshot -> config/snapshots/,
#     update_leaguehistory -> .leaguehistory_applied_weeks.json, the build ->
#     RECENT_CONTENT.json, format_stats_report -> POTW_HISTORY.json and
#     LAST_WEEK_RECAP.md) and INJURY_OVERRIDES.json is edited by hand. Those
#     are inputs and newsletter state, not the simulator; counting them would
#     have marked every line of every week "-dirty".
# So: the code, the one config file that holds the simulator's parameters,
# and the frozen durability prior league_config names (engine_paths). Inputs
# belong to the state hash and to the line record, not to this key.
ENGINE_PATHS = ("modules", "scripts", "config/league_config.json")


def engine_paths(base_path=".") -> list:
    """ENGINE_PATHS plus the durability-prior snapshot league_config names.

    That snapshot is a frozen engine input (data_loader.load_durability_prior):
    overwriting it in place changes every hazard, so it counts. The weekly
    snapshots beside it do not. A league_config that cannot be read adds
    nothing here -- the file itself is in ENGINE_PATHS, so an edit to it is
    already dirty.
    """
    paths = list(ENGINE_PATHS)
    try:
        conf = json.loads((Path(base_path) / "config" / "league_config.json")
                          .read_text(encoding="utf-8"))
        snap = (conf.get("durability_prior") or {}).get("snapshot")
    except (OSError, ValueError, AttributeError):
        snap = None
    if snap:
        paths.append(str(snap).replace("\\", "/"))
    return paths


def engine_version(base_path=".") -> dict:
    """{"commit": short sha or None, "dirty": bool}.

    `dirty` matters: on a dirty engine the commit does not identify the
    simulator, so two records can share a commit and not share a simulator.
    Recorded rather than hidden, and it is part of the grouping key.

    "Dirty" means a change under engine_paths() -- the simulator's code and
    parameters -- not anywhere in the tree. See ENGINE_PATHS for why.

    CACHED PER PROCESS per path. `git status --porcelain` takes about 4
    seconds on a repo mounted over the desktop bridge, and a run asks for
    the engine once per logged line and once per rendered page -- which made
    the live-line page's tests 160 seconds on their own. One run is one
    engine by definition (E1 records one engine per line), so re-reading it
    mid-process cannot tell us anything the first read did not.
    """
    key = str(Path(base_path).resolve())
    hit = _ENGINE_VERSION.get(key)
    if hit is not None:
        return dict(hit)

    def _git(*args):
        try:
            # 20s, not 5: `git status --porcelain` takes about 4 seconds on a
            # repo mounted over the desktop bridge, and two of them at once
            # (a parallel test run) pushed past a 5-second limit -- which
            # returned dirty=None, an engine whose dirtiness is UNKNOWN.
            out = subprocess.run(["git", *args], cwd=str(base_path),
                                 capture_output=True, text=True, timeout=20)
            return out.stdout.strip() if out.returncode == 0 else None
        except Exception:
            return None
    commit = _git("rev-parse", "--short", "HEAD")
    status = _git("status", "--porcelain", "--", *engine_paths(base_path))
    out = {"commit": commit, "dirty": bool(status) if status is not None else None}
    _ENGINE_VERSION[key] = out
    return dict(out)


def engine_key(record: dict) -> str:
    """The label a curve is grouped under.

    Three states, not two: clean is the bare commit, dirty is suffixed, and
    UNKNOWN dirtiness (git could not say) gets its own label rather than
    being filed as clean. A dirty tree pooled with the clean commit's lines
    is the exact mistake this field exists to prevent, so an unknown answer
    must not round down to the safe-looking one.
    """
    commit = record.get("engine_commit") or "unknown"
    dirty = record.get("engine_dirty")
    if dirty is None:
        return f"{commit}-unknown"
    return f"{commit}-dirty" if dirty else commit


# =============================================================================
# the record
# =============================================================================

def line_record(line, *, week: int, season: str = None, seed: int,
                num_simulations: int, engine: dict, line_key: str, as_of: str = None,
                state_hash: str = None, source: str = WEEKLY_BUILD,
                tags: dict = None, overrides_governing: dict = None) -> dict:
    """One published line, as logged. `line` is a simulator_betting.BettingLine.

    The numbers are the ones that went on the page: the spread and total are
    the rounded, published values, and the projected scores are what the
    newsletter printed beside them.

    line_key is week_state.line_cache_key(...)["key"] for the inputs this line
    was priced from -- the record's identity (IDENTITY). Required: a record
    without one cannot be told apart from a rerun.
    """
    if not line_key:
        raise ValueError("line_record needs line_key (week_state.line_cache_key): it is the "
                         "record's identity, and without it a rerun logs the same line twice")
    a, b = line.manager_a, line.manager_b
    tags = dict(tags or {})
    return {
        "season": str(season or CURRENT_SEASON),
        "week": int(week),
        "manager_a": a,
        "manager_b": b,
        "matchup_id": _matchup_id(a, b),
        "team_a": getattr(line, "team_name_a", a),
        "team_b": getattr(line, "team_name_b", b),
        # the line as published
        "spread_a": float(line.spread_a),
        "total": float(line.over_under),
        "moneyline_a": int(line.moneyline_a),
        "moneyline_b": int(line.moneyline_b),
        "win_prob_a": float(line.win_prob_a),
        "win_prob_b": float(line.win_prob_b),
        "projected_a": float(line.avg_score_a),
        "projected_b": float(line.avg_score_b),
        "banked_a": float(getattr(line, "banked_a", 0.0) or 0.0),
        "banked_b": float(getattr(line, "banked_b", 0.0) or 0.0),
        # provenance: which engine, which draws, as of when
        "engine_commit": engine.get("commit"),
        "engine_dirty": engine.get("dirty"),
        "seed": None if seed is None else int(seed),
        "num_simulations": int(num_simulations),
        "state_hash": state_hash,
        "line_key": str(line_key),
        "as_of": as_of or datetime.now().isoformat(timespec="seconds"),
        "source": source,
        # the inputs that move a line
        "tags": {k: str(v) for k, v in sorted(tags.items()) if str(v).upper() != "HEALTHY"},
        "overrides_governing": {m: bool(v) for m, v in sorted((overrides_governing or {}).items())},
        # settlement, filled in once the week closes
        "actual_a": None,
        "actual_b": None,
        "actual_source": None,
        "settled_at": None,
    }


def overrides_governing(week: int, week_dates: Sequence[date], rosters: dict,
                        override_players: Iterable[dict]) -> dict:
    """{manager: did an INJURY_OVERRIDES entry govern his roster this week}.

    One of the two inputs that move a line and are not in the line itself (the
    other is the tags). Uses absence.override_governs, the same rule the
    simulators apply, so the log records the condition the engine saw rather
    than a second reading of the file.
    """
    from . import absence
    from .data_loader import PlayerIndex
    out = {m: False for m in rosters}
    where = PlayerIndex()
    for manager, players in (rosters or {}).items():
        for name in players or []:
            where[name] = manager
    for entry in override_players or []:
        manager = where.get(entry.get("player_name", ""))
        if manager is None:
            continue
        if absence.override_governs(
                week, week_dates, entry.get("out_weeks") or (),
                entry.get("return_week"),
                absence.parse_out_from(entry.get("out_from"))):
            out[manager] = True
    return out


def _matchup_id(a: str, b: str) -> str:
    """Order-free, the same convention as simulator_betting.matchup_id."""
    return "|".join(sorted((a, b)))


def identity(record: dict) -> tuple:
    """What makes two records the same published line (see IDENTITY)."""
    if not record.get("line_key"):
        return ("legacy",) + tuple(record.get(k) for k in LEGACY_IDENTITY)
    out = tuple(record.get(k) for k in IDENTITY)
    if record.get("engine_dirty") is not False:          # dirty, or unknown
        out += tuple(record.get(k) for k in PUBLISHED)
    return out


# =============================================================================
# the file
# =============================================================================

def log_path(base_path=".") -> Path:
    return Path(base_path) / LOG_RELPATH


def load_log(base_path=".") -> dict:
    """The log, or an empty one. A corrupt file RAISES: this is an
    append-only record, and overwriting it with a fresh one would delete
    history that cannot be recovered."""
    path = log_path(base_path)
    if not path.is_file():
        return {"schema": SCHEMA, "lines": []}
    try:
        blob = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise CalibrationConflict(
            f"{path} is not readable JSON ({e}). It is the append-only record of "
            "every published line; fix or restore it rather than letting a build "
            "start a new one.") from None
    blob.setdefault("schema", SCHEMA)
    blob.setdefault("lines", [])
    return blob


def save_log(blob: dict, base_path=".") -> Path:
    path = log_path(base_path)
    blob["schema"] = blob.get("schema", SCHEMA)
    blob["_comment"] = (
        "Append-only: every line the newsletter published, logged at publish time. "
        "A re-issued line is a new entry, never an edit. Metrics live in "
        "modules/backtest_metrics.py and are grouped by engine_commit -- see "
        "modules/calibration_log.py.")
    atomic_write_json(path, blob)
    return path


def append(records: Sequence[dict], base_path=".") -> dict:
    """Append records that are not already there. {"added", "skipped", "path"}.

    Idempotent by IDENTITY (the line key), so re-running a build with nothing
    changed logs nothing twice -- a minute later or a day later -- while a
    re-issue whose inputs moved (a new day's played state, a tag, an override,
    a projection) appends.
    """
    blob = load_log(base_path)
    seen = {identity(r) for r in blob["lines"]}
    added = 0
    for record in records:
        if identity(record) in seen:
            continue
        blob["lines"].append(record)
        seen.add(identity(record))
        added += 1
    if added:
        save_log(blob, base_path)
    return {"added": added, "skipped": len(records) - added, "path": str(log_path(base_path))}


# =============================================================================
# settlement
# =============================================================================

def weekly_scores(records_json: dict) -> dict:
    """{week: {manager: score}} from RECORDS.json weekly_scores."""
    out: dict = {}
    raw = (records_json or {}).get("weekly_scores") or {}
    if isinstance(raw, dict):
        for manager, entries in raw.items():
            for entry in entries or []:
                week = entry.get("week")
                if week is None:
                    continue
                out.setdefault(int(week), {})[manager] = float(entry.get("score") or 0.0)
    return out


def settle(records_json: dict, base_path=".", today: date = None) -> dict:
    """Fill in actuals for every unsettled line whose week has closed.

    A week counts as closed when RECORDS.json has a score for both managers.
    Idempotent. A line already settled whose actuals disagree with RECORDS
    RAISES CalibrationConflict -- the log and the records cannot both be the
    truth about a played week.
    """
    blob = load_log(base_path)
    scores = weekly_scores(records_json)
    stamp = (today or date.today()).isoformat()
    settled, conflicts = 0, []
    for record in blob["lines"]:
        week_scores = scores.get(int(record["week"])) or {}
        a = week_scores.get(record["manager_a"])
        b = week_scores.get(record["manager_b"])
        if a is None or b is None:
            continue
        if record.get("settled_at"):
            if (not _same(record.get("actual_a"), a)) or (not _same(record.get("actual_b"), b)):
                conflicts.append(
                    f"week {record['week']} {record['manager_a']} v {record['manager_b']}: "
                    f"the log says {record.get('actual_a')}-{record.get('actual_b')}, "
                    f"RECORDS.json says {a}-{b}")
            continue
        record["actual_a"], record["actual_b"] = float(a), float(b)
        record["actual_source"] = "RECORDS.json weekly_scores"
        record["settled_at"] = stamp
        settled += 1
    if conflicts:
        # Many records describe one matchup-week (see the module docstring):
        # name each disagreement once, with how many records carry it.
        counts: dict = {}
        for c in conflicts:
            counts[c] = counts.get(c, 0) + 1
        conflicts = [c if n == 1 else f"{c} ({n} records)" for c, n in counts.items()]
        raise CalibrationConflict(
            "settled lines disagree with RECORDS.json: " + "; ".join(conflicts) +
            ". One of the two is wrong about a played week -- fix it rather than "
            "letting the calibration curve average them.")
    if settled:
        save_log(blob, base_path)
    return {"settled": settled, "unsettled": sum(1 for r in blob["lines"] if not r.get("settled_at")),
            "total": len(blob["lines"])}


def _same(x, y, tol: float = 0.01) -> bool:
    try:
        return abs(float(x) - float(y)) <= tol
    except (TypeError, ValueError):
        return False


# =============================================================================
# the live curve -- every statistic from backtest_metrics
# =============================================================================

def settled(lines: Iterable[dict]) -> list:
    """Only lines with actuals. An unsettled line is a forecast, not an
    observation, and never counts towards the curve."""
    return [r for r in lines
            if r.get("settled_at") and r.get("actual_a") is not None
            and r.get("actual_b") is not None]


def _as_of_key(record: dict, position: int) -> tuple:
    """Sort key for "latest": the as_of instant (a bare date is its midnight),
    then position in the log -- the later-appended record wins a tie."""
    raw = str(record.get("as_of") or "")
    try:
        when = datetime.fromisoformat(raw)
    except ValueError:
        raise CalibrationConflict(f"week {record.get('week')} {record.get('matchup_id')}: "
                                  f"as_of {raw!r} is not an ISO date or time") from None
    if when.tzinfo is not None:
        when = when.replace(tzinfo=None)
    return (when, position)


def latest_per_matchup_week(rows: Sequence[dict]) -> tuple:
    """(the rows to score, what was collapsed).

    One row per (season, week, matchup_id, source, engine): the latest as_of,
    a tie going to the later-appended row. `rows` are in log order. Each
    entry of `collapsed` names the line used and how many records it stood
    for; `ties` names any tie whose records carried DIFFERENT published
    numbers (the later one was used, and the summary says so)."""
    groups: dict = {}
    for i, r in enumerate(rows):
        key = (str(r.get("season")), int(r["week"]), r.get("matchup_id"), r.get("source"),
               engine_key(r))
        groups.setdefault(key, []).append((_as_of_key(r, i), r))
    kept, collapsed, ties = [], [], []
    for key in sorted(groups, key=lambda k: (k[0], k[1], k[2] or "", k[3] or "", k[4])):
        members = sorted(groups[key], key=lambda x: x[0])
        (when, _pos), chosen = members[-1]
        kept.append(chosen)
        collapsed.append({"season": key[0], "week": key[1], "matchup_id": key[2],
                          "source": key[3], "as_of": chosen.get("as_of"), "of": len(members)})
        same_time = [r for (w, _p), r in members if w == when]
        if len(same_time) > 1 and len({tuple(r.get(f) for f in PUBLISHED) for r in same_time}) > 1:
            ties.append(f"week {key[1]} {key[2]} ({key[3]}): {len(same_time)} records share "
                        f"as_of {chosen.get('as_of')} with different published numbers; "
                        "the later-appended was used")
    return kept, {"collapsed": collapsed, "ties": ties}


def curve(base_path=".", lines: Sequence[dict] = None, engine: str = None,
          mix_versions: bool = False) -> dict:
    """Calibration of the settled lines, BY ENGINE VERSION AND BY SOURCE.

    Returns {"groups": {group label: metrics}, "unsettled": n, "engines": [...],
    "sources": [...]}. A group label is group_label(engine, source):
    "abc1234 / weekly_build". mix_versions=True pools every version per source,
    the engine part labelled as mixed; anything else keeps them apart, because
    the engine changed under the lines (see the module docstring). Asking for
    one named `engine` is exact, still split by source. Sources are never
    pooled: two products' lines on one matchup-week share one outcome.
    """
    rows = list(lines if lines is not None else load_log(base_path)["lines"])
    done = settled(rows)
    engines = sorted({engine_key(r) for r in done})
    sources = sorted({str(r.get("source")) for r in done})
    if engine is not None:
        by_engine = {engine: [r for r in done if engine_key(r) == engine]}
    elif mix_versions:
        label = "mixed (%d engine%s)" % (len(engines), "" if len(engines) == 1 else "s")
        by_engine = {label: done}
    else:
        by_engine = {k: [r for r in done if engine_key(r) == k] for k in engines}
    groups = {}
    for eng, members in by_engine.items():
        for src in sorted({str(r.get("source")) for r in members}):
            groups[group_label(eng, src)] = [r for r in members if str(r.get("source")) == src]
    return {
        "groups": {k: _metrics(v) for k, v in groups.items()},
        "engines": engines,
        "sources": sources,
        "settled": len(done),
        "unsettled": len(rows) - len(done),
    }


SOURCE_LABELS = {WEEKLY_BUILD: "the newsletter's line", LIVE_REFRESH: "the live page's line"}


def group_label(engine: str, source: str) -> str:
    """One curve: an engine (or the pooled versions) and one source."""
    return f"{engine} / {source}"


def _metrics(rows: Sequence[dict]) -> dict:
    """Every number here comes from backtest_metrics, over ONE line per
    matchup-week and source (latest_per_matchup_week): n_records is how many
    settled records the group holds, n_lines how many distinct lines they
    describe -- the n every statistic uses."""
    n_records = len(rows)
    rows, info = latest_per_matchup_week(rows)
    out = {"n_lines": len(rows), "n_records": n_records,
           "weeks": sorted({int(r["week"]) for r in rows}),
           "collapsed": info["collapsed"], "ties": info["ties"]}
    if len(rows) < 2:
        out["note"] = "need at least 2 settled lines for the statistics"
        return out
    projected = [r["projected_a"] for r in rows] + [r["projected_b"] for r in rows]
    actual = [r["actual_a"] for r in rows] + [r["actual_b"] for r in rows]
    proj_margin = [r["projected_a"] - r["projected_b"] for r in rows]
    act_margin = [r["actual_a"] - r["actual_b"] for r in rows]
    probs = [r["win_prob_a"] / 100.0 for r in rows]

    out["level"] = bm.score_error_stats(projected, actual)
    out["margin"] = bm.margin_error_stats(proj_margin, act_margin)
    residuals = bm.standardized_residuals(proj_margin, act_margin, probs)
    out["dispersion"] = (bm.dispersion_ratio(residuals) if len(residuals) >= 2
                         else {"n": len(residuals),
                               "note": "sigma is not identified on these lines"})
    # A tied week is neither a win nor a loss (tiebreaker_rules), and the
    # probability scores take 0/1 outcomes, so ties are dropped and counted.
    scored = [(p, 1 if r["actual_a"] > r["actual_b"] else 0)
              for p, r in zip(probs, rows) if r["actual_a"] != r["actual_b"]]
    ties = len(rows) - len(scored)
    if scored:
        p_list = [p for p, _ in scored]
        outcomes = [o for _, o in scored]
        out["probability"] = {
            "n": len(scored),
            "ties_dropped": ties,
            "brier": bm.brier_score(p_list, outcomes),
            "brier_skill_vs_coin_flip": bm.brier_skill_score(p_list, outcomes),
            "log_loss": bm.log_loss(p_list, outcomes),
            "coin_flip_log_loss": bm.log_loss([0.5] * len(scored), outcomes),
            "hit_rate": bm.hit_rate([p > 0.5 for p in p_list],
                                    [bool(o) for o in outcomes]),
        }
    else:
        out["probability"] = {"n": 0, "ties_dropped": ties,
                              "note": "no decided lines yet"}
    return out


def _used_lines(m: dict) -> list:
    """Which record each scored line is: "week 2 (live_refresh): Benton|Nick
    latest of 7" -- one console line per week and source, so nobody wonders
    where the other records went."""
    by = {}
    for c in m.get("collapsed", []):
        by.setdefault((c["week"], c["source"]), []).append(
            f"{c['matchup_id']} latest of {c['of']}" if c["of"] > 1 else f"{c['matchup_id']} (1)")
    out = [f"      week {w} ({src}): " + ", ".join(v) for (w, src), v in sorted(by.items())]
    return out + [f"      NOTE: {t}" for t in m.get("ties", [])]


def format_curve(result: dict) -> list:
    """The curve as console lines. Instrumentation for the build's output --
    never the newsletter."""
    out = []
    total = result["settled"] + result["unsettled"]
    if not total:
        return ["  Calibration log: empty -- no line has been published yet."]
    out.append(f"  Calibration log: {total} record(s), {result['settled']} settled, "
               f"{result['unsettled']} awaiting a result")
    if not result["settled"]:
        out.append("    (no settled line yet, so there is no curve: the first "
                   "week's lines settle on next week's build)")
        return out
    for key, m in sorted(result["groups"].items()):
        if not m["n_lines"]:
            continue
        eng, _, src = key.rpartition(" / ")
        what = SOURCE_LABELS.get(src)
        name = f"engine {eng}, {src}" + (f" ({what})" if what else "")
        out.append(f"    {name}: {m['n_lines']} line(s) from {m['n_records']} settled "
                   f"record(s), weeks {m['weeks'][0]}-{m['weeks'][-1]}"
                   if m["weeks"] else f"    {name}")
        out += _used_lines(m)
        if "note" in m:
            out.append(f"      {m['note']}")
            continue
        lvl, mar = m["level"], m["margin"]
        out.append(f"      level  bias {lvl['bias']:+.1f} +/- {lvl['se_bias']:.1f} "
                   f"(t {lvl['t_stat']:+.2f}), mae {lvl['mae']:.1f}, "
                   f"{lvl['below']}/{lvl['n']} under projection")
        out.append(f"      margin bias {mar['bias']:+.1f} +/- {mar['se_bias']:.1f}")
        disp = m["dispersion"]
        if "rms" in disp:
            out.append(f"      spread rms {disp['rms']:.2f} "
                       f"[{disp['ci_low']:.2f}, {disp['ci_high']:.2f}] -- {disp['verdict']}")
        prob = m["probability"]
        if prob.get("n"):
            out.append(f"      probs  brier {prob['brier']:.3f} vs 0.250 coin flip "
                       f"(skill {prob['brier_skill_vs_coin_flip']:+.3f}), "
                       f"log loss {prob['log_loss']:.3f} vs {prob['coin_flip_log_loss']:.3f}, "
                       f"favourite {prob['hit_rate']['correct']}/{prob['hit_rate']['n']}")
    return out
