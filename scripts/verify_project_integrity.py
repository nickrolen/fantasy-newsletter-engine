#!/usr/bin/env python3
"""
verify_project_integrity.py -- Comprehensive project health check.

Run this AFTER any batch of file edits (especially automated/Cowork edits) to
catch silent file truncation, syntax breakage, broken imports, config drift,
encoding corruption, and engine-output regressions.

USAGE:
    py scripts/verify_project_integrity.py                  # all checks except golden master
    py scripts/verify_project_integrity.py --baseline       # update file-size baseline after success
    py scripts/verify_project_integrity.py --compare-golden # also run golden master check
    py scripts/verify_project_integrity.py --verbose        # show every file checked

EXIT CODES:
    0 = success (warnings are OK)
    1 = at least one FAILURE
"""

import argparse
import ast
import importlib
import json
import os
import sys
import traceback
from pathlib import Path


# ----------------------------------------------------------------------------
# Project layout
# ----------------------------------------------------------------------------

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
MODULES_DIR = PROJECT_ROOT / "modules"
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
CONFIG_DIR = PROJECT_ROOT / "config"
OUTPUT_DIR = PROJECT_ROOT / "output"
BASELINE_FILE = CONFIG_DIR / ".file_baselines.json"
GOLDEN_REPORT = OUTPUT_DIR / "stats_report_week22.json"
LEAGUE_CONFIG = CONFIG_DIR / "league_config.json"

# Required top-level keys in league_config.json
REQUIRED_CONFIG_KEYS = [
    "managers",
    "manager_to_team",
    "yahoo",
    "league_structure",
    "season",
    "tiebreaker_rules",
]

# Dirs to skip when scanning
SKIP_DIRS = {"__pycache__", ".git", "node_modules", "venv", ".venv", "archive"}

# Extensions tracked for baseline + size diffs
BASELINE_EXTENSIONS = {".py", ".json", ".md"}

# Shrink threshold (fraction). 0.20 means flag if file dropped by >20%.
SHRINK_THRESHOLD = 0.20

# Threshold for "suspiciously small" Python files (bytes)
SMALL_PY_BYTES = 100


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------

def _walk_files(root, extensions=None):
    """Yield Path objects for files under root, skipping junk dirs."""
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS
                       and not d.startswith(".")]
        for fname in filenames:
            p = Path(dirpath) / fname
            if extensions is None or p.suffix.lower() in extensions:
                yield p


def _rel(p):
    """Return path relative to project root using forward slashes."""
    try:
        return str(Path(p).resolve().relative_to(PROJECT_ROOT)).replace("\\", "/")
    except ValueError:
        return str(p).replace("\\", "/")


def _fmt_line(label, status, max_label=32):
    """Format a status line like '[1/6] Python Syntax .............. 45/45 OK'."""
    dots = "." * max(3, max_label - len(label))
    return f"{label} {dots} {status}"


# ----------------------------------------------------------------------------
# Check 1: Python Syntax
# ----------------------------------------------------------------------------

def check_python_syntax(verbose=False):
    """Parse every .py file in modules/ and scripts/ with ast.parse()."""
    failures = []
    warnings = []
    checked = 0
    targets = []

    for base in (MODULES_DIR, SCRIPTS_DIR):
        if base.is_dir():
            targets.extend(_walk_files(base, {".py"}))

    for fpath in targets:
        checked += 1
        rel = _rel(fpath)
        try:
            size = fpath.stat().st_size
        except OSError as e:
            failures.append(f"[SYNTAX] {rel}: cannot stat: {e}")
            continue

        if size < SMALL_PY_BYTES and fpath.name != "__init__.py":
            warnings.append(
                f"[SIZE] {rel}: {size} bytes (suspiciously small)"
            )

        try:
            with open(fpath, "r", encoding="utf-8") as f:
                source = f.read()
            ast.parse(source, filename=str(fpath))
            if verbose:
                print(f"    OK  {rel} ({size:,} bytes)")
        except SyntaxError as e:
            failures.append(
                f"[SYNTAX] {rel}: line {e.lineno}: {e.msg}"
            )
        except Exception as e:
            failures.append(f"[SYNTAX] {rel}: {type(e).__name__}: {e}")

    passed = checked - len([f for f in failures if f.startswith("[SYNTAX]")])
    status = f"{passed}/{checked} OK"
    if failures:
        status = f"{passed}/{checked} ({len(failures)} FAIL)"
    return {
        "label": "[1/6] Python Syntax",
        "status": status,
        "failures": failures,
        "warnings": warnings,
        "checked": checked,
    }


# ----------------------------------------------------------------------------
# Check 2: File Size Baseline
# ----------------------------------------------------------------------------

def load_baseline():
    """Load baseline file, or return None if it doesn't exist."""
    if not BASELINE_FILE.is_file():
        return None
    try:
        with open(BASELINE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        print(f"  WARNING: could not load baseline ({e}); treating as missing.")
        return None


def collect_current_sizes():
    """Collect {rel_path: size} for all baseline-eligible files."""
    sizes = {}
    for fpath in _walk_files(PROJECT_ROOT, BASELINE_EXTENSIONS):
        # Skip the baseline file itself
        if fpath.resolve() == BASELINE_FILE.resolve():
            continue
        try:
            sizes[_rel(fpath)] = fpath.stat().st_size
        except OSError:
            continue
    return sizes


def check_file_baselines(verbose=False):
    """Compare current file sizes against baseline."""
    failures = []
    warnings = []
    info = []

    baseline = load_baseline()
    current = collect_current_sizes()

    if baseline is None:
        return {
            "label": "[2/6] File Size Baseline",
            "status": "NO BASELINE (run with --baseline to create)",
            "failures": [],
            "warnings": [],
            "info": [f"{len(current)} files tracked in current scan."],
            "current_sizes": current,
        }

    baseline_sizes = baseline.get("sizes", {})
    checked = 0
    new_files = []
    shrunk = []
    disappeared = []

    for rel, old_size in baseline_sizes.items():
        checked += 1
        new_size = current.get(rel)
        if new_size is None:
            disappeared.append(rel)
            failures.append(f"[SIZE] {rel}: DISAPPEARED since baseline")
            continue
        if old_size <= 0:
            continue
        delta = new_size - old_size
        pct = delta / old_size
        if pct <= -SHRINK_THRESHOLD:
            warnings.append(
                f"[SIZE] {rel}: {old_size:,} -> {new_size:,} bytes "
                f"({pct * 100:+.1f}%) *** POSSIBLE TRUNCATION ***"
            )
            shrunk.append(rel)
        elif verbose:
            print(f"    OK  {rel}: {old_size:,} -> {new_size:,} ({pct*100:+.1f}%)")

    for rel in current:
        if rel not in baseline_sizes:
            new_files.append(rel)

    if new_files:
        info.append(f"{len(new_files)} new file(s) not in baseline (OK).")
        if verbose:
            for n in new_files:
                info.append(f"  NEW: {n}")

    status_bits = [f"{checked - len(shrunk) - len(disappeared)}/{checked} OK"]
    if warnings:
        status_bits.append(f"{len(warnings)} warning(s)")
    if failures:
        status_bits.append(f"{len(failures)} FAIL")
    return {
        "label": "[2/6] File Size Baseline",
        "status": ", ".join(status_bits),
        "failures": failures,
        "warnings": warnings,
        "info": info,
        "current_sizes": current,
    }


def write_baseline(current_sizes):
    """Write baseline file with current sizes."""
    BASELINE_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": 1,
        "description": (
            "Recorded file sizes for verify_project_integrity.py. "
            "Files that shrink by more than 20% trigger a truncation warning."
        ),
        "sizes": current_sizes,
    }
    with open(BASELINE_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, sort_keys=True)


# ----------------------------------------------------------------------------
# Check 3: Import Chain
# ----------------------------------------------------------------------------

def check_import_chain(verbose=False):
    """Verify every module in modules/ can be imported."""
    failures = []
    warnings = []
    checked = 0
    passed = 0

    if not MODULES_DIR.is_dir():
        return {
            "label": "[3/6] Import Chain",
            "status": "SKIPPED (no modules/ dir)",
            "failures": [],
            "warnings": [],
        }

    # Make project root importable
    root_str = str(PROJECT_ROOT)
    if root_str not in sys.path:
        sys.path.insert(0, root_str)

    module_files = sorted(
        p for p in MODULES_DIR.glob("*.py")
        if p.name != "__init__.py"
    )

    for mod_path in module_files:
        checked += 1
        name = mod_path.stem
        full_name = f"modules.{name}"
        try:
            # Force a fresh import so we catch breakage in already-loaded modules
            if full_name in sys.modules:
                importlib.reload(sys.modules[full_name])
            else:
                importlib.import_module(full_name)
            passed += 1
            if verbose:
                print(f"    OK  {full_name}")
        except Exception as e:
            tb_lines = traceback.format_exception_only(type(e), e)
            err = tb_lines[-1].strip() if tb_lines else str(e)
            failures.append(f"[IMPORT] {full_name}: {err}")

    status = f"{passed}/{checked} OK"
    if failures:
        status = f"{passed}/{checked} ({len(failures)} FAIL)"
    return {
        "label": "[3/6] Import Chain",
        "status": status,
        "failures": failures,
        "warnings": warnings,
    }


# ----------------------------------------------------------------------------
# Check 4: Config Integrity
# ----------------------------------------------------------------------------

def check_config_integrity(verbose=False):
    """Verify league_config.json structural invariants."""
    failures = []
    warnings = []

    if not LEAGUE_CONFIG.is_file():
        return {
            "label": "[4/6] Config Integrity",
            "status": "FAIL (config missing)",
            "failures": [f"[CONFIG] {_rel(LEAGUE_CONFIG)}: file does not exist"],
            "warnings": [],
        }

    try:
        with open(LEAGUE_CONFIG, "r", encoding="utf-8") as f:
            cfg = json.load(f)
    except json.JSONDecodeError as e:
        return {
            "label": "[4/6] Config Integrity",
            "status": "FAIL (invalid JSON)",
            "failures": [f"[CONFIG] league_config.json: JSON error: {e}"],
            "warnings": [],
        }
    except OSError as e:
        return {
            "label": "[4/6] Config Integrity",
            "status": "FAIL (read error)",
            "failures": [f"[CONFIG] league_config.json: read error: {e}"],
            "warnings": [],
        }

    # Top-level keys
    for key in REQUIRED_CONFIG_KEYS:
        if key not in cfg:
            failures.append(f"[CONFIG] missing required top-level key: '{key}'")

    if failures:
        return {
            "label": "[4/6] Config Integrity",
            "status": f"FAIL ({len(failures)} issue(s))",
            "failures": failures,
            "warnings": warnings,
        }

    managers = cfg.get("managers", [])
    manager_to_team = cfg.get("manager_to_team", {})
    manager_colors = cfg.get("manager_colors", {})
    manager_aliases = cfg.get("manager_aliases", {})
    num_teams = cfg.get("league_structure", {}).get("num_teams")

    if num_teams is not None and len(managers) != num_teams:
        failures.append(
            f"[CONFIG] len(managers)={len(managers)} != "
            f"league_structure.num_teams={num_teams}"
        )

    if len(manager_to_team) != len(managers):
        failures.append(
            f"[CONFIG] len(manager_to_team)={len(manager_to_team)} != "
            f"len(managers)={len(managers)}"
        )

    # alias values should be canonical manager names
    alias_targets = set(manager_aliases.values())

    for mgr in managers:
        if mgr not in manager_to_team:
            failures.append(f"[CONFIG] manager '{mgr}' missing from manager_to_team")
        if mgr not in manager_colors:
            failures.append(f"[CONFIG] manager '{mgr}' missing from manager_colors")
        if mgr not in alias_targets:
            failures.append(
                f"[CONFIG] manager '{mgr}' not referenced as alias target in manager_aliases"
            )

    if failures:
        status = f"FAIL ({len(failures)} issue(s))"
    else:
        status = "ALL CHECKS PASSED"
    return {
        "label": "[4/6] Config Integrity",
        "status": status,
        "failures": failures,
        "warnings": warnings,
    }


# ----------------------------------------------------------------------------
# Check 5: ASCII Compliance
# ----------------------------------------------------------------------------

def check_ascii_compliance(verbose=False):
    """Scan every .py file for non-ASCII characters."""
    failures = []
    warnings = []
    checked = 0
    clean = 0

    targets = []
    for base in (MODULES_DIR, SCRIPTS_DIR):
        if base.is_dir():
            targets.extend(_walk_files(base, {".py"}))

    for fpath in targets:
        checked += 1
        rel = _rel(fpath)
        try:
            with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
        except Exception as e:
            failures.append(f"[ASCII] {rel}: read error: {e}")
            continue

        non_ascii_lines = []
        for i, line in enumerate(content.split("\n"), 1):
            for ch in line:
                if ord(ch) > 127:
                    non_ascii_lines.append((i, ch))
                    break  # one report per line is enough

        if non_ascii_lines:
            first_line, first_ch = non_ascii_lines[0]
            warnings.append(
                f"[ASCII] {rel}: {len(non_ascii_lines)} non-ASCII char(s) "
                f"(first at line {first_line}, U+{ord(first_ch):04X})"
            )
        else:
            clean += 1
            if verbose:
                print(f"    OK  {rel}")

    status = f"{clean}/{checked} OK"
    if warnings:
        status += f" ({len(warnings)} pre-existing)"
    return {
        "label": "[5/6] ASCII Compliance",
        "status": status,
        "failures": failures,
        "warnings": warnings,
    }


# ----------------------------------------------------------------------------
# Check 6: Golden Master Comparison
# ----------------------------------------------------------------------------

def check_golden_master(verbose=False):
    """Lightweight sanity check on output/stats_report_week22.json vs config."""
    failures = []
    warnings = []

    if not GOLDEN_REPORT.is_file():
        return {
            "label": "[6/6] Golden Master",
            "status": "SKIPPED (no stats_report_week22.json)",
            "failures": [],
            "warnings": [],
        }
    if not LEAGUE_CONFIG.is_file():
        return {
            "label": "[6/6] Golden Master",
            "status": "SKIPPED (no league_config.json)",
            "failures": [],
            "warnings": [],
        }

    try:
        with open(GOLDEN_REPORT, "r", encoding="utf-8") as f:
            report = json.load(f)
        with open(LEAGUE_CONFIG, "r", encoding="utf-8") as f:
            cfg = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        return {
            "label": "[6/6] Golden Master",
            "status": "FAIL (load error)",
            "failures": [f"[GOLDEN] load error: {e}"],
            "warnings": [],
        }

    cfg_managers = set(cfg.get("managers", []))

    # playoff_odds.seeds covers all configured managers
    seeds = report.get("playoff_odds", {}).get("seeds", {})
    seed_managers = set(seeds.keys())
    if seed_managers != cfg_managers:
        missing = cfg_managers - seed_managers
        extra = seed_managers - cfg_managers
        if missing:
            failures.append(
                f"[GOLDEN] playoff_odds.seeds missing managers: {sorted(missing)}"
            )
        if extra:
            failures.append(
                f"[GOLDEN] playoff_odds.seeds has unknown managers: {sorted(extra)}"
            )

    # Report cards: every configured manager appears, and has a grade
    cards = report.get("report_cards", [])
    if not isinstance(cards, list) or not cards:
        failures.append("[GOLDEN] report_cards is missing or empty")
    else:
        seen_managers = set()
        for card in cards:
            mgr = card.get("manager")
            if mgr is None:
                failures.append("[GOLDEN] report_cards entry missing 'manager' field")
                continue
            seen_managers.add(mgr)
            # Accept either 'letter_grade' or 'grade'
            grade = card.get("letter_grade", card.get("grade"))
            if grade is None or grade == "":
                failures.append(
                    f"[GOLDEN] report_cards: manager '{mgr}' has missing/None grade"
                )
        missing = cfg_managers - seen_managers
        extra = seen_managers - cfg_managers
        if missing:
            failures.append(
                f"[GOLDEN] report_cards missing managers: {sorted(missing)}"
            )
        if extra:
            failures.append(
                f"[GOLDEN] report_cards has unknown managers: {sorted(extra)}"
            )

    if failures:
        status = f"FAIL ({len(failures)} issue(s))"
    else:
        status = "ALL CHECKS PASSED"
    return {
        "label": "[6/6] Golden Master",
        "status": status,
        "failures": failures,
        "warnings": warnings,
    }


# ----------------------------------------------------------------------------
# Driver
# ----------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Comprehensive project integrity checker."
    )
    parser.add_argument(
        "--baseline", action="store_true",
        help="Update the file-size baseline after a successful run."
    )
    parser.add_argument(
        "--compare-golden", action="store_true",
        help="Also run the golden master comparison."
    )
    parser.add_argument(
        "--verbose", action="store_true",
        help="Show every file checked, not just issues."
    )
    args = parser.parse_args()

    print("=" * 60)
    print("PROJECT INTEGRITY CHECK")
    print("=" * 60)

    results = []
    results.append(check_python_syntax(args.verbose))
    results.append(check_file_baselines(args.verbose))
    results.append(check_import_chain(args.verbose))
    results.append(check_config_integrity(args.verbose))
    results.append(check_ascii_compliance(args.verbose))
    if args.compare_golden:
        results.append(check_golden_master(args.verbose))
    else:
        results.append({
            "label": "[6/6] Golden Master",
            "status": "SKIPPED (no --compare-golden flag)",
            "failures": [],
            "warnings": [],
        })

    for r in results:
        print(_fmt_line(r["label"], r["status"]))

    all_warnings = []
    all_failures = []
    for r in results:
        all_warnings.extend(r.get("warnings", []))
        all_failures.extend(r.get("failures", []))

    if all_warnings:
        print("\nWARNINGS:")
        for w in all_warnings:
            print(f"  {w}")

    if all_failures:
        print("\nFAILURES:")
        for f in all_failures:
            print(f"  {f}")

    # Extra info lines (new files, etc.)
    for r in results:
        for line in r.get("info", []):
            print(f"  {line}")

    print()
    print(f"RESULT: {len(all_warnings)} WARNING(S), {len(all_failures)} FAILURE(S)")

    # Baseline update happens AFTER all checks, only if no failures
    if args.baseline:
        if all_failures:
            print("\nBaseline NOT updated (failures present). Fix failures and re-run.")
            return 1
        baseline_check = next(
            (r for r in results if r["label"].startswith("[2/6]")), None
        )
        current_sizes = baseline_check.get("current_sizes") if baseline_check else None
        if current_sizes is None:
            current_sizes = collect_current_sizes()
        write_baseline(current_sizes)
        print(f"\nBaseline updated: {_rel(BASELINE_FILE)} "
              f"({len(current_sizes)} files recorded)")

    return 1 if all_failures else 0


if __name__ == "__main__":
    sys.exit(main())
