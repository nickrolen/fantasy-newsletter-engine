"""5g s.5: `state.py pull` merges what can be merged, by per-file rules in
config/STATE_MANIFEST.json (a file entry's "merge"; modules/state_merge.py):

  append_jsonl     output/title_odds_history.jsonl
  calibration_log  data/calibration/published_lines.json
  cloud_wins       the derived "latest" files (title_odds_latest, stakes, ...)

Week 5's shape (11-24): the 3:30 PM afternoon run and Step 6 (3:43 PM) both
wrote four files. Tested on throwaway git repos (tests/test_state_manifest's
two machines and their private remote), never the real .state.
"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from modules import state_manifest as sm, state_merge as smg       # noqa: E402
from test_state_manifest import (two, _two_template, run_state, write, sh, _record,  # noqa: E402,F401
                                 tree)

HIST = "output/title_odds_history.jsonl"
CAL = "data/calibration/published_lines.json"
LATEST = "output/title_odds_latest.json"
STAKES = "output/stakes.json"


# ============================================================ the manifest

def test_the_manifest_names_the_rules():
    man = sm.load(ROOT)
    assert man.merge_rule(HIST) == "append_jsonl"
    assert man.merge_rule(CAL) == "calibration_log"
    cloud = sorted(p for p, r in man.merges if r == "cloud_wins")
    assert cloud == ["output/hub_state.json", "output/mvp_odds.json", "output/night_paragraph.json",
                     "output/nightly_last.json", "output/stakes.json", "output/title_odds_latest.json"]
    assert man.merge_rule("config/ROSTERS.json") is None
    assert sm.MERGE_RULES == smg.RULES


def test_the_manifest_refuses_an_unknown_rule():
    blob = json.loads((ROOT / sm.MANIFEST_FILE).read_text(encoding="utf-8"))
    blob["files"][0]["merge"] = "ours_wins"
    with pytest.raises(sm.ManifestError, match="merge 'ours_wins'"):
        sm.parse(blob)


def test_merge_copies_are_gitignored_and_excluded():
    assert ".state-merge/" in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert ".state-merge/" in sm.load(ROOT).excluded


# ============================================================ the rules, in memory

def hist_row(as_of, kind, g):
    return json.dumps({"as_of": as_of, "kind": kind, "title_odds": {"Garrett": g}}, sort_keys=True)


BASE_HIST = [hist_row("2026-11-24T00:05:34-08:00", "nightly", 54.1),
             hist_row("2026-11-24T07:29:27-08:00", "nightly", 56.858)]
AFTERNOON = hist_row("2026-11-24T15:30:39-08:00", "afternoon", 57.42)
BUILD = hist_row("2026-11-24T15:43:27-08:00", "weekly_build", 61.438)


def jl(lines):
    return ("\n".join(lines) + "\n").encode("utf-8")


def test_append_jsonl_merges_the_week_5_shape():
    out, summary = smg.append_jsonl(jl(BASE_HIST), jl(BASE_HIST + [AFTERNOON]), jl(BASE_HIST + [BUILD]), HIST)
    assert out == jl(BASE_HIST + [AFTERNOON, BUILD])
    assert "2 line(s) in common, 1 from the private repo, 1 from here (4 in all" in summary
    # the order is as_of, whichever side wrote it
    out, _ = smg.append_jsonl(jl(BASE_HIST), jl(BASE_HIST + [BUILD]), jl(BASE_HIST + [AFTERNOON]), HIST)
    assert out == jl(BASE_HIST + [AFTERNOON, BUILD])


def test_append_jsonl_refuses_an_edited_or_removed_line():
    edited = [BASE_HIST[0], BASE_HIST[1].replace("56.858", "56.9")]
    with pytest.raises(smg.MergeRefused, match="edited or removed"):
        smg.append_jsonl(jl(BASE_HIST), jl(edited + [AFTERNOON]), jl(BASE_HIST + [BUILD]), HIST)
    with pytest.raises(smg.MergeRefused, match="edited or removed"):
        smg.append_jsonl(jl(BASE_HIST), jl(BASE_HIST + [AFTERNOON]), jl(BASE_HIST[1:] + [BUILD]), HIST)


def test_append_jsonl_refuses_a_new_line_it_cannot_order():
    with pytest.raises(smg.MergeRefused, match="no offset"):
        smg.append_jsonl(jl(BASE_HIST), jl(BASE_HIST + [AFTERNOON]),
                         jl(BASE_HIST + [hist_row("2026-11-24T16:42:36", "weekly_build", 1.0)]), HIST)


def rec(week, a, b, source, key, *, settled=False):
    return {"season": "2026-27", "week": week, "matchup_id": f"{a}|{b}", "source": source, "line_key": key,
            "spread_a": -1.5, "actual_a": 1300.0 if settled else None, "actual_b": 1200.0 if settled else None,
            "actual_source": "RECORDS.json" if settled else None,
            "settled_at": "2026-11-23" if settled else None}


def cal_blob(lines):
    return json.dumps({"schema": 1, "lines": lines, "_comment": "append-only"}, indent=2).encode("utf-8")


SETTLED50 = [rec(1 + i // 10, "A", f"B{i}", "live_refresh", f"k{i}", settled=True) for i in range(50)]
CLOSING6 = [rec(6, "Garrett", "Nick", "closing", "c1"), rec(6, "Benton", "Hayden", "closing", "c2")]
LIVE = [rec(6, "Garrett", "Nick", "live_refresh", "l1"), rec(6, "Benton", "Hayden", "live_refresh", "l2")]
WEEKLY = [rec(6, "Garrett", "Nick", "weekly_build", "w1"), rec(6, "Benton", "Hayden", "weekly_build", "w2")]


def test_calibration_log_merges_the_week_5_shape():
    base = SETTLED50 + CLOSING6
    out, summary = smg.calibration_log(cal_blob(base), cal_blob(base + LIVE), cal_blob(base + WEEKLY), CAL)
    assert json.loads(out)["lines"] == base + LIVE + WEEKLY
    assert out == cal_blob(base + LIVE + WEEKLY)                 # calibration_log.save_log's format
    assert "52 record(s) in common (0 settled on one side), 2 appended in the private repo, 2 here" in summary


def test_calibration_log_merges_settle_fields_from_either_side():
    base = SETTLED50 + CLOSING6
    theirs = SETTLED50 + [dict(CLOSING6[0], actual_a=1500.0, actual_b=1400.0, actual_source="RECORDS.json",
                               settled_at="2026-11-30"), CLOSING6[1]] + LIVE
    ours = SETTLED50 + [CLOSING6[0], dict(CLOSING6[1], actual_a=1250.0, actual_b=1350.0,
                                          actual_source="RECORDS.json", settled_at="2026-11-30")] + WEEKLY
    out, summary = smg.calibration_log(cal_blob(base), cal_blob(theirs), cal_blob(ours), CAL)
    lines = json.loads(out)["lines"]
    assert lines[50]["actual_a"] == 1500.0 and lines[51]["actual_b"] == 1350.0
    assert lines[52:] == LIVE + WEEKLY and "(2 settled on one side)" in summary


def test_calibration_log_refuses_a_settle_conflict():
    base = SETTLED50 + CLOSING6
    t = SETTLED50 + [dict(CLOSING6[0], actual_a=1500.0, settled_at="2026-11-30"), CLOSING6[1]]
    o = SETTLED50 + [dict(CLOSING6[0], actual_a=1499.0, settled_at="2026-11-30"), CLOSING6[1]]
    with pytest.raises(smg.MergeRefused, match="settled differently on the two sides: actual_a 1500.0 vs 1499.0"):
        smg.calibration_log(cal_blob(base), cal_blob(t), cal_blob(o), CAL)


def test_calibration_log_refuses_anything_else():
    base = SETTLED50 + CLOSING6
    t = SETTLED50 + [dict(CLOSING6[0], spread_a=-2.5), CLOSING6[1]]
    with pytest.raises(smg.MergeRefused, match="changed 'spread_a'"):
        smg.calibration_log(cal_blob(base), cal_blob(t), cal_blob(base), CAL)
    with pytest.raises(smg.MergeRefused, match="fewer records"):
        smg.calibration_log(cal_blob(base), cal_blob(base[1:]), cal_blob(base), CAL)
    with pytest.raises(smg.MergeRefused, match="disagree on 'schema'"):
        smg.calibration_log(cal_blob(base), json.dumps({"schema": 2, "lines": base, "_comment": "append-only"},
                                                       indent=2).encode(), cal_blob(base), CAL)


def test_cloud_wins_takes_the_private_repos():
    assert smg.cloud_wins(b"base", b"theirs", b"ours", STAKES)[0] == b"theirs"
    with pytest.raises(smg.MergeRefused):
        smg.merge("cloud_wins", b"base", None, b"ours", STAKES)


# ============================================================ state.py pull, on throwaway repos

def _week5(a, b):
    """The common base, pushed from a and pulled into b; then b (the cloud's
    afternoon run) appends and pushes; then a (Step 6) appends, unpushed."""
    write(a, HIST, jl(BASE_HIST))
    write(a, CAL, cal_blob(SETTLED50 + CLOSING6))
    write(a, LATEST, '{"as_of": "nightly"}')
    write(a, STAKES, '{"as_of": "nightly"}')
    assert run_state(a, "push")[0] == 0
    assert run_state(b, "pull")[0] == 0
    write(b, HIST, jl(BASE_HIST + [AFTERNOON]))
    write(b, CAL, cal_blob(SETTLED50 + CLOSING6 + LIVE))
    write(b, LATEST, '{"as_of": "afternoon"}')
    write(b, STAKES, '{"as_of": "afternoon"}')
    assert run_state(b, "push")[0] == 0
    write(a, HIST, jl(BASE_HIST + [BUILD]))
    write(a, CAL, cal_blob(SETTLED50 + CLOSING6 + WEEKLY))
    write(a, LATEST, '{"as_of": "weekly_build"}')
    write(a, STAKES, '{"as_of": "weekly_build"}')


@pytest.mark.slow
def test_pull_merges_the_week_5_shape_and_push_sends_it(two):
    a, b = two
    _week5(a, b)
    rc, out = run_state(a, "pull")
    assert rc == 0, out
    assert (a / HIST).read_bytes() == jl(BASE_HIST + [AFTERNOON, BUILD])
    assert json.loads((a / CAL).read_text())["lines"] == SETTLED50 + CLOSING6 + LIVE + WEEKLY
    assert (a / LATEST).read_text() == '{"as_of": "afternoon"}'
    assert (a / STAKES).read_text() == '{"as_of": "afternoon"}'
    for rel, rule in ((HIST, "append_jsonl"), (CAL, "calibration_log"), (LATEST, "cloud_wins"),
                      (STAKES, "cloud_wins")):
        assert f"merged   {rel}  ({rule}:" in out, out
    assert "1 from the private repo, 1 from here (4 in all" in out
    # Nick's versions are kept
    backups = list((a / ".state-merge").iterdir())
    assert len(backups) == 1
    assert (backups[0] / HIST).read_bytes() == jl(BASE_HIST + [BUILD])
    assert (backups[0] / STAKES).read_text() == '{"as_of": "weekly_build"}'
    assert "kept in .state-merge" in out
    # the merged files go up with the next push, and the cloud gets them
    rc, out = run_state(a, "push")
    assert rc == 0 and HIST in out and CAL in out and STAKES not in out, out
    assert run_state(b, "pull")[0] == 0
    assert tree(b, [HIST, CAL, LATEST, STAKES]) == tree(a, [HIST, CAL, LATEST, STAKES])


@pytest.mark.slow
def test_an_edited_history_line_refuses_and_changes_nothing(two):
    a, b = two
    _week5(a, b)
    write(a, HIST, jl([BASE_HIST[0], BASE_HIST[1].replace("56.858", "1.0"), BUILD]))
    before = {"files": tree(a, [HIST, CAL, LATEST, STAKES]), "record": _record(a),
              "head": sh("rev-parse", "HEAD", cwd=a / ".state")}
    rc, out = run_state(a, "pull")
    assert rc == 1 and "append_jsonl" in out and "edited or removed" in out and HIST in out, out
    assert tree(a, [HIST, CAL, LATEST, STAKES]) == before["files"]
    assert _record(a) == before["record"] and sh("rev-parse", "HEAD", cwd=a / ".state") == before["head"]
    assert not (a / ".state-merge").exists()


@pytest.mark.slow
def test_a_settle_conflict_refuses(two):
    a, b = two
    _week5(a, b)
    run_state(b, "pull")
    settled_b = SETTLED50 + [dict(CLOSING6[0], actual_a=1500.0, settled_at="2026-11-30"), CLOSING6[1]] + LIVE
    write(b, CAL, cal_blob(settled_b))
    assert run_state(b, "push")[0] == 0
    write(a, CAL, cal_blob(SETTLED50 + [dict(CLOSING6[0], actual_a=1499.0, settled_at="2026-11-30"),
                                        CLOSING6[1]] + WEEKLY))
    before = tree(a, [HIST, CAL, LATEST, STAKES])
    rc, out = run_state(a, "pull")
    assert rc == 1 and "settled differently" in out, out
    assert tree(a, [HIST, CAL, LATEST, STAKES]) == before


@pytest.mark.slow
def test_a_file_with_no_rule_still_refuses_the_whole_pull(two):
    a, b = two
    _week5(a, b)
    run_state(b, "pull")
    write(b, "config/ROSTERS.json", "runner\n")
    assert run_state(b, "push")[0] == 0
    write(a, "config/ROSTERS.json", "desk\n")
    before = tree(a, [HIST, CAL, LATEST, STAKES, "config/ROSTERS.json"])
    rc, out = run_state(a, "pull")
    assert rc == 1 and "config/ROSTERS.json" in out
    assert HIST not in out.split("nothing was changed")[0]          # only the file with no rule is named
    assert tree(a, [HIST, CAL, LATEST, STAKES, "config/ROSTERS.json"]) == before
