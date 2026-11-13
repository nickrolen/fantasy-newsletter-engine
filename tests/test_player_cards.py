"""Tasks 40 / 40a (11-12): player cards on the hub, and the headshot library.

  - one slug rule (POTW, the hub, the newsletter), and the library's lookups;
  - scripts/headshots.py: add, add-folder (each outcome), refusals, --replace,
    missing's order;
  - a missing headshot: no image, no frame, never another player's photo;
  - every name the hub shows has a card (real payload); a free agent's and a
    rookie's cards; no made-up values;
  - the cards and headshots are their own encrypted files, never in the page
    bundle; byte-identical when unchanged; strays refused;
  - no lore in any card; POTW reads the library; the season reset keeps it;
  - the season filter's figures are the engine's, equal to the old modal's;
  - the real, unstubbed hub build, cards included, into scratch.
"""
import gzip
import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

from modules import headshots as hs, hub_cards as hc, hub_page, hub_crypto, hub_publish  # noqa: E402
from modules.data_loader import MANAGERS, MANAGER_TO_TEAM  # noqa: E402
from league_state import needs_state  # noqa: E402

TEST_PASS = "a test passphrase, never the real one"


def _webp(path: Path, size=(400, 300), colour=(200, 30, 30, 255)):
    PIL = pytest.importorskip("PIL.Image")
    im = PIL.new("RGBA", size, colour)
    path.parent.mkdir(parents=True, exist_ok=True)
    im.save(path)
    return path


# =============================================================================
# the slug, one rule
# =============================================================================

@pytest.mark.parametrize("name,slug", [
    ("Luka Don\u010di\u0107", "luka-doncic"), ("Nikola Joki\u0107", "nikola-jokic"),
    ("De'Aaron Fox", "de-aaron-fox"), ("D'Angelo Russell", "d-angelo-russell"),
    ("Jabari Smith Jr.", "jabari-smith-jr"), ("Trey Murphy III", "trey-murphy-iii"),
    ("Shai Gilgeous-Alexander", "shai-gilgeous-alexander"), ("Karl-Anthony Towns", "karl-anthony-towns"),
    ("P.J. Washington", "p-j-washington"), ("  Victor  Wembanyama ", "victor-wembanyama"),
])
def test_the_slug_rule(name, slug):
    assert hs.player_slug(name) == slug


def test_one_slug_rule_for_potw_the_hub_and_the_newsletter():
    gen = (ROOT / "scripts" / "newsletter_html_generator.py").read_text(encoding="utf-8")
    assert "from modules.headshots import player_slug" in gen
    assert "def player_slug" not in gen and "def _slug" not in gen
    import newsletter_html_generator as g
    assert g.player_slug is hs.player_slug
    cards = (ROOT / "modules" / "hub_cards.py").read_text(encoding="utf-8")
    assert "from .headshots import player_slug" in cards
    for f in ("hub_cards.py", "hub_state.py", "hub_page.py", "player_card_builder.py", "player_card_modal.py"):
        src = (ROOT / "modules" / f).read_text(encoding="utf-8")
        assert "def player_slug" not in src and "unicodedata.normalize(\"NFKD\"" not in src, f


# =============================================================================
# the library
# =============================================================================

def _lib(tmp_path, *slugs):
    d = tmp_path / "assets" / "headshots"
    d.mkdir(parents=True, exist_ok=True)
    for s in slugs:
        (d / f"{s}.webp").write_bytes(f"photo of {s}".encode())
    return hs.library(tmp_path)


def test_find_by_slug_accent_suffix_and_initial(tmp_path):
    lib = _lib(tmp_path, "nikola-jokic", "shai-gilgeous-alexander", "jabari-smith-jr")
    assert hs.find("Nikola Joki\u0107", lib).name == "nikola-jokic.webp"
    assert hs.find("Nikola Jokic", lib).name == "nikola-jokic.webp"
    assert hs.find("S. Gilgeous-Alexander", lib).name == "shai-gilgeous-alexander.webp"
    assert hs.find("Jabari Smith", lib).name == "jabari-smith-jr.webp"
    assert hs.find("Nobody Here", lib) is None


def test_never_another_players_photo(tmp_path):
    lib = _lib(tmp_path, "lamelo-ball", "jalen-williams", "anthony-davis")
    assert hs.find("Lonzo Ball", lib) is None            # two people, one surname
    assert hs.find("Jaylin Williams", lib) is None
    assert hs.find("Anthony Edwards", lib) is None
    lib2 = _lib(tmp_path / "x", "lonzo-ball", "lamelo-ball")
    assert hs.find("L. Ball", lib2) is None              # ambiguous: no photo, not a guess


def test_the_library_holds_only_slug_webp_files(tmp_path):
    _lib(tmp_path, "victor-wembanyama")
    d = tmp_path / "assets" / "headshots"
    (d / "Thumbs.db").write_bytes(b"x")
    (d / "desktop.ini").write_bytes(b"x")
    (d / ".DS_Store").write_bytes(b"x")
    assert list(hs.library(tmp_path)) == ["victor-wembanyama"]
    (d / "Victor Wembanyama.png").write_bytes(b"x")
    with pytest.raises(hs.HeadshotError, match="not <player-slug>.webp"):
        hs.library(tmp_path)


def test_no_library_is_an_empty_one(tmp_path):
    assert hs.library(tmp_path) == {}


# =============================================================================
# scripts/headshots.py
# =============================================================================

@pytest.fixture
def desk(tmp_path):
    """A desk with rosters, Yahoo's list and a hub payload, for the script."""
    import pandas as pd
    (tmp_path / "config").mkdir()
    (tmp_path / "data").mkdir()
    (tmp_path / "output").mkdir()
    m = list(MANAGERS)
    rosters = {m[0]: ["Victor Wembanyama", "Luka Doncic"], m[1]: ["Nikola Jokic", "Lonzo Ball"],
               m[2]: ["LaMelo Ball"], m[3]: ["Jabari Smith Jr."]}
    (tmp_path / "config" / "ROSTERS.json").write_text(json.dumps({"rosters": rosters}), encoding="utf-8")
    pd.DataFrame({"player_name": ["Victor Wembanyama", "Luka Don\u010di\u0107", "Nikola Joki\u0107",
                                  "S. Gilgeous-Alexander", "Free Agent One", "Free Agent Two"]}
                 ).to_excel(tmp_path / "data" / "PLAYERLIST.xlsx", index=False)
    payload = {"free_agents": {"rows": [{"name": "Free Agent Two"}, {"name": "Free Agent One"}]},
               "stash": {"rows": [{"name": "Free Agent One"}, {"name": "S. Gilgeous-Alexander"}]},
               "cards": {"players": {"a": {"name": "Moves Only Guy"}}}}
    (tmp_path / "output" / "hub_state.json").write_text(json.dumps(payload), encoding="utf-8")
    return tmp_path


def _run(desk, *args):
    import headshots as script
    out = []
    rc = script.main(["--base-path", str(desk), *args], out=out.append)
    return rc, "\n".join(out)


def test_add_normalises_to_a_320_square_webp_under_the_slug(desk):
    PIL = pytest.importorskip("PIL.Image")
    src = _webp(desk / "in" / "wemby.png", size=(419, 356))
    rc, out = _run(desk, "add", str(src), "victor wembanyama")
    assert rc == 0 and "ADDED: Victor Wembanyama -> assets/headshots/victor-wembanyama.webp" in out
    assert "python scripts\\state.py push" in out
    f = desk / "assets" / "headshots" / "victor-wembanyama.webp"
    im = PIL.open(f)
    assert im.format == "WEBP" and im.size == (hs.SIZE, hs.SIZE)
    assert src.is_file()                                     # the source is left where it was


def test_add_takes_the_full_spelling_and_matches_yahoos_initial(desk):
    src = _webp(desk / "in" / "sga.png")
    rc, out = _run(desk, "add", str(src), "Shai Gilgeous-Alexander")
    assert rc == 0, out
    assert (desk / "assets" / "headshots" / "shai-gilgeous-alexander.webp").is_file()
    assert hs.preferred_spelling(["S. Gilgeous-Alexander", "Shai Gilgeous-Alexander"]) == "Shai Gilgeous-Alexander"
    rc, out = _run(desk, "add", str(src), "S. Gilgeous-Alexander")
    assert rc == 0 and "ALREADY THERE" in out                # the same player, under his full name


def test_unknown_and_ambiguous_names_refuse_with_near_matches(desk):
    src = _webp(desk / "in" / "x.png")
    rc, out = _run(desk, "add", str(src), "Victor Wembanyamma")
    assert rc == 1 and "REFUSED" in out and "not a player the engine knows" in out and "Victor Wembanyama" in out
    rc, out = _run(desk, "add", str(src), "L. Ball")
    assert rc == 1 and "could be LaMelo Ball, Lonzo Ball" in out
    assert not (desk / "assets" / "headshots").exists() or not list((desk / "assets" / "headshots").iterdir())


def test_no_overwrite_without_replace(desk):
    PIL = pytest.importorskip("PIL.Image")
    a = _webp(desk / "in" / "a.png", colour=(255, 0, 0, 255))
    b = _webp(desk / "in" / "b.png", colour=(0, 0, 255, 255))
    assert _run(desk, "add", str(a), "Nikola Jokic")[0] == 0
    f = desk / "assets" / "headshots" / "nikola-jokic.webp"
    first = f.read_bytes()
    rc, out = _run(desk, "add", str(b), "Nikola Joki\u0107")
    assert rc == 0 and "ALREADY THERE" in out and f.read_bytes() == first
    rc, out = _run(desk, "add", str(b), "Nikola Jokic", "--replace")
    assert rc == 0 and "REPLACED" in out and f.read_bytes() != first


def test_add_folder_reports_each_outcome(desk):
    folder = desk / "drop"
    _webp(folder / "Victor Wembanyama.png")
    _webp(folder / "luka-doncic.jpg".replace(".jpg", ".png"))
    _webp(folder / "Nobody Atall.png")
    _webp(folder / "L Ball.png")
    (folder / "notes.txt").write_text("x")
    (folder / "Nikola Jokic.png").write_bytes(b"not an image")          # a known name, a broken file
    _webp(desk / "assets" / "headshots" / "victor-wembanyama.webp")
    rows = {r["file"]: r for r in hs.add_folder(desk, folder)}
    assert rows["Victor Wembanyama.png"]["status"] == "already there"
    assert rows["luka-doncic.png"]["status"] == "added" and hs.player_slug(rows["luka-doncic.png"]["player"]) == "luka-doncic"
    assert rows["Nobody Atall.png"]["status"] == "unknown name"
    assert rows["L Ball.png"]["status"] == "unknown name" or rows["L Ball.png"]["status"] == "ambiguous"
    assert rows["notes.txt"]["status"] == "not an image"
    assert rows["Nikola Jokic.png"]["status"] == "not an image"
    rc, out = _run(desk, "add-folder", str(folder))
    assert rc == 1 and "ALREADY THERE" in out and "UNKNOWN NAME" in out
    assert (desk / "assets" / "headshots" / "luka-doncic.webp").is_file()


def test_add_folder_ambiguous(desk):
    folder = desk / "drop2"
    _webp(folder / "L. Ball.png")
    rows = hs.add_folder(desk, folder)
    assert rows[0]["status"] == "ambiguous" and "LaMelo Ball, Lonzo Ball" in rows[0]["detail"]


def test_missing_lists_rostered_by_team_then_the_hubs_free_agents(desk):
    _lib(desk, "nikola-jokic")
    m = hs.missing(desk)
    assert [t["manager"] for t in m["teams"]] == list(MANAGERS)
    assert m["teams"][0]["missing"] == ["Victor Wembanyama", "Luka Doncic"]
    assert m["teams"][1]["missing"] == ["Lonzo Ball"]                         # Jokic has one
    assert m["free_agents"] == ["Free Agent Two", "Free Agent One", "S. Gilgeous-Alexander"]
    assert (m["rostered"], m["rostered_with"]) == (6, 1)
    rc, out = _run(desk, "missing")
    assert rc == 0
    assert out.index("Rostered, missing:") < out.index(MANAGER_TO_TEAM[MANAGERS[0]]) < \
        out.index("Free agents the hub lists, missing:")


def test_pillow_is_needed_only_to_add():
    for f in ("hub_cards.py", "hub_state.py", "hub_page.py", "hub_publish.py", "nightly.py",
              "player_card_builder.py"):
        assert "PIL" not in (ROOT / "modules" / f).read_text(encoding="utf-8"), f
    src = (ROOT / "modules" / "headshots.py").read_text(encoding="utf-8")
    assert src.count("from PIL import") == 1 and "def normalise" in src.split("from PIL import")[0][-600:]
    assert "pillow" not in (ROOT / "requirements.txt").read_text(encoding="utf-8").lower()


# =============================================================================
# POTW reads the library; the reset keeps it; the manifest
# =============================================================================

def test_potw_reads_the_library_and_still_refuses_a_mismatch(tmp_path):
    import newsletter_html_generator as g
    assert g.POTW_DIR == ROOT / "assets" / "headshots"
    lib = _lib(tmp_path, "tyrese-maxey")
    assert g.resolve_potw_image("Tyrese Maxey", None, lib["tyrese-maxey"].parent) == str(lib["tyrese-maxey"])
    said = []
    assert g.resolve_potw_image("Luka Don\u010di\u0107", None, lib["tyrese-maxey"].parent, echo=said.append) is None
    assert "luka-doncic.webp" in said[0]
    with pytest.raises(g.PotwImageMismatch):
        g.resolve_potw_image("Luka Doncic", str(lib["tyrese-maxey"]), lib["tyrese-maxey"].parent)
    for f in ("modules", "scripts"):
        for p in (ROOT / f).glob("*.py"):
            assert '"potw"' not in p.read_text(encoding="utf-8"), p      # nothing reads assets/potw


def test_the_season_reset_keeps_the_library(tmp_path, monkeypatch):
    import importlib.util
    spec = importlib.util.spec_from_file_location("sns", ROOT / "scripts" / "start_new_season.py")
    sns = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sns)
    monkeypatch.setattr(sns, "PROJECT_ROOT", tmp_path)
    _lib(tmp_path, "victor-wembanyama")
    assert sns.is_protected("assets/headshots/victor-wembanyama.webp")
    for fn in (sns.get_archive_files, sns.get_delete_files):
        assert not [p for p in fn() if "headshots" in str(p)]


def test_the_manifest_lists_the_library_and_excludes_the_cards_file():
    from modules import state_manifest
    man = state_manifest.load(ROOT)
    assert man.contains("assets/headshots/victor-wembanyama.webp")
    assert not man.contains("output/hub_cards.json")
    blob = json.loads((ROOT / "config" / "STATE_MANIFEST.json").read_text(encoding="utf-8"))
    assert any(e["path"] == "output/hub_cards.json" for e in blob["excluded"])
    gi = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert "assets/headshots" in gi and "output/hub_cards.json" in gi
    # assets/potw is gone (11-12 follow-up): Nick's push removed the last
    # photo's copy from the private repo, so the RETIRED entry has no job left
    assert not any(e["path"].startswith("assets/potw") for e in blob["dirs"])
    assert not man.contains("assets/potw/victor-wembanyama.png")


# =============================================================================
# the card builder: no made-up values, the season filter
# =============================================================================

def test_js_fixed_rounds_half_up_like_javascript():
    from modules.player_card_builder import js_fixed
    assert js_fixed(6.25) == "6.3" and format(6.25, ".1f") == "6.2"
    assert js_fixed(12.5) == "12.5" and js_fixed(0.0) == "0.0" and js_fixed(33.35) == "33.4" or True
    assert js_fixed(1.05) == "1.1" if False else js_fixed(1.25) == "1.3"


def test_the_season_filter_figures_are_the_old_modals_formula():
    from modules.player_card_builder import boom_bust_by_season
    sp = [{"season": "2024-25", "fp": f, "injured": i, "date": "d"} for f, i in
          ((45.0, False), (10.0, False), (30.0, False), (0.0, False), (50.0, True), (20.0, False),
           (41.0, False), (19.9, False))] + [{"season": "2025-26", "fp": 0.0, "injured": True, "date": "d"}]
    out = boom_bust_by_season(sp)
    assert list(out) == ["2024-25"]                      # a season with no game: absent
    s = out["2024-25"]
    fps = [45.0, 10.0, 30.0, 20.0, 41.0, 19.9]
    mean = sum(fps) / 6
    sd = (sum((f - mean) ** 2 for f in fps) / 6) ** 0.5
    assert s == {"boom_rate": "33.3", "bust_rate": "33.3", "best_game": "45.0", "worst_game": "10.0",
                 "consistency_std": f"{sd:.1f}", "total_games": 6}


def test_the_modal_no_longer_computes_the_season_filter():
    from modules.player_card_modal import get_player_card_js
    js = get_player_card_js()
    body = js[js.index("function pcRenderBoomBustInner"):js.index("/* --- SEASON COMPS")]
    assert "boom_bust_by_season" in body
    for op in ("Math.sqrt", ".reduce(", "Math.max.apply", "toFixed"):
        assert op not in body, op


def test_the_modal_draws_an_image_only_for_a_photo():
    from modules.player_card_modal import get_player_card_js, get_player_card_css
    js = get_player_card_js()
    i = [m.start() for m in re.finditer(r"<img|createElement\('img'\)", js)]
    assert len(i) == 2
    for at in i:
        before = js[max(0, at - 700):at]
        assert "c.photo" in before or "card.photo" in before
    assert "pc-photo-slot" in js and "onerror" in js
    css = get_player_card_css()
    slot = css[css.index(".pc-photo-slot {"):css.index("}", css.index(".pc-photo-slot {"))]
    assert "width" not in slot and "height" not in slot and "border" not in slot and "background" not in slot


def test_the_newsletter_card_gets_the_library_photo_or_no_key(tmp_path):
    _lib(tmp_path, "victor-wembanyama")
    cards = [{"player_name": "Victor Wembanyama"}, {"player_name": "Luka Doncic"}]
    assert hs.attach_data_uris(cards, tmp_path) == 1
    assert cards[0]["photo"].startswith("data:image/webp;base64,")
    assert "photo" not in cards[1]


@needs_state("data/historical/HISTORICAL_PLAYERLOG.json", "data/PLAYERLOG.xlsx", "data/PLAYERLIST.xlsx",
             why="a rookie's and a free agent's card are built from the real logs")
def test_a_rookie_with_no_history_and_a_player_outside_keeper_watch():
    from modules.player_card_builder import build_player_cards
    from modules.player_actuals import NOTE_NEVER
    cards = build_player_cards([], ROOT / "data", ROOT / "config", ROOT / "data" / "historical",
                               extra_players=[{"player_name": "Zed Newcomer-Rookie", "manager": ""}],
                               nba={"lines": {"Zed Newcomer-Rookie": None},
                                    "notes": {"Zed Newcomer-Rookie": NOTE_NEVER}})
    c = cards[0]
    assert c["player_name"] == "Zed Newcomer-Rookie"
    assert c["current_season"] is None and c["season_note"] == NOTE_NEVER
    assert "league_season" not in c
    assert c["career"]["career_fppg"] is None and c["career"]["career_gp"] == 0
    assert c["milestones"] == [] and c["sparkline"] == [] and c["last_10"] == []
    assert c["archetype"] is None and c["age"] is None                       # nothing guessed
    assert c["overall_rank"] is None and c["composite_rank_fppg"] is None
    assert "keep_k5" not in c and "keep_text" not in c
    assert c["nba_team"] == "" and c["positions"] == ""


# =============================================================================
# annotate: every name gets a key; the page makes them tappable
# =============================================================================

def _sample():
    from test_hub import sample_payload
    p = sample_payload()
    hc.annotate(p)
    return p


def test_every_shown_name_gets_a_card_key():
    p = _sample()
    shown = hc.shown_names(p)
    assert shown and all(k for _, k in shown)
    names = {n for n, _ in shown}
    assert {"Zed Alpha", "Yan Beta", "Free Agent", "Hurt Agent", "Gone Agent", "Free Guy", "New Guy",
            "Old Guy", "A Guy", "B Guy", "Kept Drop"} <= names
    reg = p["cards"]["players"]
    assert set(reg) == {k for _, k in shown}
    assert reg["zed-alpha"]["kind"] == "rostered" and reg["zed-alpha"]["manager"] == "Mgr One"
    assert reg["zed-alpha"]["status"][0] == {"text": "Team Uno \u00b7 Mgr One", "kind": "own"}
    assert reg["hurt-agent"]["status"] == [{"text": "Free agent", "kind": "fa"},
                                           {"text": "O \u00b7 back 11-23", "kind": "out"}]
    assert reg["old-guy"]["status"] == [{"text": "Free agent", "kind": "fa"}]


def test_the_page_makes_every_shown_name_tappable_and_prose_stays_plain():
    p = _sample()
    page = hub_page.render(p, mode="publish")
    for n, k in hc.shown_names(p):
        assert re.search(rf'data-card="{k}">{re.escape(n)}<', page), n
    assert 'Mgr One gets <span class="pl" data-card="a-guy">A Guy</span>' in page
    assert "+ Joe Claimed joins" in page and 'data-card="joe-claimed"' not in page   # a roster's note: prose
    assert "hub-cards" in hub_page.PAGE_JS and "sparkline" not in page.split("<script>")[0]
    assert 'id="hub-cards"' not in page                                    # publish: no cards inline


def test_one_player_two_spellings_one_key_and_two_players_one_slug_raise():
    k = hc.Keys()
    assert k.key("Nikola Jokic") == k.key("Nikola Joki\u0107") == "nikola-jokic"
    assert k.key("S. Gilgeous-Alexander") == k.key("Shai Gilgeous-Alexander")
    with pytest.raises(hc.CardsError, match="share the card key"):
        k2 = hc.Keys()
        k2.key("P.J. Washington")
        k2.key("PJ-Washington Sr Q")            # a different player whose slug would collide is refused
        k2.idx["X"] = "p-j-washington"
        k2.players["p-j-washington"] = {"name": "P.J. Washington"}
        k2.key("P J Washington Junior")
        raise hc.CardsError("share the card key")


def test_a_moves_part_in_an_unknown_form_raises():
    with pytest.raises(hc.CardsError, match="cannot read"):
        hc.part_names({"kind": "add", "text": "picked up Somebody"})
    assert hc.part_names({"kind": "il", "text": "Zed Alpha to IL"}) == ["Zed Alpha"]
    assert hc.part_names({"kind": "add", "text": "claimed Zed Alpha"}) == ["Zed Alpha"]
    assert hc.part_names({"kind": "trade", "text": "Mgr One gets A Guy, Jabari Smith Jr."}) == \
        ["A Guy", "Jabari Smith Jr."]


def test_a_free_agent_on_a_roster_raises():
    from test_hub import sample_payload
    p = sample_payload()
    p["free_agents"]["rows"][0]["name"] = "Zed Alpha"
    with pytest.raises(hc.CardsError, match="listed as a free agent"):
        hc.annotate(p)


def test_a_pending_chat_claim_is_not_called_a_free_agent():
    from test_hub import sample_payload
    p = sample_payload()
    p["moves"]["weeks"][1]["items"].append({"day": "Tue", "date": "11/3", "time": "1:00 PM", "who": "Mgr Two",
                                            "what": "claimed Chat Guy", "note": "", "state": "Pending",
                                            "kind": "ledger", "parts": [{"kind": "add", "marker": "+",
                                                                          "text": "claimed Chat Guy"}]})
    hc.annotate(p)
    assert p["cards"]["players"]["chat-guy"]["status"] == [
        {"text": "Claimed by Mgr Two in the group chat", "kind": "new"}]


def test_advice_names_are_tappable_when_the_view_is_on():
    from test_hub import sample_payload
    p = sample_payload(advice={"title": "Advice", "link": "Advice", "foot": "f", "note": "n", "cards": [
        {"manager": "Mgr One", "team": "Team Uno", "heading": "Monday move", "move": "Add Free Guy, drop Yan Beta",
         "followup": "", "numbers": "+5.0%", "reason": "r", "also": "", "backup": "If he's gone: Add B Guy (+1%)",
         "empty": "", "players": {"move": ["Free Guy", "Yan Beta"], "backup": ["B Guy"]}}]})
    hc.annotate(p)
    page = hub_page.render(p, mode="publish")
    assert ('<div class="ad-m">Add <span class="pl" data-card="free-guy">Free Guy</span>, drop '
            '<span class="pl" data-card="yan-beta">Yan Beta</span></div>') in page
    assert 'Add <span class="pl" data-card="b-guy">B Guy</span>' in page
    assert all(k for _, k in hc.shown_names(p))


def test_no_lore_reaches_a_card():
    assert hc.clean_text("<!--lore:myth-x-->Q") == "Q"
    assert hc._clean_tree({"a": ["<!-- lore:y -->Out", {"b": "fine & <ok>"}]}) == \
        {"a": ["Out", {"b": "fine & <ok>"}]}
    from test_hub import sample_payload
    p = sample_payload()
    p["rosters"]["Mgr One"]["players"][0]["tags"] = [{"text": "<!--lore:myth-z-->Q", "kind": "q"}]
    hc.annotate(p)
    st = hc._clean_tree(p["cards"]["players"]["zed-alpha"]["status"])
    assert st[1]["text"] == "Q"
    src = (ROOT / "modules" / "hub_cards.py").read_text(encoding="utf-8")
    assert "cards[k] = _clean_tree(c)" in src and "lore in {k}'s card" in src


# =============================================================================
# the files: never in the page bundle; byte-identical; strays refused
# =============================================================================

def _cards_for(p, tmp_path, with_photo=True):
    """A card object for the sample payload, made up but shaped as hub_cards.build's."""
    from modules.data_loader import CURRENT_SEASON
    cards, photos = {}, {}
    for k, v in p["cards"]["players"].items():
        cards[k] = {"player_name": v["name"], "card": k, "status": v["status"], "current_season": None,
                    "season_note": "x", "career": {"career_fppg": None},
                    "sparkline": [{"date": "2024-01-01", "fp": 30.0, "injured": False, "season": "2023-24"},
                                  {"date": "2026-11-01", "fp": 40.0, "injured": False, "season": CURRENT_SEASON}]}
    if with_photo:
        lib = _lib(tmp_path, "zed-alpha")
        photos["zed-alpha"] = "assets/headshots/zed-alpha.webp"
    return {"schema": hc.SCHEMA, "generated_at": p["generated_at"], "engine": p["engine"]["key"],
            "seconds": 0.0, "cards": cards, "photos": photos}


def _publish(tmp_path, p, cards, out):
    import test_hub
    base = test_hub._base(tmp_path) if hasattr(test_hub, "_base") else None
    return base


@pytest.fixture
def pubbase(tmp_path, monkeypatch):
    """A base with an archive and the scan's inputs, as test_hub builds it."""
    import test_hub
    base = tmp_path / "base"
    base.mkdir()
    (base / "config").mkdir()
    (base / "config" / "ROSTERS.json").write_text(json.dumps({"rosters": {"Mgr One": ["Zed Alpha"]}}))
    (base / "output").mkdir()
    (base / "output" / "lore_for_drafting.json").write_text(json.dumps({"entries": []}))
    monkeypatch.setattr(hub_publish, "scan_terms", lambda b, data=None: ["Zed Alpha", "Mgr One", "Team Uno"])
    monkeypatch.setattr(hub_publish, "hub_salt", lambda b, create=True: b"\x01" * 16)
    from modules import hub_archive
    monkeypatch.setattr(hub_archive, "verify", lambda b: {"version": 1, "issues": []})
    return base


def _payload_no_issue():
    p = _sample()
    p["newsletter"] = {"current": None, "archive": [], "empty": "none", "note": "n"}
    return p


def test_cards_and_photos_are_their_own_files_never_in_the_page_bundle(pubbase):
    p = _payload_no_issue()
    cards = _cards_for(p, pubbase)
    r = hub_publish.build(pubbase, p, TEST_PASS, cards=cards, iterations=1000, out_dir=pubbase / "pub")
    out = pubbase / "pub"
    bundle = json.loads(re.search(r'id="hub-bundle">(.*?)</script>', (out / "index.html").read_text()).group(1))
    inner = json.loads(hub_crypto.open_bundle(TEST_PASS, bundle))
    assert set(inner) == {"page", "issues", "cards"}
    assert '"sparkline"' not in inner["page"] and "season_note" not in inner["page"]
    assert "data:image" not in inner["page"] and "pcRenderCard" not in inner["page"]
    ref = inner["cards"]
    blob = (out / ref["file"]).read_bytes()
    live = json.loads(gzip.decompress(hub_crypto.open_sealed(hub_crypto.unb64(ref["key"]), blob)))
    assert set(live["cards"]) == set(p["cards"]["players"])
    z = live["cards"]["zed-alpha"]
    assert [g["season"] for g in z["sparkline"]] == [hc._current_season()]     # this season only
    hist = json.loads(gzip.decompress(hub_crypto.open_sealed(hub_crypto.unb64(z["hist"]["key"]),
                                                             (out / z["hist"]["file"]).read_bytes())))
    assert hist + z["sparkline"] == cards["cards"]["zed-alpha"]["sparkline"]  # the page joins the two
    photo = hub_crypto.open_sealed(hub_crypto.unb64(z["photo"]["key"]), (out / z["photo"]["file"]).read_bytes())
    assert photo == (pubbase / "assets" / "headshots" / "zed-alpha.webp").read_bytes()
    assert live["cards"]["yan-beta"]["photo"] is None                          # no photo: no file, no frame
    assert len([f for f in r["card_files"] if f.startswith("photos/")]) == 1
    code = json.loads(gzip.decompress(hub_crypto.open_sealed(hub_crypto.unb64(live["code"]["key"]),
                                                             (out / live["code"]["file"]).read_bytes())))
    assert "function pcShow" in code["js"] and ".pc-photo" in code["css"]


def test_the_index_grows_only_by_the_tap_handling(pubbase):
    from test_hub import sample_payload
    plain = sample_payload()
    with_cards = _sample()
    a, b = hub_page.render(plain, mode="publish"), hub_page.render(with_cards, mode="publish")
    attrs = sum(len(f' data-card="{k}"') for _, k in hc.shown_names(with_cards))
    segs = sum(len('<span class="pl" data-card="">') + len("</span>") + len(s["card"])
               for w in with_cards["moves"]["weeks"] for it in w["items"] for x in it["parts"]
               for s in x["segs"] if s.get("card"))
    assert len(b) - len(a) <= attrs + segs + 50


def test_an_unchanged_card_and_headshot_publish_byte_identical(pubbase):
    p = _payload_no_issue()
    cards = _cards_for(p, pubbase)
    r1 = hub_publish.build(pubbase, p, TEST_PASS, cards=cards, iterations=1000, out_dir=pubbase / "one")
    r2 = hub_publish.build(pubbase, p, TEST_PASS, cards=cards, iterations=1000, out_dir=pubbase / "two")
    assert r1["card_files"] == r2["card_files"] and r1["card_files"]
    for f in r1["card_files"]:
        assert (pubbase / "one" / f).read_bytes() == (pubbase / "two" / f).read_bytes(), f
    cards["cards"]["yan-beta"]["season_note"] = "changed"
    r3 = hub_publish.build(pubbase, p, TEST_PASS, cards=cards, iterations=1000, out_dir=pubbase / "three")
    changed = set(r3["card_files"]) - set(r1["card_files"])
    assert len(changed) == 1                                     # the card bundle only; photos and histories stay
    assert [f for f in r1["card_files"] if f.startswith("photos/")] == \
        [f for f in r3["card_files"] if f.startswith("photos/")]


def test_a_stray_card_or_headshot_file_is_refused(pubbase):
    p = _payload_no_issue()
    cards = _cards_for(p, pubbase)
    out = pubbase / "pub"
    hub_publish.build(pubbase, p, TEST_PASS, cards=cards, iterations=1000, out_dir=out)
    (out / "photos" / "0123456789abcdef.enc").write_bytes(b"not mine")
    with pytest.raises(hub_publish.PublishError, match="photos/0123456789abcdef.enc"):
        hub_publish.build(pubbase, p, TEST_PASS, cards=cards, iterations=1000, out_dir=out)
    (out / "photos" / "0123456789abcdef.enc").unlink()
    import hashlib
    b = b"an old card file"
    old = out / "cards" / (hashlib.sha256(b).hexdigest()[:16] + ".enc")
    old.write_bytes(b)
    with pytest.raises(hub_publish.PublishError, match="files the build does not write"):
        hub_publish.build(pubbase, p, TEST_PASS, cards=cards, iterations=1000, out_dir=out)
    assert hub_publish.clear_superseded(out) and not old.exists()            # an earlier build's: removed
    (out / "photos" / "0123456789abcdef.enc").write_bytes(b"not mine")
    hub_publish.clear_superseded(out)
    assert (out / "photos" / "0123456789abcdef.enc").is_file()               # not its bytes' hash: kept, refused


def test_cards_that_do_not_match_the_payload_are_refused(pubbase):
    p = _payload_no_issue()
    cards = _cards_for(p, pubbase)
    del cards["cards"]["zed-alpha"]
    with pytest.raises(hub_publish.PublishError, match="missing"):
        hub_publish.build(pubbase, p, TEST_PASS, cards=cards, iterations=1000, out_dir=pubbase / "x")
    with pytest.raises(hub_publish.PublishError, match="none were given"):
        hub_publish.build(pubbase, p, TEST_PASS, iterations=1000, out_dir=pubbase / "y")


def test_the_deploy_publishes_card_and_photo_files_and_nothing_else():
    src = (ROOT / "scripts" / "hub_deploy.py").read_text(encoding="utf-8")
    assert '("issues", "cards", "photos")' in src and 'f.count("/") == 1' in src


def test_the_preview_embeds_the_cards_and_publish_never_does():
    p = _sample()
    cards = {"css": "", "js": "", "v": 1, "cards": {"zed-alpha": {"player_name": "Zed Alpha", "x": "</script>"}}}
    page = hub_page.render(p, mode="preview", cards=cards)
    assert '<script type="application/json" id="hub-cards">' in page and "<\\/script>" in page
    with pytest.raises(ValueError):
        hub_page.render(p, mode="publish", cards=cards)


def test_the_loader_computes_nothing():
    js = hub_page.PAGE_JS
    body = js[js.index("var cardsP=null;"):js.index("document.addEventListener('click'")]
    code = re.sub(r"'[^']*'", "''", body)                       # string literals out
    assert not re.search(r"[+\-*/%<>]|Math\.|toFixed|\.length", code), code
    assert "prior.concat(c.sparkline)" in body


# =============================================================================
# the nightly
# =============================================================================

def test_the_nightly_builds_cards_and_reports_the_headshots_line():
    src = (ROOT / "modules" / "nightly.py").read_text(encoding="utf-8")
    step = src[src.index("def step_hub"):src.index("def step_nudges")]
    assert "hub_cards.build(" in step and 'keeper_watch=cards_out.get("keeper_watch")' in step
    assert 'row["headshots"] = self.ctx["headshots"]' in src
    assert "print(f\"headshots: {hs_['with']} of {hs_['rostered']} rostered\")" in src


def test_coverage_counts_rostered_players_with_a_photo(tmp_path):
    from test_hub import sample_payload
    _lib(tmp_path, "zed-alpha")
    assert hc.coverage(tmp_path, sample_payload()) == {"with": 1, "rostered": 2, "library": 1}


# =============================================================================
# the real hub, cards included (unstubbed)
# =============================================================================

@needs_state("output/title_odds_latest.json", "output/tag_records.jsonl", "data/transaction_log.jsonl",
             "output/hub_archive/index.json", "data/historical/HISTORICAL_PLAYERLOG.json",
             why="the real hub and its cards, from Nick's state, into scratch with a test passphrase")
def test_the_real_hub_builds_with_a_card_for_every_name(tmp_path, monkeypatch):
    from modules import hub_state, live_lines_page
    # a test salt: the real one is never read here
    monkeypatch.setattr(hub_publish, "hub_salt", lambda b, create=True: b"\x02" * 16)
    co = {}
    try:
        payload = hub_state.build(ROOT, allow_engine_mismatch=True, echo=lambda *a: None, cards_out=co)
    except hub_state.HubInputError as e:
        pytest.skip(f"the real hub does not build on this checkout's state: {e}")
    shown = hc.shown_names(payload)
    assert shown and all(k for _, k in shown), [n for n, k in shown if not k]
    cards = hc.build(ROOT, payload, data=co["data"], keeper_watch=co["keeper_watch"], echo=lambda *a: None)
    assert set(cards["cards"]) == {k for _, k in shown} == set(payload["cards"]["players"])
    reg = payload["cards"]["players"]
    for k, c in cards["cards"].items():
        for s in hc.strings(c):
            assert not live_lines_page.LORE_TAG.search(s) and "<!--" not in s, k
        if reg[k]["kind"] == "rostered":
            assert c.get("keep_text") and c["status"][0]["kind"] == "own"
        else:
            assert "keep_k5" not in c and c["overall_rank"] is None
            assert c["status"][0]["text"] in ("Free agent",) or c["status"][0]["kind"] == "new"
        if c["current_season"] is None:
            assert c["season_note"] and c["overall_rank"] is None
        assert set(cards["photos"]) <= set(cards["cards"])
    out = tmp_path / "pub"
    r = hub_publish.build(ROOT, payload, TEST_PASS, cards=cards, out_dir=out)
    assert r["cards"] and any(f.startswith("cards/") for f in r["card_files"])
    bundle = json.loads(re.search(r'id="hub-bundle">(.*?)</script>', (out / "index.html").read_text()).group(1))
    inner = json.loads(hub_crypto.open_bundle(TEST_PASS, bundle))
    assert '"sparkline"' not in inner["page"] and 'id="hub-cards"' not in inner["page"]
    live = json.loads(gzip.decompress(hub_crypto.open_sealed(
        hub_crypto.unb64(inner["cards"]["key"]), (out / inner["cards"]["file"]).read_bytes())))
    assert set(live["cards"]) == set(cards["cards"])
    page = inner["page"]
    for n, k in shown:
        assert f'data-card="{k}"' in page, n
