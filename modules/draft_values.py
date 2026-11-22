"""draft_values.py -- what a draft pick is worth, by round (H56 s.4.3; Nick
11-21, decision 4: one curve, replacing config/DRAFT_PICK_VALUES.json).

THE DATA: every LIVE pick (not a keeper) of each finished draft whose pick
order is trusted (modules/draft_history: 2024-25 on; never the season in
progress). With the 2024-25 and 2025-26 drafts that is 8 picks a round in
rounds 1-7 and nothing yet in rounds 8-10; it grows every season.

THE MEASURES, all over ONE set of games: the player's started games for the
manager who drafted him, in that season's regular season (the awards' rule,
modules/awards: a start counts when he was in an active slot and played).
- par:      points above replacement in those starts: each game's fantasy
            points minus that week's replacement level R (awards.
            replacement_levels, point in time). Trade of the Year's unit, so
            a traded pick is valued in the same currency as the players.
            A pick who never started for his drafter is worth 0: that is part
            of what a pick in that round is worth.
- fppg:     fantasy points per such game (picks with MIN_GP or more games).
- total_fp: fantasy points in those games (every pick; 0 if none).
Why the drafting team's starts and not his season anywhere: a pick's value to
whoever owns it is what the player gives the team that drafts him, exactly as
Trade of the Year counts each side's players only in its own starts.

THE CURVE: for each measure, a weighted least-squares fit of the round means
on log(round) (weights: picks per round), the shape of the old per-pick
curve's decline. Each round's value is its mean shrunk toward the curve,
    value = (n * mean + k * curve) / (n + k),  k = s2 / tau2,
with s2 the pooled within-round variance and tau2 the variance of the round
means around the curve beyond what sampling explains (empirical Bayes; tau2
<= 0 means the rounds do not differ from the curve: value = curve). A round
with no data takes the curve's value, labelled "curve (no data)". Every
round says how many picks back it.

Built by scripts/build_draft_round_values.py into data/historical/
DRAFT_ROUND_VALUES.json (public history, rebuilt at the season reset). Read
only through load() / value(); a missing file or round RAISES.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[1]
FILE = Path("data") / "historical" / "DRAFT_ROUND_VALUES.json"
SCHEMA = 1
MEASURES = ("par", "fppg", "total_fp")
MIN_GP = 5                       # a pick's FPPG counts with 5+ started games (as the old curve's MIN_GP)
MAX_ROUND_DEFAULT = None         # from config: the deepest live round of any draft (draft_history)


class DraftValuesError(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# the data: each live pick's season for his drafter
# ---------------------------------------------------------------------------

def regular_through(season: str) -> int:
    """The season's last regular-season week (config season_structure, the
    awards' source). RAISES when the season isn't listed: never a default."""
    from .data_loader import SEASON_STRUCTURE
    ss = SEASON_STRUCTURE.get(str(season))
    if not isinstance(ss, dict) or not ss.get("regular_through"):
        raise DraftValuesError(f"{season} has no regular_through in season_structure")
    return int(ss["regular_through"])


def pick_game(row: dict, reg_weeks: int) -> bool:
    """THE ONE GAME SET a pick is measured over (H56 s.4.3; 5d1 s.10a): a
    league-log row that is a START (an active slot) for the manager whose
    log it is, in that season's REGULAR SEASON (week <= reg_weeks), on a day
    he PLAYED (keeper_history.appeared: his team had a game and he was not
    the 0.0 injured row). The round values here (pick_lines, the expected)
    and the steal/bust records' actual (scripts/backfill_player_records) both
    count through it, so actual and expected are the same games."""
    from . import keeper_history as kh
    return bool(row["started"]) and int(row["week"]) <= int(reg_weeks) and kh.appeared(row)


def seasons(root=ROOT) -> list:
    """The drafts used: trusted order, keeper era, finished (not the current season)."""
    from . import draft_history as DH
    from .data_loader import CURRENT_SEASON
    rows = DH.read(root)
    return sorted({p["season"] for p in rows if DH.order_trusted(p["season"]) and DH.keeper_era(p["season"])
                   and p["season"] != CURRENT_SEASON})


def pick_lines(root=ROOT, inputs=None, cfg: Optional[dict] = None) -> list:
    """[{season, round, pick_number, manager, player, starts, par, fp}] for
    every live pick of every draft used."""
    from . import draft_history as DH, keeper_history as kh, keepability_v3 as M, awards as A, awards_past as AP
    from .data_loader import regular_season_tie_value
    root = Path(root)
    if cfg is None:
        from .data_loader import _LEAGUE_CONFIG as cfg
    inputs = inputs or kh.Inputs.load(root)
    mat = json.loads((root / "data" / "historical" / "all_matchups.json").read_text(encoding="utf-8"))
    lp = M.level_config(M.load_params())
    q = A.replacement_quantile(cfg)
    tie = float(regular_season_tie_value())
    picks = DH.read(root)
    out = []
    for s in seasons(root):
        inp = AP.season_inputs(inputs, s, mat, cfg=cfg, lp=lp, quantile=q, tie=tie)
        reg_end = str(A._week(inp, inp["reg"])["end_date"])[:10]
        R = A.replacement_levels(inp, reg_end)
        names = kh.Names(inp["rows"])
        starts: dict = {}
        for r in inp["rows"]:
            if pick_game(r, inp["reg"]):
                starts.setdefault((r["player_name"], r["manager"]), []).append(r)
        live = DH.live_rounds(s)
        for p in DH.order(s, picks):
            if p.get("is_keeper"):
                continue
            if int(p["round"]) > live:
                raise DraftValuesError(f"{s}: {p['player_name']} is a live pick in round {p['round']}, "
                                       f"past the draft's {live} live rounds")
            n = names.canon(p["player_name"], p.get("player_key")) or p["player_name"]
            games = starts.get((n, p["manager"]), [])
            out.append({"season": s, "round": int(p["round"]), "pick_number": int(p["pick_number"]),
                        "manager": p["manager"], "player": p["player_name"], "starts": len(games),
                        "par": round(sum(float(r["fantasy_points"]) - R[int(r["week"])]["R"] for r in games), 3),
                        "fp": round(sum(float(r["fantasy_points"]) for r in games), 3)})
    return out


# ---------------------------------------------------------------------------
# the curve and the shrinkage
# ---------------------------------------------------------------------------

def _measure(line: dict, m: str):
    if m == "par":
        return line["par"]
    if m == "total_fp":
        return line["fp"]
    return line["fp"] / line["starts"] if line["starts"] >= MIN_GP else None


def _wls_log(rounds: list, means: list, ns: list) -> tuple:
    """(a, b) for mean = a + b * ln(round), weighted by n."""
    x = [math.log(r) for r in rounds]
    w = [float(n) for n in ns]
    sw = sum(w)
    xb = sum(wi * xi for wi, xi in zip(w, x)) / sw
    yb = sum(wi * yi for wi, yi in zip(w, means)) / sw
    sxx = sum(wi * (xi - xb) ** 2 for wi, xi in zip(w, x))
    if sxx == 0:
        return yb, 0.0
    b = sum(wi * (xi - xb) * (yi - yb) for wi, xi, yi in zip(w, x, means)) / sxx
    return yb - b * xb, b


def round_values(lines: list, max_round: int) -> dict:
    """{measure: {"curve": {"a", "b"}, "k", "tau2", "s2", "rounds": {round: {...}}}}."""
    out = {}
    for m in MEASURES:
        by: dict = {}
        for ln in lines:
            v = _measure(ln, m)
            if v is not None:
                by.setdefault(ln["round"], []).append(float(v))
        rs = sorted(by)
        if len(rs) < 2:
            raise DraftValuesError(f"{m}: data in {len(rs)} round(s); the curve needs two")
        means = [sum(by[r]) / len(by[r]) for r in rs]
        ns = [len(by[r]) for r in rs]
        a, b = _wls_log(rs, means, ns)
        resid_ss = sum((v - sum(by[r]) / len(by[r])) ** 2 for r in rs for v in by[r])
        dof = sum(ns) - len(rs)
        s2 = resid_ss / dof if dof > 0 else 0.0
        curve = {r: a + b * math.log(r) for r in range(1, max_round + 1)}
        dev = [(mu - curve[r]) ** 2 - s2 / n for r, mu, n in zip(rs, means, ns)]
        tau2 = sum(dev) / len(dev)
        k = None if tau2 <= 0 else s2 / tau2
        rounds = {}
        for r in range(1, max_round + 1):
            if r in by:
                n, mu = len(by[r]), sum(by[r]) / len(by[r])
                val = curve[r] if k is None else (n * mu + k * curve[r]) / (n + k)
                sd = (sum((v - mu) ** 2 for v in by[r]) / (n - 1)) ** 0.5 if n > 1 else None
                rounds[str(r)] = {"value": round(val, 2), "n": n, "mean": round(mu, 2),
                                  "sd": None if sd is None else round(sd, 2), "curve": round(curve[r], 2),
                                  "basis": f"data ({n} picks), shrunk toward the curve"}
            else:
                rounds[str(r)] = {"value": round(curve[r], 2), "n": 0, "mean": None, "sd": None,
                                  "curve": round(curve[r], 2), "basis": "curve (no data)"}
        out[m] = {"curve": {"a": round(a, 4), "b": round(b, 4), "form": "a + b * ln(round)"},
                  "s2": round(s2, 3), "tau2": round(tau2, 3), "k": None if k is None else round(k, 3),
                  "rounds": rounds}
    return out


def build(root=ROOT, inputs=None) -> dict:
    from . import draft_history as DH
    lines = pick_lines(root, inputs)
    if not lines:
        raise DraftValuesError("no finished draft with a trusted order")
    r = DH.rules()
    deepest = max([int(v) for v in r["live_rounds"].values()] + [int(r["live_rounds_default"]["rounds"])])
    used = sorted({ln["season"] for ln in lines})
    return {"schema": SCHEMA, "drafts": used, "picks": len(lines), "min_gp_fppg": MIN_GP,
            "measures": round_values(lines, deepest), "lines": lines,
            "note": ("H56 s.4.3 (Nick 11-21: one curve). Each live pick of the drafts above, over his started "
                     "games for the manager who drafted him, regular season: PAR (Trade of the Year's unit), "
                     "FPPG (5+ games) and total points. Each round's mean is shrunk toward a log curve across "
                     "rounds; a round without data takes the curve. Built by scripts/build_draft_round_values.py.")}


def load(root=ROOT) -> dict:
    p = Path(root) / FILE
    if not p.is_file():
        raise DraftValuesError(f"{FILE} is missing: python scripts/build_draft_round_values.py")
    obj = json.loads(p.read_text(encoding="utf-8"))
    if obj.get("schema") != SCHEMA:
        raise DraftValuesError(f"{FILE} is schema {obj.get('schema')}, not {SCHEMA}")
    return obj


def value(table: dict, measure: str, rnd: int) -> dict:
    """{"value", "n", "basis"} for a live round. RAISES for a round the table
    lacks (a keeper round, or past the deepest live round)."""
    if measure not in MEASURES:
        raise DraftValuesError(f"unknown measure {measure!r}")
    row = table["measures"][measure]["rounds"].get(str(int(rnd)))
    if row is None:
        raise DraftValuesError(f"round {rnd} has no {measure} value (not a live round)")
    return row
