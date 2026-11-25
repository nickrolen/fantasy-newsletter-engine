"""
Claim check (prose layer, item 5): every number and every claim about
history in a newsletter draft must trace to a source.

Sources are the week's stats report (JSON and .md), the previous week's
report (for "last week's line" claims), and APPROVED entries of the lore
file. The lore file is the only bridge for knowledge the numbers cannot
prove: anything not written down somewhere is not sayable.

What it checks, per unit (a sentence, bullet, or table row):
  * unsupported_number    -- a number no source carries at the precision
                             written (small integers must also share an
                             entity -- manager, team, player -- with the
                             supporting record, or "4" would match anything)
  * unsupported_superlative -- "highest", "worst ever", "record" ... with
                             nothing in the sources making that ranking
  * unsourced_history     -- "again", "always", "habit", "first time
                             since" ... with no lore tag and no supported
                             number in the sentence
  * bad_lore_ref          -- <!--lore:id--> naming an entry that is missing,
                             not approved, or flagged stale
  * fact_as_tendency      -- a lore FACT ("6-22 in February") told as
                             character ("always collapses in February");
                             only a tendency or Nick's written lore may be
  * approximate_number    -- "nearly 60": template rule 2, give the number

Verdicts ("a collapse", "unthinkable") are allowed: they are the voice.
Facts are not allowed without a source.

Pure functions. scripts/check_draft.py does the file IO.
"""

from __future__ import annotations

import math
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Iterable, Optional

EXEMPT_SECTIONS = {9}          # Around the NBA: web-sourced, Step 8 checks it
# 4d (NEWSLETTER_REVIEW 11-25): Section 7's Money and Exposure block moved to
# the hub, and with it its exemption. No section but 9 is exempt from the
# money rules now: money_findings (whether a dollar figure may appear this
# week) and money_line_findings (that it names its pot and window).
APPROX_TOLERANCE = 0.10        # "nearly 60" may be 54..66
LORE_TAG = re.compile(r"<!--\s*lore:([A-Za-z0-9_.-]+)\s*-->")

WORD_NUMS = {
    "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
    "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16,
    "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20,
}
ORDINAL_WORDS = {
    "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6,
    "seventh": 7, "eighth": 8, "ninth": 9, "tenth": 10, "eleventh": 11,
    "twelfth": 12,
}
MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct",
     "nov", "dec"])}

APPROX_WORDS = re.compile(
    r"(?:nearly|almost|about|roughly|around|approximately|close to|just under|"
    r"just over|more than|less than|north of|south of|upwards of|~)"
    r"\s*$", re.I)

# Quantitative rankings only. "Cleanest", "cruelest", "clearest" are
# verdicts: the voice is allowed them.
SUPERLATIVE = re.compile(
    r"\b(?:highest|lowest|biggest|largest|smallest|longest|shortest|"
    r"fewest|worst|best|most|least|greatest|widest|narrowest|closest|"
    r"hottest|coldest|record|all-time|ever|career-(?:high|low|best|worst)|"
    r"season-(?:high|low|best|worst)|first time)\b", re.I)
# -est words that are not rankings
NOT_SUPERLATIVE = {
    "best", "interest", "honest", "modest", "forest", "contest", "latest",
    "test", "rest", "west", "east", "nest", "guest", "quest", "chest",
    "request", "protest", "suggest", "harvest", "invest", "arrest",
    "manifest", "earnest", "digest", "pest", "vest", "crest", "jest",
    "zest", "attest", "detest", "biggest", "honest", "unrest", "midwest",
}
# "best" and "biggest" are rankings, but so idiomatic ("his best game",
# "the biggest question") that alone they prove nothing. They count only
# with a scope word nearby.
SCOPE = re.compile(
    r"\b(?:league|season|career|all-time|ever|history|week|year|record)\b",
    re.I)

# Character language: only a "tendency" (beats chance) or Nick's own
# "written" entry may be told this way. A "fact" is told as history.
TENDENCY_WORDS = re.compile(
    r"\b(?:always|never fails|habit|curse|cursed|every (?:year|season|time)|"
    r"annual|perennial|trademark|signature|has a way of|known for|"
    r"like clockwork|without fail|true to form|as usual)\b", re.I)

HISTORY = re.compile(
    r"\b(?:again|always|never|habit|habits|tradition|as usual|"
    r"once more|yet again|first time since|reputation|known for|curse|"
    r"has a way of|historically|perennial|annual|every (?:year|season|"
    r"time|december|january|february|march|november)|this time of year|"
    r"for the \w+ (?:time|straight)|familiar|trademark|signature|"
    r"lifetime|legacy)\b", re.I)

RANK_FIELD = re.compile(
    r"high|low|best|worst|record|top|longest|shortest|most|least|max|min|"
    r"leader|rank|luck|streak|career|all_time|alltime|biggest|closest|"
    r"healthiest|injured|largest|smallest|first|milestone", re.I)


# ---------------------------------------------------------------- text utils

def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return s.lower().replace("\u2019", "'")


def strip_md(s: str) -> str:
    s = LORE_TAG.sub("", s)
    s = re.sub(r"[*_`]", "", s)
    return s.replace("\u2212", "-").replace("\u2014", " - ").replace(
        "\u2013", "-")


# ---------------------------------------------------------------- numbers

@dataclass(frozen=True)
class Num:
    value: float
    decimals: int
    raw: str
    kind: str = "num"          # num | pct | record | season | date | ordinal
    approx: bool = False
    pos: int = 0
    extra: tuple = ()          # record: (a, b); date: (month, day)

    @property
    def distinctive(self) -> bool:
        """Specific enough that matching it anywhere in the sources is
        evidence. Small integers and 1-decimal small numbers are not."""
        if self.kind in ("record", "season", "date", "year"):
            return True
        if self.decimals >= 2:
            return True
        return abs(self.value) >= 100


_SEASON = re.compile(r"\b((?:19|20)\d\d)-(\d\d)\b")
_RECORD = re.compile(r"(?<![\d.])(\d{1,2}(?:\.\d)?)-(\d{1,2}(?:\.\d)?)(?![\d.%])")
_DATE = re.compile(
    r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+(\d{1,2})"
    r"(?!\d)", re.I)
_NUMBER = re.compile(
    r"(?<![\w.])([-+]?)\$?(\d{1,3}(?:,\d{3})+|\d+)(\.\d+)?"
    r"(%|st|nd|rd|th)?(?![\w.]\d)")


def extract_numbers(text: str) -> list[Num]:
    """All numeric claims in a unit of prose."""
    out: list[Num] = []
    taken: list[tuple[int, int]] = []

    def free(a, b):
        return all(b <= x or a >= y for x, y in taken)

    # week labels are structure; 4d: the hyphenated form too ("these
    # week-6 lines", 5g's Betting Lines sentence), as in ADDS_CLAIM (5g)
    for m in re.finditer(r"\bweeks?(?:\s+|-)\d{1,2}(?:\s*(?:-|to|through|and)\s*"
                         r"\d{1,2})?", text, re.I):
        taken.append(m.span())
    for m in _SEASON.finditer(text):
        out.append(Num(float(m.group(1)), 0, m.group(0), "season",
                       pos=m.start(),
                       extra=(int(m.group(1)), int(m.group(2)))))
        taken.append(m.span())
    for m in _DATE.finditer(text):
        if not free(*m.span()):
            continue
        day = int(m.group(2))
        if 1 <= day <= 31:
            out.append(Num(float(day), 0, m.group(0), "date", pos=m.start(),
                           extra=(MONTHS[m.group(1).lower()[:3]], day)))
            taken.append(m.span())
    for m in _RECORD.finditer(text):
        if not free(*m.span()):
            continue
        before = text[max(0, m.start() - 8):m.start()].lower()
        if "week" in before:             # "Weeks 16-19" is a range
            continue
        a, b = m.group(1), m.group(2)
        out.append(Num(float(a), 0, m.group(0), "record", pos=m.start(),
                       extra=(a, b)))
        taken.append(m.span())
    for m in _NUMBER.finditer(text):
        if not free(*m.span()):
            continue
        sign, whole, frac, suffix = m.groups()
        before = text[max(0, m.start() - 6):m.start()].lower()
        if re.search(r"week\s*$|weeks\s*$|wk\s*$|week-$|wk-$", before):
            continue                      # week labels are structure
        if re.match(r":\d", text[m.end():m.end() + 2]) or \
                text[max(0, m.start() - 1):m.start()] == ":":
            continue                      # times (12:01)
        val = float(whole.replace(",", "") + (frac or ""))
        if sign == "-":
            val = -val
        dec = len(frac) - 1 if frac else 0
        kind = "pct" if suffix == "%" else (
            "ordinal" if suffix in ("st", "nd", "rd", "th") else "num")
        if kind == "num" and not frac and not sign and \
                1990 <= val <= 2100 and "," not in whole:
            kind = "year"
        approx = bool(APPROX_WORDS.search(text[max(0, m.start() - 25):
                                               m.start()]))
        out.append(Num(val, dec, m.group(0), kind, approx, m.start()))
        taken.append(m.span())
    for m in re.finditer(r"\b(" + "|".join(WORD_NUMS) + r")\b", text, re.I):
        if free(*m.span()):
            out.append(Num(float(WORD_NUMS[m.group(1).lower()]), 0,
                           m.group(0), "num", pos=m.start()))
    for m in re.finditer(r"\b(" + "|".join(ORDINAL_WORDS) + r")\b", text, re.I):
        if free(*m.span()):
            out.append(Num(float(ORDINAL_WORDS[m.group(1).lower()]), 0,
                           m.group(0), "ordinal", pos=m.start()))
    return sorted(out, key=lambda n: n.pos)


def _keys(v: float) -> Iterable[tuple[int, str]]:
    """Index keys for a source value: rounded and truncated, 0-2 decimals,
    as given, absolute, and as a percentage of a fraction."""
    seen = set()
    for c in (v, -v, v * 100, -v * 100):
        for d in (0, 1, 2):
            for x in (round(c + 0.0, d), math.trunc(c * 10 ** d) / 10 ** d,
                      math.floor(c * 10 ** d + 0.5) / 10 ** d):
                k = (d, f"{x:.{d}f}")
                if k not in seen:
                    seen.add(k)
                    yield k


# ---------------------------------------------------------------- sources

@dataclass
class Record:
    src: str
    path: str
    nums: list
    ents: frozenset
    text: str                           # normalized, for word lookups
    fields: tuple = ()                  # (field_key, value) pairs
    label: str = ""                     # path + string values, no keys


@dataclass
class Pool:
    records: list = field(default_factory=list)
    index: dict = field(default_factory=dict)       # key -> record ids
    texts: set = field(default_factory=set)         # record strings "15-4"
    dates: set = field(default_factory=set)         # (month, day)
    seasons: set = field(default_factory=set)       # (2021, 22)
    years: set = field(default_factory=set)         # 2021, 2022 ...
    by_field: dict = field(default_factory=dict)    # field -> [(v, ents)]

    field_index: dict = field(default_factory=dict)  # key -> field names

    def fields_for(self, n: "Num") -> set:
        return self.field_index.get(_key_of(abs(n.value), _raw_digits(n)),
                                    set())

    def add(self, rec: Record):
        rid = len(self.records)
        self.records.append(rec)
        for v in rec.nums:
            for k in _keys(v):
                self.index.setdefault(k, set()).add(rid)
        for f, v in rec.fields:
            self.by_field.setdefault(f, []).append((v, rec.ents))
            for k in _keys(v):
                self.field_index.setdefault(k, set()).add(f)
        t = rec.text
        for m in re.finditer(r"(?<![\d.])(\d{1,2}(?:\.\d)?)-(\d{1,2}(?:\.\d)?)"
                             r"(?![\d.])", t):
            self.texts.add(m.group(0))
        for m in re.finditer(r"\b(\d{1,2}(?:\.\d+)?)\s*(?:wins?|w)?,?\s*"
                             r"(?:-|to|,)\s*(\d{1,2}(?:\.\d+)?)\b", t):
            pass
        for m in re.finditer(r"\b20\d\d-(\d\d)-(\d\d)\b", t):
            self.dates.add((int(m.group(1)), int(m.group(2))))
        for m in _DATE.finditer(t):
            self.dates.add((MONTHS[m.group(1)[:3]], int(m.group(2))))
        for m in re.finditer(r"\b((?:19|20)\d\d)[-/](?:20)?(\d\d)\b", t):
            if int(m.group(2)) <= 12 and len(m.group(0)) == 7:
                pass
            self.seasons.add((int(m.group(1)), int(m.group(2)[-2:])))
        for m in re.finditer(r"\b((?:19|20)\d\d)\b", t):
            self.years.add(int(m.group(1)))
        for y in rec.nums:
            if 1990 <= y <= 2100 and y == int(y):
                self.years.add(int(y))


class Vocabulary:
    """Entities: managers, team names, aliases, players. Canonical names
    are lowercase; a team name maps to its manager."""

    def __init__(self, managers, manager_to_team=None, aliases=None,
                 players=()):
        self.canon: dict[str, str] = {}
        self.managers = {norm(m) for m in managers}
        for m in managers:
            self.canon[norm(m)] = norm(m)
        for m, t in (manager_to_team or {}).items():
            self.canon[norm(t)] = norm(m)
        for a, m in (aliases or {}).items():
            self.canon[norm(a)] = norm(m)
        last: dict[str, set] = {}
        for p in players:
            n = norm(p).strip()
            if len(n) < 4 or " " not in n:
                continue
            self.canon.setdefault(n, n)
            ln = n.split()[-1]
            if ln in ("jr.", "jr", "sr.", "ii", "iii", "iv") and \
                    len(n.split()) > 2:
                ln = n.split()[-2]
            last.setdefault(ln, set()).add(n)
        for ln, full in last.items():
            if len(full) == 1 and len(ln) > 3 and ln not in self.canon:
                self.canon[ln] = next(iter(full))
        terms = sorted(self.canon, key=len, reverse=True)
        self._re = re.compile(
            r"(?<![\w])(" + "|".join(re.escape(t) for t in terms) +
            r")(?:'s)?(?![\w])") if terms else None

    def spans(self, text: str) -> list[tuple[int, int, str]]:
        if not self._re:
            return []
        return [(m.start(), m.end(), self.canon[m.group(1)])
                for m in self._re.finditer(norm(text))]

    def is_manager(self, canon: str) -> bool:
        return canon in self.managers

    def find(self, text: str) -> frozenset:
        if not self._re:
            return frozenset()
        return frozenset(self.canon[m.group(1)]
                         for m in self._re.finditer(norm(text)))


def _scalars(d: dict):
    for k, v in d.items():
        if isinstance(v, bool):
            continue
        if isinstance(v, (int, float)):
            yield k, float(v)
        elif isinstance(v, list) and v and all(
                isinstance(x, (int, float)) and not isinstance(x, bool)
                for x in v):
            for x in v:
                yield k, float(x)


def add_json(pool: Pool, obj, vocab: Vocabulary, src: str):
    """Every dict (and list of scalars) becomes a record. A record's
    entities are those in its own strings, its keys on the path, and its
    ancestors' strings (a matchup's stats_a inherits manager_a)."""

    def walk(o, path, inherited):
        if isinstance(o, dict):
            strings = " ".join(str(v) for v in o.values()
                               if isinstance(v, str))
            keytext = " ".join(str(k).replace("_", " ") for k in o)
            own = vocab.find(strings) | vocab.find(path.replace("_", " ")
                                                   .replace(".", " "))
            ents = inherited | own
            fields = tuple((f"{_tail(path)}.{k}", v) for k, v in _scalars(o))
            pool.add(Record(src, path, [v for _, v in fields], ents,
                            norm(path + " " + keytext + " " + strings),
                            fields, norm(path + " " + strings)))
            for k, v in o.items():
                if isinstance(v, (dict, list)):
                    walk(v, f"{path}.{k}", ents)
        elif isinstance(o, list):
            for i, v in enumerate(o):
                if isinstance(v, (dict, list)):
                    walk(v, f"{path}[{i}]", inherited)
                elif isinstance(v, str):
                    pool.add(Record(src, f"{path}[{i}]", [
                        n.value for n in extract_numbers(v)],
                        inherited | vocab.find(v), norm(v), (),
                        norm(path + " " + v)))

    walk(obj, "", frozenset())


def _tail(path: str) -> str:
    p = re.sub(r"\[\d+\]", "", path).strip(".")
    parts = [x for x in p.split(".") if x]
    return ".".join(parts[-2:]) if parts else ""


def add_markdown(pool: Pool, md: str, vocab: Vocabulary, src: str):
    """Each line is a record; it inherits the entities of the nearest
    ### heading (the report puts the manager in the heading)."""
    heading_ents = frozenset()
    for i, line in enumerate(md.splitlines()):
        if not line.strip():
            continue
        if line.startswith("###"):
            heading_ents = vocab.find(line)
        elif line.startswith("## "):
            heading_ents = frozenset()
        clean = strip_md(line)
        nums = []
        for n in extract_numbers(clean):
            nums.append(n.value)
            if n.kind == "record":
                pass
        pool.add(Record(src, f"line {i + 1}", nums,
                        heading_ents | vocab.find(clean), norm(clean), (),
                        norm(clean)))


def add_lore(pool: Pool, entries: list, vocab: Vocabulary):
    for e in entries:
        if e.get("status") != "approved" or e.get("stale") or \
                e.get("kind") == "alias":
            continue
        text = e.get("text", "")
        if e.get("kind") == "written":
            # Nick's words make reputations sayable, not numbers: a number
            # typed into lore once is a value derived once, never advanced.
            nums = []
        else:
            nums = [float(v) for v in e.get("values", []) if
                    isinstance(v, (int, float))]
            nums += [n.value for n in extract_numbers(text)]
        ents = vocab.find(text) | frozenset(norm(x) for x in
                                             e.get("entities", []))
        pool.add(Record("lore", e.get("id", "?"), nums, ents, norm(text),
                        (), norm(text)))


# ---------------------------------------------------------------- the draft

@dataclass
class Unit:
    section: int
    line: int
    text: str           # cleaned
    raw: str
    para_ents: frozenset
    para_nums: tuple
    ents: frozenset = frozenset()
    is_row: bool = False
    head_ents: frozenset = frozenset()
    spans: tuple = ()
    managers: frozenset = frozenset()
    block: str = ""     # the bold sub-header it sits under, lower-cased

    @property
    def anchor(self) -> frozenset:
        """Who this unit is about: whom it names plus the sub-header it
        sits under (a report card's stat line names the opponent too, but
        the numbers are the header manager's). Else the paragraph."""
        return (self.ents | self.head_ents) or self.para_ents

    @property
    def is_label(self) -> bool:
        t = self.raw.strip()
        return bool(re.fullmatch(r"\*\*[^*]+\*\*", t)) and \
            len(t.split()) <= 10


def split_units(draft: str, vocab: Vocabulary) -> list[Unit]:
    units: list[Unit] = []
    section = 0
    para: list[tuple[int, str]] = []
    head = [frozenset()]          # entities of the last bold sub-header
    head_nums = [()]              # ... and its numbers (scores in a header)
    block = [""]                  # ... and its text (Unit.block)

    def flush():
        if not para:
            return
        joined = " ".join(strip_md(t) for _, t in para)
        pents = vocab.find(joined) | head[0]
        pnums = tuple(n.value for n in extract_numbers(joined)
                      if n.kind in ("num", "pct")) + head_nums[0]
        for ln, raw in para:
            clean = strip_md(raw)
            if raw.lstrip().startswith("|"):
                if re.match(r"^\s*\|[\s:|-]+\|\s*$", raw):
                    continue
                units.append(Unit(section, ln, clean, raw, pents, pnums,
                                  vocab.find(clean), True, head[0],
                                  tuple(vocab.spans(clean)),
                                  frozenset(vocab.managers), block[0]))
                continue
            for s in re.split(r"(?<=[.!?])\s+(?=[A-Z\"'(*])", raw):
                if s.strip():
                    c = strip_md(s)
                    units.append(Unit(section, ln, c, s, pents, pnums,
                                      vocab.find(c), False, head[0],
                                      tuple(vocab.spans(c)),
                                      frozenset(vocab.managers), block[0]))
        para.clear()

    for i, line in enumerate(draft.splitlines(), 1):
        m = re.match(r"^#{1,4}\s*\**\s*(\d{1,2})\.", line)
        if m:
            flush()
            section = int(m.group(1))
            head[0] = frozenset()
            head_nums[0] = ()
            block[0] = ""
            continue
        if re.match(r"^\*\*[^*]+\*\*", line.strip()) and not \
                line.lstrip().startswith(("- ", "* ", "|")):
            flush()
            head[0] = vocab.find(strip_md(line))
            head_nums[0] = tuple(n.value for n in extract_numbers(
                strip_md(line)) if n.kind == "num")
            block[0] = strip_md(line).strip().rstrip(":").strip().lower()
        if not line.strip() or line.strip() == "---" or line.startswith("#"):
            flush()
            continue
        if line.lstrip().startswith(("- ", "* ")) and para and \
                not para[-1][1].lstrip().startswith("|"):
            flush()
        para.append((i, line))
    flush()
    return units


# ---------------------------------------------------------------- checking

@dataclass
class Finding:
    kind: str
    section: int
    line: int
    token: str
    sentence: str

    def as_dict(self):
        return self.__dict__.copy()


def _matches(n: Num, pool: Pool) -> set:
    if n.kind == "season":
        return {-1} if n.extra in pool.seasons else set()
    if n.kind == "year":
        return {-1} if int(n.value) in pool.years else set()
    if n.kind == "date":
        return {-1} if n.extra in pool.dates else set()
    if n.kind == "record":
        a, b = n.extra
        if f"{a}-{b}" in pool.texts or f"{b}-{a}" in pool.texts:
            return {-1}
        ka = _key_of(float(a), a)
        kb = _key_of(float(b), b)
        return set(pool.index.get(ka, ())) & set(pool.index.get(kb, ()))
    if n.approx:
        lo, hi = abs(n.value) * (1 - APPROX_TOLERANCE), abs(n.value) * (
            1 + APPROX_TOLERANCE)
        hits = set()
        for d in (0, 1, 2):
            pass
        for k, rids in pool.index.items():
            if k[0] == 2:
                x = float(k[1])
                if lo <= x <= hi:
                    hits |= rids
        return hits
    key = (min(n.decimals, 2), f"{abs(n.value):.{min(n.decimals, 2)}f}")
    return set(pool.index.get(key, ()))


def _key_of(v: float, raw: str) -> tuple:
    d = len(raw.split(".")[1]) if "." in raw else 0
    d = min(d, 2)
    return (d, f"{abs(v):.{d}f}")


def _derived(n: Num, unit: Unit, pool: Pool) -> bool:
    """A margin, sum or percentage of two supported values: numbers in
    the same paragraph, or the same field for two entities in it."""
    target = abs(n.value)
    tol = 0.5 * 10 ** -n.decimals + 1e-9
    if n.approx:
        tol = max(tol, target * APPROX_TOLERANCE)
    vals = [v for v in unit.para_nums if v != n.value]
    cands = list(vals)
    ents = unit.anchor
    if ents:
        for f, items in pool.by_field.items():
            mine = [v for v, e in items if e & ents]
            if 2 <= len(mine) <= 12:
                for i in range(len(mine)):
                    for j in range(i + 1, len(mine)):
                        if abs(abs(mine[i] - mine[j]) - target) <= tol:
                            return True
    for i in range(len(cands)):
        for j in range(len(cands)):
            if i == j:
                continue
            a, b = cands[i], cands[j]
            if abs(abs(a - b) - target) <= tol or abs(a + b - target) <= tol:
                return True
            for k in range(j + 1, len(cands)):
                if i < j and k != i and abs(a + b + cands[k] - target) <= tol:
                    return True
            if b and n.kind == "pct" and (
                    abs(100 * (a / b - 1) - target) <= max(tol, 0.5) or
                    abs(100 * a / b - target) <= max(tol, 0.5)):
                return True
    return False


def _sig_digits(n: Num) -> int:
    return len(_raw_digits(n).replace(".", "").lstrip("0"))


def _local_anchor(n: Num, unit: Unit) -> frozenset:
    """The most specific owner of a number: in a table row, the players in
    the row (not the fantasy team column, which would admit every number
    that manager owns); in prose, a player named just before the number
    ("Jalen Johnson (182.35 FP over 3 games)")."""
    players = [(a, b, c) for a, b, c in unit.spans
               if c not in unit.managers]
    if unit.is_row:
        return frozenset(c for _, _, c in players)
    near = [(a, b, c) for a, b, c in players if b <= n.pos and
            n.pos - b <= 45]
    if near:
        return frozenset({max(near)[2]})
    return frozenset()


def number_supported(n: Num, unit: Unit, pool: Pool) -> tuple[bool, set]:
    """Supported = a source record that carries this value AND names an
    entity this sentence names (else this paragraph's). Matching against
    the whole pool is not evidence: ~6,000 records cover most two-decimal
    values under 100, so a slipped digit would almost always "match"
    somewhere. Only a long number (5+ significant digits) in a sentence
    that names nobody may match anywhere."""
    hits = _matches(n, pool)
    if -1 in hits:
        return True, set()
    local = _local_anchor(n, unit)
    # A row's numbers belong to its players only. In prose, try the
    # player named just before the number, then whoever the unit is about.
    tiers = [local] if unit.is_row and local else [
        x for x in (local, unit.anchor) if x]
    if hits:
        for ents in tiers:
            anchored = {r for r in hits if pool.records[r].ents & ents}
            if anchored:
                return True, anchored
        if not tiers and (_sig_digits(n) >= 5 or n.approx):
            return True, hits
    if n.kind in ("num", "pct") and not unit.is_row and \
            _sig_digits(n) >= 3 and _derived(n, unit, pool):
        return True, set()
    return False, set()


def _superlative_tokens(text: str) -> list[str]:
    out = []
    for m in SUPERLATIVE.finditer(text):
        w = m.group(0).lower()
        before = text[max(0, m.start() - 4):m.start()].lower()
        if w in ("least", "most") and before.endswith("at "):
            continue                       # "at least", "at most"
        if w in ("best", "biggest", "most", "ever") and not SCOPE.search(text):
            continue
        out.append(w)
    return out


def _field_extreme(n: Num, pool: Pool) -> bool:
    """The number is the max or min of a field shared by >= 3 records --
    "the week's highest score" checked against every team's score."""
    for f in pool.fields_for(n):
        vals = [v for v, _ in pool.by_field[f]]
        if len(vals) < 3:
            continue
        hit = [v for v in vals if _key_of(abs(n.value), _raw_digits(n)) in
               set(_keys(v))]
        if hit and (max(vals) in hit or min(vals) in hit):
            return True
    return False


DOLLARS = re.compile(r"\$\s?\d[\d,]*(?:\.\d+)?")

# VOICE.md: "banked" and "expected remaining" never appear as LABELS. The
# decomposition ships as the engine renders it ("912 -> 1498"); a label names
# the machinery instead of the score.
#
# A label is the word sitting next to its value: followed by a colon or
# equals, by a figure, by a table separator, or by a tag boundary
# ("<th>Banked</th><td>912"). So "he banked 912 before Thursday" IS flagged
# -- a figure beside the word is the pattern this rule removes, whatever the
# surrounding grammar -- while "he banked the win" is prose and is not.
SCORE_LABELS = re.compile(
    r"\b(banked|expected\s+remaining|remaining\s+expected)\b"
    r"\s*(?=[:=|<]|[-\u2013\u2014]\s*\d|\d)",
    re.IGNORECASE)


def score_label_findings(text: str, vocab: "Vocabulary" = None,
                         exempt_sections=()) -> list[Finding]:
    """VOICE.md: "banked" / "expected remaining" as a LABEL, anywhere.

    A label is the word next to its value -- see SCORE_LABELS for what counts
    and what does not.

    One implementation, two consumers: check_draft.py runs it over a drafted
    newsletter beside money_findings, and the live-line page's tests run it
    over the rendered HTML (modules/live_lines_page.py). `vocab` splits a
    newsletter draft into sections when one is given; without it each line of
    the text is a unit, which is what a rendered page is.
    """
    out = []
    if vocab is not None:
        units = [(u.section, u.line, u.raw, u.text) for u in split_units(text, vocab)]
    else:
        units = [(0, i, line, line) for i, line in enumerate(text.splitlines(), 1)]
    for section, line, raw, sentence in units:
        if section in exempt_sections:
            continue
        m = SCORE_LABELS.search(LORE_TAG.sub("", raw))
        if m:
            out.append(Finding("score_label", section, line,
                               m.group(0).strip(), sentence[:200]))
    return out


def money_findings(draft: str, vocab: Vocabulary, money_events,
                   exempt_sections=EXEMPT_SECTIONS) -> list[Finding]:
    """Dollar figures in a week where no money was decided (Nick, 10-14).

    `money_events` is the week's angles_weekN.json "money_events": what
    decided money THIS week. Empty means every pot and liability holds
    exactly as it did last week, so a dollar figure can only restate it --
    true of everyone and news to no one. None means the events are unknown,
    which is not the same as none: it raises rather than passing.

    Only the frequency rule is mechanical. Its sibling -- in a week that did
    decide money, state a liability only when it changed or distinguishes
    someone -- is a judgement about what a sentence is for, and a check
    keyed on names would flag the good lines ("the only one still exposed")
    with the bad. That one is VOICE.md's; the standing threads already
    print amounts only for this week's events, so the drafter is not handed
    the obvious ones.
    """
    if money_events is None:
        raise ValueError("money_events unknown for this week")
    if money_events:
        return []
    out = []
    for u in split_units(draft, vocab):
        if u.section in exempt_sections:
            continue
        m = DOLLARS.search(LORE_TAG.sub("", u.raw))
        if m:
            out.append(Finding("money_without_event", u.section, u.line,
                               m.group(0), u.text[:200]))
    return out


# LEAGUE_RULES "Language rule" (Nick, 10-07): every liability line names the
# pot and the window; never "safe from paying" or "certain to pay"
# unqualified. Until 4d the drafted money lines lived in the Money and
# Exposure block, written around the engine's own strings; that block is on
# the hub now, so a dollar line can appear in any section and is checked
# here. The pot: which of the two (regular season / League Championship,
# playoffs / semifinal). The window: when it is settled (weeks a-b, the
# regular season, the semifinals, the playoffs, the final).
POT_WORDS = re.compile(
    r"\b(?:regular[- ]season|playoffs?|semifinals?|semis|league\s+champion(?:ship)?|"
    r"playoff\s+champion(?:ship)?|title)\b", re.I)
WINDOW_WORDS = re.compile(
    r"\b(?:weeks?\s+\d{1,2}\s*(?:-|\u2013|\u2014|to|through)\s*\d{1,2}|regular[- ]season|"
    r"semifinals?|semis|playoffs?|final)\b", re.I)
SAFE_WORDS = re.compile(r"\b(?:safe|certain(?:ly)?)\b", re.I)
PAY_WORDS = re.compile(r"\b(?:pay|pays|paying|paid|payout|owe|owes|owed|collect|collects|pot|pots)\b", re.I)


def money_line_findings(draft: str, vocab: Vocabulary,
                        exempt_sections=EXEMPT_SECTIONS) -> list[Finding]:
    """A money line without its pot and window, in any section but 9
    (finding money_unqualified): a sentence with a dollar figure, or one that
    says "safe" or "certain" about paying, that does not name the pot
    (POT_WORDS) and the window (WINDOW_WORDS). Every week: whether a dollar
    figure may appear at all is money_findings'."""
    out = []
    for u in split_units(draft, vocab):
        if u.section in exempt_sections:
            continue
        raw = LORE_TAG.sub("", u.raw)
        d = DOLLARS.search(raw)
        sf = SAFE_WORDS.search(u.text) if PAY_WORDS.search(u.text) or d else None
        if not (d or sf):
            continue
        if POT_WORDS.search(u.text) and WINDOW_WORDS.search(u.text):
            continue
        out.append(Finding("money_unqualified", u.section, u.line,
                           (d or sf).group(0).rstrip(","), u.text[:200]))
    return out


# 4d: the Betting Lines are the closing line (5g: report_builder.apply_closing_line
# wrote it into the report's previews; metadata.lines names the file). Each
# matchup's four drafted lines must equal the report's preview for that
# matchup, at the precision written: the general number check would pass a
# figure from last week's report, which is in its pool.
_VS = re.compile(r"^\s*\*\*\s*(.+?)\s+vs\.?\s+(.+?)\s*\*\*\s*$", re.I)
_LINE = re.compile(r"^\s*\*?\s*(Line|Win Prob|Moneyline|Avg Score):\s*(.+?)\s*\*?\s*$")


def _num_at(raw: str) -> tuple:
    """(value, decimals) of a printed number."""
    t = raw.replace(",", "").rstrip("%")
    return float(t), (len(t.split(".")[1]) if "." in t else 0)


def _close(raw: str, want: float) -> bool:
    v, d = _num_at(raw)
    return abs(v - float(want)) <= 0.5 * 10 ** -d + 1e-9


def _two_sides(value: str, num: str) -> list:
    """'Team A 55.36% | Team B 44.64%' -> [(team, number)], number LAST (a team
    name can hold digits: Blink-183)."""
    out = []
    for part in value.split("|"):
        m = re.search(r"(" + num + r")\s*$", part.strip())
        if m:
            out.append((part.strip()[:m.start()].strip(), m.group(1)))
    return out


def betting_lines_findings(draft: str, report: dict, team_of: dict) -> list[Finding]:
    """Section 3's line blocks against the report's previews (finding
    betting_line_mismatch): every matchup present, each of its four lines
    present and equal to the preview at the precision written. team_of:
    {manager: team name} (the config's)."""
    prevs = ((report.get("looking_ahead") or {}).get("matchup_previews")) or []
    if not prevs:
        return []
    heads = list(SECTION_HEAD.finditer(draft))
    start = next((h.end() for h in heads if h.group(1) == "3"), None)
    if start is None:
        return [Finding("betting_line_mismatch", 3, 0, "", "no Section 3 in the draft")]
    end = next((h.start() for h in heads if h.start() > start), len(draft))
    first = draft[:start].count("\n") + 1
    by_teams = {}
    for pv in prevs:
        ta = pv.get("team_name_a") or team_of.get(pv["manager_a"])
        tb = pv.get("team_name_b") or team_of.get(pv["manager_b"])
        by_teams[frozenset((ta, tb))] = (pv, {ta: "a", tb: "b"})
    out, seen, cur, got = [], set(), None, {}

    def close_block():
        if cur is None:
            return
        pv, side, line0, label = cur
        for need in ("Line", "Win Prob", "Moneyline", "Avg Score"):
            if need not in got:
                out.append(Finding("betting_line_mismatch", 3, line0, need,
                                   f"{label}: no {need} line (the closing line's block has four)"))
        bl = pv["betting_line"]
        for lab, (ln, value) in got.items():
            bad = []
            if lab == "Line":
                ou = re.search(r"O/U:\s*([\d.,]+)", value)
                if not ou or not _close(ou.group(1), bl["over_under"]):
                    bad.append(f"O/U {ou.group(1) if ou else '?'} (report {bl['over_under']})")
                sp = re.match(r"(.+?)\s*([+-][\d.]+)\s*\((.+?)\s*([+-][\d.]+)\)", value.split("|")[0])
                if not sp:
                    bad.append("spread unreadable")
                else:
                    for t, raw in ((sp.group(1).strip(), sp.group(2)), (sp.group(3).strip(), sp.group(4))):
                        k = side.get(t)
                        if k is None:
                            bad.append(f"team {t!r} is not in this matchup")
                        elif not _close(raw, bl["spread_" + k]):
                            bad.append(f"spread {t} {raw} (report {bl['spread_' + k]:+.1f})")
            else:
                key, num = {"Win Prob": ("win_prob_", r"[\d.]+%"), "Moneyline": ("moneyline_", r"[+-]\d+"),
                            "Avg Score": ("avg_score_", r"[\d.,]+")}[lab]
                pairs = _two_sides(value, num)
                if len(pairs) != 2:
                    bad.append(f"{lab} unreadable")
                for t, raw in pairs:
                    k = side.get(t)
                    if k is None:
                        bad.append(f"team {t!r} is not in this matchup")
                    elif not _close(raw, bl[key + k]):
                        want = bl[key + k]
                        bad.append(f"{lab} {t} {raw} (report "
                                   + (f"{int(want):+d}" if lab == "Moneyline" else f"{want}") + ")")
            for b in bad:
                out.append(Finding("betting_line_mismatch", 3, ln, b, f"{label}: {value}"[:200]))

    for i, raw in enumerate(draft[start:end].splitlines()):
        ln = first + i
        m = _VS.match(raw)
        if m:
            close_block()
            got = {}
            key = frozenset((m.group(1).strip(), m.group(2).strip()))
            hit = by_teams.get(key)
            label = f"{m.group(1).strip()} vs {m.group(2).strip()}"
            if hit is None:
                out.append(Finding("betting_line_mismatch", 3, ln, label,
                                   f"{label} is not a matchup of the report's previews"))
                cur = None
            else:
                seen.add(key)
                cur = (hit[0], hit[1], ln, label)
            continue
        lm = _LINE.match(raw)
        if lm and cur is not None and lm.group(1) not in got:
            got[lm.group(1)] = (ln, lm.group(2))
    close_block()
    for key, (pv, side) in by_teams.items():
        if key not in seen:
            out.append(Finding("betting_line_mismatch", 3, first,
                               " vs ".join(sorted(key)),
                               f"the report previews {' vs '.join(sorted(key))}; Section 3 has no block for it"))
    return out


MAGIC = re.compile(r"\bmagic\s+numbers?\b", re.IGNORECASE)


def magic_number_findings(draft: str, vocab: Vocabulary, week: int,
                          presentation: dict = None) -> list[Finding]:
    """A magic number written before presentation.magic_number_from_week
    (Nick, 11-02: none "until like, at least week 8"). The value is still in
    the report JSON, so number tracing alone would pass it; this rule is by
    week. From that week on: nothing."""
    from .data_loader import shows_magic_number
    if shows_magic_number(week, presentation):
        return []
    out = []
    for u in split_units(draft, vocab):
        m = MAGIC.search(LORE_TAG.sub("", u.raw))
        if m:
            out.append(Finding("magic_number_early", u.section, u.line, m.group(0), u.text[:200]))
    return out


CARD_HEAD = re.compile(r"^\s*\*\*([A-Z][A-Za-z]+) \([^)]*\)\s*(?:\u2014|--|-)\s*"
                       r"[A-F][+-]?\*\*\s*$", re.M)
SECTION_HEAD = re.compile(r"^#{2,4}\s*\*\*(\d+)\.", re.M)


def report_card_findings(draft: str, cards: list) -> list[Finding]:
    """Section 2's cards must run in report_builder.report_card_order.

    The 10-14 dry run printed Nick before Hayden: the drafting prompt said
    letter grade, then Total FP, while the template said overall_score
    (67.6 Hayden, 67.2 Nick). Nick ruled for the template. The order is
    checked, not just documented, because the drafter sorts by hand.
    """
    from modules.report_builder import report_card_order
    ordered = report_card_order([dict(c) for c in cards])
    want = [c["manager"] for c in ordered]
    tied = sorted({c["manager"] for c in ordered if c.get("tied_with")})
    if tied:
        return [Finding("report_card_order", 2, 0, " = ".join(tied),
                        f"{', '.join(tied)} tie on overall_score and weekly_fp; "
                        "no rule orders them -- Nick decides")]
    heads = list(SECTION_HEAD.finditer(draft))
    start = next((h.end() for h in heads if h.group(1) == "2"), None)
    if start is None:
        return [Finding("report_card_order", 2, 0, "", "no Section 2 in the draft")]
    end = next((h.start() for h in heads if h.start() > start), len(draft))
    got = CARD_HEAD.findall(draft[start:end])
    if got != want:
        line = draft[:start].count("\n") + 1
        return [Finding("report_card_order", 2, line, " > ".join(got),
                        f"cards run {' > '.join(got)}; overall_score order "
                        f"is {' > '.join(want)}")]
    return []


# H52 (Nick, 11-17): "made N adds" is checked against the card's own count.
# The card's "New players" line counts everyone who JOINED (this week's adds
# plus last week's claims applied in this window); week 4's drafting chat
# turned Nick's "6 joined" into "made six adds" (he made 3). joined_week_adds
# is the ADD BUDGET table's own count of this week's adds (adff247).
# 5g (week 5's five false positives): a number joined to "week" by a hyphen or
# a space is a week label, not a count -- "all three week-6 adds", "his one
# week-5 add", "week 6 adds" -- so the bare "N adds" form never starts at one.
_ADD_NUM = r"(\d+|one|" + "|".join(sorted(WORD_NUMS, key=len, reverse=True)) + r")"
_NOT_A_WEEK = r"(?<!week-)(?<!week )(?<!wk-)(?<!wk )"
ADDS_CLAIM = re.compile(
    r"\b(?:made|making|makes|make|had|has|used|burned|spent)\s+" + _ADD_NUM +
    r"\s+(?:waiver(?:-wire)?\s+|free[- ]agent\s+)?adds?\b"
    r"|" + _NOT_A_WEEK + r"\b" + _ADD_NUM + r"\s+(?:waiver(?:-wire)?\s+|free[- ]agent\s+)?adds?\b"
    r"(?!\s+(?:left|remaining|to spare|in the bank|available))"
    r"|\badded\s+" + _ADD_NUM + r"\s+(?:new\s+)?players?\b", re.I)


def _add_count(word: str) -> int:
    w = word.lower()
    return 1 if w == "one" else int(w) if w.isdigit() else WORD_NUMS[w]


def adds_claim_findings(draft: str, vocab: Vocabulary, cards: list) -> list[Finding]:
    """"<manager> made N adds" (or "N adds", "added N players") where N is
    more than that manager's card's joined_week_adds for the week. The
    manager is the one named nearest before the phrase in the sentence (else
    after it, else the only manager the unit is about); a phrase with no
    manager to pin it on is not checked. A card from before the split (no
    joined_week_adds) cannot vouch for an add count: that is a finding too."""
    by = {norm(c["manager"]): c for c in cards or [] if c.get("manager")}
    out = []
    for u in split_units(draft, vocab):
        text = norm(LORE_TAG.sub("", u.text))
        mans = [(a, b, c) for a, b, c in vocab.spans(LORE_TAG.sub("", u.text)) if vocab.is_manager(c)]
        for m in ADDS_CLAIM.finditer(text):
            word = next(g for g in m.groups() if g)
            n = _add_count(word)
            before = [c for a, _b, c in mans if a < m.start()]
            after = [c for a, _b, c in mans if a >= m.end()]
            anchor = sorted(c for c in u.anchor if vocab.is_manager(c))
            who = before[-1] if before else after[0] if after else anchor[0] if len(anchor) == 1 else None
            if who is None or who not in by:
                continue
            card = by[who]
            have = card.get("joined_week_adds")
            if have is None:
                out.append(Finding("adds_over_card", u.section, u.line, m.group(0),
                                   f"{card['manager']}'s card has no joined_week_adds (a report from "
                                   f"before 11-17): \"{m.group(0)}\" cannot be checked -- {u.text[:160]}"))
            elif n > int(have):
                out.append(Finding("adds_over_card", u.section, u.line, m.group(0),
                                   f"{card['manager']} made {have} add(s) this week (joined_week_adds; "
                                   f"{card.get('joined_claims', 0)} more joined as last week's claims): "
                                   f"{u.text[:160]}"))
    return out


def _raw_digits(n: Num) -> str:
    return n.raw.replace(",", "").rstrip("%").lstrip("-+$").rstrip(
        "stndrh") or "0"


def check(draft: str, pool: Pool, vocab: Vocabulary,
          lore: Optional[dict] = None,
          exempt_sections=EXEMPT_SECTIONS) -> list[Finding]:
    lore = lore or {}
    findings: list[Finding] = []
    for u in split_units(draft, vocab):
        if u.section in exempt_sections:
            continue
        tags = LORE_TAG.findall(u.raw)
        good_tag = False
        for t in tags:
            e = lore.get(t)
            if e is None or e.get("status") != "approved" or e.get("stale"):
                findings.append(Finding("bad_lore_ref", u.section, u.line, t,
                                        u.text[:200]))
            else:
                good_tag = True
                if e.get("strength") == "fact" and TENDENCY_WORDS.search(
                        u.text):
                    findings.append(Finding(
                        "fact_as_tendency", u.section, u.line,
                        TENDENCY_WORDS.search(u.text).group(0), u.text[:200]))
        support_recs: set = set()
        any_supported = False
        for n in extract_numbers(u.text):
            if n.approx and n.kind in ("num", "pct") and \
                    not n.raw.isalpha() and not re.search(
                        r"~\s*$", u.text[max(0, n.pos - 2):n.pos]):
                # Template rule 2: "Lost by around 100" is wrong; give the
                # number. (A slipped "nearly 60" would also pass any match.)
                findings.append(Finding("approximate_number", u.section,
                                        u.line, n.raw, u.text[:200]))
                continue
            ok, recs = number_supported(n, u, pool)
            if ok:
                any_supported = True
                support_recs |= recs
            else:
                findings.append(Finding("unsupported_number", u.section,
                                        u.line, n.raw, u.text[:200]))
        sups = _superlative_tokens(u.text)
        nums_here = extract_numbers(u.text)
        if sups and (u.is_label or not (SCOPE.search(u.text) or
                                         nums_here)):
            sups = []                      # rhetorical: no scope, no number
        if sups and not good_tag:
            ranked = any(RANK_FIELD.search(pool.records[r].label)
                         for r in support_recs) or any(
                _field_extreme(n, pool) for n in nums_here
                if n.kind in ("num", "pct"))
            ents = u.anchor
            vals = {_key_of(abs(n.value), n.raw.replace(",", "").rstrip(
                "%").lstrip("-+$")) for n in nums_here
                if n.kind in ("num", "pct")}
            stated = bool(ents) and any(
                (r.ents & ents) and any(s in r.text for s in sups) and
                (not vals or any(k in set(_keys(v)) for v in r.nums
                                 for k in vals))
                for r in pool.records)
            if not (ranked or stated):
                findings.append(Finding("unsupported_superlative", u.section,
                                        u.line, sups[0], u.text[:200]))
        hist = HISTORY.search(u.text)
        if hist and not good_tag and not any_supported:
            stem = hist.group(0).lower()[:6]
            ents = u.anchor
            if ents and any((r.ents & ents) and stem in r.label
                            for r in pool.records):
                hist = None
        if hist and not good_tag and not any_supported:
            findings.append(Finding("unsourced_history", u.section, u.line,
                                    HISTORY.search(u.text).group(0),
                                    u.text[:200]))
    return findings


def build_pool(vocab: Vocabulary, reports: list, markdowns: list,
               lore_entries: list = ()) -> Pool:
    """reports: [(name, json_obj)], markdowns: [(name, text)]."""
    pool = Pool()
    for name, obj in reports:
        add_json(pool, obj, vocab, name)
    for name, md in markdowns:
        add_markdown(pool, md, vocab, name)
    add_lore(pool, list(lore_entries), vocab)
    return pool


def players_in(obj) -> set:
    """Player names a report carries: values under *player*/name keys and
    keys of player-keyed dicts."""
    out = set()

    def walk(o, key=""):
        if isinstance(o, dict):
            for k, v in o.items():
                if isinstance(v, str) and ("player" in k or k in (
                        "name", "player_name", "added", "dropped")):
                    out.add(v)
                if k in ("player_lookup", "players") and isinstance(v, dict):
                    out.update(v.keys())
                walk(v, k)
        elif isinstance(o, list):
            for v in o:
                if isinstance(v, str) and key in ("il_players", "players",
                                                  "top_5_keepers"):
                    out.add(v)
                walk(v, key)

    walk(obj)
    return {p for p in out if re.match(r"^[A-Z][\w.'-]+(?: [A-Z][\w.'-]+)+$",
                                       p)}
