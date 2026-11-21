"""
nba_seasons_bbref.py -- basketball-reference season totals for the seasons
Yahoo can no longer serve (4a4 Phase A, 11-20; Nick's ruling after the
re-fetch: 2021-22 cost 977 calls and today's game refused 479 of its 763
players, "Player key 478.p.3520 does not exist").

THE RULE (Nick, 11-20)
    One source per season. basketball-reference for 2014-15 to 2021-22 (the
    partial Yahoo 2020-21 and 2021-22 are replaced); Yahoo for 2022-23 on.
    provenance[season]["source"] names it.

THE PAGES
    https://www.basketball-reference.com/leagues/NBA_{end year}_totals.html,
    one per season, fetched politely (3.2 s apart: basketball-reference
    allows 20 pages a minute; the same pace and headers as the engine's
    other basketball-reference fetches) and cached as fetched under
    data/.cache/bbref_totals_<season>.html (local only, gitignored), so a
    rerun fetches nothing it already has. A failed fetch RAISES naming the
    URL; nothing is written to NBA_SEASONS.json until every page is in.
      - Each row: bbref id (data-append-csv), name, team, games and the
        league's eleven counts (fg fga ft fta fg3 pts trb ast stl blk tov).
        A column missing from the page RAISES, naming the columns it has.
      - A TRADED PLAYER: his season total row (TOT, 2TM, 3TM...) and never
        the per-team rows. Several rows for one bbref id and no total row:
        rejected by name.
      - The box-score identities (nba_seasons.identity_error) reject a row
        by name, as for Yahoo.

THE MATCH TO YAHOO PLAYER IDS (never guessed)
    The engine's matcher (data_loader.PlayerIndex: exact, then accents and
    punctuation, then a generational suffix, then a first initial; an
    ambiguous step is a miss) over every (Yahoo id, name) the project holds:
    NBA_SEASONS.json's players and its Yahoo seasons' listings (the 2020-21
    pool listing, the players today's game would not serve), the league log,
    player_actuals and PLAYERLIST.
      - One Yahoo id: matched. Names that normalise alike but carry two Yahoo
        ids: "ambiguous" (both ids named). Two basketball-reference rows on
        one Yahoo id: both "ambiguous". No Yahoo id: "unmatched". Every one
        is listed in the season's provenance and in the report; none is
        stored.

THE PROOF (Nick, 11-20)
    2022-23 is fetched from basketball-reference too (not stored) and
    compared with Yahoo's 2022-23 for every matched player: games and the
    eleven counts. The 274 Yahoo 2021-22 players the re-fetch kept are a
    second comparison (from the file, or from the copy saved before it is
    replaced). Each is a gate: fewer than PROOF_MIN of the compared players
    identical in all twelve numbers REFUSES, nothing written.
"""
from __future__ import annotations

import html as html_lib
import json
import re
import shutil
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from . import nba_seasons as ns

URL = "https://www.basketball-reference.com/leagues/NBA_{year}_totals.html"
SOURCE = "basketball-reference"
METHOD = "season totals page; a traded player's total row (TOT/2TM), never the per-team rows"
SEASONS = ns.seasons_between("2014-15", "2021-22")
CHECK = "2022-23"               # fetched and compared with Yahoo, never stored
PACE = 3.2                      # seconds between pages: basketball-reference allows 20 a minute
PROOF_MIN = 0.95                # share of compared players identical in all twelve numbers
COLUMNS = {"GP": ("games", "g"), "FGM": ("fg",), "FGA": ("fga",), "FTM": ("ft",), "FTA": ("fta",),
           "3PTM": ("fg3",), "PTS": ("pts",), "REB": ("trb",), "AST": ("ast",), "ST": ("stl",),
           "BLK": ("blk",), "TO": ("tov",)}
TOTAL_ROW = re.compile(r"^(TOT|\dTM)$")
KNOWN_OTHER = {"ranker", "name_display", "player", "age", "team_name_abbr", "team_id", "pos", "games_started",
               "gs", "mp", "fg_pct", "fg3a", "fg3_pct", "fg2", "fg2a", "fg2_pct", "efg_pct", "ft_pct", "orb",
               "drb", "pf", "awards", "tpl_dbl", "trp_dbl"}


def cache_path(base, season: str) -> Path:
    return Path(base) / "data" / ".cache" / f"bbref_totals_{season}.html"


def page_url(season: str) -> str:
    return URL.format(year=ns.season_year(season) + 1)


def _http_get(url: str) -> str:
    from .nba_reference import HEADERS
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=45) as resp:
        return resp.read().decode("utf-8", "replace")


def get_page(base, season: str, *, fetch: Callable[[str], str] = None, sleeper=time.sleep,
             state: dict = None) -> str:
    """The season's totals page: the cached copy, or a polite fetch cached
    as fetched. RAISES naming the URL; nothing cached on a failure."""
    cache = cache_path(base, season)
    if cache.is_file():
        return cache.read_text(encoding="utf-8")
    url = page_url(season)
    state = state if state is not None else {}
    if state.get("fetched"):
        sleeper(PACE)
    try:
        text = (fetch or _http_get)(url)
    except urllib.error.HTTPError as e:
        raise ns.SeasonsError(f"{url}: HTTP {e.code}; nothing written (the pages already fetched are cached)") from e
    except Exception as e:
        raise ns.SeasonsError(f"{url}: {type(e).__name__}: {ns.redact(e)}; nothing written") from e
    state["fetched"] = state.get("fetched", 0) + 1
    cache.parent.mkdir(parents=True, exist_ok=True)
    tmp = cache.with_suffix(cache.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(cache)
    return text


# =============================================================================
# the page
# =============================================================================

def _cell(row: str, names) -> Optional[str]:
    for n in names:
        m = re.search(r'<t[dh][^>]*data-stat="' + n + r'"[^>]*>(.*?)</t[dh]>', row, re.S)
        if m:
            return html_lib.unescape(re.sub(r"<[^>]+>", "", m.group(1))).strip()
    return None


def parse_totals(doc: str, season: str, stats: List[str]) -> Tuple[List[dict], List[dict]]:
    """([{"bbref_id", "name", "team", "gp", "stats"}], rejected) -- one row
    per player: his total row if he was traded. RAISES ShapeError when a
    column is missing or the page has no player rows."""
    m = re.search(r'<table[^>]+id="totals_stats".*?</table>', doc, re.S)
    table = m.group(0) if m else doc
    by_id: Dict[str, List[dict]] = {}
    order: List[str] = []
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", table, re.S):
        idm = re.search(r'data-append-csv="([^"]+)"', row)
        name = _cell(row, ("name_display", "player"))
        if not idm or not name or name in ("Player", "League Average"):
            continue
        name = name.rstrip("*").strip()
        vals, missing = {}, []
        for k, cols in COLUMNS.items():
            v = _cell(row, cols)
            if v is None:
                missing.append(cols[0])
            vals[k] = v
        if missing:
            known = {c for cols in COLUMNS.values() for c in cols} | KNOWN_OTHER
            other = sorted(set(re.findall(r'data-stat="([a-z0-9_]+)"', row)) - known)
            raise ns.ShapeError(f"{page_url(season)}: the row for {name} has no column {missing}; "
                                f"its unfamiliar columns: {other}")
        team = _cell(row, ("team_name_abbr", "team_id")) or ""
        rec = {"bbref_id": idm.group(1), "name": name, "team": team, "raw": vals}
        if idm.group(1) not in by_id:
            order.append(idm.group(1))
        by_id.setdefault(idm.group(1), []).append(rec)
    if not by_id:
        raise ns.ShapeError(f"{page_url(season)}: no player rows (the page changed?)")
    rows, rejected = [], []
    for bid in order:
        recs = by_id[bid]
        tot = [r for r in recs if TOTAL_ROW.match(r["team"])]
        if len(recs) > 1 and len(tot) != 1:
            rejected.append({"bbref_id": bid, "name": recs[0]["name"],
                             "why": f"{len(recs)} rows and {len(tot)} season-total rows"})
            continue
        r = tot[0] if tot else recs[0]
        try:
            nums = {}
            for k, v in r["raw"].items():
                if not re.fullmatch(r"\d+", v or ""):
                    raise ValueError(f"{k} is {v!r}, not a count")
                nums[k] = int(v)
        except ValueError as e:
            rejected.append({"bbref_id": bid, "name": r["name"], "why": str(e)})
            continue
        st = {k: nums[k] for k in stats}
        why = ns.identity_error(nums["GP"], st)
        if why:
            rejected.append({"bbref_id": bid, "name": r["name"], "why": why})
            continue
        rows.append({"bbref_id": bid, "name": r["name"], "team": r["team"], "gp": nums["GP"], "stats": st})
    return rows, rejected


# =============================================================================
# the match
# =============================================================================

def yahoo_names(base, blobs: List[dict]) -> Dict[str, List[str]]:
    """{Yahoo id: [names, first seen first]} from everything the project
    holds that pairs a Yahoo id with a name. Yahoo's own spellings (the
    file) come first, so a stored name is Yahoo's."""
    out: Dict[str, List[str]] = {}

    def add(pid, name):
        if pid is None or not name:
            return
        try:
            pid = str(int(pid))
        except (TypeError, ValueError):
            return
        lst = out.setdefault(pid, [])
        if str(name).strip() not in lst:
            lst.append(str(name).strip())

    for blob in blobs:
        for pid, r in (blob.get("players") or {}).items():
            add(pid, r.get("name"))
        for p in (blob.get("provenance") or {}).values():
            for pid, name in (p.get("listing") or {}).items():
                add(pid, name)
            for u in p.get("unserved") or []:
                add(u.get("player_id"), u.get("name"))
    log = Path(base) / "data" / "historical" / "HISTORICAL_PLAYERLOG.json"
    if log.is_file():
        for row in json.loads(log.read_text(encoding="utf-8")):
            add(row.get("player_id"), row.get("player_name"))
    act = Path(base) / "data" / "player_actuals.json"
    if act.is_file():
        a = json.loads(act.read_text(encoding="utf-8"))
        for k in ("roster_names", "extra_names"):
            for n, pid in (a.get(k) or {}).items():
                add(pid, n)
        for pid, r in (a.get("players") or {}).items():
            add(pid, (r or {}).get("name"))
    pl = Path(base) / "data" / "PLAYERLIST.xlsx"
    if pl.is_file():
        import pandas as pd
        f = pd.read_excel(pl)
        if "yahoo_id" in f.columns:
            for _, r in f.iterrows():
                if str(r.get("yahoo_id", "")).strip() not in ("", "nan"):
                    add(r["yahoo_id"], r.get("player_name"))
    return out


def build_index(names: Dict[str, List[str]]):
    """data_loader.PlayerIndex over {display name: frozenset(Yahoo ids)},
    one key per normalised name, so two ids that spell alike stay together
    (and come back ambiguous) instead of one overwriting the other."""
    from .data_loader import PlayerIndex, normalize_player_name
    by_norm: Dict[str, Tuple[str, set]] = {}
    for pid in sorted(names, key=int):
        for n in sorted(names[pid]):
            key = normalize_player_name(n)
            if not key:
                continue
            disp, ids = by_norm.setdefault(key, (n, set()))
            ids.add(pid)
    return PlayerIndex({disp: frozenset(ids) for disp, ids in by_norm.values()})


def match(rows: List[dict], index) -> Tuple[Dict[str, dict], List[dict], List[dict]]:
    """(matched {Yahoo id: row}, unmatched, ambiguous)."""
    hits: Dict[str, List[dict]] = {}
    unmatched, ambiguous = [], []
    for r in rows:
        key = index.canonical(r["name"])
        if key is None:
            unmatched.append({"name": r["name"], "bbref_id": r["bbref_id"], "gp": r["gp"]})
            continue
        ids = sorted(dict.get(index, key), key=int)
        if len(ids) != 1:
            ambiguous.append({"name": r["name"], "bbref_id": r["bbref_id"], "yahoo_ids": ids,
                              "why": f"{key!r} is {len(ids)} Yahoo players"})
            continue
        hits.setdefault(ids[0], []).append(r)
    matched = {}
    for pid, rs in hits.items():
        if len(rs) == 1:
            matched[pid] = rs[0]
        else:
            for r in rs:
                ambiguous.append({"name": r["name"], "bbref_id": r["bbref_id"], "yahoo_ids": [pid],
                                  "why": f"{len(rs)} basketball-reference players resolve to Yahoo id {pid}"})
    unmatched.sort(key=lambda x: (-x["gp"], x["name"]))
    ambiguous.sort(key=lambda x: (x["name"], x["bbref_id"]))
    return matched, unmatched, ambiguous


def compare(season: str, matched: Dict[str, dict], blob: dict, stats: List[str]) -> dict:
    """Every matched player with a Yahoo line for `season` in `blob`: games
    and the eleven counts, identical or not."""
    diffs, same, compared = [], 0, 0
    yahoo_played = {pid for pid, r in blob["players"].items()
                    if (r["seasons"].get(season) or {}).get("gp", 0) > 0}
    for pid in sorted(matched, key=int):
        y = (blob["players"].get(pid) or {}).get("seasons", {}).get(season)
        if y is None:
            continue
        compared += 1
        b = matched[pid]
        d = [(k, b["gp"] if k == "GP" else b["stats"][k], y["gp"] if k == "GP" else y["stats"][k])
             for k in ["GP"] + stats
             if (b["gp"] if k == "GP" else b["stats"][k]) != (y["gp"] if k == "GP" else y["stats"][k])]
        if d:
            diffs.append({"player_id": pid, "name": b["name"], "diffs": d})
        else:
            same += 1
    not_matched = sorted(yahoo_played - set(matched), key=int)
    return {"season": season, "compared": compared, "identical": same, "diffs": diffs,
            "yahoo_not_matched": [(pid, blob["players"][pid]["name"]) for pid in not_matched]}


def compare_lines(c: dict, label: str) -> List[str]:
    rate = c["identical"] / c["compared"] if c["compared"] else 0.0
    out = [f"PROOF {label}: {c['compared']} matched players compared; {c['identical']} identical in games and "
           f"all eleven stats ({rate:.1%}); {len(c['diffs'])} differ; {len(c['yahoo_not_matched'])} Yahoo "
           "players with games matched to no basketball-reference row"]
    for d in c["diffs"][:15]:
        out.append(f"    differs: {d['name']} ({d['player_id']}): "
                   + ", ".join(f"{k} bbref {b} vs Yahoo {y}" for k, b, y in d["diffs"]))
    if len(c["diffs"]) > 15:
        out.append(f"    ... and {len(c['diffs']) - 15} more (all in the report)")
    if c["yahoo_not_matched"]:
        out.append("    Yahoo, not matched: " + ", ".join(f"{n} ({p})" for p, n in c["yahoo_not_matched"][:15])
                   + (f" ... and {len(c['yahoo_not_matched']) - 15} more" if len(c["yahoo_not_matched"]) > 15 else ""))
    return out


# =============================================================================
# the run
# =============================================================================

def run(base=".", *, seasons: List[str] = None, check: str = CHECK, fetch: Callable[[str], str] = None,
        out_dir=None, log: Callable[[str], None] = print, sleeper=time.sleep,
        now: Callable[[], str] = None) -> dict:
    """Fetch (or read cached) every page, parse, match, prove, then replace
    `seasons` in NBA_SEASONS.json with basketball-reference's numbers in one
    atomic write. RAISES (nothing written) on a failed page, an unreadable
    page, or a failed proof."""
    seasons = list(seasons or SEASONS)
    stats = ns.stat_order(base)
    out_dir = Path(out_dir) if out_dir else Path(base) / "_to_delete" / "4a4"
    out_dir.mkdir(parents=True, exist_ok=True)
    now = now or (lambda: datetime.now(timezone.utc).replace(microsecond=0).isoformat())
    blob = ns.read(base, stats=stats)

    # the file as it was before basketball-reference replaced anything: the 2021-22 proof reads it
    before = out_dir / "NBA_SEASONS_before_bbref.json"
    if ns.path(base).is_file() and not before.exists():
        shutil.copyfile(ns.path(base), before)
    snap = json.loads(before.read_text(encoding="utf-8")) if before.exists() else {"players": {}, "provenance": {}}
    if snap.get("version") == 1:
        ns.migrate(snap)

    # 1. pages (cached ones cost nothing)
    state = {}
    pages = {}
    for s in sorted(set(seasons) | {check}):
        cached = cache_path(base, s).is_file()
        pages[s] = get_page(base, s, fetch=fetch, sleeper=sleeper, state=state)
        log(f"  {s}: {'cached' if cached else 'fetched'} {page_url(s)}")
    # 2. parse and match
    index = build_index(yahoo_names(base, [blob, snap]))
    parsed = {}
    for s, doc in pages.items():
        rows, rejected = parse_totals(doc, s, stats)
        matched, unmatched, ambiguous = match(rows, index)
        parsed[s] = {"rows": rows, "rejected": rejected, "matched": matched, "unmatched": unmatched,
                     "ambiguous": ambiguous}
    # 3. the proof: 2022-23 against Yahoo; the kept Yahoo 2021-22 players
    lines = []
    proofs = []
    c1 = compare(check, parsed[check]["matched"], blob, stats)
    proofs.append(("2022-23 vs Yahoo 2022-23", c1))
    y21 = "2021-22"
    src = blob if (blob["provenance"].get(y21) or {}).get("source") == "yahoo" else snap
    if y21 in parsed and (src.get("provenance") or {}).get(y21, {}).get("source") == "yahoo":
        proofs.append(("2021-22 vs the Yahoo 2021-22 players kept", compare(y21, parsed[y21]["matched"], src, stats)))
    else:
        lines.append("PROOF 2021-22: no Yahoo 2021-22 to compare with (not in the file or the saved copy)")
    failed = []
    for label, c in proofs:
        lines += compare_lines(c, label)
        if not c["compared"] or c["identical"] / c["compared"] < PROOF_MIN:
            failed.append(label)
    report = {"generated_at": now(), "proofs": {label: c for label, c in proofs},
              "seasons": {s: {k: v for k, v in p.items() if k not in ("rows", "matched")}
                          | {"matched": len(p["matched"]), "rows": len(p["rows"])} for s, p in parsed.items()}}
    (out_dir / "bbref_report.json").write_text(json.dumps(report, indent=1, ensure_ascii=False, default=list),
                                               encoding="utf-8")
    for line in lines:
        log(line)
    if failed:
        raise ns.SeasonsError(f"the proof failed ({'; '.join(failed)}: fewer than {PROOF_MIN:.0%} identical); "
                              f"NBA_SEASONS.json not changed. The differences: {out_dir / 'bbref_report.json'}")

    # 4. replace the seasons, one atomic write
    names = yahoo_names(base, [blob, snap])
    for s in seasons:
        p_old = blob["provenance"].get(s) or {}
        ns._clear_season(blob, s)
        P = parsed[s]
        rejected = [{"player_id": None, "name": r["name"], "why": r["why"], "bbref_id": r["bbref_id"]}
                    for r in P["rejected"]]
        for pid in sorted(P["matched"], key=int):
            r = P["matched"][pid]
            have = blob["players"].get(pid)
            name = have["name"] if have else (names.get(pid) or [r["name"]])[0]
            ns._store(blob, s, {"pid": pid, "name": name, "gp": r["gp"], "stats": r["stats"]})
        fetched = datetime.fromtimestamp(cache_path(base, s).stat().st_mtime, timezone.utc)
        blob["provenance"][s] = {
            "source": SOURCE, "url": page_url(s), "method": METHOD, "game_key": p_old.get("game_key"),
            "status": "complete", "next_start": 0, "pool": len(P["rows"]) + len(P["rejected"]),
            "fetched_at": fetched.replace(microsecond=0).isoformat(), "reason": None,
            "rejected": rejected, "no_stats": 0, "unserved": [],
            "matched": len(P["matched"]), "unmatched": P["unmatched"], "ambiguous": P["ambiguous"]}
    ns.write(base, blob)
    return {"blob": blob, "fetched": state.get("fetched", 0), "parsed": parsed, "proofs": proofs}
