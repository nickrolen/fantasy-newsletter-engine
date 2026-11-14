"""ratings.py -- OVR, POT and the attribute grades (4a; claude/4A_RESULT_2026-11-14.md).

The numbers the new hub's player card and roster table show. Plain data out
(numbers and reasons); formatting into strings is hub_state's job (4c).
Nothing here is wired into hub_state, the payload or the page.

WHAT IS VALIDATED IS WHAT SHIPS. Every function below is the formula 4a
back-tested on nine seasons of the league log (_to_delete/4a/PREREG.md):
rate() takes a keeper_history Snapshot -- the same point-in-time candidates
the back-test used (snapshot() for a past day, live_snapshot() for today) --
and config/league_config.json "ratings" (every key required).

OVR, "how much he helps a team in this league right now": a monotone map of
    composite = A x G x (L - R - penalty x S)
  L  keepability v3's level: FPPG so far shrunk toward his last three
     seasons in the league log (config/keepability_v3_params.json level_prior)
  G  his NBA team's games remaining (the next day .. the season's last
     fantasy day)
  A  availability: (games + k0 A0) / (team games while rostered + k0), A0 his
     previous three seasons' games / team games in the log (20+ team games),
     else today's rostered players' mean
  R  replacement level: a quantile of L over today's rostered players
  S  game-score sd, shrunk (penalty 0 as fitted: consistency is a grade only)
It is context-free: no manager's roster enters it, only the league's rostered
players (for R and the scale). The back-test: Spearman with rest-of-season
points beat FPPG so far in 7 of 9 seasons, pooled +0.038 [+0.009, +0.063];
against FPPG x games remaining +0.024 [-0.004, +0.051] (not shown to add
beyond games remaining). The daily fill ("startable" points) is NOT in it.

POT, "his value as a keeper": a monotone map of
    V = L x m(age) x (1 + w x m(age + 1)),  m(a) = exp(age curve)
next season's projected level from this league's age curve plus the season
after. It predicts who is kept better than FPPG (held out, six decisions,
+34.9 log-likelihood [+10.8, +64.4]) but worse than keepability v3's keep
chance, which also knows reputation (kept, draft round). It is not "upside".

GRADES: mid-rank percentiles among today's rostered players, letter bands
from config. Durability (A), consistency (-sd/FPPG), schedule (G); the five
category grades are None with a reason until per-category stats are stored.

No randomness. Missing inputs RAISE (RatingsInputError, naming them); a
player the inputs cannot rate gets None and a reason, never a made-up value.
"""
from __future__ import annotations

import json
import math
import statistics
from datetime import date, timedelta
from pathlib import Path
from typing import Callable, Optional

ROOT = Path(__file__).resolve().parents[1]


class RatingsInputError(RuntimeError):
    """A required input or config key is missing or malformed; the message names it."""


# ---------------------------------------------------------------------------
# config
# ---------------------------------------------------------------------------

REQUIRED = {
    ("as_of", "games_remaining_through"): str,
    ("ovr", "availability_k0"): (int, float),
    ("ovr", "availability_prior_min_team_games"): (int, float),
    ("ovr", "replacement_quantile"): (int, float),
    ("ovr", "consistency_penalty"): (int, float),
    ("ovr", "sd_k0_games"): (int, float),
    ("ovr", "anchors"): list,
    ("pot", "age_curve", "center"): (int, float),
    ("pot", "age_curve", "coef"): list,
    ("pot", "next_year_weight"): (int, float),
    ("pot", "anchors"): list,
    ("scale_min",): (int, float),
    ("scale_max",): (int, float),
    ("grade_bands",): list,
    ("grades", "order"): list,
    ("grades", "min_team_games"): dict,
    ("grades", "min_games"): dict,
    ("grades", "unavailable"): dict,
    ("archetype", "enabled"): bool,
}
COMPUTED_GRADES = ("durability", "consistency", "schedule")


def config(cfg: Optional[dict] = None) -> dict:
    """league_config.json "ratings", every required key checked (raises naming the missing)."""
    if cfg is None:
        full = json.loads((ROOT / "config" / "league_config.json").read_text(encoding="utf-8"))
        cfg = full.get("ratings")
    if not isinstance(cfg, dict):
        raise RatingsInputError("league_config.json has no \"ratings\" block")
    bad = []
    for path, typ in REQUIRED.items():
        node = cfg
        for k in path:
            node = node.get(k) if isinstance(node, dict) else None
        if node is None or isinstance(node, bool) and typ is not bool or not isinstance(node, typ):
            bad.append("ratings." + ".".join(path))
    if bad:
        raise RatingsInputError(f"missing or malformed config: {bad}")
    if cfg["as_of"]["games_remaining_through"] != "schedule_last_day":
        raise RatingsInputError("ratings.as_of.games_remaining_through must be \"schedule_last_day\"")
    for key in ("ovr", "pot"):
        _check_anchors(cfg[key]["anchors"], f"ratings.{key}.anchors")
    if len(cfg["pot"]["age_curve"]["coef"]) != 3:
        raise RatingsInputError("ratings.pot.age_curve.coef must have three numbers")
    bands = cfg["grade_bands"]
    lows = [b[0] for b in bands]
    if lows != sorted(lows, reverse=True) or lows[-1] != 0:
        raise RatingsInputError("ratings.grade_bands must run highest first and end at 0")
    order = cfg["grades"]["order"]
    for g in order:
        if g not in COMPUTED_GRADES and g not in cfg["grades"]["unavailable"]:
            raise RatingsInputError(f"ratings.grades.order names {g!r}, which is neither computed nor listed unavailable")
    if not cfg["scale_min"] < cfg["scale_max"]:
        raise RatingsInputError("ratings.scale_min must be below scale_max")
    return cfg


def _check_anchors(anchors, name):
    ok = (len(anchors) >= 2 and all(isinstance(a, list) and len(a) == 2 for a in anchors))
    if ok:
        ps, os_ = [a[0] for a in anchors], [a[1] for a in anchors]
        ok = ps == sorted(ps) and len(set(ps)) == len(ps) and os_ == sorted(os_) and ps[0] == 0 and ps[-1] == 100
    if not ok:
        raise RatingsInputError(f"{name} must be [[0, ovr], ..., [100, ovr]], percentiles and ratings increasing")


# ---------------------------------------------------------------------------
# the pieces (pure)
# ---------------------------------------------------------------------------

def quantile(values, q: float) -> float:
    """numpy's default (linear) quantile, without numpy."""
    xs = sorted(values)
    if not xs:
        raise RatingsInputError("no values for a quantile")
    h = (len(xs) - 1) * q
    lo = math.floor(h)
    hi = min(lo + 1, len(xs) - 1)
    return xs[lo] + (h - lo) * (xs[hi] - xs[lo])


def availability(games: int, team_games: int, prior_games: int, prior_team_games: int,
                 mean_now: float, k0: float, min_prior_team_games: float) -> float:
    a0 = prior_games / prior_team_games if prior_team_games >= min_prior_team_games else mean_now
    return (games + k0 * a0) / (team_games + k0)


def composite(A: float, G: float, L: float, R: float, penalty: float = 0.0, S: float = 0.0) -> float:
    return A * G * (L - R - penalty * S)


def age_multiplier(age: float, curve: dict) -> float:
    a = float(age) - float(curve["center"])
    c0, c1, c2 = (float(x) for x in curve["coef"])
    return math.exp(c0 + c1 * a + c2 * a * a)


def pot_value(L: float, age: float, curve: dict, next_year_weight: float) -> float:
    return L * age_multiplier(age, curve) * (1.0 + next_year_weight * age_multiplier(age + 1, curve))


def knots(universe_values, anchors) -> list:
    """[(composite, rating)] at the anchors' percentiles of the universe."""
    out = []
    for p, r in anchors:
        out.append((quantile(universe_values, p / 100.0), float(r)))
    return out


def scale(value: float, kn: list, lo: float, hi: float) -> int:
    """Piecewise linear in the composite through the knots, extended along the
    end segments, clamped to lo..hi, rounded half up. Monotone non-decreasing:
    knots with equal composites keep the lowest rating."""
    xs, ys = [], []
    for x, y in kn:
        if xs and x <= xs[-1]:
            continue                      # equal composite: the lower rating stands
        xs.append(x); ys.append(y)
    if len(xs) == 1:
        v = ys[0]
    else:
        if value <= xs[0]:
            i = 0
        elif value >= xs[-1]:
            i = len(xs) - 2
        else:
            i = max(j for j in range(len(xs) - 1) if xs[j] <= value)
        x0, x1, y0, y1 = xs[i], xs[i + 1], ys[i], ys[i + 1]
        v = y0 + (value - x0) * (y1 - y0) / (x1 - x0)
    v = min(max(v, lo), hi)
    return int(math.floor(v + 0.5))


def percentiles(values: dict) -> dict:
    """{key: mid-rank percentile} among the keys with a value (None skipped)."""
    have = sorted(((v, k) for k, v in values.items() if v is not None), key=lambda t: t[0])
    n = len(have)
    out, i = {}, 0
    while i < n:
        j = i
        while j + 1 < n and have[j + 1][0] == have[i][0]:
            j += 1
        r = (i + j) / 2.0 + 1.0
        for t in range(i, j + 1):
            out[have[t][1]] = 100.0 * (r - 0.5) / n
        i = j + 1
    return out


def letter(p: float, bands) -> str:
    for low, name in bands:
        if p >= low:
            return name
    raise RatingsInputError(f"percentile {p} below every grade band")


# ---------------------------------------------------------------------------
# inputs from the league log
# ---------------------------------------------------------------------------

def prior_availability(inputs, season: str, n_seasons: int = 3) -> Callable:
    """name -> (games, team games) over the n_seasons seasons before `season`
    in the league log (rostered days only, like every log figure)."""
    from . import keeper_history as kh
    from .data_loader import PlayerIndex
    per, s = [], season
    for _ in range(n_seasons):
        s = kh.prev_season(s)
        acc: dict = {}
        for r in inputs.log.get(s, []):
            g, tg = acc.get(r["player_name"], (0, 0))
            acc[r["player_name"]] = (g + int(kh.appeared(r)), tg + int(bool(r["had_game"])))
        per.append((acc, PlayerIndex({k: k for k in acc})))

    def f(name: str) -> tuple:
        g = tg = 0
        for acc, idx in per:
            hit = idx.canonical(name)
            if hit is not None:
                g += acc[hit][0]
                tg += acc[hit][1]
        return g, tg
    return f


def team_dates(schedule: dict) -> dict:
    """{team: sorted ISO dates} from the engine's NBA schedule ({"games": [{date, home, away}]})."""
    games = (schedule or {}).get("games")
    if not games:
        raise RatingsInputError("the NBA schedule has no games")
    out: dict = {}
    for g in games:
        d = str(g["date"])[:10]
        for t in (g.get("home"), g.get("away")):
            if t:
                out.setdefault(t, []).append(d)
    return {t: sorted(v) for t, v in out.items()}


# ---------------------------------------------------------------------------
# rate
# ---------------------------------------------------------------------------

def rate(snap, inputs, dates_by_team: dict, last_day: str, cfg: Optional[dict] = None,
         level_prior: Optional[dict] = None, previous: Optional[dict] = None) -> dict:
    """Ratings for every candidate of a keeper_history Snapshot (point in time:
    only log rows dated on or before snap.as_of are read). dates_by_team: the
    season's NBA games by team; last_day: the last day games remaining count.
    previous: {player: last week's published OVR} for the weekly change.
    Returns {"as_of", "season", "universe", "replacement_level", "knots": {...},
    "players": {name: {...}}}."""
    from . import keeper_history as kh
    from . import keepability_v3 as M
    cfg = config(cfg)
    lp = level_prior or M.level_config(M.load_params())
    as_of = snap.as_of
    season = snap.candidates[0].season if snap.candidates else None
    if season is None:
        raise RatingsInputError("the snapshot has no candidates")
    rows = [r for r in inputs.log[season] if r["date"] <= as_of]          # point in time
    by_p: dict = {}
    for r in rows:
        by_p.setdefault(r["player_name"], []).append(r)
    prior_av = prior_availability(inputs, season)
    oc, pc = cfg["ovr"], cfg["pot"]
    cands = sorted(snap.candidates, key=lambda c: c.player)
    if len({c.player for c in cands}) != len(cands):
        raise RatingsInputError("a player appears twice in the snapshot")
    avs = [c.availability for c in cands if c.availability is not None]
    mean_av = sum(avs) / len(avs) if avs else 1.0

    base = {}
    for c in cands:
        mine = by_p.get(c.player, [])
        today_rows = [r for r in mine if r["date"] == as_of]
        team = today_rows[0]["nba_team"] if today_rows else None
        scores = [r["fantasy_points"] for r in mine if kh.appeared(r)]
        sd = statistics.pstdev(scores) if len(scores) >= 2 else None
        L = float(M.level_of(c, lp)[0])
        pg, ptg = prior_av(c.player)
        A = availability(c.games, c.team_games, pg, ptg, mean_av, oc["availability_k0"],
                         oc["availability_prior_min_team_games"])
        if not team:
            G, g_reason = None, ("not on the league log's last day yet: OVR from his first logged day"
                                 if not today_rows else "no NBA team in the log")
        elif team not in dates_by_team:
            raise RatingsInputError(f"{c.player}: team {team!r} is not in the NBA schedule")
        else:
            G, g_reason = sum(1 for d in dates_by_team[team] if as_of < d <= last_day), None
        base[c.player] = {"c": c, "team": team, "L": L, "A": A, "G": G, "g_reason": g_reason,
                          "sd": sd, "n": len(scores)}

    sds = [b["sd"] for b in base.values() if b["sd"] is not None]
    sd_med = statistics.median(sds) if sds else 0.0
    R = quantile([b["L"] for b in base.values()], oc["replacement_quantile"])
    for b in base.values():
        S = ((b["n"] * b["sd"] + oc["sd_k0_games"] * sd_med) / (b["n"] + oc["sd_k0_games"])
             if b["sd"] is not None else sd_med)
        b["S"] = S
        b["C"] = None if b["G"] is None else composite(b["A"], b["G"], b["L"], R, oc["consistency_penalty"], S)
    rated = [b["C"] for b in base.values() if b["C"] is not None]
    season_over = bool(rated) and max(rated) <= 0 and all(b["G"] == 0 for b in base.values() if b["G"] is not None)
    ovr_knots = knots(rated, oc["anchors"]) if rated and not season_over else None

    # POT
    for b in base.values():
        c = b["c"]
        if c.age is None:
            b["V"], b["v_reason"] = None, "no age on record"
        else:
            b["V"], b["v_reason"] = pot_value(b["L"], c.age, pc["age_curve"], pc["next_year_weight"]), None
    vals = [b["V"] for b in base.values() if b["V"] is not None]
    pot_knots = knots(vals, pc["anchors"]) if vals else None

    # grades
    g = cfg["grades"]
    raw = {"durability": {}, "consistency": {}, "schedule": {}}
    why: dict = {"durability": {}, "consistency": {}, "schedule": {}}
    for name, b in base.items():
        c = b["c"]
        need = g["min_team_games"].get("durability", 0)
        if c.team_games >= need:
            raw["durability"][name] = b["A"]
        else:
            raw["durability"][name] = None
            why["durability"][name] = f"{c.team_games} team games: shows after {need}"
        need = g["min_games"].get("consistency", 0)
        if b["n"] >= max(need, 2) and c.fppg and c.fppg > 0 and b["sd"] is not None:
            raw["consistency"][name] = -b["sd"] / c.fppg
        else:
            raw["consistency"][name] = None
            why["consistency"][name] = f"{b['n']} games: shows after {max(need, 2)}"
        raw["schedule"][name] = b["G"]
        if b["G"] is None:
            why["schedule"][name] = b["g_reason"]
    pcts = {k: percentiles(v) for k, v in raw.items()}

    players = {}
    for name, b in sorted(base.items()):
        c = b["c"]
        if b["C"] is None:
            ovr, ovr_reason = None, b["g_reason"]
        elif season_over:
            ovr, ovr_reason = None, "no games remain this season"
        else:
            ovr, ovr_reason = scale(b["C"], ovr_knots, cfg["scale_min"], cfg["scale_max"]), None
        prev = (previous or {}).get(name)
        change = (ovr - int(prev)) if (ovr is not None and prev is not None) else None
        pot = None if b["V"] is None else scale(b["V"], pot_knots, cfg["scale_min"], cfg["scale_max"])
        grades = {}
        for attr in g["order"]:
            if attr in COMPUTED_GRADES:
                p = pcts[attr].get(name)
                grades[attr] = ({"letter": letter(p, cfg["grade_bands"]), "percentile": p,
                                 "value": raw[attr][name], "reason": None} if p is not None else
                                {"letter": None, "percentile": None, "value": None,
                                 "reason": why[attr].get(name, "no value")})
            else:
                grades[attr] = {"letter": None, "percentile": None, "value": None,
                                "reason": g["unavailable"][attr]}
        players[name] = {
            "player": name, "manager": c.manager, "nba_team": b["team"],
            "ovr": ovr, "ovr_reason": ovr_reason, "ovr_change": change,
            "ovr_composite": b["C"], "pot": pot, "pot_reason": b["v_reason"], "pot_value": b["V"],
            "components": {"level": b["L"], "availability": b["A"], "games_remaining": b["G"],
                           "game_sd": b["S"], "games": c.games, "team_games": c.team_games,
                           "fppg": c.fppg, "age": c.age},
            "grades": grades,
            "archetype": None,
            "archetype_reason": None if cfg["archetype"]["enabled"] else "dropped in 4a: needs per-category grades",
        }
    return {"as_of": as_of, "season": season, "last_day": last_day, "universe": len(players),
            "replacement_level": R, "knots": {"ovr": ovr_knots, "pot": pot_knots}, "players": players}


# ---------------------------------------------------------------------------
# today
# ---------------------------------------------------------------------------

def _nofetch(url):
    raise RatingsInputError(f"an age is missing from data/historical/BBREF_AGES.json ({url}); "
                            "ratings never fetch")


def schedule_last_day(root=ROOT) -> str:
    sched = json.loads((Path(root) / "config" / "SCHEDULE.json").read_text(encoding="utf-8"))
    ends = [str(w["end_date"])[:10] for w in sched.get("weeks", [])]
    if not ends:
        raise RatingsInputError("config/SCHEDULE.json has no weeks")
    return max(ends)


def for_today(root=ROOT, previous: Optional[dict] = None, today: Optional[date] = None,
              history=None) -> dict:
    """rate() on today's rosters (config/ROSTERS.json), the live log, the
    engine's NBA schedule and keepability v3's level prior. Read-only."""
    from . import keeper_history as kh
    from .data_loader import load_nba_schedule, _schedule_path
    root = Path(root)
    rf = root / "config" / "ROSTERS.json"
    if not rf.is_file():
        raise RatingsInputError("config/ROSTERS.json is missing")
    blob = json.loads(rf.read_text(encoding="utf-8"))
    rosters = {m: list(v) for m, v in blob.get("rosters", {}).items() if isinstance(v, list) and v}
    if not rosters:
        raise RatingsInputError("config/ROSTERS.json has no rosters")
    li, season = kh.live_inputs(root, history)
    ages = kh.load_ages(kh.age_seasons(), root, fetch=_nofetch)
    snap = kh.live_snapshot(li, season, rosters, ages)
    sched = load_nba_schedule(_schedule_path(root), today=today)
    return rate(snap, li, team_dates(sched), schedule_last_day(root), previous=previous)


# ---------------------------------------------------------------------------
# the weekly history (proposed state file; 4a does not write it)
# ---------------------------------------------------------------------------

def history_line(result: dict) -> dict:
    """One line for the proposed output/ratings_history.jsonl: as_of and each player's OVR and POT."""
    return {"as_of": result["as_of"], "season": result["season"],
            "ovr": {n: p["ovr"] for n, p in result["players"].items() if p["ovr"] is not None},
            "pot": {n: p["pot"] for n, p in result["players"].items() if p["pot"] is not None}}


def previous_from_history(lines: list, as_of: str, days: int = 7) -> Optional[dict]:
    """{player: OVR} from the latest published line at least `days` before as_of, or None."""
    cut = (date.fromisoformat(as_of) - timedelta(days=days)).isoformat()
    older = [l for l in lines if l.get("as_of") and l["as_of"] <= cut]
    if not older:
        return None
    return dict(max(older, key=lambda l: l["as_of"])["ovr"])
