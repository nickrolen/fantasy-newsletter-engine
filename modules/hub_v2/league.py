"""
hub_v2/league.py -- the League tab's strings (4c4; claude/HANDOFF_4C4_LEAGUE_
2026-11-19.md): Standings . History . Awards . Archive.

ENGINE SIDE. Every number the League tab shows is a string made here; floats
ride along only to place a chart point (the title-odds lines). The view joins
(a manager to his team mark, a card key to its route) and scales the chart;
the page prints.

    gather(base, ...) -> inputs        reads the files (the real run)
    build(inputs) -> (league, history) pure: the same inputs give the same strings

league (payload v2.league, the first load):
  standings  the regular season, weeks 1-15, in data_loader.standings_order
             (the one ranking rule): W-L-T (a tied week is a T), PF, the
             streak (LEAGUE_RULES "Streaks": every week counts, a T ends a
             streak), the title odds and their change since the run before
             (the power rows' own strings); a tie the rules broke is marked
             and said in the note
  chart      the regular-season title odds by run (output/title_odds_history.
             jsonl, every row with title_odds, in as_of order; before the
             history began, the published weekly reports, as the current
             hub's chart has them). Event markers where the engine knows the
             cause: a week's results (the first run after the week ended), a
             closing line (a "closing" run), a trade (TRADES.json, the first
             run after it). No text on the chart: each marker's words are its
             tooltip {h, b, f}
  power      the published power rankings at each week's end (output/
             stats_report_weekN.json), newest first, with the change in rank
  awards     4c5: the awards races (modules/awards: the hub build's awards
             step, every string made there) and Player of the Week history
             (config/POTW_HISTORY.json), newest first; a week whose points
             were not recorded (2025-26 weeks 1-13) gets them from the league
             log: his started games that week (potw_from_log). The whole
             segment is lazy (its own encrypted part, publish.league_files)
  archive    every archived issue, newest first (payload newsletter): the week,
             the dates, the headline when an issue has one (from 4d)

history (its own lazy files, 4c4 s.2; v2.league_history in the side file):
  champions, alltime, h2h, records, draft, trades -- see each builder.

RAISE RATHER THAN DEFAULT: a missing input raises LeagueError naming it.
"""

from __future__ import annotations

import json
from datetime import date, datetime, time as _time, timedelta
from pathlib import Path
from typing import Dict, List, Optional

MINUS = "\u2212"
DASH = "\u2014"
NDASH = "\u2013"
DOT = " \u00b7 "
UP, DOWN = "\u25b2", "\u25bc"
CHIPS = [("champions", "Champions"), ("alltime", "All-time"), ("h2h", "Head to head"), ("records", "Records"),
         ("draft", "Draft"), ("trades", "Trades")]
SEGS = [("standings", "Standings"), ("history", "History"), ("awards", "Awards"), ("archive", "Archive")]
TOP_SWINGS = 2
EVENT_MOVE = 0.05          # percentage points: a cause that moved no line gets no marker (as hub_v2.data's)


class LeagueError(RuntimeError):
    pass


# =============================================================================
# formatting
# =============================================================================

def _int(x) -> str:
    return f"{float(x):,.0f}"


def _d1(x) -> str:
    return f"{float(x):,.1f}"


def _pct1(x) -> str:
    return f"{float(x):.1f}%"


def _signed1(x) -> str:
    v = round(float(x), 1)
    s = f"{abs(v):,.1f}"
    return ("+" + s) if v > 0 else (MINUS + s) if v < 0 else s


def _clock(dt: datetime) -> str:
    from ..hub_charts import clock
    return clock(dt)


def _slug(name: str) -> str:
    from ..headshots import player_slug
    return player_slug(name)


def _rec(w: int, l: int, t: int = 0) -> str:
    return f"{w}-{l}" + (f"-{t}" if t else "")


# =============================================================================
# gather: the files (the real run)
# =============================================================================

def _json(p: Path):
    if not p.is_file():
        raise LeagueError(f"{p.as_posix()} is missing")
    return json.loads(p.read_text(encoding="utf-8"))


def gather(base, *, data, power: dict, managers: list, teams: dict, newsletter: dict, now: datetime,
           ratings: Optional[dict] = None, ratings_error: Optional[str] = None, live=None,
           awards: Optional[dict] = None) -> dict:
    """Every input build() reads, from the files and the run's own objects.
    teams: v2.teams ({manager: {slot, mono, team}}); ratings: ratings.for_today's
    result (draft "now"); live: the run's shared keeper_history live inputs
    (this season's opening-day OVR, Player of the Week's missing points);
    awards: the hub build's awards step record (hub_state.awards_step)."""
    from .. import title_odds_history as toh, draft_ovr, title_odds_run as tor
    from ..data_loader import stage_weeks
    from ..data_loader import (CURRENT_SEASON, SEASON_STRUCTURE, regular_season_weeks_for,
                               keeper_rules_for, _LEAGUE_CONFIG)
    from ..hub_archive import load_index
    import pandas as pd
    base = Path(base)
    hist = base / "data" / "historical"
    reports = {}
    for p in sorted((base / "output").glob("stats_report_week*.json")):
        try:
            wk = int(p.stem.replace("stats_report_week", ""))
        except ValueError:
            continue
        reports[wk] = json.loads(p.read_text(encoding="utf-8"))
    lh = pd.read_excel(base / "data" / "LEAGUEHISTORY.xlsx")
    lh_rows = [{k: (None if (isinstance(v, float) and v != v) else v) for k, v in r.items()}
               for r in lh.to_dict("records")]
    trades_cfg = _json(base / "config" / "TRADES.json")
    if not isinstance(trades_cfg.get("trades"), list):
        raise LeagueError("config/TRADES.json has no trades list")
    potw = _json(base / "config" / "POTW_HISTORY.json")
    cur_draft = _json(base / "config" / "DRAFT_PICKS_CURRENT.json")
    idx = load_index(base)
    plain = {i["enc"]: i["plain"] for i in idx.get("issues", [])}
    heads = {i["enc"]: (i.get("headline") or "") for i in idx.get("issues", [])}
    # this season's opening-day OVR (draft "then"), computed live; past seasons from the cache
    live_then, live_error = None, None
    if live is not None:
        try:
            from ..ratings import team_dates, schedule_last_day
            from ..data_loader import load_nba_schedule, _schedule_path
            sched = load_nba_schedule(_schedule_path(base), today=now.date())
            live_then = draft_ovr.live_then(live, team_dates(sched), schedule_last_day(base))
        except Exception as e:                       # noqa: BLE001 -- the column says why
            live_error = f"{type(e).__name__}: {e}".splitlines()[0][:300]
    else:
        live_error = "the live log could not be built"
    now_ovr = None
    if ratings is not None:
        now_ovr = {n: p["ovr"] for n, p in ratings["players"].items()}
        # 5c: free agents are rated since 5b (the Players tab's); the draft's
        # "Now" showed them as "free agents have no OVR" (the text audit)
        for n, p in (ratings.get("free_agents") or {}).items():
            now_ovr.setdefault(n, p["ovr"])
    # 4c5 (4c4 decision 9): a week the latest title-odds run banked whole from
    # the logs counts here exactly as Home's record column counts it
    try:
        banked = tor.banked_results(tor.load_latest(base), data.schedule.get("weeks") or [])
    except (FileNotFoundError, ValueError) as e:
        raise LeagueError(f"the latest title-odds run cannot be read: {e}") from None
    seasons = sorted({r["season"] for r in _json(hist / "all_matchups.json")} | {CURRENT_SEASON})
    cup_weeks = {}
    for s in seasons:
        span = stage_weeks(s, "cup")
        cup_weeks[s] = list(range(span[0], span[1] + 1)) if span else []
    potw_seasons = potw.get("seasons") or {}
    return {
        "managers": list(managers), "teams": {m: dict(teams[m]) for m in managers},
        "season": CURRENT_SEASON, "now": now, "reg_weeks": int(regular_season_weeks_for(CURRENT_SEASON)),
        "weeks": data.schedule.get("weeks") or [], "weekly_scores": data.records.get("weekly_scores") or {},
        "records_week": data.records.get("last_updated_week"),
        "power": power, "history_rows": toh.read(base), "reports": reports,
        "season_structure": SEASON_STRUCTURE, "pre_data_era": _LEAGUE_CONFIG.get("pre_data_era") or {},
        "cup_winners": (keeper_rules_for() or {}).get("cup_winners") if callable(keeper_rules_for) else {},
        "leaguehistory": lh_rows,
        "all_standings": _json(hist / "all_standings.json"), "all_matchups": _json(hist / "all_matchups.json"),
        "all_drafts": _json(hist / "all_drafts.json"), "all_trades": _json(hist / "all_trades.json"),
        "all_teams": _json(hist / "all_teams.json"),
        "season_teams": (data.records.get("team_name_history") or {}).get(CURRENT_SEASON) or {},
        "trades_now": trades_cfg["trades"], "potw": potw_seasons,
        "potw_fill": potw_from_log(potw_seasons, live[0].log if live is not None else {}),
        "banked": banked, "cup_weeks": cup_weeks,
        "awards_rec": awards,
        **_awards_past_input(base),
        "records_alltime": data.records.get("all_time") or {},
        "draft_current": cur_draft, "draft_ovr": draft_ovr.load(base),
        "live_then": live_then, "live_error": live_error, "now_ovr": now_ovr, "ratings_error": ratings_error,
        "newsletter": newsletter, "issue_plain": plain, "issue_heads": heads,
    }


# =============================================================================
# the season's results (RECORDS' weekly scores + SCHEDULE's pairings)
# =============================================================================

def week_results(inp: dict) -> Dict[int, list]:
    """{week: [(a, b, score_a, score_b, outcome "a"|"b"|"tie")]} for every week
    in RECORDS' weekly scores where both sides have a score and they are not
    both 0 (LEAGUE_RULES: 0-0 is not played)."""
    from ..data_loader import week_outcome
    scores: Dict[int, dict] = {}
    for m, entries in (inp["weekly_scores"] or {}).items():
        for e in entries if isinstance(entries, list) else []:
            if e.get("week") is not None:
                scores.setdefault(int(e["week"]), {})[m] = float(e["score"])
    # 4c5: a week banked whole overnight, not yet recorded by the weekly build
    # (title_odds_run.banked_results: the rule Home's record column counts by)
    for w, sc in (inp.get("banked") or {}).items():
        if int(w) not in scores:
            scores[int(w)] = {m: float(v) for m, v in sc.items()}
    out = {}
    pairs = {int(w["week"]): w.get("matchups") or [] for w in inp["weeks"]}
    for w in sorted(scores):
        rows = []
        for mu in pairs.get(w, []):
            a, b = mu["manager_a"], mu["manager_b"]
            sa, sb = scores[w].get(a), scores[w].get(b)
            if sa is None or sb is None or (sa == 0 and sb == 0):
                continue
            rows.append((a, b, sa, sb, week_outcome(sa, sb)))
        if rows:
            out[w] = rows
    return out


def streaks(results: Dict[int, list], managers: list) -> Dict[str, str]:
    """"W3", "L2", "T1" or DASH: the current run of one outcome, over every
    week of the season (postseason included); a T ends a streak (Nick, 10-30)."""
    seq = {m: [] for m in managers}
    for w in sorted(results):
        for a, b, _sa, _sb, o in results[w]:
            ra, rb = ("W", "L") if o == "a" else (("L", "W") if o == "b" else ("T", "T"))
            seq.setdefault(a, []).append(ra)
            seq.setdefault(b, []).append(rb)
    out = {}
    for m in managers:
        s = seq.get(m) or []
        if not s:
            out[m] = DASH
            continue
        k = 1
        while k < len(s) and s[-1 - k] == s[-1]:
            k += 1
        out[m] = f"{s[-1]}{k}"
    return out


# =============================================================================
# Standings
# =============================================================================

def standings(inp: dict, results: dict) -> dict:
    from ..data_loader import results_from, standings_order, Record
    managers, reg = inp["managers"], inp["reg_weeks"]
    scores = {}
    for w, rows in results.items():
        for a, b, sa, sb, _o in rows:
            scores.setdefault(w, {})[a] = sa
            scores.setdefault(w, {})[b] = sb
    pairs = {int(w["week"]): w.get("matchups") or [] for w in inp["weeks"]}
    records, h2h, points = results_from({w: s for w, s in scores.items() if w <= reg}, pairs, reg)
    order = standings_order(records, h2h, points, managers)
    # PF as Home shows it: the weeks the weekly build has recorded (a week
    # banked overnight counts in the record at once, in PF after the build)
    banked = sorted(int(w) for w in (inp.get("banked") or {}) if int(w) <= reg
                    and not any(int(e.get("week", -1)) == int(w) for es in (inp["weekly_scores"] or {}).values()
                                for e in (es if isinstance(es, list) else [])))
    pf = results_from({w: s for w, s in scores.items() if w <= reg and w not in banked}, pairs, reg)[2]
    # the ties the rules had to break: their groups and how
    rec = {m: records.get(m, Record()) for m in managers}
    groups: dict = {}
    for m in managers:
        groups.setdefault(rec[m].win_pct, []).append(m)
    tied, notes = set(), []
    if any(r.games for r in rec.values()):
        for pct, ms in groups.items():
            if len(ms) < 2:
                continue
            tied |= set(ms)
            ms_o = [m for m in order if m in ms]
            within = {m: sum((h2h.get(m, {}).get(o, Record()).standing for o in ms if o != m), 0) for m in ms}
            if len({within[m] for m in ms}) == len(ms):
                how = "head-to-head"
            else:
                how = "total points (head-to-head could not separate them)"
            notes.append(f"{', '.join(ms_o[:-1])} and {ms_o[-1]} are level at {rec[ms_o[0]]}: "
                         f"ordered on {how}.")
    power = {r["manager"]: r for r in inp["power"]["rows"]}
    st = streaks(results, managers)
    done = sorted(w for w in results if w <= reg)
    through = done[-1] if done else 0
    rows = []
    for i, m in enumerate(order, 1):
        pr = power.get(m)
        if pr is None:
            raise LeagueError(f"the power rows have no {m}")
        rows.append({"rank": str(i), "m": m, "record": str(rec[m]), "pf": _int(pf.get(m, 0.0)),
                     "streak": st[m], "odds": pr["odds"], "delta": pr["delta"], "dir": pr["delta_dir"],
                     "tie": m in tied})
    note = (f"Through week {through}. " if through else "No week recorded yet. ")
    note += (f"{inp['power']['label']} = the chance of finishing first in weeks 1{NDASH}{reg}; the change is "
             "since the run before. Order: winning percentage (a T counts half), then head-to-head, then points. "
             "Streaks count every week; a T ends one.")
    if banked:
        note += (f" Week {', '.join(str(w) for w in banked)} is counted from the logs, banked overnight, as on "
                 "Home; its points join PF after the weekly build records the week.")
    # one source (4c4 decision 9): Standings and Home never disagree
    shown = {r["manager"]: r["record"] for r in inp["power"]["rows"]}
    off = [m for m in managers if shown.get(m) != str(rec[m])]
    if off:
        raise LeagueError("Standings and Home disagree on " + ", ".join(f"{m} ({rec[m]} vs {shown.get(m)})"
                                                                     for m in off))
    return {"title": "Regular season", "meta": f"weeks 1{NDASH}{reg}", "odds_label": inp["power"]["label"],
            "rows": rows, "note": note, "ties": notes}


# =============================================================================
# the title-odds chart
# =============================================================================

def _aware(s: str, tz) -> datetime:
    dt = datetime.fromisoformat(s)
    return dt if dt.tzinfo else dt.replace(tzinfo=tz)


def chart(inp: dict, results: dict, tz) -> dict:
    """Every run's regular-season title odds, in time order, x the moment's
    place between the season's first day and now (0..1); the event markers
    with their tooltips; the week ticks."""
    managers = inp["managers"]
    weeks = sorted(inp["weeks"], key=lambda w: int(w["week"]))
    if not weeks:
        raise LeagueError("config/SCHEDULE.json has no weeks")
    start = datetime.combine(date.fromisoformat(str(weeks[0]["start_date"])[:10]), _time(0), tzinfo=tz)
    rows = sorted((r for r in inp["history_rows"] if r.get("title_odds")), key=lambda r: _aware(r["as_of"], tz))
    pts = []
    first_hist = _aware(rows[0]["as_of"], tz) if rows else None
    starts = {int(w["week"]): date.fromisoformat(str(w["start_date"])[:10]) for w in weeks}
    for wk in sorted(inp["reports"]):
        rep = inp["reports"][wk]
        meta = rep.get("metadata") or {}
        if meta.get("run_mode") != "publish":
            raise LeagueError(f"stats_report_week{wk}.json is not a published report")
        day = starts.get(wk + 1)
        if day is None:
            raise LeagueError(f"stats_report_week{wk}.json: week {wk + 1} is not in config/SCHEDULE.json")
        at = datetime.combine(day, _time(0), tzinfo=tz)
        if first_hist is not None and at >= datetime.combine(first_hist.date(), _time(0), tzinfo=tz):
            continue                                        # the history covers it
        vals = {p["manager"]: float(p["title_odds"]) for p in rep.get("power_rankings") or []}
        if set(vals) != set(managers):
            raise LeagueError(f"stats_report_week{wk}.json's power rankings lack title odds for every manager")
        pts.append({"at": at, "vals": vals, "src": f"the published week-{wk} report", "kind": "report",
                    "week": wk})
    for r in rows:
        vals = {m: float(v) for m, v in r["title_odds"].items()}
        if set(vals) != set(managers):
            raise LeagueError(f"title-odds run {r['run_id']} has odds for {sorted(vals)}, not {sorted(managers)}")
        pts.append({"at": _aware(r["as_of"], tz), "vals": vals, "src": f"{r.get('kind') or 'run'} run",
                    "kind": r.get("kind") or "run", "week": r.get("week")})
    pts.sort(key=lambda p: p["at"])
    now = inp["now"]
    end = max([now] + [p["at"] for p in pts])
    span = (end - start).total_seconds() or 1.0
    teams = inp["teams"]
    out = []
    for p in pts:
        x = min(max((p["at"] - start).total_seconds() / span, 0.0), 1.0)
        when = _clock(p["at"])
        order = sorted(managers, key=lambda m: (-p["vals"][m], m))
        out.append({"x": x, "vals": {m: p["vals"][m] for m in managers},
                    "texts": {m: _pct1(p["vals"][m]) for m in managers},
                    "head": f"{when}{DOT}{p['src']}",
                    "body": ", ".join(f"{teams[m]['mono']} {_pct1(p['vals'][m])}" for m in order)})
    # --- events
    events = []

    def mark(i: int, b: str):
        if i <= 0 or i >= len(pts):
            return
        prev, cur = pts[i - 1]["vals"], pts[i]["vals"]
        sw = {m: cur[m] - prev[m] for m in managers}
        top = sorted(managers, key=lambda m: (-abs(sw[m]), m))
        m0 = top[0]
        if abs(sw[m0]) < EVENT_MOVE:
            return
        f = DOT.join(f"{teams[m]['mono']} {_signed1(sw[m])}%" for m in top[:TOP_SWINGS])
        if any(e["i"] == i for e in events):              # one marker per run: the causes join
            e = next(e for e in events if e["i"] == i)
            e["tip"]["b"] += "; " + b
            return
        events.append({"i": i, "m": m0, "dir": "up" if sw[m0] > 0 else "down",
                       "tip": {"h": _clock(pts[i]["at"]), "b": b, "f": f}})
    reg_end = {int(w["week"]): datetime.combine(date.fromisoformat(str(w["end_date"])[:10]) + timedelta(days=1),
                                                _time(0), tzinfo=tz) for w in weeks}
    for w in sorted(results):
        ended = reg_end.get(w)
        if ended is None:
            continue
        i = next((k for k, p in enumerate(pts) if p["at"] >= ended), None)
        if i is None:
            continue
        won = []
        for a, b, sa, sb, o in results[w]:
            won.append(f"{teams[a]['mono']} beat {teams[b]['mono']}" if o == "a" else
                       f"{teams[b]['mono']} beat {teams[a]['mono']}" if o == "b" else
                       f"{teams[a]['mono']} and {teams[b]['mono']} tied")
        mark(i, f"Week {w} final: " + ", ".join(won))
    for i, p in enumerate(pts):
        if p["kind"] == "closing":
            mark(i, f"Week {p['week']} closing line priced")
    for t in inp["trades_now"]:
        when = _trade_moment(t, inp["season"], tz)
        if when is None:
            continue
        i = next((k for k, p in enumerate(pts) if p["at"] >= when), None)
        if i is not None:
            mark(i, f"Trade: {t['trader_manager']} {chr(8644)} {t['tradee_manager']}")
    events.sort(key=lambda e: e["i"])
    # --- ticks: each week's first day
    ticks = []
    for w in weeks:
        d = datetime.combine(date.fromisoformat(str(w["start_date"])[:10]), _time(0), tzinfo=tz)
        if d > end:
            break
        ticks.append({"x": (d - start).total_seconds() / span, "t": f"W{int(w['week'])}"})
    last = out[-1] if out else None
    aria = ("Title odds by run, every manager on one 0-100% scale"
            + (": now " + last["body"] if last else ": no run yet")
            + (", with markers where a week's results, a closing line or a trade moved them" if events else "")
            + ".")
    yticks = [{"v": float(v), "t": f"{v}%"} for v in (0, 25, 50, 75, 100)]
    return {"points": out, "events": events, "ticks": ticks, "yticks": yticks, "aria": aria,
            "note": ("Every pricing run since the history began (the nightly, the Monday pre-tip and closing "
                     "runs, the weekly build); before that, each published weekly report. Markers: a week's "
                     "results, a closing line, a trade. Tap a point for its run."),
            "empty": "" if out else "No title-odds run yet."}


def _trade_moment(t: dict, season: str, tz) -> Optional[datetime]:
    from ..keeper_history import trade_dates
    if str(t.get("season")) != season:
        return None
    if t.get("timestamp"):
        return datetime.fromtimestamp(int(t["timestamp"]), tz)
    first, _last = trade_dates(t.get("date"), season)
    return datetime.combine(date.fromisoformat(first) + timedelta(days=1), _time(0), tzinfo=tz)


# =============================================================================
# power rankings by week
# =============================================================================

def power_history(inp: dict) -> dict:
    weeks = []
    prev = None
    for wk in sorted(inp["reports"]):
        rep = inp["reports"][wk]
        pr = rep.get("power_rankings") or []
        if not pr:
            raise LeagueError(f"stats_report_week{wk}.json has no power rankings")
        rank = {p["manager"]: int(p["rank"]) for p in pr}
        rows = []
        for p in sorted(pr, key=lambda x: int(x["rank"])):
            m = p["manager"]
            if prev is None or m not in prev:
                move, d = DASH, "none"
            else:
                k = prev[m] - rank[m]
                move, d = ((f"{UP} {k}", "up") if k > 0 else (f"{DOWN} {-k}", "down") if k < 0 else (NDASH, "flat"))
            rows.append({"rank": str(rank[m]), "m": m, "odds": _pct1(p["title_odds"]), "record": str(p["record"]),
                         "move": move, "dir": d})
        d0 = (rep.get("metadata") or {}).get("date_range") or {}
        sub = (f"end of week {wk}" + (f", {d0['start'][5:]} to {d0['end'][5:]}" if d0.get("start") else ""))
        weeks.append({"week": str(wk), "label": f"Week {wk}", "sub": sub, "rows": rows})
        prev = rank
    weeks.reverse()
    return {"weeks": weeks, "note": ("Each week's published power rankings: title odds first, then the projected "
                                     "finish. The change is against the week before."),
            "empty": "" if weeks else "No week published yet."}


# =============================================================================
# Awards: the races (modules/awards, 4c5) and Player of the Week
# =============================================================================

def potw_from_log(potw: dict, log: dict) -> dict:
    """{(season, week): {"total_fp", "games", "fppg"}} for each Player of the
    Week entry without recorded points (2025-26 weeks 1-13, 4c4 decision 14):
    the credited player's STARTED games that week for the credited manager
    (in the starting lineup, and played: keeper_history.appeared) -- the
    newsletter's own measure (report_builder.build_player_of_week: total FP
    over games started). Checked 4c5 against 2025-26 weeks 14-23, where both
    exist: 10 of 10 equal. A winner not found in the log stays unrecorded."""
    from ..data_loader import PlayerIndex
    from ..keeper_history import appeared
    out = {}
    for s, entries in (potw or {}).items():
        rows = (log or {}).get(s) or []
        if not rows:
            continue
        idx = PlayerIndex({r["player_name"]: r["player_name"] for r in rows})
        for e in entries:
            if all(e.get(k) is not None for k in ("total_fp", "games", "fppg")):
                continue
            n = idx.canonical(e["player"])
            mine = [r for r in rows if n is not None and int(r["week"]) == int(e["week"]) and r["player_name"] == n
                    and r["manager"] == e["manager"] and r["started"] and appeared(r)]
            if mine:
                tot = sum(float(r["fantasy_points"]) for r in mine)
                out[(s, int(e["week"]))] = {"total_fp": round(tot, 2), "games": len(mine),
                                            "fppg": round(tot / len(mine), 2)}
    return out


def _awards_past_input(base) -> dict:
    """4c6: data/historical/AWARDS_PAST.json (public history, modules/
    awards_past), or why it cannot be shown. Never fails the League."""
    from .. import awards_past
    try:
        blob = awards_past.load(base)
        return {"awards_past": blob, "awards_past_error": None if blob is not None else
                "Past seasons' awards are not built yet (python scripts\\build_awards_past.py)."}
    except Exception as e:                           # noqa: BLE001 -- the Awards and Records say why
        return {"awards_past": None,
                "awards_past_error": f"Past seasons' awards cannot be read: {type(e).__name__}: {e}"[:300]}


PAST_UNITS = {"mvp": "PAR", "trade": "PAR gap", "improved": "FPPG"}
PAST_TILES = {"mvp": "Best MVP season", "trade": "Most lopsided trade", "improved": "Most improved season"}


def _past_value(k: str, v: float) -> str:
    return _signed1(v) if k == "improved" else _d1(v)


def _past_sub(k: str, w: dict) -> str:
    if k == "trade":
        return DOT.join(f"{m} got {', '.join(sd['got']) or 'no player'} ({_d1(sd['par'])} PAR)"
                        + (" + picks" if (w.get("picks") or {}).get(m) else "")
                        for m, sd in w["sides"].items())
    return w["sub"]


def awards_past(inp: dict) -> dict:
    """League > Awards' "Past winners" (4c6): per award, every past season's
    winner (season, winner, team, the shown-with figure), newest first, or
    why a season has none. Engine strings only."""
    from ..awards import NAMES
    blob = inp.get("awards_past")
    if blob is None:
        return {"error": inp.get("awards_past_error") or "", "by_award": {}, "note": ""}
    by = {}
    for k in blob["awards"]:
        rows = []
        for s in sorted(blob["seasons"], reverse=True):
            v = blob["seasons"][s]
            a = v["awards"][k]
            w = a["winner"]
            if w is None:
                rows.append({"season": s, "none": a["none"], "label": "", "player": None, "card": "", "m": "",
                             "team_name": "", "value": "", "unit": "", "shown": "", "sub": ""})
                continue
            rows.append({"season": s, "none": "", "label": w["label"], "player": w.get("player"),
                         "card": _slug(w["player"]) if w.get("player") else "", "m": w["m"],
                         "team_name": _season_team(inp, s, w["m"]), "value": _past_value(k, w["value"]),
                         "unit": PAST_UNITS[k], "shown": w["shown"], "sub": _past_sub(k, w)})
        by[k] = {"name": NAMES[k], "rows": rows}
    lens = sorted({v["regular_weeks"] for v in blob["seasons"].values()})
    short = [s for s, v in sorted(blob["seasons"].items()) if v["checks"]["short_weeks"]]
    note = (f"Past winners, {min(blob['seasons'])} to {max(blob['seasons'])}: each season through its own regular "
            f"season ({lens[0]} to {lens[-1]} weeks; this season 15), so totals are not like for like. Wins swung "
            "count against the official scores. "
            + (f"The league log misses some days in {', '.join(short)}: no PAR is counted on them. " if short else "")
            + "Most improved uses FPPG on a league roster before 2026-27. Best pickup, Rookie of the Year and "
              "Bust aren't kept for past seasons: the old data can't support them.")
    return {"error": "", "by_award": by, "note": note}


def award_tiles(inp: dict) -> list:
    """League > History > Records (4c6): one tile per past award, its
    all-time best season (AWARDS_PAST best: the largest measure)."""
    blob = inp.get("awards_past")
    if blob is None:
        return []
    out = []
    for k in blob["awards"]:
        b = blob["best"].get(k)
        if b is None:
            continue
        who = (f"{b['label']}{DOT}{b['m']}" if b.get("player") else b["label"])
        out.append({"key": f"award_{k}", "label": PAST_TILES[k],
                    "value": (f"{_d1(b['per_week'])} PAR a week" if k == "mvp" else
                              f"{_past_value(k, b['value'])} {PAST_UNITS[k]}"), "who": who,
                    "ctx": (f"{b['season']}{DOT}{_d1(b['value'])} PAR over {b['regular_weeks']} weeks" if k == "mvp"
                            else f"{b['season']}{DOT}{b['regular_weeks']}-week season"),
                    "tip": {"h": f"{PAST_TILES[k]}, {b['season']}", "b": f"{b['shown']}{DOT}{_past_sub(k, b)}"
                            if _past_sub(k, b) else b["shown"],
                            "f": f"{b['regular_weeks']}-week regular season; the best of {len(blob['seasons'])} "
                                 f"past seasons by the award's own measure"
                                 + (" per regular-season week" if k == "mvp" else "")}})
    return out


def awards(inp: dict) -> dict:
    seasons = []
    fill = inp.get("potw_fill") or {}
    for s in sorted(inp["potw"], reverse=True):
        rows = []
        for e in sorted(inp["potw"][s], key=lambda x: -int(x["week"])):
            for k in ("week", "player", "manager"):
                if e.get(k) is None:
                    raise LeagueError(f"POTW_HISTORY {s} lacks {k}: {e}")
            have = all(e.get(k) is not None for k in ("total_fp", "games", "fppg"))
            f = None if have else fill.get((s, int(e["week"])))
            src = e if have else f
            rows.append({"week": f"Wk {int(e['week'])}", "player": e["player"], "card": _slug(e["player"]),
                         "m": e["manager"], "pts": _d1(src["total_fp"]) if src else DASH,
                         "sub": (f"{int(src['games'])} games{DOT}{_d1(src['fppg'])} FPPG"
                                 + ("" if have else f"{DOT}from the league log") if src else
                                 "points not recorded for this week")})
        seasons.append({"season": s, "rows": rows})
    rec = inp.get("awards_rec")
    if rec is None:
        races, err, par_note, note = [], "The awards were not computed in this build.", "", ""
    elif rec.get("error") or not rec.get("races"):
        races, err, par_note, note = [], f"The awards could not be computed: {rec.get('error')}", "", ""
    else:
        races, err = rec["races"]["awards"], ""
        par_note, note = rec["races"]["par_note"], rec["races"]["note"]
    return {"potw": seasons, "potw_note": ("The week's best player by fantasy points in his starts, among rostered "
                                           "players (the newsletter's pick)."),
            "races": races, "races_error": err, "par_note": par_note, "races_note": note}


# =============================================================================
# Archive
# =============================================================================

def archive(inp: dict) -> dict:
    nl = inp["newsletter"]
    issues = ([nl["current"]] if nl.get("current") else []) + list(nl.get("archive") or [])
    out = []
    for i in issues:
        if i["file"] not in inp["issue_plain"]:
            raise LeagueError(f"archived issue {i['file']} is not in the archive's index")
        out.append({"week": i["week"], "label": i["label"], "headline": inp["issue_heads"].get(i["file"], ""),
                    "file": i["file"], "plain": inp["issue_plain"][i["file"]], "size": i["size"]})
    return {"issues": out, "empty": nl.get("empty") or "No issue archived yet.",
            "note": "Every issue, exactly as published. Headlines start with the new newsletter."}


# =============================================================================
# History: Champions
# =============================================================================

def _season_team(inp: dict, season: str, m: str) -> str:
    teams = inp["all_teams"].get(season) or (inp["season_teams"] if season == inp["season"] else {})
    for v in teams.values():
        if v.get("manager") == m:
            return v.get("team_name") or m
    return m


def champions(inp: dict) -> dict:
    by_season: dict = {}
    for r in inp["all_standings"]:
        by_season.setdefault(r["season"], []).append(r)
    ss = inp["season_structure"]
    rows = []
    cur = inp["season"]
    cw = (inp["cup_winners"] or {}).get(cur)
    rows.append({"season": cur, "kind": "live", "lines": [
        {"k": "Regular season", "t": "in progress"},
        {"k": "Playoffs", "t": "weeks 16" + NDASH + "21"},
        {"k": "Cup", "t": (cw if cw else "the first Cup, weeks 22" + NDASH + "23: not played yet")}],
        "m": None, "team": "", "who": ""})
    for s in sorted(by_season, reverse=True):
        rs = by_season[s]
        champ = [r for r in rs if r.get("playoff_rank") == 1]
        ru = [r for r in rs if r.get("playoff_rank") == 2]
        first = [r for r in rs if r.get("regular_season_rank") == 1]
        if len(first) != 1:
            raise LeagueError(f"all_standings {s}: {len(first)} regular-season winners")
        bracket = (ss.get(s) or {}).get("bracket")
        if bracket is False:
            note = (ss.get(s) or {}).get("note") or "no bracket played"
            f1 = first[0]["manager"]
            rows.append({"season": s, "kind": "nobracket", "m": None, "team": "", "who": "",
                         "lines": [{"k": "No champion", "t": note},
                                   {"k": "Regular season", "t": f"{f1} ({_season_team(inp, s, f1)})"}]})
            continue
        if len(champ) != 1 or len(ru) != 1:
            raise LeagueError(f"all_standings {s}: {len(champ)} champions and {len(ru)} runners-up")
        c, r2, f1 = champ[0]["manager"], ru[0]["manager"], first[0]["manager"]
        rows.append({"season": s, "kind": "played", "m": c, "team": _season_team(inp, s, c), "who": c,
                     "lines": [{"k": "Runner-up", "t": f"{r2} ({_season_team(inp, s, r2)})"},
                               {"k": "Regular season", "t": f1}]})
    # The two seasons before the Yahoo data, season by season (Nick, 11-19):
    # 2014-15 and 2016-17 were played; 2015-16 was not. pre_data_era.seasons
    # must agree with its titles_won / playoff_championships totals, or RAISE.
    pre = inp["pre_data_era"] or {}
    pc = pre.get("playoff_championships") or {}
    tw = pre.get("titles_won") or {}
    ps = pre.get("seasons") or {}
    if not pc or not tw or not ps:
        raise LeagueError("league_config pre_data_era lacks playoff_championships, titles_won or seasons")
    for key, total, field in (("champion", pc, "playoff_championships"), ("regular_season", tw, "titles_won")):
        counted: dict = {}
        for s, v in ps.items():
            counted[v[key]] = counted.get(v[key], 0) + 1
        if {m: n for m, n in counted.items() if n} != {m: n for m, n in total.items() if n}:
            raise LeagueError(f"league_config pre_data_era.seasons' {key}s {counted} disagree with its {field} {total}")
    pre_rows = {s: {"season": s, "kind": "records", "m": v["champion"], "team": "", "who": v["champion"],
                    "lines": [{"k": "Runner-up", "t": v["runner_up"]},
                              {"k": "Regular season", "t": f"{v['regular_season']} (runner-up {v['regular_season_runner_up']})"},
                              {"k": "Records only", "t": "before the Yahoo data: no scores or stats"}]}
                for s, v in ps.items()}
    # newest first: every season from the first data-era one back to the first
    # pre-data-era one; a season in neither is one the league did not play
    first_era = min(int(r["season"][:4]) for r in inp["all_standings"])
    for y in range(first_era - 1, min(int(s[:4]) for s in ps) - 1, -1):
        s = f"{y}-{(y + 1) % 100:02d}"
        rows.append(pre_rows[s] if s in ps else
                    {"season": s, "kind": "off", "m": None, "team": "", "who": "",
                     "lines": [{"k": "Not played", "t": "the league took the season off"}]})
    n_played = len([r for r in rows if r["kind"] in ("played", "nobracket", "records")])
    return {"rows": rows, "meta": f"{n_played} seasons with results",
            "note": ("Champion = the playoff bracket's winner; regular season = first in the standings. "
                     "2014-15 and 2016-17 predate the Yahoo data: records only, from LEAGUEHISTORY and the "
                     "league's own account. 2015-16 was not played. The Cup starts this season.")}


# =============================================================================
# History: All-time standings
# =============================================================================

def _wl(s) -> tuple:
    parts = str(s).strip().strip("()").split("-")
    if len(parts) not in (2, 3) or not all(p.strip().isdigit() for p in parts):
        raise LeagueError(f"LEAGUEHISTORY record {s!r} is not W-L or W-L-T")
    n = [int(p) for p in parts]
    return (n[0], n[1], n[2] if len(n) == 3 else 0)


def alltime(inp: dict, results: dict) -> dict:
    """Every season with records: LEAGUEHISTORY's completed seasons (2014-15 and
    2016-17 included) plus this season, live (its regular-season weeks so far)."""
    reg = inp["reg_weeks"]
    live: dict = {m: [0, 0, 0] for m in inp["managers"]}
    live_post: dict = {m: [0, 0, 0] for m in inp["managers"]}
    live_pts: dict = {m: 0.0 for m in inp["managers"]}
    for w, rows in results.items():
        for a, b, sa, sb, o in rows:
            tgt = live if w <= reg else live_post
            live_pts[a] += sa
            live_pts[b] += sb
            ia, ib = (0, 1) if o == "a" else ((1, 0) if o == "b" else (2, 2))
            tgt[a][ia] += 1
            tgt[b][ib] += 1
    by = {r["manager_name"]: r for r in inp["leaguehistory"]}
    rows = []
    for m in inp["managers"]:
        r = by.get(m)
        if r is None:
            raise LeagueError(f"LEAGUEHISTORY has no row for {m}")
        for k in ("seasons_completed", "regular_season_record", "playoff_record", "titles_won",
                  "playoff_championships", "total_points_scored_to_date", "total_points_current_season"):
            if r.get(k) is None:
                raise LeagueError(f"LEAGUEHISTORY {m} lacks {k}")
        w, l, t = _wl(r["regular_season_record"])
        pw, pl, pt = _wl(r["playoff_record"])
        W, L, T = w + live[m][0], l + live[m][1], t + live[m][2]
        PW, PL, PT = pw + live_post[m][0], pl + live_post[m][1], pt + live_post[m][2]
        done_pts = float(r["total_points_scored_to_date"]) - float(r["total_points_current_season"])
        pf = done_pts + live_pts[m]
        g = W + L + T
        pct = (W + 0.5 * T) / g if g else 0.0
        rows.append({"m": m, "record": _rec(W, L, T), "pct": f"{pct * 100:.1f}%", "_pct": pct,
                     "pf": _int(pf), "champs": str(int(r["playoff_championships"])),
                     "firsts": str(int(r["titles_won"])), "post": _rec(PW, PL, PT),
                     "seasons": str(int(r["seasons_completed"]) + 1)})
    rows.sort(key=lambda x: (-x["_pct"], x["m"]))
    order = {}
    for i, x in enumerate(rows):
        x["rank"] = str(i + 1)
        order[x["m"]] = i
        x.pop("_pct")
    cur_through = max([w for w in results if w <= reg], default=0)
    return {"rows": rows,
            "meta": "every season with records",
            "note": (f"Scope: every season with records: 2014-15 and 2016-17 (records only, from LEAGUEHISTORY), "
                     f"2017-18 to 2025-26, and this season live through week {cur_through}. 2015-16 was not "
                     "played. W-L-T and win % are the regular season (a T counts half); the playoffs are the "
                     "second line. Champ = playoff titles; 1st = regular-season titles."),
            "seasons_note": "12 seasons"}


# =============================================================================
# History: head to head
# =============================================================================

def _reg_through(inp: dict, season: str) -> int:
    if season == inp["season"]:
        return inp["reg_weeks"]
    ss = (inp["season_structure"].get(season) or {}).get("regular_through")
    if ss is None:
        raise LeagueError(f"league_config season_structure {season} has no regular_through")
    return int(ss)


def h2h(inp: dict, results: dict) -> dict:
    """{a: {b: per season [reg W, L, T, post W, L, T, cup W, L, T]}} over the
    data era (all_matchups, 2017-18 on) and this season live; the grid cells
    for each phase, and each pair's season-by-season breakdown. The Cup
    (data_loader.stage_weeks "cup": from 2026-27) is its own phase, not
    inside Postseason (4c4 decision 7)."""
    ms = inp["managers"]
    tally: dict = {}
    cups = inp.get("cup_weeks") or {}

    def add(season, w, a, b, sa, sb):
        k0 = 6 if w in (cups.get(season) or []) else 3 if w > _reg_through(inp, season) else 0
        oa = "a" if sa > sb else "b" if sb > sa else "tie"
        for x, y, res in ((a, b, oa), (b, a, {"a": "b", "b": "a", "tie": "tie"}[oa])):
            v = tally.setdefault(x, {}).setdefault(y, {}).setdefault(season, [0] * 9)
            v[k0 + {"a": 0, "b": 1, "tie": 2}[res]] += 1
    for r in inp["all_matchups"]:
        if r["score_a"] == 0 and r["score_b"] == 0:
            continue
        add(r["season"], int(r["week"]), r["manager_a"], r["manager_b"], float(r["score_a"]), float(r["score_b"]))
    for w, rows in results.items():
        for a, b, sa, sb, _o in rows:
            add(inp["season"], w, a, b, sa, sb)
    seasons = sorted({s for x in tally.values() for y in x.values() for s in y}, reverse=True)
    phases = [("reg", "Regular season", 0), ("post", "Postseason", 3), ("cup", "Cup", 6)]
    grid = {k: [] for k, _l, _o in phases}
    pairs = {}
    for a in ms:
        cells = {k: [] for k, _l, _o in phases}
        for b in ms:
            if a == b:
                for k in cells:
                    cells[k].append(None)
                continue
            per = (tally.get(a) or {}).get(b) or {}
            tot = [sum(v[i] for v in per.values()) for i in range(9)]
            key = f"{a}|{b}"
            for k, _l, o in phases:
                cells[k].append({"t": _rec(*tot[o:o + 3]), "key": key})
            lines = []
            for s in seasons:
                v = per.get(s)
                if not v:
                    continue
                txt = (_rec(*v[:3]) + (f"{DOT}postseason {_rec(*v[3:6])}" if any(v[3:6]) else "")
                       + (f"{DOT}Cup {_rec(*v[6:])}" if any(v[6:]) else ""))
                lines.append({"season": s, "t": txt})
            pairs[key] = {"a": a, "b": b, "title": f"{a} vs {b}",
                          "total": (f"Regular season {_rec(*tot[:3])}{DOT}postseason {_rec(*tot[3:6])}"
                                    f"{DOT}Cup {_rec(*tot[6:])}"),
                          "lines": lines}
        for k in grid:
            grid[k].append({"m": a, "cells": cells[k]})
    with_cup = sorted(s for s, ws in cups.items() if ws)
    played = any(any(v[6:]) for x in tally.values() for y in x.values() for v in y.values())
    cw = cups.get(with_cup[0]) if with_cup else []
    cup_note = ((f" The Cup (weeks {cw[0]}{NDASH}{cw[-1]}, from {with_cup[0]}" + ("" if played else "; none played yet")
                 + ") is its own phase.") if with_cup else " No season has had a Cup yet.")
    return {"order": ms, "grid": grid, "pairs": pairs,
            "phases": [(k, lab) for k, lab, _o in phases],
            "note": ("Each row's record against each column, 2017-18 on (the Yahoo data) and this season live. "
                     "Postseason = the bracket and the third-place series." + cup_note + " Tap a cell for its seasons.")}


# =============================================================================
# History: the record book (config/RECORDS.json all_time)
# =============================================================================

# (key, label, group, value(entry) -> str, who(entry) -> str, ctx extra)
def _who_m(e):
    return e["manager"]


def _who_wl(e):
    return f"{e['winner']} over {e['loser']}"


def _who_p(e):
    return f"{e['player_name']}{DOT}{e['manager']}"


RECORD_BOOK = [
    ("highest_weekly_score", "Highest week", "Team weeks", lambda e: _int(e["score"]), _who_m),
    ("lowest_weekly_score", "Lowest week", "Team weeks", lambda e: _int(e["score"]), _who_m),
    ("biggest_blowout", "Biggest blowout", "Team weeks", lambda e: "+" + _int(e["margin"]), _who_wl),
    ("closest_game", "Closest game", "Team weeks", lambda e: _d1(e["margin"]), _who_wl),
    ("highest_daily_team_score", "Best team day", "Team weeks", lambda e: _int(e["total_fp"]), _who_m),
    ("longest_win_streak", "Longest winning streak", "Team seasons", lambda e: f"{int(e['length'])} weeks", _who_m),
    ("longest_loss_streak", "Longest losing streak", "Team seasons", lambda e: f"{int(e['length'])} weeks", _who_m),
    ("best_manager_season", "Best season", "Team seasons",
     lambda e: _rec(int(e["wins"]), int(e["losses"])), _who_m),
    ("worst_manager_season", "Worst season", "Team seasons",
     lambda e: _rec(int(e["wins"]), int(e["losses"])), _who_m),
    ("highest_single_game", "Best player game", "Player games", lambda e: _d1(e["fantasy_points"]), _who_p),
    ("lowest_single_game", "Worst player game", "Player games", lambda e: _d1(e["fantasy_points"]), _who_p),
    ("biggest_outperformance", "Biggest game over his average", "Player games",
     lambda e: "+" + _d1(e["delta"]), _who_p),
    ("best_rookie_single_game", "Best rookie game", "Player games", lambda e: _d1(e["fantasy_points"]), _who_p),
    ("most_fp_single_week", "Best player week", "Player weeks", lambda e: _d1(e["weekly_fp"]), _who_p),
    ("best_fppg_single_week", "Best player week, per game", "Player weeks",
     lambda e: _d1(e["weekly_fppg"]) + " FPPG", _who_p),
    ("best_rookie_fantasy_week", "Best rookie week", "Player weeks", lambda e: _d1(e["weekly_fp"]), _who_p),
    ("best_season_total_fp", "Best player season", "Player seasons", lambda e: _int(e["total_fp"]), _who_p),
    ("best_season_fppg", "Best player season, per game", "Player seasons",
     lambda e: _d1(e["fppg"]) + " FPPG", _who_p),
    ("best_rookie_season_total_fp", "Best rookie season", "Player seasons", lambda e: _int(e["total_fp"]), _who_p),
    ("most_games_over_40", "Most 40-point games", "Player seasons",
     lambda e: f"{int(e['count'])} of {int(e['gp'])}", _who_p),
    ("franchise_player", "Most points for one manager", "Careers", lambda e: _int(e["total_fp"]), _who_p),
    ("career_total_fp", "Most points, career", "Careers", lambda e: _int(e["total_fp"]), _who_p),
    ("longest_player_tenure", "Longest stay with one manager", "Careers",
     lambda e: f"{int(e['consecutive_seasons'])} seasons", _who_p),
    ("best_duo_week", "Best duo, one week", "Duos", lambda e: _d1(e["combined_fp"]),
     lambda e: f"{e['player1']} and {e['player2']}{DOT}{e['manager']}"),
    ("best_duo_season", "Best duo, one season", "Duos", lambda e: _int(e["combined_fp"]),
     lambda e: f"{e['player1']} and {e['player2']}{DOT}{e['manager']}"),
    ("best_keeper_value", "Best keeper", "Moves", lambda e: _int(e["total_fp"]), _who_p),
    ("biggest_draft_steal", "Biggest draft steal", "Moves", lambda e: _signed1(e["delta"]) + " FPPG", _who_p),
    ("biggest_draft_bust", "Biggest draft bust", "Moves", lambda e: _signed1(e["delta"]) + " FPPG", _who_p),
    ("trade_winner", "Best trade pickup", "Moves", lambda e: _int(e["post_trade_fp"]), _who_p),
    ("best_waiver_pickup", "Best free-agent pickup", "Moves", lambda e: _d1(e["fppg"]) + " FPPG", _who_p),
]
TILES = ["highest_weekly_score", "biggest_blowout", "closest_game", "highest_single_game"]


def _match_index(inp: dict, results: dict) -> dict:
    """{(season, week, manager): (a, b, sa, sb)}: every game's final, the
    data era from all_matchups and this season from RECORDS."""
    out = {}
    for r in inp["all_matchups"]:
        t = (r["manager_a"], r["manager_b"], float(r["score_a"]), float(r["score_b"]))
        out[(r["season"], int(r["week"]), r["manager_a"])] = t
        out[(r["season"], int(r["week"]), r["manager_b"])] = t
    for w, rows in results.items():
        for a, b, sa, sb, _o in rows:
            out[(inp["season"], w, a)] = (a, b, sa, sb)
            out[(inp["season"], w, b)] = (a, b, sa, sb)
    return out


def _game_tip(e: dict, idx: dict) -> Optional[dict]:
    s, w = e.get("season"), e.get("week")
    m = e.get("manager") or e.get("winner")
    if not s or w is None or not m or (s, int(w), m) not in idx:
        return None
    a, b, sa, sb = idx[(s, int(w), m)]
    if sa == sb:
        res = "tied"
    else:
        win, lose = (a, b) if sa > sb else (b, a)
        res = f"{win} won by {_d1(abs(sa - sb))}"
    head = f"{s}{DOT}Week {int(w)}" + (f"{DOT}{e['date']}" if e.get("date") else "")
    return {"h": head, "b": f"{a} {_d1(sa)}{DOT}{b} {_d1(sb)}", "f": res}


def records(inp: dict, results: dict) -> dict:
    at = inp["records_alltime"]
    idx = _match_index(inp, results)
    groups: List[dict] = []
    tiles = []
    for key, label, group, val, who in RECORD_BOOK:
        top = at.get(f"{key}_top10")
        if not isinstance(top, list) or not top:
            raise LeagueError(f"config/RECORDS.json all_time has no {key}_top10")
        rows = []
        for i, e in enumerate(top, 1):
            try:
                v, w = val(e), who(e)
            except (KeyError, TypeError, ValueError) as ex:
                raise LeagueError(f"RECORDS {key}_top10 row {i}: {type(ex).__name__} {ex}") from None
            ctx = str(e.get("season") or "")
            if e.get("week") is not None:
                ctx += f"{DOT}Wk {int(e['week'])}"
            player = e.get("player_name")
            rows.append({"rank": str(i), "value": v, "who": w, "ctx": ctx,
                         "card": _slug(player) if player else None, "player": player or "",
                         "tip": _game_tip(e, idx)})
        g = next((x for x in groups if x["label"] == group), None)
        if g is None:
            g = {"label": group, "lists": []}
            groups.append(g)
        g["lists"].append({"key": key, "label": label, "rows": rows})
        if key in TILES:
            tiles.append({"key": key, "label": label, "value": rows[0]["value"], "who": rows[0]["who"],
                          "ctx": rows[0]["ctx"], "tip": rows[0]["tip"]})
    tiles.sort(key=lambda t: TILES.index(t["key"]))
    wk = inp.get("records_week")
    return {"tiles": tiles, "groups": groups, "award_tiles": award_tiles(inp),
            "award_note": ("The awards' best seasons, 2017-18 to 2025-26 (data/historical/AWARDS_PAST.json): each "
                           "season through its own regular season, so a longer season has more games. Tap a tile."
                           if inp.get("awards_past") is not None else (inp.get("awards_past_error") or "")),
            "note": ("The record book (config/RECORDS.json), the top ten of each record, 2017-18 on and this "
                     f"season through week {wk}, the last week the weekly build recorded. Tap a game for its "
                     "final." if wk else "The record book (config/RECORDS.json).")}


# =============================================================================
# History: the draft, OVR then and later
# =============================================================================

def draft(inp: dict) -> dict:
    cur = inp["season"]
    cache = inp["draft_ovr"]
    seasons = []
    by_season: dict = {}
    for p in inp["all_drafts"]:
        by_season.setdefault(p["season"], []).append(p)
    cd = inp["draft_current"]
    if cd.get("season") != cur:
        raise LeagueError(f"config/DRAFT_PICKS_CURRENT.json is {cd.get('season')}, not {cur}")
    by_season[cur] = list(cd["picks"])
    for s in sorted(by_season, reverse=True):
        picks = sorted(by_season[s], key=lambda x: int(x["pick_number"]))
        in_round: dict = {}
        rows = []
        if s == cur:
            lt = inp["live_then"]
            then_of = (lambda name: (tuple(lt["players"].get(name) or (None, "not in the draft")) + ("open",))[:3]) \
                if lt else (lambda name: (None, "this season's opening-day OVR could not be computed: "
                                                + (inp["live_error"] or "unknown"), "open"))
            now = inp["now_ovr"]

            def later_of(name):
                if now is None:
                    return None, "today's ratings failed: " + (inp["ratings_error"] or "unknown")
                if name in now:
                    v = now[name]
                    return v, None if v is not None else "no OVR today"
                return None, "not rated today: on no roster and not on the Players tab"
            later_label, later_note = "Now", "today"
            open_day = lt["open"] if lt else None
        else:
            ent = ((cache or {}).get("seasons") or {}).get(s)
            if ent is None:
                later_of = (lambda name, s=s: (None, f"not computed: data/historical/DRAFT_OVR.json has "
                                                     f"no {s} (python scripts/build_draft_ovr.py)"))
                then_of = (lambda name, f=later_of: f(name) + ("open",))
            else:
                look = {(int(x["pick_number"])): x for x in ent["picks"]}

                def then_of(name, look=look, picks=picks):
                    x = next((look.get(int(p["pick_number"])) for p in picks if p["player_name"] == name), None)
                    return (x["then"], x["then_reason"], x.get("then_point", "open")) if x else \
                        (None, "not in the cache", "open")

                def later_of(name, look=look, picks=picks):
                    x = next((look.get(int(p["pick_number"])) for p in picks if p["player_name"] == name), None)
                    return (x["later"], x["later_reason"]) if x else (None, "not in the cache")
            later_label, later_note = "Deadline", "at the trade-deadline point"
            open_day = ent["open"] if ent else None
        for p in picks:
            rd = int(p["round"])
            in_round[rd] = in_round.get(rd, 0) + 1
            name = p["player_name"]
            t, tr, tp = then_of(name)
            n, nr = later_of(name)
            if t is not None and n is not None:
                k = int(n) - int(t)
                chg, d = ((f"{UP}{k}", "up") if k > 0 else (f"{DOWN}{-k}", "down") if k < 0 else (NDASH, "flat"))
            else:
                chg, d = "", "none"
            rows.append({"pick": f"{rd}.{in_round[rd]:02d}", "overall": str(int(p["pick_number"])),
                         "m": p["manager"], "player": name, "card": _slug(name), "keeper": bool(p.get("is_keeper")),
                         "then": (str(t) + (" (wk 2)" if tp == "week2" else "")) if t is not None else DASH,
                         "then_why": tr or "",
                         "later": str(n) if n is not None else DASH, "later_why": nr or "",
                         "chg": chg, "dir": d})
        counts: dict = {}
        for p in picks:
            if not p.get("is_keeper"):
                counts[p["manager"]] = counts.get(p["manager"], 0) + 1
        seasons.append({"season": s, "later_label": later_label,
                        "meta": (f"opening day {open_day[5:]}" if open_day else "opening day not computed")
                        + f"{DOT}{later_label.lower()} {later_note}" if s != cur else
                        (f"opening day {open_day[5:]}" if open_day else "opening day not computed") + f"{DOT}now today",
                        "picks": str(len(picks)),
                        "drafted": DOT.join(f"{m} {counts[m]}" for m in sorted(counts)), "rows": rows})
    return {"seasons": seasons, "default": cur,
            "note": ("OVR then = his OVR on the season's opening day, from that day's rosters and log. Later = "
                     "his OVR at the trade-deadline point for a past season (OVR is rest-of-season value, so "
                     "none exists on a season's last day), or today's for this season. A player with no earlier "
                     "season in the league log is rated at the league average on opening day, so his then is "
                     "his OVR at the week-2 point instead, marked (wk 2). \u2014 says why there is none. "
                     "K = a keeper.")}


# =============================================================================
# History: trades
# =============================================================================

def _trade_date(t: dict, season: str) -> tuple:
    """(sort key ISO, the label)."""
    from ..keeper_history import trade_dates
    first, last = trade_dates(t.get("date"), season)
    a = date.fromisoformat(first)
    if first == last:
        return first, f"{a:%b} {a.day}, {a.year}"
    b = date.fromisoformat(last)
    return first, f"{a:%b} {a.day}{NDASH}{b.day}, {b.year}" if a.month == b.month else \
        f"{a:%b} {a.day}{NDASH}{b:%b} {b.day}, {b.year}"


def trades(inp: dict) -> dict:
    items = []
    for t in list(inp["all_trades"]) + list(inp["trades_now"]):
        for k in ("season", "date", "trader_manager", "tradee_manager", "players"):
            if t.get(k) is None:
                raise LeagueError(f"a trade lacks {k}: {json.dumps(t)[:120]}")
        a, b = t["trader_manager"], t["tradee_manager"]
        got = {a: [], b: []}
        for mv in t["players"]:
            if mv["to_manager"] not in got or mv["from_manager"] not in got:
                raise LeagueError(f"a {t['season']} trade moves {mv['player_name']} outside its two managers")
            got[mv["to_manager"]].append({"t": mv["player_name"], "card": _slug(mv["player_name"])})
        picks = t.get("picks") or {}
        for sender, lst in picks.items():
            if sender not in got:
                raise LeagueError(f"a {t['season']} trade's picks name {sender}, not one of its managers")
            other = b if sender == a else a
            got[other] += [{"t": str(x), "card": None} for x in lst]
        key, label = _trade_date(t, t["season"])
        items.append({"key": key, "date": label, "season": t["season"], "ms": [a, b],
                      "sides": [{"m": m, "gets": got[m]} for m in (a, b)]})
    items.sort(key=lambda x: x["key"], reverse=True)
    for x in items:
        x.pop("key")
    return {"items": items, "count": str(len(items)),
            "note": ("Every trade, newest first: 2017-18 on from Yahoo (data/historical/all_trades.json) and this "
                     "season's (config/TRADES.json). Draft picks are named by their original owner."),
            "empty": "No trade on record."}


# =============================================================================
# build
# =============================================================================

def build(inp: dict) -> tuple:
    """(league, history) from gather()'s inputs. RAISES LeagueError."""
    from ..league_clock import league_tz
    tz = league_tz()
    for m in inp["managers"]:
        if m not in inp["teams"]:
            raise LeagueError(f"no team mark for {m}")
    res = week_results(inp)
    league = {"segs": [list(x) for x in SEGS], "chips": [list(x) for x in CHIPS],
              "standings": standings(inp, res), "chart": chart(inp, res, tz), "power": power_history(inp),
              "awards": awards(inp), "archive": archive(inp)}
    history = {"chips": [list(x) for x in CHIPS], "champions": champions(inp), "alltime": alltime(inp, res),
               "h2h": h2h(inp, res), "records": records(inp, res), "draft": draft(inp), "trades": trades(inp),
               # 4c6: Awards' Past winners ride in the side file with the rest of the history
               # (static public history: off the payload's 400 KB); the Awards part reads them
               "awards_past": awards_past(inp)}
    return league, history
