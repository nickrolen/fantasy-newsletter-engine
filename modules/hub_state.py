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
  grid         games by players who will play (s.1a of the 1b handoff); the
               next-week tab as rosters will stand with the ledger's pending
               moves applied in the checklist's order (task 43a)
  free_agents  data_loader.free_agents, every one with his status (the latest
               tag record's free-agent tags and INJURY_OVERRIDES), two columns
               of games counting only the games he will play (the grid's
               Availability rule), ranked by projected points over those two
               (Yahoo's FPPG x those games), top N (task 39). Until this week's
               Monday window closes the columns are the rest of this week (GL)
               and next week; after it, the next two weeks, since a pickup now
               joins next Monday (rule 7; task 41: free_agent_columns)
  stash        the free agents tagged O or OFS (rule 2: only they can go
               straight into an IL slot), by projection, top N (task 42)
  advice       null: the slot only (advice v2)
  moves        every move of the season by budget week (modules/hub_moves,
               task 43): Yahoo's transactions placed by add_budget_week, the
               ledger's pending entries under their claim week
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
MOVES_DAYS = 7                     # the ledger view's feed window (move_ledger.hub_view)
WEEKDAY_LETTER = "MTWTFSS"
MINUS = "\u2212"
DASH = "\u2014"
FREE_AGENTS = "(free agents)"      # the Availability "roster" the listed free agents form


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
    for k in ("free_agents_top_n", "light_night_max", "stash_top_n"):
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


def _and_list(xs) -> str:
    """"4", "4 and 5", "4, 5 and 6"."""
    xs = list(xs)
    return xs[0] if len(xs) == 1 else ", ".join(xs[:-1]) + " and " + xs[-1]


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


def build_matchups(line: dict, mviews: dict = None) -> dict:
    """The cards; with mviews (hub_matchups.build_views), each card's three
    view ids and the last week's block (tasks 48a-48c)."""
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
    if mviews is not None:
        if len(mviews["cards_views"]) != len(cards):
            raise HubInputError("the matchup views do not match the line's matchups")
        for c, v in zip(cards, mviews["cards_views"]):
            c["views"] = v
    return {"clock": clock, "cards": cards, "buttons": {"sum": "Summary", "win": "Win %", "flow": "Game flow"},
            "last": (mviews or {}).get("last")}


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
    """(TitleOddsResult for build_power_rankings, the latest run's whole
    result, the history row before that run's or None).

    Step 1c: the latest title-odds run's result is output/title_odds_latest.json
    (modules/title_odds_run, written by the nightly run and the weekly build
    alike): its odds, expected records (build_power_rankings' second sort
    term) and finish distributions, from ONE run. It no longer comes from
    stats_report_weekN.json, so the Monday-ordering refusal of 1b is gone.

    The run must describe today's standings. The league's records (RECORDS)
    must equal either the records the run saw, or those plus every week the
    run had fully banked from the logs (a 12:01 AM Monday run, before the
    weekly build records the week): otherwise the build refuses."""
    from . import title_odds_history as toh
    from . import title_odds_run as tor_mod
    from .simulator_title_odds import TitleOddsResult
    try:
        latest = tor_mod.load_latest(base)
    except (FileNotFoundError, ValueError) as e:
        raise HubInputError(str(e)) from None
    if set(latest["title_odds"]) != set(managers):
        raise HubInputError(f"the latest title-odds run {latest['run_id']} has odds for "
                            f"{sorted(latest['title_odds'])}, not {sorted(managers)}")
    records = {m: data.get_manager_record(m) for m in managers}
    now = {m: str(records[m]) for m in managers}
    if now != latest["records"] and now != latest["records_after_banked"]:
        moved = ", ".join(f"{m} {latest['records'][m]} -> {now[m]}" for m in managers
                          if now[m] != latest["records"][m])
        raise HubInputError(
            f"the records moved since the title-odds run {latest['run_id']} ({moved}): its odds no "
            "longer describe the standings. Run python scripts\\nightly.py")
    rows = toh.read(base)
    ids = [r["run_id"] for r in rows]
    if latest["run_id"] not in ids:
        raise HubInputError(f"the latest title-odds run {latest['run_id']} has no row in "
                            f"{toh.HISTORY_FILE}: the two were not written by one run")
    prev_rows = rows[:ids.index(latest["run_id"])]
    prev = prev_rows[-1] if prev_rows else None
    tor = TitleOddsResult(
        num_simulations=int(latest["num_simulations"]), current_week=int(latest["pass_current_week"]),
        title_odds={m: float(latest["title_odds"][m]) for m in managers},
        expected_record={m: tuple(float(x) for x in latest["expected_record"][m]) for m in managers},
        finish_distribution={m: {int(k): float(v) for k, v in latest["finish_distribution"][m].items()}
                             for m in managers},
        magic_numbers={}, current_records=records, h2h_records={}, title_odds_delta={})
    return tor, latest, prev


def shown_record(latest: dict, manager: str) -> str:
    """The W-L the hub prints for `manager`: the latest title-odds run's
    records_after_banked (F5, 11-10). The Monday 12:01 AM run banks the week
    that just finished from the logs, so the hub's records move overnight,
    before the weekly build records the week in RECORDS (title_odds_inputs
    has already checked that RECORDS equals the run's records or these).
    Missing raises: never fall back to a stale record."""
    after = latest.get("records_after_banked") or {}
    if manager not in after:
        raise HubInputError(f"the latest title-odds run {latest.get('run_id')} has no "
                            f"records_after_banked for {manager}")
    return str(after[manager])


def build_power(base: Path, data, managers, keeper_watch: dict, week: int, adds: dict,
                budget: int, season_config: dict, cup_weeks: list) -> tuple:
    """(the power block, the build_power_rankings rows it was ordered by)."""
    from .report_builder import build_power_rankings
    from .data_loader import MANAGER_TO_TEAM
    tor, latest, prev = title_odds_inputs(base, data, managers)
    pf = season_points(data, latest)
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
                     "record": shown_record(latest, m), "odds": _pct(shown[m]), "delta": delta,
                     "delta_dir": ddir, "adds": f"{used} / {budget}",
                     "adds_over": used > budget,
                     "pf": _int(pf["points"][m]), "seed": f"seed {pf['seeds'][m]}"})
    as_of = datetime.fromisoformat(latest["as_of"])
    note = (f"Change is since the run before ({_clock_text(datetime.fromisoformat(prev['as_of']))})."
            if prev else "Change appears from the second run in the history.")
    block = {"kind": kind, "label": ODDS_LABEL[kind], "rows": rows, "run_id": latest["run_id"],
             "as_of": f"{ODDS_LABEL[kind]} as of {_clock_text(as_of)}",
             "note": note + f" Adds are this week's, out of {budget}, and count chat claims in the "
                           "week they were made. " + pf["note"],
             "chart_title": TITLE_CHART_LABEL,
             "chart": title_chart(base, data, season_config, cup_weeks)}
    return block, ranked


TITLE_CHART_LABEL = "Title odds"


def season_points(data, latest: dict) -> dict:
    """Task 48e: each manager's points over the COMPLETED weeks and his Cup
    seed now, through simulator_cup_odds.cup_seeding_points and get_cup_seeds
    -- never a second sum. They read RECORDS' weekly scores (the weeks the
    weekly build has recorded), the same completed weeks as the record
    column; between a Monday 12:01 run that banks the week from the logs and
    that week's weekly build, the record column already counts the week and
    PF does not yet: the note says so. A tie on points would go to
    get_cup_seeds' tiebreak (the standings so far, mid-season)."""
    from .simulator_cup_odds import cup_seeding_points, get_cup_seeds, cup_seeding_weeks
    points = cup_seeding_points(data)
    seeds = get_cup_seeds(data)
    first, last = cup_seeding_weeks()
    have = {}
    for m, entries in (data.records.get("weekly_scores") or {}).items():
        for e in entries if isinstance(entries, list) else []:
            w = e.get("week")
            if w is not None and first <= int(w) <= last:
                have.setdefault(int(w), set()).add(m)
    done = sorted(w for w, ms in have.items() if set(points) <= ms)
    n = done[-1] if done else 0
    if done != list(range(first, n + 1)):
        raise HubInputError(f"RECORDS' weekly scores cover weeks {done}, not weeks {first}-{n} in a row: "
                            "the season points cannot be shown")
    note = (f"PF: points over weeks {first}\u2013{n} completed, with each manager's Cup seed now; the Cup "
            f"seeds on weeks {first}\u2013{last}." if n else
            f"PF: no week completed yet; the Cup seeds on weeks {first}\u2013{last}.")
    if latest.get("records") != latest.get("records_after_banked"):
        note += (" The record column already counts the week banked overnight; its points join PF "
                 "after the weekly build records the week.")
    return {"points": points, "seeds": seeds, "weeks": n, "note": note}


def title_chart(base: Path, data, season_config: dict, cup_weeks: list) -> dict:
    """Task 48d (Nick, 11-10): one line chart of the REGULAR-SEASON title odds
    (title_odds) for the whole season, through hub_charts. Points: each
    league day's last title-odds history row; before the history began, the
    published stats reports, each on the Monday its data describe."""
    from . import title_odds_history as toh, hub_charts as hc
    from .data_loader import MANAGERS
    rows = toh.read(base)
    sched = data.schedule
    starts = {int(w["week"]): date.fromisoformat(str(w["start_date"])[:10]) for w in sched["weeks"]}
    first_hist = min((datetime.fromisoformat(r["as_of"]).date() for r in rows if r.get("title_odds")),
                     default=None)
    reports = []
    for p in sorted((base / "output").glob("stats_report_week*.json")):
        try:
            wk = int(p.stem.replace("stats_report_week", ""))
        except ValueError:
            continue
        day = starts.get(wk + 1)
        if first_hist is not None and day is not None and day >= first_hist:
            continue                                            # the history covers that day
        reports.append(json.loads(p.read_text(encoding="utf-8")))
    try:
        pts = hc.title_points(rows, reports, sched)
        ch = hc.title_odds_chart(pts, sched, list(MANAGERS),
                                 playoff_week=int(season_config["regular_season_weeks"]) + 1,
                                 cup_week=int(cup_weeks()[0]) if callable(cup_weeks) else int(cup_weeks[0]),
                                 label=TITLE_CHART_LABEL)
    except hc.ChartError as e:
        raise HubInputError(str(e)) from None
    return ch


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
        self.overrides = overrides or {"players": []}
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

    def for_free_agents(self, names, tags: dict) -> "Availability":
        """The same rule for the listed free agents (task 39): this instance's
        schedule, weeks, overrides, player info and today, with the free
        agents' own tags, as one "roster" (FREE_AGENTS) with no IL slots.
        Raises, as the constructor does, for a free agent with no NBA team."""
        return Availability({FREE_AGENTS: list(names)}, {}, tags, self.overrides, self.this_week,
                            self.info, self.team_dates, self.weeks, self.today)

    def with_rosters(self, rosters: dict, il_slots: dict, tags: dict) -> "Availability":
        """The same rule for other rosters (task 43a: next week's, with the
        ledger's pending moves applied): this instance's schedule, weeks,
        overrides, player info and today."""
        return Availability(rosters, il_slots, tags, self.overrides, self.this_week, self.info,
                            self.team_dates, self.weeks, self.today)

    def plays(self, name: str, d: date) -> bool:
        """His team plays on d and he is not out (OFS, an O tag's next 3
        games, an injury entry's dates). The one rule the grid and the free
        agents' GL, Next and points all count with. IL slots are the
        roster's, applied by players()."""
        return self.has_game(name, d) and not self.out(name, d)

    def playable(self, name: str, days) -> List[date]:
        """The days of `days` he will play (plays())."""
        return [d for d in days if self.plays(name, d)]

    def override_covers(self, name: str, days) -> Optional[dict]:
        """His INJURY_OVERRIDES entry when it keeps him out on any of `days`,
        else None (an entry whose dates have passed, or start later, is not
        his status now)."""
        e = self.over.get(name)
        if e is None:
            return None
        for d in days:
            w = self.week_of(d)
            if override_out_on(e, d, w, self.weeks[w][0]):
                return e
        return None

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
        return [n for n in self.rosters.get(manager, []) if n not in il and self.plays(n, d)]


# =============================================================================
# free agents: status, playable games, the two-week ranking (task 39)
# =============================================================================

PTS_LABEL = "Pts (3 wks)"
PTS_LABELS = {3: "Pts (3 wks)", 2: "Pts (2 wks)"}   # by the count of shown columns (48g)


def free_agent_tags(tag_row: dict, names) -> dict:
    """{free agent (PLAYERLIST's spelling): his tag} from a tag record (the
    latest, tag_records.latest). The record's free-agent tags first (every
    PLAYERLIST free agent since 1c-i); a player dropped since the fetch is
    found among its rostered tags. A record with no free-agent tags, a free
    agent in neither, or a tag with no rule RAISES: an untagged free agent
    is never read as healthy (the 10-29 preview's Zubac lesson)."""
    from .data_loader import PlayerIndex
    from . import absence
    fa_blob = (tag_row.get("tags") or {}).get("free_agents")
    if fa_blob is None:
        raise HubInputError(f"the latest tag record ({tag_row.get('run_id')}) carries no free-agent tags"
                            + (" (a run priced without tags)" if (tag_row.get("tags") or {})
                               .get("free_agents_assumed_healthy") else "")
                            + ": the free agents' statuses cannot be shown. Run python scripts\\nightly.py")
    fa_idx = PlayerIndex(dict(fa_blob))
    ro_idx = PlayerIndex(dict((tag_row.get("tags") or {}).get("rostered") or {}))
    out, missing, bad = {}, [], []
    for n in names:
        t = fa_idx.get(n)
        if t is None:
            t = ro_idx.get(n)
        if t is None:
            missing.append(n)
            continue
        try:
            absence.tag_kind(t)
        except absence.UnmodelledTag as e:
            bad.append(f"{n}: {e}")
            continue
        out[n] = str(t)
    if missing:
        raise HubInputError(f"the latest tag record ({tag_row.get('run_id')}) has no tag for free "
                            f"agent(s) {', '.join(missing)}: run python scripts\\nightly.py")
    if bad:
        raise HubInputError("; ".join(bad))
    return out


def override_back(entry: dict, weeks: dict) -> Optional[date]:
    """When an injury entry says he is back: its return_date, else the first
    day of its return_week, else None (report_builder.build_current_team_health's
    "override, back MM-DD" reads it the same way)."""
    from .absence import parse_return_date
    ret = parse_return_date(entry.get("return_date"), entry.get("player_name"))
    if ret is not None:
        return ret
    rw = entry.get("return_week")
    if rw is not None and int(rw) in weeks:
        return weeks[int(rw)][0]
    return None


def override_chip(entry: dict, av: Availability) -> dict:
    """An injury entry's chip: "O \u00b7 back MM-DD" (or "O \u00b7 no return date")."""
    back = override_back(entry, av.weeks)
    text = f"O \u00b7 back {_md(back)}" if back is not None else "O \u00b7 no return date"
    return {"text": text, "kind": "out"}


def free_agent_status(av: Availability, name: str, tag: str, window) -> dict:
    """A free agent's status chip(s) and source, from his tag and his injury
    entry, in the roster's precedence: OFS, then an injury entry keeping him
    out in the window (the rest of this week and next), then his tag.
      OFS                  "OFS \u00b7 season"
      injury entry         "O \u00b7 back MM-DD" (or "O \u00b7 no return date")
      O tag alone          "O \u00b7 up to 3 games" (absence.MAX_TAG_GAMES)
      Q, D                 "Q", "D"
      SUSP, NA (no effect) the tag, as a note
      healthy, P           no chip"""
    from . import absence
    norm = absence.normalised_tag(tag)
    if absence.season_out(tag):
        return {"source": "season_out", "chips": [{"text": "OFS \u00b7 season", "kind": "out"}]}
    e = av.override_covers(name, window)
    if e is not None:
        return {"source": "override", "chips": [override_chip(e, av)]}
    if norm == "O":
        return {"source": "tag", "chips": [{"text": f"O \u00b7 up to {absence.MAX_TAG_GAMES} games",
                                            "kind": "out"}]}
    if absence.tag_kind(tag) == "chain":
        return {"source": "tag", "chips": [{"text": norm, "kind": "q"}]}
    if norm in absence.NOTE_TAGS:
        return {"source": "note", "chips": [{"text": norm, "kind": "q"}]}
    return {"source": "healthy", "chips": []}


def rank_free_agents(fa_records, av: Availability, *col_days) -> List[dict]:
    """Every free agent, ranked by projected points over the columns' days
    (free_agent_columns: three since task 48g -- the rest of this week, next
    week and the week after, or the next three weeks; any count is accepted,
    one list of days per column, g1, g2, g3 ...) counting only the games he will play (Yahoo's projected FPPG x
    av.playable games), then higher Proj, then name. Injured players stay on
    the list (an O/OFS player can go straight into an open IL slot, rule 2),
    with what they will actually score. `av` is Availability.for_free_agents.
    Each row carries every value formatted: g1, g2, g3 are the columns'
    games; the "_" keys are the sort's and are dropped by the caller."""
    import math
    window = [d for days in col_days for d in days]
    rows = []
    for r in fa_records:
        n = r["player_name"]
        proj = float(r["projectedFPPG"])
        if math.isnan(proj):
            raise HubInputError(f"free agent {n} has no projectedFPPG in data/PLAYERLIST.xlsx")
        games = [len(av.playable(n, days)) for days in col_days]
        pts = proj * sum(games)
        st = free_agent_status(av, n, av.tags.get(n) or "HEALTHY", window)
        row = {"name": n, "pos": str(r.get("player_position(s)") or ""),
               "nba": av.info[n]["nba_team"], "proj": f"{proj:.1f}"}
        row.update({f"g{i + 1}": str(g) for i, g in enumerate(games)})
        row.update({"pts": f"{pts:.1f}", "tags": st["chips"], "status": st["source"], "_pts": pts,
                    "_proj": proj})
        rows.append(row)
    rows.sort(key=lambda x: (-x["_pts"], -x["_proj"], x["name"]))
    return rows


def free_agent_columns(now: datetime, week: int, wk_dates: dict, nba_schedule, games_on) -> dict:
    """Which games the free-agent table counts (task 41; Nick, 11-05, STATUS
    16q): decided by the BUILD'S CLOCK against this week's Monday window close
    (price_lock.window_close, rule 4), never by weekday name.

      before the close  "this": the rest of this week (GL), next week (Next)
                        and the week after ("Wk N+2"): a pickup in the
                        window joins this week.
      from the close    "ahead": the next three weeks ("Wk N+1", "Wk N+2",
                        "Wk N+3"): a pickup now is a group-chat claim and
                        joins the following Monday (rule 7).
    Three columns since task 48g (Nick, 11-10; two before). The Cup's
    stand-in games carry no marker here (Nick, 11-10): they count as games,
    as the schedule counts them.

    The 12:01 AM Monday build and Monday's pre-tip build show this week;
    Tuesday's 12:01 build switches. A 14-day fantasy week (weeks 7 and 17,
    rule 9) is one column. A week past the season's last fantasy week has no
    column (label DASH, no days): no add rule ends before the last week in
    LEAGUE_RULES or the config, so free agents are counted through it. A
    shown week whose days hold no NBA game RAISES: the schedule is missing,
    not empty. games_on(d) -> the NBA games on day d.

    {"mode", "cols": [{"label", "days", "week"} x 3], "join": the Monday a
    pickup made now joins (None when none can), "closes": the close}."""
    from . import price_lock
    if week not in wk_dates:
        raise HubInputError(f"week {week} is not in config/SCHEDULE.json")
    first = wk_dates[week][0]
    try:
        closes = price_lock.window_close(first, nba_schedule)
    except price_lock.NoGames as e:
        raise HubInputError(str(e)) from None
    today = now.date()

    def col(label, w, days=None):
        if w not in wk_dates:
            return {"label": DASH, "days": [], "week": None}
        if not any(games_on(d) for d in wk_dates[w]):
            raise HubInputError(f"fantasy week {w} ({wk_dates[w][0]} to {wk_dates[w][-1]}) has no NBA "
                                "game in the stored schedule: refetch it (python scripts/"
                                "fetch_nba_schedule.py) -- its free-agent column cannot be counted")
        return {"label": label, "days": list(wk_dates[w] if days is None else days), "week": w}

    if now < closes:
        cols = [col("GL", week, [d for d in wk_dates[week] if d >= today]), col("Next", week + 1),
                col(f"Wk {week + 2}", week + 2)]
        mode, join = "this", first
    else:
        cols = [col(f"Wk {week + 1}", week + 1), col(f"Wk {week + 2}", week + 2),
                col(f"Wk {week + 3}", week + 3)]
        mode = "ahead"
        join = wk_dates[week + 1][0] if (week + 1) in wk_dates else None
    return {"mode": mode, "cols": cols, "join": join, "closes": closes}


def stash_rows(fa_records, av: Availability, window, top_n: int) -> List[dict]:
    """The stash candidates (task 42): free agents TAGGED O or OFS -- only
    they can go straight into an IL slot (rule 2); a Q or healthy player with
    an injury entry cannot -- by Yahoo's projected FPPG, then name, top N.
    LONG ABSENCES ONLY (task 48f; Nick, 11-10): an O-tagged player is listed
    only when INJURY_OVERRIDES has a live entry for him -- one that keeps him
    out on some day of `window` (Availability.override_covers, the grid's own
    lookup); an O tag alone (at most 3 games) is not a stash. OFS stays as it
    was. So the chips here are only "O \u00b7 back 11-23" (the entry's) and
    "OFS \u00b7 season": the "O \u00b7 up to 3 games" status has no path into
    this table (it stays in free_agent_status for the free agents). `av` is
    the free agents' Availability (their tags). The eligible tags are the
    ledger's own (roster_moves.il_eligible_tags, the rule's one home in the
    config). A display, not advice."""
    from . import absence
    from .move_ledger import il_eligible_tags, tag_il_eligible
    eligible = il_eligible_tags()
    rows = []
    for r in fa_records:
        n = r["player_name"]
        tag = av.tags.get(n)
        if not tag_il_eligible(tag, eligible):           # the ledger's own rule (task 47)
            continue
        season = bool(absence.season_out(tag))
        if season:
            st = {"source": "season_out", "chips": [{"text": "OFS \u00b7 season", "kind": "out"}]}
        else:
            e = av.override_covers(n, window)
            if e is None:                                # an O tag alone: a short absence (48f)
                continue
            st = {"source": "override", "chips": [override_chip(e, av)]}
        proj = float(r["projectedFPPG"])
        rows.append({"name": n, "pos": str(r.get("player_position(s)") or ""), "nba": av.info[n]["nba_team"],
                     "proj": f"{proj:.1f}", "tags": st["chips"], "status": st["source"],
                     "season": season,
                     "season_note": "an IL slot all season: keeper value only" if season else "",
                     "_proj": proj})
    rows.sort(key=lambda x: (-x["_proj"], x["name"]))
    return [{k: v for k, v in x.items() if not k.startswith("_")} for x in rows[:int(top_n)]]


def open_il_text(managers, il_slots: dict, il_cap: int) -> str:
    """Teams with an open IL slot now (Yahoo's IL slots as synced)."""
    open_ = [(m, il_cap - len(il_slots.get(m, []))) for m in managers if len(il_slots.get(m, [])) < il_cap]
    if not open_:
        return "No team has an open IL slot now."
    return "Open IL slots now: " + ", ".join(f"{m} {k}" for m, k in open_) + "."


def build_grid_tab(av: Availability, managers, days: List[date], light_max: int,
                   nba_games_on: Dict[date, int], standins: dict = None) -> dict:
    """One tab: per manager, per day, the count who will play; overflow over
    10; Starts = the positional fit (schedule_strength.fill_daily_lineup_detail,
    the newsletter grid's own fit; never more than 10); Idle = count - starts.
    standins: {NBA team: {dates}} of the schedule's stand-ins for games the NBA
    has not scheduled (nba_schedule.standin_team_dates, task 46): a cell
    counting any is "est": "1" -- an estimated day, not a sure game."""
    from .schedule_strength import fill_daily_lineup_detail, MAX_STARTERS_PER_DAY
    standins = standins or {}
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
            est = any(d in standins.get(av.info[p]["nba_team"], ()) for p in ps)
            cells.append({"n": str(n), "kind": kind,
                          "overflow": str(max(0, n - MAX_STARTERS_PER_DAY)),
                          "starts": str(s), "est": "1" if est else ""})
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


def unscheduled_note(nba_schedule: dict, days) -> str:
    """Task 46: the one line ("2 games per team in Dec 4-11 not yet scheduled by
    the NBA; counted on estimated days") for a grid tab or the free-agent
    columns whose days touch the unscheduled window -- only while the loaded
    schedule has stand-ins (nba_schedule.info). "" otherwise."""
    from . import nba_schedule as ns
    block = ns.info(nba_schedule)
    if block is None:
        return ""
    a, b = date.fromisoformat(block["from"]), date.fromisoformat(block["to"])
    return ns.note_text(block) if any(a <= d <= b for d in days) else ""


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

    # --- the tags: the latest Yahoo fetch (output/tag_records.jsonl, step 1c),
    # facts that update every night whether or not the line was priced
    from .roster_plan import load_il_slots, check_against_rosters
    from . import tag_records
    rosters = {m: list(v) for m, v in data.get_current_rosters().items()}
    try:
        tag_row = tag_records.latest(base)
    except tag_records.TagRecordError as e:
        raise HubInputError(str(e)) from None
    tags = tag_records.hub_tags(tag_row, [n for v in rosters.values() for n in v])
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
    # the move ledger (step 2): facts update as soon as an entry lands
    from . import move_ledger as ml
    ledger_mode = ml.mode()
    lv = ml.hub_view(base, now, data.nba_schedule, feed_days=MOVES_DAYS)
    adds = {m: list(v) for m, v in tr.adds_by_budget_week(base, sched).get(week, {}).items()}
    if ledger_mode == "on":
        # the ledger's count: a claim is used the moment it is posted (rule 12)
        for m, v in (lv["pending_adds"].get(week) or {}).items():
            adds.setdefault(m, []).extend(v)
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
    il_cap = int(_LEAGUE_CONFIG["league_structure"]["il_slots"])
    # --- the matchup views (tasks 48a-48c): Summary, Win %, Game flow per card,
    # this week's and last week's
    if archive_index is None:
        from . import hub_archive
        archive_index = hub_archive.load_index(base)
    from . import hub_matchups, hub_charts, winprob_history
    from .league_clock import league_tz
    try:
        mviews = hub_matchups.build_views(base, data, week=week, line=line, av=av, now=now,
                                          archive_index=archive_index, tz=league_tz())
    except (hub_matchups.SummaryError, hub_charts.ChartError, winprob_history.WinProbHistoryError) as e:
        raise HubInputError(str(e)) from None
    nba_games_on = {}
    for d in this_days + next_days:
        nba_games_on[d] = sum(1 for dates in av.team_dates.values() if d in dates) // 2

    # --- the grid: this week as rosters stand; next week with the ledger's
    # pending moves applied at their windows, in the checklist's order (43a)
    next_av, pending_note = next_week_availability(base, now, data, av, week, tag_row, tags)
    # the NBA's unscheduled games (task 46): stand-ins on estimated days
    from . import nba_schedule as ns
    sdates = ns.standin_team_dates(data.nba_schedule)

    def schedule_note(days) -> str:
        return unscheduled_note(data.nba_schedule, days)

    this_tab = build_grid_tab(av, managers, this_days, cfg["light_night_max"], nba_games_on, sdates)
    next_tab = build_grid_tab(next_av, managers, next_days, cfg["light_night_max"], nba_games_on, sdates)
    grid = {"tabs": [
        dict(this_tab, key="this", label="Rest of this week", schedule_note=schedule_note(this_days),
             note=f"From {_mon_d(today)}. Counts players who will play: not in an IL slot, not "
                  "out under an O tag (at most his team's next 3 games), OFS, or an injury entry."),
        dict(next_tab, key="next", label="Next week", schedule_note=schedule_note(next_days),
             note=pending_note + " IL slots as they will stand, injury entries by date, OFS out. "
                  "An O tag costs at most his team's next 3 games from today, which can reach into "
                  "next week."),
    ], "legend": {"light": f"Light night ({cfg['light_night_max']} or fewer)",
                  "over": "More than 10: some sit",
                  "est": "Estimated: games the NBA has not scheduled yet"},
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
            # games he will play, the grid's and the free agents' rule (Nick, 11-04)
            gl = len(av.playable(n, this_days))
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
            chips += (lv["chips"].get(m) or {}).get(n, [])
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
            "pending": [{"text": j["text"]} for j in lv["joins"].get(m, [])],
            "note": ("FPPG and L14 are actual points per game (L14: the last 14 days). Proj is "
                     "Yahoo's projection. GL is games left this week. Keep is the chance he is "
                     f"one of your {kv3.line_for(kw, m)} keepers.")}

    # --- free agents (tasks 39, 41): status, playable games in two columns
    # chosen by the clock against this week's window close, ranked by points
    from . import absence
    fcols = free_agent_columns(now, week, {w: list(v) for w, v in wk_dates.items()}, data.nba_schedule,
                               lambda d: sum(1 for ds in av.team_dates.values() if d in ds) // 2)
    col_days = [c["days"] for c in fcols["cols"]]
    claimed_idx = PlayerIndex(dict(lv["claimed"]))
    fa_records = [r for r in dl_free_agents(pl, rosters).to_dict("records")
                  if claimed_idx.get(r["player_name"]) is None]          # rule 10: reserved
    dropped = {}                                                         # rule 11: free next week
    for n, info in lv["dropped"].items():
        row = proj.get(n)
        if row is None:
            raise HubInputError(f"{n}, dropped in the chat (ledger entry {info['entry']}), is not in "
                                "data/PLAYERLIST.xlsx")
        dropped[row["player_name"]] = info
    fa_names = [r["player_name"] for r in fa_records] + list(dropped)
    fa_av = av.for_free_agents(fa_names, free_agent_tags(tag_row, fa_names))
    if fcols["join"] is None:                       # the season's last window has closed
        ranked_fa = []
    else:
        ranked_fa = rank_free_agents(fa_records, fa_av, *col_days)
    if dropped and fcols["join"] is not None:
        # a chat drop is free from the next window: no games in this week's column
        this_mode = fcols["mode"] == "this"
        later = rank_free_agents([proj.get(n) for n in dropped], fa_av,
                                 *([[]] + col_days[1:] if this_mode else col_days))
        for r in later:
            info = dropped[r["name"]]
            if this_mode:
                r["g1"] = DASH
            r["tags"] = [{"text": f"available from {_ml_mon(info['window'])}", "kind": "new"}] + r["tags"]
        ranked_fa = sorted(ranked_fa + later, key=lambda x: (-x["_pts"], -x["_proj"], x["name"]))
    for i, c in enumerate(fcols["cols"]):          # a week past the season: no games, a dash
        if c["week"] is None:
            for r in ranked_fa:
                r[f"g{i + 1}"] = DASH
    fa_rows = []
    top = ranked_fa[:cfg["free_agents_top_n"]]
    # a player dropped in the chat is news: always listed, in rank order, even
    # below the top N (his points count from his window only)
    top += [r for r in ranked_fa[cfg["free_agents_top_n"]:] if r["name"] in dropped]
    for r in top:
        fa_rows.append({k: v for k, v in r.items() if not k.startswith("_")})
    shown = [c for c in fcols["cols"] if c["week"] is not None]
    long_weeks = [c["week"] for c in shown if len(c["days"]) > 7 and c["label"] != "GL"]
    if fcols["mode"] == "this":
        aside = "by projected points, rest of this week + the next two"
        cols_note = (f"This week's window is open until {_clock_text(fcols['closes'])}: a pickup "
                     "now plays from today, so GL counts the rest of this week, Next counts next "
                     "week, and the third column the week after.")
    elif fcols["join"] is None:
        aside = "the season's last window has closed"
        cols_note = "No pickup joins a roster again this season."
    else:
        aside = (f"by projected points, weeks {_and_list([str(c['week']) for c in shown])}: a pickup "
                 f"now joins {_ml_mon(fcols['join'].isoformat())}")
        cols_note = (f"This week's window closed {_clock_text(fcols['closes'])}: a pickup now is a "
                     f"group-chat claim and joins the next Monday (rule 7), so the columns are the "
                     f"next three weeks.")
        if len(shown) < 3:
            cols_note += f" Week {shown[-1]['week']} is the season's last."
    if long_weeks:
        cols_note += "".join(f" Week {w} is one fantasy week of {len(wk_dates[w])} days (rule 9): "
                             f"its games are one column." for w in long_weeks)
    pts_label = PTS_LABELS.get(len(shown)) or (f"Pts ({shown[0]['label']})" if shown else PTS_LABEL)
    free = {"rows": fa_rows, "aside": aside, "pts_label": pts_label, "mode": fcols["mode"],
            "schedule_note": schedule_note([d for c in shown for d in c["days"]]),
            "cols": [c["label"] for c in fcols["cols"]],
            "weeks": [c["week"] for c in fcols["cols"]],
            "empty": "No pickup joins a roster again this season.",
            "note": (f"{pts_label}: Yahoo's projected FPPG (Proj) times the games he will play in the "
                     f"columns. {cols_note} The columns count only games he will play: an injury "
                     f"entry's dates, OFS, and an O tag's next {absence.MAX_TAG_GAMES} games (no injury "
                     "entry) are left out. Injured players stay listed: an O or OFS player can go "
                     "straight into an open IL slot. A player claimed in the group chat leaves this "
                     "list at once; one dropped in the chat joins it, available from the next Monday.")}

    # --- stash candidates (task 42): free agents tagged O or OFS
    stash_recs = fa_records + [proj.get(n) for n in dropped]
    stash = {"rows": ([] if fcols["join"] is None else
                      stash_rows(stash_recs, fa_av, [d for ds in col_days for d in ds], cfg["stash_top_n"])),
             "aside": "OFS, or O with an injury entry, by projection",
             "open_il": open_il_text(managers, il_slots, il_cap),
             "empty": "No free agent is OFS, or tagged O with an injury entry.",
             "note": ("Long absences only: a player tagged O is listed when he has an injury entry "
                      "keeping him out (an O tag alone is at most 3 games); OFS players are listed as "
                      "before. Only a player tagged O or OFS can go straight into an IL slot (rule 2); a "
                      "Q or healthy player cannot, whatever his injury entry says. OFS is out for the "
                      "season: an IL slot all year, for his keeper value only. A display, not advice: "
                      "IL slots change only in a Monday window.")}

    # --- moves: every move of the season, by budget week (task 43)
    from . import hub_moves
    try:
        moves = hub_moves.build(base, sched, week, managers=managers, budget=budget,
                                live_claims=lv["live_claims"])
    except hub_moves.MovesError as e:
        raise HubInputError(str(e)) from None

    # --- newsletter
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
        "matchups": build_matchups(line, mviews),
        "matchup_views": mviews["views"],
        "power": power,
        "rosters": roster_blocks,
        "grid": grid,
        "free_agents": free,
        "stash": stash,
        "advice": None,
        "advice_empty": "Advice is being rebuilt; it returns here once it is ready.",
        "moves": moves,
        "newsletter": newsletter,
        "sources": {"line": (Path("output") / f"live_lines_week{week}.json").as_posix(),
                    "title_odds": f"the title-odds run {power['run_id']} (modules/title_odds_run)",
                    "actuals_through": yesterday.isoformat(),
                    "tags": f"Yahoo's tags fetched {tag_row['taken_at']} ({tag_row['mode']} run "
                            f"{tag_row['run_id']})",
                    "il_slots": "data/IL_SLOTS.json",
                    "ledger": f"config/MOVE_LEDGER.json ({ledger_mode} mode)"},
    }
    return payload


# =============================================================================
# moves and the newsletter
# =============================================================================

def _ml_mon(day: str) -> str:
    d = date.fromisoformat(str(day)[:10])
    return f"{d:%a} {d:%m-%d}"


def next_week_availability(base: Path, now: datetime, data, av: Availability, week: int,
                           tag_row: dict, tags: dict) -> tuple:
    """(Availability for next week's grid tab, its note's opening). Next
    week's rosters as they will stand once the ledger's live entries (pending,
    window open) up to next week's window are applied, window by window in the
    checklist's order (move_ledger.rosters_after: a claimed player joins his
    new team, a dropped one leaves, IL placements and activations apply).
    A fact in both ledger modes, not a price. A joining player's tag is his
    free-agent tag, kept by the rostered rule (tag_records.kept_for_hub)."""
    from . import move_ledger as ml, tag_records
    try:
        world = ml.World.from_base(base, now, data=data)
        after = ml.rosters_after(world, ml.read_rows(base), ml.read_states(base), week + 1)
    except ml.LedgerError as e:
        raise HubInputError(f"next week's grid with the pending moves: {e}") from None
    if not after["lines"]:
        note = "As rosters stand today: no pending group-chat moves."
        if after["notes"]:
            note += " Pending parts that cannot apply: " + "; ".join(after["notes"]) + "."
        return av, note
    now_names = {n for v in av.rosters.values() for n in v}
    joiners = sorted({n for v in after["rosters"].values() for n in v} - now_names)
    tag_now = dict(tags)
    if joiners:
        tag_now.update({n: t for n, t in free_agent_tags(tag_row, joiners).items()
                        if tag_records.kept_for_hub(t)})
    note = ("As rosters stand with pending moves: the group-chat moves in the ledger applied at their "
            "Monday windows, in the checklist's order (" + "; ".join(after["lines"]) + ").")
    if after["notes"]:
        note += " Pending parts that cannot apply: " + "; ".join(after["notes"]) + "."
    return av.with_rosters(after["rosters"], after["il"], tag_now), note


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
