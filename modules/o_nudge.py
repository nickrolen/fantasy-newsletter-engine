"""
o_nudge.py -- the O-past-3-games nudge (step 3b, s.3;
claude/HANDOFF_STEP3B_TAG_FRESHNESS_2026-11-10.md).

THE RULE. A player tagged O who has missed MORE than live_refresh.o_nudge.
more_than_games (3) of his NBA team's games, with NO injury entry, gets one
issue: "Zion Williamson has been O for 5 games with no injury entry", its body
the phone form ready to copy (`Injury: Zion Williamson <notes>, back MM/DD`).
An O tag alone costs at most three games (absence.MAX_TAG_GAMES), so a longer
absence is invisible to the engine until it has an entry; and since 48f an O
without an entry is hidden from the hub's stash. Run by the nightly only.

WHO: every rostered player, and the free agents a stash row could show: O,
projected FPPG at or above live_refresh.o_nudge.free_agent_min_projected_fppg
(a config threshold rather than "the lowest stash row's", which is undefined
on a night the stash is empty).

COUNTING HIS GAMES -- from data the engine already has; never a guessed number:
  ROSTERED: data/player_actuals.json (Yahoo's game-scoped daily line, "games
    played" 1 or 0, cached per finished league day for every rostered player).
    His last game played is the latest day with games 1; the count is his NBA
    team's games (the NBA schedule) after that day through yesterday. Exact.
    If the cache does not reach yesterday for him, or has no day for him, the
    count can't be made and the issue says so.
  FREE AGENTS: the engine keeps no game log for them (PLAYERLIST has no games
    played; player_actuals covers rostered players). What it does keep is every
    run's Yahoo tags, free agents included (output/tag_records.jsonl). His O
    streak's start is the earliest record of an unbroken run of O records
    ending with tonight's; the count is his team's games on the days after
    that record's league day through yesterday: a LOWER BOUND (he may have
    been out before the tag appeared), stated as "at least N". A lower bound
    of more_than_games or fewer proves nothing, so it opens nothing.
  A player whose NBA team or schedule is unknown: the issue says "can't count
  his games" and why.

ONE ISSUE PER PLAYER: the workflow (scripts/nudge_issue.py, label o-no-entry)
matches an open issue by the player, not by the whole title: the count in the
title grows every night, and matching the whole title would open a new issue
each night. An open one whose count changed gets its title edited; an open one
the night no longer lists (he has an entry, or is no longer O) is closed.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path


class NudgeConfigError(KeyError):
    pass


def config(cfg: dict = None) -> dict:
    if cfg is None:
        from .data_loader import _LEAGUE_CONFIG
        cfg = _LEAGUE_CONFIG
    blob = (cfg.get("live_refresh") or {}).get("o_nudge")
    if not isinstance(blob, dict):
        raise NudgeConfigError("config/league_config.json has no live_refresh.o_nudge")
    try:
        return {"more_than": int(blob["more_than_games"]),
                "fa_min": float(blob["free_agent_min_projected_fppg"])}
    except (KeyError, TypeError, ValueError) as e:
        raise NudgeConfigError(f"config live_refresh.o_nudge is incomplete or malformed ({e})") from None


def title(name: str, count, at_least: bool = False) -> str:
    if count is None:
        return f"{name} is tagged O with no injury entry: can't count his games"
    return f"{name} has been O for {'at least ' if at_least else ''}{count} games with no injury entry"


def title_matches(issue_title: str, name: str) -> bool:
    """Is an open issue's title this player's nudge (whatever its count)?"""
    t = str(issue_title)
    return t.startswith(f"{name} has been O for ") or t == title(name, None)


def body(name: str, why: str) -> str:
    return (f"{why}\n\nAdd his injury entry from your phone: open an issue in this repo titled\n\n"
            f"`Injury: {name} <notes>, back MM/DD`\n\n(or `Injury: {name} <notes>, out for season`). "
            "This issue closes by itself the night after he has an entry or is no longer tagged O.")


def _tag_is_o(tag) -> bool:
    from . import absence
    return tag is not None and absence.normalised_tag(tag) == "O"


def rostered_count(actuals: dict, name: str, team_dates: list, yesterday: date) -> tuple:
    """(count or None, why): his team's games after his last game played,
    through yesterday, from player_actuals. None when the cache can't say."""
    from .data_loader import PlayerIndex
    ids = PlayerIndex(dict(actuals.get("roster_names") or {}))
    pid = ids.get(name)
    rec = (actuals.get("players") or {}).get(str(pid)) if pid is not None else None
    if rec is None:
        return None, "data/player_actuals.json has no daily line for him"
    days = {date.fromisoformat(d): v for d, v in (rec.get("days") or {}).items()}
    if not days or max(days) < yesterday:
        last = max(days).isoformat() if days else "none"
        return None, (f"data/player_actuals.json reaches {last} for him, not yesterday "
                      f"({yesterday.isoformat()})")
    played = [d for d, v in days.items() if str(v[1]) == "1"]
    since = max(played) if played else None
    n = sum(1 for d in team_dates if (since is None or d > since) and d <= yesterday)
    why = (f"His team has played {n} games since his last game ({since:%a %m-%d})" if since else
           f"His team has played {n} games this season and he has played none of them")
    return n, why + " (data/player_actuals.json, Yahoo's daily games played)."


def o_since(records: list, name: str):
    """The league day of the earliest record of his unbroken O streak that
    ends with the latest record, or None (not O in the latest)."""
    from .data_loader import PlayerIndex
    start = None
    for r in sorted(records, key=lambda r: r["taken_at"], reverse=True):
        t = r.get("tags") or {}
        tag = PlayerIndex(dict(t.get("rostered") or {})).get(name)
        if tag is None:
            tag = PlayerIndex(dict(t.get("free_agents") or {})).get(name)
        if not _tag_is_o(tag):
            break
        start = date.fromisoformat(r["league_day"])
    return start


def find(base_path, tags, today: date, *, data=None, records: list = None, actuals: dict = None,
         cfg: dict = None) -> list:
    """[{player, scope, count, at_least, why, title, body}] for tonight."""
    from . import tag_records, player_actuals as pa
    from .data_loader import PlayerIndex, load_all_data
    from .schedule_strength import build_player_info_map
    from .simulator_betting import team_season_dates
    c = config(cfg)
    base = Path(base_path)
    data = data or load_all_data(base, current_week=None)
    yesterday = today - timedelta(days=1)
    rosters = {m: list(v) for m, v in data.get_current_rosters().items()}
    entries = PlayerIndex({e["player_name"]: e for e in (data.injury_overrides or {}).get("players", [])})
    info = build_player_info_map(data.playerlist)
    teams = team_season_dates(data)
    records = records if records is not None else tag_records.read(base)
    actuals = actuals if actuals is not None else pa.load(base, required=False)
    out = []

    def team_dates_of(name):
        i = info.get(name)
        t = (i or {}).get("nba_team")
        return (str(t).upper(), teams.get(str(t).upper())) if t else (None, None)

    rostered = [n for v in rosters.values() for n in v]
    rtags = PlayerIndex(dict(tags))
    for n in rostered:
        if not _tag_is_o(rtags.get(n)) or entries.get(n) is not None:
            continue
        code, dates = team_dates_of(n)
        if not dates:
            cnt, why = None, f"can't count his games: his NBA team ({code or 'unknown'}) has no schedule"
        elif actuals is None:
            cnt, why = None, "can't count his games: data/player_actuals.json is missing"
        else:
            cnt, why = rostered_count(actuals, n, dates, yesterday)
            if cnt is None:
                why = f"can't count his games: {why}"
        if cnt is not None and cnt <= c["more_than"]:
            continue
        out.append({"player": n, "scope": "rostered", "count": cnt, "at_least": False, "why": why})
    fa = getattr(tags, "free_agents", None) or {}
    proj = PlayerIndex({r["player_name"]: float(r["projectedFPPG"]) for r in
                        data.playerlist.to_dict("records") if isinstance(r.get("player_name"), str)})
    for n, tag in dict(fa).items():
        if not _tag_is_o(tag) or entries.get(n) is not None or PlayerIndex({x: 1 for x in rostered}).get(n):
            continue
        p = proj.get(n)
        if p is None or p < c["fa_min"]:
            continue
        code, dates = team_dates_of(n)
        if not dates:
            out.append({"player": n, "scope": "free agent", "count": None, "at_least": False,
                        "why": f"can't count his games: his NBA team ({code or 'unknown'}) has no schedule"})
            continue
        start = o_since(records, n)
        if start is None:
            continue                                     # not O in the latest record
        cnt = sum(1 for d in dates if start < d <= yesterday)
        if cnt <= c["more_than"]:
            continue
        out.append({"player": n, "scope": "free agent", "count": cnt, "at_least": True,
                    "why": (f"A free agent (projected {p:.1f} FPPG). His team has played at least {cnt} "
                            f"games since he was first seen tagged O on {start:%a %m-%d} "
                            "(output/tag_records.jsonl; the engine keeps no game log for free agents, "
                            "so this is a lower bound).")})
    for x in out:
        x["title"] = title(x["player"], x["count"], x["at_least"])
        x["body"] = body(x["player"], x["why"])
    return sorted(out, key=lambda x: x["player"])
