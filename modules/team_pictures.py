"""
team_pictures.py -- each team's current Yahoo picture (HUB_REDESIGN_BRIEF s.8;
claude/HANDOFF_4C3_MARKET_ADVICE_2026-11-18.md s.3).

THE NIGHTLY FETCHES IT. The nightly run's "team_pictures" step reads the
league's teams (yahoo_fantasy_api's League.teams(): {team_key: {"name",
"team_logos": [{"team_logo": {"size", "url"}}], ...}}, the shape the roster
sync and the injury fetch already read), maps each team to its manager BY
TEAM KEY (data_loader.manager_for_team), downloads the logo, and stores it:

    output/team_pictures/<sha16>.jpg     the picture, downscaled with Pillow to
                                         PX (TeamMark 72 at 2x = 144 px),
                                         centre-cropped square, JPEG; the name
                                         is the first 16 hex of its own SHA-256
    output/team_pictures/index.json      {"schema", "fetched_at", "teams":
                                         {manager: {"file", "sha", "mime", "px",
                                         "bytes", "url", "fetched_at",
                                         "changed_at"}}, "failures": {manager:
                                         why}}

CACHED BY CONTENT: an unchanged picture is the same file (nothing written);
a changed one is a new file, the index points at it, and the old file is
removed, so the hub shows the new picture from the next build (the next
day). Four small files, never more: anything in the folder the index does not
name is removed.

A FAILURE IS SOFT, like the player cards: the step never stops the run. A
team whose picture cannot be fetched or read is recorded in the index's
"failures" and the run row's "team_pictures" block (TEAM PICTURES FAILED in
the summary); its last good picture stays in the index (it is still the
manager's own picture, a day older) -- or, when there is none, the hub shows
the monogram in the manager's colour, never a broken image. A team Yahoo
lists with no picture at all loses its stored one: the monogram shows.

PRIVATE: the pictures are the managers' own images. They are league state
(config/STATE_MANIFEST.json, ignored by the public repo), reach the page only
inside the encrypted hub (data URIs in the bundle; the plaintext scan covers
them), and never appear in a test: tests make their images in memory.

Without Pillow the picture is stored as downloaded (a JPEG, PNG, GIF or WebP
by its first bytes, at most MAX_BYTES), not downscaled, and the index and the
run row say so (px null; "NOT downscaled" on the step's line). Pillow is not
in requirements.txt (task 40a's rule: tests/test_player_cards.py pins it); the
runner has it as matplotlib's own dependency.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

DIR = Path("output") / "team_pictures"
INDEX = DIR / "index.json"
SCHEMA = 1
PX = 144                        # TeamMark's largest (72) at 2x
QUALITY = 85
MAX_BYTES = 2_000_000           # a download larger than this is refused
MIME_OF = ((b"\xff\xd8\xff", "image/jpeg"), (b"\x89PNG", "image/png"), (b"GIF8", "image/gif"))


class PictureError(RuntimeError):
    pass


# =============================================================================
# reading Yahoo's answer
# =============================================================================

def logo_urls(teams_json: dict, manager_of: Callable = None) -> dict:
    """{manager: logo URL} from League.teams(). The "large" logo when Yahoo
    lists sizes, else the first. A team with no logo is left out (its
    monogram shows); a team that maps to no manager RAISES (manager_for_team)."""
    if manager_of is None:
        from .data_loader import manager_for_team as manager_of
    out = {}
    for key, t in (teams_json or {}).items():
        m = manager_of(t.get("name"), team_key=t.get("team_key") or key)
        logos = []
        for e in t.get("team_logos") or []:
            lg = e.get("team_logo") if isinstance(e, dict) else None
            if isinstance(lg, dict) and lg.get("url"):
                logos.append(lg)
        if not logos:
            continue
        best = next((x for x in logos if x.get("size") == "large"), logos[0])
        url = str(best["url"])
        if url.startswith("http://"):
            url = "https://" + url[len("http://"):]
        out[m] = url
    return out


# =============================================================================
# the picture
# =============================================================================

def _sniff(raw: bytes) -> Optional[str]:
    for magic, mime in MIME_OF:
        if raw.startswith(magic):
            return mime
    if raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        return "image/webp"
    return None


def process(raw: bytes) -> dict:
    """{"data", "mime", "px", "downscaled"}: the picture as the hub keeps it.
    With Pillow: centre square crop, PX px (smaller sources are not
    enlarged), RGB on white, JPEG. Without: the bytes as they are. RAISES
    PictureError on anything that is not an image."""
    if not raw:
        raise PictureError("an empty download")
    if len(raw) > MAX_BYTES:
        raise PictureError(f"a {len(raw):,}-byte download, more than {MAX_BYTES:,}")
    try:
        from PIL import Image, ImageOps
    except ImportError:
        mime = _sniff(raw)
        if mime is None:
            raise PictureError("not a JPEG, PNG, GIF or WebP image (and Pillow is not installed)") from None
        return {"data": raw, "mime": mime, "px": None, "downscaled": False}
    try:
        im = Image.open(io.BytesIO(raw))
        im.load()
    except Exception as e:                                   # noqa: BLE001 -- any unreadable image
        raise PictureError(f"not an image Pillow can read ({type(e).__name__})") from None
    im = ImageOps.exif_transpose(im)
    if im.mode in ("RGBA", "LA", "PA") or (im.mode == "P" and "transparency" in im.info):
        im = im.convert("RGBA")
        bg = Image.new("RGB", im.size, (255, 255, 255))
        bg.paste(im, mask=im.split()[-1])
        im = bg
    else:
        im = im.convert("RGB")
    w, h = im.size
    side = min(w, h)
    left, top = (w - side) // 2, (h - side) // 2
    im = im.crop((left, top, left + side, top + side))
    px = min(PX, side)
    if px != side:
        im = im.resize((px, px), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=QUALITY, optimize=True)
    return {"data": buf.getvalue(), "mime": "image/jpeg", "px": px, "downscaled": True}


EXT = {"image/jpeg": "jpg", "image/png": "png", "image/gif": "gif", "image/webp": "webp"}


def load_index(base) -> dict:
    p = Path(base) / INDEX
    if not p.is_file():
        return {"schema": SCHEMA, "fetched_at": None, "teams": {}, "failures": {}}
    blob = json.loads(p.read_text(encoding="utf-8"))
    if blob.get("schema") != SCHEMA:
        raise PictureError(f"{INDEX.as_posix()} is schema {blob.get('schema')}, not {SCHEMA}")
    return blob


def _write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    tmp.replace(path)


def store(base, managers, urls: dict, get_bytes: Callable, now: datetime) -> dict:
    """Fetch, process and store each manager's picture; write the index; remove
    files the index no longer names. Returns the run row's block: {"teams":
    {m: {"sha", "bytes", "changed"}}, "failures": {m: why}, "downscaled",
    "seconds"}. Never raises for one team's picture (recorded instead)."""
    t0 = time.perf_counter()
    base = Path(base)
    idx = load_index(base)
    teams, failures, block = dict(idx.get("teams") or {}), {}, {"teams": {}, "failures": {}}
    downscaled = True
    stamp = now.isoformat(timespec="seconds")
    for m in managers:
        url = urls.get(m)
        if url is None:                              # no picture on Yahoo now: the monogram shows
            teams.pop(m, None)
            block["teams"][m] = {"sha": None, "bytes": 0, "changed": False, "none": True}
            continue
        try:
            pic = process(get_bytes(url))
            sha = hashlib.sha256(pic["data"]).hexdigest()
            name = f"{sha[:16]}.{EXT[pic['mime']]}"
            path = base / DIR / name
            if not path.is_file():
                _write(path, pic["data"])
            old = teams.get(m) or {}
            changed = old.get("sha") != sha
            teams[m] = {"file": name, "sha": sha, "mime": pic["mime"], "px": pic["px"],
                        "bytes": len(pic["data"]), "url": url, "fetched_at": stamp,
                        "changed_at": stamp if changed else old.get("changed_at", stamp)}
            downscaled = downscaled and pic["downscaled"]
            block["teams"][m] = {"sha": sha[:16], "bytes": len(pic["data"]), "changed": changed}
        except Exception as e:                       # noqa: BLE001 -- one team's picture never stops the run
            failures[m] = f"{type(e).__name__}: {e}".splitlines()[0][:200]
    teams = {m: v for m, v in teams.items() if m in set(managers)}
    out = {"schema": SCHEMA, "fetched_at": stamp, "teams": teams, "failures": failures}
    _write(base / INDEX, (json.dumps(out, indent=1, sort_keys=True) + "\n").encode("utf-8"))
    keep = {v["file"] for v in teams.values()} | {INDEX.name}
    for p in (base / DIR).iterdir():
        if p.is_file() and p.name not in keep:
            p.unlink()
    block.update(failures=failures, downscaled=downscaled, kept=sorted(m for m in failures if m in teams),
                 seconds=round(time.perf_counter() - t0, 2))
    return block


def http_get(url: str, timeout: float = 20.0) -> bytes:
    """The download (the nightly's; tests pass their own getter)."""
    import requests
    if not url.startswith("https://"):
        raise PictureError(f"not an https URL: {url[:60]}")
    r = requests.get(url, timeout=timeout, stream=True)
    if r.status_code != 200:
        raise PictureError(f"HTTP {r.status_code}")
    data = r.raw.read(MAX_BYTES + 1, decode_content=True)
    return data


def fetch(base, managers, teams_json: dict, *, now: datetime, get_bytes: Callable = None,
          manager_of: Callable = None) -> dict:
    """The nightly step's work: logo_urls, then store. RAISES only when the
    teams cannot be read at all (the step records that softly)."""
    urls = logo_urls(teams_json, manager_of=manager_of)
    return store(base, managers, urls, get_bytes or http_get, now)


# =============================================================================
# the hub's side
# =============================================================================

def scan_terms(base) -> list:
    """The plaintext scan's terms for the stored pictures: a 48-character
    slice of each one's base64 (past the format's common header), the form a
    page would carry it in. [] when none is stored."""
    out = []
    try:
        idx = load_index(base)
    except Exception:                                # noqa: BLE001 -- nothing stored readably
        return out
    for v in (idx.get("teams") or {}).values():
        try:
            data = (Path(base) / DIR / v["file"]).read_bytes()
        except OSError:
            continue
        b64 = base64.b64encode(data).decode("ascii")
        if len(b64) >= 160:
            out.append(b64[96:144])
    return out


def data_uris(base, managers) -> tuple:
    """({manager: "data:image/jpeg;base64,..."}, notes): every manager with a
    stored picture whose file is there and matches its SHA-256. Anything else
    is left out (his monogram shows) and noted. Never raises: the hub must
    not fail over a picture."""
    out, notes = {}, []
    try:
        idx = load_index(base)
    except Exception as e:                           # noqa: BLE001 -- the monograms show instead
        return {}, [f"{INDEX.as_posix()}: {type(e).__name__}: {e}"]
    for m in managers:
        v = (idx.get("teams") or {}).get(m)
        if not v:
            continue
        p = Path(base) / DIR / v["file"]
        try:
            data = p.read_bytes()
        except OSError:
            notes.append(f"{m}: {v['file']} is missing")
            continue
        if hashlib.sha256(data).hexdigest() != v["sha"]:
            notes.append(f"{m}: {v['file']} does not match its SHA-256")
            continue
        out[m] = f"data:{v['mime']};base64," + base64.b64encode(data).decode("ascii")
    return out, notes
