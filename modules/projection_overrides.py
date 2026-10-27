"""Projection overrides: a patch on a Yahoo row that is wrong upstream.

WHY A FILE, NOT AN EDIT
-----------------------
On 2026-10-26 Yahoo's rest-of-season view (S_PSR, the one fetch_playerlist
scrapes) gave two healthy ROSTERED rookies 0 GP and 0.00 FP -- Cameron Boozer
(Benton) and Darius Acuff Jr. (Hayden) -- while its next-7-days view (S_PS7)
projected them 99.51 FP and 92.73 FP over 3 games. Every simulation valued
both at zero, which moved the week-2 spreads by 78 and 90 points
(HANDOFF_STALE_GATES_2026-10-26 sec.4).

Hand-editing data/PLAYERLIST.xlsx would not survive: fetch_playerlist --execute
rewrites it every week, so the patch would vanish silently at the next refresh.
So the patch lives here, fetch_playerlist applies it AFTER parsing and BEFORE
writing, and check_playerlist says which overrides are live and FAILS on one
that is past its review date or whose Yahoo row has changed since it was
written -- a temporary patch cannot become permanent by inattention.

AN ENTRY
--------
    yahoo_id     the key; a name can be respelled, an id cannot
    player_name  for people, and checked against the row: a mismatch is not applied
    set          the fields replaced:
                   projectedFPPG    a number
                   player_proj_GP   a number, or "team": the most games
                                    remaining Yahoo projects for any teammate
                                    in the same fetch (a healthy player's
                                    figure, and it does not go stale between
                                    fetches the way a typed number would)
                 player_total_proj_FP is never set: it is derived, FPPG x GP,
                 the same arithmetic check_playerlist verifies
    replaces     the Yahoo values the entry was written against. If Yahoo's
                 row no longer says this, upstream may be fixed: the override
                 still applies, and check_playerlist fails until it is reviewed
    reason, source, added, review_by (YYYY-MM-DD)
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OVERRIDES_PATH = PROJECT_ROOT / "config" / "PROJECTION_OVERRIDES.json"
SETTABLE = ("projectedFPPG", "player_proj_GP")
REQUIRED = ("yahoo_id", "player_name", "set", "replaces", "reason", "source", "review_by")
STAMP_KEY = "overrides"


class OverrideError(ValueError):
    """The overrides file is malformed. Raised, never skipped: a patch that
    silently fails to load is a zero that silently comes back."""


def load(path: Optional[Path] = None) -> list:
    """The validated entries. A missing file is no overrides; a broken one raises."""
    path = Path(path or OVERRIDES_PATH)
    if not path.is_file():
        return []
    try:
        blob = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise OverrideError(f"{path.name} is unreadable: {e}") from e
    entries = blob.get("overrides")
    if not isinstance(entries, list):
        raise OverrideError(f"{path.name} has no 'overrides' list")
    seen = set()
    for i, e in enumerate(entries):
        where = f"{path.name} entry {i} ({e.get('player_name', '?')})"
        missing = [k for k in REQUIRED if k not in e]
        if missing:
            raise OverrideError(f"{where} is missing {missing}")
        e["yahoo_id"] = str(e["yahoo_id"])
        if e["yahoo_id"] in seen:
            raise OverrideError(f"{where}: yahoo_id {e['yahoo_id']} appears twice")
        seen.add(e["yahoo_id"])
        if not e["set"] or set(e["set"]) - set(SETTABLE):
            raise OverrideError(f"{where}: 'set' may only name {SETTABLE} "
                                "(total FP is derived, FPPG x GP)")
        fppg = e["set"].get("projectedFPPG")
        if fppg is not None and not (isinstance(fppg, (int, float)) and fppg > 0):
            raise OverrideError(f"{where}: projectedFPPG must be a positive number")
        gp = e["set"].get("player_proj_GP")
        if gp is not None and gp != "team" and not (isinstance(gp, (int, float)) and gp >= 0):
            raise OverrideError(f"{where}: player_proj_GP must be a number or \"team\"")
        try:
            e["review_by"] = date.fromisoformat(str(e["review_by"])).isoformat()
        except ValueError:
            raise OverrideError(f"{where}: review_by {e['review_by']!r} is not YYYY-MM-DD")
    return entries


def _num(v) -> float:
    try:
        return float(str(v).replace(",", ""))
    except (TypeError, ValueError):
        return float("nan")


def apply(records: list, entries: list) -> tuple:
    """Patch fetch records in place. (applied, unapplied), both JSON-ready.

    records: fetch_playerlist's dicts -- _yahoo_id, player_name,
    player_nba_team, player_proj_GP, player_total_proj_FP, projectedFPPG.
    Each applied item keeps what Yahoo said, so the stamp (and every snapshot
    copied from the file) still records the upstream row.
    """
    from modules.data_loader import PlayerIndex
    by_id = {str(r.get("_yahoo_id")): r for r in records}
    applied, unapplied = [], []
    for e in entries:
        row = by_id.get(e["yahoo_id"])
        if row is None:
            unapplied.append({"yahoo_id": e["yahoo_id"], "player_name": e["player_name"],
                              "why": "not in this fetch"})
            continue
        if e["player_name"] not in PlayerIndex({row["player_name"]: 1}):
            unapplied.append({"yahoo_id": e["yahoo_id"], "player_name": e["player_name"],
                              "why": f"yahoo id {e['yahoo_id']} is {row['player_name']!r} in this fetch"})
            continue
        yahoo = {k: _num(row[k]) for k in ("player_proj_GP", "player_total_proj_FP", "projectedFPPG")}
        gp = e["set"].get("player_proj_GP", yahoo["player_proj_GP"])
        if gp == "team":
            mates = [_num(r["player_proj_GP"]) for r in records
                     if r is not row and r.get("player_nba_team") == row.get("player_nba_team")]
            mates = [g for g in mates if g == g]
            if not mates:
                unapplied.append({"yahoo_id": e["yahoo_id"], "player_name": e["player_name"],
                                  "why": f"GP 'team', and no {row.get('player_nba_team')} teammate in this fetch"})
                continue
            gp = max(mates)
        fppg = e["set"].get("projectedFPPG", yahoo["projectedFPPG"])
        row["player_proj_GP"] = float(gp)
        row["projectedFPPG"] = round(float(fppg), 2)
        row["player_total_proj_FP"] = round(float(fppg) * float(gp), 2)
        matches = all(abs(_num(v) - yahoo[k]) < 1e-6 for k, v in e["replaces"].items() if k in yahoo)
        applied.append({
            "yahoo_id": e["yahoo_id"], "player_name": row["player_name"],
            "yahoo": yahoo,
            "now": {k: row[k] for k in ("player_proj_GP", "player_total_proj_FP", "projectedFPPG")},
            "replaces": e["replaces"], "replaces_matches": bool(matches),
            "reason": e["reason"], "review_by": e["review_by"],
        })
    return applied, unapplied


def stamp_value(applied: list, unapplied: list) -> str:
    return json.dumps({"applied": applied, "unapplied": unapplied}, sort_keys=True)


def from_stamp(stamp: Optional[dict]) -> Optional[dict]:
    """{'applied': [...], 'unapplied': [...]} as fetched, or None (no record)."""
    if not stamp or STAMP_KEY not in stamp:
        return None
    try:
        return json.loads(str(stamp[STAMP_KEY]))
    except json.JSONDecodeError:
        return None


def review(entries: list, recorded: Optional[dict], today: date) -> tuple:
    """(failures, warnings, lines) for check_playerlist."""
    failures, warnings, lines = [], [], []
    applied = {a["yahoo_id"]: a for a in (recorded or {}).get("applied", [])}
    unapplied = {u["yahoo_id"]: u for u in (recorded or {}).get("unapplied", [])}
    for e in entries:
        name, due = e["player_name"], date.fromisoformat(e["review_by"])
        if today > due:
            failures.append(
                f"projection override for {name} was due for review on {e['review_by']}. "
                f"It patches a Yahoo row that should have been fixed upstream ({e['reason']}). "
                "Check Yahoo, then remove the entry or set a new review_by in "
                "config/PROJECTION_OVERRIDES.json")
        a = applied.get(e["yahoo_id"])
        if a is not None:
            y, n = a["yahoo"], a["now"]
            lines.append(f"{name}: FPPG {y['projectedFPPG']:.2f} -> {n['projectedFPPG']:.2f}, "
                         f"GP {y['player_proj_GP']:g} -> {n['player_proj_GP']:g} "
                         f"(review by {e['review_by']}; {e['reason']})")
            if not a["replaces_matches"]:
                failures.append(
                    f"Yahoo's row for {name} has changed since its override was written "
                    f"(written against {e['replaces']}, Yahoo now says GP {y['player_proj_GP']:g}, "
                    f"FP {y['player_total_proj_FP']:,.2f}). The upstream fault may be fixed -- "
                    "review the entry before it masks a real projection")
        elif recorded is None:
            warnings.append(f"projection override for {name} cannot be confirmed: nothing in "
                            "this PLAYERLIST's fetch stamp records it (fetched before overrides "
                            "were recorded, or built by hand); re-run fetch_playerlist.py --execute")
        else:
            why = unapplied.get(e["yahoo_id"], {}).get("why", "added after this file was fetched")
            warnings.append(f"projection override for {name} is NOT in effect ({why}); "
                            "re-run fetch_playerlist.py --execute")
    return failures, warnings, lines
