"""
week_state.py -- B1, the state of a fantasy week as of a date.

    week_state(data, week, as_of) -> WeekState

`as_of` means BANKED = every game strictly before it. Midnight on day D is
as_of = D. Everything here is read from the local daily logs, never Yahoo:

    PLAYERLOG.xlsx  one row per rostered player per day HIS TEAM PLAYED
                    (update_fantasy_logs.py writes no row otherwise);
                    fantasy_points, started, is_injured (= had a game and
                    scored 0: the log's DNP signal). The scoring source.
    LINEUPS.xlsx    one row per roster slot per day, game or not. The
                    COMPLETENESS source: a day the logs covered has rows
                    for every manager here.

THE TRAP (the project's signature bug)
--------------------------------------
A completed day with NBA games and no rows is indistinguishable from a day
everybody scored zero. PLAYERLOG alone cannot tell them apart -- it is
legitimately empty on a day no rostered player's team plays -- so the guard
reads LINEUPS: every completed day with NBA games must have LINEUPS rows for
every manager, or week_state RAISES MissingLogDay. allow_missing_days=True
turns that into a stated assumption, carried in WeekState.assumptions.
A day whose PLAYERLOG is partial (LINEUPS shows a starter with a game and
PLAYERLOG has no row for him) also raises. A day with LINEUPS but no
PLAYERLOG rows at all banks from LINEUPS and says so.

Names go through PlayerIndex: PLAYERLIST keeps Yahoo's spelling, the logs
strip accents.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

import pandas as pd

from . import absence
from .data_loader import MANAGERS, PlayerIndex, FantasyData


class MissingLogDay(RuntimeError):
    """A completed day with NBA games has no (or partial) log rows."""


class TagHistoryMissing(RuntimeError):
    """Mid-week, with no record of which tags existed at week start."""


@dataclass(frozen=True)
class WeekState:
    week: int
    as_of: date
    dates: tuple
    completed: tuple                 # week dates strictly before as_of
    remaining: tuple                 # week dates on or after as_of
    banked: dict                     # manager -> fantasy points started, before as_of
    banked_by_player: dict           # manager -> {player: points}
    games_remaining: dict            # player -> his team's games in `remaining`
    observed: dict                   # player -> {date: played} for completed days
    assumptions: tuple = ()
    state_hash: str = ""


def week_entry(data: FantasyData, week: int) -> dict:
    for w in data.schedule.get("weeks", []):
        if int(w["week"]) == int(week):
            return w
    raise KeyError(f"week {week} is not in SCHEDULE.json")


def week_for_date(data: FantasyData, d: date) -> int:
    """The fantasy week containing d. Raises outside every week."""
    for w in data.schedule.get("weeks", []):
        if date.fromisoformat(str(w["start_date"])[:10]) <= d <= date.fromisoformat(str(w["end_date"])[:10]):
            return int(w["week"])
    raise KeyError(f"{d} is in no fantasy week; pass --week")


def _dates(entry: dict) -> list:
    from .simulator_betting import get_dates_in_week
    return get_dates_in_week(entry)


def _iso(x) -> str:
    return str(x)[:10]


def _had_game(opp) -> bool:
    """LINEUPS writes nba_opponent "" on a day his team did not play."""
    if opp is None or (isinstance(opp, float) and pd.isna(opp)):
        return False
    return str(opp).strip().lower() not in ("", "nan", "none")


def week_state(
    data: FantasyData,
    week: int,
    as_of: date,
    team_projections: Optional[dict] = None,
    allow_missing_days: bool = False,
    managers=None,
) -> WeekState:
    from .simulator_betting import _playing_teams
    from .projections import load_all_team_projections

    managers = list(managers or MANAGERS)
    entry = week_entry(data, week)
    dates = _dates(entry)
    completed = tuple(d for d in dates if d < as_of)
    remaining = tuple(d for d in dates if d >= as_of)
    if team_projections is None:
        team_projections = load_all_team_projections(data)
    roster = PlayerIndex({n: n for tp in team_projections.values() for n in tp.players})

    def canon(name):
        return roster.canonical(name) or str(name)

    done = {d.isoformat() for d in completed}
    pl = data.playerlog
    lu = data.lineups
    pl = pl[pl["date"].astype(str).str[:10].isin(done)] if len(pl) else pl
    lu = lu[lu["date"].astype(str).str[:10].isin(done)] if len(lu) else lu
    for name, df in (("PLAYERLOG", pl), ("LINEUPS", lu)):
        if len(df) and (pd.to_numeric(df["week"], errors="coerce") != week).any():
            bad = sorted(set(df.loc[pd.to_numeric(df["week"], errors="coerce") != week, "date"].astype(str)))
            raise MissingLogDay(f"{name} rows dated inside week {week} carry another week number: {bad}")

    assumptions = []
    banked = {m: 0.0 for m in managers}
    by_player = {m: {} for m in managers}
    observed: dict = {}

    for d in completed:
        iso = d.isoformat()
        nba_games = bool(_playing_teams(data, d))
        pl_d = pl[pl["date"].astype(str).str[:10] == iso] if len(pl) else pl
        lu_d = lu[lu["date"].astype(str).str[:10] == iso] if len(lu) else lu
        if not nba_games and not len(pl_d):
            continue
        present = set(lu_d["manager"]) if len(lu_d) else set()
        missing = [m for m in managers if m not in present]
        if missing:
            msg = (f"{iso} had NBA games but LINEUPS has no rows for {', '.join(missing)}: "
                   f"the daily log has not appended (run update_fantasy_logs.py --date {iso})")
            if not allow_missing_days:
                raise MissingLogDay(msg + ". Refusing to bank zero; --allow-missing-days to override.")
            assumptions.append(f"ASSUMED: {msg}; counted no points for them that "
                               "day (--allow-missing-days).")

        # starters with a game, per LINEUPS -- PLAYERLOG must have each of them
        lu_started = lu_d[~lu_d["slot"].astype(str).str.upper().isin(["BN", "IL", "IL+", "", "NAN", "NONE"])] if len(lu_d) else lu_d
        lu_started = lu_started[lu_started["nba_opponent"].map(_had_game)] if len(lu_started) else lu_started
        want = {(r.manager, canon(r.player_name)) for r in lu_started.itertuples()}
        if len(pl_d):
            have = {(r.manager, canon(r.player_name)) for r in pl_d.itertuples()}
            gap = sorted(want - have)
            if gap:
                raise MissingLogDay(f"{iso}: PLAYERLOG is partial -- LINEUPS starts {gap} "
                                    f"with a game and PLAYERLOG has no row. Re-run the log for {iso}.")
            for r in pl_d.itertuples():
                name = canon(r.player_name)
                observed.setdefault(name, {})[d] = not bool(r.is_injured)
                if bool(r.started) and r.manager in banked:
                    fp = float(r.fantasy_points)
                    banked[r.manager] += fp
                    by_player[r.manager][name] = by_player[r.manager].get(name, 0.0) + fp
        elif len(want):
            assumptions.append(f"{iso}: PLAYERLOG has no rows; the day's points come "
                               "from LINEUPS slots.")
            for r in lu_started.itertuples():
                name = canon(r.player_name)
                fp = pd.to_numeric(r.fantasy_points, errors="coerce")
                fp = 0.0 if pd.isna(fp) else float(fp)
                observed.setdefault(name, {})[d] = fp != 0.0
                if r.manager in banked:
                    banked[r.manager] += fp
                    by_player[r.manager][name] = by_player[r.manager].get(name, 0.0) + fp

    games_remaining = {}
    for tp in team_projections.values():
        for name, p in tp.players.items():
            games_remaining[name] = sum(1 for d in remaining
                                        if str(p.nba_team).upper() in _playing_teams(data, d))

    payload = {
        "week": week, "as_of": as_of.isoformat(),
        "completed": [d.isoformat() for d in completed],
        "remaining": [d.isoformat() for d in remaining],
        "banked": {m: repr(v) for m, v in sorted(banked.items())},
        "by_player": {m: {p: repr(v) for p, v in sorted(ps.items())} for m, ps in sorted(by_player.items())},
        "games_remaining": dict(sorted(games_remaining.items())),
        "observed": {p: {d.isoformat(): v for d, v in sorted(o.items())} for p, o in sorted(observed.items())},
        "assumptions": assumptions,
    }
    h = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:16]
    return WeekState(week=week, as_of=as_of, dates=tuple(dates), completed=completed,
                     remaining=remaining, banked=banked, banked_by_player=by_player,
                     games_remaining=games_remaining, observed=observed,
                     assumptions=tuple(assumptions), state_hash=h)


# =============================================================================
# Mid-week tags
# =============================================================================

def reconcile_tags(previous: Optional[dict], live: dict, as_of: date, week_start: date,
                   assume_since_week_start: bool = False) -> tuple[dict, list, list]:
    """(anchors, events, assumptions) for the live chain tags.

    previous: {player: {"tag": str, "anchor": "YYYY-MM-DD"}} from the last
    refresh this week, or None if there was none.

      unchanged chain tag   keeps its ORIGINAL anchor -- re-anchoring would
                            charge games he already sat a second time;
      new or changed tag    re-anchored at as_of: a fresh tag supersedes;
      tag gone              cleared (no chain).

    With no previous record: at the week's start every tag is anchored there
    (the baseline); mid-week that is unknowable, so it RAISES unless
    assume_since_week_start, which is then stated as an assumption.
    """
    assumptions = []
    live_chain = {}
    for name, raw in (live or {}).items():
        tag = absence.chain_tag(raw)
        if tag is not None:
            live_chain[name] = (tag, str(raw))
    anchors, events = {}, []
    if previous is None:
        if as_of > week_start and live_chain and not assume_since_week_start:
            raise TagHistoryMissing(
                f"no tag record for this week and as_of {as_of} is after its start {week_start}: "
                "cannot tell a tag from Monday (keep its anchor) from a fresh one (re-anchor). "
                "Run the refresh on the week's first day, or pass --assume-tags-since-week-start.")
        kind = "baseline" if as_of <= week_start else "assumed since week start"
        if as_of > week_start and live_chain:
            assumptions.append(f"ASSUMED: every live tag existed since {week_start} "
                               "(--assume-tags-since-week-start).")
        for name, (tag, raw) in sorted(live_chain.items()):
            anchors[name] = week_start
            events.append({"player": name, "tag": raw, "event": kind, "anchor": week_start.isoformat()})
        return anchors, events, assumptions
    prev = PlayerIndex({n: v for n, v in previous.items()})
    for name, (tag, raw) in sorted(live_chain.items()):
        old = prev.get(name)
        if old is not None and absence.chain_tag(old["tag"]) == tag:
            anchors[name] = date.fromisoformat(old["anchor"])
            events.append({"player": name, "tag": raw, "event": "unchanged: kept anchor",
                           "anchor": old["anchor"]})
        else:
            anchors[name] = as_of
            what = "new tag" if old is None else f"changed {old['tag']} -> {raw}"
            events.append({"player": name, "tag": raw, "event": f"{what}: re-anchored",
                           "anchor": as_of.isoformat()})
    live_idx = PlayerIndex({n: n for n in live_chain})
    for name, old in sorted(previous.items()):
        if name not in live_idx:
            events.append({"player": name, "tag": old["tag"], "event": "cleared", "anchor": None})
    return anchors, events, assumptions


def tag_record(anchors: dict, live: dict) -> dict:
    """What to store for the next refresh: {player: {tag, anchor}}."""
    return {n: {"tag": str(live[n]), "anchor": a.isoformat()} for n, a in sorted(anchors.items())}
