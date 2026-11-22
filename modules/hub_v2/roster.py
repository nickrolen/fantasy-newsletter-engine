"""
hub_v2/roster.py -- ENGINE SIDE of the team page's roster table, Detailed
view (4c2; claude/HANDOFF_4C2_TEAMS_MATCHUPS_2026-11-18.md s.1, Nick's notes
claude/HUB_PREVIEW_NOTES_2026-11-14.md s.2). Built inside hub_state.build,
after the Players rows (modules/hub_v2/players.py), whose OVR, POT, Avail %
and age it shows, so every number on a team page and on a player's card is
the same string.

THE ENGINE COMPUTES. Every cell is a string formatted here; every column's
sort is an INTEGER ORDER (row indices, best first; the page reverses it on a
second tap). The page prints the strings and reorders rows; it parses and
computes nothing.

    v2.roster_cols = {                                  shared by the four teams
      "keys":   [col key...]                              every column, in order
      "groups": [{"key", "label", "cols": [col key...]}]   the chip row, in order;
                 the last is "all" (every column)
      "cols":   {col key: {"label", "num" (right-aligned), "tip" (what it means)}}
      "why":    {col key: str}                            a dash's reason, per column
      "notes":  [str]                                     the table's note lines
    }
    v2.teams[m].roster.detail = {
      "rows":   [[str per key] per roster row, in payload rosters order]
      "ovr_d":  [{"t", "dir"} or None per row]            OVR's weekly change
      "trend":  [{"values": [float], "aria"} or None]     the last-10 sparkline
      "trend_max": float                                  one scale per team
      "orders": {col key: [row index...]}                 best first
    }

THE COLUMNS (Nick's s.2 table):
  Value     OVR (and its weekly change), POT, Team value, Title delta, Start %
  Form      FPPG, L14, vs Proj, Trend, Floor, Ceil, Boom %, Bust %, MIN, MIN
            delta (4a3: FORM_MINUTES, the Players row's strings; a cell with
            no value says why: "loading", "3 of 4 games")
  Schedule  Next, Next starts, GL, B2B
  Health    GP, Avail %, Missed, Back
  Keeper    Keep %, Keep rank, Age, Acquired, Since acq.
  Profile   Archetype (only when ratings.archetype.enabled), Share, Best, Worst

RAISES (RosterError) on a missing or inconsistent input. A value that does
not exist for a player (an IL occupant's Team value, Floor with too few
games) is a dash, and the column's "why" says so.
"""

from __future__ import annotations

import math
from datetime import date, timedelta
from typing import Dict, List, Optional

MINUS = "\u2212"
DASH = "\u2014"
MIDDOT = "\u00b7"
# Floor, Ceil, Boom % and Bust % show from this many games played (proposed:
# below 10 a 10th percentile is his worst game and a share moves 10+ points a game)
MIN_GAMES_SPREAD = 10
BOOM, BUST = 1.25, 0.75
TREND_GAMES = 10
# 4a3: MIN and MIN delta, in the Form group after Bust % (the Players row's
# strings and order keys: modules/hub_v2/players.minutes_cells)
FORM_MINUTES = ("min", "mind")

GROUPS = (
    ("value", "Value", ("ovr", "pot", "tv", "tdelta", "start")),
    ("form", "Form", ("fppg", "l14", "vsproj", "trend", "floor", "ceil", "boom", "bust") + FORM_MINUTES),
    ("schedule", "Schedule", ("next", "nstarts", "gl", "b2b")),
    ("health", "Health", ("gp", "avail", "missed", "back")),
    ("keeper", "Keeper", ("keep", "keeprank", "age", "acq", "since")),
    ("profile", "Profile", ("arch", "share", "best", "worst")),
)
COLS = {
    "ovr": ("OVR", True, "4a4's OVR (skill, fixed scale), with its change this week; Prov. while his record is thin."),
    "pot": ("POT", True, "4a's POT: his value as a keeper."),
    "tv": ("Team value", True, "Points he adds to this team's best daily lineups over the next two weeks, "
                               "against the best free agent in his place. A gap of a few points between two "
                               "players is within the noise."),
    "tdelta": ("Title \u0394", True, "Team value at the price of a point: title-odds points."),
    "start": ("Start %", True, "Of his games on this team this season, the share he started."),
    "fppg": ("FPPG", True, "Fantasy points per game this season."),
    "l14": ("L14", True, "Fantasy points per game, last 14 days."),
    "vsproj": ("vs Proj", True, "His FPPG minus Yahoo's projection."),
    "trend": ("Trend", False, "His last 10 games, on one scale for the team."),
    "floor": ("Floor", True, "His 10th-percentile game this season."),
    "ceil": ("Ceil", True, "His 90th-percentile game this season."),
    "boom": ("Boom %", True, "Games at 1.25x his FPPG or more."),
    "bust": ("Bust %", True, "Games at 0.75x his FPPG or less."),
    "min": ("MIN", True, "Minutes per game in his NBA games this season."),
    "mind": ("MIN \u0394", True, "His minutes per game over the last 14 days minus his season: a bigger "
                                "or smaller role."),
    "next": ("Next", True, "Games next week he will play."),
    "nstarts": ("Next starts", True, "Of next week's games, how many fit this team's daily lineup."),
    "gl": ("GL", True, "Games left this week."),
    "b2b": ("B2B", True, "Back-to-backs in the next 3 fantasy weeks."),
    "gp": ("GP", True, "Games played this season."),
    "avail": ("Avail %", True, "4a's availability: his games over his team's, with his history."),
    "missed": ("Missed", True, "His NBA team's games this season that he did not play."),
    "back": ("Back", False, "His expected return, when he is out."),
    "keep": ("Keep %", True, "The chance he is one of this team's keepers."),
    "keeprank": ("Keep rank", False, "His place on the team by keep chance, of the keeper line."),
    "age": ("Age", True, "Age."),
    "acq": ("Acquired", False, "How and when he joined this team."),
    "since": ("Since acq.", True, "FPPG since he joined this team."),
    "arch": ("Archetype", False, "4a4's label: what kind of player he is."),
    "share": ("Share", True, "His share of this team's fantasy points this season."),
    "best": ("Best", False, "His best game this season."),
    "worst": ("Worst", False, "His worst game this season."),
}
# 5d1 s.5: each column's words are infotips.COLUMNS["roster"]'s (one place)
from .infotips import column as _column               # noqa: E402
COLS = {k: (v[0], v[1], _column("roster", k)[1]) for k, v in COLS.items()}
# best first: higher, except these (lower is better, or soonest)
LOW_FIRST = {"bust", "missed", "age", "keeprank", "back", "acq"}


class RosterError(RuntimeError):
    """A roster-table input is missing or inconsistent; named."""


# =============================================================================
# small formatters (engine side)
# =============================================================================

def _md(d: date) -> str:
    return f"{d.month:02d}-{d.day:02d}"


def _signed1(x: float) -> str:
    v = round(float(x), 1)
    return f"+{v:.1f}" if v > 0 else (f"{MINUS}{abs(v):.1f}" if v < 0 else "0.0")


def _signed0(x: float) -> str:
    v = int(round(float(x)))
    return f"+{v:,}" if v > 0 else (f"{MINUS}{abs(v):,}" if v < 0 else "0")


def _pct0(x: float) -> str:
    return f"{100.0 * float(x):.0f}%"


def nearest_rank(vals: List[float], p: float) -> float:
    """The p-th percentile (0..1) by nearest rank: an actual game of his."""
    s = sorted(vals)
    k = max(1, math.ceil(p * len(s)))
    return s[k - 1]


def _games(days: dict, first: date, through: date) -> List[tuple]:
    """[(date, points)] of the days he played (games 1) in [first, through]."""
    out = []
    d = first
    while d <= through:
        v = days.get(d.isoformat())
        if v is None:
            raise RosterError(f"data/player_actuals.json lacks {d.isoformat()}")
        if int(v[1]) == 1:
            out.append((d, float(v[0])))
        d += timedelta(days=1)
    return out


def opponents(nba_schedule: dict) -> Dict[tuple, str]:
    """{(team, date): "vs DEN" | "at DEN"} from the NBA schedule."""
    from datetime import datetime as _dt
    out = {}
    for g in (nba_schedule or {}).get("games", []):
        h, a = g.get("home"), g.get("away")
        if not h or not a:
            continue
        try:
            d = _dt.fromisoformat(str(g.get("date", "")).replace("Z", "+00:00")).date()
        except ValueError:
            continue
        out[(str(h).upper(), d)] = f"vs {str(a).upper()}"
        out[(str(a).upper(), d)] = f"at {str(h).upper()}"
    return out


def back_to_backs(dates: List[date]) -> List[tuple]:
    """Consecutive pairs among sorted dates."""
    ds = sorted(dates)
    return [(a, b) for a, b in zip(ds, ds[1:]) if (b - a).days == 1]


# =============================================================================
# acquisition
# =============================================================================

def acquisitions(base) -> Dict[tuple, dict]:
    """{(manager, name): {"kind": "FA" | "Trade", "day": date}} -- the latest
    successful transaction that moved him to that manager
    (data/transaction_log.jsonl). Names by PlayerIndex at lookup."""
    import json
    from pathlib import Path
    p = Path(base) / "data" / "transaction_log.jsonl"
    out = {}
    if not p.is_file():
        return out
    for line in p.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        if r.get("row") != "transaction" or r.get("status") != "successful":
            continue
        kind = "Trade" if str(r.get("type")) == "trade" else "FA"
        day = date.fromisoformat(str(r["league_day"])[:10])
        for x in r.get("players") or []:
            to = (x.get("to") or {}).get("manager")
            if x.get("action") in ("add", "trade") or (to and kind == "Trade"):
                if not to:
                    continue
                key = (to, x["name"])
                if key not in out or day >= out[key]["day"]:
                    out[key] = {"kind": kind, "day": day}
    return out


def draft_picks(base) -> tuple:
    """({manager: PlayerIndex name -> pick}, season year "'26")."""
    import json
    from pathlib import Path
    from ..data_loader import PlayerIndex
    p = Path(base) / "config" / "DRAFT_PICKS_CURRENT.json"
    if not p.is_file():
        raise RosterError("config/DRAFT_PICKS_CURRENT.json is missing: no Acquired for drafted players")
    blob = json.loads(p.read_text(encoding="utf-8"))
    season = str(blob.get("season") or "")
    if len(season) < 4 or not season[:4].isdigit():
        raise RosterError(f"config/DRAFT_PICKS_CURRENT.json season {season!r} is not YYYY-YY")
    out = {}
    for pk in blob.get("picks", []):
        out.setdefault(pk["manager"], PlayerIndex())[pk["player_name"]] = pk
    return out, "\u2019" + season[2:4]


def acquired(m: str, n: str, acq: dict, picks: dict, yr: str, joined: Optional[str]) -> tuple:
    """(text, sort day): "Kept '26", "R2 '26", "FA 11-09", "Trade 10-30", or
    "Joined 11-09" when only a lineup row shows when he came (no transaction,
    no pick)."""
    from ..data_loader import PlayerIndex
    hit = PlayerIndex({k[1]: v for k, v in acq.items() if k[0] == m}).get(n)
    if hit is not None:
        day = date.fromisoformat(joined) if joined else hit["day"]
        return f"{hit['kind']} {_md(day)}", (day.toordinal(), 0)
    pk = (picks.get(m) or PlayerIndex()).get(n)
    if pk is not None:
        if pk.get("is_keeper"):
            return f"Kept {yr}", (0, 0)
        return f"R{int(pk['round'])} {yr}", (0, int(pk["pick_number"]))
    if joined:
        d = date.fromisoformat(joined)
        return f"Joined {_md(d)}", (d.toordinal(), 0)
    raise RosterError(f"{n} ({m}): no transaction, no draft pick and no join date: Acquired is unknown")


# =============================================================================
# the build
# =============================================================================

def build(base, payload: dict, ctx: dict) -> tuple:
    """(roster_cols, {manager: detail}) for every team (the module docstring)."""
    from .. import player_actuals as pa
    from ..data_loader import PlayerIndex
    from ..ratings import config as rcfg
    from ..schedule_strength import fill_daily_lineup_detail
    v2 = payload["v2"]
    pl = ctx["players_block"]
    prow = {z["name"]: z for z in pl["rows"] if z["kind"] == "rostered"}
    actuals, yesterday = ctx["actuals"], ctx["yesterday"]
    first = date.fromisoformat(actuals["first_day"])
    av, next_av = ctx["av"], ctx["next_av"]
    data = ctx["data"]
    lu = data.lineups
    opp = opponents(data.nba_schedule)
    joined = ctx["joined"]
    acq = acquisitions(base)
    picks, yr = draft_picks(base)
    proj = ctx["proj"]
    over_idx = PlayerIndex({e["player_name"]: e for e in (data.injury_overrides or {}).get("players", [])})
    arch_on = bool(rcfg()["archetype"]["enabled"])
    sched_days = [d for ds in ctx["sched_days"] for d in ds]
    next_days = list(ctx["next_days"])
    tv = ctx["team_value"]
    prices, phase, price_note = ctx["title_prices"]

    # Start % and Share: the daily lineups log, the rows of this season
    lu = lu[lu["date"].astype(str) <= yesterday.isoformat()]
    started_slots = lu["slot"].astype(str).isin(("BN", "IL")) == False      # noqa: E712 (pandas)

    # next week's starters per team per day (the daily fill), next week's rosters
    nstarts = {}
    for m in v2["teams"]:
        cnt = {}
        for d in next_days:
            ps = next_av.players(m, d)
            st = fill_daily_lineup_detail([(p, set(next_av.info[p]["positions"]),
                                            float(next_av.info[p].get("proj_fppg", 0.0))) for p in ps])[0]
            for p in st:
                cnt[p] = cnt.get(p, 0) + 1
        nstarts[m] = cnt

    groups = []
    for gk, glabel, gcols in GROUPS:
        cols = [c for c in gcols if c != "arch" or arch_on]
        groups.append({"key": gk, "label": glabel, "cols": cols})
    allc = [c for g in groups for c in g["cols"]]
    groups.append({"key": "all", "label": "All", "cols": allc})
    out = {}
    for m, tvm in v2["teams"].items():
        rb = payload["rosters"][m]
        players = rb["players"]
        keep_line = int(tvm["roster"]["keep_line"])
        team_lu = lu[lu["manager"] == m]
        team_pts = float(team_lu.loc[started_slots.loc[team_lu.index], "fantasy_points"].fillna(0.0).sum())
        rows, ovr_d, trend, vals = [], [], [], {}
        why = {}
        tmax = 1.0
        for i, p in enumerate(players):
            n = p["name"]
            z = prow.get(n)
            if z is None:
                raise RosterError(f"{n} ({m}) has no Players row: the Value and Keeper columns need it")
            days = pa.player_days(actuals, n)
            games = _games(days, first, yesterday)
            pts = [g[1] for g in games]
            gp = len(games)
            fppg = (sum(pts) / gp) if gp else None
            if p["gp"] != gp:
                raise RosterError(f"{n}: {gp} games here, {p['gp']} on his roster row")
            team = str(p["nba"]).upper()
            tdates = sorted(x for x in av.team_dates.get(team, ()) if first <= x <= yesterday)
            r, v = {}, {}

            # --- Value
            r["ovr"], v["ovr"] = z["ovr"] + (" Prov." if z.get("prov") else ""), z.get("ovr_k")
            ovr_d.append(z.get("ovr_d"))
            r["pot"], v["pot"] = z["pot"], z.get("pot_k")
            t = (tv.get("values") or {}).get(m, {}).get(n)
            if p["in_il"]:
                r["tv"] = r["tdelta"] = DASH
                v["tv"] = v["tdelta"] = None
            elif t is None:
                raise RosterError(f"Team value has no value for {n} ({m})")
            else:
                r["tv"], v["tv"] = _signed0(t["pts"]), round(t["pts"], 6)
                if m in prices:
                    td = t["pts"] * prices[m]
                    r["tdelta"], v["tdelta"] = _signed1(td), round(td, 6)
                else:
                    r["tdelta"], v["tdelta"] = DASH, None
            mine = lu[(lu["manager"] == m) & (lu["player_name"] == n)]
            on_days = {str(x)[:10] for x in mine["date"]}
            played_here = [g for g in games if g[0].isoformat() in on_days]
            st_days = {str(x)[:10] for x in mine.loc[started_slots.loc[mine.index], "date"]}
            started = [g for g in played_here if g[0].isoformat() in st_days]
            if played_here:
                sp = len(started) / len(played_here)
                r["start"], v["start"] = _pct0(sp), sp
            else:
                r["start"], v["start"] = DASH, None

            # --- Form
            r["fppg"], v["fppg"] = p["fppg"], fppg
            l_pts, l_gp = pa.last14(actuals, n, yesterday)
            r["l14"], v["l14"] = p["l14"], (l_pts / l_gp) if l_gp else None
            pj = proj.get(n)
            if pj is None:
                raise RosterError(f"{n} ({m}) has no Yahoo projection (PLAYERLIST)")
            pjv = float(pj.get("projectedFPPG") or 0.0)
            if fppg is None:
                r["vsproj"], v["vsproj"] = DASH, None
            else:
                dv = round(fppg, 1) - round(pjv, 1)
                r["vsproj"], v["vsproj"] = _signed1(dv), dv
            last = pts[-TREND_GAMES:]
            if last:
                trend.append({"values": [round(float(x), 1) for x in last],
                              "aria": f"His last {len(last)} games: " + ", ".join(f"{x:.1f}" for x in last)})
                tmax = max(tmax, max(last))
                r["trend"], v["trend"] = "", sum(last) / len(last)
            else:
                trend.append(None)
                r["trend"], v["trend"] = DASH, None
            # 4a3: the minutes, as the Players row prints them (one string everywhere)
            if any(k not in z for k in ("min", "min_k", "mind", "mind_k")):
                raise RosterError(f"{n} ({m}): his Players row has no minutes (MIN, MIN \u0394): rebuild it "
                                  "with this engine")
            r["min"], v["min"] = z["min"], z["min_k"]
            r["mind"], v["mind"] = z["mind"], z["mind_k"]
            if gp >= MIN_GAMES_SPREAD:
                fl, ce = nearest_rank(pts, 0.10), nearest_rank(pts, 0.90)
                bo = sum(1 for x in pts if x >= BOOM * fppg) / gp
                bu = sum(1 for x in pts if x <= BUST * fppg) / gp
                r["floor"], r["ceil"] = f"{fl:.1f}", f"{ce:.1f}"
                r["boom"], r["bust"] = _pct0(bo), _pct0(bu)
                v.update(floor=fl, ceil=ce, boom=bo, bust=bu)
            else:
                for k in ("floor", "ceil", "boom", "bust"):
                    r[k], v[k] = DASH, None

            # --- Schedule
            ex = tvm["roster"]["extra"][i]
            r["next"], v["next"] = ex["next"], None if ex["next"] == DASH else int(ex["next"])
            if p["in_il"]:
                r["nstarts"], v["nstarts"] = DASH, None
            else:
                k = nstarts[m].get(n, 0)
                r["nstarts"], v["nstarts"] = str(k), k
            r["gl"], v["gl"] = p["gl"], None if p["gl"] == DASH else int(p["gl"])
            if p["in_il"]:
                r["b2b"], v["b2b"] = DASH, None
            else:
                b2 = len(back_to_backs([d for d in av.team_dates.get(team, ()) if d in set(sched_days)]))
                r["b2b"], v["b2b"] = str(b2), b2

            # --- Health
            r["gp"], v["gp"] = str(gp), gp
            r["avail"], v["avail"] = z["avail"], (None if z["avail"] == DASH else
                                                   int(str(z["avail"]).rstrip("%")))
            played = {g[0] for g in games}
            missed = sum(1 for d in tdates if d not in played)
            r["missed"], v["missed"] = str(missed), missed
            back = [c["text"] for c in p["tags"] if str(c["text"]).startswith("back ")]
            e = over_idx.get(n)
            if back:
                r["back"] = back[0].replace("back ", "")
            elif e is not None and e.get("return_date") and not p["status"]["source"] == "healthy":
                from ..absence import parse_return_date
                r["back"] = _md(parse_return_date(e["return_date"], n))
            else:
                r["back"] = DASH
            v["back"] = None
            if r["back"] != DASH:
                bd = parse_back(r["back"], ctx["today"])
                v["back"] = bd.toordinal()

            # --- Keeper
            r["keep"] = p["keep"]
            v["keep"] = None if not str(p["keep"]).endswith("%") else float(str(p["keep"]).rstrip("%"))
            kr = int(tvm["roster"]["keep_rank"][i].lstrip("#"))
            r["keeprank"], v["keeprank"] = (f"#{kr} of {keep_line}" if kr <= keep_line else f"#{kr}"), kr
            r["age"] = z["age"]
            v["age"] = None if z["age"] == DASH else float(z["age"])
            j = joined.get((m, n))
            r["acq"], v["acq"] = acquired(m, n, acq, picks, yr, j)
            since = [g for g in games if j is None or g[0] >= date.fromisoformat(j)]
            if since:
                sv = sum(g[1] for g in since) / len(since)
                r["since"], v["since"] = f"{sv:.1f}", sv
            else:
                r["since"], v["since"] = DASH, None

            # --- Profile
            if arch_on:
                a = (z.get("arch") or {}).get("label")
                r["arch"], v["arch"] = (a or DASH), a
            mine_pts = float(mine.loc[started_slots.loc[mine.index], "fantasy_points"].fillna(0.0).sum())
            if team_pts > 0:
                sh = mine_pts / team_pts
                r["share"], v["share"] = f"{100.0 * sh:.1f}%", sh
            else:
                r["share"], v["share"] = DASH, None
            if games:
                best = max(games, key=lambda g: (g[1], -g[0].toordinal()))
                worst = min(games, key=lambda g: (g[1], g[0].toordinal()))
                for key, g in (("best", best), ("worst", worst)):
                    o = opp.get((team, g[0]))
                    r[key] = f"{g[1]:.0f} {o}" if o else f"{g[1]:.0f} on {_md(g[0])}"
                    v[key] = g[1]
            else:
                r["best"] = r["worst"] = DASH
                v["best"] = v["worst"] = None
            rows.append(r)
            for k, x in v.items():
                vals.setdefault(k, []).append(x)

        # orders: best first; a missing value last; ties by name
        names = [p["name"] for p in players]
        orders = {}
        for k, xs in vals.items():
            have = [i for i, x in enumerate(xs) if x is not None]
            miss = [i for i, x in enumerate(xs) if x is None]
            if k == "arch":
                have.sort(key=lambda i: (str(xs[i]), names[i]))
            elif k == "acq":
                have.sort(key=lambda i: (xs[i], names[i]))
            elif k in LOW_FIRST:
                have.sort(key=lambda i: (xs[i], names[i]))
            else:
                have.sort(key=lambda i: (-xs[i], names[i]))
            orders[k] = have + miss
        missing = [k for k in allc if any(k not in r for r in rows)]
        if missing:
            raise RosterError(f"{m}: no value for column(s) {missing}")
        out[m] = {"rows": [[r[k] for k in allc] for r in rows], "ovr_d": ovr_d, "trend": trend,
                  "trend_max": round(float(tmax), 1), "orders": {k: orders[k] for k in allc}}
    why = {"tv": "IL slot: no Team value until he is active",
           "tdelta": ("IL slot, or no title-odds stakes on this run" + (f" ({price_note})" if price_note else "")),
           "start": "No games on this team yet",
           "floor": f"Fewer than {MIN_GAMES_SPREAD} games", "ceil": f"Fewer than {MIN_GAMES_SPREAD} games",
           "boom": f"Fewer than {MIN_GAMES_SPREAD} games", "bust": f"Fewer than {MIN_GAMES_SPREAD} games",
           "nstarts": "IL slot", "b2b": "IL slot", "back": "Not out", "since": "No games since he joined",
           "trend": "No games yet",
           "min": "No games yet; \"loading\" until the nightly has the minutes of every game he played",
           "mind": ("the cell says why: too few games in the last 14 days, \"no earlier games\" (all his games "
                    "are in them), or \"loading\"")}
    wk = tv.get("weeks") or []
    notes = [f"Team value and Title \u0394: weeks {' and '.join(str(w) for w in wk)}, each roster as it "
             f"stands, against the best free agent in his place ({tv.get('sims')} simulations)."
             if wk else "Team value: no window is left this season.",
             ("Title \u0394 prices a point at this week's stakes: the regular-season title through week 15, "
              "the playoff title after." if prices else f"Title \u0394: no stakes on this run ({price_note})."),
             f"Floor, Ceil, Boom % and Bust % show from {MIN_GAMES_SPREAD} games."]
    shared = {"keys": allc, "groups": groups,
              "cols": {c: {"label": COLS[c][0], "num": COLS[c][1], "tip": COLS[c][2]} for c in allc},
              "why": {k: w for k, w in why.items() if k in allc}, "notes": notes}
    return shared, out


def parse_back(text: str, today: date) -> date:
    """The date in a "01-25" back text, the next such date on or
    after today (engine side only: the order key)."""
    mmdd = text.split(" ")[-1]
    mo, dd = int(mmdd[:2]), int(mmdd[3:5])
    d = date(today.year, mo, dd)
    if d < today - timedelta(days=180):
        d = date(today.year + 1, mo, dd)
    return d
