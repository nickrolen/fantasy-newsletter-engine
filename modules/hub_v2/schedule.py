"""
hub_v2/schedule.py -- ENGINE SIDE of Team > Schedule (5d2 s.1; Nick's notes item 11,
his answers on the mock 11-21) and Matchups > Next week (s.2, item 12). Every
number is a string made here from the one range source (hub_v2/ranges.py):
the page prints and reorders, it computes nothing.

THE WORDS (Nick, 11-21, firm): a LIGHT DAY is 4 or fewer of the team's players
with a game (the games grid's meaning, config hub.light_night_max); 5 to 10 is
no label; an OVERFLOW DAY is more than 10 (someone with a game sits). Empty
slots are counts ("Empty slots: 43", "Mon 11-30 \u00b7 5 open"), never a day's name.

    v2["sched"] = {
      "weeks": [{"w", "label", "sub", "chip", "long", "days": [{"iso", "dow", "d", "today"}]}]
                    the rest of this week, next week, the week after (the
                    weeks that exist)
      "open": the index of the week the page opens on: the week a pickup can
              still change (this week before Monday's window closes, next week
              after it)
      "note": the overview's note
      "teams": {manager: {"ov": [row per week], "panes": [pane per week],
                          "pickups": {...} or None, "playoffs": {...} or None}}
    }   (teams moves to the side file: data.SIDE_KEYS)
    v2["next_week"] = {...} or None (after the season's last week)

WHICH OPPONENT: the regular season's from config/SCHEDULE.json; a bracket or
Cup week's from advice_live.bracket_opponents once its pairing is set, else
"Opponent set after week N" (never guessed).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Dict, List, Optional

from .ranges import rng, SEATS

DASH = "\u2014"
NDASH = "\u2013"
DOT = "\u00b7"
DAGGER = "\u2020"
MINUS = "\u2212"
DOW = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


class ScheduleError(RuntimeError):
    """A schedule input is missing or inconsistent; named."""


def md(d: date) -> str:
    return f"{d.month:02d}-{d.day:02d}"


def dmd(d: date) -> str:
    return f"{DOW[d.weekday()]} {md(d)}"


def _avg(vals: List[float]) -> str:
    return f"{sum(vals) / len(vals):.1f}"


def _plural(n, word):
    return f"{n} {word}" + ("" if str(n) == "1" else "s")


# =============================================================================
# the weeks and the opponents
# =============================================================================

def shown_weeks(week: int, wk_dates: Dict[int, list], today: date) -> List[dict]:
    """The rest of this week, next week and the week after (those that exist)."""
    out = []
    for w in (week, week + 1, week + 2):
        full = list(wk_dates.get(w) or [])
        if not full:
            continue
        days = [d for d in full if d >= today] if w == week else full
        if not days:
            continue
        rest = days[0] != full[0]
        long = len(full) > 7
        if rest:
            label = f"Week {w} {DOT} rest"
            sub = f"{dmd(days[0])} to {dmd(days[-1])} {DOT} {_plural(len(days), 'day')} left"
            chip = f"Wk {w} rest"
        else:
            label = f"Week {w}" + (f" {DOT} {len(full)} days" if long else "")
            sub = f"{dmd(full[0])} to {dmd(full[-1])}"
            chip = f"Wk {w}" + (f" {DOT} {len(full)} days" if long else "")
        out.append({"w": w, "label": label, "sub": sub, "chip": chip, "long": long, "_days": days,
                    "days": [{"iso": d.isoformat(), "dow": DOW[d.weekday()][0], "d": str(d.day),
                              "today": d == today} for d in days]})
    return out


def stage_after(w: int, league_config: dict = None) -> Optional[int]:
    """For a bracket or Cup week: the week after which its pairing is set
    (Semifinals: the regular season's last; Final: the Semifinals' last; Cup
    semifinal: the week before the Cup; Cup final: the Cup's first)."""
    from .ranges import stage_weeks_cfg
    sw = stage_weeks_cfg(league_config)
    if w <= sw["ros"][1]:
        return None
    if sw["semis"][0] <= w <= sw["semis"][1]:
        return sw["ros"][1]
    if sw["finals"][0] <= w <= sw["finals"][1]:
        return sw["semis"][1]
    if w == sw["cup"][0]:
        return sw["cup"][0] - 1
    if sw["cup"][0] < w <= sw["cup"][1]:
        return sw["cup"][0]
    raise ScheduleError(f"week {w} is in no stage of config postseason_format")


def opponents_for(data, w: int, managers) -> Dict[str, Optional[str]]:
    """{manager: opponent or None (not set yet)} for week w."""
    from ..data_loader import CURRENT_SEASON, regular_season_weeks_for
    last_reg = int(regular_season_weeks_for(CURRENT_SEASON))
    if w <= last_reg:
        wk = next((x for x in data.schedule["weeks"] if int(x["week"]) == int(w)), None)
        if wk is None:
            raise ScheduleError(f"week {w} is not in config/SCHEDULE.json")
        out = {}
        for mu in wk.get("matchups") or []:
            a, b = mu["manager_a"], mu["manager_b"]
            out[a], out[b] = b, a
        missing = [m for m in managers if m not in out]
        if missing:
            raise ScheduleError(f"week {w}'s matchups in config/SCHEDULE.json leave out {missing}")
        return out
    from ..advice_live import bracket_opponents
    got = bracket_opponents(data, w)
    return {m: (got[m][0] if m in got else None) for m in managers}


# =============================================================================
# one team's week
# =============================================================================

def _tags(p: dict) -> str:
    return f" {DOT} ".join(str(t["text"]) for t in p.get("tags") or [] if t.get("kind") in ("out", "q", "il"))


def strip_day(src, m: str, d: date, today: date, standins: dict) -> dict:
    x = src.day(m, d)
    av = src.av_on(d)
    s_lo, s_hi = x.starts
    e_hi = x.empty[0]                                # empty even if every Q plays
    i_hi = x.idle[1]
    il = av.il.get(m) or {}
    names = [n for n in av.rosters.get(m, [])]
    outs = [n for n in names if n not in il and av.has_game(n, d) and not av.plays(n, d)
            and n not in x.nba_out]
    il_g = [n for n in names if n in il and av.has_game(n, d)]
    q = [p for p in x.started if p not in set(x.sure_started)]
    head = f"{dmd(d)} {DOT} " + (_plural(x.nba, "NBA game") if x.nba else "no NBA games")
    kind = {"light": "Light day", "over": "Overflow day"}.get(x.kind, "")
    lines = []
    if x.nba:
        lines.append(["Start", f"{len(x.sure_started)}" + (f"+{len(q)}" if q else ""),
                      ", ".join(list(x.sure_started) + [f"{p} (Q)" for p in q]) or DASH])
        if x.sitting:
            lines.append(["Idle", str(len(x.sitting)), ", ".join(x.sitting)])
        if x.empty[1]:
            lines.append(["Empty slots", rng(*x.empty), ""])
    if x.nba_out:
        lines.append([f"{DAGGER} Out tonight (NBA report)", str(len(x.nba_out)), ", ".join(x.nba_out)])
    if outs:
        lines.append(["Out", str(len(outs)), ", ".join(outs)])
    if il_g:
        lines.append(["In IL slots (don't score)", str(len(il_g)), ", ".join(il_g)])
    est = x.est
    if est:
        lines.append(["Estimated", "", "a game the NBA hasn't scheduled yet is counted on this day"])
    if not x.nba:
        lab = ""
    elif i_hi:
        lab = f"+{i_hi}"
    elif e_hi:
        lab = str(e_hi)
    else:
        lab = ""
    aria = (f"{dmd(d)}: no NBA games" if not x.nba else
            f"{dmd(d)}: {rng(s_lo, s_hi)} start, {rng(*x.idle)} idle, {rng(*x.empty)} empty slots"
            + (f", {kind.lower()}" if kind else ""))
    return {"iso": d.isoformat(), "dow": DOW[d.weekday()][0], "d": str(d.day), "today": d == today,
            "s": s_lo, "q": s_hi - s_lo, "e": e_hi, "i": i_hi, "off": not x.nba, "kind": x.kind,
            "est": est, "nba": bool(x.nba_out), "lab": lab, "lab_k": "i" if i_hi else ("e" if e_hi else ""),
            "aria": aria, "dd": {"head": head + (f" {DOT} {kind}" if kind else ""), "lines": lines}}


def grid_rows(src, m: str, days: List[date], blocks: dict, card_of, info, today: date,
              standins: dict) -> tuple:
    """(header marks per day, rows): the players by day (the mock's grid, Nick 11-21:
    back-to-backs marked, estimated days and the NBA report's out-tonight on
    today's column)."""
    names, seen = [], set()
    for d in days:
        for n in src.av_on(d).rosters.get(m, []):
            if n not in seen:
                seen.add(n)
                names.append(n)
    by_name = {p["name"]: p for p in (blocks.get(m) or {}).get("players", [])}
    proj = lambda n: float(info[n].get("proj_fppg", 0.0)) if n in info else 0.0   # noqa: E731
    first_av = src.av_on(days[0])
    il0 = first_av.il.get(m) or {}
    active = sorted([n for n in names if n not in il0], key=lambda n: (-proj(n), n))
    ilp = sorted([n for n in names if n in il0], key=lambda n: (-proj(n), n))
    heads = []
    for d in days:
        x = src.day(m, d)
        heads.append({"dow": DOW[d.weekday()][0], "d": str(d.day), "kind": x.kind, "est": x.est,
                      "today": d == today, "nba": bool(x.nba_out) and d == today})
    rows = []
    for n in active + ilp:
        p = by_name.get(n)
        inf = info.get(n) or {}
        pos = p["pos"] if p else "/".join(inf.get("positions") or [])
        nba = p["nba"] if p else str(inf.get("nba_team") or "")
        tg = _tags(p) if p else ""
        joins = next((d for d in days if n in src.av_on(d).rosters.get(m, [])), None)
        if p is None and joins is not None:
            tg = (tg + f" {DOT} " if tg else "") + f"joins {dmd(joins)}"
        gone = next((d for d in days if n not in src.av_on(d).rosters.get(m, [])), None) if p else None
        if gone is not None:
            tg = (tg + f" {DOT} " if tg else "") + f"leaves {dmd(gone)}"
        team = str(inf.get("nba_team") or nba).upper()
        cells, g, s = [], 0, 0
        prev_game = None
        for d in days:
            av = src.av_on(d)
            x = src.day(m, d)
            on = n in av.rosters.get(m, [])
            has = on and av.has_game(n, d)
            c = {"c": ""}
            if not on:
                c["c"] = "x"                                     # not on the roster that day
            elif not has:
                c["c"] = ""
            elif n in (av.il.get(m) or {}):
                c["c"] = "il"
            elif n in x.nba_out:
                c["c"] = "nba"
            elif not av.plays(n, d):
                c["c"] = "out"
            elif n in x.sure_started:
                c["c"] = "s"
                g, s = g + 1, s + 1
            elif n in x.started:
                c["c"] = "q"
                g, s = g + 1, s + 1
            else:
                c["c"] = "i"
                g += 1
            if has:
                if prev_game is not None and (d - prev_game).days == 1:
                    c["b2b"] = True
                prev_game = d
                if d in standins.get(team, ()):
                    c["est"] = True
            cells.append(c)
        il_now = n in il0
        rows.append({"name": n, "card": (p or {}).get("card") or card_of(n), "il": il_now,
                     "dim": il_now or any(t.get("kind") == "out" for t in ((p or {}).get("tags") or [])),
                     "sub": f"{pos} {DOT} {nba}" + (f" {DOT} {tg}" if tg else ""),
                     "cells": cells, "g": str(g), "s": str(s)})
    return heads, rows


# =============================================================================
# the build
# =============================================================================

def build(ctx: dict) -> tuple:
    """(v2["sched"], v2["next_week"]) from hub_state.build's ctx (the keys read
    below). RAISES ScheduleError / RangeError on a missing input."""
    src = ctx["ranges"]
    week, today, now = int(ctx["week"]), ctx["today"], ctx["now"]
    wk = {int(w): list(v) for w, v in ctx["wk_dates"].items()}
    managers = list(ctx["managers"])
    team_of = ctx["team_of"]
    blocks = ctx["roster_blocks"]
    info = src.av.info
    standins = src.standins
    card_of = ctx.get("card_of") or (lambda n: None)
    mode, join = ctx["fcols"]["mode"], ctx["fcols"]["join"]
    J = week if mode == "this" else week + 1
    weeks = shown_weeks(week, wk, today)
    opp = {x["w"]: opponents_for(ctx["data"], x["w"], managers) for x in weeks}
    open_i = next((i for i, x in enumerate(weeks) if x["w"] == J), 0)

    teams = {m: {"ov": [], "panes": [], "pickups": None, "playoffs": None} for m in managers}
    for x in weeks:
        days = x["_days"]
        tr = {m: src.team(m, days) for m in managers}
        avg = rng(_avg([tr[m].starts[0] for m in managers]), _avg([tr[m].starts[1] for m in managers]))
        order = sorted(managers, key=lambda m: (-tr[m].starts[0], -tr[m].starts[1], m))
        for m in managers:
            t, tx = tr[m], tr[m].texts()
            o = opp[x["w"]].get(m)
            if o is None:
                after = stage_after(x["w"])
                otxt = {"m": None, "text": f"Opponent set after week {after}" if after else "No matchup"}
                edge, edge_dir, ostarts = "", "", ""
            else:
                ostarts = rng(*tr[o].starts)
                e = t.starts[1] - tr[o].starts[1]
                edge = (f"+{e}" if e > 0 else f"{MINUS}{abs(e)}" if e < 0 else "even") + (" for you" if e else "")
                edge_dir = "up" if e > 0 else "down" if e < 0 else ""
                otxt = {"m": o, "text": team_of.get(o, o)}
            row = {"label": x["label"], "sub": x["sub"], "starts": tx["starts"], "games": tx["games"],
                   "avg": avg, "rank": f"#{order.index(m) + 1} of {len(managers)}", "opp": otxt,
                   "ostarts": ostarts, "edge": edge, "edge_dir": edge_dir}
            teams[m]["ov"].append(row)
            heads, rows = grid_rows(src, m, days, blocks, card_of, info, today, standins)
            teams[m]["panes"].append({
                "w": x["w"], "label": x["label"], "sub": x["sub"], "opp": otxt,
                "tiles": [
                    {"k": "starts", "label": "Startable", "v": tx["starts"],
                     "ctx": f"{row['rank']} {DOT} avg {avg}"},
                    {"k": "games", "label": "Total games", "v": tx["games"], "ctx": "players who will play"},
                    {"k": "pts", "label": "Proj. points", "v": tx["pts"], "ctx": "your starters"},
                    {"k": "idle", "label": "Idle", "v": tx["idle"], "ctx": "games by players who sit"},
                    {"k": "empty", "label": "Empty slots", "v": tx["empty"], "ctx": "starting slots no one fills"},
                    {"k": "days", "label": "Light / overflow", "v": f"{tx['light']} / {tx['over']}",
                     "ctx": "days (4 or fewer / more than 10 with a game)"}],
                "strip": [strip_day(src, m, d, today, standins) for d in days],
                "heads": heads, "rows": rows})
    # where pickups would help: the week a pickup made now joins (rule 7)
    jw = next((x for x in weeks if x["w"] == J), None)
    if jw is not None and join is not None:
        days = jw["_days"]
        fa_av, fa_rows = ctx["fa_av"], ctx["fa_rows"]
        for m in managers:
            ed = src.empty_days(m, days)
            chips = [f"{dmd(d)} {DOT} {rng(*src.day(m, d).empty)} open" for d in ed]
            tot = src.team(m, days).empty
            fits = []
            for r in fa_rows:
                n = r["name"]
                g_e = src.games_on_empty(m, n, fa_av, days)
                if g_e <= 0:
                    continue
                fits.append((g_e, float(r["_proj"]), n, r))
            fits.sort(key=lambda z: (-z[0], -z[1], z[2]))
            left = ctx["adds_left"][m]
            when = ctx["window_text"]
            teams[m]["pickups"] = {
                "w": J, "head": f"Week {J} only",
                "lead": (f"A pickup now plays from today (this week's window is open), so week {J}'s empty slots "
                         "are the ones a pickup can still fill." if J == week else
                         f"A pickup claimed now joins {dmd(wk[J][0])} (rule 7), so week {J}'s empty slots are "
                         "the ones a pickup can still fill."),
                "total": rng(*tot), "ndays": str(len(ed)), "chips": chips,
                "adds": f"{left} of {ctx['budget']} adds left {DOT} {ctx['budget_note']}",
                "window": when,
                "fas": [{"name": n, "card": card_of(n), "meta": f"{r['pos']} {DOT} {r['nba']} {DOT} {r['proj']} proj",
                         "n": str(g_e), "g": str(src.player_games(n, days, fa_av)),
                         "text": f"{_plural(g_e, 'game')} on days you have an empty slot"}
                        for g_e, _p, n, r in fits[:4]],
                "none": "" if fits else "None of Market's free agents has a game on those days.",
                "href": f"#/market?r=next&fit={m}"}
    # the playoff and Cup weeks (Nick, 11-21): each player's games, the team's startable
    rl = [r for r in ctx["range_list"] if r.key in ("semis", "finals", "cup")]
    if rl:
        for m in managers:
            names = list(src.next_av.rosters.get(m, []))
            il = src.next_av.il.get(m) or {}
            rows = []
            for n in sorted(names, key=lambda n: (n in il, -float(info[n].get("proj_fppg", 0.0)), n)):
                p = {q["name"]: q for q in (blocks.get(m) or {}).get("players", [])}.get(n)
                rows.append({"name": n, "card": (p or {}).get("card") or card_of(n), "il": n in il,
                             "cells": [str(src.player_games(n, r.days)) for r in rl]})
            tm = [src.team(m, r.days) for r in rl]
            teams[m]["playoffs"] = {
                "cols": [{"key": r.key, "label": r.label, "sub": r.sub} for r in rl],
                "rows": rows, "team": [rng(*t.starts) for t in tm],
                "note": ("Games each player will play in those weeks (his injury entry and tags applied), and the "
                         "team's startable games, on rosters and IL slots as they will stand next week: a lot can "
                         "change before then. Weeks 16\u201321 count only for the two teams in each series.")}
    sched = {"weeks": [{k: v for k, v in x.items() if not k.startswith("_")} for x in weeks],
             "open": open_i,
             "note": ("Startable: games the team can actually start: the daily 10, with players in IL slots and "
                      "players who are out left out. A 14-day week (rule 9) is one fantasy week: every team has "
                      "the same 14 days, so the average and the rank compare fairly. Light day: 4 or fewer of your "
                      "players have a game. Overflow day: more than 10 do, so someone sits. Weeks after this one "
                      "count rosters as they will stand with the pending moves."),
             "teams": teams}
    return sched, next_week(ctx, src, week, wk, managers, team_of, today, blocks, sched)


# =============================================================================
# Matchups > Next week (s.2)
# =============================================================================

def next_week(ctx, src, week, wk, managers, team_of, today, blocks, sched) -> Optional[dict]:
    w = week + 1
    if w not in wk:
        return None                                    # after the season's last week: hidden
    days = wk[w]
    long = len(days) > 7
    label = f"Next week {DOT} week {w}" + (f" {DOT} {len(days)} days" if long else "")
    sub = f"{dmd(days[0])} to {dmd(days[-1])}"
    opp = opponents_for(ctx["data"], w, managers)
    recs = ctx["records"]
    stakes = ctx.get("stakes")
    pane_i = next((i for i, x in enumerate(sched["weeks"]) if x["w"] == w), None)
    if any(opp[m] is None for m in managers):
        after = stage_after(w)
        poss = None
        fd = (ctx.get("title_latest") or {}).get("finish_distribution")
        from .ranges import stage_weeks_cfg
        sw = stage_weeks_cfg()
        if fd and sw["semis"][0] <= w <= sw["semis"][1]:
            poss = {"text": "Semifinals: 1 v 4 and 2 v 3, seeded by the regular-season standings. Each team's "
                            "chance of each seed, from the title-odds simulation:",
                    "rows": [{"m": m, "team": team_of.get(m, m),
                              "cells": [f"{float(fd[m][str(k)]):.1f}%" for k in range(1, len(managers) + 1)]}
                             for m in managers],
                    "cols": [f"#{k}" for k in range(1, len(managers) + 1)]}
        return {"week": w, "label": label, "sub": sub, "cards": [],
                "unknown": {"text": f"Opponent set after week {after}.", "poss": poss},
                "note": "Next week's matchups are set by the results still to come."}
    cards, done = [], set()
    for m in managers:
        o = opp[m]
        if m in done:
            continue
        done |= {m, o}
        sides = []
        for s in (m, o):
            t = src.team(s, days)
            inj = []
            av = src.next_av
            il = av.il.get(s) or {}
            by = {p["name"]: p for p in (blocks.get(s) or {}).get("players", [])}
            for n in av.rosters.get(s, []):
                tg = _tags(by[n]) if n in by else ""
                gdays = [d for d in days if av.has_game(n, d)]
                missed = sum(1 for d in gdays if not av.plays(n, d))
                if n in il:
                    inj.append(f"{n} ({tg or 'IL slot'})")
                elif gdays and missed:
                    inj.append(f"{n} ({tg + ' ' + DOT + ' ' if tg else ''}out {missed} of {len(gdays)} games)")
            sides.append({"m": s, "team": team_of.get(s, s), "record": recs.get(s, ""),
                          "starts": rng(*t.starts), "games": rng(*t.games), "light": str(t.light_days),
                          "over": str(t.over_days), "injuries": inj})
        look = None
        if stakes is not None:
            row = (((stakes.get("teams") or {}).get(m) or {}).get("regular_season") or {}).get(str(w)) or \
                  (((stakes.get("teams") or {}).get(m) or {}).get("playoffs") or {}).get(str(w))
            if row is not None:
                n_all = int(row["n_win"]) + int(row["n_loss"]) + int(row.get("n_tie") or 0)
                if n_all <= 0:
                    raise ScheduleError(f"stakes.json has no iterations for {m} in week {w}")
                pa = 100.0 * int(row["n_win"]) / n_all
                mm = float(row["margin_mean"])
                fav = m if mm >= 0 else o
                look = {"win_a": f"{pa:.0f}%", "win_b": f"{100.0 * int(row['n_loss']) / n_all:.0f}%",
                        "margin": f"{team_of.get(fav, fav)} by {abs(mm):.0f}",
                        "src": f"From the title-odds simulation ({int(stakes['num_simulations']):,} seasons, run "
                               f"{_clock(stakes['as_of'])}), with rosters as they stand."}
        cards.append({"id": f"n{w}-{len(cards)}", "route": f"matchups/next/{len(cards)}",
                      "a": sides[0], "b": sides[1], "look": look, "pane": pane_i})
    return {"week": w, "label": label, "sub": sub, "cards": cards, "unknown": None,
            "early": "Early look \u2014 the line is set at Monday's close.",
            "note": (ctx.get("pending_note") or "") + " Startable games: the same numbers as Team \u203a Schedule. "
                    "Light day: 4 or fewer players with a game; overflow day: more than 10."}


def _clock(iso: str) -> str:
    dt = datetime.fromisoformat(iso)
    h = dt.strftime("%I").lstrip("0") or "12"
    return f"{dmd(dt.date())} {h}:{dt.strftime('%M')} {dt.strftime('%p')}"
