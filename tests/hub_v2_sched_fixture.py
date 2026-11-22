"""5d2: Team > Schedule and Matchups > Next week on the synthetic league
(tests/test_hub_v2.py's payload), by the REAL engine path
(modules/hub_v2/schedule.build) over the made-up league of
tests/hub_5d2_world.py on the payload's own day (Wed 12-02, week 7, after
Monday's close). Made-up names only."""

from datetime import date
from types import SimpleNamespace

import hub_5d2_world as W

DAY = date(2026, 12, 2)
PAIRS = {7: [("Marcus", "Tyler"), ("Dana", "Jordan")], 8: [("Marcus", "Dana"), ("Tyler", "Jordan")],
         9: [("Marcus", "Jordan"), ("Tyler", "Dana")]}


def sched_ctx(p: dict = None, today: date = DAY) -> dict:
    from modules.hub_v2 import ranges
    w = W.world(today=today)
    wk = w["wk_dates"]
    week = w["week"]
    weeks = [{"week": n, "matchups": [{"manager_a": a, "manager_b": b} for a, b in PAIRS.get(n, PAIRS[7])]}
             for n in sorted(wk) if n <= 15]
    J = week + 1
    fa_rows = [{"name": n, "pos": "/".join(w["info"][n]["positions"]), "nba": w["info"][n]["nba_team"],
                "proj": f"{w['info'][n]['proj_fppg']:.1f}", "_proj": w["info"][n]["proj_fppg"]} for n in w["fa"][:10]]
    stakes = {"num_simulations": 50000, "as_of": f"{today.isoformat()}T00:05:00-08:00",
              "teams": {m: {"regular_season": {str(J): {"n_win": 30000 - 2000 * i, "n_loss": 20000 + 2000 * i,
                                                        "n_tie": 0, "margin_mean": 40.0 - 25 * i}}}
                        for i, m in enumerate(W.MGRS)}}
    recs = {m: r for m, r in zip(W.MGRS, ("4-2", "3-3", "3-3", "2-4"))}
    if p is not None:
        recs = {r["manager"]: r["record"] for r in p["power"]["rows"]}
    return {"ranges": w["src"], "week": week, "today": today,
            "now": None, "wk_dates": wk, "managers": W.MGRS, "team_of": W.TEAMS,
            "data": SimpleNamespace(schedule={"weeks": weeks}),
            "fcols": {"mode": "ahead", "join": wk[J][0] if J in wk else None}, "fa_av": w["fa_av"], "fa_rows": fa_rows,
            "adds_left": {m: 2 for m in W.MGRS}, "budget": 3,
            "budget_note": "a claim now uses this week's adds (rule 7)",
            "window_text": "Claims made now are applied in Mon 12-14's window, which closes Dec 14, 6:55 PM Pacific.",
            "range_list": ranges.ranges(wk[J][0], J, wk) if J in wk else [], "stakes": stakes, "title_latest": None,
            "records": recs, "pending_note": "As rosters stand with pending moves: one claim applied.",
            "roster_blocks": (p or {}).get("rosters") or {}, "card_of": lambda n: None, "_world": w}


def add_sched(p: dict) -> dict:
    from modules.hub_v2 import schedule
    p["v2"]["sched"], p["v2"]["next_week"] = schedule.build(sched_ctx(p))
    return p
