"""
Angle selector (prose layer, item 2): which story leads the newsletter.

    score = unusualness x consequence

Unusualness: how rare the thing is against league history, as -ln(p) where
p is its tail probability among every prior season's games (a margin, a
team score, a streak length), or a probability the event carries itself
(an upset's underdog odds). History is prior seasons only: a season is
never judged against itself.

Consequence (Nick, 10-07): how much the week moved the two races that
decide things, from scores alone -- no simulator. Both are measured as the
change in the manager's EXPECTED SEED, so they add:
  cup        The Cup is seeded by total points over weeks 1-21, so every
             point counts from week 1. Each points gap is scaled by how much
             it can still move -- the weekly scoring spread x sqrt(2 x weeks
             left) -- and turned into P(he finishes ahead of that rival).
             Expected seed = sum of those; consequence = how far this week
             moved it.
  standings  Regular season only: the same on wins, where a gap can still
             move by sqrt(games left / 2).
  bracket    A postseason game decides a seed outright: 1.
(The first version added a flat bonus per seed crossed. Measured on 2025-26
it made weeks 3-6 -- when cumulative points cross every week and mean
nothing -- look like the most consequential of the season. Scaling the gap
and the crossing by the same remaining spread fixes that.)
The two races give variety without a rule: a blowout's points move Cup
seeding, a squeaker's result moves the standings.

Recency only breaks ties: angles whose scores are within TIE_BAND of each
other are ordered by how long ago their (family, manager) last led or
featured. Nothing is held back for having been used.
"""

from __future__ import annotations

import math
from bisect import bisect_left, bisect_right
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Callable, Optional

from modules.storylines import FAMILY, MILESTONE_WINS, Storyline

BRACKET_WEIGHT = 1.0       # a postseason game decides a seed outright
CONSEQUENCE_FLOOR = 0.05   # a dead week still ranks by unusualness
TIE_BAND = 0.05            # scores this close (relative) are a tie
SECONDARY = 3              # angles shown after the lead
RECENCY_LOOKBACK = 6       # weeks of past selections consulted


# ------------------------------------------------------------------ history

@dataclass
class History:
    margins: list
    rel_scores: list
    runs: list
    sigma: float                       # weekly score SD around the week mean
    leader_gb: dict                    # week -> sorted leader margins
    team_weeks: int

    @classmethod
    def build(cls, matchups: list, regular_through: Callable) -> "History":
        margins, rel, dev = [], [], []
        by_week = defaultdict(list)
        for m in matchups:
            by_week[(m["season"], m["week"])].append(m)
        for (s, w), ms in by_week.items():
            scores = [x for m in ms for x in (m["score_a"], m["score_b"])]
            mean = sum(scores) / len(scores)
            for x in scores:
                rel.append(x / mean)
                dev.append(x - mean)
            margins += [abs(m["score_a"] - m["score_b"]) for m in ms]
        sigma = math.sqrt(sum(d * d for d in dev) / max(len(dev) - 1, 1))
        runs = []
        leader = defaultdict(list)
        for s in {m["season"] for m in matchups}:
            seq = defaultdict(list)
            wins = defaultdict(int)
            for w in sorted({m["week"] for m in matchups if m["season"] == s}):
                if w > regular_through(s):
                    continue
                for m in by_week[(s, w)]:
                    a_won = m["score_a"] > m["score_b"]
                    seq[m["manager_a"]].append(a_won)
                    seq[m["manager_b"]].append(not a_won)
                    wins[m["manager_a"]] += a_won
                    wins[m["manager_b"]] += not a_won
                top = sorted(wins.values(), reverse=True)
                if len(top) > 1:
                    leader[w].append(top[0] - top[1])
            for xs in seq.values():
                runs += _run_lengths(xs)
        return cls(sorted(margins), sorted(rel), sorted(runs), sigma,
                   {w: sorted(v) for w, v in leader.items()}, len(rel))


def _run_lengths(xs: list) -> list:
    out, n = [], 0
    for i, x in enumerate(xs):
        n = n + 1 if i and x == xs[i - 1] else 1
        if i == len(xs) - 1 or xs[i + 1] != x:
            out.append(n)
    return out


def _two_sided(sorted_vals: list, x: float) -> float:
    n = len(sorted_vals)
    lo = bisect_right(sorted_vals, x) / n
    hi = (n - bisect_left(sorted_vals, x)) / n
    return min(1.0, 2 * min(lo, hi))


def _tail_ge(sorted_vals: list, x: float) -> float:
    n = len(sorted_vals)
    return (n - bisect_left(sorted_vals, x)) / n if n else 1.0


def _u(p: float, n: int, k: int = 1) -> float:
    """-ln p, with p floored at 1/(n+1): nothing is rarer than unseen.

    k = how many chances the week had to produce one of these (four team
    scores, two margins). The rarest of four draws is less rare than one
    draw, so p becomes 1-(1-p)^k. Without this, team scores -- four
    candidates a week against two margins -- led 10 of 23 weeks in 2025-26
    on numbers alone."""
    p = max(p, 1.0 / (n + 1))
    return -math.log(1.0 - (1.0 - p) ** k)


# ------------------------------------------------------------------ consequence

def _cumulative(matchups, upto):
    pts, wins = defaultdict(float), defaultdict(int)
    for m in matchups:
        if m["week"] > upto:
            continue
        pts[m["manager_a"]] += m["score_a"]
        pts[m["manager_b"]] += m["score_b"]
        a_won = m["score_a"] > m["score_b"]
        wins[m["manager_a"]] += a_won
        wins[m["manager_b"]] += not a_won
    return pts, wins


def _rank(order_key, managers):
    ranked = sorted(managers, key=order_key, reverse=True)
    return {m: i for i, m in enumerate(ranked)}, ranked


def _phi(z: float) -> float:
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def _p_ahead(gap: float, sd: float) -> float:
    """P(this gap ends positive) when it can still move by `sd`."""
    if sd <= 0:
        return 1.0 if gap > 0 else (0.0 if gap < 0 else 0.5)
    return _phi(gap / sd)


def _expected_seed_move(m, managers, gap0, gap1, sd0, sd1) -> float:
    """|change in m's expected seed| = |sum over rivals of the change in
    P(m finishes ahead of him)|. Both a gap move and a crossing count, and
    both are worth less the more season is left to undo them."""
    return abs(sum(_p_ahead(gap1(n), sd1) - _p_ahead(gap0(n), sd0)
                   for n in managers if n != m))


def consequence(season_matchups: list, week: int, cup_last: Optional[int],
                reg_last: int, sigma: float) -> dict:
    """{manager: {"cup", "standings", "bracket"}} for one week, each in
    expected seeds moved -- so the terms add."""
    this = [m for m in season_matchups if m["week"] == week]
    managers = sorted({x for m in season_matchups
                       for x in (m["manager_a"], m["manager_b"])})
    out = {m: {"cup": 0.0, "standings": 0.0, "bracket": 0.0}
           for m in managers}
    playing = {x for m in this for x in (m["manager_a"], m["manager_b"])}
    p0, w0 = _cumulative(season_matchups, week - 1)
    p1, w1 = _cumulative(season_matchups, week)

    if cup_last and week <= cup_last:
        # each gap moves by (s_m - s_n): sd sigma*sqrt(2) a week
        sd0 = sigma * math.sqrt(2 * (cup_last - week + 1))
        sd1 = sigma * math.sqrt(2 * (cup_last - week))
        for m in playing:
            out[m]["cup"] = _expected_seed_move(
                m, managers, lambda n: p0[m] - p0[n], lambda n: p1[m] - p1[n],
                sd0, sd1)

    if week <= reg_last:
        # a wins gap moves by w_m - w_n: variance 1/2 a week
        sd0 = math.sqrt(0.5 * (reg_last - week + 1))
        sd1 = math.sqrt(0.5 * (reg_last - week))
        for m in playing:
            out[m]["standings"] = _expected_seed_move(
                m, managers, lambda n: w0[m] - w0[n],
                lambda n: w1[m] - w1[n], sd0, sd1)
    else:
        for m in playing:
            out[m]["bracket"] = BRACKET_WEIGHT
    return out


# ------------------------------------------------------------------ angles

@dataclass
class Angle:
    family: str
    managers: tuple
    text: str
    unusualness: float
    consequence: float = 0.0
    parts: dict = field(default_factory=dict)
    score: float = 0.0
    source: str = "matchups"

    @property
    def key(self):
        return (self.family, self.managers[0])

    def as_dict(self) -> dict:
        return {"family": self.family, "managers": list(self.managers),
                "text": self.text, "score": round(self.score, 3),
                "unusualness": round(self.unusualness, 3),
                "consequence": round(self.consequence, 3),
                "parts": {k: round(v, 3) for k, v in self.parts.items()},
                "source": self.source}


def matchup_angles(season_matchups: list, week: int, hist: History,
                   reg_last: int) -> list[Angle]:
    out = []
    this = [m for m in season_matchups if m["week"] == week]
    for m in this:
        a, b = m["manager_a"], m["manager_b"]
        w, l = (a, b) if m["score_a"] > m["score_b"] else (b, a)
        margin = abs(m["score_a"] - m["score_b"])
        p = _two_sided(hist.margins, margin)
        side = "close" if bisect_left(hist.margins, margin) < \
            len(hist.margins) / 2 else "wide"
        out.append(Angle("margin", (w, l),
                         f"{w} beat {l} by {margin:.2f} ({side})",
                         _u(p, len(hist.margins), len(this))))
    scores = [(m["manager_a"], m["score_a"]) for m in this] + \
        [(m["manager_b"], m["score_b"]) for m in this]
    if scores:
        mean = sum(s for _, s in scores) / len(scores)
        for mgr, s in scores:
            p = _two_sided(hist.rel_scores, s / mean)
            out.append(Angle("score", (mgr,),
                             f"{mgr} scored {s:.2f}, {100 * (s / mean - 1):+.0f}% "
                             f"against the week's average",
                             _u(p, hist.team_weeks, len(scores))))
    if week <= reg_last:
        seq = defaultdict(list)
        for x in sorted(season_matchups, key=lambda x: x["week"]):
            if x["week"] > week:
                continue
            a_won = x["score_a"] > x["score_b"]
            seq[x["manager_a"]].append(a_won)
            seq[x["manager_b"]].append(not a_won)
        for mgr, xs in seq.items():
            n = _run_lengths(xs)[-1] if xs else 0
            if n >= 2:
                out.append(Angle("streak", (mgr,),
                                 f"{mgr} has {'won' if xs[-1] else 'lost'} "
                                 f"{n} straight",
                                 _u(_tail_ge(hist.runs, n), len(hist.runs),
                                    len(seq))))
    return out


def storyline_angles(stories: list[Storyline], hist: History, week: int,
                     team_weeks_this_season: int, n_matchups: int = 2,
                     n_teams: int = 4) -> list[Angle]:
    out = []
    per_matchup = {"margin", "upset", "spread"}
    for s in stories:
        mag, fam = s.magnitude, FAMILY[s.kind]
        if fam == "margin":
            p = _two_sided(hist.margins, mag["margin"])
            n = len(hist.margins)
        elif fam == "streak":
            p = _tail_ge(hist.runs, mag.get("streak", 0))
            n = len(hist.runs)
        elif fam == "upset":
            p = mag["underdog_prob"] / 100.0
            n = 100
        elif fam == "spread":
            z = abs(mag["margin"] - mag["spread"]) / (hist.sigma * math.sqrt(2))
            p = math.erfc(z / math.sqrt(2))
            n = hist.team_weeks
        elif fam == "record":
            p = 1.0 / max(team_weeks_this_season, 1)
            n = team_weeks_this_season
        elif fam == "milestone":
            gaps = [b - a for a, b in zip(MILESTONE_WINS, MILESTONE_WINS[1:])]
            p = 1.0 / (sum(gaps) / len(gaps))
            n = hist.team_weeks
        elif fam == "standings":
            gb = mag.get("games_back")
            ref = hist.leader_gb.get(week, [])
            p = _tail_ge(ref, gb) if gb is not None and ref else 0.5
            n = max(len(ref), 1)
        else:
            continue
        k = n_matchups if fam in per_matchup else (
            1 if fam in ("standings", "record") else n_teams)
        out.append(Angle(fam, tuple(s.managers), s.text.strip(" ->"),
                         _u(p, n, k), source="storyline"))
    return out


def merge(angles: list[Angle]) -> list[Angle]:
    """One angle per (family, managers): the storyline's text wins, the
    larger unusualness wins."""
    best: dict = {}
    for a in angles:
        k = (a.family, frozenset(a.managers))
        cur = best.get(k)
        if cur is None:
            best[k] = a
            continue
        u = max(cur.unusualness, a.unusualness)
        keep = a if a.source == "storyline" else cur
        keep.unusualness = u
        best[k] = keep
    return list(best.values())


# A game's story is both teams' story; anything else is its subject's. (Max
# over everyone named let "Nick leads by 7" ride on Benton's live race for
# second in 2025-26 week 21.)
PAIR_FAMILIES = {"margin", "upset", "spread"}


def score(angles: list[Angle], cons: dict) -> None:
    for a in angles:
        parts = {"cup": 0.0, "standings": 0.0, "bracket": 0.0}
        tot = 0.0
        who = a.managers if a.family in PAIR_FAMILIES else a.managers[:1]
        for m in who:
            c = cons.get(m, {})
            t = sum(c.values())
            if t >= tot:
                tot, parts = t, dict(c)
        a.parts = parts
        a.consequence = tot
        a.score = a.unusualness * max(tot, CONSEQUENCE_FLOOR)


def rank(angles: list[Angle], last_used: dict) -> tuple[list[Angle], int]:
    """Score order; within a tie band, least-recently-used first. Returns
    the ranking and how many positions recency changed."""
    srt = sorted(angles, key=lambda a: -a.score)
    out, i, moved = [], 0, 0
    while i < len(srt):
        top = srt[i].score
        j = i
        while j < len(srt) and top > 0 and \
                (top - srt[j].score) <= TIE_BAND * top:
            j += 1
        j = max(j, i + 1)
        group = srt[i:j]
        reordered = sorted(group, key=lambda a: last_used.get(a.key, -1))
        moved += sum(1 for x, y in zip(group, reordered) if x is not y)
        out += reordered
        i = j
    return out, moved


def select(ranked: list[Angle]) -> dict:
    return {"lead": ranked[0].as_dict() if ranked else None,
            "secondary": [a.as_dict() for a in ranked[1:1 + SECONDARY]]}


def run_week(season_matchups: list, week: int, hist: History,
             cup_last: Optional[int], reg_last: int,
             stories: Optional[list] = None,
             last_used: Optional[dict] = None) -> dict:
    cands = matchup_angles(season_matchups, week, hist, reg_last)
    if stories:
        tw = 2 * len([m for m in season_matchups if m["week"] <= week])
        nm = len([m for m in season_matchups if m["week"] == week])
        cands += storyline_angles(stories, hist, week, tw, nm, 2 * nm)
    cands = merge(cands)
    cons = consequence(season_matchups, week, cup_last, reg_last, hist.sigma)
    score(cands, cons)
    ranked, moved = rank(cands, last_used or {})
    sel = select(ranked)
    sel["week"] = week
    sel["recency_reordered"] = moved
    sel["consequence"] = cons
    sel["all"] = [a.as_dict() for a in ranked]
    return sel


def update_last_used(last_used: dict, sel: dict, week: int) -> None:
    for a in [sel["lead"]] + sel["secondary"]:
        if a:
            last_used[(a["family"], a["managers"][0])] = week


# ------------------------------------------------------------------ files

def season_windows(season: str) -> tuple[Optional[int], int]:
    """(last Cup-seeding week, last regular-season week). The Cup window is
    every week before the Cup stage (seeded by total points over them);
    a season with no Cup is scored as if it had one over its regular season,
    so 2025-26 can be shown."""
    from modules.data_loader import stage_weeks, regular_season_weeks_for
    reg = stage_weeks(season, "regular_season")
    reg_last = reg[1] if reg else regular_season_weeks_for(season)
    cup = stage_weeks(season, "cup")
    return (cup[0] - 1 if cup else reg_last), reg_last


def season_matchups(base, season: str, week: int) -> list:
    import json
    from pathlib import Path
    base = Path(base)
    hist = base / "data" / "historical" / "all_matchups.json"
    allm = json.loads(hist.read_text(encoding="utf-8")) if hist.exists() \
        else []
    sm = [m for m in allm if m["season"] == season]
    if not sm:
        from modules.lore import current_season_matchups
        sched = base / "config" / "SCHEDULE.json"
        rec = base / "config" / "RECORDS.json"
        sm = current_season_matchups(
            json.loads(sched.read_text(encoding="utf-8")) if sched.exists()
            else {},
            (json.loads(rec.read_text(encoding="utf-8")) if rec.exists()
             else {}).get("weekly_scores", {}), season)
    prior = [m for m in allm if m["season"] < season]
    return [m for m in sm if m["week"] <= week], prior


def recency_from(out_dir, week: int) -> dict:
    """(family, manager) -> last week it was selected, from the angles
    files of the previous RECENCY_LOOKBACK weeks."""
    import json
    from pathlib import Path
    last: dict = {}
    for w in range(max(1, week - RECENCY_LOOKBACK), week):
        f = Path(out_dir) / f"angles_week{w}.json"
        if f.exists():
            update_last_used(last, json.loads(f.read_text(encoding="utf-8")),
                             w)
    return last


def for_report(base, season: str, week: int, stories: list) -> dict:
    """Everything format_stats_report needs: the ranked angles for this
    week, with recency from earlier weeks' files."""
    from pathlib import Path
    from modules.data_loader import regular_season_weeks_for
    sm, prior = season_matchups(base, season, week)
    if not any(m["week"] == week for m in sm):
        raise ValueError(f"no week {week} results for {season}")
    hist = History.build(prior, regular_season_weeks_for)
    cup_last, reg_last = season_windows(season)
    return run_week(sm, week, hist, cup_last, reg_last, stories,
                    recency_from(Path(base) / "output", week))


def render_markdown(sel: dict) -> str:
    def line(a):
        p = a["parts"]
        bits = [f"{k} {p[k]:.2f}" for k in ("cup", "standings", "bracket")
                if p.get(k)]
        return (f"{a['text']}  _(unusualness {a['unusualness']:.2f} x "
                f"consequence {a['consequence']:.2f}"
                f"{': ' + ', '.join(bits) if bits else ''})_")
    out = ["## -> ANGLES -> WHAT LEADS THIS WEEK", "",
           "Ranked by how unusual (against every prior season) x how much it "
           "moved the Cup-seeding and standings races. Open the newsletter "
           "with the lead. The scores are for you, not the reader.", ""]
    if sel.get("lead"):
        out.append(f"- **Lead:** {line(sel['lead'])}")
    for a in sel.get("secondary", []):
        out.append(f"- {line(a)}")
    return "\n".join(out) + "\n"
