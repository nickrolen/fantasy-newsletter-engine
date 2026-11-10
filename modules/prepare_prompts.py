"""
prepare_prompts.py -- the three drafting prompts, filled from the week's stats
report (task 10a; claude/HANDOFF_PREPARE_PROMPTS_2026-11-05.md).

    python scripts\\prepare_prompts.py --week N        (after Step 6.5)

reads templates/NEWSLETTER_PROMPTS.md and writes output/prompts_weekN.md
(league state: it holds names, config/STATE_MANIFEST.json): a header listing
the files to upload with Part 1, by path, each confirmed to exist, then Parts
1, 2 and 3 ready to paste, with no [FILL IN ...] and no [IF ...] left.

WHAT IT FILLS, AND FROM WHERE
  week, dates, season   --week N; config/SCHEDULE.json; league_config
                        season.current. The report must be week N's: its .md
                        and .json headers say week N and the schedule's dates,
                        and the .md was formatted from this .json (same
                        "generated" stamp).
  the league line       len(managers) teams; season.league_season_number as
                        a word (12 -> "twelfth"); never data_era_season_number.
  the manager table     league_config managers and manager_to_team; each
                        manager's STAR PLAYERS are his top three in the
                        report's keeper watch by keep chance (keep_k5, the
                        report's own per-team rank 1-3). Why keep chance and
                        not season FPPG: it blends several seasons' level,
                        age and availability, so it names the players a
                        manager's team is built around; two weeks of FPPG is
                        noise and drops an injured star (Edwards on IL in
                        week 2). Stars are as of the report, not today's
                        rosters.
  KEY STORYLINES        the report's ANGLES block, byte for byte, heading
                        included ("NO LEAD THIS WEEK" passes through). An
                        "unavailable" block refuses: rerun Step 6.5.
  the trade block       week N's trades (below); deleted when there are none.
  Section 9's dates     week N's first and last day.
  the rosters           config/ROSTERS.json, every player, IL-slot players
                        marked "(IL)" from data/IL_SLOTS.json, which must be
                        this fantasy week's file (as of the run).
  the uploads           templates/NEWSLETTER_PROMPTS.md's Part 1 list, by
                        path (UPLOADS; a test keeps the two the same), plus
                        weeklycontextinput_weekN.json when it exists.

WEEK N'S TRADES. A chat trade agreed in week N takes effect in week N+1's
Monday window (LEAGUE_RULES rule 13), so the two sources carry it in
different weeks. Week N's trades are:
  - every move-ledger trade entry (config/MOVE_LEDGER.json, not voided)
    CLAIMED in week N; if Yahoo's log already holds its trade (week N+1's
    window, same two managers), the players must agree;
  - every Yahoo trade (data/transaction_log.jsonl) made in week N's own
    Monday window that no ledger entry taking effect in that window explains
    (a trade made directly in Yahoo). One the ledger does explain is week
    N-1's trade, already reported, and must agree with its entry.
REFUSED: a Yahoo trade in week N outside the Monday window (rule 13); a
ledger entry and a Yahoo trade between the same managers in the same window
that name different players; two of either between the same managers in one
window (no way to pair them). Picks: only data/weeklycontextinput_weekN.json
carries them (the ledger and Yahoo's log name players); a trade there must
name the same players as the ledger/log trade between those managers, or
name only picks.

Raise, never guess: every missing file, key or disagreement refuses with the
reason (PromptsRefused). The script never writes a state file but its own
output.
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime
from pathlib import Path
from typing import Optional

TEMPLATE = Path("templates") / "NEWSLETTER_PROMPTS.md"

# Part 1's upload list, in the template's order. tests/test_prepare_prompts.py
# checks these names against the template's list, so the two cannot drift.
UPLOADS = (
    Path("output") / "stats_report_week{week}.md",
    Path("templates") / "VOICE.md",
    Path("templates") / "newsletter_template.md",
    Path("config") / "LAST_WEEK_RECAP.md",
    Path("config") / "RECENT_CONTENT.json",
    Path("config") / "INJURY_OVERRIDES.json",
    Path("output") / "lore_for_drafting.json",
)
WCTI_NAME = "weeklycontextinput_week{week}.json"
# format_stats_report.load_weekly_trades' search order: the prompts must name
# the file the report read. Only data/ is where the workflow puts it.
WCTI_DIRS = (".", "data", "scripts", "config")

HAND_START = "<!-- BY HAND ONLY -->"
HAND_END = "<!-- END BY HAND ONLY -->"
IF_TRADES = "[IF FANTASY TRADES HAPPENED IN WEEK N, KEEP THIS BLOCK; OTHERWISE DELETE IT:]"
IF_WCTI = "[IF data\\weeklycontextinput_weekN.json EXISTS, KEEP THIS LINE; OTHERWISE DELETE IT:]"
END_IF = "[END IF]"
GRADE_LINE = "- Include a letter grade (A-F) for EACH manager analyzing fairness."

# The first line of every prompt (F9, 11-09: the Step 8 chat had folder access
# and opened config/LEAGUE_LORE.json, which holds proposals and rejections the
# writer must not see). templates/VERIFICATION_TEMPLATE.md carries it too.
ONLY_UPLOADED = ("Use only the files uploaded to this chat. Do not open any other file in my "
                 "folder, and never `config/LEAGUE_LORE.json`.")


def prompt_blocks(text: str) -> list:
    """The fenced prompt of each part, in order (the block after "**Prompt:**")."""
    out = []
    for chunk in text.split("**Prompt:**")[1:]:
        body = chunk.split("```", 2)
        if len(body) >= 3:
            out.append(body[1].lstrip("\n"))
    return out

PH_WEEK = "[FILL IN: N]"
PH_SEASON = "[FILL IN: YYYY-YY]"
PH_START = "[FILL IN: Start Date]"
PH_END = "[FILL IN: End Date]"
PH_TEAMS = "[FILL IN: number of teams]"
PH_ORDINAL = "[FILL IN: league season ordinal, e.g. twelfth]"
PH_MANAGERS = "[FILL IN: one row per manager: | Manager | Team Name | three star players |]"
PH_ANGLES = "[FILL IN: the stats report's ANGLES block, verbatim]"
PH_S9_START = "[FILL IN: Week N start date]"
PH_S9_END = "[FILL IN: Week N end date]"
PH_ROSTERS = ("[FILL IN: every manager's roster from config/ROSTERS.json, all players listed, "
              "IL-slot players marked (IL) from data/IL_SLOTS.json]")
# placeholders inside the trade block, which the script rewrites whole
PH_TRADE_INNER = ("[FILL IN: Manager A]", "[FILL IN: Manager B]", "[FILL IN: players/picks sent]")

ORDINALS = ("first", "second", "third", "fourth", "fifth", "sixth", "seventh", "eighth",
            "ninth", "tenth", "eleventh", "twelfth", "thirteenth", "fourteenth", "fifteenth",
            "sixteenth", "seventeenth", "eighteenth", "nineteenth", "twentieth")

ANGLES_HEAD = "## -> ANGLES -> "
ANGLES_KINDS = ("WHAT LEADS THIS WEEK", "NO LEAD THIS WEEK")
PICK_RE = re.compile(r"^\d{4}\s+\d+(?:st|nd|rd|th)\s+round\s+pick$", re.IGNORECASE)


class PromptsRefused(ValueError):
    """The prompts cannot be filled as specified; the message says why."""


# =============================================================================
# small pieces
# =============================================================================

def ordinal_word(n) -> str:
    """12 -> "twelfth". Anything the word list does not cover raises."""
    if isinstance(n, bool) or not isinstance(n, int) or n < 1:
        raise PromptsRefused(f"league_season_number {n!r}: a whole number >= 1 is needed")
    if n > len(ORDINALS):
        raise PromptsRefused(f"league_season_number {n}: the ordinal word list stops at "
                             f"{len(ORDINALS)} ({ORDINALS[-1]}); extend ORDINALS")
    return ORDINALS[n - 1]


def _month_day(d: date) -> str:
    return f"{d:%b} {d.day}"


def title_dates(start: date, end: date) -> tuple:
    """("Oct 26", "Nov 1"): the title's range, worded "to" (template rule 20)."""
    return _month_day(start), _month_day(end)


def search_dates(start: date, end: date) -> tuple:
    """Section 9's search range, with the year(s)."""
    if start.year == end.year:
        return _month_day(start), f"{_month_day(end)}, {end.year}"
    return f"{_month_day(start)}, {start.year}", f"{_month_day(end)}, {end.year}"


def _read_json(base: Path, rel: Path):
    p = base / rel
    if not p.is_file():
        raise PromptsRefused(f"{rel.as_posix()} is missing")
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise PromptsRefused(f"{rel.as_posix()} is not valid JSON: {e}") from None


def _need(d: dict, key: str, where: str):
    if not isinstance(d, dict) or key not in d or d[key] in (None, ""):
        raise PromptsRefused(f"{where} has no {key!r}")
    return d[key]


def _index(names):
    from .data_loader import PlayerIndex
    return PlayerIndex({n: n for n in names})


def _same_names(a, b) -> bool:
    """The same players, through PlayerIndex (accents, suffixes): the project's
    one name matcher."""
    a, b = list(a), list(b)
    if len(a) != len(b):
        return False
    left = list(b)
    for n in a:
        hit = _index(left).canonical(n)
        if hit is None:
            return False
        left.remove(hit)
    return True


# =============================================================================
# mangled characters (the template's dashes, arrows and bullets were mangled
# into '"' and "'" and dropped characters; this is the guard)
# =============================================================================

MANGLED = (
    (re.compile("\ufffd"), "a replacement character (U+FFFD)"),
    (re.compile("\u00e2\u20ac|\u00c3.|\u00c2(?=[\u00a0-\u00bf ])"), "UTF-8 read as cp1252 (mojibake)"),
    (re.compile(r'[A-Za-z0-9]"[A-Za-z0-9]'), 'a \'"\' inside a word or range (a dash: 3"5, A"F)'),
    (re.compile(r'(?<=\S) " (?=\S)'), "a lone '\"' between words (a dash)"),
    (re.compile(r"^\s*' ", re.MULTILINE), "a \"'\" bullet"),
    (re.compile(r"\w'\w+'\w"), "\"'\" between words (an arrow)"),
    (re.compile(r"(?<=[^\s|])  (?=[A-Z0-9])"), "two spaces where a dash was dropped"),
)


def mangled(text: str) -> list:
    """Every mangled character in `text`: [(line number, what, line)]."""
    out = []
    for i, line in enumerate(text.splitlines(), start=1):
        for rx, what in MANGLED:
            if rx.search(line):
                out.append((i, what, line))
    return out


# =============================================================================
# the inputs
# =============================================================================

def load_config(base) -> dict:
    cfg = _read_json(Path(base), Path("config") / "league_config.json")
    managers = _need(cfg, "managers", "league_config.json")
    if not isinstance(managers, list) or len(set(managers)) != len(managers) or len(managers) < 2:
        raise PromptsRefused(f"league_config.json managers {managers!r}: a list of distinct names")
    teams = _need(cfg, "manager_to_team", "league_config.json")
    if set(teams) != set(managers):
        raise PromptsRefused(f"league_config.json manager_to_team names {sorted(teams)}, the "
                             f"managers are {sorted(managers)}")
    for m in managers:
        _need(teams, m, "league_config.json manager_to_team")
    season = _need(cfg, "season", "league_config.json")
    for k in ("current", "current_long", "league_season_number"):
        _need(season, k, "league_config.json season")
    _need(cfg, "presentation", "league_config.json")
    return cfg


def week_dates(schedule: dict, week: int, season_long: str) -> tuple:
    if schedule.get("season_year") != season_long:
        raise PromptsRefused(f"config/SCHEDULE.json is season {schedule.get('season_year')!r}, "
                             f"the config's season is {season_long!r}")
    rows = [w for w in schedule.get("weeks", []) if w.get("week") == week]
    if len(rows) != 1:
        raise PromptsRefused(f"config/SCHEDULE.json has {len(rows)} entries for week {week}")
    return (date.fromisoformat(str(rows[0]["start_date"])[:10]),
            date.fromisoformat(str(rows[0]["end_date"])[:10]))


def week_of(schedule: dict, day: date) -> Optional[int]:
    from .transaction_log import week_containing
    return week_containing(schedule, day)


def read_report(base, week: int, start: date, end: date, season_long: str) -> tuple:
    """(markdown, json) of week N's stats report. Missing, another week's, or
    a .md not formatted from this .json refuses."""
    base = Path(base)
    md_rel = Path("output") / f"stats_report_week{week}.md"
    js_rel = Path("output") / f"stats_report_week{week}.json"
    for rel in (js_rel, md_rel):
        if not (base / rel).is_file():
            raise PromptsRefused(f"{rel.as_posix()} is missing: run Step 6 (generate_stats_report) "
                                 f"and Step 6.5 (format_stats_report) for week {week} first")
    data = _read_json(base, js_rel)
    meta = _need(data, "metadata", js_rel.as_posix())
    if meta.get("week") != week:
        raise PromptsRefused(f"{js_rel.as_posix()} is the week {meta.get('week')!r} report")
    if meta.get("season_year") != season_long:
        raise PromptsRefused(f"{js_rel.as_posix()} is season {meta.get('season_year')!r}, "
                             f"not {season_long}")
    dr = meta.get("date_range") or {}
    if (dr.get("start"), dr.get("end")) != (start.isoformat(), end.isoformat()):
        raise PromptsRefused(f"{js_rel.as_posix()} covers {dr.get('start')} to {dr.get('end')}; "
                             f"the schedule's week {week} is {start} to {end}")
    md = (base / md_rel).read_text(encoding="utf-8")
    lines = md.splitlines()
    head = re.match(r"^# WEEK (\d+) STATS REPORT ", lines[0] if lines else "")
    if not head or int(head.group(1)) != week:
        raise PromptsRefused(f"{md_rel.as_posix()} does not open as the week {week} report "
                             f"({(lines[0] if lines else '')[:60]!r})")
    sub = re.match(r"^# Season (\S+) \| Week (\d+) \((\S+) -> (\S+)\)$", lines[1] if len(lines) > 1 else "")
    if not sub or (sub.group(1), int(sub.group(2)), sub.group(3), sub.group(4)) != \
            (season_long, week, start.isoformat(), end.isoformat()):
        raise PromptsRefused(f"{md_rel.as_posix()}'s second line is not season {season_long}, "
                             f"week {week}, {start} to {end}")
    gen = re.match(r"^# Generated: (\S+)$", lines[2] if len(lines) > 2 else "")
    if not gen or gen.group(1) != meta.get("generated_at"):
        raise PromptsRefused(f"{md_rel.as_posix()} was not formatted from this "
                             f"{js_rel.as_posix()} (generated {gen.group(1) if gen else '?'} vs "
                             f"{meta.get('generated_at')}): rerun Step 6.5")
    return md, data


def angles_block(md: str) -> str:
    """The report's ANGLES block, byte for byte: from its heading to the
    blank line before the "---" that format_stats_report puts after it."""
    starts = [m.start() for m in re.finditer(r"(?m)^" + re.escape(ANGLES_HEAD), md)]
    if len(starts) != 1:
        raise PromptsRefused(f"the stats report has {len(starts)} ANGLES blocks, not one")
    s = starts[0]
    kind = md[s + len(ANGLES_HEAD):].split("\n", 1)[0]
    if kind not in ANGLES_KINDS:
        raise PromptsRefused(f"the report's ANGLES block is {kind!r}: the angles did not run. "
                             "Fix it and rerun Step 6.5, or fill the storylines by hand "
                             "(templates/NEWSLETTER_PROMPTS.md)")
    e = md.find("\n\n---\n", s)
    if e < 0:
        raise PromptsRefused("the report's ANGLES block has no end (the '---' after it)")
    block = md[s:e]
    if "**Money this week" not in block:
        raise PromptsRefused("the report's ANGLES block has no \"Money this week\" line "
                             "(template rule 23 needs it)")
    return block


def manager_rows(cfg: dict, data: dict, week: int) -> list:
    """[(manager, team, [three stars])], in the config's order. Stars: the
    report's keeper watch, ranks 1-3 per team (by keep chance)."""
    kw = _need(data, "keeper_watch", "the stats report")
    if kw.get("week") != week:
        raise PromptsRefused(f"the report's keeper watch is week {kw.get('week')!r}, not {week}")
    players = _need(kw, "players", "the report's keeper watch")
    out = []
    for m in cfg["managers"]:
        stars = []
        for r in (1, 2, 3):
            hit = [p for p in players if p.get("manager") == m and p.get("rank") == r]
            if len(hit) != 1:
                raise PromptsRefused(f"the report's keeper watch has {len(hit)} rank-{r} players "
                                     f"for {m}, not one")
            stars.append(_need(hit[0], "player_name", f"{m}'s rank-{r} keeper-watch row"))
        out.append((m, cfg["manager_to_team"][m], stars))
    return out


def roster_lines(base, cfg: dict, schedule: dict, today: date) -> tuple:
    """(lines, note): every manager's roster with IL-slot players marked."""
    base = Path(base)
    blob = _read_json(base, Path("config") / "ROSTERS.json")
    rosters = _need(blob, "rosters", "config/ROSTERS.json")
    synced = _need(blob, "_last_sync", "config/ROSTERS.json")
    if set(rosters) != set(cfg["managers"]):
        raise PromptsRefused(f"config/ROSTERS.json has {sorted(rosters)}, the managers are "
                             f"{sorted(cfg['managers'])}")
    il = _read_json(base, Path("data") / "IL_SLOTS.json")
    slots = _need(il, "slots", "data/IL_SLOTS.json")
    now_week = week_of(schedule, today)
    if now_week is None:
        raise PromptsRefused(f"{today} is in no fantasy week: no current IL slots to show")
    if il.get("fantasy_week") != now_week:
        raise PromptsRefused(f"data/IL_SLOTS.json is week {il.get('fantasy_week')!r}'s; today "
                             f"({today}) is week {now_week}: run `python scripts\\state.py pull` "
                             "(the nightly run syncs it)")
    unknown = set(slots) - set(cfg["managers"])
    if unknown:
        raise PromptsRefused(f"data/IL_SLOTS.json names {sorted(unknown)}, who are not managers")
    lines = []
    for m in cfg["managers"]:
        names = list(rosters[m])
        if not names or len(set(names)) != len(names):
            raise PromptsRefused(f"config/ROSTERS.json: {m}'s roster is empty or names a player twice")
        idx = _index(names)
        on_il = []
        for n in slots.get(m, []):
            hit = idx.canonical(n)
            if hit is None:
                raise PromptsRefused(f"data/IL_SLOTS.json puts {n} in {m}'s IL slot; he is not on "
                                     f"{m}'s roster in config/ROSTERS.json")
            on_il.append(hit)
        shown = [f"{n} (IL)" if n in on_il else n for n in names]
        lines.append(f"- **{m}** ({cfg['manager_to_team'][m]}; active {len(names) - len(on_il)}, "
                     f"IL {len(on_il)}): {', '.join(shown)}")
    note = (f"config\\ROSTERS.json as synced {synced}; IL slots from data\\IL_SLOTS.json "
            f"(week {now_week}, fetched {il.get('fetched_at')})")
    return lines, note


# =============================================================================
# trades
# =============================================================================

def find_wcti(base, week: int) -> Optional[Path]:
    """data/weeklycontextinput_weekN.json, or None. A copy anywhere else the
    report would read refuses: the prompts must name the file it read."""
    base = Path(base)
    name = WCTI_NAME.format(week=week)
    found = [Path(d) / name for d in WCTI_DIRS if (base / d / name).is_file()]
    if not found:
        return None
    if found != [Path("data") / name]:
        raise PromptsRefused(f"{name} is at {', '.join(p.as_posix() for p in found)}; it belongs "
                             f"in data/ only (WEEKLY_WORKFLOW.md Step 5.5)")
    return found[0]


def _log_sides(t: dict) -> dict:
    """{manager: [players he gets]} from a Yahoo trade row."""
    sides, froms = {}, {}
    for p in t.get("players", []):
        to = (p.get("to") or {}).get("manager")
        fr = (p.get("from") or {}).get("manager")
        if p.get("action") != "trade" or not to or not fr or to == fr:
            raise PromptsRefused(f"Yahoo trade {t.get('key')}: a player part that is not a trade "
                                 f"between two managers ({p.get('name')})")
        sides.setdefault(to, []).append(p["name"])
        froms.setdefault(to, set()).add(fr)
    if len(sides) != 2 or any(froms[m] != set(sides) - {m} for m in sides):
        raise PromptsRefused(f"Yahoo trade {t.get('key')} is not a trade between two managers")
    return sides


def _ledger_sides(e: dict) -> dict:
    return {s["manager"]: list(s["gets"]) for s in e["parsed"]["sides"]}


def _agree(a: dict, b: dict) -> bool:
    return set(a) == set(b) and all(_same_names(a[m], b[m]) for m in a)


def _describe(sides: dict) -> str:
    return "; ".join(f"{m} gets {', '.join(v)}" for m, v in sorted(sides.items()))


def _pacific(iso: str) -> str:
    d = datetime.fromisoformat(iso)
    h = d.hour % 12 or 12
    return f"{d:%a} {d:%b} {d.day}, {h}:{d:%M} {'AM' if d.hour < 12 else 'PM'} Pacific"


def week_trades(base, cfg: dict, schedule: dict, week: int, wcti: Optional[Path]) -> list:
    """Week N's trades: [{"sides": {manager: [players]}, "picks": {manager:
    [picks he gets]}, "when": text}]. See the module docstring."""
    from . import move_ledger as ml
    from . import transaction_log as tl
    from .jsonl_log import LogCorrupt
    base = Path(base)
    try:
        ents = [e for e in ml.entries(ml.read_rows(base)) if e["kind"] == "trade" and not e["voided"]]
        logs = [t for t in tl.transactions(base) if t["type"] == "trade"]
    except (ml.LedgerError, LogCorrupt, tl.TransactionLogError) as e:
        raise PromptsRefused(f"cannot read the trades: {e}") from None
    managers = set(cfg["managers"])

    def first_day(w):
        rows = [x for x in schedule.get("weeks", []) if x.get("week") == w]
        return str(rows[0]["start_date"])[:10] if rows else None

    def pair(sides):
        return frozenset(sides)

    for e in ents:
        if not set(_ledger_sides(e)) <= managers:
            raise PromptsRefused(f"ledger entry {e['id']} names a manager not in the config")
    by_window = {}
    for e in ents:
        k = (int(e["window_week"]), pair(_ledger_sides(e)))
        if k in by_window:
            raise PromptsRefused(f"ledger entries {by_window[k]['id']} and {e['id']} are both trades "
                                 f"between {' and '.join(sorted(k[1]))} taking effect in week "
                                 f"{k[0]}'s window: they cannot be paired with Yahoo's log")
        by_window[k] = e
    log_by_window = {}
    for t in logs:
        w = t.get("fantasy_week")
        if w is None:
            continue
        sides = _log_sides(t)
        if t["league_day"] != first_day(w):
            if w == week:
                raise PromptsRefused(f"Yahoo trade {t['key']} ({_describe(sides)}) was made "
                                     f"{_pacific(t['time'])}, outside week {w}'s Monday window: a "
                                     "trade takes effect only in a Monday window (rule 13). "
                                     "Resolve it with the commissioner first")
            continue
        k = (int(w), pair(sides))
        if k in log_by_window:
            raise PromptsRefused(f"Yahoo trades {log_by_window[k][0]['key']} and {t['key']} are both "
                                 f"between {' and '.join(sorted(k[1]))} in week {w}'s window")
        log_by_window[k] = (t, sides)

    out = []
    for (w, p), e in sorted(by_window.items(), key=lambda kv: kv[1]["id"]):
        if int(e["claim_week"]) != week and w != week:
            continue
        hit = log_by_window.get((w, p))
        if hit and not _agree(_ledger_sides(e), hit[1]):
            raise PromptsRefused(f"the move ledger and Yahoo's log disagree: ledger entry {e['id']} "
                                 f"({_describe(_ledger_sides(e))}) vs Yahoo trade {hit[0]['key']} "
                                 f"({_describe(hit[1])})")
        if int(e["claim_week"]) == week:
            when = (f"agreed in the group chat {_pacific(e['claimed_at'])}; takes effect in the "
                    f"Monday {e['window']} window")
            if hit:
                when += f", made in Yahoo {_pacific(hit[0]['time'])}"
            out.append({"sides": _ledger_sides(e), "picks": {}, "when": when})
    for (w, p), (t, sides) in sorted(log_by_window.items(), key=lambda kv: kv[1][0]["timestamp"]):
        if w == week and (w, p) not in by_window:
            if not set(sides) <= managers:
                raise PromptsRefused(f"Yahoo trade {t['key']} names a manager not in the config")
            out.append({"sides": sides, "picks": {},
                        "when": f"made in Yahoo {_pacific(t['time'])}, in the Monday window"})

    if wcti is not None:
        out = _merge_wcti(base, wcti, cfg, week, out)
    for tr in out:
        for m in set(tr["sides"]) | set(tr["picks"]):
            if not tr["sides"].get(m) and not tr["picks"].get(m):
                raise PromptsRefused(f"a week {week} trade gives {m} nothing")
    return out


def _merge_wcti(base: Path, rel: Path, cfg: dict, week: int, trades: list) -> list:
    ctx = _read_json(base, rel)
    if not isinstance(ctx, dict):
        raise PromptsRefused(f"{rel.as_posix()} is not a JSON object")
    if "week" in ctx and ctx["week"] != week:
        raise PromptsRefused(f"{rel.as_posix()} says week {ctx['week']!r}")
    if "season_year" in ctx and ctx["season_year"] != cfg["season"]["current_long"]:
        raise PromptsRefused(f"{rel.as_posix()} says season {ctx['season_year']!r}")
    raw = ctx.get("trades") or []
    if not isinstance(raw, list):
        raise PromptsRefused(f"{rel.as_posix()} trades is not a list")
    out = [dict(t, picks=dict(t["picks"])) for t in trades]
    seen = set()
    for i, t in enumerate(raw, start=1):
        a, b = t.get("manager_a"), t.get("manager_b")
        if a not in cfg["managers"] or b not in cfg["managers"] or a == b:
            raise PromptsRefused(f"{rel.as_posix()} trade {i}: managers {a!r} and {b!r}")
        p = frozenset((a, b))
        if p in seen:
            raise PromptsRefused(f"{rel.as_posix()} has two trades between {a} and {b}")
        seen.add(p)
        gets = {b: list(t.get("sends_a") or []), a: list(t.get("sends_b") or [])}
        players = {m: [x for x in v if not PICK_RE.match(str(x).strip())] for m, v in gets.items()}
        picks = {m: [str(x).strip() for x in v if PICK_RE.match(str(x).strip())] for m, v in gets.items()}
        match = [x for x in out if frozenset(x["sides"]) == p]
        if match:
            if not _agree(match[0]["sides"], players):
                raise PromptsRefused(f"{rel.as_posix()} trade {i} ({_describe(players)}) disagrees "
                                     f"with the week {week} trade ({_describe(match[0]['sides'])})")
            match[0]["picks"] = picks
        elif any(players.values()):
            raise PromptsRefused(f"{rel.as_posix()} trade {i} names players ({_describe(players)}), "
                                 f"but neither the move ledger nor Yahoo's log has a week {week} "
                                 f"trade between {a} and {b}")
        else:
            out.append({"sides": {a: [], b: []}, "picks": picks,
                        "when": f"picks only, from {rel.as_posix()}"})
    return out


def trade_block(trades: list, week: int, template_block: list) -> list:
    """The Part 3 trade block's lines, the template's grade rule kept."""
    if GRADE_LINE not in template_block:
        raise PromptsRefused(f"the template's trade block no longer has its grade rule "
                             f"({GRADE_LINE!r})")

    def sends(tr):
        a, b = sorted(set(tr["sides"]) | set(tr["picks"]))
        # what A sends is what B gets
        return [(m, tr["sides"].get(o, []) + tr["picks"].get(o, [])) for m, o in ((a, b), (b, a))]

    if len(trades) == 1:
        tr = trades[0]
        out = [f"**FIRST headline MUST cover the Week {week} trade** "
               f"({tr['when']}):"]
        out += [f"- {m} sends: {', '.join(v)}" for m, v in sends(tr)]
    else:
        out = [f"**The first {len(trades)} headlines MUST cover the Week {week} trades, "
               "one headline each:**"]
        for tr in trades:
            (a, va), (b, vb) = sends(tr)
            out.append(f"- {a}-{b} ({tr['when']}): {a} sends {', '.join(va)}; "
                       f"{b} sends {', '.join(vb)}")
    out.append(GRADE_LINE)
    return out


# =============================================================================
# the template
# =============================================================================

def _conditionals(lines: list, keep: dict) -> list:
    """Resolve [IF ...] / [END IF] blocks. keep: {condition line: None (drop
    the block), True (keep its lines) or [lines] (replace them)}."""
    out, i = [], 0
    while i < len(lines):
        line = lines[i]
        if line.strip().startswith("[IF"):
            cond = line.strip()
            if cond not in keep:
                raise PromptsRefused(f"the template has an unknown condition {cond!r}")
            j = i + 1
            while j < len(lines) and lines[j].strip() != END_IF:
                if lines[j].strip().startswith("[IF"):
                    raise PromptsRefused(f"a condition inside {cond!r}: not supported")
                j += 1
            if j == len(lines):
                raise PromptsRefused(f"the template's {cond!r} has no {END_IF}")
            body = lines[i + 1:j]
            k = keep[cond]
            if callable(k):
                k = k(body)
            if k is True:
                out += body
            elif isinstance(k, list):
                out += k
            elif out and not out[-1].strip() and j + 1 < len(lines) and not lines[j + 1].strip():
                j += 1          # a dropped block takes one of the blank lines around it
            i = j + 1
            continue
        if line.strip() == END_IF:
            raise PromptsRefused(f"the template has an {END_IF} with no [IF ...]")
        out.append(line)
        i += 1
    return out


def fill(template: str, values: dict, conditions: dict) -> str:
    """The template with its hand-only part removed, its conditions resolved
    and every placeholder filled. Anything left over refuses."""
    if template.count(HAND_START) != 1 or template.count(HAND_END) != 1 or \
            template.index(HAND_START) > template.index(HAND_END):
        raise PromptsRefused(f"the template needs one {HAND_START} ... {HAND_END} part")
    body = template[template.index(HAND_END) + len(HAND_END):].lstrip("\n")
    for ph in values:
        if ph not in body:
            raise PromptsRefused(f"the template no longer has the placeholder {ph}")
    lines = _conditionals(body.split("\n"), conditions)
    text = "\n".join(lines)

    def sub(m):
        ph = m.group(0)
        if ph not in values:
            raise PromptsRefused(f"the template has a placeholder the script does not fill: {ph}")
        return values[ph]
    text = re.sub(r"\[FILL IN: [^\]]*\]", sub, text)
    return text


def leftovers(text: str) -> list:
    """Anything a person would still have to fill: must be empty."""
    return [x for x in ("[FILL IN", "[IF", END_IF, HAND_START, HAND_END) if x in text]


def template_uploads(template: str) -> list:
    """The file names in the template's Part 1 upload list (week as N)."""
    part = template.split("## PART 1", 1)[1].split("**Prompt:**", 1)[0]
    names = re.findall(r"(?m)^- `([^`]+)`", part)
    return [n.replace(PH_WEEK, "N") for n in names]


# =============================================================================
# the whole file
# =============================================================================

def build(base, week: int, *, today: date = None, now: datetime = None) -> str:
    """output/prompts_weekN.md's text."""
    if isinstance(week, bool) or not isinstance(week, int) or week < 1:
        raise PromptsRefused(f"--week {week!r}: a week number >= 1")
    base = Path(base)
    if now is None:
        from .league_clock import league_now
        now = league_now()
    if today is None:
        today = now.date()
    from .data_loader import magic_number_from_week

    cfg = load_config(base)
    season, season_long = cfg["season"]["current"], cfg["season"]["current_long"]
    schedule = _read_json(base, Path("config") / "SCHEDULE.json")
    start, end = week_dates(schedule, week, season_long)
    md, data = read_report(base, week, start, end, season_long)
    block = angles_block(md)
    rows = manager_rows(cfg, data, week)
    rlines, rnote = roster_lines(base, cfg, schedule, today)
    wcti = find_wcti(base, week)
    trades = week_trades(base, cfg, schedule, week, wcti)
    try:
        mfrom = magic_number_from_week(cfg["presentation"])
    except ValueError as e:
        raise PromptsRefused(str(e)) from None
    ordinal = ordinal_word(cfg["season"]["league_season_number"])

    uploads = [Path(str(u).format(week=week)) for u in UPLOADS] + ([wcti] if wcti else [])
    missing = [u.as_posix() for u in uploads if not (base / u).is_file()]
    if missing:
        raise PromptsRefused(f"files to upload with Part 1 are missing: {', '.join(missing)}"
                             + (" (make the lore export: python scripts\\review_lore.py --export)"
                                if "output/lore_for_drafting.json" in missing else ""))
    tpl_rel = TEMPLATE
    if not (base / tpl_rel).is_file():
        raise PromptsRefused(f"{tpl_rel.as_posix()} is missing")
    template = (base / tpl_rel).read_text(encoding="utf-8")
    bad = mangled(template)
    if bad:
        raise PromptsRefused(f"{tpl_rel.as_posix()} has mangled characters, line "
                             f"{bad[0][0]}: {bad[0][1]}")
    names = template_uploads(template)
    expect = [u.name.replace(f"week{week}", "weekN") for u in uploads[:len(UPLOADS)]]
    if names != expect + [WCTI_NAME.format(week="N")]:
        raise PromptsRefused(f"the template's Part 1 upload list {names} is not UPLOADS {expect} "
                             "plus the weekly context file")

    t1, t2 = title_dates(start, end)
    s1, s2 = search_dates(start, end)
    values = {
        PH_WEEK: str(week), PH_SEASON: season, PH_START: t1, PH_END: t2,
        PH_TEAMS: str(len(cfg["managers"])), PH_ORDINAL: ordinal,
        PH_MANAGERS: "\n".join(f"| {m} | {team} | {', '.join(stars)} |" for m, team, stars in rows),
        PH_ANGLES: block, PH_S9_START: s1, PH_S9_END: s2, PH_ROSTERS: "\n".join(rlines),
    }
    conditions = {
        IF_WCTI: True if wcti else None,
        IF_TRADES: (lambda body: trade_block(trades, week, body)) if trades else None,
    }
    if not trades:
        # still demand the grade rule, so the block cannot rot unseen in a quiet week
        tb = template.split(IF_TRADES, 1)
        if len(tb) != 2 or GRADE_LINE not in tb[1].split(END_IF, 1)[0]:
            raise PromptsRefused("the template's trade block is missing or lost its grade rule")
    filled = fill(template, values, conditions)
    for x in PH_TRADE_INNER:
        if x in filled:
            raise PromptsRefused(f"{x} survived the fill")

    shown = "the newsletter carries none" if week < mfrom else "magic numbers may appear"
    magic_note = []
    if week < mfrom and "magic number" in block.lower():
        # The block goes in verbatim (it is the report's); say so rather than edit it.
        magic_note = [f"- **Check:** the ANGLES block mentions a magic number in a week {week} report "
                      f"(the report predates the rule, or the rule broke). The template says to leave "
                      "it out and the claim check flags one; for a current week, rerun Step 6.5 so the block drops it."]
        print(magic_note[0][2:])
    up = "\n".join(f"{i}. `{str(u).replace('/', chr(92))}`" for i, u in enumerate(uploads, start=1))
    trade_note = ("none" if not trades else
                  f"{len(trades)} (Part 3's trade block; picks only from "
                  f"data\\weeklycontextinput_week{week}.json"
                  + (", which exists)" if wcti else ", which does not exist: no picks are recorded)"))
    header = "\n".join([
        f"# Newsletter Drafting Prompts -- Week {week}, {season}",
        "",
        f"Filled by `python scripts\\prepare_prompts.py --week {week}` at {_pacific(now.isoformat())} "
        f"from `output\\stats_report_week{week}.md` (generated {data['metadata']['generated_at']}) and "
        f"`templates\\NEWSLETTER_PROMPTS.md`. Use the 3 prompts below in a **separate LLM chat**, in "
        "order. Upload the files listed here with Part 1; they carry through to Parts 2 and 3 in the "
        "same chat. Nothing is left to fill.",
        "",
        "## Upload with Part 1 (each confirmed to exist)",
        "",
        up,
        "",
        "## Pre-flight (done by the script)",
        "",
        f"- **Week {week}**, {t1} to {t2}, season {season} (config\\SCHEDULE.json); the league's "
        f"{ordinal} season (league_season_number).",
        "- **Storylines:** the report's ANGLES block, verbatim, in Part 1.",
        "- **Star players:** each manager's top three in the report's keeper watch, by keep chance.",
        f"- **Trades in week {week}:** {trade_note}.",
        f"- **Rosters:** {rnote}.",
        f"- **Magic numbers:** none before the week {mfrom} report "
        f"(presentation.magic_number_from_week); this is the week {week} report, so {shown}.",
        *magic_note,
        "",
        "---",
        "",
        "",
    ])
    text = header + filled
    if not text.endswith("\n"):
        text += "\n"
    blocks = prompt_blocks(text)
    if len(blocks) < 3 or any(not b.startswith(ONLY_UPLOADED + "\n") for b in blocks[:3]):
        raise PromptsRefused("every part's prompt must open with the uploaded-files-only line "
                             f"({ONLY_UPLOADED!r}): check templates\\NEWSLETTER_PROMPTS.md")
    left = leftovers(text)
    if left:
        raise PromptsRefused(f"the output still has {left}")
    bad = mangled(text.replace(block, ""))
    if bad:
        raise PromptsRefused(f"the output has mangled characters, line {bad[0][0]}: {bad[0][1]}: "
                             f"{bad[0][2][:80]!r}")
    if block not in text:
        raise PromptsRefused("the ANGLES block did not survive the fill byte for byte")
    return text


def output_path(base, week: int) -> Path:
    return Path(base) / "output" / f"prompts_week{week}.md"


def write(base, week: int, out: Path = None, **kw) -> Path:
    text = build(base, week, **kw)
    p = Path(out) if out is not None else output_path(base, week)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_bytes(text.encode("utf-8"))
    tmp.replace(p)
    return p
