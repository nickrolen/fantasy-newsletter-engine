"""skill.py -- OVR as a skill rating, and Durability (4a4 s.2;
claude/HANDOFF_4A4_NBA_HISTORY_OVR_ARCHETYPES_2026-11-20.md).

WHY (Nick, 11-20): "like 2k -- an overall rating of a player in a vacuum. A
meter of skill and ability ... an assessment of a players whole picture to this
point ... it should make players prove it ... It should also take age and or
fall-offs into account." And Durability: "fully separate from OVR, like 2k."

THE ESTIMATE ("how good is he per game when he plays, judged on everything he's
done"), a Marcel-style projection of his fantasy points per game in this
league's scoring, as of a day in season S (point in time: only seasons before S
and this season's games through the day):
  1. HISTORY: his NBA seasons S-1 .. S-window he PLAYED (gp > 0;
     data/historical/NBA_SEASONS.json, rostered or not), each moved to his age
     this season along the AGING CURVE, averaged with weight games x
     recency^(back - 1). n = the sum of those weights (his evidence, in games).
  2. REGRESSION: P = (n H + k B) / (n + k): a thin record is pulled toward the
     BASELINE B, a long one barely. B = the typical NBA player in his
     (experience + 1)-th season (baseline_table: games-weighted FPPG of the
     player-seasons with that many seasons before them, players whose first
     season in the file is first_season_from or later -- a true debut -- and
     seasons before S).
  3. ROOKIES (no NBA season before S): P = the ROOKIE CURVE at his NBA draft
     pick (data/historical/NBA_DRAFTS.json): a + b ln(pick), games-weighted,
     fitted on drafted players' rookie seasons (rookie_curve); undrafted: the
     curve at pick 60 (its bottom). Its weight is k_rookie games.
  4. THIS SEASON: E = (W P + c g F) / (W + c g), W = n + k, g his games so far
     and F their FPPG, c = this_season_weight; a ROOKIE: W = k_rookie and
     c = rookie_this_season_weight (his own weights: a draft-slot prior is
     not a career). share_this_season says what share this season carries.
NOT IN IT: games left, availability, anyone's roster. Durability is its own
rating (durability()); nothing in OVR reads it.

THE AGING CURVE: m(a) = exp(c0 + c1 (a - center) + c2 (a - center)^2), the
expected ratio of FPPG at age a + 1 to FPPG at age a (fit_age_curve). Moving a
season at age a0 to age a1 multiplies it by m(a0) x ... x m(a1 - 1).

THE SCALE (fixed: a 90 means the same every year): OVR = a piecewise-linear map
of E (FPPG) through config anchors, extended along the top segment and clamped
at 99; below the first anchor it approaches 40 without reaching it (5b s.1b's
rule), so nothing piles up at the bottom. Nobody's OVR moves because someone
else was picked up. DUR has its own fixed anchors (availability -> rating).

DURABILITY (durability()): how often he plays when his team does. His seasons
in the window that COUNT (nba_prior.counts_for_availability: played, or 0 games
between two played seasons or just before S), min(gp, team games) / team games
weighted recency^(back - 1) x team games, regressed toward a baseline with
k team games, then this season's games / team games blended in with its team
games. A current injury is not in it (the injury chip's job).

Pure functions; missing config RAISES (SkillError, naming it).
"""
from __future__ import annotations

import math
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from .nba_prior import counts_for_availability, season_label, season_year, team_games

PLAYED_MIN = 1


class SkillError(RuntimeError):
    """A required config key or input is missing or malformed; named."""


REQUIRED = ("window", "recency", "k_history", "this_season_weight", "k_rookie", "rookie_this_season_weight",
            "age_curve", "rookie_curve", "baseline", "team_games", "scale", "durability")


def check(sc) -> dict:
    """config ratings.skill, every key checked (RAISES naming the bad ones)."""
    if not isinstance(sc, dict):
        raise SkillError("ratings.skill is missing (4a4 s.2: OVR as a skill rating)")
    bad = [f"ratings.skill.{k}" for k in REQUIRED if k not in sc]
    num = lambda v, lo, hi: isinstance(v, (int, float)) and not isinstance(v, bool) and lo <= v <= hi
    if not bad:
        if not (isinstance(sc["window"], int) and 1 <= sc["window"] <= 10):
            bad.append("ratings.skill.window")
        for k, lo, hi in (("recency", 0.01, 1.0), ("k_history", 0, 1000), ("this_season_weight", 0.01, 1000),
                          ("k_rookie", 0.5, 1000), ("rookie_this_season_weight", 0.01, 1000)):
            if not num(sc[k], lo, hi):
                bad.append(f"ratings.skill.{k}")
        ac = sc["age_curve"]
        if not (isinstance(ac, dict) and num(ac.get("center"), 15, 40) and isinstance(ac.get("coef"), list)
                and len(ac["coef"]) == 3 and all(num(x, -5, 5) for x in ac["coef"])):
            bad.append("ratings.skill.age_curve ({center, coef: [c0, c1, c2]})")
        rc = sc["rookie_curve"]
        if not (isinstance(rc, dict) and isinstance(rc.get("drafts_from"), int) and isinstance(rc.get("min_drafts"), int)
                and isinstance(rc.get("bottom_pick"), int)):
            bad.append("ratings.skill.rookie_curve ({drafts_from, min_drafts, bottom_pick})")
        bl = sc["baseline"]
        if not (isinstance(bl, dict) and isinstance(bl.get("first_season_from"), str)
                and isinstance(bl.get("max_experience"), int) and bl["max_experience"] >= 1):
            bad.append("ratings.skill.baseline ({first_season_from, max_experience})")
        if not (isinstance(sc["team_games"], dict) and isinstance(sc["team_games"].get("default"), int)):
            bad.append("ratings.skill.team_games")
        for key in ("scale",):
            if not _anchors_ok(sc[key].get("anchors") if isinstance(sc[key], dict) else None):
                bad.append(f"ratings.skill.{key}.anchors ([[fppg, rating], ...] increasing)")
        d = sc["durability"]
        if not (isinstance(d, dict) and num(d.get("baseline"), 0, 1) and num(d.get("k_team_games"), 0, 1000)
                and isinstance(d.get("window"), int) and _anchors_ok(d.get("anchors"))):
            bad.append("ratings.skill.durability ({window, baseline, k_team_games, anchors})")
    if bad:
        raise SkillError(f"missing or malformed config: {bad}")
    return sc


def _anchors_ok(a) -> bool:
    if not isinstance(a, list) or len(a) < 2 or not all(isinstance(x, list) and len(x) == 2 for x in a):
        return False
    xs, ys = [x[0] for x in a], [x[1] for x in a]
    return xs == sorted(xs) and len(set(xs)) == len(xs) and ys == sorted(ys) and 40 <= ys[0] and ys[-1] <= 99


# ---------------------------------------------------------------------------
# seasons
# ---------------------------------------------------------------------------

def fppg(entry_season: dict, values: Dict[str, float]) -> float:
    gp = int(entry_season["gp"])
    return sum(float(entry_season["stats"][k]) * float(v) for k, v in values.items()) / gp


def played(entry: Optional[dict], before: str) -> List[str]:
    """His seasons with games, before `before`, ascending."""
    if entry is None:
        return []
    return sorted(s for s, e in (entry.get("seasons") or {}).items() if int(e.get("gp") or 0) >= PLAYED_MIN
                  and s < before)


# ---------------------------------------------------------------------------
# the aging curve
# ---------------------------------------------------------------------------

def age_step(age: float, curve: dict) -> float:
    """m(a): expected FPPG at age a + 1 over FPPG at age a."""
    a = float(age) - float(curve["center"])
    c0, c1, c2 = (float(x) for x in curve["coef"])
    return math.exp(c0 + c1 * a + c2 * a * a)


def age_move(a_from: int, a_to: int, curve: dict) -> float:
    """The factor that moves a season played at a_from to age a_to (either way)."""
    f = 1.0
    if a_to >= a_from:
        for a in range(int(a_from), int(a_to)):
            f *= age_step(a, curve)
    else:
        for a in range(int(a_to), int(a_from)):
            f /= age_step(a, curve)
    return f


def age_pairs(players: dict, values: Dict[str, float], age_of, *, min_games: int = 10,
              seasons: Optional[Iterable[str]] = None) -> List[Tuple[str, int, float, float]]:
    """[(season t+1, age at t, log(FPPG t+1 / FPPG t), weight)] over consecutive seasons
    both with min_games or more; weight the harmonic mean of the two games counts.
    age_of(pid, season) -> age or None (a pair without an age is skipped).
    seasons: only pairs whose t+1 is in it (None: all)."""
    keep = None if seasons is None else set(seasons)
    out = []
    for pid, e in players.items():
        ss = e.get("seasons") or {}
        for t, x in ss.items():
            t1 = season_label(season_year(t) + 1)
            y = ss.get(t1)
            if y is None or (keep is not None and t1 not in keep):
                continue
            g0, g1 = int(x["gp"]), int(y["gp"])
            if g0 < min_games or g1 < min_games:
                continue
            f0, f1 = fppg(x, values), fppg(y, values)
            if f0 <= 0 or f1 <= 0:
                continue
            a = age_of(pid, t)
            if a is None:
                continue
            out.append((t1, int(a), math.log(f1 / f0), 2.0 * g0 * g1 / (g0 + g1)))
    return out


def fit_age_curve(pairs: Sequence[Tuple[str, int, float, float]], center: float = 27.0) -> dict:
    """Weighted least squares of the log change on (age - center), quadratic."""
    import numpy as np
    if len(pairs) < 30:
        raise SkillError(f"only {len(pairs)} age pairs: too few to fit the aging curve")
    a = np.array([p[1] for p in pairs], float) - center
    y = np.array([p[2] for p in pairs], float)
    w = np.sqrt(np.array([p[3] for p in pairs], float))
    X = np.column_stack([np.ones_like(a), a, a * a])
    beta, *_ = np.linalg.lstsq(X * w[:, None], y * w, rcond=None)
    return {"center": center, "coef": [round(float(b), 6) for b in beta], "pairs": len(pairs)}


# ---------------------------------------------------------------------------
# the baselines: the typical player by experience; the rookie curve by pick
# ---------------------------------------------------------------------------

def baseline_table(players: dict, values: Dict[str, float], before: str, sc: dict) -> Dict[int, float]:
    """{experience e (seasons played before): games-weighted FPPG of the
    player-seasons with e seasons before them}, e = 1 .. max_experience (the last
    holds e or more), over players whose first season in the file is
    first_season_from or later (a true debut: the file starts in 2014-15) and
    seasons before `before`. A missing e takes the nearest one below it."""
    bl = sc["baseline"]
    E = int(bl["max_experience"])
    acc = {e: [0.0, 0.0] for e in range(1, E + 1)}
    for e_ in players.values():
        ps = played(e_, before)
        if not ps or ps[0] < bl["first_season_from"]:
            continue
        for i, s in enumerate(ps):
            if i == 0:
                continue
            x = e_["seasons"][s]
            k = min(i, E)
            acc[k][0] += int(x["gp"]) * fppg(x, values)
            acc[k][1] += int(x["gp"])
    out, last = {}, None
    for e in range(1, E + 1):
        if acc[e][1] > 0:
            last = acc[e][0] / acc[e][1]
        if last is None:
            raise SkillError(f"no player-season with {e} season(s) before it, before {before}: no baseline")
        out[e] = last
    return out


def rookie_rows(players: dict, drafts: dict, values: Dict[str, float]) -> List[Tuple[int, int, int, float]]:
    """[(draft year, pick, games, FPPG)] of drafted players' ROOKIE seasons (the
    season starting in the draft year), games > 0."""
    out = []
    for pid, d in (drafts.get("players") or {}).items():
        e = players.get(pid)
        s = season_label(int(d["year"]))
        x = ((e or {}).get("seasons") or {}).get(s)
        if x is None or int(x["gp"]) < PLAYED_MIN:
            continue
        out.append((int(d["year"]), int(d["pick"]), int(x["gp"]), fppg(x, values)))
    return out


def fit_rookie_curve(rows, season: str, sc: dict) -> dict:
    """{a, b, drafts, n}: FPPG = a + b ln(pick), games-weighted, on rookie
    seasons BEFORE `season` (point in time), from drafts_from on once
    min_drafts such drafts exist (the 2014-16 drafts lack the players who left
    before 2020: survivors only), else every draft on file."""
    import numpy as np
    rc = sc["rookie_curve"]
    S = season_year(season)
    prior = [r for r in rows if r[0] < S]
    late = [r for r in prior if r[0] >= int(rc["drafts_from"])]
    use = late if len({r[0] for r in late}) >= int(rc["min_drafts"]) else prior
    if len(use) < 20:
        raise SkillError(f"only {len(use)} rookie seasons before {season}: no rookie curve")
    x = np.log(np.array([r[1] for r in use], float))
    y = np.array([r[3] for r in use], float)
    w = np.sqrt(np.array([r[2] for r in use], float))
    X = np.column_stack([np.ones_like(x), x])
    beta, *_ = np.linalg.lstsq(X * w[:, None], y * w, rcond=None)
    return {"a": float(beta[0]), "b": float(beta[1]), "drafts": sorted({r[0] for r in use}), "n": len(use)}


def rookie_baseline(pick: Optional[int], curve: dict, sc: dict) -> float:
    p = int(sc["rookie_curve"]["bottom_pick"]) if pick is None else min(int(pick), int(sc["rookie_curve"]["bottom_pick"]))
    return curve["a"] + curve["b"] * math.log(p)


# ---------------------------------------------------------------------------
# the estimate
# ---------------------------------------------------------------------------

def history(entry: Optional[dict], season: str, age_now: Optional[int], values: Dict[str, float],
            sc: dict) -> dict:
    """{"H", "n", "experience", "used": [(season, gp, fppg, age factor, weight)]}; H None: no
    season he played in the window."""
    S = season_year(season)
    ps = played(entry, season)
    out = {"H": None, "n": 0.0, "experience": len(ps), "used": []}
    num = den = 0.0
    for s in ps:
        back = S - season_year(s)
        if back > int(sc["window"]):
            continue
        x = entry["seasons"][s]
        f = fppg(x, values)
        af = 1.0 if age_now is None else age_move(age_now - back, age_now, sc["age_curve"])
        w = int(x["gp"]) * float(sc["recency"]) ** (back - 1)
        num += w * f * af
        den += w
        out["used"].append((s, int(x["gp"]), round(f, 3), round(af, 4), round(w, 3)))
    if den > 0:
        out["H"], out["n"] = num / den, den
    return out


def estimate(entry: Optional[dict], season: str, age_now: Optional[int], g: int, f_now: Optional[float],
             values: Dict[str, float], sc: dict, base: Dict[int, float], rcurve: dict,
             pick: Optional[int], drafted_known: bool = True) -> dict:
    """{"E", "P", "W", "kind", "share" (this season's share), "hist"}.
    g, f_now: his games and FPPG this season so far. pick: his NBA draft pick
    (None: undrafted, or drafted before the draft file starts -- only matters
    for a rookie)."""
    h = history(entry, season, age_now, values, sc)
    if h["H"] is not None:
        e = min(max(h["experience"], 1), int(sc["baseline"]["max_experience"]))
        B = base[e]
        k = float(sc["k_history"])
        P = (h["n"] * h["H"] + k * B) / (h["n"] + k) if (h["n"] + k) > 0 else h["H"]
        W, kind = h["n"] + k, "history"
    elif h["experience"] > 0:
        # seasons on file, none in the window: the typical player of his experience
        e = min(h["experience"], int(sc["baseline"]["max_experience"]))
        P, W, kind = base[e], float(sc["k_history"]) or 1.0, "baseline (no season in the window)"
    else:
        P, W = rookie_baseline(pick, rcurve, sc), float(sc["k_rookie"])
        kind = "rookie curve" + (f" (pick {pick})" if pick is not None else " (undrafted: the curve's bottom)")
    c = float(sc["rookie_this_season_weight"] if kind.startswith("rookie") else sc["this_season_weight"])
    gg = int(g or 0)
    if gg and f_now is not None:
        E = (W * P + c * gg * float(f_now)) / (W + c * gg)
        share = c * gg / (W + c * gg)
    else:
        E, share = P, 0.0
    return {"E": E, "P": P, "W": W, "kind": kind, "share": share, "hist": h}


def share_this_season(W: float, g: int, c: float) -> float:
    """This season's share of the estimate at g games, prior weight W, weight c per game."""
    return float(c) * g / (W + float(c) * g)


# ---------------------------------------------------------------------------
# durability
# ---------------------------------------------------------------------------

def durability(entry: Optional[dict], season: str, g: int, tg: int, sc: dict) -> dict:
    """{"A": availability estimate 0..1, "prior", "n_team_games", "used"}."""
    d = sc["durability"]
    S = season_year(season)
    seasons = (entry or {}).get("seasons") or {}
    num = den = 0.0
    used = []
    for back in range(1, int(d["window"]) + 1):
        s = season_label(S - back)
        if s not in seasons or not counts_for_availability(seasons, s, season):
            continue
        t = team_games(s, sc)
        r = float(sc["recency"]) ** (back - 1)
        gp = min(int(seasons[s]["gp"]), t)
        num += r * gp
        den += r * t
        used.append((s, int(seasons[s]["gp"]), t))
    k = float(d["k_team_games"])
    a0 = float(d["baseline"])
    prior = (num + k * a0) / (den + k) if (den + k) > 0 else a0
    W = den + k
    A = (W * prior + int(g or 0)) / (W + int(tg or 0)) if (W + int(tg or 0)) > 0 else prior
    return {"A": min(max(A, 0.0), 1.0), "prior": prior, "n_team_games": den, "used": used}


# ---------------------------------------------------------------------------
# the fixed scales
# ---------------------------------------------------------------------------

def to_rating(x: float, anchors: list, lo: float = 40.0, hi: float = 99.0, rounded: bool = True):
    """Piecewise linear through the anchors, extended along the top segment
    (clamped at hi); below the first anchor it approaches lo with the bottom
    segment's slope at the anchor and never reaches it (5b s.1b)."""
    xs = [float(a[0]) for a in anchors]
    ys = [float(a[1]) for a in anchors]
    if x <= xs[0]:
        x0, x1, y0, y1 = xs[0], xs[1], ys[0], ys[1]
        slope = (y1 - y0) / (x1 - x0)
        v = y0 - (y0 - lo) * (1.0 - math.exp(slope * (x - x0) / (y0 - lo))) if (slope > 0 and y0 > lo) else y0
    else:
        i = len(xs) - 2 if x >= xs[-1] else max(j for j in range(len(xs) - 1) if xs[j] <= x)
        v = ys[i] + (x - xs[i]) * (ys[i + 1] - ys[i]) / (xs[i + 1] - xs[i])
    v = min(max(v, lo), hi)
    return int(math.floor(v + 0.5)) if rounded else v
