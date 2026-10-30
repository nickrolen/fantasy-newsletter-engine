"""
roster_plan.py -- the simulator plays the league's IL rules.

    build(...)      the pure plan: {week: {manager: {active, il, added, dropped}}}
    for_run(data, team_projections, statuses)
                    the plan for one run, from data/IL_SLOTS.json, cached
    week_rosters(run, team_projections, week)
                    (that week's team projections, {manager: IL names})

The rules are LEAGUE_RULES.md "The 2026-27 IL and transaction rules" (Nick,
10-28), rules 1-9. The ones the plan plays:

  - 15 active spots plus 2 IL slots (league_structure).
  - ONE move window per fantasy week, its first day (rules 4, 7, 9). Windows
    follow the FANTASY WEEKS, never the calendar: week 7 runs 11-30 -> 12-13
    and has one window, 11-30; 12-07 is not one. Every move takes effect from
    the window day, for the whole fantasy week.
  - IL slots are fixed for the week, both directions (rule 5): an IL
    occupant scores nothing that week, healthy or not, and a player who
    returns midweek from IL sits out the rest of it and is activated at the
    next window.
  - IL-eligible: roster_moves.il_eligible_tags (O and OFS; rule 2). A player
    with a live INJURY_OVERRIDES entry is treated as O -- any future tag is
    unknowable.
  - Every pickup costs one of weekly_add_budget adds (rule 6); no waivers
    (rule 8).

THE PLAN, at each window after the current week, for every manager alike
(the order they are taken in cannot matter):
  1. ACTIVATE every IL occupant available from the window day (no override,
     or its return_date on or before the day). Over 15 active: drop the
     lowest-projected active players (effective_fppg, stand-ins included)
     until 15.
  2. PLACE ON IL every active player whose override has him out for the whole
     week, longest return first, into the open slots. The rest stay active
     and do not play, as before.
  3. FILL every empty active spot up to 15 with stand-ins, at most
     weekly_add_budget per fantasy week (Nick 10-28: everyone keeps all 15
     filled). A spot the budget cannot reach waits for the next window.
The current week (the IL file's) is locked: IL as the file says, its
occupants masked out for the week, no moves. Weeks before it are untouched.

Only overrides move anyone: tag-chain and hazard absences are short and
differ by iteration, and one plan is shared by every iteration, the season
pass and every betting line. "Projected" is the projection (effective_fppg),
never the persistent-error multiplier m. Real pickups and trades arrive
through the roster sync, as before.

REPLACEMENT LEVEL: the PLAYERLIST players on nobody's roster as the window
opens (before its drops), with no override covering the week and not OFS
(and not tagged O at the first window after the tags were read), ranked by
effective_fppg; the level is the roster_moves.replacement_rank-th (4:
"something like the 3rd-5th best", Nick 10-28). A pickup is a STAND-IN at
that level, never a named free agent (option B, Nick 10-28): it takes the
positions and NBA team of the injured player it covers, or for an open spot
of the rank-th free agent; the durability prior's median GP; tau at zero
games. Its name ("Replacement for Anthony Edwards (35.2)", "Replacement for
open spot 1, Hayden (35.2)") is its draw key. When the real pickup syncs,
the real player replaces him: the plan is rebuilt from ROSTERS.json.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

IL_FILE = Path("data") / "IL_SLOTS.json"


class ILSlotsError(RuntimeError):
    """The IL file is missing, stale or names someone who is not rostered."""


class UntaggedPoolPlayer(RuntimeError):
    """A free agent who could set the stand-in level has no Yahoo tag."""


# =============================================================================
# the rules, read -- never defaulted
# =============================================================================

def rules() -> dict:
    from .data_loader import LEAGUE_STRUCTURE, league_rule
    tags = league_rule("roster_moves", "il_eligible_tags")
    rank = int(league_rule("roster_moves", "replacement_rank"))
    if rank < 1:
        raise ValueError(f"roster_moves.replacement_rank must be >= 1, not {rank}")
    return {"active_spots": int(LEAGUE_STRUCTURE["starters"]) + int(LEAGUE_STRUCTURE["bench"]),
            "il_slots": int(LEAGUE_STRUCTURE["il_slots"]),
            "add_budget": int(LEAGUE_STRUCTURE["weekly_add_budget"]),
            "il_eligible_tags": {str(t).upper() for t in tags},
            "replacement_rank": rank}


# The order managers are handed to build(). It cannot change the plan: every
# manager in a window sees the same pre-drop pool and a stand-in takes nobody
# from it. A test reverses it and asserts the plan and the title odds are
# bit-identical.
def pick_order() -> list:
    from .data_loader import MANAGERS
    return list(MANAGERS)


# =============================================================================
# the input: who is in an IL slot now
# =============================================================================

def write_il_slots(base_path, slots: dict, fantasy_week: int, fetched_at: datetime = None) -> Path:
    """Written by the roster sync (sync_transactions.py) from Yahoo's live
    selected_position. Gitignored, like ROSTERS.json."""
    from .data_loader import atomic_write_json
    path = Path(base_path) / IL_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(path, {
        "fetched_at": (fetched_at or datetime.now()).isoformat(timespec="seconds"),
        "fantasy_week": int(fantasy_week),
        "slots": {m: sorted(v) for m, v in sorted(slots.items())},
        "_comment": "Who sits in an IL slot, from Yahoo's live roster (selected_position). "
                    "Written by scripts/sync_transactions.py; read by modules/roster_plan.py, "
                    "which refuses a file from an earlier fantasy week.",
    })
    return path


def fantasy_week_on(schedule: dict, day: date) -> int:
    for w in schedule.get("weeks", []):
        if (date.fromisoformat(str(w["start_date"])[:10]) <= day
                <= date.fromisoformat(str(w["end_date"])[:10])):
            return int(w["week"])
    raise ILSlotsError(f"{day} is in no fantasy week; there is no IL state to record")


def load_il_slots(base_path, data, today: date = None) -> dict:
    """The IL file, checked. Raises when it is missing, from an earlier
    fantasy week than today's, or names a player not on that manager's
    ROSTERS.json list (which also catches a stale ROSTERS.json). Never falls
    back to LINEUPS: on 10-26 that fallback reported nobody on IL hours after
    three players had gone there (HANDOFF_STALE_GATES)."""
    from .week_state import week_for_date
    path = Path(base_path) / IL_FILE
    if not path.is_file():
        raise ILSlotsError(f"{IL_FILE} is missing: run the roster sync "
                           "(py scripts\\sync_transactions.py --week N --apply, or --il-only)")
    blob = json.loads(path.read_text(encoding="utf-8"))
    today = today or date.today()
    now_week = week_for_date(data, today)
    if int(blob["fantasy_week"]) < now_week:
        raise ILSlotsError(f"{IL_FILE} is from fantasy week {blob['fantasy_week']} "
                           f"(fetched {blob.get('fetched_at')}) and today is in week {now_week}: "
                           "re-run the roster sync")
    return blob


def check_against_rosters(il: dict, rosters: dict) -> None:
    from .data_loader import PlayerIndex
    for manager, names in (il.get("slots") or {}).items():
        if manager not in rosters:
            raise ILSlotsError(f"{IL_FILE} names a manager {manager!r} who has no roster")
        idx = PlayerIndex({n: n for n in rosters[manager]})
        for n in names:
            if idx.get(n) is None:
                raise ILSlotsError(f"{IL_FILE}: {n} is in {manager}'s IL slot but not on his "
                                   "ROSTERS.json list -- one of the two files is stale")


def no_il(fantasy_week: int) -> dict:
    """An explicit IL state with nobody in a slot, for a world built in
    memory (tests). Production reads the file."""
    return {"fantasy_week": int(fantasy_week), "slots": {}, "fetched_at": None}


# =============================================================================
# the plan -- pure
# =============================================================================

def _out_for_week(p, week) -> bool:
    return int(week) in [int(w) for w in (getattr(p, "out_weeks", None) or [])]


def _return_date(p):
    from .absence import parse_return_date
    return parse_return_date(getattr(p, "return_date", None), getattr(p, "player_name", None))


def _available_from(p, week, day) -> bool:
    """On every game from the window day of `week`: not out for the week and
    no return date still to come."""
    if p is None:
        return True
    if _out_for_week(p, week):
        return False
    rd = _return_date(p)
    return rd is None or rd <= day


def _covered(p, week, day) -> bool:
    """An override covers the week: out for it, or back only after its window."""
    return not _available_from(p, week, day)


def _return_order(p):
    rd = _return_date(p)
    last_out = max([int(w) for w in (getattr(p, "out_weeks", None) or [])] or [0])
    return (rd or date.max, last_out)


def _proj(p) -> float:
    return float(p.effective_fppg) if p is not None else 0.0


def _canonical(managers) -> list:
    """Managers in league order (then any others by name): the plan's output
    order never depends on the order they were handed in."""
    from .data_loader import MANAGERS
    known = [m for m in MANAGERS if m in managers]
    return known + sorted(m for m in managers if m not in known)


def standin(name: str, like, level: float, gp: float):
    """A replacement-level stand-in: no named free agent, so no pickup ever
    takes a player another manager could have had, and the pickup order
    cannot matter (Nick, 10-28: option B).

    level: the replacement_rank-th effective_fppg of the pool as the window
           opens. positions and NBA team (so the schedule): `like`'s -- the
           injured player he covers, or for an open spot the rank-th free
           agent himself. gp: the durability prior's median_gp, stated, so
           his miss rate is the league median and he is never a 'fallback'.
    No games yet, so the persistent error is tau at zero games; no override,
    no tag. His name is his draw key."""
    from .projections import PlayerProjection
    return PlayerProjection(player_name=name, nba_team=like.nba_team,
                            positions=list(like.positions or []), projected_fppg=float(level),
                            projected_gp=float(gp), standin=True)


def _pool_at_open(rostered, players, week, day, start_week, tag_idx, assume_healthy) -> list:
    """[(-effective_fppg, name)] best first: the free agents AS THE WINDOW
    OPENS, before any of its drops.

    The league has no waivers -- free agents are first come, first served at
    all times (rule 8), so a player dropped in a window really is back in
    the pool at once. The pool is read before the window's drops anyway,
    because that makes the managers' order irrelevant: every manager in a
    window sees the same pool and nobody's drop reaches anybody else's
    pickup. What it costs is negligible: a window's drops are each roster's
    lowest-projected players, which almost never rank inside the top few
    free agents (10-28: the best of them, Randle at 33.2, against a 35.2
    stand-in level)."""
    pool, untagged = [], []
    for name, p in players.items():
        if rostered.get(name) is not None:
            continue
        if _covered(p, week, day):
            continue
        if p.projected_fppg <= 0:
            continue
        tag = tag_idx.get(name)
        if tag is None and not assume_healthy:
            # Raise, don't default (Nick, 10-28): an untagged free agent is
            # not a healthy one -- he may be out for the season.
            untagged.append(name)
            continue
        if tag == "OFS" or (tag == "O" and week == start_week + 1):
            continue
        pool.append((-_proj(p), name))
    if untagged:
        raise UntaggedPoolPlayer(
            f"week {week}: no Yahoo tag for {len(untagged)} free agent(s) in the stand-in pool "
            f"({', '.join(sorted(untagged)[:8])}{' ...' if len(untagged) > 8 else ''}). "
            "The tags must come from fetch_injury_statuses, which covers every PLAYERLIST free "
            "agent (Tags.free_agents); a plain dict or a pre-10-28 statuses file carries "
            "rostered players only. A run priced without tags passes Tags.none().")
    return sorted(pool)


def build(*, start_week: int, il_slots: dict, rosters: dict, windows: list, players,
          statuses: dict, rules: dict, standin_gp: float, order: list = None,
          assume_healthy: bool = False, no_standins=frozenset()) -> dict:
    """{week: {manager: {"active", "il", "added", "dropped", "waiting", "standins"}}}
    from start_week (the IL file's week, locked) through the last window.

    rosters:    {manager: [names]} -- ROSTERS.json, the spelling the roster uses
    windows:    [(week, window day)] for every week after start_week, in order
    players:    a PlayerIndex {name: PlayerProjection} over every rostered and
                PLAYERLIST player (override fields, effective_fppg)
    statuses:   {name: Yahoo tag} as of the run, for every player who can be in
                the pool: rostered players (a drop rejoins it) AND free agents.
                A pool player with no tag RAISES (UntaggedPoolPlayer) unless
                assume_healthy -- a run explicitly priced without tags.
    standin_gp: a stand-in's projected GP (the durability prior's median_gp)
    no_standins: managers who add NO stand-ins -- their open spots stay empty.
                Never the build's plan: the counterfactual the money section
                states ("without his replacement-level pickups"). Default
                empty, so every plan the engine plays is unchanged.
    order:      ignored by the result -- kept so a test can hand in any order
                and show the plan does not move
    "added" is the stand-ins added that week, "standins" their projections,
    "waiting" the open spots the add budget left for the next window.
    Raises rather than guess: an over-full start, a pool too small for
    replacement_rank, two stand-ins with one name."""
    from .data_loader import PlayerIndex
    managers = _canonical(list(order or rosters))
    extra = {}                                  # every stand-in made so far

    def P(name):
        return extra.get(name) or players.get(name)

    tags = {}
    for n, t in (statuses or {}).items():
        tags[str(n)] = str(t).upper()
    tag_idx = PlayerIndex(dict(tags))

    state = {}
    for m in managers:
        il = list((il_slots or {}).get(m, []))
        roster_idx = PlayerIndex({n: n for n in rosters.get(m, [])})
        il = [roster_idx.get(n) for n in il]
        active = [n for n in rosters.get(m, []) if n not in il]
        if len(active) > rules["active_spots"]:
            raise ValueError(f"{m} has {len(active)} active players at week {start_week}, "
                             f"more than {rules['active_spots']}: ROSTERS.json and the IL file disagree")
        if len(il) > rules["il_slots"]:
            raise ValueError(f"{m} has {len(il)} players in IL slots, more than {rules['il_slots']}")
        state[m] = {"active": active, "il": il, "standins": set(), "open_count": 0}
    plan = {int(start_week): {m: {"active": sorted(state[m]["active"]), "il": sorted(state[m]["il"]),
                                   "added": [], "dropped": [], "waiting": 0, "standins": {}}
                              for m in managers}}

    for week, day in windows:
        week = int(week)
        # The pool as the window opens -- its rostered set snapshot before any
        # manager moves; read only if somebody needs a stand-in (then it must
        # be deep enough, and every player in it tagged).
        at_open = PlayerIndex({n: n for s in state.values() for n in s["active"] + s["il"]
                               if n not in s["standins"]})
        k = rules["replacement_rank"]
        cache = {}

        def level_now(at_open=at_open, week=week, day=day, cache=cache):
            if "pool" not in cache:
                cache["pool"] = _pool_at_open(at_open, players, week, day, start_week, tag_idx,
                                              assume_healthy)
            pool = cache["pool"]
            if len(pool) < k:
                raise ValueError(f"week {week}: only {len(pool)} free agents in the pool, "
                                 f"fewer than replacement_rank {k}")
            return -pool[k - 1][0], pool[k - 1][1]
        out_week = {}
        for m in managers:
            s = state[m]
            added, dropped, made = [], [], {}
            # 1. activate; over 15, drop the lowest-projected (stand-ins too)
            back = [n for n in s["il"] if _available_from(P(n), week, day)]
            for n in back:
                s["il"].remove(n)
                s["active"].append(n)
            while len(s["active"]) > rules["active_spots"]:
                low = min(s["active"], key=lambda n: (_proj(P(n)), n))
                s["active"].remove(low)
                dropped.append(low)
            # 2. place on IL: an override that has him out all week makes him O
            if "O" not in rules["il_eligible_tags"]:
                placed = []
            else:
                out = sorted(sorted(n for n in s["active"] if _out_for_week(P(n), week)),
                             key=lambda n: _return_order(P(n)), reverse=True)  # stable: ties by name
                placed = out[:max(0, rules["il_slots"] - len(s["il"]))]
            for n in placed:
                s["active"].remove(n)
                s["il"].append(n)
            # 3. fill every empty active spot, up to the add budget: first a
            # stand-in for each IL placement (his positions and team), then
            # one per remaining open spot (the rank-th free agent's). Spots the
            # budget cannot reach wait for the next window -- the league's
            # rule, not an error.
            need = 0 if m in no_standins else rules["active_spots"] - len(s["active"])
            if need:
                level, rank_name = level_now()
                if standin_gp is None:
                    raise ValueError(f"week {week}: {m} needs a stand-in and there is no "
                                     "median GP to give him")
            covers = list(placed)[:need]
            names = []
            for n in covers:
                names.append((f"Replacement for {n} ({level:.1f})", P(n)))
            for _ in range(need - len(covers)):
                s["open_count"] += 1
                names.append((f"Replacement for open spot {s['open_count']}, {m} ({level:.1f})",
                              players.get(rank_name)))
            take = names[:rules["add_budget"]]
            if len(take) < len(names):
                s["open_count"] -= sum(1 for nm, _ in names[len(take):] if "open spot" in nm)
            for nm, like in take:
                if nm in extra:
                    raise ValueError(f"week {week}: two stand-ins named {nm!r}")
                extra[nm] = made[nm] = standin(nm, like, level, standin_gp)
                s["active"].append(nm)
                s["standins"].add(nm)
                added.append(nm)
            assert len(s["active"]) <= rules["active_spots"] and len(s["il"]) <= rules["il_slots"]
            out_week[m] = {"active": sorted(s["active"]), "il": sorted(s["il"]), "added": added,
                           "dropped": dropped, "waiting": len(names) - len(take), "standins": made}
        plan[week] = out_week
    return plan


# =============================================================================
# one run
# =============================================================================

@dataclass
class Run:
    start_week: int
    plan: dict
    players: object = field(repr=False)
    _weeks: dict = field(default_factory=dict, repr=False)
    standins: dict = field(default_factory=dict, repr=False)
    standin_gp: float = None

    def projection(self, name):
        """The projection the plan uses for `name`: a stand-in by exact name,
        else the player index."""
        return self.standins.get(name) or self.players.get(name)

    def il_for(self, week) -> dict:
        w = self.plan.get(int(week))
        return {m: set(v["il"]) for m, v in w.items()} if w else {}


def windows_for(data, start_week: int) -> list:
    """[(week, its first day)] for every fantasy week after start_week. One per
    FANTASY week -- a 14-day week has one window."""
    out = []
    for w in data.schedule.get("weeks", []):
        if int(w["week"]) > int(start_week):
            out.append((int(w["week"]), date.fromisoformat(str(w["start_date"])[:10])))
    return sorted(out)


def standin_gp(data, team_projections) -> float:
    """A stand-in's projected GP: the durability prior's median_gp (Nick
    10-28), so his miss rate is the league median. A world with no snapshot
    (source "") uses each player's own projected GP as his prior; there the
    stand-in takes the median of the rostered players' projected GP, the same
    quantity over the only population that world has."""
    import statistics
    prior = getattr(data, "durability_prior", None)
    if prior is not None and prior.source and prior.median_gp is not None:
        return float(prior.median_gp)
    gps = [float(p.projected_gp) for tp in team_projections.values() for p in tp.players.values()]
    # None: no rostered player to take it from -- build() raises if a
    # stand-in is ever needed, and a world with no rosters never needs one.
    return float(statistics.median(gps)) if gps else None


def for_run(data, team_projections: dict, statuses: dict = None, today: date = None,
            no_standins=frozenset()) -> Run:
    """The plan for this run, computed once and cached on `data`. The IL
    state is data.il_slots when the caller set it (a world built in memory),
    else data/IL_SLOTS.json under data.base_path, checked (load_il_slots)."""
    from .crn import key_string
    from .projections import load_player_projections, populate_actual_stats
    from .data_loader import PlayerIndex
    fa = getattr(statuses, "free_agents", None)
    assume = bool(getattr(statuses, "free_agents_assumed_healthy", False))
    fp = key_string(id(team_projections), *sorted(f"{k}={v}" for k, v in (statuses or {}).items()),
                    "free_agents", *sorted(f"{k}={v}" for k, v in (fa or {}).items()),
                    f"assumed={assume}", f"fa_fetched={fa is not None}",
                    "no_standins", *sorted(no_standins))
    cache = data.__dict__.setdefault("_roster_plans", {})
    hit = cache.get(fp)
    if hit is not None and hit[0] is team_projections:
        return hit[1]
    il = getattr(data, "il_slots", None)
    if il is None:
        il = load_il_slots(getattr(data, "base_path", "."), data, today)
    rosters = {m: list(tp.players) for m, tp in team_projections.items()}
    check_against_rosters(il, rosters)
    everyone = {}
    if getattr(data, "playerlist", None) is not None and len(data.playerlist):
        everyone = dict(load_player_projections(data))
        populate_actual_stats(everyone, data)
    for tp in team_projections.values():
        everyone.update(tp.players)            # the rostered objects the run already uses
    players = PlayerIndex(everyone)
    start = int(il["fantasy_week"])
    gp = standin_gp(data, team_projections)
    plan = build(start_week=start, il_slots=il.get("slots") or {}, rosters=rosters,
                 windows=windows_for(data, start), players=players,
                 statuses={**dict(fa or {}), **dict(statuses or {})}, assume_healthy=assume,
                 rules=rules(), standin_gp=gp, order=[m for m in pick_order() if m in rosters],
                 no_standins=frozenset(no_standins))
    made = {n: p for w in plan.values() for v in w.values() for n, p in v["standins"].items()}
    run = Run(start_week=start, plan=plan, players=players, standins=made, standin_gp=gp)
    cache[fp] = (team_projections, run)
    return run


def week_rosters(run: Run, team_projections: dict, week: int):
    """(team projections for `week`, {manager: IL names}) -- or the projections
    as given and no mask for a week before the plan starts."""
    from .projections import TeamProjections
    w = run.plan.get(int(week))
    if w is None:
        return team_projections, None
    hit = run._weeks.get(int(week))
    if hit is not None and hit[0] is team_projections:
        return hit[1]
    out = {}
    for m, tp in team_projections.items():
        if m not in w:
            out[m] = tp
            continue
        names = w[m]["active"] + w[m]["il"]
        players = {}
        for n in names:
            p = tp.players.get(n) if n in tp.players else run.projection(n)
            if p is None:
                raise KeyError(f"no projection for {n} ({m}, week {week})")
            players[n] = p
        if set(players) == set(tp.players):
            out[m] = tp                         # unchanged: the same object, the same caches
        else:
            out[m] = TeamProjections(m, players, weekly_std_dev=tp.weekly_std_dev,
                                     weekly_scores=list(tp.weekly_scores or []))
    res = (out, {m: set(v["il"]) for m, v in w.items() if v["il"]})
    run._weeks[int(week)] = (team_projections, res)
    return res


def format_plan(plan: dict) -> list:
    """Short lines, one per change, for a person to read."""
    lines = []
    for week in sorted(plan):
        for m, v in plan[week].items():
            bits = ["IL " + (", ".join(v["il"]) if v["il"] else "empty")]
            if v["added"]:
                bits.append("adds " + ", ".join(v["added"]))
            if v["dropped"]:
                bits.append("drops " + ", ".join(v["dropped"]))
            if v.get("waiting"):
                bits.append(f"{v['waiting']} open spot(s) wait for the next window (add budget)")
            prev = plan.get(week - 1, {}).get(m)
            changed = (v["added"] or v["dropped"] or v.get("waiting")
                       or (prev is not None and prev["il"] != v["il"]))
            if week == min(plan) or changed:
                lines.append(f"week {week:2d}  {m:8s} " + "; ".join(bits))
    return lines
