"""
hub_state.py -- the hub's one payload, output/hub_state.json (Step 1b).

The hub (claude/SELF_RUNNING_DESIGN.md s.3) is a page that displays and never
computes: every number on it is a string in this payload, formatted here.
This module assembles it from what the engine already computes, through the
same builders the newsletter uses, so the hub cannot disagree with the
newsletter (design invariant 17):

  header       the league clock, the engine, price_lock.status and its message,
               the line's own freshness
  matchups     output/live_lines_weekN.json, as live_lines_page decomposes it
               (refuses a payload from another engine: EngineMismatch)
  power        report_builder.build_power_rankings, its order; title odds from
               the latest row of output/title_odds_history.jsonl, change since
               the row before it; adds used through
               transaction_rulings.adds_by_budget_week (add_budget_week)
  rosters      FPPG and L14 from data/player_actuals.json (Yahoo daily lines;
               modules/player_actuals), Proj = PLAYERLIST projectedFPPG, GL,
               Keep = keepability v3 (computed here, never saved: only the
               Monday-published keep chances are scored),
               status = report_builder.build_current_team_health's, joined
               dates through season_performers.joined_dates
  grid         games by players who will play (s.1a of the 1b handoff)
  free_agents  data_loader.free_agents, top N by Yahoo projection
  advice       null: the slot only (advice v2)
  moves        the synced waivers files and TRADES.json, last 7 days
  newsletter   the archive index (modules/hub_archive)

RAISES (HubInputError, or the builder's own error) on a missing input, naming
the file. The pieces that come later (the ledger, the Monday checklist,
advice) are labelled empty states, never invented data.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

SCHEMA = 1
PAYLOAD_RELPATH = Path("output") / "hub_state.json"
MOVES_DAYS = 7
WEEKDAY_LETTER = "MTWTFSS"
MINUS = "\u2212"
DASH = "\u2014"


class HubInputError(RuntimeError):
    """An input the hub needs is missing or inconsistent; the file is named."""


# =============================================================================
# config
# =============================================================================

def hub_config(league_config: dict = None) -> dict:
    """league_config.json -> "hub". Every key required."""
    if league_config is None:
        from .data_loader import _LEAGUE_CONFIG as league_config
    hub = league_config.get("hub")
    if not isinstance(hub, dict):
        raise HubInputError("config/league_config.json has no \"hub\" block")
    out = {}
    for k in ("free_agents_top_n", "light_night_max"):
        v = hub.get(k)
        if not isinstance(v, int) or isinstance(v, bool) or v < 1:
            raise HubInputError(f"config/league_config.json hub.{k} must be a positive integer, "
                                f"not {v!r}")
        out[k] = v
    return out


# =============================================================================
# formatting: every number leaves this module as a string
# =============================================================================

def _pct(x: float) -> str:
    return f"{float(x):.1f}%"


def _int(x: float) -> str:
    return f"{float(x):,.0f}"


def _signed(x: float) -> str:
    s = f"{float(x):g}"
    return s.replace("-", MINUS) if float(x) < 0 else ("+" + s if float(x) > 0 else s)


def _odds(x) -> str:
    n = int(x)
    return f"+{n}" if n > 0 else str(n).replace("-", MINUS)


def _md(d: date) -> str:
    return f"{d.month:02d}-{d.day:02d}"


def _mon_d(d: date) -> str:
    return f"{d.strftime('%a')} {d.strftime('%b')} {d.day}"


def _clock_text(dt: datetime) -> str:
    h = dt.strftime("%I").lstrip("0") or "12"
    return f"{_mon_d(dt.date())}, {h}:{dt.strftime('%M')} {dt.strftime('%p')} Pacific"


# =============================================================================
# the header and the matchups
# =============================================================================

def load_line(base: Path, week: int) -> dict:
    p = base / "output" / f"live_lines_week{week}.json"
    if not p.is_file():
        raise HubInputError(f"{p.relative_to(base)} is missing: the hub shows the live line, and "
                            f"week {week} has none. Run python scripts/refresh_lines.py --week {week}")
    payload = json.loads(p.read_text(encoding="utf-8"))
    if int(payload.get("week", -1)) != week:
        raise HubInputError(f"{p.relative_to(base)} is for week {payload.get('week')}, not {week}")
    return payload


def lock_note(status: dict, base: Path, week: int) -> dict:
    """price_lock.status -> the header's note. When locked, the waiting count
    is the refresh service's own (its runs record), else no count is claimed."""
    from . import price_lock
    if not status["first_tip"]:
        return {"locked": False, "text": "No games today: lines are live."}
    tip = datetime.fromisoformat(status["first_tip"])
    tip_text = f"{tip.strftime('%I').lstrip('0')}:{tip.strftime('%M')} {tip.strftime('%p')} Pacific"
    if not status["locked"]:
        return {"locked": False,
                "text": f"Lines are live until today's first tip, {tip_text}. "
                        "Then they lock until the 12:01 AM update."}
    runs = base / "output" / f"live_lines_week{week}.runs.json"
    waiting = None
    if runs.is_file():
        blob = json.loads(runs.read_text(encoding="utf-8"))
        last = (blob.get("runs") or [None])[-1] or {}
        if last.get("outcome") == "locked" and str(last.get("league_day", ""))[:10] == status["league_day"]:
            waiting = len(last.get("waiting") or [])
    if waiting is not None:
        return {"locked": True, "text": price_lock.lock_message(waiting)}
    return {"locked": True, "text": f"Lines locked while games are on (first tip {tip_text}); "
                                    "priced after tonight's games."}


def build_matchups(line: dict) -> dict:
    done = len(line.get("completed_dates") or [])
    left = len(line.get("remaining_dates") or [])
    cards = []
    for ln in line["lines"]:
        a_fav = float(ln["spread_a"]) < float(ln["spread_b"])
        fav, spread = (ln["manager_a"], ln["spread_a"]) if a_fav else (ln["manager_b"], ln["spread_b"])
        if float(ln["spread_a"]) == float(ln["spread_b"]):
            spread_text = "Pick'em"
        else:
            spread_text = f"{fav} {_signed(spread)}"
        side = lambda s: {"team": ln[f"team_name_{s}"], "manager": ln[f"manager_{s}"],
                          "now": _int(ln[f"banked_{s}"]), "proj": _int(ln[f"projected_final_{s}"]),
                          "win": _pct(ln[f"win_prob_{s}"])}
        cards.append({"a": side("a"), "b": side("b"), "bar_a": _pct(ln["win_prob_a"]),
                      "spread": spread_text, "total": _int(ln["over_under"]),
                      "moneyline": f"{_odds(ln['moneyline_a'])} / {_odds(ln['moneyline_b'])}"})
    total = done + left
    clock = (f"{done} of {total} game days played" if total else "no game days this week")
    return {"clock": clock, "cards": cards}


# =============================================================================
# power rankings
# =============================================================================

def _parse_expected(text: str) -> tuple:
    parts = [float(x) for x in str(text).split("-")]
    if len(parts) == 2:
        return parts[0], parts[1], 0.0
    if len(parts) == 3:
        return tuple(parts)
    raise HubInputError(f"expected record {text!r} is not W-L or W-L-T")


def odds_kind(week: int, season_config: dict, cup_weeks: list) -> str:
    """"title" through the regular season's next-to-last week; "playoff" from
    its last week (s.3: from week 15); "cup" in the Cup weeks."""
    if week in set(cup_weeks or []):
        return "cup"
    if week >= int(season_config["regular_season_weeks"]):
        return "playoff"
    return "title"


ODDS_LABEL = {"title": "Title odds", "playoff": "Playoff odds", "cup": "Cup odds"}
ODDS_KEY = {"title": "title_odds", "playoff": "playoff_odds", "cup": "cup_odds"}


def title_odds_inputs(base: Path, data, managers) -> tuple:
    """(TitleOddsResult for build_power_rankings, latest history row, the row
    before it or None, the report it came from).

    The history row is the record of the title-odds run (decision 4). It holds
    the odds; build_power_rankings also needs each team's expected record (its
    second sort term), which that run's stats report holds. The report must
    be the same run (week and seed), and its records must still be the
    league's: otherwise the odds no longer describe the standings."""
    from . import title_odds_history as toh
    from .simulator_title_odds import TitleOddsResult
    rows = toh.read(base)
    if not rows:
        raise HubInputError(f"{toh.HISTORY_FILE} has no rows: the hub's title odds come from it")
    latest, prev = rows[-1], (rows[-2] if len(rows) > 1 else None)
    week = latest.get("week")
    if week is None:
        raise HubInputError(f"{toh.HISTORY_FILE}'s latest row ({latest['run_id']}) has no week")
    rp = base / "output" / f"stats_report_week{int(week)}.json"
    if not rp.is_file():
        raise HubInputError(f"{rp.relative_to(base)} is missing: power rankings need the expected "
                            f"records of the title-odds run {latest['run_id']}")
    report = json.loads(rp.read_text(encoding="utf-8"))
    if (report.get("metadata") or {}).get("seed") != latest["seed"]:
        raise HubInputError(
            f"{rp.relative_to(base)} (seed {(report.get('metadata') or {}).get('seed')}) is not the run "
            f"that wrote the latest title-odds row {latest['run_id']} (seed {latest['seed']}): "
            "the hub cannot order the power rankings from two runs. Step 1c's nightly run passes "
            "its own TitleOddsResult")
    published = {p["manager"]: p for p in report.get("power_rankings") or []}
    if set(published) != set(managers):
        raise HubInputError(f"{rp.relative_to(base)} has no power rankings for every manager")
    records = {m: data.get_manager_record(m) for m in managers}
    changed = [m for m in managers if str(records[m]) != published[m]["record"]]
    if changed:
        moved = ", ".join(f"{m} {published[m]['record']} -> {records[m]}" for m in changed)
        raise HubInputError(
            f"records changed since the title-odds run {latest['run_id']} ({moved}): "
            "a week's results are in and its title odds are not. Run the weekly build first")
    odds = {m: float(latest["title_odds"][m]) for m in managers}
    tor = TitleOddsResult(
        num_simulations=int(latest["num_simulations"]), current_week=int(week),
        title_odds=odds,
        expected_record={m: _parse_expected(published[m]["expected_record"]) for m in managers},
        finish_distribution={m: {int(k): v for k, v in published[m]["finish_distribution"].items()}
                             for m in managers},
        magic_numbers={}, current_records=records, h2h_records={}, title_odds_delta={})
    return tor, latest, prev, report


def build_power(base: Path, data, managers, keeper_watch: dict, week: int, adds: dict,
                budget: int, season_config: dict, cup_weeks: list) -> tuple:
    """(the power block, the build_power_rankings rows it was ordered by)."""
    from .report_builder import build_power_rankings
    from .data_loader import MANAGER_TO_TEAM
    tor, latest, prev, _report = title_odds_inputs(base, data, managers)
    ranked = build_power_rankings(tor, data.records, data.leaguehistory, keeper_watch=keeper_watch)
    kind = odds_kind(week, season_config, cup_weeks)
    key = ODDS_KEY[kind]
    if kind != "title" and not latest.get(key):
        raise HubInputError(f"week {week} shows {ODDS_LABEL[kind].lower()}, and the latest title-odds "
                            f"row {latest['run_id']} has no {key}")
    shown = latest[key]
    before = (prev or {}).get(key) if prev else None
    rows = []
    for pr in ranked:
        m = pr["manager"]
        if before and m in before:
            d = float(shown[m]) - float(before[m])
            delta = (f"\u25b2 {d:.1f}" if d > 0.05 else f"\u25bc {abs(d):.1f}" if d < -0.05 else "\u2013 0.0")
            ddir = "up" if d > 0.05 else "down" if d < -0.05 else "flat"
        else:
            delta, ddir = DASH, "none"
        used = len((adds or {}).get(m, []))
        rows.append({"rank": str(pr["rank"]), "manager": m, "team": MANAGER_TO_TEAM.get(m, m),
                     "record": pr["record"], "odds": _pct(shown[m]), "delta": delta,
                     "delta_dir": ddir, "adds": f"{used} / {budget}",
                     "adds_over": used > budget})
    as_of = datetime.fromisoformat(latest["as_of"])
    from . import title_odds_history as toh
    chart = []
    for r in reversed(toh.read(base)):
        if not r.get(key):
            continue
        at = datetime.fromisoformat(r["as_of"])
        chart.append({"label": f"Week {r.get('week', '?')} \u00b7 {_mon_d(at.date())}",
                      "values": [{"manager": m, "text": _pct(r[key][m]), "width": _pct(r[key][m])}
                                 for m in [x["manager"] for x in rows]]})
    note = (f"Change is since the run before ({_clock_text(datetime.fromisoformat(prev['as_of']))})."
            if prev else "Change appears from the second run in the history.")
    block = {"kind": kind, "label": ODDS_LABEL[kind], "rows": rows,
             "as_of": f"{ODDS_LABEL[kind]} as of {_clock_text(as_of)}",
             "note": note + f" Adds are this week's, out of {budget}, and count chat claims in the "
                           "week they were made.",
             "chart": {"points": chart,
                       "note": ("One run so far; the nightly runs add a point each night from step 1c."
                                if len(chart) < 2 else "Newest first.")}}
    return block, ranked


# =============================================================================
# availability: who plays on a day (the grid's rule, s.1a)
# =============================================================================

def override_out_on(entry: dict, d: date, week: int, week_start: date) -> bool:
    """An INJURY_OVERRIDES entry covering day d (of fantasy week `week`):
    the week in out_weeks (from out_from on, when out_from falls in it), or the
    return week before return_date. The same reading as schedule_strength,
    plus out_from (absence.out_from_applies)."""
    from . import absence
    out_from = absence.parse_out_from(entry.get("out_from"))
    if week in set(entry.get("out_weeks") or []):
        if out_from is not None and week_start <= out_from:
            return absence.out_from_applies(d, week_start, out_from)
        return True
    if entry.get("return_week") == week:
        ret = absence.parse_return_date(entry.get("return_date"), entry.get("player_name"))
        if ret is not None and d < ret:
            return True
    return False


class Availability:
    """Who of a roster has a game on a day and will play it."""

    def __init__(self, rosters: dict, il_slots: dict, tags: dict, overrides: dict,
                 this_week: int, player_info: dict, team_dates: dict, weeks: dict, today: date):
        """team_dates: {NBA team: its game dates}; weeks: {fantasy week:
        (first day, last day)}. from_data() reads both from the engine.
        today: the league day; an O tag counts its games from here."""
        from .data_loader import PlayerIndex
        from . import absence
        if not isinstance(today, date):
            raise HubInputError("Availability needs today's league date: an O tag's games count from it")
        self.rosters, self.this_week, self.today = rosters, this_week, today
        self.il = {m: PlayerIndex({n: True for n in v}) for m, v in (il_slots or {}).items()}
        self.tags = PlayerIndex(dict(tags or {}))
        self.over = PlayerIndex({e["player_name"]: e for e in (overrides or {}).get("players", [])})
        self.team_dates = {t: set(v) for t, v in team_dates.items()}
        self.info = player_info
        self.weeks = dict(weeks)
        self.absence = absence
        for m, names in rosters.items():
            for n in names:
                if (self.info.get(n) or {}).get("nba_team") is None:
                    raise HubInputError(f"{n} ({m}) has no NBA team in PLAYERLIST or LINEUPS: his "
                                        "games cannot be counted")

    @classmethod
    def from_data(cls, data, rosters, il_slots, tags, overrides, this_week, player_info, today):
        from .simulator_betting import team_season_dates
        weeks = {int(w["week"]): (date.fromisoformat(str(w["start_date"])[:10]),
                                  date.fromisoformat(str(w["end_date"])[:10]))
                 for w in data.schedule.get("weeks", [])}
        return cls(rosters, il_slots, tags, overrides, this_week, player_info,
                   team_season_dates(data), weeks, today)

    def week_of(self, d: date) -> int:
        for w, (a, b) in self.weeks.items():
            if a <= d <= b:
                return w
        raise HubInputError(f"{d} is in no fantasy week of config/SCHEDULE.json")

    def has_game(self, name: str, d: date) -> bool:
        return d in self.team_dates.get(self.info[name]["nba_team"], ())

    def o_tag_dates(self, name: str) -> set:
        """An O tag with no injury entry costs at most absence.MAX_TAG_GAMES
        games (Nick, 11-01; the engine's cap): his team's next ones from today,
        across a week boundary if need be (Nick, 11-03: "maximum of 3 missed
        games into the future"). Longer absences go in INJURY_OVERRIDES."""
        dates = sorted(x for x in self.team_dates.get(self.info[name]["nba_team"], ()) if x >= self.today)
        return set(dates[:self.absence.MAX_TAG_GAMES])

    def out(self, name: str, d: date) -> bool:
        tag = self.tags.get(name)
        if tag is not None and self.absence.season_out(tag):
            return True
        if tag is not None and self.absence.normalised_tag(tag) == "O" and d in self.o_tag_dates(name):
            return True
        e = self.over.get(name)
        if e is not None:
            w = self.week_of(d)
            if override_out_on(e, d, w, self.weeks[w][0]):
                return True
        return False

    def players(self, manager: str, d: date) -> List[str]:
        il = self.il.get(manager) or {}
        return [n for n in self.rosters.get(manager, [])
                if n not in il and self.has_game(n, d) and not self.out(n, d)]


def build_grid_tab(av: Availability, managers, days: List[date], light_max: int,
                   nba_games_on: Dict[date, int]) -> dict:
    """One tab: per manager, per day, the count who will play; overflow over
    10; Starts = the positional fit (schedule_strength.fill_daily_lineup_detail,
    the newsletter grid's own fit; never more than 10); Idle = count - starts."""
    from .schedule_strength import fill_daily_lineup_detail, MAX_STARTERS_PER_DAY
    rows = []
    for m in managers:
        cells, starts, idle = [], 0, 0
        for d in days:
            ps = av.players(m, d)
            n = len(ps)
            started, _benched, _rem = fill_daily_lineup_detail(
                [(p, set(av.info[p]["positions"]), float(av.info[p].get("proj_fppg", 0.0))) for p in ps])
            s = len(started)
            starts += s
            idle += n - s
            if nba_games_on.get(d, 0) == 0:
                kind = "off"
            elif n > MAX_STARTERS_PER_DAY:
                kind = "over"
            elif n <= light_max:
                kind = "light"
            else:
                kind = "normal"
            cells.append({"n": str(n), "kind": kind,
                          "overflow": str(max(0, n - MAX_STARTERS_PER_DAY)),
                          "starts": str(s)})
        rows.append({"manager": m, "cells": cells, "starts": str(starts), "idle": str(idle),
                     "_starts": starts})
    rows.sort(key=lambda r: (-r["_starts"], r["manager"]))
    for r in rows:
        del r["_starts"]
    return {"days": [{"dow": WEEKDAY_LETTER[d.weekday()], "day": str(d.day), "date": d.isoformat()}
                     for d in days],
            "range": (f"{days[0].strftime('%b')} {days[0].day}\u2013"
                      f"{days[-1].strftime('%b')+' ' if days[-1].month != days[0].month else ''}{days[-1].day}"
                      if days else ""),
            "rows": rows}


def roster_size_text(n_rostered: int, n_in_il: int, active_cap: int, il_cap: int) -> str:
    """Active and IL counted apart, never one total "of 17" (Nick, 11-02): a
    team of 15 with both IL slots empty has a FULL active roster -- an empty
    IL slot takes only an O/OFS player (rule 2), it is not an open spot."""
    active = n_rostered - n_in_il
    if active > active_cap or n_in_il > il_cap or active < 0:
        raise HubInputError(f"a roster of {n_rostered} with {n_in_il} in IL is over the league's "
                            f"{active_cap} active + {il_cap} IL")
    return f"Active {active}/{active_cap} \u00b7 IL {n_in_il}/{il_cap}"


# =============================================================================
# the build
# =============================================================================

def build(base_path=".", *, now: datetime = None, data=None, allow_engine_mismatch: bool = False,
          archive_index: dict = None, echo=print) -> dict:
    base = Path(base_path)
    from .league_clock import league_now
    from .data_loader import (load_all_data, MANAGERS, MANAGER_TO_TEAM, PlayerIndex,
                              free_agents as dl_free_agents, add_budget_for, CURRENT_SEASON,
                              _LEAGUE_CONFIG)
    from . import week_state as ws, price_lock, live_lines_page as llp, player_actuals as pa
    from . import keepability_v3 as kv3, transaction_rulings as tr
    from .report_builder import build_current_team_health
    from .simulator_betting import schedule_week_dates
    from .schedule_strength import build_player_info_map, augment_player_info_from_lineups
    from .simulator_cup_odds import cup_weeks
    from .season_performers import joined_dates, season_first_day, load_nba_schedule

    cfg = hub_config()
    now = now or league_now()
    if now.tzinfo is None:
        raise HubInputError("the hub's clock must be timezone-aware (the league clock)")
    today = now.date()
    data = data or load_all_data(base, current_week=None)
    week = ws.week_for_date(data, today)
    report_week = week - 1
    managers = list(MANAGERS)
    wk_dates = schedule_week_dates(data)
    this_days = [d for d in wk_dates[week] if d >= today]
    next_days = list(wk_dates.get(week + 1) or [])
    yesterday = today - timedelta(days=1)

    # --- the line, and its engine
    line = load_line(base, week)
    check = llp.engine_check(line, base)
    if not check["ok"] and not allow_engine_mismatch:
        raise llp.EngineMismatch(f"week {week} live line: {check['why']}")
    status = price_lock.status(now, data.nba_schedule)
    line_at = datetime.fromisoformat(line["generated_at"])

    # --- the tags the line was priced with (its state file), the IL slots
    sp_ = base / "output" / f"live_lines_week{week}.state.json"
    if not sp_.is_file():
        raise HubInputError(f"{sp_.relative_to(base)} is missing: the hub's injury tags are the "
                            "live line's")
    tag_state = json.loads(sp_.read_text(encoding="utf-8"))
    tags = {n: t["tag"] for n, t in (tag_state.get("tags") or {}).items()}
    from .roster_plan import load_il_slots, check_against_rosters
    rosters = {m: list(v) for m, v in data.get_current_rosters().items()}
    il_state = load_il_slots(base, data)
    if int(il_state.get("fantasy_week", -1)) != week:
        raise HubInputError(f"data/IL_SLOTS.json is for fantasy week {il_state.get('fantasy_week')}, "
                            f"not week {week}: run python scripts/sync_transactions.py --week "
                            f"{report_week} --apply")
    check_against_rosters(il_state, rosters)
    il_slots = {m: list(v) for m, v in (il_state.get("slots") or {}).items()}

    # --- the builders
    health = build_current_team_health(data, report_week, injury_statuses=tags, il_state=il_state)
    kw = kv3.keeper_watch(data, report_week, root=base)
    keep_of = {(p["manager"], p["player_name"]): p for p in kw["players"]}
    budget = add_budget_for(CURRENT_SEASON)
    if budget is None:
        raise HubInputError(f"no add budget for {CURRENT_SEASON}")
    sched = data.schedule
    adds = tr.adds_by_budget_week(base, sched).get(week, {})
    power, ranked = build_power(base, data, managers, kw, week, adds, budget,
                                _LEAGUE_CONFIG["season"], cup_weeks())
    actuals = pa.load(base)
    first_day = date.fromisoformat(actuals["first_day"])
    joined, jfail = joined_dates(base, rosters, sched, first_day.isoformat())
    if jfail:
        raise HubInputError("when a player joined his team: " + "; ".join(jfail))

    # --- players: positions, teams, projections
    pl = data.playerlist
    info = build_player_info_map(pl)
    augment_player_info_from_lineups(info, rosters, data.lineups)
    proj = PlayerIndex({r["player_name"]: r for r in pl.to_dict("records")})
    av = Availability.from_data(data, rosters, il_slots, tags,
                                data.injury_overrides or {"players": []}, week, info, today)
    nba_games_on = {}
    for d in this_days + next_days:
        nba_games_on[d] = sum(1 for dates in av.team_dates.values() if d in dates) // 2

    # --- the grid
    this_tab = build_grid_tab(av, managers, this_days, cfg["light_night_max"], nba_games_on)
    next_tab = build_grid_tab(av, managers, next_days, cfg["light_night_max"], nba_games_on)
    grid = {"tabs": [
        dict(this_tab, key="this", label="Rest of this week",
             note=f"From {_mon_d(today)}. Counts players who will play: not in an IL slot, not "
                  "out under an O tag (at most his team's next 3 games), OFS, or an injury entry."),
        dict(next_tab, key="next", label="Next week",
             note="As rosters stand today: IL slots as they are now, injury entries by date, "
                  "OFS out. An O tag costs at most his team's next 3 games from today, which can "
                  "reach into next week."),
    ], "legend": {"light": f"Light night ({cfg['light_night_max']} or fewer)",
                  "over": "More than 10: some sit"},
        "foot": "Starts: games that fit a starting lineup. Idle: games by players who sit."}
    starts_left = {r["manager"]: r["starts"] for r in this_tab["rows"]}

    # --- rosters
    status_of = {}
    for m in managers:
        for p in health["teams"][m]["injured_players"]:
            status_of[(m, p["player"])] = {"source": p["source"], "why": p["why"]}
    over_idx = PlayerIndex({e["player_name"]: e for e in (data.injury_overrides or {}).get("players", [])})
    team_dates = av.team_dates
    roster_blocks = {}
    by_rank = {r["manager"]: r for r in power["rows"]}
    active_cap = int(_LEAGUE_CONFIG["league_structure"]["starters"]) + \
        int(_LEAGUE_CONFIG["league_structure"]["bench"])
    il_cap = int(_LEAGUE_CONFIG["league_structure"]["il_slots"])
    for m in managers:
        il_here = PlayerIndex({n: True for n in il_slots.get(m, [])})
        players = []
        for n in rosters.get(m, []):
            row = proj.get(n)
            if row is None:
                raise HubInputError(f"{n} ({m}) is not in data/PLAYERLIST.xlsx: no Yahoo projection")
            k = keep_of.get((m, n))
            if k is None:
                raise HubInputError(f"keepability v3 has no keep chance for {n} ({m})")
            line_k = kv3.line_for(kw, m)
            keep_p = k["keep_k5"] if line_k == 5 else k["keep_k6"] if line_k == 6 else None
            if keep_p is None:
                raise HubInputError(f"{m}'s keeper line is {line_k}; keep chance exists at 5 and 6")
            s_pts, s_gp = pa.season(actuals, n, yesterday)
            l_pts, l_gp = pa.last14(actuals, n, yesterday)
            in_il = n in il_here
            gl = sum(1 for d in this_days if d in team_dates.get(info[n]["nba_team"], ()))
            st = status_of.get((m, n), {"source": "healthy", "why": ""})
            chips = []
            if in_il:
                chips.append({"text": "IL slot", "kind": "il"})
                e = over_idx.get(n)
                if e is not None and e.get("return_date"):
                    from .absence import parse_return_date
                    chips.append({"text": f"back {_md(parse_return_date(e['return_date'], n))}",
                                  "kind": "il"})
            elif st["source"] == "season_out":
                chips.append({"text": "OFS", "kind": "out"})
            elif st["source"] == "override":
                chips.append({"text": st["why"].replace("override, ", "out, "), "kind": "out"})
            elif st["source"] == "tag":
                t = st["why"].split(" ")[0]
                chips.append({"text": t, "kind": "out" if t == "O" else "q"})
            j = joined.get((m, n))
            if j:
                chips.append({"text": f"since {_md(date.fromisoformat(j))}", "kind": "new"})
            sort = {"name": n.lower(),
                    "fppg": (s_pts / s_gp) if s_gp else -1.0,
                    "proj": float(row.get("projectedFPPG") or 0.0),
                    "l14": (l_pts / l_gp) if l_gp else -1.0,
                    "gl": -1 if in_il else gl, "keep": float(keep_p)}
            players.append({
                "name": n, "pos": str(row.get("player_position(s)") or ""),
                "nba": info[n]["nba_team"],
                "fppg": pa.fppg_text(s_pts, s_gp), "proj": f"{float(row.get('projectedFPPG') or 0):.1f}",
                "l14": pa.fppg_text(l_pts, l_gp), "gl": DASH if in_il else str(gl),
                "keep": kv3.pct(keep_p), "keep_strong": keep_p >= 0.5,
                "in_il": in_il, "tags": chips, "status": st, "_sort": sort})
        orders = {}
        for col in ("name", "fppg", "proj", "l14", "gl", "keep"):
            idx = sorted(range(len(players)),
                         key=(lambda i: (players[i]["_sort"][col], players[i]["name"])) if col == "name"
                         else (lambda i, c=col: (-players[i]["_sort"][c], players[i]["name"])))
            orders[col] = idx
        for p in players:
            del p["_sort"]
        n_il = len([x for x in rosters.get(m, []) if x in il_here])
        rk = by_rank[m]
        roster_blocks[m] = {
            "manager": m, "team": MANAGER_TO_TEAM.get(m, m),
            "subtitle": f"{m} \u00b7 {rk['record']} \u00b7 #{rk['rank']}",
            "odds": rk["odds"], "odds_label": power["label"], "adds": f"{len(adds.get(m, []))} of {budget}",
            "starts": f"{starts_left[m]} starts",
            "size": roster_size_text(len(rosters.get(m, [])), n_il, active_cap, il_cap),
            "players": players, "orders": orders, "default_order": "proj",
            "note": ("FPPG and L14 are actual points per game (L14: the last 14 days). Proj is "
                     "Yahoo's projection. GL is games left this week. Keep is the chance he is "
                     f"one of your {kv3.line_for(kw, m)} keepers.")}

    # --- free agents
    fa = dl_free_agents(pl, rosters).sort_values("projectedFPPG", ascending=False, kind="stable")
    fa_rows = []
    for r in fa.head(cfg["free_agents_top_n"]).to_dict("records"):
        t = str(r["player_nba_team"])
        fa_rows.append({"name": r["player_name"], "pos": str(r.get("player_position(s)") or ""),
                        "nba": t, "proj": f"{float(r['projectedFPPG']):.1f}",
                        "gl": str(sum(1 for d in this_days if d in team_dates.get(t, ()))),
                        "next": str(sum(1 for d in next_days if d in team_dates.get(t, ())))})
    free = {"rows": fa_rows, "note": ("Chat claims and drops show here once the move ledger exists "
                                      "(step 2): claimed players drop off, dropped players show "
                                      "\"available from Mon\".")}

    # --- moves
    moves = build_moves(base, sched, today)

    # --- newsletter
    if archive_index is None:
        from . import hub_archive
        archive_index = hub_archive.load_index(base)
    newsletter = newsletter_block(archive_index, sched)

    from . import calibration_log as cal
    eng = cal.engine_version(base)
    payload = {
        "schema": SCHEMA,
        "generated_at": now.isoformat(timespec="seconds"),
        "generated_epoch_ms": int(now.timestamp() * 1000),
        "generated_text": _clock_text(now),
        "league_day": today.isoformat(),
        "week": week,
        "engine": {"commit": eng["commit"], "dirty": eng["dirty"],
                   "key": cal.engine_key({"engine_commit": eng["commit"], "engine_dirty": eng["dirty"]})},
        "header": {"title": "League Hub", "week_label": f"Week {week} \u00b7 {_mon_d(today)}",
                   "lock": lock_note(status, base, week),
                   "line_text": f"Line priced {_clock_text(line_at)}",
                   "engine_mismatch": None if check["ok"] else check["why"]},
        "matchups": build_matchups(line),
        "power": power,
        "rosters": roster_blocks,
        "grid": grid,
        "free_agents": free,
        "advice": None,
        "advice_empty": "Advice is being rebuilt; it returns here once it is ready.",
        "checklist": None,
        "moves": moves,
        "newsletter": newsletter,
        "sources": {"line": (Path("output") / f"live_lines_week{week}.json").as_posix(),
                    "title_odds": "output/title_odds_history.jsonl",
                    "actuals_through": yesterday.isoformat(),
                    "tags": f"the week {week} live line's tag record, as of {tag_state.get('as_of')}",
                    "il_slots": "data/IL_SLOTS.json"},
    }
    return payload


# =============================================================================
# moves and the newsletter
# =============================================================================

def build_moves(base: Path, schedule: dict, today: date) -> dict:
    """Adds from the synced waivers files (their "(week N claim/add)" marks
    kept) and trades from TRADES.json, dated within the last 7 days, newest
    first. The waivers files carry dates, not times; nothing else is
    inferred."""
    import re
    from . import transaction_rulings as tr
    from .keeper_history import trade_dates
    from .data_loader import CURRENT_SEASON
    start = today - timedelta(days=MOVES_DAYS - 1)
    items = []
    for f in sorted((base / "data").glob("waivers_week*.txt")):
        m = re.search(r"waivers_week(\d+)\.txt$", f.name)
        if not m:
            continue
        lines, _ = tr.waiver_lines(f, base, int(m.group(1)), schedule)
        for ln in lines:
            p = tr.parse_add_line(ln)
            if p is None:
                continue
            d = date.fromisoformat(p["date"])
            if not (start <= d <= today):
                continue
            note = (f"week {p['marked_claim_week']} claim" if p["marked_claim_week"] else
                    f"week {p['marked_add_week']} add" if p["marked_add_week"] else "")
            items.append({"_d": d, "day": d.strftime("%a"), "date": f"{d.month}/{d.day}",
                          "who": p["manager"], "what": f"added {p['player']}", "note": note,
                          "state": "Applied", "kind": "add"})
    tp = base / "config" / "TRADES.json"
    if tp.is_file():
        for t in json.loads(tp.read_text(encoding="utf-8")).get("trades", []):
            if t.get("season") not in (None, CURRENT_SEASON):
                continue
            first, _last = trade_dates(t.get("date"), CURRENT_SEASON)
            d = date.fromisoformat(first)
            if not (start <= d <= today):
                continue
            got: Dict[str, list] = {}
            for mv in t.get("players", []):
                got.setdefault(mv["to_manager"], []).append(mv["player_name"])
            if not got:
                raise HubInputError(f"config/TRADES.json: the {t.get('date')} trade lists no players")
            what = "; ".join(f"{mg} gets {', '.join(ps)}" for mg, ps in got.items())
            items.append({"_d": d, "day": d.strftime("%a"), "date": f"{d.month}/{d.day}",
                          "who": "Trade:", "what": what, "note": "", "state": "Applied",
                          "kind": "trade"})
    items.sort(key=lambda x: x["_d"], reverse=True)
    for x in items:
        del x["_d"]
    return {"items": items,
            "empty": "No moves in the last 7 days.",
            "note": ("Yahoo adds and trades from the synced files, by date (they record no time). "
                     "Chat claims, drops and injury entries join this feed with the move ledger "
                     "(step 2).")}


def newsletter_block(index: dict, schedule: dict) -> dict:
    issues = sorted(index.get("issues", []), key=lambda i: int(i["week"]), reverse=True)
    weeks = {int(w["week"]): w for w in schedule.get("weeks", [])}

    def label(i):
        w = weeks.get(int(i["week"]))
        if w is None:
            raise HubInputError(f"archived issue week {i['week']} is in no fantasy week")
        a = date.fromisoformat(str(w["start_date"])[:10])
        b = date.fromisoformat(str(w["end_date"])[:10])
        tail = f"{b.day}" if b.month == a.month else f"{b.strftime('%b')} {b.day}"
        return f"Week {i['week']} \u00b7 {a.strftime('%b')} {a.day}\u2013{tail}"

    out = [{"week": str(i["week"]), "label": label(i), "file": i["enc"], "size": i["enc_size_text"]}
           for i in issues]
    return {"current": out[0] if out else None, "archive": out[1:],
            "empty": "No issue archived yet.",
            "note": "Past issues, exactly as published. An issue loads when you tap it."}


def write(base_path, payload: dict) -> Path:
    from .data_loader import atomic_write_json
    p = Path(base_path) / PAYLOAD_RELPATH
    atomic_write_json(p, payload, indent=1)
    return p


def load(base_path=".") -> dict:
    p = Path(base_path) / PAYLOAD_RELPATH
    if not p.is_file():
        raise HubInputError(f"{PAYLOAD_RELPATH} is missing: run python scripts/build_hub_state.py")
    payload = json.loads(p.read_text(encoding="utf-8"))
    if payload.get("schema") != SCHEMA:
        raise HubInputError(f"{PAYLOAD_RELPATH} is schema {payload.get('schema')}, not {SCHEMA}")
    return payload
