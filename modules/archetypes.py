"""archetypes.py -- archetypes v2: what kind of fantasy player he is (4a4 Phase B-2;
claude/HANDOFF_4A4_NBA_HISTORY_OVR_ARCHETYPES_2026-11-20.md s.3; Nick approved the
design 11-20: "I like this a lot more. Let's move forward with it").

A LABEL SAYS WHAT KIND OF PLAYER HE IS over his recent seasons and this one, NOT
how good he is (OVR says that). Pure functions; modules/ratings.py feeds them.

SIX SKILLS, each his fantasy points per game from its stats in this league's
scoring (config ratings.grades.categories, the tiles' own split):
    scoring PTS   shooting 3PTM   playmaking AST   rebounding REB   steals ST   blocks BLK
Efficiency (FGM, FGA, FTM, FTA, TO) is a TAG, not a skill.

THE BLEND (config ratings.archetype): per stat,
    value = (g x this season + H x history) / (g + H),  H = history_games (25)
  history: nba_prior.history_per_game -- his last three seasons he played,
           weighted history_weights (3 : 2 : 1, most recent first) x games;
  g: his games this season (his whole NBA season, data/player_actuals.json);
  no history (a rookie): this season alone, from min_games_rookie games (5);
  history and few games (g < 5, e.g. back from injury): the same blend, so
           at g = 0 it is history alone and at g = 2 about 93% history.

STANDOUTS: a skill whose blended value's percentile among TODAY'S ROSTERED
players is >= standout_pct (70: the top 30%). Free agents are ranked against
the rostered pool, as their grades are.

THE LABEL, from his standouts ordered by percentile (ties: SKILLS order):
    star (Franchise Star)           NOT from the skills (Nick 11-20): the
                                    star_count (4) highest OVRs in the league,
                                    rostered or free agent (ratings.assign_stars);
                                    his style label below becomes his first tag
    none                            all_around when all_around_min (3) or more
                                    skills are at or above all_around_pct (50:
                                    the rostered median), else role (Nick 11-20:
                                    Siakam, Franz, Mikal, Deni are not role players);
                                    with OVR on, ratings.assign_stars then decides it
                                    by the fixed all_around_ovr (75; 5d1)
    otherwise his best two (or one) by PAIRS below; with THREE OR MORE
    standouts the pair is chosen with pair_first's skills (Scoring,
    Playmaking) ahead of the rest, each group by percentile (Nick 11-20:
    Kyrie -> Bucket Getter, LaMelo -> Floor General, not 3-and-D).
    EXACTLY ONE key for every set (a test enumerates every set and order).
THE TAGS (at most 3, in this order):
    1. a third standout not in the label (three standouts, not a star):
       the skill's name ("Steals");
    2. efficiency: "Efficient" when his blended efficiency points per game
       are at or above efficient_pct (70th percentile); otherwise
       "Turnover-prone" when the share of his points his turnovers cost,
       -TO pts / (FPPG - TO pts), is at or above turnover_pct (85th
       percentile: the 15% who lose the most to turnovers). Proposed rule:
       turnovers alone would tag every high-usage star;
    3. trend: "Breakout" / "Down year" when this season (>= trend_min_games,
       15) is at least trend_margin (20%) above / below his history's FPPG
       (unblended: this season's FPPG / history's);
    4. "Rookie" (no NBA history), in place of the trend.
"""
from __future__ import annotations

from itertools import combinations
from typing import Dict, List, Optional, Tuple

SKILLS = ("scoring", "shooting", "playmaking", "rebounding", "steals", "blocks")
EFFICIENCY = "efficiency"
LABEL_KEYS = ("star", "engine", "general", "bucket", "shooter", "stretch", "three_d", "interior",
              "point_forward", "glass", "anchor", "hawk", "swiss", "all_around", "role")
TAG_KEYS = ("efficient", "turnover", "breakout", "down", "rookie")

# his best two standouts (or his one) -> the label; any set not listed is "swiss"
PAIRS = {
    frozenset({"scoring", "playmaking"}): "engine",
    frozenset({"playmaking"}): "general",
    frozenset({"playmaking", "shooting"}): "general",
    frozenset({"playmaking", "steals"}): "general",
    frozenset({"scoring"}): "bucket",
    frozenset({"scoring", "shooting"}): "bucket",
    frozenset({"scoring", "steals"}): "bucket",
    frozenset({"shooting"}): "shooter",
    frozenset({"shooting", "rebounding"}): "stretch",
    frozenset({"shooting", "blocks"}): "stretch",
    frozenset({"shooting", "steals"}): "three_d",
    frozenset({"scoring", "rebounding"}): "interior",
    frozenset({"scoring", "blocks"}): "interior",
    frozenset({"playmaking", "rebounding"}): "point_forward",
    frozenset({"rebounding"}): "glass",
    frozenset({"blocks"}): "anchor",
    frozenset({"blocks", "rebounding"}): "anchor",
    frozenset({"steals"}): "hawk",
    frozenset({"steals", "blocks"}): "hawk",
}


class ArchetypeError(RuntimeError):
    """A config key or input is missing or malformed; named."""


def check(ac: dict, categories: dict) -> dict:
    """config ratings.archetype, every key checked (RAISES naming the bad ones)."""
    if not isinstance(ac, dict):
        raise ArchetypeError("ratings.archetype is missing")
    bad = []

    def num(k, lo, hi, integer=False):
        v = ac.get(k)
        ok = isinstance(v, (int, float)) and not isinstance(v, bool) and lo <= v <= hi
        if integer and ok:
            ok = isinstance(v, int)
        if not ok:
            bad.append(f"ratings.archetype.{k}")
    if not isinstance(ac.get("enabled"), bool):
        bad.append("ratings.archetype.enabled")
    num("history_games", 1, 200)
    num("min_games_rookie", 1, 82, True)
    num("standout_pct", 1, 99)
    num("star_count", 1, 20, True)
    num("star_min_games", 1, 82, True)
    num("star_min_share", 0.05, 1.0)
    num("efficient_pct", 1, 99)
    num("turnover_pct", 1, 99)
    num("trend_min_games", 1, 82, True)
    num("trend_margin", 0.01, 1.0)
    num("all_around_min", 1, 6, True)
    num("all_around_pct", 1, 99)
    num("all_around_ovr", 1, 99, True)         # Nick, 11-20: a fixed OVR cutoff for All-Around (ratings.assign_stars)
    pf = ac.get("pair_first")
    if not isinstance(pf, list) or not all(x in SKILLS for x in pf) or len(set(pf)) != len(pf):
        bad.append("ratings.archetype.pair_first (skills, e.g. [\"scoring\", \"playmaking\"])")
    w = ac.get("history_weights")
    if not isinstance(w, list) or not w or not all(isinstance(x, (int, float)) and not isinstance(x, bool)
                                                    and x > 0 for x in w):
        bad.append("ratings.archetype.history_weights (positive numbers, most recent first)")
    lab = ac.get("labels")
    if not isinstance(lab, dict) or set(lab) != set(LABEL_KEYS) or not all(isinstance(v, str) and v.strip()
                                                                          for v in lab.values()):
        bad.append(f"ratings.archetype.labels (exactly {list(LABEL_KEYS)}, each a text)")
    elif len(set(lab.values())) != len(lab):
        bad.append("ratings.archetype.labels repeat a label")
    tg = ac.get("tags")
    if not isinstance(tg, dict) or set(tg) != set(TAG_KEYS) or not all(isinstance(v, str) and v.strip()
                                                                      for v in tg.values()):
        bad.append(f"ratings.archetype.tags (exactly {list(TAG_KEYS)}, each a text)")
    if not isinstance(categories, dict) or any(k not in categories for k in SKILLS + (EFFICIENCY,)):
        bad.append(f"ratings.grades.categories (needs {list(SKILLS + (EFFICIENCY,))})")
    if bad:
        raise ArchetypeError(f"missing or malformed config: {bad}")
    if "TO" not in categories[EFFICIENCY]:
        raise ArchetypeError("ratings.grades.categories.efficiency must hold TO (the turnover tag reads it)")
    return ac


def per_stat_this_season(totals: Dict[str, float], games: int, values: Dict[str, float]) -> Dict[str, float]:
    """This season's fantasy points per game by stat."""
    if games <= 0:
        raise ArchetypeError("no games this season")
    return {k: float(totals[k]) * float(v) / games for k, v in values.items()}


def blend(this: Optional[Dict[str, float]], g: int, hist: Optional[Dict[str, float]], ac: dict) -> Optional[dict]:
    """{"per_stat", "basis"} or None (a rookie below min_games_rookie, or nothing at all).
    this / hist: per-stat fantasy points per game (None: none)."""
    H = float(ac["history_games"])
    g = int(g or 0)
    if hist is None:
        if this is None or g < int(ac["min_games_rookie"]):
            return None
        return {"per_stat": dict(this), "basis": "this season"}
    if this is None or g == 0:
        return {"per_stat": dict(hist), "basis": "history"}
    return {"per_stat": {k: (g * this[k] + H * hist[k]) / (g + H) for k in hist}, "basis": "blend"}


def features(per_stat: Dict[str, float], categories: dict) -> dict:
    """{skill: points per game} for the six skills, plus efficiency and the turnover share."""
    out = {s: sum(per_stat[c] for c in categories[s]) for s in SKILLS}
    out[EFFICIENCY] = sum(per_stat[c] for c in categories[EFFICIENCY])
    to = per_stat["TO"]
    gross = sum(per_stat.values()) - to
    out["to_share"] = (-to / gross) if gross > 0 else None
    return out


def ordered_standouts(pcts: Dict[str, float], standout_pct: float) -> List[str]:
    """His standouts, best percentile first; ties by SKILLS order."""
    st = [s for s in SKILLS if pcts.get(s) is not None and pcts[s] >= standout_pct]
    return sorted(st, key=lambda s: (-pcts[s], SKILLS.index(s)))


def pair_order(standouts: List[str], pair_first: List[str]) -> List[str]:
    """With three or more standouts, pair_first's skills come ahead of the rest
    (each group keeps its percentile order); fewer: unchanged."""
    if len(standouts) < 3:
        return list(standouts)
    return [s for s in standouts if s in pair_first] + [s for s in standouts if s not in pair_first]


def label_key(standouts: List[str], n_at_median: int = 0, all_around_min: int = 3,
              pair_first: Optional[List[str]] = None) -> str:
    """The one STYLE label for an ordered list of standouts (Franchise Star is
    given by OVR, not here). n_at_median: how many skills are at or above
    all_around_pct (only read when there is no standout)."""
    if not standouts:
        return "all_around" if n_at_median >= all_around_min else "role"
    st = pair_order(standouts, list(pair_first or []))
    return PAIRS.get(frozenset(st[:2]), "swiss")


def classify(pcts: Dict[str, float], eff_pct: Optional[float], to_pct: Optional[float],
             trend: Optional[str], rookie: bool, ac: dict, skill_names: Dict[str, str]) -> dict:
    """{"key", "label", "standouts", "tags"} from the skill percentiles."""
    st = ordered_standouts(pcts, float(ac["standout_pct"]))
    n_med = sum(1 for s in SKILLS if pcts.get(s) is not None and pcts[s] >= float(ac["all_around_pct"]))
    key = label_key(st, n_med, int(ac["all_around_min"]), list(ac["pair_first"]))
    tags: List[str] = []
    if key not in ("role", "all_around") and len(st) > 2:
        tags.append(skill_names[pair_order(st, list(ac["pair_first"]))[2]])
    if eff_pct is not None and eff_pct >= float(ac["efficient_pct"]):
        tags.append(ac["tags"]["efficient"])
    elif to_pct is not None and to_pct >= float(ac["turnover_pct"]):
        tags.append(ac["tags"]["turnover"])
    if rookie:
        tags.append(ac["tags"]["rookie"])
    elif trend is not None:
        tags.append(ac["tags"][trend])
    return {"key": key, "label": ac["labels"][key], "standouts": pair_order(st, list(ac["pair_first"])),
            "tags": tags[:3]}


def trend_of(this_fppg: Optional[float], g: int, hist_fppg: Optional[float], ac: dict) -> Optional[str]:
    """"breakout", "down" or None."""
    if this_fppg is None or hist_fppg is None or hist_fppg <= 0 or int(g or 0) < int(ac["trend_min_games"]):
        return None
    r = this_fppg / hist_fppg
    if r >= 1.0 + float(ac["trend_margin"]):
        return "breakout"
    if r <= 1.0 - float(ac["trend_margin"]):
        return "down"
    return None


def every_combination(pair_first=("scoring", "playmaking")) -> List[Tuple[Tuple[str, ...], str]]:
    """(ordered standouts, style label key) for every subset of the skills in
    every order -- what the partition test checks (no standout: both
    all_around and role, by n_at_median). "star" is given by OVR, not here."""
    from itertools import permutations
    out = []
    for n in range(len(SKILLS) + 1):
        for combo in combinations(SKILLS, n):
            for perm in permutations(combo):
                if not perm:
                    out.append(((), label_key([], 3, 3, list(pair_first))))
                    out.append(((), label_key([], 2, 3, list(pair_first))))
                else:
                    out.append((perm, label_key(list(perm), 0, 3, list(pair_first))))
    return out
