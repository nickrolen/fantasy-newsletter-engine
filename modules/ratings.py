"""ratings.py -- OVR, POT and the attribute grades (4a; claude/4A_RESULT_2026-11-14.md).

The numbers the new hub's player card and roster table show. Plain data out
(numbers and reasons); formatting into strings is the new hub's engine side
(modules/hub_v2/players.py). Wired in 4c1: hub_state.build computes for_today
on the run's own inputs (failing softly until the switch-over), and the
nightly's hub step appends history_line to output/ratings_history.jsonl for
every PUBLISHED run (append_history; HISTORY_RELPATH, a state file).

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

POT, "his value as a keeper" (4a4 s.2, with `history`; modules/skill.py):
next season's projected fantasy points per game -- the NBA-history estimate
(his NBA seasons, rostered or not, age-moved, regressed for a thin record,
rookies from the rookie curve by draft pick, this season blended in with
config ratings.skill.pot's weights) times m(age), the NBA aging curve's next
step -- on the FIXED scale (ratings.skill.scale: the same every year, whoever
is rostered). Its gate (_to_delete/4a4/s2/PREREG_s2.md): held-out keeper
log-likelihood -92.8 vs 4a's POT -113.5, +20.8 [+4.5, +37.9]; the NBA curve
beat the league's own (-98.4). Leave-one-decision-out chose next season alone
(next_year_weight 0). Without `history` (the draft's "then"), 4a's POT:
    V = L x m(age) x (1 + w x m(age + 1)), the league's age curve, scaled on
    today's rostered players.
DUR (4a4 s.2.4, with `history`): skill.durability on its own fixed scale;
nothing in OVR reads it.

GRADES: mid-rank percentiles among today's rostered players, letter bands
from config. Durability (A), consistency (-sd/FPPG). Schedule (4a decision
5, built in 4a2): his NBA team's games in the next 3 fantasy weeks (the
games grid's horizon: the rest of the week holding the next day, and the two
after), the count beside the letter; OVR's G stays rest-of-season.

THE SEVEN CATEGORY GRADES (4a2; 4a4 s.4: the tiles match the skills): per-game
fantasy points from the league's own categories (data/player_actuals.json
cat_days, category_season), over every game he played from the season's
first day through as_of, each count times its yahoo_settings value. THIS
SEASON ONLY (the archetype carries the history). Which categories make which
grade is config grades.categories; together they are every scoring category
exactly once, so the seven per-game values add up to his FPPG:
    scoring PTS   shooting 3PTM   playmaking AST   rebounding REB
    steals ST     blocks BLK      efficiency FGM + FGA + FTM + FTA + TO
None with a reason: "stats still loading" (the cache has no categories for
a day he played: version 1, or the backfill has not reached it), "N games:
shows after M" (grades.min_games), or a cache gap. THE TILES (config
grades.order, 4a4: nine): the seven, Consistency and Schedule. Durability
is still computed (grades["durability"] is not in the order) until 4a4 s.2.4
gives it its own rating (DUR) in the card's top section.

THE ARCHETYPE (4a4 s.3, archetypes v2; modules/archetypes.py, Nick approved
the design 11-20): a label and up to three tags from six skills blended over
his last three NBA seasons (data/historical/NBA_SEASONS.json) and this one,
standouts by percentile among today's rostered players. Computed for every
rated player when `history` is given (for_today gives it); SHOWN only when
archetype.enabled (off until Nick approves the real table).

FREE AGENTS (5b; Nick 11-20): rate_free_agents rates the Players tab's free
agents against today's rostered players (their R, scale knots and grade
values, result["basis"]), which they never move. Their FPPG, games and
availability are their whole NBA season (nba_season: data/player_actuals.json
and the schedule); the back-test covered rostered players only.

UNPROVEN PLAYERS (5b s.1a; Nick 11-20: a hot month is not proof): a player
with no league-log seasons who was neither drafted nor kept this season
(is_unproven), rostered or free, is shrunk toward config ratings.unproven's
prior (prior_quantile of the PROVEN rostered players' levels: 0.0 is their
replacement level) with its k0, and his terms are his NBA season's, so the
rule follows the player, not the roster. A judgment call (no back-test):
the settings are config. for_today applies it; the back-tests and the
draft's "then" (rate() without unproven_rule) do not.

THE BOTTOM OF THE SCALE (5b s.1b): below the rostered minimum the scale
approaches scale_min instead of clamping at it (scale()), so free agents
below every rostered player do not pile up on one number; no rostered
rating changes.

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
    ("grades", "categories"): dict,
    ("grades", "schedule_weeks"): int,
    ("archetype", "enabled"): bool,
    ("skill",): dict,
}
CATEGORY_GRADES = ("scoring", "shooting", "playmaking", "rebounding", "steals", "blocks", "efficiency")
COMPUTED_GRADES = CATEGORY_GRADES + ("durability", "consistency", "schedule")
LOADING = "stats still loading"


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
    cats = cfg["grades"]["categories"]
    if set(cats) != set(CATEGORY_GRADES):
        raise RatingsInputError(f"ratings.grades.categories must name exactly {list(CATEGORY_GRADES)}, "
                                f"not {sorted(cats)}")
    seen: dict = {}
    for gname, cs in cats.items():
        if not isinstance(cs, list) or not cs or not all(isinstance(c, str) and c for c in cs):
            raise RatingsInputError(f"ratings.grades.categories.{gname} must be a list of category names")
        for c in cs:
            if c in seen:
                raise RatingsInputError(f"ratings.grades.categories: {c} is in both {seen[c]} and {gname}")
            seen[c] = gname
    missing = [g for g in CATEGORY_GRADES if not isinstance(cfg["grades"]["min_games"].get(g), int)
               or cfg["grades"]["min_games"][g] < 1]
    if missing:
        raise RatingsInputError(f"ratings.grades.min_games has no whole number of at least 1 for {missing}")
    if cfg["grades"]["schedule_weeks"] < 1:
        raise RatingsInputError("ratings.grades.schedule_weeks must be at least 1")
    from . import archetypes as AR, skill as SK
    try:
        AR.check(cfg["archetype"], cats)
        sp = SK.check(skill_config(cfg, "pot"))
        w = sp.get("next_year_weight")
        if not isinstance(w, (int, float)) or isinstance(w, bool) or not 0 <= w <= 1:
            raise SK.SkillError("missing or malformed config: ['ratings.skill.pot.next_year_weight']")
    except (AR.ArchetypeError, SK.SkillError) as e:
        raise RatingsInputError(str(e)) from None
    sk = cfg["skill"]
    pg = sk.get("provisional_games")
    if not isinstance(pg, int) or isinstance(pg, bool) or pg < 0:
        raise RatingsInputError("missing or malformed config: ['ratings.skill.provisional_games']")
    try:
        SK.check(skill_config(cfg, "ovr"))
    except SK.SkillError as e:
        raise RatingsInputError(str(e)) from None
    return cfg


def skill_config(cfg: dict, use: str) -> dict:
    """ratings.skill with one use's weights on top (4a4 s.2): "pot" (the POT
    gate's validated weights) or "ovr" (only once a skill OVR is approved)."""
    sk = cfg.get("skill")
    if not isinstance(sk, dict) or not isinstance(sk.get(use), dict):
        raise RatingsInputError(f"ratings.skill.{use} is missing (4a4 s.2: the estimate's weights for {use})")
    return dict({k: v for k, v in sk.items() if k not in ("pot", "ovr")}, **sk[use])


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
    top segment (clamped at hi), rounded half up. Monotone non-decreasing:
    knots with equal composites keep the lowest rating.

    BELOW THE FIRST KNOT (5b s.1b: free agents below the rostered minimum,
    Nick 11-20): not a straight line clamped at lo, where many would tie at
    the floor, but a curve with the bottom segment's slope at the knot that
    approaches lo and never reaches it,
        y0 - (y0 - lo) x (1 - exp(slope x (value - x0) / (y0 - lo)))
    so distinct composites keep distinct (unrounded) values. Every rostered
    player is at or above the first knot (it is their 0th percentile), so
    no rostered rating changes."""
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
        slope = (y1 - y0) / (x1 - x0)
        if value < xs[0] and slope > 0 and y0 > lo:
            v = y0 - (y0 - lo) * (1.0 - math.exp(slope * (value - x0) / (y0 - lo)))
        else:
            v = y0 + (value - x0) * slope
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
# the schedule grade's horizon (4a decision 5) and the category grades (4a2)
# ---------------------------------------------------------------------------

def schedule_horizon(as_of: str, weeks: list, n_weeks: int) -> Optional[tuple]:
    """(first, last) ISO days the schedule grade counts: from the day after
    as_of through the end of the n_weeks-th fantasy week, counting the week
    that holds that day as the first -- the hub's games grid (the rest of
    this week, next week, the week after). Before week 1: from week 1. None
    when no fantasy week remains."""
    ws = sorted(((str(w["start_date"])[:10], str(w["end_date"])[:10]) for w in weeks), key=lambda t: t[0])
    if not ws:
        raise RatingsInputError("no fantasy weeks for the schedule grade")
    nxt = (date.fromisoformat(as_of) + timedelta(days=1)).isoformat()
    idx = next((i for i, (a, b) in enumerate(ws) if nxt <= b), None)
    if idx is None:
        return None
    return nxt, ws[min(idx + n_weeks - 1, len(ws) - 1)][1]


def category_value(totals: dict, games: int, cats: list, values: dict) -> float:
    """Per-game fantasy points from these categories."""
    return sum(totals[c] * values[c] for c in cats) / games


def _category_inputs(actuals: Optional[dict], cfg: dict):
    """(header values by category, or None) and a partition check against
    the cache's own categories."""
    if actuals is None or actuals.get("cats") is None:
        return None
    h = actuals["cats"]
    order = list(h["order"])
    used = [c for g in CATEGORY_GRADES for c in cfg["grades"]["categories"][g]]
    if sorted(used) != sorted(order):
        raise RatingsInputError(f"ratings.grades.categories use {sorted(used)}; the league's scoring "
                                f"categories (data/player_actuals.json cats.order) are {sorted(order)}: "
                                "each must be in exactly one grade")
    return dict(zip(order, (float(v) for v in h["values"])))


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

def is_unproven(c) -> bool:
    """5b s.1a (Nick, 11-20): UNPROVEN = no league-log seasons (prev_lines:
    his last three seasons, rostered days only) and neither drafted nor kept
    this season. A drafted player with no history (a manager judged him
    worth a pick) and every player with league history keep keepability v3's
    level. The rule follows the player, not the roster."""
    return not c.prev_lines and bool(c.undrafted)


def shrink(fppg, games: int, prior: float, k0: float) -> float:
    """FPPG so far shrunk toward a prior, w = games / (games + k0); the prior
    itself with no games (keepability_v3.level_of's rule)."""
    k = int(games or 0)
    if not k or fppg is None:
        return float(prior)
    w = k / (k + float(k0))
    return w * float(fppg) + (1.0 - w) * float(prior)


def nba_season(actuals: dict, dates_by_team: dict, as_of: str) -> Callable:
    """(name, team) -> {"games", "fppg", "team_games", "scores"} from
    data/player_actuals.json: every NBA game he played from the season's
    first day through as_of, on a league roster or not (the FPPG tile's
    definition), and his NBA team's games over the same days (the engine's
    schedule; a player traded since counts his current team's). None when
    his daily lines do not cover every one of those days, or the team is not
    in the schedule."""
    from . import player_actuals as pa
    first = date.fromisoformat(actuals["first_day"])
    days_iso = [d.isoformat() for d in pa.days_between(first, date.fromisoformat(as_of))]
    lo = first.isoformat()

    def f(name: str, team: Optional[str]) -> Optional[dict]:
        if not team or team not in dates_by_team:
            return None
        days = pa.find_days(actuals, name)
        if days is None or any(d not in days for d in days_iso):
            return None
        scores = [float(days[d][0]) for d in days_iso if int(days[d][1]) == 1]
        tg = sum(1 for d in dates_by_team[team] if lo <= d <= as_of)
        return {"games": len(scores), "fppg": (sum(scores) / len(scores)) if scores else None,
                "team_games": tg, "scores": scores}
    return f


UNPROVEN_PRIOR = "replacement level (the proven rostered players' level, quantile {q:g})"


def rate(snap, inputs, dates_by_team: dict, last_day: str, cfg: Optional[dict] = None,
         level_prior: Optional[dict] = None, previous: Optional[dict] = None,
         actuals: Optional[dict] = None, weeks: Optional[list] = None,
         unproven_rule: bool = False, nba: Optional[Callable] = None, history=None) -> dict:
    """Ratings for every candidate of a keeper_history Snapshot (point in time:
    only log rows dated on or before snap.as_of are read). dates_by_team: the
    season's NBA games by team; last_day: the last day games remaining count.
    previous: {player: last week's published OVR} for the weekly change.
    actuals: data/player_actuals.json (the category grades; None: no
    per-category stats for this day). weeks: config/SCHEDULE.json's weeks
    (the schedule grade's horizon; None: no schedule grade).
    unproven_rule (5b s.1a; the live ratings, for_today, set it; the
    back-tests and the draft's "then" leave it off): an unproven player
    (is_unproven) is shrunk toward ratings.unproven's prior with its k0, and
    with nba (nba_season) his FPPG, games, team games and game scores are
    his whole NBA season's, as a free agent's are, so his OVR does not jump
    when he is picked up. result["basis"] (in memory only) is what
    rate_free_agents rates free agents against.
    history (4a4 s.3; nba_prior.History): the NBA seasons the archetype
    blends with this season (None: no archetype, its reason says so).
    Returns {"as_of", "season", "universe", "replacement_level", "knots": {...},
    "players": {name: {...}}, "history_unmatched": [names the file could not place]}."""
    from . import keeper_history as kh
    from . import keepability_v3 as M
    cfg = config(cfg)
    uc = cfg.get("unproven")                  # 5b's rule: retired by 4a4 (config removed); history=None only
    if unproven_rule and uc is None:
        raise RatingsInputError("unproven_rule needs ratings.unproven, retired by 4a4: the skill OVR (history) "
                                "rates every player from his NBA record or the rookie curve")
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
        games, team_games, fppg, src = c.games, c.team_games, c.fppg, "league log"
        unp = bool(unproven_rule) and is_unproven(c)
        if unp and nba is not None:
            st = nba(c.player, team)
            if st is not None:
                games, team_games, fppg, src = st["games"], st["team_games"], st["fppg"], "NBA season"
                scores = list(st["scores"])
        sd = statistics.pstdev(scores) if len(scores) >= 2 else None
        if unp:
            L, prior, k0, kind = None, None, float(uc["k0"]), None          # below, once the prior is known
        else:
            L, prior, k0, kind, _used = M.level_of(c, lp)
            L, prior, k0 = float(L), float(prior), float(k0)
        pg, ptg = prior_av(c.player)
        A = availability(games, team_games, pg, ptg, mean_av, oc["availability_k0"],
                         oc["availability_prior_min_team_games"])
        if not team:
            G, g_reason = None, ("not on the league log's last day yet: OVR from his first logged day"
                                 if not today_rows else "no NBA team in the log")
        elif team not in dates_by_team:
            raise RatingsInputError(f"{c.player}: team {team!r} is not in the NBA schedule")
        else:
            G, g_reason = sum(1 for d in dates_by_team[team] if as_of < d <= last_day), None
        base[c.player] = {"c": c, "team": team, "L": L, "A": A, "G": G, "g_reason": g_reason,
                          "sd": sd, "n": len(scores), "games": games, "team_games": team_games,
                          "fppg": fppg, "source": src, "unproven": unp, "prior": prior, "k0": k0,
                          "prior_kind": kind}

    # 5b s.1a: the unproven players' prior, from the proven rostered players only
    proven = [b["L"] for b in base.values() if not b["unproven"]]
    u_prior = quantile(proven, uc["prior_quantile"]) if (proven and uc is not None) else None
    for b in base.values():
        if b["unproven"]:
            if u_prior is None:
                raise RatingsInputError("no proven rostered player to set the unproven players' prior")
            b["L"] = shrink(b["fppg"], b["games"], u_prior, uc["k0"])
            b["prior"], b["prior_kind"] = u_prior, UNPROVEN_PRIOR.format(q=uc["prior_quantile"])

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

    # POT: 4a4 (history given) the NBA-history estimate moved one season along
    # the NBA aging curve, on the fixed scale; without history, 4a's
    skill_on = history is not None
    if skill_on:
        sx = _skill_ctx(history, season, cfg)
        for b in base.values():
            c = b["c"]
            st = nba(c.player, b["team"]) if nba is not None else None
            g_, f_, tg_ = ((st["games"], st["fppg"], st["team_games"]) if st is not None
                           else (b["games"], b["fppg"], b["team_games"]))
            b["skill"] = _skill_of(c.player, season, c.age, g_, f_, tg_, history, sx)
            b["V"], b["v_reason"] = b["skill"]["V"], b["skill"]["v_reason"]
        pot_knots = None
    else:
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
    raw: dict = {k: {} for k in COMPUTED_GRADES}
    why: dict = {k: {} for k in COMPUTED_GRADES}
    horizon = schedule_horizon(as_of, weeks, g["schedule_weeks"]) if weeks is not None else None
    values = _category_inputs(actuals, cfg)
    if actuals is not None:
        from . import player_actuals as pa
        cat_first = date.fromisoformat(actuals["first_day"])
        cat_through = date.fromisoformat(as_of)
    cat_season = {}
    for name, b in base.items():
        # the seven category grades (4a2; 4a4 s.4)
        if actuals is None:
            reason = "no per-category stats for this day"
            cs = None
        else:
            cs = pa.category_season(actuals, name, cat_first, cat_through)
            reason = {"loading": LOADING,
                      "not_cached": "no daily lines cached for him",
                      "gap": f"his daily lines are not fetched for {cs['day']}"}.get(cs["status"])
        cat_season[name] = cs if reason is None else None
        for attr in CATEGORY_GRADES:
            need = g["min_games"][attr]
            if reason is None and cs["games"] < need:
                raw[attr][name], why[attr][name] = None, f"{cs['games']} games: shows after {need}"
            elif reason is None:
                raw[attr][name] = category_value(cs["totals"], cs["games"], g["categories"][attr], values)
            else:
                raw[attr][name], why[attr][name] = None, reason
        need = g["min_team_games"].get("durability", 0)
        if b["team_games"] >= need:
            raw["durability"][name] = b["A"]
        else:
            raw["durability"][name] = None
            why["durability"][name] = f"{b['team_games']} team games: shows after {need}"
        need = g["min_games"].get("consistency", 0)
        if b["n"] >= max(need, 2) and b["fppg"] and b["fppg"] > 0 and b["sd"] is not None:
            raw["consistency"][name] = -b["sd"] / b["fppg"]
        else:
            raw["consistency"][name] = None
            why["consistency"][name] = f"{b['n']} games: shows after {max(need, 2)}"
        # schedule (4a decision 5): games in the next schedule_weeks fantasy weeks
        if weeks is None:
            raw["schedule"][name], why["schedule"][name] = None, "no fantasy weeks given"
        elif not b["team"]:
            raw["schedule"][name], why["schedule"][name] = None, b["g_reason"]
        elif horizon is None:
            raw["schedule"][name], why["schedule"][name] = None, "no fantasy weeks remain"
        else:
            raw["schedule"][name] = sum(1 for d in dates_by_team[b["team"]] if horizon[0] <= d <= horizon[1])
    pcts = {k: percentiles(v) for k, v in raw.items()}

    # the archetype (4a4 s.3): every rostered player's blend, then percentiles among them
    arch_in = ({name: _arch_input(name, season, cat_season.get(name), history, values, cfg) for name in base}
               if history is not None else {})
    arch_ref = _arch_reference(arch_in)

    players = {}
    for name, b in sorted(base.items()):
        c = b["c"]
        if skill_on:                                  # 4a4: the skill OVR on the fixed scale
            ovr, ovr_reason = b["skill"]["ovr"], (None if b["skill"]["ovr"] is not None else UNMATCHED)
        elif b["C"] is None:
            ovr, ovr_reason = None, b["g_reason"]
        elif season_over:
            ovr, ovr_reason = None, "no games remain this season"
        else:
            ovr, ovr_reason = scale(b["C"], ovr_knots, cfg["scale_min"], cfg["scale_max"]), None
        prev = (previous or {}).get(name)
        change = (ovr - int(prev)) if (ovr is not None and prev is not None) else None
        if skill_on:
            pot = b["skill"]["pot"]
        else:
            pot = None if b["V"] is None else scale(b["V"], pot_knots, cfg["scale_min"], cfg["scale_max"])
        grades = {}
        for attr in g["order"]:
            if attr in COMPUTED_GRADES and attr not in g["unavailable"]:
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
            "ovr_composite": b["skill"]["E_ovr"] if skill_on else b["C"],
            "pot": pot, "pot_reason": b["v_reason"], "pot_value": b["V"],
            "components": {"level": b["L"], "availability": b["A"], "games_remaining": b["G"],
                           "game_sd": b["S"], "games": b["games"], "team_games": b["team_games"],
                           "fppg": b["fppg"], "age": c.age, "unproven": b["unproven"], "prior": b["prior"],
                           "prior_kind": b["prior_kind"], "k0": b["k0"], "source": b["source"]},
            "grades": grades,
        }
        if skill_on:
            players[name].update(_skill_fields(b["skill"]))
        players[name].update(_archetype_result(arch_in.get(name), arch_ref, cfg, history is not None, name))
    if skill_on:
        assign_stars(players, None, cfg)
    basis = {"cfg": cfg, "lp": lp, "R": R, "unproven_prior": u_prior, "mean_av": mean_av, "sd_med": sd_med,
             "league_mean": cands[0].league_mean if cands else None, "season_over": season_over,
             "dates_by_team": dates_by_team, "horizon": horizon, "values": values, "actuals": actuals,
             "previous": dict(previous or {}), "raw": {k: {n: v for n, v in raw[k].items() if v is not None}
                                                      for k in COMPUTED_GRADES},
             "history": history, "arch_ref": arch_ref, "skill_ctx": sx if skill_on else None,
             "unproven_rule": bool(unproven_rule)}
    return {"as_of": as_of, "season": season, "last_day": last_day, "universe": len(players),
            "replacement_level": R, "knots": {"ovr": ovr_knots, "pot": pot_knots},
            "schedule_horizon": list(horizon) if horizon else None, "players": players,
            "free_agents": None, "basis": basis,
            "history_unmatched": history.unmatched() if history is not None else []}


# ---------------------------------------------------------------------------
# free agents (5b; Nick 11-20: "Free agents should definitely have OVR and POT")
# ---------------------------------------------------------------------------

def pct_among(values, v: float) -> float:
    """v's percentile among `values` (the rostered players'), the mid-rank
    rule percentiles() uses: 100 x (below + half the ties) / n. A rostered
    player's own value gives exactly his rostered percentile."""
    xs = list(values)
    below = sum(1 for x in xs if x < v)
    eq = sum(1 for x in xs if x == v)
    return 100.0 * (below + 0.5 * eq) / len(xs)


def rate_free_agents(result: dict, specs: list) -> dict:
    """{name: the same shape as result["players"]} for free agents, rated
    AGAINST TODAY'S ROSTERED PLAYERS: their R, their scale knots and their
    grade values (result["basis"]), none of which a free agent moves. The
    same formula and config as a rostered player's (rate), except:
      FPPG, games  his whole NBA season (nba_season), not rostered days
      A            his NBA games / his team's games this season (k0 and A0
                   as for everyone: A0 his last three league seasons, else
                   the rostered mean)
      L            keepability v3's level (his league history), or, when he
                   is unproven (no league seasons, not drafted this season),
                   ratings.unproven's prior and k0 -- exactly as a rostered
                   unproven player
    Grades are his percentiles among the rostered players (the same bands
    and minimum games). specs: free_agent_specs(). A spec with a "reason"
    is not rated: OVR and POT None with that reason."""
    from types import SimpleNamespace
    from . import keepability_v3 as M
    bs = result["basis"]
    cfg = bs["cfg"]
    oc, pc, g, uc = cfg["ovr"], cfg["pot"], cfg["grades"], cfg.get("unproven")
    as_of, last_day = result["as_of"], result["last_day"]
    dbt = bs["dates_by_team"]
    kn_o, kn_p = result["knots"]["ovr"], result["knots"]["pot"]
    R = bs["R"]
    horizon = bs["horizon"]
    actuals = bs["actuals"]
    out = {}
    for sp in sorted(specs, key=lambda z: z["name"]):
        name, team = sp["name"], sp.get("team")
        reason = sp.get("reason")
        if reason is None and team not in dbt:
            reason = f"his NBA team {team!r} is not in the schedule" if team else "no NBA team on record"
        if reason is not None:
            out[name] = _unrated_fa(name, team, sp.get("age"), reason, g, cfg)
            continue
        games, fppg, tg, scores = sp["games"], sp["fppg"], sp["team_games"], list(sp["scores"])
        # 5b's rule, only where rate() applied it to the rostered players (4a's OVR with
        # unproven_rule; retired by 4a4, whose skill OVR rates rookies from the draft slot)
        unp = bs["unproven_rule"] and (not sp["prev_lines"] and not sp["drafted"]) and bs["skill_ctx"] is None
        if unp:
            if bs["unproven_prior"] is None:
                raise RatingsInputError("no unproven prior: rate() found no proven rostered player")
            L = shrink(fppg, games, bs["unproven_prior"], uc["k0"])
            prior, k0, kind = bs["unproven_prior"], float(uc["k0"]), UNPROVEN_PRIOR.format(q=uc["prior_quantile"])
        else:
            c = SimpleNamespace(player=name, season=result["season"], prev_lines=list(sp["prev_lines"]),
                                league_mean=bs["league_mean"], games=games, fppg=fppg)
            L, prior, k0, kind, _u = M.level_of(c, bs["lp"])
            L, prior, k0 = float(L), float(prior), float(k0)
        pg, ptg = sp["prior_av"]
        A = availability(games, tg, pg, ptg, bs["mean_av"], oc["availability_k0"],
                         oc["availability_prior_min_team_games"])
        G = sum(1 for d in dbt[team] if as_of < d <= last_day)
        sd = statistics.pstdev(scores) if len(scores) >= 2 else None
        S = ((len(scores) * sd + oc["sd_k0_games"] * bs["sd_med"]) / (len(scores) + oc["sd_k0_games"])
             if sd is not None else bs["sd_med"])
        C = composite(A, G, L, R, oc["consistency_penalty"], S)
        if bs["season_over"] and bs.get("skill_ctx") is None:
            ovr, ovr_reason = None, "no games remain this season"
        elif bs.get("skill_ctx") is None and kn_o is None:
            ovr, ovr_reason = None, "no rostered player is rated"
        elif bs.get("skill_ctx") is None:
            ovr, ovr_reason = scale(C, kn_o, cfg["scale_min"], cfg["scale_max"]), None
        else:
            ovr, ovr_reason = None, None                     # 4a4: set below from the skill estimate
        age = sp.get("age")
        sk_fa = None
        if bs.get("skill_ctx") is not None:                       # 4a4: the skill OVR and the NBA-history POT
            sk_fa = _skill_of(name, result["season"], age, games, fppg, tg, bs["history"], bs["skill_ctx"])
            V, pot, v_reason = sk_fa["V"], sk_fa["pot"], sk_fa["v_reason"]
            ovr, ovr_reason = sk_fa["ovr"], (None if sk_fa["ovr"] is not None else UNMATCHED)
            C = sk_fa["E_ovr"]
        elif age is None:
            V, pot, v_reason = None, None, "no age on record"
        else:
            V = pot_value(L, age, pc["age_curve"], pc["next_year_weight"])
            pot, v_reason = (None, "no rostered player is rated") if kn_p is None else \
                (scale(V, kn_p, cfg["scale_min"], cfg["scale_max"]), None)
        prev = bs["previous"].get(name)
        change = (ovr - int(prev)) if (ovr is not None and prev is not None) else None
        # grades: his value, then its percentile among the rostered players
        vals, why = {}, {}
        if actuals is None:
            cs, creason = None, "no per-category stats for this day"
        else:
            from . import player_actuals as pa
            cs = pa.category_season(actuals, name, date.fromisoformat(actuals["first_day"]),
                                    date.fromisoformat(as_of))
            creason = {"loading": LOADING, "not_cached": "no daily lines cached for him",
                       "gap": f"his daily lines are not fetched for {cs['day']}"}.get(cs["status"])
        for attr in CATEGORY_GRADES:
            need = g["min_games"][attr]
            if creason is None and cs["games"] < need:
                why[attr] = f"{cs['games']} games: shows after {need}"
            elif creason is None:
                vals[attr] = category_value(cs["totals"], cs["games"], g["categories"][attr], bs["values"])
            else:
                why[attr] = creason
        need = g["min_team_games"].get("durability", 0)
        if tg >= need:
            vals["durability"] = A
        else:
            why["durability"] = f"{tg} team games: shows after {need}"
        need = max(g["min_games"].get("consistency", 0), 2)
        if len(scores) >= need and fppg and fppg > 0 and sd is not None:
            vals["consistency"] = -sd / fppg
        else:
            why["consistency"] = f"{len(scores)} games: shows after {need}"
        if horizon is None:
            why["schedule"] = "no fantasy weeks remain"
        else:
            vals["schedule"] = sum(1 for d in dbt[team] if horizon[0] <= d <= horizon[1])
        grades = {}
        for attr in g["order"]:
            if attr in COMPUTED_GRADES and attr not in g["unavailable"]:
                ref = bs["raw"][attr]
                if attr in vals and ref:
                    p = pct_among(ref.values(), vals[attr])
                    grades[attr] = {"letter": letter(p, cfg["grade_bands"]), "percentile": p,
                                    "value": vals[attr], "reason": None}
                else:
                    grades[attr] = {"letter": None, "percentile": None, "value": None,
                                    "reason": why.get(attr) or "no rostered player has this grade"}
            else:
                grades[attr] = {"letter": None, "percentile": None, "value": None,
                                "reason": g["unavailable"][attr]}
        out[name] = {
            "player": name, "manager": "", "nba_team": team, "free_agent": True,
            "ovr": ovr, "ovr_reason": ovr_reason, "ovr_change": change, "ovr_composite": C,
            "pot": pot, "pot_reason": v_reason, "pot_value": V,
            "components": {"level": L, "availability": A, "games_remaining": G, "game_sd": S,
                           "games": games, "team_games": tg, "fppg": fppg, "age": age, "unproven": unp,
                           "prior": prior, "prior_kind": kind, "k0": k0, "source": "NBA season"},
            "grades": grades}
        if sk_fa is not None:
            out[name].update(_skill_fields(sk_fa))
        hist = bs["history"]
        arch = (_arch_input(name, result["season"], cs if creason is None else None, hist, bs["values"], cfg)
                if hist is not None else None)
        out[name].update(_archetype_result(arch, bs["arch_ref"], cfg, hist is not None))
    if bs["history"] is not None:
        result["history_unmatched"] = bs["history"].unmatched()
    if bs.get("skill_ctx") is not None:
        assign_stars(result["players"], out, cfg)            # rostered and free agents together
    return out


def _unrated_fa(name, team, age, reason, g, cfg) -> dict:
    grades = {attr: {"letter": None, "percentile": None, "value": None,
                     "reason": g["unavailable"][attr] if (attr not in COMPUTED_GRADES or attr in g["unavailable"])
                     else reason} for attr in g["order"]}
    out = {"player": name, "manager": "", "nba_team": team, "free_agent": True,
           "ovr": None, "ovr_reason": reason, "ovr_change": None, "ovr_composite": None,
           "pot": None, "pot_reason": reason, "pot_value": None, "components": {"age": age}, "grades": grades}
    out.update({"archetype": None, "archetype_reason": reason, "archetype_enabled": bool(cfg["archetype"]["enabled"])})
    return out


def free_agent_specs(names, team_of: dict, inputs, season: str, actuals: dict, dates_by_team: dict,
                     as_of: str, ages: Optional[dict] = None) -> list:
    """rate_free_agents' inputs for these free agents (5b): his NBA season
    from data/player_actuals.json (nba_season), his league history (the same
    previous_lines and prior availability a rostered player's come from),
    whether he was drafted or kept this season (the draft in the live
    inputs: a drafted player keeps keepability v3's level, s.1a), and his
    age (basketball-reference, as every rostered player's; None: no age).
    team_of: {name: his NBA team or None}. A free agent the inputs cannot
    rate carries a "reason"."""
    from . import keeper_history as kh
    from .data_loader import PlayerIndex
    back = kh.previous_lines(inputs, season)
    prior_av = prior_availability(inputs, season)
    names_log = kh.Names(inputs.log.get(season, []))
    picked = {}
    for pk in inputs.picks.get(season, []):
        n = names_log.canon(pk["player_name"], pk.get("player_key")) or pk["player_name"]
        picked[n] = pk
    pick_idx = PlayerIndex({n: n for n in picked})
    stats = nba_season(actuals, dates_by_team, as_of)
    out = []
    for n in names:
        team = team_of.get(n)
        age = None
        if ages is not None:
            try:
                age = kh.age_for(ages, season, n)[0]
            except kh.AgeNotFound:
                age = None
        sp = {"name": n, "team": team, "age": age}
        if not team:
            sp["reason"] = "no NBA team on record"
        elif team not in dates_by_team:
            sp["reason"] = f"his NBA team {team!r} is not in the schedule"
        else:
            st = stats(n, team)
            if st is None:
                sp["reason"] = f"his daily NBA lines are not cached through {as_of}"
            else:
                sp.update(st)
                sp["prev_lines"] = back(n)
                sp["prior_av"] = prior_av(n)
                sp["drafted"] = pick_idx.canonical(n) is not None
        out.append(sp)
    return out


# ---------------------------------------------------------------------------
# the NBA-history estimate: POT and DUR (4a4 s.2; modules/skill.py)
# ---------------------------------------------------------------------------

def _skill_ctx(history, season: str, cfg: dict) -> dict:
    """What every player's estimate this season shares: the POT weights, the
    baselines by experience and the rookie curve (point in time: seasons and
    drafts before `season`). Cached on the history object."""
    from . import skill as SK
    key = ("skill_ctx", season)
    cache = history.__dict__.setdefault("_ctx", {})
    if key not in cache:
        sc = skill_config(cfg, "pot")
        if getattr(history, "drafts", None) is None:
            raise RatingsInputError("POT needs data/historical/NBA_DRAFTS.json (the rookie curve): run python "
                                    "scripts/fetch_nba_seasons.py --drafts")
        P = history.blob["players"]
        try:
            cache[key] = {"sc": sc, "sco": skill_config(cfg, "ovr"), "prov": int(cfg["skill"]["provisional_games"]),
                          "base": SK.baseline_table(P, history.values, season, sc),
                          "rc": SK.fit_rookie_curve(SK.rookie_rows(P, history.drafts, history.values), season, sc),
                          "scale": sc["scale"]["anchors"], "dur": sc["durability"]["anchors"]}
        except SK.SkillError as e:
            raise RatingsInputError(f"the NBA-history estimate: {e}") from None
    return cache[key]


def _skill_of(name: str, season: str, age, g, f, tg, history, sx: dict) -> dict:
    """One player's POT and DUR: {"E", "V", "pot", "v_reason", "dur", "dur_value", "kind", "share", "pick"}.
    g, f, tg: his games, FPPG and team games this season (his NBA season)."""
    from . import skill as SK
    sc = sx["sc"]
    pid, how = history.index.resolve(name)
    if how == "unmatched":
        history._unmatched.add(name)
        return {"E": None, "V": None, "pot": None, "v_reason": UNMATCHED, "dur": None, "dur_value": None,
                "kind": None, "share": None, "pick": None, "E_ovr": None, "ovr": None, "share_ovr": None,
                "provisional": None, "career_games": None, "g": g, "f": f}
    entry = history.blob["players"].get(pid) if pid else None
    d = (history.drafts.get("players") or {}).get(pid) if pid else None
    pick = None if d is None else int(d["pick"])
    est = SK.estimate(entry, season, age, g, f, history.values, sc, sx["base"], sx["rc"], pick)
    eo = SK.estimate(entry, season, age, g, f, history.values, sx["sco"], sx["base"], sx["rc"], pick)
    du = SK.durability(entry, season, g, tg, sc)
    career = sum(int((entry or {})["seasons"][s]["gp"]) for s in SK.played(entry, season)) if entry else 0
    out = {"E": est["E"], "kind": est["kind"], "share": est["share"], "pick": pick,
           "dur_value": du["A"], "dur": SK.to_rating(du["A"], sx["dur"]),
           "E_ovr": eo["E"], "ovr": SK.to_rating(eo["E"], sx["scale"]), "share_ovr": eo["share"],
           "career_games": career, "provisional": (career + int(g or 0)) < sx["prov"], "g": int(g or 0), "f": f}
    if age is None:
        out.update(V=None, pot=None, v_reason="no age on record")
    else:
        w = float(sc["next_year_weight"])
        m1 = SK.age_step(age, sc["age_curve"])
        V = est["E"] * m1 * (1.0 + w * SK.age_step(age + 1, sc["age_curve"])) / (1.0 + w)
        out.update(V=V, pot=SK.to_rating(V, sx["scale"]), v_reason=None)
    return out


def _skill_fields(sk: dict) -> dict:
    return {"dur": sk["dur"], "dur_value": sk["dur_value"], "ovr_provisional": sk["provisional"],
            "skill": {"estimate": sk["E_ovr"], "estimate_pot": sk["E"], "kind": sk["kind"],
                      "share": sk["share_ovr"], "share_pot": sk["share"], "pick": sk["pick"],
                      "career_games": sk["career_games"], "games": sk["g"], "fppg": sk["f"]}}


def assign_stars(players: dict, fas: Optional[dict], cfg: dict) -> list:
    """The archetype's two QUALITY rules (Nick, 11-20), on top of the style
    labels:
    - Franchise Star: the star_count highest OVRs in the league, rostered or
      free agent (ties by the estimate underneath), among players who have
      played this season: at least min(star_min_games, ceil(star_min_share x
      the most games anyone in the pool has played)). The star's style label
      becomes his first tag.
    - No standout skill: All-Around when his OVR is at or above the fixed
      all_around_ovr (75; Nick, 11-20, replacing the rostered median), else
      Role Player.
    Idempotent: each archetype keeps its style ("style") and is rebuilt from
    it. Returns the stars' names."""
    ac = cfg["archetype"]
    pool = dict(players)
    pool.update(fas or {})
    for p in pool.values():
        a = p.get("archetype")
        if a is not None and "style" in a:
            p["archetype"] = dict(a["style"])
    cut = ac["all_around_ovr"]                  # required (archetypes.validate); never defaulted
    for p in pool.values():
        a = p.get("archetype")
        if a is None or p.get("ovr") is None or a.get("key") not in ("role", "all_around"):
            continue
        key = "all_around" if p["ovr"] >= cut else "role"
        if key != a["key"]:
            p["archetype"] = dict(a, key=key, label=ac["labels"][key], style=dict(a))
    def games(p):
        return int(((p.get("skill") or {}).get("games")) or 0)
    most = max((games(p) for p in pool.values()), default=0)
    need = min(int(ac["star_min_games"]), int(math.ceil(float(ac["star_min_share"]) * most)))
    rated = [(n, p) for n, p in pool.items()
             if p.get("archetype") is not None and p.get("ovr") is not None and games(p) >= need]
    rated.sort(key=lambda t: (-t[1]["ovr"], -(t[1].get("ovr_composite") or 0.0), t[0]))
    stars = [n for n, _p in rated[:int(ac["star_count"])]]
    for n in stars:
        p = pool[n]
        a = p["archetype"]
        cur = {k: v for k, v in a.items() if k != "style"}      # his style label, after the All-Around rule
        orig = dict(a.get("style") or cur)                      # what the next call resets to
        tags = [cur["label"]] + [t for t in cur["tags"]]
        p["archetype"] = dict(cur, key="star", label=ac["labels"]["star"], tags=tags[:3], style=orig)
    return stars


# ---------------------------------------------------------------------------
# the archetype (4a4 s.3; modules/archetypes.py)
# ---------------------------------------------------------------------------

ARCH_OFF = "off: the labels await Nick's approval of the real table (4a4)"
ARCH_NO_HISTORY = "no NBA history given (the archetype needs data/historical/NBA_SEASONS.json)"


def _arch_input(name: str, season: str, cs: Optional[dict], history, values: Optional[dict], cfg: dict) -> dict:
    """{"feat": the blended skills, efficiency and turnover share, or None; "reason";
    "trend"; "rookie"; "basis"} for one player."""
    from . import archetypes as AR
    ac = cfg["archetype"]
    cats = cfg["grades"]["categories"]
    if values is None:
        return {"feat": None, "reason": "no per-category stats for this day", "trend": None, "rookie": False}
    hist = history.per_game(name, season, list(ac["history_weights"]))
    g = int(cs["games"]) if cs is not None else 0
    this = AR.per_stat_this_season(cs["totals"], g, values) if (cs is not None and g > 0) else None
    if cs is None and hist is None:
        return {"feat": None, "reason": "his daily lines are not all cached, and no NBA history", "trend": None,
                "rookie": True}
    bl = AR.blend(this, g, None if hist is None else hist["per_stat"], ac)
    if bl is None:
        return {"feat": None, "reason": f"{g} games: labelled after {int(ac['min_games_rookie'])} (no NBA history)",
                "trend": None, "rookie": True}
    trend = AR.trend_of(None if this is None else sum(this.values()), g,
                        None if hist is None else hist["fppg"], ac)
    return {"feat": AR.features(bl["per_stat"], cats), "reason": None, "trend": trend, "rookie": hist is None,
            "basis": bl["basis"], "games": g, "hist_games": 0 if hist is None else hist["games"]}


def _arch_reference(arch_in: dict) -> dict:
    """{"vals": {feature: {name: value}}, "pcts": {feature: {name: percentile}}} over
    the rostered players with a blend: the pool every percentile (rostered and
    free agents') is taken in."""
    from . import archetypes as AR
    vals: dict = {k: {} for k in AR.SKILLS + (AR.EFFICIENCY, "to_share")}
    for name, a in arch_in.items():
        if a["feat"] is None:
            continue
        for k in vals:
            if a["feat"].get(k) is not None:
                vals[k][name] = a["feat"][k]
    return {"vals": vals, "pcts": {k: percentiles(v) for k, v in vals.items()}}


def _archetype_result(a: Optional[dict], ref: dict, cfg: dict, have_history: bool,
                      name: Optional[str] = None) -> dict:
    """{"archetype": {"key", "label", "standouts", "tags", "skills": {skill: percentile}, "basis"} or None,
    "archetype_reason", "archetype_enabled"}. name: a rostered player (his own
    percentile in the pool); None: a free agent (pct_among the pool)."""
    from . import archetypes as AR
    ac = cfg["archetype"]
    out = {"archetype": None, "archetype_reason": None, "archetype_enabled": bool(ac["enabled"])}
    if not have_history:
        out["archetype_reason"] = ARCH_NO_HISTORY
        return out
    if a is None or a["feat"] is None:
        out["archetype_reason"] = (a or {}).get("reason") or "no value"
        return out
    pcts = {}
    for k, vals in ref["vals"].items():
        v = a["feat"].get(k)
        if v is None or not vals:
            pcts[k] = None
        elif name is not None and name in ref["pcts"][k]:
            pcts[k] = ref["pcts"][k][name]
        else:
            pcts[k] = pct_among(vals.values(), v)
    names = cfg["grades"]["labels"]
    res = AR.classify({s: pcts[s] for s in AR.SKILLS}, pcts[AR.EFFICIENCY], pcts["to_share"], a["trend"],
                      a["rookie"], ac, {s: names[s] for s in AR.SKILLS})
    res["skills"] = {s: (None if pcts[s] is None else round(pcts[s], 1)) for s in AR.SKILLS}
    res["basis"] = a.get("basis")
    out["archetype"] = res
    return out


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
              history=None, *, live: Optional[tuple] = None, actuals: Optional[dict] = None,
              cfg: Optional[dict] = None) -> dict:
    """rate() on today's rosters (config/ROSTERS.json), the live log, the
    engine's NBA schedule and keepability v3's level prior. Read-only.
    live (4c1): keeper_history.live_inputs(root, history)'s (Inputs, season),
    when the caller already built it (hub_state.build shares the one its
    keep chances use: building it is ~7 of the ~8 seconds); actuals: the
    already-loaded data/player_actuals.json. Both give exactly what reading
    them here would. cfg: the "ratings" block (default: config's)."""
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
    li, season = live if live is not None else kh.live_inputs(root, history)
    ages = kh.load_ages(kh.age_seasons(), root, fetch=_nofetch)
    snap = kh.live_snapshot(li, season, rosters, ages)
    sched = load_nba_schedule(_schedule_path(root), today=today)
    if actuals is None:
        from . import player_actuals as pa
        actuals = pa.load(root)                      # required: the category grades read it
    weeks = json.loads((root / "config" / "SCHEDULE.json").read_text(encoding="utf-8")).get("weeks") or []
    dbt = team_dates(sched)
    return rate(snap, li, dbt, schedule_last_day(root), cfg=cfg, previous=previous,
                actuals=actuals, weeks=weeks, unproven_rule=False, nba=nba_season(actuals, dbt, snap.as_of),
                history=load_history(root, li.log.get(season, []), actuals))


def load_history(root, rows, actuals: dict):
    """nba_prior.History for today: data/historical/NBA_SEASONS.json and
    data/historical/NBA_DRAFTS.json (4a4),
    who is who from the live log's rows and data/player_actuals.json's name
    maps (roster_names, extra_names). A missing, unreadable or incomplete
    file RAISES (RatingsInputError naming the file and the fix): under v2 a
    ratings failure is hard, so the nightly says so instead of publishing
    cards without it."""
    from . import nba_seasons as NS, nba_prior as NP
    try:
        blob = NS.load(str(root))
    except NS.SeasonsError as e:
        raise RatingsInputError(f"the NBA history: {e}") from None
    ids = NP.ids_from_rows(rows)
    for k in ("roster_names", "extra_names"):
        for n, pid in ((actuals or {}).get(k) or {}).items():
            ids.setdefault(n, pid)
    from . import nba_drafts as ND
    try:
        drafts = ND.load(str(root))
    except ND.DraftsError as e:
        raise RatingsInputError(f"the NBA drafts: {e}") from None
    h = NP.History(blob, NS.stat_values(str(root)), ids)
    h.drafts = drafts
    return h


# ---------------------------------------------------------------------------
# the weekly history: output/ratings_history.jsonl (4a decision 9; written 4c1)
# ---------------------------------------------------------------------------

HISTORY_RELPATH = Path("output") / "ratings_history.jsonl"
TERMS = ("level", "availability", "games_remaining")
# 4a4 (s.5): each rating's definition version. A line written before 4a4 has no
# "versions" and is {"ovr": 1, "pot": 1}. OVR 2 is the skill OVR and its
# "terms" are [estimate, FPPG this season, games this season]. The weekly change only compares a
# value with a line of the SAME version (history_values), so the switch to the
# NBA-history POT starts its weekly change afresh a week later, never a
# comparison of the old meaning with the new.
HISTORY_VERSIONS = {"ovr": 2, "pot": 2, "dur": 1}
OLD_VERSIONS = {"ovr": 1, "pot": 1}


def history_values(line: Optional[dict], key: str) -> Optional[dict]:
    """{player: value} for one rating from a history line, or None when the
    line is missing, lacks it, or holds another version of it."""
    if not line or key not in line:
        return None
    if (line.get("versions") or OLD_VERSIONS).get(key) != HISTORY_VERSIONS.get(key):
        return None
    return dict(line[key] or {})


def history_line(result: dict) -> dict:
    """One line of output/ratings_history.jsonl: as_of, each player's OVR and
    POT, and (4c1) OVR's three terms [level, availability, games remaining]
    -- what the Risers' one-line reason compares a week later. 5b: the rated
    free agents too (result["free_agents"]), named in "fa" (sorted), so a
    week later the Risers' reason ranks a rostered player among the rostered
    players only. A line without "fa" (before 5b) is all rostered players."""
    everyone = dict(result["players"])
    fas = result.get("free_agents") or {}
    everyone.update(fas)
    terms = {}
    for n, p in everyone.items():
        c = p["components"]
        sk = p.get("skill")
        if sk is not None:                    # 4a4 (ovr version 2): [estimate, his FPPG this season, his games]
            if p["ovr"] is not None and sk.get("estimate") is not None:
                terms[n] = [round(float(sk["estimate"]), 3), round(float(sk["fppg"] or 0.0), 3), int(sk["games"] or 0)]
        elif p["ovr"] is not None and all(c.get(t) is not None for t in TERMS):
            terms[n] = [round(float(c["level"]), 3), round(float(c["availability"]), 4), int(c["games_remaining"])]
    line = {"as_of": result["as_of"], "season": result["season"],
            "ovr": {n: p["ovr"] for n, p in everyone.items() if p["ovr"] is not None},
            "pot": {n: p["pot"] for n, p in everyone.items() if p["pot"] is not None},
            "terms": terms, "versions": dict(HISTORY_VERSIONS)}
    dur = {n: p["dur"] for n, p in everyone.items() if p.get("dur") is not None}
    if dur:
        line["dur"] = dur
    if fas:
        line["fa"] = sorted(n for n, p in fas.items() if p["ovr"] is not None or p["pot"] is not None)
    return line


def line_from_history(lines: list, as_of: str, days: int = 7) -> Optional[dict]:
    """The latest published line at least `days` before as_of, or None (then
    there is no weekly change: no marker, never a zero)."""
    cut = (date.fromisoformat(as_of) - timedelta(days=days)).isoformat()
    older = [l for l in lines if l.get("as_of") and l["as_of"] <= cut]
    if not older:
        return None
    return max(older, key=lambda l: l["as_of"])


def previous_from_history(lines: list, as_of: str, days: int = 7, key: str = "ovr") -> Optional[dict]:
    """{player: OVR} (key="pot": POT) from the latest published line at least
    `days` before as_of, or None."""
    line = line_from_history(lines, as_of, days)
    return history_values(line, key)


def read_history(root=ROOT) -> list:
    """Every line of output/ratings_history.jsonl, oldest first; [] when the
    file does not exist yet (it is created by the first published run). A
    malformed line RAISES, naming it."""
    p = Path(root) / HISTORY_RELPATH
    if not p.is_file():
        return []
    out = []
    for i, raw in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
        if not raw.strip():
            continue
        try:
            line = json.loads(raw)
        except ValueError as e:
            raise RatingsInputError(f"{HISTORY_RELPATH.as_posix()} line {i} is not JSON: {e}") from None
        if not isinstance(line, dict) or not isinstance(line.get("as_of"), str) \
                or not isinstance(line.get("ovr"), dict):
            raise RatingsInputError(f"{HISTORY_RELPATH.as_posix()} line {i} has no as_of and ovr")
        out.append(line)
    return out


def append_history(root, line: dict) -> Optional[Path]:
    """Append one line (a published run's history_line) to
    output/ratings_history.jsonl, creating it. Append-only: nothing is ever
    rewritten. ONE LINE PER as_of (4c1 review, 11-18): when the file's last
    line already has this line's as_of (a later run the same day: the live
    log's last day has not moved), nothing is written and None is returned.
    The weekly change reads by as_of, so it is unchanged; the file is ~3x
    smaller than one line per published run."""
    p = Path(root) / HISTORY_RELPATH
    prior = read_history(root)
    if prior and prior[-1]["as_of"] == line["as_of"]:
        return None
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(line, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n")
    return p
