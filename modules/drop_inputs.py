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
  - THE LEVERAGE A WEEK IS PRICED WITH is the file's CAUSAL one
    (rs_leverage_causal / playoff_leverage_causal, schema 3: title_odds_run's
    near-tie estimate), mapped to WeekStake.rs_leverage / playoff_leverage.
    The all-iteration *_all leverage in the file is never read here. A row
    without the causal key RAISES; a null causal leverage (too few near ties,
    recorded in causal_why) is a null leverage: worth 0 per point.
  - THE BOOTSTRAP (Nick, 11-04; HANDOFF_18B_REFIT_AND_WIRE s.2), the one
    exception to raise-don't-default: a file that is MISSING, from ANOTHER
    SEASON, or SCHEMA 1 OR 2 (before the causal leverage, 11-12) cannot be
    used yet. Schema 2 joins schema 1 here rather than raising because a
    raise would deadlock the deploy: the run whose roster plan needs a
    decision is the run that writes the schema-3 file. The advice, which
    cannot price without stakes, raises with this note (advice_live). The run then plans with no
    injured drops (the plan's behaviour before 18b), records the note "no
    stakes yet: planned without injured drops (...)", and goes on to write
    the file; the next run uses it. Anything else wrong with a file that
    exists -- unreadable JSON, an unknown schema, a missing field or row --
    RAISES.

THE ONE ACTIVATION RULE (44a, roster_plan.activation_drops) reads the keep
chances below and the long-run value; its weeks end at the season's last
bracket week (longrun_last), never at a stakes file.

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
    if schema == 2:
        return None, (f"{BOOTSTRAP_NOTE} ({path.name} is schema 2, before the causal leverage: "
                      f"the next run rewrites it as schema {STAKES_SCHEMA})")
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
    key = ("rs" if race == "regular_season" else "playoff") + "_leverage_causal"
    if key not in row:
        raise StakesFileError(f"{path}: {manager} week {week} has no {key} (schema {blob.get('schema')}): "
                              "a point is priced only with the causal leverage")
    lev = row[key]
    if lev is not None and not (-1.0 <= float(lev) <= 1.0):
        raise StakesFileError(f"{path}: {manager} week {week}: {key} {lev!r} is not a difference of probabilities")
    return row


def team_stakes(blob: dict, manager: str, window: int, *, last_regular: int, bracket: list,
                path="stakes.json") -> idr.TeamStakes:
    """One team's TeamStakes at a future window, from the file (s.4's
    matching: by week number, every week from the window through the last
    bracket week)."""
    from .title_odds_run import STAKES_SCHEMA
    if blob.get("schema") != STAKES_SCHEMA:
        raise StakesFileError(f"{path} is schema {blob.get('schema')!r}; prices need schema {STAKES_SCHEMA} "
                              "(the causal leverage): read it through read_stakes")
    if int(blob["week"]) > int(window):
        raise StakesFileError(f"{path} is from week {blob['week']}, after the window {window}")
    if not bracket:
        raise StakesFileError("the season has no bracket weeks: the stakes run through the final")
    weeks = {}
    for w in range(int(window), int(bracket[-1]) + 1):
        if w <= last_regular:
            r = _row(path, blob, manager, "regular_season", w)
            weeks[w] = idr.WeekStake(w, r["rs_leverage_causal"], None, float(r["margin_mean"]),
                                     float(r["margin_sd"]))
        elif w in bracket:
            r = _row(path, blob, manager, "playoffs", w)
            weeks[w] = idr.WeekStake(w, None, r["playoff_leverage_causal"], float(r["margin_mean"]),
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
    """{manager: {name: keep chance (K = 5)}} from the live keeper watch.
    Cached on `data` by (base path, week): one run's plans (the line's, the
    season pass's, advice's) read it once (44a: every IL return over 15 reads
    it). A copy is returned, so no caller can change another's."""
    from . import keepability_v3 as kv3
    cache = data.__dict__.setdefault("_keep_chances", {}) if hasattr(data, "__dict__") else {}
    key = (str(Path(base_path).resolve()), max(1, int(week)))
    if key not in cache:
        kw = kv3.keeper_watch(data, max(1, int(week)), root=base_path)
        out = {}
        for p in kw["players"]:
            if p.get("keep_k5") is None:
                raise ValueError(f"the keeper watch has no keep chance for {p.get('player_name')}")
            out.setdefault(p["manager"], {})[p["player_name"]] = float(p["keep_k5"])
        cache[key] = out
    return {m: dict(v) for m, v in cache[key].items()}


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
        # 44b s.3: a keeper-watch failure is KeeperWatchFailed (once per run: the
        # failure is kept), and the plan's activation rule falls back on it, loudly
        from .roster_plan import KeeperWatchFailed
        if "keep_error" in state:
            raise KeeperWatchFailed(state["keep_error"])
        if "keep" not in state:
            try:
                state["keep"] = keep if keep is not None else keep_chances(data, base_path, keep_week)
            except Exception as e:                       # noqa: BLE001 -- recorded, raised as one type
                state["keep_error"] = f"{type(e).__name__}: {e}".splitlines()[0][:300]
                raise KeeperWatchFailed(state["keep_error"]) from e
        if manager not in state["keep"]:
            raise KeyError(f"the keeper watch has no keep chances for {manager}")
        return state["keep"][manager]

    def little(manager, window):
        """44b s.6: injured_drop.little_left at `window` from the stakes file's
        team chances (rs_title, champion). None only for THE BOOTSTRAP (no
        usable stakes file: missing, another season, schema 1 or 2), the one
        stated exception above: a raise there would stop the run that writes
        the file, as it would for the decisions (44c kept it; the top 4 are
        protected, as before 44b). A file without this manager RAISES."""
        blob, n = load()
        if blob is None:
            return None
        team = (blob.get("teams") or {}).get(manager)
        if team is None:
            raise StakesFileError(f"{stakes_path(base_path)}: no stakes for {manager}")
        last_reg = regular_season_weeks_for(CURRENT_SEASON)
        ts = idr.TeamStakes(window_week=int(window), regular_season=int(window) <= last_reg,
                            rs_title=float(team["rs_title"]),
                            champion=None if team.get("champion") is None else float(team["champion"]),
                            weeks={}, last_week=int(bracket_weeks()[-1]))
        return idr.little_left(ts, idr.from_rules())

    def games(team, week, from_day=None):
        if "games" not in state:
            state["games"] = team_games(data)
        return state["games"](team, week, from_day)

    def share(p):
        if "share" not in state:
            state["share"] = availability(data)
        return state["share"](p)

    # nothing above is read or computed until a decision asks for it. longrun_last: the
    # one activation rule's long-run value runs through the season's last bracket week --
    # every stakes file's last_week (team_stakes) -- so an IL return reads no stakes file
    # (44a); the long-run value itself (roster_plan.LongRun) is attached by roster_plan.for_run
    return DropContext(config=idr.from_rules(), note=note, stakes=stakes, keep=keep_for,
                       games=games, availability=share, longrun_last=int(bracket_weeks()[-1]),
                       little_left=little)
