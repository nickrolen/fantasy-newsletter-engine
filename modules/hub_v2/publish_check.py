"""
hub_v2/publish_check.py -- open the new hub's published files the way a phone
does, before Nick flips hub.version to "v2" (5a; scripts/build_hub.py --v2
--publish-check).

    check(base, payload, cards, out_dir, ...) -> report
        builds the published new hub into out_dir with THROWAWAY_PASSPHRASE
        and a fresh salt (publish.build, live=False: never output/hub_publish/,
        never the league passphrase or the hub's salt), then:
          1. the shell: the new hub's (font-src data:, the gunzip step, the
             old-browser message), and the bundle marked gzip;
          2. the bundle opened as SHELL_JS_V2 opens it: PBKDF2-SHA256 at the
             bundle's own salt and iterations, AES-GCM, gunzip, JSON;
          3. every route: each href="#/..." in the page lands on a screen by the
             page script's own rule (route(): league/... and players/...
             are dynamic), and every tab has its screen;
          4. every lazy part opened with the key the page or the card index
             gives it, as HUB.part / HUB.photo / HUB.openIssue do: League's
             History chips and Awards (data-part), the card index, every card,
             every headshot, every newsletter issue;
          5. every published file is reached by some key (no orphan) and
             every key's file exists;
          6. the plaintext scan of every file, and its negative control (the
             decrypted page trips it: the scan would catch a leak);
          6b. (5c) the text audit: the VISIBLE text of the page, every lazy
             screen, every lazy part and every card (text, the attributes a
             reader sees -- tooltips, labels -- and Compare's data) holds no
             object text ("{'", "'cls':", "True}", "False}", "None",
             "[object", "undefined", "NaN") and no empty value ("( )",
             "\u00b7  \u00b7", two middle dots with nothing between). Empty cells and lone dashes are counted for the report;
          7. the banners the page carries (stale, engine mismatch, the H52
             closing-line note, the line header) and the sizes: the first
             load against hub.first_load_budget_kb, each lazy file against
             the 60 KB cap (the issues, whole newsletters, are exempt).
        report["ok"] is True only when 1-6b pass and the first load is within
        the budget.
"""

from __future__ import annotations

import base64
import gzip
import html as _html
import json
import re
from pathlib import Path

THROWAWAY_PASSPHRASE = "a throwaway passphrase for the publish check only"
ITERATIONS = 1000                    # the check's own key: a real build uses hub_crypto.ITERATIONS
OLD_BROWSER = "This browser is too old to open the hub. Update iOS or Chrome."


def _bundle(index_html: str) -> dict:
    m = re.search(r'id="hub-bundle">(.*?)</script>', index_html, re.S)
    if not m:
        raise ValueError("index.html carries no hub-bundle")
    return json.loads(m.group(1))


def open_page(index_html: str, passphrase: str) -> dict:
    """The shell's open step, in Python: derive, decrypt, gunzip, parse."""
    from .. import hub_crypto
    b = _bundle(index_html)
    pt = hub_crypto.open_bundle(passphrase, {k: v for k, v in b.items() if k != "z"})
    if b.get("z") == "gzip":
        pt = gzip.decompress(pt)
    return json.loads(pt)


def open_part(out_dir: Path, ref: dict, gz: bool = True):
    """HUB.part / HUB.photo: fetch ref["file"], AES-GCM with ref["key"]
    (the IV is the file's first 12 bytes), then gunzip and parse (gz)."""
    from .. import hub_crypto
    blob = (Path(out_dir) / ref["file"]).read_bytes()
    pt = hub_crypto.open_sealed(hub_crypto.unb64(ref["key"]), blob)
    return json.loads(gzip.decompress(pt)) if gz else pt


def routes(page: str) -> dict:
    """{"screens", "links", "unresolved"}: each in-page link resolved by the
    page script's route() rule."""
    screens = set(re.findall(r'class="v2-screen" data-route="([^"]+)"', page))
    links = sorted(set(re.findall(r'href="#/([^"]*)"', page)))
    bad = []
    for r in links:
        r = _html.unescape(r) or "home"
        r = r.split("?")[0] or "home"                # 5d1/5d2: a route's query is not its screen
        parts = r.split("/")
        want = r
        if parts[0] == "league" and len(parts) > 1 and parts[1]:
            want = "league"
        if parts[0] == "players" and len(parts) > 1 and parts[1]:
            want = ("compare" if len(parts) > 3 and parts[3] else "compare-pick") if parts[1] == "compare" \
                else "player"
        if parts[0] == "manager" and len(parts) > 2:       # MC2: #/manager/<name>/<tab> is his card's screen
            want = "/".join(parts[:2])
        if want not in screens:
            bad.append(r)
    return {"screens": sorted(screens), "links": links, "unresolved": bad}


# 5c: the text audit (s.3, s.5 of HANDOFF_5C). History printed a team's dict as
# its name on the live hub, and every check missed it: History is a lazy
# part, and the tests read its template, not the published part. So the
# check reads what a reader sees in every published piece.
SHOWN_ATTRS = ("aria-label", "title", "placeholder", "alt", "data-tip-h", "data-tip-b", "data-tip-f",
               "data-head", "data-body", "data-label", "data-tip")
OBJECT_TEXT = re.compile(r"\{'|'cls':|True\}|False\}|\bNone\b|\[object|\bundefined\b|\bNaN\b")
EMPTY_TEXT = re.compile(r"\(\s*\)|\u00b7\s*\u00b7")
_JSON_BLOCK = re.compile(r'<script type="application/json"[^>]*>(.*?)</script>', re.S)


def _strings(obj):
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from _strings(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _strings(v)


def visible_text(html: str) -> str:
    """What a reader can see of an HTML string: its text (tags as spaces,
    entities unescaped), the attributes shown as text (SHOWN_ATTRS), and the
    strings of its JSON data blocks (Compare's rows, drawn by the script).
    Scripts and styles are left out."""
    data = []
    for m in _JSON_BLOCK.finditer(html):
        try:
            data.extend(_strings(json.loads(m.group(1).replace("<\\/", "</"))))
        except ValueError:
            data.append(m.group(1))
    body = _JSON_BLOCK.sub(" ", html)
    body = re.sub(r"<(script|style)\b[^>]*>.*?</\1>", " ", body, flags=re.S | re.I)
    attrs = [_html.unescape(m.group(2)) for m in
             re.finditer(r'\s(' + "|".join(SHOWN_ATTRS) + r')="([^"]*)"', body)]
    text = _html.unescape(re.sub(r"<[^>]*>", " ", body))
    return "\n".join([text] + attrs + data)


# 5d1 s.9 (CHAMPION_HOTFIX follow-up; LEAGUE_RULES "Who the champion is"): the
# same mistake four times, so the published text is checked. Every visible
# "champion(s)", "championship(s)" or "title(s)" must be the League
# Champion's (the regular-season winner), or qualified "playoff" or "Cup", or
# title odds / Title delta. A word no pattern below covers REFUSES the publish:
# a new use is a deliberate addition here, never a silent one.
CHAMPION_WORD = re.compile(r"\b(?:champions?|championships?|titles?)\b", re.I)
CHAMPION_OK = [re.compile(x, f) for x, f in (
    (r"\btitle(?:[- ]odds|s? \u0394|-odds)", re.I),                         # title odds, Title delta
    (r"\b(?:playoff|cup)\s+(?:champion(?:ship)?s?|titles?)\b", re.I),       # Playoff champion, playoff title(s)
    (r"\bleague(?:'s)?\s+champion(?:ship)?s?\b", re.I),                    # League Champion(ships), the league's champion
    (r"\bregular[- ]season\s+titles?\b", re.I),                            # the regular-season title (= League Champion)
    (r"\bThe champion is the League Champion\b", 0),                        # League > History's note
    (r"\bChampions(?= (?:All-time|\d+ seasons?\b))", 0),                   # the History chip and its section: League Champions
    (r"\bTitles(?= (?:Playoff\b|=? ?League Championships))", 0),           # All-time's column (titles_won), its note and definition
    (r"(?<=\bStrk )Title\b", 0),                                           # Standings' title-odds column
)]


def champion_audit(pieces: dict) -> list:
    """[(where, the word with 40 characters either side)] for every visible
    champion/title word that no CHAMPION_OK pattern covers."""
    out = []
    for where, html in pieces.items():
        t = " ".join(visible_text(html).split())
        ok = [m.span() for rx in CHAMPION_OK for m in rx.finditer(t)]
        for m in CHAMPION_WORD.finditer(t):
            if not any(a <= m.start() and m.end() <= b for a, b in ok):
                out.append((where, t[max(0, m.start() - 40):m.end() + 40]))
    return out


# 5e (Nick, 11-22): "No rule numbers anywhere in the UI" ("rules 4-11", "(rule 3)"):
# the rule is said in words or left out. A visible rule number REFUSES the publish.
RULE_NUMBER = re.compile(r"\brules?\s+\d+", re.I)


def rule_audit(pieces: dict) -> list:
    """[(where, the rule number with 40 characters either side)] for every
    visible rule number."""
    out = []
    for where, html in pieces.items():
        t = " ".join(visible_text(html).split())
        for m in RULE_NUMBER.finditer(t):
            out.append((where, t[max(0, m.start() - 40):m.end() + 40]))
    return out


def text_audit(pieces: dict) -> dict:
    """{"pieces", "chars", "object_hits", "empty_hits", "empty_cells", "dash_cells"} over
    {where: html}. A hit is (where, the match with 30 characters either side)."""
    obj, emp, cells, dashes, chars = [], [], 0, 0, 0
    for where, html in pieces.items():
        t = visible_text(html)
        chars += len(t)
        for rx, out in ((OBJECT_TEXT, obj), (EMPTY_TEXT, emp)):
            for m in rx.finditer(t):
                out.append((where, " ".join(t[max(0, m.start() - 30):m.end() + 30].split())))
        for c in re.findall(r"<td\b[^>]*>(.*?)</td>", html, re.S):
            v = _html.unescape(re.sub(r"<[^>]*>", "", c)).strip()
            cells += (v == "")
            dashes += (v == "\u2014")
    return {"pieces": len(pieces), "chars": chars, "object_hits": obj, "empty_hits": emp,
            "empty_cells": cells, "dash_cells": dashes}


def _image_kind(b: bytes) -> str:
    if b[:3] == b"\xff\xd8\xff":
        return "jpeg"
    if b[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if b[:4] == b"RIFF" and b[8:12] == b"WEBP":
        return "webp"
    return ""


def check(base, payload: dict, cards, out_dir, *, now=None, pictures=None, terms=None, echo=print,
          picture_notes=(), card_errors=(), keep_shown: bool = False) -> dict:
    """Publish to out_dir under a throwaway passphrase, open every piece and
    check it (the report's "ok" and "problems"). keep_shown (H56): also
    return "shown", {where: HTML} of every piece the text audit read, for a
    caller's own audit of the published text."""
    from .. import hub_crypto, hub_publish, hub_archive
    from . import publish
    out = Path(out_dir)
    salt = hub_crypto.new_salt()
    rep = publish.build(base, payload, THROWAWAY_PASSPHRASE, salt=salt, out_dir=out, iterations=ITERATIONS,
                        terms=terms, now=now, cards=cards, pictures=pictures, strict_issues=True)
    terms = terms if terms is not None else hub_publish.scan_terms(base)
    problems = []
    shell = (out / "index.html").read_text(encoding="utf-8")
    b = _bundle(shell)
    sh = {"font_src": "font-src data:" in shell, "gunzip": "DecompressionStream('gzip')" in shell,
          "old_browser_text": OLD_BROWSER in shell, "bundle_gzip": b.get("z") == "gzip"}
    problems += [f"the shell lacks {k}" for k, v in sh.items() if not v]
    inner = open_page(shell, THROWAWAY_PASSPHRASE)
    page = inner["page"]
    reached = {"index.html"}
    shown = {"page": page}                           # 5c: every published piece's HTML, for the text audit
    # 5b: the lazy screens (team pages, last week's matchups): each opened, and
    # its HTML checked with the page's own (links, cards, parts, pictures)
    screens_opened = {}
    for raw in re.findall(r"data-screen-part='([^']*)'", page):
        ref = json.loads(_html.unescape(raw))
        try:
            h = str(open_part(out, ref).get("html") or "")
            if not h.strip():
                problems.append(f"{ref['file']}: an empty screen part")
            screens_opened[ref["file"]] = h
            shown[f"screen {ref['file']}"] = h
            reached.add(ref["file"])
        except Exception as e:                       # noqa: BLE001 -- named
            problems.append(f"{ref.get('file')}: {type(e).__name__}: {e}")
    page = page + "".join(screens_opened.values())
    rt = routes(page)
    if rt["unresolved"]:
        problems.append(f"links with no screen: {rt['unresolved']}")
    for tab in ("home", "matchups", "teams", "players", "market", "league"):
        if tab not in rt["screens"]:
            problems.append(f"no {tab} screen")
    opened = {"screens": len(screens_opened), "parts": {}, "cards": 0, "photos": 0, "issues": 0, "pictures": 0}
    # League's History chips and Awards (5d1 s.8: and the past seasons' parts
    # their pickers hold, opened from inside them: a queue, not one pass)
    todo = list(re.findall(r"data-part='([^']*)'", page))
    while todo:
        raw = todo.pop(0)
        ref = json.loads(_html.unescape(raw))
        if ref.get("file") in opened["parts"]:
            continue
        try:
            obj = open_part(out, ref)
            if not str(obj.get("html") or "").strip():
                problems.append(f"{ref['file']}: an empty part")
            opened["parts"][ref["file"]] = len(obj["html"])
            shown[f"part {ref['file']}"] = str(obj["html"])
            reached.add(ref["file"])
            todo += re.findall(r"data-part='([^']*)'", str(obj["html"]))
        except Exception as e:                       # noqa: BLE001 -- named
            problems.append(f"{ref.get('file')}: {type(e).__name__}: {e}")
    if not opened["parts"]:
        problems.append("no lazy part found in the page (League's History and Awards)")
    # 5b: the team pages' full pictures (data-pic on the 72 TeamMark): each an image
    for raw in re.findall(r"data-pic='([^']*)'", page):
        ref = json.loads(_html.unescape(raw))
        try:
            uri = str(open_part(out, ref).get("pic") or "")
            m = re.fullmatch(r"data:image/(jpeg|png|gif|webp);base64,([A-Za-z0-9+/=]+)", uri)
            if not m or not _image_kind(base64.b64decode(m.group(2))):
                problems.append(f"{ref['file']}: a team picture part that is not an image")
            reached.add(ref["file"])
            opened["pictures"] += 1
        except Exception as e:                       # noqa: BLE001 -- named
            problems.append(f"{ref.get('file')}: {type(e).__name__}: {e}")
    # the cards: the index, every card, every headshot
    if inner.get("cards"):
        try:
            idx = open_part(out, inner["cards"])
            reached.add(inner["cards"]["file"])
            for key, ent in sorted(idx["cards"].items()):
                c = open_part(out, ent["card"])
                if not str(c.get("html") or "").strip():
                    problems.append(f"card {key}: empty")
                shown[f"card {key}"] = str(c.get("html") or "")
                reached.add(ent["card"]["file"])
                opened["cards"] += 1
                if ent.get("photo"):
                    img = open_part(out, ent["photo"], gz=False)
                    if not _image_kind(img):
                        problems.append(f"headshot of {key}: not an image")
                    reached.add(ent["photo"]["file"])
                    opened["photos"] += 1
            for raw in re.findall(r'data-card="([^"]+)"', page):
                if raw not in idx["cards"]:
                    problems.append(f"the page links card {raw}, which the index lacks")
        except Exception as e:                       # noqa: BLE001 -- named
            problems.append(f"the cards: {type(e).__name__}: {e}")
    elif (payload.get("cards") or {}).get("players"):
        problems.append("the payload lists cards and the bundle has no card index")
    # the newsletter issues, by the archive's own keys
    for f, k in sorted(inner["issues"].items()):
        try:
            pt = hub_crypto.open_sealed(hub_crypto.unb64(k), (out / "issues" / f).read_bytes())
            if b"<html" not in pt[:4000].lower():
                problems.append(f"issue {f}: not an HTML page")
            reached.add(f"issues/{f}")
            opened["issues"] += 1
        except Exception as e:                       # noqa: BLE001 -- named
            problems.append(f"issue {f}: {type(e).__name__}: {e}")
    for f in re.findall(r'data-issue="([^"]+)"', page):
        if f not in inner["issues"]:
            problems.append(f"the page opens issue {f}, which the bundle has no key for")
    audit = text_audit(shown)
    if audit["object_hits"]:
        problems.append(f"object text on the page ({len(audit['object_hits'])}): {audit['object_hits'][:5]}")
    if audit["empty_hits"]:
        problems.append(f"empty values on the page ({len(audit['empty_hits'])}): {audit['empty_hits'][:5]}")
    champ = champion_audit(shown)                    # 5d1 s.9: who is called champion
    audit["champion_hits"] = champ
    if champ:
        problems.append(f"a champion or title the rules don't name ({len(champ)}; LEAGUE_RULES \"Who the champion "
                        f"is\"): {champ[:5]}")
    rules = rule_audit(shown)                        # 5e: no rule numbers in the UI
    audit["rule_hits"] = rules
    if rules:
        problems.append(f"a rule number on the page ({len(rules)}; say it in words): {rules[:5]}")
    orphans = sorted(set(rep["files"]) - reached)
    if orphans:
        problems.append(f"published files no key reaches: {orphans}")
    scan = hub_publish.scan_dir(out, terms)
    if scan["hits"]:
        problems.append(f"PLAINTEXT: {scan['hits']}")
    control = bool(hub_publish.hits(inner["page"].encode("utf-8"), terms))
    if not control:
        problems.append("the negative control did not trip: the decrypted page matched no scan term")
    banners = {"stale_banner": 'id="stale"' in page, "stale_shown": bool(re.search(r'id="stale" role="status">', page)),
               "engine_mismatch": "Do not price anything off this page." in page,
               "closing_note": None, "line_header": (re.search(r'(Closing line priced|Line priced)[^<]*', page)
                                                     or [None])[0]}
    cn = (payload.get("header") or {}).get("closing_note")
    banners["closing_note"] = (_html.escape(cn, quote=True) in page or cn in page) if cn else None
    if banners["closing_note"] is False:
        problems.append("the H52 closing-line note is in the payload and not on the page")
    if not banners["stale_banner"]:
        problems.append("the page has no stale banner")
    if (payload.get("header") or {}).get("engine_mismatch") and not banners["engine_mismatch"]:
        problems.append("the engine-mismatch banner is in the payload and not on the page")
    if rep["over_budget"]:
        problems.append(f"the first load is {rep['served_bytes']:,} bytes, over the {rep['budget_bytes']:,} budget")
    if rep["over_cap"]:
        problems.append(f"lazy files over {rep['lazy_cap_bytes']:,} bytes: {rep['over_cap']}")
    sizes = rep["sizes"]

    def group(prefix):
        v = [n for f, n in sizes.items() if f.startswith(prefix)]
        return {"files": len(v), "bytes": sum(v), "largest": max(v) if v else 0}

    return {"ok": not problems, "problems": problems, "dir": str(out), "shell": sh, "routes": rt,
            "opened": opened, "orphans": orphans, "scan": {"terms": len(terms), "files": len(scan["files"]),
                                                           "hits": scan["hits"], "control": control},
            "banners": banners, "text_audit": audit, "first_load": rep["served_bytes"], "budget": rep["budget_bytes"],
            "headroom": rep["budget_bytes"] - rep["served_bytes"], "fonts": rep["fonts_served_bytes"],
            "pictures": len(pictures or []), "picture_notes": list(picture_notes),
            "card_errors": list(card_errors),
            "groups": {g: group(g + "/") for g in ("parts", "cards", "photos", "issues")},
            "parts": {f: sizes[f] for f in sorted(opened["parts"])}, "league_parts": rep["league_parts"],
            "card_files": rep["card_files"], "over_cap": rep["over_cap"], "build": rep,
            **({"shown": shown} if keep_shown else {})}


def summary(rep: dict) -> list:
    g = rep["groups"]
    lines = [f"Publish check of {rep['dir']} (a throwaway key; the league passphrase and salt were not read):",
             f"  first load (index.html as served): {rep['first_load']:,} bytes of {rep['budget']:,} "
             f"({rep['headroom']:,} left; fonts {rep['fonts']:,}; {rep['pictures']} team picture(s) inline)",
             f"  routes: {len(rep['routes']['links'])} links, {len(rep['routes']['screens'])} screens, "
             f"{len(rep['routes']['unresolved'])} unresolved",
             f"  opened: {len(rep['opened']['parts'])} History/Awards parts (largest {g['parts']['largest']:,} B), "
             f"{rep['opened']['screens']} lazy screens, {rep['opened']['pictures']} team pictures, {rep['opened']['cards']} cards (largest {g['cards']['largest']:,} B), {rep['opened']['photos']} "
             f"headshots (largest {g['photos']['largest']:,} B), {rep['opened']['issues']} issues "
             f"(largest {g['issues']['largest']:,} B, whole newsletters: exempt from the 60 KB cap)",
             f"  plaintext scan: {rep['scan']['terms']} terms over {rep['scan']['files']} files, "
             f"{len(rep['scan']['hits'])} hit(s); negative control {'tripped' if rep['scan']['control'] else 'DID NOT TRIP'}",
             f"  text audit: {rep['text_audit']['pieces']} pieces, {rep['text_audit']['chars']:,} characters "
             f"of visible text: {len(rep['text_audit']['object_hits'])} object text, "
             f"{len(rep['text_audit']['empty_hits'])} empty value(s); {rep['text_audit']['empty_cells']} empty "
             f"cell(s), {rep['text_audit']['dash_cells']} dash cell(s) (counted, not failed); "
             f"{len(rep['text_audit'].get('champion_hits') or [])} unqualified champion/title word(s), "
             f"{len(rep['text_audit'].get('rule_hits') or [])} rule number(s)",
             f"  banners: stale {'present' if rep['banners']['stale_banner'] else 'MISSING'}"
             f" ({'shown' if rep['banners']['stale_shown'] else 'hidden'}), engine mismatch "
             f"{'shown' if rep['banners']['engine_mismatch'] else 'not shown'}, closing-line note "
             f"{ {None: 'none due', True: 'shown', False: 'MISSING'}[rep['banners']['closing_note']] }, "
             f"header: {rep['banners']['line_header']}"]
    for n in rep["picture_notes"]:
        lines.append(f"  team picture left out: {n}")
    lines.append("PASS: every check passed." if rep["ok"] else "FAIL:\n  - " + "\n  - ".join(rep["problems"]))
    return lines
