"""
advice_v2.py -- advice v2's engine: adds and drops, as Monday moves and chat moves.

claude/ADVICE_V2_DESIGN.md decisions 1-4 and 7; V1 (the calibration) is
claude/ADVICE_V1_RESULT_2026-11-05.md, V2 (live, on the ledger) is
claude/HANDOFF_ADVICE_V2_2026-11-11.md. The live inputs are built by
modules/advice_live.py, which is the only caller that reads files.

    horizon_for(now, week, week_dates, close) -> Horizon (Monday move | chat move)
    recommend(inputs, manager, settings, weighting) -> Recommendation
    advise_all(inputs, settings, weighting) -> {manager: Advice}  (contested, backups)

PURE. Nothing here opens a file (RETRO_SIM_REQUIREMENTS R2; a source test pins
it): the caller passes the world, the rosters, the projections, the tags and
the stakes. The 2025-26 replay (modules/advice_replay.py) and the live
2026-27 path build the same MondayInputs from different sources.

THE TWO HORIZONS (V2 s.2), decided by the build's clock against this week's
Monday window close (price_lock.window_close), never by weekday name -- the
same switch as hub_state.free_agent_columns:
    before the close   the MONDAY MOVE: a Yahoo move in today's window, valued
                       this week and next;
    from the close     the CHAT MOVE: a group-chat claim, effective next Monday
                       (rule 7), counted against THIS week's add budget,
                       valued next week and the week after.
Week 7 (14 days) is one matchup. A horizon week past the season's last week
is absent (None): it adds nothing.

THE MOVES (decision 2):
    add_drop   add a free agent, drop an unprotected active player
    add_open   add into an open ACTIVE spot (an open IL slot is never one)
    il_add     an IL-eligible active player into an open IL slot, then add
    il_swap    drop an unprotected IL occupant, an IL-eligible active player
               into his slot, then add
IL eligibility (rule 2) is the caller's: MondayInputs.il_eligible. For a
Monday move it is the tag now (O or OFS); for a chat move the IL change
happens in next Monday's window, so the live path admits only a player who
will still be O or OFS then (advice_live says how).

THE TAGS' ANCHOR (V2 s.2): the tags are anchored at their fetch date,
MondayInputs.anchor. A chat move's horizon starts later; marginal_value
(MVContext.tag_anchor) and the week engine (tag_anchor) both count a tag's
games from the anchor over the NBA schedule, so the games before next Monday
spend the chain and the horizon sees only what is left. An anchor AFTER the
horizon starts raises; so does one more than a week before it.

THE UNIT (decision 2.4): startable games under the exact daily fill
(lineup_fill via marginal_value and simulator_betting), O days removed by the
absence model, an overflow game (an 11th healthy player with a game that day,
or no seat his positions fit) worth nothing.

HOW A MOVE IS PRICED (decision 7: screen, then price the finalists):
  1. SCREEN, marginal_value over the two horizon weeks at screen_sims:
     each unprotected drop's points lost; every free agent against the
     roster minus the cheapest drop; the best adds x the cheapest drops.
  2. PRICE the finalists:
     - dwp[k]: the change in the manager's win chance in horizon week k
       against his ACTUAL opponent, simulator_betting.simulate_week_matrix
       with keyed common random numbers (one KeyedDraws per call: the same
       seed and inputs give the same numbers, and an unchanged player's
       draws never move). A 14-day week is one matchup. A tied week is worth
       MondayInputs.tie_value (0.5 in the regular season, where a T is half
       a win; 1 or 0 in a bracket week, where the higher seed takes it).
       A week with no matchup (an opponent of None: a bracket pairing not
       set yet, or a team idle) has no win-chance term.
     - dT_horizon: sum_k leverage_k x dwp[k], in injured_drop's stake units
       (rs_weight x P(regular-season title) + playoff_weight x P(champion));
       leverage_k is injured_drop.win_value_parts -- the stakes file's CAUSAL
       (near-tie) leverage, the same one point_value prices a point with.
     - dT_later: the title-odds change from the weeks after the horizon,
       sum_w injured_drop.point_value(stake_w) x dpts_w -- the per-manager
       sensitivity of decision 7, read off the stakes the season pass
       already writes. dpts_w is what the season pass measures
       (HANDOFF_ADVICE_TITLE_TERM s.2): the manager's expected startable
       points that week (marginal_value) on the roster the pass's own roster
       plan gives him WITH the move minus WITHOUT it -- a static roster, its
       stand-ins, IL returns and 18b drops included, no replacement cap.
   THE ROSTERS ARE THE SEASON PASS'S: MondayInputs.plan (PlanSpec) is the
   roster plan the pass plays (roster_plan.build's own arguments); the "no
   move" baseline of both horizon weeks is that plan (an IL occupant back at
   the next window, a stand-in in an open spot), and a move is that plan
   rebuilt with the move as known moves at its window (known_for) -- the
   encoding the check against season_sim (scripts/advice_title_check.py)
   runs the pass with.
     - dT_rs / dT_po: the same title change split by race, so the display
       can show the phase's top prize (Priced.title_odds).
  3. RANK by a Weighting; RECOMMENDED (decision 1, amended 11-05) is wins
     this week + next + 0.5 x the title term only when it is NEGATIVE: a veto.
     THE POINTS TIE-BREAK (V2 s.6.2, V1 s.7.6): a move whose |dwp| summed
     over the two weeks is under FLAT_WIN (0.5%) cannot be told apart by win
     chance -- the matchups are decided, or have no opponent -- so its win
     part is treated as zero and moves are ordered by expected startable
     points (dpts summed). It beats standing pat only on points.
  4. THE LAST ADD: with one add left, a move must clear settings.last_add_bar
     (its insurance value); a flat move never does.

CONTESTED PLAYERS (decision 4): advise_all prices every manager, then marks
"also wanted by" (another manager whose top move adds the same player) and
picks each manager's BACKUP: his best qualifying move whose add is neither his
top add nor anybody else's. Free agents are never split between managers.

PROTECTION (decision 3a): the manager's top `protected` by keep chance are
never a suggested drop (injured_drop.keep_rank orders them, ties by name).
Everyone else is priced, IL occupants included. A player joining by a
pending claim has no keep chance yet (ManagerState.joining): he is not
protected, and every OTHER player without a keep chance raises.

IL PLACEMENT IS NOT FREE (decision 2): a player put into an IL slot scores
nothing for the rest of that week (simulator_betting's il_mask). If the plan
activates him at the next window, the follow-up drop is THE PLAN'S
(roster_plan.activation_drops, the one activation rule, 44a: the least
long-run value, never a protected player) -- a two-step plan, shown.

THE ACTIVATION STEP (44a): when the plan activates an IL occupant at the
window advice is advising on (activation_step: the horizon's first week, when
it is one of the plan's windows -- a chat move's next Monday), the manager
must decide who goes whether or not he adds anyone. That step is the plan's
own (who comes back, who the one rule drops; it costs no add) and is shown
BEFORE the pick. The pick is a move from the roster AFTER the step: the
returners are active and never a pick's drop, the step's drops are gone, and
the step is encoded with the move (known_for(step=...)) so the plan prices
the pick on exactly that roster. So the pick cannot drop the player just
activated, and the step cannot drop the player the pick adds. A Monday
move is before the window's close, where the plan's start week is an OPEN
window (44b s.2, roster_plan.window_open): its activation is shown there too.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta
from typing import Mapping, Optional, Sequence

import numpy as np

from . import absence, injured_drop, roster_plan
from . import marginal_value as mv
from . import simulator_betting as sb
from .data_loader import PlayerIndex
from .projections import DEFAULT_WEEKLY_STD_DEV, PlayerProjection, TeamProjections

IL_TAGS = frozenset({"O", "OFS"})          # LEAGUE_RULES 2026-27 IL rule 2
KINDS = ("add_drop", "add_open", "il_add", "il_swap")
MONDAY, CHAT = "monday", "chat"
# The points tie-break (V2 s.6.2): |dwp| summed over the two weeks under this
# is a decided (or unmatched) horizon, ranked by expected startable points.
FLAT_WIN = 0.005


# =============================================================================
# The horizon: a Monday move or a chat move, by the clock
# =============================================================================

@dataclass(frozen=True)
class Horizon:
    kind: str                  # MONDAY | CHAT
    weeks: tuple               # (first, second); second None past the season's last week
    budget_week: int           # the week whose adds the move uses (rule 7: the week it is made in)
    effective: date            # the Monday the move takes effect
    closes: datetime           # this week's Monday window close

    def label(self) -> str:
        if self.kind == MONDAY:
            return "Monday move"
        return f"Chat move (effective {self.effective:%a} {self.effective:%m-%d})"


def horizon_for(now: datetime, week: int, week_dates: Mapping[int, Sequence[date]],
                close: datetime) -> Optional[Horizon]:
    """The move a manager can make now (V2 s.2). `week` is the fantasy week
    holding `now` (the league clock), `close` its Monday window close
    (price_lock.window_close). Before the close: the Monday move, this week
    and next. From the close: the chat move, next week and the week after
    (rule 7), still on this week's add budget. None when no window is left
    this season (the effective week is past the last week)."""
    if now.tzinfo is None or close.tzinfo is None:
        raise ValueError("the horizon is decided on the league clock (aware datetimes)")
    week = int(week)
    if week not in week_dates:
        raise KeyError(f"week {week} is not in the schedule")
    kind, first = (MONDAY, week) if now < close else (CHAT, week + 1)
    if first not in week_dates:
        return None
    second = first + 1 if (first + 1) in week_dates else None
    return Horizon(kind, (first, second), week, list(week_dates[first])[0], close)


# =============================================================================
# The world: what simulator_betting reads off `data`, passed in explicitly
# =============================================================================

class World:
    """A FantasyData stand-in built from explicit inputs (R2).

    simulator_betting reads exactly these off `data`: nba_schedule ({"games":
    [{date, home, away}]}), schedule ({"weeks": [{week, start_date,
    end_date}]}), get_nba_games_for_date, current_week, durability_prior,
    and it caches on __dict__. Nothing else.

    current_week: the week BEFORE the one holding the tags' anchor, so
    simulator_betting.tag_week (current_week + 1) is the tags' own week."""

    def __init__(self, nba_schedule: dict, schedule_weeks: Sequence[dict], current_week: int,
                 durability_prior=None):
        games = [dict(g) for g in (nba_schedule or {}).get("games", [])
                 if g.get("home") and g.get("away")]
        self.nba_schedule = {"games": games}
        self.schedule = {"weeks": [dict(w) for w in schedule_weeks]}
        self.current_week = int(current_week)
        self.durability_prior = durability_prior
        self._by_date: dict = {}
        for g in games:
            self._by_date.setdefault(str(g["date"])[:10], []).append(g)
        self._weeks = {int(w["week"]): dict(w) for w in schedule_weeks}

    def get_nba_games_for_date(self, d: date) -> list:
        ds = d.strftime("%Y-%m-%d")
        return [{"date": ds, "home_team": g["home"], "away_team": g["away"]}
                for g in self._by_date.get(ds, [])]

    def week(self, w: int) -> dict:
        if int(w) not in self._weeks:
            raise KeyError(f"week {w} is not in the world's schedule")
        out = dict(self._weeks[int(w)])
        out.pop("matchups", None)
        out["week"] = int(w)
        return out

    def dates(self, w: int) -> list:
        wd = self.week(w)
        d0 = date.fromisoformat(str(wd["start_date"])[:10])
        d1 = date.fromisoformat(str(wd["end_date"])[:10])
        return [d0 + timedelta(days=k) for k in range((d1 - d0).days + 1)]

    def week_of(self, d: date) -> Optional[int]:
        for w in self._weeks:
            ds = self.dates(w)
            if ds and ds[0] <= d <= ds[-1]:
                return w
        return None

    def teams_on(self, d: date) -> frozenset:
        return frozenset(t for g in self._by_date.get(d.isoformat(), [])
                         for t in (g["home"], g["away"]))


# =============================================================================
# Inputs
# =============================================================================

@dataclass(frozen=True)
class Settings:
    seed: int = 20261105
    screen_sims: int = 48       # marginal_value, the screen
    price_sims: int = 1000      # simulate_week_matrix, the finalists
    # marginal_value over the weeks after the horizon: roster_moves.longrun_sims (44b s.1,
    # 200), the roster plan's LongRun's own -- one long-run measure (44a's parity)
    long_sims: int = field(default_factory=lambda: roster_plan.longrun_rules()["sims"])
    adds_screen: int = 25       # free agents kept by the add screen
    drops_screen: int = 6       # cheapest drops kept by the drop screen
    finalists: int = 12         # moves priced in full, per manager
    protected: int = 4          # decision 3a
    # The insurance value of a last add, in score units (win chance summed over
    # the two weeks), from the 2025-26 replay (V1 result s.4): P(a roster player
    # is newly O by next Monday) 0.575 x the median one-week gain of a top pick
    # 0.056 x a 1-in-4 chance that claiming his replacement early in the chat
    # beats Monday's race (four managers, a deep pool) = 0.008, rounded up.
    # It withheld no Monday pick in the replay; it binds on chat moves (V2 s.6.3).
    last_add_bar: float = 0.01


@dataclass(frozen=True)
class Weighting:
    """How the two weekly gains and the title-odds term combine (decision 1).

    mode "wins":  w1 x dwp[0] + w2 x dwp[1] + lam x dT_later / lbar
                  (lbar: the manager's mean stake per win over the horizon,
                  so lam = 1 values a stake unit after the horizon like one
                  inside it);
    mode "title": dT_horizon + lam x dT_later (lam = 1: the title-odds
                  change alone, every week by its leverage);
    mode "wins_penalty": as "wins", but the title term counts only when it is
                  NEGATIVE: it can stop a move that costs long-run value (a
                  keeper cut for games, an injured star dropped before his
                  return) but never buys a "gem" on projection alone. The
                  2025-26 replay's recommendation (V1 result s.3): with the full
                  term, more title weight made both the two-week and the
                  rest-of-season outcomes WORSE, because long-run value is the
                  projection's level times many weeks, and the projection's
                  level error (breakouts, rookies, decline) dominates it."""
    name: str
    mode: str = "wins"
    w1: float = 1.0
    w2: float = 1.0
    lam: float = 0.0

    def score(self, p: "Priced") -> float:
        if self.mode == "title":
            return p.dT_horizon + self.lam * p.dT_later
        if self.mode not in ("wins", "wins_penalty"):
            raise ValueError(f"unknown weighting mode {self.mode!r}")
        t = min(0.0, p.dT_later) if self.mode == "wins_penalty" else p.dT_later
        later = (self.lam * t / p.lbar) if (self.lam and p.lbar) else 0.0
        return self.w1 * p.dwp[0] + self.w2 * p.dwp[1] + later


RECOMMENDED = Weighting("wins + 0.5 title penalty", "wins_penalty", 1, 1, 0.5)

WEIGHTINGS = (
    RECOMMENDED,
    Weighting("wins only", "wins", 1, 1, 0.0),
    Weighting("wins + 0.5 title", "wins", 1, 1, 0.5),
    Weighting("wins + 1 title", "wins", 1, 1, 1.0),
    Weighting("wins + 2 title", "wins", 1, 1, 2.0),
    Weighting("this week only", "wins", 1, 0, 0.0),
    Weighting("title odds only", "title", lam=1.0),
)


@dataclass(frozen=True)
class ManagerState:
    manager: str
    active: tuple                 # on the 15 (13 before 2025-26 week 16) active spots
    il: tuple                     # in IL slots, fixed for the week
    active_capacity: int
    il_capacity: int
    adds_left: int                # in the move's budget week (V2 s.3: the one counter)
    keep: Mapping[str, float]     # keep chance for every real player on the roster
    opponents: Mapping[int, Optional[str]]  # horizon week -> opponent; None: no matchup
    # V2 s.3: the roster in the SECOND horizon week before any move, when the
    # ledger's pending moves for that window change it ((active, il)); None:
    # the same as the first week's
    later: Optional[tuple] = None
    # players joining by a pending claim: no keep chance yet, never protected
    joining: frozenset = frozenset()

    def roster(self) -> tuple:
        return tuple(self.active) + tuple(self.il)

    def all_names(self) -> tuple:
        extra = () if self.later is None else tuple(self.later[0]) + tuple(self.later[1])
        return tuple(dict.fromkeys(self.roster() + extra))


@dataclass
class PlanSpec:
    """The roster plan the season pass plays: roster_plan.build's keyword
    arguments (the live path takes them from roster_plan.for_run, Run.args;
    a fixture or the replay builds its own). The horizon baseline and the
    title term read every week's rosters off it (HANDOFF_ADVICE_TITLE_TERM
    s.2): plan() is the plan as it stands (args["known"], the ledger's known
    moves), plan(known_for(move, ...)) the plan with the move. One plan --
    roster_plan.build itself -- never a second copy of its rules."""
    args: dict
    _plans: dict = field(default_factory=dict, repr=False)

    def __post_init__(self):
        if "known" not in self.args:
            raise KeyError("PlanSpec.args needs 'known' (the ledger's known moves; {} for none)")

    def plan(self, extra: Optional[dict] = None) -> dict:
        known = merge_known(self.args.get("known") or {}, extra or {})
        key = json.dumps({str(w): v for w, v in sorted(known.items())}, sort_keys=True)
        hit = self._plans.get(key)
        if hit is None:
            hit = self._plans[key] = roster_plan.build(**{**self.args, "known": known})
        return hit

    @staticmethod
    def standins(plan: dict) -> dict:
        """{name: PlayerProjection} of every stand-in the plan made."""
        return {n: p for w in plan.values() for v in w.values() for n, p in v["standins"].items()}


@dataclass
class MondayInputs:
    season: str
    horizon: tuple                     # (effective week, the week after or None)
    world: World
    projections: dict                  # name -> PlayerProjection: rostered and pool
    statuses: dict                     # name -> tag (O, OFS, Q, D, ...); absent = HEALTHY
    managers: dict                     # manager -> ManagerState
    pool: tuple                        # free agents, in a stable order
    anchor: date                       # the tags' anchor: their fetch date (V2 s.2)
    stakes: dict = field(default_factory=dict)   # manager -> injured_drop.TeamStakes
    drop_config: Optional[injured_drop.Config] = None
    banked: dict = field(default_factory=dict)   # (manager, week) -> points already scored
    weekly_sd: dict = field(default_factory=dict)  # manager -> weekly std dev
    kind: str = MONDAY                 # MONDAY | CHAT
    # names that may go into an IL slot at the horizon's window (rule 2).
    # None: the tag now (a Monday move only; a chat move must pass it)
    il_eligible: Optional[frozenset] = None
    # (manager, week) -> what a tied week is worth to him; absent: 0.5 (a
    # regular-season T, tie_win_value). The live path fills every bracket week
    tie_value: dict = field(default_factory=dict)
    nba_outs: dict = field(default_factory=dict)   # step 3b: {player: date} out tonight
    reserved: frozenset = frozenset()  # players claimed (pending) by anyone: never in the pool
    # the season pass's roster plan (PlanSpec): REQUIRED -- the horizon's
    # baseline and the later weeks are read off it (HANDOFF_ADVICE_TITLE_TERM)
    plan: Optional[PlanSpec] = None
    _standins: dict = field(default_factory=dict, repr=False)
    _sims: dict = field(default_factory=dict, repr=False)
    _ctx: dict = field(default_factory=dict, repr=False)

    def status(self, name: str) -> str:
        return absence.normalised_tag(self.statuses.get(name, "HEALTHY"))

    def projection(self, name: str) -> PlayerProjection:
        """A player's projection, or a plan stand-in's (made by _plan). RAISES
        on a name it has neither for: never a silent zero."""
        p = self.projections.get(name)
        if p is None:
            p = self._standins.get(name)
        if p is None:
            p = PlayerIndex(self.projections).get(name)
        if p is None:
            raise KeyError(f"no projection for {name}")
        return p

    def weeks(self) -> list:
        """The horizon's weeks that exist (the second is None past the season)."""
        return [w for w in self.horizon if w is not None]

    def il_ok(self, name: str) -> bool:
        if self.il_eligible is not None:
            return name in self.il_eligible
        if self.kind != MONDAY:
            raise ValueError("a chat move's IL eligibility is next Monday's: pass il_eligible")
        return self.status(name) in IL_TAGS

    def check(self) -> None:
        """Raise on inputs that would make a silent wrong answer."""
        if len(self.horizon) != 2 or self.horizon[0] is None:
            raise ValueError("the horizon is two matchups (the second None past the season)")
        if self.horizon[1] is not None and int(self.horizon[1]) != int(self.horizon[0]) + 1:
            raise ValueError(f"the horizon {self.horizon} is not two consecutive weeks")
        if self.kind not in (MONDAY, CHAT):
            raise ValueError(f"kind must be {MONDAY!r} or {CHAT!r}, not {self.kind!r}")
        if self.kind == CHAT and self.il_eligible is None:
            raise ValueError("a chat move's IL eligibility is next Monday's: pass il_eligible")
        if self.plan is None:
            raise ValueError("no roster plan (PlanSpec): the horizon's baseline and the title term "
                             "are the season pass's plan's (HANDOFF_ADVICE_TITLE_TERM s.2)")
        for w in self.weeks():
            if int(w) < int(self.plan.args["start_week"]):
                raise ValueError(f"horizon week {w} is before the plan's start week "
                                 f"{self.plan.args['start_week']}")
        first = self.world.dates(self.horizon[0])[0]
        if self.anchor > first:
            raise ValueError(f"the tags' anchor {self.anchor} is after the horizon's first day {first}")
        aw = self.world.week_of(self.anchor)
        if aw is None or aw < int(self.horizon[0]) - 1:
            raise ValueError(f"the tags' anchor {self.anchor} is more than a week before the horizon "
                             f"(week {self.horizon[0]}): the tags are too old to price it")
        seen = {}
        for m, st in self.managers.items():
            if len(st.active) > st.active_capacity:
                raise ValueError(f"{m}: {len(st.active)} active players over {st.active_capacity}")
            if len(st.il) > st.il_capacity:
                raise ValueError(f"{m}: {len(st.il)} in IL slots over {st.il_capacity}")
            for n in st.roster():
                if n in seen:
                    raise ValueError(f"{n} is on {seen[n]}'s and {m}'s rosters")
                seen[n] = m
            for n in st.all_names():
                if n not in self.projections:
                    raise KeyError(f"{m}'s {n} has no projection")
            for w in self.weeks():
                if w not in st.opponents:
                    raise KeyError(f"{m} has no opponent entry in week {w} (None: no matchup)")
        for n in self.pool:
            if n in seen:
                raise ValueError(f"free agent {n} is on {seen[n]}'s roster")
            if n not in self.projections:
                raise KeyError(f"free agent {n} has no projection")
            if n in self.reserved:
                raise ValueError(f"free agent {n} is claimed in the chat (rule 10): not in the pool")


# =============================================================================
# Assembly: the one way MondayInputs are built (live path and fixtures)
# =============================================================================

def monday_il_eligible(names, statuses: Mapping[str, str]) -> frozenset:
    """A Monday move's IL eligibility (rule 2): tagged O or OFS now."""
    return frozenset(n for n in names
                     if absence.normalised_tag(statuses.get(n, "HEALTHY")) in IL_TAGS)


def chat_il_eligible(names, projections: Mapping[str, PlayerProjection], week: int) -> frozenset:
    """A chat move's IL eligibility (44b s.5): THE PLAN'S RULE,
    roster_plan.out_all_week -- an active player whose injury entry has him
    out for the whole of the chat move's week is IL-eligible at its window
    (entry-as-O, held 11 of 11 in 44a s.4.1), with or without an O/OFS tag
    today. The same function the plan's step 2 places by, so the two cannot
    differ. (An OFS tag with no entry is eligible for neither: 44a case 4.)"""
    return frozenset(n for n in names if roster_plan.out_all_week(projections[n], week))


def assemble(*, horizon: "Horizon", season: str, nba_schedule: dict, schedule_weeks: Sequence[dict],
             durability_prior, anchor: date, projections: Mapping[str, PlayerProjection],
             statuses: Mapping[str, str], rosters: Mapping[str, tuple], shape: tuple,
             adds_left: Mapping[str, int], keep: Mapping[str, Mapping[str, float]],
             opponents: Mapping[str, Mapping[int, Optional[str]]], pool: Sequence[str],
             il_eligible: frozenset, later: Mapping[str, tuple] = None,
             joining: Mapping[str, frozenset] = None, reserved: frozenset = frozenset(),
             stakes: Mapping = None, drop_config: Optional[injured_drop.Config] = None,
             tie_value: Mapping = None, nba_outs: Mapping = None,
             weekly_sd: Mapping = None, plan: Optional[PlanSpec] = None) -> MondayInputs:
    """MondayInputs from explicit parts, checked. rosters: {manager:
    (active, il)} in the horizon's first week, the ledger's pending moves
    applied; later: the same for the second week where it differs. The World's
    current week is the one before the anchor's, so the week engine reads the
    tags as the anchor's week's (simulator_betting.tag_week)."""
    probe = World(nba_schedule, schedule_weeks, 0, durability_prior)
    aw = probe.week_of(anchor)
    if aw is None:
        raise ValueError(f"the tags' anchor {anchor} is in no fantasy week")
    world = World(nba_schedule, schedule_weeks, aw - 1, durability_prior)
    later = dict(later or {})
    joining = dict(joining or {})
    weeks = [w for w in horizon.weeks if w is not None]
    states = {}
    for m, (act, il) in rosters.items():
        if m not in adds_left or m not in keep or m not in opponents:
            raise KeyError(f"{m}: adds left, keep chances and opponents are all required")
        states[m] = ManagerState(m, tuple(act), tuple(il), int(shape[0]), int(shape[1]), int(adds_left[m]),
                                 dict(keep[m]), {w: opponents[m][w] for w in weeks},
                                 later.get(m), frozenset(joining.get(m, ())))
    inp = MondayInputs(season=season, horizon=tuple(horizon.weeks), world=world,
                       projections=dict(projections), statuses=dict(statuses), managers=states,
                       pool=tuple(pool), anchor=anchor, stakes=dict(stakes or {}), drop_config=drop_config,
                       kind=horizon.kind, il_eligible=frozenset(il_eligible),
                       tie_value=dict(tie_value or {}), nba_outs=dict(nba_outs or {}),
                       reserved=frozenset(reserved), weekly_sd=dict(weekly_sd or {}), plan=plan)
    inp.check()
    return inp


# =============================================================================
# Moves and their prices
# =============================================================================

@dataclass(frozen=True)
class Move:
    manager: str
    kind: str
    add: str
    drop: Optional[str] = None
    to_il: Optional[str] = None
    screen_points: float = 0.0
    screen_starts: float = 0.0

    def describe(self) -> str:
        parts = [f"add {self.add}"]
        if self.drop:
            parts.append(f"drop {self.drop}")
        if self.to_il:
            parts.append(f"{self.to_il} to IL")
        return ", ".join(parts)


def known_for(move: "Move", window: int, followup: Optional[str] = None,
              next_window: Optional[int] = None, step: Optional[dict] = None) -> dict:
    """The move as the roster plan's KNOWN moves (roster_plan.build's `known`):
    {window week: {manager: {"il_place", "drop", "add", "il_activate"}}}.
    THE ONE ENCODING: the title term prices a move by rebuilding the plan with
    it, and the check against season_sim (scripts/advice_title_check.py) runs
    the pass with the same dict, so the two price the same thing.
    window: the horizon's first week (the move's window); the follow-up drop
    of an IL move happens at next_window (the horizon's second week).
    step: the plan's activation at the window (activation_step), applied
    with the move so the move is priced on the roster after it (44a)."""
    e = {"il_place": [], "drop": [], "add": [move.add], "il_activate": []}
    if step:
        if int(step["week"]) != int(window):
            raise ValueError(f"the activation step is week {step['week']}'s, the move's window {window}")
        e["drop"].extend(step["drops"])
        e["il_activate"].extend(step["back"])
    if move.to_il:
        e["il_place"].append(move.to_il)
    if move.drop:
        e["drop"].append(move.drop)
    out = {int(window): {move.manager: e}}
    if followup:
        if next_window is None:
            raise ValueError(f"{move.describe()}: a follow-up drop needs the next window")
        out[int(next_window)] = {move.manager: {"il_place": [], "drop": [followup], "add": [],
                                                "il_activate": []}}
    return out


def merge_known(*parts) -> dict:
    """Known-move dicts merged per window and manager (lists concatenated)."""
    out: dict = {}
    for k in parts:
        for w, by_m in (k or {}).items():
            for m, e in by_m.items():
                t = out.setdefault(int(w), {}).setdefault(m, {"il_place": [], "drop": [], "add": [],
                                                              "il_activate": []})
                for key in ("il_place", "drop", "add", "il_activate"):
                    t[key] = list(t[key]) + list(e.get(key) or [])
    return out


@dataclass(frozen=True)
class Priced:
    move: Move
    dwp: tuple              # win-chance change, horizon week 1 and 2 (0.0 with no matchup)
    wp_base: tuple          # the manager's win chance with no move (None with no matchup)
    dpts: tuple             # mean points change, horizon weeks
    dstarts: tuple          # mean started-games change, horizon weeks
    dT_horizon: float       # stake units
    dT_later: float         # stake units
    dpts_later: float       # his points after the horizon, the plan's rosters with - without
    lbar: float             # mean stake per win over the horizon (0: no stakes)
    followup_drop: Optional[str] = None
    dpts_later_by_week: tuple = ()    # ((week, points with - without the move), ...)
    dT_rs: float = 0.0      # the title change from regular-season weeks (stake units)
    dT_po: float = 0.0      # ... from bracket weeks (stake units)
    followup_standin: bool = False    # the follow-up drop is a plan stand-in (a placeholder pickup)

    def flat(self) -> bool:
        """The points tie-break applies: the win chances cannot tell it apart."""
        return abs(self.dwp[0]) + abs(self.dwp[1]) < FLAT_WIN

    def title_odds(self, config: Optional[injured_drop.Config], regular_season: bool) -> Optional[float]:
        """The change in the phase's top prize as a probability (V2 s.6.1): the
        regular-season title through the regular season, the playoff title
        (champion) from the playoffs on. None without stakes."""
        if config is None or not self.lbar and not (self.dT_rs or self.dT_po):
            return None
        if regular_season:
            return self.dT_rs / config.rs_weight if config.rs_weight else None
        return self.dT_po / config.playoff_weight if config.playoff_weight else None

    def reason(self) -> str:
        s = f"{self.dstarts[0] + self.dstarts[1]:+.1f} starts"
        s += f"; win chance {100 * self.dwp[0]:+.1f}% this week, {100 * self.dwp[1]:+.1f}% next"
        if self.lbar:
            s += f"; title {self.dT_horizon + self.dT_later:+.4f}"
        if self.flat():
            s += f"; matchups decided: ranked on points ({self.dpts[0] + self.dpts[1]:+.1f})"
        if self.followup_drop:
            s += f"; next week drop {self.followup_drop} when {self.move.to_il} returns"
        return s


@dataclass(frozen=True)
class Recommendation:
    manager: str
    top: Optional[Priced]          # None: no move clears the bar
    ranked: tuple                  # (score, Priced), best first (by key)
    weighting: str
    bar: float
    note: str = ""
    keys: tuple = ()               # the ranking keys, aligned with ranked

    def qualifying(self) -> list:
        """(score, Priced) of every move that beats standing pat (and the bar)."""
        return [sp for sp, k in zip(self.ranked, self.keys) if qualifies(k, self.bar)]


@dataclass(frozen=True)
class Advice:
    """One manager's advice after the contest is read (decision 4)."""
    manager: str
    rec: Recommendation
    top: Optional[Priced]
    top_score: Optional[float]
    also_wanted_by: tuple          # managers whose top move adds the same player
    backup: Optional[Priced]       # his best qualifying move whose add is nobody else's top
    backup_score: Optional[float]
    step: Optional[dict] = None    # the plan's activation at the advised window (activation_step)


# =============================================================================
# helpers
# =============================================================================

def protected(state: ManagerState, n: int) -> frozenset:
    """The top n by keep chance (decision 3a): roster_plan.protected_players,
    THE ONE PROTECTION FUNCTION (the plan's activation rule ranks with it too).
    A roster player with no keep chance RAISES, unless he joins by a pending
    claim (state.joining: no keep chance yet, never protected)."""
    keep = dict(state.keep)

    def chance(name):
        if name in keep:
            return keep[name]
        if name in state.joining:
            return None
        raise KeyError(f"no keep chance for {name}: the decision needs his team's keep chances")
    return roster_plan.protected_players(state.all_names(), chance, n)


def protected_for(inputs: "MondayInputs", manager: str, settings: "Settings") -> frozenset:
    """The manager's protected players (44b s.6): the top settings.protected;
    his keeper candidates (injured_drop keeper_candidates) when his team has
    little left to play for (injured_drop.little_left on his stakes at the
    horizon). The count is injured_drop.protected_count, the plan's own."""
    st = inputs.managers[manager]
    cfg, ts = inputs.drop_config, inputs.stakes.get(manager)
    if cfg is None:
        return protected(st, settings.protected)
    little = injured_drop.little_left(ts, cfg) if ts is not None else None
    return protected(st, injured_drop.protected_count(little, replace(cfg, protected_keepers=settings.protected)))


def back_next_week(inputs: MondayInputs, name: str, week: Optional[int]) -> bool:
    """Expected available from `week`'s window: no OFS, no override covering it."""
    if week is None:
        return False
    p = inputs.projections[name]
    if absence.season_out(inputs.status(name)):
        return False
    if week in (p.out_weeks or []):
        return False
    if p.return_week is not None and p.return_week > week:
        return False
    return True


def activation_step(inputs: MondayInputs, manager: str) -> Optional[dict]:
    """The plan's activation at the window advice is advising on (44a s.3):
    {"week", "back": [returners], "drops": [who the one rule drops],
    "standins": [drops that are plan stand-ins]} -- or None when the plan
    activates nobody of his there. The window is the horizon's first week:
    a chat move's next Monday, or a Monday move's own window, open until its
    close (44b s.2). A return needs no injury entry: the plan's own
    availability (roster_plan._available_from) decides, and a mid-week
    returner it chooses to activate early (44b s.4) is shown the same way."""
    w1 = int(inputs.horizon[0])
    P0 = _plan(inputs)
    v = (P0.get(w1) or {}).get(manager)
    if v is None or not v.get("activated"):
        return None
    st = inputs.managers[manager]
    back, drops = list(v["activated"]), list(v.get("activation_drops") or [])
    stand = PlanSpec.standins(P0)
    if any(n not in st.il for n in back) or any(n not in st.active and n not in stand for n in drops):
        raise ValueError(f"{manager}: the plan's week-{w1} activation ({back}, dropping {drops}) is not on "
                         f"the roster advice reads (active {sorted(st.active)}, IL {sorted(st.il)}): the "
                         "plan and the ledger's view disagree")
    return {"week": w1, "back": back, "drops": drops, "standins": [n for n in drops if n in stand]}


def after_step(st: ManagerState, step: Optional[dict]) -> tuple:
    """(active, IL, returners): the manager's roster after the activation
    step -- what the pick is a move from."""
    if not step:
        return tuple(st.active), tuple(st.il), ()
    back = tuple(step["back"])
    active = tuple(n for n in st.active if n not in step["drops"]) + tuple(n for n in back
                                                                          if n not in st.active)
    return active, tuple(n for n in st.il if n not in back), back


def _mv_ctx(inputs: MondayInputs, weeks: Sequence[int], sims: int, seed: int):
    """A marginal_value context from the horizon's first week through the last
    of `weeks`, every relevant player in it. It always STARTS at the horizon;
    the tags are anchored at inputs.anchor (their fetch date, on or before the
    horizon's first day: MVContext.tag_anchor), so a chat move's horizon sees
    only what is left of a tag's games. Callers read the weeks they want off
    roster_totals' by_week."""
    last = max([int(w) for w in weeks] + [int(w) for w in inputs.weeks()])
    span = list(range(int(inputs.horizon[0]), last + 1))
    ck = (tuple(span), sims, seed)
    hit = inputs._ctx.get(ck)
    if hit is not None:
        return hit
    names = list(dict.fromkeys([n for st in inputs.managers.values() for n in st.all_names()]
                               + list(inputs.pool)))
    rosters = {m: list(st.active) for m, st in inputs.managers.items()}
    first = inputs.world.dates(span[0])[0]
    if inputs.anchor > first:
        raise ValueError(f"the tags' anchor {inputs.anchor} is after the horizon's first day {first}")
    ctx = mv.build_context({n: inputs.projections[n] for n in names}, rosters,
                           inputs.world.nba_schedule, inputs.world.schedule["weeks"],
                           "this_week", span[0] - 1, injury_statuses=inputs.statuses,
                           extra_players=names, durability_prior=inputs.world.durability_prior,
                           sims=sims, seed=seed, season=inputs.season, tag_anchor=inputs.anchor)
    ctx.weeks = span
    ctx.days = [(d, w, inputs.world.teams_on(d)) for w in span for d in inputs.world.dates(w)]
    inputs._ctx[ck] = ctx
    return ctx


def _totals(ctx, roster) -> tuple:
    pts, starts, by_week = mv.roster_totals(ctx, list(roster))
    return float(pts.mean()), float(starts.mean()), {w: float(np.mean(v)) for w, v in by_week.items()}


# =============================================================================
# 1. The screen
# =============================================================================

def candidate_moves(inputs: MondayInputs, manager: str, settings: Settings) -> list:
    """Every move worth pricing, best screen value first."""
    st = inputs.managers[manager]
    prot = protected_for(inputs, manager, settings)
    ctx = _mv_ctx(inputs, inputs.weeks(), settings.screen_sims, settings.seed)
    R, IL, back = after_step(st, activation_step(inputs, manager))     # 44a: a move after the step
    base_p, base_s, _ = _totals(ctx, R)

    def gain(roster):
        p, s, _ = _totals(ctx, roster)
        return p - base_p, s - base_s

    moves: list = []
    droppable = [n for n in R if n not in prot and n not in back]
    dcost = {d: -gain([n for n in R if n != d])[0] for d in droppable}
    drops = sorted(droppable, key=lambda d: (dcost[d], d))[:settings.drops_screen]
    pool = [n for n in inputs.pool]

    def best_adds(against):
        bp, _bs, _ = _totals(ctx, against)
        vals = {}
        for f in pool:
            p, s, _ = _totals(ctx, list(against) + [f])
            vals[f] = (p - bp, s)
        return sorted(pool, key=lambda f: (-vals[f][0], f))[:settings.adds_screen]

    if drops:
        d0 = drops[0]
        adds = best_adds([n for n in R if n != d0])
        for d in drops:
            rest = [n for n in R if n != d]
            for f in adds:
                p, s = gain(rest + [f])
                moves.append(Move(manager, "add_drop", f, drop=d, screen_points=p, screen_starts=s))
    if len(R) < st.active_capacity:                      # an open ACTIVE spot only
        for f in best_adds(list(R)):
            p, s = gain(list(R) + [f])
            moves.append(Move(manager, "add_open", f, screen_points=p, screen_starts=s))
    newly_out = [n for n in R if n not in back and inputs.il_ok(n)]
    if newly_out and len(R) >= st.active_capacity:
        for pl in newly_out:
            rest = [n for n in R if n != pl]
            adds = best_adds(rest)
            if len(IL) < st.il_capacity:
                for f in adds:
                    p, s = gain(rest + [f])
                    moves.append(Move(manager, "il_add", f, to_il=pl, screen_points=p, screen_starts=s))
            else:
                for x in IL:
                    if x in prot:
                        continue
                    for f in adds:
                        p, s = gain(rest + [f])
                        moves.append(Move(manager, "il_swap", f, drop=x, to_il=pl,
                                          screen_points=p, screen_starts=s))
    moves.sort(key=lambda mo: (-mo.screen_points, mo.kind, mo.add, mo.drop or "", mo.to_il or ""))
    return moves


def finalists(moves: Sequence[Move], settings: Settings) -> list:
    """The best `finalists` by screen value, plus the best move of every kind
    (so an IL move is always priced when one exists)."""
    out = list(moves[:settings.finalists])
    for k in KINDS:
        best = next((mo for mo in moves if mo.kind == k), None)
        if best is not None and best not in out:
            out.append(best)
    return out


# =============================================================================
# 2. Pricing
# =============================================================================

def week_roster(inputs: MondayInputs, st: ManagerState, move: Optional[Move], k: int,
                followup: Optional[str]) -> tuple:
    """(players on the roster, players in IL slots) in horizon week k: the
    first week's roster, or the second week's when the ledger's pending moves
    for that window change it (ManagerState.later), with the move applied."""
    if k == 1 and st.later is not None:
        players = set(st.later[0]) | set(st.later[1])
        il = set(st.later[1])
    else:
        players = set(st.roster())
        il = set(st.il)
    if move is not None:
        players.add(move.add)
        if move.drop:
            players.discard(move.drop)
            il.discard(move.drop)
        if move.to_il and move.to_il in players:
            il.add(move.to_il)
        if k == 1 and move.to_il and followup is not None:
            il.discard(move.to_il)
            players.discard(followup)
    return frozenset(players), frozenset(il)


def _scores(inputs: MondayInputs, manager: str, players: frozenset, il: frozenset, week: int,
            settings: Settings) -> tuple:
    key = (manager, players, il, week, settings.price_sims)
    hit = inputs._sims.get(key)
    if hit is not None:
        return hit
    tp = {manager: TeamProjections(manager, {n: inputs.projection(n) for n in sorted(players)},
                                   weekly_std_dev=float(inputs.weekly_sd.get(manager,
                                                                             DEFAULT_WEEKLY_STD_DEV)))}
    draws = sb.KeyedDraws(settings.seed, settings.price_sims)
    extra = {"nba_outs": dict(inputs.nba_outs)} if inputs.nba_outs else {}
    res = sb.simulate_week_matrix(inputs.world, tp, inputs.world.week(week), inputs.statuses, draws,
                                  tag_anchor=inputs.anchor, managers=[manager],
                                  il_mask={manager: set(il)}, **extra)[manager]
    out = (res["score"] + float(inputs.banked.get((manager, week), 0.0)), res["games"])
    inputs._sims[key] = out
    return out


def _win(mine: np.ndarray, theirs: np.ndarray, tie: float = 0.5) -> float:
    """P(mine wins): a tied week counts `tie` (0.5 a regular-season T; 1 or 0
    in a bracket week, where the higher seed takes it)."""
    return float(np.mean(mine > theirs) + float(tie) * np.mean(mine == theirs))


def _leverage_parts(inputs: MondayInputs, manager: str, week: Optional[int]) -> tuple:
    """(rs part, playoff part) of the stake per win in `week`, stake units."""
    ts = inputs.stakes.get(manager)
    if week is None or ts is None or inputs.drop_config is None:
        return 0.0, 0.0
    ws = ts.weeks.get(week)
    if ws is None:
        return 0.0, 0.0
    return injured_drop.win_value_parts(ws, inputs.drop_config)     # the one price (causal leverage)


def _leverage(inputs: MondayInputs, manager: str, week: Optional[int]) -> float:
    return sum(_leverage_parts(inputs, manager, week))


def _plan(inputs: MondayInputs, extra: Optional[dict] = None) -> dict:
    """The season pass's roster plan, with `extra` known moves (a move,
    known_for) or as it stands; its stand-ins registered so their projections
    resolve (MondayInputs.projection)."""
    if inputs.plan is None:
        raise ValueError("no roster plan (PlanSpec) on the inputs")
    P = inputs.plan.plan(extra)
    sig = lambda x: (x.nba_team, list(x.positions), x.projected_fppg, x.projected_gp)
    clash = {n: p for n, p in PlanSpec.standins(P).items()
             if n in inputs._standins and sig(inputs._standins[n]) != sig(p)}
    if clash:
        # A stand-in's name carries its level to 0.1 (roster_plan), his projection the exact
        # level; a move changes the pool, so the move's plan can make a stand-in whose level
        # differs only past the first decimal. In ONE plan the name is unique (the season pass
        # is never confused); advice values two plans side by side, so the newcomer gets a
        # name of his own here -- in a copy of the plan, never the cached one.
        P = _renamed(P, {n: f"{n} [{p.projected_fppg:.6f}]" for n, p in clash.items()})
    for n, p in PlanSpec.standins(P).items():
        old = inputs._standins.get(n)
        if old is not None and sig(old) != sig(p):
            raise ValueError(f"two different stand-ins named {n!r}")
        inputs._standins[n] = p
    return P


def _renamed(P: dict, names: Mapping) -> dict:
    """Plan P with stand-ins renamed (names: old -> new), every week and list."""
    from copy import copy as _copy
    f = lambda n: names.get(n, n)
    out = {}
    for w, wk in P.items():
        out[w] = {}
        for m, v in wk.items():
            v2 = dict(v)
            for k in ("active", "il", "added", "dropped"):
                if k in v2 and isinstance(v2[k], list):
                    v2[k] = [f(x) if isinstance(x, str) else x for x in v2[k]]
            st = {}
            for n, pr in v.get("standins", {}).items():
                if n in names:
                    pr = _copy(pr)
                    pr.player_name = names[n]
                st[f(n)] = pr
            v2["standins"] = st
            out[w][m] = v2
    return out


def plan_roster(P: dict, manager: str, week: int) -> tuple:
    """(players on the roster, players in IL slots) in `week`, as plan P has them."""
    wk = P.get(int(week))
    if wk is None or manager not in wk:
        raise KeyError(f"the roster plan has no week {week} for {manager}")
    v = wk[manager]
    return frozenset(v["active"]) | frozenset(v["il"]), frozenset(v["il"])


def _week_points(ctx, roster: Sequence[str], week: int) -> float:
    """Mean startable points of `roster` (active players) in `week`, by
    marginal_value. Every name must be in the context: roster_totals would
    skip a missing one silently."""
    missing = [n for n in roster if ctx.players.canonical(n) is None]
    if missing:
        raise KeyError(f"not in the valuation context: {missing}")
    bw = mv.roster_totals(ctx, list(roster))[2]
    if int(week) not in bw:
        raise KeyError(f"week {week} is not in the valuation context's span")
    return float(np.mean(bw[int(week)]))


def _later_weeks(inputs: MondayInputs, manager: str) -> list:
    ts = inputs.stakes.get(manager)
    if ts is None:
        return []
    last_h = max(inputs.weeks())
    return [w for w in range(last_h + 1, int(ts.last_week) + 1) if w in ts.weeks]


def _later_ctx(inputs: MondayInputs, weeks: Sequence[int], sims: int, seed: int, plans: Sequence[dict]):
    """The valuation context over the horizon and `weeks`, with every stand-in
    of `plans` added (marginal_value.add_players)."""
    ctx = _mv_ctx(inputs, weeks, sims, seed)
    for P in plans:
        mv.add_players(ctx, PlanSpec.standins(P))
    return ctx


def followup_drop(inputs: MondayInputs, manager: str, move: Move, settings: Settings) -> Optional[str]:
    """Next week's drop when the IL'd player returns: THE PLAN'S (44a). The
    plan is rebuilt with the move (and the activation step) at its window; he
    is in IL there only if the plan keeps him (an injury entry out on the
    window day: roster_plan._available_from; otherwise the plan activates him
    at once), and if the plan activates him at next week's window, the
    follow-up is the player the one activation rule drops there
    (roster_plan.activation_drops: the least long-run value, never protected,
    never the returner; a stand-in valued at his level). None if he is not
    back next week, there is no next week, or the team has room for him."""
    return _followup(inputs, manager, move)[0]


def _followup(inputs: MondayInputs, manager: str, move: Move) -> tuple:
    """(the follow-up drop or None, whether he is a plan stand-in)."""
    if not move.to_il or inputs.horizon[1] is None:
        return None, False
    w1, w2 = inputs.horizon
    P = _plan(inputs, known_for(move, w1, step=activation_step(inputs, manager)))
    if move.to_il not in plan_roster(P, manager, w1)[1]:
        return None, False                       # the plan never held him in IL: activated at once
    v = P[int(w2)][manager]
    if move.to_il not in (v.get("activated") or []):
        return None, False                       # the plan keeps him in IL: not back
    drops = list(v.get("activation_drops") or [])
    if not drops:
        return None, False                       # room for him: nobody goes
    return drops[0], drops[0] in PlanSpec.standins(P)


def price(inputs: MondayInputs, manager: str, moves: Sequence[Move], settings: Settings,
          followups: Optional[Mapping] = None) -> list:
    """Each move's two weekly win-chance changes and its title-odds change.

    THE ROSTERS ARE THE SEASON PASS'S (HANDOFF_ADVICE_TITLE_TERM s.2): the
    roster plan as it stands (PlanSpec.plan()) is the "no move" baseline, and
    the plan rebuilt with the move as known moves at its window (known_for;
    an IL move's follow-up drop at the next window) is the move. So the
    horizon weeks see what the pass sees -- an IL occupant back at the next
    window, a stand-in in an open spot, an 18b drop -- and the weeks after the
    horizon are a STATIC roster: dpts_w = his expected startable points in
    week w on the plan's roster with the move minus without it
    (marginal_value), however far below replacement that is. No replacement
    cap (C2's streaming assumption is gone: the pass does not stream).
    dT_later = sum_w injured_drop.point_value(stake_w) x dpts_w. The opponent's
    roster in the horizon is the baseline plan's.
    followups: {move: follow-up drop} to price a given follow-up (the check
    against season_sim prices the list's); else followup_drop chooses it."""
    st = inputs.managers[manager]
    hz = list(inputs.horizon)
    w1, w2 = hz
    P0 = _plan(inputs)
    base = [None if w is None else plan_roster(P0, manager, w) for w in hz]
    base_sc, opp_sc, ties = [None, None], [None, None], [0.5, 0.5]
    for k, w in enumerate(hz):
        if w is None:
            continue
        base_sc[k] = _scores(inputs, manager, *base[k], w, settings)
        o = st.opponents[w]
        if o is not None:
            opp_sc[k] = _scores(inputs, o, *plan_roster(P0, o, w), w, settings)[0]
            ties[k] = float(inputs.tie_value.get((manager, w), 0.5))
    wp_base = tuple(None if opp_sc[k] is None else _win(base_sc[k][0], opp_sc[k], ties[k])
                    for k in (0, 1))
    parts = [_leverage_parts(inputs, manager, w) for w in hz]
    levs = [a + b for a, b in parts]
    lbar = float(np.mean(levs)) if any(levs) else 0.0
    later = _later_weeks(inputs, manager)
    ts = inputs.stakes.get(manager)
    step = activation_step(inputs, manager)

    out = []
    for mo in moves:
        fs = False
        if followups is not None and mo in followups:
            fu = followups[mo]
        else:
            fu, fs = _followup(inputs, manager, mo) if mo.to_il else (None, False)
        P = _plan(inputs, known_for(mo, w1, fu, w2, step=step))
        dwp, dpts, dst = [0.0, 0.0], [0.0, 0.0], [0.0, 0.0]
        for k, w in enumerate(hz):
            if w is None:
                continue
            players, il = plan_roster(P, manager, w)
            sc, games = _scores(inputs, manager, players, il, w, settings)
            if opp_sc[k] is not None:
                dwp[k] = _win(sc, opp_sc[k], ties[k]) - wp_base[k]
            dpts[k] = float(np.mean(sc - base_sc[k][0]))
            dst[k] = float(np.mean(games - base_sc[k][1]))
        dT_h = sum(levs[k] * dwp[k] for k in (0, 1))
        dT_rs = sum(parts[k][0] * dwp[k] for k in (0, 1))
        dT_po = sum(parts[k][1] * dwp[k] for k in (0, 1))
        dT_l, dpl, by_w = 0.0, 0.0, []
        if later:
            lctx = _later_ctx(inputs, later, settings.long_sims, settings.seed, [P0, P])
            for w in later:
                a = P[int(w)][manager]["active"]
                b = P0[int(w)][manager]["active"]
                d = 0.0 if sorted(a) == sorted(b) else _week_points(lctx, a, w) - _week_points(lctx, b, w)
                dpl += d
                by_w.append((w, round(d, 3)))
                pv_rs, pv_po = injured_drop.point_value_parts(ts.weeks[w], inputs.drop_config)
                dT_l += (pv_rs + pv_po) * d
                dT_rs += pv_rs * d
                dT_po += pv_po * d
        out.append(Priced(mo, tuple(dwp), wp_base, tuple(dpts), tuple(dst), dT_h, dT_l, dpl, lbar, fu,
                          tuple(by_w), dT_rs, dT_po, fs))
    return out


# =============================================================================
# 3. Ranking
# =============================================================================

def rank_key(weighting: Weighting, p: Priced) -> tuple:
    """(effective score, expected startable points). A flat move's win part is
    noise (V2 s.6.2): it is scored without it (only a title penalty is left)
    and ordered by points; standing pat is (0, 0)."""
    pts = p.dpts[0] + p.dpts[1]
    if p.flat():
        return (weighting.score(replace(p, dwp=(0.0, 0.0), dT_horizon=0.0)), pts)
    return (weighting.score(p), pts)


def qualifies(key: tuple, bar: float) -> bool:
    """Beats standing pat, and the last add's bar when it binds: above the
    bar, or (no bar) level with standing pat and ahead of it on points."""
    s, pts = key
    if s > bar:
        return True
    return bar <= 0.0 and s == 0.0 and pts > 0.0


def recommend(inputs: MondayInputs, manager: str, settings: Settings = Settings(),
              weighting: Weighting = RECOMMENDED, priced: Optional[Sequence[Priced]] = None
              ) -> Recommendation:
    """The manager's best move under `weighting`, or none.

    A move must beat standing pat; with one add left it must also clear
    settings.last_add_bar (decision 2: the last add's insurance value), which
    a flat move (the points tie-break) never does. Pass `priced` to re-rank
    without re-pricing."""
    st = inputs.managers[manager]
    if st.adds_left <= 0:
        return Recommendation(manager, None, (), weighting.name, math.inf, "no adds left")
    if priced is None:
        priced = price(inputs, manager, finalists(candidate_moves(inputs, manager, settings), settings),
                       settings)
    prot = protected_for(inputs, manager, settings)
    step = activation_step(inputs, manager)
    if step and set(step["drops"]) & prot:
        raise AssertionError(f"{manager}: the activation step drops a protected keeper "
                             f"({sorted(set(step['drops']) & prot)}): the plan and advice protect differently")
    for p in priced:
        if p.move.drop in prot or p.followup_drop in prot:
            raise AssertionError(f"{p.move.describe()}: drops a protected keeper")
        if step and (p.move.drop in step["back"] or p.move.drop in step["drops"]
                     or p.move.add in step["drops"] or p.move.to_il in step["back"]):
            raise AssertionError(f"{p.move.describe()}: conflicts with the activation step {step}")
        if p.move.add in inputs.reserved:
            raise AssertionError(f"{p.move.describe()}: adds a player claimed in the chat (rule 10)")
    keyed = sorted(((rank_key(weighting, p), weighting.score(p), p) for p in priced),
                   key=lambda t: (-t[0][0], -t[0][1], t[2].move.kind, t[2].move.add, t[2].move.drop or ""))
    ranked = tuple((s, p) for _k, s, p in keyed)
    keys = tuple(k for k, _s, _p in keyed)
    bar = max(0.0, settings.last_add_bar) if st.adds_left == 1 else 0.0
    top = ranked[0][1] if ranked and qualifies(keys[0], bar) else None
    note = "" if top is not None else ("nothing clears the last add's bar" if st.adds_left == 1
                                       else "standing pat beats every move")
    return Recommendation(manager, top, ranked, weighting.name, bar, note, keys)


def advise_all(inputs: MondayInputs, settings: Settings = Settings(),
               weighting: Weighting = RECOMMENDED, recs: Optional[dict] = None) -> dict:
    """{manager: Advice}: every manager's recommendation, then the contest
    (decision 4). "Also wanted by": another manager whose top move adds the
    same player. The backup: his best qualifying move whose add is neither
    his own top add nor anybody else's. Free agents are never split."""
    recs = recs or {m: recommend(inputs, m, settings, weighting) for m in sorted(inputs.managers)}
    tops = {m: r.top.move.add for m, r in recs.items() if r.top is not None}
    out = {}
    for m in sorted(recs):
        r = recs[m]
        step = activation_step(inputs, m)
        if r.top is None:
            out[m] = Advice(m, r, None, None, (), None, None, step)
            continue
        mine = tops[m]
        wanted = tuple(sorted(o for o, a in tops.items() if o != m and a == mine))
        others = {a for o, a in tops.items() if o != m}
        top_score = next(s for s, p in r.ranked if p is r.top)
        backup = next(((s, p) for s, p in r.qualifying()
                       if p.move.add != mine and p.move.add not in others), None)
        out[m] = Advice(m, r, r.top, top_score, wanted,
                        backup[1] if backup else None, backup[0] if backup else None, step)
    return out


# =============================================================================
# The simple rules the replay compares against (decision 6)
# =============================================================================

def _healthy_pool(inputs: MondayInputs) -> list:
    return [n for n in inputs.pool if inputs.status(n) not in IL_TAGS]


def most_games(inputs: MondayInputs, manager: str, settings: Settings,
               drop: Optional[str] = None) -> Optional[Move]:
    """'Add the most games': the free agent with the most startable games
    this week and next (ties: higher projection); the drop is the unprotected
    active player with the fewest (ties: lower projection) unless `drop` is
    given. No move unless it gains startable games."""
    st = inputs.managers[manager]
    prot = protected_for(inputs, manager, settings)
    ctx = _mv_ctx(inputs, inputs.weeks(), settings.screen_sims, settings.seed)
    R = list(st.active)
    _bp, bs, _ = _totals(ctx, R)
    open_spot = len(R) < st.active_capacity
    if drop is None and not open_spot:
        cands = [n for n in R if n not in prot]
        if not cands:
            return None
        lost = {d: bs - _totals(ctx, [n for n in R if n != d])[1] for d in cands}
        drop = min(cands, key=lambda d: (round(lost[d], 6), inputs.projections[d].effective_fppg, d))
    rest = [n for n in R if n != drop] if drop else R
    _rp, rs, _ = _totals(ctx, rest)
    best, best_key = None, None
    for f in _healthy_pool(inputs):
        s = _totals(ctx, rest + [f])[1] - rs
        k = (round(s, 6), inputs.projections[f].effective_fppg)
        if best_key is None or k > best_key or (k == best_key and f < best):
            best, best_key = f, k
    if best is None:
        return None
    p, s, _ = _totals(ctx, rest + [best])
    if s - bs <= 0:
        return None
    return Move(manager, "add_drop" if drop else "add_open", best, drop=drop,
                screen_points=p - _bp, screen_starts=s - bs)


def highest_projection(inputs: MondayInputs, manager: str, settings: Settings,
                       drop: Optional[str] = None) -> Optional[Move]:
    """'Add the highest projection': the healthy free agent with the highest
    point-in-time projection; the drop is the unprotected active player with
    the lowest, unless `drop` is given. No move unless the add projects higher."""
    st = inputs.managers[manager]
    prot = protected_for(inputs, manager, settings)
    R = list(st.active)
    open_spot = len(R) < st.active_capacity
    proj = lambda n: inputs.projections[n].effective_fppg
    if drop is None and not open_spot:
        cands = [n for n in R if n not in prot]
        if not cands:
            return None
        drop = min(cands, key=lambda d: (proj(d), d))
    pool = _healthy_pool(inputs)
    if not pool:
        return None
    add = max(pool, key=lambda f: (proj(f), [-ord(c) for c in f]))
    if drop and proj(add) <= proj(drop):
        return None
    ctx = _mv_ctx(inputs, inputs.weeks(), settings.screen_sims, settings.seed)
    bp, bs, _ = _totals(ctx, R)
    rest = [n for n in R if n != drop] if drop else R
    p, s, _ = _totals(ctx, rest + [add])
    return Move(manager, "add_drop" if drop else "add_open", add, drop=drop,
                screen_points=p - bp, screen_starts=s - bs)


def engine_drop(rec: Recommendation, moves: Sequence[Move]) -> Optional[str]:
    """The drop the common-drop variant gives the simple rules: the engine's
    own add/drop drop, else its cheapest screened drop."""
    if rec.top is not None and rec.top.move.kind == "add_drop":
        return rec.top.move.drop
    for _s, p in rec.ranked:
        if p.move.kind == "add_drop":
            return p.move.drop
    return next((mo.drop for mo in moves if mo.kind == "add_drop"), None)
