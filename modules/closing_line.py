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
No special case for a player added after his own game tipped: Yahoo locks a
player once his game starts (Nick).

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


def check_inputs(base_path, data, *, monday: date, first_tip: datetime, close: datetime) -> dict:
    """Every input the closing line takes from disk, checked against the
    close and the first tip. Raises ClosingRefused naming the input."""
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
    st = read_stamp(base / "data" / "PLAYERLIST.xlsx") or {}
    if not st.get("fetched_at"):
        raise ClosingRefused("data/PLAYERLIST.xlsx has no fetch stamp")
    pl_at = _aware(st["fetched_at"], "data/PLAYERLIST.xlsx's fetch stamp")
    if pl_at >= first_tip:
        raise ClosingRefused(f"data/PLAYERLIST.xlsx was fetched {pl_at.isoformat(timespec='minutes')}, "
                             f"after Monday's first tip ({first_tip.isoformat(timespec='minutes')}): "
                             "the closing line's projections are as at the first tip.")
    ov = str((data.injury_overrides or {}).get("last_updated") or "")
    if ov and ov[:10] > monday.isoformat():
        raise ClosingRefused(f"config/INJURY_OVERRIDES.json was last updated {ov}, after Monday "
                             f"{monday}: the closing line's injuries are as at the first tip.")
    return {"rosters_synced": synced, "il_fetched": fetched, "playerlist_fetched": pl_at,
            "overrides_last_updated": ov or None}


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
    row = tag_records.for_close(base, monday, first)          # NoPretipTags is a refusal too
    tags = tag_records.as_tags(row)
    info = check_inputs(base, full, monday=monday, first_tip=first, close=close)
    sp_ = base / "output" / f"live_lines_week{week}.state.json"
    if not sp_.is_file():
        raise ClosingRefused(f"{sp_.relative_to(base).as_posix()} is missing: the closing line is "
                             "priced on the week's seed, which the week's first line records")
    seed = int(json.loads(sp_.read_text(encoding="utf-8"))["seed"])

    data = pre_close_data(base, monday, load_all_data(base, current_week=None))
    p = rl.prepare(base, week, monday, seed=seed, statuses=tags, dry_run=True, data=data,
                   fresh_tags=True)
    key = rl.cache_key(p, sims)
    stamp = close.isoformat(timespec="seconds")
    res, payload = rl.compute(p, sims, extra={
        "generated_at": stamp, "kind": "closing",
        "closing": {"window_close": stamp, "first_tip": first.isoformat(timespec="seconds"),
                    "as_of": monday.isoformat(), "seed": seed,
                    "tags": {"run_id": row["run_id"], "mode": row["mode"], "taken_at": row["taken_at"]},
                    "overrides_last_updated": info["overrides_last_updated"],
                    "rule": "rosters and IL as at the close; tags, projections and results as at "
                            "Monday's first tip; the week's seed (Nick, 11-03)"},
        "cache": key})
    records = rl.calibration_records(p, res, sims, key, source=cal.CLOSING, as_of=stamp)

    sp = tor.run_pass(pre_close_data(base, monday, load_all_data(base, current_week=None)),
                      seed=seed, sims=title_sims, statuses=tags)
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
