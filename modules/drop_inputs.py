"""
drop_inputs.py -- what the roster plan's injured-drop decisions read (task 18b).

modules/injured_drop decides; it reads nothing. This module is where its
inputs come from in a real run, behind roster_plan.DropContext, and it is
LAZY: nothing here is read unless some team needs a decision at some window
(an injured player out for the whole week beyond the IL slots). Today no
team does, so a run reads nothing new and prices exactly as before.

THE STAKES: the previous run's stakes file (written by title_odds_run after
every season pass; schema 2 carries the margins and title chances).
  - MATCHING (INJURED_DROP_DESIGN s.4): a future window W uses the file's row
    for every week w from W to the last bracket week, by week number, as the
    file states it: P(title | wins w) - P(title | loses w) conditioned on
    what the file's run knew. A row exists for every week still undecided
    when the file was written, so every future week has one; a week the plan
    needs with no row RAISES (the file is from after that week, or cut).
    The file's age is not limited: a file from an earlier week of this
    season still describes every week after it (the nightly run rewrites it
    each night). It must not be from a later week than the plan's start.
  - THE BOOTSTRAP (Nick, 11-04; HANDOFF_18B_REFIT_AND_WIRE s.2), the one
    exception to raise-don't-default: a file that is MISSING, from ANOTHER
    SEASON, or SCHEMA 1 cannot be used yet. The run then plans with no
    injured drops (the plan's behaviour before 18b), records the note "no
    stakes yet: planned without injured drops (...)", and goes on to write
    the file; the next run uses it. Anything else wrong with a file that
    exists -- unreadable JSON, an unknown schema, a missing field or row --
    RAISES.

KEEP CHANCES: keepability v3's live keeper watch (keepability_v3.keeper_watch,
about 8 s on the real data), once per run and only when a decision is needed.
K = 5 chances, the same order as the top-4 protection everywhere else.

POINTS: a player's expected points in week w are his effective FPPG x his
NBA team's games that week (from his return date in a midweek-return week)
x the share of games he plays, 1 - durability_miss_rate(his pre-season GP).
His pre-season GP is the durability prior's (data.durability_prior), as the
simulator's baseline hazard uses, without recording a fallback; a stand-in's
is the prior's median, stated on him.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from . import injured_drop as idr

BOOTSTRAP_NOTE = "no stakes yet: planned without injured drops"


class StakesFileError(RuntimeError):
    """The stakes file exists and cannot be used: unreadable or malformed."""


def stakes_path(base_path) -> Path:
    from .title_odds_run import STAKES_FILE
    return Path(base_path) / STAKES_FILE


def read_stakes(base_path, season: str = None):
    """(blob, None) when the file can be used; (None, note) for the
    bootstrap (missing, another season, schema 1). Raises StakesFileError
    for anything else."""
    from .data_loader import CURRENT_SEASON
    from .title_odds_run import STAKES_SCHEMA
    season = season or CURRENT_SEASON
    path = stakes_path(base_path)
    if not path.is_file():
        return None, f"{BOOTSTRAP_NOTE} ({path.name} is missing)"
    try:
        blob = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise StakesFileError(f"{path} is unreadable ({e}); it is not regenerated here") from e
    if not isinstance(blob, dict):
        raise StakesFileError(f"{path} is not a JSON object")
    schema = blob.get("schema")
    if schema == 1:
        return None, f"{BOOTSTRAP_NOTE} ({path.name} is schema 1, before the margins)"
    if schema != STAKES_SCHEMA:
        raise StakesFileError(f"{path} has schema {schema!r}; this engine reads {STAKES_SCHEMA}")
    if blob.get("season") != season:
        return None, f"{BOOTSTRAP_NOTE} ({path.name} is for {blob.get('season')!r}, not {season})"
    for k in ("week", "as_of", "teams"):
        if k not in blob:
            raise StakesFileError(f"{path} has no {k!r}")
    return blob, None


def _row(path, blob, manager, race, week):
    try:
        team = blob["teams"][manager]
    except KeyError:
        raise StakesFileError(f"{path}: no stakes for {manager}") from None
    row = (team.get(race) or {}).get(str(week))
    if row is None:
        raise idr.StakesError(f"{path} (as of {blob.get('as_of')}, week {blob.get('week')}) has no "
                              f"{race} row for {manager}, week {week}: the plan needs it")
    for k in ("margin_mean", "margin_sd"):
        if row.get(k) is None:
            raise StakesFileError(f"{path}: {manager} week {week} has no {k}")
    return row


def team_stakes(blob: dict, manager: str, window: int, *, last_regular: int, bracket: list,
                path="stakes.json") -> idr.TeamStakes:
    """One team's TeamStakes at a future window, from the file (s.4's
    matching: by week number, every week from the window through the last
    bracket week)."""
    if int(blob["week"]) > int(window):
        raise StakesFileError(f"{path} is from week {blob['week']}, after the window {window}")
    if not bracket:
        raise StakesFileError("the season has no bracket weeks: the stakes run through the final")
    weeks = {}
    for w in range(int(window), int(bracket[-1]) + 1):
        if w <= last_regular:
            r = _row(path, blob, manager, "regular_season", w)
            weeks[w] = idr.WeekStake(w, r.get("rs_leverage"), None, float(r["margin_mean"]),
                                     float(r["margin_sd"]))
        elif w in bracket:
            r = _row(path, blob, manager, "playoffs", w)
            weeks[w] = idr.WeekStake(w, None, r.get("playoff_leverage"), float(r["margin_mean"]),
                                     float(r["margin_sd"]))
        else:
            raise StakesFileError(f"week {w} is in neither the regular season nor the bracket")
    team = blob["teams"].get(manager) or {}
    for k in ("rs_title", "champion"):
        if k not in team:
            raise StakesFileError(f"{path}: {manager} has no {k}")
    return idr.TeamStakes(window_week=int(window), regular_season=int(window) <= last_regular,
                          rs_title=float(team["rs_title"]),
                          champion=None if team["champion"] is None else float(team["champion"]),
                          weeks=weeks, last_week=int(bracket[-1]))


def keep_chances(data, base_path, week: int) -> dict:
    """{manager: {name: keep chance (K = 5)}} from the live keeper watch."""
    from . import keepability_v3 as kv3
    kw = kv3.keeper_watch(data, max(1, int(week)), root=base_path)
    out = {}
    for p in kw["players"]:
        if p.get("keep_k5") is None:
            raise ValueError(f"the keeper watch has no keep chance for {p.get('player_name')}")
        out.setdefault(p["manager"], {})[p["player_name"]] = float(p["keep_k5"])
    return out


def team_games(data):
    """games(nba_team, week, from_day=None) -> his team's games that fantasy
    week, on or after from_day."""
    from .simulator_betting import schedule_week_dates, team_season_dates
    dates = team_season_dates(data)
    weeks = schedule_week_dates(data)
    cache = {}

    def games(team: str, week: int, from_day: date = None) -> int:
        k = (str(team).upper(), int(week), from_day)
        if k not in cache:
            days = weeks.get(int(week))
            if days is None:
                raise KeyError(f"week {week} is not in SCHEDULE.json")
            ds = set(days)
            cache[k] = sum(1 for d in dates.get(str(team).upper(), ())
                           if d in ds and (from_day is None or d >= from_day))
        return cache[k]
    return games


def availability(data):
    """share(projection) -> 1 - durability_miss_rate(his pre-season GP)."""
    from . import absence
    params = absence.baseline_params()
    prior = getattr(data, "durability_prior", None)

    def share(p) -> float:
        if getattr(p, "standin", False) or prior is None or not prior.source:
            gp = float(p.projected_gp)
        else:
            hit = prior.gp.get(p.player_name)
            gp = float(hit) if hit is not None else float(prior.median_gp)
        return 1.0 - absence.durability_miss_rate(gp, params)
    return share


def context(data, base_path, keep_week: int, keep=None):
    """The production roster_plan.DropContext: the config, and the stakes
    and keep chances read only when first asked for. keep: a stand-in for
    the keeper watch ({manager: {name: chance}}) -- fixtures only."""
    from .roster_plan import DropContext
    from .data_loader import regular_season_weeks_for, CURRENT_SEASON
    from .simulator_playoff_odds import bracket_weeks
    state = {}

    def load():
        if "blob" not in state:
            state["blob"], state["note"] = read_stakes(base_path)
        return state["blob"], state["note"]

    def note():
        return load()[1]

    def stakes(manager, window):
        blob, n = load()
        if blob is None:
            raise idr.StakesError(n)
        return team_stakes(blob, manager, window, last_regular=regular_season_weeks_for(CURRENT_SEASON),
                           bracket=bracket_weeks(), path=stakes_path(base_path))

    def keep_for(manager):
        if "keep" not in state:
            state["keep"] = keep if keep is not None else keep_chances(data, base_path, keep_week)
        if manager not in state["keep"]:
            raise KeyError(f"the keeper watch has no keep chances for {manager}")
        return state["keep"][manager]

    def games(team, week, from_day=None):
        if "games" not in state:
            state["games"] = team_games(data)
        return state["games"](team, week, from_day)

    def share(p):
        if "share" not in state:
            state["share"] = availability(data)
        return state["share"](p)

    # nothing above is read or computed until a decision asks for it
    return DropContext(config=idr.from_rules(), note=note, stakes=stakes, keep=keep_for,
                       games=games, availability=share)
