"""mvp_odds.py -- the MVP race's odds (4c6; claude/HANDOFF_4C6_MVP_ODDS_2026-11-19.md,
claude/AWARDS_DEFINITIONS_2026-11-14.md "The awards races" part 3).

THE QUESTION: each player's chance to finish the regular season (weeks
1..R) with the most PAR -- modules/awards' MVP measure, unchanged.

THE MEASURE
- BANKED: his PAR through the live log's last day, exactly as
  awards.compute has it (res["awards"]["mvp"]["rows"]).
- SIMULATED: plus his PAR in every simulated STARTED game of the regular
  season's remaining days, from THE TITLE ODDS' OWN PASS
  (season_sim.run_season(mvp=True)): the same seed, availability, lineups,
  rosters and known moves. The tally is read off the arrays the team scores
  are summed from (simulator_betting.simulate_week_matrix's `started`), so
  the title odds are bit-identical with it on. A player's points are his
  game points; the team noise is a team-level term and belongs to no player.
- THE FUTURE REPLACEMENT LEVEL is unknown. It is held at the CURRENT R (the
  last R awards.compute has: the week in progress, or the last finished
  week) for every remaining game: league_config awards.mvp_odds.
  future_replacement = "current". "season_mean" (the mean of the weeks' R
  so far) is the alternative; sensitivity() prices both on the same pass.
- ODDS: the share of simulations in which he has the most PAR. A tie at the
  top splits that simulation evenly among the tied.
- NOBODY IS LEFT OUT: every player with banked PAR or a simulated start is
  in every simulation (a player the pass does not roster holds his banked
  PAR), so the odds over everyone sum to 1 and "everyone else" is exactly
  the rest. The file keeps the contenders (the top contenders_n by banked
  PAR, plus anyone at store_min or more); the page prints its five rows'
  odds and anyone else at show_min or more.
- STAND-INS (the roster plan's replacement-level pickups) are not players
  and are never in the race.

THE FILE: output/mvp_odds.json (STATE; config/STATE_MANIFEST.json), written
by the NIGHTLY run only (nightly._mvp_record), right after its title odds;
read by every hub build (hub_state.awards_step). Its day is printed with
the odds. The weekly awards history line (modules/awards) carries the odds
(attach) only when the odds were priced on that week's last day: there is
no backfill, so the odds' history starts with the first such week.
"""
from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

import numpy as np

FILE = Path("output") / "mvp_odds.json"
SCHEMA = 1
RULES = ("current", "season_mean")
CFG_KEYS = ("future_replacement", "contenders_n", "store_min", "show_min")
INFO = ("The chance he finishes the regular season with the most PAR, from the same simulation as the "
        "title odds.")


class MvpOddsError(RuntimeError):
    pass


def config(cfg: Optional[dict] = None) -> dict:
    """league_config awards.mvp_odds. A missing key RAISES (never defaulted)."""
    if cfg is None:
        from .data_loader import _LEAGUE_CONFIG as cfg
    m = ((cfg or {}).get("awards") or {}).get("mvp_odds")
    if not isinstance(m, dict):
        raise MvpOddsError("league_config awards has no \"mvp_odds\" block")
    miss = [k for k in CFG_KEYS if k not in m]
    if miss:
        raise MvpOddsError(f"league_config awards.mvp_odds is missing {miss}")
    if m["future_replacement"] not in RULES:
        raise MvpOddsError(f"awards.mvp_odds.future_replacement must be one of {RULES}")
    if not (0 < float(m["store_min"]) <= float(m["show_min"]) < 1) or int(m["contenders_n"]) < 1:
        raise MvpOddsError("awards.mvp_odds: need 0 < store_min <= show_min < 1 and contenders_n >= 1")
    return m


# =============================================================================
# the core (pure)
# =============================================================================

def odds(banked: dict, sim: dict, R: float, n: int) -> dict:
    """{player: P(most PAR at the end)} over n simulations.

    banked: {player: PAR so far}; sim: {player: (points[n], games[n])}, his
    simulated started points and games still to come. A player in banked
    only holds his PAR; a player in sim only starts from 0. A tie at the top
    splits the simulation evenly. The values sum to 1 (over every player
    with any chance; the rest are 0 and left out)."""
    keys = sorted(sim)
    if keys:
        S = np.empty((n, len(keys)))
        for j, k in enumerate(keys):
            pts, g = sim[k]
            pts, g = np.asarray(pts, float), np.asarray(g, float)
            if pts.shape != (n,) or g.shape != (n,):
                raise MvpOddsError(f"{k}: simulated arrays are not [{n}]")
            S[:, j] = float(banked.get(k, 0.0)) + pts - R * g
        top = S.max(axis=1)
    else:
        S, top = np.empty((n, 0)), np.full(n, -np.inf)
    const = {k: float(v) for k, v in banked.items() if k not in sim}
    c = max(const.values()) if const else -np.inf
    lead = [k for k, v in const.items() if v == c]
    top = np.maximum(top, c)
    win = S == top[:, None]
    cwin = (c == top) if lead else np.zeros(n, dtype=bool)
    k_tied = win.sum(axis=1) + cwin * len(lead)
    out = {}
    share = win / k_tied[:, None]
    for j, k in enumerate(keys):
        p = float(share[:, j].sum() / n)
        if p > 0:
            out[k] = p
    if lead:
        p = float((cwin / k_tied).sum() / n)      # each tied leader's own share
        if p > 0:
            for k in lead:
                out[k] = p
    return out


def future_R(res: dict, rule: str) -> tuple:
    """(R, words) for every remaining game: "current", the latest week's R
    (awards.replacement_levels as of the log's last day); "season_mean",
    the mean of every week's R so far."""
    R = res.get("R") or {}
    if not R:
        raise MvpOddsError("no replacement level yet (the season has not started)")
    if rule == "current":
        w = max(R)
        return float(R[w]["R"]), f"week {w}'s replacement level as of {R[w]['as_of']}, held"
    if rule == "season_mean":
        vals = [float(v["R"]) for _w, v in sorted(R.items())]
        return float(sum(vals) / len(vals)), f"the mean of weeks 1\u2013{max(R)}'s replacement levels"
    raise MvpOddsError(f"unknown future replacement rule {rule!r}")


def pct(p: Optional[float]) -> str:
    """The odds as printed: "61% to win"; "under 1%" and "over 99%" at the
    ends (a sampled 0 or 1 is not a proof)."""
    if p is None:
        return ""
    x = float(p) * 100
    if x < 0.5:
        return "under 1% to win"
    if x >= 99.5:
        return "over 99% to win"
    return f"{int(x + 0.5)}% to win"


def short_pct(p: Optional[float]) -> str:
    """A chart label's odds: "61%", "<1%", ">99%"."""
    s = pct(p)
    return {"under 1% to win": "<1%", "over 99% to win": ">99%"}.get(s, s.replace(" to win", ""))


# =============================================================================
# from a pass
# =============================================================================

def _sim_from(sp) -> date:
    """The first day the pass simulates (the in-progress week's as-of, else
    the first simulated regular week's first day)."""
    m = sp.mvp
    if m.get("as_of"):
        return date.fromisoformat(m["as_of"])
    from .week_state import week_entry
    if not m["weeks"]:
        raise MvpOddsError("the pass simulates no regular-season day")
    return date.fromisoformat(str(week_entry(sp.data, min(m["weeks"]))["start_date"])[:10])


def check_aligned(sp, res: dict) -> None:
    """The pass and the awards must meet at one day: the pass simulates from
    the day after the log's last day. RAISES otherwise (a banked game would
    be counted twice, or a day missed)."""
    if sp.mvp is None:
        raise MvpOddsError("the pass did not tally started points (run_season(mvp=True))")
    if not sp.mvp["weeks"]:
        return
    want = date.fromisoformat(res["through"]) + timedelta(days=1)
    got = _sim_from(sp)
    if got != want:
        raise MvpOddsError(f"the pass simulates from {got} but the awards' log ends {res['through']}: "
                           "they must meet (the pass from the day after the log's last day)")


def _inputs(sp, res: dict) -> tuple:
    """(banked {label: PAR}, sim {label: (pts, games)}, team {label: manager},
    names {label: roster key})."""
    from .data_loader import PlayerIndex
    rows = res["awards"]["mvp"]["rows"]
    banked = {r["key"]: float(r["value"]) for r in rows}
    team = {r["key"]: r["m"] for r in rows}
    idx = PlayerIndex({k: k for k in banked})
    stand = set(sp.mvp["standins"])
    sim, names = {}, {}
    for k, v in sp.mvp["players"].items():
        if k in stand or str(k).startswith("Replacement for "):
            continue
        lab = idx.canonical(k) or k
        if lab in sim:
            raise MvpOddsError(f"two roster keys ({names[lab]}, {k}) are the same player {lab}")
        sim[lab], names[lab] = (v[0], v[1]), k
        if len(v) > 2 and lab not in team:
            team[lab] = v[2]
    return banked, sim, team, names


def compute(sp, res: dict, cfg: Optional[dict] = None, rule: Optional[str] = None) -> dict:
    """The odds blob (the file's content) from a pass with the tally and the
    awards as of the log's last day. RAISES MvpOddsError."""
    c = config(cfg)
    rule = rule or c["future_replacement"]
    check_aligned(sp, res)
    n = int(sp.num_simulations)
    banked, sim, team, _names = _inputs(sp, res)
    R, words = future_R(res, rule)
    p = odds(banked, sim, R, n)
    total = sum(p.values())
    if abs(total - 1.0) > 1e-9:
        raise MvpOddsError(f"the odds sum to {total}, not 1")
    by_banked = sorted(banked, key=lambda k: (-banked[k], k))[:int(c["contenders_n"])]
    keep = set(by_banked) | {k for k, v in p.items() if v >= float(c["store_min"])}
    cont = []
    for k in keep:
        pts, g = sim.get(k, (np.zeros(n), np.zeros(n)))
        sp_par = np.asarray(pts, float) - R * np.asarray(g, float)
        cont.append({"key": k, "label": k, "m": team.get(k), "p": round(p.get(k, 0.0), 6),
                     "banked": round(banked.get(k, 0.0), 2), "sim_par": round(float(sp_par.mean()), 2),
                     "sim_starts": round(float(np.asarray(g, float).mean()), 3),
                     "sim_points": round(float(np.asarray(pts, float).mean()), 2),
                     "rostered": k in sim})
    cont.sort(key=lambda x: (-x["p"], -x["banked"], x["key"]))
    return {"schema": SCHEMA, "season": res["season"], "through": res["through"], "week": res["week"],
            "final": bool(res.get("final")), "seed": int(sp.seed), "num_simulations": n,
            "sim_from": (_sim_from(sp).isoformat() if sp.mvp["weeks"] else None), "weeks": list(sp.mvp["weeks"]),
            "replacement": {"rule": rule, "R": round(R, 3), "words": words},
            "contenders": cont, "everyone_else": round(max(0.0, 1.0 - sum(x["p"] for x in cont)), 6),
            "in_race": len(set(banked) | set(sim)), "run_id": None}


def sensitivity(sp, res: dict, cfg: Optional[dict] = None) -> dict:
    """{rule: {player: p}} for every future-R rule, on the same pass."""
    check_aligned(sp, res)
    banked, sim, _team, _names = _inputs(sp, res)
    return {r: odds(banked, sim, future_R(res, r)[0], int(sp.num_simulations)) for r in RULES}


# =============================================================================
# the file
# =============================================================================

def write(base, blob: dict) -> Path:
    """output/mvp_odds.json (state): the nightly's odds, replaced each night."""
    from .data_loader import atomic_write_json
    if blob.get("schema") != SCHEMA or not blob.get("run_id"):
        raise MvpOddsError("an MVP odds blob needs this schema and its run's id")
    p = Path(base) / FILE
    p.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(p, blob, indent=1)
    return p


def load(base) -> Optional[dict]:
    """The latest odds, or None when the nightly has not written any. A file
    of another schema RAISES."""
    p = Path(base) / FILE
    if not p.is_file():
        return None
    blob = json.loads(p.read_text(encoding="utf-8"))
    if blob.get("schema") != SCHEMA:
        raise MvpOddsError(f"{FILE.as_posix()} is schema {blob.get('schema')}, not {SCHEMA}")
    for k in ("season", "through", "contenders", "num_simulations", "replacement"):
        if k not in blob:
            raise MvpOddsError(f"{FILE.as_posix()} lacks {k!r}")
    return blob


# =============================================================================
# the history line (modules/awards' weekly MVP line gains "odds")
# =============================================================================

def line_odds(blob: Optional[dict], season: str, through: str) -> tuple:
    """(odds for a history line, why not): the odds go on a week's MVP line
    only when they were priced on that week's last day (`through`)."""
    if blob is None:
        return None, "no MVP odds were priced (the nightly writes them)"
    if blob["season"] != season:
        return None, f"the odds on file are for {blob['season']}"
    if blob["through"] != through:
        return None, f"the odds on file are as of {blob['through']}, not the week's last day {through}"
    return {"run_id": blob.get("run_id"), "num_simulations": int(blob["num_simulations"]),
            "R": blob["replacement"]["R"],
            "p": [{"key": x["key"], "label": x["label"], "m": x["m"], "p": x["p"]}
                  for x in blob["contenders"] if x["p"] > 0]}, None


def attach(lines: list, blob: Optional[dict]) -> list:
    """The pending history lines with the MVP line's added "odds" field (a
    dict, or None with "odds_why"). Other awards' lines are untouched. Old
    lines on file have no field and still read (awards.read_history)."""
    out = []
    for ln in lines:
        if ln.get("award") == "mvp":
            o, why = line_odds(blob, ln["season"], ln["through"])
            ln = dict(ln, odds=o)
            if o is None:
                ln["odds_why"] = why
        out.append(ln)
    return out
