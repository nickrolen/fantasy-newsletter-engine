"""
League lore: the only bridge for knowledge the stats report can't prove.

config/LEAGUE_LORE.json holds entries. Nick owns every one; the engine
only proposes.

  kind "written"  -- Nick's words: reputations, habits, the stuff nobody
                     says out loud. Static. Sayable once approved.
  kind "derived"  -- a tendency found in the data ("Garrett in December").
                     Stores its DEFINITION, not its numbers: every refresh
                     recomputes it and re-renders the text from a template,
                     so an approved entry can never quietly go out of date.
                     If the tendency stops holding it is flagged stale and
                     the claim check stops accepting it.
  kind "alias"    -- a nickname ("NAW", "Wemby") the claim check should
                     read as the player.

Proposals are honest about multiple comparisons. Every family scans many
cells (4 managers x 7 months x ...); some will look striking by chance.
Each cell gets a permutation p-value, and a cell is proposed only if it
survives Benjamini-Hochberg at FDR_Q across EVERY cell scanned this run.
The evidence block says how many were scanned.

Once approved, an entry is one pre-registered claim, not a scan, so it is
monitored on its own p-value: stale when p > STALE_P or the direction flips.
"""

from __future__ import annotations

import json
import math
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Callable, Optional

import numpy as np

LORE_FILE = "config/LEAGUE_LORE.json"
FDR_Q = 0.10          # a TENDENCY: survives FDR across every cell scanned
FACT_P = 0.05         # a FACT worth offering: striking on its own, but in
                      # a 60-cell scan ~3 cells clear this by chance alone
LOYALTY_MIN_SEASONS = 4   # draft-day appearances that make a pairing lore
STALE_P = 0.10        # an approved claim stops holding above this
PERMUTATIONS = 4000
SEED = 20261007
CLOSE_GAME_QUANTILE = 0.10   # "close" = the closest tenth of all games
MIN_GAMES = 12               # cells with fewer games aren't evaluated

MONTH_NAMES = {10: "October", 11: "November", 12: "December", 1: "January",
               2: "February", 3: "March", 4: "April"}
PHASES = ("early", "late", "playoffs")
PHASE_LABEL = {"early": "the first third of the regular season",
               "late": "the last third of the regular season",
               "playoffs": "the playoffs"}


# ------------------------------------------------------------------ data

@dataclass(frozen=True)
class Game:
    season: str
    week: int
    manager: str
    opponent: str
    score: float
    opp_score: float

    @property
    def won(self) -> bool:
        return self.score > self.opp_score

    @property
    def margin(self) -> float:
        return abs(self.score - self.opp_score)


def games_from_matchups(matchups: list) -> list[Game]:
    out = []
    for m in matchups:
        a, b = m.get("score_a"), m.get("score_b")
        if a is None or b is None or a == b:
            continue
        out.append(Game(m["season"], int(m["week"]), m["manager_a"],
                        m["manager_b"], float(a), float(b)))
        out.append(Game(m["season"], int(m["week"]), m["manager_b"],
                        m["manager_a"], float(b), float(a)))
    return out


def current_season_matchups(schedule: dict, weekly_scores: dict,
                            season: str) -> list:
    """This season's played matchups from SCHEDULE.json pairings and
    RECORDS.json weekly_scores (the historical file is only rolled at
    season end)."""
    score = {(m, int(r["week"])): float(r["score"])
             for m, rows in (weekly_scores or {}).items() for r in rows}
    out = []
    for w in schedule.get("weeks", []):
        for p in w.get("matchups", []):
            a, b = p.get("manager_a"), p.get("manager_b")
            if (a, w["week"]) in score and (b, w["week"]) in score:
                out.append({"season": season, "week": w["week"],
                            "manager_a": a, "manager_b": b,
                            "score_a": score[(a, w["week"])],
                            "score_b": score[(b, w["week"])]})
    return out


def week_months(playerlog_rows: Optional[list] = None,
                schedule: Optional[dict] = None,
                season: Optional[str] = None) -> dict:
    """(season, week) -> calendar month of the week's first day."""
    first: dict = {}
    for r in playerlog_rows or ():
        k = (r.get("season_key"), int(r.get("week", 0)))
        d = r.get("date")
        if d and (k not in first or d < first[k]):
            first[k] = d
    for w in (schedule or {}).get("weeks", []):
        if season and w.get("start_date"):
            first[(season, int(w["week"]))] = w["start_date"]
    return {k: int(v[5:7]) for k, v in first.items()}


# ------------------------------------------------------------------ cells

@dataclass
class Cell:
    id: str
    family: str
    manager: str
    definition: dict
    template: str
    values: dict
    p: float
    n: int
    direction: str            # "high" | "low"
    q: float = 1.0
    tested: bool = True       # False: a count, true by definition (loyalty)

    def render(self) -> str:
        return render(self.template, self.values)


def render(template: str, values: dict) -> str:
    return template.format(**values)


def _perm_p(observed: float, null: np.ndarray) -> float:
    """Two-sided permutation p-value, (k + 1) / (N + 1)."""
    k = int(np.sum(np.abs(null) >= abs(observed) - 1e-12))
    return (k + 1) / (len(null) + 1)


def _split_record(games, inside):
    w = sum(1 for g, i in zip(games, inside) if i and g.won)
    l = sum(1 for g, i in zip(games, inside) if i and not g.won)
    ow = sum(1 for g, i in zip(games, inside) if not i and g.won)
    ol = sum(1 for g, i in zip(games, inside) if not i and not g.won)
    return w, l, ow, ol


def _label_cell(games, labels, target, rng, perms):
    """Win% with label == target minus win% otherwise, permuting labels
    within the manager's games."""
    won = np.array([g.won for g in games], dtype=float)
    lab = np.array(labels, dtype=object)
    inside = lab == target
    n_in = int(inside.sum())
    if n_in < MIN_GAMES or n_in > len(games) - MIN_GAMES:
        return None
    obs = won[inside].mean() - won[~inside].mean()
    null = np.empty(perms)
    for i in range(perms):
        s = rng.permutation(inside)
        null[i] = won[s].mean() - won[~s].mean()
    return obs, _perm_p(obs, null), inside


def _phase(game: Game, regular_through: Callable) -> Optional[str]:
    rt = regular_through(game.season)
    if game.week > rt:
        return "playoffs"
    if game.week <= rt / 3:
        return "early"
    if game.week > 2 * rt / 3:
        return "late"
    return None


def _seasons(games) -> str:
    s = sorted({g.season for g in games})
    return f"{s[0]} to {s[-1]}" if s else ""


def scan(games: list[Game], months: dict, regular_through: Callable,
         drafts: list = (), positions: Optional[dict] = None,
         perms: int = PERMUTATIONS, seed: int = SEED) -> list[Cell]:
    """Every cell of every family. No filtering here: the filter is FDR."""
    rng = np.random.default_rng(seed)
    cells: list[Cell] = []
    by_mgr = defaultdict(list)
    for g in games:
        by_mgr[g.manager].append(g)
    span = _seasons(games)

    # month
    for m, gs in sorted(by_mgr.items()):
        labels = [months.get((g.season, g.week)) for g in gs]
        for mon in sorted({x for x in labels if x}, key=lambda x: (x < 9, x)):
            r = _label_cell(gs, labels, mon, rng, perms)
            if not r:
                continue
            obs, p, inside = r
            w, l, ow, ol = _split_record(gs, inside)
            cells.append(Cell(
                f"month-{m.lower()}-{MONTH_NAMES[mon][:3].lower()}", "month",
                m, {"family": "month", "manager": m, "month": mon},
                "{manager} is {w}-{l} in {month} matchups ({pct}% wins), "
                "against {ow}-{ol} ({opct}%) the rest of the year, "
                "{span}.",
                dict(manager=m, month=MONTH_NAMES[mon], w=w, l=l, ow=ow, ol=ol,
                     pct=round(100 * w / max(w + l, 1)),
                     opct=round(100 * ow / max(ow + ol, 1)), span=span),
                p, w + l, "high" if obs > 0 else "low"))

    # season phase
    for m, gs in sorted(by_mgr.items()):
        labels = [_phase(g, regular_through) for g in gs]
        for ph in PHASES:
            r = _label_cell(gs, labels, ph, rng, perms)
            if not r:
                continue
            obs, p, inside = r
            w, l, ow, ol = _split_record(gs, inside)
            cells.append(Cell(
                f"phase-{m.lower()}-{ph}", "phase", m,
                {"family": "phase", "manager": m, "phase": ph},
                "{manager} is {w}-{l} in {phase} ({pct}% wins), against "
                "{ow}-{ol} ({opct}%) the rest of the time, {span}.",
                dict(manager=m, phase=PHASE_LABEL[ph], w=w, l=l, ow=ow, ol=ol,
                     pct=round(100 * w / max(w + l, 1)),
                     opct=round(100 * ow / max(ow + ol, 1)), span=span),
                p, w + l, "high" if obs > 0 else "low"))

    # close games: exact binomial against a coin flip
    margins = sorted(g.margin for g in games)
    if margins:
        close = margins[int(CLOSE_GAME_QUANTILE * (len(margins) - 1))]
        for m, gs in sorted(by_mgr.items()):
            cg = [g for g in gs if g.margin <= close]
            if len(cg) < MIN_GAMES:
                continue
            w = sum(g.won for g in cg)
            n = len(cg)
            p = _binom_two_sided(w, n)
            cells.append(Cell(
                f"close-{m.lower()}", "close", m,
                {"family": "close", "manager": m,
                 "quantile": CLOSE_GAME_QUANTILE},
                "{manager} is {w}-{l} in games decided by {close} points or "
                "fewer (the closest tenth of all games), {span}.",
                dict(manager=m, w=w, l=n - w, close=round(close, 2),
                     span=span), p, n, "high" if w > n / 2 else "low"))

    # volatility: weekly score relative to that week's league average
    wk_mean = defaultdict(list)
    for g in games:
        wk_mean[(g.season, g.week)].append(g.score)
    wk_mean = {k: float(np.mean(v)) for k, v in wk_mean.items()}
    rel = {m: np.array([g.score / wk_mean[(g.season, g.week)] for g in gs])
           for m, gs in by_mgr.items()}
    if len(rel) >= 3:
        pooled = np.concatenate(list(rel.values()))
        sizes = {m: len(v) for m, v in rel.items()}
        for m, v in sorted(rel.items()):
            obs = float(np.std(v)) - float(np.std(pooled))
            null = np.empty(perms)
            for i in range(perms):
                null[i] = float(np.std(rng.choice(pooled, sizes[m],
                                                  replace=False))) - \
                    float(np.std(pooled))
            p = _perm_p(obs, null)
            cells.append(Cell(
                f"volatility-{m.lower()}", "volatility", m,
                {"family": "volatility", "manager": m},
                "{manager}'s weekly scores swing {dir} the league's: a typical "
                "week lands {sd}% from the league average, against {lsd}% "
                "for the league, {span}.",
                dict(manager=m, dir="more than" if obs > 0 else "less than",
                     sd=round(100 * float(np.std(v)), 1),
                     lsd=round(100 * float(np.std(pooled)), 1), span=span),
                p, len(v), "high" if obs > 0 else "low"))

    # streakiness: runs in each season's regular-season W/L sequence
    for m, gs in sorted(by_mgr.items()):
        seqs = []
        for s in sorted({g.season for g in gs}):
            rt = regular_through(s)
            seq = [g.won for g in sorted(gs, key=lambda g: g.week)
                   if g.season == s and g.week <= rt]
            if len(seq) >= 6:
                seqs.append(np.array(seq))
        if not seqs:
            continue
        obs_runs = sum(_runs(x) for x in seqs)
        null = np.array([sum(_runs(rng.permutation(x)) for x in seqs)
                         for _ in range(perms)])
        exp = float(null.mean())
        p = _perm_p(obs_runs - exp, null - exp)
        cells.append(Cell(
            f"streaks-{m.lower()}", "streaks", m,
            {"family": "streaks", "manager": m},
            "{manager}'s results come {how}: {runs} win/loss runs across "
            "{seasons} regular seasons, where a random order of the same "
            "results gives about {exp}.",
            dict(manager=m, how="in streaks" if obs_runs < exp else
                 "alternating more than chance", runs=obs_runs,
                 seasons=len(seqs), exp=round(exp)),
            p, sum(len(x) for x in seqs),
            "low" if obs_runs < exp else "high"))

    # playoff scoring relative to own regular season
    for m, gs in sorted(by_mgr.items()):
        labels = ["po" if g.week > regular_through(g.season) else "rs"
                  for g in gs]
        v = np.array([g.score / wk_mean[(g.season, g.week)] for g in gs])
        inside = np.array([x == "po" for x in labels])
        if inside.sum() < MIN_GAMES // 2:
            continue
        obs = v[inside].mean() - v[~inside].mean()
        null = np.empty(perms)
        for i in range(perms):
            s = rng.permutation(inside)
            null[i] = v[s].mean() - v[~s].mean()
        p = _perm_p(obs, null)
        cells.append(Cell(
            f"playoff-scoring-{m.lower()}", "playoff_scoring", m,
            {"family": "playoff_scoring", "manager": m},
            "{manager} scores {pct}% {dir} the league average in the playoffs, "
            "against {rpct}% {rdir} in the regular season ({n} playoff "
            "games, {span}).",
            dict(manager=m, pct=abs(round(100 * (v[inside].mean() - 1), 1)),
                 dir="above" if v[inside].mean() >= 1 else "below",
                 rpct=abs(round(100 * (v[~inside].mean() - 1), 1)),
                 rdir="above" if v[~inside].mean() >= 1 else "below",
                 n=int(inside.sum()), span=span),
            p, int(inside.sum()), "high" if obs > 0 else "low"))

    # draft: round of the first non-keeper pick at a position
    if drafts and positions:
        for pos, label in (("C", "center"), ("PG", "point guard")):
            first: dict = {}
            for d in drafts:
                if d.get("is_keeper"):
                    continue
                pp = positions.get((d["season"], _pkey(d["player_name"]))) or \
                    positions.get((None, _pkey(d["player_name"])), "")
                if pos not in [x.strip() for x in pp.split(",")]:
                    continue
                k = (d["season"], d["manager"])
                first[k] = min(first.get(k, 99), int(d["round"]))
            seasons = sorted({s for s, _ in first})
            mgrs = sorted({m for _, m in first})
            full = [s for s in seasons if all((s, m) in first for m in mgrs)]
            if len(full) < 4 or len(mgrs) < 3:
                continue
            mat = np.array([[first[(s, m)] for m in mgrs] for s in full],
                           dtype=float)
            for j, m in enumerate(mgrs):
                obs = mat[:, j].mean() - mat.mean()
                null = np.empty(perms)
                for i in range(perms):
                    sh = np.array([rng.permutation(r) for r in mat])
                    null[i] = sh[:, j].mean() - sh.mean()
                p = _perm_p(obs, null)
                cells.append(Cell(
                    f"draft-first-{pos.lower()}-{m.lower()}", "draft", m,
                    {"family": "draft", "manager": m, "position": pos},
                    "{manager} takes his first {label} in round {avg} on "
                    "average, against {lavg} for the league ({n} drafts, "
                    "{first_s} to {last_s}).",
                    dict(manager=m, label=label,
                         avg=round(float(mat[:, j].mean()), 1),
                         lavg=round(float(mat.mean()), 1), n=len(full),
                         first_s=full[0], last_s=full[-1]),
                    p, len(full), "late" if obs > 0 else "early"))
    # loyalty: the same player on the same manager's draft day, again and
    # again (fresh pick or keeper). A count, not a test.
    if drafts:
        cnt: dict = defaultdict(lambda: [0, 0, []])
        for d in drafts:
            k = (d["manager"], d["player_name"])
            cnt[k][1 if d.get("is_keeper") else 0] += 1
            cnt[k][2].append(d["season"])
        for (m, pl), (fresh, kept, ss) in sorted(cnt.items()):
            if fresh + kept < LOYALTY_MIN_SEASONS:
                continue
            ss = sorted(set(ss))
            cells.append(Cell(
                f"loyalty-{m.lower()}-{_pkey(pl)}", "loyalty", m,
                {"family": "loyalty", "manager": m, "player": pl},
                "{player} has been on {manager}'s roster on draft day in "
                "{n} of {seasons} drafts ({fresh} picked, {kept} kept), "
                "{first_s} to {last_s}.",
                dict(manager=m, player=pl, n=len(ss), fresh=fresh, kept=kept,
                     seasons=len({d["season"] for d in drafts}),
                     first_s=ss[0], last_s=ss[-1]),
                0.0, fresh + kept, "high", tested=False))
    return cells


def _runs(seq) -> int:
    seq = list(seq)
    return 1 + sum(1 for a, b in zip(seq, seq[1:]) if a != b) if seq else 0


def _binom_two_sided(k: int, n: int) -> float:
    probs = [math.comb(n, i) / 2 ** n for i in range(n + 1)]
    pk = probs[k]
    return min(1.0, sum(p for p in probs if p <= pk + 1e-15))


def _pkey(name: str) -> str:
    return re.sub(r"[^a-z]", "", name.lower())


def positions_from_playerlog(rows: list) -> dict:
    out: dict = {}
    for r in rows:
        nm, pos = r.get("player_name"), r.get("positions")
        if nm and pos:
            out[(r.get("season_key"), _pkey(nm))] = pos
            out[(None, _pkey(nm))] = pos
    return out


def benjamini_hochberg(cells: list[Cell]) -> None:
    """Sets each cell's q-value (BH-adjusted p) in place."""
    cells = [c for c in cells if c.tested]
    m = len(cells)
    order = sorted(range(m), key=lambda i: cells[i].p)
    q = [1.0] * m
    prev = 1.0
    for rank in range(m, 0, -1):
        i = order[rank - 1]
        prev = min(prev, cells[i].p * m / rank)
        q[i] = prev
    for i, c in enumerate(cells):
        c.q = min(1.0, q[i])


# ------------------------------------------------------------------ file

def load(base: Path) -> dict:
    p = Path(base) / LORE_FILE
    if not p.exists():
        return {"entries": []}
    return json.loads(p.read_text(encoding="utf-8"))


BACKUP_DIR = Path("data") / "lore_backups"


def save(base: Path, lore: dict) -> Path:
    """Write the file, keeping one backup per day. The file is not in git
    (the repo is public), so these backups are its only history."""
    p = Path(base) / LORE_FILE
    p.parent.mkdir(parents=True, exist_ok=True)
    if p.exists():
        bdir = Path(base) / BACKUP_DIR
        bdir.mkdir(parents=True, exist_ok=True)
        bak = bdir / f"LEAGUE_LORE_{date.today().isoformat()}.json"
        if not bak.exists():
            bak.write_bytes(p.read_bytes())
    p.write_text(json.dumps(lore, indent=2, ensure_ascii=True) + "\n",
                 encoding="utf-8")
    return p


def strength_of(c: Cell) -> Optional[str]:
    """tendency: beats chance after correcting for the scan -- may be told
    as character ("Benton fades in February"). fact: true and checkable,
    but not evidence of a pattern -- told as history only ("Benton is 6-22
    in February"). None: not worth offering."""
    if not c.tested:
        return "fact"
    if c.q <= FDR_Q:
        return "tendency"
    if c.p <= FACT_P:
        return "fact"
    return None


def _evidence(c: Cell, scanned: int, today: str) -> dict:
    if not c.tested:
        return {"count": c.n, "checked_on": today,
                "note": "a count from the draft history; no test needed"}
    ev = {"games_or_drafts": c.n, "p": round(c.p, 5), "q": round(c.q, 4),
          "direction": c.direction, "cells_scanned": scanned,
          "fdr_q": FDR_Q, "checked_on": today}
    if strength_of(c) == "fact":
        ev["note"] = (f"True, but not a pattern: {scanned} cells were "
                      f"scanned, and about {round(FACT_P * scanned)} would "
                      f"look this striking by chance. Say it as history, "
                      f"not as character.")
    return ev


def propose(lore: dict, cells: list[Cell], today: Optional[str] = None
            ) -> list[dict]:
    """Add a proposed entry for each cell worth offering that isn't already
    in the file in any status. A rejected entry stays in the file with its
    decision log -- never re-proposed, never destroyed, and reversible with
    review_lore.py --revisit."""
    today = today or date.today().isoformat()
    benjamini_hochberg(cells)
    scanned = sum(1 for c in cells if c.tested)
    have = {e.get("id") for e in lore.get("entries", [])}
    new = []
    for c in sorted(cells, key=lambda c: (c.tested, c.q, c.p)):
        st = strength_of(c)
        if st is None or c.id in have:
            continue
        e = {"id": c.id, "kind": "derived", "strength": st,
             "status": "proposed",
             "definition": c.definition, "template": c.template,
             "text": c.render(), "entities": [c.manager],
             "values": [v for v in c.values.values()
                        if isinstance(v, (int, float))],
             "render_values": c.values,
             "evidence": _evidence(c, scanned, today),
             "stale": False}
        lore.setdefault("entries", []).append(e)
        new.append(e)
    return new


def refresh(lore: dict, cells: list[Cell], today: Optional[str] = None
            ) -> list[str]:
    """Recompute every derived entry from its definition. Returns the ids
    that changed state (newly stale, or recovered)."""
    today = today or date.today().isoformat()
    by_id = {c.id: c for c in cells}
    changed = []
    for e in lore.get("entries", []):
        if e.get("kind") != "derived":
            continue
        c = by_id.get(e["id"])
        was = bool(e.get("stale"))
        if c is None:
            e["stale"] = True
            e["stale_reason"] = "no longer computable from the data"
        else:
            e["values"] = [v for v in c.values.values()
                           if isinstance(v, (int, float))]
            e["render_values"] = c.values
            try:
                e["text"] = render(e.get("template", c.template), c.values)
            except (KeyError, IndexError, ValueError) as err:
                e["stale"] = True
                e["stale_reason"] = f"template no longer renders: {err}"
                changed += [e["id"]] if not was else []
                continue
            e.setdefault("evidence", {})["checked_on"] = today
            if e.get("strength") == "tendency":
                # one pre-registered claim now: judged on its own p
                flipped = c.direction != e["evidence"].get(
                    "direction", c.direction)
                e["evidence"].update({"p_now": round(c.p, 5),
                                      "games_or_drafts": c.n})
                e["stale"] = flipped or c.p > STALE_P
                e["stale_reason"] = ("direction flipped" if flipped else
                                     f"p {c.p:.3f} > {STALE_P}"
                                     if e["stale"] else "")
            else:
                # a fact re-renders with today's numbers; it can't go false
                e["stale"] = False
                e["stale_reason"] = ""
        if bool(e["stale"]) != was:
            changed.append(e["id"])
    return changed


# ------------------------------------------------------------------ aliases

def propose_aliases(lore: dict, drafts_text: list[str], players: set,
                    today: Optional[str] = None,
                    reserved: set = frozenset()) -> list[dict]:
    """Nicknames used in past newsletters: initials (SGA, NAW, KAT) or a
    shortened surname (Wemby). A token is proposed only when exactly ONE
    known player fits it, it isn't itself a word of any player's name or a
    reserved word (team names, managers), and it was used at least twice."""
    today = today or date.today().isoformat()
    have = {e.get("id") for e in lore.get("entries", [])}
    name_words = {w.lower() for p in players for w in re.split(r"[\s-]+", p)}
    name_words |= {w.lower() for r in reserved for w in re.split(r"\s+", r)}
    nba_codes = {"NBA", "FP", "FPPG", "IL", "GTD", "UTIL", "PG", "SG", "SF",
                 "PF", "ROS", "POTW", "MVP", "OT", "CV", "ATL", "BOS", "BKN",
                 "CHA", "CHI", "CLE", "DAL", "DEN", "DET", "GSW", "HOU", "IND",
                 "LAC", "LAL", "MEM", "MIA", "MIL", "MIN", "NOP", "NYK", "OKC",
                 "ORL", "PHI", "PHX", "POR", "SAC", "SAS", "TOR", "UTA", "WAS"}
    counts: dict = defaultdict(int)
    near: dict = defaultdict(int)
    for text in drafts_text:
        for para in re.split(r"\n\s*\n", text):
            for tok in set(re.findall(r"\b([A-Z]{3,4}|[A-Z][a-z]{3,7})\b",
                                      para)):
                if tok in nba_codes or tok.lower() in name_words:
                    continue
                fits = [p for p in players if _fits(tok, p)]
                if len(fits) == 1:
                    counts[(tok, fits[0])] += 1
                    surname = re.split(r"[\s-]+", fits[0])[-1]
                    if surname in para:
                        near[(tok, fits[0])] += 1
    # A shortened surname must have appeared next to the real one at least
    # once ("Wemby" beside "Wembanyama"); otherwise "Power" (Rankings) is
    # Norman Powell. Initials only need to be unique.
    counts = {k: v for k, v in counts.items()
              if k[0].isupper() and k[0] == k[0].upper() or near[k]}
    new = []
    for (tok, name), n in sorted(counts.items(), key=lambda x: -x[1]):
        aid = f"alias-{tok.lower()}"
        if n < 2 or aid in have:
            continue
        e = {"id": aid, "kind": "alias", "status": "proposed",
             "alias": tok, "name": name,
             "text": f"{tok} = {name}",
             "evidence": {"uses_in_past_newsletters": n,
                          "checked_on": today}}
        lore.setdefault("entries", []).append(e)
        have.add(aid)
        new.append(e)
    return new


def _fits(tok: str, name: str) -> bool:
    parts = [p for p in re.split(r"[\s-]+", name) if p and
             p.lower().rstrip(".") not in ("jr", "sr", "ii", "iii", "iv")]
    if tok.isupper():
        return "".join(p[0].upper() for p in parts) == tok
    last = parts[-1] if parts else ""
    return len(tok) >= 4 and last.lower().startswith(tok.lower()[:4]) and \
        tok.lower() != last.lower() and tok.lower()[:-1] in last.lower()


def decide(entry: dict, status: str, today: Optional[str] = None,
           note: str = "") -> None:
    """Every status change is logged on the entry; nothing is destroyed."""
    prev = entry.get("status")
    entry.setdefault("decisions", []).append(
        {"on": today or date.today().isoformat(), "from": prev, "to": status,
         **({"note": note} if note else {})})
    entry["status"] = status
    if status == "approved":
        entry["approved_on"] = today or date.today().isoformat()


def undo(entry: dict) -> bool:
    """Revert the last logged decision (logged too)."""
    log = entry.get("decisions") or []
    if not log:
        return False
    last = log[-1]
    decide(entry, last["from"], note=f"undo of {last['to']}")
    return True


def approved(lore: dict) -> list[dict]:
    return [e for e in lore.get("entries", [])
            if e.get("status") == "approved" and not e.get("stale")]


def approved_aliases(lore: dict) -> dict:
    return {e["alias"]: e["name"] for e in lore.get("entries", [])
            if e.get("kind") == "alias" and e.get("status") == "approved"}
