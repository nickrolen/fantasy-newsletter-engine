"""
advice_live.py -- advice v2 on the live inputs, every run that prices (V2).

claude/HANDOFF_ADVICE_V2_2026-11-11.md is the brief; claude/ADVICE_V2_DESIGN.md
the decisions. modules/advice_v2 is the engine and reads nothing; this module
is the ONLY place advice reads a file or writes one.

    build(base, now)              -> (MondayInputs, Horizon, meta) from the live files
    run_step(base, now, ...)      the nightly run's step "advice": build, advise_all,
                                  write both outputs; never stops the run (below)
    read_latest(base)             output/advice_latest.json, checked
    hub_view(latest, power_rows)  the hub's advice view (strings only)

THE INPUTS (V2 s.3), each from one place:
  - the clock: the fantasy week holding `now` and its Monday window close
    (price_lock.window_close) -> advice_v2.horizon_for: the Monday move before
    the close, the chat move after (rule 7);
  - rosters and IL slots: Yahoo's (config/ROSTERS.json, data/IL_SLOTS.json, as
    synced), with the move ledger's pending moves applied for the horizon
    weeks they affect (move_ledger.rosters_after, the checklist's order): a
    pending claim is on its manager's roster from its window (rule 10), a
    pending chat drop off his;
  - the pool: PLAYERLIST minus every roster as it will stand in the horizon's
    first week, minus every pending claim of any window (rule 10: reserved at
    once). A pending chat drop is in it when his window is the horizon's first
    week (rule 11); on a Monday, a drop effective NEXT Monday is still on his
    team this week, so he is not;
  - adds left: move_ledger.adds_used for the move's budget week -- the week
    the move is MADE in (a Monday move: this week; a chat claim: this week too,
    rule 7). It is transaction_rulings.adds_by_budget_week (the one counter,
    invariant 10a) plus the week's pending claims not yet in Yahoo; never a
    second count (a source test pins it);
  - tags: the latest tag record (output/tag_records.jsonl) with step 3b's
    nba_outs, anchored at its fetch date (its league day);
  - injury entries: through the projections (load_player_projections applies
    INJURY_OVERRIDES); a chat move's IL eligibility is the plan's own rule on
    them (roster_plan.out_all_week, 44b s.5);
  - projections: the season pass's own -- the roster plan's player index
    (roster_plan.for_run: PLAYERLIST with INJURY_OVERRIDES, season-to-date
    actuals blended in by populate_actual_stats, the rostered players' objects
    from load_all_team_projections), so effective_fppg is the line's and the
    pass's. (V2 read load_player_projections alone: projection only, no
    actuals; HANDOFF_ADVICE_TITLE_TERM's check found it.)
  - the roster plan: the season pass's (roster_plan.for_run on the same data,
    team projections and tags, its known moves the ledger's), as
    advice_v2.PlanSpec: the horizon's baseline and the title term's later
    weeks are read off it, and a move is priced by rebuilding it with the move
    as known moves. Its lazily read inputs (the stakes, the keeper watch) are
    read here, so the engine reads no file;
  - keep chances: the keeper watch (drop_inputs.keep_chances, K = 5: the
    roster plan's and 18b's), for the top-4 protection (decision 3a) -- read
    through the plan's own DropContext when the plan starts this week (44a:
    one read, and the plan's activation rule and advice protect from the
    same numbers);
  - stakes: the latest priced run's, through drop_inputs.read_stakes (their one
    reader), in 18b's units;
  - opponents: SCHEDULE.json for regular-season weeks; for bracket and Cup
    weeks the bracket's pairing once it is set (bracket_opponents), else no
    matchup (no win-chance term) -- the points tie-break then ranks;
  - each team's weekly standard deviation: the team projections' (the same
    load_all_team_projections the line and the season pass read), so the
    engine's win chances carry the same team noise as the line's;
  - banked points: none. No horizon starts mid-week: a Monday move starts
    today, the window's first day, and a chat move next Monday.

THE ACTIVATION STEP (44a): when the plan activates an IL occupant at the
advised window (advice_v2.activation_step: a chat move's next Monday), each
output carries it per manager -- "activation" in advice_latest.json and the
history row, a "Step:" line in advice_show.py, the hub card's first line, and
the summary's ADVICE line -- before the pick: "Haliburton is back for week 6:
activate him and drop X. It costs no add." Nobody returning: no field, no
line (null). The drop is the plan's one activation rule's
(roster_plan.activation_drops); the pick is priced on the roster after it.

THE OUTPUTS (state, config/STATE_MANIFEST.json):
  output/advice_latest.json     the latest run's advice: per manager his move
                                and backup with every number, the reason, the
                                horizon, "also wanted by", the title-odds change,
                                the run id and its cause, and the display strings
  output/advice_history.jsonl   append-only, one row per run (V4's scorecard
                                reads it): each manager's top move and backup,
                                predicted gains, horizon, as-of; Monday's 12:01
                                nightly row is "published": true
write() is the one writer of both (a source test pins it).

A FAILURE NEVER STOPS THE RUN: advice is not a price and prices nothing; a
failed step must not keep the hub from publishing. It is loud instead: the
error is written to both outputs (the hub's view, when on, says the advice
could not be updated, and shows no stale pick), the run's "advice" block
carries it, and the run summary prints ADVICE FAILED.
"""

from __future__ import annotations

import json
import time
import traceback
from datetime import date, datetime
from pathlib import Path
from typing import Optional

LATEST_FILE = Path("output") / "advice_latest.json"
HISTORY_FILE = Path("output") / "advice_history.jsonl"
SCHEMA = 1
SWITCH_VALUES = ("off", "on")


class AdviceInputError(RuntimeError):
    """An input the advice needs is missing or contradicts another."""


# =============================================================================
# the hub switch (config advice.hub, required)
# =============================================================================

def hub_switch(cfg: dict = None) -> str:
    """league_config.json advice.hub: "off" or "on", required. Missing or
    anything else raises (UnspecifiedRule / AdviceInputError)."""
    if cfg is None:
        from .data_loader import league_rule
        v = league_rule("advice", "hub")
    else:
        if "advice" not in cfg or "hub" not in (cfg["advice"] or {}):
            from .data_loader import UnspecifiedRule
            raise UnspecifiedRule("league_config.json has no advice.hub")
        v = cfg["advice"]["hub"]
    if v not in SWITCH_VALUES:
        raise AdviceInputError(f"league_config.json advice.hub is {v!r}; it must be one of {SWITCH_VALUES}")
    return v


def show_title_odds(cfg: dict = None) -> bool:
    """league_config.json advice.show_title_odds: true or false, required.
    Missing raises UnspecifiedRule; anything but a JSON boolean raises."""
    if cfg is None:
        from .data_loader import league_rule
        v = league_rule("advice", "show_title_odds")
    else:
        if "advice" not in cfg or "show_title_odds" not in (cfg["advice"] or {}):
            from .data_loader import UnspecifiedRule
            raise UnspecifiedRule("league_config.json has no advice.show_title_odds")
        v = cfg["advice"]["show_title_odds"]
    if not isinstance(v, bool):
        raise AdviceInputError(f"league_config.json advice.show_title_odds is {v!r}; it must be true or false")
    return v


# =============================================================================
# the ledger's part: rosters per horizon week, the pool, the adds left
# =============================================================================

def ledger_view(world, rows: list, states: list, weeks: tuple, playerlist) -> dict:
    """The rosters as they will stand in each horizon week (the ledger's
    pending moves applied, move_ledger.rosters_after), the players reserved by
    a pending claim (rule 10), and the pool (rules 10-11).
    {"rosters": [{m: (active, il)}, {m: (active, il)} or None],
     "reserved": set, "pool": [names], "notes": [...]}"""
    from . import move_ledger as ml
    from .data_loader import roster_index
    w1, w2 = weeks
    out = []
    notes = []
    for w in (w1, w2):
        if w is None:
            out.append(None)
            continue
        ra = ml.rosters_after(world, rows, states, w)
        notes += ra["notes"]
        out.append({m: (tuple(n for n in v if n not in set(ra["il"].get(m, []))), tuple(ra["il"].get(m, [])))
                    for m, v in ra["rosters"].items()})
    live = ml.live(world, ml.entries(rows), states)
    reserved = {c["player"] for c in ml.budget_claims(live) if ml.reserved_by(live, c["player"]) is not None}
    first = out[0]
    on_roster = roster_index({m: list(a) + list(i) for m, (a, i) in first.items()})
    res_idx = roster_index({"reserved": sorted(reserved)})
    pool = [n for n in playerlist if n not in on_roster and n not in res_idx]
    return {"rosters": out, "reserved": reserved, "pool": pool, "notes": list(dict.fromkeys(notes))}


def adds_left(world, rows: list, states: list, budget_week: int, budget: int, managers) -> dict:
    """{manager: adds left in budget week `budget_week`}: the ledger's counter
    (move_ledger.adds_used: transaction_rulings.adds_by_budget_week, the one
    counter, plus the week's pending claims not yet in Yahoo). Never a second
    count."""
    from . import move_ledger as ml
    used = ml.adds_used(world, ml.entries(rows), states, int(budget_week))
    return {m: int(budget) - len(used.get(m, [])) for m in managers}


# =============================================================================
# bracket and Cup weeks: the pairing once it is set
# =============================================================================

def pairing_map(pairs, seeds: dict) -> dict:
    """{manager: (opponent, tie value)} for seeded pairs: a tied week goes to
    the higher seed (tiebreaker_rules series_week / cup_game, higher_seed)."""
    out = {}
    for a, b in pairs:
        if a not in seeds or b not in seeds:
            raise AdviceInputError(f"no seed for {a} or {b}")
        hi = a if int(seeds[a]) < int(seeds[b]) else b
        out[a] = (b, 1.0 if hi == a else 0.0)
        out[b] = (a, 1.0 if hi == b else 0.0)
    return out


def series_results(pairs, scores_by_week: dict, seeds: dict) -> list:
    """[(winner, loser)] of each best-of series over the weeks given (every
    week played; a tied week to the higher seed)."""
    out = []
    for a, b in pairs:
        wins = {a: 0, b: 0}
        for w in sorted(scores_by_week):
            s = scores_by_week[w]
            if a not in s or b not in s:
                raise AdviceInputError(f"week {w} has no score for {a} or {b}")
            if float(s[a]) == float(s[b]):
                win = a if int(seeds[a]) < int(seeds[b]) else b
            else:
                win = a if float(s[a]) > float(s[b]) else b
            wins[win] += 1
        winner = a if wins[a] > wins[b] else b
        out.append((winner, b if winner == a else a))
    return out


def bracket_opponents(data, week: int) -> dict:
    """{manager: (opponent, tie value)} for bracket or Cup week `week` once
    its pairing is set, {} before (no matchup yet: no win-chance term).
    Semifinals: the regular season fully recorded, seeded by the standings.
    Final and third place: every semifinal week played. Cup semifinals: weeks
    1 to the week before the Cup played (seeded on total points). Cup final
    and third place: the Cup semifinal played. A tie rule other than
    higher_seed raises."""
    from .data_loader import CURRENT_SEASON, league_rule, regular_season_weeks_for
    from .season_sim import recorded_weeks
    from . import simulator_playoff_odds as po
    from . import simulator_cup_odds as co
    for k in ("series_week", "cup_game"):
        if league_rule("tiebreaker_rules", k) != "higher_seed":
            raise AdviceInputError(f"tiebreaker_rules.{k} is {league_rule('tiebreaker_rules', k)!r}: "
                                   "advice models higher_seed only")
    last_reg = int(regular_season_weeks_for(CURRENT_SEASON))
    rounds, crounds = po.bracket_rounds(), co.cup_rounds()

    def within(rng):
        return rng is not None and int(rng[0]) <= int(week) <= int(rng[1])

    def played(weeks):
        out = {}
        for w in weeks:
            s = po.resolve_completed_week(data, w)
            if not s:
                return None
            out[w] = s
        return out

    def semis(seeds):
        pairs, _why = po.get_semifinal_matchups(data, seeds)
        return [(p["manager_a"], p["manager_b"]) for p in pairs]

    reg_done = set(range(1, last_reg + 1)) <= recorded_weeks(data, last_reg)
    semi = rounds.get(po.SEMIFINAL_ROUND)
    if within(semi):
        if not reg_done:
            return {}
        seeds = po.get_playoff_seeds(data)
        return pairing_map(semis(seeds), seeds)
    if within(rounds.get(po.FINAL_ROUND)) or within(rounds.get(po.THIRD_PLACE_ROUND)):
        sc = played(range(int(semi[0]), int(semi[1]) + 1)) if reg_done else None
        if sc is None:
            return {}
        seeds = po.get_playoff_seeds(data)
        res = series_results(semis(seeds), sc, seeds)
        return pairing_map([(res[0][0], res[1][0]), (res[0][1], res[1][1])], seeds)
    csemi = crounds.get(co.CUP_SEMIFINAL_ROUND)
    if within(csemi):
        before = range(last_reg + 1, int(csemi[0]))
        if not reg_done or played(before) is None:
            return {}
        seeds = co.get_cup_seeds(data)
        pairs, _why = co.get_cup_semifinal_matchups(data, seeds)
        return pairing_map([(p["manager_a"], p["manager_b"]) for p in pairs], seeds)
    if within(crounds.get(co.CUP_FINAL_ROUND)):
        before = range(last_reg + 1, int(csemi[0]))
        sc = played(range(int(csemi[0]), int(csemi[1]) + 1)) if reg_done and played(before) else None
        if sc is None:
            return {}
        seeds = co.get_cup_seeds(data)
        pairs, _why = co.get_cup_semifinal_matchups(data, seeds)
        res = series_results([(p["manager_a"], p["manager_b"]) for p in pairs], sc, seeds)
        return pairing_map([(res[0][0], res[1][0]), (res[0][1], res[1][1])], seeds)
    return {}


def phase_of(week: int) -> str:
    """"regular_season", "playoffs" or "cup" for a fantasy week."""
    from .data_loader import CURRENT_SEASON, regular_season_weeks_for
    from .simulator_playoff_odds import bracket_weeks
    if int(week) <= int(regular_season_weeks_for(CURRENT_SEASON)):
        return "regular_season"
    if int(week) in bracket_weeks():
        return "playoffs"
    return "cup"


def opponents_for(data, weeks, managers) -> tuple:
    """({manager: {week: opponent or None}}, {(manager, week): tie value}).
    Regular season: SCHEDULE.json (a manager with no matchup raises); a tied
    week is half a win (tiebreaker_rules.tie_win_value). Bracket and Cup:
    bracket_opponents."""
    from .data_loader import league_rule
    opp = {m: {} for m in managers}
    ties = {}
    half = float(league_rule("tiebreaker_rules", "tie_win_value"))
    for w in weeks:
        if w is None:
            continue
        if phase_of(w) == "regular_season":
            entry = next((x for x in data.schedule.get("weeks", []) if int(x["week"]) == int(w)), None)
            if entry is None:
                raise AdviceInputError(f"SCHEDULE.json has no week {w}")
            for mu in entry.get("matchups") or []:
                a, b = mu["manager_a"], mu["manager_b"]
                opp[a][w], opp[b][w] = b, a
                ties[(a, w)] = ties[(b, w)] = half
            missing = [m for m in managers if w not in opp[m]]
            if missing:
                raise AdviceInputError(f"SCHEDULE.json week {w} has no matchup for {', '.join(missing)}")
        else:
            bo = bracket_opponents(data, w)
            for m in managers:
                if m in bo:
                    opp[m][w] = bo[m][0]
                    ties[(m, w)] = bo[m][1]
                else:
                    opp[m][w] = None
    return opp, ties


# =============================================================================
# the inputs, from the live files
# =============================================================================

def build(base_path, now: datetime, data=None):
    """(MondayInputs, Horizon, meta) as of `now` (the league clock), or
    (None, None, meta) when no window is left this season. Reads only."""
    from . import advice_v2 as av, drop_inputs as di, injured_drop, move_ledger as ml, price_lock
    from . import tag_records, week_state as ws
    from .data_loader import (CURRENT_SEASON, MANAGERS, PlayerIndex, load_all_data,
                              regular_season_weeks_for)
    from . import roster_plan
    from .hub_state import free_agent_tags
    from .projections import load_all_team_projections
    from .simulator_betting import schedule_week_dates
    from .simulator_playoff_odds import bracket_weeks
    base = Path(base_path)
    if now.tzinfo is None:
        raise AdviceInputError("advice runs on the league clock (an aware datetime)")
    data = data or load_all_data(base, current_week=None)
    today = now.date()
    week = ws.week_for_date(data, today)
    wk_dates = {int(w): list(v) for w, v in schedule_week_dates(data).items()}
    close = price_lock.window_close(wk_dates[week][0], data.nba_schedule)
    hz = av.horizon_for(now, week, wk_dates, close)
    meta = {"week": week, "week_first_day": wk_dates[week][0].isoformat(),
            "closes": close.isoformat(timespec="minutes")}
    if hz is None:
        meta["note"] = "no window is left this season"
        return None, None, meta
    managers = list(MANAGERS)
    # --- the ledger: rosters per horizon week, the pool, adds left
    world = ml.World.from_base(base, now=now, data=data)
    rows, states = ml.read_rows(base), ml.read_states(base)
    pl_names = [str(n) for n in data.playerlist["player_name"]]
    lv = ledger_view(world, rows, states, hz.weeks, pl_names)
    first, second = lv["rosters"]
    active_cap, il_cap, budget = ml.roster_shape()
    left = adds_left(world, rows, states, hz.budget_week, budget, managers)
    # --- the season pass's roster plan, and its projections (actuals blended)
    tag_row = tag_records.latest(base)
    tags = tag_records.as_tags(tag_row)
    tps = load_all_team_projections(data)
    run = roster_plan.for_run(data, tps, tags, today=today, now=now)   # 44b s.2: the run's clock
    drops = run.args["drops"]
    if drops is not None and drops.note() is None:      # read now: the engine reads no file
        for m in managers:
            drops.keep(m)
    pidx = run.args["players"]
    named = set()
    for ro in (first, second):
        for m, (a, i) in (ro or {}).items():
            named.update(a)
            named.update(i)
    proj, unprojected = {}, []
    for n in sorted(named):
        p = pidx.get(n)
        if p is None:
            raise AdviceInputError(f"{n} (on a roster in the horizon) is not in data/PLAYERLIST.xlsx: "
                                   "no projection to price him")
        proj[n] = p
    pool = []
    for n in lv["pool"]:
        p = pidx.get(n)
        if p is None:
            unprojected.append(n)
            continue
        proj[n] = p
        pool.append(n)
    # --- the tags, anchored at their fetch date
    anchor = date.fromisoformat(tag_row["league_day"])
    yahoo_rostered = [n for v in data.get_current_rosters().values() for n in v]
    statuses = dict(tag_records.hub_tags(tag_row, yahoo_rostered))
    others = [n for n in sorted(named) if n not in set(yahoo_rostered)] + pool
    statuses.update({n: t for n, t in free_agent_tags(tag_row, others).items()
                     if t not in (None, "HEALTHY")})
    nba_outs = dict((tag_row.get("tags") or {}).get("nba_outs") or {})
    # --- keep chances (decision 3a): the keeper watch; a player joining by a
    # pending claim has none yet, a player traded in carries his. Through the
    # plan's DropContext when the plan starts this week (the same call, week - 1):
    # one read, and the activation rule and advice protect from the same numbers
    if drops is not None and int(run.start_week) == int(week):
        keep_all = {m: dict(drops.keep(m)) for m in managers}
    else:
        keep_all = di.keep_chances(data, base, week - 1)
    by_player = {}
    for m, d in keep_all.items():
        for n, c in d.items():
            by_player[n] = c
    kidx = PlayerIndex(by_player)
    keep, joining = {}, {}
    for m in managers:
        names = set(first[m][0]) | set(first[m][1])
        if second is not None:
            names |= set(second[m][0]) | set(second[m][1])
        keep[m], joining[m] = {}, set()
        for n in sorted(names):
            c = kidx.get(n)
            if c is None:
                joining[m].add(n)
            else:
                keep[m][n] = float(c)
        on_yahoo = set(data.get_current_rosters().get(m, []))
        stray = [n for n in joining[m] if n in on_yahoo]
        if stray:
            raise AdviceInputError(f"the keeper watch has no keep chance for {', '.join(stray)} ({m}'s "
                                   "roster): protection (decision 3a) cannot be decided")
    # --- IL eligibility at the horizon's window (rule 2)
    actives = [n for m in managers for n in first[m][0]]
    if hz.kind == av.MONDAY:
        il_ok = av.monday_il_eligible(actives, statuses)
    else:
        # 44b s.5: the plan's rule (roster_plan.out_all_week) on the plan's own projections
        il_ok = av.chat_il_eligible(actives, proj, hz.weeks[0])
    # --- stakes and opponents
    blob, note = di.read_stakes(base)
    if blob is None:
        raise AdviceInputError(f"no usable stakes: {note}")
    last_reg = int(regular_season_weeks_for(CURRENT_SEASON))
    stakes = {m: di.team_stakes(blob, m, hz.weeks[0], last_regular=last_reg, bracket=bracket_weeks(),
                                path=str(di.stakes_path(base)))
              for m in managers}
    opponents, ties = opponents_for(data, hz.weeks, managers)
    missing_sd = [m for m in managers if m not in tps]
    if missing_sd:
        raise AdviceInputError(f"no team projection (weekly std dev) for {', '.join(missing_sd)}")
    weekly_sd = {m: float(tps[m].weekly_std_dev) for m in managers}
    later = {}
    if second is not None:
        for m in managers:
            if (set(second[m][0]), set(second[m][1])) != (set(first[m][0]), set(first[m][1])):
                later[m] = second[m]
    inp = av.assemble(horizon=hz, season=CURRENT_SEASON, nba_schedule=data.nba_schedule,
                      schedule_weeks=data.schedule["weeks"], durability_prior=data.durability_prior,
                      anchor=anchor, projections=proj, statuses=statuses, rosters=first,
                      shape=(active_cap, il_cap), adds_left=left, keep=keep, opponents=opponents,
                      pool=pool, il_eligible=il_ok, later=later, joining=joining,
                      reserved=frozenset(lv["reserved"]), stakes=stakes,
                      drop_config=injured_drop.from_rules(), tie_value=ties, nba_outs=nba_outs,
                      weekly_sd=weekly_sd, plan=av.PlanSpec(dict(run.args)))
    meta.update({"anchor": anchor.isoformat(), "tags_taken_at": tag_row["taken_at"],
                 "tags_run": tag_row["run_id"], "pool": len(pool), "unprojected_free_agents": len(unprojected),
                 "reserved": sorted(lv["reserved"]), "ledger_notes": lv["notes"],
                 "stakes_as_of": blob.get("as_of"), "stakes_run": blob.get("run_id"),
                 "joining": {m: sorted(v) for m, v in joining.items() if v},
                 "later": sorted(later), "budget": budget,
                 "plan": {"start_week": run.start_week, "known": run.args.get("known") or {},
                          "notes": list(run.notes)},
                 "weekly_sd": {m: round(v, 1) for m, v in weekly_sd.items()}})
    return inp, hz, meta


# =============================================================================
# what is written
# =============================================================================

def _move_dict(p, score, inputs, hz, cfg) -> dict:
    regular = phase_of(hz.weeks[0]) == "regular_season"
    no_stakes = phase_of(hz.weeks[0]) == "cup"
    t = None if no_stakes else p.title_odds(cfg, regular)
    mo = p.move
    return {"kind": mo.kind, "add": mo.add, "drop": mo.drop, "to_il": mo.to_il,
            "followup_drop": p.followup_drop, "followup_standin": bool(p.followup_standin),
            "describe": mo.describe(),
            "score": round(float(score), 6), "flat": bool(p.flat()),
            "dwp": [round(x, 6) for x in p.dwp],
            "wp_base": [None if x is None else round(x, 6) for x in p.wp_base],
            "dpts": [round(x, 3) for x in p.dpts], "dstarts": [round(x, 3) for x in p.dstarts],
            "dT_horizon": round(p.dT_horizon, 6), "dT_later": round(p.dT_later, 6),
            "dT_rs": round(p.dT_rs, 6), "dT_po": round(p.dT_po, 6),
            "dpts_later": round(p.dpts_later, 3),
            "title_odds": None if t is None else round(t, 6),
            "title_label": None if no_stakes else ("title odds" if regular else "playoff title odds"),
            "reason": p.reason()}


def _pct(x: float) -> str:
    return f"{100.0 * x:+.1f}%".replace("-", "\u2212")


def _md(d: date) -> str:
    return f"{d:%a} {d:%m-%d}"


def move_text(m: dict) -> str:
    """'Add X, drop Y' or the IL step, in words."""
    k = m["kind"]
    if k == "add_drop":
        return f"Add {m['add']}, drop {m['drop']}"
    if k == "add_open":
        return f"Add {m['add']} (open roster spot)"
    if k == "il_add":
        return f"Move {m['to_il']} to an open IL slot, add {m['add']}"
    if k == "il_swap":
        return f"Drop {m['drop']} from the IL slot, move {m['to_il']} into it, add {m['add']}"
    raise AdviceInputError(f"unknown move kind {k!r}")


def numbers_text(m: dict, horizon: dict, opponents: dict, *, show_title: bool) -> str:
    """'+6.0% vs Hayden this week, +2.0% vs Benton next week \u00b7 title odds +0.4%'.
    show_title (advice.show_title_odds): False leaves the title-odds part out
    entirely -- the hub shows no number; advice_show.py says "hidden"."""
    names = ("this week", "next week") if horizon["kind"] == "monday" else ("next week", "the week after")
    bits = []
    for k, w in enumerate(horizon["weeks"]):
        if w is None:
            bits.append(f"no week {horizon['weeks'][0] + 1} this season")
            continue
        o = opponents.get(str(w))
        if o is None:
            bits.append(f"no matchup set {names[k]} (week {w})")
        else:
            bits.append(f"{_pct(m['dwp'][k])} vs {o} {names[k]}")
    s = ", ".join(bits)
    if not show_title:
        return s
    if m["title_label"] is None:
        s += " \u00b7 no title odds at stake in the Cup"
    else:
        s += f" \u00b7 {m['title_label']} {_pct(m['title_odds'] or 0.0)}"
    return s


def reason_text(m: dict, horizon: dict) -> str:
    """The reason line in the league's terms, from Priced.reason()'s pieces:
    startable games, then points when the matchups are decided."""
    names = ("this week", "next week") if horizon["kind"] == "monday" else ("next week", "the week after")
    st = m["dstarts"]
    tot = st[0] + st[1]
    word = "start" if abs(round(tot, 1)) == 1.0 else "starts"
    parts = [f"{tot:+.1f} {word} ({names[0]} {st[0]:+.1f}, {names[1]} {st[1]:+.1f})".replace("-", "\u2212")]
    pts = m["dpts"][0] + m["dpts"][1]
    parts.append(f"{pts:+.0f} pts".replace("-", "\u2212"))
    if m["flat"]:
        parts.append("the matchups are as good as decided, so it is ranked on points")
    return "; ".join(parts)


def followup_text(m: dict, horizon: dict) -> str:
    if not m.get("followup_drop"):
        return ""
    w2 = horizon["weeks"][1]
    if m.get("followup_standin"):
        return (f"Then, in week {w2}'s window: when {m['to_il']} returns, drop the replacement-level "
                f"pickup the plan assumes by then ({m['followup_drop']}).")
    return f"Then, in week {w2}'s window: drop {m['followup_drop']} when {m['to_il']} returns."


def _and(names) -> str:
    names = list(names)
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def step_text(step: dict) -> str:
    """The activation step in words (44a): "Haliburton is back for week 6:
    activate him and drop X. It costs no add." """
    back, drops = list(step["back"]), list(step["drops"])
    one = len(back) == 1
    s = f"{_and(back)} {'is' if one else 'are'} back for week {step['week']}: activate {'him' if one else 'them'}"
    s += f" and drop {_and(drops)}" if drops else " (there is room: nobody goes)"
    return s + ("" if s.endswith(".") else ".") + " It costs no add."


def step_dict(step) -> Optional[dict]:
    """advice_latest.json's "activation" for one manager, or None."""
    if not step:
        return None
    if step.get("standins"):
        # the advised window is the plan's first: no stand-in exists before it
        raise AdviceInputError(f"the activation step drops a plan stand-in {step['standins']}: the advised "
                               "window must be the plan's first")
    return {"week": int(step["week"]), "back": list(step["back"]), "drops": list(step["drops"]),
            "text": step_text(step)}


def cause_text(mode: str, cause: Optional[str]) -> str:
    if mode == "nightly":
        return "the nightly run"
    if mode == "pretip":
        return "Monday's pre-tip run"
    c = str(cause or "").strip()
    for pre in ("Monday move: ", "Monday moves: "):
        if c.startswith(pre):
            c = c[len(pre):]
    return c or mode


def _clock(dt: datetime) -> str:
    h = dt.strftime("%I").lstrip("0") or "12"
    return f"{h}:{dt.strftime('%M')} {dt.strftime('%p')}"


def latest_payload(*, run_id: str, mode: str, cause: Optional[str], now: datetime, inputs, hz, meta: dict,
                   advice: dict, weighting: str, settings, seconds: dict) -> dict:
    from . import injured_drop
    cfg = inputs.drop_config or injured_drop.from_rules()
    horizon = {"kind": hz.kind, "label": hz.label(), "weeks": list(hz.weeks),
               "effective": hz.effective.isoformat(), "budget_week": hz.budget_week,
               "closes": hz.closes.isoformat(timespec="minutes")}
    show = show_title_odds()
    mans = {}
    for m, a in sorted(advice.items()):
        st = inputs.managers[m]
        opps = {str(w): st.opponents.get(w) for w in hz.weeks if w is not None}
        e = {"adds_left": st.adds_left, "opponents": opps, "also_wanted_by": list(a.also_wanted_by),
             "activation": step_dict(a.step),
             "move": None, "backup": None, "note": a.rec.note, "bar": a.rec.bar if a.rec.bar != float("inf") else None}
        for key, p, s in (("move", a.top, a.top_score), ("backup", a.backup, a.backup_score)):
            if p is None:
                continue
            d = _move_dict(p, s, inputs, hz, cfg)
            d["text"] = {"move": move_text(d), "numbers": numbers_text(d, horizon, opps, show_title=show),
                         "reason": reason_text(d, horizon), "followup": followup_text(d, horizon)}
            e[key] = d
        if a.top is None:
            e["empty"] = ("No adds left this week (week {}'s budget)".format(hz.budget_week)
                          if st.adds_left <= 0 else
                          "No move clears the last add's bar" if a.rec.note.startswith("nothing clears")
                          else "No move beats standing pat")
        mans[m] = e
    return {"schema": SCHEMA, "run_id": run_id, "mode": mode, "cause": cause,
            "cause_text": cause_text(mode, cause), "as_of": now.isoformat(timespec="seconds"),
            "updated_text": f"Updated {_clock(now)} after {cause_text(mode, cause)}.",
            "league_day": now.date().isoformat(), "horizon": horizon, "weighting": weighting,
            "settings": dict(settings.__dict__), "inputs": meta, "seconds": seconds,
            "show_title_odds": show, "managers": mans, "error": None}


def failure_payload(*, run_id: str, mode: str, cause: Optional[str], now: datetime, error: str,
                    seconds: dict, meta: dict = None) -> dict:
    return {"schema": SCHEMA, "run_id": run_id, "mode": mode, "cause": cause,
            "cause_text": cause_text(mode, cause), "as_of": now.isoformat(timespec="seconds"),
            "updated_text": f"Advice could not be updated at {_clock(now)} ({cause_text(mode, cause)}).",
            "league_day": now.date().isoformat(), "horizon": None, "weighting": None, "settings": None,
            "inputs": meta or {}, "seconds": seconds, "managers": {}, "error": error}


def no_window_payload(*, run_id, mode, cause, now, meta, seconds) -> dict:
    p = failure_payload(run_id=run_id, mode=mode, cause=cause, now=now, error=None, seconds=seconds, meta=meta)
    p["updated_text"] = f"Updated {_clock(now)} after {cause_text(mode, cause)}."
    p["season_over"] = "No window is left this season: no pickup joins a roster again."
    return p


def _hist_move(d: Optional[dict]) -> Optional[dict]:
    if d is None:
        return None
    keep = ("kind", "add", "drop", "to_il", "followup_drop", "score", "flat", "dwp", "wp_base", "dpts",
            "dstarts", "dT_horizon", "dT_later", "dT_rs", "dT_po", "dpts_later", "title_odds")
    return {**{k: d[k] for k in keep}, "followup_standin": bool(d.get("followup_standin"))}


def history_row(payload: dict, *, published: bool) -> dict:
    """One row per run (V4's scorecard): enough to score later -- the move,
    its predicted gains, the horizon, the as-of, the opponents."""
    return {"schema": SCHEMA, "run_id": payload["run_id"], "mode": payload["mode"],
            "cause": payload["cause"], "as_of": payload["as_of"], "league_day": payload["league_day"],
            "published": bool(published), "horizon": payload["horizon"],
            "anchor": (payload.get("inputs") or {}).get("anchor"),
            "managers": {m: {"adds_left": e["adds_left"], "opponents": e["opponents"],
                             "also_wanted_by": e["also_wanted_by"], "note": e["note"],
                             "activation": e.get("activation"),
                             "top": _hist_move(e["move"]), "backup": _hist_move(e["backup"])}
                         for m, e in payload["managers"].items()},
            "error": payload["error"]}


def write(base_path, payload: dict, row: dict) -> None:
    """THE ONE WRITER of output/advice_latest.json and output/advice_history.jsonl."""
    from .data_loader import atomic_write_json
    from .jsonl_log import append_rows
    base = Path(base_path)
    atomic_write_json(base / LATEST_FILE, payload, indent=1)
    append_rows(base / HISTORY_FILE, [row])


def read_latest(base_path=".") -> dict:
    p = Path(base_path) / LATEST_FILE
    if not p.is_file():
        raise AdviceInputError(f"{LATEST_FILE.as_posix()} is missing: the advice step has not run yet "
                               "(python scripts\\state.py pull, or the next nightly run)")
    blob = json.loads(p.read_text(encoding="utf-8"))
    if blob.get("schema") != SCHEMA:
        raise AdviceInputError(f"{LATEST_FILE.as_posix()} has schema {blob.get('schema')!r}, not {SCHEMA}")
    for k in ("run_id", "as_of", "managers", "error", "updated_text"):
        if k not in blob:
            raise AdviceInputError(f"{LATEST_FILE.as_posix()} has no {k!r}")
    return blob


def read_history(base_path=".") -> list:
    from .jsonl_log import read_rows
    return read_rows(Path(base_path) / HISTORY_FILE, HISTORY_FILE.as_posix())


# =============================================================================
# the run's step
# =============================================================================

def is_published(mode: str, now: datetime, hz, week_first_day: Optional[date]) -> bool:
    """Monday's 12:01 run: the nightly run on a window day (decision 4)."""
    return (mode == "nightly" and hz is not None and hz.kind == "monday"
            and week_first_day is not None and now.date() == week_first_day)


def summary_lines(payload: dict) -> list:
    """One line per manager: his top move (the run summary)."""
    if payload.get("error"):
        return [f"ADVICE FAILED: {payload['error'].splitlines()[0]}"]
    if payload.get("season_over"):
        return [f"ADVICE: {payload['season_over']}"]
    hz = payload["horizon"]
    out = []
    for m, e in payload["managers"].items():
        st = e.get("activation")
        head = f"ADVICE {m} ({hz['label']}): " + (f"Step: {st['text']} Then: " if st else "")
        if e["move"] is None:
            out.append(head + f"{e.get('empty', 'no move')}")
            continue
        mv = e["move"]
        line = head + f"{mv['text']['move']} -- {mv['text']['numbers']}"
        if e["also_wanted_by"]:
            line += f" [also wanted by {', '.join(e['also_wanted_by'])}]"
        out.append(line)
    return out


def run_step(base_path, now: datetime, *, run_id: str, mode: str, cause: Optional[str], data=None,
             settings=None, echo=print) -> dict:
    """Build, advise, write. Returns {"block": the run record's "advice"
    block, "detail": the step's line, "lines": the run summary's lines}. Any
    error is recorded (both outputs, the block) and the run goes on."""
    from . import advice_v2 as av
    settings = settings or av.Settings()
    t0 = time.perf_counter()
    seconds = {}
    meta = {}
    published = False
    try:
        inp, hz, meta = build(base_path, now, data=data)
        seconds["inputs"] = round(time.perf_counter() - t0, 2)
        if inp is None:
            payload = no_window_payload(run_id=run_id, mode=mode, cause=cause, now=now, meta=meta,
                                        seconds=seconds)
        else:
            t1 = time.perf_counter()
            advice = av.advise_all(inp, settings, av.RECOMMENDED)
            seconds["engine"] = round(time.perf_counter() - t1, 2)
            payload = latest_payload(run_id=run_id, mode=mode, cause=cause, now=now, inputs=inp, hz=hz,
                                     meta=meta, advice=advice, weighting=av.RECOMMENDED.name,
                                     settings=settings, seconds=seconds)
            published = is_published(mode, now, hz, date.fromisoformat(meta["week_first_day"]))
    except Exception as e:                       # noqa: BLE001 -- recorded loudly, never stops the run
        err = f"{type(e).__name__}: {e}"
        seconds["failed_after"] = round(time.perf_counter() - t0, 2)
        payload = failure_payload(run_id=run_id, mode=mode, cause=cause, now=now, error=err,
                                  seconds=seconds, meta=meta)
        payload["traceback"] = traceback.format_exc().splitlines()[-12:]
    seconds["total"] = round(time.perf_counter() - t0, 2)
    payload["seconds"] = seconds
    payload["published"] = published
    write(base_path, payload, history_row(payload, published=published))
    lines = summary_lines(payload)
    block = {"error": payload["error"], "published": published, "seconds": seconds,
             "horizon": (payload.get("horizon") or {}).get("label"),
             "top": {m: (e["move"] or {}).get("describe") for m, e in payload["managers"].items()}}
    if payload["error"]:
        detail = f"FAILED (recorded; the run goes on): {payload['error']}"
    elif payload.get("season_over"):
        detail = payload["season_over"]
    else:
        detail = (f"{payload['horizon']['label']}, weeks {payload['horizon']['weeks']}, "
                  f"{seconds.get('total')} s: "
                  + "; ".join(f"{m} {(e['move'] or {}).get('describe') or e.get('empty')}"
                              for m, e in payload["managers"].items()))
    return {"block": block, "detail": detail, "lines": lines, "payload": payload}


# =============================================================================
# the hub's view (strings only: the page computes nothing)
# =============================================================================

def _move_players(m: dict, fields) -> list:
    """The players a move's text names, in field order (hub_cards, task 40)."""
    return [m[f] for f in fields if m.get(f)]


def hub_view(latest: dict, power_rows: list) -> dict:
    """One card per manager in power-rankings order: the heading (Monday move /
    chat move), the move and its follow-up, the numbers, the reason, "also
    wanted by", the backup, or "No move beats standing pat"; under it the
    update line. A failed run's view says so and shows no pick."""
    cards = []
    hz = latest.get("horizon") or {}
    for r in power_rows:
        m = r["manager"]
        card = {"manager": m, "team": r["team"], "heading": hz.get("label") or "", "step": "", "move": "",
                "followup": "",
                "numbers": "", "reason": "", "also": "", "backup": "", "empty": "",
                "players": {}}         # task 40: the players each text names (hub_cards makes them tappable)
        if latest.get("error"):
            card["empty"] = "Advice could not be updated."
        elif latest.get("season_over"):
            card["empty"] = latest["season_over"]
        else:
            e = latest["managers"].get(m)
            if e is None:
                raise AdviceInputError(f"{LATEST_FILE.as_posix()} has no advice for {m}")
            st = e.get("activation")
            if st:
                card["step"] = st["text"]
                card["players"]["step"] = list(st["back"]) + list(st["drops"])
            if e["move"] is None:
                card["empty"] = e.get("empty") or "No move beats standing pat"
            else:
                t = e["move"]["text"]
                card.update(move=t["move"], followup=t["followup"], numbers=t["numbers"], reason=t["reason"])
                card["players"]["move"] = _move_players(e["move"], ("add", "drop", "to_il"))
                if t["followup"]:
                    card["players"]["followup"] = _move_players(
                        e["move"], ("to_il",) if e["move"].get("followup_standin") else ("followup_drop", "to_il"))
                if e["also_wanted_by"]:
                    card["also"] = "Also wanted by " + " and ".join(e["also_wanted_by"])
                if e["backup"] is not None:
                    b = e["backup"]["text"]
                    card["backup"] = f"If he's gone: {b['move']} ({b['numbers']})"
                    card["players"]["backup"] = _move_players(e["backup"], ("add", "drop", "to_il"))
        cards.append(card)
    foot = latest["updated_text"]
    if latest.get("error"):
        foot += " The last pick is not shown: it may no longer stand."
    return {"title": "Advice", "link": "Advice", "cards": cards, "foot": foot,
            "note": ("The engine's pick for each team: win chance this week and next for a Monday move, "
                     "next week and the week after for a chat move, plus the change in title odds. "
                     "A move that costs title odds is held back; one that gains them gets no credit "
                     "for it. Advice, not a rule.")}
