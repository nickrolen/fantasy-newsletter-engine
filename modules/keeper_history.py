"""Every keeper decision this league has made, as a dataset (keepability v3, step A).

KEEPABILITY_V3_DESIGN.md, HANDOFF_KEEPABILITY_A_MEASURE_2026-10-29. Builds data;
fits nothing and changes no consumer -- keepability v2.2 stays live until step C.

A DECISION is named by the season the keepers were kept FOR (2021-22 .. 2026-27)
and made from the PREVIOUS season's rosters. Each manager keeps his K (6 in every
decision so far) from his roster on that season's last day.

Each decision is looked at from three AS-OF points in the previous season:
  week2  the last logged day of fantasy week 2 (where 2026-27 is today)
  mid    the last logged day of week ceil(R/2), R = that season's last
         regular-season week (season_structure.regular_through)
  end    the season's last logged day -- the roster the decision was made from
At week2 and mid a manager's candidates are his roster on THAT day, so some
eventual keepers are missing; the count present is the CEILING.

POINT-IN-TIME: every feature is computed from playerlog rows dated on or
before the as-of day, and trades dated on or before it. Draft results and the
season's keeper flags are known from the draft, before the season. Ages are
basketball-reference's for that season (age on February 1 of it) -- a fixed
fact about the player, not an outcome.

ACQUIRED, for the stint with his manager that runs up to the as-of day:
  draft   drafted or kept by this manager this season, on his roster since day 1
  trade   the stint began within TRADE_WINDOW_DAYS of a trade sending him to
          this manager (all_trades.json)
  pickup  anything else: he arrived mid-season with no trade record -- an
          add from free agency, or a re-add after a drop

Names: the playerlog's spelling is canonical (accents stripped). Drafts carry
Yahoo ids; a draft pick resolves by id when the playerlog has it, else by name
through PlayerIndex (accents, suffixes, initials). Trades carry names only.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field, asdict
from datetime import date, timedelta
from pathlib import Path
from typing import Callable, Optional

from .data_loader import PlayerIndex, SEASON_STRUCTURE

ROOT = Path(__file__).resolve().parents[1]
DECISIONS = ("2021-22", "2022-23", "2023-24", "2024-25", "2025-26", "2026-27")
POINTS = ("week2", "mid", "end")
PLAYERLOG = "data/historical/HISTORICAL_PLAYERLOG.json"
DRAFTS = "data/historical/all_drafts.json"
DRAFTS_CURRENT = "config/DRAFT_PICKS_CURRENT.json"
TRADES = "data/historical/all_trades.json"
AGES_FILE = "data/historical/BBREF_AGES.json"
BBREF_URL = "https://www.basketball-reference.com/leagues/NBA_{year}_per_game.html"
TRADE_WINDOW_DAYS = 3        # a trade shows on the receiving roster within this many days
                             # (measured 10-29: every placeable move shows the same day)


# The shrinkage curve's constants, MEASURED 10-23/10-28 against these two
# priors (REVIEW_PROJECTION_VS_ACTUALS_RESULT_2026-10-23,
# SHRINKAGE_CURVE_RESULT_2026-10-28) -- reused here, not refit:
#   prior = last season's FPPG (10+ games then)   k0 = 13  (401 player-seasons)
#   prior = the league mean of rostered players  k0 = 4.7 (589 player-seasons)
K0_PRIOR_SEASON = 13.0
K0_LEAGUE_MEAN = 4.7
PRIOR_MIN_GAMES = 10
PREV_SEASONS = 3            # how far back prev_lines reach (step B2)


def shrunk_level(fppg, games: int, prev_fppg, prev_games, league_mean: float) -> tuple:
    """(level, prior, k0, prior_kind): FPPG so far shrunk toward a prior,
    w = k / (k + k0), k = games so far (bench games count). At zero games it
    is the prior."""
    if prev_fppg is not None and (prev_games or 0) >= PRIOR_MIN_GAMES:
        prior, k0, kind = float(prev_fppg), K0_PRIOR_SEASON, "last season"
    else:
        prior, k0, kind = float(league_mean), K0_LEAGUE_MEAN, "league mean"
    k = int(games or 0)
    w = k / (k + k0)
    return (w * float(fppg) + (1 - w) * prior) if k else prior, prior, k0, kind


class KeeperNotOnRoster(ValueError):
    """A keeper not found on his manager's end-of-season roster: a name or id
    matching problem (every keeper since 2021-22 was on it, measured 10-29)."""


def prev_season(season: str) -> str:
    y = int(season[:4]) - 1
    return f"{y}-{(y + 1) % 100:02d}"


def season_end_year(season: str) -> int:
    return int(season[:4]) + 1


def appeared(row: dict) -> bool:
    """He played: his team had a game and he was not the 0.0 'injured' row.
    is_injured is defined as had a game and scored 0.0
    (rollup_season_to_history), so this is the same set of games as
    projections.appearances WITHOUT its started==True condition -- bench games
    count. A missing flag raises; it is never read as 'played'."""
    try:
        return bool(row["had_game"]) and not bool(row["is_injured"])
    except KeyError as e:
        raise ValueError(f"playerlog row without {e}: {row.get('player_name')} {row.get('date')}")


# ---------------------------------------------------------------------------
# inputs
# ---------------------------------------------------------------------------

@dataclass
class Inputs:
    log: dict            # season -> rows (playerlog), sorted by date
    picks: dict          # season -> draft picks
    trades: list

    @classmethod
    def load(cls, root=ROOT) -> "Inputs":
        root = Path(root)
        rows = json.loads((root / PLAYERLOG).read_text(encoding="utf-8"))
        log: dict = {}
        for r in rows:
            log.setdefault(r["season_key"], []).append(r)
        for s in log:
            log[s].sort(key=lambda r: (r["date"], r["manager"], r["player_name"]))
        picks: dict = {}
        for p in json.loads((root / DRAFTS).read_text(encoding="utf-8")):
            picks.setdefault(p["season"], []).append(p)
        cur = json.loads((root / DRAFTS_CURRENT).read_text(encoding="utf-8"))
        for p in cur["picks"]:
            picks.setdefault(cur["season"], []).append({**p, "season": cur["season"]})
        trades = json.loads((root / TRADES).read_text(encoding="utf-8"))
        return cls(log=log, picks=picks, trades=trades)


class Names:
    """Resolve a draft or trade name to the playerlog's spelling for a season:
    by Yahoo id when both sides carry it, else through PlayerIndex. None when
    the player never appears in that season's log."""

    def __init__(self, rows: list):
        self.by_id: dict = {}
        self.idx = PlayerIndex()
        for r in rows:
            if r.get("player_id") is not None:
                self.by_id[int(r["player_id"])] = r["player_name"]
            self.idx[r["player_name"]] = r["player_name"]

    def canon(self, name: str, player_id=None) -> Optional[str]:
        if player_id not in (None, ""):
            hit = self.by_id.get(int(player_id))
            if hit is not None:
                return hit
        return self.idx.canonical(name)


_MONTHS = {m: i for i, m in enumerate(
    ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"), 1)}


def trade_dates(raw: str, season: str) -> tuple:
    """(first, last) ISO day of a trade's `date`. Most are one ISO day; one
    2025-26 trade (Sengun <-> Barnes) carries Yahoo's week range "Feb 2 -
    Feb 8". A range is placed in the season's calendar (Oct-Dec in the first
    year, the rest in the second). Anything else RAISES -- a trade that cannot
    be placed in time cannot be kept out of an earlier as-of point."""
    raw = str(raw or "").strip()
    try:
        return (date.fromisoformat(raw).isoformat(),) * 2
    except ValueError:
        pass
    parts = [x.strip().split() for x in raw.split("-")]
    if len(parts) == 2 and all(len(x) == 2 and x[0][:3] in _MONTHS and x[1].isdigit() for x in parts):
        y0 = int(season[:4])
        out = []
        for mon, day in parts:
            m = _MONTHS[mon[:3]]
            out.append(date(y0 if m >= 8 else y0 + 1, m, int(day)).isoformat())
        return tuple(out)
    raise ValueError(f"{season} trade date {raw!r} is neither an ISO day nor a 'Mon D - Mon D' range")


# ---------------------------------------------------------------------------
# as-of points and rosters
# ---------------------------------------------------------------------------

def regular_through(season: str) -> int:
    entry = SEASON_STRUCTURE.get(season)
    if not isinstance(entry, dict) or not entry.get("regular_through"):
        raise KeyError(f"season_structure.{season}.regular_through is not stated; "
                       "the mid-season point cannot be placed")
    return int(entry["regular_through"])


def as_of_point(rows: list, season: str, point: str) -> tuple:
    """(week, date) of one as-of point in one season's log."""
    last_by_week: dict = {}
    for r in rows:
        if r["date"] > last_by_week.get(r["week"], ""):
            last_by_week[r["week"]] = r["date"]
    if point == "end":
        return max(last_by_week), max(last_by_week.values())
    w = {"week2": 2, "mid": None}[point] or math.ceil(regular_through(season) / 2)
    if w not in last_by_week:
        raise KeyError(f"{season}: no playerlog rows in week {w}")
    return w, last_by_week[w]


def as_of_points(rows: list, season: str) -> dict:
    """{point: (week, date)} for one season's log."""
    return {p: as_of_point(rows, season, p) for p in POINTS}


def roster_on(rows: list, day: str) -> dict:
    out: dict = {}
    for r in rows:
        if r["date"] == day:
            out.setdefault(r["manager"], set()).add(r["player_name"])
    return {m: sorted(v) for m, v in out.items()}


def keepers_of(inputs: Inputs, decision: str) -> dict:
    """{manager: [names in the previous season's log spelling]} kept FOR
    `decision`. A keeper absent from the previous season's log keeps his draft
    spelling here and fails the roster check (KeeperNotOnRoster)."""
    names = Names(inputs.log[prev_season(decision)])
    out: dict = {}
    for p in inputs.picks.get(decision, []):
        if p.get("is_keeper"):
            out.setdefault(p["manager"], []).append(
                names.canon(p["player_name"], p.get("player_key")) or p["player_name"])
    if not out:
        raise KeyError(f"no keeper picks for {decision}")
    return {m: sorted(v) for m, v in out.items()}


def check_keepers_on_rosters(keepers: dict, end_rosters: dict, decision: str) -> None:
    misses = [(m, k) for m, ks in keepers.items() for k in ks
              if k not in set(end_rosters.get(m, []))]
    if misses:
        raise KeeperNotOnRoster(f"{decision}: keepers not on their manager's end-of-season "
                                f"roster (a name-matching problem): {misses}")


# ---------------------------------------------------------------------------
# ages: basketball-reference, cached
# ---------------------------------------------------------------------------

def load_ages(seasons, root=ROOT, fetch: Optional[Callable] = None, today: str = None) -> dict:
    """{season: PlayerIndex(name -> age)} from basketball-reference's per-game
    page for each season (age on February 1 of that season), cached in
    AGES_FILE with the source URL and fetch date. A season not in the cache is
    fetched; a failed fetch RAISES (fetch_playerlist.AgeFetchError) and nothing
    is written for it."""
    from scripts.fetch_playerlist import ages_from_basketball_reference
    path = Path(root) / AGES_FILE
    cache = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {
        "_source": BBREF_URL, "_convention": "basketball-reference 'Age' column: age on "
        "February 1 of the season; the first row wins for a traded player",
        "seasons": {}}
    changed = False
    for s in seasons:
        if s not in cache["seasons"]:
            year = season_end_year(s)
            ages = ages_from_basketball_reference(year, add=0, fetch=fetch)
            cache["seasons"][s] = {"url": BBREF_URL.format(year=year),
                                   "fetched": today or date.today().isoformat(),
                                   "ages": dict(sorted(ages.items()))}
            changed = True
    if changed:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(cache, indent=1, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)
    return {s: PlayerIndex(cache["seasons"][s]["ages"]) for s in seasons}


def age_seasons(decisions=DECISIONS) -> list:
    """Every season an age may come from: each candidate season and both
    neighbours."""
    out = set()
    for d in decisions:
        s = prev_season(d)
        out |= {prev_season(s), s, next_season(s)}
    return sorted(out)


def next_season(season: str) -> str:
    y = int(season[:4]) + 1
    return f"{y}-{(y + 1) % 100:02d}"


class AgeNotFound(KeyError):
    """No age for a player in his season or either neighbouring season."""


def age_for(ages: dict, season: str, name: str) -> tuple:
    """(age, age_source) for `name` in `season`.

    basketball-reference's per-game page has a row only for a player who
    played: Kawhi Leonard and Zion Williamson (2021-22) and Tyrese
    Haliburton (2025-26) missed those seasons and have none. Nick, 10-29:
    take the neighbouring season's age, plus or minus one year -- the
    FOLLOWING season first (age - 1), else the preceding one (age + 1).
    Neither: AgeNotFound. ages: {season: PlayerIndex} (load_ages), holding
    the neighbours too."""
    for s, shift, label in ((season, 0, ""), (next_season(season), -1, " - 1"),
                            (prev_season(season), +1, " + 1")):
        idx = ages.get(s)
        if idx is not None and idx.get(name) is not None:
            return int(idx.get(name)) + shift, f"bbref {s}{label}"
    raise AgeNotFound(f"{name}: no basketball-reference age for {season} or either "
                      "neighbouring season")


# ---------------------------------------------------------------------------
# features
# ---------------------------------------------------------------------------

@dataclass
class Candidate:
    decision: str
    season: str
    point: str
    as_of: str
    manager: str
    player: str
    kept_next: bool                  # the label: kept by THIS manager for `decision`
    kept: bool                       # kept this season (by anyone: a traded keeper carries it)
    draft_round: Optional[int]       # non-keeper round this season (by anyone); None if kept or undrafted
    undrafted: bool                  # neither kept nor drafted this season
    acquired: str                    # how this stint with his manager began: draft | trade | pickup
    stint_start: str
    games: int                       # appearances so far this season (any roster in the league)
    fppg: Optional[float]            # None with no appearances
    fppg_rank: int                   # 1 = best on this roster at the as-of day (no games: last, by name)
    team_games: int                  # his NBA team's games while he was rostered in the league
    availability: Optional[float]    # games / team_games
    days_rostered: int               # days on a league roster this season, through as_of
    first_day: str                   # first day on a league roster this season
    prev_games: Optional[int]        # last season, while rostered in the league; None: not rostered
    prev_fppg: Optional[float]
    age: Optional[int]               # None: not found -- reported, never guessed
    age_source: Optional[str] = None # "bbref <season>", or a neighbour's "- 1" / "+ 1"
    draft_pick: Optional[int] = None # his non-keeper pick number this season (carried on a trade)
    draft_rank: Optional[int] = None # overall rank across eras: players kept league-wide + pick
    level: Optional[float] = None    # shrunk_level(): FPPG so far toward the prior
    level_prior: Optional[float] = None
    level_prior_kind: Optional[str] = None
    prev_lines: list = field(default_factory=list)  # [(season, games, fppg)] for up to PREV_SEASONS
                                                    # seasons before this one, newest first; only
                                                    # seasons with appearances (rostered in this league)
    league_mean: Optional[float] = None             # rostered players' FPPG this season, so far
    team_flips: int = 0              # times his rows' nba_team changes; > 2 means the log
                                     # alternates teams after an NBA trade, and had_game /
                                     # is_injured (so team_games, availability) are unreliable


@dataclass
class Snapshot:
    decision: str
    point: str
    week: int
    as_of: str
    rosters: dict
    keepers: dict
    ceiling: int                     # keepers on their manager's roster at as_of
    absent: list                     # (manager, keeper) not on his roster yet
    candidates: list = field(default_factory=list)

    def by_manager(self) -> dict:
        out: dict = {}
        for c in self.candidates:
            out.setdefault(c.manager, []).append(c)
        return out


def _stint_start(days_with: set, season_days: list, as_of: str) -> str:
    """First day of the unbroken run of days, ending at as_of, on which this
    manager had him. season_days: every logged day of the season, sorted."""
    upto = [d for d in season_days if d <= as_of]
    start = as_of
    for d in reversed(upto):
        if d in days_with:
            start = d
        else:
            break
    return start


def _season_line(rows: list) -> tuple:
    """(games, fppg) from one player's rows."""
    pts = [r["fantasy_points"] for r in rows if appeared(r)]
    return len(pts), (sum(pts) / len(pts) if pts else None)


def previous_lines(inputs: Inputs, season: str, n_seasons: int = PREV_SEASONS):
    """A function name -> [(season, games, fppg)] for the n_seasons seasons
    before `season`, newest first, only those in which he appeared (the log
    covers a player only while he is rostered in this league). Whole seasons:
    every one of them ends before `season` starts."""
    seasons, s = [], season
    for _ in range(n_seasons):
        s = prev_season(s)
        seasons.append(s)
    per = []
    for s in seasons:
        rows: dict = {}
        for r in inputs.log.get(s, []):
            rows.setdefault(r["player_name"], []).append(r)
        per.append((s, rows, PlayerIndex({k: k for k in rows})))

    def lines(name: str) -> list:
        out = []
        for s, rows, idx in per:
            hit = idx.canonical(name)
            if hit is None:
                continue
            g, f = _season_line(rows[hit])
            if g:
                out.append((s, g, round(f, 4)))
        return out
    return lines


def snapshot(inputs: Inputs, decision: str, point: str, ages: Optional[dict] = None,
             check: bool = True, labels: bool = True, as_of: Optional[str] = None) -> Snapshot:
    """The decision as seen from one as-of point. Everything below reads
    `rows` -- the season's playerlog cut at as_of -- and trades dated on or
    before it. ages: {season: PlayerIndex} (load_ages) for the season and its
    neighbours; None leaves every age missing."""
    season = prev_season(decision)
    all_rows = inputs.log[season]
    if as_of is None:
        week, as_of = as_of_point(all_rows, season, point)
    else:                                   # live: the last day logged so far
        week = max(r["week"] for r in all_rows if r["date"] <= as_of)
    rows = [r for r in all_rows if r["date"] <= as_of]          # point-in-time, here and only here
    season_days = sorted({r["date"] for r in rows})
    keepers = keepers_of(inputs, decision) if labels else {}
    if check and labels:
        end_day = as_of_point(all_rows, season, "end")[1]
        check_keepers_on_rosters(keepers, roster_on(all_rows, end_day), decision)
    rosters = roster_on(rows, as_of)
    absent = [(m, k) for m, ks in keepers.items() for k in ks if k not in set(rosters.get(m, []))]
    ceiling = sum(len(ks) for ks in keepers.values()) - len(absent)

    names = Names(all_rows)
    kept_now, round_now, pick_now, drafted_by = set(), {}, {}, {}
    season_picks = inputs.picks.get(season, [])
    kept_league = sum(1 for p in season_picks if p.get("is_keeper"))
    for p in season_picks:
        n = names.canon(p["player_name"], p.get("player_key"))
        if n is None:
            continue
        drafted_by[n] = p["manager"]
        if p.get("is_keeper"):
            kept_now.add(n)
        else:
            round_now[n] = int(p["round"])
            pick_now[n] = int(p["pick_number"])
    played = [r["fantasy_points"] for r in rows if appeared(r)]
    league_mean = sum(played) / len(played) if played else 0.0     # rostered players, so far
    trades_in = {}                                     # (player, to_manager) -> [(first, last)]
    for t in inputs.trades:
        if t.get("season") != season:
            continue
        first, last = trade_dates(t.get("date"), season)
        if first > as_of:                              # point-in-time
            continue
        for mv in t.get("players", []):
            n = names.canon(mv["player_name"])
            if n is not None:
                trades_in.setdefault((n, mv["to_manager"]), []).append((first, last))

    by_player: dict = {}
    days_with: dict = {}
    for r in rows:
        by_player.setdefault(r["player_name"], []).append(r)
        days_with.setdefault((r["player_name"], r["manager"]), set()).add(r["date"])
    prev_by_player: dict = {}
    for r in inputs.log.get(prev_season(season), []):
        prev_by_player.setdefault(r["player_name"], []).append(r)
    prev_names = PlayerIndex({n: n for n in prev_by_player})
    back = previous_lines(inputs, season)

    snap = Snapshot(decision, point, week, as_of, rosters, keepers, ceiling, absent)
    for m, roster in sorted(rosters.items()):
        mine = []
        for n in roster:
            prow = by_player[n]
            games, fppg = _season_line(prow)
            team_games = sum(1 for r in prow if r["had_game"])
            start = _stint_start(days_with[(n, m)], season_days, as_of)
            if drafted_by.get(n) == m and start == season_days[0]:
                acquired = "draft"
            elif any(date.fromisoformat(a) - timedelta(days=TRADE_WINDOW_DAYS)
                     <= date.fromisoformat(start)
                     <= date.fromisoformat(b) + timedelta(days=TRADE_WINDOW_DAYS)
                     for a, b in trades_in.get((n, m), [])):
                acquired = "trade"
            else:
                acquired = "pickup"
            age, age_source = age_for(ages, season, n) if ages is not None else (None, None)
            teams = [r["nba_team"] for r in prow]
            flips = sum(1 for a, b in zip(teams, teams[1:]) if a != b)
            pn = prev_names.canonical(n)
            pg, pf = _season_line(prev_by_player[pn]) if pn else (None, None)
            level, prior, _k0, prior_kind = shrunk_level(fppg, games, pf, pg, league_mean)
            mine.append(Candidate(
                decision=decision, season=season, point=point, as_of=as_of, manager=m, player=n,
                kept_next=n in set(keepers.get(m, [])), kept=n in kept_now,
                draft_round=round_now.get(n), undrafted=n not in kept_now and n not in round_now,
                acquired=acquired, stint_start=start, games=games,
                fppg=None if fppg is None else round(fppg, 3), fppg_rank=0,
                team_games=team_games,
                availability=None if not team_games else round(games / team_games, 4),
                days_rostered=len({r["date"] for r in prow}), first_day=min(r["date"] for r in prow),
                prev_games=pg, prev_fppg=None if pf is None else round(pf, 3),
                age=age, age_source=age_source, team_flips=flips,
                draft_pick=pick_now.get(n),
                draft_rank=None if n not in pick_now else kept_league + pick_now[n],
                level=round(level, 3), level_prior=round(prior, 3), level_prior_kind=prior_kind,
                prev_lines=back(n), league_mean=round(league_mean, 4)))
        order = sorted(mine, key=lambda c: (c.fppg is None, -(c.fppg or 0.0), c.player))
        for i, c in enumerate(order, 1):
            c.fppg_rank = i
        snap.candidates.extend(sorted(mine, key=lambda c: c.player))
    return snap


def live_inputs(root=ROOT, history: Optional[Inputs] = None) -> tuple:
    """(Inputs, season) with THIS season's log built from LINEUPS.xlsx exactly
    as rollup_season_to_history will file it at season's end (bench games
    included), its draft from DRAFT_PICKS_CURRENT.json and its trades from
    config/TRADES.json -- so live features use the historical definitions."""
    import sys as _sys
    _sys.path.insert(0, str(Path(root) / "scripts"))
    import rollup_season_to_history as R
    from .data_loader import CURRENT_SEASON, _LEAGUE_CONFIG
    history = history or Inputs.load(root)
    flat = [r for rows in history.log.values() for r in rows]
    rows, _report = R.build_rows(CURRENT_SEASON, flat)
    rows.sort(key=lambda r: (r["date"], r["manager"], r["player_name"]))
    trades_cfg = json.loads((Path(root) / "config" / "TRADES.json").read_text(encoding="utf-8")) \
        if (Path(root) / "config" / "TRADES.json").is_file() else {}
    trades = list(history.trades) + list(R.build_trades(CURRENT_SEASON, trades_cfg, _LEAGUE_CONFIG) or [])
    return Inputs(log={**history.log, CURRENT_SEASON: rows}, picks=history.picks, trades=trades), \
        CURRENT_SEASON


def live_snapshot(inputs: Inputs, season: str, rosters: dict, ages: Optional[dict] = None) -> Snapshot:
    """This season's candidates on TODAY's rosters (config/ROSTERS.json via
    data.get_current_rosters), with every feature read from the live log as
    far as it goes. A player on today's roster who is not on the log's last
    day (a Monday-window add the log has not reached) keeps whatever he has
    logged with anyone this season; with nothing logged he gets no games, his
    prior as his level and no availability. No labels: the decision is next
    offseason's."""
    rows = inputs.log[season]
    last = max(r["date"] for r in rows)
    base = snapshot(inputs, next_season(season), "end", ages, labels=False, as_of=last)
    by_name = {c.player: c for c in base.candidates}
    names = Names(rows)
    hist_names = PlayerIndex({n: n for n in by_name})
    prev_rows: dict = {}
    for r in inputs.log.get(prev_season(season), []):
        prev_rows.setdefault(r["player_name"], []).append(r)
    prev_idx = PlayerIndex({n: n for n in prev_rows})
    played = [r["fantasy_points"] for r in rows if appeared(r)]
    league_mean = sum(played) / len(played) if played else 0.0
    kept_league = sum(1 for p in inputs.picks.get(season, []) if p.get("is_keeper"))
    pick_of = {}
    for p in inputs.picks.get(season, []):
        n = names.canon(p["player_name"], p.get("player_key")) or p["player_name"]
        pick_of[n] = p
    pick_idx = PlayerIndex({n: n for n in pick_of})
    back = previous_lines(inputs, season)
    trades_to = {(mv["player_name"], mv["to_manager"]) for t in inputs.trades
                 if t.get("season") == season for mv in t.get("players", [])}
    out = Snapshot(next_season(season), "live", base.week, last,
                   {m: list(v) for m, v in rosters.items()}, {}, 0, [])
    for m, roster in sorted(rosters.items()):
        for raw in roster:
            hit = hist_names.canonical(raw)
            if hit is not None:
                c = by_name[hit]
                out.candidates.append(Candidate(**{**asdict(c), "manager": m}))
                continue
            pk = pick_of.get(pick_idx.canonical(raw) or "")
            pn = prev_idx.canonical(raw)
            pg, pf = _season_line(prev_rows[pn]) if pn else (None, None)
            level, prior, _k0, kind = shrunk_level(None, 0, pf, pg, league_mean)
            age, age_source = age_for(ages, season, raw) if ages is not None else (None, None)
            kept = bool(pk and pk.get("is_keeper"))
            out.candidates.append(Candidate(
                decision=out.decision, season=season, point="live", as_of=last, manager=m, player=raw,
                kept_next=False, kept=kept,
                draft_round=None if (not pk or kept) else int(pk["round"]),
                undrafted=pk is None, acquired="trade" if any(n == raw and mm == m for n, mm in trades_to)
                else ("draft" if pk and pk["manager"] == m else "pickup"),
                stint_start=last, games=0, fppg=None, fppg_rank=0, team_games=0, availability=None,
                days_rostered=0, first_day=last, prev_games=pg, prev_fppg=None if pf is None else round(pf, 3),
                age=age, age_source=age_source,
                draft_pick=None if (not pk or kept) else int(pk["pick_number"]),
                draft_rank=None if (not pk or kept) else kept_league + int(pk["pick_number"]),
                level=round(level, 3), level_prior=round(prior, 3), level_prior_kind=kind,
                prev_lines=back(raw), league_mean=round(league_mean, 4)))
    for m in rosters:
        mine = sorted([c for c in out.candidates if c.manager == m],
                      key=lambda c: (c.fppg is None, -(c.fppg or 0.0), c.player))
        for i, c in enumerate(mine, 1):
            c.fppg_rank = i
    return out


def build(inputs: Optional[Inputs] = None, root=ROOT, decisions=DECISIONS, points=POINTS,
          ages: Optional[dict] = None) -> dict:
    """{(decision, point): Snapshot}. ages: {season: PlayerIndex} (load_ages),
    every candidate season AND its neighbours (age_seasons()); None leaves
    every age missing."""
    inputs = inputs or Inputs.load(root)
    return {(d, p): snapshot(inputs, d, p, ages) for d in decisions for p in points}


def season_days_total(inputs: Inputs, season: str) -> int:
    return len({r["date"] for r in inputs.log[season]})


def summary(inputs: Inputs, snaps: dict) -> list:
    """Per decision, from the end point: candidates per manager, keepers found,
    partial seasons, missing ages; the week2/mid ceilings."""
    out = []
    for d in sorted({k[0] for k in snaps}):
        end = snaps[(d, "end")]
        season = prev_season(d)
        days = sorted({r["date"] for r in inputs.log[season]})
        cands = end.candidates
        partial = [c for c in cands if c.days_rostered < len(days)]
        late = [c for c in cands if c.first_day > days[0]]
        out.append({
            "decision": d, "from_season": season, "end_day": end.as_of,
            "candidates": {m: len(v) for m, v in end.by_manager().items()},
            "keepers_found": sum(1 for c in cands if c.kept_next),
            "keepers": sum(len(v) for v in end.keepers.values()),
            "partial_season": len(partial), "joined_after_day_1": len(late),
            "prev_season_not_rostered": sum(1 for c in cands if c.prev_games is None),
            "missing_age": sorted(c.player for c in cands if c.age is None),
            "age_from_neighbour": sorted(f"{c.player} ({c.age_source})" for c in cands
                                         if c.age_source and c.age_source.endswith(("- 1", "+ 1"))),
            "ceilings": {p: snaps[(d, p)].ceiling for p in POINTS if (d, p) in snaps},
            "weeks": {p: snaps[(d, p)].week for p in POINTS if (d, p) in snaps},
            "acquired": {a: sum(1 for c in cands if c.acquired == a) for a in ("draft", "trade", "pickup")},
            "team_label_flipping": sorted(c.player for c in cands if c.team_flips > 2),
        })
    return out
