#!/usr/bin/env python3
"""
build_dryrun_packet.py -- a past week, rebuilt with today's code, as it stood then.

WHAT IT IS FOR
--------------
The dry run (STATUS_2026-10-12 sec.4): Nick drafts weeks 21 and 16 of 2025-26
through the real Step 7, from packets this script assembles, so the shape of
a week-1 newsletter -- grid, ANGLES, standing threads, advice preview,
voice, lore -- is seen before it ships.

POINT IN TIME
-------------
The archive is an end-of-season copy, and the pipeline reads accumulated
state. Rebuilt naively, week 16 would know weeks 17-23. So a sandbox is
built per week, and every file is put back to how it stood after week N-1:

  exact by construction
    PLAYERLOG / LINEUPS / waivers       truncated to the week being built
    data/historical/*                    2025-26 removed: those files only
                                         ever hold COMPLETED seasons
    LEAGUEHISTORY.xlsx                   2025-26 subtracted (its stored
                                         all_standings row: W-L, titles, points)
    POTW_HISTORY, RECENT_CONTENT         entries / snapshot from before week N
  rebuilt by the real pipeline
    RECORDS.json                         all-time state at the start of
                                         2025-26 (live, repaired RECORDS minus
                                         the 2025-26 regular season), season
                                         sections empty, then weeks 1..N-1
                                         replayed through generate_stats_report
  not recoverable (STATUS sec.4 "known limit")
    PLAYERLIST, ROSTERS, INJURY_OVERRIDES  end-of-season copies. Week N runs
                                         in --repro, which freezes betting
                                         lines from the archived report.
    payouts / postseason money rules     2026-27's. 2025-26's are not in config.

--verify replays the whole season and compares the rebuilt RECORDS with the
archived end-of-season file; a packet is only as good as that comparison.

USAGE
    py scripts/build_dryrun_packet.py --season 2025-26 --week 21
    py scripts/build_dryrun_packet.py --season 2025-26 --verify

Writes output/dryrun/<season>_week<N>/ (gitignored: it holds the lore export).
"""

from __future__ import annotations

import argparse
import copy
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "output" / "dryrun"

CODE_DIRS = ("modules", "scripts", "templates")
REPO_CONFIG_FILES = ("LEAGUE_LORE.json", "PLAYER_AGES.json", "DRAFT_PICK_VALUES.json",
                     "ROOKIE_SEASONS.json")
HISTORY_LISTS = ("all_matchups.json", "all_standings.json", "all_drafts.json",
                 "all_trades.json")


def log(msg):
    print(f"  {msg}", flush=True)


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def season_config(season: str) -> dict:
    """Today's league_config with the replayed season's own season block,
    league key, team names and roster shape."""
    cur = json.loads((ROOT / "config" / "league_config.json").read_text(encoding="utf-8"))
    old = json.loads((ROOT / "archive" / season / "config" / "league_config.json")
                     .read_text(encoding="utf-8"))
    if old["season"]["current"] != season:
        raise ValueError(f"archive/{season} config says {old['season']['current']}")
    gap = int(cur["season"]["current"][:4]) - int(season[:4])
    cfg = copy.deepcopy(cur)
    s = cfg["season"]
    for k in ("current", "current_long", "regular_season_weeks", "playoff_start_week",
              "total_weeks", "nba_schedule_file"):
        s[k] = old["season"][k]
    s["data_era_season_number"] = cur["season"]["data_era_season_number"] - gap
    s["league_season_number"] = cur["season"]["league_season_number"] - gap
    cfg["yahoo"]["current_league_key"] = old["yahoo"]["current_league_key"]
    cfg["manager_to_team"] = old["manager_to_team"]
    ls = dict(old["league_structure"])
    for k, v in cur["league_structure"].items():
        ls.setdefault(k, v)
    ls["total_rounds"] = ls["roster_size"] - ls["il_slots"]
    # COUNTERFACTUAL, for the dry run only: 2025-26 had no add budget, so
    # the advice engine (rightly) refuses to define replacement level. The
    # packet is a test of what Section 10's preview looks like, so this
    # season is given 2026-27's budget. The packet README says so.
    ls["weekly_add_budget_from"] = season
    ls["_dryrun_note"] = ("weekly_add_budget_from set to the replayed season "
                          "so the C2/C3 preview renders; not a fact about it")
    cfg["league_structure"] = ls
    return cfg


# ---------------------------------------------------------------------------
# History and accumulated state, put back to before week N
# ---------------------------------------------------------------------------

def strip_season_history(src: Path, dst: Path, season: str) -> None:
    dst.mkdir(parents=True, exist_ok=True)
    for f in src.iterdir():
        if f.suffix != ".json":
            continue
        blob = json.loads(f.read_text(encoding="utf-8"))
        if f.name in HISTORY_LISTS:
            blob = [r for r in blob if r.get("season") != season]
        elif f.name == "all_teams.json":
            blob.pop(season, None)
        elif f.name == "DRAFT_PERFORMANCE.json":
            blob["picks"] = [p for p in blob.get("picks", []) if p.get("season") != season]
            blob["seasons"] = [x for x in blob.get("seasons", []) if x != season]
        elif f.name == "HISTORICAL_PLAYERLOG.json":
            long = f"{season[:4]}-{int(season[:4]) + 1}"
            blob = [r for r in blob if str(r.get("season_year")) != long]
        (dst / f.name).write_text(json.dumps(blob), encoding="utf-8")


def _wl(s: str):
    """(wins, losses) from a record string. Raises on a W-L-T record.

    It used to take the first two fields and drop a third, which would have
    silently thrown away a tie. LEAGUEHISTORY stores only W-L today; if that
    changes, the rewind has to learn about ties rather than guess.
    """
    parts = s.strip("()").split("-")
    if len(parts) > 2:
        raise ValueError(
            f"record {s!r} carries a tie; rewind_leaguehistory only handles "
            "W-L. Teach it about ties before replaying a season with one.")
    a, b = parts
    return int(a), int(b)


def rewind_leaguehistory(path: Path, season_rows: dict) -> None:
    """Take the replayed season back out of the to-date totals."""
    lh = pd.read_excel(path)
    for i, row in lh.iterrows():
        r = season_rows[row["manager_name"]]
        lh.at[i, "seasons_completed"] = int(row["seasons_completed"]) - 1
        w, l = _wl(row["regular_season_record"])
        lh.at[i, "regular_season_record"] = f"({w - r['reg_wins']}-{l - r['reg_losses']})"
        pw, pl = _wl(row["playoff_record"])
        lh.at[i, "playoff_record"] = (f"({pw - (r['wins'] - r['reg_wins'])}-"
                                      f"{pl - (r['losses'] - r['reg_losses'])})")
        lh.at[i, "titles_won"] = int(row["titles_won"]) - int(r["regular_season_rank"] == 1)
        lh.at[i, "playoff_championships"] = (int(row["playoff_championships"])
                                             - int(r.get("playoff_rank") == 1))
        lh.at[i, "total_points_scored_to_date"] = round(
            float(row["total_points_scored_to_date"]) - float(r["points_for"]), 2)
    lh.to_excel(path, index=False)


def season_start_records(live: dict, archived: dict, season: str,
                         season_rows: dict, reg_games: list) -> dict:
    """RECORDS as they stood before week 1 of `season`.

    all_time comes from the LIVE file (repaired: careers and H2H are
    regular-season only) with the season's regular-season games and all its
    points taken back out, and any single-entry record set during it
    dropped. Season sections are emptied, as start_new_season does.
    """
    rec = copy.deepcopy(live)
    at = rec["all_time"]
    for g in reg_games:
        key = "_vs_".join(sorted([g["winner"], g["loser"]]))
        at["h2h"][key][g["winner"].lower()] -= 1
    for mgr, c in at["manager_careers"].items():
        r = season_rows[mgr]
        c["total_wins"] -= r["reg_wins"]
        c["total_losses"] -= r["reg_losses"]
        c["total_points_scored"] = round(c["total_points_scored"] - r["points_for"], 2)
        gp = c["total_wins"] + c["total_losses"]
        c["games_played"] = gp
        c["win_pct"] = round(100 * c["total_wins"] / gp, 1) if gp else 0
    _drop_season_entries(at, season)
    for k in ("season_records", "h2h_season", "manager_season_totals", "weekly_scores",
              "season_fppg_stats", "cumulative_blunders", "single_week_blunders_high"):
        if k in rec:
            rec[k] = {}
    rec["last_updated_week"] = 0
    rec["last_history_week"] = 0
    rec["team_name_history"] = archived.get("team_name_history", rec.get("team_name_history"))
    return rec


def _drop_season_entries(node, season):
    """Remove every record entry tagged with `season`, at any depth.
    A single-entry record (a dict tagged with it) becomes empty; a list
    loses the tagged items."""
    if isinstance(node, dict):
        for k in list(node):
            v = node[k]
            if isinstance(v, dict) and v.get("season") == season:
                node[k] = {}
            elif isinstance(v, list):
                node[k] = [x for x in v if not (isinstance(x, dict) and x.get("season") == season)]
                for x in node[k]:
                    _drop_season_entries(x, season)
            else:
                _drop_season_entries(v, season)


def truncate_season_data(src_data: Path, dst_data: Path, week: int) -> None:
    for name in ("PLAYERLOG.xlsx", "LINEUPS.xlsx"):
        df = pd.read_excel(src_data / name)
        df[df["week"] <= week].to_excel(dst_data / name, index=False)
    for f in dst_data.glob("waivers_week*.txt"):
        n = int(f.stem.replace("waivers_week", ""))
        if n > week:
            f.unlink()


# ---------------------------------------------------------------------------
# The sandbox
# ---------------------------------------------------------------------------

def build_sandbox(season: str, week: int, dest: Path) -> dict:
    arch = ROOT / "archive" / season
    if dest.exists():
        shutil.rmtree(dest)
    for d in CODE_DIRS:
        shutil.copytree(ROOT / d, dest / d, ignore=shutil.ignore_patterns("__pycache__"))
    (dest / "config").mkdir(parents=True)
    (dest / "data").mkdir()
    (dest / "output").mkdir()
    for f in (arch / "config").glob("*"):
        if f.is_file() and f.name != "league_config.json":
            shutil.copy2(f, dest / "config" / f.name)
    for name in REPO_CONFIG_FILES:
        if (ROOT / "config" / name).exists():
            shutil.copy2(ROOT / "config" / name, dest / "config" / name)
    (dest / "config" / "league_config.json").write_text(
        json.dumps(season_config(season), indent=2), encoding="utf-8")
    snap = arch / "config" / "snapshots" / f"RECENT_CONTENT_pre_week{week}.json"
    if snap.exists():
        shutil.copy2(snap, dest / "config" / "RECENT_CONTENT.json")
    (dest / "config" / "snapshots").mkdir(exist_ok=True)

    for f in (arch / "data").glob("*"):
        if f.is_file():
            shutil.copy2(f, dest / "data" / f.name)
    cfg = season_config(season)
    nba = cfg["season"]["nba_schedule_file"]
    shutil.copy2(ROOT / nba, dest / nba)
    strip_season_history(ROOT / "data" / "historical", dest / "data" / "historical", season)

    standings = json.loads((ROOT / "data" / "historical" / "all_standings.json")
                           .read_text(encoding="utf-8"))
    rows = {r["manager"]: r for r in standings if r["season"] == season}
    if len(rows) != 4:
        raise ValueError(f"all_standings has {len(rows)} rows for {season}")
    rewind_leaguehistory(dest / "data" / "LEAGUEHISTORY.xlsx", rows)

    matchups = json.loads((ROOT / "data" / "historical" / "all_matchups.json")
                          .read_text(encoding="utf-8"))
    reg_through = cfg["season"]["regular_season_weeks"]
    reg_games = [m for m in matchups if m["season"] == season and m["week"] <= reg_through]
    live = json.loads((ROOT / "config" / "RECORDS.json").read_text(encoding="utf-8"))
    archived = json.loads((arch / "config" / "RECORDS.json").read_text(encoding="utf-8"))
    start = season_start_records(live, archived, season, rows, reg_games)
    (dest / "config" / "RECORDS.json").write_text(json.dumps(start, indent=2), encoding="utf-8")

    potw = dest / "config" / "POTW_HISTORY.json"
    if potw.exists():
        blob = json.loads(potw.read_text(encoding="utf-8"))
        blob["seasons"][season] = [h for h in blob["seasons"].get(season, [])
                                   if int(h["week"]) < week]
        potw.write_text(json.dumps(blob, indent=2), encoding="utf-8")
    return {"rows": rows, "archived": archived, "full_data": arch / "data"}


def run(dest: Path, *args, timeout=900) -> None:
    cmd = [sys.executable, str(dest / "scripts" / args[0]), *map(str, args[1:])]
    t = time.time()
    p = subprocess.run(cmd, cwd=dest, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=timeout)
    if p.returncode != 0:
        tail = (p.stdout + p.stderr)[-3000:]
        raise RuntimeError(f"{' '.join(map(str, args))} exited {p.returncode}:\n{tail}")
    log(f"{args[0]} {' '.join(map(str, args[1:]))}  ({time.time() - t:.0f}s)")


def replay(dest: Path, full_data: Path, through: int) -> None:
    """Weeks 1..through, each on data truncated to that week, saving RECORDS."""
    for k in range(1, through + 1):
        truncate_season_data(full_data, dest / "data", k)
        run(dest, "generate_stats_report.py", "--week", k, "--base-path", dest,
            "--fast", "--no-fetch-injuries", "--no-freshness", "--allow-stale-schedule")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--season", required=True)
    ap.add_argument("--week", type=int, help="the week to build a packet for")
    ap.add_argument("--stage", choices=("sandbox", "replay", "report", "packet"),
                    required=True,
                    help="sandbox: build it; replay: weeks --from..--to into RECORDS; "
                         "report: week N in --repro; packet: assemble")
    ap.add_argument("--from", dest="frm", type=int, default=1)
    ap.add_argument("--to", type=int)
    args = ap.parse_args(argv)
    week = args.week
    dest = OUT / f"_sandbox_{args.season}_week{week}"
    arch = ROOT / "archive" / args.season
    if args.stage == "sandbox":
        build_sandbox(args.season, week, dest)
        log(f"sandbox ready: {dest}")
    elif args.stage == "replay":
        for k in range(args.frm, (args.to or week - 1) + 1):
            truncate_season_data(arch / "data", dest / "data", k)
            run(dest, "generate_stats_report.py", "--week", k, "--base-path", dest,
                "--fast", "--no-fetch-injuries", "--no-freshness", "--allow-stale-schedule")
    elif args.stage == "report":
        report(args.season, week, dest)
    else:
        packet(args.season, week, dest)
    return 0


def packet(season: str, week: int, dest: Path) -> Path:
    """The files Step 7 uploads, as they stood at week N, plus a README."""
    arch = ROOT / "archive" / season
    out = OUT / f"{season}_week{week}"
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    so = dest / "output"
    for name in (f"stats_report_week{week}.md", f"stats_report_week{week}.json",
                 f"advice_preview_week{week}.html", f"angles_week{week}.json"):
        if not (so / name).exists():
            raise FileNotFoundError(f"{name} missing: run --stage report first")
        shutil.copy2(so / name, out / name)
    # Lore as it read at week N: the sandbox's code and data, its own copy
    # of the lore file, derived entries refreshed against week-N data.
    for f in ("propose_lore.py", "review_lore.py"):
        shutil.copy2(ROOT / "scripts" / f, dest / "scripts" / f)
    shutil.copy2(ROOT / "modules" / "lore.py", dest / "modules" / "lore.py")
    shutil.copy2(ROOT / "config" / "LEAGUE_LORE.json", dest / "config" / "LEAGUE_LORE.json")
    run(dest, "propose_lore.py", "--refresh", "--base", dest)
    run(dest, "review_lore.py", "--export", "--base", dest)
    shutil.copy2(so / "lore_for_drafting.json", out / "lore_for_drafting.json")
    for name in ("VOICE.md", "newsletter_template.md", "NEWSLETTER_PROMPTS.md"):
        shutil.copy2(ROOT / "templates" / name, out / name)
    snap = arch / "config" / "snapshots" / f"RECENT_CONTENT_pre_week{week}.json"
    shutil.copy2(snap, out / "RECENT_CONTENT.json")
    shutil.copy2(arch / "config" / "INJURY_OVERRIDES.json", out / "INJURY_OVERRIDES.json")
    notes = []
    recap = arch / "config" / "LAST_WEEK_RECAP.md"
    head = recap.read_text(encoding="utf-8").splitlines()[0] if recap.exists() else ""
    if f"Week {week - 1} " in head or head.rstrip().endswith(f"Week {week - 1}"):
        shutil.copy2(recap, out / "LAST_WEEK_RECAP.md")
    else:
        notes.append(f"No LAST_WEEK_RECAP.md: the only archived recap is \"{head.strip('# ')}\", "
                     f"not week {week - 1}'s, and it is written from the finished "
                     f"newsletter, which is not archived for week {week - 1}. Draft without "
                     f"it; continuity from last week will be thin, which is the archive's "
                     f"gap, not the voice's.")
    ctx = arch / "data" / f"weeklycontextinput_week{week}.json"
    if ctx.exists():
        shutil.copy2(ctx, out / ctx.name)
    angles = json.loads((out / f"angles_week{week}.json").read_text(encoding="utf-8"))
    # Read `dead`, not `lead`. A dead week KEEPS its best angle under "lead"
    # as reference-only material, so `lead` is truthy either way and this
    # line called week 16 -- the no-lead week the dry run exists to test --
    # "a lead", contradicting the NO LEAD block in its own stats report.
    lead = "NO LEAD" if angles.get("dead") else "a lead"
    uploads = [f for f in ("stats_report_week%d.md" % week, "VOICE.md", "newsletter_template.md",
                           "LAST_WEEK_RECAP.md", "RECENT_CONTENT.json", "INJURY_OVERRIDES.json",
                           "lore_for_drafting.json", f"weeklycontextinput_week{week}.json")
               if (out / f).exists()]
    n_lore = len(json.loads((out / "lore_for_drafting.json").read_text(encoding="utf-8"))["entries"])
    readme = f"""# Dry run: {season} week {week}

Built {time.strftime('%Y-%m-%d %H:%M')} by scripts/build_dryrun_packet.py, from today's code,
with every file put back to how it stood after week {week - 1} (see the script's
header for exactly how). The ANGLES block has {lead} this week.

## Run it exactly as on 10-26

1. Open a **fresh chat** (not the project chat).
2. Use the three prompts in `NEWSLETTER_PROMPTS.md`, Part 1 to 3, as written.
   Upload with Part 1:
{chr(10).join('   - `' + f + '`' for f in uploads)}
3. Save the combined draft as `WEEK{week}_DRAFT.md` in this folder.
4. Tell the session; it runs the claim check against this week's sandbox and
   builds the HTML (which runs the table check).

`advice_preview_week{week}.html` is the Section 10 preview: open it in a browser.
It is never part of the newsletter.

## What is as it was, and what is not

As it was: results, standings, records (rebuilt by replaying weeks 1-{week - 1}
through the real pipeline and checked against the matchups), races, POTW
history, recent content, and lore -- {n_lore} approved entries, derived ones
re-read against week-{week} data (a loyalty count is the one it was then).

Not as it was -- read these as artefacts of the replay, not of the voice:
- PLAYERLIST, ROSTERS and INJURY_OVERRIDES are end-of-season copies. The betting
  lines are frozen from the archived report; the grid and advice numbers are not
  what they were that week.
- Money is described with **2026-27's** rules ($180 regular-season pot, $90
  playoff pot, semifinal liability). 2025-26's rules were different and are not
  in config. If the lead is a money line, its numbers are this year's.
- The standing threads show a **Cup race**. {season} had no Cup; the thread is
  drawn from 2026-27's rules. Do not write about a Cup in this week.
- 2025-26 had no add budget; the advice preview assumes 2026-27's three adds.
- The prompts call this the league's twelfth season; {season} was the eleventh.
- Written lore is Nick's words as written in 2026, and may know things that
  happened after week {week}. Derived lore does not.
""" + ("".join(f"- {n}\n" for n in notes))
    (out / "README.md").write_text(readme, encoding="utf-8")
    log(f"packet: {out}")
    for f in sorted(out.iterdir()):
        log(f"  {f.name}")
    return out


def report(season: str, week: int, dest: Path) -> None:
    """Week N as the live pipeline would have run it: RECORDS after N-1,
    data through N, betting lines frozen from the archived report."""
    arch = ROOT / "archive" / season
    recs = json.loads((dest / "config" / "RECORDS.json").read_text(encoding="utf-8"))
    at = recs.get("last_updated_week")
    if at not in (week - 1, week):
        raise RuntimeError(f"RECORDS is at week {at}; replay weeks 1..{week - 1} first")
    truncate_season_data(arch / "data", dest / "data", week)
    for name in (f"stats_report_week{week}.json", f"looking_ahead_week{week}.json"):
        if (arch / "output" / name).exists():
            shutil.copy2(arch / "output" / name, dest / "output" / name)
    snap = arch / "config" / "snapshots" / f"RECENT_CONTENT_pre_week{week}.json"
    if snap.exists():
        shutil.copy2(snap, dest / "config" / "snapshots" / snap.name)
        shutil.copy2(snap, dest / "config" / "RECENT_CONTENT.json")
    # 1. A normal run saves week N into RECORDS, as the live pipeline does
    #    before the formatter reads it (the ANGLES block takes the current
    #    season's results from RECORDS). --repro alone never saves, and the
    #    block came out "unavailable".
    if at == week - 1:
        run(dest, "generate_stats_report.py", "--week", week, "--base-path", dest,
            "--fast", "--no-fetch-injuries", "--no-freshness", "--allow-stale-schedule")
    for name in (f"stats_report_week{week}.json", f"looking_ahead_week{week}.json"):
        if (arch / "output" / name).exists():
            shutil.copy2(arch / "output" / name, dest / "output" / name)
    # 2. The report itself, in --repro: week N is already recorded, and the
    #    betting lines are frozen from the archived report.
    run(dest, "generate_stats_report.py", "--week", week, "--base-path", dest,
        "--repro", "--no-fetch-injuries", "--allow-stale-schedule")
    run(dest, "format_stats_report.py", "--week", week, "--base-path", dest)


if __name__ == "__main__":
    sys.exit(main())
