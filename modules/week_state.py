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

    KNOWN LIMITATION, CONSIDERED AND LEFT (Nick, 10-22): every new or changed
    tag gets a new anchor, and a cleared-then-returned tag counts as new. A
    chronic case -- a player who picks up a Q most mornings and plays anyway
    (Embiid) -- is therefore re-anchored again and again, and each fresh
    anchor restarts his chain at as_of. Not handled now, deliberately: it
    needs a rule for when a returning tag is "the same" absence, and nobody
    has written one. The per-week tag log (append_tag_log) keeps the history
    that would let such a rule be measured.
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


# =============================================================================
# B3: the line's cache key, and the tag log
# =============================================================================
#
# state_hash is a fingerprint of the week's PLAYED state -- the logs as of a
# date -- and stays exactly that. A cache keyed on it alone would serve a
# stale line after precisely the changes a refresh exists to catch: a fresh
# tag (tags are not in the state at all), a PLAYERLIST refresh (games
# remaining depend on a player's NBA team, not his projection), an
# INJURY_OVERRIDES edit, a new seed, an engine change. line_cache_key names
# every input to the line explicitly instead.

def _sha(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()[:16]


def projections_fingerprint(team_projections: dict) -> str:
    """Every field of every PlayerProjection the line was simulated from --
    roster membership, NBA team, positions, projected and actual FPPG/GP and
    spread, and the override fields load_all_team_projections copies onto
    them -- plus each team's weekly spread. config/PROJECTION_OVERRIDES.json
    reaches the line only through PLAYERLIST (fetch_playerlist applies it),
    so it is covered here, by what it changed, and only once it has."""
    from dataclasses import asdict
    out = {}
    for m, tp in sorted(team_projections.items()):
        out[m] = {"weekly_std_dev": repr(float(tp.weekly_std_dev)),
                  "players": {n: asdict(p) for n, p in sorted(tp.players.items())}}
    return _sha(out)


def tags_fingerprint(live: dict, anchors: dict) -> str:
    """The tags the line was priced on, raw, and the anchor each chain tag
    was given -- the tag record plus the non-chain statuses that still reach
    the simulator."""
    return _sha({"live": {str(n): str(t) for n, t in sorted((live or {}).items())},
                 "anchors": {str(n): a.isoformat() for n, a in sorted((anchors or {}).items())}})


def governing_overrides(data: FantasyData, week: int, week_dates, team_projections: dict) -> list:
    """The INJURY_OVERRIDES entries that govern a rostered player this week
    (absence.override_governs -- the rule the simulator applies), whole.
    Whole, not a per-manager yes/no: moving a return_week inside a governing
    entry changes the line without changing whether it governs."""
    names = PlayerIndex({n: n for tp in team_projections.values() for n in tp.players})
    out = []
    for entry in (data.injury_overrides or {}).get("players") or []:
        if names.get(entry.get("player_name", "")) is None:
            continue
        if absence.override_governs(week, week_dates, entry.get("out_weeks") or (),
                                    entry.get("return_week"),
                                    absence.parse_out_from(entry.get("out_from"))):
            out.append(entry)
    return sorted(out, key=lambda e: json.dumps(e, sort_keys=True, default=str))


def schedule_fingerprint(data: FantasyData, week_entry_: dict) -> str:
    """The fantasy week (its dates and matchups) and the NBA schedule. Neither
    is in state_hash beyond per-player game COUNTS: a postponed game that moves
    a day changes the daily lineup fill without changing a count, and the
    matchups decide which totals a line compares."""
    games = sorted((str(g.get("date"))[:10], str(g.get("home")), str(g.get("away")))
                   for g in (data.nba_schedule or {}).get("games", []))
    return _sha({"week": {k: week_entry_.get(k) for k in ("week", "start_date", "end_date", "matchups")},
                 "nba_games": games})


def line_cache_key(*, state_hash: str, tags: str, projections: str, overrides: list,
                   schedule: str, assumptions, seed: int, num_simulations: int,
                   engine: dict, il: dict = None) -> dict:
    """{"key": str, "parts": {...}, "cacheable": bool, "why_not": str|None}.

    parts: state_hash (the played state), tags, projections, overrides (the
    governing INJURY_OVERRIDES entries), schedule, assumptions (every
    override flag a refresh records), seed, num_simulations, engine (E1's
    calibration_log.engine_version: commit + dirtiness over engine_paths).

    A dirty or unknown engine is NOT cacheable: the commit does not identify
    the code, so two different uncommitted simulators would share a key.
    Such a run always recomputes; it never serves a cached line."""
    engine = dict(engine or {})
    parts = {"state_hash": state_hash, "tags": tags, "projections": projections,
             "overrides": _sha(overrides or []), "schedule": schedule,
             "assumptions": _sha(sorted(str(a) for a in (assumptions or ()))),
             "il": _sha(il or {}),
             "seed": int(seed), "num_simulations": int(num_simulations),
             "engine_commit": engine.get("commit"), "engine_dirty": engine.get("dirty")}
    why_not = None
    if not engine.get("commit"):
        why_not = "engine commit unknown (git could not say)"
    elif engine.get("dirty") is None:
        why_not = "engine dirtiness unknown (git could not say)"
    elif engine.get("dirty"):
        why_not = f"engine {engine.get('commit')}-dirty: the commit does not identify the code"
    return {"key": _sha(parts), "parts": parts, "cacheable": why_not is None, "why_not": why_not}


def tag_log_path(out_dir, week: int):
    from pathlib import Path
    return Path(out_dir) / f"live_lines_week{week}.tag_log.jsonl"


def append_tag_log(out_dir, week: int, *, as_of: date, generated_at: str, produced_by: str,
                   seed: int, state_hash: str, events: list) -> int:
    """Append one refresh's tag events to the week's log, one JSON line per
    event with the refresh it came from. The week's state file keeps only the
    live anchors (a cleared tag is deleted from it, correctly) and the line's
    own tag_events are overwritten each refresh; this is what still says,
    a week later, why the line moved. Returns the number of lines added."""
    path = tag_log_path(out_dir, week)
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [json.dumps({"as_of": as_of.isoformat(), "generated_at": generated_at,
                        "produced_by": produced_by, "seed": seed, "state_hash": state_hash,
                        **e}, sort_keys=True, default=str) for e in events]
    if rows:
        with open(path, "a", encoding="utf-8") as f:
            f.write("\n".join(rows) + "\n")
    return len(rows)


def read_tag_log(out_dir, week: int) -> list:
    path = tag_log_path(out_dir, week)
    if not path.exists():
        return []
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]
