"""
Typed storylines (prose layer, item 1).

compute_storyline_alerts() in format_stats_report used to build its "READ
FIRST" strings directly. The angle selector (modules/angles.py) needs the
same storylines as data -- what kind, about whom, how big -- so this builds
Storyline objects and the alert strings are rendered from them. The strings
are byte-for-byte what they were (tests/test_storylines.py pins them against
every archived 2025-26 report).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class Storyline:
    kind: str                 # see KINDS
    managers: tuple           # primary first
    text: str                 # the alert string, exactly as before
    magnitude: dict = field(default_factory=dict, hash=False, compare=False)

    @property
    def family(self) -> str:
        return FAMILY[self.kind]


# kind -> family. A family is what the angle selector dedupes on: the
# streak alert and the matchup's streak angle are the same story.
FAMILY = {
    "season_high_score": "record", "alltime_win_streak": "streak",
    "season_win_streak": "streak", "loss_streak": "streak",
    "streak_snapped": "streak", "major_upset": "upset", "upset": "upset",
    "spread_covered": "spread", "close_call": "spread",
    "milestone": "milestone", "win_streak_record": "streak",
    "win_streak_tied": "streak", "win_streak_watch": "streak",
    "win_streak_alert": "streak", "alltime_blowout": "margin",
    "blowout": "margin", "alltime_closest": "margin", "nail_biter": "margin",
    "close_game": "margin", "standings_lead": "standings",
    "clinch_watch": "standings",
}

MILESTONE_WINS = [50, 75, 100, 125, 150, 175, 200]
BLOWOUT_MARGIN = 500
NAIL_BITER_MARGIN = 10
CLOSE_GAME_MARGIN = 25
STANDINGS_LEAD_GAMES = 4
SPREAD_ALERT_MIN = 30
CLOSE_CALL_SHORTFALL = 50


def _other(m: dict, mgr: str) -> str:
    return m.get("manager_a") if mgr == m.get("manager_b") else \
        m.get("manager_b")


def compute_storylines(data: dict, predictions: Optional[dict],
                       season: str, managers: list) -> list[Storyline]:
    out: list[Storyline] = []
    add = out.append
    week = (data.get("metadata") or {}).get("week", 0)
    streaks = data.get("current_streaks") or {}
    atr = data.get("all_time_records") or {}
    at_win = atr.get("longest_win_streaks") or {}
    career = {c["manager"]: c for c in (atr.get("career_standings") or [])}
    mentioned = set()
    matchups = data.get("matchup_summaries") or []

    # === RECORD UPDATES ===
    for update in data.get("record_updates", []):
        desc = update.get("description", "")
        val = update.get("value", "")
        utype = update.get("type", "")
        if "highest_weekly_team_score" in utype:
            for ms in matchups:
                for side in ("a", "b"):
                    if ms[f"stats_{side}"]["total_fp"] == val:
                        mgr = ms[f"manager_{side}"]
                        add(Storyline(
                            "season_high_score", (mgr,),
                            f" -> SEASON RECORD: {mgr} scored {val:.2f} FP -> "
                            f"the highest team score of the {season} season",
                            {"score": val}))
                        break
                else:
                    continue
                break
        elif "win_streak" in utype:
            if "new" in desc.lower() or "sets" in desc.lower():
                for mgr in managers:
                    if mgr.lower() not in desc.lower():
                        continue
                    cur = streaks.get(mgr, {}).get("win_streak", 0)
                    at = at_win.get(mgr, {}).get("length", 0)
                    ats = at_win.get(mgr, {}).get("season", "")
                    if not at:
                        # No all-time streak on file for him, so there is no
                        # record to beat. Defaulting length to 0 and season to
                        # "" made every streak a record and printed
                        # "surpassing their previous record of 0 ()".
                        # The blowout claims below already require a stored
                        # record before asserting one.
                        continue
                    mag = {"streak": cur, "all_time": at}
                    if cur > at:
                        add(Storyline(
                            "alltime_win_streak", (mgr,),
                            f" -> ALL-TIME RECORD: {mgr} set a new personal "
                            f"best with a {cur}-game win streak, surpassing "
                            f"their previous record of {at} ({ats})", mag))
                    else:
                        gap = at - cur
                        if gap == 1:
                            t = (f" -> SEASON RECORD: {mgr} set a new "
                                 f"season-best {cur}-game win streak -> just 1 "
                                 f"win from tying their all-time record of "
                                 f"{at} ({ats})")
                        elif gap == 2:
                            t = (f" -> SEASON RECORD: {mgr} set a new "
                                 f"season-best {cur}-game win streak -> 2 wins "
                                 f"from tying their all-time record of {at} "
                                 f"({ats})")
                        else:
                            t = (f" -> SEASON RECORD: {mgr} set a new "
                                 f"season-best {cur}-game win streak "
                                 f"(all-time record: {at})")
                        add(Storyline("season_win_streak", (mgr,), t, mag))
                    mentioned.add(mgr)
                    break
        elif "loss_streak" in utype:
            for mgr in managers:
                if mgr.lower() in desc.lower():
                    cur = streaks.get(mgr, {}).get("loss_streak", 0)
                    add(Storyline("loss_streak", (mgr,),
                                  f" -> LOSING STREAK: {mgr} has now lost "
                                  f"{cur} straight", {"streak": cur}))
                    break

    # === LOSING STREAK ENDINGS ===
    for m in matchups:
        winner = m.get("winner")
        loser = _other(m, winner)
        ws = streaks.get(winner, {})
        sl = ws.get("season_longest_loss_streak", 0)
        slw = ws.get("season_longest_loss_weeks", "")
        if ws.get("win_streak", 0) == 1 and sl >= 3 and slw:
            try:
                parts = slw.split("-")
                if len(parts) == 2:
                    a, b = int(parts[0]), int(parts[1])
                    if b == week - 1:
                        wkey = "stats_a" if winner == m["manager_a"] else \
                            "stats_b"
                        lkey = "stats_b" if winner == m["manager_a"] else \
                            "stats_a"
                        add(Storyline(
                            "streak_snapped", (winner, loser),
                            f" -> STREAK SNAPPED: {winner} ends {sl}-game "
                            f"losing streak (weeks {a}-{b}) with Week {week} "
                            f"victory over {loser}, "
                            f"{m.get(wkey, {}).get('total_fp', 0):.2f} -> "
                            f"{m.get(lkey, {}).get('total_fp', 0):.2f}",
                            {"streak": sl}))
            except (ValueError, TypeError):
                pass

    # === UPSETS / SPREADS (last week's lines) ===
    if predictions:
        for m in matchups:
            winner = m.get("winner")
            loser = _other(m, winner)
            a, b = m.get("manager_a"), m.get("manager_b")
            margin = m.get("margin", 0)
            pred = predictions.get(tuple(sorted([a, b])))
            if not pred:
                continue
            fav, dog = pred.get("favorite"), pred.get("underdog")
            fp_ = pred.get("win_prob_favorite", 50)
            dp = pred.get("win_prob_underdog", 50)
            spread = pred.get("spread", 0)
            if winner == dog and fp_ >= 51:
                ws_ = m.get("stats_a" if winner == a else "stats_b",
                            {}).get("total_fp", 0)
                ls_ = m.get("stats_b" if winner == a else "stats_a",
                            {}).get("total_fp", 0)
                mag = {"underdog_prob": dp, "favorite_prob": fp_}
                if fp_ >= 70:
                    add(Storyline("major_upset", (winner, loser),
                                  f" -> MAJOR UPSET: {winner} ({dp:.0f}% win "
                                  f"prob) stuns {loser} ({fp_:.0f}% favorite), "
                                  f"{ws_:.2f} -> {ls_:.2f}", mag))
                elif fp_ >= 60:
                    add(Storyline("upset", (winner, loser),
                                  f" -> UPSET: {winner} ({dp:.0f}% win prob) "
                                  f"defeats favored {loser} ({fp_:.0f}%), "
                                  f"{ws_:.2f} -> {ls_:.2f}", mag))
                else:
                    add(Storyline("upset", (winner, loser),
                                  f" -> UPSET: {winner} wins as {dp:.0f}% "
                                  f"underdog over {loser} ({fp_:.0f}% "
                                  f"favorite)", mag))
            elif winner == fav and spread and abs(spread) >= SPREAD_ALERT_MIN:
                mag = {"spread": abs(spread), "margin": margin}
                if margin > abs(spread):
                    add(Storyline("spread_covered", (winner, loser),
                                  f" -> SPREAD COVERED: {winner} beat the "
                                  f"{abs(spread):.1f}-point spread with "
                                  f"{margin:.2f}-point victory", mag))
                elif margin < abs(spread) - CLOSE_CALL_SHORTFALL:
                    add(Storyline("close_call", (winner, loser),
                                  f" -> CLOSE CALL: {winner} was favored by "
                                  f"{abs(spread):.1f} but only won by "
                                  f"{margin:.2f}", mag))

    # === CAREER MILESTONES ===
    for mgr, c in career.items():
        wins = c.get("wins", 0)
        won = any(m.get("winner") == mgr for m in matchups)
        if not won or wins not in MILESTONE_WINS:
            continue
        ms_ = streaks.get(mgr, {})
        ls_ = ms_.get("season_longest_loss_streak", 0)
        lw = ms_.get("season_longest_loss_weeks", "")
        wait = ""
        if lw and ls_ >= 2:
            try:
                parts = lw.split("-")
                if len(parts) == 2:
                    s0, e0 = int(parts[0]), int(parts[1])
                    if e0 == week - 1:
                        wait = (f" after a {ls_}-week wait (stuck at "
                                f"{wins - 1} since Week {s0})")
            except (ValueError, TypeError):
                pass
        add(Storyline("milestone", (mgr,),
                      f" -> MILESTONE: {mgr} secures career win #{wins}{wait}",
                      {"wins": wins}))

    # === WIN STREAK CONTEXT ===
    for mgr, ms_ in streaks.items():
        if mgr in mentioned:
            continue
        cur = ms_.get("win_streak", 0)
        if cur < 3:
            continue
        at = at_win.get(mgr, {}).get("length", 0)
        ats = at_win.get(mgr, {}).get("season", "")
        if not at:
            # Same as above: no stored record, so no record claim. This is
            # what printed "(previous: 0 in )" in the week-16 report.
            continue
        mag = {"streak": cur, "all_time": at}
        if cur > at:
            add(Storyline("win_streak_record", (mgr,),
                          f" -> ALL-TIME RECORD: {mgr}'s {cur}-game win streak "
                          f"is a new personal best (previous: {at} in {ats})",
                          mag))
        elif cur == at:
            add(Storyline("win_streak_tied", (mgr,),
                          f" -> RECORD TIED: {mgr}'s {cur}-game win streak "
                          f"ties their all-time best ({ats})", mag))
        elif cur == at - 1:
            add(Storyline("win_streak_watch", (mgr,),
                          f" -> RECORD WATCH: {mgr} has won {cur} straight -> "
                          f"1 win from tying their all-time record of {at} "
                          f"({ats})", mag))
        elif cur == at - 2 and cur >= 4:
            add(Storyline("win_streak_alert", (mgr,),
                          f" -> STREAK ALERT: {mgr} has won {cur} straight "
                          f"(all-time record: {at})", mag))

    # === MATCHUP MARGINS ===
    bb = atr.get("biggest_blowout", {})
    cg = atr.get("closest_game", {})
    for m in matchups:
        margin = m.get("margin", 0)
        winner = m.get("winner")
        loser = _other(m, winner)
        mag = {"margin": margin}
        if margin > BLOWOUT_MARGIN:
            if bb.get("margin", 0) and margin > bb["margin"]:
                add(Storyline("alltime_blowout", (winner, loser),
                              f" -> ALL-TIME BLOWOUT: {winner}'s {margin:.2f}-"
                              f"point victory over {loser} is the largest "
                              f"margin in league history!", mag))
            else:
                add(Storyline("blowout", (winner, loser),
                              f" -> BLOWOUT: {winner} crushed {loser} by "
                              f"{margin:.2f} points", mag))
        elif margin < NAIL_BITER_MARGIN:
            if cg.get("margin", float("inf")) and margin < cg["margin"]:
                add(Storyline("alltime_closest", (winner, loser),
                              f" -> ALL-TIME CLOSEST: {winner}'s {margin:.2f}-"
                              f"point victory over {loser} is the closest game "
                              f"in league history!", mag))
            else:
                add(Storyline("nail_biter", (winner, loser),
                              f" -> NAIL-BITER: {winner} edged {loser} by just "
                              f"{margin:.2f} points", mag))
        elif margin < CLOSE_GAME_MARGIN:
            add(Storyline("close_game", (winner, loser),
                          f" -> CLOSE GAME: {winner} held off {loser} by "
                          f"{margin:.2f} points", mag))

    # === STANDINGS ===
    st = data.get("current_standings", [])
    if st and len(st) > 1:
        lead, sec = st[0], st[1]
        try:
            gb = int(lead.get("record", "0-0").split("-")[0]) - \
                int(sec.get("record", "0-0").split("-")[0])
            if gb >= STANDINGS_LEAD_GAMES:
                add(Storyline("standings_lead",
                              (lead["manager"], sec["manager"]),
                              f" -> STANDINGS: {lead['manager']} leads by {gb} "
                              f"games over {sec['manager']} ({lead['record']} "
                              f"vs {sec['record']})", {"games_back": gb}))
        except (ValueError, IndexError):
            pass

    for pr in (data.get("power_rankings") or []):
        if pr.get("magic_number") and pr.get("rank") == 1:
            add(Storyline("clinch_watch", (pr["manager"],),
                          f" -> CLINCH WATCH: {pr['manager']}'s magic number "
                          f"is {pr['magic_number']}",
                          {"magic_number": pr["magic_number"]}))
    return out
