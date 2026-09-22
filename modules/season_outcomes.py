"""
season_outcomes.py

Who won what in a season, computed one way.

This used to live in scripts/rollup_season_to_history.py, while
scripts/rollover_leaguehistory.py had its own version that assumed the
postseason was the last two weeks of the season. From 2026-27 the last two
weeks are the CUP, so that version credited the Cup winner as Playoff
Champion and wrote it into LEAGUEHISTORY.xlsx, permanently.

Three different titles come out of a season here and they are not
interchangeable:

    League Champion   best record over the regular season (weeks 1-15 from
                      2026-27, 1-21 before). Decides the draft order and the
                      payouts. This league's real champion.
    Playoff Champion  winner of the bracket -- best-of-3 semifinals and final
                      from 2026-27, single games before it.
    Cup Champion      winner of weeks 22-23. New in 2026-27; earns an extra
                      keeper rather than money. NOT the playoff champion.

Every week boundary comes from league_config via data_loader, so none of it
has to be restated when the format changes again.
"""

from collections import defaultdict

from .data_loader import (
    MANAGERS, cup_winner, is_regular_season_week, stage_weeks,
)


def _scores_by_week(records):
    out = {}
    for mgr, rows in records.get("weekly_scores", {}).items():
        if not isinstance(rows, list):
            continue
        for row in rows:
            week = row.get("week")
            if week is None:
                continue
            out.setdefault(int(week), {})[mgr] = float(row.get("score", 0.0) or 0.0)
    return out


def build_matchups(season_key, records, schedule):
    """Rows in the all_matchups.json schema, in week order.

    Ties leave winner and loser as None. No season on file has one -- scores
    carry two decimals -- but inventing a winner would be worse than saying
    there wasn't one.
    """
    scores = _scores_by_week(records)
    rows = []
    for wk in sorted(schedule.get("weeks", []), key=lambda w: w.get("week", 0)):
        week = wk.get("week")
        if week is None:
            continue
        week = int(week)
        for mu in wk.get("matchups", []):
            a, b = mu.get("manager_a"), mu.get("manager_b")
            sa = scores.get(week, {}).get(a)
            sb = scores.get(week, {}).get(b)
            if a is None or b is None or sa is None or sb is None:
                continue
            winner = a if sa > sb else b if sb > sa else None
            loser = b if sa > sb else a if sb > sa else None
            rows.append({
                "season": season_key, "week": week,
                "manager_a": a, "manager_b": b,
                "score_a": round(sa, 2), "score_b": round(sb, 2),
                "winner": winner, "loser": loser,
                "margin": round(abs(sa - sb), 2),
            })
    return rows


def _playoff_placing(season_key, rows):
    """{manager: 1..4} from the bracket, or {} if no bracket was played.

    The final is whichever last-week matchup is between the two managers who
    won in the first bracket week; the other is the consolation game. Derived
    rather than assumed, because the bracket is not always the same weeks and
    from 2026-27 it is six of them.
    """
    span = stage_weeks(season_key, "playoffs")
    if not span:
        return {}
    first, last = span
    def series_winners(lo, hi):
        tally = {}
        for r in rows:
            if not (lo <= r["week"] <= hi) or not r["winner"]:
                continue
            key = tuple(sorted((r["manager_a"], r["manager_b"])))
            tally.setdefault(key, {})
            tally[key][r["winner"]] = tally[key].get(r["winner"], 0) + 1
            tally[key].setdefault(r["loser"], 0)
        out = []
        for (x, y), w in tally.items():
            if w.get(x, 0) == w.get(y, 0):
                continue
            win = x if w.get(x, 0) > w.get(y, 0) else y
            out.append((win, y if win == x else x))
        return out

    # Semifinal round is the first half of the bracket; the final round is
    # whatever is left. For a two-week bracket that is one week each.
    mid = first + (last - first) // 2
    semis = series_winners(first, mid if last > first else first)
    if len(semis) != 2:
        return {}
    advanced = {w for w, _ in semis}
    finals = series_winners(mid + 1 if last > first else last, last)
    placing = {}
    for win, lose in finals:
        if win in advanced and lose in advanced:
            placing[win], placing[lose] = 1, 2
        elif win not in advanced and lose not in advanced:
            placing[win], placing[lose] = 3, 4
    return placing if len(placing) == 4 else {}


def build_standings(season_key, rows):
    """Rows in the all_standings.json schema, plus explicit scope fields.

    WHAT `rank` ACTUALLY MEANS. Checked against all eight stored seasons: it
    is the rank by ALL-GAMES W-L -- regular season and postseason added
    together and sorted. It is not the playoff finish and it is not the
    league title. In 2020-21 it has Nick 1st; Hayden won that bracket. In
    2017-18 it has Nick 2nd and Hayden 3rd; the bracket finished Hayden 2nd
    and Nick 3rd. It coincides with the regular-season order most years,
    which is exactly why nobody noticed.

    That number answers no question this league asks, and from 2026-27 it
    gets worse -- it would blend 15 regular-season games with a six-week
    bracket and a two-week Cup. It is preserved as-is for continuity with the
    eight seasons already written, tagged with `rank_basis` so it can never
    be mistaken again, and joined by the two ranks that mean something:

        regular_season_rank  the League Champion order -- what decides the
                             title, the draft order and the payouts
        playoff_rank         the bracket finish -- the Playoff Champion
    """
    from collections import defaultdict as _dd
    allw = _dd(lambda: [0, 0, 0])   # wins, losses, ties
    regw = _dd(lambda: [0, 0])
    points = _dd(float)
    h2h = _dd(lambda: _dd(int))

    for r in rows:
        points[r["manager_a"]] += r["score_a"]
        points[r["manager_b"]] += r["score_b"]
        in_reg = is_regular_season_week(season_key, r["week"])
        if not r["winner"]:
            allw[r["manager_a"]][2] += 1
            allw[r["manager_b"]][2] += 1
            continue
        allw[r["winner"]][0] += 1
        allw[r["loser"]][1] += 1
        if in_reg:
            regw[r["winner"]][0] += 1
            regw[r["loser"]][1] += 1
            h2h[r["winner"]][r["loser"]] += 1

    managers = sorted(allw)

    # Regular-season rank: wins, then head-to-head AMONG THE TIED GROUP, then
    # total points -- the rule in league_config.tiebreaker_rules, and the same
    # one build_draft_order.py applies.
    #
    # "Among the tied group" is the part that matters and the part that is
    # easy to get wrong. Summing a manager's head-to-head wins against the
    # whole league just recovers their win total and changes nothing, so the
    # tie silently falls through to points. In 2025-26 that would have ranked
    # Garrett 2nd on points when Benton had actually won the season series
    # 4-3 -- and this rank sets the draft order.
    from itertools import groupby
    reg_order = []
    by_wins = sorted(managers, key=lambda m: -regw[m][0])
    for _, group in groupby(by_wins, key=lambda m: regw[m][0]):
        tied = list(group)
        if len(tied) > 1:
            within = {m: sum(h2h[m][o] for o in tied if o != m) for m in tied}
            tied.sort(key=lambda m: (-within[m], -points[m], m))
        reg_order.extend(tied)
    reg_rank = {m: i for i, m in enumerate(reg_order, 1)}

    placing = _playoff_placing(season_key, rows)

    # The file's own convention: all-games W-L, ties broken on points.
    all_games_order = sorted(managers,
                             key=lambda m: (-allw[m][0], -points[m], m))
    all_games_rank = {m: i for i, m in enumerate(all_games_order, 1)}

    out = []
    for m in managers:
        wins, losses, ties = allw[m]
        out.append({
            "season": season_key,
            "manager": m,
            "rank": all_games_rank[m],
            "rank_basis": "all_games_record",
            "wins": wins,
            "losses": losses,
            "ties": ties,
            "points_for": round(points[m], 1),
            "reg_wins": regw[m][0],
            "reg_losses": regw[m][1],
            "regular_season_rank": reg_rank[m],
            "playoff_rank": placing.get(m),
        })
    out.sort(key=lambda r: r["rank"])
    return out


def league_champion(standings):
    """The regular-season winner: the League Champion."""
    for row in standings:
        if row.get("regular_season_rank") == 1:
            return row["manager"]
    return None


def playoff_champion(standings):
    """The bracket winner. None when no bracket was played (2019-20)."""
    for row in standings:
        if row.get("playoff_rank") == 1:
            return row["manager"]
    return None


def cup_champion(season, rows=None):
    """The Cup winner.

    Read from league_config keeper_rules.cup_winners, because the Cup decides
    next season's keeper counts and that result has to be written down rather
    than re-derived every time. Falls back to deriving it from the weeks 22-23
    matchups when the config has not been filled in yet.
    """
    recorded = cup_winner(season)
    if recorded:
        return recorded
    span = stage_weeks(season, "cup")
    if not span or not rows:
        return None
    first, last = span
    semi_winners = {r["winner"] for r in rows
                    if r.get("winner") and r["week"] == first}
    for r in rows:
        if r["week"] != last or not r.get("winner"):
            continue
        if {r["manager_a"], r["manager_b"]} <= semi_winners:
            return r["winner"]
    return None


def season_outcomes(season, records, schedule):
    """(league_champion, playoff_champion, cup_champion, standings)."""
    rows = build_matchups(season, records, schedule)
    if not rows:
        return None, None, None, []
    standings = build_standings(season, rows)
    return (league_champion(standings), playoff_champion(standings),
            cup_champion(season, rows), standings)
