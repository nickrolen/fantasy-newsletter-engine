"""nba_prior.py -- a player's NBA seasons (data/historical/NBA_SEASONS.json) as
the ratings read them (4a4 Phase B; claude/HANDOFF_4A4_NBA_HISTORY_OVR_ARCHETYPES_2026-11-20.md).

WHO IS WHO (Index): players are matched by Yahoo player id (the league log's
rows, data/player_actuals.json's name maps), else by a UNIQUE name in the file
(PlayerIndex: accents, suffixes). A name the file cannot place is "unmatched"
-- the caller reports it, never quietly a rookie.

THE ARCHETYPE'S HISTORY (history_per_game; s.3): his last three seasons he
PLAYED before the season asked for (0-game seasons skipped: they never pull a
skill down), each stat's fantasy points per game in this league's scoring,
weighted history_weights (3 : 2 : 1, most recent first) x games.
modules/archetypes.py groups the stats into skills.

THE 0-GAME AND TEAM-GAMES RULINGS (s.1, 11-20; Durability reads them, s.2.4):
counts_for_availability -- a played season counts; a 0-game season counts
only between two seasons he played, or immediately before the season asked
for with a played season before it (a year lost to injury); team_games --
config, 82, 72 in 2020-21, 70 in 2019-20 (the file has no team per season).
"""
from __future__ import annotations

from typing import Dict, Iterable, List, Optional, Tuple

PLAYED_MIN = 1          # a season with gp >= 1 is a season he played


class PriorError(RuntimeError):
    """A required config key or input is missing or malformed; the message names it."""


def season_year(label: str) -> int:
    try:
        y = int(str(label)[:4])
        assert (y + 1) % 100 == int(str(label)[5:7])
        return y
    except Exception:                                   # noqa: BLE001 -- named below
        raise PriorError(f"{label!r} is not a season like 2017-18") from None


def season_label(year: int) -> str:
    return f"{year}-{(year + 1) % 100:02d}"


def team_games(season: str, hc: dict) -> int:
    tg = hc["team_games"]
    return int(tg.get(season, tg["default"]))


def fppg_of(entry_season: dict, values: Dict[str, float]) -> float:
    """Fantasy points per game of one season entry ({"gp", "stats"}), this league's scoring."""
    gp = int(entry_season["gp"])
    if gp < PLAYED_MIN:
        raise PriorError("a 0-game season has no FPPG")
    try:
        return sum(float(entry_season["stats"][k]) * float(v) for k, v in values.items()) / gp
    except KeyError as e:
        raise PriorError(f"a season entry lacks the stat {e.args[0]!r}") from None


def _played(seasons: dict) -> List[str]:
    return sorted(s for s, e in seasons.items() if int(e.get("gp") or 0) >= PLAYED_MIN)


def counts_for_availability(seasons: dict, s: str, season: str) -> bool:
    """Does season s (before `season`) count toward availability? Played: yes.
    0 games: only between two seasons he played, or immediately before
    `season` with a played season before it (ruling 11-20)."""
    e = seasons.get(s)
    if e is None or s >= season:
        return False
    if int(e.get("gp") or 0) >= PLAYED_MIN:
        return True
    played = [p for p in _played(seasons) if p < season]
    before = any(p < s for p in played)
    after = any(s < p for p in played)
    return before and (after or season_year(s) == season_year(season) - 1)


def history_per_game(entry: Optional[dict], season: str, values: Dict[str, float],
                     weights: List[float]) -> Optional[dict]:
    """The archetype's history: {"per_stat": {stat: fantasy points per game}, "fppg",
    "games", "used": [(season, gp, weight)]} over his last len(weights) seasons he
    PLAYED before `season` (most recent first; 0-game seasons skipped, so they
    never pull a skill down), each weighted weights[i] x games. None: no played
    season before `season` (a rookie)."""
    if entry is None:
        return None
    seasons = entry.get("seasons") or {}
    played = [s for s in reversed(_played(seasons)) if s < season][:len(weights)]
    if not played:
        return None
    acc = {k: 0.0 for k in values}
    den = 0.0
    used, games = [], 0
    for s, w in zip(played, weights):
        e = seasons[s]
        gp = int(e["gp"])
        ww = float(w) * gp
        for k, v in values.items():
            try:
                acc[k] += ww * float(e["stats"][k]) * float(v) / gp
            except KeyError:
                raise PriorError(f"{entry.get('name')} {s} lacks the stat {k!r}") from None
        den += ww
        games += gp
        used.append((s, gp, w))
    per = {k: a / den for k, a in acc.items()}
    return {"per_stat": per, "fppg": sum(per.values()), "games": games, "used": used}


class Index:
    """Who is who in NBA_SEASONS: by Yahoo id, else by a unique name."""

    def __init__(self, blob: dict, ids: Optional[Dict[str, object]] = None):
        from .data_loader import PlayerIndex
        self.players = blob["players"]
        by_name: Dict[str, List[str]] = {}
        for pid, r in self.players.items():
            by_name.setdefault(r["name"], []).append(str(pid))
        self._names = by_name
        self._idx = PlayerIndex({n: n for n in by_name})
        self.ids: Dict[str, str] = {}
        if ids:
            self.add_ids(ids)

    def add_ids(self, ids: Dict[str, object]) -> None:
        """{name: Yahoo id} (ints or strings); an id already known for a name is kept."""
        for n, pid in ids.items():
            if pid is None or n in self.ids:
                continue
            self.ids[n] = str(int(pid))

    def resolve(self, name: str) -> Tuple[Optional[str], str]:
        """(Yahoo player id or None, how): "id" (his id, in the file),
        "id, no seasons" (his id, not in the file: no NBA season on record --
        a rookie; the id still finds his NBA draft pick),
        "name" (a unique name match), "unmatched" (no id and no unique name)."""
        pid = self.ids.get(name)
        if pid is not None:
            return pid, ("id" if pid in self.players else "id, no seasons")
        hit = self._idx.canonical(name)
        if hit is not None and len(self._names[hit]) == 1:
            return self._names[hit][0], "name"
        return None, "unmatched"

    def entry(self, name: str) -> Tuple[Optional[dict], str]:
        pid, how = self.resolve(name)
        return (self.players.get(pid) if pid is not None else None), how


def ids_from_rows(rows: Iterable[dict]) -> Dict[str, object]:
    """{player name: Yahoo id} from league-log rows that carry one."""
    out: Dict[str, object] = {}
    for r in rows:
        if r.get("player_id") is not None:
            out.setdefault(r["player_name"], r["player_id"])
    return out


class History:
    """What ratings.rate() reads for the archetype: the file, this league's stat
    values and who is who (Index). unmatched() lists the names asked for that
    the file could not place (the caller reports them)."""

    def __init__(self, blob: dict, values: Dict[str, float], ids: Optional[Dict[str, object]] = None):
        self.blob = blob
        self.values = dict(values)
        self.index = Index(blob, ids)
        self._unmatched: set = set()

    def entry(self, name: str) -> Tuple[Optional[dict], str]:
        e, how = self.index.entry(name)
        if how == "unmatched":
            self._unmatched.add(name)
        return e, how

    def per_game(self, name: str, season: str, weights: List[float]) -> Optional[dict]:
        e, _how = self.entry(name)
        return history_per_game(e, season, self.values, weights)

    def unmatched(self) -> List[str]:
        return sorted(self._unmatched)
