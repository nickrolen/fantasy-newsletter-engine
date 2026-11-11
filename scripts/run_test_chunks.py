#!/usr/bin/env python3
"""
run_test_chunks.py -- the full test suite in pieces that each finish inside a
time cap (Nick, 11-10: builders' tool calls stop after 3 minutes, and the
suite takes far longer). Builders run the related tests while working and the
full suite ONCE at the end, with this.

    python scripts/run_test_chunks.py --chunk K --of N --out-dir DIR
        runs test files K, K+N, K+2N, ... (sorted) with pytest -n WORKERS,
        writes DIR/suite_K_of_N.log, prints the failures and the count line.
    python scripts/run_test_chunks.py --summary --of N --out-dir DIR
        adds up every chunk's log: passed, failed, skipped, and each FAILED
        line, and names any chunk with no log or a timed-out log.

A chunk that times out (exit 124) is reported as such; split it with a larger
--of, or run its files by name. DIR should be scratch (_to_delete\\<job>\\):
logs can name players. Needs pytest-xdist for --workers > 1.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
COUNT = re.compile(r"(\d+) (passed|failed|skipped|error|errors)")


def files_for(k: int, n: int) -> list:
    allf = sorted(p.relative_to(ROOT).as_posix() for p in (ROOT / "tests").glob("test_*.py"))
    return [f for i, f in enumerate(allf, start=1) if i % n == k % n]


def run_chunk(k: int, n: int, out: Path, workers: int, timeout: int) -> int:
    k = k % n                    # chunk N is chunk 0 (same files): one log name for both
    files = files_for(k, n)
    if not files:
        print(f"chunk {k} of {n}: no files")
        return 0
    out.mkdir(parents=True, exist_ok=True)
    log = out / f"suite_{k}_of_{n}.log"
    cmd = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-rfs"]
    if workers > 1:
        cmd += ["-n", str(workers)]
    try:
        r = subprocess.run(cmd + files, cwd=ROOT, capture_output=True, text=True, timeout=timeout)
        text, code = r.stdout + r.stderr, r.returncode
    except subprocess.TimeoutExpired as e:
        text = (e.stdout or b"").decode() if isinstance(e.stdout, bytes) else (e.stdout or "")
        text += f"\nTIMED OUT after {timeout}s\n"
        code = 124
    log.write_text(text, encoding="utf-8")
    for line in text.splitlines():
        if line.startswith(("FAILED", "ERROR")) or "TIMED OUT" in line:
            print(line)
    tail = [l for l in text.splitlines() if COUNT.search(l)]
    print(f"chunk {k} of {n} ({len(files)} files): exit {code}; {tail[-1].strip() if tail else 'no count line'}")
    return code


def summary(n: int, out: Path) -> int:
    tot = {"passed": 0, "failed": 0, "skipped": 0, "error": 0}
    bad, missing = [], []
    for k in range(n):
        log = out / f"suite_{k}_of_{n}.log"
        if not log.is_file():
            if files_for(k, n):
                missing.append(k)
            continue
        text = log.read_text(encoding="utf-8")
        if "TIMED OUT" in text:
            missing.append(f"{k} (timed out)")
        lines = [l for l in text.splitlines() if COUNT.search(l)]
        if lines:
            for num, kind in COUNT.findall(lines[-1]):
                tot["error" if kind.startswith("error") else kind] += int(num)
        bad += [l for l in text.splitlines() if l.startswith(("FAILED", "ERROR"))]
    for l in sorted(set(bad)):
        print(l)
    print(f"{tot['passed']} passed, {tot['failed']} failed, {tot['skipped']} skipped, {tot['error']} errors")
    if missing:
        print(f"NOT COMPLETE: chunk(s) {', '.join(map(str, missing))} have no finished log")
        return 1
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--chunk", type=int)
    ap.add_argument("--of", type=int, required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--timeout", type=int, default=170, help="seconds per chunk (default 170)")
    ap.add_argument("--summary", action="store_true")
    a = ap.parse_args(argv)
    out = Path(a.out_dir)
    if not out.is_absolute():
        out = ROOT / out
    if a.summary:
        return summary(a.of, out)
    if a.chunk is None:
        ap.error("--chunk K is required (or --summary)")
    return run_chunk(a.chunk, a.of, out, a.workers, a.timeout)


if __name__ == "__main__":
    sys.exit(main())
