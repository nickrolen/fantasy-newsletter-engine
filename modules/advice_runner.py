"""
advice_runner.py -- wires C2/C3 (modules/advice.py) into Step 6.

This is the I/O boundary: it builds marginal_value contexts from loaded data,
reads the premise gate, and decides publish vs preview. The engine itself
reads nothing.

THREE RULES (claude/C2_C3_DESIGN.md)

  1. FAILURE NEVER REACHES THE NEWSLETTER. run_advice_safely() turns any
     exception into {"ran": False, "status": "error", ...}. Step 6, the
     stats report and the newsletter generate regardless -- this is the
     pipeline the week-1 bar exists to protect, and a test raises inside the
     engine and asserts it.

  2. PUBLISH ONLY ON CLEAR. Publishes from season.advice_publish_from_week,
     for this season, and only if scripts/validate_marginal_value.py
     recorded CLEAR. MARGINAL means talk, not ship (Nick, 10-06, before
     seeing the number: "hold me to that"). There is no override flag.

  3. NEVER SILENT. Before the launch week Section 10 is unchanged and the
     engine runs as a PREVIEW (output/advice_preview_weekN.html). From the
     launch week, if it did not run or is not published, Section 10 says
     so and why -- it never falls back to the old trade ideas.
"""

from __future__ import annotations

import json
import time
import traceback
from pathlib import Path
from typing import Optional

from . import advice as adv
from . import marginal_value as mv
from .data_loader import (ADVICE_PUBLISH_FROM_WEEK, COMMISSIONER, CURRENT_SEASON,
                          add_budget_for, cup_winner, free_agents, keeper_rules_for,
                          stage_weeks)

GATE_RELPATH = Path("config") / "snapshots" / "MV_PREMISE_CHECK.json"
SIMS = (mv.SHORTLIST_SIMS, mv.DEFAULT_SIMS)


def read_gate(base_path) -> Optional[dict]:
    path = Path(base_path) / GATE_RELPATH
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"band": "UNREADABLE"}


def publish_decision(gate: Optional[dict], season: str, week: int,
                     from_week: Optional[int]) -> tuple[bool, str]:
    """(publish?, reason). Order matters: the first reason that blocks wins."""
    if from_week is None:
        return False, "no season.advice_publish_from_week configured"
    if week < from_week:
        return False, f"preview: publishes from week {from_week}"
    if gate is None:
        return False, ("the premise check has not been run this season "
                       "(scripts/validate_marginal_value.py)")
    if gate.get("season") != season:
        return False, f"the premise check on file is for {gate.get('season')}, not {season}"
    band = gate.get("band")
    if band == "MARGINAL":
        return False, ("premise check MARGINAL: paused pending discussion. "
                       "MARGINAL means talk, not ship")
    if band != "CLEAR":
        return False, f"premise check {band}: not published"
    return True, "published"


def _next_season(season: str) -> str:
    y = int(str(season)[:4]) + 1
    return f"{y}-{(y + 1) % 100:02d}"


def protected_keeper_counts(managers, season: str = CURRENT_SEASON) -> dict:
    """Next season's keeper count per manager. While this season's Cup is
    undecided nobody knows who gets the bonus, so everyone is protected at
    base + bonus: protecting one extra player is cheap, dropping a future
    sixth keeper is not."""
    nxt = _next_season(season)
    rule = keeper_rules_for(nxt)
    base, bonus = int(rule["base"]), int(rule.get("cup_winner_bonus") or 0)
    winner = cup_winner(season) if bonus else None
    return {m: base + (bonus if (winner is None or winner == m) else 0) for m in managers}


def _fallback_info(lineups) -> dict:
    try:
        df = lineups.dropna(subset=["nba_team"]).sort_values("date")
        last = df.groupby("player_name").last()
        return {n: (r["nba_team"], r.get("positions", "")) for n, r in last.iterrows()}
    except Exception:
        return {}


def build_advice(data, week: int, title_odds=None, keeper_watch=None,
                 injury_statuses=None, freshness_tracker=None, publish: bool = False,
                 sims=SIMS) -> dict:
    from .projections import load_player_projections, populate_actual_stats

    t0 = time.perf_counter()
    rosters = {m: list(v) for m, v in data.get_current_rosters().items() if v}
    if len(rosters) < 2:
        return {"ran": False, "status": "no_rosters", "reason": "no rosters yet", "week": week}

    projs = load_player_projections(data)
    try:
        populate_actual_stats(projs, data)
    except Exception:
        pass
    fas = free_agents(data.playerlist, rosters)["player_name"].tolist()
    fb = _fallback_info(getattr(data, "lineups", None))
    sweeks = data.schedule.get("weeks", [])

    def ctx(window, cw, n):
        return mv.build_context(projs, rosters, data.nba_schedule, sweeks, window, cw,
                                injury_statuses=injury_statuses, extra_players=fas,
                                fallback_info=fb, sims=n)

    short_n, full_n = sims
    ctxs = {"this_week": (ctx("this_week", week, short_n), ctx("this_week", week, full_n))}
    if mv.window_weeks("regular_season", week):
        ctxs["regular_season"] = (ctx("regular_season", week, short_n),
                                  ctx("regular_season", week, full_n))
    if mv.window_weeks("regular_season", week + 1):
        ctxs["rest_of_season"] = (ctx("regular_season", week + 1, short_n),
                                  ctx("regular_season", week + 1, full_n))

    counts_k = protected_keeper_counts(rosters)
    protected, prot_week = adv.protected_keepers(keeper_watch, week, rosters, counts_k)
    k = adv.replacement_k(CURRENT_SEASON, rosters)
    budget = add_budget_for(CURRENT_SEASON) or 0

    plans = [adv.waiver_plan(m, ctxs, fas, None if protected is None else protected[m],
                             budget, prot_week, replacement_rank=k) for m in rosters]
    adv.mark_contested(plans)

    trades, tcounts = [], {"considered": 0, "eligible": 0, "shown": 0, "not_shown": 0}
    if "regular_season" in ctxs:
        records = getattr(title_odds, "current_records", None) if title_odds else None
        finish = getattr(title_odds, "finish_distribution", None) if title_odds else None
        reg = stage_weeks(CURRENT_SEASON, "regular_season")
        remaining = (reg[1] - week) if reg else None
        cup_ctx = ctx("cup_seeding", week, full_n) if mv.window_weeks("cup_seeding", week) else None
        refill = adv.Refill(*ctxs["regular_season"], fas, k)
        trades, tcounts = adv.find_trades(
            *ctxs["regular_season"], protected, adv.keepability_index(keeper_watch),
            COMMISSIONER, cup_ctx=cup_ctx,
            cup_live=lambda a, b: mv.cup_column_live(finish, [a, b], records, remaining),
            refill=refill)

    if publish and freshness_tracker is not None:
        adv.stamp_ages(trades, adv.trade_key, freshness_tracker.trade_ideas, week)
        for p in plans:
            adv.stamp_ages(p.this_week + p.regular_season, adv.rec_key,
                           freshness_tracker.free_agent_recs, week)

    tops = [p.regular_season[0].add for p in plans if p.regular_season]
    shared = max((tops.count(t) for t in set(tops)), default=0)
    return {
        "ran": True, "published": publish, "week": week, "for_week": week + 1,
        "plans": [adv.asdict(p) for p in plans],
        "trades": [adv.asdict(t) for t in trades],
        "trade_counts": tcounts,
        "bar": {"per_week": adv.FLOOR_PER_WEEK, "se_mult": adv.SE_MULT,
                "this_week_floor": adv.floor_for(ctxs["this_week"][1]),
                "season_floor": (adv.floor_for(ctxs["regular_season"][1])
                                 if "regular_season" in ctxs else None)},
        "replacement_k": k, "adds_budget": budget, "commissioner": COMMISSIONER,
        "protected_asof_week": prot_week,
        "personalisation": {"top_season_adds": tops, "max_managers_sharing_top_add": shared},
        "free_agents": len(fas), "unprojected": sorted(set(ctxs["this_week"][1].unprojected)),
        "runtime_s": round(time.perf_counter() - t0, 1),
    }


def run_advice_safely(base_path, data, week: int, builder=None, **kw) -> dict:
    """Never raises. Decides publish vs preview, runs the engine, and turns
    any failure into a reported status the section prints. The builder is
    looked up at CALL time so a test that replaces build_advice exercises
    this path, not the real engine."""
    if builder is None:
        builder = build_advice
    gate = read_gate(base_path)
    publish, reason = publish_decision(gate, CURRENT_SEASON, week, ADVICE_PUBLISH_FROM_WEEK)
    launched = ADVICE_PUBLISH_FROM_WEEK is not None and week >= ADVICE_PUBLISH_FROM_WEEK
    try:
        out = builder(data, week, publish=publish, **kw)
    except Exception as e:  # noqa: BLE001 -- the whole point
        print(f"  WARNING: C2/C3 did not run: {type(e).__name__}: {e}")
        traceback.print_exc()
        out = {"ran": False, "status": "error",
               "reason": f"{type(e).__name__}: {e}", "week": week}
    out.setdefault("published", False)
    if not out.get("ran"):
        out["published"] = False
    out["launched"] = launched
    out["publish_reason"] = reason if out.get("ran") else out.get("reason", reason)
    out["gate"] = gate
    return out
