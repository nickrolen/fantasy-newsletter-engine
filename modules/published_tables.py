"""
published_tables.py -- reconcile every table in a published newsletter.

WHY
---
Historical League Standings published 2021-22 and 2022-23 wrong for a season
(ties on wins went to the first name in a list), and its 1st column added
two pre-data-era titles to a nine-season count. Every number in it looked
plausible on its own. What was wrong was the RELATION between numbers: a
summary column that did not count the cells beside it, a ranking that
disagreed with the stored finishes, a column marked "current" that was not
the current season. Those relations are checkable, so this checks them --
on the published HTML, not on the functions that build it, because the HTML
is what people read and a renderer bug sits between correct data and the page.

Each check knows one table and states its relations. A table nobody wrote a
check for is listed in the result as UNCHECKED, so coverage is visible
rather than assumed.

FINDINGS
--------
Every finding is a reason not to send the page. There are no warnings: a
relation that does not hold is a wrong number in print.

    py scripts/check_published_tables.py output/WEEK1_NEWSLETTER.html
"""

from __future__ import annotations

import html as _html
import json
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Optional

VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link",
        "meta", "source", "track", "wbr"}


# ---------------------------------------------------------------------------
# A small DOM
# ---------------------------------------------------------------------------

@dataclass(eq=False)
class Node:
    tag: str
    attrs: dict
    children: list = field(default_factory=list)
    parent: Optional["Node"] = None

    @property
    def classes(self) -> set:
        return set((self.attrs.get("class") or "").split())

    def text(self) -> str:
        parts = []
        for c in self.children:
            parts.append(c if isinstance(c, str) else c.text())
        return re.sub(r"\s+", " ", "".join(parts)).strip()

    def find_all(self, tag=None, cls=None) -> list:
        out = []
        for c in self.children:
            if isinstance(c, Node):
                if (tag is None or c.tag == tag) and (cls is None or cls in c.classes):
                    out.append(c)
                out.extend(c.find_all(tag, cls))
        return out

    def find(self, tag=None, cls=None):
        hits = self.find_all(tag, cls)
        return hits[0] if hits else None


class _Builder(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node("root", {})
        self.cur = self.root
        self._skip = 0          # inside <script>/<style>

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip += 1
            return
        if self._skip:
            return
        node = Node(tag, dict(attrs), parent=self.cur)
        self.cur.children.append(node)
        if tag not in VOID:
            self.cur = node

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self._skip = max(0, self._skip - 1)
            return
        if self._skip:
            return
        n = self.cur
        while n is not self.root and n.tag != tag:
            n = n.parent
        if n is not self.root:
            self.cur = n.parent

    def handle_data(self, data):
        if not self._skip:
            self.cur.children.append(data)


def parse(doc: str) -> Node:
    b = _Builder()
    b.feed(doc)
    return b.root


# ---------------------------------------------------------------------------
# Findings
# ---------------------------------------------------------------------------

@dataclass
class Finding:
    table: str
    check: str
    detail: str

    def __str__(self):
        return f"[{self.table}] {self.check}: {self.detail}"


def _num(s: str) -> Optional[float]:
    s = s.replace(",", "").replace("%", "").replace("+", "").strip()
    m = re.fullmatch(r"-?\d+(?:\.\d+)?", s)
    return float(m.group(0)) if m else None


def _wl(s: str):
    m = re.fullmatch(r"(\d+)-(\d+)(?:-(\d+))?", s.strip())
    return tuple(int(x) for x in m.groups() if x is not None) if m else None


def _table_rows(t: Node) -> list:
    """[[cell Node, ...], ...] for every <tr>."""
    return [[c for c in tr.children if isinstance(c, Node) and c.tag in ("td", "th")]
            for tr in t.find_all("tr")]


def _heading_before(t: Node, root_doc: str = "") -> str:
    """The nearest section header preceding a table, by walking up and back."""
    n = t
    while n is not None and n.parent is not None:
        sibs = n.parent.children
        i = sibs.index(n)
        for s in reversed(sibs[:i]):
            if isinstance(s, Node):
                for cls in ("sc-mgr-section-header", "section-header", "section-title"):
                    h = s if cls in s.classes else (s.find_all(cls=cls) or [None])[-1]
                    if h is not None:
                        return h.text()
                for tag in ("h1", "h2", "h3", "h4"):
                    h = s if s.tag == tag else (s.find_all(tag) or [None])[-1]
                    if h is not None:
                        return h.text()
        n = n.parent
    return "?"


SEASON = re.compile(r"^\d\d-\d\d$")
PLACE = {"1st": 1, "2nd": 2, "3rd": 3, "4th": 4}


# ---------------------------------------------------------------------------
# Checks: Stats Corner history grids
# ---------------------------------------------------------------------------

def check_history_grid(t: Node, title: str, ctx: dict) -> list:
    """Season-by-season grids: Historical League Standings, Playoff Results,
    Luck Index. Relations:
      - every summary column counts the row's cells of that place;
      - each season column holds each place at most once (a permutation);
      - a column marked current is the newsletter's own season;
      - every completed season before the newsletter's is shown;
      - standings / playoff finishes equal the stored ranks;
      - a CAREER column is the sum of the row (to rounding).
    """
    out = []
    rows = _table_rows(t)
    if not rows:
        return out
    header = [c.text() for c in rows[0]]
    season_cols = [i for i, h in enumerate(header) if SEASON.match(h)]
    seasons = [header[i] for i in season_cols]
    summary = {i: h for i, h in enumerate(header) if h in PLACE or h in ("\U0001F3C6",)}
    is_standings = "Standings" in title
    is_playoffs = "Playoff" in title

    # current marker
    for i in season_cols:
        if "sc-hist-current" in rows[0][i].classes and ctx.get("season"):
            want = ctx["season"][2:]
            if header[i] != want:
                out.append(Finding(title, "current column",
                                   f"{header[i]} is marked as the current season; "
                                   f"this newsletter's season is {want}"))

    # completeness against stored completed seasons
    stored = ctx.get("standings") or {}
    if stored and ctx.get("season") and (is_standings or is_playoffs):
        due = [s[2:] for s in stored if s < ctx["season"]]
        missing = [s for s in due if s not in seasons]
        if missing:
            out.append(Finding(title, "season missing",
                               f"completed season(s) {missing} not shown"))

    # per-row place cells
    place_rows = {}
    for r in rows[1:]:
        if not r:
            continue
        mgr = r[0].text()
        places = []
        for i in season_cols:
            cell = r[i] if i < len(r) else None
            p = None
            if cell is not None:
                for lab, k in PLACE.items():
                    if cell.find_all(cls=f"sc-hist-{lab}") or f"sc-hist-{lab}" in cell.classes:
                        p = k
            places.append(p)
        place_rows[mgr] = places
        for i, lab in summary.items():
            got = _num(r[i].text()) if i < len(r) else None
            k = 1 if lab == "\U0001F3C6" else PLACE[lab]
            want = sum(1 for p in places if p == k)
            if got is None or int(got) != want:
                out.append(Finding(title, f"{lab} column",
                                   f"{mgr} shows {r[i].text() if i < len(r) else '?'}; "
                                   f"the row has {want} {'title' if k == 1 else lab} "
                                   f"cell(s) in the {len(seasons)} seasons shown"))
        if "CAREER" in header:
            ci = header.index("CAREER")
            vals = [_num(r[i].text()) for i in season_cols if i < len(r)]
            vals = [v for v in vals if v is not None]
            got = _num(r[ci].text()) if ci < len(r) else None
            if got is not None and vals and abs(sum(vals) - got) > 0.05 * len(vals) + 1e-9:
                out.append(Finding(title, "CAREER column",
                                   f"{mgr} shows {got:+.1f}; the seasons sum to {sum(vals):+.1f}"))

    if place_rows and (is_standings or is_playoffs):
        for j, s in enumerate(seasons):
            col = [ps[j] for ps in place_rows.values() if ps[j] is not None]
            if len(col) != len(set(col)):
                out.append(Finding(title, "duplicate place",
                                   f"{s}: places {sorted(col)}"))
            full = next((k for k in stored if k[2:] == s), None)
            if full:
                key = "regular_season_rank" if is_standings else "playoff_rank"
                for mgr, ps in place_rows.items():
                    want = (stored[full].get(mgr) or {}).get(key)
                    if ps[j] != want:
                        out.append(Finding(title, "stored finish",
                                           f"{s} {mgr}: shown {ps[j]}, stored {key} {want}"))
    return out


def check_h2h_matrix(t: Node, title: str, ctx: dict) -> list:
    """A beat B w-l  <=>  B beat A l-w. Row totals are returned for the
    profile cross-check."""
    out = []
    rows = _table_rows(t)
    names = [c.text() for c in rows[0]][1:]
    grid = {}
    for r in rows[1:]:
        a = r[0].text()
        for b, c in zip(names, r[1:]):
            grid[(a, b)] = _wl(c.text())
    for (a, b), wl in grid.items():
        if a == b or wl is None:
            continue
        back = grid.get((b, a))
        if back is None or (wl[0], wl[1]) != (back[1], back[0]):
            out.append(Finding(title, "antisymmetry",
                               f"{a} v {b} {wl[0]}-{wl[1]} but {b} v {a} "
                               f"{'missing' if back is None else f'{back[0]}-{back[1]}'}"))
    totals = {}
    for (a, b), wl in grid.items():
        if wl and a != b:
            w, l = totals.get(a, (0, 0))
            totals[a] = (w + wl[0], l + wl[1])
    ctx["_h2h_totals"] = totals
    return out


def check_manager_profiles(root: Node, ctx: dict) -> list:
    """Win % = W/(W+L); rank badges 1..N in win-% order; the record equals
    the H2H matrix's row total (same games, same scope); titles must be
    counted over the same seasons as the record, or say otherwise."""
    title = "Manager Profiles"
    out = []
    cards = root.find_all(cls="sc-mgr-card")
    seen = []
    for card in cards:
        name = (card.find(cls="sc-mgr-name") or Node("x", {})).text()
        badge = (card.find(cls="sc-mgr-rank-badge") or Node("x", {})).text()
        stats = {}
        for item in card.find_all(cls="sc-mgr-stat-item"):
            val = (item.find(cls="sc-mgr-stat-val") or Node("x", {})).text()
            lab = (item.find(cls="sc-mgr-stat-label") or Node("x", {})).text()
            stats[lab or val] = val
        rec = _wl(stats.get("Record", ""))
        pct = _num(stats.get("Win %", ""))
        if rec and pct is not None:
            calc = 100.0 * rec[0] / max(1, rec[0] + rec[1])
            if abs(calc - pct) > 0.051:
                out.append(Finding(title, "win %", f"{name}: {pct}% shown, "
                                   f"{rec[0]}-{rec[1]} is {calc:.1f}%"))
        h2h = ctx.get("_h2h_totals", {}).get(name)
        if rec and h2h and (rec[0], rec[1]) != h2h:
            out.append(Finding(title, "record vs H2H",
                               f"{name}: card {rec[0]}-{rec[1]}, H2H rows sum to "
                               f"{h2h[0]}-{h2h[1]} -- two scopes for one record"))
        titles = next((v for v in stats.values() if re.search(r"\btitles?\b", v)), None)
        if titles and not re.search(r"season|all|since|incl", titles, re.I):
            n = int(re.match(r"\d+", titles).group(0)) if re.match(r"\d+", titles) else None
            firsts = ctx.get("_firsts_shown", {}).get(name)
            if n is not None and firsts is not None and n != firsts:
                out.append(Finding(title, "titles scope",
                                   f"{name}: '{titles}' beside a record of data-era "
                                   f"games, but the standings grid shows {firsts} "
                                   f"first-place finish(es). Count the same seasons, "
                                   f"or label the scope."))
        seen.append((name, PLACE.get(badge), pct))
    ranked = sorted([s for s in seen if s[2] is not None], key=lambda x: -x[2])
    badges = [b for _, b, _ in ranked]
    if seen and badges != sorted(b for b in badges if b is not None):
        out.append(Finding(title, "rank badges",
                           f"badges {[(n, b) for n, b, _ in seen]} are not in win-% order"))
    return out


# ---------------------------------------------------------------------------
# Checks: Season Records leaderboards
# ---------------------------------------------------------------------------

CONTEXT = re.compile(r"\((\d{4}-\d{2}), (\d+)-(\d+)(?:-(\d+))?, ([\d,.]+) FP/week, (\d+) weeks\)")


def check_leaderboards(root: Node, ctx: dict) -> list:
    """Ranks run 1..n; values are monotone in the board's direction; where the
    context gives W-L, FP/week and weeks: W+L(+T) = weeks and
    value = FP/week x weeks to rounding."""
    out = []
    for lb in root.find_all(cls="sc-rb-leaderboard"):
        name = (lb.find(cls="sc-rb-lb-title") or Node("x", {})).text()
        entries = lb.find_all(cls="sc-rb-entry")
        ranks, values = [], []
        for e in entries:
            r = _num((e.find(cls="sc-rb-rank") or Node("x", {})).text().rstrip("."))
            v = _num((e.find(cls="sc-rb-value") or Node("x", {})).text())
            ranks.append(r)
            values.append(v)
            ctxt = (e.find(cls="sc-rb-context") or Node("x", {})).text()
            m = CONTEXT.search(ctxt)
            if m and v is not None:
                season, w, l, t, per, weeks = m.groups()
                games = int(w) + int(l) + int(t or 0)
                if games != int(weeks):
                    out.append(Finding(f"Season Records / {name}", "record vs weeks",
                                       f"{ctxt}: {games} games in {weeks} weeks"))
                per = float(per.replace(",", ""))
                if abs(per * int(weeks) - v) > 0.05 * int(weeks) + 0.05:
                    out.append(Finding(f"Season Records / {name}", "total vs per-week",
                                       f"{v:,.1f} shown; {per:,.1f} x {weeks} = "
                                       f"{per * int(weeks):,.1f}"))
        if ranks and any(r is None for r in ranks):
            continue
        # Ties may share a rank; otherwise 1, 2, 3 ...
        for i in range(1, len(ranks)):
            if not (ranks[i] == ranks[i - 1] or ranks[i] == i + 1):
                out.append(Finding(f"Season Records / {name}", "ranks",
                                   f"ranks run {ranks}"))
                break
        vals = [v for v in values if v is not None]
        if len(vals) >= 2:
            desc = all(a >= b for a, b in zip(vals, vals[1:]))
            asc = all(a <= b for a, b in zip(vals, vals[1:]))
            if not (desc or asc):
                out.append(Finding(f"Season Records / {name}", "order",
                                   f"values not ordered: {vals}"))
    return out


# ---------------------------------------------------------------------------
# Checks: newsletter tables
# ---------------------------------------------------------------------------

def check_probability_table(t: Node, title: str, ctx: dict) -> list:
    """Champ / Runner-Up / 3rd / 4th, or 1st..4th of percentages: each row
    and each column is a distribution over the same outcomes and sums to
    100%."""
    out = []
    rows = _table_rows(t)
    header = [c.text() for c in rows[0]]
    pcols = [i for i, h in enumerate(header) if h.endswith("%") or h in PLACE]
    cols = {i: 0.0 for i in pcols}
    for r in rows[1:]:
        vals = [_num(r[i].text()) for i in pcols if i < len(r)]
        if None in vals:
            continue
        for i, v in zip(pcols, vals):
            cols[i] += v
        tol = 0.051 * len(vals) + 0.1
        if abs(sum(vals) - 100) > tol:
            out.append(Finding(title, "row sum", f"{r[0].text()}: {sum(vals):.1f}%"))
    for i, total in cols.items():
        if abs(total - 100) > 0.051 * (len(rows) - 1) + 0.1:
            out.append(Finding(title, "column sum", f"{header[i]}: {total:.1f}%"))
    return out


def check_betting_line(t: Node, title: str, ctx: dict) -> list:
    """Two teams: win probabilities sum to 100%; spreads are opposite."""
    out = []
    rows = _table_rows(t)
    header = [c.text() for c in rows[0]]
    if "Win Prob" not in header or len(rows) != 3:
        return out
    wi = header.index("Win Prob")
    p = [_num(r[wi].text()) for r in rows[1:]]
    if None not in p and abs(sum(p) - 100) > 0.2:
        out.append(Finding(title, "win prob", f"{rows[1][0].text()} {p[0]}% + "
                           f"{rows[2][0].text()} {p[1]}% = {sum(p):.1f}%"))
    if "Spread" in header:
        si = header.index("Spread")
        sp = [_num(r[si].text()) for r in rows[1:]]
        if None not in sp and abs(sp[0] + sp[1]) > 0.01:
            out.append(Finding(title, "spread", f"spreads {sp} are not opposite"))
    return out


def check_ranked_table(t: Node, title: str, ctx: dict) -> list:
    """A Rank column runs 1..n; the column the title names is sorted that way."""
    out = []
    rows = _table_rows(t)
    header = [c.text() for c in rows[0]]
    if "Rank" not in header:
        return out
    ri = header.index("Rank")
    ranks = [_num(r[ri].text()) for r in rows[1:] if len(r) > ri]
    if ranks != list(range(1, len(ranks) + 1)) and None not in ranks:
        # ties may share a rank
        ok = all(b == a or b == i + 2 for i, (a, b) in enumerate(zip(ranks, ranks[1:])))
        if not ok or ranks[0] != 1:
            out.append(Finding(title, "ranks", f"ranks run {ranks}"))
    m = re.search(r"\((Total FP|FPPG)", title)
    key = m.group(1) if m else ("FP" if "Performances" in title else None)
    if key and key in header:
        ki = header.index(key)
        vals = [_num(r[ki].text()) for r in rows[1:] if len(r) > ki]
        vals = [v for v in vals if v is not None]
        worst = title.startswith("Worst")
        good = all((a <= b) if worst else (a >= b) for a, b in zip(vals, vals[1:]))
        if not good:
            out.append(Finding(title, "order",
                               f"{key} not {'ascending' if worst else 'descending'}: {vals[:8]}"))
    if title.startswith("Power Rankings") and "Record" in header:
        recs = [_wl(r[header.index("Record")].text()) for r in rows[1:]]
        recs = [x for x in recs if x]
        if len({x[0] + x[1] for x in recs}) > 1:
            out.append(Finding(title, "records", f"games played differ: {recs}"))
    return out


FPPG_CEILING = 90.0     # as in check_playerlist: nobody averages more


def check_per_game_table(t: Node, title: str, ctx: dict) -> list:
    """Wherever a row shows Total FP, GP (a count) and FPPG, FPPG = Total/GP;
    no FPPG cell is above the ceiling. Catches a row shifted by one cell,
    which is how WEEK18 printed Pascal Siakam's FPPG as 1859.0 (a total)."""
    out = []
    rows = _table_rows(t)
    header = [c.text() for c in rows[0]]
    fcols = [i for i, h in enumerate(header) if "FPPG" in h and "Proj" not in h]
    if not fcols:
        return out
    fi = fcols[0]
    # The numerator/denominator pair must be the SAME basis as the FPPG
    # column. Two labelled triples qualify: all-games (Total FP / GP) and
    # starts-only (Starter FP / Starter GP). The waiver ROI table used to
    # print starts-only FPPG beside all-games Total and GP, which reconciles
    # to nothing, and was skipped via a "Starter FPPG" label. It now prints
    # its own numerator and denominator, so it is checked like any other
    # (10-13). A label is not a substitute for numbers that add up.
    plain = header[fi] == "FPPG"
    ti = gi = None
    if plain:
        for tname, gname in (("Total FP", "GP"), ("Starter FP", "Starter GP")):
            if tname in header and gname in header:
                ti, gi = header.index(tname), header.index(gname)
                break
    for r in rows[1:]:
        if len(r) != len(header):
            out.append(Finding(title, "cell count",
                               f"{r[0].text() if r else '?'}: {len(r)} cells under "
                               f"{len(header)} columns"))
            continue
        name = next((c.text() for c in r if c.text() and not _num(c.text())), r[0].text())
        fppg = _num(r[fi].text())
        if fppg is not None and fppg > FPPG_CEILING:
            out.append(Finding(title, "FPPG range",
                               f"{name}: FPPG {r[fi].text()} -- a total in the FPPG column?"))
            continue
        if ti is not None and gi is not None:
            tot, gp = _num(r[ti].text()), _num(r[gi].text())
            if None not in (tot, gp, fppg) and gp > 0:
                # Totals may be printed rounded to the unit.
                tol = 0.06 + 0.5 / gp
                if abs(tot / gp - fppg) > tol:
                    out.append(Finding(title, "FPPG = Total/GP",
                                       f"{name}: {tot:,.1f} / {gp:.0f} = {tot / gp:.2f}, "
                                       f"shown {fppg:.2f}"))
    return out


def check_free_agents(t: Node, title: str, ctx: dict) -> list:
    """Games this / next week are counts of days in one fantasy week; the
    per-game check covers FPPG."""
    out = []
    rows = _table_rows(t)
    header = [c.text() for c in rows[0]]
    for col in ("Games This Week", "Games Next Week"):
        if col in header:
            i = header.index(col)
            for r in rows[1:]:
                g = _num(r[i].text()) if i < len(r) else None
                if g is None or not 0 <= g <= 7:
                    out.append(Finding(title, col, f"{r[0].text()}: {r[i].text() if i < len(r) else '?'}"))
    return out


def check_games_grid(t: Node, title: str, ctx: dict) -> list:
    """Each day: starters + open slots = the seats in a lineup; "full" only
    when nothing is open; fillable never exceeds open. Each row: Fillable is
    the sum of its days' fillable slots (when known)."""
    from modules.lineup_fill import NUM_SEATS
    out = []
    rows = _table_rows(t)
    header = [c.text() for c in rows[0]]
    for r in rows[1:]:
        mgr = r[0].text()
        day_fill, known = 0, True
        for i, c in enumerate(r[3:], start=3):
            if "gg-off" in c.classes:
                continue
            n_node = c.find(cls="gg-n")
            started = _num(n_node.text()) if n_node else None
            note = (c.find(cls="gg-note") or Node("x", {})).text()
            fill = re.search(r"(\d+) fillable", note)
            opn = re.search(r"(\d+) open", note)
            fill_n = int(fill.group(1)) if fill else 0
            holes = None if started is None else NUM_SEATS - int(started)
            label = header[i] if i < len(header) else f"day {i}"
            if started is None or not 0 <= started <= NUM_SEATS:
                out.append(Finding(title, "starters", f"{mgr} {label}: {c.text()!r}"))
                continue
            if opn and int(opn.group(1)) != holes:
                out.append(Finding(title, "open slots",
                                   f"{mgr} {label}: {int(started)} started and "
                                   f"{opn.group(1)} open of {NUM_SEATS}"))
            if ("gg-full" in c.classes) != (holes == 0):
                out.append(Finding(title, "full marker",
                                   f"{mgr} {label}: {int(started)} of {NUM_SEATS} "
                                   f"{'marked' if 'gg-full' in c.classes else 'not marked'} full"))
            if fill_n > holes:
                out.append(Finding(title, "fillable", f"{mgr} {label}: {fill_n} fillable, "
                                   f"{holes} open"))
            day_fill += fill_n
        if "Fillable" in header:
            f = _num(r[header.index("Fillable")].text())
            if f is not None and int(f) != day_fill:
                out.append(Finding(title, "Fillable column",
                                   f"{mgr}: {int(f)} shown, days sum to {day_fill}"))
    return out


def _both(*fns):
    def run(t, title, ctx):
        out = []
        for fn in fns:
            out.extend(fn(t, title, ctx))
        return out
    run.__name__ = "+".join(f.__name__ for f in fns)
    return run


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

def _dispatch(t: Node, title: str):
    header = [c.text() for c in (_table_rows(t) or [[]])[0]]
    if "sc-hist-table" in t.classes:
        return check_history_grid
    if "gg-table" in t.classes:
        return check_games_grid
    if header and header[0] == "" and len(header) > 2:
        return check_h2h_matrix
    if "Champ %" in header or (header[1:] and all(h in PLACE for h in header[1:])):
        return check_probability_table
    if "Win Prob" in header and "Spread" in header:
        return check_betting_line
    if "Rank" in header and "FPPG" in header:
        return _both(check_ranked_table, check_per_game_table)
    if "Rank" in header:
        return check_ranked_table
    if "Games This Week" in header:
        return _both(check_free_agents, check_per_game_table)
    if any("FPPG" in h for h in header):
        return check_per_game_table
    return None


def load_context(base: Path, season: Optional[str]) -> dict:
    path = Path(base) / "data" / "historical" / "all_standings.json"
    standings = {}
    if path.is_file():
        for r in json.loads(path.read_text(encoding="utf-8")):
            standings.setdefault(r["season"], {})[r["manager"]] = r
    return {"season": season, "standings": standings}


def check_document(doc: str, ctx: dict) -> tuple[list, list]:
    """(findings, unchecked table titles)."""
    root = parse(doc)
    findings, unchecked = [], []
    tables = root.find_all("table")
    # History grids first: the profile check reads the firsts they show.
    ordered = sorted(tables, key=lambda t: 0 if "sc-hist-table" in t.classes else 1)
    for t in ordered:
        title = _heading_before(t)
        fn = _dispatch(t, title)
        if fn is None:
            unchecked.append(title)
            continue
        findings.extend(fn(t, title, ctx))
        if fn is check_history_grid and "Standings" in title:
            rows = _table_rows(t)
            header = [c.text() for c in rows[0]]
            if "1st" in header:
                i = header.index("1st")
                ctx["_firsts_shown"] = {
                    r[0].text(): sum(1 for c in r if c.find_all(cls="sc-hist-1st"))
                    for r in rows[1:] if r}
    findings.extend(check_manager_profiles(root, ctx))
    findings.extend(check_leaderboards(root, ctx))
    return findings, unchecked


def season_of(path: Path, doc: str) -> Optional[str]:
    """The newsletter's season: the archive folder name, else the page."""
    for part in Path(path).parts:
        if re.fullmatch(r"\d{4}-\d{2}", part):
            return part
    m = re.search(r"(20\d\d-\d\d) (?:season|Season)", doc)
    return m.group(1) if m else None
