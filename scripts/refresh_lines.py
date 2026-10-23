#!/usr/bin/env python3
"""
refresh_lines.py -- B2, the as-of betting line (manual refresh).

    py scripts\\refresh_lines.py [--week N] [--as-of YYYY-MM-DD]

Writes output/live_lines_weekN.json: for each matchup, banked points (from
the local logs, every game before as_of), the simulated remainder, and the
line on banked + remainder. Defaults: as_of = today, week = the fantasy
week containing as_of.

It also keeps output/live_lines_weekN.state.json -- the week's SEED and the
TAG RECORD -- because a live line must only move for a reason:
  - one seed per week, chosen at the first refresh and reused after;
  - a Yahoo tag that is unchanged since the last refresh keeps its original
    anchor (re-anchoring would charge games he already sat twice); a new or
    changed tag is re-anchored at as_of; the output lists which happened.

Refuses (raises) rather than guess:
  - a completed game day missing from the logs   (--allow-missing-days)
  - mid-week with no tag record for the week      (--assume-tags-since-week-start)
  - a different --seed from the week's recorded one (--reseed)
  - a Yahoo fetch that fails                      (--statuses FILE or --no-tags)
  - an OFS tag the overrides file returns          (--allow-season-out-conflict)
Every override used is written into the output's "assumptions".

Starters are legal lineups (A4): PG SG G SF PF F C C UTIL UTIL.
"""

from __future__ import annotations

import argparse
import json
import secrets
import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from modules.data_loader import load_all_data, atomic_write_json          # noqa: E402
from modules.projections import load_all_team_projections                 # noqa: E402
from modules import simulator_betting as sb                               # noqa: E402
from modules import week_state as ws                                      # noqa: E402

CAVEATS = [
    "Team-level noise on the remainder is scaled by sqrt(share of the week's NBA game-days "
    "still to come).",
    "Untagged absences are simulated (the baseline hazard, modules/absence.py) on the "
    "remainder only; banked points already happened.",
]


class SeedChanged(RuntimeError):
    pass


def _fetch_statuses(base: Path) -> dict:
    try:
        from modules.fetch_injury_statuses import fetch_injury_statuses
    except ImportError as e:
        raise RuntimeError(f"cannot fetch Yahoo tags ({e}); pass --statuses FILE or --no-tags")
    from modules.fetch_injury_statuses import InjuryFetchError
    try:
        statuses = fetch_injury_statuses(oauth_file=str(base / "oauth2.json"), verbose=False)
    except InjuryFetchError as e:
        raise RuntimeError(f"Yahoo injury fetch failed ({e}); pass --statuses FILE or --no-tags")
    if not statuses:
        raise RuntimeError("Yahoo returned no injury statuses; pass --statuses FILE or --no-tags")
    return dict(statuses)


def refresh(base_path=".", week=None, as_of=None, sims=sb.DEFAULT_NUM_SIMULATIONS, seed=None,
            statuses=None, no_tags=False, allow_missing_days=False,
            assume_tags_since_week_start=False, reseed=False, dry_run=False, data=None,
            allow_season_out_conflict=False) -> dict:
    base = Path(base_path)
    as_of = as_of or date.today()
    data = data or load_all_data(base, current_week=None)
    week = week or ws.week_for_date(data, as_of)
    entry = ws.week_entry(data, week)
    week_start = date.fromisoformat(str(entry["start_date"])[:10])
    out_dir = base / "output"
    state_path = out_dir / f"live_lines_week{week}.state.json"
    stored = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else None
    assumptions = []

    # --- the week's seed
    if stored is not None and seed is not None and int(seed) != int(stored["seed"]) and not reseed:
        raise SeedChanged(f"week {week} has been priced with seed {stored['seed']}; a new seed moves "
                          "the line for no reason. --reseed to do it anyway.")
    if seed is None:
        seed = int(stored["seed"]) if stored else secrets.randbits(62)
    if stored is not None and int(seed) != int(stored["seed"]):
        assumptions.append(f"RESEEDED: week {week} seed {stored['seed']} -> {seed} (--reseed).")
    if stored is not None and as_of.isoformat() < stored.get("as_of", "") and not dry_run:
        raise RuntimeError(f"the week {week} record is already at {stored['as_of']}, after as_of "
                           f"{as_of}; use --dry-run to price an earlier date")

    # --- tags
    if no_tags:
        live = {}
        assumptions.append("NO TAGS: priced without Yahoo injury tags (--no-tags).")
    else:
        live = statuses if statuses is not None else _fetch_statuses(base)
        # every tag must land on a rostered player -- never silently dropped
        from modules import absence
        _teams = load_all_team_projections(data)
        live, _unmatched, _missing = absence.resolve_tags(
            live, [n for tp in _teams.values() for n in tp.players])
        # an OFS tag the overrides file returns: refuse, or let the override
        # win and say so in the assumptions (the same escape the weekly build
        # has as --allow-season-out-conflict)
        live, _conflicts = absence.resolve_season_out_conflicts(
            live, {n: p for tp in _teams.values() for n, p in tp.players.items()},
            allow_season_out_conflict)
        for c in _conflicts:
            assumptions.append(f"SEASON-OUT OVERRIDDEN: {c['line']} -- {c['resolution']} "
                               "(--allow-season-out-conflict).")
        live = dict(live)
    previous = stored.get("tags") if stored else None
    anchors, events, tag_assumptions = ws.reconcile_tags(
        previous, live, as_of, week_start, assume_tags_since_week_start)
    assumptions += tag_assumptions

    # --- state and the line
    teams = load_all_team_projections(data)
    state = ws.week_state(data, week, as_of, teams, allow_missing_days=allow_missing_days)
    assumptions += list(state.assumptions)
    res = sb.simulate_week_remainder(data, teams, entry, state, seed, sims, live or None, anchors)
    basis = {n: b.basis for n, b in res.tag_blocks.items()}
    for e in events:
        if e["anchor"] is None:
            continue
        e["basis"] = basis.get(e["player"], "suppressed: an INJURY_OVERRIDES entry governs this week")

    lines = []
    for ln in res.lines:
        lines.append({
            "matchup": f"{ln.manager_a} vs {ln.manager_b}",
            "manager_a": ln.manager_a, "manager_b": ln.manager_b,
            "team_name_a": ln.team_name_a, "team_name_b": ln.team_name_b,
            "spread_a": ln.spread_a, "spread_b": ln.spread_b, "over_under": ln.over_under,
            "win_prob_a": round(ln.win_prob_a, 2), "win_prob_b": round(ln.win_prob_b, 2),
            "moneyline_a": ln.moneyline_a, "moneyline_b": ln.moneyline_b,
            "banked_a": round(ln.banked_a, 2), "banked_b": round(ln.banked_b, 2),
            "remaining_mean_a": round(ln.remaining_mean_a, 2),
            "remaining_mean_b": round(ln.remaining_mean_b, 2),
            "projected_final_a": round(ln.projected_final_a, 2),
            "projected_final_b": round(ln.projected_final_b, 2),
            "display_a": f"{ln.banked_a:.0f} \u2192 {ln.projected_final_a:.0f}",
            "display_b": f"{ln.banked_b:.0f} \u2192 {ln.projected_final_b:.0f}",
            "std_dev_a": round(ln.std_dev_a, 2), "std_dev_b": round(ln.std_dev_b, 2),
        })
    # Which engine produced these numbers. ONE definition, shared with E1's
    # calibration log (modules/calibration_log.engine_version / engine_key):
    # a payload from a retired engine carries retired caveats, and the page
    # refuses to render it (modules/live_lines_page.py).
    from modules import calibration_log as _cal
    _engine = _cal.engine_version(base)
    payload = {
        "week": week, "as_of": as_of.isoformat(),
        "engine": {"commit": _engine["commit"], "dirty": _engine["dirty"],
                   "key": _cal.engine_key({"engine_commit": _engine["commit"],
                                           "engine_dirty": _engine["dirty"]})},
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "seed": seed, "num_simulations": sims, "state_hash": state.state_hash,
        "completed_dates": [d.isoformat() for d in state.completed],
        "remaining_dates": [d.isoformat() for d in state.remaining],
        "assumptions": assumptions, "tag_events": events, "caveats": CAVEATS,
        "lines": lines,
    }
    if not dry_run:
        # E1: a re-issued line is a NEW calibration record with its own as-of
        # timestamp and state hash, never an edit of the pre-week one -- the
        # log says what was on the page when (modules/calibration_log.py).
        from modules import calibration_log as cal
        rosters = {m: list(v) for m, v in (data.get_current_rosters() or {}).items() if v}
        governing = cal.overrides_governing(
            week, sb.get_dates_in_week(entry), rosters,
            (data.injury_overrides or {}).get("players") or [])
        engine = cal.engine_version(base)
        stamp = datetime.now().isoformat(timespec="seconds")
        logged = cal.append([
            cal.line_record(ln, week=week, seed=seed, num_simulations=sims,
                            engine=engine, as_of=stamp, state_hash=state.state_hash,
                            source=cal.LIVE_REFRESH, tags=live or {},
                            overrides_governing=governing)
            for ln in res.lines], base)
        payload["calibration_logged"] = logged["added"]
        atomic_write_json(out_dir / f"live_lines_week{week}.json", payload)
        atomic_write_json(state_path, {"week": week, "seed": seed, "as_of": as_of.isoformat(),
                                       "tags": ws.tag_record(anchors, live)})
    return payload


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--week", type=int)
    ap.add_argument("--as-of", type=lambda s: date.fromisoformat(s))
    ap.add_argument("--sims", type=int, default=sb.DEFAULT_NUM_SIMULATIONS)
    ap.add_argument("--seed", type=int)
    ap.add_argument("--reseed", action="store_true")
    ap.add_argument("--statuses", help="JSON {player: tag} instead of fetching Yahoo")
    ap.add_argument("--no-tags", action="store_true")
    ap.add_argument("--allow-missing-days", action="store_true")
    ap.add_argument("--assume-tags-since-week-start", action="store_true")
    ap.add_argument("--allow-season-out-conflict", action="store_true",
                    help="a player tagged OFS whom INJURY_OVERRIDES returns: the override "
                         "wins, the tag is dropped, and the line's assumptions say so")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--base-path", default=".")
    a = ap.parse_args(argv)
    st = json.loads(Path(a.statuses).read_text(encoding="utf-8")) if a.statuses else None
    p = refresh(a.base_path, a.week, a.as_of, a.sims, a.seed, st, a.no_tags, a.allow_missing_days,
                a.assume_tags_since_week_start, a.reseed, a.dry_run,
                allow_season_out_conflict=a.allow_season_out_conflict)
    print(f"Week {p['week']} as of {p['as_of']}  seed {p['seed']}  state {p['state_hash']}")
    for ln in p["lines"]:
        print(f"  {ln['matchup']:22s} {ln['manager_a']} {ln['spread_a']:+.1f}  "
              f"win {ln['win_prob_a']:.1f}/{ln['win_prob_b']:.1f}  "
              f"{ln['banked_a']:.0f}->{ln['projected_final_a']:.0f} vs "
              f"{ln['banked_b']:.0f}->{ln['projected_final_b']:.0f}")
    for e in p["tag_events"]:
        print(f"  tag {e['player']}: {e['tag']} {e['event']}" + (f" ({e['basis']})" if e.get("basis") else ""))
    for s in p["assumptions"]:
        print(f"  ! {s}")


if __name__ == "__main__":
    main()
