"""Nick's 11 calibration scenarios for task 18b (INJURED_DROP_DESIGN.md s.5),
as hand-made stakes, rosters and keep chances -- the inputs the decision
function (modules/injured_drop) takes. Shared by tests/test_injured_drop.py
and the fit of M, F and K (fit(); scripts/fit_injured_drop.py prints it).

THE ACCEPTANCE RULES (Nick, 11-04; HANDOFF_18B_REFIT_AND_WIRE s.1):
  - PINNED, Nick's firm answers: 2, 3, 4 and 9 drop; 5 and 6 hold; 8 is a
    top-4 keeper and so protected outright;
  - DIRECTION ONLY, the "Depends" answers (pairs (weaker, stronger): if the
    weaker case drops, the stronger must drop too):
      1   a higher keep chance never makes a drop more likely,
      7   a contender is never less likely to drop than a team with little
          left to play for (and 11 the same),
      10  a bigger series stake never makes a hold more likely,
      9b  a team two games back is never more likely to drop than the tied
          team (Nick's "maybe hold if you're at a significant disadvantage");
  - the region must work on every one of SEEDS (the toy season's seed).

HOW THE STAKES ARE MADE. Each scenario's race is played out by a toy season
of four teams, A (the team deciding) and B, C, D, with this league's format
(s.5's "the race" column turned into records):
  - regular season weeks 1-15, each pair five times (the rotation AB/CD,
    AC/BD, AD/BC); title = most wins, ties by points over the weeks played
    out (the toy has no head-to-head);
  - playoffs: seeds 1 v 4 and 2 v 3, best of three, weeks 16-18; the final
    weeks 19-21; champion = the final's winner;
  - a team's week score ~ Normal(mean x g_w / 3.4, SD_7 / sqrt(2) x sqrt(g_w / 3.4)),
    g_w the NBA games per team that fantasy week (GAMES);
  - stakes read off the iterations exactly as modules/title_odds_run does
    (P(title | wins w) - P(title | loses w); margins' mean and SD).
Nothing here is tuned to the answers: every number is fixed below, with its
source, before the fit.

THE FIXED NUMBERS, and where they come from:
  SD_7 = 250     the margin SD of a 7-day week in the real 11-04 season pass
                 (median over every team and remaining week, week 7 aside);
  WEAK = 100     a long shot's weekly shortfall: the size of the real line's
                 gap, Nick -118 v Garrett (week 3, 11-04);
  GAMES          the real 2026-27 NBA schedule's games per team per fantasy
                 week (11-04), except week 7: 14 days, whose NBA-Cup-period
                 games are not in the schedule yet (task 33), so 2 x 3.4;
  STANDIN = 35.2 the stand-in level of 10-28 (roster_moves.replacement_rank);
  AVAIL = 70/82  everyone's share of games played (the pre-season prior's GP
                 is about 69-70); the same for a player and his stand-in, so
                 durability does not move any scenario;
  KEEP_BY_RANK   the published week-2 keeper watch (2026-27), keep chance at
                 K = 5 by rank on the team, the mean over the four teams.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np

from modules import injured_drop as idr

SD_7 = 250.0
WEAK = 100.0
MEAN = 1500.0
GAMES = {1: 2.87, 2: 3.27, 3: 3.6, 4: 3.4, 5: 3.4, 6: 3.2, 7: 6.8, 8: 3.67, 9: 3.53, 10: 3.47,
         11: 3.6, 12: 3.47, 13: 3.47, 14: 3.6, 15: 3.6, 16: 3.53, 17: 4.13, 18: 3.27, 19: 3.53,
         20: 3.47, 21: 3.6}
STANDIN = 35.2
AVAIL = 70.0 / 82.0
KEEP_BY_RANK = [0.932, 0.783, 0.611, 0.511, 0.397, 0.242, 0.136, 0.102, 0.077, 0.06, 0.05, 0.04,
                0.03, 0.02, 0.01]
# a 55-FPPG player "in practice a top-4 keeper" (s.5, scenario 8): a typical top-4
# keeper's chance, the mean of ranks 1-4
TOP4_TYPICAL = round(sum(KEEP_BY_RANK[:4]) / 4, 3)
TEAMS = ("A", "B", "C", "D")
LAST_REG, LAST = 15, 21
SIMS, SEED = 40000, 20261103
SEEDS = (20261103, 1, 2, 3, 4, 5)       # the fit holds on all of them (Nick, 11-04)


def pairings(week: int) -> list:
    return [[("A", "B"), ("C", "D")], [("A", "C"), ("B", "D")], [("A", "D"), ("B", "C")]][(week - 1) % 3]


def season_stakes(window: int, wins: dict, weak: tuple = (), week16: Optional[dict] = None,
                  sims: int = SIMS, seed: int = SEED) -> dict:
    """{team: TeamStakes} at `window`. wins: regular-season wins after
    window - 1 weeks (losses are the rest). For a window in the playoffs
    (week16 given): wins are the final standings and week16 {team: won week
    16}. weak: teams WEAK points a week short."""
    rng = np.random.default_rng(seed)
    n = sims
    idx = {t: i for i, t in enumerate(TEAMS)}
    mean = np.array([MEAN - (WEAK if t in weak else 0.0) for t in TEAMS])
    sd_team = SD_7 / np.sqrt(2.0)

    def scores(w):
        g = GAMES[w] / 3.4
        return mean * g + rng.standard_normal((n, 4)) * sd_team * np.sqrt(g)

    results, margins = {}, {}
    W = np.tile(np.array([float(wins[t]) for t in TEAMS]), (n, 1))
    P = np.zeros((n, 4))
    for w in range(window, LAST_REG + 1):
        sc = scores(w)
        res, mar = np.full((n, 4), np.nan), np.full((n, 4), np.nan)
        for a, b in pairings(w):
            i, j = idx[a], idx[b]
            res[:, i] = (sc[:, i] > sc[:, j]).astype(float)
            res[:, j] = 1.0 - res[:, i]
            mar[:, i], mar[:, j] = sc[:, i] - sc[:, j], sc[:, j] - sc[:, i]
        results[w], margins[w] = res, mar
        W += res
        P += sc
    # standings: most wins, then points (a stable sort on -wins after -points)
    key = W * 1e7 + P
    ranks = np.argsort(-key, axis=1)                     # [n, 4] team index by place
    title = {t: ranks[:, 0] == idx[t] for t in TEAMS}
    # playoffs, weeks 16-21
    seed_of = ranks
    first_bracket = max(window, 16)
    sw = np.zeros((n, 4))                                # semifinal week wins
    for w in range(16, 19):
        if w < first_bracket:
            # week 16 already played (a playoff window): its result is given
            for t in TEAMS:
                sw[:, idx[t]] += float(week16[t])
            continue
        sc = scores(w)
        res, mar = np.full((n, 4), np.nan), np.full((n, 4), np.nan)
        for hi, lo in ((0, 3), (1, 2)):
            a, b = seed_of[:, hi], seed_of[:, lo]
            r = np.arange(n)
            sa, sb = sc[r, a], sc[r, b]
            aw = (sa > sb).astype(float)
            res[r, a], res[r, b] = aw, 1.0 - aw
            mar[r, a], mar[r, b] = sa - sb, sb - sa
            sw[r, a] += aw
            sw[r, b] += 1.0 - aw
        results[w], margins[w] = res, mar
    r = np.arange(n)
    fin = []
    for hi, lo in ((0, 3), (1, 2)):
        a, b = seed_of[:, hi], seed_of[:, lo]
        fin.append(np.where(sw[r, a] >= 2, a, b))
    fa, fb = fin
    fw = np.zeros((n, 4))
    for w in range(19, 22):
        sc = scores(w)
        res, mar = np.full((n, 4), np.nan), np.full((n, 4), np.nan)
        sa, sb = sc[r, fa], sc[r, fb]
        aw = (sa > sb).astype(float)
        res[r, fa], res[r, fb] = aw, 1.0 - aw
        mar[r, fa], mar[r, fb] = sa - sb, sb - sa
        # the third-place series is played too: its weeks count for its teams
        # (champion leverage 0 there by construction)
        la = np.where(fa == seed_of[:, 0], seed_of[:, 3], seed_of[:, 0])   # the 1 v 4 semi's loser
        lb = np.where(fb == seed_of[:, 1], seed_of[:, 2], seed_of[:, 1])   # the 2 v 3 semi's loser
        s3a, s3b = sc[r, la], sc[r, lb]
        a3 = (s3a > s3b).astype(float)
        res[r, la], res[r, lb] = a3, 1.0 - a3
        mar[r, la], mar[r, lb] = s3a - s3b, s3b - s3a
        fw[r, fa] += aw
        fw[r, fb] += 1.0 - aw
        results[w], margins[w] = res, mar
    champ_idx = np.where(fw[r, fa] >= 2, fa, fb)
    champ = {t: champ_idx == idx[t] for t in TEAMS}

    from modules import title_odds_run as tor
    out = {}
    for t in TEAMS:
        j = idx[t]
        weeks = {}
        for w in sorted(results):
            outcome = title[t] if w <= LAST_REG else champ[t]
            lv = tor.leverage(results[w][:, j], outcome)
            ms = tor.margin_stats(margins[w][:, j])
            weeks[w] = idr.WeekStake(w, lv["leverage"] if w <= LAST_REG else None,
                                     None if w <= LAST_REG else lv["leverage"],
                                     ms["margin_mean"], ms["margin_sd"])
        out[t] = idr.TeamStakes(window_week=window, regular_season=window <= LAST_REG,
                                rs_title=float(title[t].mean()), champion=float(champ[t].mean()),
                                weeks=weeks, last_week=LAST)
    return out


def points(fppg: float, window: int, back: Optional[int]) -> dict:
    """Expected points per week, window..21: 0 before `back` (None: never)."""
    return {w: (0.0 if back is None or w < back else fppg * GAMES[w] * AVAIL)
            for w in range(window, LAST + 1)}


def keep_for(rank: Optional[int], chance: Optional[float] = None, above: Optional[list] = None) -> dict:
    """The team's keep chances, with the player 'P' at `rank` (None: rank 8,
    not a candidate). chance overrides his; above overrides those ranked
    above him."""
    rank = 8 if rank is None else rank
    vals = list(KEEP_BY_RANK)
    if chance is not None:
        vals[rank - 1] = chance
    if above is not None:
        vals[:rank - 1] = above
    names = [f"T{i}" for i in range(1, len(vals) + 1)]
    names[rank - 1] = "P"
    return dict(zip(names, vals))


@dataclass
class Scenario:
    sid: str
    note: str
    window: int
    wins: dict
    fppg: float
    out_weeks: Optional[int]              # None: out for the season
    answer: Optional[str]                 # "hold" / "drop" when PINNED; None: direction only
    rank: Optional[int] = None            # keeper rank on his team; None = not a candidate
    chance: Optional[float] = None
    above: Optional[list] = None
    weak: tuple = ()
    week16: Optional[dict] = None
    team: str = "A"
    by: str = ""                          # which part of the rule gives a pinned answer

    def back(self):
        return None if self.out_weeks is None else self.window + self.out_weeks

    def candidate(self) -> idr.Candidate:
        return idr.Candidate("P", self.back(), points(self.fppg, self.window, self.back()),
                             points(STANDIN, self.window, self.window))

    def keep(self) -> dict:
        return keep_for(self.rank, self.chance, self.above)

    def stakes(self, seed: int = SEED, cache={}) -> idr.TeamStakes:
        k = (self.window, tuple(sorted(self.wins.items())), self.weak,
             tuple(sorted((self.week16 or {}).items())), seed, SD_7, WEAK, MEAN, SIMS)
        if k not in cache:
            cache[k] = season_stakes(self.window, self.wins, self.weak, self.week16, seed=seed)
        return cache[k][self.team]


TIGHT_4 = {"A": 2, "B": 2, "C": 1, "D": 1}                 # week 4: all four within a game
TIGHT_11 = {"B": 6, "A": 5, "C": 5, "D": 4}                # week 11: A one game back of first
LEAD_12 = {"A": 9, "B": 5, "C": 4, "D": 4}                 # week 12: A leads by 4
OUT_12 = {"A": 2, "B": 8, "C": 6, "D": 6}                  # week 12: A out of the RS race
CONTEND_12 = {"A": 8, "B": 7, "C": 4, "D": 3}              # week 12: A leads a live race by 1
MID_6 = {"B": 4, "A": 3, "C": 2, "D": 1}                   # week 6: A mid-pack
TIED_14 = {"A": 9, "B": 9, "C": 4, "D": 4}                 # week 14: tied for first, 2 left
BEHIND_14 = {"B": 9, "A": 7, "C": 5, "D": 5}               # week 14: A two back, 2 left
FINAL_15 = {"A": 11, "B": 8, "C": 6, "D": 5}               # the final standings: A seed 1
CONTEND_5 = {"A": 4, "B": 2, "C": 1, "D": 1}               # week 5: A 4-0
BAD_5 = {"A": 0, "B": 4, "C": 2, "D": 2}                   # week 5: A 0-4
WON_16 = {"A": 1, "D": 0, "B": 1, "C": 0}                  # A (seed 1) won week 16 of his semi
LOST_16 = {"A": 0, "D": 1, "B": 1, "C": 0}                 # A lost it: a bigger series stake


def scenarios() -> list:
    """Every scenario of s.5 and the variants its direction checks compare."""
    S = Scenario
    return [
        S("1b", "week 4, tight, 41 FPPG, out 4, no keeper chance", 4, TIGHT_4, 41, 4, None),
        S("1a6", "week 4, tight, 41 FPPG, out 4, keeper candidate no. 6", 4, TIGHT_4, 41, 4, None, rank=6),
        S("1a5", "week 4, tight, 41 FPPG, out 4, keeper candidate no. 5", 4, TIGHT_4, 41, 4, None, rank=5),
        S("2", "week 4, tight, 36 FPPG, out 8", 4, TIGHT_4, 36, 8, "drop"),
        S("3", "week 11, one game back, 45 FPPG, out 3 (back 14-15)", 11, TIGHT_11, 45, 3, "drop"),
        S("4", "week 11, one game back, 45 FPPG, out 5 (back for the playoffs)", 11, TIGHT_11, 45, 5, "drop"),
        S("5", "week 12, leads by 4, 45 FPPG, out 3", 12, LEAD_12, 45, 3, "hold"),
        S("6r5", "week 12, out of the race, long shot, 44 FPPG, keeper candidate no. 5, out 6", 12, OUT_12, 44, 6,
          "hold", rank=5, weak=("A",), by="little left to play for"),
        S("6r6", "week 12, out of the race, long shot, 44 FPPG, keeper candidate no. 6, out 6", 12, OUT_12, 44, 6,
          "hold", rank=6, weak=("A",), by="little left to play for"),
        S("7", "week 12, out of the race, long shot, 38 FPPG, not a candidate, out 6", 12, OUT_12, 38, 6, None,
          weak=("A",)),
        S("7c", "week 12, a contender (leads a live race), 38 FPPG, not a candidate, out 6", 12, CONTEND_12, 38,
          6, None),
        S("8", "week 6, mid-pack, 55 FPPG, a top-4 keeper (Nick, 11-04), out 10", 6, MID_6, 55, 10, "hold",
          rank=4, chance=TOP4_TYPICAL, above=[0.99, 0.95, 0.90], by="top-4 keeper"),
        S("9r5", "week 14, tied, 2 left, 50 FPPG, keeper candidate no. 5, out 2", 14, TIED_14, 50, 2, "drop",
          rank=5),
        S("9r6", "week 14, tied, 2 left, 50 FPPG, keeper candidate no. 6, out 2", 14, TIED_14, 50, 2, "drop",
          rank=6),
        S("9b5", "week 14, two games back, 2 left, 50 FPPG, keeper candidate no. 5, out 2", 14, BEHIND_14, 50, 2,
          None, rank=5),
        S("9b6", "week 14, two games back, 2 left, 50 FPPG, keeper candidate no. 6, out 2", 14, BEHIND_14, 50, 2,
          None, rank=6),
        S("10", "week 17, semifinal, won week 16, 42 FPPG, out 2 (back for the final)", 17, FINAL_15, 42, 2, None,
          week16=WON_16),
        S("10L", "week 17, semifinal, LOST week 16, 42 FPPG, out 2 (back for the final)", 17, FINAL_15, 42, 2,
          None, week16=LOST_16),
        S("11b", "week 5, little to play for (0-4, a long shot), 46 FPPG, out for the season", 5, BAD_5, 46,
          None, None, weak=("A",)),
        S("11a", "week 5, contender (4-0), 46 FPPG, age 33, out for the season", 5, CONTEND_5, 46, None, None),
    ]


# (weaker, stronger): if the weaker case drops, the stronger must drop too
DIRECTIONS = [
    ("1a5", "1a6"), ("1a6", "1b"),          # 1: a higher keep chance never makes a drop more likely
    ("7", "7c"),                             # 7: a contender drops at least as readily
    ("11b", "11a"),                          # 11: the same
    ("10", "10L"),                           # 10: a bigger series stake never makes a hold more likely
    ("9b5", "9r5"), ("9b6", "9r6"),          # 9: two games back never drops more readily than tied
]


@dataclass
class Numbers:
    sid: str
    answer: Optional[str]
    hold: float               # cost of holding
    drop0: float              # cost of dropping, keeper term aside
    chance: float             # keep chance if a candidate (rank <= 6), else 0
    protected: bool
    little_left: bool
    candidate: bool
    rs_title: float
    champion: float


def numbers(cfg: idr.Config, seed: int = SEED) -> list:
    """Each scenario's costs at one seed. The keeper term is taken out so the
    fit can vary K: costs(K=0) gives the cost of dropping without it."""
    zero = idr.Config(**{**cfg.__dict__, "keeper_weight": 0.0})
    out = []
    for s in scenarios():
        st, cand, keep = s.stakes(seed), s.candidate(), s.keep()
        c = idr.costs(cand, st, keep, zero)
        rank = c["keep_rank"]
        out.append(Numbers(s.sid, s.answer, c["cost_hold"], c["cost_drop"],
                           c["keep_chance"] if rank <= cfg.keeper_candidates else 0.0,
                           rank <= cfg.protected_keepers, idr.little_left(st, cfg),
                           rank <= cfg.keeper_candidates, st.rs_title, st.champion))
    return out


def gives(n: Numbers, M: float, F: float, K: float) -> str:
    """decide()'s answer from a scenario's numbers (the same rule, so the
    fit can sweep M, F and K without rebuilding anything)."""
    if n.protected or (n.little_left and n.candidate):
        return "hold"
    drop = n.drop0 + n.chance * K
    if n.hold < (1.0 + M) * drop or n.hold - drop < F:
        return "hold"
    return "drop"


GRID_M = np.round(np.arange(0.0, 2.0001, 0.02), 4)
GRID_K = np.round(np.arange(0.0, 1.0001, 0.005), 4)
GRID_F = np.round(np.arange(0.0, 0.3001, 0.002), 4)


def feasible(nums: list, Ms=GRID_M, Ks=GRID_K, Fs=GRID_F) -> np.ndarray:
    """[M, K, F] bool: every pinned answer given and every direction kept."""
    MM, KK, FF = np.meshgrid(Ms, Ks, Fs, indexing="ij")
    drops = {}
    for n in nums:
        if n.protected or (n.little_left and n.candidate):
            drops[n.sid] = np.zeros(MM.shape, bool)
            continue
        d = n.drop0 + n.chance * KK
        drops[n.sid] = (n.hold >= (1.0 + MM) * d) & (n.hold - d >= FF)
    ok = np.ones(MM.shape, bool)
    for n in nums:
        if n.answer == "drop":
            ok &= drops[n.sid]
        elif n.answer == "hold":
            ok &= ~drops[n.sid]
    for weak, strong in DIRECTIONS:
        ok &= ~(drops[weak] & ~drops[strong])
    return ok


def region(ok: np.ndarray, Ms=GRID_M, Ks=GRID_K, Fs=GRID_F) -> Optional[dict]:
    """Each axis' range over the feasible points (None if there are none)."""
    if not ok.any():
        return None
    i, j, k = np.nonzero(ok)
    return {"M": (float(Ms[i].min()), float(Ms[i].max())), "K": (float(Ks[j].min()), float(Ks[j].max())),
            "F": (float(Fs[k].min()), float(Fs[k].max())), "points": int(ok.sum())}


def _erode(ok: np.ndarray, r: tuple) -> np.ndarray:
    """Points whose whole box of half-widths r (in cells, per axis) is
    feasible; outside the grid counts as infeasible (M, K, F >= 0 are real edges)."""
    out = ok.copy()
    for ax, rad in enumerate(r):
        for _ in range(int(rad)):
            a = np.zeros_like(out)
            b = np.zeros_like(out)
            sl = [slice(None)] * 3
            sl2 = [slice(None)] * 3
            sl[ax], sl2[ax] = slice(1, None), slice(None, -1)
            a[tuple(sl2)] = out[tuple(sl)]          # neighbour above
            b[tuple(sl)] = out[tuple(sl2)]          # neighbour below
            out = out & a & b
    return out


def centre(ok: np.ndarray, Ms=GRID_M, Ks=GRID_K, Fs=GRID_F) -> tuple:
    """(M, K, F, depth): the point deepest inside the feasible region, depth
    measured as a share t of the region's own extent on every axis at once
    (so no axis dominates): the largest t whose eroded region is non-empty,
    then the survivor nearest that region's centroid."""
    if not ok.any():
        raise ValueError("no feasible point")
    pts = np.argwhere(ok)
    ext = np.maximum(pts.max(axis=0) - pts.min(axis=0) + 1, 1)
    lo, hi = 0.0, 0.5
    for _ in range(12):
        t = (lo + hi) / 2
        if _erode(ok, tuple(int(round(t * e)) for e in ext)).any():
            lo = t
        else:
            hi = t
    core = _erode(ok, tuple(int(round(lo * e)) for e in ext))
    cp = np.argwhere(core)
    c = cp.mean(axis=0)
    i, j, k = (int(x) for x in cp[np.argmin((((cp - c) / ext) ** 2).sum(axis=1))])
    return float(Ms[i]), float(Ks[j]), float(Fs[k]), round(lo, 3)


def fit(cfg: idr.Config, seeds=SEEDS) -> dict:
    """Each seed's region, the region common to all seeds, and its centre."""
    per, common = {}, None
    for sd in seeds:
        ok = feasible(numbers(cfg, sd))
        per[sd] = region(ok)
        common = ok if common is None else (common & ok)
    out = {"per_seed": per, "common": region(common)}
    out["centre"] = centre(common) if common.any() else None
    return out
