"""draft_ovr.py -- each draft pick's OVR then and later (4c4: League > History >
Draft; claude/HANDOFF_4C4_LEAGUE_2026-11-19.md s.1).

4a4 (Nick 11-20): THE NUMBERS ARE THE SKILL OVR (modules/skill.py), point in
time: ratings.rate() with the NBA history (history_for: NBA_SEASONS.json and
NBA_DRAFTS.json; the estimate reads only seasons and drafts before the one
rated) on keeper_history's snapshot of the day, this season's games from the
league log to that day (the back-test's source; the live OVR's is the whole NBA
season). Ages: data/historical/BBREF_AGES.json (2019-20 on); a season without
ages (2017-18, 2018-19) has no age move, and no POT. Every pick has an
opening-day OVR now (his NBA record, or the rookie curve by his draft pick), so
THEN_NO_PRIOR and the week-2 fallback no longer arise (kept for 4a's numbers).
THEN is his OVR on that season's OPENING DAY (its first logged day).
LATER is, for a past season, his OVR at that season's TRADE-DEADLINE POINT:
the same position in the season as this season's deadline (2027-03-04 is
78.0% of the way from the first to the last fantasy day), kept as it was
(H56 redesigns the Draft tab next). For THIS season, LATER is today's OVR (hub_state's ratings step);
the hub joins that live, it is not in this file.

A pick whose opening-day level has no earlier season to stand on (a rookie,
a player new to the league's rosters, and every player of 2017-18, the log's
first season) has no opening-day THEN: the formula's level is then the league
mean of that first day, the same for all of them, so the number would say
nothing about him (THEN_NO_PRIOR). 4c5 (4c4 decision 2): such a pick's THEN
falls back to 4a's WEEK-2 POINT (the season's last logged day of fantasy week
2, 4a's first validated cell), marked then_point "week2" and labelled
"(wk 2)" on the page; with no OVR there either, it stays blank with both
reasons. A pick not rostered on the day has no OVR that day (the universe is
the rostered players, as 4a's was).

THE CACHE: past seasons never change, but their schedules (games remaining,
OVR's G) come from basketball-reference's month pages cached in data/.cache/
-- on Nick's machine only, never on the runner. So past seasons are computed
once, on a machine with that cache, by scripts/build_draft_ovr.py, into
data/historical/DRAFT_OVR.json: public history beside all_drafts.json (the
same class of file as DRAFT_PERFORMANCE.json), committed with the code, not
league state, regenerable at will. 2025-26's schedule is data/nba_schedule_
2025-26.json (the Cup final excluded), as 4a's. This season's opening day is
computed live by the hub (live_then) from the live log and the engine's own
NBA schedule.

Cost (4c4, measured on the VM): about 0.1 s for a snapshot and 0.1-0.4 s for
rate(), so all nine past seasons at two points take a few seconds.
"""
from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from typing import Callable, Optional

ROOT = Path(__file__).resolve().parents[1]
CACHE_RELPATH = Path("data") / "historical" / "DRAFT_OVR.json"
SCHEMA = 3                    # 2 (4c5): then_point, and each season's week-2 day; 3 (4a4): the skill OVR
THEN_NO_PRIOR = "no earlier season of his in the league log: his opening-day level is the league average"
NOT_ROSTERED = "not on a roster that day"
OPEN, WEEK2 = "open", "week2"


class DraftOvrError(RuntimeError):
    pass


def deadline_fraction(root=ROOT) -> float:
    """Where this season's trade deadline sits between its first and last
    fantasy day (4a: (2027-03-04 - 2026-10-20) / (2027-04-11 - 2026-10-20))."""
    root = Path(root)
    cfg = json.loads((root / "config" / "league_config.json").read_text(encoding="utf-8"))
    dl = (cfg.get("yahoo_settings") or {}).get("trade_deadline")
    if not dl:
        raise DraftOvrError("league_config yahoo_settings.trade_deadline is missing")
    weeks = json.loads((root / "config" / "SCHEDULE.json").read_text(encoding="utf-8")).get("weeks") or []
    if not weeks:
        raise DraftOvrError("config/SCHEDULE.json has no weeks")
    first = min(date.fromisoformat(str(w["start_date"])[:10]) for w in weeks)
    last = max(date.fromisoformat(str(w["end_date"])[:10]) for w in weeks)
    return (date.fromisoformat(dl) - first).days / (last - first).days


def points_of(rows: list, frac: float) -> tuple:
    """(opening day, deadline day) of a season's log: its first logged day,
    and the last logged day on or before the deadline's position (4a's
    deadline_day)."""
    days = sorted({r["date"] for r in rows})
    if not days:
        raise DraftOvrError("a season with no logged day")
    first, last = date.fromisoformat(days[0]), date.fromisoformat(days[-1])
    target = (first + timedelta(days=round(frac * (last - first).days))).isoformat()
    return days[0], max(d for d in days if d <= target)


def history_for(inputs, season: str, root=ROOT):
    """nba_prior.History for a season of the league log (4a4): who is who from
    that season's rows, NBA_SEASONS.json and NBA_DRAFTS.json (read once; point
    in time inside the estimate)."""
    from . import ratings, nba_prior as NP
    key = (str(Path(root).resolve()), season)
    if key not in _HIST:
        base = _HIST.get(("files", key[0]))
        if base is None:
            base = ratings.load_history(root, [], {})
            _HIST[("files", key[0])] = base
        h = NP.History(base.blob, base.values, NP.ids_from_rows(inputs.log.get(season, [])))
        h.drafts = base.drafts
        _HIST[key] = h
    return _HIST[key]


_HIST: dict = {}


def ages_for(season: str, root=ROOT) -> Optional[dict]:
    """keeper_history ages for the season when BBREF_AGES.json holds it, else None (no fetch)."""
    from . import keeper_history as kh
    held = json.loads((Path(root) / kh.AGES_FILE).read_text(encoding="utf-8")).get("seasons", {})
    if season not in held:
        return None
    return kh.load_ages([season], root)


def rate_day(inputs, season: str, as_of: str, dates_by_team: dict, last_day: str, *,
             opening: bool, history=None, root=ROOT) -> dict:
    """{log name: (ovr or None, reason or None)} for every player rostered on
    as_of: the skill OVR (4a4; history: history_for's, built when not given)."""
    from . import keeper_history as kh, ratings
    snap = kh.snapshot(inputs, kh.next_season(season), "end", ages=None, check=False, labels=False, as_of=as_of)
    ages = ages_for(season, root)
    if ages is not None:                              # an age not found: None (no age move), never guessed
        for c in snap.candidates:
            try:
                c.age = kh.age_for(ages, season, c.player)[0]
            except kh.AgeNotFound:
                c.age = None
    h = history if history is not None else history_for(inputs, season, root)
    res = ratings.rate(snap, inputs, dates_by_team, last_day, history=h)
    return {name: (p["ovr"], None if p["ovr"] is not None else p["ovr_reason"]) for name, p in res["players"].items()}


def season_entry(inputs, season: str, dates_by_team: dict, frac: float) -> dict:
    """One past season: its two days and every pick (all_drafts order) with
    THEN and LATER, each an int or None with its reason."""
    from . import keeper_history as kh
    rows = inputs.log.get(season)
    if not rows:
        raise DraftOvrError(f"{season} has no rows in the league log")
    picks = inputs.picks.get(season) or []
    if not picks:
        raise DraftOvrError(f"{season} has no draft picks")
    last = rows[-1]["date"]
    open_day, dl_day = points_of(rows, frac)
    then = rate_day(inputs, season, open_day, dates_by_team, last, opening=True)
    later = rate_day(inputs, season, dl_day, dates_by_team, last, opening=False)
    wk2_day, wk2 = week2_ratings(inputs, season, rows, dates_by_team, last)
    names = kh.Names(rows)
    out = []
    for p in sorted(picks, key=lambda x: int(x["pick_number"])):
        n = names.canon(p["player_name"], p.get("player_key"))
        t, point = then_with_fallback(then.get(n) if n else None,
                                      wk2.get(n, (None, NOT_ROSTERED)) if (n and wk2_day) else None)
        lt = later.get(n) if n else None
        out.append({"pick_number": int(p["pick_number"]), "round": int(p["round"]), "manager": p["manager"],
                    "player": p["player_name"], "is_keeper": bool(p.get("is_keeper")),
                    "then": t[0] if t else None, "then_reason": t[1] if t else NOT_ROSTERED, "then_point": point,
                    "later": lt[0] if lt else None, "later_reason": lt[1] if lt else NOT_ROSTERED})
    return {"season": season, "open": open_day, "week2": wk2_day, "deadline": dl_day, "picks": out}


def week2_ratings(inputs, season: str, rows: list, dates_by_team: dict, last_day: str, history=None) -> tuple:
    """(week-2 day or None, {name: (ovr, reason)}): 4a's week-2 point, the last
    logged day of fantasy week 2 (keeper_history.as_of_point), rated as any
    day. None and {} when the log has no week 2 yet."""
    from . import keeper_history as kh
    try:
        day = kh.as_of_point(rows, season, "week2")[1]
    except KeyError:
        return None, {}
    return day, rate_day(inputs, season, day, dates_by_team, last_day, opening=False, history=history)


def then_with_fallback(t, w) -> tuple:
    """((ovr, reason) or None, point): the opening day's, unless it is blank
    for THEN_NO_PRIOR and the week-2 point has an OVR (4c4 decision 2)."""
    if t is not None and t[0] is None and t[1] == THEN_NO_PRIOR and w is not None:
        if w[0] is not None:
            return (w[0], None), WEEK2
        return (None, f"{THEN_NO_PRIOR}; none at week 2 either ({w[1]})"), OPEN
    return t, OPEN


def bbref_dates(season: str, last_day: str, root=ROOT) -> dict:
    """{team: sorted game days <= last_day} for a past season, as 4a built it:
    2025-26 from data/nba_schedule_2025-26.json (the Cup final, alone on
    2025-12-16, excluded), earlier seasons from the cached basketball-reference
    month pages (scripts/enrich_historical_playerlog.bbref_schedule, never
    fetching: a page not cached RAISES)."""
    import sys
    root = Path(root)
    if season == "2025-26":
        games = json.loads((root / "data" / "nba_schedule_2025-26.json").read_text(encoding="utf-8"))["games"]
        byday: dict = {}
        for g in games:
            byday.setdefault(g["date"][:10], []).append(g)
        out: dict = {}
        for d, gs in byday.items():
            if d == "2025-12-16" and len(gs) == 1:
                continue
            for g in gs:
                for t in (g["home"], g["away"]):
                    out.setdefault(t, []).append(d)
    else:
        sys.path.insert(0, str(root / "scripts"))
        import enrich_historical_playerlog as E

        def nofetch(url):
            raise DraftOvrError(f"{url} is not in data/.cache: the draft OVR cache is built only where "
                                "basketball-reference's pages are cached (Nick's machine)")
        sched, _final = E.bbref_schedule(season, fetch=nofetch)
        out = {}
        for d, m in sched.items():
            for t in m:
                out.setdefault(t, []).append(d)
    return {t: sorted(x for x in ds if x <= last_day) for t, ds in out.items()}


def build_cache(root=ROOT, inputs=None, seasons=None, schedule: Callable = None) -> dict:
    """The cache's object for every past season in the league log (all but
    the current season). schedule(season, last_day) -> {team: days}
    (default: bbref_dates)."""
    from . import keeper_history as kh
    from .data_loader import CURRENT_SEASON
    root = Path(root)
    inputs = inputs or kh.Inputs.load(root)
    frac = deadline_fraction(root)
    schedule = schedule or (lambda s, last: bbref_dates(s, last, root))
    cur = CURRENT_SEASON
    out = {}
    for s in sorted(seasons or inputs.log):
        if s == cur or s not in inputs.picks:
            continue
        out[s] = season_entry(inputs, s, schedule(s, inputs.log[s][-1]["date"]), frac)
    return {"schema": SCHEMA, "deadline_fraction": round(frac, 6), "seasons": out,
            "note": ("4a4: the skill OVR, point in time. THEN: his OVR on the season's opening day; LATER: his "
                     "OVR at the trade-deadline point (modules/draft_ovr). Built by scripts/build_draft_ovr.py.")}


def load(root=ROOT) -> Optional[dict]:
    """The cache, or None when there is none. A wrong schema RAISES."""
    p = Path(root) / CACHE_RELPATH
    if not p.is_file():
        return None
    obj = json.loads(p.read_text(encoding="utf-8"))
    if obj.get("schema") != SCHEMA:
        raise DraftOvrError(f"{CACHE_RELPATH} is schema {obj.get('schema')}, not {SCHEMA}: run "
                            "python scripts/build_draft_ovr.py")
    return obj


def live_then(live: tuple, dates_by_team: dict, last_day: str, history=None) -> dict:
    """This season's opening-day OVR: {pick name: (ovr or None, reason, point)} over
    the current season's picks, from the live log (hub_state's shared
    keeper_history.live_inputs) and the engine's NBA schedule
    (ratings.team_dates). Point in time: only the first logged day's rows."""
    from . import keeper_history as kh
    inputs, season = live
    rows = inputs.log.get(season) or []
    if not rows:
        raise DraftOvrError(f"the live log has no rows for {season}")
    open_day = rows[0]["date"]
    if history is None:
        raise DraftOvrError("this season's opening-day OVR needs the NBA history (the ratings' own)")
    then = rate_day(inputs, season, open_day, dates_by_team, last_day, opening=True, history=history)
    wk2_day, wk2 = week2_ratings(inputs, season, rows, dates_by_team, last_day, history)
    names = kh.Names(rows)
    out = {}
    for p in inputs.picks.get(season) or []:
        n = names.canon(p["player_name"], p.get("player_key"))
        t, point = then_with_fallback(then.get(n) if n else None,
                                      wk2.get(n, (None, NOT_ROSTERED)) if (n and wk2_day) else None)
        out[p["player_name"]] = (t[0], t[1], point) if t else (None, NOT_ROSTERED, OPEN)
    return {"open": open_day, "week2": wk2_day, "players": out}
