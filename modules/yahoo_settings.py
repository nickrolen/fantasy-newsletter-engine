"""
yahoo_settings.py -- the Yahoo league settings the engine models, checked.

WHY (claude/SELF_RUNNING_DESIGN.md s.4, s.6.1a, invariant 9). Nick made
Hayden, Garrett and Benton co-commissioners on 10-30, so a setting can now
change in Yahoo without him. The engine models some of those settings -- the
roster, the weeks, the add limit, the scoring -- and a change it does not know
about would make every number quietly wrong. So every run of record reads the
settings (read-only: league/<key>/settings) and compares every modelled one
with config/league_config.json. Any difference REFUSES, naming it:

    "Yahoo setting X changed from A to B; update config or revert in Yahoo."

and a modelled setting missing from Yahoo's response raises too. Nothing is
ever defaulted, and config is never edited to match.

WHAT IS COMPARED (expected() and found() build the same keys):
    num_teams          league_structure.num_teams
    roster             position -> count: lineup_optimizer.STARTER_SLOTS for
                       the starters, league_structure.bench as BN and
                       .il_slots as IL; their total is .roster_size
    weeks              start/end week and date: season.total_weeks and
                       config/SCHEDULE.json's first and last week
    max_weekly_adds    roster_moves.yahoo_max_adds_setting (6, not the
                       league's weekly_add_budget of 3: rule 7)
    scoring_type, uses_playoff, waiver_time_days, uses_faab,
    can_trade_draft_picks, stat_values      yahoo_settings.* (the scoring
                       categories and their fantasy-point values)
    trade_deadline     yahoo_settings.trade_deadline vs Yahoo's trade_end_date
                       (Nick, 10-31: the engine knows the deadline)
Settings the engine has no rule for are listed in yahoo_settings._unchecked.

The account's identifiers (league password, edit key, chat and invitation
links) are never kept: scrub() keeps only what is compared, which is how the
test fixture was made.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class SettingsDrift(RuntimeError):
    """A modelled setting differs between Yahoo and the config."""


class SettingMissing(RuntimeError):
    """A modelled setting is missing from Yahoo's response or from the config."""


def _need(d: dict, key: str, where: str):
    if not isinstance(d, dict) or key not in d:
        raise SettingMissing(f"{where} has no {key!r}: a setting the engine models must be "
                             "stated, never defaulted")
    return d[key]


def _bool(v, where):
    if isinstance(v, bool):
        return v
    if str(v) in ("0", "1"):
        return str(v) == "1"
    raise SettingMissing(f"{where}: {v!r} is not a yes/no value")


# ============================================================================ Yahoo's side

def _parts(raw: dict):
    try:
        league = raw["fantasy_content"]["league"]
        meta, settings = league[0], league[1]["settings"][0]
    except (KeyError, IndexError, TypeError):
        raise SettingMissing("the response is not league/<key>/settings "
                             "(fantasy_content.league[0], [1].settings[0])") from None
    return meta, settings


def found(raw: dict) -> dict:
    """The modelled settings as Yahoo states them."""
    meta, st = _parts(raw)
    y = "Yahoo's response"
    roster = {}
    for rp in _need(st, "roster_positions", y):
        pos = rp["roster_position"]
        roster[str(pos["position"]).upper()] = int(pos["count"])
    mods = {}
    for s in _need(_need(st, "stat_modifiers", y), "stats", y + " stat_modifiers"):
        mods[int(s["stat"]["stat_id"])] = float(s["stat"]["value"])
    values = {}
    for s in _need(_need(st, "stat_categories", y), "stats", y + " stat_categories"):
        c = s["stat"]
        if str(c.get("enabled", "1")) != "1" or c.get("is_only_display_stat") in ("1", 1):
            continue
        sid = int(c["stat_id"])
        if sid not in mods:
            raise SettingMissing(f"{y}: scoring category {c.get('abbr')} has no value")
        values[str(c["abbr"])] = mods[sid]
    return {
        "num_teams": int(_need(meta, "num_teams", y)),
        "roster": roster,
        "weeks": {"start_week": int(_need(meta, "start_week", y)),
                  "end_week": int(_need(meta, "end_week", y)),
                  "start_date": str(_need(meta, "start_date", y)),
                  "end_date": str(_need(meta, "end_date", y))},
        "max_weekly_adds": int(_need(st, "max_weekly_adds", y)),
        "scoring_type": str(_need(st, "scoring_type", y)),
        "uses_playoff": _bool(_need(st, "uses_playoff", y), "uses_playoff"),
        "waiver_time_days": int(_need(st, "waiver_time", y)),
        "uses_faab": _bool(_need(st, "uses_faab", y), "uses_faab"),
        "can_trade_draft_picks": _bool(_need(st, "can_trade_draft_picks", y),
                                       "can_trade_draft_picks"),
        "trade_deadline": str(_need(st, "trade_end_date", y)),
        "stat_values": values,
    }


SCRUB_META = ("num_teams", "start_week", "end_week", "start_date", "end_date")
SCRUB_SETTINGS = ("roster_positions", "stat_categories", "stat_modifiers", "max_weekly_adds",
                  "scoring_type", "uses_playoff", "waiver_time", "uses_faab",
                  "can_trade_draft_picks", "trade_end_date")


def scrub(raw: dict) -> dict:
    """The response with only the compared fields: no league name, key,
    password, edit key, links or chat ids. What the test fixture holds."""
    meta, st = _parts(raw)
    return {"fantasy_content": {"league": [
        {k: meta[k] for k in SCRUB_META if k in meta},
        {"settings": [{k: st[k] for k in SCRUB_SETTINGS if k in st}]}]}}


# ============================================================================ the config's side

def expected(cfg: dict = None, schedule: dict = None) -> dict:
    """The same keys as found(), from config/league_config.json and
    config/SCHEDULE.json. A missing key raises."""
    if cfg is None:
        cfg = json.loads((ROOT / "config" / "league_config.json").read_text(encoding="utf-8"))
    if schedule is None:
        schedule = json.loads((ROOT / "config" / "SCHEDULE.json").read_text(encoding="utf-8"))
    from .lineup_optimizer import STARTER_SLOTS
    c = "config/league_config.json"
    ls = _need(cfg, "league_structure", c)
    rm = _need(cfg, "roster_moves", c)
    ys = _need(cfg, "yahoo_settings", c)
    season = _need(cfg, "season", c)
    roster = {}
    for slot in STARTER_SLOTS:
        roster[slot.upper()] = roster.get(slot.upper(), 0) + 1
    roster["BN"] = int(_need(ls, "bench", c + " league_structure"))
    roster["IL"] = int(_need(ls, "il_slots", c + " league_structure"))
    size = int(_need(ls, "roster_size", c + " league_structure"))
    if sum(roster.values()) != size:
        raise SettingMissing(f"{c}: the starters, bench and IL slots add up to "
                             f"{sum(roster.values())}, not roster_size {size}")
    weeks = sorted(schedule.get("weeks", []), key=lambda w: int(w["week"]))
    if not weeks:
        raise SettingMissing("config/SCHEDULE.json has no weeks")
    total = int(_need(season, "total_weeks", c + " season"))
    if int(weeks[-1]["week"]) != total:
        raise SettingMissing(f"config/SCHEDULE.json ends at week {weeks[-1]['week']}, "
                             f"season.total_weeks is {total}")
    return {
        "num_teams": int(_need(ls, "num_teams", c + " league_structure")),
        "roster": roster,
        "weeks": {"start_week": int(weeks[0]["week"]), "end_week": total,
                  "start_date": str(weeks[0]["start_date"])[:10],
                  "end_date": str(weeks[-1]["end_date"])[:10]},
        "max_weekly_adds": int(_need(rm, "yahoo_max_adds_setting", c + " roster_moves")),
        "scoring_type": str(_need(ys, "scoring_type", c + " yahoo_settings")),
        "uses_playoff": bool(_need(ys, "uses_playoff", c + " yahoo_settings")),
        "waiver_time_days": int(_need(ys, "waiver_time_days", c + " yahoo_settings")),
        "uses_faab": bool(_need(ys, "uses_faab", c + " yahoo_settings")),
        "can_trade_draft_picks": bool(_need(ys, "can_trade_draft_picks", c + " yahoo_settings")),
        "trade_deadline": str(_need(ys, "trade_deadline", c + " yahoo_settings")),
        "stat_values": {str(k): float(v) for k, v in
                        _need(ys, "stat_values", c + " yahoo_settings").items()},
    }


# ============================================================================ the check

def differences(want: dict, got: dict) -> list:
    """["setting: config A, Yahoo B", ...] for every modelled setting that
    differs, nested ones named by their path (roster.C, stat_values.TO)."""
    out = []
    for key in sorted(set(want) | set(got)):
        a, b = want.get(key), got.get(key)
        if isinstance(a, dict) and isinstance(b, dict):
            for sub in sorted(set(a) | set(b)):
                if a.get(sub) != b.get(sub):
                    out.append((f"{key}.{sub}", a.get(sub, "(absent)"), b.get(sub, "(absent)")))
        elif a != b:
            out.append((key, a, b))
    return out


def check(raw: dict, cfg: dict = None, schedule: dict = None) -> dict:
    """The comparison. Returns {setting: value} (what was compared, all
    equal); raises SettingsDrift naming every difference."""
    want, got = expected(cfg, schedule), found(raw)
    diff = differences(want, got)
    if diff:
        raise SettingsDrift("\n".join(
            f"Yahoo setting {k} changed from {a!r} to {b!r}; update config or revert in Yahoo."
            for k, a, b in diff))
    return got


def fetch_raw(base_path=None) -> dict:
    """ONE read-only call, league/<key>/settings, through the same OAuth file
    and library every Yahoo script uses. The token is never read here."""
    import os
    from yahoo_oauth import OAuth2
    import yahoo_fantasy_api as yfa
    from .data_loader import LEAGUE_KEY
    base = Path(base_path or ROOT)
    cwd = os.getcwd()
    try:
        os.chdir(base)                       # yahoo_oauth writes a refreshed token beside it
        oauth = OAuth2(None, None, from_file="oauth2.json")
        return yfa.League(oauth, LEAGUE_KEY).yhandler.get_settings_raw(LEAGUE_KEY)
    finally:
        os.chdir(cwd)
