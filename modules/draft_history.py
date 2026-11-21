"""The league's past drafts, read one way (H56, Nick 11-20).

Yahoo's draft record (data/historical/all_drafts.json) is right about WHO
drafted and kept WHOM (verified 11-20: every drafted player is on his
drafter's opening-day roster from 2021-22, 49-52 of 52 before that; all 120
keepers 2021-22 to 2025-26 were on the same manager's roster on the last day
of the previous season). Its pick ORDER for 2017-18 to 2023-24 is not: the
league remembers Garrett taking Wembanyama first overall in 2023, Yahoo lists
him 3.02, and the league's memories conflict with each other too. So:

- order trusted:  config draft_history.order_trusted_from (2024-25) and every
                  later season, the current one included;
- order punted:   every earlier season. Its pick numbers and rounds are never
                  shown and never used: the picks come back with pick_number
                  and round set to None;
- dropped:        draft_history.drafts_dropped (2018-19), whose list does not
                  match the opening rosters at all. No picks at all: None.

all_drafts.json is NOT edited; it stays Yahoo's record and this module applies
the rule. Every reader goes through here (tests/test_h56_draft_order.py greps
for any other module or script that opens all_drafts.json to read it; the
writers -- pull_historical_data, pull_current_draft, rollup_season_to_history,
backfill_draft_names -- are listed there by name).

Live rounds by draft (LEAGUE_RULES "Drafts and keepers by season") are here
too, from config: draft_history.live_rounds and live_rounds_default.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional

from .data_loader import KEEPER_ERA_START, league_rule

ROOT = Path(__file__).resolve().parents[1]
DRAFTS_FILE = Path("data") / "historical" / "all_drafts.json"
CURRENT_FILE = Path("config") / "DRAFT_PICKS_CURRENT.json"

PUNTED_NOTE = "Yahoo's pick order for this season isn't reliable, so picks are shown by team."
DROPPED_NOTE = "This draft's record doesn't match the opening rosters; it isn't shown."
_SEASON = re.compile(r"(\d{4})-(\d{2})")


class DraftHistoryError(ValueError):
    """The draft-history rule is missing, malformed, or asked something it cannot answer."""


def _season(season) -> str:
    s = str(season)
    m = _SEASON.fullmatch(s)
    if not m or (int(m.group(1)) + 1) % 100 != int(m.group(2)):
        raise DraftHistoryError(f"{season!r} is not a season like '2024-25'")
    return s


def rules(config: Optional[dict] = None) -> dict:
    """The draft_history block, validated. Missing keys raise (never defaulted)."""
    if config is None:
        node = {k: league_rule("draft_history", k) for k in
                ("order_trusted_from", "drafts_dropped", "live_rounds", "live_rounds_default")}
    else:
        node = config.get("draft_history")
        if not isinstance(node, dict):
            raise DraftHistoryError("league_config.json has no draft_history block (H56)")
        missing = [k for k in ("order_trusted_from", "drafts_dropped", "live_rounds", "live_rounds_default")
                   if k not in node]
        if missing:
            raise DraftHistoryError(f"draft_history lacks {missing}: add the rule; it is never defaulted")
    _season(node["order_trusted_from"])
    if not isinstance(node["drafts_dropped"], list):
        raise DraftHistoryError("draft_history.drafts_dropped must be a list of seasons")
    for s in node["drafts_dropped"]:
        _season(s)
    for s, n in node["live_rounds"].items():
        _season(s)
        if not isinstance(n, int) or n < 1:
            raise DraftHistoryError(f"draft_history.live_rounds[{s}] = {n!r} is not a round count")
    d = node["live_rounds_default"]
    for k in ("from", "rounds", "last_round_picks"):
        if k not in d:
            raise DraftHistoryError(f"draft_history.live_rounds_default lacks {k}")
    _season(d["from"])
    return node


def order_trusted(season, config: Optional[dict] = None) -> bool:
    """True when Yahoo's pick order for `season`'s draft is used (2024-25 on)."""
    r = rules(config)
    s = _season(season)
    return s >= r["order_trusted_from"] and s not in r["drafts_dropped"]


def dropped(season, config: Optional[dict] = None) -> bool:
    """True when `season`'s draft list is not used at all (2018-19)."""
    return _season(season) in rules(config)["drafts_dropped"]


def apply_rule(rows: list, config: Optional[dict] = None) -> list:
    """Yahoo's draft rows with the rule applied: dropped seasons removed, and a
    punted season's pick_number and round set to None (copies; the input is
    not changed). Row order within a punted season is by manager then name, so
    nothing downstream can recover Yahoo's order from position either."""
    r = rules(config)
    out, punted = [], {}
    for p in rows:
        s = _season(p.get("season"))
        if s in r["drafts_dropped"]:
            continue
        if s >= r["order_trusted_from"]:
            out.append(dict(p))
        else:
            punted.setdefault(s, []).append({**p, "pick_number": None, "round": None})
    for s, ps in punted.items():
        out.extend(sorted(ps, key=lambda p: (p.get("manager") or "", p.get("player_name") or "")))
    out.sort(key=lambda p: (p["season"], p["pick_number"] is None,
                            p["pick_number"] if p["pick_number"] is not None else 0))
    return out


def read(root=ROOT, config: Optional[dict] = None) -> list:
    """Every past season's picks from all_drafts.json, the rule applied.
    Raises if the file is missing (a reader that can live without it catches)."""
    return read_path(Path(root) / DRAFTS_FILE, config)


def read_in(historical_dir, config: Optional[dict] = None, missing_ok: bool = False) -> list:
    """read() for a caller that holds the data/historical directory (the
    player cards). missing_ok: [] when the file is absent."""
    path = Path(historical_dir) / DRAFTS_FILE.name
    if missing_ok and not path.is_file():
        return []
    return read_path(path, config)


def read_path(path, config: Optional[dict] = None) -> list:
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"{path} is missing")
    rows = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(rows, list):
        raise DraftHistoryError(f"{path} is not a list of picks")
    return apply_rule(rows, config)


def opening_day_stand_ins(log_rows: list, config: Optional[dict] = None) -> list:
    """For each DROPPED season (2018-19) with rows in the league log: every
    manager's roster on the season's first logged day, as draft-day rows
    (is_keeper False -- 2018-19 had no keepers -- no pick number, no round,
    source "opening_day_roster"). The handoff's "keep only the opening-day
    rosters' picture": for the lore's draft-day loyalty counts, never for
    anything about the draft itself."""
    drop = set(rules(config)["drafts_dropped"])
    first: dict = {}
    for r in log_rows:
        s = r.get("season_key")
        if s in drop and (s not in first or r["date"] < first[s]):
            first[s] = r["date"]
    seen, out = set(), []
    for r in log_rows:
        s = r.get("season_key")
        if s in first and r["date"] == first[s] and (s, r["manager"], r["player_name"]) not in seen:
            seen.add((s, r["manager"], r["player_name"]))
            out.append({"season": s, "pick_number": None, "round": None, "manager": r["manager"],
                        "player_key": None if r.get("player_id") is None else str(r["player_id"]),
                        "player_name": r["player_name"], "is_keeper": False,
                        "source": "opening_day_roster"})
    return sorted(out, key=lambda p: (p["season"], p["manager"], p["player_name"]))


def by_season(rows: list) -> dict:
    out: dict = {}
    for p in rows:
        out.setdefault(p["season"], []).append(p)
    return out


def order(season, rows: list, config: Optional[dict] = None) -> Optional[list]:
    """`season`'s picks in draft order, or None when its order is punted or
    its draft dropped. `rows` are apply_rule()'s (or read()'s) output."""
    if not order_trusted(season, config):
        return None
    ps = [p for p in rows if p.get("season") == season]
    if any(p.get("pick_number") is None for p in ps):
        raise DraftHistoryError(f"{season}: a trusted season's pick lacks its pick number")
    return sorted(ps, key=lambda p: int(p["pick_number"]))


def with_slots(ordered: list) -> list:
    """A trusted season's ordered picks (order()'s output) with "slot" set:
    "2.03" = round 2, third pick of that round, counted within each round."""
    seen: dict = {}
    out = []
    for p in ordered:
        rd = int(p["round"])
        seen[rd] = seen.get(rd, 0) + 1
        out.append({**p, "slot": f"{rd}.{seen[rd]:02d}"})
    return out


# ---------------------------------------------------------------------------
# live rounds by draft (LEAGUE_RULES "Drafts and keepers by season")
# ---------------------------------------------------------------------------

def keeper_era(draft_season) -> bool:
    """True for a draft from 2021-22 on: straight order, keepers out of the pool."""
    return _season(draft_season) >= KEEPER_ERA_START


def live_rounds(draft_season, config: Optional[dict] = None) -> int:
    """How many rounds of `draft_season`'s draft are live (players drafted):
    7 for 2021-22 to 2025-26, 9 for 2026-27, 10 from 2027-28. Raises for a
    snake draft before the keeper era (every round was live and the picks are
    never valued) and for a keeper-era season the config does not state."""
    s = _season(draft_season)
    if not keeper_era(s):
        raise DraftHistoryError(f"{s} was a snake draft with no keepers: it has no live-round count "
                                "(its picks are listed, never valued)")
    r = rules(config)
    if s in r["live_rounds"]:
        return int(r["live_rounds"][s])
    d = r["live_rounds_default"]
    if s >= d["from"]:
        return int(d["rounds"])
    raise DraftHistoryError(f"draft_history.live_rounds does not state {s}")


def picks_in_round(draft_season, rnd: int, teams: int, config: Optional[dict] = None) -> int:
    """How many picks a live round holds: every team's, except the last live
    round from 2027-28 on, which holds live_rounds_default.last_round_picks
    (the Cup winner's 6th keeper takes his)."""
    n = live_rounds(draft_season, config)
    if not 1 <= int(rnd) <= n:
        raise DraftHistoryError(f"round {rnd} is not a live round of the {draft_season} draft ({n} live)")
    d = rules(config)["live_rounds_default"]
    if _season(draft_season) >= d["from"] and int(rnd) == n:
        return int(d["last_round_picks"])
    return int(teams)
