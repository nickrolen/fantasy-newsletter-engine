"""
closing_line.py -- the closing line: the official line (step 1c; Nick, 11-03).

Week N's line is priced ONCE more after Monday's window closes
(price_lock.window_close: the last tip minus 5 minutes, rule 4), on:
  - ROSTERS AND IL AS AT THE CLOSE: Yahoo's rosters (config/ROSTERS.json and
    data/IL_SLOTS.json, both synced after the close), with the transaction log
    confirming no transaction after the close: one RAISES (moves after the
    window break rule 4 and need Nick);
  - EVERYTHING ELSE AS AT MONDAY'S FIRST TIP: no Monday results banked (the
    as-of is Monday, nothing played; the logs are cut before Monday whenever
    this runs), and the tags from the latest tag record taken on Monday before
    the first tip (modules/tag_records.for_close: the pre-tip run's, else the
    12:01 AM run's). No such record refuses. Yahoo's projections must have
    been fetched before the first tip (PLAYERLIST's fetch stamp), or it refuses;
  - THE WEEK'S SEED, as every line of that week (live_lines_weekN.state.json).

PROJECTIONS AS AT THE FIRST TIP, FROM A COPY THE ENGINE KEEPS (H51, 11-17):
every run on a window Monday before the first tip that records tags also
copies the live PLAYERLIST to config/snapshots/pretip/PLAYERLIST_weekNN.xlsx
(capture_pretip_playerlist; state, under the config/snapshots manifest dir).
The closing line prices on the latest fetch made before the tip that the
engine still holds: the live file or that copy, whichever was fetched later
while still before the tip (playerlist_at_tip). So Monday's Step 4.75 refetch
after the tip (11-16, 6:28 PM) no longer refuses the close; with no pre-tip
copy and a post-tip live file it still refuses. A copy's stamp must describe
its rows and be before the tip, or it refuses.
No special case for a player added after his own game tipped: Yahoo locks a
player once his game starts (Nick).

INJURY ENTRIES AS AT MONDAY'S FIRST TIP (Step 3a, task 26): the overrides are
rebuilt as they stood at the first tip from output/override_history.jsonl
(modules/override_history.as_of: every change after the tip undone, newest
first), and the line RAISES when an entry that governs the week was changed
after the tip with no history record to undo (its updated_at says so), or when
the file disagrees with the history. Entries written before the history began
carry no updated_at and count as before the tip; no time is invented for them.

It uses no information from after the close, so it can run any time after it
(1c-ii: at the start of Tuesday's 12:01 AM run, before the log pull). It
refuses before the close, and run twice it is byte-identical: the payload
carries the close, never the time it was computed; a second run that would
write different bytes raises (ClosingChanged) and writes nothing.

Writes:
  output/closing_line_weekN.json          the line (refresh_lines' payload shape)
  data/calibration/published_lines.json   its records, source "closing": SCORED,
                                          the headline (calibration_log)
  output/title_odds_history.jsonl         title odds re-priced at the close on
                                          the same information, one row marked
                                          kind "closing" (run id closing-weekN)
"""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path


class ClosingRefused(RuntimeError):
    """The closing line cannot be priced (and nothing was written)."""


class ClosingChanged(ClosingRefused):
    """A second run would write a different closing line or title-odds row."""


def closing_path(base_path, week: int) -> Path:
    return Path(base_path) / "output" / f"closing_line_week{int(week)}.json"


def run_id_for(week: int) -> str:
    return f"closing-week{int(week)}"


# =============================================================================
# when is a closing line due? (step 1c-ii, HANDOFF_STEP1C2 s.3)
# =============================================================================
#
# The scheduled nightly run asks this before its own steps. The answer is the
# LATEST window day (a fantasy week's first day) whose close has passed; it is
# due unless that week already has its closing line or its "no closing line"
# record. So a missed night is caught up on the next one, and a week is never
# priced twice. Only the latest week is ever considered: a closing line priced
# a week late would see moves made after its close.
#
# "No closing line this week" (HANDOFF s.3): a week whose Monday has no tag
# record from before its first tip (tag_records.NoPretipTags) cannot be priced
# now or ever, so it is recorded ONCE in output/closing_none_weekN.json and
# never retried. Every other refusal stops the run and is retried the next
# night: those are fixable (a sync, a schedule refetch, Nick's ruling).
# Nick can record one by hand when a refusal is permanent:
#     python scripts\nightly.py --no-closing-line --week N --reason "..."


PRETIP_DIR = Path("config") / "snapshots" / "pretip"


def pretip_playerlist_path(base_path, week: int) -> Path:
    """Week `week`'s pre-tip PLAYERLIST copy (state: config/snapshots is a
    manifest dir)."""
    return Path(base_path) / PRETIP_DIR / f"PLAYERLIST_week{int(week):02d}.xlsx"


def _playerlist_stamp(path: Path, what: str):
    """(fetched_at aware, stamp) of a PLAYERLIST workbook whose stamp describes
    its rows. Raises ClosingRefused otherwise (no stamp, naive, or rows that
    changed since the fetch)."""
    import pandas as pd
    from .playerlist_freshness import DATA_SHEET, assess, read_stamp
    st = read_stamp(path) or {}
    if not st.get("fetched_at"):
        raise ClosingRefused(f"{what} has no fetch stamp")
    at = _aware(st["fetched_at"], f"{what}'s fetch stamp")
    frame = pd.read_excel(path, sheet_name=DATA_SHEET)
    if assess(frame, st, today=at.date())["how"] != "stamp":
        raise ClosingRefused(f"{what}'s fetch stamp ({st['fetched_at']}) does not describe its rows "
                             "(edited or pasted since the fetch): it cannot vouch for the projections "
                             "as at the first tip.")
    return at, st


def playerlist_at_tip(base_path, week: int, first_tip: datetime) -> dict:
    """The PLAYERLIST the closing line prices on: the latest fetch made before
    `first_tip` among the live file and the week's pre-tip copy.
    {"path": Path, "rel": "data/PLAYERLIST.xlsx" | the copy's, "fetched_at":
    aware, "source": "live" | "pretip copy"}. Raises ClosingRefused when
    neither was fetched before the tip, or a copy's stamp cannot vouch for it."""
    base = Path(base_path)
    live = base / "data" / "PLAYERLIST.xlsx"
    copy = pretip_playerlist_path(base, week)
    found, late = [], []
    if copy.is_file():
        rel = copy.relative_to(base).as_posix()
        at, _st = _playerlist_stamp(copy, rel)
        if at >= first_tip:
            raise ClosingRefused(f"{rel} was fetched {at.isoformat(timespec='minutes')}, after Monday's "
                                 f"first tip ({first_tip.isoformat(timespec='minutes')}): a pre-tip "
                                 "copy must be from before the tip (it was not written by "
                                 "capture_pretip_playerlist?).")
        found.append({"path": copy, "rel": rel, "fetched_at": at, "source": "pretip copy"})
    if live.is_file():
        try:
            at, _st = _playerlist_stamp(live, "data/PLAYERLIST.xlsx")
        except ClosingRefused:
            if not found:
                raise
            at = None
        if at is not None and at < first_tip:
            found.append({"path": live, "rel": "data/PLAYERLIST.xlsx", "fetched_at": at,
                          "source": "live"})
        elif at is not None:
            late.append(at)
    if not found:
        when = (f"was fetched {late[0].isoformat(timespec='minutes')}, " if late else "")
        raise ClosingRefused(f"data/PLAYERLIST.xlsx {when}after Monday's first tip "
                             f"({first_tip.isoformat(timespec='minutes')}), and there is no pre-tip "
                             f"copy ({copy.relative_to(base).as_posix()}): the closing line's "
                             "projections are as at the first tip.")
    # the latest fetch before the tip; a tie (the copy of the live file) reads the copy
    return max(found, key=lambda f: (f["fetched_at"], f["source"] == "pretip copy"))


def capture_pretip_playerlist(base_path, now: datetime) -> str:
    """On a window Monday before the first tip, copy the live PLAYERLIST to
    the week's pre-tip copy (H51). Called by every nightly-family run that
    records tags (modules/nightly.py), so the copy is the live file as at the
    last run before the tip, whatever Monday's manual steps do later.
    Returns what it did (one line for the run record). Writes nothing on any
    other day, after the tip, when the live file was fetched after the tip,
    or when the copy already holds a later (or the same) fetch."""
    import os
    import shutil
    from . import price_lock
    from .data_loader import load_nba_schedule, load_schedule
    from .nba_schedule import schedule_path
    base = Path(base_path)
    if now.tzinfo is None:
        raise ValueError("capture_pretip_playerlist needs the league clock (aware)")
    from .league_clock import league_tz
    day = now.astimezone(league_tz()).date()
    sched = load_schedule(base / "config" / "SCHEDULE.json")
    week = next((int(w["week"]) for w in sched.get("weeks", [])
                 if str(w["start_date"])[:10] == day.isoformat()), None)
    if week is None:
        return "not a window day: no pre-tip PLAYERLIST copy"
    first = price_lock.first_tip(day, load_nba_schedule(schedule_path(base)))
    if first is None or now >= first:
        return "after the first tip: the pre-tip PLAYERLIST copy stands"
    live = base / "data" / "PLAYERLIST.xlsx"
    at, _st = _playerlist_stamp(live, "data/PLAYERLIST.xlsx")
    if at >= first:
        return (f"data/PLAYERLIST.xlsx was fetched {at.isoformat(timespec='minutes')}, after the first "
                "tip: not copied")
    copy = pretip_playerlist_path(base, week)
    if copy.is_file():
        had, _ = _playerlist_stamp(copy, copy.relative_to(base).as_posix())
        if had >= at:
            return (f"pre-tip PLAYERLIST copy for week {week} already holds the fetch of "
                    f"{had.isoformat(timespec='minutes')}")
    copy.parent.mkdir(parents=True, exist_ok=True)
    tmp = copy.with_name(copy.name + ".tmp")
    shutil.copyfile(live, tmp)
    os.replace(tmp, copy)
    return (f"pre-tip PLAYERLIST copy for week {week}: the fetch of {at.isoformat(timespec='minutes')}"
            f" -> {copy.relative_to(base).as_posix()}")


def none_path(base_path, week: int) -> Path:
    return Path(base_path) / "output" / f"closing_none_week{int(week)}.json"


def settled(base_path, week: int) -> str:
    """"priced", "none" or "" (neither the line nor the record exists)."""
    if closing_path(base_path, week).is_file():
        return "priced"
    if none_path(base_path, week).is_file():
        return "none"
    return ""


def latest_closed_week(now: datetime, weeks, schedule):
    """The week of the latest window day whose close is at or before `now`
    (None before the first close). weeks: SCHEDULE.json's week entries;
    schedule: the NBA schedule (tip times). Raises price_lock's TipTimeMissing
    / NoGames for a window day whose close cannot be placed."""
    from . import price_lock
    if now.tzinfo is None:
        raise ValueError("latest_closed_week needs an aware time")
    days = sorted(((date.fromisoformat(str(w["start_date"])[:10]), int(w["week"])) for w in weeks),
                  reverse=True)
    for day, week in days:
        if day > now.date():
            continue
        if price_lock.window_close(day, schedule) <= now:
            return week
    return None


def due(base_path, now: datetime, data=None):
    """The week whose closing line the scheduled nightly run must price first,
    or None."""
    from .data_loader import load_all_data
    data = data or load_all_data(base_path, current_week=None)
    week = latest_closed_week(now, data.schedule.get("weeks", []), data.nba_schedule)
    if week is None or settled(base_path, week):
        return None
    return week


def record_none(base_path, week: int, *, reason: str, run_id: str, now: datetime,
                by: str = "nightly.py (scheduled)") -> Path:
    """Write output/closing_none_weekN.json: week N has no closing line, once.
    Refuses when the week already has its line or its record."""
    if not str(reason or "").strip():
        raise ClosingRefused("a 'no closing line' record needs its reason")
    got = settled(base_path, week)
    if got:
        raise ClosingRefused(f"week {week} already has its closing "
                             + ("line" if got == "priced" else "'no closing line' record")
                             + ": nothing to record")
    p = none_path(base_path, week)
    p.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps({"schema": 1, "week": int(week), "outcome": "no closing line this week",
                       "reason": str(reason), "recorded_at": now.isoformat(timespec="seconds"),
                       "run_id": run_id, "by": by}, indent=2) + "\n"
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(body, encoding="utf-8")
    tmp.replace(p)
    return p


def pre_close_data(base_path, monday: date, data=None):
    """The league's data as at Monday's first tip: LINEUPS and PLAYERLOG cut
    to the days before Monday, the logs' week recomputed from what is left."""
    import pandas as pd
    from .data_loader import load_all_data
    data = data or load_all_data(base_path, current_week=None)
    cut = monday.isoformat()
    for attr in ("lineups", "playerlog"):
        df = getattr(data, attr)
        if df is not None and len(df):
            setattr(data, attr, df[df["date"].astype(str).str[:10] < cut].copy())
    wk = data.playerlog["week"].max() if len(data.playerlog) else None
    data.current_week = int(wk) if wk is not None and pd.notna(wk) else 0
    data.__dict__.pop("_roster_plans", None)
    return data


def _aware(text: str, what: str) -> datetime:
    t = datetime.fromisoformat(str(text))
    if t.tzinfo is None:
        raise ClosingRefused(f"{what} ({text}) carries no time zone: it cannot be placed against the "
                             "close. Re-run the step that writes it (it now stamps the league clock).")
    return t


def overrides_at(base_path, data, moment: datetime) -> dict:
    """INJURY_OVERRIDES as it stood at `moment` (Monday's first tip), resolved
    the way the loader resolves it (data_loader.resolve_injury_overrides):
    the file with every change after `moment` undone from the history
    (override_history.as_of). Raises ClosingRefused when the file and the
    history disagree."""
    from . import override_history as oh
    from .data_loader import (_read_rosters_file, load_injury_overrides,
                              resolve_injury_overrides)
    base = Path(base_path)
    raw = load_injury_overrides(base / "config" / "INJURY_OVERRIDES.json")
    try:
        rebuilt, _undone = oh.as_of(raw, oh.read(base), moment)
    except oh.OverrideHistoryError as e:
        raise ClosingRefused(f"the injury entries at Monday's first tip cannot be rebuilt: {e}") from None
    pl = data.playerlist
    return resolve_injury_overrides(rebuilt, _read_rosters_file(base / "config" / "ROSTERS.json"),
                                    pl["player_name"].dropna().tolist()
                                    if "player_name" in pl.columns else [])


def align_to_close(tags, rostered) -> tuple:
    """(tags, left, joined): the pre-tip tags re-sorted to the rosters AS AT
    THE CLOSE (11-17). The tags are the pre-tip run's, but the rosters are the
    close's, and a move between the two (a 3:55 PM drop, a 4:30 PM add) moves a
    player between the record's two populations:
      - a rostered tag whose player is on no roster at the close becomes a free
        agent's tag (`left`), so it can't land on nobody
        (absence.UnresolvedTagName refused week 5's close on 11-17 for Murray
        and Mobley, both O, both dropped after the pre-tip run);
      - a free agent's tag whose player is rostered at the close becomes a
        rostered tag (`joined`).
    The tag itself never changes: still as at the tip. nba_outs follow the
    same move (a free agent has none)."""
    from .data_loader import PlayerIndex
    from .fetch_injury_statuses import Tags
    roster = PlayerIndex({n: n for n in rostered})
    fa = dict(tags.free_agents) if tags.free_agents is not None else None
    keep, left, joined = {}, [], []
    for name, st in dict(tags).items():
        if roster.canonical(name) is None:
            left.append(name)
            if fa is not None:
                fa.setdefault(name, st)
        else:
            keep[name] = st
    have = {roster.canonical(n) for n in keep}
    if fa is not None:
        for name in sorted(fa):
            key = roster.canonical(name)
            if key is not None and key not in have:
                keep[name] = fa.pop(name)
                have.add(key)
                joined.append(name)
    outs = {n: d for n, d in dict(tags.nba_outs or {}).items() if roster.canonical(n) is not None}
    return (Tags(keep, fa, tags.free_agents_assumed_healthy, outs or None),
            sorted(left), sorted(joined))


def check_inputs(base_path, data, *, monday: date, first_tip: datetime, close: datetime,
                 week: int = None) -> dict:
    """Every input the closing line takes from disk, checked against the
    close and the first tip. Raises ClosingRefused naming the input. With
    `week`, the projections are playerlist_at_tip's (the live file or the
    week's pre-tip copy); without it, the live file only."""
    from . import transaction_log as tlog
    from .playerlist_freshness import read_stamp
    base = Path(base_path)
    late = tlog.after(base, close)
    if late:
        raise ClosingRefused(
            "transaction(s) after the window closed (" + close.isoformat(timespec="minutes") + "): "
            + "; ".join(f"{t['key']} {t['time']} {t['type']} "
                        + ", ".join(f"{p['action']} {p['name']}" for p in t["players"]) for t in late)
            + ". Moves after the window break rule 4: ask Nick before the closing line is priced.")
    ros = json.loads((base / "config" / "ROSTERS.json").read_text(encoding="utf-8"))
    il = json.loads((base / "data" / "IL_SLOTS.json").read_text(encoding="utf-8"))
    synced = _aware(ros.get("_last_sync"), "config/ROSTERS.json's last sync")
    fetched = _aware(il.get("fetched_at"), "data/IL_SLOTS.json's fetch time")
    for what, t in (("config/ROSTERS.json", synced), ("data/IL_SLOTS.json", fetched)):
        if t < close:
            raise ClosingRefused(f"{what} was synced at {t.isoformat(timespec='minutes')}, before the "
                                 f"close ({close.isoformat(timespec='minutes')}): the closing line's "
                                 "rosters are as at the close. Run the nightly sync first "
                                 "(python scripts\\nightly.py --closing does it).")
    if week is not None:
        chosen = playerlist_at_tip(base, week, first_tip)
        pl_at, pl_rel = chosen["fetched_at"], chosen["rel"]
    else:
        st = read_stamp(base / "data" / "PLAYERLIST.xlsx") or {}
        if not st.get("fetched_at"):
            raise ClosingRefused("data/PLAYERLIST.xlsx has no fetch stamp")
        pl_at, pl_rel = _aware(st["fetched_at"], "data/PLAYERLIST.xlsx's fetch stamp"), \
            "data/PLAYERLIST.xlsx"
        if pl_at >= first_tip:
            raise ClosingRefused(f"data/PLAYERLIST.xlsx was fetched "
                                 f"{pl_at.isoformat(timespec='minutes')}, after Monday's first tip "
                                 f"({first_tip.isoformat(timespec='minutes')}): the closing line's "
                                 "projections are as at the first tip.")
    ov = str((data.injury_overrides or {}).get("last_updated") or "")
    if ov and ov[:10] > monday.isoformat():
        raise ClosingRefused(f"config/INJURY_OVERRIDES.json was last updated {ov}, after Monday "
                             f"{monday}: the closing line's injuries are as at the first tip.")
    return {"rosters_synced": synced, "il_fetched": fetched, "playerlist_fetched": pl_at,
            "playerlist": pl_rel, "overrides_last_updated": ov or None}


def price(base_path, week: int, *, now: datetime = None, sims: int = None, title_sims: int = None,
          data=None, write: bool = True, out_base=None) -> dict:
    """Price week `week`'s closing line and its title odds. Returns
    {"outcome": "priced" | "unchanged", "line": payload, "row": history row,
     "path": ...}. Raises ClosingRefused (nothing written) on any refusal.
    out_base: where the three outputs go (tests: a scratch folder; the inputs
    are still read from base_path). Default: base_path."""
    import refresh_lines as rl                       # scripts/ on sys.path (nightly.py)
    from . import calibration_log as cal, price_lock, tag_records, title_odds_run as tor
    from . import title_odds_history as toh
    from .data_loader import SEASON_SIMS, load_all_data
    from .league_clock import league_now
    from .simulator_betting import DEFAULT_NUM_SIMULATIONS
    from .week_state import week_entry
    base = Path(base_path)
    now = now or league_now()
    sims = sims or DEFAULT_NUM_SIMULATIONS
    title_sims = title_sims or SEASON_SIMS
    full = data or load_all_data(base, current_week=None)
    monday = date.fromisoformat(str(week_entry(full, week)["start_date"])[:10])
    first = price_lock.first_tip(monday, full.nba_schedule)
    if first is None:
        raise ClosingRefused(f"week {week} opens {monday}, a day with no NBA games: no window to close")
    close = price_lock.window_close(monday, full.nba_schedule)
    if now < close:
        raise ClosingRefused(f"week {week}'s window closes {close.isoformat(timespec='minutes')}; it is "
                             f"{now.isoformat(timespec='minutes')}. The closing line is priced after "
                             "the close.")
    # H51: the projections as at the first tip, from the live file or the
    # week's pre-tip copy (playerlist_at_tip); every load below reads that one
    pl = playerlist_at_tip(base, week, first)
    paths = {"playerlist": pl["rel"]}
    if data is None and pl["rel"] != "data/PLAYERLIST.xlsx":
        full = load_all_data(base, current_week=None, paths=paths)
    row = tag_records.for_close(base, monday, first)          # NoPretipTags is a refusal too
    close_rostered = [n for v in json.loads((base / "config" / "ROSTERS.json").read_text(
        encoding="utf-8"))["rosters"].values() for n in v]
    tags, left_tags, joined_tags = align_to_close(tag_records.as_tags(row), close_rostered)
    at_tip = overrides_at(base, full, first)
    full.injury_overrides = at_tip
    info = check_inputs(base, full, monday=monday, first_tip=first, close=close, week=week)
    sp_ = base / "output" / f"live_lines_week{week}.state.json"
    if not sp_.is_file():
        raise ClosingRefused(f"{sp_.relative_to(base).as_posix()} is missing: the closing line is "
                             "priced on the week's seed, which the week's first line records")
    seed = int(json.loads(sp_.read_text(encoding="utf-8"))["seed"])

    data = pre_close_data(base, monday, load_all_data(base, current_week=None, paths=paths))
    data.injury_overrides = at_tip
    data.plan_now = now                      # 44b s.2: after the close, so the week is locked
    p = rl.prepare(base, week, monday, seed=seed, statuses=tags, dry_run=True, data=data,
                   fresh_tags=True)
    from . import override_history as oh, week_state as ws
    from .simulator_betting import get_dates_in_week
    late = oh.changed_after(ws.governing_overrides(p.data, week, get_dates_in_week(p.entry), p.teams),
                            first)
    if late:
        raise ClosingRefused(
            "injury entr" + ("ies" if len(late) > 1 else "y") + " governing week "
            f"{week} changed after Monday's first tip ({first.isoformat(timespec='minutes')}) with no "
            "history record to undo: " + ", ".join(f"{e.get('player_name')} (updated_at "
                                                    f"{e.get('updated_at')})" for e in late)
            + ". The closing line uses no information from after the close (design s.4.1): "
              "ask Nick.")
    key = rl.cache_key(p, sims)
    stamp = close.isoformat(timespec="seconds")
    res, payload = rl.compute(p, sims, extra={
        "generated_at": stamp, "kind": "closing",
        "closing": {"window_close": stamp, "first_tip": first.isoformat(timespec="seconds"),
                    "as_of": monday.isoformat(), "seed": seed,
                    "tags": {"run_id": row["run_id"], "mode": row["mode"], "taken_at": row["taken_at"],
                             "left_roster_before_close": left_tags,
                             "joined_roster_before_close": joined_tags},
                    "overrides_last_updated": info["overrides_last_updated"],
                    "playerlist": {"file": pl["rel"],
                                   "fetched_at": pl["fetched_at"].isoformat(timespec="seconds")},
                    "rule": "rosters and IL as at the close; tags, projections and results as at "
                            "Monday's first tip; the week's seed (Nick, 11-03)"},
        "cache": key})
    records = rl.calibration_records(p, res, sims, key, source=cal.CLOSING, as_of=stamp)

    pass_data = pre_close_data(base, monday, load_all_data(base, current_week=None, paths=paths))
    pass_data.injury_overrides = at_tip
    pass_data.plan_now = now
    sp = tor.run_pass(pass_data, seed=seed, sims=title_sims, statuses=tags)
    ro = tor.readouts(sp)
    hist = toh.make_row(base_path=base, run_id=run_id_for(week), produced_by="closing_line",
                        seed=seed, num_simulations=title_sims, title_odds=ro["title_odds"],
                        week=week, playoff_odds=ro["playoff_odds"], cup_odds=ro["cup_odds"],
                        as_of=close, kind="closing", expected_record=ro["expected_record"])

    out = Path(out_base) if out_base is not None else base
    body = json.dumps(payload, indent=1, sort_keys=True) + "\n"
    path = closing_path(out, week)
    existing_row = next((r for r in toh.read(out) if r["run_id"] == hist["run_id"]), None)
    if path.is_file() or existing_row is not None:
        same_line = path.is_file() and path.read_text(encoding="utf-8") == body
        same_row = existing_row is not None and existing_row == json.loads(json.dumps(hist))
        if not (same_line and same_row):
            raise ClosingChanged(
                f"week {week}'s closing line is already on file and this run "
                + ("would price a different line" if not same_line else "would write a different "
                   "title-odds row")
                + " (an engine change, or an input changed after the close?). Nothing was written.")
        return {"outcome": "unchanged", "line": payload, "row": existing_row, "path": path,
                "calibration_added": 0}
    if not write:
        return {"outcome": "dry", "line": payload, "row": hist, "path": path, "calibration_added": 0}
    logged = cal.append(records, out)
    toh.append(out, hist)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(body)
    return {"outcome": "priced", "line": payload, "row": hist, "path": path,
            "calibration_added": logged["added"]}
