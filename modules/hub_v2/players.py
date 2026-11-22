"""
hub_v2/players.py -- ENGINE SIDE of the new hub's Players tab, its Compare
screen and the ratings on the new player card (4c1;
claude/HANDOFF_4C1_PLAYERS_2026-11-18.md s.1-4). Built inside hub_state.build
(after hub_cards.annotate, whose card keys it needs) from the run's own inputs.

THE ENGINE COMPUTES. Every number the page shows is a string formatted here;
every sort and every Compare winner is an INTEGER ORDER KEY made here. The
page never parses a display string and never does arithmetic: it sorts by the
orders and, in Compare, bolds the side whose integer key is larger.

WHO (s.2): every player the hub can show a card for -- payload["cards"]
["players"] (hub_cards.annotate): the rostered players, plus every non-rostered
player the hub names (the free agents and stash lists, the moves feed, the
trade block, advice). A run whose cards failed lists the rostered players and
the free-agent and stash rows, with no card keys.

RATINGS (s.1): ratings.for_today on the same run's inputs (hub_state.build
computes it, failing softly: ctx["ratings"]["error"]). Every player gets
OVR, POT, the weekly changes (only with a published line at least 7 days
back: no marker otherwise, never a zero) and the grade tiles (4a4 s.4:
nine, config ratings.grades.order). 5b
(Nick, 11-20): FREE AGENTS TOO (hub_state.ratings_fa_step:
ratings.rate_free_agents, rated against today's rostered players, which
they never move; rt["fa_error"] when that failed). A player still without
an OVR (no NBA team, no lines, a failed rating) sorts last both ways; equal
OVRs sort by the composite underneath (s.1b).

THE ARCHETYPE (4a4 s.3, archetypes v2) appears only when
ratings.archetype.enabled is true (off until Nick approves the real table):
then each row carries "arch" {label, kw (the tags, joined), st (the
standouts), preview}. Off, the same dict rides as "arch_off", which no page
reads and publish never prints; archetype_preview() (build_hub.py --v2
--archetype-preview, a PREVIEW build only) moves it to "arch", marked.

    v2["players"] = {
      "rows": [{key, name, q (folded search key), kind ("rostered"|"fa"), m,
                chip {text, slot}, team, meta, pos, nba, age, ovr, ovr_d, pot,
                pot_d, dur, dur_k, dur_d, prov (4a4: OVR provisional), fppg, l14, next, keep, keep_rank, avail, g3,
                chips [{text, kind}], healthy, f {pos, nba, age, h, k},
                cmp [{t, k}] (CMP_ROWS order), grades [8 tiles] or None,
                ring {hero, cmp} or None, ini, team_gp, gp, total, total_rank,
                min, min_k, mind, mind_k, min_g {iso: minutes} (4a3)}],
      "orders": {col: {"d": [i...], "a": [i...]}}   missing values last both ways
      "default": "ovr",
      "filters": {"pos": [..], "nba": [..], "age": [{key, label}]},
      "risers": [{i, ovr, d, reason}] or None (None: no line a week back),
      "count": "99 players", "who": the list's description,
      "cmp_rows": [{key, label}], "grade_labels": [..]}
    v2["ratings"] = {"as_of", "error", "change_note", "archetype"}

MINUTES (4a3; minutes_cells): MIN is his minutes per game over the games he
played this season; MIN delta is his minutes per game over the last 14 days
minus MIN (one decimal each, as printed), shown from MIN_DELTA_GAMES games
in the last 14 days. Until the nightly's backfill gives every game he played
its minutes, both say "loading"; below the minimum MIN delta says "3 games:
of 4 games" (the reason, short: 11-19 review); with every game of his in the last 14 days it says "no
earlier games" (the difference would be 0 by construction). Never a made-up
0. The roster table (roster.py), the card (card.py) and Compare all print
these strings.
"""

from __future__ import annotations

import math
import unicodedata
from datetime import date, timedelta
from typing import Dict, List, Optional

MINUS = "\u2212"
DASH = "\u2014"
UP, DOWN = "\u25b2", "\u25bc"
BASE_POS = ("PG", "SG", "SF", "PF", "C")
AGE_BANDS = (("u25", "24 and under", None, 24), ("25-29", "25\u201329", 25, 29), ("30+", "30 and over", 30, None))
RISERS_MAX = 5
# Compare's rows, in order (s.4): the grade tiles (config order, 4a4: nine) follow these
CMP_ROWS = (("pot", "POT"), ("dur", "DUR"), ("fppg", "FPPG"), ("l14", "L14"), ("min", "MIN"), ("avail", "Avail %"),
            ("g3", "Games, next 3 wks"), ("keep", "Keep %"), ("age", "Age"))
# 4a3: MIN delta shows from this many games in the last 14 days; the card's
# last-5 table reads his last MIN_LAST games' minutes
MIN_DELTA_GAMES = 4
MIN_LAST = 10
MIN_LOADING = "loading"
from ..ratings import CATEGORY_GRADES                     # noqa: E402 -- 4a4: the seven, one source
# the rings' circumferences (bundle.css .lh-ring: r 34 in an 80 box; Compare: r 22 in a 56 box)
RING_HERO_R, RING_CMP_R = 34.0, 22.0
FOLD = {"\u00f8": "o", "\u0111": "d", "\u0142": "l", "\u00df": "ss", "\u00e6": "ae", "\u0153": "oe",
        "\u0131": "i", "\u00f0": "d", "\u00fe": "th"}


class PlayersError(RuntimeError):
    """An input the Players tab needs is missing or inconsistent; named."""


# =============================================================================
# small formatters (engine side)
# =============================================================================

def fold(text: str) -> str:
    """Lower case, accents folded ("Joki\u0107" -> "jokic"): the search key's
    rule. The page folds what is typed with the same rule (NFKD, combining
    marks dropped, the same few letters mapped) and only matches strings."""
    s = unicodedata.normalize("NFKD", str(text))
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    return "".join(FOLD.get(c, c) for c in s)


def ordinal(n: int) -> str:
    n = int(n)
    suf = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suf}"


def change(d: Optional[int]) -> Optional[dict]:
    """A weekly change as {"t", "dir"}; None (no marker) when there is none."""
    if d is None:
        return None
    d = int(d)
    if d > 0:
        return {"t": f"{UP}{d}", "dir": "up", "long": f"{UP} {d} this week"}
    if d < 0:
        return {"t": f"{DOWN}{abs(d)}", "dir": "down", "long": f"{DOWN} {abs(d)} this week"}
    return {"t": "\u2013", "dir": "flat", "long": "No change this week"}


def ring(ovr: int, r: float) -> str:
    """The OVR ring's stroke-dasharray: the arc is OVR/99 of the circle."""
    c = 2 * math.pi * r
    return f"{c * ovr / 99.0:.1f} {c:.1f}"


def initials(name: str) -> str:
    """Two letters for a missing headshot: the first letters of his first and
    last words (a suffix such as Jr. or III skipped)."""
    words = [w for w in str(name).replace(".", " ").split() if w]
    words = [w for w in words if w.upper() not in ("JR", "SR", "II", "III", "IV", "V")] or words
    if not words:
        return "?"
    return (words[0][0] + (words[-1][0] if len(words) > 1 else "")).upper()


def grade_class(letter: Optional[str]) -> str:
    return {"A": "lh-g-a", "B": "lh-g-b", "C": "lh-g-c", "D": "lh-g-d"}.get((letter or "?")[0], "")


def age_band(age) -> str:
    if age is None:
        return "unknown"
    for key, _lab, lo, hi in AGE_BANDS:
        if (lo is None or age >= lo) and (hi is None or age <= hi):
            return key
    return "unknown"


def letter_rank(letter: Optional[str], bands) -> Optional[int]:
    """A letter's order key: its band's place from the bottom (D = 0)."""
    if letter is None:
        return None
    names = [b[1] for b in bands]
    return len(names) - 1 - names.index(letter)


def _int_or_none(text: str, scale: int = 1) -> Optional[int]:
    """An order key from a number this module formatted: the displayed value
    as an integer (x10 for one decimal), so a bold winner never contradicts
    what is printed. Engine side only."""
    if text in (None, DASH, ""):
        return None
    return int(round(float(str(text).replace("%", "").replace(",", "")) * scale))


def _signed1(x: float) -> str:
    return f"+{x:.1f}" if x > 0 else (f"{MINUS}{abs(x):.1f}" if x < 0 else "0.0")


def minutes_cells(actuals: dict, name: str, first: date, through: date, l14_first: date,
                  played: List[str]) -> dict:
    """4a3: {"min", "min_k", "mind", "mind_k", "min_g"} for one player (the
    module docstring's MINUTES). min_k and mind_k are the printed values x10
    as integers (None: no value, sorts last and wins nothing). played: the
    days he played, in order (his card lines); min_g holds the minutes of the
    last MIN_LAST of them that have minutes stored, as strings, so the card's
    last 5 shows a game's minutes as soon as its day has them."""
    from .. import player_actuals as pa
    out = {"min": DASH, "min_k": None, "mind": DASH, "mind_k": None,
           "min_g": {i: str(m) for i, m in pa.minutes_on(actuals, name, played[-MIN_LAST:]).items()}}
    st = pa.minutes_games(actuals, name, first, through)
    if st["status"] == "loading":
        return dict(out, min=MIN_LOADING, mind=MIN_LOADING)
    if st["status"] != "ok" or not st["games"]:
        return out                                     # no games, or no lines: a dash, as FPPG is
    mins = [m for _i, m in st["games"]]
    mpg = sum(mins) / len(mins)
    out["min"] = f"{mpg:.1f}"
    out["min_k"] = _int_or_none(out["min"], 10)
    l14 = [m for i, m in st["games"] if i >= l14_first.isoformat()]
    k = len(l14)
    if k < MIN_DELTA_GAMES:
        out["mind"] = f"{k} of {MIN_DELTA_GAMES} games"
    elif k == len(mins):
        out["mind"] = "no earlier games"
    else:
        dl = round(round(sum(l14) / k, 1) - round(mpg, 1), 1)
        out["mind"] = _signed1(dl)
        out["mind_k"] = int(round(dl * 10))
    return out


# =============================================================================
# the risers' reason (s.2): which of OVR's terms moved most
# =============================================================================

def _pcts(vals: Dict[str, float]) -> Dict[str, float]:
    from ..ratings import percentiles
    return percentiles(vals)


SKILL_TERMS = ("estimate", "fppg", "games")


def riser_reason(name: str, now: Dict[str, list], then: Dict[str, list], pool=None, kind: str = "4a") -> str:
    """The one-line reason for an OVR rise (proposed rule, 4c1): OVR is
    availability x games left x (level - replacement), ranked against the
    league. For each of the three terms, his percentile among the players in
    both lines, now and a week back; the reason is the term whose percentile
    rose most. None rose (he held while others fell): says so.
        level            "scoring level 44.0 \u2192 46.2"
        availability     "playing more: 82% \u2192 90% of games"
        games_remaining  "more games left than most: 62"
    now, then: {player: [level, availability, games remaining]}. pool (5b):
    the players to rank among (default: everyone in both lines).
    kind "skill" (4a4: the skill OVR, history line version 2): the terms are
    [estimate, FPPG this season, games this season]:
        estimate  "skill estimate 40.0 \u2192 43.0 FPPG"
        fppg      "this season 35.2 \u2192 38.0 FPPG"
        games     "more games on his record: 12 \u2192 15"
    """
    both = sorted(set(now) & set(then) & (set(pool) if pool is not None else set(now)))
    if name not in both:
        raise PlayersError(f"riser {name}: not in both history lines")
    names = SKILL_TERMS if kind == "skill" else ("level", "availability", "games_remaining")
    gains = {}
    for j, term in enumerate(names):
        pn = _pcts({n: float(now[n][j]) for n in both})
        pt = _pcts({n: float(then[n][j]) for n in both})
        gains[term] = pn[name] - pt[name]
    term = max(names, key=lambda t: (gains[t], -names.index(t)))
    if gains[term] <= 0:
        return "held steady while the league around him slipped"
    a, b = then[name], now[name]
    if kind == "skill":
        if term == "estimate":
            return f"skill estimate {float(a[0]):.1f} \u2192 {float(b[0]):.1f} FPPG"
        if term == "fppg":
            return f"this season {float(a[1]):.1f} \u2192 {float(b[1]):.1f} FPPG"
        return f"more games on his record: {int(a[2])} \u2192 {int(b[2])}"
    if term == "level":
        return f"scoring level {float(a[0]):.1f} \u2192 {float(b[0]):.1f}"
    if term == "availability":
        return f"playing more: {float(a[1]) * 100:.0f}% \u2192 {float(b[1]) * 100:.0f}% of games"
    return f"more games left than most: {int(b[2])}"


# =============================================================================
# the build
# =============================================================================

def fa_team(name: str, info: dict, proj, ref=None) -> Optional[str]:
    """A free agent's NBA team: the player info's, else PLAYERLIST's, else
    (5c, 5b decision 14) basketball-reference's THIS season's list (ref:
    reference_teams()) -- the rule the Players rows, Next and the free
    agents' ratings share. The reference is only a fallback: it never
    overrides a current source (it is fetched by hand and can be weeks old;
    a player traded since would carry his old team)."""
    t = (info.get(name) or {}).get("nba_team")
    if t is None:
        prow = proj.get(name)
        t = None if prow is None else str(prow.get("player_nba_team") or "") or None
    if t is None and ref:
        t = ref.get(name) or None
    return t


def reference_teams(base) -> dict:
    """5c: {name: schedule team code} from data/NBA_PLAYER_REFERENCE.json's
    this-season list (basketball-reference; a PlayerIndex, so names compare
    as everywhere else), only players with one team this season. Last
    season's list is never used (an off-season move makes it wrong). No
    cache file: {} -- the fallback reaches nobody and those free agents stay
    "no NBA team on record", as before; nothing is made up."""
    from ..data_loader import PlayerIndex
    from .. import nba_reference
    try:
        cache = nba_reference.load_cache(base)
    except nba_reference.ReferenceMissing:
        return PlayerIndex({})
    players = ((cache.get("seasons") or {}).get("this_season") or {}).get("players") or {}
    return PlayerIndex({n: str(t).upper() for n, t in players.items() if t})


def _nba_games(base) -> list:
    from ..season_performers import load_nba_schedule
    return load_nba_schedule(base)


def schedule_opponents(games: list) -> dict:
    """{NBA team: {YYYY-MM-DD: its opponent that day, "@XXX" away, "XXX" at
    home}} from the stored NBA schedule: the league log's own notation. A
    team with two games on one day (never seen) RAISES: no guess."""
    out: dict = {}
    for g in games:
        iso = str(g["date"])[:10]
        for team, opp in ((g["home"], g["away"]), (g["away"], "@" + g["home"])):
            day = out.setdefault(team, {})
            if iso in day:
                raise PlayersError(f"{team} has two games on {iso} in the NBA schedule")
            day[iso] = opp
    return out


def override_window(av, first) -> list:
    """The days an INJURY_OVERRIDES entry is read over for a free agent's
    status: from `first` (today) to the end of next fantasy week, as the
    free agents' table reads it (hub_state.free_agent_status's window)."""
    from ..hub_state import HubInputError
    if not hasattr(av, "week_of") or not hasattr(av, "override_covers"):    # a stand-in (the synthetic league)
        return []
    try:
        w = av.week_of(first)
    except HubInputError:                            # outside the season's weeks: no window
        return []
    last = av.weeks.get(w + 1, av.weeks[w])[1]
    return [first + timedelta(days=i) for i in range((last - first).days + 1)]


def universe(payload: dict) -> List[dict]:
    """The Players tab's players (_universe): public for the free agents'
    ratings (hub_state.ratings_fa_step), which rate exactly these."""
    return _universe(payload)


def _universe(payload: dict) -> List[dict]:
    """[{key, name, kind, m, status}]: payload cards' players, or (the cards
    failed) the rostered players and the listed free agents, keyless."""
    reg = (payload.get("cards") or {}).get("players")
    if reg:
        return [{"key": k, "name": v["name"], "kind": "rostered" if v["kind"] == "rostered" else "fa",
                 "m": v["manager"] if v["kind"] == "rostered" else "", "status": list(v["status"])}
                for k, v in reg.items()]
    out, seen = [], set()
    for m, rb in payload["rosters"].items():
        for p in rb["players"]:
            seen.add(p["name"])
            out.append({"key": None, "name": p["name"], "kind": "rostered", "m": m,
                        "status": [{"text": f"{rb['team']} \u00b7 {m}", "kind": "own"}] + list(p.get("tags") or [])})
    for r in payload["free_agents"]["rows"] + payload["stash"]["rows"]:
        if r["name"] not in seen:
            seen.add(r["name"])
            out.append({"key": None, "name": r["name"], "kind": "fa", "m": "",
                        "status": [{"text": "Free agent", "kind": "fa"}] + list(r.get("tags") or [])})
    return out


def build(base, payload: dict, ctx: dict) -> tuple:
    """(v2["players"], v2["ratings"]) for this payload. RAISES PlayersError
    (or the readers' own errors) on an inconsistent input."""
    from .. import player_actuals as pa
    from ..ratings import config as rcfg, letter as _letter
    from ..hub_state import free_agent_tags, HubInputError
    v2 = payload["v2"]
    teams_v2 = v2["teams"]
    rt = ctx["ratings"]
    res = rt.get("result")
    rerr = rt.get("error")
    cfg = rcfg()
    bands = cfg["grade_bands"]
    labels = cfg["grades"]["labels"]
    order = cfg["grades"]["order"]
    yesterday = ctx["yesterday"]
    actuals = ctx["actuals"]
    av = ctx["av"]
    info = ctx["info"]
    next_days = list(ctx["next_days"])
    proj = ctx["proj"]
    kw_age = {(r["manager"], r["player_name"]): r.get("age") for r in ctx["keeper_watch"]["players"]}

    uni = _universe(payload)
    names = [u["name"] for u in uni]
    rostered_names = [u["name"] for u in uni if u["kind"] == "rostered"]
    fa_names = [u["name"] for u in uni if u["kind"] == "fa"]
    if "no_id" in ctx:                                   # tests: the synthetic league has no PLAYERLIST
        no_id = list(ctx["no_id"])
    else:
        _ids, no_id = pa.extra_ids(base, fa_names) if fa_names else ({}, [])
    cl = pa.card_lines(actuals, names, yesterday, required=rostered_names, no_id=no_id)
    first = date.fromisoformat(cl["first_day"])
    l14_first = max(first, yesterday - timedelta(days=pa.L14_DAYS - 1))

    # the roster rows (by name), and the free agents' availability (Next)
    row_of, idx_of = {}, {}
    for m, rb in payload["rosters"].items():
        for i, p in enumerate(rb["players"]):
            row_of[p["name"]] = (m, p)
            idx_of[p["name"]] = i
    ref = ctx["ref_teams"] if "ref_teams" in ctx else reference_teams(base)
    fa_team_of = {n: fa_team(n, info, proj, ref) for n in fa_names}
    fa_ok = [n for n in fa_names if fa_team_of[n] and fa_team_of[n] in av.team_dates and n in info]
    # 5c: a free agent whose team is the reference's fallback is in neither
    # the player info nor PLAYERLIST, so the tag record (PLAYERLIST's free
    # agents) may have no tag for him. With a tag, Next counts his games with
    # that team; without one his Next stays a dash -- an untagged free agent
    # is never read as healthy, and he must not make the whole build fail
    # (free_agent_tags raises for the rest, as before).
    # 5d1 s.3 (5c decision 4): such a free agent picks up his INJURY_OVERRIDES
    # entry: "O - back MM-DD" on his row and card, his games counted with it
    # (Availability's own override rule), and never "healthy". The entry is
    # his status: he has no Yahoo tag to read.
    fa_info, fa_untagged, fa_override = {}, set(), {}
    window = override_window(av, yesterday + timedelta(days=1))
    for n in fa_names:
        t = fa_team_of[n]
        if n in fa_ok or (info.get(n) or {}).get("nba_team") is not None:
            continue
        e = av.override_covers(n, window) if window else None
        if e is not None and t and t in av.team_dates:
            fa_override[n] = e
        elif "fa_av" not in ctx:
            try:
                free_agent_tags(ctx["tag_row"], [n])
            except HubInputError:
                fa_untagged.add(n)
                continue
        if not t or t not in av.team_dates:
            continue
        fa_info[n] = {"nba_team": t, "positions": set(), "proj_fppg": None}
        fa_ok.append(n)
    if fa_override:
        from ..hub_state import override_chip
        reg = (payload.get("cards") or {}).get("players") or {}
        for u in uni:
            if u["name"] in fa_override:
                chip = override_chip(fa_override[u["name"]], av)
                u["status"] = [c for c in u["status"] if c.get("kind") != "out"] + [chip]
                if u.get("key") in reg:                  # the card shows the same status as the row
                    reg[u["key"]]["status"] = [c for c in reg[u["key"]]["status"] if c.get("kind") != "out"] + [dict(chip)]
    if not fa_ok:
        fa_av = None
    elif "fa_av" in ctx:                                 # tests: a stand-in Availability
        fa_av = ctx["fa_av"](fa_ok)
    else:
        fa_av = av.for_free_agents(fa_ok, free_agent_tags(ctx["tag_row"], [n for n in fa_ok if n not in fa_override]),
                                   extra_info=fa_info)

    ctx["_fa_av"], ctx["_fa_ok"] = fa_av, list(fa_ok)     # 5d2: the Players groups' Schedule columns
    sched_opp = ctx["sched_opp"] if "sched_opp" in ctx else schedule_opponents(_nba_games(base))

    # the ratings, and last week's line
    rp = (res or {}).get("players") or {}
    fp = (res or {}).get("free_agents") or {}                 # 5b
    fa_err = rt.get("fa_error")
    prev_line = rt.get("previous_line")
    from ..ratings import history_values                      # 4a4: only a line of the same version
    prev_pot = history_values(prev_line, "pot")
    prev_dur = history_values(prev_line, "dur")
    horizon = (res or {}).get("schedule_horizon")

    # the numbers, per player (engine side)
    nums = {}
    for u in uni:
        n = u["name"]
        lines = cl["lines"].get(n)
        if lines is None:
            nums[n] = {"gp": 0, "pts": 0.0, "l14_pts": 0.0, "l14_gp": 0, "covered": False,
                       "note": cl["notes"].get(n) or pa.NOTE_NEVER}
            continue
        pts = sum(float(x[1]) for x in lines)
        gp = sum(int(x[2]) for x in lines)
        l14 = [x for x in lines if x[0] >= l14_first.isoformat()]
        nums[n] = {"gp": gp, "pts": round(pts, 2), "l14_pts": round(sum(float(x[1]) for x in l14), 2),
                   "l14_gp": sum(int(x[2]) for x in l14), "covered": True, "note": ""}
    # the total's rank among the rostered players
    r_total = sorted((nums[n]["pts"] for n in rostered_names), reverse=True)

    rows = []
    for u in uni:
        n, m = u["name"], u["m"]
        x = nums[n]
        fppg = pa.fppg_text(x["pts"], x["gp"])
        l14 = pa.fppg_text(x["l14_pts"], x["l14_gp"])
        if u["kind"] == "rostered":
            if n not in row_of or row_of[n][0] != m:
                raise PlayersError(f"{n} ({m}) is rostered in the card list but not on {m}'s roster rows")
            _m, p = row_of[n]
            if p["fppg"] != fppg or p["l14"] != l14:
                raise PlayersError(f"{n}: FPPG {fppg} / L14 {l14} here, {p['fppg']} / {p['l14']} on his roster row")
            i = idx_of[n]
            tv = teams_v2[m]
            pos, nba = p["pos"], p["nba"]
            age = kw_age.get((m, n))
            nxt = tv["roster"]["extra"][i]["next"]
            keep, keep_rank = p["keep"], tv["roster"]["keep_rank"][i]
            chip = {"text": tv["mono"], "slot": tv["slot"], "team": tv["team"]}
        else:
            prow = proj.get(n) or {}
            pos = str(prow.get("player_position(s)") or "")
            nba = fa_team_of.get(n) or ""
            a = prow.get("age")
            age = None if a is None or (isinstance(a, float) and math.isnan(a)) else a
            nxt = (str(len(fa_av.playable(n, next_days))) if fa_av is not None and n in fa_ok and next_days else DASH)
            keep, keep_rank = DASH, ""
            chip = {"text": "FA", "slot": "", "team": "Free agent"}
        if age is not None:
            age = int(age) if float(age).is_integer() else age
        r = rp.get(n) if u["kind"] == "rostered" else fp.get(n)
        chips = [c for c in u["status"] if c.get("kind") in ("out", "q", "il")]
        # 5c: a free agent the tag record has no tag for (the fallback team's,
        # outside PLAYERLIST) is never read as healthy ("Healthy only" leaves him out)
        healthy = not chips and n not in fa_untagged
        positions = [s for s in pos.split(",") if s in BASE_POS]
        # team games through yesterday (the card's "games of team games")
        team = nba if u["kind"] == "rostered" else fa_team_of.get(n)
        tdates = av.team_dates.get(team) if team else None
        team_gp = (sum(1 for d in tdates if first <= (d if isinstance(d, date) else date.fromisoformat(str(d)[:10]))
                       <= yesterday) if tdates is not None else None)
        # the schedule's games, next 3 fantasy weeks
        if r is not None and r["grades"].get("schedule", {}).get("value") is not None:
            g3 = str(int(r["grades"]["schedule"]["value"]))
        elif horizon and tdates is not None:
            g3 = str(sum(1 for d in tdates if horizon[0] <= (d.isoformat() if isinstance(d, date) else str(d)[:10])
                         <= horizon[1]))
        else:
            g3 = DASH
        row = {"key": u["key"], "name": n, "kind": u["kind"], "m": m, "chip": chip,
               "pos": pos, "nba": nba or DASH, "meta": f"{pos or DASH} \u00b7 {nba or DASH}",
               "age": DASH if age is None else str(age), "fppg": fppg, "l14": l14, "next": nxt,
               "keep": keep, "keep_rank": keep_rank, "g3": g3, "chips": [dict(c) for c in chips],
               "healthy": healthy, "ini": initials(n), "gp": str(x["gp"]),
               "team_gp": DASH if team_gp is None else str(team_gp),
               "total": f"{x['pts']:,.0f}" if x["covered"] else DASH,
               "season_note": "" if x["covered"] else x["note"],
               "l14_ctx": "", "l14_dir": "",
               "f": {"pos": positions, "nba": nba or "", "age": age_band(age),
                     "h": "1" if healthy else "0", "k": "r" if u["kind"] == "rostered" else "fa"}}
        if x["gp"] and x["l14_gp"]:
            dl = round(x["l14_pts"] / x["l14_gp"], 1) - round(x["pts"] / x["gp"], 1)
            row["l14_ctx"] = (f"{UP} {abs(dl):.1f} vs season" if dl > 0.05 else
                              f"{DOWN} {abs(dl):.1f} vs season" if dl < -0.05 else "Level with his season")
            row["l14_dir"] = "up" if dl > 0.05 else "down" if dl < -0.05 else ""
        # 4a3: the minutes (MIN, MIN delta, Compare's MIN, the card's last 5)
        played = [ln[0] for ln in (cl["lines"].get(n) or []) if int(ln[2]) == 1]
        row.update(minutes_cells(actuals, n, first, yesterday, l14_first, played))
        # 5d1 s.3: the card's last-5 Opp from the NBA schedule when the league log has no
        # line that day (free agents, games before he joined a roster): his team's opponent
        tm = sched_opp.get(team or "") or {}
        row["opp_g"] = {i: tm[i] for i in played[-MIN_LAST:] if i in tm}
        # the total's rank among the rostered players
        if x["covered"] and r_total:
            rk = 1 + sum(1 for t in r_total if t > x["pts"])
            row["total_rank"] = (f"#{rk} of {len(r_total)} rostered" if u["kind"] == "rostered" else
                                 f"would be #{rk} of {len(r_total)} rostered")
        else:
            row["total_rank"] = ""
        row["q"] = " ".join(fold(s) for s in (n, nba or "", chip["team"] if m else "free agent", m) if s)
        # ratings
        if r is not None and r["ovr"] is not None:
            row.update(ovr=str(r["ovr"]), ovr_k=int(r["ovr"]), ovr_d=change(r["ovr_change"]),
                       ring={"hero": ring(r["ovr"], RING_HERO_R), "cmp": ring(r["ovr"], RING_CMP_R)},
                       ovr_note="", prov=bool(r.get("ovr_provisional")))   # 4a4: a thin record
        else:
            why = ("ratings failed on this run" if rerr else
                   f"free agents' ratings failed on this run" if (u["kind"] == "fa" and fa_err) else
                   (r or {}).get("ovr_reason") or "not rated")
            row.update(ovr=DASH, ovr_k=None, ovr_d=None, ring=None, ovr_note=why, prov=False)
        if r is not None and r["pot"] is not None:
            pd_ = None
            if prev_pot is not None and n in prev_pot:
                pd_ = int(r["pot"]) - int(prev_pot[n])
            row.update(pot=str(r["pot"]), pot_k=int(r["pot"]), pot_d=change(pd_))
        else:
            row.update(pot=DASH, pot_k=None, pot_d=None)
        # 4a4 s.2.4: DUR, its own rating, with its weekly change
        if r is not None and r.get("dur") is not None:
            dd = None
            if prev_dur is not None and n in prev_dur:
                dd = int(r["dur"]) - int(prev_dur[n])
            row.update(dur=str(r["dur"]), dur_k=int(r["dur"]), dur_d=change(dd))
        else:
            row.update(dur=DASH, dur_k=None, dur_d=None)
        comps = (r or {}).get("components") or {}
        row["avail"] = (f"{float(comps['availability']) * 100:.0f}%" if r is not None
                        and comps.get("availability") is not None else DASH)
        # the grade tiles (every rated player; 5b: free agents too; 4a4: nine)
        if r is not None:
            tiles = []
            for attr in order:
                g = r["grades"][attr]
                # compact (the payload's size): the display name and the colour
                # class are added back by tiles(); empty fields are left out
                t = {"key": attr, "letter": g["letter"] or DASH}
                if g["letter"] is None:
                    t["reason"] = g["reason"] or "no value"
                else:
                    t["w"] = f"{float(g['percentile']):.0f}%"
                    t["pct"] = f"{ordinal(int(math.floor(float(g['percentile']) + 0.5)))} pct"
                    t["p"] = round(float(g["percentile"]), 3)   # for the archetype preview only
                if attr == "schedule" and g.get("value") is not None:
                    t["count"] = f"{int(g['value'])} games"
                tiles.append(t)
            row["grades"] = tiles
        else:
            row["grades"] = None
        # Compare's cells: the printed text and its integer order key (None: wins nothing)
        cells = [{"t": row["pot"], "k": row["pot_k"]},
                 {"t": row["dur"], "k": row["dur_k"]},
                 {"t": fppg, "k": _int_or_none(fppg, 10)},
                 {"t": l14, "k": _int_or_none(l14, 10)},
                 {"t": row["min"], "k": row["min_k"]},                    # 4a3: more is better
                 {"t": row["avail"], "k": _int_or_none(row["avail"])},
                 {"t": g3, "k": _int_or_none(g3)},
                 {"t": keep, "k": _int_or_none(keep) if u["kind"] == "rostered" else None},
                 {"t": row["age"], "k": None}]                          # age has no winner
        for attr in order:                                  # 4a4 s.4: Compare follows the tiles
            if row["grades"] is None:
                cells.append({"t": DASH, "k": None})
            else:
                g = r["grades"][attr]
                cells.append({"t": g["letter"] or DASH, "k": letter_rank(g["letter"], bands)})
        row["cmp"] = cells
        # 4a4 s.3: the archetype ("arch" only when enabled; else "arch_off", never printed)
        a = (r or {}).get("archetype")
        if a is not None:
            row["arch" if cfg["archetype"]["enabled"] else "arch_off"] = {
                "label": a["label"], "kw": " \u00b7 ".join(a["tags"]),
                "st": ", ".join(labels[x] for x in a["standouts"]), "preview": False}
        rows.append(row)

    rows.sort(key=lambda z: (z["name"].lower(), z["name"]))

    # orders: best first ("d") and its reverse ("a"), missing values last both ways
    def order_by(keyf):
        have = [i for i, z in enumerate(rows) if keyf(z) is not None]
        miss = [i for i, z in enumerate(rows) if keyf(z) is None]
        d = sorted(have, key=lambda i: (_neg(keyf(rows[i])), rows[i]["name"].lower()))
        a = sorted(have, key=lambda i: (keyf(rows[i]), rows[i]["name"].lower()))
        return {"d": d + miss, "a": a + miss}
    comp = {n: pr.get("ovr_composite") for n, pr in list(rp.items()) + list(fp.items())}

    def ovr_key(z):                                   # 5b s.1b: equal OVRs by the composite underneath
        if z["ovr_k"] is None:
            return None
        c = comp.get(z["name"])
        return (z["ovr_k"], float(c) if c is not None else float("-inf"))
    orders = {"ovr": order_by(ovr_key), "pot": order_by(lambda z: z["pot_k"]), "dur": order_by(lambda z: z["dur_k"]),
              "fppg": order_by(lambda z: _int_or_none(z["fppg"], 10)),
              "next": order_by(lambda z: _int_or_none(z["next"]))}
    by_name = sorted(range(len(rows)), key=lambda i: (rows[i]["name"].lower(), rows[i]["name"]))
    orders["name"] = {"d": by_name, "a": list(reversed(by_name))}

    filters = {"pos": [p for p in BASE_POS if any(p in z["f"]["pos"] for z in rows)],
               "nba": sorted({z["f"]["nba"] for z in rows if z["f"]["nba"]}),
               "age": [{"key": k, "label": lab} for k, lab, _lo, _hi in AGE_BANDS
                       if any(z["f"]["age"] == k for z in rows)]}

    # risers: the biggest OVR gains a week back, each with its reason
    risers = None
    # 4a4: only a line of the same OVR version (history_values): a week after the switch
    if prev_line is not None and res is not None and history_values(prev_line, "ovr") is not None:
        rkind = "4a"
        now_terms = {}
        for n, pr in list(rp.items()) + list(fp.items()):
            c = pr["components"]
            sk = pr.get("skill")
            if sk is not None:
                rkind = "skill"
                if pr["ovr"] is not None and sk.get("estimate") is not None:
                    now_terms[n] = [float(sk["estimate"]), float(sk["fppg"] or 0.0), int(sk["games"] or 0)]
            elif pr["ovr"] is not None and all(c.get(t) is not None for t in ("level", "availability", "games_remaining")):
                now_terms[n] = [float(c["level"]), float(c["availability"]), int(c["games_remaining"])]
        then_terms = dict(prev_line.get("terms") or {})
        pos_of = {z["name"]: i for i, z in enumerate(rows)}
        # 5b: a rostered player's reason ranks him among the players rostered in
        # both lines (a line before 5b has no "fa": all rostered), as before; a
        # free agent (now or then) among them and himself
        was_fa = set(prev_line.get("fa") or [])
        league = {n for n in rp if n not in was_fa}
        cands = [(n, pr["ovr_change"]) for n, pr in list(rp.items()) + list(fp.items())
                 if pr["ovr_change"] is not None and pr["ovr_change"] > 0 and n in pos_of
                 and n in now_terms and n in then_terms]
        cands.sort(key=lambda t: (-t[1], t[0]))
        risers = []
        for n, d in cands[:RISERS_MAX]:
            z = rows[pos_of[n]]
            pool = league | {n}
            mark = z["chip"]["team"] if z["kind"] == "rostered" else "FA"
            risers.append({"i": pos_of[n], "ovr": z["ovr"], "d": change(d)["t"],
                           "reason": f"{mark} \u00b7 {riser_reason(n, now_terms, then_terms, pool, rkind)}"})

    n_r = sum(1 for z in rows if z["kind"] == "rostered")
    block = {"rows": rows, "orders": orders, "default": "ovr", "filters": filters, "risers": risers,
             "count": f"{len(rows)} players",
             "who": (f"Every player the hub has a card for: {n_r} rostered and {len(rows) - n_r} free agents "
                     "it names (the free-agent and stash lists, the moves feed, the trade block)."),
             "cmp_rows": [{"key": k, "label": lab} for k, lab in CMP_ROWS]
             + [{"key": g, "label": labels[g]} for g in order],
             "grade_labels": [labels[g] for g in order]}
    if prev_line is None:
        change_note = ("No weekly change yet: it appears once a published rating is at least 7 days old "
                       "(the ratings history starts with the first published run).")
    else:
        change_note = f"Changes are since the ratings of {_md(prev_line['as_of'])}."
    ratings_block = {"as_of": _md(res["as_of"]) if res else DASH,
                     "error": rerr, "change_note": change_note,
                     "archetype": bool(cfg["archetype"]["enabled"]), "preview": False}
    return block, ratings_block


def _neg(k):
    """Best first: a number or a tuple of numbers, negated."""
    return tuple(-x for x in k) if isinstance(k, tuple) else -k


def _md(iso: str) -> str:
    d = date.fromisoformat(str(iso)[:10])
    return f"{d:%a} {d.month:02d}-{d.day:02d}"


def tiles(grades: Optional[list]) -> Optional[list]:
    """A row's compact grade tiles, whole: each with its display name (config
    ratings.grades.labels), its band's colour class, and every field."""
    if grades is None:
        return None
    from ..ratings import config as rcfg
    labels = rcfg()["grades"]["labels"]
    return [{"key": t["key"], "name": labels[t["key"]], "letter": t["letter"],
             "cls": grade_class(None if t["letter"] == DASH else t["letter"]), "reason": t.get("reason", ""),
             "w": t.get("w", ""), "pct": t.get("pct", ""), "p": t.get("p"), "count": t.get("count", "")}
            for t in grades]


def archetype_table(payload: dict, kind: str = "rostered") -> list:
    """The archetype review's table (4a4 s.3): [(label, [(player, manager,
    standouts, tags)])], largest group first, then ("(no label)", ...) for rows
    without one. kind: "rostered" or "fa". Reads "arch" or "arch_off"."""
    groups, none = {}, []
    for z in payload["v2"]["players"]["rows"]:
        if z["kind"] != kind:
            continue
        a = z.get("arch") or z.get("arch_off")
        if a:
            groups.setdefault(a["label"], []).append((z["name"], z["m"] or "FA", a["st"] or DASH, a["kw"] or DASH))
        else:
            none.append((z["name"], z["m"] or "FA", DASH, DASH))
    out = sorted(groups.items(), key=lambda t: (-len(t[1]), t[0]))
    return out + ([("(no label)", none)] if none else [])


def archetype_preview(payload: dict) -> int:
    """PREVIEW ONLY (build_hub.py --v2 --archetype-preview): every row's
    computed archetype ("arch_off", ratings' own: the blend with his NBA
    history) shown, marked "preview". Publish mode refuses a payload this
    touched. Returns how many rostered rows got a label."""
    v2 = payload["v2"]
    n = 0
    for z in v2["players"]["rows"]:
        a = z.pop("arch_off", None) or z.get("arch")
        z["arch"] = None if a is None else dict(a, preview=True)
        if a is not None and z["kind"] == "rostered":
            n += 1
    v2["ratings"]["preview"] = True
    return n
