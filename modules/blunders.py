"""
blunders.py -- the one definition of a lineup blunder (Nick, 11-09;
claude/HANDOFF_MONDAY_FIXES_2026-11-09.md, F2).

WHAT A BLUNDER IS
    On each day:
        blunders = the most starters achievable from the players who played
                 - the starters who played
    with the exact fill (modules/lineup_fill: a maximum matching), so a
    blunder that needs a reshuffle counts. Nick's week 3, Fri 11-06: Jalen
    Johnson started at PF and did not play; Derrick White (PG,SG) sat on the
    bench and scored 38.00. White cannot fill PF, but Brown PF / Daniels SF /
    White SG starts all ten who played: 1 blunder, 38.00. The greedy this
    replaces (a bench player straight into an open seat) missed it.

PLAYED (as update_leaguehistory has always read it)
    - IL and IL+ slots never count, on either side.
    - A starter holds his seat if he appeared: a game, not injured. Yahoo's
      DNP rows are is_injured with 0 FP. A starter who played for 0 or fewer
      points still held his seat (25 such starter-days in nine seasons):
      benching him is a swap question, Section 6's, not a blunder.
    - A bench player is a blunder candidate if he appeared and scored > 0.

WHICH BENCH PLAYERS, AND THE POINTS
    The day's real seating of the starters who played is the start
    (lineup_fill.exact_fill's `start`); the bench candidates are added by the
    same greedy, highest points first, each by an augmenting path (a
    reshuffle of starters). That is the largest lineup that keeps every
    starter who played and, among those, the one with the most points. So:
        count  = the most starters achievable - the starters who played
        points = the bench players added
               = the best total achievable without benching a starter who
                 played, minus the actual total.
    Not the unrestricted best total: that folds in swap gains (a bench player
    outscoring a starter who played), which the what-if counts as swaps and
    adds to the potential gain separately; blunder points are pure gain.

    Each blunder names the open seat its reshuffle reaches (the starter there
    who did not play, or EMPTY) and the moves on the way, e.g. White at SG
    via Daniels SG->SF, Brown SF->PF into Johnson's PF.

THE CALLERS (every count of blunders; pinned by tests/test_blunders.py)
    scripts/update_leaguehistory.py   the weekly count into LEAGUEHISTORY
    modules/what_if_analyzer.py       Section 6, the report card's lineup
                                      cost, the blunder names; its counts are
                                      what records_tracker.update_cumulative_
                                      blunders adds into RECORDS
    scripts/recompute_blunders.py     the stored history, recomputed
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Iterable, Optional

from . import lineup_fill

BASE_POSITIONS = frozenset({"PG", "SG", "SF", "PF", "C"})
IL_SLOTS = frozenset({"IL", "IL+"})
BENCH = "BN"
_SEAT_NAMES = {name.upper(): name for name, _elig in lineup_fill.SEATS}


class BlunderInputError(ValueError):
    """A lineup the blunder count cannot read. Never defaulted."""


@dataclass(frozen=True)
class Row:
    """One rostered player on one day."""
    name: str
    slot: str                   # PG SG G SF PF F C Util, BN, IL, IL+
    positions: frozenset
    fp: Optional[float]         # None: no game (or injured: no points that count)
    appeared: bool              # a game, not injured


@dataclass(frozen=True)
class Blunder:
    date: str
    bench_player: str
    bench_player_fp: float
    available_slot: str         # the open seat the reshuffle reaches
    dnp_starter: str            # who sat there and did not play, or "EMPTY"
    moves: tuple = ()           # ((starter, from slot, to slot), ...)

    def to_dict(self) -> dict:
        return {"date": self.date, "bench_player": self.bench_player,
                "bench_player_fp": self.bench_player_fp, "available_slot": self.available_slot,
                "dnp_starter": self.dnp_starter,
                "moves": [{"player": p, "from": a, "to": b} for p, a, b in self.moves]}

    def reshuffle_text(self) -> str:
        return ", ".join(f"{p} {a}->{b}" for p, a, b in self.moves)


@dataclass
class Day:
    date: str
    blunders: list = field(default_factory=list)
    stale_positions: list = field(default_factory=list)   # starters seated outside their listing

    @property
    def count(self) -> int:
        return len(self.blunders)

    @property
    def points(self) -> float:
        return round(sum(b.bench_player_fp for b in self.blunders), 2)


# =============================================================================
# reading rows
# =============================================================================

def parse_positions(value) -> frozenset:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return frozenset()
    return frozenset(p.strip().upper() for p in str(value).split(",")) & BASE_POSITIONS


def norm_slot(slot) -> str:
    s = str(slot).strip().upper()
    if s in IL_SLOTS or s == BENCH:
        return s
    if s in _SEAT_NAMES:
        return _SEAT_NAMES[s]
    raise BlunderInputError(f"unknown lineup slot {slot!r}")


def _fp(value, who, date) -> float:
    try:
        x = float(value)
    except (TypeError, ValueError):
        raise BlunderInputError(f"{date} {who}: fantasy points {value!r} is not a number") from None
    if math.isnan(x):
        raise BlunderInputError(f"{date} {who}: fantasy points missing on a game row")
    return x


def rows_from_frames(lineups_day, playerlog_day) -> list:
    """One manager-day from LINEUPS and PLAYERLOG rows (the current season's
    files). A player appeared if PLAYERLOG has a row for him not marked
    injured; his points are that row's."""
    date = str(lineups_day.iloc[0]["date"])[:10] if len(lineups_day) else "?"
    played = {}
    for _, r in playerlog_day.iterrows():
        inj = r.get("is_injured", False)
        if isinstance(inj, float) and math.isnan(inj):
            inj = False
        if not bool(inj):
            played[r["player_name"]] = _fp(r.get("fantasy_points"), r["player_name"], date)
    rows = []
    for _, r in lineups_day.iterrows():
        name = r["player_name"]
        fp = played.get(name)
        rows.append(Row(name=name, slot=norm_slot(r["slot"]), positions=parse_positions(r.get("positions")),
                        fp=fp, appeared=fp is not None))
    return rows


def rows_from_history(records: Iterable[dict]) -> list:
    """One manager-day from data/historical/HISTORICAL_PLAYERLOG.json rows."""
    rows = []
    for r in records:
        appeared = bool(r["had_game"]) and not bool(r["is_injured"])
        rows.append(Row(name=r["player_name"], slot=norm_slot(r["slot"]),
                        positions=parse_positions(r.get("positions")),
                        fp=_fp(r["fantasy_points"], r["player_name"], r["date"]) if appeared else None,
                        appeared=appeared))
    return rows


# =============================================================================
# the count
# =============================================================================

def day(date: str, rows: Iterable[Row]) -> Day:
    """The day's blunders (see the module docstring)."""
    rows = list(rows)
    seats = lineup_fill.SEATS
    free = {}
    for si, (name, _elig) in enumerate(seats):
        free.setdefault(name, []).append(si)
    players, start, stale = [], {}, []
    for r in rows:
        if r.slot in IL_SLOTS or r.slot == BENCH or not r.appeared:
            continue
        if not free.get(r.slot):
            raise BlunderInputError(f"{date}: more starters who played at {r.slot} than the "
                                    "lineup has seats")
        si = free[r.slot].pop(0)
        pos = r.positions
        if not (pos & seats[si][1]):
            # Yahoo seated him there, so he was eligible: the listing is stale
            pos = pos | seats[si][1]
            stale.append(r.name)
        players.append((("S", r.name), pos, 0.0))
        start[si] = len(players) - 1
    # who sat in each open seat and did not play (a label only)
    dnp_at = {}
    for r in rows:
        if r.slot not in IL_SLOTS and r.slot != BENCH and not r.appeared and free.get(r.slot):
            dnp_at[free[r.slot].pop(0)] = r.name
    for r in rows:
        if r.slot == BENCH and r.appeared and r.fp is not None and r.fp > 0:
            players.append((("B", r.name), r.positions, float(r.fp)))
    fp_of = {r.name: r.fp for r in rows if r.slot == BENCH}
    started, _benched, assign = lineup_fill.exact_fill(players, seats, start)
    final = {key: si for si, key in assign.items()}
    blunders = []
    for key in started:
        if key[0] != "B":
            continue
        s, moves = final[key], []
        while s in start:
            t = players[start[s]][0]
            s2 = final[t]
            if seats[s][0] != seats[s2][0]:
                moves.append((t[1], seats[s][0], seats[s2][0]))
            s = s2
        blunders.append(Blunder(date=date, bench_player=key[1], bench_player_fp=float(fp_of[key[1]]),
                                available_slot=seats[s][0], dnp_starter=dnp_at.get(s, "EMPTY"),
                                moves=tuple(moves)))
    return Day(date=date, blunders=blunders, stale_positions=stale)


def week_from_frames(lineups, playerlog) -> dict:
    """{manager: [Day, ...]} for already-filtered LINEUPS / PLAYERLOG frames
    (one season, one week), by date."""
    out = {}
    if lineups is None or lineups.empty:
        return out
    lu = lineups.assign(_d=lineups["date"].astype(str).str[:10],
                        _m=lineups["manager"].astype(str).str.strip())
    pl = playerlog.assign(_d=playerlog["date"].astype(str).str[:10],
                          _m=playerlog["manager"].astype(str).str.strip())
    for (m, d), lu_day in lu.groupby(["_m", "_d"], sort=True):
        pl_day = pl[(pl["_m"] == m) & (pl["_d"] == d)]
        out.setdefault(m, []).append(day(d, rows_from_frames(lu_day, pl_day)))
    return out


def counts(week_days: dict) -> dict:
    """{manager: blunders} for managers with any (update_leaguehistory's shape)."""
    return {m: sum(d.count for d in days) for m, days in week_days.items()
            if sum(d.count for d in days) > 0}
