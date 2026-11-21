"""
nba_drafts.py -- every NBA draft 2014 to 2026: pick, round, player, matched to
Yahoo player ids (4a4 s.2.5; claude/HANDOFF_4A4_NBA_HISTORY_OVR_ARCHETYPES_2026-11-20.md).

WHY: OVR's rookie baseline (s.2.2, step 5) is a rookie curve, expected
rookie-season FPPG by NBA draft pick (Nick, 11-20: "NBA draft position is
fine"). Nothing in the repo held NBA draft positions (checked 11-20:
NBA_PLAYER_REFERENCE.json has teams only, PLAYERLIST has no draft column,
BBREF_AGES.json ages only, data/.cache had no draft page, and
data/historical/all_drafts.json is the LEAGUE's fantasy drafts).

THE PAGES
    https://www.basketball-reference.com/draft/NBA_{year}.html, one per draft
    (13 pages), fetched politely (nba_seasons_bbref's pace and headers: 3.2 s
    apart) and cached as fetched under data/.cache/bbref_draft_<year>.html
    (local only, gitignored), so a rerun fetches nothing it already has and a
    parser fix re-reads the cache. A failed fetch RAISES naming the URL;
    nothing is written to NBA_DRAFTS.json until every page is in.
      - Each pick row: pick_overall, the player (data-append-csv: his
        basketball-reference id) and the team. A pick row with no player (a
        forfeited pick) is counted, not stored.
      - THE ROUND: from the page's round rows ("Round 2" headers) when it has
        them; otherwise pick <= 30 is round 1 (every first round 2014-2026
        had 30 picks); provenance "round_from" says which.
      - A page whose picks are not 1..n without gaps (forfeited picks keep
        their numbers out of the order, so gaps in ROUND 2 are allowed and
        listed), or with fewer than MIN_PICKS picks, RAISES.

THE MATCH (never guessed): nba_seasons_bbref's -- the engine's PlayerIndex over
every (Yahoo id, name) the project holds (NBA_SEASONS.json, the league log,
player_actuals, PLAYERLIST). One Yahoo id: matched. Several: "ambiguous".
None: "unmatched" (most often a pick who never played an NBA game: no Yahoo
season lists him). Both listed per draft, neither stored as a match. An id
matched in two drafts: resolve_shared_ids (THE FILE, below).

THE FILE (data/historical/NBA_DRAFTS.json; public NBA data, NOT state:
committed so the cloud runner has it)
    {"version", "about", "provenance": {year: {"source", "url", "fetched_at",
       "picks", "forfeited", "round_from", "matched", "unmatched": [...],
       "ambiguous": [...], "gaps": [...]}},
     "drafts": {year: [{"pick", "round", "name", "bbref_id", "team",
                        "yahoo_id" or null}]},
     "players": {yahoo id: {"year", "pick", "round", "name"}}}
  ONE YAHOO ID, TWO DRAFT ENTRIES (two players who share a name, e.g. Justin
  Jackson 2017 #15 and 2018 #43): the id's first season in NBA_SEASONS.json
  decides (resolve_shared_ids); the entry that does not fit, or every entry
  when none or several fit, goes to unmatched with the reason. Deterministic: years
  ascending, picks ascending, players by numeric id; one pick per line.
  A player with a Yahoo id who is not in "players" was UNDRAFTED, or drafted
  before 2014 (the reader knows his first NBA season; s.2.2).
"""
from __future__ import annotations

import html as html_lib
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

RELPATH = Path("data") / "historical" / "NBA_DRAFTS.json"
URL = "https://www.basketball-reference.com/draft/NBA_{year}.html"
SOURCE = "basketball-reference"
VERSION = 1
FIRST_YEAR, LAST_YEAR = 2014, 2026
FIRST_ROUND = 30
MIN_PICKS = 45
ABOUT = ("Every NBA draft's picks (basketball-reference's draft pages), matched to Yahoo player ids. Public NBA "
         "data, not league state. Written by scripts/fetch_nba_seasons.py --drafts.")


class DraftsError(RuntimeError):
    """A page, the match or the file is wrong; the message names it."""


def years(first: int = FIRST_YEAR, last: int = LAST_YEAR) -> List[int]:
    if first > last:
        raise DraftsError(f"first year {first} is after last year {last}")
    return list(range(int(first), int(last) + 1))


def path(base=".") -> Path:
    return Path(base) / RELPATH


def cache_path(base, year: int) -> Path:
    return Path(base) / "data" / ".cache" / f"bbref_draft_{int(year)}.html"


def get_page(base, year: int, *, fetch: Callable[[str], str] = None, sleeper=time.sleep,
             state: dict = None) -> str:
    """The draft's page: the cached copy, or a polite fetch cached as fetched.
    RAISES naming the URL; nothing cached on a failure."""
    from . import nba_seasons_bbref as nb
    cache = cache_path(base, year)
    if cache.is_file():
        return cache.read_text(encoding="utf-8")
    url = URL.format(year=int(year))
    state = state if state is not None else {}
    if state.get("fetched"):
        sleeper(nb.PACE)
    try:
        text = (fetch or nb._http_get)(url)
    except Exception as e:
        from . import nba_seasons as ns
        raise DraftsError(f"{url}: {type(e).__name__}: {ns.redact(e)}; nothing written "
                          "(the pages already fetched are cached)") from e
    state["fetched"] = state.get("fetched", 0) + 1
    cache.parent.mkdir(parents=True, exist_ok=True)
    tmp = cache.with_suffix(cache.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(cache)
    return text


def _cell(row: str, name: str) -> Optional[str]:
    m = re.search(r'<t[dh][^>]*data-stat="' + name + r'"[^>]*>(.*?)</t[dh]>', row, re.S)
    if not m:
        return None
    return html_lib.unescape(re.sub(r"<[^>]+>", "", m.group(1))).strip()


def parse_draft(doc: str, year: int) -> dict:
    """{"picks": [{"pick", "round", "name", "bbref_id", "team"}], "forfeited", "round_from", "gaps"}."""
    doc = doc.replace("<!--", "").replace("-->", "")
    m = re.search(r'<table[^>]+id="stats".*?</table>', doc, re.S)
    if not m:
        raise DraftsError(f"{year}: no draft table (id=\"stats\") on the page")
    body = m.group(0)
    rnd, saw_round_rows = 1, False
    picks, forfeited = [], 0
    for row in re.findall(r"<tr[^>]*>.*?</tr>", body, re.S):
        text = html_lib.unescape(re.sub(r"<[^>]+>", " ", row))
        rm = re.search(r"\bRound\s+(\d)\b", text)
        if rm and 'data-stat="pick_overall"' not in row:
            rnd, saw_round_rows = int(rm.group(1)), True
            continue
        p = _cell(row, "pick_overall")
        if p is None or not p.isdigit():
            continue
        name = _cell(row, "player")
        if not name:
            forfeited += 1
            continue
        bid = re.search(r'data-stat="player"[^>]*data-append-csv="([^"]+)"', row) or \
            re.search(r'data-append-csv="([^"]+)"[^>]*data-stat="player"', row)
        picks.append({"pick": int(p), "round": rnd, "name": name, "bbref_id": bid.group(1) if bid else None,
                      "team": _cell(row, "team_id") or ""})
    if not picks:
        raise DraftsError(f"{year}: the draft table has no pick rows")
    if not saw_round_rows:
        for x in picks:
            x["round"] = 1 if x["pick"] <= FIRST_ROUND else 2
    nums = [x["pick"] for x in picks]
    if len(set(nums)) != len(nums):
        raise DraftsError(f"{year}: a pick number repeats ({sorted(n for n in nums if nums.count(n) > 1)[:5]})")
    first = sorted(x["pick"] for x in picks if x["round"] == 1)
    if first != list(range(1, len(first) + 1)) or len(first) != FIRST_ROUND:
        raise DraftsError(f"{year}: the first round is not picks 1..{FIRST_ROUND} without a gap ({first[:3]}..)")
    gaps = sorted(set(range(1, max(nums) + 1)) - set(nums))
    if len(picks) < MIN_PICKS:
        raise DraftsError(f"{year}: only {len(picks)} picks read (at least {MIN_PICKS} expected): the parser is "
                          "wrong for this page")
    picks.sort(key=lambda x: x["pick"])
    return {"picks": picks, "forfeited": forfeited, "gaps": gaps,
            "round_from": "the page's round rows" if saw_round_rows else f"pick number (1..{FIRST_ROUND} round 1)"}


def first_season_start(seasons_blob: dict, pid: str) -> Optional[int]:
    """The start year of his first season PLAYED in NBA_SEASONS.json (2017 for
    2017-18), or None (no season in the file)."""
    seasons = ((seasons_blob.get("players") or {}).get(pid) or {}).get("seasons") or {}
    played = sorted(s for s, e in seasons.items() if int(e.get("gp") or 0) > 0)
    return int(played[0][:4]) if played else None


def resolve_shared_ids(claims: Dict[str, List[dict]], seasons_blob: dict) -> Tuple[Dict[Tuple[int, int], str], List[dict]]:
    """Two or more draft entries matched to one Yahoo id (two players who share
    a name, Nick 11-20: Justin Jackson 2017 #15 and 2018 #43): the id's FIRST
    SEASON in NBA_SEASONS.json decides. An entry fits when that season starts
    in its draft year or later (rookie season = draft year + 1, a later debut
    allowed). Exactly one fits: it keeps the id; the others go to unmatched.
    None fits, several fit, or the id has no season in the file: every entry
    goes to unmatched. Never guessed.
    claims: {pid: [{"year", "pick", "name"}]} (only ids with 2+ entries).
    Returns ({(year, pick): pid} kept, [unmatched {"year", "pick", "name", "why"}])."""
    keep, out = {}, []
    for pid, es in sorted(claims.items(), key=lambda t: int(t[0])):
        first = first_season_start(seasons_blob, pid)
        names = ", ".join(f"{e['year']} #{e['pick']}" for e in es)
        if first is None:
            fits = []
            why = f"Yahoo id {pid} is claimed by {names} and has no season in NBA_SEASONS.json to tell them apart"
        else:
            fits = [e for e in es if first >= int(e["year"])]
            why = None
        if len(fits) == 1:
            w = fits[0]
            keep[(int(w["year"]), int(w["pick"]))] = pid
            for e in es:
                if e is not w:
                    out.append(dict(e, why=f"shares Yahoo id {pid} with {w['year']} #{w['pick']}, whose first season "
                                           f"({first}-{(first + 1) % 100:02d}) fits that draft, not this one"))
        else:
            for e in es:
                out.append(dict(e, why=why or (f"Yahoo id {pid} is claimed by {names}; his first season "
                                               f"({first}-{(first + 1) % 100:02d}) fits "
                                               + ("none of them" if not fits else "more than one of them"))))
    return keep, out


def build(base, pages: Dict[int, str], *, now: Optional[str] = None) -> dict:
    """The file's blob from {year: page text}: parsed, matched to Yahoo ids.
    An id matched by entries in two drafts is resolved by resolve_shared_ids."""
    from . import nba_seasons as ns, nba_seasons_bbref as nb
    try:
        seasons_blob = ns.load(str(base))
    except ns.SeasonsError as e:
        raise DraftsError(f"the match needs data/historical/NBA_SEASONS.json: {e}") from None
    index = nb.build_index(nb.yahoo_names(base, [seasons_blob]))
    stamp = now or datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    parsed, per_year = {}, {}
    claims: Dict[str, List[dict]] = {}
    for year in sorted(pages):
        d = parse_draft(pages[year], year)
        rows = [{"name": x["name"], "bbref_id": x["bbref_id"] or f"pick{x['pick']}", "gp": 0} for x in d["picks"]]
        matched, unmatched, ambiguous = nb.match(rows, index)
        by_bid = {r["bbref_id"]: pid for pid, r in matched.items()}
        ids = [by_bid.get(r["bbref_id"]) for r in rows]
        parsed[year], per_year[year] = d, {"ids": ids, "unmatched": unmatched, "ambiguous": ambiguous}
        for x, pid in zip(d["picks"], ids):
            if pid is not None:
                claims.setdefault(pid, []).append({"year": int(year), "pick": x["pick"], "name": x["name"]})
    shared = {pid: es for pid, es in claims.items() if len(es) > 1}
    keep, lost = resolve_shared_ids(shared, seasons_blob)
    lost_at = {(e["year"], e["pick"]): e for e in lost}
    blob = {"version": VERSION, "about": ABOUT, "provenance": {}, "drafts": {}, "players": {}}
    for year in sorted(pages):
        d, py = parsed[year], per_year[year]
        out = []
        unm = [{"name": u["name"], "pick": next(x["pick"] for x in d["picks"] if x["name"] == u["name"])}
               for u in py["unmatched"]]
        for x, pid in zip(d["picks"], py["ids"]):
            at = (int(year), x["pick"])
            if pid is not None and pid in shared and keep.get(at) != pid:
                unm.append({"name": x["name"], "pick": x["pick"], "why": lost_at[at]["why"]})
                pid = None
            out.append(dict(x, yahoo_id=pid))
            if pid is not None:
                blob["players"][pid] = {"year": int(year), "pick": x["pick"], "round": x["round"], "name": x["name"]}
        unm.sort(key=lambda u: u["pick"])
        blob["drafts"][str(year)] = out
        blob["provenance"][str(year)] = {
            "source": SOURCE, "url": URL.format(year=year), "fetched_at": stamp, "picks": len(out),
            "forfeited": d["forfeited"], "gaps": d["gaps"], "round_from": d["round_from"],
            "matched": sum(1 for x in out if x["yahoo_id"]), "unmatched": unm, "ambiguous": py["ambiguous"]}
    return blob


def dumps(blob: dict) -> str:
    lines = ["{", f'  "version": {json.dumps(blob["version"])},', f'  "about": {json.dumps(blob["about"])},',
             '  "provenance": {']
    prov = sorted(blob["provenance"].items())
    for i, (y, p) in enumerate(prov):
        lines.append(f"    {json.dumps(y)}: {json.dumps(p, sort_keys=True, ensure_ascii=True)}"
                     + ("," if i < len(prov) - 1 else ""))
    lines += ["  },", '  "drafts": {']
    dr = sorted(blob["drafts"].items())
    for i, (y, picks) in enumerate(dr):
        lines.append(f"    {json.dumps(y)}: [")
        for j, x in enumerate(picks):
            lines.append("      " + json.dumps(x, sort_keys=True, ensure_ascii=True) + ("," if j < len(picks) - 1 else ""))
        lines.append("    ]" + ("," if i < len(dr) - 1 else ""))
    lines += ["  },", '  "players": {']
    pl = sorted(blob["players"].items(), key=lambda t: int(t[0]))
    for i, (pid, x) in enumerate(pl):
        lines.append(f"    {json.dumps(pid)}: {json.dumps(x, sort_keys=True, ensure_ascii=True)}"
                     + ("," if i < len(pl) - 1 else ""))
    lines += ["  }", "}"]
    return "\n".join(lines) + "\n"


def write(base, blob: dict) -> Path:
    p = path(base)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(dumps(blob), encoding="utf-8")
    os.replace(tmp, p)
    return p


def load(base=".") -> dict:
    """For readers (the ratings): the file, checked. Missing or unreadable
    RAISES, naming the file and the fix."""
    p = path(base)
    if not p.is_file():
        raise DraftsError(f"{RELPATH.as_posix()} is missing: run python scripts/fetch_nba_seasons.py --drafts")
    try:
        blob = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise DraftsError(f"{RELPATH.as_posix()} is unreadable ({type(e).__name__}): run python "
                          "scripts/fetch_nba_seasons.py --drafts") from e
    if blob.get("version") != VERSION or not isinstance(blob.get("players"), dict) \
            or not isinstance(blob.get("drafts"), dict):
        raise DraftsError(f"{RELPATH.as_posix()} is not a version {VERSION} file: run python "
                          "scripts/fetch_nba_seasons.py --drafts")
    return blob


def run(base=".", *, first: int = FIRST_YEAR, last: int = LAST_YEAR, fetch: Callable[[str], str] = None,
        sleeper=time.sleep, log=print, now: Optional[str] = None) -> dict:
    """Fetch (or read from the cache) every draft page, then build and write
    the file. Nothing is written unless every page is in and parses."""
    state: dict = {}
    pages = {}
    for y in years(first, last):
        cached = cache_path(base, y).is_file()
        pages[y] = get_page(base, y, fetch=fetch, sleeper=sleeper, state=state)
        log(f"  {y}: {'cached' if cached else 'fetched'}")
    blob = build(base, pages, now=now)
    write(base, blob)
    return {"blob": blob, "fetched": state.get("fetched", 0)}


def summary_lines(blob: dict) -> List[str]:
    prov = blob["provenance"]
    picks = sum(p["picks"] for p in prov.values())
    matched = sum(p["matched"] for p in prov.values())
    out = [f"NBA_DRAFTS: {len(prov)} drafts ({min(prov)}-{max(prov)}), {picks} picks, {matched} matched to a Yahoo "
           f"id, {len(blob['players'])} players."]
    for y, p in sorted(prov.items()):
        out.append(f"  {y}  picks {p['picks']:>2}  matched {p['matched']:>2}  unmatched {len(p['unmatched']):>2}  "
                   f"ambiguous {len(p['ambiguous'])}  forfeited/empty {p['forfeited']}  round from {p['round_from']}"
                   + (f"  gaps {p['gaps']}" if p["gaps"] else ""))
        if p["unmatched"]:
            out.append("      unmatched: " + ", ".join(f"#{u['pick']} {u['name']}" for u in p["unmatched"][:12])
                       + (f" ... and {len(p['unmatched']) - 12} more" if len(p["unmatched"]) > 12 else ""))
        for u in p["unmatched"]:
            if u.get("why"):
                out.append(f"      shared id: #{u['pick']} {u['name']}: {u['why']}")
        for a in p["ambiguous"]:
            out.append(f"      ambiguous: {a['name']} -> Yahoo {a['yahoo_ids']}: {a['why']}")
    top = [x for y in sorted(blob["drafts"]) for x in blob["drafts"][y] if x["pick"] <= 14 and not x["yahoo_id"]]
    out.append(f"  Lottery picks (1-14) unmatched: {len(top)}"
               + (": " + ", ".join(f"{x['name']} ({x['pick']})" for x in top[:15]) if top else ""))
    return out
