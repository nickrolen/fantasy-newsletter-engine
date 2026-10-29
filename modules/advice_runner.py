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

  2. PUBLISH ON CLEAR -- OR ON NICK'S RECORDED OVERRIDE. Publishes from
     season.advice_publish_from_week, for this season, when
     scripts/validate_marginal_value.py recorded CLEAR. MARGINAL means talk,
     not ship (Nick, 10-06). On 10-29, with the gate at FAIL, Nick decided to
     ship anyway ("I don't want section 10 blank in week 3... do our best"):
     season.advice_premise_override in league_config, dated and attributed,
     lists the measured bands it overrides. The gate still runs and records;
     the override never covers UNSTABLE, a missing gate or another season's;
     and every build prints that it published on the override. There is no
     command-line flag.

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


# The bands an override may name: a measured result Nick has read. UNSTABLE
# (the samples disagree) and UNREADABLE are not measurements.
OVERRIDABLE = ("FAIL", "MARGINAL")


def premise_override(season_config: dict = None) -> Optional[dict]:
    """season.advice_premise_override, validated; None when absent. A
    malformed one RAISES -- a config error must not publish or block by
    accident."""
    import re
    if season_config is None:
        from .data_loader import SEASON_CONFIG as season_config
    raw = (season_config or {}).get("advice_premise_override")
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ValueError("season.advice_premise_override must be an object")
    problems = []
    for key in ("season", "by", "date", "reason"):
        if not isinstance(raw.get(key), str) or not raw.get(key).strip():
            problems.append(f"{key} must be a non-empty string")
    if isinstance(raw.get("date"), str) and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw["date"]):
        problems.append("date must be YYYY-MM-DD")
    bands = raw.get("overrides_bands")
    if (not isinstance(bands, list) or not bands
            or any(b not in OVERRIDABLE for b in bands)):
        problems.append(f"overrides_bands must be a non-empty list drawn from {list(OVERRIDABLE)}")
    if problems:
        raise ValueError("season.advice_premise_override is malformed: " + "; ".join(problems))
    return dict(raw)


def read_gate(base_path) -> Optional[dict]:
    path = Path(base_path) / GATE_RELPATH
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"band": "UNREADABLE"}


def publish_decision(gate: Optional[dict], season: str, week: int,
                     from_week: Optional[int], override: Optional[dict] = None) -> tuple[bool, str]:
    """(publish?, reason). Order matters: the first reason that blocks wins.
    `override` is premise_override(): it publishes a gate whose band it
    names, for its season, and says so in the reason."""
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
    if (override and override.get("season") == season
            and band in (override.get("overrides_bands") or [])):
        return True, (f"published on {override['by']}'s override of a {band} premise gate "
                      f"({override['date'][5:]})")
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
    il = il_occupants(data, rosters)

    projs = load_player_projections(data)
    try:
        populate_actual_stats(projs, data)
    except Exception:
        pass
    fas = free_agents(data.playerlist, rosters)["player_name"].tolist()
    fb = _fallback_info(getattr(data, "lineups", None))
    sweeks = data.schedule.get("weeks", [])

    statuses = advice_statuses(injury_statuses)

    def ctx(window, cw, n):
        return mv.build_context(projs, rosters, data.nba_schedule, sweeks, window, cw,
                                injury_statuses=statuses, extra_players=fas,
                                fallback_info=fb, sims=n,
                                # the pre-season durability prior, the same one
                                # the week engine reads -- never the live GP
                                durability_prior=getattr(data, "durability_prior", None))

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
                             budget, prot_week, replacement_rank=k, il=il.get(m))
             for m in rosters]
    adv.mark_contested(plans)

    trades, tcounts = [], {"considered": 0, "eligible": 0, "shown": 0, "not_shown": 0}
    if "regular_season" in ctxs:
        records = getattr(title_odds, "current_records", None) if title_odds else None
        finish = getattr(title_odds, "finish_distribution", None) if title_odds else None
        # the games left as PAIRINGS, from the same season pass as the
        # records -- the exact elimination check needs who plays whom
        remaining = getattr(title_odds, "remaining_pairs", None) if title_odds else None
        cup_ctx = ctx("cup_seeding", week, full_n) if mv.window_weeks("cup_seeding", week) else None
        refill = adv.Refill(*ctxs["regular_season"], fas, k)
        trades, tcounts = adv.find_trades(
            *ctxs["regular_season"], protected, adv.keepability_index(keeper_watch),
            COMMISSIONER, cup_ctx=cup_ctx,
            cup_live=lambda a, b: mv.cup_column_live(finish, [a, b], records, remaining),
            refill=refill, il=il)

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
        "il_slots": {m: sorted(v) for m, v in il.items() if v},
        "protected_asof_week": prot_week,
        "personalisation": {"top_season_adds": tops, "max_managers_sharing_top_add": shared},
        "free_agents": len(fas), "unprojected": sorted(set(ctxs["this_week"][1].unprojected)),
        "runtime_s": round(time.perf_counter() - t0, 1),
    }


def advice_statuses(injury_statuses):
    """The tags marginal value reads, for EVERY player it values: rostered
    players and the free agents C2 would add. The Tags mapping holds rostered
    players only and keeps free agents apart (Tags.free_agents); handed over
    as-is, every free agent read as HEALTHY -- the 10-29 preview recommended
    Ivica Zubac, tagged O, as a this-week add to two managers. A rostered
    player's tag wins a name clash."""
    from .data_loader import PlayerIndex
    merged = PlayerIndex(dict(getattr(injury_statuses, "free_agents", None) or {}))
    for name, tag in dict(injury_statuses or {}).items():
        merged[name] = tag
    return merged


def il_occupants(data, rosters: dict) -> dict:
    """{manager: set of roster names in an IL slot} -- the IL file the roster
    plan reads (roster_plan: data.il_slots when set, else data/IL_SLOTS.json,
    which raises when missing or stale). The advice never moves them: an IL
    slot holds only an O or OFS player and is fixed for the week (rules 2, 5),
    and dropping or trading one does not free an ACTIVE spot -- an add
    against it would put a 16th player in 15 active spots (rule 1)."""
    from . import roster_plan
    from .data_loader import PlayerIndex
    state = getattr(data, "il_slots", None)
    if state is None:
        state = roster_plan.load_il_slots(getattr(data, "base_path", "."), data)
    out = {}
    for m, names in (state.get("slots") or {}).items():
        idx = PlayerIndex({n: n for n in rosters.get(m, [])})
        out[m] = {idx.get(n) for n in names if idx.get(n) is not None}
    return out


def preview(base_path=".", week: int = None, title_sims: int = 2000, statuses_file: str = None,
            out_path=None) -> Path:
    """Render Section 10 exactly as the build would for report week `week`,
    to output/advice_preview_weekN.html, publish decision included (the
    override, if in force). For reading before it ships; writes nothing else.
    Tags: --statuses FILE (fetch_injury_statuses --output), else fetched."""
    import importlib
    from .advice_render import render_preview_page
    from .data_loader import load_all_data
    from .report_builder import build_keeper_watch
    from .season_sim import run_season
    base = Path(base_path)
    data = load_all_data(base)
    week = data.current_week if week is None else int(week)
    fis = importlib.import_module("modules.fetch_injury_statuses")
    if statuses_file:
        tags = fis.Tags.from_json(json.loads(Path(statuses_file).read_text(encoding="utf-8")))
    else:
        tags = fis.fetch_injury_statuses(oauth_file=str(base / "oauth2.json"))
    sp = run_season(data, title_sims, 20262027, injury_statuses=tags, through="regular")
    launch = max(week, ADVICE_PUBLISH_FROM_WEEK or week)
    keeper_watch = build_keeper_watch(data, week)
    if isinstance(keeper_watch, dict):
        keeper_watch["week"] = week          # stamped, exactly as report_builder does
    out = run_advice_safely(base, data, week, title_odds=sp.title_result(),
                            keeper_watch=keeper_watch, injury_statuses=tags,
                            decision_week=launch)
    out["decision_week"] = launch
    path = Path(out_path) if out_path else base / "output" / f"advice_preview_week{week}.html"
    path.parent.mkdir(parents=True, exist_ok=True)
    if not out.get("ran"):
        raise RuntimeError(f"C2/C3 did not run: {out.get('publish_reason')}")
    path.write_text(render_preview_page(out), encoding="utf-8")
    print(f"  C2/C3 {'published' if out.get('published') else 'not published'}: "
          f"{out.get('publish_reason')} ({out.get('runtime_s')}s)")
    print(f"  Wrote {path}")
    return path


def run_advice_safely(base_path, data, week: int, builder=None, decision_week: int = None,
                      **kw) -> dict:
    """Never raises. Decides publish vs preview, runs the engine, and turns
    any failure into a reported status the section prints. The builder is
    looked up at CALL time so a test that replaces build_advice exercises
    this path, not the real engine."""
    if builder is None:
        builder = build_advice
    gate = read_gate(base_path)
    # A malformed override raises here, outside the guard: it is a config
    # error, and it must not publish or block by accident.
    override = premise_override()
    # decision_week: the preview asks what a LATER report week would publish
    # (the launch week) while valuing today's data. The build never passes it.
    dweek = week if decision_week is None else int(decision_week)
    publish, reason = publish_decision(gate, CURRENT_SEASON, dweek, ADVICE_PUBLISH_FROM_WEEK,
                                       override)
    launched = ADVICE_PUBLISH_FROM_WEEK is not None and dweek >= ADVICE_PUBLISH_FROM_WEEK
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
    out["premise_override"] = override if (override and out.get("published")
                                           and "override" in reason) else None
    return out


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Render the Section 10 preview for a report week.")
    ap.add_argument("--week", type=int, default=None, help="the completed report week")
    ap.add_argument("--statuses", default=None, help="a tags file instead of fetching Yahoo")
    ap.add_argument("--title-sims", type=int, default=2000)
    a = ap.parse_args()
    preview(".", a.week, a.title_sims, a.statuses)
