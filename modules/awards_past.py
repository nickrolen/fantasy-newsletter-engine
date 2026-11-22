"""awards_past.py -- past seasons' awards for the record book (4c6 part B;
claude/HANDOFF_4C6_MVP_ODDS_2026-11-19.md, 4C5_DECISIONS decision 17: "the 4
solid ones" -- MVP with wins swung, Trade of the Year, Most improved; 4c7,
claude/HANDOFF_4C7_AWARDS_EXTENSION_2026-11-22.md: the rest of the season's
awards -- Best pickup, Rookie of the Year, Bust of the Year -- plus Player of
the Week's seasons, the manager awards (modules/manager_awards) and the
all-time lists Records shows).

ONE DEFINITION: every number is modules/awards.compute's, on a past
season's inputs (season_inputs), asked for the awards the old data supports
(PAST). Through each season's OWN regular season (league_config
season_structure.<season>.regular_through: 21, 21, 19, 16, 20, 21, 21, 21,
21 weeks for 2017-18 .. 2025-26), the "title" of that season as weeks 1-15
are this season's. Playoff weeks never count; a season without a bracket
(2019-20, stopped after week 19) changes nothing: the awards are regular-
season awards.

WHAT DIFFERS FROM THIS SEASON, AND WHY (each said in the file's notes)
- WINS SWUNG are counted against the OFFICIAL weekly scores (all_matchups),
  not the log's started totals: the league log misses whole days in 2017-18
  (weeks 1, 3, 5, 6, 18, 20) and one in 2019-20 (week 17), and elsewhere
  differs by a few points of stat corrections. The definition's "his team's
  total" is the real total; his own started points come from the log.
- PAR on a missing day is not counted (no row): those seasons' PAR runs low
  for everyone who played those days. checks() measures it per season.
- MOST IMPROVED uses the league log's FPPG (his games on a league roster)
  for both sides, because there are no daily NBA lines before 2026-27. The
  "usual level" is the same P3 prior as this season's.
- TRADE OF THE YEAR: data/historical/all_trades.json; each side's players'
  PAR plus each draft pick it got at its round's expected PAR (H56 s.4.4,
  modules/draft_values: est.); a pick for a 2020 or earlier draft is listed,
  not valued.
- BEST PICKUP (4c7): no transaction log before 2026-27, so the adds are read
  off the daily rosters (awards._roster_adds): a stint that doesn't begin on
  opening day and isn't a trade arrival (all_trades.json, completed trades,
  within keeper_history's trade window). The drop is shown only when the
  rosters make it unambiguous.
- ROOKIE OF THE YEAR (4c7): a player's rookie season is his FIRST SEASON
  PLAYED in data/historical/NBA_SEASONS.json (every NBA season 2014-15 on,
  by Yahoo id, else a unique name). config/ROOKIE_SEASONS.json is checked
  against it; where they disagree NBA_SEASONS wins (it has every season's
  games; ROOKIE_SEASONS is a hand list), and the season's checks name each.
  A player first seen in 2014-15 is "2014-15 or earlier": never a rookie
  here. A started player the file cannot place leaves the award NOT
  COMPUTED (awards._rookies), never guessed.
- BUST OF THE YEAR (4c7; the reviewer's default, Nick to confirm): no
  preseason projection was stored before 2026-27, and the draft order is
  punted through 2023-24, so the expectation is HIS PREVIOUS NBA SEASON'S
  FPPG (NBA_SEASONS, this league's scoring; at least bust_min_games games
  in it, else no expectation). His actual is that season's whole NBA line
  (NBA_SEASONS: every NBA game, as this season's Bust uses every NBA game,
  so a dropped bust stays in the race; it is not cut at the league's
  regular season). Drafted or kept that season; 10+ games. 2018-19 has no
  draft list (H56), so no Bust.
- PLAYER OF THE WEEK (4c7): config/POTW_HISTORY.json, which starts in
  2025-26; weeks without points get them from the league log (hub_v2.league.
  potw_from_log, the newsletter's own measure). Per season: most wins, and
  the best single winning week.
- MANAGER AWARDS (4c7, modules/manager_awards): Lineup manager of the year,
  Draft of the year, Waiver king, Unluckiest season, on the same inputs.

data/historical/AWARDS_PAST.json is PUBLIC HISTORY (like DRAFT_OVR.json):
built on Nick's machine by scripts/build_awards_past.py, committed; the
runner never rebuilds it. write() refuses any path outside data/historical/.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from . import awards as A

ROOT = Path(__file__).resolve().parents[1]
FILE = Path("data") / "historical" / "AWARDS_PAST.json"
SCHEMA = 2
PAST = ("mvp", "trade", "improved", "pickup", "roy", "bust")
TOP = 5
ALLTIME_TOP = 10
NOT_BUILT: dict = {}
# Records' tiles: a season total of PAR is ranked PER REGULAR-SEASON WEEK
# (Nick, 11-19, for MVP: past regular seasons ran 16 to 21 weeks); one stint,
# a trade's gap, a shortfall and a rate are ranked as they are
PER_WEEK = ("mvp", "roy", "draft", "waiver")


class AwardsPastError(RuntimeError):
    pass


def seasons(cfg: Optional[dict] = None) -> list:
    """Every past season with a regular season on record (2017-18 on): the
    season_structure seasons with a regular_through, before this one."""
    from .data_loader import CURRENT_SEASON
    if cfg is None:
        from .data_loader import _LEAGUE_CONFIG as cfg
    ss = cfg.get("season_structure") or {}
    return sorted(s for s, v in ss.items() if not s.startswith("_") and isinstance(v, dict)
                  and v.get("regular_through") and s < CURRENT_SEASON)


def season_inputs(inputs, season: str, matchups: list, *, cfg: dict, lp, quantile: float, tie: float,
                  nba: Optional[dict] = None) -> dict:
    """awards.compute's inputs for a past season. Weeks come from the log's
    own days (each week's first and last logged day) with all_matchups'
    pairings; RAISES if a regular-season week is missing from either, or if
    two weeks overlap."""
    from .data_loader import PlayerIndex
    ss = (cfg.get("season_structure") or {}).get(season) or {}
    reg = ss.get("regular_through")
    if not reg:
        raise AwardsPastError(f"{season} has no regular_through in season_structure")
    rows = list(inputs.log.get(season) or [])
    if not rows:
        raise AwardsPastError(f"{season} has no rows in the league log")
    days_of: dict = {}
    for r in rows:
        days_of.setdefault(int(r["week"]), set()).add(r["date"])
    mu = [m for m in matchups if m["season"] == season]
    weeks, official = [], {}
    for w in sorted(days_of):
        ms = [m for m in mu if int(m["week"]) == w]
        weeks.append({"week": w, "start_date": min(days_of[w]), "end_date": max(days_of[w]),
                      "matchups": [{"manager_a": m["manager_a"], "manager_b": m["manager_b"]} for m in ms]})
        if w <= reg:
            for m in ms:
                official.setdefault(w, {})[m["manager_a"]] = float(m["score_a"])
                official[w][m["manager_b"]] = float(m["score_b"])
    miss_log = [w for w in range(1, reg + 1) if w not in days_of]
    miss_mu = [w for w in range(1, reg + 1) if w not in official]
    if miss_log or miss_mu:
        raise AwardsPastError(f"{season}: regular-season weeks missing from the log {miss_log} "
                              f"or from all_matchups {miss_mu}")
    for a, b in zip(weeks, weeks[1:]):
        if b["start_date"] <= a["end_date"]:
            raise AwardsPastError(f"{season}: weeks {a['week']} and {b['week']} overlap in the log")
    week_of = {d: w for w, ds in days_of.items() for d in ds}
    acfg = A.config(cfg)
    if nba is None:                                  # 4c7: Rookie of the Year and Bust read NBA_SEASONS
        nba = nba_context(ROOT, inputs)
    rookies, rcheck = rookie_seasons(nba, season, rows)
    return {"root": None, "season": season, "inputs": inputs, "rows": rows, "weeks": weeks, "reg": int(reg),
            "week_of": week_of, "days": sorted(week_of), "cfg": acfg, "quantile": float(quantile),
            "lp": lp, "transactions": [], "ledger": [], "rookies": rookies, "rookie_check": rcheck,
            "preseason": bust_expectation(nba, season, int(acfg["bust_min_games"]),
                                          inputs.picks.get(season) or [], rows),
            "preseason_rel": None, "pickups_from": "rosters",
            "actuals_first": None, "act_by_id": {}, "act_by_name": PlayerIndex(), "tie_value": float(tie),
            "fppg_source": "log", "official_totals": official}


# =============================================================================
# 4c7: NBA_SEASONS for Rookie of the Year and Bust
# =============================================================================

def nba_context(root=ROOT, inputs=None) -> dict:
    """NBA_SEASONS.json, this league's stat values, who is who (nba_prior.
    Index, with every Yahoo id the league log carries), the names the file's
    provenance could not match per season, and ROOKIE_SEASONS.json."""
    from . import nba_prior, nba_seasons
    root = Path(root)
    blob = json.loads((root / nba_seasons.RELPATH).read_text(encoding="utf-8"))
    ids = {}
    if inputs is not None:
        for rows in inputs.log.values():
            ids.update({k: v for k, v in nba_prior.ids_from_rows(rows).items() if k not in ids})
    unmatched: dict = {}
    for s, v in (blob.get("provenance") or {}).items():
        for u in v.get("unmatched") or []:
            unmatched.setdefault(u["name"], set()).add(s)
    return {"blob": blob, "values": nba_seasons.stat_values(root), "index": nba_prior.Index(blob, ids),
            "first": nba_seasons.FIRST_SEASON, "unmatched": unmatched,
            "rookie_file": json.loads((root / "config" / "ROOKIE_SEASONS.json").read_text(encoding="utf-8"))}


def _nba_entry(nba: dict, name: str, pid=None) -> Optional[dict]:
    if pid not in (None, ""):
        e = nba["blob"]["players"].get(str(int(pid)))
        if e is not None:
            return e
    e, _how = nba["index"].entry(name)
    return e


def rookie_season(nba: dict, name: str, pid=None) -> Optional[str]:
    """His first NBA season PLAYED (NBA_SEASONS), "<first> or earlier" when
    that is the file's first season, None when the file cannot place him.
    RAISES when his name is in an earlier season's unmatched list (that
    season could hide his real first one)."""
    e = _nba_entry(nba, name, pid)
    if e is None:
        return None
    played = sorted(s for s, x in (e.get("seasons") or {}).items() if int(x.get("gp") or 0) > 0)
    if not played:
        return None
    first = played[0]
    if first <= nba["first"]:
        return f"{nba['first']} or earlier"
    hid = sorted(s for s in nba["unmatched"].get(e["name"], ()) if s < first)
    if hid:
        raise AwardsPastError(f"{name}: first NBA season {first} in NBA_SEASONS, but the file could not match "
                              f"him in {hid}: his rookie season is not known")
    return first


def rookie_seasons(nba: dict, season: str, rows: list) -> tuple:
    """({log name: rookie season} for every player in the season's log the
    file can place, {"rookies": [...], "disagree": [...], "unplaced": [...]})."""
    from .data_loader import PlayerIndex
    rf = PlayerIndex(nba["rookie_file"])
    ids: dict = {}
    for r in rows:
        ids.setdefault(r["player_name"], r.get("player_id"))
    out, rookies, disagree, unplaced = {}, [], [], []
    for n, pid in sorted(ids.items()):
        s = rookie_season(nba, n, pid)
        if s is None:
            unplaced.append(n)
            continue
        out[n] = s
        if s == season:
            rookies.append(n)
        hit = rf.canonical(n)
        if hit is not None and (rf[hit] == season) != (s == season):
            disagree.append({"player": n, "nba_seasons": s, "rookie_seasons": rf[hit]})
    return out, {"rookies": rookies, "disagree": disagree, "unplaced": unplaced,
                 "rule": "NBA_SEASONS wins: the first season he played"}


def bust_expectation(nba: dict, season: str, need: int, picks: list, rows: list) -> dict:
    """awards._busts' expectation for a past season: his PREVIOUS NBA season's
    FPPG (NBA_SEASONS, this league's scoring), with at least `need` games in
    it; his actual: this season's NBA line (games, points)."""
    from . import nba_prior
    from .data_loader import PlayerIndex
    prev = nba_prior.season_label(nba_prior.season_year(season) - 1)
    values = nba["values"]

    cache: dict = {}

    def expect(n, pid=None):
        k = (n, pid)
        if k not in cache:
            e = _nba_entry(nba, n, pid)
            x = None if e is None else (e.get("seasons") or {}).get(prev)
            if e is None:
                cache[k] = (None, "not in NBA_SEASONS.json")
            elif x is None or int(x.get("gp") or 0) == 0:
                cache[k] = (None, f"no {prev} NBA season (a rookie, or a year out): no expectation")
            elif int(x["gp"]) < need:
                cache[k] = (None, f"{int(x['gp'])} NBA games in {prev} ({need} needed for an expectation)")
            else:
                cache[k] = (nba_prior.fppg_of(x, values), None)
        return cache[k]

    def actual(n, pid=None):
        e = _nba_entry(nba, n, pid)
        x = None if e is None else (e.get("seasons") or {}).get(season)
        if x is None or int(x.get("gp") or 0) == 0:
            return None, f"no {season} NBA games in NBA_SEASONS.json"
        return (int(x["gp"]), nba_prior.fppg_of(x, values) * int(x["gp"])), None

    def why(n, pid=None):
        return expect(n, pid)[1] or "no expectation"

    from . import keeper_history as kh
    by = PlayerIndex()                               # every drafted or kept player with an expectation
    names = kh.Names(rows)
    for p in picks:
        n = names.canon(p["player_name"], p.get("player_key")) or p["player_name"]
        v, _w = expect(n, p.get("player_key"))
        if v is not None:
            by[n] = v
    return {"kind": "previous season", "by_name": by, "file": "NBA_SEASONS.json", "fetched": None,
            "previous": prev, "actual": actual, "why": why, "missing_kind": "no expectation",
            "source": f"his {prev} NBA FPPG (data/historical/NBA_SEASONS.json, this league's scoring): no "
                      "preseason projection was stored before 2026-27"}


def checks(inp: dict) -> dict:
    """How far the log's started totals sit from the official scores, per
    regular-season team-week: {"team_weeks", "off", "max_off", "short_weeks",
    "flips"} (flips: results the log's totals would reverse)."""
    tot: dict = {}
    for r in inp["rows"]:
        if r["started"] and int(r["week"]) <= inp["reg"]:
            k = (int(r["week"]), r["manager"])
            tot[k] = tot.get(k, 0.0) + float(r["fantasy_points"])
    off, mx, short, flips, n = 0, 0.0, set(), 0, 0
    for w, sc in inp["official_totals"].items():
        for m, v in sc.items():
            n += 1
            d = round(tot.get((w, m), 0.0), 2) - v
            if abs(d) > 0.005:
                off += 1
            mx = max(mx, abs(d))
            if d < -15:
                short.add(w)
        wk = A._week(inp, w)
        for p in wk["matchups"]:
            a, b = p["manager_a"], p["manager_b"]
            real = (sc[a] > sc[b]) - (sc[a] < sc[b])
            la, lb = round(tot.get((w, a), 0.0), 2), round(tot.get((w, b), 0.0), 2)
            flips += real != ((la > lb) - (la < lb))
    return {"team_weeks": n, "off": off, "max_off": round(mx, 2), "short_weeks": sorted(short), "flips": flips}


def _row(a: dict, r: dict) -> dict:
    keep = {"label": r["label"], "player": r.get("player"), "m": r["m"], "value": round(float(r["value"]), 2),
            "shown": r["shown"], "sub": r["sub"]}
    if a == "mvp":
        keep.update(ms=r["ms"], swung=r["swung"], starts=r["starts"])
    elif a == "improved":
        keep.update(fppg=round(r["fppg"], 2), usual=round(r["usual"], 2), games=r["games"])
    elif a == "trade":
        keep.update(date=r["date"], sides={m: {"par": round(sd["par"], 2), "players_par": round(sd["players_par"], 2),
                                               "picks_est": round(sd["picks_est"], 2), "got": sd["got"],
                                               "picks": sd["picks"]}
                                           for m, sd in r["sides"].items()}, picks=r["picks"])
    elif a == "pickup":
        keep.update(add_day=r["add_day"], stint=list(r["stint"]), drops=list(r["drops"]))
    elif a == "roy":
        keep.update(ms=r["ms"])
    elif a == "bust":
        keep.update(expected=round(r["expected"], 2), fppg=round(r["fppg"], 2), games=r["games"])
    return keep


def _mrow(r: dict) -> dict:
    return {k: (round(v, 4) if isinstance(v, float) else v) for k, v in r.items()}


def _managers(rec: dict) -> dict:
    """The manager awards' season record: per award every manager's row and
    the winners (or why there are none)."""
    from . import manager_awards as MA
    out = {}
    for k in MA.KEYS:
        a = rec["awards"][k]
        rows = [_mrow(r) for r in a["rows"]]
        out[k] = {"winners": list(a["winners"]), "top": rows, "none": a["none"] if not rows else ""}
    return out


NONE = {"trade": "no regular-season trade", "improved": "no eligible player improved",
        "pickup": "no in-season pickup started", "roy": "no first-year NBA player started for a league team",
        "bust": "no drafted or kept player fell short of his expectation"}


def season_awards(inp: dict) -> dict:
    """One season's record: per award its winner and top TOP (or why it has
    none), R per week, the manager awards, the data checks, and (4c7) every
    pickup stint and every trade, for the all-time lists."""
    from . import manager_awards as MA
    end = str(A._week(inp, inp["reg"])["end_date"])[:10]
    res = A.compute(inp, end, only=PAST)
    if not res["final"]:
        raise AwardsPastError(f"{inp['season']}: the regular season is not final at {end}")
    out = {"season": inp["season"], "regular_weeks": inp["reg"], "through": end,
           "R": {str(w): round(v["R"], 3) for w, v in res["R"].items()}, "checks": checks(inp), "awards": {}}
    if inp.get("rookie_check") is not None:
        out["checks"]["rookies"] = inp["rookie_check"]
    # a pickup straight off another roster (within 3 days) with no recorded trade: counted as a pickup
    # (dropped, then added); listed so a trade missing from all_trades.json would show
    out["checks"]["pickups_off_rosters"] = sorted(res["awards"]["pickup"].get("off_rosters") or [],
                                                  key=lambda x: (x["day"], x["player"]))
    for k in PAST:
        a = res["awards"][k]
        if a["error"]:
            raise AwardsPastError(f"{inp['season']} {k}: {a['error']}")
        rows = [_row(k, r) for r in a["rows"][:TOP]]
        kinds: dict = {}
        for e in a["excluded"]:
            kinds[e["kind"]] = kinds.get(e["kind"], 0) + 1
        none = ""
        if not rows:
            first = inp["season"] == min(inp["inputs"].log)
            nodraft = k == "bust" and not inp["inputs"].picks.get(inp["season"])
            none = ("the first season in the league log: no earlier season to measure against"
                    if k == "improved" and first else
                    f"{inp['season']} has no draft list (H56): no drafted or kept player to judge" if nodraft else
                    NONE.get(k, "none"))
        out["awards"][k] = {"winner": rows[0] if rows else None, "top": rows, "none": none,
                            "excluded": kinds, "eligible": len(a["rows"])}
        if k == "bust":
            out["awards"][k]["source"] = a["source"]
    out["managers"] = _managers(MA.compute(inp, res))
    out["_all"] = {"pickup": [_row("pickup", r) for r in res["awards"]["pickup"].get("stints") or []],
                   "trade": [_row("trade", r) for r in res["awards"]["trade"]["rows"]]}
    return out


def alltime(blob: dict) -> dict:
    """Records' all-time lists (4c7 D: one measure per idea): the top
    ALLTIME_TOP pickup stints by PAR and trades by PAR gap, every past
    season, each entry carrying its season. Ties to the earlier season."""
    out = {}
    for k in ("pickup", "trade"):
        rows = [dict(r, season=s) for s, v in sorted(blob["seasons"].items()) for r in v["_all"][k]]
        rows.sort(key=lambda r: (-r["value"], r["season"], r["label"]))
        out[k] = rows[:ALLTIME_TOP]
    return out


def potw(root=ROOT, inputs=None, only_seasons: Optional[list] = None) -> dict:
    """Player of the Week by past season (4c7): {season: {"weeks", "most_wins":
    [{"player", "wins", "ms"}], "best_week": {"week", "player", "m", "total_fp",
    "games", "fppg", "from_log"}, "unrecorded": [weeks]}} from config/
    POTW_HISTORY.json (it starts in 2025-26), weeks without points filled from
    the league log (hub_v2.league.potw_from_log). This season is left out (it
    is not final)."""
    from .data_loader import CURRENT_SEASON
    from .hub_v2.league import potw_from_log
    hist = json.loads((Path(root) / "config" / "POTW_HISTORY.json").read_text(encoding="utf-8"))
    seasons = {s: v for s, v in (hist.get("seasons") or {}).items()
               if s < CURRENT_SEASON and (only_seasons is None or s in only_seasons)}
    fill = potw_from_log(seasons, inputs.log if inputs is not None else {})
    out = {}
    for s, entries in sorted(seasons.items()):
        wins: dict = {}
        best, unrec = None, []
        for e in sorted(entries, key=lambda x: int(x["week"])):
            for k in ("week", "player", "manager"):
                if e.get(k) is None:
                    raise AwardsPastError(f"POTW_HISTORY {s} lacks {k}: {e}")
            x = wins.setdefault(e["player"], {"player": e["player"], "wins": 0, "ms": []})
            x["wins"] += 1
            if e["manager"] not in x["ms"]:
                x["ms"].append(e["manager"])
            have = all(e.get(k) is not None for k in ("total_fp", "games", "fppg"))
            src = e if have else fill.get((s, int(e["week"])))
            if src is None:
                unrec.append(int(e["week"]))
                continue
            row = {"week": int(e["week"]), "player": e["player"], "m": e["manager"],
                   "total_fp": round(float(src["total_fp"]), 2), "games": int(src["games"]),
                   "fppg": round(float(src["fppg"]), 2), "from_log": not have}
            if best is None or row["total_fp"] > best["total_fp"]:
                best = row
        top = max((x["wins"] for x in wins.values()), default=0)
        out[s] = {"weeks": len(entries), "most_wins": sorted([x for x in wins.values() if x["wins"] == top],
                                                              key=lambda x: x["player"]),
                  "best_week": best, "unrecorded": unrec}
    return out


def build(root=ROOT, inputs=None, cfg: Optional[dict] = None, only_seasons: Optional[list] = None) -> dict:
    """The whole file's content. RAISES AwardsPastError (or awards' errors)."""
    from . import keeper_history as kh, keepability_v3 as M, ratings
    from .data_loader import regular_season_tie_value
    root = Path(root)
    if cfg is None:
        from .data_loader import _LEAGUE_CONFIG as cfg
    inputs = inputs or kh.Inputs.load(root)
    mat = json.loads((root / "data" / "historical" / "all_matchups.json").read_text(encoding="utf-8"))
    nba = nba_context(root, inputs)
    lp = M.level_config(M.load_params())
    from .awards import replacement_quantile
    q = replacement_quantile(cfg)
    tie = float(regular_season_tie_value())
    from . import manager_awards as MA
    out = {"schema": SCHEMA, "awards": list(PAST), "manager_awards": list(MA.KEYS), "not_built": NOT_BUILT,
           "seasons": {},
           "notes": {
               "measure": "Each award as defined in claude/AWARDS_DEFINITIONS_2026-11-14.md (modules/awards), "
                          "through each season's own regular season (season_structure regular_through).",
               "wins_swung": "Counted against the official weekly scores (all_matchups); his own started points "
                             "from the league log.",
               "missing_days": "The league log misses whole days in some weeks (checks.short_weeks): no PAR is "
                               "counted on them.",
               "most_improved": "League-log FPPG (games on a league roster) for this season and the usual level; "
                                "there are no daily NBA lines before 2026-27.",
               "trades": "data/historical/all_trades.json; each side's players' PAR plus each draft pick it got "
                         "at the average PAR of players taken in that round (est.; data/historical/"
                         "DRAFT_ROUND_VALUES.json); picks for a 2020 or earlier draft listed, not valued.",
               "pickups": "No transaction log before 2026-27: a pickup is a stint on a roster that doesn't begin "
                          "on opening day and isn't a trade arrival (all_trades.json, completed trades); the add "
                          "day is its first logged day. The drop shows only when the daily rosters make it "
                          "unambiguous (one arrival and one departure that day).",
               "rookies": "His first NBA season played in data/historical/NBA_SEASONS.json; config/"
                          "ROOKIE_SEASONS.json is checked against it and NBA_SEASONS wins where they disagree "
                          "(checks.rookies.disagree).",
               "bust": "The expectation is his previous NBA season's FPPG (NBA_SEASONS, 10+ games in it): no "
                       "preseason projection was stored before 2026-27, and the pick order is punted through "
                       "2023-24. His actual is that season's whole NBA line. 2018-19 has no draft list.",
               "potw_seasons": "Player of the Week history starts in 2025-26 (config/POTW_HISTORY.json); weeks without "
                       "points take them from the league log.",
               "managers": "modules/manager_awards: Lineup manager of the year (fill rate), Draft of the year "
                           "(drafted players' PAR, keepers apart), Waiver king (all pickups' PAR), Unluckiest "
                           "season (losses in weeks above the league median). Regular season only.",
               "best": "Records' tiles: a season's PAR total (MVP, Rookie of the Year, Draft of the year, Waiver "
                       "king) is ranked per regular-season week; the rest by their own measure."}}
    for s in (only_seasons or seasons(cfg)):
        inp = season_inputs(inputs, s, mat, cfg=cfg, lp=lp, quantile=q, tie=tie, nba=nba)
        out["seasons"][s] = season_awards(inp)
    out["potw_seasons"] = potw(root, inputs, only_seasons)
    out["alltime"] = alltime(out)
    for v in out["seasons"].values():
        v.pop("_all")
    out["best"] = best(out)
    validate(out)
    return out


BEST_KEYS = PAST + ("lineup", "draft", "waiver", "unlucky", "potw_wins", "potw_week")


def best(blob: dict) -> dict:
    """Each award's all-time best season (the Records tiles): the winner with
    the largest measure; ties to the earlier season. A season total of PAR
    (PER_WEEK: MVP, Nick 11-19; and, 4c7, Rookie of the Year, Draft of the
    year, Waiver king) ranks PER REGULAR-SEASON WEEK (past regular seasons
    ran 16 to 21 weeks, so a total favours the long ones); its entry carries
    "per_week". Unluckiest breaks a tie on losses by points against. Player
    of the Week: the most wins in one season, and the best winning week."""
    from . import manager_awards as MA
    out = {}

    def pick(cand, k, tb=lambda w: 0):
        if not cand:
            return None

        def measure(x):
            return x[1]["value"] / blob["seasons"][x[0]]["regular_weeks"] if k in PER_WEEK else x[1]["value"]
        s, w = max(cand, key=lambda x: (round(measure(x), 6), tb(x[1]), [-ord(c) for c in x[0]]))
        b = {"season": s, **w, "regular_weeks": blob["seasons"][s]["regular_weeks"]}
        if k in PER_WEEK:
            b["per_week"] = round(w["value"] / blob["seasons"][s]["regular_weeks"], 3)
        return b
    for k in PAST:
        out[k] = pick([(s, v["awards"][k]["winner"]) for s, v in sorted(blob["seasons"].items())
                       if v["awards"][k]["winner"] is not None], k)
    for k in MA.KEYS:
        out[k] = pick([(s, v["managers"][k]["top"][0]) for s, v in sorted(blob["seasons"].items())
                       if v["managers"][k]["top"]], k, (lambda w: w.get("pa", 0)) if k == "unlucky" else
                      (lambda w: 0))
    pw = blob.get("potw_seasons") or {}
    c = [(s, x) for s, v in sorted(pw.items()) for x in v["most_wins"]]
    out["potw_wins"] = (None if not c else
                        dict(max(c, key=lambda t: (t[1]["wins"], [-ord(ch) for ch in t[0]]))[1],
                             season=max(c, key=lambda t: (t[1]["wins"], [-ord(ch) for ch in t[0]]))[0]))
    c = [(s, v["best_week"]) for s, v in sorted(pw.items()) if v.get("best_week")]
    out["potw_week"] = (None if not c else
                        dict(max(c, key=lambda t: (t[1]["total_fp"], [-ord(ch) for ch in t[0]]))[1],
                             season=max(c, key=lambda t: (t[1]["total_fp"], [-ord(ch) for ch in t[0]]))[0]))
    return out


def validate(blob: dict) -> None:
    """The file's schema. RAISES AwardsPastError naming the first problem."""
    def need(cond, what):
        if not cond:
            raise AwardsPastError(f"AWARDS_PAST: {what}")
    from . import manager_awards as MA
    need(blob.get("schema") == SCHEMA, f"schema must be {SCHEMA}")
    need(blob.get("awards") == list(PAST), f"awards must be {list(PAST)}")
    need(blob.get("manager_awards") == list(MA.KEYS), f"manager_awards must be {list(MA.KEYS)}")
    need(isinstance(blob.get("seasons"), dict) and blob["seasons"], "no seasons")
    for s, v in blob["seasons"].items():
        need(v.get("season") == s, f"{s}: season key")
        need(isinstance(v.get("regular_weeks"), int) and v["regular_weeks"] > 0, f"{s}: regular_weeks")
        for k in PAST:
            a = (v.get("awards") or {}).get(k)
            need(isinstance(a, dict), f"{s}: no {k}")
            need((a["winner"] is None) == (not a["top"]), f"{s} {k}: winner and top disagree")
            need(a["winner"] is not None or a["none"], f"{s} {k}: no winner and no reason")
            for r in a["top"]:
                for f in ("label", "m", "value", "shown"):
                    need(f in r, f"{s} {k}: a row lacks {f}")
            vals = [r["value"] for r in a["top"]]
            need(vals == sorted(vals, reverse=True), f"{s} {k}: top is not in order")
        for k in MA.KEYS:
            a = (v.get("managers") or {}).get(k)
            need(isinstance(a, dict), f"{s}: no manager award {k}")
            need(bool(a["top"]) == bool(a["winners"]), f"{s} {k}: winners and rows disagree")
            need(a["top"] or a["none"], f"{s} {k}: no rows and no reason")
            for r in a["top"]:
                for f in ("m", "value", "shown", "sub", "rank"):
                    need(f in r, f"{s} {k}: a row lacks {f}")
            vals = [r["value"] for r in a["top"]]
            need(vals == sorted(vals, reverse=True), f"{s} {k}: rows are not in order")
    need(isinstance(blob.get("potw_seasons"), dict), "no potw_seasons")
    need(set((blob.get("alltime") or {})) == {"pickup", "trade"}, "alltime must hold pickup and trade")
    for k, rows in blob["alltime"].items():
        need(len(rows) <= ALLTIME_TOP and all("season" in r for r in rows), f"alltime {k}: rows")
        need([r["value"] for r in rows] == sorted((r["value"] for r in rows), reverse=True),
             f"alltime {k}: not in order")
    need(set(blob.get("best") or {}) == set(BEST_KEYS), "best must name every award")


def write(blob: dict, path, root=ROOT) -> Path:
    """Write the file. REFUSES any path outside <root>/data/historical/."""
    root = Path(root).resolve()
    p = Path(path)
    p = (p if p.is_absolute() else root / p).resolve()
    allowed = (root / "data" / "historical").resolve()
    if allowed not in p.parents:
        raise AwardsPastError(f"refused: {p} is not inside {allowed} (AWARDS_PAST is public history)")
    validate(blob)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(blob, indent=1, ensure_ascii=True, sort_keys=False) + "\n", encoding="utf-8")
    return p


def load(root=ROOT) -> Optional[dict]:
    """The committed file, validated; None when it is not built yet."""
    p = Path(root) / FILE
    if not p.is_file():
        return None
    blob = json.loads(p.read_text(encoding="utf-8"))
    validate(blob)
    return blob
