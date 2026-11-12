"""
headshots.py -- the league's one headshot library (task 40a; Nick, 11-07 and 11-12).

    assets/headshots/<player-slug>.webp          (private state, the manifest)

One photo per player, used by the hub's player cards, the newsletter's Keeper
Watch cards and the Player of the Week. The old per-week folder assets/potw/
is retired: POTW reads this library.

NICK SUPPLIES EVERY PHOTO. Nothing here, or anywhere in the engine, fetches,
links or downloads a player photo from the web (a standing rule). Photos come
in through scripts/headshots.py (add, add-folder), which normalises them.

THE SLUG (player_slug) is the rule POTW has used since 10-30: accents
stripped, lowercase, every run of other characters one hyphen.
"Luka Don\u010di\u0107" -> "luka-doncic", "De'Aaron Fox" -> "de-aaron-fox",
"Jabari Smith Jr." -> "jabari-smith-jr". It is the one slug rule: the
newsletter generator imports it from here (a source pin).

NORMALISED: a square crop centred on the image, SIZE x SIZE pixels, WebP at
QUALITY, alpha kept. 320 px is twice the largest place a headshot is shown
(the newsletter's Player of the Week photo, 150 CSS px, at 2x density); the
hub's card shows it smaller. Typical file: 10-25 KB. Pillow does the
normalising and is needed ONLY when Nick adds a photo (scripts/headshots.py,
on his desk); the cloud runner never imports it -- reading the library is
plain file I/O.

FINDING A PLAYER'S PHOTO (find): his slug's file, else the one library file
whose name the hub's PlayerIndex rules match to him (an accent, a suffix, Yahoo's
"S. Gilgeous-Alexander"); two matches is no match. Never another player's
photo, and no photo is no photo: the pages show no image and no frame.

A FILE THAT IS NOT A SLUG .webp in the library RAISES (HeadshotError): the
library holds only what scripts/headshots.py writes. Windows' and macOS's own
folder files (Thumbs.db, desktop.ini, dot-files) are ignored.
"""

from __future__ import annotations

import difflib
import io
import json
import re
import unicodedata
from pathlib import Path
from typing import Dict, List, Optional

LIB_RELDIR = Path("assets") / "headshots"
EXT = ".webp"
MIME = "image/webp"
SIZE = 320
QUALITY = 80
MIN_SOURCE = 120                     # px on the short side: smaller than this is refused
IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff")
IGNORED = ("thumbs.db", "desktop.ini")
SLUG_FILE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*\.webp$")
PUSH_HINT = "Then run: python scripts\\state.py push"


class HeadshotError(RuntimeError):
    pass


class UnknownPlayer(HeadshotError):
    pass


class AmbiguousPlayer(HeadshotError):
    pass


def player_slug(name: str) -> str:
    """"Luka Don\u010di\u0107" -> "luka-doncic": accents stripped, lowercase,
    every run of other characters one hyphen. The ONE slug rule (POTW, the
    hub's cards and the newsletter's cards)."""
    text = unicodedata.normalize("NFKD", str(name or "")).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def lib_dir(base_path=".") -> Path:
    return Path(base_path) / LIB_RELDIR


def _ignored(p: Path) -> bool:
    return p.name.startswith(".") or p.name.lower() in IGNORED


def library(base_path=".", lib: Path = None) -> Dict[str, Path]:
    """{slug: path} of every photo. No folder: an empty library. A file that
    is not <slug>.webp RAISES."""
    d = Path(lib) if lib is not None else lib_dir(base_path)
    if not d.exists():
        return {}
    if not d.is_dir():
        raise HeadshotError(f"{d} is not a folder")
    out, bad = {}, []
    for p in sorted(d.iterdir()):
        if _ignored(p):
            continue
        if p.is_dir() or not SLUG_FILE.match(p.name):
            bad.append(p.name)
            continue
        out[p.stem] = p
    if bad:
        raise HeadshotError(f"{LIB_RELDIR.as_posix()} holds file(s) that are not <player-slug>.webp: {bad}. "
                            "The library holds only what scripts/headshots.py writes: add a photo with "
                            "python scripts\\headshots.py add <file> \"<Player Name>\" and move the "
                            "others out")
    return out


def _stem_index(lib: Dict[str, Path]):
    from .data_loader import PlayerIndex
    return PlayerIndex({slug.replace("-", " "): path for slug, path in lib.items()})


def find(name: str, lib: Dict[str, Path]) -> Optional[Path]:
    """His photo, or None. His slug's file first; else the one file the
    PlayerIndex rules match to him (ambiguous: none). Never another player's."""
    if not name:
        return None
    hit = lib.get(player_slug(name))
    if hit is not None:
        return hit
    return _stem_index(lib).get(str(name))


def data_uri(path: Path) -> str:
    import base64
    return f"data:{MIME};base64," + base64.b64encode(Path(path).read_bytes()).decode("ascii")


def coverage(names, lib: Dict[str, Path]) -> tuple:
    """(with a photo, of all) for a list of names."""
    names = list(names)
    return sum(1 for n in names if find(n, lib) is not None), len(names)


# =============================================================================
# known players: whom a photo can be added for
# =============================================================================

def known_players(base_path=".") -> List[str]:
    """Every player the engine knows by name: the rosters (config/ROSTERS.json),
    Yahoo's list (data/PLAYERLIST.xlsx), this season's log (data/PLAYERLOG.xlsx)
    and every player the hub's payload names (output/hub_state.json's cards).
    Spellings as each file has them."""
    base = Path(base_path)
    names = set()
    rp = base / "config" / "ROSTERS.json"
    if rp.is_file():
        for v in (json.loads(rp.read_text(encoding="utf-8")).get("rosters") or {}).values():
            names.update(str(n) for n in v)
    import pandas as pd
    for rel in ("data/PLAYERLIST.xlsx", "data/PLAYERLOG.xlsx"):
        p = base / rel
        if p.is_file():
            names.update(str(n) for n in pd.read_excel(p, usecols=["player_name"])["player_name"].dropna())
    hp = base / "output" / "hub_state.json"
    if hp.is_file():
        cards = (json.loads(hp.read_text(encoding="utf-8")).get("cards") or {}).get("players") or {}
        names.update(str(v["name"]) for v in cards.values())
    if not names:
        raise HeadshotError("no known players: config/ROSTERS.json and data/PLAYERLIST.xlsx are both "
                            "missing (python scripts\\state.py pull first)")
    return sorted(names)


def _initial_form(n: str) -> bool:
    return bool(re.match(r"^[A-Za-z]\.?\s", n))


def preferred_spelling(spellings) -> str:
    """Of one player's spellings, the one his slug is made from: not Yahoo's
    initial form ("S. Gilgeous-Alexander"), then the longest (a suffix kept),
    then the first alphabetically."""
    full = [s for s in spellings if not _initial_form(s)] or list(spellings)
    return sorted(full, key=lambda s: (-len(s), s))[0]


def players_by_spelling(known):
    """{one spelling: [every spelling of that player]}: the known names grouped
    into players by the PlayerIndex rules (an accent, a suffix, Yahoo's initial)."""
    from .data_loader import PlayerIndex
    g = PlayerIndex()
    for k in known:
        c = g.canonical(k)
        if c is None:
            g[k] = [k]
        elif k not in g[c]:
            g[c].append(k)
    return g


def resolve(name: str, known) -> str:
    """The known player `name` means, under the hub's PlayerIndex rules, as his
    preferred spelling. Unknown or ambiguous RAISES, listing the near matches."""
    from .data_loader import PlayerIndex
    groups = players_by_spelling(list(known))
    hit = groups.canonical(name)
    if hit is not None:
        spellings = list(groups[hit])
        if name not in spellings:
            spellings.append(name)              # the spelling Nick typed is one of his, too
        return preferred_spelling(spellings)
    # a miss: ambiguous (two players fit) or unknown (none does)
    fits = [preferred_spelling(v) for k, v in dict.items(groups)
            if PlayerIndex({s: s for s in v}).canonical(name) is not None]
    if len(fits) > 1:
        raise AmbiguousPlayer(f"'{name}' could be {', '.join(sorted(fits))}: write the full name")
    by_lower = {str(k).lower(): preferred_spelling(v) for k, v in dict.items(groups)}
    near = [by_lower[h] for h in difflib.get_close_matches(str(name).lower(), list(by_lower), n=5, cutoff=0.6)]
    raise UnknownPlayer(f"'{name}' is not a player the engine knows (the rosters, Yahoo's player list, "
                        f"this season's log, the hub's names)"
                        + (f"; near matches: {', '.join(near)}" if near else "; no near match"))


# =============================================================================
# adding (Nick's desk; Pillow)
# =============================================================================

def normalise(src) -> bytes:
    """The library's form of an image file: centred square crop, SIZE px, WebP."""
    try:
        from PIL import Image, ImageOps
    except ImportError:
        raise HeadshotError("Pillow is not installed, and adding a photo needs it to crop and resize: "
                            "run  python -m pip install pillow  and try again") from None
    try:
        im = Image.open(src)
        im.load()
    except Exception as e:                                    # noqa: BLE001 -- any unreadable image
        raise HeadshotError(f"{Path(str(src)).name} is not an image Pillow can read ({type(e).__name__})") from None
    im = ImageOps.exif_transpose(im)
    alpha = im.mode in ("RGBA", "LA", "PA") or (im.mode == "P" and "transparency" in im.info)
    im = im.convert("RGBA" if alpha else "RGB")
    w, h = im.size
    side = min(w, h)
    if side < MIN_SOURCE:
        raise HeadshotError(f"{Path(str(src)).name} is {w}x{h}: at least {MIN_SOURCE} px on the short side "
                            "is needed (a bigger photo, please)")
    left, top = (w - side) // 2, (h - side) // 2
    im = im.crop((left, top, left + side, top + side)).resize((SIZE, SIZE), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "WEBP", quality=QUALITY, method=6)
    return buf.getvalue()


def _write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    tmp.replace(path)


def add(base_path, src, name: str, *, replace: bool = False, known=None) -> dict:
    """Normalise `src` into the library as `name`'s photo.
    {"status": "added" | "replaced" | "already there", "player", "path", "bytes", "removed"}.
    Never overwrites without replace. Unknown or ambiguous names RAISE."""
    base = Path(base_path)
    src = Path(src)
    if not src.is_file():
        raise HeadshotError(f"{src} is not a file")
    player = resolve(name, known if known is not None else known_players(base))
    lib = library(base)
    slug = player_slug(player)
    target = lib_dir(base) / f"{slug}{EXT}"
    have = find(player, lib)
    if have is not None and not replace:
        return {"status": "already there", "player": player, "path": have, "bytes": have.stat().st_size,
                "removed": None}
    data = normalise(src)
    _write(target, data)
    removed = None
    if have is not None and have.resolve() != target.resolve():
        have.unlink()                                  # the same player under an older spelling
        removed = have
    return {"status": "replaced" if have is not None else "added", "player": player, "path": target,
            "bytes": len(data), "removed": removed}


def name_from_file(p: Path) -> str:
    """A bulk-drop file's player: its name without the extension, hyphens and
    underscores read as spaces ("victor-wembanyama.png", "Victor Wembanyama.jpg")."""
    return re.sub(r"[_\-]+", " ", p.stem).strip()


def add_folder(base_path, folder, *, replace: bool = False) -> List[dict]:
    """add() for every image in `folder` (not below it), each reported:
    added, replaced, already there, unknown name, ambiguous, or not an image."""
    base = Path(base_path)
    folder = Path(folder)
    if not folder.is_dir():
        raise HeadshotError(f"{folder} is not a folder")
    known = known_players(base)
    out = []
    for p in sorted(folder.iterdir()):
        if p.is_dir() or _ignored(p):
            continue
        row = {"file": p.name, "name": name_from_file(p)}
        if p.suffix.lower() not in IMAGE_EXTS:
            out.append(dict(row, status="not an image", detail=f"not one of {', '.join(IMAGE_EXTS)}"))
            continue
        try:
            r = add(base, p, row["name"], replace=replace, known=known)
            out.append(dict(row, status=r["status"], player=r["player"], path=r["path"], bytes=r["bytes"],
                            detail=(f"replaced {r['removed'].name}" if r["removed"] else "")))
        except AmbiguousPlayer as e:
            out.append(dict(row, status="ambiguous", detail=str(e)))
        except UnknownPlayer as e:
            out.append(dict(row, status="unknown name", detail=str(e)))
        except HeadshotError as e:
            out.append(dict(row, status="not an image", detail=str(e)))
    return out


# =============================================================================
# who is missing
# =============================================================================

def missing(base_path=".") -> dict:
    """Who has no photo: rostered players first, by team (the config's manager
    order), then the free agents the hub lists (its free-agent and stash
    tables, in that order). Rosters from config/ROSTERS.json; the hub's lists
    from output/hub_state.json (RAISES if missing: python scripts\\state.py pull)."""
    from .data_loader import MANAGERS, MANAGER_TO_TEAM
    base = Path(base_path)
    lib = library(base)
    rp = base / "config" / "ROSTERS.json"
    if not rp.is_file():
        raise HeadshotError("config/ROSTERS.json is missing: python scripts\\state.py pull first")
    rosters = json.loads(rp.read_text(encoding="utf-8")).get("rosters") or {}
    hp = base / "output" / "hub_state.json"
    if not hp.is_file():
        raise HeadshotError("output/hub_state.json is missing: python scripts\\state.py pull first")
    payload = json.loads(hp.read_text(encoding="utf-8"))
    teams, n_ro, have_ro = [], 0, 0
    rostered = set()
    for m in MANAGERS:
        names = list(rosters.get(m) or [])
        rostered.update(names)
        miss = [n for n in names if find(n, lib) is None]
        n_ro += len(names)
        have_ro += len(names) - len(miss)
        teams.append({"manager": m, "team": MANAGER_TO_TEAM.get(m, m), "missing": miss, "of": len(names)})
    fa = []
    for r in list(payload["free_agents"]["rows"]) + list(payload["stash"]["rows"]):
        if r["name"] not in fa and r["name"] not in rostered:
            fa.append(r["name"])
    fa_miss = [n for n in fa if find(n, lib) is None]
    return {"teams": teams, "rostered": n_ro, "rostered_with": have_ro,
            "free_agents": fa, "free_agents_missing": fa_miss, "library": len(lib)}


def attach_data_uris(cards: list, base_path=".") -> int:
    """The newsletter's Keeper Watch cards: card["photo"] = the library photo
    as a data URI, for each card that has one; the rest get no "photo" key
    (the modal then draws no image and no frame). Returns how many."""
    lib = library(base_path)
    n = 0
    for c in cards:
        f = find(c["player_name"], lib)
        if f is not None:
            c["photo"] = data_uri(f)
            n += 1
    return n
