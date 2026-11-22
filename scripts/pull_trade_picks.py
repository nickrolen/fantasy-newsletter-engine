#!/usr/bin/env python3
"""
pull_trade_picks.py -- the draft picks in every trade, from Yahoo's own
records (H56 Part 2; claude/HANDOFF_56_DRAFT_ORDER_PUNT_2026-11-20.md s.4.1).

    python scripts/pull_trade_picks.py fetch [--out DIR]
        NETWORK (Nick runs it). One Yahoo call per season: every trade
        transaction of the nine past leagues (yahoo.historical_league_keys,
        2017-18 to 2025-26) and this season's (yahoo.current_league_key):
        10 calls. Saves Yahoo's raw JSON, untouched, as DIR/<season>.json
        (default _to_delete/56/raw_trades). Writes nothing else.

    python scripts/pull_trade_picks.py parse [--raw DIR] [--write]
        OFFLINE. Parses the raw files (modules/trade_picks) and reports: the
        shape Yahoo used, every trade's picks, each row of
        data/historical/all_trades.json matched to its Yahoo trade, the
        players byte for byte, the 2023-24 screenshot check, picks past a
        draft's live rounds (keeper slots), 2025-26 against its hand-typed
        labels, and this season against config/TRADES.json (report only:
        that file is league state). --write adds "draft_picks" to
        all_trades.json, and only if every past row matched, the players are
        unchanged and no Yahoo trade is missing from the file.

all_trades.json is public history (data/historical/, not in
config/STATE_MANIFEST.json), so it takes the picks; config/TRADES.json is
state and is never written here. The existing "picks" field (2025-26's
hand-typed labels, from config/TRADES.json at the rollup) is left as it is;
the structured picks go in "draft_picks".
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from modules import trade_picks as TP                       # noqa: E402
from modules import draft_history as DH                     # noqa: E402
from modules.data_loader import (CURRENT_SEASON, HISTORICAL_LEAGUE_KEYS, LEAGUE_KEY,  # noqa: E402
                                 team_key_managers)

RAW_DEFAULT = ROOT / "_to_delete" / "56" / "raw_trades"
TRADES_FILE = ROOT / "data" / "historical" / "all_trades.json"


def league_keys() -> dict:
    keys = dict(HISTORICAL_LEAGUE_KEYS)
    keys[CURRENT_SEASON] = LEAGUE_KEY
    return dict(sorted(keys.items()))


def cmd_fetch(a) -> int:
    from yahoo_oauth import OAuth2
    import yahoo_fantasy_api as yfa
    from modules.yahoo_auth import build_oauth
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    sc = build_oauth(ROOT / "oauth2.json", OAuth2=OAuth2)
    calls = 0
    for season, key in league_keys().items():
        lg = yfa.League(sc, key)
        raw = lg.yhandler.get(f"league/{key}/transactions;types=trade")
        calls += 1
        (out / f"{season}.json").write_text(json.dumps(raw, indent=1, ensure_ascii=False), encoding="utf-8")
        n = len(TP.parse(raw))
        print(f"  {season} ({key}): {n} trade(s) -> {out / (season + '.json')}")
    print(f"{calls} Yahoo call(s). Now: python scripts/pull_trade_picks.py parse")
    return 0


def opening_days() -> dict:
    log = json.loads((ROOT / "data" / "historical" / "HISTORICAL_PLAYERLOG.json").read_text(encoding="utf-8"))
    out: dict = {}
    for r in log:
        s = r["season_key"]
        if s not in out or r["date"] < out[s]:
            out[s] = r["date"]
    sched = json.loads((ROOT / "config" / "SCHEDULE.json").read_text(encoding="utf-8"))
    out[CURRENT_SEASON] = sched["weeks"][0]["start_date"]
    return out


LABEL = re.compile(r"(\d{4}) (\d+)(?:st|nd|rd|th) \((\w+)\)")


def _label(text: str) -> tuple:
    """'2026 2nd (Nick)' -> ("2026-27", 2, "Nick")."""
    m = LABEL.fullmatch(text.strip())
    if not m:
        raise ValueError(f"a 2025-26 pick label {text!r} is not 'YYYY Nth (Manager)'")
    y = int(m.group(1))
    return f"{y}-{(y + 1) % 100:02d}", int(m.group(2)), m.group(3)


def _labels_agree(rows) -> list:
    """For every 2025-26 row with typed labels: do the recorded picks (Yahoo,
    corrected, plus chat) equal them exactly?"""
    out = []
    for r in rows:
        if r["season"] == "2025-26" and r.get("picks") and "draft_picks" in r:
            typed = sorted((d, rd, o, sender) for sender, labels in r["picks"].items() for d, rd, o in map(_label, labels))
            got = sorted((p["draft"], p["round"], p["original_manager"], p["from_manager"]) for p in r["draft_picks"])
            out.append(typed == got)
    return out


def cmd_parse(a) -> int:
    raw_dir = Path(a.raw)
    files = sorted(raw_dir.glob("*.json"))
    if not files:
        print(f"REFUSED: no raw files in {raw_dir}: run 'python scripts/pull_trade_picks.py fetch' first")
        return 1
    yahoo, managers, vetoed = {}, {}, {}
    print("## How Yahoo records a trade (part keys, pick fields)\n")
    for f in files:
        s = f.stem
        raw = json.loads(f.read_text(encoding="utf-8"))
        yahoo[s] = TP.parse(raw)                     # completed trades only
        vetoed[s] = TP.not_completed(raw)
        managers[s] = team_key_managers(s, ROOT)
        if not managers[s]:
            print(f"REFUSED: RECORDS.team_name_history has no team keys for {s}")
            return 1
        shapes = sorted({json.dumps(t["parts"]) for t in yahoo[s]})
        fields = sorted({tuple(p["fields"]) for t in yahoo[s] for p in t["picks"]})
        print(f"- {s}: {len(yahoo[s])} trades, {sum(len(t['picks']) for t in yahoo[s])} picks; parts {shapes}; "
              f"pick fields {fields}")
    days = opening_days()
    on_disk = json.loads(TRADES_FILE.read_text(encoding="utf-8"))
    # a trade Yahoo does not mark completed (vetoed) is not a trade (Nick, 11-21): its row goes
    gone = {(s, ts) for s, v in vetoed.items() for _k, ts, _st in v}
    removed = [r for r in on_disk if (r["season"], str(r.get("timestamp"))) in gone]
    before = [r for r in on_disk if (r["season"], str(r.get("timestamp"))) not in gone]
    print(f"\n## Not completed in Yahoo\n\n{[(s, k, st) for s, v in vetoed.items() for k, _t, st in v]}; "
          f"rows removed: {[(r['season'], r['date'], [p['player_name'] for p in r['players']]) for r in removed]}")
    past = {s: v for s, v in yahoo.items() if s != CURRENT_SEASON}
    from modules.data_loader import normalize_player_name
    matched, rep = TP.match(before, past, managers, names=normalize_player_name)
    after = TP.add_picks(before, matched, managers, days)
    same = TP.players_unchanged(before, after)
    print(f"\n## all_trades.json\n\n{rep['matched']} of {len(before)} rows matched to a Yahoo trade; "
          f"unmatched rows {rep['unmatched_rows']}; Yahoo trades not in the file {rep['yahoo_only']}; "
          f"players and every other field unchanged: {same}")
    print("\n## Every trade's picks\n")
    for r in after:
        if "draft_picks" not in r:
            continue
        for p in r["draft_picks"]:
            tag = "listed, not valued (snake draft)" if not DH.keeper_era(p["draft"]) else "live"
            fix = f"; CORRECTED: {p['corrected']}" if p.get("corrected") else ""
            print(f"- {r['season']} {r['date']}: {p['from_manager']} -> {p['to_manager']}: "
                  f"{p['original_manager'] or '?'}'s {p['draft']} round {p['round']} "
                  f"[{tag}; {p['source']}; {p['draft_how']}{fix}]")
        for p in r.get("draft_picks_reversed", []):
            print(f"- {r['season']} {r['date']}: REVERSED (not part of the trade): {p['from_manager']} -> "
                  f"{p['to_manager']}: {p['original_manager']}'s {p['draft']} round {p['round']}: {p['reversed']}")
    sc = TP.screenshot_check(after)
    print(f"\n## The 2023-24 screenshot\n\nJan 15 exactly Nick->Benton round 1, Benton->Nick round 3: {sc['jan15']}; "
          f"Feb 26 has picks, Mar 7 has none (True = as the screenshot): {sc['later_have_picks']}; "
          f"all 2023-24: {sc['rows']}")
    # 2025-26 against its hand-typed labels
    print("\n## 2025-26: Yahoo against the hand-typed labels (config/TRADES.json at the rollup)\n")
    for r in after:
        if r["season"] != "2025-26" or "draft_picks" not in r:
            continue
        typed = sorted((d, rd, orig, sender) for sender, labels in (r.get("picks") or {}).items()
                       for d, rd, orig in map(_label, labels))
        got = sorted((p["draft"], p["round"], p["original_manager"], p["from_manager"]) for p in r["draft_picks"])   # Yahoo + chat
        print(f"- {r['date']}: {'SAME' if typed == got else 'DIFFERENT'}; typed {typed}; recorded {got}")
    if CURRENT_SEASON in yahoo:
        print(f"\n## {CURRENT_SEASON} (report only; config/TRADES.json is state)\n")
        for t in yahoo[CURRENT_SEASON]:
            ps = TP.picks_for_file(t, CURRENT_SEASON, managers[CURRENT_SEASON], days.get(CURRENT_SEASON))
            print(f"- {TP.day_of(t['timestamp'])}: {len(t['players'])} players; picks "
                  f"{[(p['draft'], p['round'], p['original_manager'], p['from_manager'], p['to_manager']) for p in ps]}")
    ok = same and not rep["unmatched_rows"] and not rep["yahoo_only"] and \
        all(typed_ok for typed_ok in _labels_agree(after))
    if a.write:
        if not ok:
            print("\nNOT WRITTEN: every past row must match, the players stay byte for byte, and no Yahoo "
                  "trade may be missing from the file. The reviewer decides.")
            return 1
        TRADES_FILE.write_text(json.dumps(after, indent=2, ensure_ascii=False), encoding="utf-8")   # the file's own format
        print(f"\nWrote {TRADES_FILE} (draft_picks on {len(matched)} rows; {len(removed)} vetoed row(s) removed).")
    else:
        print(f"\n{'Ready' if ok else 'NOT ready'} to write (--write).")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fetch")
    f.add_argument("--out", default=str(RAW_DEFAULT))
    p = sub.add_parser("parse")
    p.add_argument("--raw", default=str(RAW_DEFAULT))
    p.add_argument("--write", action="store_true")
    a = ap.parse_args(argv)
    return {"fetch": cmd_fetch, "parse": cmd_parse}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
