#!/usr/bin/env python3
"""
backtest_report.py -- Score the published betting lines and report calibration.

Consumes data/backtest/published_lines.csv (from backtest_extract.py), applies
the scoring rules in modules/backtest_metrics.py, prints a text report, and
optionally writes the calibration figure used in the README.

The report separates three questions that are easy to conflate:

    LEVEL       are the projected team scores right on average?
    DIFFERENCE  is the projected margin right on average?
    CONFIDENCE  is the stated uncertainty honest?

A model can pass one and fail another. Reporting a single "accuracy" number
would hide exactly that.

HOW TO USE
    python scripts/backtest_report.py
    python scripts/backtest_report.py --plot assets/backtest_calibration.png
    python scripts/backtest_report.py --json data/backtest/backtest_summary.json
"""

import argparse
import csv
import json
import sys
from pathlib import Path
from statistics import fmean

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from modules.backtest_metrics import (          # noqa: E402
    score_error_stats, margin_error_stats, standardized_residuals,
    dispersion_ratio, brier_score, brier_skill_score, log_loss, hit_rate,
)

DEFAULT_INPUT = "data/backtest/published_lines.csv"
NUMERIC = ("week", "spread_a", "total_line", "moneyline_a", "win_prob_a",
           "proj_a", "proj_b", "actual_a", "actual_b")


def load_rows(path: Path) -> list:
    with open(path, "r", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise SystemExit("No rows in %s -- run scripts/backtest_extract.py first." % path)
    for row in rows:
        for field in NUMERIC:
            row[field] = float(row[field])
    return rows


def compute(rows: list) -> dict:
    projected, actual = [], []
    for row in rows:
        projected += [row["proj_a"], row["proj_b"]]
        actual += [row["actual_a"], row["actual_b"]]

    proj_margin = [r["proj_a"] - r["proj_b"] for r in rows]
    act_margin = [r["actual_a"] - r["actual_b"] for r in rows]
    win_prob = [r["win_prob_a"] for r in rows]
    a_won = [r["actual_a"] > r["actual_b"] for r in rows]

    residuals = standardized_residuals(proj_margin, act_margin, win_prob)
    totals_over = sum(1 for r in rows
                      if (r["actual_a"] + r["actual_b"]) > r["total_line"])
    covered = sum(1 for r, m in zip(rows, act_margin) if m > -r["spread_a"])
    total_err = [(r["actual_a"] + r["actual_b"]) - r["total_line"] for r in rows]

    return {
        "weeks": sorted({int(r["week"]) for r in rows}),
        "n_lines": len(rows),
        "level": score_error_stats(projected, actual),
        "margin": margin_error_stats(proj_margin, act_margin),
        "dispersion": dispersion_ratio(residuals),
        "brier": brier_score(win_prob, [int(w) for w in a_won]),
        "brier_skill": brier_skill_score(win_prob, [int(w) for w in a_won]),
        "log_loss": log_loss(win_prob, [int(w) for w in a_won]),
        "favourite": hit_rate([p > 0.5 for p in win_prob], a_won),
        "totals_over": totals_over,
        "spread_covered": covered,
        "total_bias": fmean(total_err),
        "total_mae": fmean(abs(e) for e in total_err),
    }


def render(summary: dict) -> str:
    level, margin, disp = summary["level"], summary["margin"], summary["dispersion"]
    weeks = summary["weeks"]
    out = []
    out.append("=" * 66)
    out.append("BETTING-LINE BACKTEST -- weeks %d-%d, %d published lines"
               % (weeks[0], weeks[-1], summary["n_lines"]))
    out.append("=" * 66)

    out.append("\n1. LEVEL -- team-score projections (n=%d)" % level["n"])
    out.append("     mean error   %+8.1f FP   (t = %+.2f)" % (level["bias"], level["t_stat"]))
    out.append("     MAE          %8.1f FP" % level["mae"])
    out.append("     RMSE         %8.1f FP" % level["rmse"])
    out.append("     %d of %d team-weeks landed below projection"
               % (level["below"], level["n"]))

    out.append("\n2. DIFFERENCE -- matchup margins (n=%d)" % margin["n"])
    out.append("     mean error   %+8.1f FP   (t = %+.2f)" % (margin["bias"], margin["t_stat"]))
    out.append("     MAE          %8.1f FP" % margin["mae"])
    out.append("     totals bias  %+8.1f FP   (MAE %.1f)"
               % (summary["total_bias"], summary["total_mae"]))
    out.append("     over/under   %d of %d went OVER"
               % (summary["totals_over"], summary["n_lines"]))
    out.append("     against spread  team_a covered %d of %d"
               % (summary["spread_covered"], summary["n_lines"]))

    out.append("\n3. CONFIDENCE -- is the stated uncertainty honest? (n=%d)" % disp["n"])
    out.append("     rms(z)       %8.3f   95%% CI [%.2f, %.2f]"
               % (disp["rms"], disp["ci_low"], disp["ci_high"]))
    out.append("     mean(z)      %+8.3f" % disp["mean"])
    out.append("     verdict:     %s" % disp["verdict"])

    fav = summary["favourite"]
    out.append("\n4. MONEYLINE (n=%d)" % fav["n"])
    out.append("     favourite won      %d of %d (%.0f%%)"
               % (fav["correct"], fav["n"], 100 * fav["rate"]))
    out.append("     Brier score        %.4f   (0.2500 = always saying 50%%)" % summary["brier"])
    out.append("     Brier skill        %+.1f%%" % (100 * summary["brier_skill"]))
    out.append("     log loss           %.4f   (0.6931 = always saying 50%%)" % summary["log_loss"])

    out.append("\n" + "-" * 66)
    out.append("Sample is small (%d lines over %d weeks) and the two matchups in a"
               % (summary["n_lines"], len(weeks)))
    out.append("given week share a scoring environment, so the effective sample is")
    out.append("smaller still. Treat every interval above as wide.")
    out.append("-" * 66)
    return "\n".join(out)


def write_plot(rows: list, summary: dict, path: Path) -> None:
    """Two-panel diagnostic figure. matplotlib is imported here, not at module
    level, so the numeric report runs without it installed."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        raise SystemExit("matplotlib is required for --plot (pip install matplotlib)")

    surface, ink, ink2 = "#fcfcfb", "#0b0b0b", "#52514e"
    muted, grid, axis_c = "#898781", "#e1e0d9", "#c3c2b7"
    series, ref = "#2a78d6", "#eb6834"
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10, "text.color": ink})

    projected, actual = [], []
    for row in rows:
        projected += [row["proj_a"], row["proj_b"]]
        actual += [row["actual_a"], row["actual_b"]]
    proj_margin = [r["proj_a"] - r["proj_b"] for r in rows]
    act_margin = [r["actual_a"] - r["actual_b"] for r in rows]
    residual = [a - p for a, p in zip(act_margin, proj_margin)]
    bias = summary["level"]["bias"]

    figure, axes = plt.subplots(1, 2, figsize=(11.4, 5.3))
    figure.patch.set_facecolor(surface)

    def frame(ax):
        ax.set_facecolor(surface)
        ax.grid(True, color=grid, lw=0.8, ls="-", zorder=0)
        ax.set_axisbelow(True)
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
        for side in ("left", "bottom"):
            ax.spines[side].set_color(axis_c)
            ax.spines[side].set_linewidth(0.8)
        ax.tick_params(colors=muted, length=0, labelsize=9)

    def limits(values, pad=0.10):
        low, high = min(values), max(values)
        margin_pad = (high - low) * pad
        return low - margin_pad, high + margin_pad

    ax = axes[0]
    frame(ax)
    low, high = limits(projected + actual)
    span = high - low
    ax.plot([low, high], [low, high], color=axis_c, lw=1.6, zorder=1)
    ax.plot([low, high], [low + bias, high + bias], color=ref, lw=1.8, zorder=2)
    ax.scatter(projected, actual, s=66, color=series, edgecolor=surface, lw=2, zorder=3)
    ax.set_xlim(low, high)
    ax.set_ylim(low, high)
    ax.set_aspect("equal")
    ax.set_xlabel("Projected team score (FP)", color=ink2)
    ax.set_ylabel("Actual team score (FP)", color=ink2)
    ax.set_title("Team-score projections run high", color=ink,
                 fontsize=12.5, weight="bold", loc="left", pad=22)
    ax.text(0, 1.012, "%d team-weeks  |  %d of %d landed below projection"
            % (summary["level"]["n"], summary["level"]["below"], summary["level"]["n"]),
            transform=ax.transAxes, color=muted, fontsize=9.5)
    ax.text(low + 0.05 * span, low + 0.085 * span, "perfect prediction", color=muted,
            fontsize=9, rotation=45, rotation_mode="anchor", ha="left", va="bottom")
    ax.text(high - 0.03 * span, high + bias - 0.105 * span, "mean bias %+.0f FP" % bias,
            color=ref, fontsize=9.5, weight="bold", ha="right", va="top")

    ax = axes[1]
    frame(ax)
    low, high = limits(proj_margin + act_margin, 0.13)
    span = high - low
    ax.axhline(0, color=grid, lw=0.8, zorder=0)
    ax.axvline(0, color=grid, lw=0.8, zorder=0)
    ax.plot([low, high], [low, high], color=axis_c, lw=1.6, zorder=1)
    ax.scatter(proj_margin, act_margin, s=66, color=series,
               edgecolor=surface, lw=2, zorder=3)
    ax.set_xlim(low, high)
    ax.set_ylim(low, high)
    ax.set_aspect("equal")
    ax.set_xlabel("Projected margin (FP)", color=ink2)
    ax.set_ylabel("Actual margin (FP)", color=ink2)
    ax.set_title("...but the margin is close to unbiased", color=ink,
                 fontsize=12.5, weight="bold", loc="left", pad=22)
    ax.text(0, 1.012, "%d matchups  |  mean bias %+.0f FP  (t = %.1f, not significant)"
            % (summary["margin"]["n"], summary["margin"]["bias"], summary["margin"]["t_stat"]),
            transform=ax.transAxes, color=muted, fontsize=9.5)
    ax.text(low + 0.05 * span, low + 0.085 * span, "perfect prediction", color=muted,
            fontsize=9, rotation=45, rotation_mode="anchor", ha="left", va="bottom")
    worst = max(range(len(residual)), key=lambda i: abs(residual[i]))
    ax.annotate("wk%d: favoured by %.0f, lost by %.0f"
                % (rows[worst]["week"], abs(proj_margin[worst]), abs(act_margin[worst])),
                xy=(proj_margin[worst], act_margin[worst]),
                xytext=(proj_margin[worst] + 0.17 * span,
                        act_margin[worst] - 0.040 * span),
                color=ink2, fontsize=9, ha="center", va="top",
                arrowprops=dict(arrowstyle="-", color=muted, lw=0.9,
                                shrinkA=2, shrinkB=6))

    weeks = summary["weeks"]
    figure.suptitle("Betting-line backtest - CHS Alumni league, weeks %d-%d (2025-26)"
                    % (weeks[0], weeks[-1]), color=ink, fontsize=13.5,
                    weight="bold", x=0.045, ha="left", y=0.985)
    figure.text(0.045, 0.923,
                "Lines exactly as published in each week's newsletter, "
                "scored against the following week's result.",
                color=muted, fontsize=9.5, ha="left", va="top")
    figure.tight_layout(rect=[0, 0, 1, 0.885])
    path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(path, dpi=170, facecolor=surface)
    plt.close(figure)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Score published betting lines against actual results.")
    parser.add_argument("--input", default=DEFAULT_INPUT,
                        help="Backtest CSV (default: %s)" % DEFAULT_INPUT)
    parser.add_argument("--plot", nargs="?", const="assets/backtest_calibration.png",
                        default=None, help="Write the calibration figure")
    parser.add_argument("--json", dest="json_path", nargs="?",
                        const="data/backtest/backtest_summary.json", default=None,
                        help="Write the summary as JSON")
    args = parser.parse_args(argv)

    rows = load_rows(PROJECT_ROOT / args.input)
    summary = compute(rows)
    print(render(summary))

    if args.json_path:
        path = PROJECT_ROOT / args.json_path
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(summary, handle, indent=2)
        print("\nSummary written to %s" % path)

    if args.plot:
        path = PROJECT_ROOT / args.plot
        write_plot(rows, summary, path)
        print("Figure written to %s" % path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
