"""trophy_case.py -- one trophy case per manager (4c7 B; claude/HANDOFF_4C7_
AWARDS_EXTENSION_2026-11-22.md). THE ONE FUNCTION the hub's History >
All-time and item 17's manager card both call: build().

WHAT IT COUNTS (finished seasons only; this season joins at its reset)
- TITLES, by LEAGUE_RULES' "Who the champion is":
  - LEAGUE CHAMPIONSHIPS: the League Champion, first in the regular season
    (season_outcomes.league_champion over data/historical/all_standings.json,
    plus config pre_data_era.seasons' league_champion for 2014-15 and
    2016-17). These are "titles": LEAGUEHISTORY.xlsx titles_won.
  - PLAYOFF TITLES: the bracket's winner (season_outcomes.playoff_champion;
    2019-20 had no bracket) plus pre_data_era's playoff_champion.
    LEAGUEHISTORY playoff_championships.
  - CUPS: keeper_rules.cup_winners (from 2026-27; none played yet).
- AWARDS HIS PLAYERS WON FOR HIM (data/historical/AWARDS_PAST.json,
  2017-18 on), credited to:
  - MVP and Rookie of the Year: the manager he scored the most PAR for that
    season (a traded player's first team in "ms");
  - Best pickup: the manager who added him;
  - Trade of the Year: the manager who won the trade;
  - Most improved: the manager he finished the season with.
- MANAGER AWARDS (modules/manager_awards): Lineup manager of the year, Draft
  of the year, Waiver king; co-winners (a tie at the top) each get one.
- APART, never added to the honours: BUST OF THE YEAR (his drafted or kept
  player fell furthest short) and the UNLUCKIEST SEASON. They are counted in
  their own fields ("busts", "unlucky"), and the hub prints them muted.

Every count carries its seasons (who, when), so a tap can show them.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[1]
TITLES = ("league", "playoff", "cup")
PLAYER_AWARDS = ("mvp", "pickup", "roy", "trade", "improved")
MANAGER_AWARDS = ("lineup", "draft", "waiver")
APART = ("bust", "unlucky")
ORDER = TITLES + PLAYER_AWARDS + MANAGER_AWARDS + APART
LABELS = {"league": "League Championships", "playoff": "Playoff titles", "cup": "Cups", "mvp": "MVPs",
          "pickup": "Best pickups", "roy": "Rookies of the Year", "trade": "Trades of the Year",
          "improved": "Most improved", "lineup": "Lineup manager", "draft": "Draft of the year",
          "waiver": "Waiver king", "bust": "Busts of the Year", "unlucky": "Unluckiest seasons"}


class TrophyCaseError(RuntimeError):
    pass


def _credit_player(k: str, w: dict) -> str:
    if k in ("mvp", "roy"):
        ms = w.get("ms") or [w["m"]]
        return ms[0]
    return w["m"]


def build(root=ROOT, *, past: Optional[dict] = None, standings: Optional[list] = None,
          cfg: Optional[dict] = None, managers: Optional[list] = None) -> dict:
    """{"managers": [{"m", "counts": {key: n}, "items": {key: [{"season",
    "what"}]}}] (League Championships, then playoff titles, then name),
    "seasons": the seasons the awards cover, "cup_from", "error": None}.
    past: AWARDS_PAST.json's blob (awards_past.load when None); standings:
    all_standings.json's rows; cfg: league_config. RAISES TrophyCaseError on
    a season whose champion cannot be named."""
    from . import season_outcomes as SO
    root = Path(root)
    if cfg is None:
        from .data_loader import _LEAGUE_CONFIG as cfg
    if managers is None:
        managers = list(cfg["managers"])
    if standings is None:
        standings = json.loads((root / "data" / "historical" / "all_standings.json").read_text(encoding="utf-8"))
    if past is None:
        from . import awards_past
        past = awards_past.load(root)
    items = {m: {k: [] for k in ORDER} for m in managers}

    def add(m, k, season, what):
        if m not in items:
            raise TrophyCaseError(f"{season} {LABELS[k]}: {m} is not one of the managers {managers}")
        items[m][k].append({"season": season, "what": what})
    by: dict = {}
    for r in standings:
        by.setdefault(r["season"], []).append(r)
    for s, rs in sorted(by.items()):
        lc = SO.league_champion(rs)
        if not lc:
            raise TrophyCaseError(f"{s}: no League Champion in all_standings")
        add(lc, "league", s, "")
        pc = SO.playoff_champion(rs)
        if pc:
            add(pc, "playoff", s, "")
    pre = ((cfg.get("pre_data_era") or {}).get("seasons")) or {}
    for s, v in sorted(pre.items()):
        if s.startswith("_"):
            continue
        add(v["league_champion"], "league", s, "(standings and brackets only)")
        add(v["playoff_champion"], "playoff", s, "(standings and brackets only)")
    for s, m in sorted(((cfg.get("keeper_rules") or {}).get("cup_winners") or {}).items()):
        if not s.startswith("_") and m:
            add(m, "cup", s, "")
    seasons = []
    if past is not None:
        seasons = sorted(past["seasons"])
        for s in seasons:
            v = past["seasons"][s]
            for k in PLAYER_AWARDS + ("bust",):
                w = v["awards"][k]["winner"]
                if w is not None:
                    add(_credit_player(k, w), k, s, w["label"])
            for k in MANAGER_AWARDS + ("unlucky",):
                for m in v["managers"][k]["winners"]:
                    top = v["managers"][k]["top"][0]
                    add(m, k, s, top["shown"])
    for m in managers:
        for k in ORDER:
            items[m][k].sort(key=lambda x: x["season"])
    rows = [{"m": m, "counts": {k: len(items[m][k]) for k in ORDER}, "items": items[m]} for m in managers]
    rows.sort(key=lambda r: (-r["counts"]["league"], -r["counts"]["playoff"], managers.index(r["m"])))
    return {"managers": rows, "seasons": seasons, "order": list(ORDER), "labels": dict(LABELS),
            "apart": list(APART), "awards_from": seasons[0] if seasons else None,
            "awards_to": seasons[-1] if seasons else None}
