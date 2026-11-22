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


# =============================================================================
# 5d1 s.5 (Nick, 11-20: "Some of these columns are not intuitive."): every
# table column's definition. A tap on a column's header opens a small popover
# with its name, the definition below and, where the table sorts, a Sort
# button. {table: {column key: (name, one or two plain sentences)}}. For
# Nick's review (claude/5D1_RESULT); change the words here and nowhere else.
# A header with no entry here fails tests/test_5d1_page.py: a new column
# can't ship without one (5d2's Players groups and Market's sorts included).
# =============================================================================

COLUMNS = {
    "roster": {
        "name": ("Player", "The player, his NBA team and positions, and any injury tag. Tap his name for his card."),
        "fppg": ("FPPG", "Fantasy points per game in his NBA games this season, on a league roster or not."),
        "gp": ("GP", "NBA games he has played this season."),
        "proj": ("Proj", "Yahoo's projected fantasy points per game for him for the rest of the season."),
        "next": ("Next", "Games he will play next fantasy week: his NBA team's games, less any he is expected "
                         "to miss."),
        "ovr": ("OVR", "How good he is per game when he plays, on a fixed 40-99 scale, with its change this "
                       "week. \"Prov.\" means it rests on few games and will settle."),
        "pot": ("POT", "His keeper value: next season's projected fantasy points per game, on the same 40-99 "
                       "scale."),
        "tv": ("Team value", "The points he adds to this team's best daily lineups over the next two weeks, "
                             "against the best free agent in his place. A few points either way is within the "
                             "noise."),
        "tdelta": ("Title \u0394", "His Team value turned into title odds: how many points of title odds he is "
                                   "worth to this team right now."),
        "start": ("Start %", "Of his games while on this team this season, the share he was in a starting slot."),
        "l14": ("L14", "Fantasy points per game over the last 14 days."),
        "vsproj": ("vs Proj", "His FPPG this season minus Yahoo's projection for him: above zero, he is beating "
                              "it."),
        "trend": ("Trend", "His last 10 games as a small line, on one scale for the whole team."),
        "floor": ("Floor", "A bad game for him: 1 game in 10 is lower than this. Shows from 10 games."),
        "ceil": ("Ceil", "A big game for him: 1 game in 10 is higher than this. Shows from 10 games."),
        "boom": ("Boom %", "The share of his games at 1.25 times his FPPG or more."),
        "bust": ("Bust %", "The share of his games at 0.75 times his FPPG or less."),
        "min": ("MIN", "Minutes per game in his NBA games this season."),
        "mind": ("MIN \u0394", "His minutes per game over the last 14 days minus his season's: a bigger or "
                               "smaller role lately."),
        "nstarts": ("Next starts", "Of his games next week, how many fit this team's daily lineup of 10, the "
                                   "same daily fill the engine uses."),
        "gl": ("GL", "Games left this fantasy week that he will play."),
        "b2b": ("B2B", "Back-to-backs (games on two days in a row) in the next 3 fantasy weeks."),
        "avail": ("Avail %", "How often he plays when his NBA team does, this season with his history."),
        "missed": ("Missed", "His NBA team's games this season that he did not play."),
        "back": ("Back", "When he is expected back, if he is out."),
        "keep": ("Keep %", "The chance he is one of this team's keepers next season, from the keeper model."),
        "keeprank": ("Keep rank", "His place on this team by keep chance, against the keeper line (the number "
                                  "the team keeps)."),
        "age": ("Age", "His age today."),
        "acq": ("Acquired", "How and when he joined this team: kept, drafted, a free-agent add or a trade."),
        "since": ("Since acq.", "Fantasy points per game since he joined this team."),
        "arch": ("Archetype", "What kind of fantasy player he is, from his last three NBA seasons and this one."),
        "share": ("Share", "His share of this team's fantasy points this season."),
        "best": ("Best", "His best game this season, in fantasy points."),
        "worst": ("Worst", "His worst game this season, in fantasy points."),
    },
    "players": {
        "name": ("Player", "The player, his fantasy team (or FA for a free agent), positions and NBA team. Tap "
                           "his name for his card."),
        "ovr": ("OVR", "How good he is per game when he plays, on a fixed 40-99 scale that means the same every "
                       "year. \"Prov.\" means it rests on few games and will settle."),
        "pot": ("POT", "His keeper value: next season's projected fantasy points per game, on the same 40-99 "
                       "scale."),
        "dur": ("DUR", "Durability: how often he plays when his team does, over his last three NBA seasons and "
                       "this one, on its own 40-99 scale. A current injury isn't in it."),
        "fppg": ("FPPG", "Fantasy points per game in his NBA games this season, on a league roster or not."),
        "next": ("Next", "Games he will play next fantasy week: his NBA team's games, less any he is expected "
                         "to miss."),
        # 5d2 s.3: the Detailed groups
        "rank": ("Rank", "His place by FPPG among every player in this table."),
        "posrank": ("Pos rank", "His place by FPPG among the players in this table whose first listed position is "
                                "his: C4 is the fourth-best center here."),
        "keep": ("Keep %", "The chance he is one of his team's keepers next season, from the keeper model. A free "
                           "agent has no keep chance."),
        "gp": ("GP", "NBA games he has played this season."),
        "total": ("Total FP", "His fantasy points in his NBA games this season."),
        "proj": ("Proj", "Yahoo's projected fantasy points per game for him for the rest of the season."),
        "vsproj": ("vs Proj", "His FPPG this season minus Yahoo's projection: above zero, he is beating it."),
        "par": ("PAR so far", "Points above replacement in his started games on league rosters this season: the "
                              "number the MVP race uses. Not odds."),
        "started": ("Started", "His NBA games this season played from a starting slot on a league roster."),
        "startpct": ("Start %", "Of his games on his current team this season, the share he started (Team > "
                                "Roster's number)."),
        "potw": ("POTW", "Player of the Week wins this season."),
        "best": ("Best", "His best game this season, in fantasy points, and the opponent."),
        "l7": ("L7", "Fantasy points per game over the last 7 days."),
        "l14": ("L14", "Fantasy points per game over the last 14 days."),
        "l30": ("L30", "Fantasy points per game over the last 30 days."),
        "trend": ("Trend", "His last 10 games as a small line, on one scale for the whole table."),
        "floor": ("Floor", "A bad game for him: 1 game in 10 is lower than this. Shows from 10 games."),
        "ceil": ("Ceil", "A big game for him: 1 game in 10 is higher than this. Shows from 10 games."),
        "boom": ("Boom %", "The share of his games at 1.25 times his FPPG or more. Shows from 10 games."),
        "bust": ("Bust %", "The share of his games at 0.75 times his FPPG or less. Shows from 10 games."),
        "min": ("MIN", "Minutes per game in his NBA games this season."),
        "mind": ("MIN \u0394", "His minutes per game over the last 14 days minus his season's: a bigger or smaller "
                               "role lately."),
        "streak": ("Streak", "Hot: his FPPG over the last 4 weeks is more than 15% above Yahoo's projection; cold: "
                             "more than 15% below (the newsletter's line), from 4 games."),
        "b_min": ("MIN", "Minutes per game (Totals: his minutes this season)."),
        "b_pts": ("PTS", "Points per game (Totals: this season)."),
        "b_reb": ("REB", "Rebounds per game (Totals: this season)."),
        "b_ast": ("AST", "Assists per game (Totals: this season)."),
        "b_stl": ("STL", "Steals per game (Totals: this season)."),
        "b_blk": ("BLK", "Blocks per game (Totals: this season)."),
        "b_to": ("TO", "Turnovers per game (Totals: this season)."),
        "b_3pm": ("3PM", "Made threes per game (Totals: this season)."),
        "b_fg": ("FGM-A", "Field goals made and attempted per game (Totals: this season)."),
        "b_fgp": ("FG%", "Field goals made over attempted, this season."),
        "b_ft": ("FTM-A", "Free throws made and attempted per game (Totals: this season)."),
        "b_ftp": ("FT%", "Free throws made over attempted, this season."),
        "sh_pts": ("From PTS", "The share of his fantasy points that comes from his points scored."),
        "sh_3": ("From 3PM", "The share of his fantasy points that comes from his made threes."),
        "sh_reb": ("From REB", "The share of his fantasy points that comes from rebounds."),
        "sh_ast": ("From AST", "The share of his fantasy points that comes from assists."),
        "sh_stl": ("From STL", "The share of his fantasy points that comes from steals."),
        "sh_blk": ("From BLK", "The share of his fantasy points that comes from blocks."),
        "sh_eff": ("From eff.", "The share from makes, misses and turnovers together (field goals and free throws "
                                "made and missed, turnovers): below zero, they cost him points."),
        "gl": ("GL", "Games left this fantasy week that he will play."),
        "nx3": ("Next 3 wks", "Games he will play over Market's Next 3 weeks range (from the week a pickup now "
                              "would join)."),
        "b2b": ("B2B", "Back-to-backs (games on two days in a row) in the rest of this week and the next two."),
        "semis": ("Semis", "Games he will play in weeks 16\u201318, the playoff semifinals."),
        "finals": ("Finals", "Games he will play in weeks 19\u201321, the final and the third-place series."),
        "cup": ("Cup", "Games he will play in weeks 22\u201323, the Cup."),
        "status": ("Status", "His injury tag, or Healthy."),
        "back": ("Back", "When he is expected back, if he is out."),
        "avail": ("Avail %", "How often he plays when his NBA team does, this season with his history."),
        "missed": ("Missed", "His NBA team's games this season that he did not play."),
        "ilslot": ("IL slot", "\"IL slot\" when he sits in one of his team's IL slots now."),
        "owner": ("Owner", "His fantasy team, or Free agent."),
        "acq": ("Acquired", "How and when he joined his team: kept, drafted, a free-agent add or a trade."),
        "free": ("Free since", "For a free agent: who dropped him and when, or that no team has had him this "
                               "season."),
        "adds": ("Added", "Times a team added him this season (pre-season moves count nowhere, rule 14)."),
        "drops": ("Dropped", "Times a team dropped him this season."),
        "owners": ("Managers", "How many of the four managers have had him on a roster, all-time (from 2017-18)."),
        "seasons": ("Seasons", "Seasons he was on a league roster (2017-18 on)."),
        "cfppg": ("Career FPPG", "Fantasy points per game on league rosters, every season (2017-18 on)."),
        "bestsea": ("Best season", "His best season on league rosters by FPPG."),
        "kept": ("Kept", "Times he has been kept."),
        "drafted": ("Drafted", "His first draft in the league: by whom and when, with the round once the pick order "
                               "is trusted (2024-25 on)."),
        "arch": ("Archetype", "What kind of fantasy player he is, from his last three NBA seasons and this one."),
        "nbasea": ("NBA seasons", "His NBA seasons on file, 2014-15 on; \"+\" means he played before that too."),
        "nbadraft": ("NBA draft", "His NBA draft year and overall pick (the 2014\u20132026 drafts on file)."),
    },
    "market": {
        "name": ("Player", "The free agent, his positions and NBA team, and any injury tag. Tap his name for his "
                           "card."),
        "fppg": ("FPPG", "Fantasy points per game in his NBA games this season."),
        "l14": ("L14", "Fantasy points per game over the last 14 days."),
        "games": ("Games", "Games he will play in each week shown. A pickup in Monday's window joins that week; "
                           "one claimed midweek joins next Monday."),
        # 5d2 s.4: the range picker's columns and sorts
        "pts": ("Proj pts", "Yahoo's projected fantasy points per game times the games he will play in the range."),
        "total": ("Games", "Games he will play over the whole range (an injury entry, an O tag's next games, OFS "
                           "and a D tag's next game are left out)."),
        "l7": ("L7", "Fantasy points per game over the last 7 days."),
        "l30": ("L30", "Fantasy points per game over the last 30 days."),
        "ovr": ("OVR", "How good he is per game when he plays, on a fixed 40-99 scale."),
        "pot": ("POT", "His keeper value: next season's projected fantasy points per game, on the 40-99 scale."),
        "dur": ("DUR", "Durability: how often he plays when his team does, on its own 40-99 scale."),
        "mind": ("MIN \u0394", "His minutes per game over the last 14 days minus his season's."),
        "avail": ("Avail %", "How often he plays when his NBA team does, this season with his history."),
        "status": ("Status", "His injury tag, or Healthy."),
        "age": ("Age", "His age today."),
    },
    "standings": {
        "team": ("Team", "The team, ranked by the regular-season standings: record, then head-to-head, then "
                         "points."),
        "wl": ("W-L", "Wins and losses this regular season; a tied week counts as half a win."),
        "pf": ("PF", "Points for: the team's fantasy points this regular season."),
        "strk": ("Strk", "The current streak: W3 is three wins in a row. A tied week ends a streak."),
        "title": ("Title odds", "The chance this team finishes first in the regular season and is League "
                                "Champion, with its change since the run before. Tap it for the chart."),
    },
    "alltime": {
        "team": ("Team", "The manager and his team today, over every season with records."),
        "wl": ("W-L", "Every regular-season week, won and lost; a tied week counts as half a win."),
        "pf": ("PF", "Points for, every season with Yahoo data (2017-18 on)."),
        "titles": ("Titles", "League Championships: first in the regular season."),
        "playoff": ("Playoff", "Playoff titles: the bracket's winner."),
    },
    "draft": {
        "pick": ("Pick", "Round and pick, as Yahoo recorded the draft (2024-25 on: earlier pick orders aren't "
                         "reliable)."),
        "player": ("Player", "Who was drafted, and by which team; keepers sit in the last rounds."),
        "then": ("Then", "His OVR when that season started, on the fixed 40-99 scale (\"wk 2\" when he was first "
                         "rated a week in)."),
        "now": ("Now", "His OVR today."),
        "deadline": ("Deadline", "His OVR at that season's trade-deadline point."),
    },
    "keepers": {
        "player": ("Player", "Everyone on this team, in IL slots too."),
        "keep": ("Keep", "The chance he is one of this team's keepers next season."),
        "rank": ("Rank", "His place on this team by keep chance; the top ones are the likely keepers."),
    },
    "last5": {
        "day": ("Day", "The day of the game."),
        "opp": ("Opp", "His NBA team's opponent that day; @ is away."),
        "fp": ("FP", "His fantasy points in that game; INJ when he was out."),
        "min": ("MIN", "Minutes he played in that game."),
    },
    "career": {
        "season": ("Season", "A season he was on a league roster (2017-18 on)."),
        "gp": ("GP", "Games he played on league rosters that season."),
        "fppg": ("FPPG", "Fantasy points per game on league rosters that season."),
        "total": ("Total", "His fantasy points on league rosters that season."),
        "with": ("With", "The managers he played for that season."),
    },
    "compare": {
        "ovr": ("OVR", "How good he is per game when he plays, on a fixed 40-99 scale."),
        "pot": ("POT", "His keeper value: next season's projected fantasy points per game, on the 40-99 scale."),
        "dur": ("DUR", "Durability: how often he plays when his team does, on its own 40-99 scale."),
        "fppg": ("FPPG", "Fantasy points per game this season."),
        "l14": ("L14", "Fantasy points per game over the last 14 days."),
        "min": ("MIN", "Minutes per game this season."),
        "avail": ("Avail %", "How often he plays when his NBA team does, this season with his history."),
        "g3": ("Games, next 3 wks", "Games he will play over the next 3 fantasy weeks."),
        "keep": ("Keep %", "The chance he is one of his team's keepers next season; none for a free agent."),
        "age": ("Age", "His age today."),
        "scoring": ("Scoring", "Fantasy points per game from his points, ranked among rostered players."),
        "shooting": ("Shooting", "Fantasy points per game from his made threes, ranked among rostered players."),
        "playmaking": ("Playmaking", "Fantasy points per game from his assists, ranked among rostered players."),
        "rebounding": ("Rebounding", "Fantasy points per game from his rebounds, ranked among rostered players."),
        "steals": ("Steals", "Fantasy points per game from his steals, ranked among rostered players."),
        "blocks": ("Blocks", "Fantasy points per game from his blocks, ranked among rostered players."),
        "efficiency": ("Efficiency", "Fantasy points per game from makes, misses and turnovers: high means he "
                                     "shoots well and rarely turns it over."),
        "consistency": ("Consistency", "How steady his games are: the smaller the swings around his average, "
                                       "the higher."),
        "schedule": ("Schedule", "His NBA team's games over the next 3 fantasy weeks, ranked."),
    },
    "grid": {
        "week": ("Week", "Games each player will play in that fantasy week; tap a cell for the days and who "
                         "starts."),
        "idle": ("Idle", "Games this week by players who sit: more than 10 of the team's healthy players have "
                         "a game that day (an overflow day), or a position can't seat them."),
        "total": ("Total", "Games over the weeks shown."),
    },
    # 5d2 s.1: Team > Schedule
    "sched": {
        "week": ("Week", "The rest of this fantasy week, next week and the week after. Week 7 (and 17) is one "
                         "fantasy week of 14 days."),
        "starts": ("You", "Startable games: games your team can actually start, after the daily 10, players in IL "
                          "slots and players who are out. Under it, the games your players will play."),
        "avg": ("League avg", "The four teams' average startable games that week. A range means a Q-tagged "
                              "player's next game is uncertain."),
        "rank": ("Rank", "Your place among the four teams by startable games that week."),
        "opp": ("Opponent", "That week's opponent, his startable games and your edge in games. A playoff or Cup "
                            "week's opponent shows once the results that decide it are in."),
    },
    "sgrid": {
        "player": ("Player", "Who is on your roster that week, his positions and NBA team, and why he is out or "
                             "in an IL slot. Rows from next week on count the pending group-chat moves."),
        "day": ("Day", "One day of the week. Gold: a light day (4 or fewer of your players have a game). Dark: "
                       "an overflow day (more than 10). ~ an estimated day; \u2020 out tonight on the NBA's "
                       "injury report."),
        "g": ("G", "Games he will play that week (not out, not in an IL slot)."),
        "s": ("S", "Of his games, how many fit your daily lineup of 10: the engine's exact fill, best "
                   "projected players first."),
    },
    "splay": {
        "player": ("Player", "Who is on your roster as it will stand next week; IL slots last."),
        "semis": ("Semifinals", "Games he will play in weeks 16\u201318, the best-of-3 semifinals (his injury entry "
                                "and tags applied)."),
        "finals": ("Finals", "Games he will play in weeks 19\u201321, the final and the third-place series."),
        "cup": ("Cup", "Games he will play in weeks 22\u201323, the Cup."),
    },
    # 5d2 s.2: Matchups > Next week, before its opponents are set
    "nextwk": {
        "team": ("Team", "Each team, with its chance of each regular-season seed."),
        "seed": ("Seed", "The chance this team finishes the regular season in that place, from the title-odds "
                         "simulation: 1 v 4 and 2 v 3 in the semifinals."),
    },
}


def column(table: str, key: str) -> tuple:
    """(name, definition) of one table column. RAISES KeyError for one
    with no entry: every header has a definition."""
    if table not in COLUMNS or key not in COLUMNS[table]:
        raise KeyError(f"no column definition {table}|{key}: add it to modules/hub_v2/infotips.COLUMNS")
    return COLUMNS[table][key]


def columns_flat() -> dict:
    """{"table|key": [name, definition]}: the page's one copy (#v2-coldefs)."""
    return {f"{t}|{k}": list(v) for t, cols in COLUMNS.items() for k, v in cols.items()}
