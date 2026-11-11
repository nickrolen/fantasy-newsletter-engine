"""
nba_injury_report.py -- the NBA's official injury report, read, stored, applied
(step 3b, s.4; claude/HANDOFF_STEP3B_TAG_FRESHNESS_2026-11-10.md; Nick, 11-10).

NICK'S RULE: "Out" on the NBA report counts as out for that game right away,
and it is flagged so he can fix a problem.

THE SOURCE. The league office files a per-game report (by 5 PM local the day
before, with game-day updates) as a PDF every 15 minutes:
    https://ak-static.cms.nba.com/referee/injury/Injury-Report_2026-11-10_05_00PM.pdf
The name is the filing time on the NBA's clock (US Eastern). The season's index
page (official.nba.com, config live_refresh.nba_report.index_url) links the
latest ones; when it cannot be read, the latest is found by trying the last
probe_steps filing times. Checked 11-10 from Nick's VM and from Anthropic's
cloud (both 200); GitHub's runners were NOT checked (the builder may not touch
GitHub): the first cloud run is that check, and a refusal there is "NBA report
unavailable", never a stopped run.

READING IT. pypdf (pure Python, pinned in requirements.txt) gives every text
fragment with its position; the table is rebuilt by column from the header
row's x positions (Game Date, Game Time, Matchup, Team, Player Name, Current
Status, Reason). Blank cells carry down (a team's second player has no team
cell). A reason that wraps leaves lines with only reason text, centred around the
player's own line; those parts are dropped (a reason decides nothing), and
"reason" is what sits on the player's line. A status outside
STATUSES, or a page with no header and none before it, is UNREADABLE: the
format changed, and nothing from that report is used.

STORED (output/nba_injury_reports.jsonl, league state, append-only): one row
per read, by the nightly run, the afternoon check and Monday's pre-tip runs:
{"schema", "run_id", "mode", "read_at", "outcome": "ok"|"unavailable"|
"unreadable", "url", "filed_at" (Eastern, with offset), "sha256", "entries"
[{"game_date", "game_time", "matchup", "team", "name" (as printed: "Last,
First"), "player" (First Last), "status", "reason"}], "not_submitted" [teams],
"reason" (why unavailable/unreadable), "same_as" (an unchanged report: the run
whose row holds its entries; entries omitted)}.

WHAT "OUT" DOES (assess): for a ROSTERED player the report has Out in a game on
the run's league day ("tonight"):
  - his Yahoo tag is O or OFS, or an injury entry keeps him out that day:
    nothing changes (the tag or the entry already covers it);
  - otherwise he is a CERTAIN MISS of that one game: Tags.nba_outs
    {player: day}, which the line, the title odds (its week in progress) and
    the closing line read through the tags, and the grid shows. A Q or D tag's
    chain then continues as if that game was missed (absence.missed_distribution
    conditioned on it; simulator_betting.tag_blocks); no tag misses that game
    only. It never writes an injury entry: the report has no return dates.
Tomorrow's games on the same report are not applied tonight: tomorrow's runs
read the report again.

FLAGS (flags_and_notes): every rostered player the report has Out tonight where
Yahoo has no O/OFS -- a hub note, a run-summary line, and one issue per player
per game (scripts/nba_issue.py, label nba-report). Names that resolve to no
player we know are listed in the run summary; one that looks like a ROSTERED
player (same team and a close name) is flagged loudly (hub, summary, issue):
it could hide an Out. Nothing here ever stops a run.
"""

from __future__ import annotations

import difflib
import hashlib
import io
import re
import unicodedata
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

REPORT_FILE = Path("output") / "nba_injury_reports.jsonl"
SCHEMA = 1
STATUSES = ("Out", "Doubtful", "Questionable", "Probable", "Available")
HEADER_WORDS = ("Game", "Date", "Time", "Matchup", "Team", "Player", "Name", "Current", "Status", "Reason")
COLUMNS = ("game_date", "game_time", "matchup", "team", "name", "status", "reason")
NAME_RE = re.compile(r"Injury-Report_(\d{4}-\d{2}-\d{2})_(\d{2})_(\d{2})(AM|PM)\.pdf")
USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36")

# The report's team names -> the NBA schedule's codes (data/nba_schedule_*.json).
TEAMS = {
    "Atlanta Hawks": "ATL", "Boston Celtics": "BOS", "Brooklyn Nets": "BKN", "Charlotte Hornets": "CHA",
    "Chicago Bulls": "CHI", "Cleveland Cavaliers": "CLE", "Dallas Mavericks": "DAL",
    "Denver Nuggets": "DEN", "Detroit Pistons": "DET", "Golden State Warriors": "GSW",
    "Houston Rockets": "HOU", "Indiana Pacers": "IND", "LA Clippers": "LAC",
    "Los Angeles Lakers": "LAL", "Memphis Grizzlies": "MEM", "Miami Heat": "MIA",
    "Milwaukee Bucks": "MIL", "Minnesota Timberwolves": "MIN", "New Orleans Pelicans": "NOP",
    "New York Knicks": "NYK", "Oklahoma City Thunder": "OKC", "Orlando Magic": "ORL",
    "Philadelphia 76ers": "PHI", "Phoenix Suns": "PHX", "Portland Trail Blazers": "POR",
    "Sacramento Kings": "SAC", "San Antonio Spurs": "SAS", "Toronto Raptors": "TOR",
    "Utah Jazz": "UTA", "Washington Wizards": "WAS",
}


class ReportUnavailable(RuntimeError):
    """No report could be fetched (network, refused, none filed recently)."""


class ReportUnreadable(RuntimeError):
    """A report was fetched but its table is not the format this module reads."""


# =============================================================================
# config
# =============================================================================

def config(cfg: dict = None) -> dict:
    """live_refresh.nba_report, checked (every key required)."""
    if cfg is None:
        from .data_loader import _LEAGUE_CONFIG
        cfg = _LEAGUE_CONFIG
    blob = (cfg.get("live_refresh") or {}).get("nba_report")
    if not isinstance(blob, dict):
        raise KeyError("config/league_config.json has no live_refresh.nba_report")
    need = ("index_url", "pdf_url", "time_zone", "cadence_minutes", "probe_steps", "timeout_seconds",
            "stale_hours")
    missing = [k for k in need if blob.get(k) in (None, "")]
    if missing:
        raise KeyError(f"config live_refresh.nba_report does not specify {missing}")
    return {**blob, "tz": ZoneInfo(str(blob["time_zone"]))}


# =============================================================================
# finding and fetching the latest report
# =============================================================================

def filed_at(url: str, tz: ZoneInfo) -> datetime:
    """The filing time a report's name carries, on the NBA's clock."""
    m = NAME_RE.search(url)
    if not m:
        raise ReportUnreadable(f"{url!r} is not an injury report's name")
    d, hh, mm, ap = m.groups()
    t = datetime.strptime(f"{d} {hh}:{mm} {ap}", "%Y-%m-%d %I:%M %p")
    return t.replace(tzinfo=tz)


def url_for(at: datetime, cfg: dict) -> str:
    at = at.astimezone(cfg["tz"])
    return str(cfg["pdf_url"]).format(date=at.strftime("%Y-%m-%d"), hh=at.strftime("%I"),
                                      mm=at.strftime("%M"), ampm=at.strftime("%p"))


def http_get(url: str, timeout: float) -> bytes:
    """GET; raises urllib.error.HTTPError / URLError / TimeoutError."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def latest_url(now: datetime, cfg: dict, get=http_get) -> tuple:
    """(url, filed_at, how): the newest report filed at or before now. The
    index page first; else the last probe_steps filing times, newest first.
    Raises ReportUnavailable with every reason tried."""
    tz, why = cfg["tz"], []
    try:
        page = get(str(cfg["index_url"]), float(cfg["timeout_seconds"])).decode("utf-8", "replace")
        found = sorted({(filed_at(m.group(0), tz), m.group(0)) for m in NAME_RE.finditer(page)})
        found = [x for x in found if x[0] <= now.astimezone(tz)]
        if found:
            at, name = found[-1]
            return url_for(at, cfg), at, "index"
        why.append("the index page lists no report")
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
        why.append(f"index page: {_err(e)}")
    step = timedelta(minutes=int(cfg["cadence_minutes"]))
    t = now.astimezone(tz)
    cad = int(cfg["cadence_minutes"])
    t = t.replace(minute=(t.minute // cad) * cad, second=0, microsecond=0)
    misses = 0
    for _ in range(int(cfg["probe_steps"])):
        url = url_for(t, cfg)
        try:
            get(url, float(cfg["timeout_seconds"]))
            return url, t, "probe"
        except urllib.error.HTTPError as e:
            if e.code not in (403, 404):
                why.append(f"{url.rsplit('/', 1)[-1]}: {_err(e)}")
                break
            misses += 1
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            why.append(f"{url.rsplit('/', 1)[-1]}: {_err(e)}")
            break
        t -= step
    if misses:
        why.append(f"no report filed in the last {misses} filing time(s) back to {t + step:%m-%d %H:%M} ET")
    raise ReportUnavailable("; ".join(why))


def _err(e: Exception) -> str:
    if isinstance(e, urllib.error.HTTPError):
        return f"HTTP {e.code}"
    if isinstance(e, urllib.error.URLError):
        return f"network ({e.reason})"
    return f"{type(e).__name__}: {e}"


def fetch(now: datetime, cfg: dict, get=http_get) -> tuple:
    """(url, filed_at, pdf bytes, how). Raises ReportUnavailable."""
    url, at, how = latest_url(now, cfg, get)
    try:
        body = get(url, float(cfg["timeout_seconds"]))
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise ReportUnavailable(f"{url.rsplit('/', 1)[-1]}: {_err(e)}") from None
    if not body.startswith(b"%PDF"):
        raise ReportUnavailable(f"{url.rsplit('/', 1)[-1]} is not a PDF")
    return url, at, body, how


# =============================================================================
# parsing
# =============================================================================

def fragments(pdf: bytes) -> list:
    """[[(x, y, text), ...] per page]: every text fragment with its position
    (the text matrix times the current matrix), from pypdf."""
    try:
        import pypdf
    except ImportError as e:
        raise ReportUnreadable(f"pypdf is not installed ({e}): pip install -r requirements.txt") from None
    try:
        reader = pypdf.PdfReader(io.BytesIO(pdf))
        pages = []
        for page in reader.pages:
            out = []

            def visit(text, cm, tm, _fd, _fs, out=out):
                t = str(text).strip()
                if t:
                    x = tm[4] * cm[0] + tm[5] * cm[2] + cm[4]
                    y = tm[4] * cm[1] + tm[5] * cm[3] + cm[5]
                    out.append((round(float(x), 1), round(float(y), 1), t))
            page.extract_text(visitor_text=visit)
            pages.append(out)
        return pages
    except Exception as e:                              # noqa: BLE001 -- any pypdf failure
        raise ReportUnreadable(f"the PDF could not be read ({type(e).__name__}: {e})") from None


def _lines(frags: list) -> list:
    """Fragments grouped into lines (same y, within 1.5 points), top first,
    each line's fragments left to right."""
    rows = []
    for x, y, t in sorted(frags, key=lambda f: (-f[1], f[0])):
        if rows and abs(rows[-1][0] - y) <= 1.5:
            rows[-1][1].append((x, t))
        else:
            rows.append([y, [(x, t)]])
    return [(y, sorted(fs)) for y, fs in rows]


def _header(lines: list):
    """(y, column x starts) from the header line, or None."""
    for y, fs in lines:
        words = [t for _, t in fs]
        if words[:1] == ["Game"] and all(w in words for w in ("Matchup", "Team", "Player", "Reason")):
            xs = [x for x, _ in fs]
            starts = []
            i = 0
            # Game Date | Game Time | Matchup | Team | Player Name | Current Status | Reason
            pairs = [("Game", "Date"), ("Game", "Time"), ("Matchup",), ("Team",), ("Player", "Name"),
                     ("Current", "Status"), ("Reason",)]
            for want in pairs:
                while i < len(words) and words[i] != want[0]:
                    i += 1
                if i >= len(words):
                    raise ReportUnreadable(f"the header line {' '.join(words)!r} lacks {' '.join(want)}")
                starts.append(xs[i])
                i += len(want)
            return y, starts
    return None


def _cells(fs: list, starts: list) -> dict:
    cells = {c: [] for c in COLUMNS}
    for x, t in fs:
        col = 0
        for j, s in enumerate(starts):
            if x >= s - 2.0:
                col = j
        cells[COLUMNS[col]].append(t)
    # a word the PDF broke at its hyphen ("Jackson-" "Davis,") is one word again
    return {c: re.sub(r"(\w)- (\w)", r"\1-\2", " ".join(v)).strip() for c, v in cells.items()}


def first_last(printed: str) -> str:
    """'Jackson Jr., Jaren' -> 'Jaren Jackson Jr.'; 'Udeh, Jr., Ernest' ->
    'Ernest Udeh Jr.'; a name with no comma as is; any other shape raises."""
    s = " ".join(str(printed).split())
    parts = [x.strip() for x in s.split(",")]
    if len(parts) == 1:
        return s
    if len(parts) == 3 and parts[1].rstrip(".").lower() in ("jr", "sr", "ii", "iii", "iv"):
        return f"{parts[2]} {parts[0]} {parts[1]}"        # 'Udeh, Jr., Ernest'
    if len(parts) != 2:
        raise ReportUnreadable(f"the name {printed!r} is not 'Last, First'")
    return f"{parts[1]} {parts[0]}".strip()


def parse_fragments(pages: list) -> dict:
    """{"heading": "11/10/26 05:00 PM" or None, "entries": [...], "not_submitted": [team, ...]}."""
    entries, not_submitted, heading = [], [], None
    starts = None
    carry = {"game_date": "", "game_time": "", "matchup": "", "team": ""}
    for pno, frags in enumerate(pages, start=1):
        lines = _lines(frags)
        hdr = _header(lines)
        if hdr is not None:
            hy, starts = hdr
        elif starts is None:
            raise ReportUnreadable(f"page {pno} has no table header, and no page before it had one")
        else:
            hy = None
        for y, fs in lines:
            text = " ".join(t for _, t in fs)
            m = re.search(r"Injury Report:\s*(\d\d/\d\d/\d\d)\s+(\d\d:\d\d)\s*(AM|PM)", text)
            if m:                                   # the title line, on every page
                heading = heading or " ".join(m.groups())
                continue
            if hy is not None and y >= hy - 1.5:    # the header line and anything above it
                continue
            if re.fullmatch(r"Page\s+\d+\s+of\s*\d+", text):
                continue
            c = _cells(fs, starts)
            for k in ("game_date", "game_time", "matchup", "team"):
                if c[k]:
                    carry[k] = c[k]
            if c["name"] and c["status"]:
                if c["status"] not in STATUSES:
                    raise ReportUnreadable(f"page {pno}: status {c['status']!r} for {c['name']!r} is "
                                           f"none of {STATUSES}")
                date_ = _iso_date(carry["game_date"], pno)
                entries.append({"game_date": date_, "game_time": carry["game_time"],
                                "matchup": carry["matchup"], "team": carry["team"],
                                "name": c["name"], "player": first_last(c["name"]),
                                "status": c["status"], "reason": c["reason"]})
            elif "NOT YET SUBMITTED" in c["reason"].upper() and not c["name"]:
                not_submitted.append({"team": carry["team"], "game_date": _iso_date(carry["game_date"], pno),
                                      "matchup": carry["matchup"]})
            elif c["reason"] and not (c["name"] or c["status"]):
                # a wrapped reason: the report centres the player's line between
                # the wrapped parts, so a part cannot be told apart from the next
                # player's; reasons decide nothing, and the parts are dropped
                continue
            elif c["name"] and not c["status"]:
                raise ReportUnreadable(f"page {pno}: a player line with no status ({c['name']!r})")
    if not entries and not not_submitted:
        raise ReportUnreadable("the report's table has no rows")
    return {"heading": heading, "entries": entries, "not_submitted": not_submitted}


def _iso_date(text: str, pno: int) -> str:
    try:
        return datetime.strptime(text.strip(), "%m/%d/%Y").date().isoformat()
    except ValueError:
        raise ReportUnreadable(f"page {pno}: game date {text!r} is not MM/DD/YYYY") from None


def parse(pdf: bytes) -> dict:
    return parse_fragments(fragments(pdf))


# =============================================================================
# the stored reads
# =============================================================================

def read_rows(base_path=".") -> list:
    from .jsonl_log import read_rows as _rr
    return _rr(Path(base_path) / REPORT_FILE, REPORT_FILE.as_posix())


def read_and_store(base_path, now: datetime, *, run_id: str, mode: str, get=http_get,
                   cfg: dict = None) -> dict:
    """Fetch the latest report, parse it and append its row. Never raises for
    the report itself: an unavailable or unreadable one is a row saying so."""
    from .jsonl_log import append_rows
    cfg = cfg or config()
    row = {"schema": SCHEMA, "run_id": run_id, "mode": mode,
           "read_at": now.isoformat(timespec="seconds")}
    try:
        url, at, body, how = fetch(now, cfg, get)
        row.update(url=url, filed_at=at.isoformat(timespec="minutes"), found_by=how,
                   sha256=hashlib.sha256(body).hexdigest())
        prev = None
        for r in reversed(read_rows(base_path)):
            if r.get("outcome") == "ok":
                prev = r
                break
        if prev is not None and prev.get("sha256") == row["sha256"]:
            row.update(outcome="ok", same_as=prev.get("same_as") or prev["run_id"])
        else:
            parsed = parse(body)
            row.update(outcome="ok", heading=parsed["heading"], entries=parsed["entries"],
                       not_submitted=parsed["not_submitted"])
    except ReportUnavailable as e:
        row.update(outcome="unavailable", reason=str(e))
    except ReportUnreadable as e:
        row.update(outcome="unreadable", reason=str(e))
    append_rows(Path(base_path) / REPORT_FILE, [row])
    return row


def latest(base_path=".") -> dict:
    """{"attempt": the latest row (or None), "report": the latest ok row with
    its entries resolved through same_as (or None)}."""
    rows = read_rows(base_path)
    if not rows:
        return {"attempt": None, "report": None}
    by_id = {r["run_id"]: r for r in rows}
    rep = None
    for r in reversed(rows):
        if r.get("outcome") == "ok":
            rep = dict(r)
            if "same_as" in r:
                src = by_id.get(r["same_as"])
                if src is None or "entries" not in src:
                    raise ValueError(f"{REPORT_FILE} row {r['run_id']} is the same as "
                                     f"{r['same_as']}, which holds no entries")
                rep.update(entries=src["entries"], not_submitted=src.get("not_submitted", []),
                           heading=src.get("heading"))
            break
    return {"attempt": rows[-1], "report": rep}


# =============================================================================
# names, and what Out does
# =============================================================================

def _fold(s: str) -> str:
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode("ascii").lower()
    s = re.sub(r"[^a-z ]", "", s.replace("-", " "))
    s = re.sub(r"\b(jr|sr|ii|iii|iv)\b", "", s)
    return " ".join(s.split())


def known_players(base_path, rosters: dict, playerlist=None) -> dict:
    """{name: NBA team code or None}: PLAYERLIST, the rosters and the cached
    basketball-reference lists (data/NBA_PLAYER_REFERENCE.json), the same
    union modules/nba_reference reads."""
    import json
    out = {}
    p = Path(base_path) / "data" / "NBA_PLAYER_REFERENCE.json"
    if p.is_file():
        blob = json.loads(p.read_text(encoding="utf-8"))
        for key in ("last_completed", "this_season"):
            for n, t in ((blob.get("seasons") or {}).get(key) or {}).get("players", {}).items():
                out[n] = t
    if playerlist is not None:
        for n, t in zip(playerlist["player_name"], playerlist["player_nba_team"]):
            if isinstance(n, str):
                out[n] = str(t).upper() if isinstance(t, str) else out.get(n)
    for names in rosters.values():
        for n in names:
            out.setdefault(n, None)
    return out


def resolve(entries: list, known: dict, rostered) -> list:
    """Each entry plus "resolved" (a known player's name, the ROSTER's spelling
    when he is rostered) or None, and "loud" (an unresolved name that looks
    like a rostered player: same team and a close name) naming who."""
    from .data_loader import PlayerIndex
    kidx = PlayerIndex({n: n for n in known})
    ridx = PlayerIndex({n: n for n in rostered})
    team_of = {n: t for n, t in known.items()}
    out = []
    for e in entries:
        hit = kidx.canonical(e["player"])
        r = dict(e, resolved=None, loud=None)
        if hit is not None:
            rhit = ridx.canonical(hit)
            r["resolved"] = rhit if rhit is not None else hit
        else:
            code = TEAMS.get(e["team"])
            q = _fold(e["player"])
            for n in rostered:
                his = team_of.get(n)
                same_team = code is not None and his == code
                close = difflib.SequenceMatcher(None, q, _fold(n)).ratio() >= 0.75
                same_last = q.split()[-1:] == _fold(n).split()[-1:]
                # his team decides when both are known (Dillon Mitchell, BOS, is not
                # Davion Mitchell); a rostered player with no known team stays a suspect
                if (same_team and (close or same_last)) or (his is None and close and same_last):
                    r["loud"] = n
                    break
        out.append(r)
    return out


def assess(report: dict, tags, rosters: dict, override_out_on_day, today: date, known: dict,
           now: datetime = None, cfg: dict = None) -> dict:
    """What tonight's report does. report: latest()["report"] (or None);
    tags: the run's Yahoo tags (rostered); override_out_on_day(name) -> True
    when an injury entry keeps him out today.
    {"applied": {player: today}, "flags": [...], "covered": [...],
     "unresolved": [...], "loud": [...], "stale": str or None, "filed_at"}."""
    from . import absence
    from .data_loader import PlayerIndex
    cfg = cfg or config()
    res = {"applied": {}, "flags": [], "covered": [], "unresolved": [], "loud": [], "stale": None,
           "filed_at": None, "not_submitted": []}
    if not report:
        return res
    res["filed_at"] = report.get("filed_at")
    at = datetime.fromisoformat(report["filed_at"])
    if now is not None and now - at > timedelta(hours=float(cfg["stale_hours"])):
        res["stale"] = (f"the latest NBA report was filed {at:%m-%d %H:%M} ET, more than "
                        f"{cfg['stale_hours']} hours ago: not applied")
        return res
    rostered = [n for v in rosters.values() for n in v]
    tidx = tags if isinstance(tags, PlayerIndex) else PlayerIndex(dict(tags or {}))
    day = today.isoformat()
    res["not_submitted"] = [x for x in report.get("not_submitted", []) if x.get("game_date") == day]
    seen = set()
    for e in resolve(report.get("entries", []), known, rostered):
        if e["resolved"] is None:
            item = {"name": e["player"], "team": e["team"], "status": e["status"],
                    "game_date": e["game_date"]}
            res["unresolved"].append(item)
            if e["loud"]:
                res["loud"].append(dict(item, maybe=e["loud"]))
            continue
        if e["status"] != "Out" or e["game_date"] != day:
            continue
        name = e["resolved"]
        if name not in rostered or name in seen:
            continue
        seen.add(name)
        tag = tidx.get(name)
        norm = absence.normalised_tag(tag) if tag is not None else "HEALTHY"
        if norm not in ("O", "OFS"):
            md = f"{today:%a %m-%d}"
            ytxt = "no tag" if norm in ("HEALTHY", "P") else norm
            res["flags"].append({"player": name, "game_date": day, "yahoo": ytxt,
                                 "text": f"NBA report: {name} out tonight (Yahoo: {ytxt})",
                                 "title": f"NBA report: {name} out {md} (Yahoo: {ytxt})"})
        if norm in ("O", "OFS"):
            res["covered"].append(f"{name} (Yahoo {norm})")
        elif override_out_on_day(name):
            res["covered"].append(f"{name} (injury entry)")
        else:
            res["applied"][name] = day
    return res


def summary(row: dict, assessed: dict) -> str:
    """The run summary's line(s) for one read (or reuse) of the report."""
    if row is None:
        return "NBA report: none read yet"
    if row.get("outcome") != "ok":
        return f"NBA report unavailable ({row.get('reason')}); Yahoo's tags stand"
    bits = [f"NBA report filed {datetime.fromisoformat(row['filed_at']):%m-%d %I:%M %p} ET"]
    if assessed.get("stale"):
        bits.append(assessed["stale"])
    if assessed["applied"]:
        bits.append("out tonight (applied): " + ", ".join(sorted(assessed["applied"])))
    if assessed["covered"]:
        bits.append("out tonight, already covered: " + ", ".join(assessed["covered"]))
    for f in assessed["flags"]:
        bits.append(f"FLAG {f['text']}")
    for x in assessed["loud"]:
        bits.append(f"FLAG unresolved NBA report name {x['name']} ({x['team']}, {x['status']}): "
                    f"is it {x['maybe']}? Check his status")
    if assessed["unresolved"]:
        bits.append(f"{len(assessed['unresolved'])} name(s) not matched to a known player: "
                    + ", ".join(f"{x['name']} ({TEAMS.get(x['team'], x['team'])})"
                                for x in assessed["unresolved"]))
    if assessed.get("not_submitted"):
        bits.append("not yet submitted tonight: " + ", ".join(sorted({x["team"] for x in
                                                                     assessed["not_submitted"]})))
    return "; ".join(bits)
