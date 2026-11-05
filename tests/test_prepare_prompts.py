"""
scripts/prepare_prompts.py / modules/prepare_prompts.py (task 10a): the three
drafting prompts, filled from the week's stats report.
claude/HANDOFF_PREPARE_PROMPTS_2026-11-05.md is the spec.

Every test but the last builds a small league in tmp_path (the real template,
a fixture config, report, rosters, IL slots, ledger and log). The last fills
Nick's real week-2 report when it is on disk, writing nothing.
"""

import json
import re
import shutil
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from modules import angles as ang
from modules import prepare_prompts as pp

ROOT = Path(__file__).resolve().parent.parent
PT = timezone(timedelta(hours=-8))
NOW = datetime(2026, 11, 5, 10, 0, tzinfo=PT)
TODAY = NOW.date()           # week 3
MANAGERS = ["Ann", "Bob", "Cal", "Dee"]
TEAMS = {"Ann": "Team A", "Bob": "Team B", "Cal": "Team C", "Dee": "Team D"}
ROSTERS = {m: [f"{m} Player{i}" for i in range(1, 6)] for m in MANAGERS}
WEEKS = [(1, "2026-10-20", "2026-10-25"), (2, "2026-10-26", "2026-11-01"),
         (3, "2026-11-02", "2026-11-08"), (4, "2026-11-09", "2026-11-15")]

LEAD_SEL = {
    "lead": {"text": "SEASON RECORD: Cal scored 1735.75 FP", "unusualness": 2.08,
             "consequence": 0.26, "parts": {"cup": 0.26}},
    "secondary": [{"text": "Bob scored 1317.15, -16% against the week's average",
                   "unusualness": 0.94, "consequence": 0.42, "parts": {"cup": 0.42}}],
    "race_state": ["Regular season (weeks 1-15): Ann 2-0 | Cal 1-1 (1 back)",
                   "Cup (weeks 1-21): Cal 3158.15 | Ann 3128.95 (29.20 back)"],
    "money_events": [],
}
DEAD_SEL = {"dead": "every result this week was within its usual range",
            "race_state": ["Regular season (weeks 1-15): Ann 2-0"], "money_events": [],
            "lead": {"text": "Ann won by 4", "unusualness": 0.1, "consequence": 0.1, "parts": {}}}


# ============================================================ the fixture league

def _w(p: Path, obj):
    p.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(obj, str):
        p.write_bytes(obj.encode("utf-8"))
    else:
        p.write_text(json.dumps(obj, indent=1), encoding="utf-8")


def report_md(week, sel, generated="2026-11-02T08:13:15.844342", start="2026-10-26",
              end="2026-11-01", season="2026-2027"):
    header = (f"# WEEK {week} STATS REPORT -> NEWSLETTER INPUT\n"
              f"# Season {season} | Week {week} ({start} -> {end})\n"
              f"# Generated: {generated}\n# \n# fixture\n\n---\n\n"
              "## -> STORYLINE ALERTS -> READ FIRST -> \n\n- an alert\n\n---\n\n")
    block = ang.render_markdown(sel)
    # exactly how format_stats_report joins it (pinned by a test below)
    return header + block.rstrip("\n") + "\n\n---\n\n" + "## SECTION 1: MATCHUP SUMMARIES\n\nbody\n"


def keeper_players(order=None):
    out = []
    for m in MANAGERS:
        names = order.get(m) if order and m in order else ROSTERS[m]
        for r, n in enumerate(names, start=1):
            out.append({"player_name": n, "manager": m, "rank": r, "keep_k5": round(1 - r / 10, 2)})
    return out


def league(tmp_path, *, week=2, sel=LEAD_SEL, cfg_extra=None, il_week=3, il=None,
           keeper=None, ledger=None, log=None, wcti=None, wcti_dir="data"):
    b = tmp_path
    shutil.copy(ROOT / pp.TEMPLATE, (b / "templates").mkdir(parents=True) or b / pp.TEMPLATE)
    cfg = {"managers": MANAGERS, "manager_to_team": TEAMS,
           "season": {"current": "2026-27", "current_long": "2026-2027",
                      "league_season_number": 12, "data_era_season_number": 10},
           "presentation": {"magic_number_from_week": 8}}
    for k, v in (cfg_extra or {}).items():
        cfg[k] = {**cfg.get(k, {}), **v} if isinstance(v, dict) else v
    _w(b / "config/league_config.json", cfg)
    _w(b / "config/SCHEDULE.json", {"season_year": "2026-2027", "weeks": [
        {"week": w, "start_date": s, "end_date": e} for w, s, e in WEEKS]})
    s, e = [(s, e) for w, s, e in WEEKS if w == week][0]
    _w(b / f"output/stats_report_week{week}.md", report_md(week, sel, start=s, end=e))
    _w(b / f"output/stats_report_week{week}.json", {
        "metadata": {"week": week, "season_year": "2026-2027",
                     "date_range": {"start": s, "end": e},
                     "generated_at": "2026-11-02T08:13:15.844342"},
        "keeper_watch": {"week": week, "players": keeper or keeper_players()}})
    _w(b / "config/ROSTERS.json", {"rosters": ROSTERS, "_last_sync": "2026-11-05T08:27:59-08:00"})
    _w(b / "data/IL_SLOTS.json", {"fetched_at": "2026-11-05T08:27:57-08:00", "fantasy_week": il_week,
                                  "slots": il if il is not None else {"Ann": ["Ann Player2"],
                                                                      "Dee": ["Dee Player4", "Dee Player5"]}})
    for u in pp.UPLOADS[1:]:
        _w(b / u, "{}" if u.suffix == ".json" else "fixture\n")
    if ledger is not None:
        _w(b / "config/MOVE_LEDGER.json", {"schema": 1, "_comment": "fixture", "rows": ledger})
    if log is not None:
        _w(b / "data/transaction_log.jsonl", "".join(json.dumps(r) + "\n" for r in log))
    if wcti is not None:
        _w(b / wcti_dir / f"weeklycontextinput_week{week}.json", wcti)
    return b


def build(b, week=2, today=TODAY):
    return pp.build(b, week, today=today, now=NOW)


def ledger_trade(id_, a, a_gets, b, b_gets, *, claim_week=2, window="2026-11-02",
                 claimed="2026-10-29T21:14:00-07:00"):
    return {"row": "entry", "id": id_, "text": "Trade: ...", "kind": "trade",
            "parsed": {"sides": [{"manager": a, "gets": a_gets}, {"manager": b, "gets": b_gets}]},
            "claimed_at": claimed, "claim_week": claim_week, "window_week": claim_week + 1,
            "window": window, "entered_at": claimed, "entered_by": "test", "checks": []}


def log_trade(key, a, a_gets, b, b_gets, *, day="2026-11-02", week=3, time="11:57:20"):
    def part(n, to, fr):
        return {"name": n, "player_key": f"k.{n}", "action": "trade",
                "from": {"type": "team", "team_key": fr, "team": TEAMS[fr], "manager": fr},
                "to": {"type": "team", "team_key": to, "team": TEAMS[to], "manager": to}}
    return {"row": "transaction", "key": key, "id": 1, "type": "trade", "status": "successful",
            "timestamp": int(datetime.fromisoformat(f"{day}T{time}-08:00").timestamp()),
            "time": f"{day}T{time}-08:00", "league_day": day, "fantasy_week": week,
            "players": [part(n, a, b) for n in a_gets] + [part(n, b, a) for n in b_gets],
            "rulings": [], "logged_at": "x", "logged_by": "x"}


def part(text, name):
    """One part of the output: 1, 2 or 3."""
    i = text.index(f"## PART {name}")
    j = text.find("## PART", i + 5)
    return text[i: j if j > 0 else len(text)]


# ============================================================ mangled characters

OLD_MANGLED_SAMPLES = [
    '# Newsletter Drafting Prompts " Reusable Template',
    "2. **Key storylines (3\"5 bullets)** \" The big narratives. Check:",
    "8. **Stats Corner**  EIGHT tables required, in this order:",
    "   3. Best Performers  Total FP, This Season",
    "Follow the extract'cite'write'clean workflow internally",
    "' Injury updates for currently injured rostered players",
    "Include a letter grade (A\"F) for EACH manager",
    "a dash read wrong \u00e2\u20ac\u201d here", "a replacement \ufffd character",
]


@pytest.mark.parametrize("line", OLD_MANGLED_SAMPLES)
def test_the_detector_catches_every_kind_of_mangling_the_old_template_had(line):
    assert pp.mangled(line), line


def test_the_template_has_no_mangled_characters():
    text = (ROOT / pp.TEMPLATE).read_text(encoding="utf-8")
    assert pp.mangled(text) == []


def test_the_template_keeps_its_rules_and_drops_the_stale_text():
    text = (ROOT / pp.TEMPLATE).read_text(encoding="utf-8")
    for gone in ("college friends", "Smaxey", "Saboner", "Paolo Banchero", "Luka Doncic"):
        assert gone not in text, gone
    for kept in ("magic numbers from the week 8 report on only", "template rule 23",
                 "The advice returns with the new engine.", "NOT by letter grade",
                 "EIGHT tables required", "TWO tables required", pp.GRADE_LINE,
                 "Check DRAFT PICK OWNERSHIP", "## VERIFICATION CHECKLIST",
                 "Verify against `trade_partners` data", "template rule 21"):
        assert kept in text, kept


def test_the_template_is_still_fillable_by_hand():
    text = (ROOT / pp.TEMPLATE).read_text(encoding="utf-8")
    assert text.count(pp.HAND_START) == text.count(pp.HAND_END) == 1
    assert "Pre-Flight Checklist" in text.split(pp.HAND_END)[0]
    for ph in (pp.PH_WEEK, pp.PH_MANAGERS, pp.PH_ANGLES, pp.PH_ROSTERS, pp.PH_ORDINAL,
               pp.PH_S9_START, pp.IF_TRADES, pp.IF_WCTI, pp.END_IF):
        assert ph in text, ph


def test_the_upload_list_is_the_templates_list():
    text = (ROOT / pp.TEMPLATE).read_text(encoding="utf-8")
    want = [u.name.replace("week{week}", "weekN") for u in pp.UPLOADS] + ["weeklycontextinput_weekN.json"]
    assert pp.template_uploads(text) == want


# ============================================================ the whole output

def test_nothing_is_left_to_fill_and_nothing_is_mangled(tmp_path):
    out = build(league(tmp_path))
    assert pp.leftovers(out) == []
    for bad in ("[FILL IN", "[IF", "[END IF]", "BY HAND ONLY"):
        assert bad not in out
    block = pp.angles_block((tmp_path / "output/stats_report_week2.md").read_text("utf-8"))
    assert pp.mangled(out.replace(block, "")) == []
    assert out.count("```") == 2 * 4       # three prompts and the verification prompt, fenced


def test_week_dates_season_and_the_closing_line(tmp_path):
    out = build(league(tmp_path))
    assert "**Season 2026-27 | Week 2 (Oct 26 to Nov 1)**" in out
    assert "## **CHS Alumni Fantasy Basketball League \u2014 Week 2 Newsletter**" in out
    assert "**End of Week 2 Newsletter**" in out
    assert "Continue the Week 2 Newsletter." in out and "Finish the Week 2 Newsletter." in out
    assert "headlines from **Oct 26 to Nov 1, 2026**" in part(out, 3)


def test_section_9_dates_across_a_new_year():
    assert pp.search_dates(date(2026, 12, 28), date(2027, 1, 3)) == ("Dec 28, 2026", "Jan 3, 2027")
    assert pp.title_dates(date(2026, 11, 30), date(2026, 12, 13)) == ("Nov 30", "Dec 13")


def test_the_uploads_are_listed_by_path_at_the_top_each_existing(tmp_path):
    b = league(tmp_path)
    out = build(b)
    top = out.split("## PART 1")[0]
    listed = re.findall(r"(?m)^\d+\. `([^`]+)`$", top)
    assert listed == [str(u).format(week=2).replace("/", "\\") for u in pp.UPLOADS]
    for x in listed:
        assert (b / x.replace("\\", "/")).is_file()
    assert "weeklycontextinput" not in out


def test_a_missing_upload_refuses(tmp_path):
    b = league(tmp_path)
    (b / "output/lore_for_drafting.json").unlink()
    with pytest.raises(pp.PromptsRefused, match="lore_for_drafting.json.*review_lore.py --export"):
        build(b)


def test_the_weekly_context_file_is_listed_when_it_exists(tmp_path):
    b = league(tmp_path, wcti={"week": 2, "notes": "a note"})
    out = build(b)
    assert "`data\\weeklycontextinput_week2.json`" in out.split("## PART 1")[0]
    assert "- `weeklycontextinput_week2.json`" in part(out, 1)


def test_a_weekly_context_file_outside_data_refuses(tmp_path):
    b = league(tmp_path, wcti={"week": 2}, wcti_dir="config")
    with pytest.raises(pp.PromptsRefused, match="belongs in data/ only"):
        build(b)


# ============================================================ league line, managers

def test_twelfth_comes_from_league_season_number_not_the_data_era(tmp_path):
    out = build(league(tmp_path, cfg_extra={"season": {"data_era_season_number": 3}}))
    assert "a 4-team keeper league among CHS alumni, now in its twelfth season." in out
    out = build(league(tmp_path / "b", cfg_extra={"season": {"league_season_number": 13}}))
    assert "now in its thirteenth season." in out


def test_the_ordinal_words_raise_past_the_list():
    assert pp.ordinal_word(12) == "twelfth" and pp.ordinal_word(1) == "first"
    for bad in (len(pp.ORDINALS) + 1, 0, "12", True, None):
        with pytest.raises(pp.PromptsRefused):
            pp.ordinal_word(bad)


def _table(out):
    rows = re.findall(r"(?m)^\| (\w+) \| ([^|]+) \| ([^|]+) \|$", part(out, 1))
    return [(m, t.strip(), [s.strip() for s in stars.split(",")]) for m, t, stars in rows
            if m not in ("Manager",)]


def test_the_manager_table_is_the_config_and_the_stars_come_from_the_report(tmp_path):
    order = {"Bob": ["Bob Player5", "Bob Player3", "Bob Player1", "Bob Player2", "Bob Player4"]}
    out = build(league(tmp_path, keeper=keeper_players(order)))
    rows = _table(out)
    assert [(m, t) for m, t, _ in rows] == [(m, TEAMS[m]) for m in MANAGERS]
    stars = {m: s for m, _, s in rows}
    assert stars["Bob"] == ["Bob Player5", "Bob Player3", "Bob Player1"]
    assert stars["Ann"] == ["Ann Player1", "Ann Player2", "Ann Player3"]


def test_a_manager_without_three_ranked_players_refuses(tmp_path):
    kp = [p for p in keeper_players() if not (p["manager"] == "Cal" and p["rank"] == 2)]
    with pytest.raises(pp.PromptsRefused, match="rank-2 players for Cal"):
        build(league(tmp_path, keeper=kp))


def test_a_team_name_missing_from_the_config_refuses(tmp_path):
    b = league(tmp_path)
    cfg = json.loads((b / "config/league_config.json").read_text())
    del cfg["manager_to_team"]["Dee"]
    _w(b / "config/league_config.json", cfg)
    with pytest.raises(pp.PromptsRefused, match="manager_to_team"):
        build(b)


# ============================================================ the ANGLES block

def test_the_angles_block_appears_byte_for_byte(tmp_path):
    out = build(league(tmp_path))
    block = ang.render_markdown(LEAD_SEL).rstrip("\n")
    assert block in out
    p1 = part(out, 1)
    assert p1.index("### KEY STORYLINES") < p1.index(block) < p1.index("**Money (template rule 23):**")
    # in its order: the lead, the secondary, the threads, the money line
    pos = [out.index(x) for x in ("**Lead:**", "Bob scored 1317.15", "**Standing threads**",
                                  "**Money this week")]
    assert pos == sorted(pos)


def test_no_lead_this_week_passes_through(tmp_path):
    out = build(league(tmp_path, sel=DEAD_SEL))
    block = ang.render_markdown(DEAD_SEL).rstrip("\n")
    assert block in out and "## -> ANGLES -> NO LEAD THIS WEEK" in out


def test_an_unavailable_angles_block_refuses(tmp_path):
    b = league(tmp_path)
    p = b / "output/stats_report_week2.md"
    md = p.read_text("utf-8")
    s = md.index("## -> ANGLES -> ")
    e = md.index("\n\n---\n", s)
    _w(p, md[:s] + "## -> ANGLES -> unavailable this week (boom). Choose the lead from the "
           "storyline alerts.\n" + md[e:])
    with pytest.raises(pp.PromptsRefused, match="the angles did not run"):
        build(b)


def test_the_block_ends_where_format_stats_report_ends_it():
    src = (ROOT / "scripts" / "format_stats_report.py").read_text("utf-8")
    assert 'angles_block = angles_block.rstrip("\\n") + "\\n\\n---\\n\\n"' in src
    assert 'out = ["## -> ANGLES -> WHAT LEADS THIS WEEK"' in (ROOT / "modules/angles.py").read_text("utf-8")


# ============================================================ the report's week

def test_a_missing_report_refuses(tmp_path):
    b = league(tmp_path)
    (b / "output/stats_report_week2.md").unlink()
    with pytest.raises(pp.PromptsRefused, match="stats_report_week2.md is missing"):
        build(b)
    with pytest.raises(pp.PromptsRefused, match="stats_report_week3.json is missing"):
        build(b, week=3)


def test_another_weeks_report_refuses(tmp_path):
    b = league(tmp_path)
    js = json.loads((b / "output/stats_report_week2.json").read_text())
    js["metadata"]["week"] = 1
    _w(b / "output/stats_report_week2.json", js)
    with pytest.raises(pp.PromptsRefused, match="is the week 1 report"):
        build(b)
    b = league(tmp_path / "md")
    _w(b / "output/stats_report_week2.md", report_md(1, LEAD_SEL))
    with pytest.raises(pp.PromptsRefused, match="does not open as the week 2 report"):
        build(b)


def test_a_markdown_not_formatted_from_this_json_refuses(tmp_path):
    b = league(tmp_path)
    _w(b / "output/stats_report_week2.md", report_md(2, LEAD_SEL, generated="2026-11-01T00:00:00"))
    with pytest.raises(pp.PromptsRefused, match="rerun Step 6.5"):
        build(b)


def test_dates_that_disagree_with_the_schedule_refuse(tmp_path):
    b = league(tmp_path)
    js = json.loads((b / "output/stats_report_week2.json").read_text())
    js["metadata"]["date_range"]["end"] = "2026-11-02"
    _w(b / "output/stats_report_week2.json", js)
    with pytest.raises(pp.PromptsRefused, match="schedule's week 2"):
        build(b)


# ============================================================ rosters and IL

def test_every_player_is_listed_and_il_players_are_marked(tmp_path):
    out = part(build(league(tmp_path)), 3)
    for m in MANAGERS:
        line = [x for x in out.splitlines() if x.startswith(f"- **{m}** (")][0]
        for n in ROSTERS[m]:
            assert n in line
    ann = [x for x in out.splitlines() if x.startswith("- **Ann** (")][0]
    assert "Ann Player2 (IL)" in ann and "Ann Player1 (IL)" not in ann
    assert "(Team A; active 4, IL 1)" in ann
    dee = [x for x in out.splitlines() if x.startswith("- **Dee** (")][0]
    assert "Dee Player4 (IL), Dee Player5 (IL)" in dee and "active 3, IL 2" in dee
    bob = [x for x in out.splitlines() if x.startswith("- **Bob** (")][0]
    assert "(IL)" not in bob and "IL 0" in bob


def test_last_weeks_il_file_refuses(tmp_path):
    with pytest.raises(pp.PromptsRefused, match="IL_SLOTS.json is week 2's; today .* is week 3"):
        build(league(tmp_path, il_week=2))


def test_an_il_player_not_on_the_roster_refuses(tmp_path):
    with pytest.raises(pp.PromptsRefused, match="not on Bob's roster"):
        build(league(tmp_path, il={"Bob": ["Ann Player1"]}))


# ============================================================ trades

def test_no_trade_no_block(tmp_path):
    out = build(league(tmp_path, ledger=[], log=[]))
    assert "headline MUST cover" not in out and pp.GRADE_LINE not in out
    assert "### Section 9: Around the NBA\n\n**Then search the web**" in out


def test_a_chat_trade_claimed_in_week_n_makes_the_block(tmp_path):
    led = [ledger_trade(1, "Ann", ["Bob Player1"], "Bob", ["Ann Player3", "Ann Player4"])]
    out = part(build(league(tmp_path, ledger=led, log=[])), 3)
    assert "**FIRST headline MUST cover the Week 2 trade** (agreed in the group chat" in out
    assert "- Ann sends: Ann Player3, Ann Player4" in out
    assert "- Bob sends: Bob Player1" in out
    assert pp.GRADE_LINE in out
    assert out.index("headline MUST cover") < out.index("**Then search the web**")


def test_a_chat_trade_from_another_week_is_not_this_weeks(tmp_path):
    led = [ledger_trade(1, "Ann", ["Bob Player1"], "Bob", ["Ann Player3"], claim_week=1,
                        window="2026-10-26", claimed="2026-10-22T20:00:00-07:00")]
    out = build(league(tmp_path, ledger=led, log=[]))
    assert "headline MUST cover" not in out


def test_the_ledger_and_yahoo_agreeing_is_one_trade(tmp_path):
    led = [ledger_trade(1, "Ann", ["Bob Player1"], "Bob", ["Ann Player3"])]
    log = [log_trade("tr.1", "Ann", ["Bob Player1"], "Bob", ["Ann Player3"])]
    out = part(build(league(tmp_path, ledger=led, log=log)), 3)
    assert out.count("sends:") == 2 and "made in Yahoo Mon Nov 2, 11:57 AM Pacific" in out


def test_the_ledger_and_yahoo_disagreeing_refuses(tmp_path):
    led = [ledger_trade(1, "Ann", ["Bob Player1"], "Bob", ["Ann Player3"])]
    log = [log_trade("tr.1", "Ann", ["Bob Player2"], "Bob", ["Ann Player3"])]
    with pytest.raises(pp.PromptsRefused, match="move ledger and Yahoo's log disagree"):
        build(league(tmp_path, ledger=led, log=log))


def test_last_weeks_trade_applied_this_week_must_agree_too(tmp_path):
    led = [ledger_trade(1, "Ann", ["Bob Player1"], "Bob", ["Ann Player3"], claim_week=1,
                        window="2026-10-26", claimed="2026-10-22T20:00:00-07:00")]
    log = [log_trade("tr.1", "Ann", ["Bob Player1"], "Bob", ["Ann Player4"], day="2026-10-26", week=2)]
    with pytest.raises(pp.PromptsRefused, match="disagree"):
        build(league(tmp_path, ledger=led, log=log))
    log = [log_trade("tr.1", "Ann", ["Bob Player1"], "Bob", ["Ann Player3"], day="2026-10-26", week=2)]
    assert "headline MUST cover" not in build(league(tmp_path / "ok", ledger=led, log=log))


def test_a_trade_made_in_yahoo_in_week_ns_window_makes_the_block(tmp_path):
    log = [log_trade("tr.9", "Cal", ["Dee Player1"], "Dee", ["Cal Player1"], day="2026-10-26", week=2)]
    out = part(build(league(tmp_path, ledger=[], log=log)), 3)
    assert "made in Yahoo Mon Oct 26" in out and "- Dee sends: Dee Player1" in out


def test_a_midweek_yahoo_trade_refuses(tmp_path):
    log = [log_trade("tr.9", "Cal", ["Dee Player1"], "Dee", ["Cal Player1"], day="2026-10-28", week=2)]
    with pytest.raises(pp.PromptsRefused, match="outside week 2's Monday window"):
        build(league(tmp_path, ledger=[], log=log))


def test_picks_come_from_the_weekly_context_file(tmp_path):
    led = [ledger_trade(1, "Ann", ["Bob Player1"], "Bob", ["Ann Player3"])]
    wcti = {"week": 2, "trades": [{"manager_a": "Ann", "sends_a": ["Ann Player3", "2027 2nd round pick"],
                                   "manager_b": "Bob", "sends_b": ["Bob Player1"]}]}
    out = part(build(league(tmp_path, ledger=led, log=[], wcti=wcti)), 3)
    assert "- Ann sends: Ann Player3, 2027 2nd round pick" in out


def test_a_weekly_context_trade_that_disagrees_refuses(tmp_path):
    led = [ledger_trade(1, "Ann", ["Bob Player1"], "Bob", ["Ann Player3"])]
    wcti = {"week": 2, "trades": [{"manager_a": "Ann", "sends_a": ["Ann Player4"],
                                   "manager_b": "Bob", "sends_b": ["Bob Player1"]}]}
    with pytest.raises(pp.PromptsRefused, match="disagrees with the week 2 trade"):
        build(league(tmp_path, ledger=led, log=[], wcti=wcti))
    wcti = {"week": 2, "trades": [{"manager_a": "Cal", "sends_a": ["Cal Player1"],
                                   "manager_b": "Dee", "sends_b": ["Dee Player1"]}]}
    with pytest.raises(pp.PromptsRefused, match="neither the move ledger nor Yahoo's log"):
        build(league(tmp_path / "b", ledger=led, log=[], wcti=wcti))


def test_a_picks_only_trade_needs_no_ledger_entry(tmp_path):
    wcti = {"week": 2, "trades": [{"manager_a": "Cal", "sends_a": ["2027 1st round pick"],
                                   "manager_b": "Dee", "sends_b": ["2027 3rd round pick"]}]}
    out = part(build(league(tmp_path, ledger=[], log=[], wcti=wcti)), 3)
    assert "- Cal sends: 2027 1st round pick" in out and "- Dee sends: 2027 3rd round pick" in out


def test_two_trades_get_one_headline_each(tmp_path):
    led = [ledger_trade(1, "Ann", ["Bob Player1"], "Bob", ["Ann Player3"]),
           ledger_trade(2, "Cal", ["Dee Player1"], "Dee", ["Cal Player2"])]
    out = part(build(league(tmp_path, ledger=led, log=[])), 3)
    assert "The first 2 headlines MUST cover the Week 2 trades, one headline each" in out
    assert out.count(pp.GRADE_LINE) == 1


def test_a_voided_ledger_trade_is_no_trade(tmp_path):
    led = [ledger_trade(1, "Ann", ["Bob Player1"], "Bob", ["Ann Player3"]),
           {"row": "void", "entry": 1, "by": "Nick", "on": "2026-10-30", "reason": "typo"}]
    assert "headline MUST cover" not in build(league(tmp_path, ledger=led, log=[]))


# ============================================================ the file and the state

def test_write_writes_only_its_output(tmp_path):
    b = league(tmp_path)
    before = {p: p.read_bytes() for p in b.rglob("*") if p.is_file()}
    out = pp.write(b, 2, today=TODAY, now=NOW)
    assert out == b / "output/prompts_week2.md"
    after = {p: p.read_bytes() for p in b.rglob("*") if p.is_file()}
    assert set(after) - set(before) == {out}
    assert all(after[p] == before[p] for p in before)


def test_the_output_is_league_state_and_never_committed():
    from modules import state_manifest as sm
    man = sm.load(ROOT)
    assert man.contains("output/prompts_week3.md")
    assert "output/prompts_week*.md" in (ROOT / ".gitignore").read_text("utf-8").splitlines()


def test_the_workflow_runs_the_script_first():
    wf = (ROOT / "WEEKLY_WORKFLOW.md").read_text("utf-8")
    step7 = wf.split("## Step 7: Draft the Newsletter", 1)[1].split("## Step 7.5", 1)[0]
    first = [x for x in step7.splitlines() if x.strip() and not x.startswith("#")][0:3]
    assert any("python scripts\\prepare_prompts.py --week N" in x for x in first), first
    assert "py scripts" not in step7


def test_the_script_refuses_with_exit_1(tmp_path, capsys):
    import importlib.util
    spec = importlib.util.spec_from_file_location("prep_script", ROOT / "scripts/prepare_prompts.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    b = league(tmp_path)
    (b / "output/stats_report_week2.md").unlink()
    assert mod.main(["--week", "2", "--base-path", str(b)]) == 1
    assert "REFUSED: output/stats_report_week2.md is missing" in capsys.readouterr().out


# ============================================================ Nick's real week 2

def test_nicks_real_week_2_fills_cleanly():
    """On Nick's folder only (the report is league state). Writes nothing.
    `today` is the IL file's own week, so the check is about the fill, not
    about when the suite runs."""
    if not (ROOT / "output/stats_report_week2.md").is_file() or not (ROOT / "data/IL_SLOTS.json").is_file():
        pytest.skip("Nick's week-2 report is not on this machine")
    il = json.loads((ROOT / "data/IL_SLOTS.json").read_text("utf-8"))
    sched = json.loads((ROOT / "config/SCHEDULE.json").read_text("utf-8"))
    today = date.fromisoformat([w for w in sched["weeks"] if w["week"] == il["fantasy_week"]][0]["start_date"])
    out = pp.build(ROOT, 2, today=today, now=NOW)
    assert pp.leftovers(out) == []
    block = pp.angles_block((ROOT / "output/stats_report_week2.md").read_text("utf-8"))
    assert block in out and pp.mangled(out.replace(block, "")) == []
    assert "now in its twelfth season" in out
