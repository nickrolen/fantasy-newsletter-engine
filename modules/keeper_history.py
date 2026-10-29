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


def snapshot(inputs: Inputs, decision: str, point: str, ages: Optional[PlayerIndex] = None,
             check: bool = True) -> Snapshot:
    """The decision as seen from one as-of point. Everything below reads
    `rows` -- the season's playerlog cut at as_of -- and trades dated on or
    before it."""
    season = prev_season(decision)
    all_rows = inputs.log[season]
    week, as_of = as_of_point(all_rows, season, point)
    rows = [r for r in all_rows if r["date"] <= as_of]          # point-in-time, here and only here
    season_days = sorted({r["date"] for r in rows})
    keepers = keepers_of(inputs, decision)
    if check:
        end_day = as_of_point(all_rows, season, "end")[1]
        check_keepers_on_rosters(keepers, roster_on(all_rows, end_day), decision)
    rosters = roster_on(rows, as_of)
    absent = [(m, k) for m, ks in keepers.items() for k in ks if k not in set(rosters.get(m, []))]
    ceiling = sum(len(ks) for ks in keepers.values()) - len(absent)

    names = Names(all_rows)
    kept_now, round_now, drafted_by = set(), {}, {}
    for p in inputs.picks.get(season, []):
        n = names.canon(p["player_name"], p.get("player_key"))
        if n is None:
            continue
        drafted_by[n] = p["manager"]
        if p.get("is_keeper"):
            kept_now.add(n)
        else:
            round_now[n] = int(p["round"])
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
            teams = [r["nba_team"] for r in prow]
            flips = sum(1 for a, b in zip(teams, teams[1:]) if a != b)
            pn = prev_names.canonical(n)
            pg, pf = _season_line(prev_by_player[pn]) if pn else (None, None)
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
                age=None if ages is None else ages.get(n), team_flips=flips))
        order = sorted(mine, key=lambda c: (c.fppg is None, -(c.fppg or 0.0), c.player))
        for i, c in enumerate(order, 1):
            c.fppg_rank = i
        snap.candidates.extend(sorted(mine, key=lambda c: c.player))
    return snap


def build(inputs: Optional[Inputs] = None, root=ROOT, decisions=DECISIONS, points=POINTS,
          ages: Optional[dict] = None) -> dict:
    """{(decision, point): Snapshot}. ages: {season: PlayerIndex} (load_ages);
    None leaves every age missing."""
    inputs = inputs or Inputs.load(root)
    return {(d, p): snapshot(inputs, d, p, None if ages is None else ages.get(prev_season(d)))
            for d in decisions for p in points}


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
            "ceilings": {p: snaps[(d, p)].ceiling for p in POINTS if (d, p) in snaps},
            "weeks": {p: snaps[(d, p)].week for p in POINTS if (d, p) in snaps},
            "acquired": {a: sum(1 for c in cands if c.acquired == a) for a in ("draft", "trade", "pickup")},
            "team_label_flipping": sorted(c.player for c in cands if c.team_flips > 2),
        })
    return out
