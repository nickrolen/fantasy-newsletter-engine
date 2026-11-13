"""The player cards follow-up (11-12; claude/HANDOFF_CARDS_FOLLOWUP_2026-11-12.md).

  s.1 ONE FPPG EVERYWHERE (Nick, option c): a card's season numbers are the
      player's NBA numbers (data/player_actuals.json, every game he played),
      on the hub and in the newsletter's Keeper Watch cards:
        - every rostered card equals its roster row's FPPG and GP (real payload);
        - a free agent's card uses the NBA source; the league-roster figure is
          one secondary line, only where it differs;
        - a player the source does not cover gets the note, never the league
          figure in disguise;
        - the ranks, this season's career row, the sparkline, the boom/bust
          panel and the season filter read the NBA numbers.
  s.2 THE CARDS FAIL SOFTLY (like advice): annotate, build or publish failing
      leaves the hub with plain names and no card files, the run OK and the
      failure recorded loudly; a plaintext leak in a card file still stops it.
"""
import copy
import gzip
import json
import re
import sys
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

from modules import hub_cards as hc, hub_crypto, hub_publish, nightly  # noqa: E402
from modules import player_actuals as pa  # noqa: E402
from modules import player_card_builder as pcb  # noqa: E402
from league_state import needs_state  # noqa: E402

TEST_PASS = "a test passphrase, never the real one"
CUR = pcb.CURRENT_SEASON


# =============================================================================
# s.1 the source: player_actuals.card_lines
# =============================================================================

def _blob():
    """first day 11-01; Ann rostered (every day), Bo dropped after 11-03, Cy rostered but short a day."""
    days = {f"2026-11-0{i}": [10.0 * i, 1] for i in range(1, 6)}
    return {"version": 1, "season": CUR, "first_day": "2026-11-01",
            "players": {"1": {"name": "Ann Arbor", "days": dict(days)},
                        "2": {"name": "Bo Dropped", "days": {d: v for d, v in days.items() if d <= "2026-11-03"}},
                        "3": {"name": "Cy Short", "days": {d: v for d, v in days.items() if d != "2026-11-04"}}},
            "roster_names": {"Ann Arbor": 1, "Cy Short": 3}, "rosters_from": "x", "updated_at": "x"}


def test_card_lines_covers_a_player_only_with_every_day():
    b = _blob()
    out = pa.card_lines(b, ["Ann Arbor", "Bo Dropped", "Nobody Here"], date(2026, 11, 5), required=["Ann Arbor"])
    assert [r[0] for r in out["lines"]["Ann Arbor"]] == [f"2026-11-0{i}" for i in range(1, 6)]
    assert out["lines"]["Bo Dropped"] is None and out["notes"]["Bo Dropped"] == pa.NOTE_SINCE.format(last="Nov 3")
    assert out["lines"]["Nobody Here"] is None and out["notes"]["Nobody Here"] == pa.NOTE_NEVER
    # the same player through his last day IS covered (the newsletter's earlier week)
    assert pa.card_lines(b, ["Bo Dropped"], date(2026, 11, 3))["lines"]["Bo Dropped"] is not None


def test_a_rostered_player_short_a_day_raises_never_a_note():
    with pytest.raises(pa.ActualsStale, match="Cy Short on 2026-11-04"):
        pa.card_lines(_blob(), ["Cy Short"], date(2026, 11, 5), required=["Cy Short"])
    with pytest.raises(pa.ActualsStale, match="not in data/player_actuals.json"):
        pa.card_lines(_blob(), ["Nobody Here"], date(2026, 11, 3), required=["Nobody Here"])
    # a player dropped since, required through a week he was rostered in (the
    # newsletter's report week): covered by his cached days
    assert pa.card_lines(_blob(), ["Bo Dropped"], date(2026, 11, 3), required=["Bo Dropped"])["lines"]["Bo Dropped"]
    with pytest.raises(pa.ActualsStale, match="Bo Dropped on 2026-11-04"):
        pa.card_lines(_blob(), ["Bo Dropped"], date(2026, 11, 5), required=["Bo Dropped"])


def test_the_card_sums_are_the_roster_rows_sums():
    b = _blob()
    lines = pa.card_lines(b, ["Ann Arbor"], date(2026, 11, 5))["lines"]["Ann Arbor"]
    s = pcb.nba_season(lines)
    assert (s["pts"], s["gp"]) == pa.season(b, "Ann Arbor", date(2026, 11, 5))


# =============================================================================
# s.1 the card
# =============================================================================

def _lines(fps, start=1):
    """[[iso, points, games]]: one day per entry; None = no game that day."""
    return [[f"2026-11-{start + i:02d}", 0.0 if fp is None else float(fp), 0 if fp is None else 1]
            for i, fp in enumerate(fps)]


def _kw(name, mgr, gp, fppg):
    return {"player_name": name, "manager": mgr, "age": 25, "pos_group": "G", "season_gp": gp,
            "season_fppg": fppg, "season_total_fp": gp * fppg, "proj_fppg": 30.0, "keep_k5": 0.5,
            "keep_k6": 0.6, "rank": 3, "out_for_season": False, "injured": False}


def _build(kw_rows, lines, extras=(), notes=None, tmp_path=None):
    return pcb.build_player_cards(list(kw_rows), tmp_path / "data", tmp_path / "config",
                                  tmp_path / "data" / "historical", extra_players=list(extras),
                                  nba={"lines": lines, "notes": notes or {}})


@pytest.fixture
def empty_base(tmp_path):
    for d in ("data/historical", "config"):
        (tmp_path / d).mkdir(parents=True)
    return tmp_path


def test_the_headline_is_the_nba_number_and_the_league_figure_a_secondary_line(empty_base, capsys):
    # a pickup: 2 games on a league roster at 15.5, 9 NBA games at 27.1 (11-12's card)
    fps = [30, 20, None, 25, 35, 15, None, 40, 22, 26.9, 30]
    cards = _build([_kw("Pick Up", "Nick", 2, 15.5)], {"Pick Up": _lines(fps)}, tmp_path=empty_base)
    c = cards[0]
    played = [f for f in fps if f is not None]
    assert c["current_season"]["gp"] == 9
    assert c["current_season"]["fppg"] == float(pa.fppg_text(round(sum(played), 2), 9))
    assert c["current_season"]["total_fp"] == round(sum(played), 1)
    assert c["league_season"]["text"] == "On a league roster: 15.5 FPPG in 2 games"
    # the same numbers: no secondary line
    same = _build([_kw("Same Guy", "Nick", 2, 25.0)], {"Same Guy": _lines([20, 30])}, tmp_path=empty_base)[0]
    assert "league_season" not in same and same["current_season"]["fppg"] == 25.0


def test_everything_computed_from_season_numbers_reads_the_nba_numbers(empty_base):
    lines = {"Hot Hand": _lines([50, None, 44, 10]), "Cold Hand": _lines([20, 21, 22, 23])}
    cards = {c["player_name"]: c for c in
             _build([_kw("Hot Hand", "Nick", 1, 10.0), _kw("Cold Hand", "Hayden", 4, 60.0)], lines,
                    tmp_path=empty_base)}
    hot, cold = cards["Hot Hand"], cards["Cold Hand"]
    # the ranks: by the NBA numbers (Hot 34.7 > Cold 21.5), not the league's (Cold 60 > Hot 10)
    assert hot["composite_rank_fppg"] == 1 and cold["composite_rank_fppg"] == 2 and hot["overall_rank"] == 1
    # this season's career row and the career totals
    row = [r for r in hot["career"]["season_breakdown"] if r["season"] == CUR]
    assert row and (row[0]["gp"], row[0]["fppg"], row[0]["total_fp"]) == (3, 34.7, 104.0)
    assert hot["career"]["career_gp"] == 3 and hot["career"]["career_fppg"] == 34.7
    # the sparkline's current season and the last 10 (newest first)
    assert [(g["date"], g["fp"]) for g in hot["sparkline"] if g["season"] == CUR] == \
        [("2026-11-01", 50.0), ("2026-11-03", 44.0), ("2026-11-04", 10.0)]
    assert [g["fp"] for g in hot["last_10"]] == [10.0, 44.0, 50.0]
    # the boom/bust panel and the season filter's figures
    assert hot["boom_bust"]["total_games"] == 3 and hot["boom_bust"]["boom_rate"] == round(200 / 3, 1)
    assert hot["boom_bust_by_season"][CUR]["total_games"] == 3
    assert hot["boom_bust_by_season"][CUR]["best_game"] == "50.0"


def test_a_free_agent_card_uses_the_nba_source_or_says_why(empty_base):
    lines = {"Free Covered": _lines([30, 31]), "Free Gone": None}
    notes = {"Free Gone": pa.NOTE_SINCE.format(last="Nov 8")}
    cards = {c["player_name"]: c for c in
             _build([], lines, extras=[{"player_name": "Free Covered", "manager": ""},
                                       {"player_name": "Free Gone", "manager": ""}],
                    notes=notes, tmp_path=empty_base)}
    fc, fg = cards["Free Covered"], cards["Free Gone"]
    assert fc["current_season"]["gp"] == 2 and fc["current_season"]["fppg"] == 30.5
    assert fc["overall_rank"] is None and "keep_k5" not in fc                 # never ranked
    # not covered: no numbers, the note, nothing computed from a season he has none of
    assert fg["current_season"] is None and fg["season_note"] == notes["Free Gone"]
    assert not [g for g in fg["sparkline"] if g["season"] == CUR] and fg["last_10"] == []
    assert fg["boom_bust"]["total_games"] == 0 and CUR not in fg["boom_bust_by_season"]
    assert not [r for r in fg["career"]["season_breakdown"] if r["season"] == CUR]
    assert fg["archetype"] is None and fg["overall_rank"] is None


def test_a_card_never_falls_back_to_the_league_figure(empty_base):
    with pytest.raises(ValueError, match="no NBA line"):
        _build([_kw("Nobody Decided", "Nick", 3, 20.0)], {}, tmp_path=empty_base)
    with pytest.raises(TypeError):                                           # nba= is required
        pcb.build_player_cards([], empty_base / "data", empty_base / "config", empty_base / "data" / "historical")


def test_the_modal_prints_the_secondary_line():
    from modules.player_card_modal import get_player_card_js, get_player_card_css
    js = get_player_card_js()
    assert "c.league_season && c.league_season.text" in js and "pc-league-line" in js
    assert ".pc-league-line {" in get_player_card_css()


def test_the_newsletter_reads_the_report_weeks_nba_numbers(tmp_path):
    import newsletter_html_generator as g
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "player_actuals.json").write_text(json.dumps(_blob()))
    sr = {"metadata": {"date_range": {"start": "2026-11-01", "end": "2026-11-03"}}}
    out = g.keeper_watch_nba_lines(sr, [{"player_name": "Ann Arbor"}], tmp_path)
    assert out["through"] == "2026-11-03" and len(out["lines"]["Ann Arbor"]) == 3
    with pytest.raises(pa.ActualsStale):                                     # every Keeper Watch player rostered
        g.keeper_watch_nba_lines({"metadata": {"date_range": {"end": "2026-11-05"}}},
                                 [{"player_name": "Cy Short"}], tmp_path)
    with pytest.raises(ValueError, match="date_range"):
        g.keeper_watch_nba_lines({"metadata": {}}, [{"player_name": "Ann Arbor"}], tmp_path)
    src = (ROOT / "scripts" / "newsletter_html_generator.py").read_text(encoding="utf-8")
    i = src.index("_nba = keeper_watch_nba_lines(")
    assert i < src.index("_player_cards = build_player_cards(") and "nba=_nba" in src
    assert i < src.index("try:", i) < src.index("_player_cards = build_player_cards(")   # outside the try: loud


# =============================================================================
# s.2 the cards fail softly
# =============================================================================

def _sample():
    from test_hub import sample_payload
    return sample_payload()


def test_strip_undoes_annotate_exactly():
    plain = _sample()
    plain["cards"] = None                       # as hub_state.build writes it before annotate
    p = copy.deepcopy(plain)
    hc.annotate(p)
    assert p != plain and p["cards"]["players"]
    assert hc.strip(p) == plain
    # whatever part of annotate ran: a partial run strips clean too
    q = copy.deepcopy(plain)
    for rb in q["rosters"].values():
        for x in rb["players"]:
            x["card"] = "k"
    part = [x for w in q["moves"]["weeks"] for it in w["items"] for x in it["parts"]][0]
    part["segs"] = [{"t": "x"}]
    assert hc.strip(q) == plain


@pytest.fixture
def deskbase(tmp_path, monkeypatch):
    """A base the publish runs on (the scan's inputs, a test salt, no archive),
    with the sample payload as the state file and HUB_PASSPHRASE a test one."""
    base = tmp_path / "base"
    (base / "config").mkdir(parents=True)
    (base / "config" / "ROSTERS.json").write_text(json.dumps({"rosters": {"Mgr One": ["Zed Alpha"]}}))
    (base / "output").mkdir()
    monkeypatch.setattr(hub_publish, "scan_terms", lambda b, data=None: ["Zed Alpha", "Mgr One", "Team Uno"])
    monkeypatch.setattr(hub_publish, "hub_salt", lambda b, create=True: b"\x03" * 16)
    from modules import hub_archive
    monkeypatch.setattr(hub_archive, "verify", lambda b: {"version": 1, "issues": []})
    monkeypatch.setenv("HUB_PASSPHRASE", TEST_PASS)
    from modules import hub_state
    monkeypatch.setattr(hub_crypto, "ITERATIONS", 1000)
    p = _sample()
    p["newsletter"] = {"current": None, "archive": [], "empty": "none", "note": "n"}
    hc.annotate(p)
    p["schema"] = hub_state.SCHEMA
    (base / "state.json").write_text(json.dumps(p))
    return base


def _cards_obj(p):
    cards = {k: {"player_name": v["name"], "card": k, "status": v["status"], "current_season": None,
                 "season_note": "x", "career": {"career_fppg": None},
                 "sparkline": [{"date": "2026-11-01", "fp": 40.0, "injured": False, "season": CUR}]}
             for k, v in p["cards"]["players"].items()}
    return {"schema": hc.SCHEMA, "generated_at": p["generated_at"], "engine": p["engine"]["key"],
            "seconds": 0.0, "cards": cards, "photos": {}}


def _published_plain(base, res):
    """The publish directory holds the shell only (no cards/, no photos/), the
    page names no card, the bundle carries no card file, and the preview too."""
    pub = hub_publish.publish_dir(base)
    files = sorted(str(f.relative_to(pub)).replace("\\", "/") for f in pub.rglob("*") if f.is_file())
    assert files == ["index.html"], files
    shell = (pub / "index.html").read_text(encoding="utf-8")
    bundle = json.loads(re.search(r'id="hub-bundle">(.*?)</script>', shell, re.S).group(1))
    inner = json.loads(hub_crypto.open_bundle(TEST_PASS, bundle))
    assert "cards" not in inner and "data-card=\"" not in inner["page"]
    assert "Zed Alpha" in inner["page"]                                       # the names, plain
    prev = (base / "output" / "hub_preview.html").read_text(encoding="utf-8")
    assert "data-card=\"" not in prev and 'id="hub-cards"' not in prev
    assert res["payload"]["cards"] is None and not [n for n, k in hc.shown_names(res["payload"]) if k]


def test_a_card_build_failure_publishes_plain_names_and_no_card_files(deskbase, monkeypatch):
    import build_hub

    def boom(base, payload, **k):
        raise hc.CardsError("two players share the card key 'x'")
    monkeypatch.setattr(hc, "build", boom)
    res = build_hub.run(deskbase, state=deskbase / "state.json", echo=lambda *a: None)
    assert res["rc"] == 0 and res["cards"] is None
    assert res["cards_error"] == {"stage": "build", "error": "CardsError: two players share the card key 'x'"}
    _published_plain(deskbase, res)


def test_a_card_publish_failure_publishes_plain_names_and_no_card_files(deskbase, monkeypatch):
    import build_hub
    p = json.loads((deskbase / "state.json").read_text())
    monkeypatch.setattr(hc, "build", lambda base, payload, **k: _cards_obj(p))

    def broken(*a, **k):
        raise OSError("photos/x.webp: no such file")
    monkeypatch.setattr(hc, "publish_files", broken)
    res = build_hub.run(deskbase, state=deskbase / "state.json", echo=lambda *a: None)
    assert res["rc"] == 0 and res["cards_error"]["stage"] == "publish"
    assert "no such file" in res["cards_error"]["error"]
    _published_plain(deskbase, res)


def test_a_good_build_still_publishes_its_cards(deskbase, monkeypatch):
    import build_hub
    p = json.loads((deskbase / "state.json").read_text())
    monkeypatch.setattr(hc, "build", lambda base, payload, **k: _cards_obj(p))
    res = build_hub.run(deskbase, state=deskbase / "state.json", echo=lambda *a: None)
    assert res["cards_error"] is None and res["cards"] == len(p["cards"]["players"])
    assert [f for f in res["report"]["files"] if f.startswith("cards/")]


def test_a_card_file_that_leaks_plaintext_still_stops_the_hub(deskbase, monkeypatch):
    import build_hub
    p = json.loads((deskbase / "state.json").read_text())
    monkeypatch.setattr(hc, "build", lambda base, payload, **k: _cards_obj(p))
    monkeypatch.setattr(hc, "publish_files", lambda *a, **k: ({"cards/0123456789abcdef.enc": b"..Zed Alpha.."},
                                                             {"file": "cards/0123456789abcdef.enc", "key": "AA=="}))
    with pytest.raises(hub_publish.PlaintextLeak):
        build_hub.run(deskbase, state=deskbase / "state.json", echo=lambda *a: None)


def test_a_seal_that_keeps_matching_a_term_is_a_leak_not_a_soft_failure(deskbase, monkeypatch):
    import build_hub
    p = json.loads((deskbase / "state.json").read_text())
    monkeypatch.setattr(hc, "build", lambda base, payload, **k: _cards_obj(p))

    def stuck(*a, **k):
        raise hub_crypto.SealExhausted("a card file matched a scan term 20 times running")
    monkeypatch.setattr(hub_crypto, "seal_by_content", stuck)
    with pytest.raises(hub_publish.PlaintextLeak):
        build_hub.run(deskbase, state=deskbase / "state.json", echo=lambda *a: None)


NOW = datetime(2026, 11, 11, 14, 14, tzinfo=ZoneInfo("America/Los_Angeles"))


@pytest.mark.parametrize("stage", ["annotate", "build", "publish"])
def test_the_run_records_a_card_failure_loudly_and_goes_on(tmp_path, monkeypatch, stage):
    """Each failure kind: the hub step is OK, the hub is written with plain
    names, the run's "cards" block, the summary line and the step's line say
    CARDS FAILED, and the run's outcome is ok -- as a failed advice step."""
    import build_hub
    from modules import hub_state, hub_matchups
    annotated = _sample()
    hc.annotate(annotated)
    written = []

    def fake_state(base, **k):
        p = copy.deepcopy(annotated)
        if stage == "annotate":
            hc.strip(p)
            k["cards_out"]["error"] = {"stage": "annotate", "error": "CardsError: a moves-feed part this "
                                                                    "module cannot read"}
        return p
    monkeypatch.setattr(hub_state, "build", fake_state)
    monkeypatch.setattr(hub_state, "write", lambda base, payload: written.append(copy.deepcopy(payload)))
    monkeypatch.setattr(hub_matchups, "write_night", lambda *a, **k: None)
    built = []

    def fake_cards(base, payload, **k):
        built.append(1)
        if stage == "build":
            raise KeyError("player_name")
        return {"cards": {}, "seconds": 0.1, "photos": {}}
    monkeypatch.setattr(hc, "build", fake_cards)
    monkeypatch.setattr(hc, "write", lambda base, obj: None)
    monkeypatch.setattr(hc, "coverage", lambda base, payload: {"with": 0, "rostered": 2, "library": 0})
    (tmp_path / "output").mkdir()
    (tmp_path / hc.CARDS_RELPATH).write_text("{}")                          # an earlier run's cards

    def fake_run(base, **k):
        if stage == "publish":
            p = copy.deepcopy(annotated)
            hc.strip(p)
            return {"rc": 0, "cards": None, "payload": p,
                    "cards_error": {"stage": "publish", "error": "CardFilesError: OSError: no such file"}}
        return {"rc": 0, "cards": 0, "cards_error": None, "payload": None}
    monkeypatch.setattr(build_hub, "run", fake_run)
    run = nightly.Run(tmp_path, "refresh", now=NOW, cause="a test")
    steps = {n: (lambda: "ok") for n in run.steps()}
    steps["hub"] = run.step_hub
    row = run.execute(steps)
    assert row["outcome"] == "ok" and row["exit"] == 0
    hub = [s for s in row["steps"] if s["step"] == "hub"][0]
    assert hub["outcome"] == "ok" and f"player cards FAILED at {stage}" in hub["detail"]
    assert row["cards"]["stage"] == stage and row["cards"]["error"] and row["cards"]["cards"] is None
    assert run.ctx["cards_lines"][0].startswith(f"CARDS FAILED ({stage}):")
    assert written[-1]["cards"] is None and not [n for n, k in hc.shown_names(written[-1]) if k]
    assert not (tmp_path / hc.CARDS_RELPATH).exists()                       # never reused
    assert built == ([] if stage == "annotate" else [1])
    assert "headshots" not in row


def test_a_good_run_records_its_cards_and_the_summary_prints_failures():
    src = (ROOT / "modules" / "nightly.py").read_text(encoding="utf-8")
    assert 'row["cards"] = self.ctx["cards"]' in src
    assert 'for line in run.ctx.get("cards_lines") or []:' in src
    step = src[src.index("def step_hub"):src.index("def step_nudges")]
    assert "build_hub.run(" in step and "hub_cards.discard(" in step and "hub_cards.strip(payload)" in step
    hs = (ROOT / "modules" / "hub_state.py").read_text(encoding="utf-8")
    block = hs[hs.index("hub_cards.annotate(payload)") - 200:hs.index("hub_cards.annotate(payload)") + 600]
    assert "raise HubInputError" not in block and "hub_cards.strip(payload)" in block


# =============================================================================
# the real hub (unstubbed): the run path, the NBA numbers, the soft annotate
# =============================================================================

@needs_state("output/title_odds_latest.json", "output/tag_records.jsonl", "data/transaction_log.jsonl",
             "output/hub_archive/index.json", "data/historical/HISTORICAL_PLAYERLOG.json",
             "data/player_actuals.json",
             why="the real hub, its cards and their NBA numbers, from Nick's state, into scratch")
def test_the_real_hub_cards_carry_the_roster_rows_numbers(tmp_path, monkeypatch):
    import build_hub
    from modules import hub_state
    monkeypatch.setattr(hub_publish, "hub_salt", lambda b, create=True: b"\x02" * 16)   # never the real one
    monkeypatch.setenv("HUB_PASSPHRASE", TEST_PASS)
    try:
        payload = hub_state.build(ROOT, allow_engine_mismatch=True, echo=lambda *a: None)
    except hub_state.HubInputError as e:
        pytest.skip(f"the real hub does not build on this checkout's state: {e}")
    sp = tmp_path / "payload.json"
    sp.write_text(json.dumps(payload), encoding="utf-8")
    res = build_hub.run(ROOT, state=sp, out_dir=tmp_path / "o", echo=lambda *a: None)
    assert res["rc"] == 0 and res["cards_error"] is None, res["cards_error"]
    out = tmp_path / "o" / "hub_publish"
    bundle = json.loads(re.search(r'id="hub-bundle">(.*?)</script>', (out / "index.html").read_text()).group(1))
    inner = json.loads(hub_crypto.open_bundle(TEST_PASS, bundle))
    live = json.loads(gzip.decompress(hub_crypto.open_sealed(
        hub_crypto.unb64(inner["cards"]["key"]), (out / inner["cards"]["file"]).read_bytes())))["cards"]
    blob = pa.load(ROOT)
    through = date.fromisoformat(payload["sources"]["actuals_through"])
    reg = payload["cards"]["players"]
    n_rostered = 0
    for rb in payload["rosters"].values():
        for row in rb["players"]:
            c = live[row["card"]]
            cs = c["current_season"]
            pts, gp = pa.season(blob, row["name"], through)
            assert row["gp"] == gp
            if gp:
                assert f"{cs['fppg']:.1f}" == row["fppg"] and cs["gp"] == row["gp"], row["name"]
                assert cs["fppg"] == float(pa.fppg_text(pts, gp))
            else:
                assert cs is None and row["fppg"] == "—"
            ls = c.get("league_season")
            if ls:
                assert cs is None or ls["gp"] != cs["gp"] or f"{ls['fppg']:.1f}" != f"{cs['fppg']:.1f}"
            n_rostered += 1
    assert n_rostered == sum(1 for v in reg.values() if v["kind"] == "rostered")
    for k, v in reg.items():
        if v["kind"] == "rostered":
            continue
        c = live[k]
        if c["current_season"] is None:
            assert c["season_note"].startswith("No NBA numbers")
        else:                                                                 # covered: the NBA source
            lines = pa.card_lines(blob, [v["name"]], through)["lines"][v["name"]]
            assert lines is not None and c["current_season"]["gp"] == pcb.nba_season(lines)["gp"]


@needs_state("output/title_odds_latest.json", "output/tag_records.jsonl", "data/transaction_log.jsonl",
             "output/hub_archive/index.json",
             why="annotate failing inside the real hub build: plain names, the hub goes on")
def test_annotate_failing_in_the_real_build_leaves_plain_names(monkeypatch):
    from modules import hub_state

    def broken(part):
        raise hc.CardsError(f"a moves-feed part this module cannot read: {part!r}")
    monkeypatch.setattr(hc, "part_names", broken)                            # after the rosters were keyed
    co = {}
    try:
        payload = hub_state.build(ROOT, allow_engine_mismatch=True, echo=lambda *a: None, cards_out=co)
    except hub_state.HubInputError as e:
        if "moves-feed" in str(e):
            raise
        pytest.skip(f"the real hub does not build on this checkout's state: {e}")
    if not any(it["parts"] for w in payload["moves"]["weeks"] for it in w["items"]):
        pytest.skip("no moves-feed part on this state to fail on")
    assert co["error"]["stage"] == "annotate" and "moves-feed" in co["error"]["error"]
    assert payload["cards"] is None
    for rb in payload["rosters"].values():
        assert not [p for p in rb["players"] if "card" in p]
    assert not [r for r in payload["free_agents"]["rows"] if "card" in r]
