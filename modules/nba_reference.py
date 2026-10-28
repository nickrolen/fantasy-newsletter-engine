"""
nba_reference.py -- who is an NBA player, cached, for checking override names.

The overrides file describes injuries, not rosters (STATUS_2026-10-28,
"Overrides policy"): a player with a long injury goes in rostered or not, and
an unrostered one with a long injury falls out of PLAYERLIST precisely
because he is hurt. So "is this a real player" cannot be asked of the rosters
and PLAYERLIST alone. The reference is the union of:

    PLAYERLIST and config/ROSTERS.json        read live, every call
    basketball-reference per-game, last completed season (NBA_2026)
    basketball-reference per-game, this season (NBA_2027) -- anyone who has
        played a game, rookies included

The two basketball-reference lists are CACHED in data/NBA_PLAYER_REFERENCE.json
with fetched_at and their sources, and refreshed by one command:

    py scripts/overrides.py refresh-reference

Integrity and `overrides.py add` read the cache and never touch the network.
A missing cache RAISES with that command. A failed fetch RAISES and leaves
the old cache in place -- unlike fetch_playerlist's age lookup, which
returns {} on any error.

Names compare through data_loader.PlayerIndex (accents, suffixes, initials),
so "Jimmy Butler III" is "Jimmy Butler".
"""

from __future__ import annotations

import html as html_lib
import json
import re
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from .data_loader import CURRENT_SEASON, PlayerIndex, atomic_write_json, closest_player_name

CACHE = Path("data") / "NBA_PLAYER_REFERENCE.json"
REFRESH_COMMAND = "py scripts/overrides.py refresh-reference"
URL = "https://www.basketball-reference.com/leagues/NBA_{year}_per_game.html"
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}
# basketball-reference's team codes that differ from the NBA schedule's.
BBREF_TO_SCHEDULE = {"BRK": "BKN", "CHO": "CHA", "PHO": "PHX"}
MULTI_TEAM = re.compile(r"^\dTM$")


class ReferenceMissing(RuntimeError):
    """The cached reference does not exist: run the refresh command."""


class ReferenceFetchError(RuntimeError):
    """A basketball-reference fetch failed; the old cache is untouched."""


def season_end_years(season: str = CURRENT_SEASON) -> tuple:
    """(last completed season's end year, this season's): '2026-27' -> (2026, 2027)."""
    start = int(str(season)[:4])
    return start, start + 1


def parse_per_game(doc: str) -> list:
    """[(name, schedule team code or None)] in page order. A player traded
    mid-season has a combined '2TM' row and then one row per team, in order:
    his team is the LAST single-team row, so later rows overwrite earlier ones."""
    out = []
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", doc, re.S):
        name = re.search(r'data-stat="(?:name_display|player)"[^>]*>(?:<a[^>]*>)?([^<]+)', row)
        if not name or name.group(1).strip() in ("Player", "League Average"):
            continue
        team = re.search(r'data-stat="(?:team_name_abbr|team_id)"[^>]*>(?:<a[^>]*>)?([^<]+)', row)
        code = team.group(1).strip() if team else None
        if code and MULTI_TEAM.match(code):
            code = None
        if code:
            code = BBREF_TO_SCHEDULE.get(code, code)
        out.append((html_lib.unescape(name.group(1)).strip(), code))
    return out


def _fetch(year: int) -> str:
    req = urllib.request.Request(URL.format(year=year), headers=HEADERS)
    with urllib.request.urlopen(req, timeout=45) as resp:
        return resp.read().decode("utf-8", "replace")


def refresh(base_path=".", fetch=_fetch, now: datetime = None) -> dict:
    """Fetch both seasons and write the cache. Raises (writing nothing) on
    any failure, including a page that parses to no players."""
    last, this = season_end_years()
    seasons = {}
    for label, year in (("last_completed", last), ("this_season", this)):
        url = URL.format(year=year)
        try:
            rows = parse_per_game(fetch(year))
        except Exception as e:
            raise ReferenceFetchError(f"{url}: {type(e).__name__}: {e}. "
                                      f"The cached reference was NOT changed.") from e
        if not rows:
            raise ReferenceFetchError(f"{url} parsed to no players: the page changed. "
                                      "The cached reference was NOT changed.")
        teams = {}
        for name, code in rows:
            if code or name not in teams:
                teams[name] = code
        seasons[label] = {"source": url, "season_end_year": year, "players": teams}
    blob = {"fetched_at": (now or datetime.now(timezone.utc)).isoformat(timespec="seconds"),
            "_comment": "basketball-reference per-game lists: every NBA player who played "
                        "last season or has played this one, with his team (schedule codes; "
                        "null after a multi-team season with no single-team row). "
                        f"Refresh: {REFRESH_COMMAND}. Read by modules/nba_reference.py.",
            "seasons": seasons}
    atomic_write_json(Path(base_path) / CACHE, blob)
    return blob


def load_cache(base_path=".") -> dict:
    path = Path(base_path) / CACHE
    if not path.is_file():
        raise ReferenceMissing(f"{path} is missing: the NBA player-name reference has never been "
                               f"fetched. Run `{REFRESH_COMMAND}` (needs the network once).")
    return json.loads(path.read_text(encoding="utf-8"))


def _playerlist(base: Path) -> dict:
    """{name: NBA team} from data/PLAYERLIST.xlsx, or {} if there is none."""
    path = base / "data" / "PLAYERLIST.xlsx"
    if not path.is_file():
        return {}
    import pandas as pd
    frame = pd.read_excel(path)
    return {str(r["player_name"]): str(r["player_nba_team"]).upper()
            for _, r in frame.iterrows() if str(r.get("player_name", "")).strip()}


def _rostered(base: Path) -> list:
    path = base / "config" / "ROSTERS.json"
    if not path.is_file():
        return []
    blob = json.loads(path.read_text(encoding="utf-8"))
    return [n for v in (blob.get("rosters") or {}).values() if isinstance(v, list) for n in v]


class Reference:
    """The union, with where each name came from and the team each source gives."""

    def __init__(self, base_path=".", cache: dict = None, playerlist: dict = None,
                 rostered: list = None):
        base = Path(base_path)
        self.cache = cache if cache is not None else load_cache(base)
        self.playerlist = playerlist if playerlist is not None else _playerlist(base)
        self.rostered = rostered if rostered is not None else _rostered(base)
        seasons = self.cache.get("seasons") or {}
        self.this_season = (seasons.get("this_season") or {}).get("players") or {}
        self.last_season = (seasons.get("last_completed") or {}).get("players") or {}
        names = {}
        for src in (self.last_season, self.this_season, dict.fromkeys(self.rostered),
                    self.playerlist):
            for n in src:
                names[n] = n
        self.index = PlayerIndex(names)
        self._pl = PlayerIndex(dict(self.playerlist))
        self._ros = PlayerIndex({n: n for n in self.rostered})
        self._this = PlayerIndex(dict(self.this_season))
        self._last = PlayerIndex(dict(self.last_season))

    @property
    def fetched_at(self) -> str:
        return str(self.cache.get("fetched_at"))

    def resolve(self, name: str):
        """The reference's spelling of `name`, or None."""
        return self.index.canonical(name)

    def in_league_files(self, name: str) -> bool:
        """On a roster (ROSTERS.json) or in PLAYERLIST -- where an override
        takes effect. A real player in neither is inert until he reappears."""
        return self._ros.canonical(name) is not None or self._pl.canonical(name) is not None

    def near(self, name: str, cutoff: float = 0.8):
        """The closest real name to one that resolved to nobody -- a typo hint."""
        return closest_player_name(name, list(dict.keys(self.index)), cutoff)

    def team_for(self, name: str):
        """(schedule team code, where it came from) or (None, None). PLAYERLIST
        first (this week's Yahoo list), then this season's basketball-reference
        list, then last season's -- which an off-season move can make wrong,
        and says so."""
        for idx, label in ((self._pl, "PLAYERLIST"),
                           (self._this, "basketball-reference, this season"),
                           (self._last, "basketball-reference, LAST season -- confirm")):
            key = idx.canonical(name)
            if key is not None and dict.get(idx, key):
                return str(dict.get(idx, key)).upper(), label
        return None, None

    def unknown_message(self, name: str) -> str:
        hint = self.near(name)
        if hint:
            return (f"{name!r} matches no NBA player (PLAYERLIST, ROSTERS.json, or "
                    f"basketball-reference as of {self.fetched_at}). Probably a typo: did you "
                    f"mean {hint!r}?")
        return (f"{name!r} matches no NBA player (PLAYERLIST, ROSTERS.json, or "
                f"basketball-reference as of {self.fetched_at}), and nothing is close to it. "
                f"Check the spelling; a rookie who has not played yet needs `{REFRESH_COMMAND}` "
                "after his first game, or his PLAYERLIST row.")

