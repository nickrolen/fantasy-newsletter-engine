"""awards_past.py -- past seasons' awards for the record book (4c6 part B;
claude/HANDOFF_4C6_MVP_ODDS_2026-11-19.md, 4C5_DECISIONS decision 17: "the 4
solid ones" -- MVP with wins swung, Trade of the Year, Most improved).

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
- NOT BUILT (the old data cannot support them): Best pickup (no transaction
  log before 2026-27: no add dates, no drops), Rookie of the Year
  (ROOKIE_SEASONS is thin after 2022-23), Bust (no stored preseason
  projections). NOT_BUILT says so in the file.

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
SCHEMA = 1
PAST = ("mvp", "trade", "improved")
TOP = 5
NOT_BUILT = {
    "pickup": "no transaction log before 2026-27: no add dates and no drops",
    "roy": "config/ROOKIE_SEASONS.json is too thin after 2022-23 to name every season's rookies",
    "bust": "no preseason projection was stored before 2026-27",
}


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


def season_inputs(inputs, season: str, matchups: list, *, cfg: dict, lp, quantile: float, tie: float) -> dict:
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
    return {"root": None, "season": season, "inputs": inputs, "rows": rows, "weeks": weeks, "reg": int(reg),
            "week_of": week_of, "days": sorted(week_of), "cfg": A.config(cfg), "quantile": float(quantile),
            "lp": lp, "transactions": [], "ledger": [], "rookies": {}, "preseason": None, "preseason_rel": None,
            "actuals_first": None, "act_by_id": {}, "act_by_name": PlayerIndex(), "tie_value": float(tie),
            "fppg_source": "log", "official_totals": official}


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
    return keep


def season_awards(inp: dict) -> dict:
    """One season's record: per award its winner and top TOP (or why it has
    none), R per week, and the data checks."""
    end = str(A._week(inp, inp["reg"])["end_date"])[:10]
    res = A.compute(inp, end, only=PAST)
    if not res["final"]:
        raise AwardsPastError(f"{inp['season']}: the regular season is not final at {end}")
    out = {"season": inp["season"], "regular_weeks": inp["reg"], "through": end,
           "R": {str(w): round(v["R"], 3) for w, v in res["R"].items()}, "checks": checks(inp), "awards": {}}
    for k in PAST:
        a = res["awards"][k]
        rows = [_row(k, r) for r in a["rows"][:TOP]]
        kinds: dict = {}
        for e in a["excluded"]:
            kinds[e["kind"]] = kinds.get(e["kind"], 0) + 1
        none = ""
        if not rows:
            first = inp["season"] == min(inp["inputs"].log)
            none = ("the first season in the league log: no earlier season to measure against"
                    if k == "improved" and first else
                    {"trade": "no regular-season trade", "improved": "no eligible player improved"}.get(k, "none"))
        out["awards"][k] = {"winner": rows[0] if rows else None, "top": rows, "none": none,
                            "excluded": kinds, "eligible": len(a["rows"])}
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
    lp = M.level_config(M.load_params())
    from .awards import replacement_quantile
    q = replacement_quantile(cfg)
    tie = float(regular_season_tie_value())
    out = {"schema": SCHEMA, "awards": list(PAST), "not_built": NOT_BUILT, "seasons": {},
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
                         "DRAFT_ROUND_VALUES.json); picks for a 2020 or earlier draft listed, not valued."}}
    for s in (only_seasons or seasons(cfg)):
        inp = season_inputs(inputs, s, mat, cfg=cfg, lp=lp, quantile=q, tie=tie)
        out["seasons"][s] = season_awards(inp)
    out["best"] = best(out)
    validate(out)
    return out


def best(blob: dict) -> dict:
    """Each award's all-time best season (the Records tiles): the winner with
    the largest measure; ties to the earlier season. MVP ranks by PAR PER
    REGULAR-SEASON WEEK (Nick, 11-19: past regular seasons ran 16 to 21
    weeks, so a total favours the long ones); its entry carries "per_week"."""
    out = {}
    for k in PAST:
        cand = [(s, v["awards"][k]["winner"]) for s, v in sorted(blob["seasons"].items())
                if v["awards"][k]["winner"] is not None]
        if cand:
            def measure(x):
                return x[1]["value"] / blob["seasons"][x[0]]["regular_weeks"] if k == "mvp" else x[1]["value"]
            s, w = max(cand, key=lambda x: (measure(x), [-ord(c) for c in x[0]]))
            out[k] = {"season": s, **w, "regular_weeks": blob["seasons"][s]["regular_weeks"]}
            if k == "mvp":
                out[k]["per_week"] = round(w["value"] / blob["seasons"][s]["regular_weeks"], 3)
        else:
            out[k] = None
    return out


def validate(blob: dict) -> None:
    """The file's schema. RAISES AwardsPastError naming the first problem."""
    def need(cond, what):
        if not cond:
            raise AwardsPastError(f"AWARDS_PAST: {what}")
    need(blob.get("schema") == SCHEMA, f"schema must be {SCHEMA}")
    need(blob.get("awards") == list(PAST), f"awards must be {list(PAST)}")
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
    need(set(blob.get("best") or {}) == set(PAST), "best must name every award")


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
