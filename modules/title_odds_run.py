"""
title_odds_run.py -- one title-odds run, and everything it writes (step 1c).

The weekly build and the nightly run price title odds through this module,
so there is one path (HANDOFF_STEP1C1 s.3):

  run_pass(data, seed, sims, statuses)   the season pass (season_sim.run_season)
                                         as deep as the season's format goes --
                                         exactly the weekly build's call
  record(base, sp, ...)                  the run's three outputs:
      output/title_odds_history.jsonl    one row (modules/title_odds_history):
                                         title odds, now with each manager's
                                         expected record, and playoff and Cup
                                         odds when the pass computed them
      output/title_odds_latest.json      the whole result the hub's power
                                         rankings need: odds, expected records,
                                         finish distributions, the records the
                                         run saw, its seed and as-of. The hub
                                         reads THIS, not stats_report_weekN.json
      output/stakes.json                 each team's leverage in each remaining
                                         week (INJURED_DROP_DESIGN s.3.1), for
                                         task 18b; nothing reads it yet
  price(base, data, ...)                 the nightly / pre-tip / closing run:
                                         refuses while prices are locked
                                         (modules/price_lock), then run_pass +
                                         record

THE STAKES (INJURED_DROP_DESIGN s.3.1; Nick, 11-03), read off the iterations
the pass already ran -- no extra simulation:
    RS leverage(team, w)      = P(regular-season title | wins week w)
                              - P(regular-season title | loses week w)
                                for every regular-season week not yet decided;
    playoff leverage(team, w) = P(champion | wins week w)
                              - P(champion | loses week w)
                                for every bracket week not yet decided.
"Wins week w" is the team's own matchup that week (season_sim.SeasonPass.
week_results); a regular-season T is neither a win nor a loss and is left out
of both. A week the team cannot win or cannot lose in any iteration has no
leverage: null, with the counts, never a number made up. A regular-season
week whose every day is already banked is decided and has no row.

SCHEMA 2 (task 18b) adds, read off the same iterations and still drawing
nothing:
    each row's margin_mean, margin_sd -- his score minus his opponent's that
        week, over the iterations he has a game. modules/injured_drop turns
        a point into a change in the week's win chance with them (the
        margin's density at zero, a normal fit: phi(mean/sd)/sd);
    each team's rs_title and champion -- P(regular-season title) and
        P(champion) over the whole pass ("little left to play for", design
        s.3.3); champion is null when the pass stopped before the bracket;
    the season the file is for.

Nothing that scores probabilities reads any of these files (invariant 13;
tests/test_title_odds_history.py pins it for all three).
"""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path

import numpy as np

LATEST_FILE = Path("output") / "title_odds_latest.json"
STAKES_FILE = Path("output") / "stakes.json"
# Every nightly.py mode that prices title odds is a kind (11-11: Step 3a/3b's
# refresh, poll and afternoon runs were refused here, "kind must be one of";
# tests/test_title_odds_kinds.py pins nightly.MODES against this tuple).
KINDS = ("nightly", "pretip", "closing", "weekly_build", "refresh", "poll", "afternoon")
SCHEMA = 1
STAKES_SCHEMA = 2           # 2: margins, rs_title / champion, season (task 18b)


class TitleOddsLocked(RuntimeError):
    """Games are on (modules/price_lock): title odds were not priced."""


def through_for() -> str:
    """How deep the season's format goes: the weekly build's own rule."""
    from .simulator_playoff_odds import bracket_rounds
    from .simulator_cup_odds import cup_rounds
    return ("cup" if bracket_rounds() and cup_rounds()
            else "playoffs" if bracket_rounds() else "regular")


def run_pass(data, *, seed: int, sims: int, statuses, through: str = None):
    """The season pass the weekly build and the nightly run both price from."""
    from .season_sim import run_season
    return run_season(data, num_simulations=sims, seed=seed, injury_statuses=statuses,
                      through=through or through_for())


# =============================================================================
# the stakes
# =============================================================================

def margin_stats(margin) -> dict:
    """{margin_mean, margin_sd} over the iterations with a game (not NaN);
    both None when there is none."""
    m = np.asarray(margin, float)
    m = m[~np.isnan(m)]
    if not len(m):
        return {"margin_mean": None, "margin_sd": None}
    return {"margin_mean": float(m.mean()), "margin_sd": float(m.std())}


def leverage(won: np.ndarray, outcome: np.ndarray) -> dict:
    """P(outcome | won the week) - P(outcome | lost it), over the iterations.
    won: 1.0 / 0.0 / 0.5 (a T) / NaN (no game); outcome: bool. A T or no
    game is in neither group."""
    won = np.asarray(won, float)
    outcome = np.asarray(outcome, bool)
    w, lo = won == 1.0, won == 0.0
    n_w, n_l = int(w.sum()), int(lo.sum())
    out = {"n_win": n_w, "n_loss": n_l, "n_tie": int((won == 0.5).sum())}
    if n_w == 0 or n_l == 0:
        out.update(p_if_win=(float(outcome[w].mean()) if n_w else None),
                   p_if_loss=(float(outcome[lo].mean()) if n_l else None), leverage=None,
                   why=("never wins this week in the simulation" if n_w == 0
                        else "never loses this week in the simulation"))
        return out
    pw, pl = float(outcome[w].mean()), float(outcome[lo].mean())
    out.update(p_if_win=pw, p_if_loss=pl, leverage=pw - pl)
    return out


def _decided_by_banking(sp, week: int) -> bool:
    """A regular-season week the pass took from the logs whole: every day of
    it banked (its as-of is past the week's last day)."""
    ip = (sp.in_progress or {}).get(week)
    if not ip:
        return False
    from .week_state import week_entry
    end = date.fromisoformat(str(week_entry(sp.data, week)["end_date"])[:10])
    return date.fromisoformat(ip["as_of"]) > end


def stakes(sp) -> dict:
    """{manager: {"regular_season": {week: ...}, "playoffs": {week: ...}}}
    (weeks as strings), each entry leverage()'s dict renamed to its race."""
    from .simulator_playoff_odds import bracket_weeks
    last_reg = sp.regular_weeks[1]
    bracket = set(bracket_weeks()) if sp.through in ("playoffs", "cup") else set()
    title = {j: sp.reg_finish[:, 0] == j for j in range(len(sp.managers))}
    champ = {j: sp.playoff_finish[:, 0] == j for j in range(len(sp.managers))}
    played_bracket = sp.through in ("playoffs", "cup")
    out = {m: {"rs_title": float(title[j].mean()),
               "champion": float(champ[j].mean()) if played_bracket else None,
               "regular_season": {}, "playoffs": {}} for j, m in enumerate(sp.managers)}
    margins = getattr(sp, "week_margins", None) or {}
    for w in sorted(sp.week_results):
        arr = sp.week_results[w]
        marg = margins.get(w)
        if marg is None:
            raise ValueError(f"the season pass has results but no margins for week {w}")
        if w <= last_reg:
            if _decided_by_banking(sp, w):
                continue
            for j, m in enumerate(sp.managers):
                lv = leverage(arr[:, j], title[j])
                lv["rs_leverage"] = lv.pop("leverage")
                lv.update(margin_stats(marg[:, j]))
                out[m]["regular_season"][str(w)] = lv
        elif w in bracket:
            for j, m in enumerate(sp.managers):
                if np.isnan(arr[:, j]).all():
                    continue
                lv = leverage(arr[:, j], champ[j])
                lv["playoff_leverage"] = lv.pop("leverage")
                lv.update(margin_stats(marg[:, j]))
                out[m]["playoffs"][str(w)] = lv
    return out


# =============================================================================
# the outputs
# =============================================================================

def _records_after_banked(sp) -> dict:
    """The league's records with every fully banked in-progress week's result
    added: what the standings will read once the weekly build records that
    week. {manager: Record}."""
    from .data_loader import week_outcome
    from .week_state import week_entry
    recs = {m: sp.data.get_manager_record(m) for m in sp.managers}
    for w in sorted(sp.in_progress or {}):
        if not _decided_by_banking(sp, w):
            continue
        banked = sp.in_progress[w]["banked"]
        for mu in week_entry(sp.data, w).get("matchups", []):
            a, b = mu["manager_a"], mu["manager_b"]
            o = week_outcome(float(banked[a]), float(banked[b]))
            recs[a] = recs[a].add("win" if o == "a" else "loss" if o == "b" else "tie")
            recs[b] = recs[b].add("win" if o == "b" else "loss" if o == "a" else "tie")
    return recs


def readouts(sp) -> dict:
    """The pass's readouts, as plain numbers."""
    tr = sp.title_result()
    out = {"title_odds": {m: float(v) for m, v in tr.title_odds.items()},
           "expected_record": {m: [float(x) for x in tr.expected_record[m]] for m in sp.managers},
           "finish_distribution": {m: {str(k): float(v) for k, v in tr.finish_distribution[m].items()}
                                   for m in sp.managers},
           "magic_numbers": dict(tr.magic_numbers),
           "playoff_odds": None, "playoff_finish_distribution": None, "cup_odds": None}
    if sp.through in ("playoffs", "cup"):
        pr = sp.playoff_result()
        out["playoff_odds"] = {m: float(v) for m, v in pr.title_odds.items()}
        out["playoff_finish_distribution"] = {
            m: {str(k): float(v) for k, v in pr.finish_distribution[m].items()} for m in sp.managers}
    if sp.through == "cup":
        out["cup_odds"] = {m: float(v) for m, v in sp.cup_result().cup_odds.items()}
    return out


def latest_payload(sp, ro: dict, *, run_id: str, kind: str, produced_by: str, as_of: datetime,
                   week: int, engine: dict) -> dict:
    return {
        "schema": SCHEMA, "run_id": run_id, "kind": kind, "produced_by": produced_by,
        "as_of": as_of.isoformat(timespec="seconds"), "week": int(week),
        "pass_current_week": int(sp.current_week), "seed": int(sp.seed),
        "num_simulations": int(sp.num_simulations), "through": sp.through,
        "engine": {"commit": engine["commit"], "dirty": engine["dirty"]},
        "records": {m: str(sp.data.get_manager_record(m)) for m in sp.managers},
        "records_after_banked": {m: str(r) for m, r in _records_after_banked(sp).items()},
        "in_progress": {str(w): {"as_of": v["as_of"], "banked": {m: float(x) for m, x in v["banked"].items()}}
                        for w, v in (sp.in_progress or {}).items()},
        **ro,
    }


def stakes_payload(sp, *, run_id: str, kind: str, as_of: datetime, week: int) -> dict:
    from .data_loader import CURRENT_SEASON
    return {
        "schema": STAKES_SCHEMA, "season": CURRENT_SEASON, "run_id": run_id, "kind": kind,
        "as_of": as_of.isoformat(timespec="seconds"),
        "week": int(week), "seed": int(sp.seed), "num_simulations": int(sp.num_simulations),
        "through": sp.through,
        "definition": {
            "rs_leverage": "P(regular-season title | wins week w) - P(... | loses week w)",
            "playoff_leverage": "P(champion | wins week w) - P(... | loses week w)",
            "wins_week": "the team's own matchup that week; a regular-season T is in neither group",
            "null": "the team never wins (or never loses) that week in the simulation; the counts say which",
            "margin_mean / margin_sd": "his score minus his opponent's that week, over the iterations with a game",
            "rs_title / champion": "P(regular-season title) / P(champion) over the whole pass; champion null without a bracket",
            "source": "the iterations of this run's season pass; no extra simulation"},
        "teams": stakes(sp),
    }


def _write_json(path: Path, blob: dict) -> None:
    from .data_loader import atomic_write_json
    atomic_write_json(path, blob, indent=1)


def record(base_path, sp, *, run_id: str, produced_by: str, kind: str, week: int,
           as_of: datetime = None, history: bool = True, latest: bool = True,
           write_stakes: bool = True) -> dict:
    """Write the run's outputs. The history row is checked against the file
    before anything is written (a repeated run id raises, nothing written)."""
    from . import title_odds_history as toh
    from .calibration_log import engine_version
    from .league_clock import league_now
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {KINDS}, not {kind!r}")
    base = Path(base_path)
    as_of = as_of or league_now()
    ro = readouts(sp)
    row = toh.make_row(base_path=base, run_id=run_id, produced_by=produced_by, seed=sp.seed,
                       num_simulations=sp.num_simulations, title_odds=ro["title_odds"],
                       week=week, playoff_odds=ro["playoff_odds"], cup_odds=ro["cup_odds"],
                       as_of=as_of, kind=kind, expected_record=ro["expected_record"])
    if history:
        toh.append(base, row)
    out = {"row": row, "latest": None, "stakes": None}
    if latest:
        blob = latest_payload(sp, ro, run_id=run_id, kind=kind, produced_by=produced_by,
                              as_of=as_of, week=week, engine=engine_version(base))
        _write_json(base / LATEST_FILE, blob)
        out["latest"] = blob
    if write_stakes:
        blob = stakes_payload(sp, run_id=run_id, kind=kind, as_of=as_of, week=week)
        _write_json(base / STAKES_FILE, blob)
        out["stakes"] = blob
    return out


def price(base_path, data, *, seed: int, sims: int, statuses, run_id: str, produced_by: str,
          kind: str, week: int, now: datetime = None) -> dict:
    """Price title odds now, unless games are on: then TitleOddsLocked is
    raised and nothing is computed or written (design s.4.1, as the line)."""
    from . import price_lock
    from .league_clock import league_now
    now = now or league_now()
    st = price_lock.status(now, data.nba_schedule)
    if st["locked"]:
        raise TitleOddsLocked(f"games are on (first tip {st['first_tip']}): title odds are "
                              "priced after tonight's games")
    sp = run_pass(data, seed=seed, sims=sims, statuses=statuses)
    out = record(base_path, sp, run_id=run_id, produced_by=produced_by, kind=kind, week=week,
                 as_of=now)
    out["pass"] = sp
    return out


def load_latest(base_path=".") -> dict:
    p = Path(base_path) / LATEST_FILE
    if not p.is_file():
        raise FileNotFoundError(f"{LATEST_FILE.as_posix()} is missing: run python scripts\\nightly.py")
    blob = json.loads(p.read_text(encoding="utf-8"))
    if blob.get("schema") != SCHEMA:
        raise ValueError(f"{LATEST_FILE.as_posix()} is schema {blob.get('schema')}, not {SCHEMA}")
    return blob
