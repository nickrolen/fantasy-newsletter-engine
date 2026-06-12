"""
luck_index.py

Computes the Luck Index (All-Play Expected Wins) for each manager.

Uses the all-play method: each week, a manager's expected wins equals the
fraction of OTHER managers they outscored that week. Summed across weeks,
this gives the wins a team "should have" against a balanced (round-robin)
schedule. Comparing to actual wins isolates schedule luck -- the thing
fantasy luck actually is.

Formula:
    For each week, rank managers 1..N by score (1 = lowest, N = highest).
    Expected wins this week = (rank - 1) / (N - 1)
    Season expected wins = sum across weeks
    Luck Index = Actual Wins - Expected Wins

A positive Luck Index means the manager has won more games than their
scoring would suggest against a balanced schedule -- they benefited from
favorable matchup draws. A negative one means the opposite.

Historical note: the original implementation used a Pythagorean
expected-record model with exponent 2. This was replaced with all-play
expected wins because:
  (a) exponent 2 systematically relabeled skill differential as luck;
  (b) all-play directly measures schedule luck, which is what fantasy
      luck actually is;
  (c) all-play is the industry standard for fantasy sports analysis.

DESTINATION: Section 5 (Fun Facts) -- debate-sparking stat for the newsletter.

INTEGRATION POINTS:
    - report_builder.py: build_stats_report() calls build_luck_index()
    - format_stats_report.py: format_section_5_fun_facts() renders the table
"""

from dataclasses import dataclass, field
from typing import Optional

from .data_loader import FantasyData, MANAGERS, CURRENT_SEASON


# =============================================================================
# CONFIGURATION
# =============================================================================

# Luck rating thresholds, calibrated to the null distribution of all-play luck.
#
# Monte Carlo null experiment (4 equal teams, random schedules): the SD of
# (actual wins - all-play expected wins) is ~= 1.49 wins over a 20-week season,
# i.e. ~= 0.333 * sqrt(weeks). Fixed +/-1.0 / +/-2.0 bands sat at 0.67 / 1.34
# sigma, so a perfectly average team drew a "Lucky/Unlucky" label ~50% of the
# time. Labels now fire at z >= 1.5 ("Lucky"/"Unlucky", ~2.2 wins at week 20)
# and z >= 2.0 ("Very", ~3.0 wins at week 20), scaling with weeks played.
LUCK_NULL_SD_PER_SQRT_WEEK = 0.333
LUCK_Z_THRESHOLD = 1.5
VERY_LUCK_Z_THRESHOLD = 2.0


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class ManagerLuckIndex:
    """Luck Index results for a single manager."""
    manager: str

    # Raw inputs
    points_for: float = 0.0
    points_against: float = 0.0
    games_played: int = 0

    # Actual record
    actual_wins: int = 0
    actual_losses: int = 0
    actual_win_pct: float = 0.0

    # All-play expected record
    expected_win_pct: float = 0.0
    expected_wins: float = 0.0
    expected_losses: float = 0.0

    # Luck metric
    luck_index: float = 0.0
    luck_rating: str = ""

    # Per-game averages
    avg_points_for: float = 0.0
    avg_points_against: float = 0.0
    scoring_margin: float = 0.0

    def to_dict(self) -> dict:
        return {
            "manager": self.manager,
            "points_for": round(self.points_for, 2),
            "points_against": round(self.points_against, 2),
            "games_played": self.games_played,
            "actual_record": f"{self.actual_wins}-{self.actual_losses}",
            "actual_wins": self.actual_wins,
            "actual_losses": self.actual_losses,
            "actual_win_pct": round(self.actual_win_pct, 1),
            "expected_record": f"{self.expected_wins:.1f}-{self.expected_losses:.1f}",
            "expected_wins": round(self.expected_wins, 1),
            "expected_losses": round(self.expected_losses, 1),
            "expected_win_pct": round(self.expected_win_pct, 1),
            "luck_index": round(self.luck_index, 1),
            "luck_rating": self.luck_rating,
            "avg_points_for": round(self.avg_points_for, 1),
            "avg_points_against": round(self.avg_points_against, 1),
            "scoring_margin": round(self.scoring_margin, 1),
        }


@dataclass
class LuckIndexReport:
    """Complete Luck Index report for the league."""
    managers: dict = field(default_factory=dict)
    method: str = "all-play"
    weeks_analyzed: int = 0
    luckiest: str = ""
    unluckiest: str = ""

    def to_dict(self) -> dict:
        return {
            "method": self.method,
            "weeks_analyzed": self.weeks_analyzed,
            "luckiest": self.luckiest,
            "unluckiest": self.unluckiest,
            "managers": {
                m: li.to_dict() for m, li in self.managers.items()
            },
        }


# =============================================================================
# CORE COMPUTATION
# =============================================================================

def _allplay_expected_wins_for_week(week_scores):
    """
    Compute all-play expected wins for one week, given a list of
    (manager, score) pairs.

    Each manager's expected wins this week equals the fraction of OTHER
    managers they outscored. Ties split the credit evenly (average rank).

    Returns: {manager: expected_wins_this_week} where each value is in [0, 1].
    """
    n = len(week_scores)
    if n <= 1:
        return {m: 0.0 for m, _ in week_scores}

    # Sort ascending (lowest score first). Rank 1 = lowest, rank N = highest.
    sorted_scores = sorted(week_scores, key=lambda x: x[1])

    expected = {}
    i = 0
    while i < n:
        j = i
        while j + 1 < n and sorted_scores[j + 1][1] == sorted_scores[i][1]:
            j += 1

        avg_rank = (i + 1 + j + 1) / 2.0
        share = (avg_rank - 1) / (n - 1)

        for k in range(i, j + 1):
            expected[sorted_scores[k][0]] = share

        i = j + 1

    return expected


def _reconstruct_matchup_results(weekly_scores, schedule, through_week):
    """
    Reconstruct week-by-week matchup results from weekly_scores + schedule.
    """
    score_lookup = {}
    for manager, scores_list in weekly_scores.items():
        score_lookup[manager] = {
            entry["week"]: entry["score"]
            for entry in scores_list
        }

    results = []
    for week_data in schedule.get("weeks", []):
        week_num = week_data["week"]
        if week_num > through_week:
            break

        for matchup in week_data.get("matchups", []):
            mgr_a = matchup["manager_a"]
            mgr_b = matchup["manager_b"]

            score_a = score_lookup.get(mgr_a, {}).get(week_num)
            score_b = score_lookup.get(mgr_b, {}).get(week_num)

            if score_a is None or score_b is None:
                continue

            # Tie convention for luck index: winner=None signals a tie, which
            # downstream splits credit 0.5/0.5 between both managers. This is
            # the mathematically correct treatment for schedule-luck
            # measurement (a tie is half a win, half a loss, for each side).
            if score_a > score_b:
                winner = mgr_a
            elif score_b > score_a:
                winner = mgr_b
            else:
                winner = None  # tie -- split credit downstream

            results.append({
                "week": week_num,
                "manager_a": mgr_a,
                "manager_b": mgr_b,
                "score_a": score_a,
                "score_b": score_b,
                "winner": winner,
            })

    return results


def _classify_luck(luck, games_played=20):
    """
    Classify a luck index into a rating string, scaled to sample size.

    The label thresholds are z-scores against the null distribution of
    all-play luck (sigma ~= 0.333 * sqrt(games_played)), so early-season
    noise does not earn a luck narrative.
    """
    import math
    sigma = LUCK_NULL_SD_PER_SQRT_WEEK * math.sqrt(max(games_played, 1))
    if luck >= VERY_LUCK_Z_THRESHOLD * sigma:
        return "Very Lucky"
    elif luck >= LUCK_Z_THRESHOLD * sigma:
        return "Lucky"
    elif luck <= -VERY_LUCK_Z_THRESHOLD * sigma:
        return "Very Unlucky"
    elif luck <= -LUCK_Z_THRESHOLD * sigma:
        return "Unlucky"
    return "Fair"


def compute_luck_index(records, schedule, through_week):
    """
    Compute the Luck Index for all managers through a given week
    using all-play expected wins.
    """
    weekly_scores = records.get("weekly_scores", {})

    matchup_results = _reconstruct_matchup_results(
        weekly_scores, schedule, through_week
    )

    if not matchup_results:
        return LuckIndexReport(weeks_analyzed=0)

    # Note: wins/losses are floats here -- a tie awards 0.5 wins and 0.5
    # losses to each side (project-wide tie convention for luck calc).
    manager_data = {m: {"pf": 0.0, "pa": 0.0, "wins": 0.0, "losses": 0.0, "games": 0}
                    for m in MANAGERS}

    for result in matchup_results:
        mgr_a = result["manager_a"]
        mgr_b = result["manager_b"]
        score_a = result["score_a"]
        score_b = result["score_b"]
        winner = result["winner"]

        if mgr_a in manager_data:
            manager_data[mgr_a]["pf"] += score_a
            manager_data[mgr_a]["pa"] += score_b
            manager_data[mgr_a]["games"] += 1
            if winner == mgr_a:
                manager_data[mgr_a]["wins"] += 1
            elif winner == mgr_b:
                manager_data[mgr_a]["losses"] += 1
            else:
                # Tie -- split credit evenly.
                manager_data[mgr_a]["wins"] += 0.5
                manager_data[mgr_a]["losses"] += 0.5

        if mgr_b in manager_data:
            manager_data[mgr_b]["pf"] += score_b
            manager_data[mgr_b]["pa"] += score_a
            manager_data[mgr_b]["games"] += 1
            if winner == mgr_b:
                manager_data[mgr_b]["wins"] += 1
            elif winner == mgr_a:
                manager_data[mgr_b]["losses"] += 1
            else:
                # Tie -- split credit evenly.
                manager_data[mgr_b]["wins"] += 0.5
                manager_data[mgr_b]["losses"] += 0.5

    # All-play expected wins over the same week-set as actual matchups
    valid_weeks = sorted({r["week"] for r in matchup_results})

    expected_wins_total = {m: 0.0 for m in MANAGERS}
    for week in valid_weeks:
        week_pairs = []
        for m in MANAGERS:
            for entry in weekly_scores.get(m, []):
                if entry["week"] == week:
                    week_pairs.append((m, entry["score"]))
                    break
        week_expected = _allplay_expected_wins_for_week(week_pairs)
        for m, ew in week_expected.items():
            expected_wins_total[m] += ew

    report = LuckIndexReport(weeks_analyzed=through_week)

    for manager in MANAGERS:
        md = manager_data[manager]
        games = md["games"]

        if games == 0:
            continue

        pf = md["pf"]
        pa = md["pa"]
        actual_wins = md["wins"]
        actual_losses = md["losses"]

        expected_wins = expected_wins_total[manager]
        expected_losses = games - expected_wins
        expected_pct = (expected_wins / games) if games > 0 else 0.0

        actual_pct = (actual_wins / games * 100) if games > 0 else 0.0

        luck = actual_wins - expected_wins
        luck_rating = _classify_luck(luck, games)

        avg_pf = pf / games
        avg_pa = pa / games

        report.managers[manager] = ManagerLuckIndex(
            manager=manager,
            points_for=pf,
            points_against=pa,
            games_played=games,
            actual_wins=actual_wins,
            actual_losses=actual_losses,
            actual_win_pct=actual_pct,
            expected_win_pct=expected_pct * 100,
            expected_wins=expected_wins,
            expected_losses=expected_losses,
            luck_index=luck,
            luck_rating=luck_rating,
            avg_points_for=avg_pf,
            avg_points_against=avg_pa,
            scoring_margin=avg_pf - avg_pa,
        )

    if report.managers:
        sorted_by_luck = sorted(
            report.managers.values(),
            key=lambda x: x.luck_index,
            reverse=True,
        )
        report.luckiest = sorted_by_luck[0].manager
        report.unluckiest = sorted_by_luck[-1].manager

    return report


# =============================================================================
# HISTORICAL LUCK ANALYSIS
# =============================================================================

@dataclass
class SeasonLuck:
    """Luck data for a single season."""
    season: str
    manager: str
    actual_wins: int = 0
    actual_losses: int = 0
    expected_wins: float = 0.0
    luck_index: float = 0.0
    luck_rating: str = ""
    points_for: float = 0.0
    points_against: float = 0.0
    scoring_margin: float = 0.0
    games: int = 0

    def to_dict(self) -> dict:
        return {
            "season": self.season,
            "manager": self.manager,
            "actual_record": f"{self.actual_wins}-{self.actual_losses}",
            "actual_wins": self.actual_wins,
            "actual_losses": self.actual_losses,
            "expected_wins": round(self.expected_wins, 1),
            "luck_index": round(self.luck_index, 1),
            "luck_rating": self.luck_rating,
            "scoring_margin": round(self.scoring_margin, 1),
            "games": self.games,
        }


@dataclass
class CareerLuck:
    """Career luck totals for a manager."""
    manager: str
    total_wins: int = 0
    total_losses: int = 0
    total_games: int = 0
    expected_wins: float = 0.0
    career_luck: float = 0.0
    win_pct: float = 0.0
    expected_win_pct: float = 0.0
    scoring_margin: float = 0.0
    seasons: list = field(default_factory=list)

    luckiest_season: Optional[SeasonLuck] = None
    unluckiest_season: Optional[SeasonLuck] = None

    def to_dict(self) -> dict:
        return {
            "manager": self.manager,
            "actual_record": f"{self.total_wins}-{self.total_losses}",
            "total_wins": self.total_wins,
            "total_losses": self.total_losses,
            "total_games": self.total_games,
            "expected_wins": round(self.expected_wins, 1),
            "career_luck": round(self.career_luck, 1),
            "win_pct": round(self.win_pct, 1),
            "expected_win_pct": round(self.expected_win_pct, 1),
            "scoring_margin": round(self.scoring_margin, 1),
            "seasons": [s.to_dict() for s in self.seasons],
            "luckiest_season": self.luckiest_season.to_dict() if self.luckiest_season else None,
            "unluckiest_season": self.unluckiest_season.to_dict() if self.unluckiest_season else None,
        }


@dataclass
class HistoricalLuckReport:
    """Complete historical luck analysis."""
    managers: dict = field(default_factory=dict)
    seasons_analyzed: list = field(default_factory=list)
    all_time_luckiest: str = ""
    all_time_unluckiest: str = ""
    luckiest_single_season: Optional[SeasonLuck] = None
    unluckiest_single_season: Optional[SeasonLuck] = None
    method: str = "all-play"

    def to_dict(self) -> dict:
        return {
            "method": self.method,
            "seasons_analyzed": self.seasons_analyzed,
            "all_time_luckiest": self.all_time_luckiest,
            "all_time_unluckiest": self.all_time_unluckiest,
            "luckiest_single_season": self.luckiest_single_season.to_dict() if self.luckiest_single_season else None,
            "unluckiest_single_season": self.unluckiest_single_season.to_dict() if self.unluckiest_single_season else None,
            "managers": {m: cl.to_dict() for m, cl in self.managers.items()},
        }


def _reconstruct_weekly_scores_from_matchups(season_matchups):
    """
    Given a list of matchup dicts for ONE season, build:
        {week: {manager: score, ...}}
    """
    by_week = {}
    for m in season_matchups:
        wk = m["week"]
        by_week.setdefault(wk, {})
        by_week[wk][m["manager_a"]] = m["score_a"]
        by_week[wk][m["manager_b"]] = m["score_b"]
    return by_week


def compute_historical_luck(all_matchups, current_season_data=None):
    """
    Compute historical luck index from all_matchups.json data using
    all-play expected wins.
    """
    by_season = {}
    for match in all_matchups:
        by_season.setdefault(match["season"], []).append(match)

    seasons = sorted(by_season.keys())

    if current_season_data:
        cs = current_season_data["season"]
        cs_matchups = current_season_data.get("matchups")
        if cs_matchups:
            by_season[cs] = cs_matchups
            if cs not in seasons:
                seasons.append(cs)

    season_data = {m: {} for m in MANAGERS}

    for season, matchups in by_season.items():
        # Note: wins/losses are floats -- ties split 0.5/0.5 (project tie
        # convention for luck calc).
        per_mgr = {m: {"pf": 0.0, "pa": 0.0, "wins": 0.0, "losses": 0.0, "games": 0}
                   for m in MANAGERS}
        for match in matchups:
            mgr_a, mgr_b = match["manager_a"], match["manager_b"]
            sa, sb = match["score_a"], match["score_b"]
            winner = match["winner"]
            # Determine a tie from the scores (historical matchup dicts may
            # carry "winner" set to one side even on equal scores; rely on
            # scores as the source of truth).
            is_tie = (sa == sb) or (winner is None)
            for mgr, sf, sg, won in [
                (mgr_a, sa, sb, winner == mgr_a),
                (mgr_b, sb, sa, winner == mgr_b),
            ]:
                if mgr not in per_mgr:
                    continue
                per_mgr[mgr]["pf"] += sf
                per_mgr[mgr]["pa"] += sg
                per_mgr[mgr]["games"] += 1
                if is_tie:
                    per_mgr[mgr]["wins"] += 0.5
                    per_mgr[mgr]["losses"] += 0.5
                elif won:
                    per_mgr[mgr]["wins"] += 1
                else:
                    per_mgr[mgr]["losses"] += 1

        weekly = _reconstruct_weekly_scores_from_matchups(matchups)
        exp_wins = {m: 0.0 for m in MANAGERS}
        for wk, score_map in weekly.items():
            week_pairs = [(m, s) for m, s in score_map.items() if m in MANAGERS]
            ew = _allplay_expected_wins_for_week(week_pairs)
            for m, val in ew.items():
                exp_wins[m] += val

        for m in MANAGERS:
            if per_mgr[m]["games"] == 0:
                continue
            season_data[m][season] = {
                "pf": per_mgr[m]["pf"],
                "pa": per_mgr[m]["pa"],
                "wins": per_mgr[m]["wins"],
                "losses": per_mgr[m]["losses"],
                "games": per_mgr[m]["games"],
                "expected_wins": exp_wins[m],
            }

    report = HistoricalLuckReport(seasons_analyzed=seasons)
    all_season_luck = []

    for manager in MANAGERS:
        career = CareerLuck(manager=manager)
        career_pf = 0.0
        career_pa = 0.0
        career_expected_wins = 0.0

        for season in seasons:
            if season not in season_data[manager]:
                continue

            sd = season_data[manager][season]
            games = sd["games"]
            if games == 0:
                continue

            pf, pa = sd["pf"], sd["pa"]
            wins, losses = sd["wins"], sd["losses"]
            exp_wins = sd["expected_wins"]
            luck = wins - exp_wins
            margin = (pf - pa) / games

            season_luck = SeasonLuck(
                season=season,
                manager=manager,
                actual_wins=wins,
                actual_losses=losses,
                expected_wins=exp_wins,
                luck_index=luck,
                luck_rating=_classify_luck(luck, games),
                points_for=pf,
                points_against=pa,
                scoring_margin=margin,
                games=games,
            )

            career.seasons.append(season_luck)
            all_season_luck.append(season_luck)

            career.total_wins += wins
            career.total_losses += losses
            career.total_games += games
            career_pf += pf
            career_pa += pa
            career_expected_wins += exp_wins

        if career.total_games > 0:
            career.expected_wins = career_expected_wins
            career.career_luck = career.total_wins - career_expected_wins
            career.win_pct = career.total_wins / career.total_games * 100
            career.expected_win_pct = (career_expected_wins / career.total_games) * 100
            career.scoring_margin = (career_pf - career_pa) / career.total_games

        if career.seasons:
            career.luckiest_season = max(career.seasons, key=lambda s: s.luck_index)
            career.unluckiest_season = min(career.seasons, key=lambda s: s.luck_index)

        report.managers[manager] = career

    if report.managers:
        sorted_by_luck = sorted(
            report.managers.values(),
            key=lambda x: x.career_luck,
            reverse=True,
        )
        report.all_time_luckiest = sorted_by_luck[0].manager
        report.all_time_unluckiest = sorted_by_luck[-1].manager

    if all_season_luck:
        report.luckiest_single_season = max(all_season_luck, key=lambda s: s.luck_index)
        report.unluckiest_single_season = min(all_season_luck, key=lambda s: s.luck_index)

    return report


def build_historical_luck(data, current_week, current_season=None):
    """
    Build historical luck report including the current season, using
    all-play expected wins throughout.
    """
    if current_season is None:
        current_season = CURRENT_SEASON

    reg_weeks = data.schedule.get("regular_season_weeks", current_week)
    through_week = min(current_week, reg_weeks)

    current_matchups = _reconstruct_matchup_results(
        weekly_scores=data.records.get("weekly_scores", {}),
        schedule=data.schedule,
        through_week=through_week,
    )

    cs_matchups = []
    for r in current_matchups:
        loser = r["manager_b"] if r["winner"] == r["manager_a"] else r["manager_a"]
        cs_matchups.append({
            "season": current_season,
            "week": r["week"],
            "manager_a": r["manager_a"],
            "manager_b": r["manager_b"],
            "score_a": r["score_a"],
            "score_b": r["score_b"],
            "winner": r["winner"],
            "loser": loser,
            "margin": abs(r["score_a"] - r["score_b"]),
        })

    current_season_data = {
        "season": current_season,
        "matchups": cs_matchups,
    }

    historical = compute_historical_luck(
        all_matchups=data.all_matchups,
        current_season_data=current_season_data,
    )

    return historical.to_dict()


# =============================================================================
# CONVENIENCE FUNCTION (for use in report_builder.py)
# =============================================================================

def build_luck_index(data, week):
    """
    Build Luck Index section for the stats report.
    """
    reg_weeks = data.schedule.get("regular_season_weeks", week)
    through_week = min(week, reg_weeks)
    report = compute_luck_index(
        records=data.records,
        schedule=data.schedule,
        through_week=through_week,
    )
    return report.to_dict()




# =============================================================================
# TESTING / MAIN
# =============================================================================

if __name__ == "__main__":
    import sys
    import json
    from pathlib import Path
    
    # Add parent directory to path
    sys.path.insert(0, str(Path(__file__).parent.parent))
    
    from modules.data_loader import load_all_data
    
    base = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
    week = int(sys.argv[2]) if len(sys.argv) > 2 else None
    
    print("Loading data...")
    data = load_all_data(base)
    
    if week is None:
        week = data.current_week
    
    print(f"Computing Luck Index through Week {week}")
    print("=" * 60)
    
    result = build_luck_index(data, week)
    
    print(f"\nPythagorean Exponent: {result['exponent']}")
    print(f"Luckiest: {result['luckiest']}")
    print(f"Unluckiest: {result['unluckiest']}")
    print()
    
    # Print table
    header = f"{'Manager':<10} {'Actual':>8} {'Expected':>10} {'Luck':>6} {'Rating':<14} {'Avg PF':>8} {'Avg PA':>8} {'Margin':>8}"
    print(header)
    print("-" * len(header))
    
    for manager in MANAGERS:
        m = result["managers"].get(manager, {})
        if not m:
            continue
        print(
            f"{m['manager']:<10} "
            f"{m['actual_record']:>8} "
            f"{m['expected_record']:>10} "
            f"{m['luck_index']:>+6.1f} "
            f"{m['luck_rating']:<14} "
            f"{m['avg_points_for']:>8.1f} "
            f"{m['avg_points_against']:>8.1f} "
            f"{m['scoring_margin']:>+8.1f}"
        )
