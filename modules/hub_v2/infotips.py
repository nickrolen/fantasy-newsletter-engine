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
}


def tip(key: str) -> tuple:
    if key not in TIPS:
        raise KeyError(f"no InfoTip {key!r}: add it to modules/hub_v2/infotips.TIPS")
    return TIPS[key]
