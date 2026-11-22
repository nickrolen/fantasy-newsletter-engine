"""5d2: a made-up league for the range source (modules/hub_v2/ranges.py), its
tests and the Team > Schedule mock. Nothing here is league data: invented
players on invented NBA teams, an invented NBA schedule, the design system's
placeholder teams. Only the fantasy weeks' dates come from config (the
league's calendar: week 7 and week 17 are 14 days).

    world(today=...) -> {"av", "next_av", "wk_dates", "week", "managers",
                         "teams", "slots", "info", "fa", "fa_av", "src", ...}
"""

from __future__ import annotations

import json
import random
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

MGRS = ["Marcus", "Tyler", "Dana", "Jordan"]
TEAMS = {"Marcus": "Glass Cannons", "Tyler": "Zone Defense", "Dana": "Pick & Roll Call",
         "Jordan": "Fast Break Bros"}
SLOTS = {"Marcus": "blue", "Tyler": "teal", "Dana": "orange", "Jordan": "plum"}

NBA = ["ARC", "BLZ", "CMT", "DRF", "EMB", "FLR", "GRN", "HWK", "IRN", "JET", "KNG", "LNX", "MTR", "NOV",
       "ORB", "PIK", "QSR", "RVN", "SKY", "TDE", "UMB", "VLT", "WSP", "XEN", "YTI", "ZPH", "AXL", "BRK",
       "CYN", "DUN"]
FIRST = ["Avery", "Bram", "Cael", "Dorian", "Emrys", "Fenn", "Gideon", "Hollis", "Ivo", "Jaspen", "Kellan",
         "Lorcan", "Mattix", "Nolan", "Orrin", "Pax", "Quinlan", "Rafe", "Soren", "Tobin", "Ulric", "Vesper",
         "Wystan", "Xander", "Yorick", "Zeph", "Alder", "Bastien", "Corwin", "Dashiel"]
LAST = ["Ashgrove", "Brightwater", "Corvane", "Dunmore", "Ellery", "Fenwold", "Galloway", "Hartwell",
        "Ivesdale", "Jessamy", "Kinloch", "Lockhart", "Merriwen", "Northcott", "Oakhurst", "Pembry",
        "Quillon", "Rookwood", "Stavely", "Thistlewood", "Underhay", "Valemont", "Wickersham", "Yarrowby",
        "Zennor", "Amberly", "Blackwood", "Coldridge", "Drummel", "Everhart"]
POS = [["PG"], ["PG", "SG"], ["SG"], ["SG", "SF"], ["SF"], ["SF", "PF"], ["PF"], ["PF", "C"], ["C"]]
# NBA nights by weekday (Mon..Sun): a typical count of games
NIGHT = [8, 5, 11, 6, 10, 8, 7]
NO_GAMES = {date(2026, 11, 26), date(2026, 12, 24)} | {date(2027, 2, 12) + timedelta(days=i) for i in range(6)}


def week_dates() -> dict:
    s = json.loads((ROOT / "config" / "SCHEDULE.json").read_text(encoding="utf-8"))
    out = {}
    for w in s["weeks"]:
        a = date.fromisoformat(str(w["start_date"])[:10])
        b = date.fromisoformat(str(w["end_date"])[:10])
        out[int(w["week"])] = [a + timedelta(days=i) for i in range((b - a).days + 1)]
    return out


def nba_schedule(wk: dict, seed: int = 7) -> dict:
    """{team: [dates]}: an invented NBA season over the fantasy weeks."""
    rnd = random.Random(seed)
    days = [d for w in sorted(wk) for d in wk[w]]
    played = {t: [] for t in NBA}
    for d in days:
        if d in NO_GAMES:
            continue
        n = max(1, min(15, NIGHT[d.weekday()] + rnd.randint(-2, 2)))
        rested = sorted(NBA, key=lambda t: (bool(played[t]) and played[t][-1] == d - timedelta(days=1),
                                            len(played[t]), rnd.random()))
        for t in rested[:2 * n]:
            played[t].append(d)
    return played


def world(today: date = date(2026, 11, 24), seed: int = 11) -> dict:
    """The league on `today` (default Tue 11-24, week 6, after Monday's close)."""
    from modules.hub_state import Availability
    from modules.hub_v2 import ranges
    rnd = random.Random(seed)
    wk = week_dates()
    weeks = {w: (ds[0], ds[-1]) for w, ds in wk.items()}
    week = next(w for w, (a, b) in weeks.items() if a <= today <= b)
    team_dates = nba_schedule(wk)
    names = [f"{f} {l}" for f, l in zip(FIRST, LAST)] + [f"{f} {l}" for f, l in zip(FIRST, LAST[7:] + LAST[:7])] \
        + [f"{f} {l}" for f, l in zip(FIRST, LAST[15:] + LAST[:15])] \
        + [f"{f} {l}" for f, l in zip(FIRST, LAST[22:] + LAST[:22])]
    rnd.shuffle(names)
    info, rosters, il, tags = {}, {}, {}, {}
    k = 0
    for m in MGRS:
        rosters[m] = []
        for j in range(16 if m == "Jordan" else 17):
            n = names[k]
            k += 1
            info[n] = {"positions": POS[(j * 2 + MGRS.index(m)) % len(POS)],
                       "proj_fppg": round(48 - j * 1.6 + rnd.uniform(-3, 3), 1),
                       "nba_team": NBA[(k * 7) % len(NBA)]}
            rosters[m].append(n)
        il[m] = rosters[m][-2:] if m != "Jordan" else rosters[m][-1:]
    # tags: one Q, one D, an O with an injury entry (back in week 7), an OFS in IL
    overrides = {"players": []}
    for i, m in enumerate(MGRS):
        r = rosters[m]
        tags[r[3]] = "Q"
        if i % 2 == 0:
            tags[r[6]] = "D"
        tags[r[-1]] = "OFS" if i == 0 else "O"
        if i != 0 and week + 1 in wk:
            overrides["players"].append({"player_name": r[-1], "out_weeks": [week],
                                         "return_week": week + 1,
                                         "return_date": (wk[week + 1][0] + timedelta(days=3 + i)).isoformat()})
    # one O tag without an entry, active (at most his team's next 3 games)
    tags[rosters["Tyler"][2]] = "O"
    av = Availability(rosters, il, tags, overrides, week, info, team_dates, weeks, today, {})
    # next week: Dana's IL returner is activated and her 15th man dropped
    nr = {m: list(v) for m, v in rosters.items()}
    nil = {m: list(v) for m, v in il.items()}
    back = rosters["Dana"][-1]
    nil["Dana"].remove(back)
    nr["Dana"].remove(rosters["Dana"][14])
    next_av = av.with_rosters(nr, nil, tags)
    # free agents
    fa = []
    for j in range(24):
        n = names[k]
        k += 1
        info[n] = {"positions": POS[j % len(POS)], "proj_fppg": round(36 - j * 0.7 + rnd.uniform(-2, 2), 1),
                   "nba_team": NBA[(j * 11 + 3) % len(NBA)]}
        fa.append(n)
    fa_tags = {fa[2]: "Q", fa[5]: "O"}
    fa_av = av.for_free_agents(fa, fa_tags)
    src = ranges.Source(av, next_av, week, wk, 4, {})
    return {"av": av, "next_av": next_av, "wk_dates": wk, "week": week, "today": today, "managers": MGRS,
            "teams": TEAMS, "slots": SLOTS, "info": info, "rosters": rosters, "il": il, "tags": tags,
            "overrides": overrides, "fa": fa, "fa_av": fa_av, "src": src, "team_dates": team_dates,
            "next_rosters": nr, "next_il": nil}
