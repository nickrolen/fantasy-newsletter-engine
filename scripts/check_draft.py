"""
Prose-layer claim check (Step 7.5). Run on the assembled draft before
Step 8 and before the HTML generator:

    python scripts/check_draft.py --week N
    python scripts/check_draft.py --draft assets/WEEKN_DRAFT.md --week N

Every number must trace to stats_report_weekN (json or md), last week's
report, or an approved lore entry; every superlative to a ranking in the
sources; every claim about history ("again", "always", "first time
since") to a lore tag <!--lore:id--> or a supported number.

Writes output/claim_check_weekN.md. Exit 0 = clean, 1 = findings,
2 = could not run (missing report).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from modules import claim_check as cc  # noqa: E402

LORE_FILE = "config/LEAGUE_LORE.json"
KIND_ORDER = ["unsupported_number", "unsupported_superlative",
              "unsourced_history", "fact_as_tendency", "approximate_number",
              "bad_lore_ref", "money_without_event", "report_card_order"]
KIND_LABEL = {
    "unsupported_number": "Numbers with no source",
    "unsupported_superlative": "Rankings with no source",
    "unsourced_history": "History claims with no lore tag",
    "bad_lore_ref": "Lore tags that don't resolve",
    "fact_as_tendency": "Lore facts told as character (say it as history)",
    "approximate_number": "Approximate numbers (template rule 2: give it)",
    "money_without_event": "Dollar figures in a week nothing was decided",
    "report_card_order": "Report cards out of overall_score order",
}


def load_lore(base: Path, refresh: bool = True) -> list:
    """Approved derived entries are recomputed before every check, so the
    numbers they make sayable are today's. If the history can't be read,
    the stored values are used and the check says so."""
    p = base / LORE_FILE
    if not p.exists():
        return []
    if refresh:
        try:
            import propose_lore
            from modules import lore as L
            lore = L.load(base)
            cells, _ = propose_lore.build_cells(base)
            changed = L.refresh(lore, cells)
            L.save(base, lore)
            for i in changed:
                print(f"lore: {i} changed state (stale={next(e['stale'] for e in lore['entries'] if e['id'] == i)})")
        except Exception as err:  # noqa: BLE001
            print(f"lore: refresh failed ({err}); using stored values")
    return json.loads(p.read_text(encoding="utf-8")).get("entries", [])


def run(draft_text: str, week: int, out_dirs: list[Path], config: dict,
        lore_entries: list, roster_players=(), bases=(),
        include_recap: bool = True, money_events=None) -> tuple[list, dict]:
    """money_events: this week's (angles_weekN.json); None skips the money
    rule -- main() always passes it, and refuses to run without it."""
    pool, vocab, lore, meta = prepare(week, out_dirs, config, lore_entries,
                                      roster_players, bases, include_recap)
    findings = cc.check(draft_text, pool, vocab, lore)
    cards = (meta.get("current_report") or {}).get("report_cards")
    if cards:
        findings += cc.report_card_findings(draft_text, cards)
    if money_events is not None:
        findings += cc.money_findings(draft_text, vocab, money_events)
        # VOICE.md: the decomposition ships as "912 -> 1498", never as a
        # "Banked:" label. Same check the live-line page's tests run.
        findings += cc.score_label_findings(draft_text, vocab)
    return findings, meta


def load_money_events(week: int, out_dirs: list[Path]) -> list:
    """What decided money this week, from the ANGLES file the stats report
    wrote. Missing is an error, not "nothing decided": the two would read
    the same and only one of them is true."""
    for d in out_dirs:
        f = d / f"angles_week{week}.json"
        if f.exists():
            sel = json.loads(f.read_text(encoding="utf-8"))
            if "money_events" not in sel:
                raise FileNotFoundError(
                    f"{f} has no money_events (written before 10-15): "
                    f"re-run format_stats_report.py --week {week}")
            return sel["money_events"]
    raise FileNotFoundError(
        f"angles_week{week}.json not found in {[str(d) for d in out_dirs]}: "
        f"the money rule needs this week's decided events")


def historical_team_names(base) -> dict:
    """{team name: manager} for every season in RECORDS.team_name_history."""
    path = Path(base) / "config" / "RECORDS.json"
    if not path.is_file():
        return {}
    history = json.loads(path.read_text(encoding="utf-8")).get(
        "team_name_history", {})
    out = {}
    for teams in history.values():
        for entry in (teams or {}).values():
            if entry.get("team_name") and entry.get("manager"):
                out[entry["team_name"]] = entry["manager"]
    return out


def prepare(week: int, out_dirs: list[Path], config: dict,
            lore_entries: list, roster_players=(), bases=(),
            include_recap: bool = True):
    """Sources: stats report N and N-1 (json + md), looking-ahead files,
    the week's trade context, INJURY_OVERRIDES, last week's published
    draft (what was said last week is a fact about last week), and
    LAST_WEEK_RECAP -- the files the drafting chat was given."""
    bases = [Path(b) for b in bases]
    reports, mds, players = [], [], set(roster_players)
    found_current = False
    for w in (week, week - 1):
        for d in out_dirs:
            j = d / f"stats_report_week{w}.json"
            m = d / f"stats_report_week{w}.md"
            if j.exists():
                obj = json.loads(j.read_text(encoding="utf-8"))
                reports.append((j.name, obj))
                players |= cc.players_in(obj)
                if w == week:
                    found_current = True
                    current = obj
            if m.exists():
                mds.append((m.name, m.read_text(encoding="utf-8")))
            if j.exists() or m.exists():
                break
    extra = [f"looking_ahead_week{week}.json",
             f"looking_ahead_week{week + 1}.json",
             f"weeklycontextinput_week{week}.json"]
    for d in out_dirs + [base / "data" for base in bases]:
        for name in extra:
            if (d / name).exists():
                reports.append((name, json.loads((d / name).read_text(
                    encoding="utf-8"))))
    for base in bases:
        inj = base / "config" / "INJURY_OVERRIDES.json"
        if inj.exists():
            obj = json.loads(inj.read_text(encoding="utf-8"))
            reports.append((inj.name, obj))
            players |= cc.players_in(obj)
        prev = base / "assets" / f"WEEK{week - 1}_DRAFT.md"
        if prev.exists():
            mds.append((prev.name, prev.read_text(encoding="utf-8")))
        recap = base / "config" / "LAST_WEEK_RECAP.md"
        if recap.exists() and include_recap:
            mds.append((recap.name, recap.read_text(encoding="utf-8")))
    if not found_current:
        raise FileNotFoundError(f"stats_report_week{week}.json not found in "
                                f"{[str(d) for d in out_dirs]}")
    aliases = dict(config.get("manager_aliases") or {})
    # Every name a manager's team has carried, not just this season's. Benton
    # was "Smaxey" through 2025-26 and is "Kevin Quran't" from 2026-27; a
    # draft about an archived week (the dry run, any recap) uses the old
    # name, and a team name is how a table row is anchored to its manager.
    aliases.update(historical_team_names(base))
    for e in lore_entries:
        if e.get("kind") == "alias" and e.get("status") == "approved":
            aliases[e["alias"]] = e["name"]
            players.add(e["name"])
    vocab = cc.Vocabulary(config["managers"], config.get("manager_to_team"),
                          aliases, sorted(players))
    pool = cc.build_pool(vocab, reports, mds, lore_entries)
    lore = {e.get("id"): e for e in lore_entries}
    return pool, vocab, lore, {
        "sources": [n for n, _ in reports] + [n for n, _ in mds],
        "records": len(pool.records), "current_report": current}


def render(findings: list, week: int, meta: dict) -> str:
    unknown = {f.kind for f in findings} - set(KIND_ORDER)
    if unknown:
        # render() lists findings by KIND_ORDER: an unlisted kind would be
        # counted in the total and printed nowhere.
        raise ValueError(f"finding kind(s) {sorted(unknown)} missing from KIND_ORDER")
    c = Counter(f.kind for f in findings)
    lines = [f"# Claim check -- week {week}", "",
             f"Sources: {', '.join(meta['sources'])}; lore entries: "
             f"{meta.get('lore', 0)} approved.", ""]
    for name in meta.get("drift", []):
        lines += [f"**Warning:** output/{name} changed after this week's "
                  "point-in-time capture (a re-run?). Checked against the "
                  "live file.", ""]
    if not findings:
        lines.append("**Clean.** Every number, ranking and history claim "
                      "traces to a source.")
        return "\n".join(lines) + "\n"
    lines.append(f"**{len(findings)} finding(s).** Fix each, or give it a "
                 "source: a lore entry for knowledge the numbers can't "
                 "prove. Step 8 still runs after this.")
    for k in KIND_ORDER:
        fs = [f for f in findings if f.kind == k]
        if not fs:
            continue
        lines += ["", f"## {KIND_LABEL[k]} ({len(fs)})", ""]
        for f in fs:
            lines.append(f"- S{f.section} L{f.line} `{f.token}` -- "
                         f"{f.sentence}")
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--week", type=int, required=True)
    ap.add_argument("--draft")
    ap.add_argument("--reports-dir", action="append")
    ap.add_argument("--from-capture", action="store_true",
                    help="check against the stats reports saved in the "
                         "point-in-time captures, not output/")
    ap.add_argument("--base", default=str(ROOT))
    args = ap.parse_args(argv)
    base = Path(args.base)
    draft = Path(args.draft) if args.draft else (
        base / "assets" / f"WEEK{args.week}_DRAFT.md")
    dirs = [Path(d) for d in (args.reports_dir or [])] or [base / "output"]
    from modules.point_in_time import (capture_dir, output_drift,
                                       OUTPUTS_SUBDIR)
    if args.from_capture:
        dirs = [capture_dir(base, w) / OUTPUTS_SUBDIR
                for w in (args.week, args.week - 1)]
    config = json.loads((base / "config" / "league_config.json")
                        .read_text(encoding="utf-8"))
    lore = load_lore(base)
    try:
        money = load_money_events(args.week, dirs)
        findings, meta = run(draft.read_text(encoding="utf-8"), args.week,
                             dirs, config, lore, bases=[base],
                             money_events=money)
    except FileNotFoundError as e:
        print(f"claim check could not run: {e}")
        return 2
    meta["lore"] = sum(1 for e in lore if e.get("status") == "approved")
    meta["drift"] = [] if args.from_capture else output_drift(base, args.week)
    for name in meta["drift"]:
        print(f"WARNING: output/{name} changed after this week's capture; "
              "checked against the live file")
    # Record which lore entries this draft actually used, so next week's
    # export can prefer ones that have not run lately. The tags are the only
    # record of what the drafting chat reached for; without this, every
    # approved entry looks equally fresh in all 23 issues (Nick, 10-14).
    # Season comes from the base's own config, not a module constant, so a
    # replay records against the season it is replaying.
    try:
        from modules.claim_check import LORE_TAG
        from modules import lore_usage
        season = (config.get("season") or {}).get("current")
        if season:
            lore_usage.record(base, season, args.week,
                              LORE_TAG.findall(draft.read_text(encoding="utf-8")))
    except Exception as e:  # never let bookkeeping fail the check
        print(f"  WARNING: lore usage not recorded: {type(e).__name__}: {e}")

    text = render(findings, args.week, meta)
    out = base / "output" / f"claim_check_week{args.week}.md"
    out.parent.mkdir(exist_ok=True)
    out.write_text(text, encoding="utf-8")
    c = Counter(f.kind for f in findings)
    print(f"claim check week {args.week}: {len(findings)} finding(s) "
          + ", ".join(f"{k}={v}" for k, v in c.items()) + f" -> {out}")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
