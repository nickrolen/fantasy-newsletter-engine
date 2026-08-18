#!/usr/bin/env python3
"""
backtest_extract.py -- Build the betting-line backtest dataset.

WHAT THIS DOES
    Pairs every betting line the newsletter published with the result that
    actually happened, and writes them to data/backtest/published_lines.csv.

WHY IT READS THE HTML AND NOT THE JSON
    output/looking_ahead_week*.json looks like the obvious source, but it is
    not a faithful record. Those files are regenerated whenever a past week is
    re-run, and a re-run today uses today's rosters and injury statuses. Three
    of the 2025-26 files were overwritten this way: looking_ahead_week21.json
    now says Nick was a +419.5 underdog at 6.6%, while the newsletter actually
    published +118.5 at 34.62%.

    Backtesting the regenerated numbers would score a prediction that was
    never made, with information that was not available at the time. The
    published HTML is the only immutable record, so that is what gets parsed.
    It is also the only one committed to the repo -- output/*.json is
    gitignored -- which means this script reproduces from a fresh clone.

    Final SCORES are unaffected by re-runs (a completed week's score is a
    fact), so where both sources exist this script cross-checks them and
    fails loudly if they ever disagree.

TIMING
    The lines for week N are published in week N-1's newsletter, before week
    N is played. WEEK16_NEWSLETTER.html therefore supplies the week 17 lines.

HOW TO USE
    python scripts/backtest_extract.py
    python scripts/backtest_extract.py --output data/backtest/published_lines.csv
    python scripts/backtest_extract.py --strict      # fail if any week is unresolved
"""

import argparse
import csv
import json
import re
import sys
from pathlib import Path
from typing import Optional

from bs4 import BeautifulSoup

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_NEWSLETTER_GLOB = "output/WEEK*_NEWSLETTER.html"
DEFAULT_OUTPUT = "data/backtest/published_lines.csv"

FIELDNAMES = [
    "week", "manager_a", "manager_b", "team_a", "team_b",
    "spread_a", "total_line", "moneyline_a", "win_prob_a",
    "proj_a", "proj_b", "actual_a", "actual_b", "actual_source",
]

RESULT_PATTERN = re.compile(
    r"([A-Za-z0-9 '!.]+?)\s+([\d,]+\.\d\d)\s+def\.\s+([A-Za-z0-9 '!.]+?)\s+([\d,]+\.\d\d)"
)


def load_team_to_manager(root: Path) -> dict:
    """Read the team-name -> manager map from league_config.json.

    Loaded on call, never at import time, so importing this module cannot
    fail on a machine that has not been configured yet.
    """
    config_path = root / "config" / "league_config.json"
    if not config_path.exists():
        raise FileNotFoundError(
            "League config not found at %s. Copy config/league_config.json.example "
            "and fill in your league details." % config_path
        )
    with open(config_path, "r", encoding="utf-8") as handle:
        config = json.load(handle)
    return {team: manager for manager, team in config["manager_to_team"].items()}


def _to_float(raw: str) -> float:
    return float(raw.replace(",", "").replace("+", "").lstrip("ou"))


def parse_betting_tables(soup: BeautifulSoup) -> list:
    """Pull every published betting line out of one newsletter."""
    header = soup.find(
        lambda tag: tag.name in ("h1", "h2", "h3")
        and "betting" in tag.get_text(strip=True).lower()
    )
    if header is None:
        return []

    lines, seen = [], set()
    for table in header.find_all_next("table", limit=8):
        headings = [th.get_text(strip=True).lower() for th in table.find_all("th")]
        if not (any("spread" in h for h in headings)
                and any("moneyline" in h for h in headings)):
            continue

        rows = [[td.get_text(strip=True) for td in tr.find_all("td")]
                for tr in table.find_all("tr")[1:]]
        rows = [r for r in rows if len(r) >= 6]
        if len(rows) != 2:
            continue

        key = (rows[0][0], rows[1][0])
        if key in seen:
            continue
        seen.add(key)

        (team_a, spread_a, total, moneyline_a, win_prob_a, avg_a) = rows[0][:6]
        (team_b, _, _, _, _, avg_b) = rows[1][:6]
        lines.append({
            "team_a": team_a, "team_b": team_b,
            "spread_a": _to_float(spread_a),
            "total_line": _to_float(total),
            "moneyline_a": int(_to_float(moneyline_a)),
            "win_prob_a": float(win_prob_a.rstrip("%")) / 100.0,
            "proj_a": _to_float(avg_a), "proj_b": _to_float(avg_b),
        })
    return lines


def parse_results(soup: BeautifulSoup, team_to_manager: dict) -> dict:
    """Pull the final scores for the week this newsletter covers."""
    text = soup.get_text("\n")
    scores = {}
    for winner, win_score, loser, lose_score in RESULT_PATTERN.findall(text):
        for team, score in ((winner.strip(), win_score), (loser.strip(), lose_score)):
            manager = team_to_manager.get(team)
            if manager is not None:
                scores[manager] = float(score.replace(",", ""))
    return scores


def load_stats_report_scores(root: Path, week: int) -> Optional[dict]:
    """Final scores from output/stats_report_week<N>.json, when present.

    These files are gitignored, so this is a local-only fallback used for
    weeks that never got a newsletter.
    """
    path = root / "output" / ("stats_report_week%d.json" % week)
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as handle:
        report = json.load(handle)
    scores = {}
    for matchup in report.get("matchup_summaries", []):
        scores[matchup["manager_a"]] = round(matchup["score_a"], 2)
        scores[matchup["manager_b"]] = round(matchup["score_b"], 2)
    return scores or None


def build_rows(root: Path, strict: bool = False) -> list:
    team_to_manager = load_team_to_manager(root)

    lines_for_week, actuals_for_week = {}, {}
    newsletters = sorted(root.glob(DEFAULT_NEWSLETTER_GLOB))
    if not newsletters:
        raise FileNotFoundError("No newsletters matched %s" % DEFAULT_NEWSLETTER_GLOB)

    for path in newsletters:
        week = int(re.search(r"WEEK(\d+)", path.name).group(1))
        soup = BeautifulSoup(path.read_text(encoding="utf-8"), "html.parser")
        lines_for_week[week + 1] = parse_betting_tables(soup)
        actuals_for_week[week] = (parse_results(soup, team_to_manager), "newsletter")
        print("  read %-28s lines for week %d, results for week %d"
              % (path.name, week + 1, week))

    rows, unresolved = [], []
    for week in sorted(lines_for_week):
        actual, source = actuals_for_week.get(week, (None, None))
        if not actual:
            fallback = load_stats_report_scores(root, week)
            if fallback:
                actual, source = fallback, "stats_report"
                print("  week %d: no newsletter, results taken from stats_report" % week)

        if not actual:
            unresolved.append(week)
            print("  week %d: lines published but no result available -- skipped" % week)
            continue

        # Cross-check the two sources wherever both exist.
        if source == "newsletter":
            crosscheck = load_stats_report_scores(root, week)
            if crosscheck:
                for manager, value in crosscheck.items():
                    if manager in actual and abs(actual[manager] - value) > 0.011:
                        raise ValueError(
                            "Week %d: newsletter and stats_report disagree on %s "
                            "(%.2f vs %.2f)" % (week, manager, actual[manager], value)
                        )

        for line in lines_for_week[week]:
            manager_a = team_to_manager[line["team_a"]]
            manager_b = team_to_manager[line["team_b"]]
            if manager_a not in actual or manager_b not in actual:
                unresolved.append(week)
                continue
            row = {"week": week, "manager_a": manager_a, "manager_b": manager_b,
                   "actual_a": actual[manager_a], "actual_b": actual[manager_b],
                   "actual_source": source}
            row.update(line)
            rows.append({field: row[field] for field in FIELDNAMES})

    if strict and unresolved:
        raise SystemExit("Unresolved weeks: %s" % sorted(set(unresolved)))
    return rows


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Pair published betting lines with actual results.")
    parser.add_argument("--root", default=str(PROJECT_ROOT),
                        help="Project root (default: repo root)")
    parser.add_argument("--output", default=DEFAULT_OUTPUT,
                        help="CSV to write (default: %s)" % DEFAULT_OUTPUT)
    parser.add_argument("--strict", action="store_true",
                        help="Exit non-zero if any published week is unresolved")
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    print("Reading published newsletters from %s" % (root / "output"))
    rows = build_rows(root, strict=args.strict)

    out_path = root / args.output
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)

    weeks = sorted({row["week"] for row in rows})
    print("\nWrote %d resolved lines (weeks %d-%d) to %s"
          % (len(rows), weeks[0], weeks[-1], out_path))
    return 0


if __name__ == "__main__":
    sys.exit(main())
