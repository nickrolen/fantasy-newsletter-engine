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
  bracket    A postseason game: the change in what the manager stands to
             win or pay, by the league's own stakes -- payouts for the
             playoff bracket (champion collects, 3rd and 4th pay), the
             extra keeper for the Cup -- scaled so a decisive game in that
             bracket is 1. So a playoff semifinal and final both count 1,
             the third-place game 0 (both sides pay either way), a Cup
             semifinal 0.5 and the Cup final 1. Only bracket angles carry it.
(The first version added a flat bonus per seed crossed. Measured on 2025-26
it made weeks 3-6 -- when cumulative points cross every week and mean
nothing -- look like the most consequential of the season. Scaling the gap
and the crossing by the same remaining spread fixes that.)
The two races give variety without a rule: a blowout's points move Cup
seeding, a squeaker's result moves the standings.

Consequence takes the race an angle moved MOST, not the sum (Nick, 10-07:
a margin is eligible for both races and summing gave it two bites).

Last week's lead told again (same subject, kind, direction) is scored on
its conditional rarity -- given last week, how unusual is this week -- from
how often prior seasons repeated it. Recency otherwise only breaks ties:
angles within TIE_BAND are ordered by how long ago their (family, manager)
last featured.

A race settled early is an angle of its own (decided_angles): the title
clinched, a team out of it, a team safe from the places that pay or certain
to land in them -- exact, from wins and games left, with the payout config
saying which places pay. It counts 1, like a decisive bracket game, and is
as unusual as the earlier of: how early it was settled against prior
seasons, or how much doubt the week resolved. The title race is also a
standing thread printed every week, with the leader's magic number.

A week with no lead says so (is_dead): the best angle moved neither race,
or was no rarer than a coin flip and decided nothing. The block then tells
the writer to open on the races (their state is printed) or on lore, not
to build an opening out of a result -- that is how significance gets
invented. A decisive bracket game always leads.
"""

from __future__ import annotations

import math
from bisect import bisect_left, bisect_right
from collections import defaultdict

from modules.data_loader import (Record, regular_season_tie_value, results_from,
                                 standings_order, week_outcome)
from dataclasses import dataclass, field
from typing import Callable, Optional

from modules.storylines import FAMILY, MILESTONE_WINS, Storyline

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
    rel_pairs: list = field(default_factory=list)   # (last week, this week)
    decided_left: dict = field(default_factory=dict)  # event -> [share left]

    @classmethod
    def build(cls, matchups: list, regular_through: Callable) -> "History":
        margins, rel, dev = [], [], []
        by_week = defaultdict(list)
        for m in matchups:
            by_week[(m["season"], m["week"])].append(m)
        team_rel = defaultdict(dict)
        for (s, w), ms in by_week.items():
            scores = [x for m in ms for x in (m["score_a"], m["score_b"])]
            mean = sum(scores) / len(scores)
            for x in scores:
                rel.append(x / mean)
                dev.append(x - mean)
            for m in ms:
                team_rel[(s, m["manager_a"])][w] = m["score_a"] / mean
                team_rel[(s, m["manager_b"])][w] = m["score_b"] / mean
            margins += [abs(m["score_a"] - m["score_b"]) for m in ms]
        sigma = math.sqrt(sum(d * d for d in dev) / max(len(dev) - 1, 1))
        runs = []
        leader = defaultdict(list)
        for s in {m["season"] for m in matchups}:
            seq = defaultdict(list)
            wins = defaultdict(float)
            for w in sorted({m["week"] for m in matchups if m["season"] == s}):
                if w > regular_through(s):
                    continue
                for m in by_week[(s, w)]:
                    # a T is its own result: it ends a W or an L run
                    o = week_outcome(m["score_a"], m["score_b"])
                    seq[m["manager_a"]].append({"a": "W", "b": "L"}.get(o, "T"))
                    seq[m["manager_b"]].append({"a": "L", "b": "W"}.get(o, "T"))
                    wa, wb = _credit(o)
                    wins[m["manager_a"]] += wa
                    wins[m["manager_b"]] += wb
                top = sorted(wins.values(), reverse=True)
                if len(top) > 1:
                    leader[w].append(top[0] - top[1])
            for xs in seq.values():
                runs += _run_lengths(xs)
        pairs = [(wk[w - 1], wk[w]) for wk in team_rel.values()
                 for w in wk if w - 1 in wk]
        decided = defaultdict(list)
        for s in {m["season"] for m in matchups}:
            sm = [m for m in matchups if m["season"] == s]
            rt = regular_through(s)
            seen = set()
            for w in range(1, rt + 1):
                for ev, mgr in decided_status(sm, w, rt) - seen:
                    # as a share of the regular season: 3 weeks left of
                    # 21 is not as early as 3 of 15 (2026-27's length)
                    decided[ev].append((rt - w) / rt)
                    seen.add((ev, mgr))
        return cls(sorted(margins), sorted(rel), sorted(runs), sigma,
                   {w: sorted(v) for w, v in leader.items()}, len(rel),
                   pairs, {k: sorted(v) for k, v in decided.items()})

    def p_score_again(self, rel: float, direction: str) -> float:
        """Two-sided P(a score this extreme | the same team was in the same
        tail -- bottom or top quarter -- last week)."""
        n = len(self.rel_scores)
        lo, hi = self.rel_scores[n // 4], self.rel_scores[(3 * n) // 4]
        if direction == "low":
            cond = [c for p, c in self.rel_pairs if p <= lo]
            k = sum(1 for c in cond if c <= rel)
        else:
            cond = [c for p, c in self.rel_pairs if p >= hi]
            k = sum(1 for c in cond if c >= rel)
        return min(1.0, 2 * k / len(cond)) if cond else 1.0

    def p_streak_again(self, n: int) -> float:
        """P(a run reaches n | it reached n-1)."""
        prev = _tail_ge(self.runs, n - 1)
        return _tail_ge(self.runs, n) / prev if prev else 1.0


def _run_lengths(xs: list) -> list:
    out, n = [], 0
    for i, x in enumerate(xs):
        n = n + 1 if i and x == xs[i - 1] else 1
        if i == len(xs) - 1 or xs[i + 1] != x:
            out.append(n)
    return out


# ------------------------------------------------------------------ decided
#
# A race can be settled before it's over: the title clinched, a team out of
# it, a team safe from paying or certain to pay. Exact, from wins and games
# left (a tie in wins counts as undecided: the points tiebreak can still go
# either way). Which places collect and which pay comes from the payout
# config, like the bracket stakes.

def _payer_places() -> set:
    import re as _re
    from modules.data_loader import PAYOUTS
    pay = (PAYOUTS or {}).get("league_champion") or {}
    return {int(x) for x in _re.findall(r"(\d)(?:st|nd|rd|th)",
                                         pay.get("paid_by") or "")}


def decided_status(season_matchups: list, week: int, reg_last: int) -> set:
    """{(event, manager)} true after `week` of the regular season."""
    if week > reg_last:
        return set()
    _, wins = _cumulative([m for m in season_matchups if m["week"] <= reg_last],
                          week)
    managers = sorted({x for m in season_matchups
                       for x in (m["manager_a"], m["manager_b"])})
    left = reg_last - week
    mx = {m: wins[m] + left for m in managers}
    payers = _payer_places()
    safe = (min(payers) - 1) if payers else None
    out = set()
    if left == 0:
        # Season over: the tiebreak settles ties (league_config
        # tiebreaker_rules: head-to-head, then total points).
        order = final_order(season_matchups, reg_last)
        for i, m in enumerate(order, 1):
            out.add(("clinched_title" if i == 1 else "out_of_title", m))
            if safe:
                out.add(("safe_from_paying" if i <= safe else "will_pay", m))
        return out
    for m in managers:
        others = [o for o in managers if o != m]
        if all(wins[m] > mx[o] for o in others):
            out.add(("clinched_title", m))
        elif any(wins[o] > mx[m] for o in others):
            out.add(("out_of_title", m))
        if safe:
            if sum(1 for o in others if mx[o] >= wins[m]) < safe:
                out.add(("safe_from_paying", m))
            elif sum(1 for o in others if wins[o] > mx[m]) >= safe:
                out.add(("will_pay", m))
    return out


def final_order(season_matchups: list, reg_last: int) -> list:
    """Regular-season finish: data_loader.standings_order -- winning
    percentage (a T is half a win), head-to-head among the tied, total
    points. This used to be its own copy of that rule."""
    reg = [m for m in season_matchups if m["week"] <= reg_last]
    records, h2h, pts = _records(reg, reg_last)
    return standings_order(records, h2h, pts, sorted(records))


def magic_number(season_matchups: list, week: int, reg_last: int):
    """(leader, wins the leader needs -- his wins or his rivals' losses --
    to clinch the title outright). None once the season is over."""
    _, wins = _cumulative([m for m in season_matchups if m["week"] <= reg_last],
                          week)
    if not wins or week >= reg_last:
        return None
    left = reg_last - week
    lead = max(wins, key=lambda m: wins[m])
    # strictly ahead of every rival's best case; with a half game (a T)
    # in the gap the count rounds up to the next whole result
    need = math.floor(max(wins[o] + left for o in wins if o != lead) - wins[lead]) + 1
    return lead, max(0, need)


# Language rule (Nick, 10-07): never "safe from paying" or "certain to pay"
# unqualified. Every liability line names the pot and the window: before
# the semifinals resolve, an unqualified "safe" is a false statement about
# total liability. tests/test_angles.py checks every template.
DECIDED_TEXT = {
    "clinched_title": "{m} clinched the regular-season title (weeks "
                      "{w0}-{w1}) and the ${rs_total} that comes with it "
                      "({rec}, {left} weeks left)",
    "out_of_title": "{m} can no longer win the regular season (weeks "
                    "{w0}-{w1}) or its ${rs_total} ({rec}, {left} weeks left)",
    "safe_from_paying": "{m} can't finish {payers} in the regular season "
                        "(weeks {w0}-{w1}), so he won't pay into its "
                        "${rs_total} pot. The ${po_total} playoff pot is "
                        "still open until the semifinals ({rec}, {left} "
                        "weeks left)",
    "will_pay": "{m} will finish {payers} in the regular season (weeks "
                "{w0}-{w1}) and pay ${rs_per} of its ${rs_total} pot. The "
                "${po_total} playoff pot is still open until the semifinals "
                "({rec}, {left} weeks left)",
}


def _pot_terms(reg_last: int) -> dict:
    from modules.data_loader import league_rule
    rs = league_rule("payouts", "league_champion")
    po = league_rule("payouts", "playoff_champion")
    return {"w0": 1, "w1": reg_last, "rs_total": int(rs["total"]),
            "rs_per": int(rs["per_payer"]), "po_total": int(po["total"])}


def decided_angles(season_matchups: list, week: int, reg_last: int,
                   hist: "History") -> list:
    if week > reg_last:
        return []
    now = decided_status(season_matchups, week, reg_last)
    before = decided_status(season_matchups, week - 1, reg_last) \
        if week > 1 else set()
    recs, _h2h, _pts = _records(season_matchups, min(week, reg_last))
    out = []
    left = reg_last - week
    # standings going into the week, for how in doubt each line still was
    p0, w0 = _cumulative([x for x in season_matchups if x["week"] <= reg_last],
                         week - 1)
    order0 = sorted(w0, key=lambda x: (-w0[x], -p0[x]))
    sd0 = math.sqrt(0.5 * (reg_last - week + 1))
    pay = _payer_places()
    for ev, m in sorted(now - before):
        ref = hist.decided_left.get(ev, [])
        p = _tail_ge(ref, left / reg_last) if ref else 0.5
        # Two ways a settled race is news: settled EARLY (rare timing --
        # Nick's clinch with 3 weeks left), or settled while still in
        # DOUBT (the entropy the week resolved -- a final-day tiebreak).
        line = 1 if ev in ("clinched_title", "out_of_title") else (
            min(pay) - 1 if pay else 1)
        if m in order0 and len(order0) > line:
            i = order0.index(m)
            rival = order0[line] if i < line else order0[line - 1]
            q = _p_ahead(w0[m] - w0[rival], sd0)
        else:
            q = 0.5                       # nothing played yet: fully open
        doubt = -sum(x * math.log(x) for x in (q, 1 - q) if 0 < x < 1)
        payers = " or ".join(_ordinal(k) for k in sorted(_payer_places()))
        out.append(Angle("decided", (m,), DECIDED_TEXT[ev].format(
            m=m, rec=str(recs.get(m, Record())), left=left,
            payers=payers, **_pot_terms(reg_last)),
            max(_u(p, max(len(ref), 1)), doubt), source="decided",
            direction=ev))
    return out


def _ordinal(n: int) -> str:
    return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


def decided_consequence(season_matchups, week, reg_last) -> dict:
    """A settled stake counts 1, like a decisive bracket game."""
    now = decided_status(season_matchups, week, reg_last)
    before = decided_status(season_matchups, week - 1, reg_last) \
        if week > 1 else set()
    return {m: 1.0 for _, m in now - before}


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

def _credit(outcome: str) -> tuple:
    """Standings credit (a, b) for one week: 1/0, 0/1, or the T value each."""
    if outcome == "a":
        return 1.0, 0.0
    if outcome == "b":
        return 0.0, 1.0
    t = float(regular_season_tie_value())
    return t, t


def _cumulative(matchups, upto):
    """(points, standings value) through `upto`. The value is W + 0.5*T
    (tiebreaker_rules): a tied week is a T for both (Nick, 10-20), so it
    can be a half. Every check below -- clinched, eliminated, safe, will
    pay, the magic number, the standings consequence -- runs on this value,
    and stays exact: a remaining game is still worth at most 1."""
    pts, wins = defaultdict(float), defaultdict(float)
    for m in matchups:
        if m["week"] > upto:
            continue
        pts[m["manager_a"]] += m["score_a"]
        pts[m["manager_b"]] += m["score_b"]
        wa, wb = _credit(week_outcome(m["score_a"], m["score_b"]))
        wins[m["manager_a"]] += wa
        wins[m["manager_b"]] += wb
    return pts, wins


def _records(matchups, upto):
    """({manager: Record}, h2h, points) through `upto` -- W-L-T for display
    and for the one ranking rule (data_loader.standings_order)."""
    by_week, pairs = defaultdict(dict), defaultdict(list)
    for m in matchups:
        if m["week"] > upto:
            continue
        by_week[m["week"]][m["manager_a"]] = m["score_a"]
        by_week[m["week"]][m["manager_b"]] = m["score_b"]
        pairs[m["week"]].append({"manager_a": m["manager_a"], "manager_b": m["manager_b"]})
    return results_from(by_week, pairs, upto)


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
    out = {m: {"cup": 0.0, "standings": 0.0, "bracket": 0.0, "decided": 0.0}
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
        # a standings gap moves by w_m - w_n: variance 1/2 a week. The gap is
        # W + 0.5*T, so it can be a half game; _p_ahead reads it as a
        # continuous gap -- a half is half, nothing is rounded.
        sd0 = math.sqrt(0.5 * (reg_last - week + 1))
        sd1 = math.sqrt(0.5 * (reg_last - week))
        for m in playing:
            out[m]["standings"] = _expected_seed_move(
                m, managers, lambda n: w0[m] - w0[n],
                lambda n: w1[m] - w1[n], sd0, sd1)
    return out


# ------------------------------------------------------------------ bracket

def _p_series(wa: int, wb: int, need: int) -> float:
    """P(side A takes the series) from (wa, wb), each game a coin flip."""
    if wa >= need:
        return 1.0
    if wb >= need:
        return 0.0
    return 0.5 * _p_series(wa + 1, wb, need) + 0.5 * _p_series(wa, wb + 1,
                                                              need)


def _game_winner(m: dict, seeds: dict, tie_rule: str) -> str:
    """The winner of a bracket game. A tied score goes by the configured
    rule (league_config tiebreaker_rules); an unknown rule raises."""
    if m["score_a"] != m["score_b"]:
        return m["manager_a"] if m["score_a"] > m["score_b"] else \
            m["manager_b"]
    if tie_rule != "higher_seed":
        raise ValueError(f"unknown bracket tie rule {tie_rule!r}")
    return min((m["manager_a"], m["manager_b"]), key=lambda x: seeds[x])


def bracket_structure(season: str) -> list:
    """[{stage, title, seeded_by, values, rounds:[{name, kind, weeks}]}]
    from league_config: the three-stage format from its effective season,
    the legacy two-week single-game bracket before it."""
    import re as _re
    from modules.data_loader import (POSTSEASON_FORMAT, PAYOUTS, stage_weeks,
                                     uses_three_stage_format)

    from modules.data_loader import league_rule

    def values_for(key, third_key):
        """Stake by finishing place, from the payout config. A prize with
        no dollar value (the Cup keeper) is one unit for the winner. The
        third-place contest's stake is read too -- zero today -- so a stake
        added there later needs no code change."""
        pay = league_rule("payouts", key)
        if pay.get("total"):
            payers = {int(x) for x in _re.findall(
                r"(\d)(?:st|nd|rd|th)", pay.get("paid_by") or "")}
            vals = {1: float(pay["total"]), 2: 0.0, 3: 0.0, 4: 0.0,
                    **{k: -float(pay.get("per_payer", 0)) for k in payers}}
        else:
            vals = {1: 1.0, 2: 0.0, 3: 0.0, 4: 0.0}
        third = float(league_rule("payouts", third_key, "total") or 0)
        vals[3] += third
        vals[4] -= third
        return vals

    def kind(name):
        n = name.lower()
        return "third" if "third" in n else (
            "final" if "final" in n and "semi" not in n else "semis")

    out = []
    pw = stage_weeks(season, "playoffs")
    if pw:
        if uses_three_stage_format(season):
            st = POSTSEASON_FORMAT["stages"]["playoffs"]
            rounds = [{"name": r["name"], "kind": kind(r["name"]),
                       "weeks": tuple(r["weeks"])} for r in st["rounds"]]
        else:
            st = {"title": "Playoff Champion"}
            rounds = [{"name": "Semifinals", "kind": "semis",
                       "weeks": (pw[0], pw[0])},
                      {"name": "Final", "kind": "final",
                       "weeks": (pw[1], pw[1])},
                      {"name": "Third Place", "kind": "third",
                       "weeks": (pw[1], pw[1])}]
        out.append({"stage": "playoffs", "title": st.get("title"),
                    "seeded_by": "standings",
                    "values": values_for("playoff_champion",
                                         "playoff_third_place"),
                    "tie": league_rule("tiebreaker_rules", "series_week"),
                    "rounds": rounds})
    cw = stage_weeks(season, "cup")
    if cw:
        st = POSTSEASON_FORMAT["stages"]["cup"]
        out.append({"stage": "cup", "title": st.get("title"),
                    "seeded_by": "points",
                    "values": values_for("cup_champion", "cup_third_place"),
                    "tie": league_rule("tiebreaker_rules", "cup_game"),
                    "rounds": [{"name": r["name"], "kind": kind(r["name"]),
                                "weeks": tuple(r["weeks"])}
                               for r in st["rounds"]]})
    return out


def _seeds(season_matchups, last_week, by):
    """Bracket seeds: by points (the Cup), or by the regular-season
    standings (data_loader.standings_order) -- not raw wins then points."""
    pts, _wins = _cumulative(season_matchups, last_week)
    if by == "points":
        order = sorted(pts, key=lambda m: pts[m], reverse=True)
    else:
        records, h2h, rpts = _records(season_matchups, last_week)
        order = standings_order(records, h2h, rpts, sorted(records))
    return {m: i + 1 for i, m in enumerate(order)}


def _expected(values, kind, p):
    v = lambda k: values.get(k, 0.0)  # noqa: E731
    final = 0.5 * v(1) + 0.5 * v(2)
    third = 0.5 * v(3) + 0.5 * v(4)
    if kind == "semis":
        return p * final + (1 - p) * third
    if kind == "final":
        return p * v(1) + (1 - p) * v(2)
    return p * v(3) + (1 - p) * v(4)


def bracket_week(season_matchups: list, week: int, season: str,
                 hist_sigma: float) -> tuple[dict, list]:
    """({manager: bracket consequence}, [bracket Angles]) for one week."""
    cons, angles = {}, []
    games_this = [m for m in season_matchups if m["week"] == week]
    for br in bracket_structure(season):
        rounds = br["rounds"]
        first = min(r["weeks"][0] for r in rounds)
        if not any(r["weeks"][0] <= week <= r["weeks"][1] for r in rounds):
            continue
        seeds = _seeds(season_matchups, first - 1, br["seeded_by"])
        by_seed = {v: k for k, v in seeds.items()}
        pts, _ = _cumulative(season_matchups, first - 1)
        nwk = max(1, len({m["week"] for m in season_matchups
                          if m["week"] < first}))
        avg = {m: pts[m] / nwk for m in pts}
        vals = br["values"]
        semis = next(r for r in rounds if r["kind"] == "semis")
        pairs = {"semis": [(by_seed.get(1), by_seed.get(4)),
                           (by_seed.get(2), by_seed.get(3))]}

        def series(a, b, r, upto):
            wa = wb = 0
            for m in season_matchups:
                if not (r["weeks"][0] <= m["week"] <= min(upto, r["weeks"][1])):
                    continue
                if {m["manager_a"], m["manager_b"]} != {a, b}:
                    continue
                a_won = _game_winner(m, seeds, br["tie"]) == a
                wa, wb = wa + a_won, wb + (not a_won)
            return wa, wb

        need = (semis["weeks"][1] - semis["weeks"][0]) // 2 + 1
        winners, losers = [], []
        for a, b in pairs["semis"]:
            wa, wb = series(a, b, semis, semis["weeks"][1])
            if max(wa, wb) >= need:
                (winners if wa > wb else losers).append(a)
                (losers if wa > wb else winners).append(b)
        pairs["final"] = [tuple(winners)] if len(winners) == 2 else []
        pairs["third"] = [tuple(losers)] if len(losers) == 2 else []
        swings = [abs(_expected(vals, k, 1.0) - _expected(vals, k, 0.5))
                  for k in ("semis", "final", "third")]
        norm = max(swings) or 1.0
        for r in rounds:
            if not (r["weeks"][0] <= week <= r["weeks"][1]):
                continue
            need_r = (r["weeks"][1] - r["weeks"][0]) // 2 + 1
            for a, b in pairs.get(r["kind"], []):
                g = next((m for m in games_this if {m["manager_a"],
                                                    m["manager_b"]} == {a, b}),
                         None)
                if g is None:
                    continue
                w0 = series(a, b, r, week - 1)
                w1 = series(a, b, r, week)
                for side, (x0, y0), (x1, y1) in ((a, w0, w1),
                                                 (b, w0[::-1], w1[::-1])):
                    d = abs(_expected(vals, r["kind"], _p_series(x1, y1,
                                                                 need_r)) -
                            _expected(vals, r["kind"], _p_series(x0, y0,
                                                                 need_r)))
                    cons[side] = cons.get(side, 0.0) + d / norm
                a_won = _game_winner(g, seeds, br["tie"]) == a
                win, lose = (a, b) if a_won else (b, a)
                p_win = _phi((avg.get(win, 0) - avg.get(lose, 0)) /
                             (hist_sigma * math.sqrt(2)))
                ww, ll = w1 if a_won else w1[::-1]
                decided = max(ww, ll) >= need_r
                # A best-of-3 plays all three weeks. A series settled 2-0 in
                # week 17 still has a game in week 18; that game decides
                # nothing, and the liability belongs to week 17 only.
                settled_before = max(w0) >= need_r
                tag = f"{br['stage']} " if br["stage"] == "cup" else ""
                sw, sl = seeds.get(win), seeds.get(lose)
                if not decided:
                    text = (f"{win} ({sw} seed) {'leads' if ww > ll else 'evens'}"
                            f" the {tag}{r['name'].lower()} series with {lose} "
                            f"({sl} seed), {ww}-{ll}")
                elif settled_before:
                    text = (f"{win} beat {lose} in a {tag}"
                            f"{r['name'].lower()} game the series had "
                            f"already settled")
                elif r["kind"] == "final":
                    title = (br["title"] or "title").replace(
                        "Champion", "championship").replace(
                        "Cup championship", "Cup").lower().replace(
                        "cup", "Cup")
                    text = (f"{win} ({sw} seed) won the {title} over "
                            f"{lose} ({sl} seed)")
                elif r["kind"] == "semis":
                    text = (f"{win} ({sw} seed) knocked {lose} ({sl} seed) out "
                            f"of the {tag}{r['name'].lower()}")
                    if br["stage"] == "playoffs":
                        from modules.data_loader import league_rule
                        po = league_rule("payouts", "playoff_champion")
                        text += (f": {lose} pays ${int(po['per_payer'])} into "
                                 f"the ${int(po['total'])} playoff pot, {win} "
                                 f"is clear of it")
                else:
                    text = (f"{win} beat {lose} in the {tag}"
                            f"{r['name'].lower()} game")
                angles.append(Angle("bracket", (win, lose), text,
                                    _u(p_win, 1000, max(len(games_this), 1)),
                                    source="bracket"))
    return cons, angles


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
    direction: str = ""       # score: high/low; streak: won/lost
    stat: float = 0.0         # score: relative score; streak: length
    k: int = 1                # chances the week had (see _u)
    repeat: bool = False

    @property
    def key(self):
        return (self.family, self.managers[0])

    def as_dict(self) -> dict:
        return {"family": self.family, "managers": list(self.managers),
                "text": self.text, "score": round(self.score, 3),
                "unusualness": round(self.unusualness, 3),
                "consequence": round(self.consequence, 3),
                "parts": {k: round(v, 3) for k, v in self.parts.items()},
                "source": self.source, "direction": self.direction,
                "repeat": self.repeat}


def matchup_angles(season_matchups: list, week: int, hist: History,
                   reg_last: int) -> list[Angle]:
    out = []
    this = [m for m in season_matchups if m["week"] == week]
    for m in this:
        a, b = m["manager_a"], m["manager_b"]
        if m["score_a"] == m["score_b"]:
            # a T (tiebreaker_rules.regular_season_week) -- nobody "beat" anyone
            p = _two_sided(hist.margins, 0.0)
            out.append(Angle("margin", (a, b), f"{a} and {b} tied at {m['score_a']:.2f}",
                             _u(p, len(hist.margins), len(this))))
            continue
        w, l = (a, b) if m["score_a"] > m["score_b"] else (b, a)
        margin = abs(m["score_a"] - m["score_b"])
        p = _two_sided(hist.margins, margin)
        q = bisect_left(hist.margins, margin) / len(hist.margins)
        side = " (one of the closest quarter of all games)" if q < 0.25 else (
            " (one of the widest quarter of all games)" if q > 0.75 else "")
        out.append(Angle("margin", (w, l),
                         f"{w} beat {l} by {margin:.2f}{side}",
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
                             _u(p, hist.team_weeks, len(scores)),
                             direction="high" if s >= mean else "low",
                             stat=s / mean, k=len(scores)))
    if week <= reg_last:
        seq = defaultdict(list)
        for x in sorted(season_matchups, key=lambda x: x["week"]):
            if x["week"] > week:
                continue
            # W / L / T: a T ends a winning AND a losing streak (interim
            # rule, flagged to Nick 10-20; History.from_matchups agrees)
            o = week_outcome(x["score_a"], x["score_b"])
            seq[x["manager_a"]].append({"a": "W", "b": "L"}.get(o, "T"))
            seq[x["manager_b"]].append({"a": "L", "b": "W"}.get(o, "T"))
        for mgr, xs in seq.items():
            n = _run_lengths(xs)[-1] if xs else 0
            if n >= 2 and xs[-1] in ("W", "L"):
                won = xs[-1] == "W"
                out.append(Angle("streak", (mgr,),
                                 f"{mgr} has {'won' if won else 'lost'} "
                                 f"{n} straight",
                                 _u(_tail_ge(hist.runs, n), len(hist.runs),
                                    len(seq)),
                                 direction="won" if won else "lost",
                                 stat=n, k=len(seq)))
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
PAIR_FAMILIES = {"margin", "upset", "spread", "bracket"}

# Which races an angle bears on. A team score is points: the Cup race. A
# streak or a standings lead is wins: the standings. Without this, "Nick
# leads by 5 games" led 2025-26 week 19 on the Cup movement of Nick's
# blowout, and a -33% score in a playoff semifinal outranked the 1 seed
# being knocked out.
RACES = {"score": ("cup",), "record": ("cup",),
         "margin": ("cup", "standings"), "spread": ("cup", "standings"),
         "upset": ("standings", "bracket"), "streak": ("standings",),
         "standings": ("standings",), "milestone": ("standings",),
         "bracket": ("bracket",), "decided": ("decided",)}


def score(angles: list[Angle], cons: dict) -> None:
    for a in angles:
        parts = {"cup": 0.0, "standings": 0.0, "bracket": 0.0, "decided": 0.0}
        tot = 0.0
        who = a.managers if a.family in PAIR_FAMILIES else a.managers[:1]
        races = RACES.get(a.family, ("cup", "standings"))
        for m in who:
            c = {k: (v if k in races else 0.0)
                 for k, v in cons.get(m, {}).items()}
            # The race it moved MOST, not the sum: a margin is eligible for
            # both races, and summing gave it two bites where a score or a
            # streak gets one (Nick, 10-07: margins led 11 of 23 weeks on
            # that arithmetic).
            t = max(c.values(), default=0.0)
            if t >= tot:
                tot, parts = t, c
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


def apply_repeats(cands: list[Angle], last_lead: Optional[dict],
                  hist: History) -> int:
    """Last week's lead, told again, is news only by how much it went on.
    An angle with the same subject, kind and direction as last week's lead
    is scored on its CONDITIONAL rarity -- given last week, how unusual is
    this week? -- from how often prior seasons repeated it. (Nick, 10-07:
    "Garrett scored X, -18%" led weeks 4 and 5 back to back.) Families
    without a model of their own repetition are left alone."""
    if not last_lead:
        return 0
    n = 0
    for a in cands:
        if (a.family, a.managers[0], a.direction) != (
                last_lead.get("family"), (last_lead.get("managers") or [""])[0],
                last_lead.get("direction", "")):
            continue
        if a.family == "score":
            p = hist.p_score_again(a.stat, a.direction)
        elif a.family == "streak":
            p = hist.p_streak_again(int(a.stat))
        else:
            continue
        a.unusualness = _u(p, hist.team_weeks, a.k)
        a.repeat = True
        a.text += " (continues last week's lead)"
        n += 1
    return n


DEAD_U = math.log(2)    # no rarer than a coin flip


def is_dead(lead: Optional[Angle]) -> Optional[str]:
    """A week with no lead: the best angle is no rarer than a coin flip,
    or it moved nothing. Told as a lead, it invites the writer to invent
    significance -- the hype the voice rules out."""
    if lead is None:
        return "no angles"
    if lead.consequence >= 1.0:
        return None          # a decisive game leads, however expected
    if lead.consequence < CONSEQUENCE_FLOOR:
        return "nothing this week moved the Cup or standings races"
    if lead.unusualness < DEAD_U:
        return "nothing this week was rarer than a coin flip"
    return None


def select(ranked: list[Angle]) -> dict:
    dead = is_dead(ranked[0] if ranked else None)
    return {"lead": ranked[0].as_dict() if ranked else None,
            "secondary": [a.as_dict() for a in ranked[1:1 + SECONDARY]],
            "dead": dead}


def run_week(season_matchups: list, week: int, hist: History,
             cup_last: Optional[int], reg_last: int,
             stories: Optional[list] = None,
             last_used: Optional[dict] = None,
             season: Optional[str] = None,
             last_lead: Optional[dict] = None,
             pick_ownership: Optional[dict] = None) -> dict:
    cands = matchup_angles(season_matchups, week, hist, reg_last)
    bcons, bangles = (bracket_week(season_matchups, week, season, hist.sigma)
                      if season else ({}, []))
    cands += bangles
    if stories:
        tw = 2 * len([m for m in season_matchups if m["week"] <= week])
        nm = len([m for m in season_matchups if m["week"] == week])
        cands += storyline_angles(stories, hist, week, tw, nm, 2 * nm)
    cands += decided_angles(season_matchups, week, reg_last, hist)
    cands = merge(cands)
    repeats = apply_repeats(cands, last_lead, hist)
    cons = consequence(season_matchups, week, cup_last, reg_last, hist.sigma)
    for m, v in bcons.items():
        cons.setdefault(m, {"cup": 0.0, "standings": 0.0, "bracket": 0.0, "decided": 0.0})
        cons[m]["bracket"] = v
    for m, v in decided_consequence(season_matchups, week, reg_last).items():
        cons.setdefault(m, {"cup": 0.0, "standings": 0.0, "bracket": 0.0, "decided": 0.0})
        cons[m]["decided"] = v
    score(cands, cons)
    ranked, moved = rank(cands, last_used or {})
    sel = select(ranked)
    sel["week"] = week
    sel["recency_reordered"] = moved
    sel["repeats_discounted"] = repeats
    from modules.standing_threads import lines as standing_lines
    sel["race_state"] = standing_lines(season_matchups, week, season,
                                       cup_last, reg_last, pick_ownership)
    # What decided money this week -- the gate for every dollar figure in
    # the draft (check_draft reads it from angles_weekN.json).
    from modules.standing_threads import money_events
    sel["money_events"] = [list(e) for e in
                           money_events(season_matchups, week, season, reg_last)]
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


def last_lead_from(out_dir, week: int) -> Optional[dict]:
    import json
    from pathlib import Path
    f = Path(out_dir) / f"angles_week{week - 1}.json"
    if not f.exists():
        return None
    sel = json.loads(f.read_text(encoding="utf-8"))
    return None if sel.get("dead") else sel.get("lead")


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
    import json
    trades = Path(base) / "config" / "TRADES.json"
    picks = json.loads(trades.read_text(encoding="utf-8")).get(
        "draft_pick_ownership") if trades.exists() else None
    return run_week(sm, week, hist, cup_last, reg_last, stories,
                    recency_from(Path(base) / "output", week), season,
                    last_lead_from(Path(base) / "output", week), picks)


def money_line(sel: dict) -> str:
    """The instruction the drafter reads; check_draft enforces it."""
    ev = sel.get("money_events")
    if ev is None:
        raise KeyError("angles selection has no money_events")
    if not ev:
        return ("**Money this week: nothing was decided.** Quote no dollar "
                "figures anywhere in the newsletter; a pot can be named "
                "without its amount. (Checked: a dollar figure this week is a "
                "claim-check finding.)")
    words = {"clinched_title": "clinched the regular-season title",
             "out_of_title": "out of the regular-season title race",
             "safe_from_paying": "settled out of the regular-season pot's "
                                 "paying places",
             "will_pay": "settled into the regular-season pot's paying places",
             "semifinal_lost": "lost his playoff semifinal",
             "semifinal_won": "won his playoff semifinal",
             "playoff_title": "won the playoff championship"}
    what = "; ".join(f"{m} {words[e]}" for e, m in ev)
    return (f"**Money this week:** {what}. Dollar figures belong to these "
            "lines only. A liability that held last week and holds this week "
            "is not news for anyone it applies to.")


def render_markdown(sel: dict) -> str:
    def line(a):
        p = a["parts"]
        bits = [f"{k} {p[k]:.2f}" for k in ("cup", "standings", "bracket")
                if p.get(k)]
        return (f"{a['text']}  _(unusualness {a['unusualness']:.2f} x "
                f"consequence {a['consequence']:.2f}"
                f"{': ' + ', '.join(bits) if bits else ''})_")
    if sel.get("dead"):
        out = ["## -> ANGLES -> NO LEAD THIS WEEK", "",
               f"Nothing this week earns a lead: {sel['dead']}. Do NOT "
               "build an opening out of the result below -- that is how "
               "significance gets invented. Open on the state of the races, "
               "or on lore (an approved entry about whoever the race is "
               "about), and keep the week's results to their sections.", ""]
        out += [f"- {x}" for x in sel.get("race_state", [])]
        out += ["", money_line(sel)]
        if sel.get("lead"):
            out += ["", f"(Best of a quiet week, for reference only: "
                        f"{sel['lead']['text']})"]
        return "\n".join(out) + "\n"
    threads = ["", "**Standing threads** -- the four races, every week. "
               "Mention where they stand; settled races stay as history; "
               "they lead only when something is decided:",
               ""] + [f"- {x}" for x in sel.get("race_state", [])]
    out = ["## -> ANGLES -> WHAT LEADS THIS WEEK", "",
           "Ranked by how unusual (against every prior season) x how much it "
           "moved the Cup-seeding and standings races. Open the newsletter "
           "with the lead. The scores are for you, not the reader.", ""]
    if sel.get("lead"):
        out.append(f"- **Lead:** {line(sel['lead'])}")
    for a in sel.get("secondary", []):
        out.append(f"- {line(a)}")
    if sel.get("race_state"):
        out += threads
    out += ["", money_line(sel)]
    return "\n".join(out) + "\n"
