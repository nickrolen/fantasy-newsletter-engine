"""Page layout before newsletter 1 publishes (HANDOFF_PAGE_LAYOUT_FIXES
2026-10-30; Nick's review of the week 1 preview).

Nick's rule for the whole page: prose comes after the table or panel it
describes, never before.
"""
import itertools
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import newsletter_html_generator as gen                       # noqa: E402
from modules import standing_threads as T                    # noqa: E402
from modules import published_tables as pt                   # noqa: E402
from modules.data_loader import MANAGER_TO_TEAM              # noqa: E402
import test_money_section as M                               # noqa: E402

CTX = {"season": None, "standings": {}}


# ------------------------------------------------- 1. matchup scoreboard headers

TEAMS = sorted(set(MANAGER_TO_TEAM.values()) | {"Kevin Quran't", "Blink-183"})


@pytest.fixture
def teams():
    gen.set_team_names({"matchups": [{"team_a": t} for t in TEAMS]})
    yield
    gen.set_team_names(None)


def test_every_team_name_renders_a_boxed_scoreboard_header(teams):
    for a, b in itertools.permutations(TEAMS, 2):
        for line in (f"**{a} 1424.30 def. {b} 1145.60**", f"{a} 1424.30 -- {b} 1145.60"):
            html = gen.parse_section(line + "\n\nA paragraph.\n", "1. Matchup Recap")
            assert f'<div class="matchup-header">{line.strip("*")}</div>' in html, line


def test_every_team_name_renders_a_boxed_versus_header(teams):
    for a, b in itertools.permutations(TEAMS, 2):
        html = gen.parse_section(f"**{a} vs {b}**\n\nA preview.\n", "3. Betting Lines")
        assert f'<div class="matchup-header">{a} vs {b}</div>' in html, (a, b)


def test_a_line_naming_no_league_team_is_not_a_scoreboard(teams):
    assert gen.scoreboard_header("Tyrese Maxey 170.90 def. Luka Doncic 158.20") is None


# ----------------------------------------------- 2. Player of the Week photo

def test_a_winner_with_no_file_gets_no_photo(tmp_path):
    said = []
    assert gen.resolve_potw_image("Tyrese Maxey", None, tmp_path, echo=said.append) is None
    assert "none for Tyrese Maxey" in said[0] and "tyrese-maxey.png" in said[0]


def test_another_players_file_refuses(tmp_path):
    f = tmp_path / "luka-doncic.png"
    f.write_bytes(b"x")
    with pytest.raises(gen.PotwImageMismatch, match="tyrese-maxey"):
        gen.resolve_potw_image("Tyrese Maxey", str(f), tmp_path)
    with pytest.raises(gen.PotwImageMismatch):
        gen.resolve_potw_image(None, str(f), tmp_path)
    assert gen.resolve_potw_image("Luka Dončić", str(f), tmp_path) == str(f)   # accents


DRAFT = ("# Title\n\n## **4. Player of the Week**\n\n**Player of the Week: Tyrese Maxey (PHI)**\n\n"
         "He scored a lot.\n")


def test_a_matching_file_is_embedded_and_none_is_never_a_fallback(tmp_path):
    out = tmp_path / "page.html"
    gen.build_newsletter_html(DRAFT, str(out), potw_dir=tmp_path)
    assert 'class="potw-img"' not in out.read_text(encoding="utf-8")
    (tmp_path / "luka-doncic.png").write_bytes(b"\x89PNG luka")
    gen.build_newsletter_html(DRAFT, str(out), potw_dir=tmp_path)
    assert 'class="potw-img"' not in out.read_text(encoding="utf-8")       # never Luka
    (tmp_path / "tyrese-maxey.png").write_bytes(b"\x89PNG maxey")
    gen.build_newsletter_html(DRAFT, str(out), potw_dir=tmp_path)
    page = out.read_text(encoding="utf-8")
    import base64
    want = base64.b64encode(b"\x89PNG maxey").decode()
    assert f'src="data:image/png;base64,{want}"' in page


def test_the_step_9_command_no_longer_passes_a_fixed_photo():
    wf = (ROOT / "WEEKLY_WORKFLOW.md").read_text(encoding="utf-8")
    assert "--potw assets\\potw.png" not in wf and "assets\\potw\\<winner-slug>.png" in wf


# ----------------------------------------------------- 3. Money and Exposure

def _money_page():
    ms = M._ms()
    rest, summ = gen.lift_block(M.BLOCK.split("\n", 1)[1], gen.MONEY_HEADER)
    html = T.render_money_html(ms, summ)
    return ms, html


def test_money_tables_come_first_and_the_paragraphs_last():
    _ms, html = _money_page()
    assert html.index("Title and money") < html.index("Pots and the Cup") < html.index("mx-summary")
    after = html[html.index('<div class="mx-summary">'):]
    assert after.count("<table") == 0
    assert "mx-lines" not in html and "mx-foot" not in html and "simulated seasons" not in html
    assert "Range" not in html


def test_both_money_tables_are_checked_with_their_relations():
    _ms, html = _money_page()
    page = f"<html><body><h2>Power Rankings</h2>{html}</body></html>"
    findings, unchecked = pt.check_document(page, dict(CTX))
    assert findings == [] and unchecked == []
    for old, new, check in ((">+$74<", ">+$84<", "zero-sum"),
                            (">-$135 (", ">-$185 (", "range")):
        f, _ = pt.check_document(page.replace(old, new, 1), dict(CTX))
        assert any(x.check == check for x in f), check
    # pots: a playoff-pot column that no longer sums to 200
    pots = re.search(r'<table class="mx-table mx-pots">.*?</table>', page, re.S).group(0)
    cells = re.findall(r"<td>([\d.]+)</td>", pots)
    broken = page.replace(pots, pots.replace(f"<td>{cells[3]}</td>", "<td>99.9</td>", 1))
    f, _ = pt.check_document(broken, dict(CTX))
    assert any(x.check in ("column sum", "subset") for x in f)
    # the subset relation reads the title table above it
    alone = page.replace(re.search(r'<h4 class="mx-caption">Title and money.*?</table></div>',
                                   page, re.S).group(0), "")
    f, _ = pt.check_document(alone, dict(CTX))
    assert any(x.check == "subset" for x in f)


# ------------------------------------------------------------ 5. games grid

def test_the_games_grid_has_no_footnote():
    import test_games_grid as G
    from modules import games_grid as gg
    src = (ROOT / "modules" / "games_grid.py").read_text(encoding="utf-8")
    assert "As of report time" not in src.split('def render_html')[1]
    html = gg.render_html(G._report())
    assert "As of report time" not in html and "INJURY_OVERRIDES" not in html


# ------------------------------------------------------------ 6. Keeper Watch

def test_keeper_watch_prose_comes_after_the_panel():
    from modules.stats_corner_viz import render_keeper_watch
    import test_keepability_wire as W
    html = render_keeper_watch(W._kw(), summary_html="<p>Drafter's paragraph.</p>")
    sub = html.index("sc-viz-subtitle")
    grid = html.index('class="sc-kw3-grid"')
    assert sub < grid < html.index("Drafter's paragraph.")
    if "sc-kw3-note" in html:
        assert grid < html.index('class="sc-kw3-note"')


def test_the_docs_no_longer_put_prose_on_top():
    for f in ("templates/newsletter_template.md", "WEEKLY_WORKFLOW.md"):
        text = (ROOT / f).read_text(encoding="utf-8")
        for bad in ("appear at the top of the block", "appear at the top of the panel",
                    "lifts them into the top of the panel"):
            assert bad not in text, (f, bad)
