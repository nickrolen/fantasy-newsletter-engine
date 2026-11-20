"""5a: the switch-over prep (claude/HANDOFF_5A_SWITCHOVER_PREP_2026-11-19.md s.6).

The switch (config hub.version), the new hub's real publisher and its shell
(gzip, CSP, the old-browser message), every lazy part encrypted by content,
the plaintext scan's negative controls, the payload's side file, parity (the
banners, the header, the current hub's deep links) and the publish check.
Synthetic where the rule is logic; one real, unstubbed test on today's state
(it skips without it). Throwaway passphrases and salts only."""

import copy
import gzip
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

import league_state                                    # noqa: E402
import test_hub as T1
import test_hub_v2 as T2

from modules import hub_version, hub_page, hub_publish, hub_crypto, hub_archive
from modules.hub_v2 import publish as v2pub, publish_check as pc, data as v2data

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
PASS = T2.PASS
GEN = T2.GEN
SALT = b"\x05" * 16

# the live hub's shell before 5a (HEAD 61ff888): SHELL_JS and shell_html('{"v":1}')
V1_SHELL_JS_SHA16 = "654e5a0aeb0d723c"
V1_SHELL_SHA = "a38b5e8c2554ff72a70f8b943674a981fdf5fbbd51f626724c6191c1345a2d1f"


def _fixed_iv(monkeypatch):
    """Every fresh IV and salt the same bytes: two builds of one payload are
    then byte-comparable (index.html included)."""
    monkeypatch.setattr(hub_crypto, "secrets", SimpleNamespace(token_bytes=lambda n: b"\x07" * n))


def _version(monkeypatch, v):
    monkeypatch.setattr(hub_version, "_config", lambda: {"hub": {"version": v}})


def _v2_world(tmp_path, keep_cards: bool = False):
    """The synthetic new hub with a real archived issue (every link to the
    made-up week-8 file points at it) and no player cards (the check would
    otherwise ask for their files)."""
    e = T2._archive(tmp_path)
    p = json.loads(json.dumps(T2.synth_payload()).replace("week08-aaaaaaaaaaaa.enc", e["enc"]))
    if not keep_cards:
        p["cards"] = None
    return p


def _files(d: Path) -> dict:
    return {q.relative_to(d).as_posix(): q.read_bytes() for q in sorted(d.rglob("*")) if q.is_file()}


# =============================================================================
# the switch
# =============================================================================

def test_hub_version_is_required_and_one_of_two():
    for cfg in ({}, {"hub": {}}, {"hub": {"version": "v3"}}, {"hub": {"version": None}}, {"hub": {"version": "V2"}}):
        with pytest.raises(hub_version.HubVersionError):
            hub_version.from_config(cfg)
    assert hub_version.from_config({"hub": {"version": "v1"}}) == "v1"
    assert hub_version.from_config({"hub": {"version": "v2"}}) == "v2"


def test_the_engines_config_names_a_hub():
    # 5a ships "v1"; Nick's flip to "v2" (the runbook) must not fail the suite
    assert hub_version.version() in hub_version.VERSIONS
    cfg = json.loads((ROOT / "config" / "league_config.json").read_text(encoding="utf-8"))
    assert cfg["hub"]["version"] == hub_version.version() and "_version" in cfg["hub"]


def test_the_live_shell_is_byte_for_byte_as_before():
    assert hashlib.sha256(hub_page.SHELL_JS.encode()).hexdigest()[:16] == V1_SHELL_JS_SHA16
    assert hashlib.sha256(hub_page.shell_html('{"v":1}').encode()).hexdigest() == V1_SHELL_SHA
    assert hub_page.shell_html('{"v":1}') == hub_page.shell_html('{"v":1}', "v1")
    assert hub_page.SHELL_JS == hub_page._SJ_HEAD + hub_page._SJ_OPEN_V1 + hub_page._SJ_BODY + hub_page._SJ_START_V1


def test_the_new_shell_gunzips_allows_its_fonts_and_names_an_old_browser():
    s = hub_page.shell_html('{"v":1}', "v2")
    csp = re.search(r'Content-Security-Policy" content="([^"]+)"', s).group(1)
    assert csp.endswith("img-src data: blob:; font-src data:") and "default-src 'none'" in csp
    assert "DecompressionStream('gzip')" in s and "B.z!=='gzip'" in s
    assert hub_page.OLD_BROWSER_TEXT == "This browser is too old to open the hub. Update iOS or Chrome."
    assert hub_page.OLD_BROWSER_TEXT in s and "Wrong passphrase." in s
    assert hub_page._SJ_BODY_A in hub_page.SHELL_JS_V2 and hub_page._SJ_BODY_B in hub_page.SHELL_JS_V2   # the same loader, HUB, key
    assert "hub-key-v1" in s                                         # a phone's remembered key keeps working
    with pytest.raises(ValueError):
        hub_page.shell_html('{"v":1}', "v3")


def test_build_hub_run_follows_the_switch(monkeypatch, tmp_path):
    import build_hub
    calls = []
    monkeypatch.setattr(build_hub, "run_v2_publish", lambda base, **k: calls.append(("v2", k)) or {"rc": 0})
    _version(monkeypatch, "v2")
    assert build_hub.run(tmp_path, preview_only=True) == {"rc": 0} and calls[0][0] == "v2"
    _version(monkeypatch, "v1")
    with pytest.raises(Exception) as e:              # v1 goes on to the current hub's build (no payload here)
        build_hub.run(tmp_path, preview_only=True)
    assert "hub_state.json" in str(e.value) and len(calls) == 1
    monkeypatch.setattr(hub_version, "_config", lambda: {"hub": {}})
    with pytest.raises(hub_version.HubVersionError):
        build_hub.run(tmp_path, preview_only=True)


def test_v1_to_v2_to_v1_publishes_the_old_page_byte_identical(tmp_path, monkeypatch):
    """The same publish directory, v1 -> v2 -> v1: the second v1 build is the
    first byte for byte, and nothing of the new hub's is left."""
    _fixed_iv(monkeypatch)
    p1 = T1.publish_world(tmp_path)
    p2 = _v2_world(tmp_path)                         # the archive holds both payloads' issues from the start
    p2["newsletter"]["archive"] = [dict(p1["newsletter"]["current"])]
    out = hub_publish.publish_dir(tmp_path)
    hub_publish.build(tmp_path, p1, PASS, terms=T1.TERMS + T2.TERMS, iterations=1000, now=T1.GEN)
    first = _files(out)
    # the switch to v2: the new hub, live, into the same directory
    v2pub.clear_superseded(out)
    rep = v2pub.build(tmp_path, p2, PASS, salt=hub_publish.hub_salt(tmp_path), out_dir=None, live=True,
                      iterations=1000, terms=T1.TERMS + T2.TERMS, now=GEN, pictures=[])
    assert rep["live"] and rep["dir"] == str(out)
    mid = _files(out)
    assert mid["index.html"] != first["index.html"] and any(f.startswith("parts/") for f in mid)
    for f in first:                                  # the issues stay, byte for byte
        if f.startswith("issues/"):
            assert mid[f] == first[f]
    # and back
    hub_publish.clear_superseded(out)
    hub_publish.build(tmp_path, p1, PASS, terms=T1.TERMS + T2.TERMS, iterations=1000, now=T1.GEN)
    assert _files(out) == first


def test_v2_refuses_a_payload_whose_new_keys_or_ratings_failed():
    good = {"v2": {"ratings": {"error": None}}, "v2_error": None}
    hub_version.check_v2_whole(good)
    for bad, why in (({"v2": None, "v2_error": {"stage": "league", "error": "KeyError: x"}}, "league"),
                     ({"v2": None, "v2_error": None}, "no new-hub keys"),
                     ({"v2": {"ratings": {"error": "RatingsInputError: y"}}, "v2_error": None}, "ratings failed")):
        with pytest.raises(hub_version.V2HubFailed, match=why):
            hub_version.check_v2_whole(bad)
        assert hub_version.v2_failures(bad)


def test_run_v2_publish_refuses_before_writing_anything(tmp_path, monkeypatch):
    import build_hub
    p = T2.synth_payload()
    p["v2"], p["v2_error"] = None, {"stage": "market", "error": "ValueError: z"}
    (tmp_path / "config").mkdir()
    shutil.copyfile(ROOT / "config" / "STATE_MANIFEST.json", tmp_path / "config" / "STATE_MANIFEST.json")
    sp = tmp_path / "s" / "state.json"
    sp.parent.mkdir()
    sp.write_text(json.dumps(p), encoding="utf-8")
    with pytest.raises(hub_version.V2HubFailed, match="market"):
        build_hub.run_v2_publish(tmp_path, state=sp, out_dir=tmp_path / "o")
    assert not (tmp_path / "o").exists()
    _version(monkeypatch, "v2")
    assert build_hub.main(["--base-path", str(tmp_path), "--state", str(sp), "--out-dir", str(tmp_path / "o")]) == 1


def _nightly_hub(monkeypatch, tmp_path, version, payload):
    import build_hub
    from modules import nightly, hub_state, hub_cards
    _version(monkeypatch, version)
    monkeypatch.setattr(hub_state, "build", lambda base, **k: payload)
    wrote = []
    monkeypatch.setattr(hub_state, "write", lambda base, p: wrote.append("payload"))
    monkeypatch.setattr(build_hub, "run", lambda base, **k: {"rc": 0, "cards_error": None, "payload": None,
                                                             "report": None})
    monkeypatch.setattr(hub_cards, "build", lambda base, payload, **k: {"cards": {}, "seconds": 0.0})
    monkeypatch.setattr(hub_cards, "write", lambda base, obj: None)
    monkeypatch.setattr(hub_cards, "coverage", lambda base, payload: {"with": 0, "rostered": 0, "library": 0})
    run = nightly.Run(tmp_path, "refresh", now=T2.GEN, cause="x")
    return run, wrote


def test_the_nightly_hub_step_is_hard_under_v2_and_soft_under_v1(tmp_path, monkeypatch):
    from modules import nightly
    failed = {"header": {"engine_mismatch": False}, "v2": None, "v2_error": {"stage": "roster", "error": "E: r"}}
    run, wrote = _nightly_hub(monkeypatch, tmp_path, "v2", failed)
    with pytest.raises(nightly.StepRefused, match="roster"):
        run.step_hub()
    assert wrote == []                               # refused before anything is written: the last good page stays
    run, wrote = _nightly_hub(monkeypatch, tmp_path, "v1", copy.deepcopy(failed))
    out = run.step_hub()                             # soft under v1, as before
    assert out.startswith("preview only") and "hub.version" not in out and wrote == ["payload"]
    ratings = {"header": {"engine_mismatch": False}, "v2": {"ratings": {"error": "R: q"}}, "v2_error": None}
    run, _ = _nightly_hub(monkeypatch, tmp_path, "v2", ratings)
    with pytest.raises(nightly.StepRefused, match="ratings failed"):
        run.step_hub()


# =============================================================================
# publishing the new hub
# =============================================================================

def test_the_bundle_is_gzipped_then_encrypted_and_opens_as_the_shell_opens_it(tmp_path):
    p = _v2_world(tmp_path)
    out = tmp_path / "_to_delete" / "x" / "publish"
    v2pub.build(tmp_path, p, PASS, salt=SALT, out_dir=out, iterations=1000, terms=T2.TERMS, now=GEN, pictures=[])
    sh = (out / "index.html").read_text(encoding="utf-8")
    b = pc._bundle(sh)
    assert b["z"] == "gzip"
    raw = hub_crypto.open_bundle(PASS, {k: v for k, v in b.items() if k != "z"})
    assert raw[:2] == b"\x1f\x8b"                    # gzip inside the encryption
    inner = pc.open_page(sh, PASS)
    assert json.loads(gzip.decompress(raw)) == inner and "Glass Cannons" in inner["page"]
    assert "font-src data:" in sh and hub_page.OLD_BROWSER_TEXT in sh


def test_every_lazy_part_decrypts_by_its_content_and_every_file_is_reached(tmp_path):
    p = _v2_world(tmp_path)
    rep = pc.check(tmp_path, p, None, tmp_path / "_to_delete" / "c" / "publish", now=GEN + timedelta(hours=1),
                   pictures=[], terms=T2.TERMS)
    assert rep["ok"], rep["problems"]
    assert len(rep["opened"]["parts"]) == 7 and rep["opened"]["issues"] == 1 and not rep["orphans"]
    assert rep["scan"]["control"] and rep["routes"]["unresolved"] == []


def test_unchanged_parts_are_byte_identical_across_two_runs(tmp_path):
    p = _v2_world(tmp_path)
    a, b = tmp_path / "_to_delete" / "a", tmp_path / "_to_delete" / "b"
    for d in (a, b):
        v2pub.build(tmp_path, p, PASS, salt=SALT, out_dir=d, iterations=1000, terms=T2.TERMS, now=GEN, pictures=[])
    fa, fb = _files(a), _files(b)
    assert set(fa) == set(fb) and len(fa) > 2
    assert fa["index.html"] != fb["index.html"]      # a fresh IV every build, as the current hub's
    assert {f: v for f, v in fa.items() if f != "index.html"} == {f: v for f, v in fb.items() if f != "index.html"}
    # into the same folder: only index.html is rewritten
    before = {f: (a / f).stat().st_mtime_ns for f in fa}
    v2pub.build(tmp_path, p, PASS, salt=SALT, out_dir=a, iterations=1000, terms=T2.TERMS, now=GEN, pictures=[])
    assert [f for f in fa if (a / f).stat().st_mtime_ns != before[f]] == ["index.html"]


def test_a_stray_file_refuses_and_clear_superseded_takes_the_parts_too(tmp_path):
    p = _v2_world(tmp_path)
    out = tmp_path / "_to_delete" / "s"
    v2pub.build(tmp_path, p, PASS, salt=SALT, out_dir=out, iterations=1000, terms=T2.TERMS, now=GEN, pictures=[])
    (out / "parts" / "notes.txt").write_text("x")
    with pytest.raises(hub_publish.PublishError, match="notes.txt"):
        v2pub.build(tmp_path, p, PASS, salt=SALT, out_dir=out, iterations=1000, terms=T2.TERMS, now=GEN, pictures=[])
    (out / "parts" / "notes.txt").unlink()
    gone = hub_publish.clear_superseded(out)        # the current hub's own build clears the new hub's parts
    assert gone and all(g.startswith("parts/") for g in gone) and not list((out / "parts").glob("*.enc"))
    assert "parts" in hub_publish.CONTENT_DIRS and "parts" in v2pub.CONTENT_DIRS


@pytest.mark.parametrize("plant", ["<!-- lore:phase-x -->", "Marcus Guard", "PICTURE"])
def test_the_scan_catches_a_planted_term_in_a_lazy_part(tmp_path, monkeypatch, plant):
    """The negative controls: a lore tag, a name and a team picture planted in a
    lazy part are caught by the scan when that part is written in plaintext."""
    import test_hub_v2_market as TM
    from modules import team_pictures as tp
    pics = TM._pics(tmp_path)
    terms = T2.TERMS + tp.scan_terms(tmp_path)
    if plant == "PICTURE":
        plant = next(iter(pics.values())).split(",", 1)[1]
    p = _v2_world(tmp_path)
    out = tmp_path / "_to_delete" / "n"
    v2pub.build(tmp_path, p, PASS, salt=SALT, out_dir=out, iterations=1000, terms=terms, now=GEN)
    assert hub_publish.scan_dir(out, terms)["hits"] == {}
    # a lazy part written without its encryption: the scan names it
    leaked = out / "parts" / "0000000000000000.enc"
    leaked.write_bytes(json.dumps({"html": f"<p>{plant}</p>"}).encode())
    hits = hub_publish.scan_dir(out, terms)["hits"]
    assert list(hits) == ["parts/0000000000000000.enc"]
    leaked.unlink()
    # and a build whose parts' sealing broke never writes: PlaintextLeak
    lg_html = {"html": f"<p>{plant}</p>"}
    monkeypatch.setattr(v2pub, "league_files", lambda vm, root, terms=(): (
        {"parts/1111111111111111.enc": json.dumps(lg_html).encode()},
        {"awards": {"file": "parts/1111111111111111.enc", "key": "AA=="}}, None))
    with pytest.raises(hub_publish.PlaintextLeak):
        v2pub.build(tmp_path, p, PASS, salt=SALT, out_dir=tmp_path / "_to_delete" / "n2", iterations=1000,
                    terms=terms, now=GEN)


def test_a_scratch_build_still_refuses_the_live_directory_and_live_writes_it(tmp_path):
    p = _v2_world(tmp_path)
    with pytest.raises(v2pub.V2PublishError, match="hub_publish"):
        v2pub.build(tmp_path, p, PASS, salt=SALT, out_dir=hub_publish.publish_dir(tmp_path), iterations=1000,
                    terms=T2.TERMS, now=GEN, pictures=[])
    with pytest.raises(v2pub.V2PublishError, match="out_dir"):
        v2pub.build(tmp_path, p, PASS, salt=SALT, iterations=1000, terms=T2.TERMS, now=GEN, pictures=[])
    rep = v2pub.build(tmp_path, p, PASS, salt=SALT, live=True, iterations=1000, terms=T2.TERMS, now=GEN, pictures=[])
    assert (hub_publish.publish_dir(tmp_path) / "index.html").is_file() and rep["live"]


def test_a_live_build_needs_every_listed_issue_in_the_archive(tmp_path):
    p = _v2_world(tmp_path)
    p["newsletter"]["archive"] = [{"week": "7", "label": "Week 7", "file": "week07-bbbbbbbbbbbb.enc", "size": "1 MB"}]
    with pytest.raises(v2pub.V2PublishError, match="week07"):
        v2pub.build(tmp_path, p, PASS, salt=SALT, live=True, iterations=1000, terms=T2.TERMS, now=GEN, pictures=[])


def test_the_deploy_mirror_takes_the_parts_folder(tmp_path):
    import hub_deploy
    p = _v2_world(tmp_path)
    v2pub.build(tmp_path, p, PASS, salt=SALT, live=True, iterations=1000, terms=T2.TERMS, now=GEN, pictures=[])
    tgt = tmp_path / "hub"
    (tgt / ".git").mkdir(parents=True)
    (tgt / "cards").mkdir()
    (tgt / "cards" / "0123456789abcdef.enc").write_bytes(b"an old card")       # the current hub's, unreferenced
    r = hub_deploy.stage(tmp_path, tgt, terms=T2.TERMS, out=lambda *a: None)
    assert any(f.startswith("parts/") for f in r["files"]) and "cards/0123456789abcdef.enc" in r["removed"]


# =============================================================================
# the payload's side file (4C5_DECISIONS 13, and the headroom)
# =============================================================================

def test_the_growing_keys_ride_in_the_side_file_and_come_back(tmp_path):
    p = T2.synth_payload()
    want = {f"{a}.{b}": copy.deepcopy(p["v2"][a][b]) for a, b in v2data.SIDE_KEYS}
    p["engine"] = {"key": "abc"}
    obj = v2data.players_file(p)
    for a, b in v2data.SIDE_KEYS:
        assert b not in p["v2"][a]
    assert p["v2"]["players_file"]["moved"] == sorted(want) and obj["moved"] == want
    v2data.attach_players(p, obj)
    assert {f"{a}.{b}": p["v2"][a][b] for a, b in v2data.SIDE_KEYS} == want
    p2 = T2.synth_payload()
    p2["engine"] = {"key": "abc"}
    obj2 = v2data.players_file(p2)
    obj2["moved"].pop("league.awards")
    with pytest.raises(v2data.V2Error, match="league.awards"):
        v2data.attach_players(p2, obj2)


# =============================================================================
# parity: the banners, the header, the current hub's links
# =============================================================================

def test_the_banners_and_the_header_reach_the_published_new_hub(tmp_path):
    p = _v2_world(tmp_path)
    p["header"]["engine_mismatch"] = "priced by engine abc1234, and the engine on disk is def5678"
    p["header"]["closing_note"] = "The closing line was refused tonight (no window): the lines are last night's."
    p["header"]["nba"] = {"text": "NBA injury report filed Mon 3:15 PM Pacific.",
                          "flags": ["NBA report lists Some Body (AAA), not matched: is it Some Bodie?"]}
    p["v2"]["line_text"] = "Closing line priced Mon 7:02 PM"
    rep = pc.check(tmp_path, p, None, tmp_path / "_to_delete" / "b" / "publish", now=GEN + timedelta(hours=40),
                   pictures=[], terms=T2.TERMS)
    assert rep["ok"], rep["problems"]
    page = pc.open_page((tmp_path / "_to_delete" / "b" / "publish" / "index.html").read_text(encoding="utf-8"),
                        pc.THROWAWAY_PASSPHRASE)["page"]
    b = rep["banners"]
    assert b["stale_shown"] and b["engine_mismatch"] and b["closing_note"] is True
    assert b["line_header"] == "Closing line priced Mon 7:02 PM"
    assert "NBA injury report filed Mon 3:15 PM Pacific." in page and "not matched: is it Some Bodie?" in page
    fresh = pc.check(tmp_path, _v2_world(tmp_path), None, tmp_path / "_to_delete" / "f" / "publish",
                     now=GEN + timedelta(hours=1), pictures=[], terms=T2.TERMS)
    assert not fresh["banners"]["stale_shown"] and not fresh["banners"]["engine_mismatch"]


def test_the_current_hubs_links_map_to_the_new_screens():
    js = T2.page.script()
    for old, new in (("v-main", "home"), ("v-last", "matchups"), ("v-chart", "league/standings"),
                     ("v-block", "block"), ("v-advice", "advice"), ("v-roster-", "teams/"), ("v-mu(", "matchups/w")):
        assert old in js and new in js, old
    assert js.index("function legacy()") < js.index("function route()") and "route(){\n  legacy();" in js


def _jsdom_env():
    node = shutil.which("node")
    if not node:
        return None
    env = dict(os.environ)
    if os.environ.get("HUB_TEST_JSDOM"):
        env["NODE_PATH"] = os.environ["HUB_TEST_JSDOM"]
    ok = subprocess.run([node, "-e", "require.resolve('jsdom')"], env=env, capture_output=True).returncode == 0
    return (node, env) if ok else None


def _shell(out, scenario, passphrase=PASS):
    je = _jsdom_env()
    if je is None:
        pytest.skip("node and jsdom are not installed here (NODE_PATH or HUB_TEST_JSDOM)")
    node, env = je
    r = subprocess.run([node, str(ROOT / "tests" / "js" / "shell_v2.js"), str(out), passphrase, json.dumps(scenario)],
                       env=env, capture_output=True, text=True, timeout=120)
    return json.loads(r.stdout)


@pytest.fixture(scope="module")
def synth_published(tmp_path_factory):
    base = tmp_path_factory.mktemp("v2pub")
    p = _v2_world(base, keep_cards=True)            # the card keys stay (Compare's rows); no card files
    out = base / "_to_delete" / "j" / "publish"
    v2pub.build(base, p, PASS, salt=SALT, out_dir=out, iterations=1000, terms=T2.TERMS, now=GEN, pictures=[])
    return out, p


@pytest.mark.slow
def test_in_jsdom_the_new_shell_opens_says_wrong_passphrase_and_names_an_old_browser(synth_published):
    out, _p = synth_published
    ok = _shell(out, {"part": True})
    assert ok["mounted"] and ok["screen"] == ["home"] and ok["part_html"] > 0 and ok["errors"] == [], ok
    wrong = _shell(out, {}, passphrase=PASS + " not")
    assert not wrong["mounted"] and wrong["msg"] == "Wrong passphrase."
    old = _shell(out, {"old": True})
    assert not old["mounted"] and old["button_disabled"] and old["msg_before"] == hub_page.OLD_BROWSER_TEXT


@pytest.mark.slow
def test_in_jsdom_compare_keeps_its_data_once_published(synth_published):
    """The shell's mount re-created every <script> as code: Compare's data block
    (type application/json, id v2-cmp) lost its id and threw. The v2 shell
    leaves data blocks as they are."""
    out, p = synth_published
    page = pc.open_page((out / "index.html").read_text(encoding="utf-8"), PASS)["page"]
    data = json.loads(re.search(r'<script type="application/json" id="v2-cmp">(.*?)</script>', page, re.S).group(1))
    keys = sorted(data["rows"])[:2]
    r = _shell(out, {"hash": f"#/players/compare/{keys[0]}/{keys[1]}"})
    assert r["mounted"] and r["screen"] == ["compare"] and r["cmp_rows"] > 0 and r["errors"] == [], json.dumps(r)


@pytest.mark.slow
@pytest.mark.parametrize("hash_,screen,pane", [("#v-roster-Marcus", "teams/Marcus", None),
                                                ("#v-chart", "league", None), ("#v-block", "market", "block"),
                                                ("#v-mu8-0-win", "matchups/w8-0", "win"), ("#v-main", "home", None),
                                                ("#v-last", "matchups", None), ("#v-nothing", "home", None)])
def test_in_jsdom_the_current_hubs_links_land_on_the_new_screens(synth_published, hash_, screen, pane):
    out, p = synth_published
    if screen.startswith("matchups/w"):
        screen = p["v2"]["matchups"][0]["id"] and f"matchups/{p['v2']['matchups'][0]['id']}"
        hash_ = "#v-mu" + p["v2"]["matchups"][0]["id"][1:] + "-win"
    r = _shell(out, {"hash": hash_})
    assert r["mounted"] and r["screen"] == [screen], r
    if pane:
        assert pane in r["selected"], r
    assert r["errors"] == [], r


# =============================================================================
# the one real, unstubbed test: today's state, the full v2 publish, both ways
# =============================================================================

@pytest.fixture(scope="module")
def real():
    from modules import hub_state as hs, player_actuals
    from modules.league_clock import league_now
    needed = [ROOT / "data" / "player_actuals.json", ROOT / "output" / "title_odds_history.jsonl",
              ROOT / "output" / "title_odds_latest.json", ROOT / "output" / "tag_records.jsonl",
              ROOT / "config" / "ROSTERS.json", ROOT / "output" / "hub_archive" / "index.json"]
    if not all(q.exists() for q in needed):
        pytest.skip("no league state on this machine")
    league_state.skip_if_actuals_behind()
    try:
        po = {}
        p = hs.build(ROOT, now=league_now(), allow_engine_mismatch=True, echo=lambda *a, **k: None, players_out=po)
    except (hs.HubInputError, player_actuals.ActualsError) as e:
        pytest.skip(f"the hub's real inputs are not current today ({e})")
    size = len(json.dumps(p))
    pub = v2data.attach_players(copy.deepcopy(p), po) if p.get("v2") is not None else None
    return p, po, pub, size


@pytest.mark.slow
def test_real_payload_has_its_headroom_and_the_new_hub_publishes_whole(real, tmp_path, monkeypatch):
    from modules import hub_cards, team_pictures, hub_state as hs
    p, po, pub, size = real
    assert hub_version.v2_failures(p) == [], hub_version.v2_failures(p)
    assert size <= 300_000, f"the payload is {size:,} bytes: under 25% headroom below the 400,000 cap"
    assert sorted(po["moved"]) == sorted(f"{a}.{b}" for a, b in v2data.SIDE_KEYS)
    assert pub["v2"]["line_text"] == p["header"]["line_text"]        # the "Closing line priced" header, one source
    cards = hub_cards.build(ROOT, p, echo=lambda *a, **k: None)
    pics, _n = team_pictures.data_uris(ROOT, list(pub["v2"]["team_order"]))
    out = tmp_path / "check" / "publish"
    rep = pc.check(ROOT, pub, cards, out, pictures=pics)
    assert rep["ok"], rep["problems"]
    assert len(rep["opened"]["parts"]) == 7 and rep["opened"]["cards"] == len(cards["cards"])
    idx = hub_archive.verify(ROOT)
    assert rep["opened"]["issues"] == len(idx["issues"])
    assert rep["first_load"] <= rep["budget"] and rep["scan"]["hits"] == {}
    # both directions on today's payload, with a fixed IV and a throwaway salt (never the hub's own)
    _fixed_iv(monkeypatch)
    monkeypatch.setattr(hub_publish, "hub_salt", lambda base, create=True: SALT)
    live = tmp_path / "live"
    terms = hub_publish.scan_terms(ROOT)
    hub_publish.build(ROOT, p, PASS, terms=terms, iterations=1000, cards=cards, out_dir=live)
    first = _files(live)
    v2pub.clear_superseded(live)
    v2pub.build(ROOT, pub, PASS, salt=SALT, out_dir=live, live=True, iterations=1000, terms=terms, cards=cards,
                pictures=pics)
    assert any(f.startswith("parts/") for f in _files(live))
    hub_publish.clear_superseded(live)
    hub_publish.build(ROOT, p, PASS, terms=terms, iterations=1000, cards=cards, out_dir=live)
    assert _files(live) == first
