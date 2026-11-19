"""
hub_v2/infotips.py -- every InfoTip (the small i beside a non-obvious number),
written once and reused wherever the concept appears. For Nick to approve in
review (4b); change the words here and nowhere else.

Each: (title, one or two plain sentences). They say what the number means and
how to read it, not how it is computed.
"""

TIPS = {
    "title_odds": ("Title odds",
                   "The chance this team finishes first in the regular season (weeks 1\u201315), from the "
                   "engine's simulation of every game left. The change is since the run before."),
    "win": ("Win %",
            "The chance this team wins this week's matchup, from the engine's simulation of the games left. "
            "It moves with each day's results, injury tags and lineup changes."),
    "keep": ("Keep %",
             "The chance he is one of this team's keepers next season (the team's keeper line, 5 or 6), "
             "from the keeper model the newsletter's Keeper Watch uses."),
    "proj": ("Proj",
             "Yahoo's projected fantasy points per game for him for the rest of the season."),
    "lines": ("The lines",
              "Spread: the favourite's projected margin. Total: both teams' projected points added together. "
              "Moneyline: American odds; \u2212200 means risking 200 to win 100, +200 winning 200 on 100."),
    # 4c1: the ratings. OVR's words are 4a decision 1's; FG% & TOs' are 4a2
    # decision 5's; the rest are for Nick's approval.
    "ovr": ("OVR",
            "Rest-of-season fantasy value above a replacement player: his scoring level, how often he plays, "
            "and his team's games left. It doesn't know injury return dates yet."),
    "pot": ("POT",
            "His value as a keeper: his scoring level projected over the next two seasons with this league's "
            "age curve. Keep chance is shown beside it, not inside it."),
    "fppg": ("FPPG",
             "Fantasy points per game in his NBA games this season, on a league roster or not. Where his "
             "league-roster figure differs, it is the line under the tiles."),
    "grades": ("Grades",
               "Each grade ranks him among the players on league rosters: A+ is the top 5%, D the bottom 5%. "
               "Tap a grade for what it measures."),
    "grade_scoring": ("Scoring", "Fantasy points per game from his points and threes."),
    "grade_playmaking": ("Playmaking", "Fantasy points per game from his assists."),
    "grade_rebounding": ("Rebounding", "Fantasy points per game from his rebounds."),
    "grade_stocks": ("Stocks", "Fantasy points per game from his steals and blocks."),
    "grade_efficiency": ("FG% & TOs", "Fantasy points from his makes, misses and turnovers."),
    "grade_durability": ("Durability",
                         "How often he plays when his team does, this season and his last three in the league. "
                         "It shows after 16 team games."),
    "grade_consistency": ("Consistency",
                          "How steady his games are: the smaller the swings around his average, the higher. "
                          "It shows after 16 games."),
    "grade_schedule": ("Schedule",
                       "His NBA team's games over the next 3 fantasy weeks, the games grid's weeks. The count "
                       "is beside the letter."),
    # 4a3: the minutes (the card's Season line; the roster's MIN columns carry their own notes)
    "min": ("MIN",
            "Minutes per game in his NBA games this season. MIN \u0394: his minutes per game over the last "
            "14 days against his season, a sign of a bigger or smaller role. It shows from 4 games in the "
            "last 14 days."),
    "fa_pct": ("Free agents",
               "Free agents get no OVR or POT: the ratings were tested on rostered players only. Instead, his "
               "FPPG and its percentile among the rostered players."),
    # 4c3: the Market tab's Advice view
    "advice": ("Advice",
               "The engine's plan for each team, up to its adds left. Each move is priced after the one before it, "
               "as the change in your chance to win each week; an IL activation is priced against leaving him in "
               "IL, which blocks every move. Advice, not a rule."),
    "age_curve": ("The age curve",
                  "How a player's scoring changes from one season to the next at each age, fitted on this "
                  "league's own history. POT uses it."),
}


def tip(key: str) -> tuple:
    if key not in TIPS:
        raise KeyError(f"no InfoTip {key!r}: add it to modules/hub_v2/infotips.TIPS")
    return TIPS[key]
