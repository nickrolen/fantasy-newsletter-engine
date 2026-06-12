"""
fun_facts_generator.py

Auto-generates interesting facts from weekly and season data.
Produces 6-7 fun facts for the newsletter, scored by "interestingness".

FACT CATEGORIES:
- Weekly: Player performances, injuries, efficiency, positional dominance,
          schedule advantages, boom/bust, margin facts, consistency
- Season: Points race, efficiency, streaks, approaching season records  
- Historical: Career milestones, all-time H2H, all-time records (since 2017)

FIXES (v4):
- Removed waiver pickup facts (redundant with waiver table)
- Added positional dominance facts (100+ FP gaps at a position)
- Added schedule advantage facts (5+ game differences)
- Added boom/bust facts (same manager has best AND worst game)
- Added margin facts (close games, blowouts, near-records)
- Added consistency facts (players with all games 40+ or 45+ FP)
"""

from dataclasses import dataclass, field
from typing import Optional
import random

from .data_loader import FantasyData, MANAGERS
from .weekly_stats import WeeklyReport, ManagerWeekStats
from .records_tracker import RecordUpdate, get_current_streaks, get_season_series


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class FunFact:
    """A single fun fact."""
    category: str  # "weekly", "season", "historical"
    subcategory: str  # More specific type
    text: str
    interestingness: float  # 0-100 score
    details: dict = field(default_factory=dict)
    
    def __lt__(self, other):
        return self.interestingness < other.interestingness


# =============================================================================
# HELPER: Get this week's matchup pairs
# =============================================================================

def get_this_week_matchup_pairs(report: WeeklyReport) -> set[tuple[str, str]]:
    """Get set of (manager_a, manager_b) tuples for this week's matchups."""
    pairs = set()
    for matchup in report.matchups:
        # Store both orderings for easy lookup
        pairs.add((matchup.manager_a, matchup.manager_b))
        pairs.add((matchup.manager_b, matchup.manager_a))
    return pairs


def managers_played_this_week(m1: str, m2: str, matchup_pairs: set) -> bool:
    """Check if two managers played each other this week."""
    return (m1, m2) in matchup_pairs


# =============================================================================
# HISTORICAL FACTS (since 2017)
# =============================================================================

def generate_career_milestone_facts(
    records: dict,
    report: WeeklyReport,
) -> list[FunFact]:
    """Generate facts about career milestones (wins, passing other managers)."""
    facts = []
    all_time = records.get("all_time", {})
    careers = all_time.get("manager_careers", {})
    
    if not careers:
        return facts
    
    # Sort managers by career wins
    career_wins = [(m, stats.get("total_wins", 0)) for m, stats in careers.items()]
    career_wins.sort(key=lambda x: -x[1])
    
    # Check for approaching milestone wins (50, 75, 100, 125, 150, etc.)
    for manager, wins in career_wins:
        for milestone in [50, 75, 100, 125, 150, 175, 200]:
            if wins < milestone <= wins + 3:
                away = milestone - wins
                facts.append(FunFact(
                    category="historical",
                    subcategory="career_milestone",
                    text=f"{manager} is just {away} win{'s' if away > 1 else ''} away from {milestone} career victories.",
                    interestingness=82 + (3 - away) * 4,
                    details={"manager": manager, "milestone": milestone, "away": away},
                ))
                break
    
    # Check if someone is close to passing another manager all-time
    for i, (manager, wins) in enumerate(career_wins[1:], 1):
        ahead_manager, ahead_wins = career_wins[i-1]
        gap = ahead_wins - wins
        if 0 < gap <= 3:
            facts.append(FunFact(
                category="historical",
                subcategory="career_race",
                text=f"{manager} is {gap} win{'s' if gap > 1 else ''} behind {ahead_manager} for #{i} on the all-time wins leaderboard.",
                interestingness=78 + (3 - gap) * 4,
                details={"chaser": manager, "leader": ahead_manager, "gap": gap},
            ))
    
    return facts


def generate_historical_h2h_facts(
    records: dict,
    report: WeeklyReport,
) -> list[FunFact]:
    """
    Generate facts about all-time H2H records.
    
    ONLY for managers who played each other THIS WEEK.
    """
    facts = []
    all_time = records.get("all_time", {})
    h2h_records = all_time.get("h2h", {})
    matchup_pairs = get_this_week_matchup_pairs(report)
    
    if not h2h_records:
        return facts
    
    for matchup in report.matchups:
        h2h_key = f"{min(matchup.manager_a, matchup.manager_b)}_vs_{max(matchup.manager_a, matchup.manager_b)}"
        h2h = h2h_records.get(h2h_key, {})
        
        if not h2h:
            continue
        
        a_wins = h2h.get(matchup.manager_a.lower(), 0)
        b_wins = h2h.get(matchup.manager_b.lower(), 0)
        total = a_wins + b_wins
        
        if total < 20:
            continue
        
        # Determine dominant/dominated
        if a_wins > b_wins:
            dominant, dominated = matchup.manager_a, matchup.manager_b
            dom_wins, sub_wins = a_wins, b_wins
        else:
            dominant, dominated = matchup.manager_b, matchup.manager_a
            dom_wins, sub_wins = b_wins, a_wins
        
        # Milestone meetings (40th, 50th, 60th, etc.)
        for milestone in [40, 50, 60, 70]:
            if total == milestone - 1:  # This game was the milestone
                facts.append(FunFact(
                    category="historical",
                    subcategory="h2h_milestone",
                    text=f"This week marked the {milestone}th all-time meeting between {matchup.manager_a} and {matchup.manager_b}.",
                    interestingness=65,
                    details={"matchup": h2h_key, "total": milestone},
                ))
                break
        
        # Lopsided rivalry context (if winner extended dominance)
        if matchup.winner and dom_wins >= 1.5 * sub_wins and total >= 30:
            win_pct = dom_wins / total * 100
            if matchup.winner == dominant:
                facts.append(FunFact(
                    category="historical",
                    subcategory="h2h_dominance",
                    text=f"{dominant} has now won {dom_wins} of {total} all-time meetings against {dominated} ({win_pct:.0f}%).",
                    interestingness=72,
                    details={"dominant": dominant, "record": f"{dom_wins}-{sub_wins}"},
                ))
            elif matchup.winner == dominated:
                # Upset!
                facts.append(FunFact(
                    category="historical",
                    subcategory="h2h_upset",
                    text=f"{dominated} got some revenge against {dominant}, who still leads their all-time series {dom_wins}-{sub_wins + 1}.",
                    interestingness=76,
                    details={"underdog": dominated, "favorite": dominant},
                ))
    
    return facts


def generate_all_time_record_facts(
    records: dict,
    report: WeeklyReport,
) -> list[FunFact]:
    """Generate facts about approaching or breaking all-time records."""
    facts = []
    all_time = records.get("all_time", {})
    
    # Check if this week's high score approached all-time high
    highest_all_time = all_time.get("highest_weekly_score", {})
    if highest_all_time:
        all_time_score = highest_all_time.get("score", 0)
        all_time_manager = highest_all_time.get("manager", "")
        all_time_season = highest_all_time.get("season", "")
        
        this_week_scores = [(m, s.total_fp) for m, s in report.manager_stats.items()]
        this_week_scores.sort(key=lambda x: -x[1])
        top_manager, top_score = this_week_scores[0]
        
        if top_score >= all_time_score:
            facts.append(FunFact(
                category="historical",
                subcategory="record_broken",
                text=f"NEW ALL-TIME RECORD! {top_manager}'s {top_score:.1f} points breaks the previous mark of {all_time_score:.1f}.",
                interestingness=98,
                details={"score": top_score, "previous": all_time_score},
            ))
        elif top_score >= all_time_score * 0.90:
            gap = all_time_score - top_score
            facts.append(FunFact(
                category="historical",
                subcategory="near_record",
                text=f"{top_manager}'s {top_score:.1f} points came within {gap:.1f} of the all-time weekly record ({all_time_score:.1f} by {all_time_manager}, {all_time_season}).",
                interestingness=74,
                details={"score": top_score, "record": all_time_score},
            ))
    
    # Check career win percentage leaders
    careers = all_time.get("manager_careers", {})
    if careers:
        win_pcts = [(m, stats.get("win_pct", 0), stats.get("total_wins", 0)) for m, stats in careers.items()]
        win_pcts.sort(key=lambda x: -x[1])
        
        if len(win_pcts) >= 2:
            leader, leader_pct, leader_wins = win_pcts[0]
            second, second_pct, _ = win_pcts[1]
            
            if leader_pct - second_pct >= 5 and leader_wins >= 50:
                facts.append(FunFact(
                    category="historical",
                    subcategory="career_dominance",
                    text=f"{leader}'s {leader_pct:.1f}% career win rate leads the league by {leader_pct - second_pct:.1f} percentage points over {second}.",
                    interestingness=68,
                    details={"leader": leader, "pct": leader_pct},
                ))
    
    return facts


def generate_trade_partner_facts(
    records: dict,
    report: WeeklyReport,
) -> list[FunFact]:
    """Generate facts about trade partnerships."""
    facts = []
    
    # Only show occasionally (every 3rd week)
    if report.week % 3 != 0:
        return facts
    
    all_time = records.get("all_time", {})
    trade_partners = all_time.get("trade_partners", {})
    
    if not trade_partners:
        return facts
    
    # Find most active trade partnership
    sorted_partners = sorted(trade_partners.items(), key=lambda x: -x[1])
    if sorted_partners and sorted_partners[0][1] >= 6:
        pair, count = sorted_partners[0]
        pair_names = pair.replace("_and_", " and ")
        facts.append(FunFact(
            category="historical",
            subcategory="trade_history",
            text=f"{pair_names} have completed {count} trades since 2017, making them the league's most active trade partners.",
            interestingness=62,
            details={"pair": pair, "trades": count},
        ))
    
    return facts


# =============================================================================
# SEASON-LEVEL FACTS (this season only)
# =============================================================================

def generate_streak_facts(
    records: dict,
    report: WeeklyReport,
) -> list[FunFact]:
    """Generate facts about notable win/loss streaks (4+ only)."""
    facts = []
    
    sr = records.get("season_records", {})
    current_streaks = sr.get("current_streaks", sr.get("current_win_streak", {}))
    
    # Handle old format
    if isinstance(current_streaks, dict) and any(isinstance(v, int) for v in current_streaks.values()):
        # Old format: {manager: int}
        win_streaks = sr.get("current_win_streak", {})
        loss_streaks = sr.get("current_loss_streak", {})
    else:
        # New format: {manager: {win: int, loss: int}}
        win_streaks = {m: current_streaks.get(m, {}).get("win", 0) for m in MANAGERS}
        loss_streaks = {m: current_streaks.get(m, {}).get("loss", 0) for m in MANAGERS}
    
    for manager in MANAGERS:
        win_streak = win_streaks.get(manager, 0)
        loss_streak = loss_streaks.get(manager, 0)
        
        # Only report notable streaks (4+)
        if win_streak >= 4:
            facts.append(FunFact(
                category="season",
                subcategory="win_streak",
                text=f"{manager} has won {win_streak} straight matchups.",
                interestingness=70 + win_streak * 3,
                details={"manager": manager, "streak": win_streak},
            ))
        
        if loss_streak >= 4:
            facts.append(FunFact(
                category="season",
                subcategory="loss_streak",
                text=f"{manager} has dropped {loss_streak} consecutive matchups.",
                interestingness=68 + loss_streak * 3,
                details={"manager": manager, "streak": loss_streak},
            ))
    
    return facts


def generate_points_race_facts(
    records: dict,
    report: WeeklyReport,
) -> list[FunFact]:
    """Generate facts about the season points race."""
    facts = []
    
    season_stats = records.get("season_fppg_stats", {})
    if not season_stats:
        return facts
    
    # Sort by total points
    totals = [(m, stats.get("total_fp", 0)) for m, stats in season_stats.items()]
    totals.sort(key=lambda x: -x[1])
    
    if len(totals) >= 2:
        leader, leader_pts = totals[0]
        second, second_pts = totals[1]
        gap = leader_pts - second_pts
        
        if gap >= 300:
            facts.append(FunFact(
                category="season",
                subcategory="points_leader",
                text=f"{leader} leads the season scoring race by {gap:.0f} fantasy points over {second}.",
                interestingness=66,
                details={"leader": leader, "gap": gap},
            ))
        elif gap <= 100 and gap > 0:
            facts.append(FunFact(
                category="season",
                subcategory="points_race_tight",
                text=f"The scoring race is tight: {leader} leads {second} by just {gap:.0f} fantasy points.",
                interestingness=70,
                details={"leader": leader, "second": second, "gap": gap},
            ))
    
    # Check for FPPG leaders
    fppg_data = [(m, stats.get("fppg", stats.get("season_fppg", 0))) for m, stats in season_stats.items()]
    fppg_data.sort(key=lambda x: -x[1])
    
    if fppg_data and fppg_data[0][1] >= 38:
        leader, fppg = fppg_data[0]
        facts.append(FunFact(
            category="season",
            subcategory="efficiency_leader",
            text=f"{leader} leads the league in season FPPG at {fppg:.1f} per game.",
            interestingness=64,
            details={"leader": leader, "fppg": fppg},
        ))
    
    return facts


def generate_season_record_facts(
    records: dict,
    report: WeeklyReport,
) -> list[FunFact]:
    """Generate facts about season records being approached."""
    facts = []
    
    sr = records.get("season_records", {})
    
    # Check this week's scores against season high/low
    highest = sr.get("highest_weekly_team_score", {})
    lowest = sr.get("lowest_weekly_team_score", {})
    
    for manager, stats in report.manager_stats.items():
        score = stats.total_fp
        
        # Approaching season high
        if highest and score >= highest.get("score", 0) * 0.95:
            if score > highest.get("score", 0):
                facts.append(FunFact(
                    category="season",
                    subcategory="season_high",
                    text=f"{manager}'s {score:.1f} points sets a new season high!",
                    interestingness=80,
                    details={"manager": manager, "score": score},
                ))
    
    return facts


def generate_season_h2h_facts(
    records: dict,
    report: WeeklyReport,
) -> list[FunFact]:
    """
    Generate facts about season H2H records.
    
    ONLY for managers who played each other THIS WEEK.
    """
    facts = []
    h2h_season = records.get("h2h_season", {})
    matchup_pairs = get_this_week_matchup_pairs(report)
    
    for matchup in report.matchups:
        key = f"{min(matchup.manager_a, matchup.manager_b)}_vs_{max(matchup.manager_a, matchup.manager_b)}"
        record = h2h_season.get(key, {})
        
        if not record:
            continue
        
        a_wins = record.get(matchup.manager_a.lower(), 0)
        b_wins = record.get(matchup.manager_b.lower(), 0)
        total = a_wins + b_wins
        
        # Season sweep (4-0 or 5-0)
        if total >= 4:
            if a_wins >= 4 and b_wins == 0:
                facts.append(FunFact(
                    category="season",
                    subcategory="season_sweep",
                    text=f"{matchup.manager_a} is {a_wins}-0 against {matchup.manager_b} this season.",
                    interestingness=72,
                    details={"sweeper": matchup.manager_a, "swept": matchup.manager_b},
                ))
            elif b_wins >= 4 and a_wins == 0:
                facts.append(FunFact(
                    category="season",
                    subcategory="season_sweep",
                    text=f"{matchup.manager_b} is {b_wins}-0 against {matchup.manager_a} this season.",
                    interestingness=72,
                    details={"sweeper": matchup.manager_b, "swept": matchup.manager_a},
                ))
    
    return facts


# =============================================================================
# WEEKLY FACTS (this week only)
# =============================================================================

def generate_player_performance_facts(report: WeeklyReport) -> list[FunFact]:
    """Generate facts about individual player performances this week."""
    facts = []
    
    # Find exceptional single games (70+ FP)
    big_games = []
    for manager, stats in report.manager_stats.items():
        for player_name, ps in stats.player_stats.items():
            if hasattr(ps, 'game_logs') and ps.game_logs:
                for game in ps.game_logs:
                    fp = game.get('fantasy_points', 0)
                    if fp >= 70:
                        big_games.append((player_name, fp, manager, game.get('date', '')))
    
    big_games.sort(key=lambda x: -x[1])
    for player, fp, manager, date in big_games[:2]:  # Top 2 big games
        if fp >= 80:
            facts.append(FunFact(
                category="weekly",
                subcategory="monster_game",
                text=f"{player} exploded for {fp:.1f} fantasy points in a single game for {manager}.",
                interestingness=82,
                details={"player": player, "fp": fp, "manager": manager},
            ))
        else:
            facts.append(FunFact(
                category="weekly",
                subcategory="big_game",
                text=f"{player} went off for {fp:.1f} fantasy points in one game.",
                interestingness=72,
                details={"player": player, "fp": fp},
            ))
    
    # Best weekly FPPG (55+ on 3+ games)
    best_fppg = None
    for manager, stats in report.manager_stats.items():
        for player_name, ps in stats.player_stats.items():
            if ps.games_started >= 3 and ps.fppg >= 55:
                if best_fppg is None or ps.fppg > best_fppg[1]:
                    best_fppg = (player_name, ps.fppg, ps.games_started, manager)
    
    if best_fppg:
        facts.append(FunFact(
            category="weekly",
            subcategory="weekly_fppg",
            text=f"{best_fppg[0]} averaged {best_fppg[1]:.1f} FPPG across {best_fppg[2]} games for {best_fppg[3]}.",
            interestingness=74,
            details={"player": best_fppg[0], "fppg": best_fppg[1]},
        ))
    
    # Player carried their team (>18% of total)
    for manager, stats in report.manager_stats.items():
        if stats.total_fp > 0:
            for player_name, ps in stats.player_stats.items():
                if ps.games_started >= 3:
                    pct = (ps.total_fp / stats.total_fp) * 100
                    if pct >= 18:
                        facts.append(FunFact(
                            category="weekly",
                            subcategory="carry_job",
                            text=f"{player_name} accounted for {pct:.0f}% of {manager}'s scoring this week.",
                            interestingness=68,
                            details={"player": player_name, "pct": pct, "manager": manager},
                        ))
    
    return facts


def generate_injury_facts(report: WeeklyReport) -> list[FunFact]:
    """Generate facts about injuries this week."""
    facts = []
    
    injuries = [(m, s.games_lost_to_injury) for m, s in report.manager_stats.items()]
    injuries.sort(key=lambda x: -x[1])
    
    most_injured = injuries[0]
    least_injured = injuries[-1]
    
    # Significant injury disparity
    if most_injured[1] >= 6 and least_injured[1] <= 2:
        facts.append(FunFact(
            category="weekly",
            subcategory="injury_disparity",
            text=f"{most_injured[0]} lost {most_injured[1]} games to injury this week while {least_injured[0]} lost just {least_injured[1]}.",
            interestingness=66,
            details={"unlucky": most_injured[0], "lucky": least_injured[0]},
        ))
    elif most_injured[1] >= 8:
        facts.append(FunFact(
            category="weekly",
            subcategory="injury_woes",
            text=f"{most_injured[0]} was hit hard by injuries, losing {most_injured[1]} games this week.",
            interestingness=64,
            details={"manager": most_injured[0], "injuries": most_injured[1]},
        ))
    
    return facts


def generate_season_injury_burden_facts(data: FantasyData) -> list[FunFact]:
    """
    Generate facts about season-long injury burden.
    
    SLOT TREATMENT:
    - IL+ is treated identically to BN (just another bench slot).
    - IL means the player is injured. ANY IL row with an nba_opponent
      counts as an IL Injury Game, regardless of fantasy_points.
    
    Uses data from LINEUPS to calculate:
    - Total injury burden % (non-IL injuries + ALL IL scheduled games)
    - Non-IL injury burden % (unexpected injuries in starter/BN/IL+ slots)
    - IL usage (all scheduled games in IL slot)
    """
    facts = []
    
    lineups = data.lineups.copy()
    
    # Derive has_game
    lineups['has_game'] = (
        lineups['nba_opponent'].notna() & 
        (lineups['nba_opponent'].astype(str).str.strip() != '')
    )
    
    injury_stats = {}
    
    for manager in MANAGERS:
        mgr_df = lineups[lineups['manager'] == manager]
        
        # All games with opponent (any slot)
        all_games = mgr_df[mgr_df['has_game'] == True]
        total_all_games = len(all_games)
        
        # --- IL slot: ANY scheduled game = injury game ---
        il_games = all_games[all_games['slot'] == 'IL']
        il_injury_games = len(il_games)  # ALL IL scheduled games count
        
        # --- Non-IL slots (starters, Util, BN, IL+): injury = fp == 0.0 ---
        non_il_games = all_games[all_games['slot'] != 'IL']
        total_non_il = len(non_il_games)
        non_il_injuries = len(non_il_games[non_il_games['fantasy_points'] == 0.0])
        
        # --- Totals ---
        total_all_injuries = non_il_injuries + il_injury_games
        
        non_il_pct = (non_il_injuries / total_non_il * 100) if total_non_il > 0 else 0.0
        total_pct = (total_all_injuries / total_all_games * 100) if total_all_games > 0 else 0.0
        
        # Get top IL player (ALL IL scheduled games, not just fp == 0.0)
        il_all_rows = mgr_df[(mgr_df['has_game'] == True) & (mgr_df['slot'] == 'IL')]
        top_il_player = None
        top_il_games = 0
        if not il_all_rows.empty:
            il_by_player = il_all_rows.groupby('player_name').size()
            top_il_player = il_by_player.idxmax()
            top_il_games = il_by_player.max()
        
        injury_stats[manager] = {
            'total_pct': total_pct,
            'non_il_pct': non_il_pct,
            'total_injuries': total_all_injuries,
            'il_injuries': il_injury_games,
            'top_il_player': top_il_player,
            'top_il_games': top_il_games,
        }
    
    # Sort by total injury burden
    sorted_by_total = sorted(injury_stats.items(), key=lambda x: -x[1]['total_pct'])
    sorted_by_non_il = sorted(injury_stats.items(), key=lambda x: -x[1]['non_il_pct'])
    
    most_injured_mgr, most_injured_stats = sorted_by_total[0]
    healthiest_mgr, healthiest_stats = sorted_by_total[-1]
    
    # Fact 1: Most injured team (total burden)
    if most_injured_stats['total_pct'] >= 20:
        facts.append(FunFact(
            category="season",
            subcategory="injury_burden_leader",
            text=f"{most_injured_mgr} has lost {most_injured_stats['total_pct']:.1f}% of scheduled games to injury this season -> the highest burden in the league.",
            interestingness=72,
            details={
                "manager": most_injured_mgr, 
                "pct": most_injured_stats['total_pct'],
                "games": most_injured_stats['total_injuries']
            },
        ))
    
    # Fact 2: Healthiest team
    if healthiest_stats['total_pct'] <= 18 and (most_injured_stats['total_pct'] - healthiest_stats['total_pct']) >= 5:
        facts.append(FunFact(
            category="season",
            subcategory="injury_burden_healthiest",
            text=f"{healthiest_mgr} has been the healthiest team at just {healthiest_stats['total_pct']:.1f}% injury burden -> {most_injured_stats['total_pct'] - healthiest_stats['total_pct']:.1f} percentage points better than {most_injured_mgr}.",
            interestingness=70,
            details={
                "manager": healthiest_mgr,
                "pct": healthiest_stats['total_pct'],
                "gap": most_injured_stats['total_pct'] - healthiest_stats['total_pct']
            },
        ))
    
    # Fact 3: Heavy IL usage (keeper injuries, long-term absences)
    for manager, stats in sorted_by_total:
        if stats['il_injuries'] >= 40 and stats['top_il_player']:
            facts.append(FunFact(
                category="season",
                subcategory="injury_burden_il_heavy",
                text=f"{manager} has logged {stats['il_injuries']} injury games in IL slots this season, with {stats['top_il_player']} alone accounting for {stats['top_il_games']}.",
                interestingness=68,
                details={
                    "manager": manager,
                    "il_games": stats['il_injuries'],
                    "top_player": stats['top_il_player'],
                    "top_games": stats['top_il_games']
                },
            ))
    
    # Fact 4: Big gap between most and least injured (use game counts, not percentages)
    games_gap = most_injured_stats['total_injuries'] - healthiest_stats['total_injuries']
    if games_gap >= 40:
        facts.append(FunFact(
            category="season",
            subcategory="injury_burden_gap",
            text=f"{most_injured_mgr} has lost {most_injured_stats['total_injuries']} games to injury this season -> {games_gap} more than {healthiest_mgr}'s league-low {healthiest_stats['total_injuries']}.",
            interestingness=74,
            details={
                "most_injured": most_injured_mgr,
                "most_injured_games": most_injured_stats['total_injuries'],
                "healthiest": healthiest_mgr,
                "healthiest_games": healthiest_stats['total_injuries'],
                "gap": games_gap
            },
        ))
    
    return facts


def generate_positional_dominance_facts(report: WeeklyReport) -> list[FunFact]:
    """Generate facts about positional dominance in matchups."""
    facts = []
    
    for matchup in report.matchups:
        stats_a = matchup.stats_a
        stats_b = matchup.stats_b
        
        if not stats_a or not stats_b:
            continue
        
        # Check each position for significant gaps (100+ FP difference)
        positions = [
            ("guard", stats_a.guard_stats.total_fp, stats_b.guard_stats.total_fp, "guards"),
            ("forward", stats_a.forward_stats.total_fp, stats_b.forward_stats.total_fp, "forwards"),
            ("center", stats_a.center_stats.total_fp, stats_b.center_stats.total_fp, "centers"),
        ]
        
        for pos_name, fp_a, fp_b, pos_plural in positions:
            gap = abs(fp_a - fp_b)
            if gap >= 100:
                if fp_a > fp_b:
                    winner, loser = matchup.manager_a, matchup.manager_b
                else:
                    winner, loser = matchup.manager_b, matchup.manager_a
                
                facts.append(FunFact(
                    category="weekly",
                    subcategory="positional_dominance",
                    text=f"{winner}'s {pos_plural} outscored {loser}'s by {gap:.0f} FP this week.",
                    interestingness=68 + min(gap - 100, 50) * 0.2,  # Higher gap = more interesting
                    details={"winner": winner, "loser": loser, "position": pos_name, "gap": gap},
                ))
    
    return facts


def generate_schedule_advantage_facts(report: WeeklyReport) -> list[FunFact]:
    """Generate facts about schedule advantages (games played -> )."""
    facts = []
    
    for matchup in report.matchups:
        stats_a = matchup.stats_a
        stats_b = matchup.stats_b
        
        if not stats_a or not stats_b:
            continue
        
        games_a = stats_a.total_healthy_starter_games
        games_b = stats_b.total_healthy_starter_games
        gap = abs(games_a - games_b)
        
        # Only interesting if 5+ game difference
        if gap >= 5:
            if games_a > games_b:
                more_games, fewer_games = matchup.manager_a, matchup.manager_b
                more_count, fewer_count = games_a, games_b
            else:
                more_games, fewer_games = matchup.manager_b, matchup.manager_a
                more_count, fewer_count = games_b, games_a
            
            facts.append(FunFact(
                category="weekly",
                subcategory="schedule_advantage",
                text=f"{more_games} played {more_count} games this week vs {fewer_games}'s {fewer_count} -> a {gap}-game schedule advantage.",
                interestingness=64 + min(gap - 5, 5) * 2,
                details={"advantaged": more_games, "disadvantaged": fewer_games, "gap": gap},
            ))
    
    return facts


def generate_boom_bust_facts(report: WeeklyReport) -> list[FunFact]:
    """Generate facts about managers with both the highest and lowest single-game performances."""
    facts = []
    
    # Collect all games across all managers
    all_games = []
    for manager, stats in report.manager_stats.items():
        for player_name, ps in stats.player_stats.items():
            for game in ps.game_logs:
                if game.get("started") and not game.get("is_injured"):
                    all_games.append({
                        "manager": manager,
                        "player": player_name,
                        "fp": game["fantasy_points"],
                    })
    
    if len(all_games) < 4:
        return facts
    
    # Sort to find best and worst
    all_games.sort(key=lambda x: x["fp"], reverse=True)
    best_game = all_games[0]
    worst_game = all_games[-1]
    
    # Check if same manager had both best and worst
    if best_game["manager"] == worst_game["manager"]:
        manager = best_game["manager"]
        facts.append(FunFact(
            category="weekly",
            subcategory="boom_bust",
            text=f"{manager} had the week's highest single-game score ({best_game['fp']:.2f} FP from {best_game['player']}) AND the lowest ({worst_game['fp']:.2f} FP from {worst_game['player']}).",
            interestingness=75,
            details={"manager": manager, "best": best_game, "worst": worst_game},
        ))
    
    return facts


def generate_margin_facts(report: WeeklyReport, records: dict) -> list[FunFact]:
    """Generate facts about matchup margins -> largest/smallest of week, season records."""
    facts = []
    
    if not report.matchups:
        return facts
    
    # Find this week's closest and most lopsided matchups
    matchups_by_margin = sorted(report.matchups, key=lambda m: m.margin)
    closest = matchups_by_margin[0]
    widest = matchups_by_margin[-1]
    
    # Get season records for context
    all_time = records.get("all_time", {})
    closest_ever = all_time.get("closest_game", {})
    biggest_blowout = all_time.get("biggest_blowout", {})
    
    # Closest game of the week (only if notably close - under 30 points)
    if closest.margin <= 30:
        facts.append(FunFact(
            category="weekly",
            subcategory="close_game",
            text=f"The {closest.manager_a} vs {closest.manager_b} matchup was decided by just {closest.margin:.1f} points -> the week's closest contest.",
            interestingness=67 + (30 - closest.margin) * 0.5,  # Closer = more interesting
            details={"matchup": f"{closest.manager_a}_vs_{closest.manager_b}", "margin": closest.margin},
        ))
    
    # Biggest blowout of the week (only if notably large - 100+ points)
    if widest.margin >= 100:
        loser = widest.manager_b if widest.winner == widest.manager_a else widest.manager_a
        facts.append(FunFact(
            category="weekly",
            subcategory="blowout",
            text=f"{widest.winner}'s {widest.margin:.0f}-point victory over {loser} was the week's most lopsided result.",
            interestingness=66 + min(widest.margin - 100, 100) * 0.1,
            details={"winner": widest.winner, "loser": loser, "margin": widest.margin},
        ))
    
    # Check if this week had a historically close game
    if closest_ever:
        record_margin = closest_ever.get("margin", 0)
        if closest.margin <= record_margin * 1.1:  # Within 10% of record
            facts.append(FunFact(
                category="weekly",
                subcategory="near_record_close",
                text=f"The {closest.margin:.1f}-point margin between {closest.manager_a} and {closest.manager_b} nearly matched the all-time closest game ({record_margin:.1f} points).",
                interestingness=80,
                details={"this_week": closest.margin, "record": record_margin},
            ))
    
    # Check if this week had a historically large blowout
    if biggest_blowout:
        record_margin = biggest_blowout.get("margin", 0)
        if widest.margin >= record_margin * 0.9:  # Within 10% of record
            facts.append(FunFact(
                category="weekly",
                subcategory="near_record_blowout",
                text=f"{widest.winner}'s {widest.margin:.0f}-point win approached the all-time blowout record ({record_margin:.0f} points).",
                interestingness=78,
                details={"this_week": widest.margin, "record": record_margin},
            ))
    
    return facts


def generate_consistency_facts(report: WeeklyReport) -> list[FunFact]:
    """Generate facts about player consistency (all games above a threshold)."""
    facts = []
    
    # Find players who scored 40+ FP in every game (min 3 games)
    for manager, stats in report.manager_stats.items():
        for player_name, ps in stats.player_stats.items():
            started_games = [g for g in ps.game_logs if g.get("started") and not g.get("is_injured")]
            
            if len(started_games) >= 3:
                min_score = min(g["fantasy_points"] for g in started_games)
                
                # All games 45+ FP is elite consistency
                if min_score >= 45:
                    facts.append(FunFact(
                        category="weekly",
                        subcategory="elite_consistency",
                        text=f"{player_name} scored 45+ FP in all {len(started_games)} games this week -> elite consistency for {manager}.",
                        interestingness=74,
                        details={"player": player_name, "manager": manager, "games": len(started_games), "min": min_score},
                    ))
                # All games 40+ FP is still notable
                elif min_score >= 40:
                    facts.append(FunFact(
                        category="weekly",
                        subcategory="consistency",
                        text=f"{player_name} didn't dip below 40 FP in any of his {len(started_games)} games this week for {manager}.",
                        interestingness=68,
                        details={"player": player_name, "manager": manager, "games": len(started_games), "min": min_score},
                    ))
    
    return facts


def generate_efficiency_facts(report: WeeklyReport) -> list[FunFact]:
    """Generate facts about team efficiency this week."""
    facts = []
    
    efficiencies = [(m, s.efficiency_pct) for m, s in report.manager_stats.items()]
    efficiencies.sort(key=lambda x: -x[1])
    
    most_eff, most_pct = efficiencies[0]
    least_eff, least_pct = efficiencies[-1]
    
    if most_pct >= 96:
        facts.append(FunFact(
            category="weekly",
            subcategory="high_efficiency",
            text=f"{most_eff} operated at {most_pct:.1f}% roster efficiency this week.",
            interestingness=65,
            details={"manager": most_eff, "efficiency": most_pct},
        ))
    
    if least_pct <= 70:
        facts.append(FunFact(
            category="weekly",
            subcategory="low_efficiency",
            text=f"{least_eff} left significant points on the table with just {least_pct:.1f}% roster efficiency.",
            interestingness=63,
            details={"manager": least_eff, "efficiency": least_pct},
        ))
    
    return facts


def generate_luck_index_facts(luck_index: dict) -> list[FunFact]:
    """
    Generate fun facts from the Luck Index (all-play expected wins).

    Uses the gap between actual and expected records to surface
    interesting narratives about schedule fortune and misfortune.

    Args:
        luck_index: Dict from build_luck_index(), with keys
            'managers' (dict of manager -> stats), 'luckiest', 'unluckiest'.
    """
    facts = []
    if not luck_index:
        return facts

    managers_data = luck_index.get("managers", {})
    if not managers_data:
        return facts

    luckiest_name = luck_index.get("luckiest", "")
    unluckiest_name = luck_index.get("unluckiest", "")

    luckiest = managers_data.get(luckiest_name, {})
    unluckiest = managers_data.get(unluckiest_name, {})

    # 1. Very Lucky manager (luck >= +2.0)
    if luckiest and luckiest.get("luck_index", 0) >= 2.0:
        li = luckiest["luck_index"]
        actual = luckiest.get("actual_record", "?")
        expected = luckiest.get("expected_record", "?")
        facts.append(FunFact(
            category="season",
            subcategory="luck_very_lucky",
            text=(
                f"{luckiest_name}'s {actual} record significantly outpaces "
                f"the all-play expected {expected}--a luck index "
                f"of {li:+.1f} suggests favorable scheduling has been kind "
                f"this season."
            ),
            interestingness=72,
            details={
                "manager": luckiest_name,
                "luck_index": li,
                "actual": actual,
                "expected": expected,
            },
        ))

    # 2. Very Unlucky manager (luck <= -2.0)
    if unluckiest and unluckiest.get("luck_index", 0) <= -2.0:
        li = unluckiest["luck_index"]
        actual = unluckiest.get("actual_record", "?")
        expected = unluckiest.get("expected_record", "?")
        facts.append(FunFact(
            category="season",
            subcategory="luck_very_unlucky",
            text=(
                f"{unluckiest_name}'s scoring profile suggests a "
                f"{expected} record, but instead sits at {actual}--a "
                f"luck index of {li:+.1f}, the league's worst. "
                f"Bad timing and tough matchup draws have defined the season."
            ),
            interestingness=74,
            details={
                "manager": unluckiest_name,
                "luck_index": li,
                "actual": actual,
                "expected": expected,
            },
        ))

    # 3. Luck gap between luckiest and unluckiest
    if luckiest and unluckiest:
        gap = (luckiest.get("luck_index", 0)
               - unluckiest.get("luck_index", 0))
        if gap >= 4.0:
            facts.append(FunFact(
                category="season",
                subcategory="luck_gap",
                text=(
                    f"The luck gap between {luckiest_name} "
                    f"({luckiest.get('luck_index', 0):+.1f}) and "
                    f"{unluckiest_name} "
                    f"({unluckiest.get('luck_index', 0):+.1f}) is "
                    f"{gap:.1f} wins--nearly {gap:.0f} games of "
                    f"difference that scoring alone can't explain."
                ),
                interestingness=70,
                details={
                    "lucky": luckiest_name,
                    "unlucky": unluckiest_name,
                    "gap": gap,
                },
            ))

    # 4. Any manager with scoring margin that contradicts record
    for mgr_name, md in managers_data.items():
        margin = md.get("scoring_margin_per_game", 0)
        wins = md.get("actual_wins", 0)
        losses = md.get("actual_losses", 0)
        if margin > 50 and losses > wins:
            facts.append(FunFact(
                category="season",
                subcategory="luck_margin_contradiction",
                text=(
                    f"{mgr_name} outscores opponents by "
                    f"{margin:.1f} points per game on average yet has a "
                    f"losing record ({wins}-{losses})--one of the "
                    f"more unlikely statistical anomalies in league history."
                ),
                interestingness=78,
                details={
                    "manager": mgr_name,
                    "margin": margin,
                    "record": f"{wins}-{losses}",
                },
            ))

    return facts

def generate_fun_facts(
    report: WeeklyReport,
    data: FantasyData,
    record_updates: list[RecordUpdate] = None,
    title_odds: dict[str, float] = None,
    waiver_adds: dict[str, list[str]] = None,
    luck_index: dict = None,
    num_facts: int = 7,
    seed: int = None,
    freshness_tracker: "FreshnessTracker" = None,
) -> list[FunFact]:
    """
    Generate 6-7 fun facts for the newsletter.
    
    Ensures a mix of:
    - Historical facts (since 2017): career milestones, all-time H2H, records
    - Season facts: streaks, points race, season H2H, luck index
    - Weekly facts: player performances, injuries, waivers
    
    Args:
        report: WeeklyReport with this week's stats
        data: FantasyData container
        record_updates: List of record updates from this week
        title_odds: Dict of manager -> title odds percentage
        waiver_adds: Dict of manager -> list of waiver pickup names
        luck_index: Dict from build_luck_index() (all-play expected wins data)
        num_facts: Number of facts to return (default 7)
        seed: Random seed for reproducibility
        freshness_tracker: Optional FreshnessTracker to filter stale content
    """
    if seed is not None:
        random.seed(seed)
    
    record_updates = record_updates or []
    waiver_adds = waiver_adds or {}
    records = data.records
    
    # Generate all candidate facts by category
    historical_facts = []
    historical_facts.extend(generate_career_milestone_facts(records, report))
    historical_facts.extend(generate_historical_h2h_facts(records, report))
    historical_facts.extend(generate_all_time_record_facts(records, report))
    historical_facts.extend(generate_trade_partner_facts(records, report))
    
    season_facts = []
    season_facts.extend(generate_streak_facts(records, report))
    season_facts.extend(generate_points_race_facts(records, report))
    season_facts.extend(generate_season_record_facts(records, report))
    season_facts.extend(generate_season_h2h_facts(records, report))
    season_facts.extend(generate_season_injury_burden_facts(data))
    if luck_index:
        season_facts.extend(generate_luck_index_facts(luck_index))
    
    weekly_facts = []
    weekly_facts.extend(generate_player_performance_facts(report))
    weekly_facts.extend(generate_injury_facts(report))
    weekly_facts.extend(generate_efficiency_facts(report))
    weekly_facts.extend(generate_positional_dominance_facts(report))
    weekly_facts.extend(generate_schedule_advantage_facts(report))
    weekly_facts.extend(generate_boom_bust_facts(report))
    weekly_facts.extend(generate_margin_facts(report, records))
    weekly_facts.extend(generate_consistency_facts(report))
    
    # Apply freshness filtering if tracker provided
    # Use min_count to ensure we have enough facts even if many are stale
    if freshness_tracker is not None:
        from .content_freshness import filter_fresh_facts
        
        # Filter each category with min_count fallback
        # We want at least 3 historical, 2 season, 3 weekly to ensure diversity
        historical_facts = filter_fresh_facts(historical_facts, freshness_tracker, report.week, min_count=3)
        season_facts = filter_fresh_facts(season_facts, freshness_tracker, report.week, min_count=2)
        # Weekly facts are inherently fresh - but still filter for edge cases
        weekly_facts = filter_fresh_facts(weekly_facts, freshness_tracker, report.week, min_count=3)
    
    # Sort each category by interestingness
    historical_facts.sort(reverse=True)
    season_facts.sort(reverse=True)
    weekly_facts.sort(reverse=True)
    
    # Select facts ensuring diversity across levels
    selected = []
    
    # Take top 2-3 from each category
    for fact in historical_facts[:3]:
        selected.append(fact)
    
    for fact in season_facts[:2]:
        if fact not in selected:
            selected.append(fact)
    
    for fact in weekly_facts[:3]:
        if fact not in selected:
            selected.append(fact)
    
    # If we need more, pull from remaining
    all_remaining = historical_facts[3:] + season_facts[2:] + weekly_facts[3:]
    all_remaining.sort(reverse=True)
    
    for fact in all_remaining:
        if len(selected) >= num_facts:
            break
        if fact not in selected:
            selected.append(fact)
    
    # Final sort by interestingness
    selected.sort(reverse=True)
    
    final_facts = selected[:num_facts]
    
    # Record shown facts if tracker provided
    if freshness_tracker is not None:
        from .content_freshness import record_shown_facts
        record_shown_facts(final_facts, freshness_tracker, report.week)
    
    return final_facts


def format_fun_facts(facts: list[FunFact]) -> list[dict]:
    """Format fun facts for JSON output."""
    return [
        {
            "category": fact.category,
            "subcategory": fact.subcategory,
            "text": fact.text,
            "interestingness": fact.interestingness,
        }
        for fact in facts
    ]
