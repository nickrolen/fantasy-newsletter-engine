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

SCHEMA 3 (HANDOFF_CAUSAL_LEVERAGE_2026-11-12 s.1): THE CAUSAL LEVERAGE. The
leverage above is measured over ALL iterations, and a team that wins week w in
an iteration is also, more often, the team whose players run hot all season in
that iteration (each player's projection error persists through the pass). So
it carries season-long luck as well as what the week itself causes: on the
11-11 pass it ran 1.3-1.7x what a direct +40-point perturbation of one week
(same draws) moves the title odds by. Schema 3 adds, per team and week, the
leverage AMONG NEAR-TIE ITERATIONS (|margin| < band), where winning or losing
the week is close to a coin flip and so carries little about the rest of that
iteration's season -- a regression-discontinuity estimate, still read off the
same iterations, still drawing nothing from the pass:
    rs_leverage_causal / playoff_leverage_causal
        P(title | wins w, |margin| < band) - P(title | loses w, |margin| < band);
    causal_band       the band used (points);
    causal_n_win / causal_n_loss   the iterations in the band on each side;
    causal_se         a bootstrap SE (causal_bootstrap resamples of each side,
                      seeded from the pass's seed, the team and the week:
                      deterministic, and nothing drawn from the pass's streams);
    causal_why        null, or why the band was widened, or why it is null.
The band is league_config stakes.near_tie_band (25, chosen 11-12 on the
development team-weeks of the perturbation check, from {25, 50, 75}). TOO FEW
NEAR TIES: a side with fewer than stakes.near_tie_min iterations in the band
widens the band to the next of stakes.near_tie_wider (50, then 75), saying so
in causal_why; if even the widest band is short, the causal leverage is NULL
with the counts in causal_why -- worth 0 per point, as every null leverage is
(modules/injured_drop). It NEVER falls back to the all-iteration leverage.
The all-iteration leverage is kept, renamed rs_leverage_all /
playoff_leverage_all (with n_win, n_loss, n_tie, p_if_win, p_if_loss), for
reference only: nothing prices with it. modules/injured_drop.point_value -- the
one place a point is priced -- uses the causal one (drop_inputs maps it).

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
STAKES_SCHEMA = 3           # 2: margins, rs_title / champion, season (task 18b);
                            # 3: the causal (near-tie) leverage; the old one kept as *_all


class TitleOddsLocked(RuntimeError):
    """Games are on (modules/price_lock): title odds were not priced."""


def through_for() -> str:
    """How deep the season's format goes: the weekly build's own rule."""
    from .simulator_playoff_odds import bracket_rounds
    from .simulator_cup_odds import cup_rounds
    return ("cup" if bracket_rounds() and cup_rounds()
            else "playoffs" if bracket_rounds() else "regular")


def line_anchors(base_path):
    """week -> {player: (tag, anchor date)}: the live line's chain-tag anchors
    for that week, from its state file (output/live_lines_week<N>.state.json,
    "tags", written by refresh_lines with week_state.reconcile_tags). The
    season pass reads it only mid-week with chain tags (season_sim._tag_chain,
    HANDOFF_CAUSAL_LEVERAGE_2026-11-12 s.3); a missing file or record raises."""
    from datetime import date as _date

    def read(week: int) -> dict:
        p = Path(base_path) / "output" / f"live_lines_week{int(week)}.state.json"
        if not p.is_file():
            raise FileNotFoundError(f"{p.as_posix()} is missing: a mid-week pass anchors its tags where "
                                    "the week's live line did (price the line first)")
        blob = json.loads(p.read_text(encoding="utf-8"))
        rec = blob.get("tags")
        if not isinstance(rec, dict):
            raise ValueError(f"{p.as_posix()} has no tag record ('tags')")
        return {n: (v["tag"], _date.fromisoformat(v["anchor"])) for n, v in rec.items()}
    return read


def run_pass(data, *, seed: int, sims: int, statuses, through: str = None, tag_anchors=None):
    """The season pass the weekly build and the nightly run both price from.
    tag_anchors: season_sim.run_season's (line_anchors(base) in production)."""
    from .season_sim import run_season
    return run_season(data, num_simulations=sims, seed=seed, injury_statuses=statuses,
                      through=through or through_for(), tag_anchors=tag_anchors)


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


def near_tie_rules() -> dict:
    """league_config.json stakes: the near-tie band, the wider bands to try
    when too few iterations fall in it, the minimum per side, and the number
    of bootstrap resamples. Every key required (league_rule raises)."""
    from .data_loader import league_rule
    band = int(league_rule("stakes", "near_tie_band"))
    wider = [int(x) for x in league_rule("stakes", "near_tie_wider")]
    min_n = int(league_rule("stakes", "near_tie_min"))
    boot = int(league_rule("stakes", "causal_bootstrap"))
    if band <= 0 or any(w <= band for w in wider) or wider != sorted(wider):
        raise ValueError(f"stakes: near_tie_wider {wider} must be increasing and wider than near_tie_band {band}")
    if min_n < 1 or boot < 2:
        raise ValueError("stakes: near_tie_min >= 1 and causal_bootstrap >= 2")
    return {"band": band, "wider": wider, "min_n": min_n, "boot": boot}


def causal_leverage(won: np.ndarray, outcome: np.ndarray, margin: np.ndarray, *, rules: dict,
                    seed) -> dict:
    """The near-tie leverage (module docstring, schema 3):
    {leverage, band, n_win, n_loss, se, why}. won as in leverage(); margin
    his score minus his opponent's (NaN without a game). seed: the bootstrap's
    numpy SeedSequence entropy (deterministic; independent of the pass)."""
    won = np.asarray(won, float)
    outcome = np.asarray(outcome, bool)
    margin = np.asarray(margin, float)
    bands = [rules["band"]] + list(rules["wider"])
    why = None
    for h in bands:
        near = np.abs(margin) < h                    # NaN (no game) is never near
        wi = np.flatnonzero(near & (won == 1.0))
        lo = np.flatnonzero(near & (won == 0.0))
        if min(len(wi), len(lo)) >= rules["min_n"]:
            break
        why = (f"fewer than {rules['min_n']} wins or losses within {h} points "
               f"({len(wi)} / {len(lo)})")
    else:
        return {"leverage": None, "band": None, "n_win": int(len(wi)), "n_loss": int(len(lo)),
                "se": None, "why": why + ": no causal leverage (worth 0 per point)"}
    if why is not None:
        why = f"{why}; widened to {h}"
    ow, ol = outcome[wi], outcome[lo]
    lev = float(ow.mean() - ol.mean())
    rng = np.random.default_rng(np.random.SeedSequence(seed))
    bw = ow[rng.integers(0, len(ow), (rules["boot"], len(ow)))].mean(axis=1)
    bl = ol[rng.integers(0, len(ol), (rules["boot"], len(ol)))].mean(axis=1)
    return {"leverage": lev, "band": int(h), "n_win": int(len(wi)), "n_loss": int(len(lo)),
            "se": float(np.std(bw - bl, ddof=1)), "why": why}


def _causal_fields(prefix: str, c: dict) -> dict:
    return {f"{prefix}_causal": c["leverage"], "causal_band": c["band"], "causal_n_win": c["n_win"],
            "causal_n_loss": c["n_loss"], "causal_se": c["se"], "causal_why": c["why"]}


def _boot_seed(sp, j: int, week: int, race: int) -> list:
    return [int(sp.seed) & 0xFFFFFFFFFFFFFFFF, int(j), int(week), int(race)]


def _decided_by_banking(sp, week: int) -> bool:
    """A regular-season week the pass took from the logs whole: every day of
    it banked (its as-of is past the week's last day)."""
    ip = (sp.in_progress or {}).get(week)
    if not ip:
        return False
    from .week_state import week_entry
    end = date.fromisoformat(str(week_entry(sp.data, week)["end_date"])[:10])
    return date.fromisoformat(ip["as_of"]) > end


def stakes(sp, rules: dict = None) -> dict:
    """{manager: {"regular_season": {week: ...}, "playoffs": {week: ...}}}
    (weeks as strings): each entry leverage()'s dict with the leverage
    renamed <race>_leverage_all, plus the causal leverage (schema 3) and the
    margins. rules: near_tie_rules() (read from config when None)."""
    from .simulator_playoff_odds import bracket_weeks
    rules = rules or near_tie_rules()
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
                lv["rs_leverage_all"] = lv.pop("leverage")
                lv.update(_causal_fields("rs_leverage", causal_leverage(
                    arr[:, j], title[j], marg[:, j], rules=rules, seed=_boot_seed(sp, j, w, 0))))
                lv.update(margin_stats(marg[:, j]))
                out[m]["regular_season"][str(w)] = lv
        elif w in bracket:
            for j, m in enumerate(sp.managers):
                if np.isnan(arr[:, j]).all():
                    continue
                lv = leverage(arr[:, j], champ[j])
                lv["playoff_leverage_all"] = lv.pop("leverage")
                lv.update(_causal_fields("playoff_leverage", causal_leverage(
                    arr[:, j], champ[j], marg[:, j], rules=rules, seed=_boot_seed(sp, j, w, 1))))
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
            "rs_leverage_causal": "P(regular-season title | wins week w) - P(... | loses week w), among the "
                                  "iterations with |margin| < causal_band (near ties): what the week itself "
                                  "causes. The one the price of a point uses (injured_drop.point_value)",
            "playoff_leverage_causal": "the same with P(champion), in a bracket week",
            "causal_band / causal_n_win / causal_n_loss": "the band used and the iterations in it on each side",
            "causal_se": "a bootstrap SE of the causal leverage (resampling each side)",
            "causal_why": "null; or why the band was widened (too few near ties); or why the causal leverage is "
                          "null (worth 0 per point). Never the all-iteration leverage",
            "rs_leverage_all": "P(regular-season title | wins week w) - P(... | loses week w) over ALL iterations "
                               "(schema 2's rs_leverage): carries season-long luck; reference only, never priced",
            "playoff_leverage_all": "the same with P(champion); reference only",
            "wins_week": "the team's own matchup that week; a regular-season T is in neither group",
            "null": "the team never wins (or never loses) that week in the simulation; the counts say which",
            "margin_mean / margin_sd": "his score minus his opponent's that week, over the iterations with a game",
            "rs_title / champion": "P(regular-season title) / P(champion) over the whole pass; champion null without a bracket",
            "source": "the iterations of this run's season pass; no extra simulation"},
        "near_tie": near_tie_rules(),
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
          kind: str, week: int, now: datetime = None, tag_anchors=None) -> dict:
    """Price title odds now, unless games are on: then TitleOddsLocked is
    raised and nothing is computed or written (design s.4.1, as the line)."""
    from . import price_lock
    from .league_clock import league_now
    now = now or league_now()
    st = price_lock.status(now, data.nba_schedule)
    if st["locked"]:
        raise TitleOddsLocked(f"games are on (first tip {st['first_tip']}): title odds are "
                              "priced after tonight's games")
    data.plan_now = now                      # 44b s.2: the plan's open window is judged at the run's clock
    sp = run_pass(data, seed=seed, sims=sims, statuses=statuses,
                  tag_anchors=tag_anchors if tag_anchors is not None else line_anchors(base_path))
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
