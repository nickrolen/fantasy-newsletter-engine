#!/usr/bin/env python3
"""
check_playerlist.py -- gate data/PLAYERLIST.xlsx before it reaches the engine.

WHY
---
PLAYERLIST carries the projections every simulator runs on, and until now
nothing checked it. The rules were written down in WEEKLY_WORKFLOW Step 2.5 (now 4.75)
and enforced by an LLM following a prompt; check_file_health.py never opened
the file. So a bad week looked exactly like a good one.

The failure modes are all quiet:

    a rostered player missing        -> 0.0 FPPG in every simulation
    a column shifted by one          -> plausible numbers, wrong players
    the file not regenerated         -> last week's projections, silently
    an age missing                   -> defaults to 27 in keepability
    GP or FP unparseable             -> the row vanishes

None of those raise. Each of them changes the newsletter.

WHAT IT COMPARES AGAINST
------------------------
Itself, a week ago. config/snapshots/ keeps a copy each time this runs
clean, and the week-over-week comparison is what catches a misaligned paste
or scrape. A misalignment moves MOST rows at once, in no particular
direction; a projection refresh moves a few. (It used to fail on any one
player gaining games remaining. That happens whenever an injury outlook
improves -- six players on 2026-10-13 -- and was wrong; see GP_UP_SHARE.)

USAGE
    py scripts/check_playerlist.py
    py scripts/check_playerlist.py --snapshot     # save as this week's baseline
    py scripts/check_playerlist.py --strict       # warnings become failures

EXIT CODES
    0 = usable
    1 = do not generate a newsletter from this
"""

import argparse
import json
import re
import shutil
import sys
from datetime import date, datetime
from pathlib import Path

import pandas as pd

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(PROJECT_ROOT))

from modules.data_loader import (  # noqa: E402
    DURABILITY_PRIOR, FLAT_GP_SHARE_MAX, NBA_SCHEDULE_FILE, PlayerIndex, gp_column_is_flat,
    normalize_player_name, _without_suffix, initial_match,
)
from modules import absence  # noqa: E402
from modules import playerlist_freshness  # noqa: E402
from modules import projection_overrides  # noqa: E402

PLAYERLIST = PROJECT_ROOT / "data" / "PLAYERLIST.xlsx"
ROSTERS = PROJECT_ROOT / "config" / "ROSTERS.json"
SNAPSHOTS = PROJECT_ROOT / "config" / "snapshots"

REQUIRED = ["player_name", "player_nba_team", "player_position(s)",
            "player_total_proj_FP", "player_proj_GP", "projectedFPPG"]

# A projection is a forecast, not a measurement, so it moves. These bounds are
# set wide enough that ordinary week-to-week drift is quiet and a structural
# error is not.
FPPG_JUMP = 0.40        # 40% week-over-week change in projected FPPG
FPPG_FLOOR = 5.0        # nobody worth listing projects below this
FPPG_CEILING = 90.0     # nobody projects above this either
GP_CEILING = 82         # an NBA regular season; nobody has more remaining

# Share of players present in both weeks whose projected games remaining went
# UP, above which the file is treated as misaligned. Measured 2026-10-13:
#   Yahoo's real refresh 10-05 -> 10-13    6 of 168 up (3.6%), 10 down
#   stats shifted one row against names   78-82 of 175 up (45-47%)
# In season every player's games remaining falls each week, so a legitimate
# refresh is mostly DOWN; a shift is a coin flip either way. "How many rows
# changed" would not work -- in season nearly all of them change. Direction
# is the signature. The 40% FPPG jump below misses the likely shift entirely:
# fetch_playerlist sorts by total FP, so neighbouring rows have similar FPPG
# (0 of 175 rows jumped 40% in the simulated shift).
GP_UP_SHARE = 0.25
MIN_COMMON_FOR_SHARE = 20   # fewer players in common and a share means little

# ...COMPARED LIKE WITH LIKE (HANDOFF_STALE_GATES sec.2). GP is "games
# remaining", and between two in-season files every player loses the games his
# team played, so a raw comparison reads "down" for everyone -- a shift
# included -- and the check could not fail. So each file's GP is divided by
# his team's games remaining ON THAT FILE'S DATE (a pre-season file: of 82)
# and the shares are compared. A share must rise by more than this to count:
# half a game in a hundred. Measured 2026-10-27, it changes nothing that
# matters -- the real 10-05 -> 10-13 refresh reads 6 of 168 up at 0 or at
# 0.005, a one-row shift of it 79 of 167.
#
# LIMIT, measured the same day: an in-season file is flat (healthy players all
# sit near 0.96 of games remaining), so a one-row shift barely moves anyone's
# share -- 24 of 177 (14%) up on a synthetic in-season pair, under the 25%.
# The direction test catches a shift in a pre-season file and largely misses
# one in season. That is a gap in this check, not a threshold to lower here.
#
# And the one comparison that is NOT like with like -- the first in-season
# fetch against a pre-season baseline, once a season -- is skipped and said:
# the column's meaning changed at week 1 (its durability haircut is gone).
GP_SHARE_EPS = 0.005

# THE GP COLUMN CARRIES TWO DIFFERENT MEANINGS, one per season phase, and the
# baseline injury hazard only works on one of them (measured 2026-10-22):
#
#   pre-season   projected games of 82, with a durability haircut on everyone
#                -> sd 4.9-5.0, 54 of 175 players (31%) within one game of
#                   the median. THIS is a durability forecast.
#   in-season    games of those REMAINING, marked down only for a player
#                Yahoo already knows is hurt
#                -> sd 2.74, 191 of 200 (96%) within one game of the median.
#                   NOT a durability forecast at all.
#
# Both are correct files; which one you have depends only on the date. So the
# check is not "flat is bad", it is "flat must agree with the phase":
#   flat before week 1  -> the scrape is broken, or Yahoo switched early: FAIL
#   flat in season      -> expected, and reported. The engine is protected
#                          because the hazard reads config durability_prior (a
#                          pre-season snapshot), never this file -- so the
#                          check confirms THAT instead, and fails if the
#                          configured prior is this file or is itself flat.
# Refusing every in-season file would leave Step 2.5 permanently red while the
# file it rejects is perfectly good for the only thing it is still used for:
# scoring (projectedFPPG correlates 0.97 across the same refresh that breaks
# GP at 0.52).


def _first_week_start():
    """Week 1's start date from config/SCHEDULE.json, or None."""
    try:
        blob = json.loads((PROJECT_ROOT / "config" / "SCHEDULE.json").read_text(encoding="utf-8"))
        starts = [str(w["start_date"])[:10] for w in blob.get("weeks", []) if w.get("start_date")]
        return date.fromisoformat(min(starts)) if starts else None
    except (OSError, json.JSONDecodeError, KeyError, ValueError):
        return None


def load_rosters() -> dict:
    if not ROSTERS.is_file():
        return {}
    try:
        blob = json.loads(ROSTERS.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    rosters = blob.get("rosters", blob)
    return {m: p for m, p in rosters.items() if isinstance(p, list)}


def _snapshot_is_from_today(path) -> bool:
    """Snapshots are named PLAYERLIST_<YYYY-MM-DD>.xlsx."""
    found = re.search(r"(\d{4}-\d{2}-\d{2})", getattr(path, "name", ""))
    return bool(found) and found.group(1) == date.today().isoformat()


def _fantasy_week(d):
    """The fantasy week containing d (config/SCHEDULE.json), or None outside one."""
    try:
        blob = json.loads((PROJECT_ROOT / "config" / "SCHEDULE.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    for w in blob.get("weeks", []):
        try:
            start = date.fromisoformat(str(w["start_date"])[:10])
            end = date.fromisoformat(str(w["end_date"])[:10])
        except (KeyError, ValueError):
            continue
        if start <= d <= end:
            return int(w["week"])
    return None


def rosters_synced_at():
    """(datetime, how) for config/ROSTERS.json: its _last_sync stamp, else
    the file's mtime. Both are naive local times from whichever machine wrote
    them -- which is why the roster guard compares FANTASY WEEKS, not times."""
    try:
        blob = json.loads(ROSTERS.read_text(encoding="utf-8"))
        if blob.get("_last_sync"):
            return datetime.fromisoformat(str(blob["_last_sync"])), "_last_sync"
    except (OSError, json.JSONDecodeError, ValueError):
        pass
    if ROSTERS.is_file():
        return datetime.fromtimestamp(ROSTERS.stat().st_mtime), "file mtime"
    return None, None


def team_game_dates():
    """{team: set of scheduled game dates}, or None without a schedule."""
    try:
        blob = json.loads((PROJECT_ROOT / NBA_SCHEDULE_FILE).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return None
    out = {}
    for g in blob.get("games", []) if isinstance(blob, dict) else []:
        try:
            d = date.fromisoformat(str(g["date"])[:10])
        except (KeyError, ValueError):
            continue
        for t in (g.get("home"), g.get("away")):
            if t:
                out.setdefault(str(t).upper(), set()).add(d)
    return out or None


def gp_shares(frame, on: date, team_dates: dict) -> pd.Series:
    """Projected GP as a share of the player's team's games remaining on
    `on` (absence.remaining_team_games: scheduled games on or after it plus
    the ones not scheduled yet). NaN for a team the schedule does not know."""
    params = absence.baseline_params()
    cache, out = {}, []
    for team, gp in zip(frame["player_nba_team"], frame["player_proj_GP"]):
        t = str(team).upper()
        g = pd.to_numeric(gp, errors="coerce")
        if t not in team_dates or pd.isna(g):
            out.append(float("nan"))
            continue
        if t not in cache:
            cache[t] = absence.remaining_team_games(team_dates[t], on, params)
        out.append(float(g) / cache[t] if cache[t] else float("nan"))
    return pd.Series(out, index=frame.index)


def _snapshot_date(path):
    found = re.search(r"(\d{4}-\d{2}-\d{2})", getattr(path, "name", ""))
    try:
        return date.fromisoformat(found.group(1)) if found else None
    except ValueError:
        return None


def save_snapshot(failures: list) -> Path:
    """Copy the LIVE file to config/snapshots/PLAYERLIST_<today>.xlsx.

    Unconditional when --snapshot is passed (HANDOFF_STALE_GATES sec.5). The
    gate answers "may we publish from this file"; the snapshot answers "what
    did Yahoo say this week" -- and the live file is overwritten by the next
    fetch, so a snapshot skipped because the file failed is gone for good,
    in exactly the unusual week calibration most wants. The copy carries the
    _fetch stamp, so it also records any projection overrides and the Yahoo
    values they replaced.
    """
    SNAPSHOTS.mkdir(parents=True, exist_ok=True)
    target = SNAPSHOTS / f"PLAYERLIST_{date.today().isoformat()}.xlsx"
    replaced = target.exists()
    shutil.copy2(PLAYERLIST, target)
    if failures:
        print("\n  " + "!" * 62)
        print(f"  SNAPSHOT TAKEN FROM A FILE THAT FAILED THE GATE ({len(failures)} failure(s)):")
        for f in failures:
            print(f"    x {f}")
        print("  It records what Yahoo said this week. It is NOT a file to publish from.")
        print("  " + "!" * 62)
    print(f"  Saved baseline: {target.relative_to(PROJECT_ROOT)}"
          f"{' (replaced the one taken earlier today)' if replaced else ''}")
    return target


def previous_snapshot():
    """The most recent saved PLAYERLIST, or None."""
    if not SNAPSHOTS.is_dir():
        return None, None
    found = sorted(SNAPSHOTS.glob("PLAYERLIST_*.xlsx"), reverse=True)
    if not found:
        return None, None
    try:
        return pd.read_excel(found[0]), found[0]
    except Exception:
        return None, found[0]


def main():
    ap = argparse.ArgumentParser(description="Validate data/PLAYERLIST.xlsx.")
    ap.add_argument("--snapshot", action="store_true",
                    help="save this file as the baseline for next week")
    ap.add_argument("--strict", action="store_true",
                    help="treat warnings as failures")
    ap.add_argument("--file", default=None,
                    help="check this workbook instead of data/PLAYERLIST.xlsx "
                         "(e.g. one written by fetch_playerlist.py --out)")
    args = ap.parse_args()
    path = Path(args.file) if args.file else PLAYERLIST
    if args.file and args.snapshot:
        print("  --snapshot saves the LIVE file as next week's baseline; it "
              "cannot be combined with --file.")
        return 1

    failures, warnings = [], []

    print("=" * 66)
    print("  CHECK PLAYERLIST")
    print("=" * 66)

    if not path.is_file():
        print(f"\n  FAIL: {path} does not exist.")
        return 1
    try:
        frame = pd.read_excel(path)
    except Exception as e:
        print(f"\n  FAIL: could not read it: {e}")
        return 1

    missing_cols = [c for c in REQUIRED if c not in frame.columns]
    if missing_cols:
        print(f"\n  FAIL: missing column(s): {missing_cols}")
        if args.snapshot:
            save_snapshot([f"missing column(s): {missing_cols}"])
        return 1
    if frame.empty:
        print("\n  FAIL: no rows. The season reset empties this file; it has "
              "to be rebuilt before a newsletter can be generated.\n"
              "  Run: py scripts/fetch_playerlist.py --execute")
        return 1

    frame["_key"] = frame["player_name"].apply(normalize_player_name)
    print(f"\n  {len(frame)} players")

    # --- duplicates ---------------------------------------------------------
    dupes = frame[frame["_key"].duplicated(keep=False)]
    if not dupes.empty:
        names = sorted(set(dupes["player_name"]))
        failures.append(f"duplicate players ({len(names)}): {names[:6]}")

    # --- the arithmetic -----------------------------------------------------
    off = []
    for _, row in frame.iterrows():
        gp = pd.to_numeric(row["player_proj_GP"], errors="coerce")
        fp = pd.to_numeric(row["player_total_proj_FP"], errors="coerce")
        fppg = pd.to_numeric(row["projectedFPPG"], errors="coerce")
        if pd.isna(gp) or pd.isna(fp) or pd.isna(fppg):
            failures.append(f"{row['player_name']}: unreadable GP/FP/FPPG")
            continue
        if gp > 0 and abs(fp / gp - fppg) > 0.05:
            off.append(f"{row['player_name']} ({fp:.1f}/{gp:.0f}="
                       f"{fp / gp:.2f} vs {fppg:.2f})")
    if off:
        failures.append(f"projectedFPPG does not equal total/GP for "
                        f"{len(off)}: {off[:4]}")

    # --- plausibility -------------------------------------------------------
    fppg = pd.to_numeric(frame["projectedFPPG"], errors="coerce")
    low = frame[fppg < FPPG_FLOOR]["player_name"].tolist()
    high = frame[fppg > FPPG_CEILING]["player_name"].tolist()
    gp_all = pd.to_numeric(frame["player_proj_GP"], errors="coerce")
    gp_bad = frame[(gp_all < 0) | (gp_all > GP_CEILING)]["player_name"].tolist()
    if gp_bad:
        failures.append(f"{len(gp_bad)} player(s) with projected GP outside "
                        f"0-{GP_CEILING}: {gp_bad[:5]}")
    if low:
        failures.append(f"{len(low)} player(s) below {FPPG_FLOOR} FPPG: {low[:5]}")
    if high:
        failures.append(f"{len(high)} player(s) above {FPPG_CEILING} FPPG: {high[:5]}")
    print(f"  FPPG range: {fppg.min():.1f} - {fppg.max():.1f}")

    # --- the GP column's meaning, against the season phase ------------------
    flat, shape = gp_column_is_flat(frame["player_proj_GP"])
    first_week_start = _first_week_start()
    in_season = first_week_start is not None and date.today() >= first_week_start
    print(f"  GP shape: median {shape['median']:.0f}, {shape['within_one']}/{shape['n']} "
          f"players ({shape['share']:.0%}) within one game of it "
          f"-- {'in-season' if flat else 'pre-season'} shaped")
    if flat and first_week_start is None:
        warnings.append(
            f"the projected-GP column is flat ({shape['within_one']}/{shape['n']}, "
            f"{shape['share']:.0%} within one game of the median) and config/SCHEDULE.json "
            "does not say when week 1 starts, so it cannot be told from the in-season "
            "shape, which is normal")
    elif flat and not in_season:
        failures.append(
            f"the projected-GP column is in-season shaped before week 1 "
            f"({first_week_start}): {shape['within_one']} of {shape['n']} players "
            f"({shape['share']:.0%}) are within one game of the median "
            f"{shape['median']:.0f}, above the {FLAT_GP_SHARE_MAX:.0%} limit, where a "
            f"pre-season file sits near 31%. Either the scrape is misaligned or Yahoo "
            f"switched the column to games-remaining early -- and the baseline injury "
            f"hazard needs the pre-season meaning for its durability prior")
    if flat and in_season:
        print("    (expected in season; the durability prior is taken from "
              f"{DURABILITY_PRIOR.get('snapshot')}, not from this file)")
    prior_rel = DURABILITY_PRIOR.get("snapshot")
    prior_path = PROJECT_ROOT / str(prior_rel or "")
    if not prior_rel:
        failures.append("config durability_prior.snapshot is not set; the baseline injury "
                        "hazard has no durability prior")
    elif not prior_path.is_file():
        failures.append(f"config durability_prior.snapshot ({prior_rel}) is not a file; "
                        "the baseline injury hazard has no durability prior")
    elif prior_path.resolve() == PLAYERLIST.resolve():
        failures.append("config durability_prior.snapshot points at the LIVE PLAYERLIST. "
                        "It must be a pre-season snapshot: in season this file's GP column "
                        "is games remaining, which switches the injury hazard off")
    else:
        try:
            prior_flat, prior_shape = gp_column_is_flat(
                pd.read_excel(prior_path)["player_proj_GP"])
        except Exception as e:
            failures.append(f"could not read the durability prior {prior_rel}: {e}")
        else:
            if prior_flat:
                failures.append(
                    f"the durability prior {prior_rel} is in-season shaped "
                    f"({prior_shape['within_one']}/{prior_shape['n']}, "
                    f"{prior_shape['share']:.0%} within one game of the median) and is "
                    "not a durability forecast. Point it at a snapshot from before week 1")
            else:
                print(f"  durability prior: {prior_rel} "
                      f"({prior_shape['share']:.0%} flat, pre-season shaped)")

    # --- roster coverage ----------------------------------------------------
    # Through PlayerIndex, the resolver the simulators use, so this check and
    # the engine agree on who is present. Yahoo's roster and pool endpoints
    # spell some players differently in the same fetch ("Shai Gilgeous-
    # Alexander" / "S. Gilgeous-Alexander"); plain normalising called that a
    # missing player while the engine -- on 10-12 -- also missed him, through
    # a second, shorter copy of the ladder. Both now resolve the same way.
    rosters = load_rosters()
    if rosters:
        have = PlayerIndex({n: n for n in frame["player_name"]})
        absent, respelled = [], []
        for manager, players in rosters.items():
            for p in players:
                hit = have.get(p)
                if hit is None:
                    absent.append(f"{p} ({manager})")
                elif normalize_player_name(hit) != normalize_player_name(p):
                    respelled.append(f"{p} -> {hit}")
        if respelled:
            print(f"  resolved by respelling ({len(respelled)}): "
                  f"{', '.join(respelled[:6])}")
        if absent:
            failures.append(
                f"{len(absent)} rostered player(s) missing -- each would "
                f"project 0.0 FPPG: {absent[:8]}")
        else:
            total = sum(len(p) for p in rosters.values())
            print(f"  roster coverage: {total}/{total} rostered players present")
    else:
        warnings.append("config/ROSTERS.json is empty or unreadable, so roster "
                        "coverage was NOT checked. Before the draft this is "
                        "expected.")

    # --- ages ---------------------------------------------------------------
    if "age" in frame.columns:
        ageless = frame[frame["age"].isna()]["player_name"].tolist()
        if ageless:
            warnings.append(
                f"{len(ageless)} player(s) with no age (keepability will "
                f"assume 27): {ageless[:6]}")
    else:
        warnings.append("no age column")

    # --- when it was fetched -------------------------------------------------
    # A fact written by fetch_playerlist, not an inference from whether the
    # numbers moved (modules/playerlist_freshness.py).
    stamp_ = playerlist_freshness.read_stamp(path)
    fresh = playerlist_freshness.assess(frame.drop(columns=["_key"]), stamp_)
    if fresh["how"] == "stamp":
        print(f"  fetched {fresh['fetched_on']} ({fresh['age_days']} day(s) ago) "
              f"from {fresh['source']}")
        if fresh["stale"]:
            failures.append(
                f"fetched {fresh['age_days']} days ago ({fresh['fetched_on']}), "
                f"more than {playerlist_freshness.MAX_AGE_DAYS} -- this week's "
                f"projections were not pulled")
    elif fresh["how"] == "mismatch":
        warnings.append(
            "the fetch stamp no longer matches the projections in this file "
            "(edited after fetching?), so it was ignored and freshness is "
            "judged by comparing against the last snapshot")
    else:
        warnings.append(
            "no fetch stamp (built by hand, or before stamps existed), so "
            "freshness is judged by comparing against the last snapshot. "
            "fetch_playerlist.py --execute writes one.")

    # --- the rosters were synced for THIS week ------------------------------
    # Roster coverage above is only as current as ROSTERS.json, which Steps
    # 3-4 rebuild. On 10-26 this check ran (as Step 2.5) against rosters from
    # 10-19 and both missed Boozer's pickup and failed on Jalen Williams'
    # drop. So the fetch now runs after the roster gate, and this makes the
    # order impossible to undo quietly: rosters synced in an earlier fantasy
    # week than the fetch fail. Weeks, not timestamps -- _last_sync and
    # fetched_at are naive local times, and on 10-26 they came from machines
    # seven hours apart.
    if rosters and stamp_ and stamp_.get("fetched_at"):
        fetched = datetime.fromisoformat(str(stamp_["fetched_at"]))
        synced, how = rosters_synced_at()
        week_fetched = _fantasy_week(fetched.date())
        week_synced = _fantasy_week(synced.date()) if synced else None
        if week_fetched is not None:
            if week_synced is None or week_synced < week_fetched:
                failures.append(
                    f"config/ROSTERS.json was last synced {synced:%Y-%m-%d %H:%M} ({how}) -- "
                    f"{'before the season' if week_synced is None else f'week {week_synced}'} -- "
                    f"but this PLAYERLIST was fetched in week {week_fetched} "
                    f"({fetched:%Y-%m-%d %H:%M}). Roster coverage was judged against last "
                    "week's rosters. Run Steps 3-4.5 (generate_rosters, sync_transactions, "
                    "check_rosters) before Step 4.75 (this fetch and check)")
            else:
                print(f"  rosters synced {synced:%Y-%m-%d %H:%M} ({how}), week {week_synced}; "
                      f"fetched in week {week_fetched}")

    # --- projection overrides --------------------------------------------------
    try:
        entries = projection_overrides.load(PROJECT_ROOT / "config" / "PROJECTION_OVERRIDES.json")
    except projection_overrides.OverrideError as e:
        failures.append(f"config/PROJECTION_OVERRIDES.json: {e}")
        entries = []
    if entries:
        o_fail, o_warn, o_lines = projection_overrides.review(
            entries, projection_overrides.from_stamp(stamp_), date.today())
        failures += o_fail
        warnings += o_warn
        if o_lines:
            print(f"  projection overrides live ({len(o_lines)}):")
            for line in o_lines:
                print(f"      {line}")

    # --- against last week --------------------------------------------------
    prev, prev_path = previous_snapshot()
    if prev is None:
        warnings.append("no previous snapshot to compare against. Run with "
                        "--snapshot to start the baseline.")
    else:
        prev = prev.copy()
        prev["_key"] = prev["player_name"].apply(normalize_player_name)
        joined = frame.merge(prev, on="_key", suffixes=("", "_prev"))

        # Yahoo renames players. On 2026-10-05 "Shai Gilgeous-Alexander"
        # became "S. Gilgeous-Alexander" and "Bobby Portis" became "Bobby
        # Portis Jr." -- not one projection changed, only the spelling --
        # while every other file in the project kept the old form. A rename
        # looks exactly like one player leaving the pool and another
        # arriving, so nothing flagged it, and a keeper silently lost his
        # projection. Anything that leaves and comes back under a name
        # reducing to the same person is reported.
        entered = set(frame["player_name"]) - set(prev["player_name"])
        departed = set(prev["player_name"]) - set(frame["player_name"])
        renames = []
        for gone in sorted(departed):
            for arrived in sorted(entered):
                same = (_without_suffix(gone) == _without_suffix(arrived)
                        or initial_match(gone, arrived))
                if same:
                    renames.append((gone, arrived))
        for gone, arrived in renames:
            warnings.append(
                f"Yahoo renamed {gone!r} to {arrived!r}. Projections still "
                f"resolve, but every other file in the project uses the old "
                f"spelling -- check anything that stores this name.")

        print(f"  compared against {prev_path.name} "
              f"({len(joined)} players in both)")

        if len(joined) == len(frame) == len(prev):
            same = frame[REQUIRED].equals(prev[REQUIRED]) if list(prev.columns) else False
            # Identical to a snapshot taken on an EARLIER day means the file
            # was not rebuilt. Identical to one taken today just means this
            # ran twice today, which is what happens after a re-run, and
            # Yahoo's numbers do not move between two runs an hour apart.
            if same and fresh["how"] == "stamp":
                # The stamp already settled freshness; identical numbers just
                # mean Yahoo has not moved a projection since the snapshot.
                print(f"  (projections unchanged since {prev_path.name}; the "
                      f"file itself was fetched {fresh['fetched_on']})")
            elif same and _snapshot_is_from_today(prev_path):
                print("  (identical to today's snapshot -- a same-day re-run, "
                      "not a stale file)")
            elif same:
                failures.append(
                    "identical to the previous snapshot -- this file was not "
                    "regenerated this week")

        # Like with like: GP as a share of games remaining on each file's date.
        prev_flat, _prev_shape = gp_column_is_flat(prev["player_proj_GP"])
        regime_change = flat and not prev_flat
        live_on = (date.fromisoformat(str(fresh["fetched_on"])[:10])
                   if fresh["how"] == "stamp" else date.today())
        prev_on = _snapshot_date(prev_path)
        tdates = team_game_dates()
        by_share = tdates is not None and prev_on is not None
        if by_share:
            frame["_gp_share"] = gp_shares(frame, live_on, tdates)
            prev["_gp_share"] = gp_shares(prev, prev_on, tdates)
            joined = frame.merge(prev, on="_key", suffixes=("", "_prev"))
        else:
            warnings.append("GP compared raw, not as a share of games remaining: "
                            f"{'no NBA schedule' if tdates is None else 'the snapshot name has no date'}")
        if regime_change:
            print(f"  GP not compared: {prev_path.name} is pre-season shaped and this file is "
                  "in-season shaped -- the column changed meaning at week 1 (games of 82 with "
                  "a durability haircut -> games remaining). Expected once a season.")

        jumps, grew, compared = [], [], 0
        for _, row in joined.iterrows():
            a = pd.to_numeric(row["projectedFPPG"], errors="coerce")
            b = pd.to_numeric(row["projectedFPPG_prev"], errors="coerce")
            if pd.notna(a) and pd.notna(b) and b > 0:
                if abs(a - b) / b > FPPG_JUMP:
                    jumps.append(f"{row['player_name']} {b:.1f} -> {a:.1f}")
            if regime_change:
                continue
            g = pd.to_numeric(row["player_proj_GP"], errors="coerce")
            h = pd.to_numeric(row["player_proj_GP_prev"], errors="coerce")
            if by_share:
                sg, sh = row["_gp_share"], row["_gp_share_prev"]
                if pd.notna(sg) and pd.notna(sh):
                    compared += 1
                    if sg > sh + GP_SHARE_EPS:
                        grew.append(f"{row['player_name']} {h:.0f} -> {g:.0f}")
            elif pd.notna(g) and pd.notna(h):
                compared += 1
                if g > h:
                    grew.append(f"{row['player_name']} {h:.0f} -> {g:.0f}")
        if jumps:
            warnings.append(
                f"{len(jumps)} player(s) moved more than {FPPG_JUMP:.0%} in "
                f"projected FPPG: {jumps[:6]}")
        share = len(grew) / compared if compared else 0.0
        if compared >= MIN_COMMON_FOR_SHARE and share > GP_UP_SHARE:
            failures.append(
                f"{len(grew)} of {compared} players ({share:.0%}) have a larger share of "
                f"their team's games remaining than last week. A refresh moves a few "
                f"players up as injury outlooks improve; this many, in both directions, "
                f"is the signature of stats shifted against names: {grew[:6]}")
        elif grew:
            print(f"  games remaining up for {len(grew)} of {compared} "
                  f"({share:.0%}; outlooks improving -- not a problem): "
                  f"{', '.join(grew[:6])}")

    # --- report -------------------------------------------------------------
    if warnings:
        print(f"\n  WARNINGS ({len(warnings)}):")
        for w in warnings:
            print(f"    - {w}")
    if failures:
        print(f"\n  FAILURES ({len(failures)}):")
        for f in failures:
            print(f"    - {f}")

    if args.snapshot:
        save_snapshot(failures)

    if args.strict and warnings and not failures:
        print("\n  --strict: warnings treated as failures.")
        return 1
    if failures:
        print("\n  RESULT: DO NOT generate a newsletter from this file.")
        print("  Rebuild it: py scripts/fetch_playerlist.py --execute")
        print("  Or fall back to the manual procedure in WEEKLY_WORKFLOW.md "
              "Step 4.75.")
        return 1

    print("\n  RESULT: usable." + (f" {len(warnings)} warning(s)." if warnings else ""))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        print(f"\nERROR: {e}")
        sys.exit(1)
