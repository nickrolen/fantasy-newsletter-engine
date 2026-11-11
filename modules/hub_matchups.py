"""
hub_matchups.py -- the matchup Summary view's text (hub polish 3, task 48a;
Nick, 11-10).

MONDAY: the newsletter's own paragraph. The issue numbered N previews
fantasy week N+1 (the week-3 issue, sent 11-09, holds week 4's matchups).
Its source is the archived issue as sent (output/hub_archive/, the plaintext
HTML archive_issue.py wrote), parsed at build time with the standard
library's HTML parser; nothing new is written. Inside
<section id="betting-lines">, each matchup is a <div class="matchup-header">
"Team A vs Team B", then the line table, then the paragraph(s) up to the next
header. Each header is matched to a matchup of config/SCHEDULE.json by team
names, in either order. RAISES (SummaryError) when the section is missing, a
header appears twice, a block matches no matchup, or a matchup has no block.
Text only: tags and comments are dropped (lore markers included) and the lore
tag pattern is stripped; the page passes it through live_lines_page.clean.

TUESDAY TO SUNDAY: a paragraph built from the night's numbers, on top, with
Monday's paragraph below it headed "Monday's preview (newsletter line: ...)".
No written prose and no model call: every fact comes from the same run's
inputs (the line, the win-% history, the closing line, the logs' last banked
day, the grid's Availability), and check_numbers() RAISES if any number in
the paragraph is not one of them. Its framing (hub.matchup_framing, required)
is the first that applies: Final, Blowout, Comeback, Lead change, Close,
Steady. Each framing has at least three phrasings, chosen by a hash of
(season, week, league day, matchup), so a rerun is byte-identical.

Voice: plain, short, factual; no causation the numbers do not show ("his top
scorer was X" is fine, "X won it" is not). Two to four sentences.
"""

from __future__ import annotations

import hashlib
import re
from html.parser import HTMLParser
from pathlib import Path
from typing import Dict, List, Optional

FRAMINGS = ("final", "blowout", "comeback", "lead_change", "close", "steady")
FRAMING_KEYS = ("blowout_win_pct", "comeback_close_below", "comeback_now_at", "comeback_rise_points",
                "comeback_rise_was_below", "close_low", "close_high")
WAITING = "Monday's preview arrives with the newsletter."
NO_ISSUE_WEEK1 = "No newsletter previewed week 1: the first issue previewed week 2."


class SummaryError(RuntimeError):
    """The newsletter's betting-lines section cannot be read as the matchups
    of the week, or a paragraph states a number its inputs do not hold."""


def framing_config(league_config: dict = None) -> dict:
    """league_config.json -> hub.matchup_framing. Every key required, a
    number from 0 to 100; missing or malformed RAISES."""
    if league_config is None:
        from .data_loader import _LEAGUE_CONFIG as league_config
    blk = (league_config.get("hub") or {}).get("matchup_framing")
    if not isinstance(blk, dict):
        raise SummaryError("config/league_config.json has no hub.matchup_framing block")
    out = {}
    for k in FRAMING_KEYS:
        v = blk.get(k)
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not 0 <= v <= 100:
            raise SummaryError(f"config/league_config.json hub.matchup_framing.{k} must be a number "
                               f"from 0 to 100, not {v!r}")
        out[k] = float(v)
    if out["close_low"] >= out["close_high"]:
        raise SummaryError("hub.matchup_framing: close_low must be below close_high")
    return out


# =============================================================================
# Monday: the newsletter's paragraph
# =============================================================================

class _Lines(HTMLParser):
    """The betting-lines section: [{"header", "cells": [[...]], "paras": [...]}]."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.depth = 0            # nesting inside the section (0 = outside)
        self.found = 0
        self.blocks: List[dict] = []
        self.mode = None          # "header" | "cell" | "p"
        self.buf: List[str] = []
        self.row: Optional[list] = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if self.depth:
            self.depth += 1 if tag not in _VOID else 0
            cls = (a.get("class") or "").split()
            if tag == "div" and "matchup-header" in cls:
                self.mode, self.buf = "header", []
            elif tag == "tr" and self.blocks:
                self.row = []
            elif tag in ("td", "th") and self.row is not None:
                self.mode, self.buf = "cell", []
            elif tag == "p" and self.blocks:
                self.mode, self.buf = "p", []
            return
        if tag == "section" and a.get("id") == "betting-lines":
            self.depth, self.found = 1, self.found + 1

    def handle_endtag(self, tag):
        if not self.depth:
            return
        text = re.sub(r"\s+", " ", "".join(self.buf)).strip()
        if tag == "div" and self.mode == "header":
            self.blocks.append({"header": text, "cells": [], "paras": []})
            self.mode = None
        elif tag in ("td", "th") and self.mode == "cell":
            self.row.append(text)
            self.mode = None
        elif tag == "tr" and self.row is not None:
            self.blocks[-1]["cells"].append(self.row)
            self.row = None
        elif tag == "p" and self.mode == "p":
            if text:
                self.blocks[-1]["paras"].append(text)
            self.mode = None
        if tag not in _VOID:
            self.depth -= 1

    def handle_data(self, data):
        if self.depth and self.mode:
            self.buf.append(data)

    def handle_comment(self, data):        # comments (lore markers among them) never reach the text
        return


_VOID = {"br", "img", "hr", "meta", "link", "input", "col", "wbr", "source", "area", "base", "embed"}


def _strip_lore(text: str) -> str:
    from .live_lines_page import LORE_TAG
    return re.sub(r"\s+", " ", LORE_TAG.sub("", text)).strip()


def newsletter_line(cells: list) -> str:
    """The line the newsletter printed, from its table: the favourite's spread
    and moneyline and the total, as printed ("Luka my Balls -111.0 / -205,
    O/U 3200"). Header row: Team, Spread, Total, Moneyline, ..."""
    if len(cells) < 3:
        raise SummaryError("a betting-lines table has fewer than two team rows")
    head = [c.lower() for c in cells[0]]
    try:
        it, isp, itot, iml = (head.index(k) for k in ("team", "spread", "total", "moneyline"))
    except ValueError:
        raise SummaryError(f"a betting-lines table's header is {cells[0]}, not Team/Spread/Total/Moneyline")
    rows = cells[1:3]
    fav = [r for r in rows if r[isp].startswith("-")]
    r = fav[0] if fav else rows[0]
    total = re.sub(r"^[ou]", "", r[itot])
    return f"{r[it]} {r[isp]} / {r[iml]}, O/U {total}"


def newsletter_blocks(html_text: str, matchups: list, team_of: dict, issue: int) -> dict:
    """{(manager_a, manager_b): {"paragraphs": [...], "line": text}} for the
    week the issue previews. matchups: the schedule's for that week."""
    p = _Lines()
    p.feed(html_text)
    p.close()
    where = f"issue {issue} (output/hub_archive)"
    if p.found == 0:
        raise SummaryError(f"{where} has no <section id=\"betting-lines\">")
    if p.found > 1:
        raise SummaryError(f"{where} has {p.found} betting-lines sections")
    heads = [b["header"] for b in p.blocks]
    dup = sorted({h for h in heads if heads.count(h) > 1})
    if dup:
        raise SummaryError(f"{where}: matchup header(s) {dup} appear twice")
    out = {}
    for b in p.blocks:
        parts = [x.strip() for x in re.split(r"\s+vs\.?\s+", b["header"])]
        hit = None
        if len(parts) == 2:
            for mu in matchups:
                ta, tb = team_of[mu["manager_a"]], team_of[mu["manager_b"]]
                if {ta, tb} == set(parts) and ta != tb:
                    hit = (mu["manager_a"], mu["manager_b"])
        if hit is None:
            raise SummaryError(f"{where}: the block \"{b['header']}\" matches no matchup of that week")
        paras = [_strip_lore(x) for x in b["paras"]]
        paras = [x for x in paras if x]
        if not paras:
            raise SummaryError(f"{where}: the block \"{b['header']}\" has no paragraph")
        out[hit] = {"paragraphs": paras, "line": newsletter_line(b["cells"])}
    for mu in matchups:
        if (mu["manager_a"], mu["manager_b"]) not in out:
            raise SummaryError(f"{where}: the matchup {team_of[mu['manager_a']]} vs "
                               f"{team_of[mu['manager_b']]} has no block")
    return out


def monday_preview(base, week: int, matchups: list, team_of: dict, index: dict) -> dict:
    """{"state": "issue" | "waiting" | "none", "text", "by": {pair: block}}
    for `week`: issue week-1 from the archive index (hub_archive.load_index)."""
    if int(week) <= 1:
        return {"state": "none", "text": NO_ISSUE_WEEK1, "by": {}}
    entry = [e for e in index.get("issues", []) if int(e["week"]) == int(week) - 1]
    if not entry:
        return {"state": "waiting", "text": WAITING, "by": {}}
    from .hub_archive import archive_dir
    path = archive_dir(base) / entry[0]["plain"]
    if not path.is_file():
        raise SummaryError(f"{path} is missing: the archived issue {int(week) - 1} cannot be read")
    by = newsletter_blocks(path.read_text(encoding="utf-8"), matchups, team_of, int(week) - 1)
    return {"state": "issue", "text": "", "by": by}


# =============================================================================
# Tuesday to Sunday: the night's paragraph
# =============================================================================

def _p1(x) -> str:
    return f"{float(x):.1f}"


def _pts(x) -> str:
    """Points as the paragraph prints them: one decimal (the newsletter's own
    habit). A margin is always the difference of the two PRINTED scores
    (_margin), so the paragraph's arithmetic checks out to the reader."""
    return f"{float(x):,.1f}"


def _margin(x, y) -> str:
    m = round(abs(round(float(x), 1) - round(float(y), 1)), 1)
    return f"{m:,.1f}" if m > 0 else f"{abs(float(x) - float(y)):,.2f}"


def _games(x) -> str:
    v = round(float(x))
    return f"{v}"


def pick_framing(f: dict, cfg: dict) -> str:
    """The first framing that applies (the brief's table, in order)."""
    if f["final"]:
        return "final"
    if max(f["win_a"], f["win_b"]) >= cfg["blowout_win_pct"]:
        return "blowout"
    if f.get("close_a") is not None:
        for s in ("a", "b"):
            if f[f"close_{s}"] < cfg["comeback_close_below"] and f[f"win_{s}"] >= cfg["comeback_now_at"]:
                return "comeback"
    if f.get("prev_a") is not None:
        for s in ("a", "b"):
            # a rise counts only for the team that was the underdog at the last
            # run (Nick, 11-10): a favourite growing its lead is no comeback
            if f[f"prev_{s}"] < cfg["comeback_rise_was_below"] \
                    and f[f"win_{s}"] - f[f"prev_{s}"] >= cfg["comeback_rise_points"]:
                return "comeback"
    if f.get("prev_leader") is not None and f["leader"] is not None and f["leader"] != f["prev_leader"]:
        return "lead_change"
    if all(cfg["close_low"] <= f[f"win_{s}"] <= cfg["close_high"] for s in ("a", "b")):
        return "close"
    return "steady"


VARIANTS = {
    "final": [
        "Final: {W} beat {L}, {ws} to {ls}, by {margin}.",
        "The week is over: {W} {ws}, {L} {ls}, a margin of {margin}.",
        "{W} finished {margin} ahead of {L}, {ws} to {ls}.",
    ],
    "blowout": [
        "{lead} leads {trail} by {margin}, {ls_} to {ts_}, and the line has {lead} at {wl}.",
        "{lead} is {margin} up on {trail}, {ls_} to {ts_}; the line gives him {wl}.",
        "The line has {lead} at {wl}: he leads {trail} {ls_} to {ts_}, by {margin}.",
    ],
    "comeback": [
        "{riser} is back in it: his chance is {wr} now, from {wfrom} {since}.",
        "{riser}'s chance has climbed to {wr}, from {wfrom} {since}.",
        "The line has moved toward {riser}: {wr} now, against {wfrom} {since}.",
    ],
    "lead_change": [
        "{lead} has moved in front since the last update: {ls_} to {ts_} over {trail}, by {margin}.",
        "The lead changed hands since the last update: {lead} {ls_}, {trail} {ts_}.",
        "{lead} now leads {trail} by {margin}, {ls_} to {ts_}, after trailing at the last update.",
    ],
    "close": [
        "It is close: {lead} leads {trail} by {margin}, {ls_} to {ts_}.",
        "{lead} is {margin} ahead of {trail}, {ls_} to {ts_}, and the line has it near even.",
        "A tight one: {lead} {ls_}, {trail} {ts_}, a gap of {margin}.",
    ],
    "steady": [
        "{lead} leads {trail} by {margin}, {ls_} to {ts_}.",
        "{lead} is ahead of {trail}, {ls_} to {ts_}, by {margin}.",
        "{trail} trails {lead} by {margin}, {ts_} to {ls_}.",
    ],
}
TIED = [
    "{a} and {b} are level at {s}.",
    "Nothing separates them: {a} {s}, {b} {s}.",
    "{a} and {b} are tied on {s}.",
]


def _variant(key: str, n: int, season: str, week: int, day: str, pair: tuple) -> int:
    h = hashlib.sha256(f"{season}|{week}|{day}|{pair[0]}|{pair[1]}|{key}".encode()).hexdigest()
    return int(h[:8], 16) % n


def night_paragraph(f: dict, cfg: dict, *, season: str, week: int, day: str) -> dict:
    """{"framing", "text", "numbers"} from the facts `f` (night_facts).
    Deterministic: the phrasing comes from a hash of (season, week, league
    day, matchup). check_numbers() is run on the result before it returns."""
    a, b = f["a"], f["b"]
    fr = pick_framing(f, cfg)
    pair = (a, b)
    S = []
    nums: Dict[str, str] = {}

    def num(s: str) -> str:
        nums[s] = s
        return s

    if fr == "final":
        W, L = (a, b) if f["banked_a"] > f["banked_b"] else (b, a)
        if f["banked_a"] == f["banked_b"]:
            S.append(f"Final: {a} and {b} tied at {num(_pts(f['banked_a']))}.")
        else:
            ws, ls = f[f"banked_{'a' if W == a else 'b'}"], f[f"banked_{'a' if L == a else 'b'}"]
            v = VARIANTS["final"][_variant("final", 3, season, week, day, pair)]
            S.append(v.format(W=W, L=L, ws=num(_pts(ws)), ls=num(_pts(ls)), margin=num(_margin(ws, ls))))
        if f.get("close_a") is not None:
            S.append(f"The closing line had {a} at {num(_p1(f['close_a']))}% and {b} at "
                     f"{num(_p1(f['close_b']))}%.")
    else:
        if f["leader"] is None:
            v = TIED[_variant("tied", 3, season, week, day, pair)]
            S.append(v.format(a=a, b=b, s=num(_pts(f["banked_a"]))))
        else:
            lead, trail = f["leader"], (b if f["leader"] == a else a)
            ls_ = f[f"banked_{'a' if lead == a else 'b'}"]
            ts_ = f[f"banked_{'a' if trail == a else 'b'}"]
            margin = _margin(ls_, ts_)
            if fr == "comeback":
                riser, wr, wfrom, since = f["riser"]
                v = VARIANTS["comeback"][_variant("comeback", 3, season, week, day, pair)]
                S.append(v.format(riser=riser, wr=num(_p1(wr)) + "%", wfrom=num(_p1(wfrom)) + "%", since=since))
                S.append(f"{lead} leads {trail} by {num(margin)}, {num(_pts(ls_))} to {num(_pts(ts_))}.")
            else:
                wl = f[f"win_{'a' if lead == a else 'b'}"]
                v = VARIANTS[fr][_variant(fr, 3, season, week, day, pair)]
                S.append(v.format(lead=lead, trail=trail, margin=num(margin), ls_=num(_pts(ls_)),
                                  ts_=num(_pts(ts_)), wl=num(_p1(wl)) + "%"))
        # the line now, and how it moved
        fav = a if f["win_a"] >= f["win_b"] else b
        sf = "a" if fav == a else "b"
        moved = []
        if fr == "comeback":
            pass                                         # the first sentence already says how it moved
        elif f.get("prev_a") is not None:
            moved.append(f"{num(_signed(f['win_' + sf] - f['prev_' + sf]))} since the last update")
        if f.get("close_a") is not None and fr != "comeback":
            moved.append(f"{num(_signed(f['win_' + sf] - f['close_' + sf]))} since the closing line")
        if len(moved) == 2 and moved[0].split(" since ")[0] == moved[1].split(" since ")[0]:
            moved = [moved[0].split(" since ")[0] + " since the last update and the closing line"]
        s2 = f"The line gives {fav} {num(_p1(f['win_' + sf]))}%"
        s2 += (" (" + ", ".join(moved) + ")") if moved else ""
        s2 += (f", with {num(_games(f['games_left_a']))} games left for {a} and "
               f"{num(_games(f['games_left_b']))} for {b}.") if f.get("games_left_a") is not None else "."
        if f["last_day"]:
            s2 = s2[:-1] + f"; {f['today_name']} is the last day."
        S.append(s2)
    # the last banked day
    sw = f.get("swing")
    if sw:
        def side(m, s):
            top = sw[f"top_{s}"]
            if not (top and top["player"]) and float(sw["pts_" + s]) == 0:
                return f"{m} had no games"
            t = f"{m} scored {num(_pts(sw['pts_' + s]))}"
            if top and top["player"]:
                t += f" (his top scorer was {top['player']}, {num(_pts(top['points']))})"
            return t
        sa, sb = side(a, "a"), side(b, "b")
        if sa.endswith("had no games") and sb.endswith("had no games"):
            S.append(f"Neither team had a game on {sw['day_name']}.")
        else:
            S.append(f"On {sw['day_name']}, {sa} and {sb}.")
    outs = [x for x in (f.get("out_a"), f.get("out_b")) if x]
    if outs and fr != "final":
        S.append(" ".join(outs))
    text = " ".join(S[:4]) if len(S) <= 4 else " ".join(S[:3] + [S[-1]])
    check_numbers(text, set(nums.values()) | set(f.get("_extra_numbers") or ()))
    return {"framing": fr, "text": text, "numbers": sorted(nums.values())}


def _signed(x: float) -> str:
    v = round(float(x), 1)
    return f"up {abs(v):.1f} points" if v > 0 else f"down {abs(v):.1f} points" if v < 0 else "unchanged"


NUMBER = re.compile(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?")


def check_numbers(text: str, allowed: set) -> None:
    """Every number in `text` must be one of the inputs' formatted numbers
    (the strings the paragraph was built from, like check_draft's claim
    check): otherwise SummaryError. Names that contain digits are allowed by
    being in `allowed` too."""
    allowed_nums = set()
    for a in allowed:
        allowed_nums.update(NUMBER.findall(str(a)))
    bad = [x for x in NUMBER.findall(text) if x not in allowed_nums]
    if bad:
        raise SummaryError(f"the matchup paragraph states {bad}, which no input holds: {text!r}")


def out_text(manager: str, rows: list) -> str:
    """"Nick is without Edwards (all 4 of his games) and White (2 of 3,
    back 11-14)." from [(player, missed, games, back or None)]."""
    if not rows:
        return ""
    parts = []
    for name, missed, games, back in rows:
        t = f"{name} (all {games} of his games" if missed == games else f"{name} ({missed} of {games}"
        if back:
            t += f", back {back}"
        parts.append(t + ")")
    joined = parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " and " + parts[-1]
    return f"{manager} is without {joined} for the rest of the week."


# =============================================================================
# the views: this week's and last week's matchups (48a, 48b, 48c)
# =============================================================================

def _orient(ln: dict, a: str, b: str) -> dict:
    """A line (or history matchup) as seen from (a, b): keys *_a are a's."""
    if (ln["manager_a"], ln["manager_b"]) == (a, b):
        return ln
    if (ln["manager_a"], ln["manager_b"]) == (b, a):
        out = {}
        for k, v in ln.items():
            out[k[:-2] + "_b" if k.endswith("_a") else k[:-2] + "_a" if k.endswith("_b") else k] = v
        return out
    raise SummaryError(f"no line for {a} vs {b}")


def _find(lines: list, a: str, b: str) -> Optional[dict]:
    for ln in lines:
        if {ln["manager_a"], ln["manager_b"]} == {a, b}:
            return _orient(ln, a, b)
    return None


def week_flow(data, week: int, as_of, team_projections=None) -> dict:
    """From the logs (week_state, the line's own banking): {"banked": {manager:
    {iso: points}}, "top": {manager: {iso: {"player", "points"}}}} for the
    week's days before as_of."""
    from . import week_state as ws
    st = ws.week_state(data, week, as_of, team_projections)
    out = {"banked": {}, "top": {}, "total": {}}
    for m in st.banked:
        bd = st.banked_by_day.get(m) or {}
        out["banked"][m] = {d.isoformat(): round(float(bd.get(d, 0.0)), 2) for d in st.completed}
        out["total"][m] = float(st.banked[m])
        tops = {}
        for d in st.completed:
            per = (st.by_day_player.get(m) or {}).get(d) or {}
            if per:
                nm = sorted(per, key=lambda x: (-per[x], x))[0]
                tops[d.isoformat()] = {"player": nm, "points": round(float(per[nm]), 2)}
            else:
                tops[d.isoformat()] = {"player": None, "points": 0.0}
        out["top"][m] = tops
    return out


def outs_for(av, manager: str, days) -> list:
    """[(player, games missed, games, "MM-DD" or None)] for his roster
    players (not in an IL slot) out for some or all of his remaining games:
    the grid's Availability rule; an injury entry's return date if any."""
    from .hub_state import override_back
    il = av.il.get(manager) or {}
    rows = []
    for nme in av.rosters.get(manager, []):
        if nme in il:
            continue
        g = [d for d in days if av.has_game(nme, d)]
        miss = [d for d in g if av.out(nme, d)]
        if not miss:
            continue
        e = av.override_covers(nme, g)
        back = override_back(e, av.weeks) if e is not None else None
        rows.append((nme, len(miss), len(g), f"{back.month:02d}-{back.day:02d}" if back else None))
    return sorted(rows, key=lambda r: (-r[1], r[0]))


def night_facts(a: str, b: str, ln: dict, prev: Optional[dict], close: Optional[dict], swing: Optional[dict],
                out_a: str, out_b: str, last_day: bool, today_name: str, final: bool) -> dict:
    """The facts a paragraph may use (the brief's list), every one from the
    same run's inputs; oriented to (a, b)."""
    lead = a if ln["banked_a"] > ln["banked_b"] else b if ln["banked_b"] > ln["banked_a"] else None
    f = {"a": a, "b": b, "final": final, "banked_a": float(ln["banked_a"]), "banked_b": float(ln["banked_b"]),
         "win_a": float(ln["win_prob_a"]), "win_b": float(ln["win_prob_b"]), "leader": lead,
         "games_left_a": ln.get("games_left_a"), "games_left_b": ln.get("games_left_b"),
         "swing": swing, "out_a": out_a, "out_b": out_b, "last_day": last_day, "today_name": today_name,
         "_extra_numbers": [x for x in (out_a, out_b) if x]}
    if prev is not None:
        f["prev_a"], f["prev_b"] = float(prev["win_prob_a"]), float(prev["win_prob_b"])
        pa, pb = float(prev["banked_a"]), float(prev["banked_b"])
        f["prev_leader"] = a if pa > pb else b if pb > pa else None
    else:
        f["prev_a"] = f["prev_b"] = f["prev_leader"] = None
    if close is not None:
        f["close_a"], f["close_b"] = float(close["win_prob_a"]), float(close["win_prob_b"])
    else:
        f["close_a"] = f["close_b"] = None
    return f


def _add_riser(f: dict, cfg: dict) -> None:
    for s in ("a", "b"):
        m = f[s]
        if f["close_a"] is not None and f[f"close_{s}"] < cfg["comeback_close_below"] \
                and f[f"win_{s}"] >= cfg["comeback_now_at"]:
            f["riser"] = (m, f[f"win_{s}"], f[f"close_{s}"], "at the closing line")
            return
    for s in ("a", "b"):
        if f["prev_a"] is not None and f[f"prev_{s}"] < cfg["comeback_rise_was_below"] \
                and f[f"win_{s}"] - f[f"prev_{s}"] >= cfg["comeback_rise_points"]:
            f["riser"] = (f[s], f[f"win_{s}"], f[f"prev_{s}"], "at the last update")
            return


NIGHT_FILE = Path("output") / "night_paragraph.json"


def night_path(base) -> Path:
    return Path(base) / NIGHT_FILE


def read_night(base):
    """The stored nightly paragraphs (output/night_paragraph.json), or None."""
    p = night_path(base)
    if not p.is_file():
        return None
    import json as _json
    blob = _json.loads(p.read_text(encoding="utf-8"))
    if blob.get("schema") != 1 or not isinstance(blob.get("paras"), dict):
        raise SummaryError(f"{NIGHT_FILE.as_posix()} is not a schema-1 night-paragraph file")
    return blob


def write_night(base, night: dict, *, run_id: str) -> Path:
    """Store the nightly run's paragraphs (decisions 2-3, Step 3a): written
    ONLY by the nightly run's hub step (modules/nightly.step_hub; a test pins
    it), read by every later build that day. League state (the manifest)."""
    from .data_loader import atomic_write_json
    blob = dict(night)
    blob["schema"] = 1
    blob["run_id"] = run_id
    p = night_path(base)
    atomic_write_json(p, blob, indent=1)
    return p


def prev_nightly_row(rows: list, line_at):
    """The win-% row the nightly paragraph's "since the last update" compares
    against (decision 2, Step 3a): the latest NIGHTLY run's row before the line
    being described. A daytime refresh's or a pre-tip run's row never stands in
    for last night, so a midday entry cannot hide the day's real move."""
    from datetime import datetime as _dt
    before = [r for r in rows if _dt.fromisoformat(r["as_of"]) < line_at and r.get("trigger") == "nightly"]
    return before[-1] if before else None


def stored_para(stored, week: int, a: str, b: str):
    """The nightly run's stored paragraph for a vs b in `week`, as stored
    (byte for byte), or None (another week's, or none stored)."""
    if stored is None or int(stored.get("week", -1)) != int(week):
        return None
    kept = (stored.get("paras") or {}).get(f"{a}|{b}")
    return dict(kept) if kept is not None else None


def build_views(base, data, *, week: int, line: dict, av, now, archive_index: dict, tz,
                night: str = "build") -> dict:
    """{"cards_views": [{"sum", "win", "flow"} per card of this week's line],
    "last": the last week's block or None, "views": [view, ...], "night": the
    built paragraphs (night="build") or None}. Every string is final;
    hub_page prints them.

    night (Step 3a, decisions 2-3): "build" builds the Tuesday-to-Sunday
    paragraph, comparing against the previous NIGHTLY win-% row (a daytime
    refresh's row never hides the day's move); "reuse" shows the stored one
    (output/night_paragraph.json) byte for byte when it is this week's, else
    none. Only the nightly run builds AND stores it; a refresh or a pre-tip
    run reuses it."""
    from . import hub_charts as hc, winprob_history as wh
    from .data_loader import MANAGER_TO_TEAM, CURRENT_SEASON
    from .week_state import week_entry
    from datetime import date as _date, datetime as _dt, timedelta as _td, time as _time
    import json as _json
    base = Path(base)
    cfg = framing_config()
    views = []

    def closing_of(w):
        p = base / "output" / f"closing_line_week{w}.json"
        return _json.loads(p.read_text(encoding="utf-8")) if p.is_file() else None

    def preview_paras(prev_block, a, b):
        if prev_block["state"] != "issue":
            return [{"head": "Monday's preview", "text": prev_block["text"]}]
        blk = prev_block["by"].get((a, b)) or prev_block["by"].get((b, a))
        if blk is None:
            raise SummaryError(f"the newsletter has no block for {a} vs {b}")
        return [{"head": f"Monday's preview (newsletter line: {blk['line']})", "text": t}
                for t in blk["paragraphs"][:1]] + [{"head": "", "text": t} for t in blk["paragraphs"][1:]]

    def add_views(w, i, a, b, entry, *, back, back_label, paras, win_points, flow_banked, flow_exp,
                  sub):
        ids = {k: f"v-mu{w}-{i}-{k}" for k in ("sum", "win", "flow")}
        title = f"{MANAGER_TO_TEAM.get(a, a)} vs {MANAGER_TO_TEAM.get(b, b)}"
        views.append({"id": ids["sum"], "back": back, "back_label": back_label, "title": title,
                      "sub": f"Week {w} \u00b7 Summary \u00b7 {sub}", "kind": "summary", "paras": paras})
        views.append({"id": ids["win"], "back": back, "back_label": back_label, "title": title,
                      "sub": f"Week {w} \u00b7 Win % over the week", "kind": "chart",
                      "chart": hc.winprob_chart(entry, a, b, win_points, tz)})
        gf = hc.gameflow_chart(entry, a, b, flow_banked, flow_exp)
        views.append({"id": ids["flow"], "back": back, "back_label": back_label, "title": title,
                      "sub": f"Week {w} \u00b7 Game flow", "kind": "chart",
                      "chart": {k: v for k, v in gf.items() if not k.startswith("_")}, "_gf": gf})
        return ids

    # ------------------------------------------------------------- this week
    entry = week_entry(data, week)
    first = _date.fromisoformat(str(entry["start_date"])[:10])
    mus = entry.get("matchups", [])
    prev_block = monday_preview(base, week, mus, MANAGER_TO_TEAM, archive_index)
    rows = wh.read(base, week)
    closing = closing_of(week)
    line_at = _dt.fromisoformat(line["generated_at"])
    prev_row = prev_nightly_row(rows, line_at)
    if night not in ("build", "reuse"):
        raise ValueError(f"night must be 'build' or 'reuse', not {night!r}")
    stored = read_night(base) if night == "reuse" else None
    if stored is not None and int(stored.get("week", -1)) != int(week):
        stored = None
    built = {}
    completed = list(line.get("completed_dates") or [])
    remaining = [_date.fromisoformat(x) for x in line.get("remaining_dates") or []]
    has_daily = all("daily_banked_a" in ln and "daily_expected_a" in ln for ln in line["lines"])
    logs = None if has_daily else week_flow(data, week, _date.fromisoformat(str(line["as_of"])[:10]))
    today = now.date()
    cards = []
    for i, ln0 in enumerate(line["lines"]):
        a, b = ln0["manager_a"], ln0["manager_b"]
        ln = ln0
        if has_daily:
            banked = {a: dict(ln["daily_banked_a"]), b: dict(ln["daily_banked_b"])}
            expected = {a: dict(ln["daily_expected_a"]), b: dict(ln["daily_expected_b"])}
            tops = {a: ln.get("top_day_a"), b: ln.get("top_day_b")}
        else:
            banked = {m: logs["banked"][m] for m in (a, b)}
            expected = None
            tops = {m: ({"date": completed[-1], **logs["top"][m][completed[-1]]} if completed else None)
                    for m in (a, b)}
        for m, s in ((a, "a"), (b, "b")):                    # the line's own banked, by day (48c test)
            if abs(sum(banked[m].values()) - float(ln[f"banked_{s}"])) > 0.01 * max(1, len(banked[m])):
                raise SummaryError(f"week {week} {m}: the days' banked points add to "
                                   f"{sum(banked[m].values()):.2f}, the line says {ln[f'banked_{s}']}")
            if expected is not None and abs(float(ln[f"banked_{s}"]) + sum(expected[m].values())
                                            - float(ln[f"projected_final_{s}"])) > 0.01 * max(1, len(expected[m])):
                raise SummaryError(f"week {week} {m}: the expected days do not end at projected_final")
        win_points = hc.winprob_points(a, b, rows, closing, None)
        paras = []
        if night == "reuse":
            kept = stored_para(stored, week, a, b)
            if kept is not None:
                paras.append(kept)
        elif today != first and completed:
            prev = _find(prev_row["matchups"], a, b) if prev_row else None
            close = _find(closing["lines"], a, b) if closing else None
            last = completed[-1]
            dname = _date.fromisoformat(last).strftime("%A")
            swing = {"day_name": dname, "pts_a": banked[a][last], "pts_b": banked[b][last],
                     "top_a": tops[a], "top_b": tops[b]}
            ot_a = out_text(a, outs_for(av, a, remaining))
            ot_b = out_text(b, outs_for(av, b, remaining))
            f = night_facts(a, b, ln, prev, close, swing, ot_a, ot_b, len(remaining) == 1,
                            remaining[0].strftime("%A") if remaining else "", False)
            _add_riser(f, cfg)
            para = night_paragraph(f, cfg, season=CURRENT_SEASON, week=week, day=today.isoformat())
            paras.append({"head": f"Tonight's update \u00b7 {now.strftime('%a')} {now.month:02d}-{now.day:02d}",
                          "text": para["text"], "framing": para["framing"]})
            built[f"{a}|{b}"] = dict(paras[-1])
        paras += preview_paras(prev_block, a, b)
        ids = add_views(week, i, a, b, entry, back="v-main", back_label="Hub", paras=paras,
                        win_points=win_points, flow_banked=banked, flow_exp=expected,
                        sub=f"{len(completed)} of {len(completed) + len(remaining)} days banked")
        gf = views[-1]["_gf"]
        for m, s in ((a, "a"), (b, "b")):
            if expected is not None and abs(gf["_ends"][m] - float(ln[f"projected_final_{s}"])) > \
                    0.01 * max(1, len(expected[m])):
                raise SummaryError(f"week {week} {m}: the game flow's dashed end {gf['_ends'][m]:.2f} is not "
                                   f"projected_final {ln[f'projected_final_{s}']}")
        cards.append(ids)

    # ------------------------------------------------------------- last week
    last_block = None
    lw = week - 1
    if lw >= 1:
        e2 = week_entry(data, lw)
        end2 = _date.fromisoformat(str(e2["end_date"])[:10])
        flow = week_flow(data, lw, end2 + _td(days=1))
        pb2 = monday_preview(base, lw, e2.get("matchups", []), MANAGER_TO_TEAM, archive_index)
        rows2 = wh.read(base, lw)
        close2 = closing_of(lw)
        at = _dt.combine(end2 + _td(days=1), _time(0), tzinfo=tz)
        lcards = []
        for i, mu in enumerate(e2.get("matchups", [])):
            a, b = mu["manager_a"], mu["manager_b"]
            fa, fb = flow["total"][a], flow["total"][b]
            final_ln = {"manager_a": a, "manager_b": b, "banked_a": round(fa, 2), "banked_b": round(fb, 2),
                        "win_prob_a": 100.0 if fa > fb else 0.0 if fa < fb else 50.0,
                        "win_prob_b": 0.0 if fa > fb else 100.0 if fa < fb else 50.0}
            close = _find(close2["lines"], a, b) if close2 else None
            last = end2.isoformat()
            swing = {"day_name": end2.strftime("%A"), "pts_a": flow["banked"][a][last],
                     "pts_b": flow["banked"][b][last], "top_a": flow["top"][a][last], "top_b": flow["top"][b][last]}
            f = night_facts(a, b, final_ln, None, close, swing, "", "", False, "", True)
            para = night_paragraph(f, cfg, season=CURRENT_SEASON, week=lw, day=last)
            paras = [{"head": "Final", "text": para["text"], "framing": para["framing"]}]
            paras += preview_paras(pb2, a, b)
            win_points = hc.winprob_points(a, b, rows2, close2, {"at": at, "a": fa, "b": fb})
            ids = add_views(lw, i, a, b, e2, back="v-last", back_label="Last week's matchups", paras=paras,
                            win_points=win_points, flow_banked={a: flow["banked"][a], b: flow["banked"][b]},
                            flow_exp=None, sub="final")
            lead = a if fa > fb else b if fb > fa else None
            # the margin of the PRINTED scores, so the card's arithmetic checks out
            result = (f"Final: {lead} by {hc.pts(abs(round(fa) - round(fb)))}" if lead else "Final: tied")
            lcards.append({"a": {"team": MANAGER_TO_TEAM.get(a, a), "manager": a, "score": hc.pts(fa)},
                           "b": {"team": MANAGER_TO_TEAM.get(b, b), "manager": b, "score": hc.pts(fb)},
                           "result": result, "views": ids})
        w0 = _date.fromisoformat(str(e2["start_date"])[:10])
        last_block = {"view": "v-last", "link": "Last week's matchups",
                      "title": f"Week {lw} \u00b7 {w0:%b} {w0.day}\u2013"
                               + (f"{end2.day}" if end2.month == w0.month else f"{end2:%b} {end2.day}"),
                      "cards": lcards,
                      "note": "How last week ended. These stay here until next Monday's first update after "
                              "this week's final."}
    for v in views:
        v.pop("_gf", None)
    out_night = ({"week": int(week), "league_day": today.isoformat(), "paras": built}
                 if night == "build" else None)
    return {"cards_views": cards, "last": last_block, "views": views, "night": out_night}
