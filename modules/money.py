"""
money.py -- who paid whom, season by season (MC2; LEAGUE_RULES "Payouts by
season", Nick 11-23). THE ONE READER of config payouts_by_season.

Two pots a season, never added to anything else (LEAGUE_RULES "Stakes and
currencies": money and the keeper have no exchange rate):

    regular season  by the regular-season finish (the League Champion first)
    playoffs        the Playoff Champion, the runner-up, the semifinal losers

    2014-15 to 2025-26: +$150 to the League Champion, -$50 each from the
    other three; +$75 to the Playoff Champion, -$25 each from the other three.
    2026-27 on: +$180 / $0 / -$90 / -$90; +$90 to the Playoff Champion, $0 to
    the runner-up, -$45 each from the semifinal losers. The Cup: no money.

table(season) -> the season's range (RAISES for a season outside every range)
nets(season, reg_order, bracket) -> {manager: {"regular": int, "playoffs": int|None}}

A pot that has not been decided is not on the card: the caller passes only
finished pots (no projection here; projections are the hub's Money view).
Every season's nets sum to zero across the four managers (a test checks it).
"""
from __future__ import annotations

from typing import Optional

REG_KEYS = ("1", "2", "3", "4")
PO_KEYS = ("champion", "runner_up", "semifinal_loser")


class MoneyError(RuntimeError):
    """A payout fact is missing or contradictory; named."""


def _cfg(cfg: Optional[dict] = None) -> dict:
    if cfg is None:
        from .data_loader import _LEAGUE_CONFIG as cfg
    blk = cfg.get("payouts_by_season")
    if not isinstance(blk, dict) or not isinstance(blk.get("ranges"), list) or not blk["ranges"]:
        raise MoneyError("league_config payouts_by_season.ranges is missing (LEAGUE_RULES 'Payouts by season')")
    return blk


def _season_start(s: str) -> int:
    try:
        y = int(str(s)[:4])
    except ValueError:
        raise MoneyError(f"{s!r} is not a season key like 2025-26") from None
    if len(str(s)) != 7 or str(s)[4] != "-":
        raise MoneyError(f"{s!r} is not a season key like 2025-26")
    return y


def table(season: str, cfg: Optional[dict] = None) -> dict:
    """The season's payouts: {"regular_season": {"1".."4": net}, "playoffs":
    {"champion", "runner_up", "semifinal_loser": net}}. RAISES (MoneyError)
    for a season no range covers, two ranges covering it, or a malformed or
    non-zero-sum range."""
    y = _season_start(season)
    hits = []
    for r in _cfg(cfg)["ranges"]:
        lo = _season_start(r.get("from"))
        hi = None if r.get("to") is None else _season_start(r["to"])
        if lo <= y and (hi is None or y <= hi):
            hits.append(r)
    if not hits:
        raise MoneyError(f"league_config payouts_by_season has no range for {season}")
    if len(hits) > 1:
        raise MoneyError(f"league_config payouts_by_season has {len(hits)} ranges for {season}")
    r = hits[0]
    rs, po = r.get("regular_season"), r.get("playoffs")
    if not isinstance(rs, dict) or sorted(rs) != sorted(REG_KEYS):
        raise MoneyError(f"payouts_by_season {r.get('from')}: regular_season needs exactly {REG_KEYS}")
    if not isinstance(po, dict) or sorted(po) != sorted(PO_KEYS):
        raise MoneyError(f"payouts_by_season {r.get('from')}: playoffs needs exactly {PO_KEYS}")
    for k, v in list(rs.items()) + list(po.items()):
        if isinstance(v, bool) or not isinstance(v, int):
            raise MoneyError(f"payouts_by_season {r.get('from')}: {k} {v!r} is not whole dollars")
    if sum(rs.values()) != 0:
        raise MoneyError(f"payouts_by_season {r.get('from')}: the regular season's nets sum to {sum(rs.values())}")
    if po["champion"] + po["runner_up"] + 2 * po["semifinal_loser"] != 0:
        raise MoneyError(f"payouts_by_season {r.get('from')}: the playoffs' nets do not sum to zero")
    return {"regular_season": dict(rs), "playoffs": dict(po)}


def nets(season: str, reg_order: list, bracket: Optional[dict], cfg: Optional[dict] = None) -> dict:
    """{manager: {"regular": net, "playoffs": net or None}} for one finished
    season. reg_order: the regular-season finish, 1st to 4th (None: the
    regular season is not decided; no regular-season money). bracket:
    {"champion", "runner_up", "semifinal_losers": [two]} or None (no bracket
    played, or not decided yet: no playoff money)."""
    t = table(season, cfg)
    managers = list(reg_order or [])
    if bracket is not None:
        managers = managers or [bracket["champion"], bracket["runner_up"], *bracket["semifinal_losers"]]
    out = {m: {"regular": None, "playoffs": None} for m in managers}
    if reg_order:
        if len(reg_order) != 4 or len(set(reg_order)) != 4:
            raise MoneyError(f"{season}: the regular-season finish {reg_order} is not four managers")
        for i, m in enumerate(reg_order):
            out[m]["regular"] = t["regular_season"][str(i + 1)]
    if bracket is not None:
        who = [bracket["champion"], bracket["runner_up"], *bracket["semifinal_losers"]]
        if len(who) != 4 or len(set(who)) != 4 or set(who) != set(out):
            raise MoneyError(f"{season}: the bracket {bracket} is not the season's four managers")
        po = t["playoffs"]
        out[bracket["champion"]]["playoffs"] = po["champion"]
        out[bracket["runner_up"]]["playoffs"] = po["runner_up"]
        for m in bracket["semifinal_losers"]:
            out[m]["playoffs"] = po["semifinal_loser"]
    for k in ("regular", "playoffs"):
        vals = [v[k] for v in out.values() if v[k] is not None]
        if vals and sum(vals) != 0:
            raise MoneyError(f"{season}: the {k} nets sum to {sum(vals)}, not zero")
    return out


def check_engine_payouts(season: str, cfg: Optional[dict] = None) -> None:
    """The season's range must equal config 'payouts' (the engine's own
    amounts for the current season: angles, standing threads, the sim).
    RAISES on any difference."""
    if cfg is None:
        from .data_loader import _LEAGUE_CONFIG as cfg
    t = table(season, cfg)
    p = cfg["payouts"]
    lc, pc = p["league_champion"], p["playoff_champion"]
    want = {"1": int(lc["total"]), "3": -int(lc["per_payer"]), "4": -int(lc["per_payer"])}
    got = {k: t["regular_season"][k] for k in want}
    if got != want or t["regular_season"]["2"] != 0:
        raise MoneyError(f"payouts_by_season {season} regular season {t['regular_season']} disagrees with "
                         f"payouts.league_champion ({lc['total']}, {lc['per_payer']} each from 3rd and 4th)")
    po = t["playoffs"]
    if (po["champion"], po["semifinal_loser"], po["runner_up"]) != (int(pc["total"]), -int(pc["per_payer"]), 0):
        raise MoneyError(f"payouts_by_season {season} playoffs {po} disagree with payouts.playoff_champion "
                         f"({pc['total']}, {pc['per_payer']} each from the semifinal losers)")


def dollars(v: int) -> str:
    """+$150, −$50, $0."""
    if v > 0:
        return f"+${v:,}"
    if v < 0:
        return f"−${-v:,}"
    return "$0"
