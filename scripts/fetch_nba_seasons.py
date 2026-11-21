"""
fetch_nba_seasons.py -- every player's NBA seasons from Yahoo, in this league's
eleven stats, into data/historical/NBA_SEASONS.json (4a4 Phase A, 11-20).

    python scripts/fetch_nba_seasons.py                 fetch 2014-15 to 2025-26
    python scripts/fetch_nba_seasons.py --max-calls 200 stop after 200 Yahoo calls
    python scripts/fetch_nba_seasons.py --check         no Yahoo: the summary and coverage
    python scripts/fetch_nba_seasons.py --first 2026-27 --last 2026-27
                                                        the season reset's yearly add (19c)
    python scripts/fetch_nba_seasons.py --refetch 2019-20
    python scripts/fetch_nba_seasons.py --bbref         2014-15 to 2021-22 from basketball-reference's
                                                        season totals (9 pages, 2022-23 as the proof);
                                                        no Yahoo call (Nick, 11-20)
    python scripts/fetch_nba_seasons.py --drafts        every NBA draft 2014 to 2026 from basketball-reference's
                                                        draft pages (13 pages, ~45 s) into
                                                        data/historical/NBA_DRAFTS.json, matched to Yahoo
                                                        ids; no Yahoo call (4a4 s.2.5; modules/nba_drafts.py)
    python scripts/fetch_nba_seasons.py --drafts --draft-last 2027
                                                        the season reset's yearly add (19c): every draft
                                                        2014..2027 is rebuilt; the cached pages cost nothing
    python scripts/fetch_nba_seasons.py --debug-raw 2021-22 2022-23
                                                        save Yahoo's raw responses for one page of
                                                        each (and a few variants of the request),
                                                        scrubbed, to _to_delete/4a4/; ~7 calls a
                                                        season; NBA_SEASONS.json untouched

Resumable: the file is saved after every page; a stopped run (the call cap,
a failed page) picks up where it stopped when run again. Seasons already
complete cost nothing. Prints progress and a final summary; never prints a
credential (errors are redacted). Exit 0: every season asked for is complete;
2: stopped at --max-calls; 1: a season unavailable or a run-stopping failure.
The file and its rules: modules/nba_seasons.py.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from modules import nba_seasons as ns          # noqa: E402


def main(argv=None, *, source=None, log=print, now=None, sleeper=time.sleep, bbref_fetch=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--base-path", default=".")
    ap.add_argument("--first", default=ns.FIRST_SEASON)
    ap.add_argument("--last", default=ns.LAST_SEASON)
    ap.add_argument("--max-calls", type=int, default=None, help="stop after this many Yahoo calls (resumable)")
    ap.add_argument("--sleep", type=float, default=0.3, help="seconds between pages (default 0.3)")
    ap.add_argument("--refetch", nargs="*", default=[], metavar="SEASON",
                    help="drop these seasons from the file and fetch them again")
    ap.add_argument("--top-n", type=int, default=300, help="the summary's top-N line (default 300)")
    ap.add_argument("--check", action="store_true", help="no Yahoo call: print the summary and coverage")
    ap.add_argument("--debug-raw", nargs="+", default=None, metavar="SEASON",
                    help="save Yahoo's raw responses for one page of each season (scrubbed); writes no data")
    ap.add_argument("--out-dir", default=str(Path("_to_delete") / "4a4"),
                    help="where --debug-raw and --bbref save their reports")
    ap.add_argument("--bbref", action="store_true",
                    help="2014-15 to 2021-22 from basketball-reference season totals, proven on 2022-23; no Yahoo")
    ap.add_argument("--drafts", action="store_true",
                    help="every NBA draft (basketball-reference draft pages) into data/historical/NBA_DRAFTS.json; "
                         "no Yahoo (4a4 s.2.5)")
    ap.add_argument("--draft-last", type=int, default=None, metavar="YEAR",
                    help="with --drafts: the last draft to read (default 2026); the file always holds 2014 on")
    a = ap.parse_args(argv)
    if a.max_calls is not None and a.max_calls < 1:
        log("REFUSED: --max-calls must be 1 or more")
        return 1
    t0 = time.monotonic()
    try:
        seasons = ns.seasons_between(a.first, a.last)
        for s in a.refetch:
            if s not in seasons:
                raise ns.SeasonsError(f"--refetch {s} is outside --first {a.first} .. --last {a.last}")
        if a.drafts:
            from modules import nba_drafts as nd
            fy, ly = nd.FIRST_YEAR, (a.draft_last or nd.LAST_YEAR)
            log(f"NBA drafts {fy} to {ly} from basketball-reference's draft pages (cached pages are reused) ...")
            kw = {"now": now} if now else {}
            try:
                r = nd.run(a.base_path, first=fy, last=ly, fetch=bbref_fetch, sleeper=sleeper, log=log, **kw)
            except nd.DraftsError as e:
                log(f"REFUSED: {e}")
                log("The pages fetched before this are cached; NBA_DRAFTS.json was not written.")
                return 1
            log(f"{r['fetched']} page(s) fetched; wrote {nd.RELPATH.as_posix()} in {time.monotonic() - t0:.0f} s")
            for line in nd.summary_lines(r["blob"]):
                log(line)
            return 0
        stats = ns.stat_order(a.base_path)
        if a.debug_raw:
            out_dir = Path(a.out_dir)
            if not out_dir.is_absolute():
                out_dir = Path(a.base_path) / out_dir
            src = source if source is not None else ns.YahooGet(a.base_path)
            lines = ns.debug_raw(a.base_path, src, a.debug_raw, out_dir, log=log)
            log(f"{len(lines)} Yahoo call(s); saved to {out_dir} (raw_*.json, raw_digest.txt)")
            return 0
        if a.bbref:
            from modules import nba_seasons_bbref as nb
            out_dir = Path(a.out_dir)
            if not out_dir.is_absolute():
                out_dir = Path(a.base_path) / out_dir
            log("basketball-reference season totals, 2014-15 to 2021-22 (and 2022-23 as the proof) ...")
            kw = {"now": now} if now else {}
            r = nb.run(a.base_path, fetch=bbref_fetch, out_dir=out_dir, log=log, sleeper=sleeper, **kw)
            log(f"{r['fetched']} page(s) fetched; report: {out_dir / 'bbref_report.json'}")
            blob = r["blob"]
            for line in ns.summary_lines(a.base_path, blob, seconds=time.monotonic() - t0, top_n=a.top_n,
                                         seasons=seasons):
                log(line)
            prov = blob["provenance"]
            return 0 if all((prov.get(s) or {}).get("status") == "complete" for s in seasons) else 1
        if a.check:
            blob = ns.read(a.base_path, stats=stats)
            for line in ns.summary_lines(a.base_path, blob, top_n=a.top_n, seasons=seasons):
                log(line)
            prov = blob["provenance"]
            return 0 if all((prov.get(s) or {}).get("status") == "complete" for s in seasons) else 1
        log(f"Fetching NBA seasons {seasons[-1]} back to {seasons[0]} from Yahoo"
            + (f" (at most {a.max_calls} calls)" if a.max_calls else "") + " ...")
        kw = {"now": now} if now else {}
        res = ns.fetch(a.base_path, source, seasons=seasons, max_calls=a.max_calls, sleep=a.sleep,
                       refetch=a.refetch, log=log, sleeper=sleeper, **kw)
    except ns.SeasonsError as e:
        log(f"REFUSED: {ns.redact(e)}")
        log("The pages fetched before this are saved; nothing else was written.")
        return 1
    except Exception as e:                                     # auth, import: name it, never a credential
        log(f"FAILED: {type(e).__name__}: {ns.redact(e)}")
        return 1
    for line in ns.summary_lines(a.base_path, res["blob"], res, seconds=time.monotonic() - t0,
                                 top_n=a.top_n, seasons=seasons):
        log(line)
    prov = res["blob"]["provenance"]
    if res["stopped"]:
        return 2
    if res["error"] or not all((prov.get(s) or {}).get("status") == "complete" for s in seasons):
        return 1
    if any(not ns.cross_ok((prov.get(s) or {}).get("cross_check"))[0] for s in seasons):
        return 1
    return 0


if __name__ == "__main__":
    try:                                    # a name with an accent (Jokic's) never stops a redirected run on Windows
        sys.stdout.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass
    sys.exit(main())
