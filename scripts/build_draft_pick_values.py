#!/usr/bin/env python3
"""
build_draft_pick_values.py

Generates config/DRAFT_PICK_VALUES.json from historical draft performance data.

PICK-LEVEL GRANULARITY WITH BLENDED VALUES:
    Expected values are computed per individual pick number (1-36) using a
    70/30 blend of raw historical average and regression-fitted value.
    This preserves pick-level personality (some picks historically hit harder)
    while reining in outliers from small sample sizes.

    Blend formula: expected = 0.70 * raw_mean + 0.30 * regression_fitted

EXPANSION ROUND DECAY (R8-R9, picks 29-36):
    R8-R9 picks cannot use the R1-R7 regression or 2025-26 raw data because:
    - The R1-R7 regression is nearly flat and overestimates expansion picks
    - The 2025-26 R8-R9 data is contaminated (mid-season IL+ to BN conversion
      filled slots with established stars, not true draft-caliber players)
    Instead, R8-R9 picks anchor at the R7 blended average and decay at a
    configurable rate (default 0.5 FPPG per pick), landing in the "Roster Churn"
    and "Waiver Replacement" tiers where they belong.

KEEPER ERA ONLY (2021-22 onward):
    Pre-keeper drafts (2017-18 through 2020-21) are excluded because the full
    player pool was available in rounds 1-7, making those picks incomparable
    to keeper-era drafts where 24 players are held off the board.

    2020-21 was technically the first keeper season, but no keepers existed yet
    (first year of the system), so the draft pool was still fully open.
    2021-22 was the first draft where keepers were actually held off the board.

Picks 1-28 (R1-R7): 70/30 blend from keeper-era draft data (5 seasons).
Picks 29-36 (R8-R9): Cliff decay from R7 average.

Two value metrics per pick:
    - Expected FPPG: How productive the player is per game
    - Expected Total FP: How much cumulative production to expect

Re-run each offseason after updating historical data to keep values current.

Usage:
    python scripts/build_draft_pick_values.py
    python scripts/build_draft_pick_values.py --dry-run   # Preview without saving

Requires: data/historical/DRAFT_PERFORMANCE.json (built by extract_draft_fppg.py)
Outputs:  config/DRAFT_PICK_VALUES.json
"""

import argparse
import json
import math
import statistics
import sys
from collections import defaultdict
from pathlib import Path

# Add project root to path for config imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from modules.data_loader import KEEPER_ERA_START, LEAGUE_STRUCTURE, NUM_TEAMS

PROJECT_ROOT = Path(__file__).parent.parent
DRAFT_PERF_FILE = PROJECT_ROOT / "data" / "historical" / "DRAFT_PERFORMANCE.json"
OUTPUT_FILE = PROJECT_ROOT / "config" / "DRAFT_PICK_VALUES.json"

# Minimum games played to count a draft pick's season
MIN_GP = 5

# Blend ratio: raw average vs regression line (for picks 1-28)
# Changed from 70/30 to 50/50 to smooth out small-sample variance
RAW_WEIGHT = 0.50
REG_WEIGHT = 0.50

# Maximum deviation from regression line (FPPG)
# Prevents outlier picks from having unrealistic expectations
MAX_DEVIATION_FROM_REGRESSION = 1.5

# Teams and draft structure from config
TEAMS = NUM_TEAMS

HISTORICAL_DRAFT_ROUNDS = LEAGUE_STRUCTURE.get("historical_draft_rounds", 7)
HISTORICAL_PICKS = HISTORICAL_DRAFT_ROUNDS * TEAMS

TOTAL_DRAFT_ROUNDS = LEAGUE_STRUCTURE.get("total_draft_rounds", 9)
TOTAL_PICKS = TOTAL_DRAFT_ROUNDS * TEAMS

# Expansion round decay: FPPG and Total FP drop per pick beyond P28
# These are aggressive because R8-R9 pick from a much worse pool than R1-R7
EXPANSION_FPPG_DECAY_PER_PICK = 0.5   # FPPG drop per pick after P28
EXPANSION_TFP_DECAY_PER_PICK = 40.0   # Total FP drop per pick after P28

# Tier definitions
TIER_THRESHOLDS = [
    (42.0, "Elite Draft Asset"),
    (38.0, "Strong Draft Asset"),
    (36.0, "Solid Contributor"),
    (34.0, "Fringe Contributor"),
    (32.0, "Roster Churn"),
    (0.0,  "Waiver Replacement"),
]

TIER_DESCRIPTIONS = {
    "Elite Draft Asset": {
        "description": (
            "Likely keeper candidate. Best non-keeper player available - expect a "
            "high-upside investment or established star not worth a keeper slot. "
            "Reasonable to expect this player becomes a top-6 roster piece and future keeper."
        ),
        "trade_notes": (
            "Premium asset. Should only be traded for a proven contributor or as "
            "the centerpiece of a significant package."
        ),
    },
    "Strong Draft Asset": {
        "description": (
            "Possible keeper, reliable starter at minimum. These players are strong "
            "contributors who may develop into keeper-worthy assets, but it's less "
            "certain than Round 1. Floor is still a dependable starter."
        ),
        "trade_notes": (
            "Valuable asset with upside. Worth including in trades as a meaningful "
            "sweetener or to bridge a gap in player value."
        ),
    },
    "Solid Contributor": {
        "description": (
            "Dependable starter, unlikely to become a keeper. These players fill "
            "roster spots and contribute, but rarely break into a team's top 6. "
            "Solid but unspectacular."
        ),
        "trade_notes": (
            "Moderate asset. Useful in trades as a secondary piece but not enough "
            "on its own to swing a deal."
        ),
    },
    "Fringe Contributor": {
        "description": (
            "Useful roster piece that could stick or could get dropped. This is the "
            "boundary between players who contribute all season and players who get "
            "replaced by waiver pickups. Some hits, some misses."
        ),
        "trade_notes": (
            "Low-value asset. Functions as a throw-in to balance a trade rather "
            "than a meaningful piece."
        ),
    },
    "Roster Churn": {
        "description": (
            "Likely replaced via waivers by midseason. The player drafted here may "
            "start on the roster but has a high probability of being dropped within "
            "the first few weeks as better options emerge on the waiver wire."
        ),
        "trade_notes": (
            "Minimal asset. Near-zero standalone trade value. Only useful as filler "
            "in a multi-piece deal."
        ),
    },
    "Waiver Replacement": {
        "description": (
            "Dart throw - most get dropped early. Occasionally a breakout candidate "
            "lands here, but the expected outcome is a player who doesn't last on "
            "the roster past October. Functionally equivalent to a top waiver wire pickup."
        ),
        "trade_notes": (
            "Negligible trade value. Not enough to influence any deal on its own."
        ),
    },
}


def get_tier(fppg: float) -> str:
    """Assign a tier based on mid-point FPPG."""
    for threshold, tier_name in TIER_THRESHOLDS:
        if fppg >= threshold:
            return tier_name
    return "Waiver Replacement"


def linear_regression(x_vals, y_vals):
    """
    Simple linear regression on raw data points.
    Returns (intercept, slope, residual_std_error).
    """
    n = len(x_vals)
    x_mean = sum(x_vals) / n
    y_mean = sum(y_vals) / n
    ss_xy = sum((x - x_mean) * (y - y_mean) for x, y in zip(x_vals, y_vals))
    ss_xx = sum((x - x_mean) ** 2 for x in x_vals)
    slope = ss_xy / ss_xx if ss_xx != 0 else 0
    intercept = y_mean - slope * x_mean

    predictions = [intercept + slope * x for x in x_vals]
    residuals = [(y - yhat) ** 2 for y, yhat in zip(y_vals, predictions)]
    rse = math.sqrt(sum(residuals) / (n - 2)) if n > 2 else 0

    return intercept, slope, rse


def pick_to_round(pick_number: int) -> int:
    """Convert 1-indexed pick number to round number (4 teams)."""
    return (pick_number - 1) // TEAMS + 1


def main():
    parser = argparse.ArgumentParser(description="Build data-driven DRAFT_PICK_VALUES.json")
    parser.add_argument("--dry-run", action="store_true", help="Preview without saving")
    args = parser.parse_args()

    # ---- Load draft performance data ----
    if not DRAFT_PERF_FILE.exists():
        print(f"ERROR: {DRAFT_PERF_FILE} not found!")
        print("Run extract_draft_fppg.py first to generate it.")
        sys.exit(1)

    with open(DRAFT_PERF_FILE, "r", encoding="utf-8") as f:
        perf_data = json.load(f)

    picks = perf_data["picks"]
    all_seasons = perf_data["seasons"]

    keeper_era_seasons = [s for s in all_seasons if s >= KEEPER_ERA_START]
    print(f"Loaded {len(picks)} total draft picks across {len(all_seasons)} seasons")
    print(f"Filtering to keeper era: {KEEPER_ERA_START}+ ({len(keeper_era_seasons)} seasons: {', '.join(keeper_era_seasons)})")
    print(f"Blend ratio: {RAW_WEIGHT:.0%} raw average / {REG_WEIGHT:.0%} regression (picks 1-{HISTORICAL_PICKS})")
    print(f"Expansion decay: {EXPANSION_FPPG_DECAY_PER_PICK} FPPG/pick, {EXPANSION_TFP_DECAY_PER_PICK} TFP/pick (picks {HISTORICAL_PICKS+1}-{TOTAL_PICKS})")

    # ---- Collect all qualifying data points (R1-R7 only for regression) ----
    fppg_x, fppg_y = [], []
    tfp_x, tfp_y = [], []
    pick_raw_fppgs = defaultdict(list)
    pick_raw_totalfps = defaultdict(list)
    skipped = 0

    for p in picks:
        pn = p["pick_number"]
        r = p["round"]
        season = p["season"]

        if season < KEEPER_ERA_START:
            skipped += 1
            continue

        # Only use R1-R7 draft picks for regression fitting
        if r <= 7:
            is_draft = True
        else:
            is_draft = False

        if is_draft and p["fppg"] is not None and p["gp"] >= MIN_GP:
            fppg_x.append(pn)
            fppg_y.append(p["fppg"])
            tfp_x.append(pn)
            tfp_y.append(p["total_fp"])
            pick_raw_fppgs[pn].append(p["fppg"])
            pick_raw_totalfps[pn].append(p["total_fp"])

    print(f"Excluded {skipped} pre-keeper-era picks")
    print(f"Regression data: {len(fppg_x)} qualifying data points across picks 1-{max(fppg_x)}")

    # ---- Fit regressions on R1-R7 raw data points ----
    fppg_intercept, fppg_slope, fppg_rse = linear_regression(fppg_x, fppg_y)
    tfp_intercept, tfp_slope, tfp_rse = linear_regression(tfp_x, tfp_y)

    print(f"\nFPPG regression: FPPG = {fppg_intercept:.2f} + ({fppg_slope:.4f} * pick)")
    print(f"  Residual std error: {fppg_rse:.2f}")
    print(f"Total FP regression: TFP = {tfp_intercept:.1f} + ({tfp_slope:.2f} * pick)")
    print(f"  Residual std error: {tfp_rse:.1f}")

    # ---- Compute blended values for P1-P28 first (needed for R7 anchor) ----
    blended_fppg_values = {}
    blended_tfp_values = {}

    for pn in range(1, HISTORICAL_PICKS + 1):
        reg_fppg = fppg_intercept + fppg_slope * pn
        reg_tfp = tfp_intercept + tfp_slope * pn

        raw_fppgs = pick_raw_fppgs.get(pn, [])
        raw_tfps = pick_raw_totalfps.get(pn, [])

        if raw_fppgs:
            raw_fppg_mean = statistics.mean(raw_fppgs)
            raw_tfp_mean = statistics.mean(raw_tfps)
            blended_fppg = RAW_WEIGHT * raw_fppg_mean + REG_WEIGHT * reg_fppg
            blended_tfp = RAW_WEIGHT * raw_tfp_mean + REG_WEIGHT * reg_tfp
            
            # Apply deviation cap: don't let blended value stray more than
            # MAX_DEVIATION_FROM_REGRESSION from the regression line
            if blended_fppg > reg_fppg + MAX_DEVIATION_FROM_REGRESSION:
                blended_fppg = reg_fppg + MAX_DEVIATION_FROM_REGRESSION
            elif blended_fppg < reg_fppg - MAX_DEVIATION_FROM_REGRESSION:
                blended_fppg = reg_fppg - MAX_DEVIATION_FROM_REGRESSION
            
            # Same cap for Total FP (scaled: ~60x the FPPG cap based on typical TFP/FPPG ratio)
            tfp_cap = MAX_DEVIATION_FROM_REGRESSION * 60
            if blended_tfp > reg_tfp + tfp_cap:
                blended_tfp = reg_tfp + tfp_cap
            elif blended_tfp < reg_tfp - tfp_cap:
                blended_tfp = reg_tfp - tfp_cap
            
            blended_fppg_values[pn] = blended_fppg
            blended_tfp_values[pn] = blended_tfp
        else:
            blended_fppg_values[pn] = reg_fppg
            blended_tfp_values[pn] = reg_tfp

    # ---- Compute R7 anchor for expansion decay ----
    r7_picks = list(range(HISTORICAL_PICKS - TEAMS + 1, HISTORICAL_PICKS + 1))  # P25-P28
    r7_avg_fppg = statistics.mean([blended_fppg_values[pn] for pn in r7_picks])
    r7_avg_tfp = statistics.mean([blended_tfp_values[pn] for pn in r7_picks])

    print(f"\nR7 anchor (P25-P28 blended avg): {r7_avg_fppg:.1f} FPPG, {r7_avg_tfp:.0f} TFP")

    # ---- Build expansion picks (P29-P36) using cliff decay ----
    for pn in range(HISTORICAL_PICKS + 1, TOTAL_PICKS + 1):
        steps_beyond_r7 = pn - HISTORICAL_PICKS
        blended_fppg_values[pn] = r7_avg_fppg - (steps_beyond_r7 * EXPANSION_FPPG_DECAY_PER_PICK)
        blended_tfp_values[pn] = r7_avg_tfp - (steps_beyond_r7 * EXPANSION_TFP_DECAY_PER_PICK)

    # ---- Build output JSON ----
    print(f"\n{'Pick':>4} {'Rd':>2} | {'N':>2} | {'Raw':>6} | {'Reg':>6} | {'Blend':>6} | {'Blend TFP':>9} | Tier")
    print("-" * 78)

    pick_values = {}
    for pn in range(1, TOTAL_PICKS + 1):
        rd = pick_to_round(pn)
        is_expansion = pn > HISTORICAL_PICKS

        reg_fppg = fppg_intercept + fppg_slope * pn
        reg_tfp = tfp_intercept + tfp_slope * pn

        raw_fppgs = pick_raw_fppgs.get(pn, [])
        raw_tfps = pick_raw_totalfps.get(pn, [])
        n = len(raw_fppgs)
        raw_fppg_mean = statistics.mean(raw_fppgs) if raw_fppgs else 0
        raw_tfp_mean = statistics.mean(raw_tfps) if raw_tfps else 0

        fppg_mid = round(blended_fppg_values[pn], 1)
        tfp_mid = round(blended_tfp_values[pn], 1)

        # Low/high: raw min/max for data-backed picks, RSE-based for expansion
        if not is_expansion and raw_fppgs:
            fppg_low = round(min(raw_fppgs), 1)
            fppg_high = round(max(raw_fppgs), 1)
            tfp_low = round(min(raw_tfps), 1)
            tfp_high = round(max(raw_tfps), 1)
        else:
            fppg_low = round(fppg_mid - fppg_rse, 1)
            fppg_high = round(fppg_mid + fppg_rse, 1)
            tfp_low = round(tfp_mid - tfp_rse, 1)
            tfp_high = round(tfp_mid + tfp_rse, 1)

        tier = get_tier(fppg_mid)
        tier_info = TIER_DESCRIPTIONS[tier]

        ext_tag = " *" if is_expansion else ""
        print(f"  P{pn:>2} R{rd} | {n:>2} | {raw_fppg_mean:>6.1f} | {reg_fppg:>6.1f} | {fppg_mid:>6.1f} | {tfp_mid:>9.0f} | {tier}{ext_tag}")

        pick_values[str(pn)] = {
            "pick_number": pn,
            "round": rd,
            "tier": tier,
            "expected_projFPPG": {
                "low": fppg_low,
                "mid": fppg_mid,
                "high": fppg_high,
            },
            "expected_total_fp": {
                "low": tfp_low,
                "mid": tfp_mid,
                "high": tfp_high,
            },
            "historical_stats": {
                "sample_size": n,
                "raw_mean_fppg": round(raw_fppg_mean, 2),
                "raw_median_fppg": round(statistics.median(raw_fppgs), 2) if raw_fppgs else 0,
                "raw_mean_total_fp": round(raw_tfp_mean, 2),
                "raw_median_total_fp": round(statistics.median(raw_tfps), 2) if raw_tfps else 0,
                "regression_fppg": round(reg_fppg, 2),
                "regression_total_fp": round(reg_tfp, 2),
            },
            "description": tier_info["description"],
            "trade_value_notes": (
                f"{tier_info['trade_notes']} "
                f"Pick {pn} (R{rd}) ~ {fppg_mid} FPPG / ~{tfp_mid:,.0f} Total FP."
            ),
        }

        if is_expansion:
            pick_values[str(pn)]["_note"] = (
                "Expansion round pick. Expected value derived from R7 average with "
                f"cliff decay ({EXPANSION_FPPG_DECAY_PER_PICK} FPPG/pick). "
                "Will become data-driven as more keeper-era drafts with 9 rounds accrue."
            )

    # ---- Round-level summary ----
    round_summary = {}
    for rd in range(1, TOTAL_DRAFT_ROUNDS + 1):
        rd_picks = [pn for pn in range(1, TOTAL_PICKS + 1) if pick_to_round(pn) == rd]
        fppg_mids = [float(pick_values[str(pn)]["expected_projFPPG"]["mid"]) for pn in rd_picks]
        tfp_mids = [float(pick_values[str(pn)]["expected_total_fp"]["mid"]) for pn in rd_picks]
        round_summary[str(rd)] = {
            "round": rd,
            "picks": rd_picks,
            "avg_fppg": round(statistics.mean(fppg_mids), 2),
            "avg_total_fp": round(statistics.mean(tfp_mids), 1),
            "fppg_range": f"{min(fppg_mids):.1f} - {max(fppg_mids):.1f}",
            "tier": get_tier(statistics.mean(fppg_mids)),
        }

    output = {
        "_description": (
            "Draft pick valuation guide for trade grading. Maps each individual pick "
            "number (1-36) to expected player value (projFPPG and Total FP) and role tier. "
            "Picks 1-28 use a 70/30 blend of raw historical average and regression line. "
            "Picks 29-36 (expansion rounds R8-R9) use cliff decay from the R7 average."
        ),
        "_methodology": (
            f"Built from {len(fppg_x)} qualifying data points across "
            f"{len(keeper_era_seasons)} keeper-era seasons "
            f"({keeper_era_seasons[0]} through {keeper_era_seasons[-1]}). "
            f"Pre-keeper drafts (2017-18 through 2020-21) are excluded because the full "
            f"player pool was available, making those picks incomparable to keeper-era "
            f"drafts where keepers are held off the board. "
            f"Picks 1-28: expected = {RAW_WEIGHT:.0%} raw mean + {REG_WEIGHT:.0%} regression. "
            f"Picks 29-36: anchor at R7 blended average ({r7_avg_fppg:.1f} FPPG) then decay "
            f"{EXPANSION_FPPG_DECAY_PER_PICK} FPPG per pick. R8-R9 raw data (2025-26 only) "
            f"is excluded from blending because mid-season IL+ to BN conversion filled those "
            f"slots with established stars, not true draft-caliber players."
        ),
        "_data_source": "data/historical/DRAFT_PERFORMANCE.json (built by extract_draft_fppg.py)",
        "_regenerate": "Run: python scripts/build_draft_pick_values.py",
        "_last_updated_seasons": keeper_era_seasons,
        "_excluded_seasons": [s for s in all_seasons if s < KEEPER_ERA_START],
        "_blend_config": {
            "raw_weight": RAW_WEIGHT,
            "regression_weight": REG_WEIGHT,
            "max_deviation_from_regression": MAX_DEVIATION_FROM_REGRESSION,
            "applies_to": "picks 1-28 (R1-R7)",
            "note": (
                "50/50 blend of raw mean and regression to smooth small-sample variance. "
                "Additionally capped at \u00b11.5 FPPG from regression to prevent outlier picks "
                "from having unrealistic expectations."
            ),
        },
        "_expansion_config": {
            "applies_to": "picks 29-36 (R8-R9)",
            "r7_anchor_fppg": round(r7_avg_fppg, 2),
            "r7_anchor_total_fp": round(r7_avg_tfp, 1),
            "fppg_decay_per_pick": EXPANSION_FPPG_DECAY_PER_PICK,
            "total_fp_decay_per_pick": EXPANSION_TFP_DECAY_PER_PICK,
            "note": (
                "R8-R9 use cliff decay instead of regression extrapolation because "
                "the R1-R7 regression is too flat (pool quality drops sharply after R7). "
                "2025-26 R8-R9 raw data is contaminated by mid-season roster expansion. "
                "Decay values will be replaced by actual data once multiple 9-round "
                "drafts have occurred."
            ),
        },
        "_regression_model": {
            "fppg": {
                "formula": f"FPPG = {fppg_intercept:.2f} + ({fppg_slope:.4f} * pick_number)",
                "intercept": round(fppg_intercept, 4),
                "slope": round(fppg_slope, 4),
                "residual_std_error": round(fppg_rse, 2),
                "data_points": len(fppg_x),
            },
            "total_fp": {
                "formula": f"TotalFP = {tfp_intercept:.1f} + ({tfp_slope:.2f} * pick_number)",
                "intercept": round(tfp_intercept, 2),
                "slope": round(tfp_slope, 2),
                "residual_std_error": round(tfp_rse, 1),
                "data_points": len(tfp_x),
            },
            "fit_range": "picks 1-28 (R1-R7 keeper era only)",
        },
        "_league_context": {
            "league_size": TEAMS,
            "keepers_per_team": LEAGUE_STRUCTURE.get("keepers_per_team", 6),
            "total_keepers": TEAMS * LEAGUE_STRUCTURE.get("keepers_per_team", 6),
            "draft_rounds": TOTAL_DRAFT_ROUNDS,
            "picks_per_round": TEAMS,
            "total_draft_picks": TOTAL_PICKS,
            "roster_size": LEAGUE_STRUCTURE.get("roster_size", 17),
            "roster_composition": "10 starters + 5 BN + 2 IL",
            "notes": (
                "Roster expanded from 7 to 9 draft rounds mid-2025-26 season when "
                "2 IL+ slots were converted to BN slots. Picks 29-36 are the R8-R9 "
                "picks; picks 37+ are keeper slots, not true draft picks."
            ),
        },
        "pick_values": pick_values,
        "round_summary": round_summary,
        "trade_grading_guide": {
            "how_to_use": (
                "When grading a trade involving draft picks, look up the specific pick "
                "number (not just the round) to get the expected value. Sum the expected "
                "mid-point projFPPG for each side (players + pick values). Compare totals "
                "and factor in team context. A perfectly even trade on paper may still "
                "deserve asymmetric grades if one side's context makes the move smarter."
            ),
            "key_principle": (
                "A single high-value pick is generally worth more than multiple "
                "low-value picks, because keeper leagues reward elite assets over "
                "roster filler. Two late-round picks will likely both be dropped by "
                "midseason, while an early-round pick could become a keeper for years."
            ),
            "contextual_factors": [
                "Team record and playoff positioning (contender vs rebuilding)",
                "Current season championship odds",
                "Roster holes the acquired player fills",
                "Injury situations affecting available roster spots",
                "Keeper implications (does the acquired player have long-term value?)",
                "Draft pick year (current year picks worth slightly less since draft "
                "already set rosters; future year picks carry uncertainty premium)",
            ],
        },
    }

    if args.dry_run:
        print(f"\n[DRY RUN] Would save to {OUTPUT_FILE}")
        print(json.dumps(output, indent=2)[:500] + "...")
    else:
        OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            json.dump(output, f, indent=2)
        print(f"\nSaved to {OUTPUT_FILE}")
        print(f"File size: {OUTPUT_FILE.stat().st_size / 1024:.1f} KB")


if __name__ == "__main__":
    main()
