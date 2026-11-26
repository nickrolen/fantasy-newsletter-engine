"""
hub_v2/ranges.py -- 5d2 s.0: ONE source for every number that depends on a
team or a player over a range of days (claude/HANDOFF_5D2_SCHEDULE_MARKET_
PLAYERS_2026-11-21.md s.0; Nick's notes items 11-14).

Team > Schedule, Matchups' Next week, Players' Schedule group and Market's
range picker all read these numbers from here. A second calculation of the
same thing is a bug (5D_NOTES item 11, "One source of truth").

THE DAY (day_fill) -- the games grid's own rule, which used to live in three
copies (hub_state.build_grid_tab's fit, data.starters_on, roster.build's Next
starts) and now lives only here:
  who        Availability.grid_players(m, d): (sure, maybe, nba_out), IL
             slots excluded (an IL slot does not score, LEAGUE_RULES rule 5).
             "maybe" is a Q tag's next game (the grid's range, step 3b).
  the fill   schedule_strength.fill_daily_lineup_detail, i.e. lineup_fill.
             exact_fill -- the one exact daily fill advice (marginal_value)
             and the grid already use: the most starters, then the most
             projected points; players in roster order, weighted by Yahoo's
             projected FPPG (player info proj_fppg).
  lo / hi    lo counts the sure players, hi adds the maybes. Every count is
             (lo, hi); the page prints a range "3-4" only when they differ.
  count      players who will play that day (their games).
  starts     the fill's starters (never more than SEATS = 10).
  idle       count - starts: games by players who sit (5b's Idle, the same
             number: more than 10 with a game, or a position that can't seat).
  empty      SEATS - starts on a day with an NBA game; 0 on a day without.
             A count, never a day's name (Nick, 11-21).
  pts        the starters' projected FPPG, summed.
  light day  4 or fewer of the team's players have a game (hub.light_night_max,
             the games grid's meaning); 5 to 10 is no label.
  overflow   more than 10 have a game: someone with a game sits.

THE RANGE (Range, ranges): Nick's seven (item 14) -- Next week, Next 2 weeks,
Next 3 weeks, Rest of season (the regular season, through week 15), the
Semifinals (weeks 16-18), the Finals (19-21), the Cup (22-23). The stages'
weeks come from config postseason_format (required; a missing stage RAISES).
Relative ranges start at the JOIN WEEK: the first week a pickup made now
would play (hub_state.free_agent_columns' rule: this week before Monday's
window closes, the next week from the close, rule 7). A range under way
counts only its days from the join day (today, or the join week's Monday);
a range wholly before the join day is HIDDEN (not returned).

WHICH ROSTERS: this week's days use this week's Availability (rosters and IL
slots as they stand); every later day uses next week's (the ledger's pending
moves applied, hub_state.next_week_availability) -- the grid's own split. A
far range (the Semifinals in December) is priced on rosters as they will
stand next week: the page says so.

DISPLAY ONLY, as Availability is: the lines, title odds and advice keep the
simulators' availability (marginal_value's draws). Advice's lineup fill is
the same exact_fill; its starts are a simulated expectation, not these counts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Callable, Dict, List, Optional, Sequence, Tuple

DASH = "\u2014"
NDASH = "\u2013"


class RangeError(RuntimeError):
    """A range input is missing or inconsistent; the input is named."""


def _seats() -> int:
    from ..schedule_strength import MAX_STARTERS_PER_DAY
    return int(MAX_STARTERS_PER_DAY)


SEATS = _seats()


def rng(lo, hi, fmt=str) -> str:
    """A count, or "lo-hi" (en dash) when a Q's next game makes it uncertain."""
    return fmt(lo) if lo == hi else f"{fmt(lo)}{NDASH}{fmt(hi)}"


# =============================================================================
# the day
# =============================================================================

@dataclass(frozen=True)
class Day:
    d: date
    nba: int                       # NBA games that day, league-wide
    count: Tuple[int, int]         # players who will play (lo, hi)
    starts: Tuple[int, int]
    pts: Tuple[float, float]
    started: Tuple[str, ...]       # the hi fill's starters, in fill order
    sure_started: Tuple[str, ...]  # the lo fill's starters
    sure: Tuple[str, ...]
    maybe: Tuple[str, ...]
    nba_out: Tuple[str, ...]       # out that game on the NBA's injury report
    est: bool                      # counts a stand-in game the NBA hasn't scheduled
    kind: str                      # the grid's kind: off / over / light / normal

    @property
    def idle_s(self) -> Tuple[int, int]:
        """Idle in each scenario: (sure players only, every Q plays)."""
        return (self.count[0] - self.starts[0], self.count[1] - self.starts[1])

    @property
    def idle(self) -> Tuple[int, int]:
        a, b = self.idle_s
        return (min(a, b), max(a, b))

    @property
    def empty(self) -> Tuple[int, int]:
        if not self.nba:
            return (0, 0)
        return (SEATS - self.starts[1], SEATS - self.starts[0])

    @property
    def light(self) -> bool:
        """A LIGHT DAY (Nick, 11-21: the games grid's meaning): an NBA day on
        which 4 or fewer of the team's players have a game (config
        hub.light_night_max), counting a Q's next game (the high end)."""
        return self.kind == "light"

    @property
    def over(self) -> bool:
        """An OVERFLOW DAY (Nick, 11-21): more than 10 of the team's players
        have a game, so someone with a game sits (the high end). 5 to 10 is
        no label. Empty slots are counts, never a day's name."""
        return self.kind == "over"

    @property
    def sitting(self) -> Tuple[str, ...]:
        on = set(self.started)
        return tuple(n for n in self.sure + self.maybe if n not in on)


def fill(av, names: Sequence[str]) -> Tuple[List[str], float]:
    """(starters, their projected points) of one day's exact fill, players in
    the given order (ties in projection break by it)."""
    from ..schedule_strength import fill_daily_lineup_detail
    rows = []
    for p in names:
        inf = av.info[p]
        rows.append((p, set(inf["positions"]), float(inf.get("proj_fppg", 0.0))))
    st = fill_daily_lineup_detail(rows)[0]
    return st, sum(float(av.info[p].get("proj_fppg", 0.0)) for p in st)


def nba_games_on(team_dates: dict, d: date) -> int:
    return sum(1 for ds in team_dates.values() if d in ds) // 2


def day_fill(av, m: str, d: date, light_max: int, standins: dict = None, nba: int = None) -> Day:
    """One team's day (the module docstring). `av` is the Availability whose
    rosters count on d; light_max is config hub.light_night_max (the grid's
    "light" kind); standins {NBA team: {dates}} marks estimated days."""
    standins = standins or {}
    sure, maybe, nba_out = av.grid_players(m, d)
    s_lo, p_lo = fill(av, sure)
    s_hi, p_hi = fill(av, sure + maybe)
    lo, hi = len(sure), len(sure) + len(maybe)
    n = nba_games_on(av.team_dates, d) if nba is None else int(nba)
    if n == 0:
        kind = "off"
    elif hi > SEATS:
        kind = "over"
    elif hi <= int(light_max):
        kind = "light"
    else:
        kind = "normal"
    est = bool(standins) and any(d in standins.get(av.info[p]["nba_team"], ()) for p in sure + maybe)
    return Day(d=d, nba=n, count=(lo, hi), starts=(len(s_lo), len(s_hi)), pts=(p_lo, p_hi),
               started=tuple(s_hi), sure_started=tuple(s_lo), sure=tuple(sure), maybe=tuple(maybe),
               nba_out=tuple(nba_out), est=est, kind=kind)


# =============================================================================
# the ranges
# =============================================================================

RANGE_KEYS = ("next", "next2", "next3", "ros", "semis", "finals", "cup")
RANGE_LABEL = {"next": "Next week", "next2": "Next 2 weeks", "next3": "Next 3 weeks",
               "ros": "Rest of season", "semis": "Semifinals", "finals": "Finals", "cup": "Cup"}


@dataclass(frozen=True)
class Range:
    key: str
    label: str
    sub: str                      # "Week 7 (14 days)", "Weeks 16-18", "Week 18 (rest)"
    weeks: Tuple[int, ...]
    days: Tuple[date, ...]
    partial: bool                 # under way: counts only its days from the join day


def stage_weeks_cfg(league_config: dict = None) -> Dict[str, Tuple[int, int]]:
    """{"ros", "semis", "finals", "cup": (first, last)} from config
    postseason_format.stages (required). RAISES naming a missing piece."""
    if league_config is None:
        from ..data_loader import _LEAGUE_CONFIG as league_config
    st = (league_config.get("postseason_format") or {}).get("stages")
    if not isinstance(st, dict):
        raise RangeError("config postseason_format.stages is missing: the ranges' weeks cannot be read")

    def wk(x, what):
        if not (isinstance(x, list) and len(x) == 2 and all(isinstance(v, int) for v in x) and x[0] <= x[1]):
            raise RangeError(f"config postseason_format {what} weeks must be [first, last], got {x!r}")
        return (x[0], x[1])
    out = {"ros": wk((st.get("regular_season") or {}).get("weeks"), "stages.regular_season")}
    rounds = {str(r.get("name")): r for r in (st.get("playoffs") or {}).get("rounds") or []}
    for key, name in (("semis", "Semifinals"), ("finals", "Final")):
        if name not in rounds:
            raise RangeError(f"config postseason_format.stages.playoffs.rounds has no {name!r} round")
        out[key] = wk(rounds[name].get("weeks"), f"stages.playoffs.rounds[{name}]")
    out["cup"] = wk((st.get("cup") or {}).get("weeks"), "stages.cup")
    return out


def _sub(weeks: Sequence[int], wk_dates: dict, partial: bool) -> str:
    long = [w for w in weeks if len(wk_dates.get(w) or ()) > 7]
    if len(weeks) == 1:
        w = weeks[0]
        s = f"Week {w}"
        if w in long:
            s += f" ({len(wk_dates[w])} days)"
        return s + (" (rest)" if partial else "")
    s = f"Weeks {weeks[0]}{NDASH}{weeks[-1]}"
    if partial:
        s += " (rest)"
    if long:
        s += " \u00b7 " + ", ".join(f"wk {w} is {len(wk_dates[w])} days" for w in long)
    return s


def ranges(join_day: date, join_week: int, wk_dates: Dict[int, list],
           league_config: dict = None) -> List[Range]:
    """The seven ranges, in Nick's order, without the hidden ones. join_week:
    the first week a pickup made now plays (free_agent_columns' join);
    join_day: the first day counted (today when join_week is this week, else
    that week's Monday). wk_dates: {week: [its days]}."""
    if join_week not in wk_dates:
        return []
    last = max(wk_dates)
    sw = stage_weeks_cfg(league_config)
    spans = {"next": (join_week, join_week), "next2": (join_week, join_week + 1),
             "next3": (join_week, join_week + 2), "ros": (join_week, sw["ros"][1]),
             "semis": sw["semis"], "finals": sw["finals"], "cup": sw["cup"]}
    out = []
    for key in RANGE_KEYS:
        a, b = spans[key]
        a, b = max(a, join_week), min(b, last)
        if a > b:
            continue                                      # passed (or beyond the season): hidden
        weeks = tuple(range(a, b + 1))
        missing = [w for w in weeks if w not in wk_dates]
        if missing:
            raise RangeError(f"the range {key} needs weeks {missing}, not in config/SCHEDULE.json")
        days = tuple(d for w in weeks for d in wk_dates[w] if d >= join_day)
        if not days:
            continue
        partial = days[0] != wk_dates[weeks[0]][0]
        out.append(Range(key, RANGE_LABEL[key], _sub(weeks, wk_dates, partial), weeks, days, partial))
    return out


# =============================================================================
# the source
# =============================================================================

@dataclass
class TeamRange:
    days: int
    nba_days: int
    games: Tuple[int, int]
    starts: Tuple[int, int]
    idle: Tuple[int, int]
    empty: Tuple[int, int]
    pts: Tuple[float, float]
    light_days: int
    over_days: int

    def texts(self) -> dict:
        return {"games": rng(*self.games), "starts": rng(*self.starts), "idle": rng(*self.idle),
                "empty": rng(*self.empty), "pts": rng(round(self.pts[0]), round(self.pts[1]), _int),
                "light": str(self.light_days), "over": str(self.over_days), "days": str(self.days)}


def _int(x) -> str:
    return f"{int(x):,}"


class Source:
    """Every range-dependent number, from one place (the module docstring).
    av: this week's Availability; next_av: next week's (pending moves applied;
    may be av itself); week: this fantasy week; wk_dates {week: [days]};
    light_max: config hub.light_night_max; standins: the schedule's stand-ins."""

    def __init__(self, av, next_av, week: int, wk_dates: Dict[int, list], light_max: int,
                 standins: dict = None):
        if week not in wk_dates:
            raise RangeError(f"week {week} is not in config/SCHEDULE.json")
        self.av, self.next_av, self.week = av, next_av, int(week)
        self.wk_dates = {int(w): list(v) for w, v in wk_dates.items()}
        self.this_last = self.wk_dates[self.week][-1]
        self.light_max = int(light_max)
        self.standins = standins or {}
        self._day: Dict[tuple, Day] = {}
        self._nba: Dict[date, int] = {}
        self._base_hi: Dict[tuple, list] = {}

    def av_on(self, d: date):
        return self.av if d <= self.this_last else self.next_av

    def nba(self, d: date) -> int:
        if d not in self._nba:
            self._nba[d] = nba_games_on(self.av.team_dates, d)
        return self._nba[d]

    def week_of(self, d: date) -> int:
        for w, ds in self.wk_dates.items():
            if ds and ds[0] <= d <= ds[-1]:
                return w
        raise RangeError(f"{d} is in no fantasy week of config/SCHEDULE.json")

    def day(self, m: str, d: date) -> Day:
        k = (m, d)
        if k not in self._day:
            self._day[k] = day_fill(self.av_on(d), m, d, self.light_max, self.standins, self.nba(d))
        return self._day[k]

    def team(self, m: str, days: Sequence[date]) -> TeamRange:
        # sums by scenario (sure only / every Q plays), then lo-hi: the grid's
        # own rule, so a range never mixes one day's low end with another's high
        g0 = g1 = s0 = s1 = i0 = i1 = e0 = e1 = 0
        p0 = p1 = 0.0
        light = over = nd = 0
        for d in days:
            x = self.day(m, d)
            g0, g1 = g0 + x.count[0], g1 + x.count[1]
            s0, s1 = s0 + x.starts[0], s1 + x.starts[1]
            i0, i1 = i0 + x.idle_s[0], i1 + x.idle_s[1]
            e1, e0 = e1 + x.empty[0], e0 + x.empty[1]
            p0, p1 = p0 + x.pts[0], p1 + x.pts[1]
            light += x.light
            over += x.over
            nd += bool(x.nba)
        return TeamRange(len(days), nd, (g0, g1), (s0, s1), (min(i0, i1), max(i0, i1)), (e1, e0), (p0, p1),
                         light, over)

    def rosters(self, d: date) -> dict:
        return self.av_on(d).rosters

    def player_starts(self, m: str, days: Sequence[date]) -> Dict[str, int]:
        """{player: days he is in the hi fill} -- 4c2's Next starts, from the
        one fill."""
        out: Dict[str, int] = {}
        for d in days:
            for p in self.day(m, d).started:
                out[p] = out.get(p, 0) + 1
        return out

    def player_games(self, name: str, days: Sequence[date], av=None) -> int:
        """The days of `days` he will play (Availability.plays): a rostered
        player through the roster's Availability of each day, a free agent
        through `av` (the free agents' Availability)."""
        if av is not None:
            return len(av.playable(name, days))
        return sum(1 for d in days if self.av_on(d).plays(name, d))

    def empty_days(self, m: str, days: Sequence[date]) -> List[date]:
        """The days of `days` on which m has an empty slot even if every Q
        plays (the low end of empty > 0)."""
        return [d for d in days if self.day(m, d).empty[0] > 0]

    def games_on_empty(self, m: str, name: str, av, days: Sequence[date]) -> int:
        """Nick, 11-21 (the mock's fix): a free agent's games on days m has an
        empty slot -- not "starts for you", which counted games where he would
        only push out one of m's own starters and ignored the drop a pickup
        needs. Value to a team stays with Advice and Market."""
        return len(av.playable(name, self.empty_days(m, days)))


# =============================================================================
# Part B (Advice goals handoff; 5F_NOTES item 7): a move's starts, counted
# like Team > Schedule -- the same day_fill on a roster with the move applied
# =============================================================================

class _IL:
    def __init__(self, base, extra, out=()):
        self.base, self.extra, self.out = base, set(extra), set(out)

    def __contains__(self, n):
        return n not in self.out and (n in self.extra or n in self.base)


class Moved:
    """An Availability (`av`) with team `m`'s roster changed by advice's moves
    ({"add", "drop", "to_il", "activate"} dicts, in order): each activation
    out of its IL slot (the plan's activation step), each add in (his games and
    tags from `fa_av`, the free agents' Availability), each drop out, each IL
    placement into an IL slot (an IL slot does not score). Everything else is
    av's own, so day_fill counts it exactly as Team > Schedule does."""

    def __init__(self, av, fa_av, m: str, moves: Sequence[dict]):
        from ..hub_state import Availability
        self._av, self._fa = av, fa_av
        ros = list(av.rosters.get(m, []))
        adds, to_il, back = [], [], []
        for mv in moves:
            back += list(mv.get("activate") or [])
            if mv.get("drop") and mv["drop"] in ros:
                ros.remove(mv["drop"])
            if mv.get("to_il"):
                to_il.append(mv["to_il"])
            if mv.get("add") and mv["add"] not in ros:
                if fa_av is None or (fa_av.info.get(mv["add"]) or {}).get("nba_team") is None:
                    raise RangeError(f"{mv['add']} (an advice add) is not among the free agents' "
                                     "Availability: his games cannot be counted")
                ros.append(mv["add"])
                adds.append(mv["add"])
        self.rosters = {**av.rosters, m: ros}
        self.il = {**av.il, m: _IL(av.il.get(m) or {}, to_il, back)}
        # the info keeps the hub's name rules (PlayerIndex: an accent, a suffix, Yahoo's
        # initial): a roster's "Luka Doncic" is info's "Luka Don\u010di\u0107" (11-25: a plain
        # dict here raised KeyError on the real state)
        from ..data_loader import PlayerIndex
        self.info = PlayerIndex({**(dict(fa_av.info) if fa_av is not None else {}), **dict(av.info)})
        self.team_dates = av.team_dates
        self._adds = set(adds)
        self._grid = Availability.grid_players

    def grid_status(self, n, d):
        if n in self._adds:
            return self._fa.grid_status(n, d)
        return self._av.grid_status(n, d)

    def grid_players(self, manager, d):
        return self._grid(self, manager, d)


def _sig(mv: dict) -> tuple:
    return (mv.get("add"), mv.get("drop"), mv.get("to_il"), tuple(mv.get("activate") or ()))


def move_days(src: "Source", fa_av, m: str, earlier: Sequence[dict], move,
              days: Sequence[date], memo: dict = None) -> List[dict]:
    """AC1 (the Advice card around days): the move's effect on each of `days`,
    counted like Team > Schedule (the sure players' exact fill, day_fill), with
    `earlier` steps and the move (a dict, or a list of dicts applied together:
    an activation with its drops) against the earlier steps alone. Numbers only
    (advice_live makes the strings). Per day:
        {"d", "nba": NBA games that day, "n": his players who play (before the
         move: Team > Schedule's own count for step 1), "s": his starts before,
         "delta": starts after - before, "pts": the starters' projected points
         after - before (Team > Schedule's fill, each player's projection),
         "ins": [players the move brings in, who play that day],
         "outs": [players the move takes out, who would have played],
         "in_names" / "out_names": every player the move brings in / takes out
         ("drop_names": the dropped ones, without an IL placement),
         "full": no start changes while 10 or more of his already play and a
         player the move brings in plays (no room: his game adds no start;
         "pts" says whether he starts over someone)}
    memo: a dict shared across calls (one hub build) so a step priced under
    several goals is filled once per day."""
    memo = {} if memo is None else memo
    mvs = list(move) if isinstance(move, (list, tuple)) else [move]
    ins = [n for mv in mvs for n in (mv.get("activate") or [])] + [mv["add"] for mv in mvs if mv.get("add")]
    drops = [mv["drop"] for mv in mvs if mv.get("drop")]
    outs = drops + [mv["to_il"] for mv in mvs if mv.get("to_il")]
    e_sig = tuple(_sig(x) for x in earlier)
    m_sig = tuple(_sig(x) for x in mvs)
    moved = {}

    def _moved(av, steps, key):
        k = (id(av), key)
        if k not in moved:
            moved[k] = Moved(av, fa_av, m, steps)
        return moved[k]
    out = []
    for d in days:
        key = (m, e_sig, m_sig, d)
        if key in memo:
            out.append(memo[key])
            continue
        av = src.av_on(d)
        a = (day_fill(_moved(av, list(earlier), "a"), m, d, src.light_max, src.standins, src.nba(d))
             if earlier else src.day(m, d))
        b = day_fill(_moved(av, list(earlier) + mvs, "b"), m, d, src.light_max, src.standins, src.nba(d))
        delta = b.starts[0] - a.starts[0]
        ins_p = [n for n in ins if n in b.sure]
        outs_p = [n for n in outs if n in a.sure]
        full = delta == 0 and a.count[0] >= SEATS and bool(ins_p)
        x = {"d": d, "nba": a.nba, "n": a.count[0], "s": a.starts[0], "delta": delta,
             "pts": round(b.pts[0] - a.pts[0], 3), "ins": ins_p, "outs": outs_p,
             "in_names": list(ins), "drop_names": list(drops), "out_names": list(outs), "full": bool(full)}
        memo[key] = x
        out.append(x)
    return out


def move_starts(src: "Source", fa_av, m: str, earlier: Sequence[dict], move: dict,
                days: Sequence[date]) -> dict:
    """Part B: the move's starts on `days`, counted like Team > Schedule (the
    sure players' exact fill, day_fill): with `earlier` steps and the move,
    minus with the earlier steps alone. {"delta", "gained": [days], "lost":
    [days]}. One source with the AC1 strip (move_days)."""
    xs = move_days(src, fa_av, m, earlier, move, days)
    return {"delta": sum(x["delta"] for x in xs), "gained": [x["d"] for x in xs if x["delta"] > 0],
            "lost": [x["d"] for x in xs if x["delta"] < 0]}
