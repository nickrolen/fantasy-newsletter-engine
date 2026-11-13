"""
hub_cards.py -- a player card for every player the hub names (task 40).

ONE CARD BUILDER. The cards are the newsletter's Keeper Watch cards
(modules/player_card_builder, opened in modules/player_card_modal's modal),
built live from the same run's data, so the hub and the newsletter never show
a player differently. A player outside Keeper Watch (a free agent, a player
named only in the moves feed) gets the same card without what does not apply
to him: no keep chance, no rank. A card's season numbers are his NBA numbers
(Nick, 11-12): data/player_actuals.json through the roster table's own day
(nba_lines), so a rostered card equals his row; a player that cache does not
cover gets a note instead (a free agent new to the hub's lists: the next
run fetches him, 40b; or one with no Yahoo id), and the league-roster figure
is a secondary line (player_card_builder, ONE FPPG EVERYWHERE).

WHICH NAMES (annotate, called by hub_state.build on every payload): every
player name the hub shows in a table or list --
    the rosters, the free agents, the stash candidates, the trade block, the
    moves feed (each add, drop, claim, IL step and trade side) and the advice
    view (when its switch is on).
Each gets a card key (his slug, modules/headshots.player_slug; one key for one
player's several spellings, by the PlayerIndex rules), written into the
payload beside the name (row["card"], or a part's "segs"), and
payload["cards"]["players"] lists them: {key: {"name", "kind", "manager",
"status"}}. Names inside prose (the matchup paragraphs, a roster's pending
note, the grid's NBA-report tooltip) are left plain.

THE LIVE PARTS ("status", from the payload itself, so the card and the row
agree): the owner (team and manager), "Free agent", or a group-chat claim;
the row's own chips (IL slot, O / Q / D, an injury entry's return, OFS,
"since MM-DD").

BUILT (build): every card, keyed, with his headshot's path when the library
has one (modules/headshots). Every string passes live_lines_page.clean (the
lore strip; the modal escapes on insertion). RAISES (CardsError) when an input
file is missing -- the builder's own loader would print a warning and carry
on with nothing, which is a made-up "no history".

PUBLISHED (publish_files), never inside the page bundle:
    cards/<sha16>.enc     the card bundle: every card (this season's games);
                          gzip, then AES-GCM
    cards/<sha16>.enc     the modal's script and style (player_card_modal), apart
                          from the cards so they republish only when the code changes
    cards/<sha16>.enc     one per player with earlier seasons: those seasons'
                          games (the bulk of a card; it changes once a season)
    photos/<sha16>.enc    one per headshot
each encrypted by its content (hub_crypto.seal_by_content), so an unchanged
file is byte-identical every run. The page bundle carries the card bundle's
file and key; the card bundle carries each history's and photo's. The page
fetches the bundle on the first tap and a player's history and photo when his
card opens (hub_page's loader; the shell's HUB.cards / part / photo).

PREVIEW (preview_bundle): the same cards in plaintext, every season and the
headshot as a data URI, inside output/hub_preview.html (never published).
"""

from __future__ import annotations

import contextlib
import gzip
import hashlib
import html
import io
import json
import re
import time
from pathlib import Path
from typing import Dict, List, Optional

SCHEMA = 1
CARDS_RELPATH = Path("output") / "hub_cards.json"     # regenerable; not state (the manifest's excluded)
CARD_DIR = "cards"
PHOTO_DIR = "photos"
BUNDLE_VERSION = 1
REQUIRED = ("data/historical/HISTORICAL_PLAYERLOG.json", "data/PLAYERLOG.xlsx", "data/PLAYERLIST.xlsx",
            "config/ROSTERS.json", "config/RECORDS.json", "data/historical/all_drafts.json",
            "data/historical/all_trades.json", "config/TRADES.json", "config/DRAFT_PICK_VALUES.json",
            "config/DRAFT_PICKS_CURRENT.json")
FREE_AGENT = "Free agent"


class CardsError(RuntimeError):
    pass


def clean_text(value) -> str:
    """A card string through live_lines_page.clean (the lore-tag strip, then
    HTML escaping), unescaped again: the modal escapes it when it inserts it,
    so escaping twice would print "&amp;"."""
    from .live_lines_page import clean
    return html.unescape(clean(value))


def _clean_tree(x):
    if isinstance(x, str):
        return clean_text(x)
    if isinstance(x, list):
        return [_clean_tree(v) for v in x]
    if isinstance(x, dict):
        return {k: _clean_tree(v) for k, v in x.items()}
    return x


def strings(x):
    """Every string value in a card (tests: no lore in any card)."""
    if isinstance(x, str):
        yield x
    elif isinstance(x, list):
        for v in x:
            yield from strings(v)
    elif isinstance(x, dict):
        for v in x.values():
            yield from strings(v)


# =============================================================================
# the names the payload shows, and their keys
# =============================================================================

class Keys:
    """Card keys: one per player, his slug; a player's several spellings (an
    accent, Yahoo's "S. Gilgeous-Alexander", a suffix) share one, by the
    PlayerIndex rules. Two different players with one slug RAISE."""

    def __init__(self):
        from .data_loader import PlayerIndex
        self.idx = PlayerIndex()
        self.players: Dict[str, dict] = {}

    def key(self, name: str) -> str:
        from .headshots import player_slug
        name = str(name)
        canon = self.idx.canonical(name)
        if canon is not None:
            return self.idx[canon]
        k = player_slug(name)
        if not k:
            raise CardsError(f"no card key for the name {name!r}")
        if k in self.players:
            raise CardsError(f"two players share the card key {k!r}: {self.players[k]['name']!r} and "
                             f"{name!r}")
        self.idx[name] = k
        self.players[k] = {"name": name}
        return k


_PART_PATTERNS = {
    "add": re.compile(r"^(?:added|claimed) (?P<n>.+)$"),
    "drop": re.compile(r"^dropped (?P<n>.+)$"),
    "il": re.compile(r"^(?P<n>.+) (?:to|off) IL$"),
    "trade": re.compile(r"^(?P<who>.+?) gets (?P<ns>.+)$"),
}


def part_names(part: dict) -> List[str]:
    """The players a moves-feed part names, from its text in the feed's own
    forms (transaction_log.feed_item, move_ledger.feed_item). A part in any
    other form RAISES: a new form must be taught here, not dropped quietly."""
    pat = _PART_PATTERNS.get(part.get("kind"))
    m = pat.match(part["text"]) if pat else None
    if m is None:
        raise CardsError(f"a moves-feed part this module cannot read: {part!r}")
    if part["kind"] == "trade":
        return [n.strip() for n in m.group("ns").split(", ")]
    return [m.group("n")]


def segments(text: str, named: List[tuple]) -> List[dict]:
    """`text` cut into plain pieces {"t"} and the named players {"t", "card"},
    left to right. named: [(name, key)]; every name must occur in the text."""
    out, i = [], 0
    names = sorted({n for n, _ in named}, key=len, reverse=True)
    key_of = dict(named)
    for n in names:
        if n not in text:
            raise CardsError(f"{n!r} is not in {text!r}")
    while i < len(text):
        best = None
        for n in names:
            j = text.find(n, i)
            if j != -1 and (best is None or j < best[0]):
                best = (j, n)
        if best is None:
            out.append({"t": text[i:]})
            break
        j, n = best
        if j > i:
            out.append({"t": text[i:j]})
        out.append({"t": n, "card": key_of[n]})
        i = j + len(n)
    return out


def annotate(payload: dict) -> dict:
    """Give every player name the payload shows a card key (in place) and list
    them in payload["cards"]. Returns payload["cards"]."""
    keys = Keys()
    owner, status, kind, claimed = {}, {}, {}, {}
    for m, rb in payload["rosters"].items():
        for p in rb["players"]:
            k = p["card"] = keys.key(p["name"])
            if k in owner and owner[k] != m:
                raise CardsError(f"{p['name']} is on two rosters ({owner[k]}, {m})")
            owner[k] = m
            status[k] = [{"text": f"{rb['team']} \u00b7 {m}", "kind": "own"}] + \
                [dict(c) for c in p.get("tags") or []]
    for table in (payload["free_agents"]["rows"], payload["stash"]["rows"]):
        for r in table:
            k = r["card"] = keys.key(r["name"])
            if k in owner:
                raise CardsError(f"{r['name']} is listed as a free agent and is on {owner[k]}'s roster")
            status.setdefault(k, [{"text": FREE_AGENT, "kind": "fa"}] + [dict(c) for c in r.get("tags") or []])
    for c in payload["trade_block"]["cards"]:
        for lst in c["lists"]:
            for r in lst["rows"]:
                r["card"] = keys.key(r["name"])
    for w in payload["moves"]["weeks"]:
        for it in w["items"]:
            for x in it["parts"]:
                names = part_names(x)
                x["segs"] = segments(x["text"], [(n, keys.key(n)) for n in names])
                if it.get("kind") == "ledger" and it.get("state") == "Pending" and x["kind"] == "add":
                    for n in names:
                        claimed[keys.key(n)] = it["who"]
    adv = payload.get("advice")
    if adv is not None:
        for c in adv["cards"]:
            pl = c.get("players") or {}
            for fld in ("step", "move", "followup", "backup"):
                named = [(n, keys.key(n)) for n in pl.get(fld) or [] if n in (c.get(fld) or "")]
                if (pl.get(fld) or []) and len(named) != len(pl[fld]):
                    missing = [n for n in pl[fld] if n not in (c.get(fld) or "")]
                    raise CardsError(f"advice for {c['manager']}: {missing} not in its {fld} text")
                if c.get(fld):
                    c[f"{fld}_segs"] = segments(c[fld], named)
    players = {}
    for k, v in keys.players.items():
        if k in owner:
            kd = "rostered"
        elif k in claimed:
            kd = "claimed"
            status[k] = [{"text": f"Claimed by {claimed[k]} in the group chat", "kind": "new"}]
        else:
            kd = "free_agent"
        players[k] = {"name": v["name"], "kind": kd, "manager": owner.get(k, ""),
                      "status": status.get(k) or [{"text": FREE_AGENT, "kind": "fa"}]}
    payload["cards"] = {"players": dict(sorted(players.items()))}
    return payload["cards"]


def strip(payload: dict) -> dict:
    """Undo annotate, in place, whatever part of it ran: no card key beside
    any name, no cut text, no card list -- the payload exactly as it was
    before annotate (tested), so the page shows every name as plain text.
    The cards fail softly (Nick, 11-12): this is the hub without them."""
    for rb in (payload.get("rosters") or {}).values():
        for p in rb["players"]:
            p.pop("card", None)
    for key in ("free_agents", "stash"):
        for r in (payload.get(key) or {}).get("rows") or []:
            r.pop("card", None)
    for c in (payload.get("trade_block") or {}).get("cards") or []:
        for lst in c["lists"]:
            for r in lst["rows"]:
                r.pop("card", None)
    for w in (payload.get("moves") or {}).get("weeks") or []:
        for it in w["items"]:
            for x in it["parts"]:
                x.pop("segs", None)
    adv = payload.get("advice")
    if adv is not None:
        for c in adv["cards"]:
            for fld in ("step", "move", "followup", "backup"):
                c.pop(f"{fld}_segs", None)
    payload["cards"] = None
    return payload


def failure(stage: str, e: BaseException) -> dict:
    """A card failure as the run records it: {"stage": annotate | build |
    preview | publish, "error": "Type: message"}."""
    return {"stage": stage, "error": f"{type(e).__name__}: {e}".splitlines()[0][:500]}


def discard(base_path) -> None:
    """Remove output/hub_cards.json (an earlier run's cards, regenerable):
    after a card failure nothing may reuse them."""
    p = Path(base_path) / CARDS_RELPATH
    if p.is_file():
        p.unlink()


def shown_names(payload: dict) -> List[tuple]:
    """(name, card key) for every player name the page shows in a table or
    list -- the invariant's walk (tests), independent of annotate's."""
    out = []
    for rb in payload["rosters"].values():
        out += [(p["name"], p.get("card")) for p in rb["players"]]
    out += [(r["name"], r.get("card")) for r in payload["free_agents"]["rows"] + payload["stash"]["rows"]]
    for c in payload["trade_block"]["cards"]:
        for lst in c["lists"]:
            out += [(r["name"], r.get("card")) for r in lst["rows"]]
    for w in payload["moves"]["weeks"]:
        for it in w["items"]:
            for x in it["parts"]:
                segs = x.get("segs") or []
                got = [s for s in segs if s.get("card")]
                for n in part_names(x):
                    hit = [s for s in got if s["t"] == n]
                    out.append((n, hit[0]["card"] if hit else None))
    adv = payload.get("advice")
    if adv is not None:
        for c in adv["cards"]:
            for fld, names in (c.get("players") or {}).items():
                segs = c.get(f"{fld}_segs") or []
                for n in names:
                    hit = [s for s in segs if s.get("t") == n and s.get("card")]
                    out.append((n, hit[0]["card"] if hit else None))
    return out


# =============================================================================
# building the cards
# =============================================================================

def build(base_path, payload: dict, *, data=None, keeper_watch=None, echo=print) -> dict:
    """Every card the payload names, built by player_card_builder from this
    folder's data. keeper_watch: the run's keepability v3 (hub_state.build
    computed it; computed here otherwise, for the payload's report week)."""
    from .player_card_builder import build_player_cards
    from . import headshots
    base = Path(base_path)
    t0 = time.perf_counter()
    reg = (payload.get("cards") or {}).get("players")
    if reg is None:
        raise CardsError("the payload lists no cards (hub_cards.annotate): rebuild it with "
                         "python scripts/build_hub_state.py")
    missing = [r for r in REQUIRED if not (base / r).is_file()]
    if missing:
        raise CardsError(f"the player cards need {', '.join(missing)}: missing")
    if keeper_watch is None:
        from . import keepability_v3 as kv3
        from .data_loader import load_all_data
        data = data or load_all_data(base, current_week=None)
        keeper_watch = kv3.keeper_watch(data, int(payload["week"]) - 1, root=base)
    kw_rows = list(keeper_watch["players"])
    kw_of = {(r["manager"], r["player_name"]): r for r in kw_rows}
    rostered = {k: v for k, v in reg.items() if v["kind"] == "rostered"}
    for k, v in rostered.items():
        if (v["manager"], v["name"]) not in kw_of:
            raise CardsError(f"keepability v3 has no row for {v['name']} ({v['manager']}): the card's "
                             "keep chance and season numbers come from it")
    shown = {(v["manager"], v["name"]) for v in rostered.values()}
    unshown = [f"{n} ({m})" for (m, n) in kw_of if (m, n) not in shown]
    if unshown:
        raise CardsError(f"rostered but not on the hub's rosters: {', '.join(unshown)}")
    extras = [{"player_name": v["name"], "manager": ""} for k, v in reg.items() if v["kind"] != "rostered"]
    nba = nba_lines(base, payload, kw_rows, extras)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        built = build_player_cards(kw_rows, base / "data", base / "config", base / "data" / "historical",
                                   extra_players=extras, nba=nba)
    by_name = {c["player_name"]: c for c in built}
    try:
        lib = headshots.library(base)
    except headshots.HeadshotError as e:
        raise CardsError(str(e)) from None
    cards, photos = {}, {}
    for k, v in reg.items():
        c = by_name.get(v["name"])
        if c is None:
            raise CardsError(f"no card was built for {v['name']}")
        c = dict(c, status=[dict(x) for x in v["status"]], card=k)
        cards[k] = _clean_tree(c)
        f = headshots.find(v["name"], lib)
        if f is not None:
            photos[k] = (headshots.LIB_RELDIR / f.name).as_posix()
    from .live_lines_page import LORE_TAG
    for k, c in cards.items():
        for s in strings(c):
            if LORE_TAG.search(s) or "<!--" in s:
                raise CardsError(f"lore in {k}'s card")
    secs = round(time.perf_counter() - t0, 2)
    return {"schema": SCHEMA, "generated_at": payload["generated_at"],
            "engine": (payload.get("engine") or {}).get("key"), "seconds": secs,
            "cards": cards, "photos": photos}


def nba_lines(base_path, payload: dict, kw_rows, extras) -> dict:
    """The cards' season numbers (ONE FPPG EVERYWHERE, 11-12): every card
    player's NBA season through the day the roster table's actuals run to
    (payload sources.actuals_through), from the same cache
    (player_actuals.card_lines). A rostered player must be covered (his row
    already is); anyone else is covered when the cache has his every day, and
    otherwise gets the note: "fetched from tonight" (40b: the actuals step
    fetches every name the previous hub showed), or, for a player with no
    Yahoo id by the engine's one rule (player_actuals.extra_ids), why."""
    from datetime import date
    from . import player_actuals as pa
    through = (payload.get("sources") or {}).get("actuals_through")
    if not through:
        raise CardsError("the payload names no actuals_through date: the cards' NBA numbers run to it")
    try:
        blob = pa.load(base_path)
        _ids, no_id = pa.extra_ids(base_path, [x["player_name"] for x in extras]) if extras else ({}, [])
        return pa.card_lines(blob, [r["player_name"] for r in kw_rows] + [x["player_name"] for x in extras],
                             date.fromisoformat(through), required=[r["player_name"] for r in kw_rows],
                             no_id=no_id)
    except pa.ActualsError as e:
        raise CardsError(str(e)) from None


def write(base_path, obj: dict) -> Path:
    from .data_loader import atomic_write_json
    p = Path(base_path) / CARDS_RELPATH
    atomic_write_json(p, obj, indent=None)
    return p


def load_for(base_path, payload: dict) -> Optional[dict]:
    """output/hub_cards.json when it was built for this payload, else None."""
    p = Path(base_path) / CARDS_RELPATH
    if not p.is_file():
        return None
    obj = json.loads(p.read_text(encoding="utf-8"))
    if obj.get("schema") != SCHEMA or obj.get("generated_at") != payload["generated_at"] \
            or obj.get("engine") != (payload.get("engine") or {}).get("key"):
        return None
    return obj


def check_against(payload: dict, obj: dict) -> None:
    """Every key the payload lists has a card, and no card is extra."""
    want = set(((payload.get("cards") or {}).get("players") or {}))
    have = set(obj["cards"])
    if want != have:
        raise CardsError(f"the cards do not match the payload: missing {sorted(want - have)[:5]}, "
                         f"extra {sorted(have - want)[:5]}")


def coverage(base_path, payload: dict) -> dict:
    """{"with", "rostered"}: rostered players with a headshot (the nightly's line)."""
    from . import headshots
    lib = headshots.library(base_path)
    names = [p["name"] for rb in payload["rosters"].values() for p in rb["players"]]
    n, of = headshots.coverage(names, lib)
    return {"with": n, "rostered": of, "library": len(lib)}


# =============================================================================
# the files
# =============================================================================

def _current_season() -> str:
    from .data_loader import CURRENT_SEASON
    return CURRENT_SEASON


def split(card: dict) -> tuple:
    """(the card with this season's games only, the earlier seasons' games)."""
    cur = _current_season()
    sp = card.get("sparkline") or []
    return dict(card, sparkline=[g for g in sp if g["season"] == cur]), [g for g in sp if g["season"] != cur]


def _gz(obj) -> bytes:
    raw = json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return gzip.compress(raw, compresslevel=9, mtime=0)


def modal_assets() -> dict:
    from .player_card_modal import get_player_card_css, get_player_card_js
    return {"css": get_player_card_css(), "js": get_player_card_js()}


def publish_files(base_path, obj: dict, root_key: bytes, terms=()) -> tuple:
    """({relative path: bytes}, the card bundle's {"file", "key"}). root_key:
    the page key (hub_crypto.derive_key of the passphrase and the hub salt)."""
    from . import hub_crypto
    base = Path(base_path)
    K = hub_crypto.subkey(root_key, hub_crypto.CARDS_INFO)
    files = {}

    def put(dirname: str, plaintext: bytes) -> dict:
        k, blob = hub_crypto.seal_by_content(K, plaintext, terms)
        rel = f"{dirname}/{hashlib.sha256(blob).hexdigest()[:16]}.enc"
        files[rel] = blob
        return {"file": rel, "key": hub_crypto.b64(k)}

    out = {}
    for key in sorted(obj["cards"]):
        live, prior = split(obj["cards"][key])
        live["hist"] = put(CARD_DIR, _gz(prior)) if prior else None
        p = obj["photos"].get(key)
        live["photo"] = put(PHOTO_DIR, (base / p).read_bytes()) if p else None
        out[key] = live
    code = put(CARD_DIR, _gz(modal_assets()))
    ref = put(CARD_DIR, _gz({"v": BUNDLE_VERSION, "code": code, "cards": out}))
    return files, ref


def preview_bundle(base_path, obj: dict) -> dict:
    """The plaintext preview's cards: every season, the headshot as a data URI."""
    from . import headshots
    base = Path(base_path)
    cards = {}
    for key, c in obj["cards"].items():
        c = dict(c, hist=None)
        p = obj["photos"].get(key)
        c["photo"] = headshots.data_uri(base / p) if p else None
        cards[key] = c
    return dict(modal_assets(), v=BUNDLE_VERSION, cards=cards)
