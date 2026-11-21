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
            "How good he is per game when he plays: his fantasy production judged on his whole NBA record "
            "(rostered or not), this season, and his age, on a fixed 40-99 scale that means the same every year. "
            "It isn't about games left or how often he plays: that's DUR."),
    "prov": ("Prov.",
             "Small sample: this rating will settle as he plays more."),
    "pot": ("POT",
            "His keeper value: next season's projected fantasy points per game, from his whole NBA record "
            "(rostered or not) and this season, moved a year along the NBA's age curve, on the fixed 40-99 "
            "scale. Keep chance is shown beside it, not inside it."),
    "dur": ("DUR",
            "Durability: how often he plays when his team does, over his last three NBA seasons and this one, "
            "on its own 40-99 scale. A current injury is not in it: the injury tag says that."),
    "fppg": ("FPPG",
             "Fantasy points per game in his NBA games this season, on a league roster or not. Where his "
             "league-roster figure differs, it is the line under the tiles."),
    "grades": ("Grades",
               "Each grade ranks him among the players on league rosters, this season only: A+ is the top 5%, "
               "D the bottom 5%. Tap a grade for what it measures."),
    # 4a4 s.4: the nine tiles (this season only; the archetype and OVR carry the history)
    "grade_scoring": ("Scoring", "Fantasy points per game from his points, this season."),
    "grade_shooting": ("Shooting", "Fantasy points per game from his made threes, this season."),
    "grade_playmaking": ("Playmaking", "Fantasy points per game from his assists, this season."),
    "grade_rebounding": ("Rebounding", "Fantasy points per game from his rebounds, this season."),
    "grade_steals": ("Steals", "Fantasy points per game from his steals, this season."),
    "grade_blocks": ("Blocks", "Fantasy points per game from his blocks, this season."),
    "grade_efficiency": ("Efficiency",
                         "Fantasy points per game from his makes, misses and turnovers, this season: high means "
                         "he shoots well and rarely turns it over."),
    "archetype": ("Archetype",
                  "What kind of player he is over his last three seasons and this one. The grades below are "
                  "this season only."),
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
    # 4c3: the Market tab's Advice view
    "advice": ("Advice",
               "The engine's plan for each team, up to its adds left. Each move is priced after the one before it, "
               "as the change in your chance to win each week; an IL activation is priced against leaving him in "
               "IL, which blocks every move. Advice, not a rule."),
    "age_curve": ("The age curve",
                  "How a player's fantasy scoring changes from one season to the next at each age, fitted on "
                  "every NBA player's seasons since 2014-15. POT uses it."),
}


def tip(key: str) -> tuple:
    if key not in TIPS:
        raise KeyError(f"no InfoTip {key!r}: add it to modules/hub_v2/infotips.TIPS")
    return TIPS[key]
