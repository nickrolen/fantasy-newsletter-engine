"""The 2026-27 Yahoo injury vocabulary (HANDOFF_YAHOO_TAGS_2026-10-22).

Yahoo retired GTD/DTD/INJ/IL/IL+ and the live set is P, Q, D, O, OFS, with
SUSP and NA separate and not injury designations. Four free agents carried D
on 10-22, so the first rostered D tag would have halted the build.

Test 1 is the pin: if the vocabulary changes again, this is what notices.
"""
import json
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pytest

from modules import absence
from modules import marginal_value as mv
from modules import simulator_betting as sb
from modules.data_loader import FantasyData, MANAGERS
from modules.fetch_injury_statuses import injury_input, normalize_injury_status
from modules.projections import PlayerProjection, TeamProjections

ROOT = Path(__file__).parent.parent
SEED = 20262027
P = absence.baseline_params()
MON = date(2026, 10, 26)
WEEK = [MON + timedelta(days=k) for k in range(7)]
EVERY_DAY = [MON + timedelta(days=k) for k in range(70)]


# =============================================================================
# 1 -- the handled set is pinned
# =============================================================================

def test_the_handled_tag_set_is_exactly_the_2026_27_vocabulary():
    assert set(absence.CHAIN_PLAY) == {"Q", "D", "O"}
    assert absence.SEASON_OUT_TAGS == {"OFS"}
    assert absence.TAG_ALIASES == {"P": "HEALTHY"}
    assert absence.NO_EFFECT_TAGS == {"HEALTHY"}
    assert absence.NOTE_TAGS == {"SUSP", "NA"}
    assert absence.RETIRED_TAGS == {"GTD", "DTD", "INJ", "IL", "IL+"}
    kinds = {t: absence.tag_kind(t) for t in ("P", "Q", "D", "O", "OFS", "SUSP", "NA", "HEALTHY")}
    assert kinds == {"P": "none", "HEALTHY": "none", "SUSP": "none", "NA": "none",
                     "Q": "chain", "D": "chain", "O": "chain", "OFS": "season_out"}
    # OFS is not a chain and not no-effect -- the two ways it could go wrong
    assert absence.chain_tag("OFS") is None and absence.season_out("OFS")
    assert "OFS" not in absence.NO_EFFECT_TAGS and "OFS" not in absence.CHAIN_PLAY
    assert not any(absence.season_out(t) for t in ("P", "Q", "D", "O", "SUSP", "NA", "HEALTHY"))


def test_the_chain_lives_in_config_with_its_provenance():
    cfg = json.loads((ROOT / "config" / "league_config.json").read_text(encoding="utf-8"))
    chain = cfg["absence_chain"]
    assert {k for k in chain if not k.startswith("_")} == {"Q", "D", "O"}
    for tag, probs in absence.CHAIN_PLAY.items():
        assert tuple(chain[tag]) == probs
    assert "NOT MEASURED" in chain["_stated"] and "NICK" in chain["_stated"].upper()
    # not typed a second time in code
    src = (ROOT / "modules" / "absence.py").read_text(encoding="utf-8")
    assert "0.45" not in src and "0.55" not in src
    with pytest.raises(KeyError, match="absence_chain"):
        absence.chain_play({})


# =============================================================================
# 2 -- D sits between Q and O
# =============================================================================

def test_doubtful_costs_more_than_questionable_and_less_than_out():
    q, d, o = (absence.expected_missed(t) for t in ("Q", "D", "O"))
    assert q < d < o
    assert (round(q, 3), round(d, 3), round(o, 3)) == (0.625, 1.286, 1.625)
    # and at every game of the chain, not only on average
    for k in range(absence.MAX_TAG_GAMES):
        assert absence.CHAIN_PLAY["Q"][k] > absence.CHAIN_PLAY["D"][k] > absence.CHAIN_PLAY["O"][k] \
            or (k and absence.CHAIN_PLAY["O"][k] >= absence.CHAIN_PLAY["D"][k])
    # P(plays his first game): Q 60%, D 25%, O never
    assert [absence.CHAIN_PLAY[t][0] for t in ("Q", "D", "O")] == [0.60, 0.25, 0.00]


def test_the_doubtful_distribution_is_derived_not_typed():
    """missed_distribution walks CHAIN_PLAY; nothing types a second copy."""
    p1, p2, p3 = absence.CHAIN_PLAY["D"]
    expect = (p1, (1 - p1) * p2, (1 - p1) * (1 - p2) * p3, (1 - p1) * (1 - p2) * (1 - p3))
    assert absence.missed_distribution("D") == pytest.approx(expect, abs=1e-12)
    assert sum(absence.missed_distribution("D")) == pytest.approx(1.0, abs=1e-12)


# =============================================================================
# a world for the engine tests: one team playing every day
# =============================================================================

def _world(gp=70.0, players=("P0", "P1", "P2")):
    weeks = [{"week": w, "start_date": (MON + timedelta(days=7 * (w - 1))).isoformat(),
              "end_date": (MON + timedelta(days=7 * w - 1)).isoformat()} for w in range(1, 11)]
    games = [{"date": d.isoformat() + "T00:00:00Z", "home": "BOS", "away": "MIA"} for d in EVERY_DAY]
    data = FantasyData(schedule={"weeks": weeks}, nba_schedule={"games": games}, current_week=0)
    teams = {m: TeamProjections(m, {f"{n}{m}": PlayerProjection(
                 player_name=f"{n}{m}", nba_team="BOS", positions=["PG"],
                 projected_fppg=30.0, projected_gp=gp) for n in players}, weekly_std_dev=100.0)
             for m in MANAGERS}
    return data, teams, weeks


def _out_mask(data, teams, weeks, statuses, player="P0Nick", n=2000, through=10):
    """[n, games] bool: unavailable, over every day of weeks 1..through."""
    draws = sb.KeyedDraws(SEED, n)
    cols = []
    for w in weeks[:through]:
        for d in sb.get_dates_in_week(w):
            cols.append(~sb.availability_on(data, teams, w, statuses, draws, "Nick", player, d, MON))
    return np.stack(cols, axis=1)


# =============================================================================
# 3 and 4 -- OFS
# =============================================================================

def test_out_for_season_misses_every_remaining_game_in_every_simulation():
    data, teams, weeks = _world()
    out = _out_mask(data, teams, weeks, {"P0Nick": "OFS"})
    assert out.all()                                   # not one game, not one simulation
    assert out.shape[1] == 70                          # and not capped at three
    assert out.shape[1] > absence.MAX_TAG_GAMES


def test_out_for_season_is_exempt_from_the_three_game_cap():
    """MAX_TAG_GAMES was written when every tag was a short-horizon signal.
    OFS is the first that is not, and it is exempt by construction: it never
    enters the chain, and the chain refuses it loudly if asked."""
    data, teams, weeks = _world()
    draws = sb.KeyedDraws(SEED, 100)
    assert "OFS" not in sb.tag_blocks(data, teams, {"P0Nick": "OFS"}, draws, MON)
    with pytest.raises(absence.UnmodelledTag, match="not a chain tag"):
        absence.missed_distribution("OFS")
    with pytest.raises(absence.UnmodelledTag, match="not a chain tag"):
        absence.missed_from_uniform(np.zeros(3), "OFS")


def test_out_for_season_total_misses_equal_his_remaining_team_games():
    """No double charge: expected misses are `remaining - effective gp`, and
    the effective gp is 0, so they are exactly his remaining games."""
    data, teams, weeks = _world()
    draws = sb.KeyedDraws(SEED, 500)
    base = sb.baseline_blocks(data, teams, draws, MON, ["Nick"],
                              injury_statuses={"P0Nick": "OFS"})["P0Nick"]
    assert base.season_out and base.rate == 1.0 and base.miss_rate == 1.0
    assert absence.effective_projected_gp("OFS", 70.0) == 0.0
    mask = base.season_mask()
    assert mask.all() and mask.shape[1] == len(base.dates)
    # every scheduled game, in every simulation; `remaining` also counts the
    # NBA Cup games the schedule file does not list yet, and the rate is
    # (remaining - 0) / remaining either way
    assert mask.sum(axis=1).mean() == len(base.dates)
    assert absence.baseline_rate(absence.durability_miss_rate(0.0, P), base.remaining) == 1.0


def test_out_for_season_beats_an_override_governed_week_but_a_return_raises():
    data, teams, weeks = _world()
    p = teams["Nick"].players["P0Nick"]
    p.out_weeks = [1]                                  # agrees with OFS: fine
    try:
        assert _out_mask(data, teams, weeks, {"P0Nick": "OFS"}).all()
    finally:
        p.out_weeks = []
    p.return_week, p.return_date = 3, (MON + timedelta(days=15)).isoformat()
    try:
        with pytest.raises(absence.SeasonOutConflict, match="P0Nick is tagged OFS"):
            _out_mask(data, teams, weeks, {"P0Nick": "OFS"})
    finally:
        p.return_week, p.return_date = None, None


def test_out_for_season_moves_nobody_else():
    data, teams, weeks = _world()
    wd = sb.schedule_week(data, 4)
    healthy = sb.simulate_week_matrix(data, teams, wd, {}, sb.KeyedDraws(SEED, 400), tag_anchor=MON)
    ofs = sb.simulate_week_matrix(data, teams, wd, {"P0Nick": "OFS"}, sb.KeyedDraws(SEED, 400),
                                  tag_anchor=MON)
    for m in ("Hayden", "Benton", "Garrett"):
        assert np.array_equal(healthy[m]["score"], ofs[m]["score"]), m
    assert ofs["Nick"]["score"].mean() < healthy["Nick"]["score"].mean()


# =============================================================================
# 5 -- SUSP and NA
# =============================================================================

@pytest.mark.parametrize("tag", ["SUSP", "NA"])
def test_suspension_and_not_available_cost_nothing_from_the_tag_path(tag):
    """They are not injury designations. The old code mapped both to O --
    an injury-shaped three-game recovery for a suspension."""
    data, teams, weeks = _world()
    draws = sb.KeyedDraws(SEED, 500)
    assert sb.tag_blocks(data, teams, {"P0Nick": tag}, draws, MON) == {}
    assert absence.chain_tag(tag) is None and not absence.season_out(tag)
    assert normalize_injury_status(tag) == tag          # no longer mapped to O
    # identical to carrying no tag at all: the hazard alone, through his GP
    tagged = _out_mask(data, teams, weeks, {"P0Nick": tag}, n=400, through=3)
    none = _out_mask(data, teams, weeks, {}, n=400, through=3)
    assert np.array_equal(tagged, none)


@pytest.mark.parametrize("tag", ["SUSP", "NA"])
def test_a_noted_tag_is_logged_and_recorded_not_fatal(tag):
    inj = injury_input(lambda: {"A": tag, "B": "Q", "C": "HEALTHY"}, ["A", "B", "C"], needed=True)
    assert inj.available and inj.noted == [f"A ({tag})"]
    assert inj.record()["noted_tags"] == [f"A ({tag})"]
    assert absence.noted_tags({"A": tag.lower(), "B": "Q"}) == [f"A ({tag})"]
    src = (ROOT / "scripts" / "generate_stats_report.py").read_text(encoding="utf-8")
    assert "TAG NOTED" in src and "for one in injury.noted:" in src
    flow = (ROOT / "WEEKLY_WORKFLOW.md").read_text(encoding="utf-8")
    assert "TAG NOTED" in flow


# =============================================================================
# 6 and 7 -- retired and unknown tags
# =============================================================================

@pytest.mark.parametrize("tag", ["GTD", "DTD", "INJ", "IL", "IL+"])
def test_every_retired_designation_raises_naming_the_vocabulary_change(tag):
    with pytest.raises(absence.UnmodelledTag, match="retired when Yahoo replaced"):
        absence.tag_kind(tag)
    data, teams, weeks = _world()
    with pytest.raises(absence.UnmodelledTag, match="retired when Yahoo replaced"):
        sb.tag_blocks(data, teams, {"P0Nick": tag}, sb.KeyedDraws(SEED, 10), MON)


def test_an_unknown_tag_still_raises_unmodelled():
    with pytest.raises(absence.UnmodelledTag, match="no absence rule"):
        absence.tag_kind("XYZ")
    data, teams, weeks = _world()
    with pytest.raises(absence.UnmodelledTag, match="P0Nick"):
        sb.tag_blocks(data, teams, {"P0Nick": "XYZ"}, sb.KeyedDraws(SEED, 10), MON)


# =============================================================================
# the two engines still agree, with the new tags
# =============================================================================

@pytest.mark.parametrize("tag", ["Q", "D", "O", "OFS", "SUSP"])
def test_marginal_value_and_the_week_engine_agree_on_the_new_tags(tag):
    data, teams, weeks = _world()
    projs = {n: p for tp in teams.values() for n, p in tp.players.items()}
    rosters = {m: list(teams[m].players) for m in MANAGERS}
    statuses = {"P0Nick": tag}
    ctx = mv.build_context(projs, rosters, data.nba_schedule, weeks, "regular_season", 0,
                           injury_statuses=statuses, sims=300, seed=SEED)
    draws = sb.KeyedDraws(SEED, 300)
    for w in weeks[:3]:
        for d in sb.get_dates_in_week(w):
            a = mv._draws(ctx, ctx.player("P0Nick"), d, w["week"])
            b = sb.availability_on(data, teams, w, statuses, draws, "Nick", "P0Nick", d, MON)
            assert np.array_equal(a, b), (tag, d)


# =============================================================================
# the escape: --allow-season-out-conflict (Nick, 10-22)
#
# SeasonOutConflict was the only refusal in the tree with no way through, and
# its message told Nick to "correct the tag" -- Yahoo's data, which he cannot
# touch. His only move was to delete correct information from his own file.
# The house pattern is refuse AND record an override, so: the override wins,
# because INJURY_OVERRIDES is the better-informed input everywhere else in the
# precedence chain.
# =============================================================================

class _Proj:
    def __init__(self, return_week=None, return_date=None, return_games=None, total_week_games=None):
        self.return_week, self.return_date = return_week, return_date
        self.return_games, self.total_week_games = return_games, total_week_games


def _conflict_pair():
    return ({"Hartenstein": "OFS", "Knueppel": "Q"},
            {"Hartenstein": _Proj(3, "2026-11-09"), "Knueppel": _Proj(2, "2026-10-26")})


def test_the_conflict_still_refuses_by_default():
    st, projs = _conflict_pair()
    with pytest.raises(absence.SeasonOutConflict) as e:
        absence.resolve_season_out_conflicts(st, projs)
    msg = str(e.value)
    assert "Hartenstein is tagged OFS" in msg and "return_week=3" in msg
    assert "Knueppel" not in msg                      # a Q tag is no conflict
    assert "--allow-season-out-conflict" in msg       # the way through is named
    assert "correct the tag" not in msg               # not Nick's to correct
    assert "report metadata" in msg and "point-in-time capture" in msg


def test_the_flag_lets_the_override_win_and_records_it():
    st, projs = _conflict_pair()
    out, conflicts = absence.resolve_season_out_conflicts(st, projs, allow=True)
    assert len(conflicts) == 1 and conflicts[0]["player"] == "Hartenstein"
    assert conflicts[0]["stated_return"] == "return_week=3, return_date='2026-11-09'"
    assert "the override wins" in conflicts[0]["resolution"]
    # the tag is dropped for the run, so the overrides file alone governs him
    assert dict(dict.items(out)) == {"Hartenstein": "HEALTHY", "Knueppel": "Q"}
    assert not absence.season_out(out["Hartenstein"])


def test_a_plain_out_weeks_entry_is_not_a_conflict():
    """out_weeks agrees with OFS; only a stated RETURN contradicts it."""
    projs = {"X": _Proj()}
    assert absence.season_out_conflicts({"X": "OFS"}, projs) == []
    assert absence.resolve_season_out_conflicts({"X": "OFS"}, projs)[0]["X"] == "OFS"
    for field in ("return_week", "return_date", "return_games"):
        p = _Proj(**{field: 3 if field != "return_date" else "2026-11-09"})
        assert len(absence.season_out_conflicts({"X": "OFS"}, {"X": p})) == 1, field


def test_the_override_winning_means_he_plays_after_his_return():
    """End to end: with the flag the player is out for the override's weeks
    and available afterwards, instead of out for the season."""
    data, teams, weeks = _world()
    p = teams["Nick"].players["P0Nick"]
    p.out_weeks, p.return_week, p.return_date = [1, 2], 3, weeks[2]["start_date"]
    try:
        projs = {"P0Nick": p}
        kept, _ = absence.resolve_season_out_conflicts({"P0Nick": "OFS"}, projs, allow=True)
        out = _out_mask(data, teams, weeks, dict(dict.items(kept)), through=5)
        assert out[:, :14].all()                      # weeks 1-2: the override
        later = out[:, 14:]                           # week 3 on: hazard only
        assert not later.all() and later.mean() < 0.5
        # and without the flag nothing runs at all
        with pytest.raises(absence.SeasonOutConflict):
            absence.resolve_season_out_conflicts({"P0Nick": "OFS"}, projs)
    finally:
        p.out_weeks, p.return_week, p.return_date = [], None, None


def test_the_injury_input_record_carries_the_conflict():
    st, projs = _conflict_pair()
    roster = list(st)
    with pytest.raises(absence.SeasonOutConflict):
        injury_input(lambda: st, roster, needed=True, projections=projs)
    inj = injury_input(lambda: st, roster, needed=True, projections=projs,
                       allow_season_out_conflict=True)
    rec = inj.record()
    assert rec["season_out_override"] is True
    assert [c["player"] for c in rec["season_out_conflicts"]] == ["Hartenstein"]
    assert rec["available"] is True and rec["count"] == 2
    clean = injury_input(lambda: {"Knueppel": "Q"}, ["Knueppel"], needed=True, projections=projs)
    assert clean.record()["season_out_override"] is False
    assert clean.record()["season_out_conflicts"] == []


def test_the_build_offers_the_flag_and_records_it_like_the_others():
    src = (ROOT / "scripts" / "generate_stats_report.py").read_text(encoding="utf-8")
    assert "--allow-season-out-conflict" in src
    assert "allow_season_out_conflict=args.allow_season_out_conflict" in src
    assert '"season_out_override": [c["line"] for c in injury.season_out_conflicts] or None' in src
    assert "WARNING (overridden):" in src
    # the house pattern: every escape is a flag AND a line in the capture
    for flag, recorded in (("--allow-stale-schedule", '"stale_schedule_override": stale'),
                           ("--allow-no-injury-statuses", '"injury_statuses_override"'),
                           ("--allow-season-out-conflict", '"season_out_override"')):
        assert flag in src and recorded in src, flag
    flow = (ROOT / "WEEKLY_WORKFLOW.md").read_text(encoding="utf-8")
    assert "--allow-season-out-conflict" in flow


def test_the_live_line_refresh_has_the_same_escape():
    """refresh_lines would otherwise have a refusal with no way through."""
    src = (ROOT / "scripts" / "refresh_lines.py").read_text(encoding="utf-8")
    assert "--allow-season-out-conflict" in src
    assert "resolve_season_out_conflicts(" in src
    assert "SEASON-OUT OVERRIDDEN:" in src            # recorded in the assumptions
    import inspect
    import importlib.util
    spec = importlib.util.spec_from_file_location("rl", ROOT / "scripts" / "refresh_lines.py")
    rl = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rl)
    assert "allow_season_out_conflict" in inspect.signature(rl.refresh).parameters


def test_step_0b_is_runnable_from_a_clean_machine():
    """-n 2 needs pytest-xdist; the step that gives the command must also give
    the install, or the doc only works on a machine that happens to have it."""
    flow = (ROOT / "WEEKLY_WORKFLOW.md").read_text(encoding="utf-8")
    step = flow.split("## Step 0b")[1].split("\n## ")[0]
    assert "-n 2" in step
    assert "pip install -r requirements.txt" in step or "pip install pytest-xdist" in step
    assert "unrecognized arguments: -n" in step        # the symptom, named
    reqs = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    assert any(line.strip().startswith("pytest-xdist") for line in reqs.splitlines())
    assert any(line.strip().startswith("pytest>") for line in reqs.splitlines())
