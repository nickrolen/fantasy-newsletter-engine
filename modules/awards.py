"""awards.py -- the league awards and their races (4c5; claude/AWARDS_DEFINITIONS_
2026-11-14.md, claude/HANDOFF_4C5_AWARDS_2026-11-19.md).

THE ENGINE COMPUTES; the hub (modules/hub_v2/league.py, page_league.py) only
prints the strings made here.

THE SHARED RULES
- The awards season is weeks 1..R (regular_season_weeks_for: 15 this season),
  live through the season and Final after week R. Playoff weeks never count.
- ONLY STARTED POINTS COUNT: a game counts when the player was in his
  manager's starting lineup that day (the live log's `started`, from
  LINEUPS.xlsx: an active slot, not BN / IL / IL+) AND he played (keeper_
  history.appeared: his team had a game and he was not the 0.0 row). A
  started DNP is no game: it scores 0 for his team, and it is not charged
  replacement points (4c5 decision).
- PAR (points above replacement in starts): for every such game, his fantasy
  points minus that game week's replacement level R, summed.
- R, PER GAME WEEK, POINT IN TIME: OVR's R (ratings.rate): the replacement
  quantile (config ratings.ovr.replacement_quantile, 0 = the lowest) of the
  level L (keepability v3's level_of) over the players rostered on the week's
  last logged day, from keeper_history.snapshot cut at that day. A week still
  in progress uses its last logged day so far. Later rows never reach an
  earlier week's R (snapshot reads only rows on or before its day).
  Measured 4c5: 0.1 s a week, so R is not cached (each history line carries
  its week's R instead).
- A TRADED PLAYER's PAR sums across his teams for MVP and Rookie of the Year,
  and splits by team for Trade of the Year (each side counts only its own
  starts after the trade).
- ELIGIBILITY never excludes silently: every exclusion carries its reason.
  An award whose inputs are missing (Rookie of the Year without this season's
  rookies in config/ROOKIE_SEASONS.json) is NOT COMPUTED and says why.

THE RACES: output/awards_history.jsonl (STATE, append-only; config/STATE_
MANIFEST.json): one line per award per FINISHED regular-season week (the
week's last day), holding the top N (config awards.history_top_n). The hub
build computes the lines of every finished week not on file (`pending`); the
nightly appends them when it publishes (one line per award per week, never
per run). On the first nightly the file is missing, so that run backfills
weeks 1..now with the SAME function the weekly writer uses (lines_for_week):
the backfill is the weekly writer. Week 7 (14 days) is one week, one line.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
HISTORY_RELPATH = Path("output") / "awards_history.jsonl"
SCHEMA = 1
KEYS = ("mvp", "pickup", "improved", "roy", "trade", "bust")
NAMES = {"mvp": "MVP", "pickup": "Best pickup", "improved": "Most improved", "roy": "Rookie of the Year",
         "trade": "Trade of the Year", "bust": "Bust of the Year"}
# the one-line definitions (AWARDS_DEFINITIONS), the awards' InfoTips
INFO = {
    "mvp": "Most points above replacement (PAR) in his starts, weeks 1\u201315, summed over every team he "
           "played for. Wins swung: the matchups his team would have lost had his started games been "
           "replacement-level games (a tie counts half).",
    "pickup": "Most PAR for the manager who added him from free agency, from the add through week 15. "
              "In-season free-agent adds only (preseason adds aren't moves); each add counts on its own.",
    "improved": "This season's fantasy points per game minus his usual level: his last three seasons in "
                "this league, games-weighted. 20+ games this season and 20+ in those seasons.",
    "roy": "Most PAR in his starts among first-year NBA players, weeks 1\u201315.",
    "trade": "For each regular-season trade, the PAR each side has had from the players it got, in its own "
             "starts, through week 15. The biggest gap wins; draft picks are listed, not valued.",
    "bust": "The biggest shortfall against Yahoo's preseason projection, in points (FPPG short \u00d7 games), "
            "among players drafted or kept. 10+ games: an injured-out season is not a bust.",
}
PAR_INFO = ("PAR: each started game's fantasy points minus that week's replacement level (the level of the "
            "lowest-rated rostered player, as in OVR). Bench points never count.")
UNITS = {"mvp": "PAR", "pickup": "PAR", "improved": "FPPG", "roy": "PAR", "trade": "PAR gap", "bust": "pts short"}
UP, DOWN, NDASH, MINUS, DOT = "\u25b2", "\u25bc", "\u2013", "\u2212", " \u00b7 "
CFG_KEYS = ("history_top_n", "shown", "most_improved_min_games", "most_improved_min_prior_games",
            "most_improved_prior_spec", "bust_min_games")


class AwardsError(RuntimeError):
    pass


class AwardsInputError(AwardsError):
    pass


# =============================================================================
# config and formatting
# =============================================================================

def config(cfg: Optional[dict] = None) -> dict:
    """The league_config "awards" block. A missing key RAISES (never defaulted)."""
    if cfg is None:
        from .data_loader import _LEAGUE_CONFIG as cfg
    a = (cfg or {}).get("awards")
    if not isinstance(a, dict):
        raise AwardsInputError("league_config has no \"awards\" block")
    miss = [k for k in CFG_KEYS if k not in a]
    if miss:
        raise AwardsInputError(f"league_config awards is missing {miss}")
    if not (isinstance(a["shown"], int) and isinstance(a["history_top_n"], int) and 1 <= a["shown"] <= a["history_top_n"]):
        raise AwardsInputError("league_config awards: need 1 <= shown <= history_top_n (integers)")
    return a


def _d1(x) -> str:
    v = round(float(x), 1)
    s = f"{abs(v):,.1f}"
    return (MINUS + s) if v < 0 else s


def _s1(x) -> str:
    v = round(float(x), 1)
    s = f"{abs(v):,.1f}"
    return ("+" + s) if v > 0 else (MINUS + s) if v < 0 else s


def _half(x: float) -> str:
    """3 -> "3", 2.5 -> "2.5" (a flip to a tie counts half)."""
    v = round(float(x) * 2) / 2
    return str(int(v)) if v == int(v) else f"{v:.1f}"


def _md(day: str) -> str:
    return str(day)[5:10]


def _short(name: str) -> str:
    """An end label's name: his last name ("Nikola Jokic" -> "Jokic"; a
    suffix keeps the word before it)."""
    parts = str(name).split()
    while len(parts) > 1 and parts[-1].rstrip(".").lower() in ("jr", "sr", "ii", "iii", "iv"):
        parts = parts[:-1]
    return parts[-1] if parts else str(name)


# =============================================================================
# gather
# =============================================================================

def _preseason(path: Path) -> dict:
    """Yahoo's preseason projection: {name: projected FPPG} (PlayerIndex) and
    where it came from."""
    import pandas as pd
    from .data_loader import PlayerIndex
    if not path.is_file():
        raise AwardsInputError(f"the preseason projection snapshot {path.as_posix()} is missing")
    x = pd.ExcelFile(path)
    df = x.parse(x.sheet_names[0])
    for col in ("player_name", "projectedFPPG"):
        if col not in df.columns:
            raise AwardsInputError(f"{path.name} has no {col} column")
    fetched = None
    if "_fetch" in x.sheet_names:
        f = x.parse("_fetch")
        kv = dict(zip(f["key"].astype(str), f["value"].astype(str)))
        fetched = (kv.get("fetched_at") or "")[:10] or None
    idx = PlayerIndex()
    for n, v in zip(df["player_name"], df["projectedFPPG"]):
        if isinstance(n, str) and v == v:
            idx[n] = float(v)
    return {"by_name": idx, "file": path.name, "fetched": fetched}


def gather(root=ROOT, *, live=None, actuals: Optional[dict] = None, cfg: Optional[dict] = None,
           params: Optional[dict] = None) -> dict:
    """Every input compute() reads. live: the run's shared keeper_history.
    live_inputs (built here when None); actuals: data/player_actuals.json's
    blob (loaded here when None); cfg: the whole league_config (the module's
    when None)."""
    from . import keeper_history as kh, keepability_v3 as M, transaction_log as tl, ratings
    from .data_loader import PlayerIndex, regular_season_weeks_for
    root = Path(root)
    if cfg is None:
        from .data_loader import _LEAGUE_CONFIG as cfg
    acfg = config(cfg)
    if live is None:
        live = kh.live_inputs(root, kh.Inputs.load(root))
    inputs, season = live
    rows = list(inputs.log.get(season) or [])
    sched = json.loads((root / "config" / "SCHEDULE.json").read_text(encoding="utf-8"))
    weeks = sorted(sched.get("weeks") or [], key=lambda w: int(w["week"]))
    if not weeks:
        raise AwardsInputError("config/SCHEDULE.json has no weeks")
    reg = int(regular_season_weeks_for(season))
    week_of = {}
    for w in weeks:
        d0, d1 = date.fromisoformat(str(w["start_date"])[:10]), date.fromisoformat(str(w["end_date"])[:10])
        for i in range((d1 - d0).days + 1):
            week_of[date.fromordinal(d0.toordinal() + i).isoformat()] = int(w["week"])
    snap_rel = (cfg.get("durability_prior") or {}).get("snapshot")
    if not snap_rel:
        raise AwardsInputError("league_config durability_prior.snapshot (the preseason PLAYERLIST) is not set")
    ledger_p = root / "config" / "MOVE_LEDGER.json"
    if not ledger_p.is_file():
        raise AwardsInputError("config/MOVE_LEDGER.json is missing")
    if actuals is None:
        from . import player_actuals as pa
        actuals = pa.load(root)
    by_id, by_name = {}, PlayerIndex()
    for pid, rec in (actuals.get("players") or {}).items():
        by_id[int(pid)] = rec
        by_name[rec["name"]] = rec
    params = params if params is not None else M.load_params()
    return {
        "root": root, "season": season, "inputs": inputs, "rows": rows, "weeks": weeks, "reg": reg,
        "week_of": week_of, "days": sorted({r["date"] for r in rows}), "cfg": acfg,
        "quantile": float(ratings.config(cfg.get("ratings"))["ovr"]["replacement_quantile"]),
        "lp": M.level_config(params),
        "transactions": tl.transactions(root),
        "ledger": json.loads(ledger_p.read_text(encoding="utf-8")).get("rows") or [],
        "rookies": json.loads((root / "config" / "ROOKIE_SEASONS.json").read_text(encoding="utf-8")),
        "preseason": _preseason(root / snap_rel), "preseason_rel": snap_rel,
        "actuals_first": actuals.get("first_day"), "act_by_id": by_id, "act_by_name": by_name,
        "tie_value": None,
    }


# =============================================================================
# the shared pieces
# =============================================================================

def _week(inp: dict, w: int) -> dict:
    return inp["weeks"][[int(x["week"]) for x in inp["weeks"]].index(int(w))]


def replacement_levels(inp: dict, cut: str) -> Dict[int, dict]:
    """{week: {"R", "as_of", "who", "n"}} for every regular-season week begun
    by `cut`: the replacement quantile of L over the players rostered on the
    week's last logged day on or before `cut` (point in time). Cached per day
    in inp (a finished week's R does not depend on the cut)."""
    from . import keeper_history as kh, keepability_v3 as M, ratings
    cache = inp.setdefault("_R", {})
    out = {}
    for w in inp["weeks"]:
        k = int(w["week"])
        if k > inp["reg"] or str(w["start_date"])[:10] > cut:
            continue
        hi = min(str(w["end_date"])[:10], cut)
        days = [d for d in inp["days"] if str(w["start_date"])[:10] <= d <= hi]
        if not days:
            continue
        as_of = days[-1]
        if as_of not in cache:
            snap = kh.snapshot(inp["inputs"], kh.next_season(inp["season"]), "end", None, check=False,
                               labels=False, as_of=as_of)
            levels = {c.player: float(M.level_of(c, inp["lp"])[0]) for c in snap.candidates}
            if not levels:
                raise AwardsInputError(f"no rostered player on {as_of}: no replacement level")
            R = ratings.quantile(list(levels.values()), inp["quantile"])
            who = min(levels, key=lambda n: (abs(levels[n] - R), n))
            cache[as_of] = {"R": float(R), "as_of": as_of, "who": who, "n": len(levels)}
        out[k] = cache[as_of]
    return out


def _tie_value(inp: dict) -> float:
    if inp.get("tie_value") is None:
        from .data_loader import regular_season_tie_value
        inp["tie_value"] = float(regular_season_tie_value())
    return inp["tie_value"]


def _result_value(a: float, b: float, tie: float) -> float:
    a, b = round(a, 2), round(b, 2)
    return 1.0 if a > b else tie if a == b else 0.0


def _opponent(week: dict, m: str) -> Optional[str]:
    for mu in week.get("matchups") or []:
        if mu["manager_a"] == m:
            return mu["manager_b"]
        if mu["manager_b"] == m:
            return mu["manager_a"]
    return None


def wins_swung(his: dict, totals: dict, inp: dict, R: dict, finished: list) -> tuple:
    """(swung, cost) in wins. his: {(week, manager): [his started points,
    his started games]}. For each FINISHED week, his team's total with his
    started points taken out and R per started game put in, against the
    opponent's real total: a W that becomes an L is 1, a W that becomes a T
    or a T that becomes an L is the T's value (0.5, config). `cost`: the
    other direction (his games were below replacement and cost a result)."""
    tie = _tie_value(inp)
    up = down = 0.0
    for (w, m), (pts, g) in sorted(his.items()):
        if w not in finished:
            continue
        opp = _opponent(_week(inp, w), m)
        if opp is None:
            continue
        a, b = totals.get(w, {}).get(m, 0.0), totals.get(w, {}).get(opp, 0.0)
        cf = a - pts + R[w]["R"] * g
        d = _result_value(a, b, tie) - _result_value(cf, b, tie)
        if d > 0:
            up += d
        elif d < 0:
            down -= d
    return up, down


def _actual(inp: dict, name: str, pid, through: str) -> tuple:
    """(games, points) in his NBA games through `through` (player_actuals:
    every NBA game, on a league roster or not), or (None, reason)."""
    rec = inp["act_by_id"].get(int(pid)) if pid not in (None, "") else None
    if rec is None:
        rec = inp["act_by_name"].get(name)
    if rec is None:
        return None, "no daily NBA lines cached for him (data/player_actuals.json)"
    days = rec.get("days") or {}
    d0 = date.fromisoformat(inp["actuals_first"])
    d1 = date.fromisoformat(through)
    g = p = 0
    for i in range((d1 - d0).days + 1):
        d = date.fromordinal(d0.toordinal() + i).isoformat()
        v = days.get(d)
        if v is None:
            return None, f"his daily lines are not fetched for {d}"
        p += float(v[0])
        g += int(v[1])
    return (g, p), None


def _excl(out: list, who: str, kind: str, reason: str) -> None:
    out.append({"who": who, "kind": kind, "reason": reason})


def _award(key: str) -> dict:
    return {"key": key, "name": NAMES[key], "info": INFO[key], "unit": UNITS[key], "rows": [], "excluded": [],
            "error": None, "source": None}


def _rank(rows: list) -> list:
    return sorted(rows, key=lambda r: (-r["value"], r["label"], r["key"]))


# =============================================================================
# compute
# =============================================================================

def week_of_cut(inp: dict, cut: str) -> int:
    """The regular-season week `cut` falls in (0 before week 1)."""
    w = inp["week_of"].get(cut)
    if w is None:
        if cut < str(inp["weeks"][0]["start_date"])[:10]:
            return 0
        raise AwardsInputError(f"{cut} is in no fantasy week of config/SCHEDULE.json")
    return min(int(w), inp["reg"])


def finished_weeks(inp: dict, through: Optional[str] = None) -> list:
    """Regular-season weeks whose last day is logged (on or before `through`,
    default the log's last day)."""
    last = inp["days"][-1] if inp["days"] else ""
    through = min(through or last, last)
    return [int(w["week"]) for w in inp["weeks"]
            if int(w["week"]) <= inp["reg"] and str(w["end_date"])[:10] <= through]


def compute(inp: dict, through: str) -> dict:
    """Every award as of `through` (an ISO day on or before the log's last).
    RAISES AwardsInputError on missing inputs; an award that cannot be
    computed carries its error instead of rows."""
    from . import keeper_history as kh
    season, reg = inp["season"], inp["reg"]
    if inp["days"] and through > inp["days"][-1]:
        raise AwardsInputError(f"{through} is past the live log's last day {inp['days'][-1]}")
    reg_end = str(_week(inp, reg)["end_date"])[:10]
    cut = min(through, reg_end)
    wk = week_of_cut(inp, cut)
    res = {"schema": SCHEMA, "season": season, "through": through, "cut": cut, "week": wk,
           "final": through >= reg_end, "reg": reg, "finished": [], "R": {},
           "awards": {k: _award(k) for k in KEYS}}
    if wk == 0 or not inp["days"]:
        return res
    R = replacement_levels(inp, cut)
    finished = finished_weeks(inp, cut)
    res["R"], res["finished"] = R, finished
    rows = [r for r in inp["rows"] if r["date"] <= cut]
    for r in rows:
        if inp["week_of"].get(r["date"]) != int(r["week"]):
            raise AwardsInputError(f"log row {r['player_name']} {r['date']} is week {r['week']}, "
                                   f"SCHEDULE says {inp['week_of'].get(r['date'])}")
    rows = [r for r in rows if int(r["week"]) <= reg]
    names = kh.Names(rows) if rows else kh.Names([])
    pid_of = {}
    for r in rows:
        if r.get("player_id") is not None:
            pid_of[r["player_name"]] = r["player_id"]
    totals: dict = {}
    starts = []
    for r in rows:
        if r["started"]:
            w = int(r["week"])
            totals.setdefault(w, {}).setdefault(r["manager"], 0.0)
            totals[w][r["manager"]] += float(r["fantasy_points"])
            if kh.appeared(r):
                starts.append(r)

    def par(r):
        return float(r["fantasy_points"]) - R[int(r["week"])]["R"]

    # ---- per player: PAR over every team (MVP, Rookie of the Year)
    per: dict = {}
    for r in starts:
        d = per.setdefault(r["player_name"], {"par": 0.0, "starts": 0, "teams": {}, "wk": {}, "last": ("", "")})
        v = par(r)
        d["par"] += v
        d["starts"] += 1
        d["teams"][r["manager"]] = d["teams"].get(r["manager"], 0.0) + v
        x = d["wk"].setdefault((int(r["week"]), r["manager"]), [0.0, 0])
        x[0] += float(r["fantasy_points"])
        x[1] += 1
        if r["date"] >= d["last"][0]:
            d["last"] = (r["date"], r["manager"])

    a = res["awards"]["mvp"]
    for n, d in per.items():
        up, down = wins_swung(d["wk"], totals, inp, R, finished)
        teams = sorted(d["teams"], key=lambda m: -d["teams"][m])
        sub = f"{d['starts']} starts" + (DOT + " + ".join(f"{m} {_d1(d['teams'][m])}" for m in teams)
                                         if len(teams) > 1 else "")
        a["rows"].append({"key": n, "player": n, "label": n, "m": d["last"][1], "ms": teams,
                          "value": d["par"], "shown": f"wins swung: {_half(up)}", "sub": sub,
                          "swung": up, "cost": down, "starts": d["starts"]})
    a["rows"] = _rank(a["rows"])

    _pickups(inp, res, rows, starts, par, names, cut)
    _improved(inp, res, rows, pid_of, cut)
    _rookies(inp, res, per, pid_of, cut)
    _trades(inp, res, starts, par, names, cut, reg_end)
    _busts(inp, res, names, pid_of, cut)
    return res


def _stints(rows: list) -> dict:
    """{(player, manager): [(first day, last day)]}: runs of consecutive
    logged days on which that manager had him."""
    days = sorted({r["date"] for r in rows})
    pos = {d: i for i, d in enumerate(days)}
    have: dict = {}
    for r in rows:
        have.setdefault((r["player_name"], r["manager"]), set()).add(r["date"])
    out = {}
    for k, ds in have.items():
        idx = sorted(pos[d] for d in ds)
        runs, s = [], idx[0]
        for a, b in zip(idx, idx[1:]):
            if b != a + 1:
                runs.append((days[s], days[a]))
                s = b
        runs.append((days[s], days[idx[-1]]))
        out[k] = runs
    return out


def _fa_adds(inp: dict, names) -> list:
    """Every free-agent add not voided: (day, manager, log name, transaction)."""
    out = []
    for t in inp["transactions"]:
        if t.get("status") != "successful":
            continue
        voided = {str(r.get("player") or "").lower() for r in t.get("rulings") or [] if r.get("kind") == "void"}
        for p in t.get("players") or []:
            if p.get("action") != "add" or (p.get("from") or {}).get("type") != "freeagents":
                continue
            if str(p.get("name") or "").lower() in voided:
                continue
            m = (p.get("to") or {}).get("manager")
            pid = str(p.get("player_key") or "").rsplit(".", 1)[-1]
            n = names.canon(p["name"], pid if pid.isdigit() else None) or p["name"]
            out.append((str(t["league_day"])[:10], m, n, t))
    return out


def _dropped(inp: dict, t: dict, m: str, n: str, day: str, names) -> tuple:
    """(who he was added for, or [], and a note when that is not known): the
    move ledger's entry (the league's record of the claim), else the same
    Yahoo transaction's drop, else that manager's separate drops that day
    when they pair one to one with his separate adds in time order (drop,
    add, drop, add). Anything else is "not paired": never guessed."""
    from .data_loader import PlayerIndex
    void = {r.get("entry") for r in inp["ledger"] if r.get("row") == "void"}
    for e in inp["ledger"]:
        if e.get("row") != "entry" or e.get("kind") != "move" or e.get("id") in void:
            continue
        pz = e.get("parsed") or {}
        if pz.get("manager") != m or str(e.get("window") or "")[:10] != day:
            continue
        if PlayerIndex({x: x for x in pz.get("add") or []}).canonical(n) is not None:
            return list(pz.get("drop") or []), None
    same = [p["name"] for p in t.get("players") or []
            if p.get("action") == "drop" and (p.get("from") or {}).get("manager") == m]
    if same:
        return same, None
    adds, drops, void_added = [], [], set()
    for x in inp["transactions"]:
        if str(x.get("league_day"))[:10] != day or x.get("status") != "successful":
            continue
        ps = x.get("players") or []
        vd = {str(r.get("player") or "").lower() for r in x.get("rulings") or [] if r.get("kind") == "void"}
        mine_add = [p for p in ps if p.get("action") == "add" and (p.get("to") or {}).get("manager") == m]
        mine_drop = [p for p in ps if p.get("action") == "drop" and (p.get("from") or {}).get("manager") == m]
        for p in mine_add:
            if str(p["name"]).lower() in vd:
                void_added.add(str(p["name"]).lower())
        if mine_add and not mine_drop:
            adds += [(int(x["timestamp"]), p["name"]) for p in mine_add if str(p["name"]).lower() not in vd]
        if mine_drop and not mine_add:
            drops += [(int(x["timestamp"]), p["name"]) for p in mine_drop]
    drops = [d for d in drops if str(d[1]).lower() not in void_added]
    if not drops:
        return [], None
    adds.sort()
    drops.sort()
    if len(adds) == len(drops) and all(drops[i][0] <= adds[i][0] and (i == 0 or drops[i][0] > adds[i - 1][0])
                                       for i in range(len(adds))):
        for (_ta, an), (_td, dn) in zip(adds, drops):
            if names.canon(an) == n or an == n:
                return [dn], None
    return [], "drop not paired in Yahoo's log"


def _pickups(inp, res, rows, starts, par, names, cut) -> None:
    a = res["awards"]["pickup"]
    first_day = str(inp["weeks"][0]["start_date"])[:10]
    adds = _fa_adds(inp, names)
    stints = _stints(rows)
    par_of: dict = {}
    for r in starts:
        par_of.setdefault((r["player_name"], r["manager"]), []).append((r["date"], par(r)))
    best: dict = {}
    for (n, m), runs in stints.items():
        prev_end = ""
        for s, e in runs:
            hits = [x for x in adds if x[1] == m and x[2] == n and prev_end < x[0] <= s]
            prev_end = e
            if not hits:
                continue
            day, _m, _n, t = max(hits, key=lambda x: (x[0], int(x[3].get("timestamp") or 0)))
            v = sum(p for d, p in par_of.get((n, m), []) if s <= d <= e)
            g = sum(1 for d, _p in par_of.get((n, m), []) if s <= d <= e)
            pre = day < first_day
            if pre:     # Nick, 11-19: preseason adds are not moves (LEAGUE_RULES rule 14), so not pickups
                _excl(a["excluded"], n, "preseason add",
                      f"added {_md(day)}, before the season's first game: preseason adds are not moves (rule 14)")
                continue
            drops, note = _dropped(inp, t, m, n, day, names)
            shown = (f"dropped {' and '.join(drops)} on {_md(day)}" if drops else
                     f"added {_md(day)}; {note}" if note else f"added {_md(day)}, no drop")
            row = {"key": f"{n}|{m}|{day}", "player": n, "label": n, "m": m, "value": v, "shown": shown,
                   "sub": f"{g} starts for {m}" + (DOT + "preseason add" if pre else ""),
                   "add_day": day, "stint": [s, e], "drops": drops, "preseason": pre}
            if n not in best or (row["value"], row["add_day"]) > (best[n]["value"], best[n]["add_day"]):
                best[n] = row
            a.setdefault("stints", []).append(row)
    a["rows"] = _rank(best.values())


def _improved(inp, res, rows, pid_of, cut) -> None:
    from . import keeper_history as kh, keepability_v3 as M
    a = res["awards"]["improved"]
    c = inp["cfg"]
    need, need_prior, spec = int(c["most_improved_min_games"]), int(c["most_improved_min_prior_games"]), \
        c["most_improved_prior_spec"]
    back = inp.get("_back")
    if back is None:
        back = inp["_back"] = kh.previous_lines(inp["inputs"], inp["season"])
    for n in sorted({r["player_name"] for r in rows}):
        line, why = _actual(inp, n, pid_of.get(n), cut)
        if line is None:
            _excl(a["excluded"], n, "no daily lines", why)
            continue
        g, p = line
        if g < need:
            _excl(a["excluded"], n, f"under {need} games this season", f"{g} games this season ({need} needed)")
            continue
        prior, used = M.prior_from_lines(inp["season"], back(n), spec)
        if prior is None:
            _excl(a["excluded"], n, "no prior league seasons", "no earlier season in this league's log")
            continue
        pg = sum(x[1] for x in used)
        if pg < need_prior:
            _excl(a["excluded"], n, f"under {need_prior} games in his prior league seasons",
                  f"{pg} games in his prior league seasons ({need_prior} needed)")
            continue
        f = p / g
        if f - prior <= 0:                      # eligible, but not improved: never in the race
            continue
        last_m = max((r for r in rows if r["player_name"] == n), key=lambda r: r["date"])["manager"]
        a["rows"].append({"key": n, "player": n, "label": n, "m": last_m, "value": f - prior,
                          "shown": f"{_d1(f)} vs {_d1(prior)} usual",
                          "sub": f"{g} games" + DOT + "usual over " + ", ".join(x[0] for x in used),
                          "fppg": f, "usual": prior, "games": g})
    a["rows"] = _rank(a["rows"])


def _rookies(inp, res, per, pid_of, cut) -> None:
    from .data_loader import PlayerIndex
    a = res["awards"]["roy"]
    season = inp["season"]
    idx = PlayerIndex(inp["rookies"])
    listed = sorted(n for n, s in inp["rookies"].items() if s == season)
    unknown = sorted(n for n in per if idx.canonical(n) is None)
    if not listed or unknown:
        bits = []
        if not listed:
            bits.append(f"it lists no {season} rookie")
        if unknown:
            bits.append(f"{len(unknown)} players started this season are not in it ("
                        + ", ".join(unknown[:4]) + (", ..." if len(unknown) > 4 else "") + ")")
        a["error"] = ("Not computed: config/ROOKIE_SEASONS.json is not up to date for " + season + ": "
                      + "; ".join(bits) + ". Run python scripts\\build_rookie_seasons.py --update.")
        return
    for n, d in per.items():
        if idx[idx.canonical(n)] != season:
            continue
        line, why = _actual(inp, n, pid_of.get(n), cut)
        sub = (f"{_d1(line[1] / line[0])} FPPG in {line[0]} games" if line and line[0] else (why or "no games"))
        a["rows"].append({"key": n, "player": n, "label": n, "m": d["last"][1], "value": d["par"],
                          "shown": sub, "sub": f"{d['starts']} starts"})
    a["rows"] = _rank(a["rows"])


def _trades(inp, res, starts, par, names, cut, reg_end) -> None:
    from . import keeper_history as kh
    a = res["awards"]["trade"]
    season = inp["season"]
    for t in inp["inputs"].trades:
        if t.get("season") != season:
            continue
        first, _last = kh.trade_dates(t.get("date"), season)
        ma, mb = t.get("trader_manager"), t.get("tradee_manager")
        label = f"{ma} \u21c4 {mb}, {_md(first)}"
        if first > reg_end:
            _excl(a["excluded"], label, "after the regular season", f"made {first}, after week {inp['reg']}")
            continue
        if first > cut:
            continue
        got = {ma: [], mb: []}
        for mv in t.get("players") or []:
            n = names.canon(mv["player_name"]) or mv["player_name"]
            got.setdefault(mv["to_manager"], []).append(n)
        side = {}
        for m in (ma, mb):
            mine = set(got.get(m) or [])
            side[m] = sum(par(r) for r in starts if r["manager"] == m and r["player_name"] in mine
                          and r["date"] >= first)
        picks = {m: list(v or []) for m, v in (t.get("picks") or {}).items() if v}
        win, lose = (ma, mb) if side[ma] >= side[mb] else (mb, ma)
        a["rows"].append({"key": f"{first}|{ma}|{mb}|" + ",".join(sorted(sum(got.values(), []))),
                          "player": None, "label": label, "m": win, "value": abs(side[ma] - side[mb]),
                          "shown": f"won by {win}" + (DOT + "draft picks listed, not valued" if picks else ""),
                          "sub": "",
                          "sides": {m: {"par": side[m], "got": got.get(m) or []} for m in (ma, mb)},
                          "picks": picks, "date": first})
    a["rows"] = _rank(a["rows"])


def _other(m, a, b):
    return b if m == a else a


def _busts(inp, res, names, pid_of, cut) -> None:
    a = res["awards"]["bust"]
    pre = inp["preseason"]
    a["source"] = (f"Yahoo's preseason projection ({inp['preseason_rel']}"
                   + (f", fetched {pre['fetched']}" if pre["fetched"] else "") + ")")
    need = int(inp["cfg"]["bust_min_games"])
    for p in inp["inputs"].picks.get(inp["season"]) or []:
        n = names.canon(p["player_name"], p.get("player_key")) or p["player_name"]
        how = "keeper" if p.get("is_keeper") else f"pick {int(p['pick_number'])}"
        hit = pre["by_name"].canonical(n) or pre["by_name"].canonical(p["player_name"])
        if hit is None:
            _excl(a["excluded"], n, "not in Yahoo's preseason projections",
                  f"{how}: not in {pre['file']}")
            continue
        exp = pre["by_name"][hit]
        line, why = _actual(inp, n, p.get("player_key") or pid_of.get(n), cut)
        if line is None:
            _excl(a["excluded"], n, "no daily lines", why)
            continue
        g, pts = line
        if g < need:
            _excl(a["excluded"], n, f"under {need} games: out, not a bust", f"{g} games ({need} needed)")
            continue
        f = pts / g
        short = (exp - f) * g
        if short <= 0:
            continue
        a["rows"].append({"key": n, "player": n, "label": n, "m": p["manager"], "value": short,
                          "shown": f"expected {_d1(exp)}, {_d1(f)} in {g} games",
                          "sub": f"{p['manager']}'s {how}", "expected": exp, "fppg": f, "games": g})
    a["rows"] = _rank(a["rows"])


# =============================================================================
# the history file (state, append-only)
# =============================================================================

def history_lines(res: dict, cfg: dict) -> list:
    """One line per award for a FINISHED week's result (its cut is the week's
    last day). RAISES for a week in progress."""
    w = res["week"]
    if w == 0 or w not in res["finished"]:
        raise AwardsError(f"week {w} is not finished as of {res['cut']}: no history line")
    n = int(cfg["history_top_n"])
    out = []
    for k in KEYS:
        a = res["awards"][k]
        out.append({"schema": SCHEMA, "season": res["season"], "week": w, "through": res["cut"], "award": k,
                    "final": w == res["reg"], "replacement_level": round(res["R"][w]["R"], 3),
                    "top": [{"rank": i, "key": r["key"], "label": r["label"], "m": r["m"],
                             "value": round(float(r["value"]), 2)} for i, r in enumerate(a["rows"][:n], 1)],
                    "eligible": len(a["rows"]), "excluded": len(a["excluded"]), "error": a["error"]})
    return out


def lines_for_week(inp: dict, week: int) -> list:
    """THE weekly writer: the lines a finished week gets, computed at its last
    day. The backfill calls exactly this."""
    return history_lines(compute(inp, str(_week(inp, week)["end_date"])[:10]), inp["cfg"])


def _key(line: dict) -> tuple:
    return line["season"], int(line["week"]), line["award"]


def pending(inp: dict, lines: list) -> list:
    """The lines of every finished regular-season week of this season not on
    file, oldest week first (the first nightly's backfill: weeks 1..now). A
    week with some awards on file and not others RAISES."""
    have: dict = {}
    for ln in lines:
        if ln["season"] == inp["season"]:
            have.setdefault(int(ln["week"]), set()).add(ln["award"])
    out = []
    for w in finished_weeks(inp):
        got = have.get(w, set())
        if got == set(KEYS):
            continue
        if got:
            raise AwardsError(f"{HISTORY_RELPATH.as_posix()} has week {w} for {sorted(got)} only")
        out += lines_for_week(inp, w)
    return out


def read_history(root=ROOT) -> list:
    """Every line; no file is []. A bad or repeated line RAISES, naming it."""
    p = Path(root) / HISTORY_RELPATH
    if not p.is_file():
        return []
    out, seen = [], set()
    for i, raw in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
        if not raw.strip():
            continue
        try:
            ln = json.loads(raw)
        except json.JSONDecodeError as e:
            raise AwardsError(f"{HISTORY_RELPATH.as_posix()} line {i} is not JSON: {e}") from None
        for f in ("season", "week", "award", "top"):
            if f not in ln:
                raise AwardsError(f"{HISTORY_RELPATH.as_posix()} line {i} lacks {f!r}")
        if _key(ln) in seen:
            raise AwardsError(f"{HISTORY_RELPATH.as_posix()} line {i} repeats {_key(ln)}")
        seen.add(_key(ln))
        out.append(ln)
    return out


def append_history(root, lines: list) -> Optional[Path]:
    """Append `lines` (append-only; one line per award per week). A line
    already on file RAISES -- nothing is ever rewritten. None when there is
    nothing to append."""
    if not lines:
        return None
    have = {_key(x) for x in read_history(root)}
    new = [_key(x) for x in lines]
    if len(set(new)) != len(new) or have & set(new):
        raise AwardsError(f"{HISTORY_RELPATH.as_posix()} already has {sorted(have & set(new))[:3]}: "
                          "the history is append-only, one line per award per week")
    p = Path(root) / HISTORY_RELPATH
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8", newline="\n") as f:
        for ln in lines:
            f.write(json.dumps(ln, ensure_ascii=False, separators=(",", ":")) + "\n")
    return p


# =============================================================================
# the races: movement, the new leader, the chart (engine strings)
# =============================================================================

def _by(lines: list, season: str) -> dict:
    return {(int(x["week"]), x["award"]): x for x in lines if x["season"] == season}


def _nice(lo: float, hi: float) -> list:
    """Three to five round y ticks spanning [lo, hi]."""
    import math
    span = max(hi - lo, 1.0)
    raw = span / 4
    mag = 10 ** math.floor(math.log10(raw))
    step = next(s * mag for s in (1, 2, 2.5, 5, 10) if s * mag >= raw)
    a = math.floor(lo / step) * step
    b = math.ceil(hi / step) * step
    out, v = [], a
    while v <= b + 1e-9:
        out.append(round(v, 6))
        v += step
    return out


def _tick(v: float) -> str:
    return (MINUS if v < 0 else "") + (f"{abs(v):,.0f}" if abs(v) >= 10 or v == int(v) else f"{abs(v):.1f}")


def race_chart(award: str, rows: list, lines: list, season: str) -> Optional[dict]:
    """The race chart's model: today's top rows' values week by week, from
    the history lines only (a player outside a week's stored top N has no
    point that week). Under two weeks of lines: None (the list only)."""
    by = _by(lines, season)
    wks = sorted(w for (w, k) in by if k == award)
    if len(wks) < 2:
        return None
    # a line's name: his last name, or his first name when two last names would read alike (two
    # Mitchells); an end label is the name only (the values are the rows' and the readout's)
    shorts = {r["key"]: (_short(r["label"]) if r.get("player") else r["label"].split(", ")[-1]) for r in rows}
    dup = {v for v in shorts.values() if list(shorts.values()).count(v) > 1}
    name = {k: (next(r["label"] for r in rows if r["key"] == k).split()[0] if v in dup else v)
            for k, v in shorts.items()}
    series = []
    for r in rows:
        vals, texts = [], []
        for w in wks:
            hit = next((e for e in by[(w, award)]["top"] if e["key"] == r["key"]), None)
            vals.append(None if hit is None else float(hit["value"]))
            texts.append(None if hit is None else (_s1(hit["value"]) if award == "improved" else _d1(hit["value"])))
        if all(v is None for v in vals):
            continue
        last = max(i for i, v in enumerate(vals) if v is not None)
        series.append({"key": r["key"], "m": r["m"], "vals": vals, "texts": texts,
                       "end": name[r["key"]]})
    if not series:
        return None
    allv = [v for s in series for v in s["vals"] if v is not None]
    yt = _nice(min(0.0, min(allv)), max(allv))
    points = []
    for i, w in enumerate(wks):
        bits = [f"{name[s['key']]} {s['texts'][i]}" for s in series if s["texts"][i] is not None]
        points.append({"head": f"Week {w}", "body": DOT.join(bits) if bits else "none of today's top 5 in the top 10"})
    return {"weeks": [str(w) for w in wks], "ticks": [{"x": i / (len(wks) - 1), "t": f"W{w}"} for i, w in enumerate(wks)],
            "yticks": [{"v": v, "t": _tick(v)} for v in yt], "ymin": yt[0], "ymax": yt[-1], "series": series,
            "points": points, "aria": f"{NAMES[award]} race: today's top {len(series)}, {UNITS[award]} week by week"}


def races(res: dict, lines: list, cfg: dict) -> dict:
    """The awards' display model, every value an engine string: per award
    its top `shown` rows with the shown-with figures, the move against the
    week before (from the history lines), "new leader", the race chart, its
    status (Live / Final), exclusions summed up with reasons, or its error."""
    from .headshots import player_slug
    show = int(cfg["shown"])
    season, wk = res["season"], res["week"]
    by = _by(lines, season)
    out = []
    for k in KEYS:
        a = res["awards"][k]
        prev = by.get((wk - 1, k)) if wk else None
        prev_rank = {e["key"]: int(e["rank"]) for e in (prev or {}).get("top") or []}
        rows = []
        for i, r in enumerate(a["rows"][:show], 1):
            if prev is None:
                move, d = "", "none"
            elif r["key"] not in prev_rank:
                move, d = "new", "up"
            else:
                j = prev_rank[r["key"]] - i
                move, d = (f"{UP} {j}", "up") if j > 0 else (f"{DOWN} {-j}", "down") if j < 0 else (NDASH, "flat")
            v = r["value"]
            sides = [{"m": m, "par": f"{_d1(sd['par'])} PAR",
                      "players": [{"name": n, "card": player_slug(n)} for n in sd["got"]],
                      "picks": bool((r.get("picks") or {}).get(_other(m, *list(r["sides"])))) }
                     for m, sd in (r.get("sides") or {}).items()]
            rows.append({"rank": str(i), "key": r["key"], "label": r["label"], "player": r.get("player"),
                         "card": player_slug(r["player"]) if r.get("player") else "", "m": r["m"],
                         "value": _s1(v) if k == "improved" else _d1(v), "unit": UNITS[k],
                         "shown": r["shown"], "sub": r["sub"], "move": move, "dir": d, "sides": sides})
        leader = ""
        if prev is not None and prev.get("top") and a["rows"] and prev["top"][0]["key"] != a["rows"][0]["key"]:
            leader = f"New leader: {a['rows'][0]['label']} (was {prev['top'][0]['label']})."
        kinds: dict = {}
        for e in a["excluded"]:
            kinds[e["kind"]] = kinds.get(e["kind"], 0) + 1
        excl = ("Not eligible: " + "; ".join(f"{v} {kk}" for kk, v in sorted(kinds.items(), key=lambda x: -x[1]))
                + ".") if kinds else ""
        empty = ""
        if a["error"] is None and not rows:
            empty = {"trade": "No regular-season trade yet.", "bust": "No drafted or kept player is short of "
                     "his projection with 10+ games yet."}.get(k, "No eligible player yet.") if wk else \
                "The season has not started."
        out.append({"key": k, "name": a["name"], "info": a["info"],
                    "status": "Final" if res["final"] else "Live",
                    "meta": (f"weeks 1{NDASH}{res['reg']}" if res["final"] else
                             f"through week {wk}" + ("" if wk in res["finished"] else " (in progress)")) if wk else "",
                    "unit": UNITS[k], "rows": rows, "leader": leader, "excluded": excl, "error": a["error"] or "",
                    "empty": empty, "source": a["source"] or "",
                    "chart": None if a["error"] else race_chart(k, rows, lines, season)})
    return {"awards": out, "par_note": PAR_INFO,
            "note": ("The arrows compare with the week before. Each race chart draws today's top 5 from the "
                     "weekly lines (the top 10 is kept each week).")}


def newsletter_facts(lines: list, season: str, week: int) -> dict:
    """The weekly facts for the newsletter's races line (4c5 s.4, a proposal):
    per award the leader, second, the gap, a new leader, and the top 5's
    rank changes against the week before. Pure: from the history lines."""
    by = _by(lines, season)
    out = {}
    for k in KEYS:
        ln, prev = by.get((week, k)), by.get((week - 1, k))
        if ln is None:
            continue
        top = ln["top"]
        pr = {e["key"]: int(e["rank"]) for e in (prev or {}).get("top") or []}
        out[k] = {
            "award": NAMES[k], "week": week, "error": ln.get("error"),
            "leader": top[0]["label"] if top else None, "leader_team": top[0]["m"] if top else None,
            "leader_value": top[0]["value"] if top else None,
            "second": top[1]["label"] if len(top) > 1 else None,
            "gap": round(top[0]["value"] - top[1]["value"], 2) if len(top) > 1 else None,
            "new_leader": bool(prev and prev["top"] and top and prev["top"][0]["key"] != top[0]["key"]),
            "previous_leader": prev["top"][0]["label"] if prev and prev["top"] else None,
            "moves": [{"label": e["label"], "rank": int(e["rank"]),
                       "change": (pr[e["key"]] - int(e["rank"])) if e["key"] in pr else None}
                      for e in top[:5]],
        }
    return out
