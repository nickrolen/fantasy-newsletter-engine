"""
season_performers.py

Season-to-date best/worst performer tables for Stats Corner, AS OF THE END OF
THE REPORT WEEK (week_end), whatever day the build runs.

Tables generated:
1. Best Performers (Total FP, This Season) - Top 30 by Total FP
2. Best Performers (FPPG, This Season) - Top 30 by FPPG (min 50% GP)
3. Biggest Duds (Total FP, This Season) - Bottom 30 by Total FP
4. Biggest Duds (FPPG, This Season) - Bottom 30 by FPPG (min 50% GP)

WHERE EVERY NUMBER COMES FROM (HANDOFF_SEASON_PERFORMERS_ASOF_2026-10-30;
Nick's decisions of 10-30, SEASON_PERFORMERS_ASOF_STOP_2026-10-30):

  points   Yahoo, the SUM of each player's daily lines ('date' requests) from
           the season's first game day through week_end. Not the season total:
           that runs through NOW (the bug this replaces -- a 10-30 build of
           week 1 counted 10-26..10-29's points over week 1's games), and it
           carries NBA stat corrections that the daily lines do not. The daily
           sum matched PLAYERLOG exactly for all 52 stable week-1 players;
           season-minus-later-days matched 47. No disk cache: a day's line can
           still change, and the calls are cheap (3 per day of season).
  ids      the league's own rosters (lg.to_team(..).roster()), mapped to the
           ROSTERS.json spelling -- never a name search, which took the first
           result when no name matched exactly.
  games    basketball-reference player game logs, games dated on or before
           week_end: GP (an appearance counts with zero stats), minutes, and
           the NBA team for each game (stats.nba.com is blocked from Nick's
           machine; there is no fallback). Fetched fresh every build, no cache.
  FPPG     Yahoo points through week_end / bbref GP through week_end.

FAILURES ARE LOUD. A rostered player with no Yahoo ID, no bbref ID, a failed
fetch, or a disagreement between Yahoo's played days and bbref's game dates
makes the section INCOMPLETE; build_season_performers then raises
SeasonPerformersIncomplete, and Step 6 refuses unless
--allow-incomplete-season-performers (recorded in the report metadata and the
capture; the page says the tables are incomplete).
"""

import html as _html
import json
import re
import time
import urllib.error
import urllib.request
import warnings
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple


def _league_now():
    from .league_clock import league_now
    return league_now()

import pandas as pd

warnings.filterwarnings('ignore', category=FutureWarning, module='pandas')
warnings.filterwarnings('ignore', message='Could not infer format')

# Yahoo API imports are lazy-loaded to allow the module to be imported
# even when yahoo_oauth is not available (e.g., in testing environments)
yfa = None
OAuth2 = None


def _ensure_yahoo_imports():
    """Lazy-load Yahoo API dependencies."""
    global yfa, OAuth2
    if yfa is None:
        from yahoo_oauth import OAuth2 as _OAuth2
        import yahoo_fantasy_api as _yfa
        OAuth2 = _OAuth2
        yfa = _yfa


from .data_loader import (
    PlayerIndex,
    LEAGUE_KEY, CURRENT_SEASON,
    MANAGER_TO_TEAM, NBA_SCHEDULE_FILE,
)

NBA_SEASON = CURRENT_SEASON

YAHOO_BATCH = 25
YAHOO_CATS = ("FGM", "FGA", "FTM", "FTA", "3PTM", "PTS", "REB", "AST", "ST", "BLK", "TO")
BBREF_PER_GAME = "https://www.basketball-reference.com/leagues/NBA_{year}_per_game.html"
BBREF_GAMELOG = "https://www.basketball-reference.com/players/{letter}/{pid}/gamelog/{year}"
BBREF_DELAY = 3.2            # basketball-reference: 20 pages a minute
BBREF_TO_SCHEDULE = {"BRK": "BKN", "CHO": "CHA", "PHO": "PHX"}


class SeasonPerformersIncomplete(RuntimeError):
    """The section is incomplete or failed. .status says how; Step 6 refuses
    unless --allow-incomplete-season-performers."""

    def __init__(self, message: str, status: Optional[dict] = None):
        super().__init__(message)
        self.status = status or {}


class SourceError(RuntimeError):
    """A fetch or a parse failed. Never caught to a default."""


# =============================================================================
# DATA LOADING HELPERS
# =============================================================================

def get_yahoo_league(base_path: Path) -> "yfa.League":
    """Initialize Yahoo Fantasy API connection."""
    _ensure_yahoo_imports()
    oauth_file = base_path / 'oauth2.json'
    from .yahoo_auth import build_oauth  # fail-fast: never prompts interactively
    oauth = build_oauth(oauth_file, OAuth2=OAuth2)
    return yfa.League(oauth, LEAGUE_KEY)


def load_rosters(base_path: Path) -> Dict[str, List[str]]:
    """Load current rosters from config/ROSTERS.json."""
    rosters_path = base_path / 'config' / 'ROSTERS.json'
    with open(rosters_path, encoding="utf-8") as f:
        data = json.load(f)
    return data.get('rosters', {})


def load_playerlist(base_path: Path) -> pd.DataFrame:
    """Load data/PLAYERLIST.xlsx with projections."""
    return pd.read_excel(base_path / 'data' / 'PLAYERLIST.xlsx')


def load_schedule(base_path: Path) -> dict:
    """Load fantasy schedule from config/SCHEDULE.json."""
    with open(base_path / 'config' / 'SCHEDULE.json', encoding="utf-8") as f:
        return json.load(f)


def load_nba_schedule(base_path: Path) -> List[dict]:
    """Load NBA game schedule from the configured schedule file."""
    with open(base_path / NBA_SCHEDULE_FILE, encoding="utf-8") as f:
        return json.load(f).get('games', [])


def get_week_end_date(schedule: dict, week: int) -> datetime:
    """Get the end date for a given fantasy week."""
    for w in schedule.get('weeks', []):
        if w['week'] == week:
            return datetime.strptime(w['end_date'], '%Y-%m-%d')
    raise ValueError(f"Week {week} not found in schedule")


def _game_day(game: dict) -> str:
    """The schedule stamps each game 'YYYY-MM-DDT00:00:00Z': the NBA game date
    (the calendar Yahoo's daily lines and basketball-reference both use)."""
    return str(game['date'])[:10]


def calculate_team_games(nba_schedule: List[dict], through_date: datetime) -> Dict[str, int]:
    """Calculate games played per NBA team through a given date (inclusive)."""
    through = through_date.date().isoformat() if isinstance(through_date, datetime) \
        else str(through_date)[:10]
    team_games = {}
    for game in nba_schedule:
        if _game_day(game) <= through:
            for team in [game['home'], game['away']]:
                team_games[team] = team_games.get(team, 0) + 1
    return team_games


def season_first_day(nba_schedule: List[dict]) -> date:
    days = sorted(_game_day(g) for g in nba_schedule)
    if not days:
        raise SourceError("the NBA schedule has no games: the season's first day is unknown")
    return date.fromisoformat(days[0])


def calculate_gp_pct_with_trades(
    player_team_games: Dict[str, int],
    nba_team_totals: Dict[str, int]
) -> float:
    """
    Calculate GP% accounting for trades.

    If a player played 20 games for ATL (41 total) and 10 games for WAS (38 total),
    their possible GP is calculated based on the teams they were actually on.
    """
    if not player_team_games:
        return 0.0
    total_played = sum(player_team_games.values())
    total_possible = sum(nba_team_totals.get(team, 0) for team in player_team_games.keys())
    if total_possible == 0:
        return 0.0
    return min(100.0, (total_played / total_possible) * 100)


# =============================================================================
# YAHOO: ids from the league's rosters, points as the sum of daily lines
# =============================================================================

def roster_player_ids(lg, rosters: Dict[str, List[str]]) -> Tuple[Dict[str, int], List[str]]:
    """({ROSTERS.json name: Yahoo player id}, [failures]) from the league's own
    rosters -- no name search. Every ROSTERS.json name must be on a Yahoo
    roster (accents and suffixes matched by PlayerIndex)."""
    yahoo = {}
    for team_key in lg.teams():
        for p in lg.to_team(team_key).roster():
            yahoo[str(p["name"])] = int(p["player_id"])
    idx = PlayerIndex(yahoo)
    out, failures = {}, []
    for manager, names in rosters.items():
        for n in names:
            pid = idx.get(n)
            if pid is None:
                failures.append(f"{n} ({manager}): not on any Yahoo roster in the league")
            else:
                out[n] = int(pid)
    return out, failures


def _num(x) -> Optional[float]:
    """A Yahoo stat value: a number, or None for '-' (his team did not play)."""
    if isinstance(x, (int, float)):
        return float(x)
    try:
        return float(str(x))
    except ValueError:
        return None


def yahoo_daily_points(lg, ids: Dict[str, int], first_day: date, last_day: date,
                       batch: int = YAHOO_BATCH) -> Tuple[dict, int]:
    """({name: {"points", "played", "zero_lines"}}, calls) -- the sum of each
    player's daily lines from first_day through last_day inclusive.

    A daily line is one of three things (measured 10-30):
      team did not play   every stat '-'          -> not a game
      DNP                 every stat 0.0           -> zero_lines (bbref decides)
      played              some stat non-zero       -> played
    A line missing for a requested player, or without total_points, RAISES."""
    by_id = {pid: n for n, pid in ids.items()}
    out = {n: {"points": 0.0, "played": [], "zero_lines": []} for n in ids}
    pids = sorted(by_id)
    calls = 0
    d = first_day
    while d <= last_day:
        seen = set()
        for i in range(0, len(pids), batch):
            rows = lg.player_stats(pids[i:i + batch], 'date', date=d)
            calls += 1
            for r in rows:
                pid = int(r.get("player_id", 0))
                if pid not in by_id:
                    continue
                if "total_points" not in r:
                    raise SourceError(f"Yahoo's {d} line for {by_id[pid]} has no total_points")
                seen.add(pid)
                cats = [_num(r.get(c)) for c in YAHOO_CATS]
                if all(v is None for v in cats):
                    if _num(r["total_points"]) not in (None, 0.0):
                        raise SourceError(f"Yahoo's {d} line for {by_id[pid]}: no stats but "
                                          f"{r['total_points']} points")
                    continue                                   # his team did not play
                rec = out[by_id[pid]]
                rec["points"] += float(_num(r["total_points"]) or 0.0)
                if any(v for v in cats if v is not None):
                    rec["played"].append(d.isoformat())
                else:
                    rec["zero_lines"].append(d.isoformat())
        gone = sorted(by_id[p] for p in set(pids) - seen)
        if gone:
            raise SourceError(f"Yahoo returned no {d} line for {gone}")
        d += timedelta(days=1)
    for rec in out.values():
        rec["points"] = round(rec["points"], 2)
    return out, calls


# =============================================================================
# BASKETBALL-REFERENCE: ids, game logs (fresh every build, no cache)
# =============================================================================

def bbref_get(url: str, fetch: Optional[Callable] = None, delay: float = BBREF_DELAY) -> str:
    """The page, fetched now. No cache: this season's pages change daily. A
    failed fetch RAISES."""
    try:
        if fetch is not None:
            return fetch(url)
        from .nba_reference import HEADERS
        time.sleep(delay)
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=45) as resp:
            return resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        raise SourceError(f"{url}: HTTP {e.code}") from e
    except SourceError:
        raise
    except Exception as e:
        raise SourceError(f"{url}: {type(e).__name__}: {e}") from e


def parse_bbref_ids(doc: str) -> Dict[str, set]:
    """{display name: {bbref ids}} from a season's per-game page."""
    out: Dict[str, set] = {}
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", doc, re.S):
        m = re.search(r'data-append-csv="([^"]+)"\s+data-stat="(?:name_display|player)"[^>]*>'
                      r'(?:<a[^>]*>)?([^<]+)', row)
        if m:
            out.setdefault(_html.unescape(m.group(2)).strip(), set()).add(m.group(1))
    if not out:
        raise SourceError("basketball-reference's per-game page parsed to no players: "
                          "the page changed")
    return out


def bbref_ids_for(names: List[str], pages: List[Dict[str, set]]) -> Tuple[Dict[str, str], List[str]]:
    """({rostered name: bbref id}, [failures]). This season's page first, then
    last season's (a player who has not played this season is only there).
    Names match through PlayerIndex (accents, Jr./III, initials; ambiguity is
    a miss). No match, or two ids behind one name, is a failure, never a skip."""
    idxs = [PlayerIndex(page) for page in pages]
    out, failures = {}, []
    for n in names:
        hits = None
        for idx in idxs:
            hits = idx.get(n)
            if hits is not None:
                break
        if hits is None:
            failures.append(f"{n}: not on basketball-reference's per-game page this season "
                            "or last")
        elif len(hits) != 1:
            failures.append(f"{n}: {len(hits)} basketball-reference players match ({sorted(hits)})")
        else:
            out[n] = next(iter(hits))
    return out, failures


def parse_gamelog(doc: str) -> List[dict]:
    """[{"date", "team", "appeared", "minutes"}] from a player's regular-season
    game log: one row per team game while he was on the team. An appearance is
    a row with minutes (Inactive / Did Not Play rows have none) -- it counts
    even with zero stats. The team is the schedule's code (BRK -> BKN ...)."""
    i = doc.find('id="player_game_log_reg"')
    if i < 0:
        raise SourceError("no regular-season game-log table (player_game_log_reg): "
                          "the page changed")
    tab = doc[i:]
    tab = tab[:tab.find("</table>")]
    out = []
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", tab, re.S):
        d = re.search(r'data-stat="date"[^>]*>(?:<a[^>]*>)?(\d{4}-\d{2}-\d{2})<', row)
        if not d:
            continue
        t = re.search(r'data-stat="team_name_abbr"[^>]*>(?:<a[^>]*>)?([A-Z]{3})<', row)
        if not t:
            raise SourceError(f"game-log row {d.group(1)} has no team")
        mp = re.search(r'data-stat="mp"[^>]*csk="(\d+)"', row)
        out.append({"date": d.group(1), "team": BBREF_TO_SCHEDULE.get(t.group(1), t.group(1)),
                    "appeared": mp is not None,
                    "minutes": (int(mp.group(1)) / 60.0) if mp else None})
    return out


def gamelog_url(bbref_id: str, season: str = CURRENT_SEASON) -> str:
    return BBREF_GAMELOG.format(letter=bbref_id[0], pid=bbref_id, year=int(season[:4]) + 1)


# =============================================================================
# THE SECTION
# =============================================================================

def cross_check(yahoo: dict, games: List[dict]) -> Tuple[List[str], List[str]]:
    """([cameos], [findings]) for one player, both sides through week_end.
    Yahoo's played days must be bbref's appearance dates. A bbref appearance
    whose Yahoo line is all zeros is a zero-stat cameo (listed, not a fault);
    anything else is a finding."""
    ydays = set(yahoo["played"])
    zeros = set(yahoo["zero_lines"])
    bdays = {g["date"] for g in games if g["appeared"]}
    cameos, findings = [], []
    for d in sorted(bdays - ydays):
        if d in zeros:
            cameos.append(d)
        else:
            findings.append(f"basketball-reference has an appearance on {d}; Yahoo has no line")
    for d in sorted(ydays - bdays):
        findings.append(f"Yahoo has stats on {d}; basketball-reference has no appearance")
    return cameos, findings


def joined_dates(base_path: Path, rosters: Dict[str, List[str]], schedule: dict,
                 first_day: str) -> Tuple[Dict[Tuple[str, str], Optional[str]], List[str]]:
    """({(manager, rostered name): the day he joined that team, or None when
    he has been on it since the season's first day}, [failures]).

    The season tables count every game a player played this season, before
    he joined his current team too (newsletter 1's draft credited Paul
    George's and Aaron Wiggins's week 1 games "for" teams that added them on
    10-26). This is what the "since" marker reads. In order:
      1. his latest ADD by that manager in the synced waivers files, with the
         commissioner's rulings applied (a void is no add; an effective date
         moves it -- transaction_rulings);
      2. drafted or kept by that manager (DRAFT_PICKS_CURRENT.json): day one;
      3. his first LINEUPS row with that manager (effective dates applied);
    and with none of them, a FAILURE: shown as if he had been there all
    season, he would be the bug this fixes."""
    import re as _re
    from .transaction_rulings import (waiver_lines, _parse_line, effective_dates, load_all,
                                      apply_effective_dates)
    base = Path(base_path)
    adds: Dict[Tuple[str, str], str] = {}
    for f in sorted((base / "data").glob("waivers_week*.txt")):
        m = _re.search(r"waivers_week(\d+)\.txt$", f.name)
        if not m:
            continue
        lines, _ = waiver_lines(f, base, int(m.group(1)), schedule)
        for ln in lines:
            p = _parse_line(ln)
            if p:
                key = (p[1], p[2])
                adds[key] = max(adds.get(key, p[0]), p[0])
    for r in effective_dates(load_all(base)):
        adds[(r.manager, r.player)] = r.effective
    by_mgr_adds: Dict[str, PlayerIndex] = {}
    for (mgr, name), day in adds.items():
        by_mgr_adds.setdefault(mgr, PlayerIndex())[name] = day

    drafted: Dict[str, PlayerIndex] = {}
    picks_path = base / "config" / "DRAFT_PICKS_CURRENT.json"
    if picks_path.is_file():
        for pk in json.loads(picks_path.read_text(encoding="utf-8")).get("picks", []):
            drafted.setdefault(pk.get("manager", ""), PlayerIndex())[pk.get("player_name", "")] = True

    first_row: Dict[str, PlayerIndex] = {}
    lu_path = base / "data" / "LINEUPS.xlsx"
    if lu_path.is_file():
        from .data_loader import load_lineups
        lu = apply_effective_dates(load_lineups(lu_path), base, "lineups", schedule,
                                   echo=lambda *_: None)
        for (mgr, name), day in lu.groupby(["manager", "player_name"])["date"].min().items():
            first_row.setdefault(mgr, PlayerIndex())[name] = str(day)[:10]

    out, failures = {}, []
    for mgr, names in rosters.items():
        for n in names:
            add = (by_mgr_adds.get(mgr) or PlayerIndex()).get(n)
            if add is not None:
                out[(mgr, n)] = add if add > first_day else None
            elif (drafted.get(mgr) or PlayerIndex()).get(n) is not None:
                out[(mgr, n)] = None
            elif (row := (first_row.get(mgr) or PlayerIndex()).get(n)) is not None:
                out[(mgr, n)] = row if row > first_day else None
            else:
                failures.append(f"{n} ({mgr}): when he joined the team cannot be determined "
                                "(no add in the waivers files, not drafted or kept, no LINEUPS row)")
    return out, failures


def aggregate(rosters: Dict[str, List[str]], playerlist: pd.DataFrame, ids: Dict[str, int],
              points: dict, bbref_ids: Dict[str, str], logs: Dict[str, List[dict]],
              nba_team_games: Dict[str, int], week_end: str,
              joined: Optional[Dict[Tuple[str, str], Optional[str]]] = None
              ) -> Tuple[pd.DataFrame, dict]:
    """(stats rows, {"cameos", "findings"}) for every rostered player whose
    sources all came back. joined: joined_dates' map -- a row whose player
    joined his team during the season carries `joined` and `games_with_team`
    (his counted games on or after that day)."""
    pl = PlayerIndex({r["player_name"]: r for r in playerlist.to_dict("records")})
    rows, cameos, findings = [], {}, {}
    for manager, names in rosters.items():
        fantasy_team = MANAGER_TO_TEAM.get(manager, manager)
        for n in names:
            if n not in ids or n not in bbref_ids or n not in logs:
                continue
            games = [g for g in logs[n] if g["date"] <= week_end]
            c, f = cross_check(points[n], games)
            if c:
                cameos[n] = c
            if f:
                findings[n] = f
            app = [g for g in games if g["appeared"]]
            gp = len(app)
            per_team: Dict[str, int] = {}
            for g in games:
                per_team[g["team"]] = per_team.get(g["team"], 0) + (1 if g["appeared"] else 0)
            mins = [g["minutes"] for g in app if g["minutes"] is not None]
            total_fp = points[n]["points"]
            nba_team = games[-1]["team"] if games else (pl.get(n) or {}).get("player_nba_team", "")
            since = (joined or {}).get((manager, n))
            rows.append({
                "joined": since,
                "games_with_team": (sum(1 for g in app if g["date"] >= since)
                                    if since else None),
                "player_name": n, "fantasy_team": fantasy_team, "nba_team": nba_team,
                "total_fp": round(total_fp, 1),
                "fppg": round(total_fp / gp, 2) if gp else 0.0,
                "gp": gp,
                "gp_pct": round(max(0.0, min(100.0, calculate_gp_pct_with_trades(per_team, nba_team_games))), 1),
                "mpg": round(sum(mins) / len(mins), 1) if mins else None,
            })
    df = pd.DataFrame(rows, columns=["player_name", "fantasy_team", "nba_team", "total_fp", "fppg",
                                     "gp", "gp_pct", "mpg", "joined", "games_with_team"])
    for c in ("total_fp", "fppg", "gp_pct"):
        df[c] = pd.to_numeric(df[c]).astype(float)
    df["gp"] = pd.to_numeric(df["gp"]).astype(int)
    proj_lookup = PlayerIndex(playerlist.set_index('player_name').to_dict('index'))
    df['proj_fppg_ros'] = df['player_name'].map(
        lambda x: proj_lookup.get(x, {}).get('projectedFPPG', 0)).astype(float).round(2)
    df['proj_fp_ros'] = df['player_name'].map(
        lambda x: proj_lookup.get(x, {}).get('player_total_proj_FP', 0)).astype(float).round(1)
    proj = df['proj_fppg_ros'].where(df['proj_fppg_ros'] != 0)
    df['eff_pct'] = (((df['fppg'] / proj) - 1) * 100).round(1).fillna(0.0)
    return df, {"cameos": cameos, "findings": findings}


def _row_dict(row) -> dict:
    out = {k: row[k] for k in ('player_name', 'fantasy_team', 'nba_team', 'total_fp', 'fppg',
                               'gp', 'gp_pct', 'mpg', 'eff_pct', 'proj_fp_ros', 'proj_fppg_ros')}
    j = row.get('joined') if hasattr(row, 'get') else None
    out['joined'] = j if isinstance(j, str) and j else None
    g = row.get('games_with_team') if out['joined'] else None
    out['games_with_team'] = int(g) if out['joined'] and g is not None and not pd.isna(g) else None
    return out


def tables(stats: pd.DataFrame, min_gp_pct: float = 50.0) -> dict:
    """The four tables. EVERY table requires GP > 0: zero games is not a
    performance (week 1, 2026-27: 30 players tied at 0.0 FP were once published
    as a "Best Performers" leaderboard)."""
    qualified = stats[stats['gp_pct'] >= min_gp_pct].copy()
    if len(qualified) == 0:
        qualified = stats[stats['gp'] > 0].copy()
    played = stats[stats['gp'] > 0].copy()
    return {
        'best_total_fp': [_row_dict(r) for _, r in played.nlargest(30, 'total_fp').iterrows()],
        'best_fppg': [_row_dict(r) for _, r in qualified.nlargest(30, 'fppg').iterrows()],
        'worst_total_fp': [_row_dict(r) for _, r in played.nsmallest(30, 'total_fp').iterrows()],
        'worst_fppg': [_row_dict(r) for _, r in qualified.nsmallest(30, 'fppg').iterrows()],
        'min_gp_pct_threshold': min_gp_pct,
    }


def generate_season_performers_data(week: int, base_path: Path, min_gp_pct: float = 50.0,
                                    lg=None, bbref_fetch: Optional[Callable] = None,
                                    bbref_delay: float = BBREF_DELAY,
                                    now: Optional[datetime] = None) -> Dict:
    """The section's data, with a "status" block. Never raises on a source
    problem: every failure is recorded in status (complete False); a caller
    that must refuse reads it (build_season_performers)."""
    base = Path(base_path)
    t0 = time.time()
    rosters = load_rosters(base)
    playerlist = load_playerlist(base)
    schedule = load_schedule(base)
    nba_schedule = load_nba_schedule(base)
    week_end_dt = get_week_end_date(schedule, week)
    week_end = week_end_dt.date().isoformat()
    first = season_first_day(nba_schedule)
    nba_team_games = calculate_team_games(nba_schedule, week_end_dt)
    names = [n for v in rosters.values() for n in v]
    status = {"as_of": week_end, "first_day": first.isoformat(),
              "built_at": (now or _league_now()).isoformat(timespec="seconds"),
              "players": len(names), "yahoo_ids": 0, "points_counted": 0, "bbref_ids": 0,
              "games_counted": 0, "failed": 0, "failures": [], "findings": {}, "cameos": {},
              "yahoo_calls": 0, "bbref_pages": 0, "complete": False, "ran": False}
    out = {"best_total_fp": [], "best_fppg": [], "worst_total_fp": [], "worst_fppg": [],
           "min_gp_pct_threshold": min_gp_pct, "status": status}
    failures = status["failures"]
    print(f"Generating season performers for week {week} (through {week_end}, "
          f"{len(names)} rostered players)...")
    # Yahoo
    ids, points = {}, {}
    try:
        lg = lg or get_yahoo_league(base)
        ids, f = roster_player_ids(lg, rosters)
        failures += f
        last = min(week_end_dt.date(), (now or _league_now()).date())
        status["points_through"] = last.isoformat()
        if first <= last:
            points, status["yahoo_calls"] = yahoo_daily_points(lg, ids, first, last)
        else:
            points = {n: {"points": 0.0, "played": [], "zero_lines": []} for n in ids}
    except Exception as e:
        failures.append(f"Yahoo: {type(e).__name__}: {e}")
        points = {}
    status["yahoo_ids"] = len(ids)
    status["points_counted"] = len(points)
    # basketball-reference
    bb_ids, logs = {}, {}
    try:
        year = int(CURRENT_SEASON[:4]) + 1
        pages = []
        for y in (year, year - 1):
            pages.append(parse_bbref_ids(bbref_get(BBREF_PER_GAME.format(year=y), bbref_fetch,
                                                   bbref_delay)))
            status["bbref_pages"] += 1
        bb_ids, f = bbref_ids_for(names, pages)
        failures += f
        for n in names:
            if n not in bb_ids:
                continue
            try:
                logs[n] = parse_gamelog(bbref_get(gamelog_url(bb_ids[n]), bbref_fetch, bbref_delay))
                status["bbref_pages"] += 1
            except SourceError as e:
                failures.append(f"{n}: basketball-reference game log: {e}")
    except Exception as e:
        failures.append(f"basketball-reference: {type(e).__name__}: {e}")
    status["bbref_ids"] = len(bb_ids)
    status["games_counted"] = len(logs)
    # When each rostered player joined his current team (the "since" marker).
    joined, join_failures = {}, []
    try:
        joined, join_failures = joined_dates(base, rosters, schedule, first.isoformat())
    except Exception as e:
        join_failures = [f"joining dates: {type(e).__name__}: {e}"]
    failures += join_failures
    status["joined"] = {f"{n} ({m})": d for (m, n), d in sorted(joined.items()) if d}
    if points:
        stats, checks = aggregate(rosters, playerlist, ids, points, bb_ids, logs, nba_team_games,
                                  week_end, joined)
        status["findings"], status["cameos"] = checks["findings"], checks["cameos"]
        out.update(tables(stats, min_gp_pct))
        status["ran"] = True
        status["counted"] = int(len(stats))
    else:
        status["counted"] = 0
    counted = status["counted"]
    status["failed"] = len(names) - counted + len(status["findings"]) + len(join_failures)
    status["complete"] = bool(status["ran"] and not failures and not status["findings"]
                              and counted == len(names))
    status["runtime_s"] = round(time.time() - t0, 1)
    print(f"  Season performers: {counted}/{len(names)} players counted through {week_end}; "
          f"{len(failures)} failure(s), {len(status['findings'])} cross-check finding(s), "
          f"{len(status['cameos'])} cameo(s); Yahoo {status['yahoo_calls']} calls, "
          f"basketball-reference {status['bbref_pages']} pages, {status['runtime_s']}s")
    for x in failures:
        print(f"    FAILURE: {x}")
    for n, fs in status["findings"].items():
        for x in fs:
            print(f"    FINDING: {n}: {x}")
    return out


def problems_of(status: dict) -> List[str]:
    return list(status.get("failures") or []) + [
        f"{n}: {x}" for n, fs in (status.get("findings") or {}).items() for x in fs]


def build_season_performers(base_path: Path, week: int, allow_incomplete: bool = False,
                            **kw) -> Dict:
    """The section for the stats report. INCOMPLETE OR FAILED RAISES
    SeasonPerformersIncomplete, unless allow_incomplete (Step 6's
    --allow-incomplete-season-performers), in which case the status records
    the override and the page says the tables are incomplete."""
    try:
        data = generate_season_performers_data(week=week, base_path=Path(base_path), **kw)
    except Exception as e:
        status = {"ran": False, "complete": False, "failures": [f"{type(e).__name__}: {e}"],
                  "findings": {}, "cameos": {}, "players": None, "counted": 0}
        data = {"best_total_fp": [], "best_fppg": [], "worst_total_fp": [], "worst_fppg": [],
                "min_gp_pct_threshold": 50.0, "status": status}
    status = data["status"]
    if not status.get("complete"):
        problems = problems_of(status)
        msg = ("season performers incomplete: "
               f"{status.get('counted', 0)}/{status.get('players')} players counted; "
               + "; ".join(problems[:6]) + (" ..." if len(problems) > 6 else ""))
        if not allow_incomplete:
            raise SeasonPerformersIncomplete(msg, status)
        status["override"] = "--allow-incomplete-season-performers"
        print(f"  WARNING (overridden): {msg}")
    else:
        status["override"] = None
    return data


def team_label(row: dict) -> str:
    """The Fantasy Team cell: "Blink-183", or "Blink-183 (since 10-26)" for a
    player who joined that team during the season -- none of his games before
    that day were for it."""
    team = str(row.get("fantasy_team", ""))
    j = row.get("joined")
    if j:
        return f"{team} (since {str(j)[5:10]})"
    return team


SINCE_NOTE = ("Season totals count every game the player played this season, including "
              "games before he joined his current team. \"since MM-DD\" marks a player who "
              "joined during the season: none of his games before that date were for that team.")


def incomplete_note(season_performers: Optional[dict]) -> Optional[str]:
    """One plain sentence for the page when the season tables are incomplete
    (only reachable with --allow-incomplete-season-performers), else None. A
    report from before the status block existed carries none and gets None."""
    status = (season_performers or {}).get("status")
    if not status or status.get("complete"):
        return None
    if not status.get("ran"):
        return ("The season tables could not be built this week "
                "(published with --allow-incomplete-season-performers).")
    missing = (status.get("players") or 0) - (status.get("counted") or 0)
    parts = []
    if missing:
        parts.append(f"{missing} of {status.get('players')} rostered players are missing")
    if status.get("findings"):
        parts.append(f"{len(status['findings'])} player(s) have games the two sources disagree on")
    return (f"The season tables through {status.get('as_of')} are incomplete: "
            + ("; ".join(parts) or "a source failed") + ".")
