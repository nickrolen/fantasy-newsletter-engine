"""4a4 Phase A: every player's NBA seasons from Yahoo (modules/nba_seasons,
scripts/fetch_nba_seasons; claude/HANDOFF_4A4_NBA_HISTORY_OVR_ARCHETYPES_2026-11-20.md).

1. the fetch on fixtures: the schema, the calls, the game-key lookup
2. resumable and --max-calls: a capped run and its resumption write exactly
   what one uninterrupted run writes, with no call repeated
3. deterministic output
4. a season Yahoo can't serve is named, never guessed
5. Yahoo's shapes: composites, a missing stat, the wrong coverage
6. the box-score identities reject a player by name; gp 0; no stats
7. never prints a credential
8. load() for readers; the coverage summary
9. (11-20) a season with no games is unavailable, never complete; the
   first fetch's file (version 1: "team", empty old seasons) is corrected on
   read and only its empty seasons are fetched again; no team is stored
10. (11-20) --debug-raw saves one page's raw responses, scrubbed
No network: a fake Yahoo in Yahoo's recorded shapes (players / player /
player_stats, as tests/test_40b_fa_actuals.py records them).
"""
import json
import re
from pathlib import Path

import pytest

from modules import nba_seasons as ns
from scripts import fetch_nba_seasons as cli

VALUES = {"FGM": 1, "FGA": -0.45, "FTM": 1, "FTA": -0.75, "3PTM": 3, "PTS": 0.5, "REB": 1.5, "AST": 2,
          "ST": 3, "BLK": 3, "TO": -2}
ORDER = list(VALUES)
NOW = "2026-11-20T21:00:00+00:00"


@pytest.fixture(autouse=True)
def _small_seasons(monkeypatch):
    """The fixtures' pools are 25-60 players; a real season needs 300 who played."""
    assert ns.MIN_PLAYED == 300
    monkeypatch.setattr(ns, "MIN_PLAYED", 5)


def box(seed: int, gp: int) -> dict:
    if gp == 0:
        return {k: 0 for k in ORDER}
    fgm, tpm, ftm = 4 * gp + seed % 7, gp + seed % 3, 2 * gp + seed % 5
    return {"FGM": fgm, "FGA": 2 * fgm + seed % 4, "FTM": ftm, "FTA": ftm + seed % 3, "3PTM": tpm,
            "PTS": 2 * fgm + tpm + ftm, "REB": 5 * gp, "AST": 3 * gp + seed % 2, "ST": gp, "BLK": seed % 9,
            "TO": 2 * gp}


class FakeYahoo:
    """game/{key}/players;start=;count=25/stats;type=season;season= and
    games;game_codes=nba;seasons=, in Yahoo's JSON shapes."""
    IDS = ns.YAHOO_IDS

    def __init__(self, pools, games, *, composite=False, fail=None, coverage=None, drop_stat=None,
                 lookup_override=None, old_years=(), retired=(), retired_mode="refuse", today="466",
                 league_off=None):
        self.pools = pools            # {year: [(pid, name, team, gp, stats or None)]}
        self.games = games            # {year: game key} Yahoo knows
        self.composite = composite
        self.fail = fail or {}        # {(year, start): number of times to raise}
        self.coverage = coverage      # override the coverage season
        self.drop_stat = drop_stat
        self.lookup_override = lookup_override
        self.old_years = set(old_years)     # the season's own game sends every stat as "-" (as Yahoo does, 11-20)
        self.retired = set(retired)         # ids today's game will not serve
        self.retired_mode = retired_mode    # "refuse" (an error for the whole request) or "omit"
        self.today = today
        self.league_off = league_off or {}  # {year: points added to Yahoo's league total}
        self.calls = 0
        self.uris = []

    def get(self, uri):
        self.calls += 1
        self.uris.append(uri)
        m = re.fullmatch(r"games;game_codes=nba;seasons=([\d,]+)", uri)
        if m:
            games = {"count": 0}
            n = 0
            for y in (int(x) for x in m.group(1).split(",")):
                key = (self.lookup_override or {}).get(y, self.games.get(y))
                if key is None:
                    continue
                games[str(n)] = {"game": [{"game_key": key, "game_id": key, "name": "Basketball", "code": "nba",
                                           "type": "full", "season": str(y)}]}
                n += 1
            games["count"] = n
            return {"fantasy_content": {"games": games}}
        m = re.fullmatch(r"players;player_keys=([\d.p,]+)/stats;type=season;season=(\d+)", uri)
        if m:
            year = int(m.group(2))
            keys = m.group(1).split(",")
            assert all(k.startswith(self.today + ".p.") for k in keys), uri
            ids = [int(k.split(".p.")[1]) for k in keys]
            assert len(ids) <= 25
            if self.retired_mode == "refuse" and self.retired & set(ids):
                raise RuntimeError('{"error": {"description": "Invalid player key"}, "access_token": "SECRETTOKEN123"}')
            rows = [r for r in self.pools[year] if r[0] in ids and r[0] not in self.retired]
            return {"fantasy_content": {"players": self._players(rows, self.today, year, real=True)}}
        m = re.fullmatch(r"league/(\d+)\.l\.\d+/players;player_keys=([\d.p,]+)/stats;type=season", uri)
        if m:
            key = m.group(1)
            year = [y for y, k in self.games.items() if k == key][0]
            ids = [int(k.split(".p.")[1]) for k in m.group(2).split(",")]
            players = {"count": len(ids)}
            for i, pid in enumerate(ids):
                pid_, name, team, gp, st = [r for r in self.pools[year] if r[0] == pid][0]
                total = round(sum(st[k] * VALUES[k] for k in ORDER) + self.league_off.get(year, 0), 2)
                players[str(i)] = {"player": [[{"player_key": f"{key}.p.{pid}"}, {"player_id": str(pid)},
                                               {"name": {"full": name}}],
                                              {"player_stats": {"0": {"coverage_type": "season", "season": str(year)},
                                                                "stats": [{"stat": {"stat_id": "12", "value": "-"}}]},
                                               "player_points": {"0": {"coverage_type": "season", "season": str(year)},
                                                                 "coverage_type": "season", "season": str(year),
                                                                 "total": str(total)}}]}
            return {"fantasy_content": {"league": [{"league_key": f"{key}.l.1"}, {"players": players}]}}
        m = re.fullmatch(r"game/(\d+)/players;start=(\d+);count=25/stats;type=season;season=(\d+)", uri)
        assert m, uri
        key, start, year = m.group(1), int(m.group(2)), int(m.group(3))
        assert self.games[year] == key
        if self.fail.get((year, start)):
            self.fail[(year, start)] -= 1
            raise RuntimeError('{"error": {"description": "Request denied"}, "access_token": "SECRETTOKEN123", '
                               '"Authorization": "Bearer SECRETBEARER"}')
        rows = self.pools[year][start:start + 25]
        if not rows:
            return {"fantasy_content": {"game": [{"game_key": key}, {"players": []}]}}
        return {"fantasy_content": {"game": [{"game_key": key},
                                             {"players": self._players(rows, key, year,
                                                                       real=year not in self.old_years)}]}}

    def _players(self, rows, key, year, *, real):
        players = {"count": len(rows)}
        for i, (pid, name, team, gp, st) in enumerate(rows):
            if not real and st is not None:
                gp = 0                         # Yahoo's old games: the pool, every stat "-"
            meta = [{"player_key": f"{key}.p.{pid}"}, {"player_id": str(pid)}, {"name": {"full": name}}, [],
                    {"editorial_team_abbr": team}]
            if st is None:
                stats = []
            else:
                stats = [{"stat": {"stat_id": "0", "value": str(gp) if gp else "-"}},
                         {"stat": {"stat_id": "2", "value": str(30 * gp)}}]
                for k in ORDER:
                    if self.composite and k in ("FGM", "FGA", "FTM", "FTA"):
                        continue
                    if k == self.drop_stat:
                        continue
                    stats.append({"stat": {"stat_id": self.IDS[k], "value": str(st[k]) if gp else "-"}})
                if self.composite:
                    stats.append({"stat": {"stat_id": "9004003", "value": f"{st['FGM']}/{st['FGA']}" if gp else "-/-"}})
                    stats.append({"stat": {"stat_id": "9007006", "value": f"{st['FTM']}/{st['FTA']}" if gp else "-/-"}})
            cov = {"coverage_type": "season", "season": str(self.coverage or year)}
            players[str(i)] = {"player": [meta, {"player_stats": {"0": cov, "stats": stats}}]}
        return players


GAMES = {2016: "364", 2017: "375", 2018: "385"}


def pool(year, n, *, start_id=1):
    out = []
    for i in range(n):
        pid = start_id + i * 7
        gp = 0 if i % 11 == 10 else 40 + (pid + year) % 40
        out.append((pid, f"Player {pid}", ["BOS", "LAL", "OKC"][pid % 3], gp, box(pid + year, gp)))
    return out


def world(tmp_path, pools=None, **kw):
    base = tmp_path / "repo"
    (base / "config").mkdir(parents=True)
    cfg = {"yahoo": {"current_league_key": "466.l.42309",
                     "historical_league_keys": {"2017-18": "375.l.132631", "2018-19": "385.l.90986"}},
           "yahoo_settings": {"stat_values": VALUES}}
    (base / "config" / "league_config.json").write_text(json.dumps(cfg), encoding="utf-8")
    pools = pools or {2016: pool(2016, 26), 2017: pool(2017, 60), 2018: pool(2018, 25)}
    return base, FakeYahoo(pools, dict(GAMES), **kw)


def run(base, fake, *args):
    out = []
    rc = cli.main(["--base-path", str(base), "--first", "2016-17", "--last", "2018-19", "--sleep", "0", *args],
                  source=fake, log=out.append, now=lambda: NOW, sleeper=lambda s: None)
    return rc, out


def text(base):
    return (base / "data" / "historical" / "NBA_SEASONS.json").read_text(encoding="utf-8")


# 1 ---------------------------------------------------------------------------

def test_the_fetch_writes_the_schema_with_one_lookup_and_every_page(tmp_path):
    base, fake = world(tmp_path)
    rc, out = run(base, fake)
    assert rc == 0, out
    # 1 lookup; 2018: 25 -> 2 pages (the second empty); 2017: 60 -> 3; 2016: 26 -> 2;
    # then one cross-check for each season the league played (2018-19, 2017-18)
    assert fake.calls == 1 + 2 + 3 + 2 + 2
    assert fake.uris[-2:] == ["league/385.l.90986/players;player_keys=" + ",".join(
        f"385.p.{p_}" for p_ in sorted((json.loads(text(base))["provenance"]["2018-19"]["cross_check"][i]["player_id"]
                                        for i in range(3)), key=int)) + "/stats;type=season",
                              fake.uris[-1]]
    assert fake.uris[0] == "games;game_codes=nba;seasons=2016,2017,2018"
    assert fake.uris[1].startswith("game/385/players;start=0;"), "newest season first"
    blob = json.loads(text(base))
    assert blob["version"] == 2 and blob["stats"] == ORDER
    assert {s: p["game_key"] for s, p in blob["provenance"].items()} == {"2016-17": "364", "2017-18": "375",
                                                                        "2018-19": "385"}
    for s, p in blob["provenance"].items():
        assert p["status"] == "complete" and p["source"] == "yahoo" and p["fetched_at"] == NOW
        assert p["rejected"] == [] and p["reason"] is None and p["unserved"] == []
        assert p["method"] == ns.SEASON_METHOD
        assert not {"phase", "listing", "key_next"} & set(p), "the run's working state goes at completion"
    assert "cross_check" not in blob["provenance"]["2016-17"], "the league did not play 2016-17 on Yahoo"
    assert [c["file"] == c["yahoo_league"] for c in blob["provenance"]["2017-18"]["cross_check"]] == [True] * 3
    pid, name, team, gp, st = pool(2017, 60)[3]
    rec = blob["players"][str(pid)]
    assert rec["seasons"]["2017-18"] == {"gp": gp, "stats": st}
    assert "team" not in text(base), "Yahoo's team is today's, not the season's: never stored"
    assert list(rec["seasons"]["2017-18"]["stats"]) == ORDER
    assert rec["name"] == name
    assert ns.load(base)["players"] == blob["players"]


def test_the_lookup_must_agree_with_config_before_any_page(tmp_path):
    base, fake = world(tmp_path, lookup_override={2017: "380"})
    rc, out = run(base, fake)
    assert rc == 1 and fake.calls == 1
    assert any("config yahoo.historical_league_keys says 375" in line for line in out)


# 2 ---------------------------------------------------------------------------

def test_max_calls_stops_and_the_next_run_resumes_to_the_same_file(tmp_path):
    base, fake = world(tmp_path / "a")
    assert run(base, fake)[0] == 0
    whole, whole_calls = text(base), fake.calls

    base2, fake2 = world(tmp_path / "b")
    rc, out = run(base2, fake2, "--max-calls", "4")     # the lookup, 2018-19's two pages, 2017-18's first
    assert rc == 2 and fake2.calls == 4
    assert any("STOPPED at --max-calls" in line for line in out)
    blob = json.loads(text(base2))
    assert blob["provenance"]["2017-18"]["status"] == "partial"
    assert blob["provenance"]["2017-18"]["next_start"] == 25
    with pytest.raises(ns.SeasonsError, match="not complete"):
        ns.load(base2)
    calls_before = fake2.calls
    rc, out = run(base2, fake2, "--max-calls", "2")
    assert rc == 2
    rc, out = run(base2, fake2)
    assert rc == 0, out
    assert fake2.calls == whole_calls, "no page fetched twice, no second lookup"
    assert not any(u.startswith("games;") for u in fake2.uris[calls_before:])
    assert text(base2) == whole

    rc, out = run(base2, fake2)
    assert rc == 0 and fake2.calls == whole_calls, "complete seasons cost nothing"


def test_a_failed_page_mid_season_stops_and_resumes(tmp_path):
    base, fake = world(tmp_path, fail={(2017, 25): 2})
    rc, out = run(base, fake)
    assert rc == 1
    assert any("the page at 25 failed" in line for line in out)
    p = json.loads(text(base))["provenance"]
    assert p["2018-19"]["status"] == "complete" and p["2017-18"]["status"] == "partial"
    assert "2016-17" not in p or p["2016-17"]["status"] != "complete"
    rc, out = run(base, fake)
    assert rc == 0, out
    base2, fake2 = world(tmp_path / "clean")
    run(base2, fake2)
    assert text(base) == text(base2)


# 3 ---------------------------------------------------------------------------

def test_the_output_is_deterministic_and_ordered(tmp_path):
    base, fake = world(tmp_path / "a")
    run(base, fake)
    shuffled = {y: list(reversed(rows)) for y, rows in fake.pools.items()}
    base2, fake2 = world(tmp_path / "b", pools=shuffled)
    run(base2, fake2)
    assert text(base) == text(base2), "the pool's order never shows in the file"
    blob = json.loads(text(base))
    ids = list(blob["players"])
    assert ids == sorted(ids, key=int)
    assert any(len(i) == 1 for i in ids) and any(len(i) == 3 for i in ids), "numeric, not text, order"
    for r in blob["players"].values():
        assert list(r["seasons"]) == sorted(r["seasons"])
    lines = text(base).split("\n")
    assert sum(1 for line in lines if re.match(r'^"\d+":\{"name"', line)) == len(ids), "one player per line"


# 4 ---------------------------------------------------------------------------

def test_a_season_yahoo_does_not_list_is_named_not_guessed(tmp_path):
    base, fake = world(tmp_path)
    del fake.games[2016]
    rc, out = run(base, fake)
    assert rc == 1
    p = json.loads(text(base))["provenance"]["2016-17"]
    assert p["status"] == "unavailable" and p["game_key"] is None
    assert "returned no NBA game for season 2016 (2016-17)" in p["reason"]
    assert not any("2016-17" in r["seasons"] for r in json.loads(text(base))["players"].values())
    assert any(line.startswith("  GAPS: 2016-17 unavailable") for line in out)
    assert not any("game/364" in u for u in fake.uris)
    # Yahoo serves it later: the next run looks it up again and fetches it
    fake.games[2016] = "364"
    rc, out = run(base, fake)
    assert rc == 0, out
    assert json.loads(text(base))["provenance"]["2016-17"]["status"] == "complete"


def test_a_season_whose_first_page_fails_is_unavailable_and_two_in_a_row_stop(tmp_path):
    base, fake = world(tmp_path, fail={(2018, 0): 2})
    rc, out = run(base, fake)
    assert rc == 1
    p = json.loads(text(base))["provenance"]
    assert p["2018-19"]["status"] == "unavailable"
    assert "Yahoo could not serve the season's first page (game 385)" in p["2018-19"]["reason"]
    assert p["2017-18"]["status"] == "complete", "one bad season does not stop the others"

    base2, fake2 = world(tmp_path / "b", fail={(2018, 0): 2, (2017, 0): 2})
    rc, out = run(base2, fake2)
    assert rc == 1
    assert any("two seasons in a row" in line for line in out)
    assert not any("game/364" in u for u in fake2.uris), "stopped before the third season"


def test_an_empty_season_is_unavailable(tmp_path):
    base, fake = world(tmp_path)
    fake.pools[2016] = []
    rc, out = run(base, fake)
    assert rc == 1
    assert "Yahoo returned no players for 2016-17" in json.loads(text(base))["provenance"]["2016-17"]["reason"]


# 5 ---------------------------------------------------------------------------

def test_composite_fgm_fga_and_ftm_fta_read_the_same(tmp_path):
    base, fake = world(tmp_path / "a")
    run(base, fake)
    base2, fake2 = world(tmp_path / "b", composite=True)
    assert run(base2, fake2)[0] == 0
    assert text(base) == text(base2)


def test_a_missing_stat_raises_naming_the_ids_yahoo_sent(tmp_path):
    base, fake = world(tmp_path, drop_stat="BLK")
    rc, out = run(base, fake)
    assert rc == 1
    msg = " ".join(out)
    assert "carry no stat ['18 (BLK)']" in msg and "they carry ids ['0', '2', '3', '4'" in msg


def test_stats_for_the_wrong_season_raise(tmp_path):
    base, fake = world(tmp_path, coverage=2099)
    rc, out = run(base, fake)
    assert rc == 1
    assert any("not season 2018" in line for line in out)
    blob = json.loads(text(base)) if (base / ns.RELPATH).exists() else {"players": {}}
    assert blob["players"] == {}


# 6 ---------------------------------------------------------------------------

def test_a_player_failing_an_identity_is_rejected_by_name(tmp_path):
    base, fake = world(tmp_path)
    pid, name, team, gp, st = fake.pools[2017][2]
    bad = dict(st, PTS=st["PTS"] + 1)
    fake.pools[2017][2] = (pid, name, team, gp, bad)
    rc, out = run(base, fake)
    assert rc == 0
    blob = json.loads(text(base))
    rej = blob["provenance"]["2017-18"]["rejected"]
    assert rej == [{"player_id": str(pid), "name": name,
                    "why": f"PTS {bad['PTS']} is not 2 x FGM {st['FGM']} + 3PTM {st['3PTM']} + FTM {st['FTM']}"}]
    assert "2017-18" not in blob["players"][str(pid)]["seasons"]
    assert any(f"rejected: {name}" in line for line in out)


def test_identities():
    st = box(5, 50)
    assert ns.identity_error(50, st) is None
    assert "more than FGA" in ns.identity_error(50, dict(st, FGA=st["FGM"] - 1))
    assert "more than FTA" in ns.identity_error(50, dict(st, FTA=st["FTM"] - 1))
    assert "over 90" in ns.identity_error(91, st)
    assert "on 0 games played" in ns.identity_error(0, st)


def test_gp_zero_is_kept_for_a_player_who_played_and_dropped_for_one_who_never_did(tmp_path):
    base, fake = world(tmp_path)
    fake.pools[2016].append((500, "Hurt All Year", "GSW", 0, box(0, 0)))
    fake.pools[2017].append((500, "Hurt All Year", "GSW", 70, box(500, 70)))
    for y in (2016, 2017, 2018):
        fake.pools[y].append((600, "Never Played", "FA", 0, box(0, 0)))
    rc, out = run(base, fake)
    assert rc == 0
    blob = json.loads(text(base))
    assert blob["players"]["500"]["seasons"]["2016-17"] == {"gp": 0, "stats": {k: 0 for k in ORDER}}
    assert "600" not in blob["players"]
    assert any("Dropped" in line and "0 games in every season" in line for line in out)


def test_a_player_with_no_stats_at_all_is_counted_not_stored(tmp_path):
    base, fake = world(tmp_path)
    fake.pools[2018].append((700, "Ghost", "FA", 0, None))
    rc, out = run(base, fake)
    assert rc == 0
    blob = json.loads(text(base))
    assert blob["provenance"]["2018-19"]["no_stats"] == 1 and "700" not in blob["players"]


def test_the_name_is_his_most_recent_seasons(tmp_path):
    base, fake = world(tmp_path)
    pid = 900
    fake.pools[2016].append((pid, "Enes Kanter", "BOS", 50, box(1, 50)))
    fake.pools[2018].append((pid, "Enes Freedom", "BOS", 30, box(2, 30)))
    run(base, fake)
    assert json.loads(text(base))["players"][str(pid)]["name"] == "Enes Freedom"


# 7 ---------------------------------------------------------------------------

def test_never_prints_a_credential(tmp_path, capsys):
    base, fake = world(tmp_path, fail={(2018, 0): 2, (2017, 0): 2})
    rc, out = run(base, fake)
    printed = "\n".join(out) + capsys.readouterr().out + text(base)
    assert "Request denied" in printed, "the error is named"
    assert "SECRETTOKEN123" not in printed and "SECRETBEARER" not in printed
    assert ns.redact("refresh_token=abc.def&x=1") == "refresh_token=<redacted>&x=1"
    assert ns.redact('"consumer_secret": "s3cr3t"') == '"consumer_secret": "<redacted>"'


# 8 ---------------------------------------------------------------------------

def test_load_refuses_missing_and_incomplete(tmp_path):
    with pytest.raises(ns.SeasonsError, match="is missing: run python scripts/fetch_nba_seasons.py"):
        ns.load(tmp_path)
    base, fake = world(tmp_path)
    run(base, fake, "--max-calls", "2")
    with pytest.raises(ns.SeasonsError, match=r"\['2017-18'\] are not complete"):
        ns.load(base, seasons=["2017-18"])
    (base / ns.RELPATH).write_text("{not json", encoding="utf-8")
    with pytest.raises(ns.SeasonsError, match="unreadable"):
        ns.load(base)


def test_a_file_with_other_stats_is_refused(tmp_path):
    base, fake = world(tmp_path)
    run(base, fake)
    cfg = json.loads((base / "config" / "league_config.json").read_text())
    cfg["yahoo_settings"]["stat_values"]["PTS"] = 1
    cfg["yahoo_settings"]["stat_values"] = {k: v for k, v in cfg["yahoo_settings"]["stat_values"].items() if k != "TO"}
    (base / "config" / "league_config.json").write_text(json.dumps(cfg))
    rc, out = run(base, fake)
    assert rc == 1 and any("refetch" in line for line in out)


def test_the_config_is_required(tmp_path):
    base, fake = world(tmp_path)
    (base / "config" / "league_config.json").write_text(json.dumps({"yahoo_settings": {"stat_values": VALUES}}))
    rc, out = run(base, fake)
    assert rc == 1 and any("historical_league_keys is missing" in line for line in out)
    assert fake.calls == 0


def test_the_check_reports_coverage_with_no_yahoo_call(tmp_path):
    base, fake = world(tmp_path)
    run(base, fake)
    calls = fake.calls
    p1, p2 = fake.pools[2017][0], fake.pools[2018][1]
    log = [{"season_key": "2017-18", "player_id": p1[0], "player_name": p1[1], "had_game": True},
           {"season_key": "2018-19", "player_id": p2[0], "player_name": p2[1], "had_game": True},
           {"season_key": "2018-19", "player_id": 9999, "player_name": "Not In Pool", "had_game": True},
           {"season_key": "2018-19", "player_id": 8888, "player_name": "Never Played Here", "had_game": False}]
    (base / "data" / "historical" / "HISTORICAL_PLAYERLOG.json").write_text(json.dumps(log))
    (base / "data" / "player_actuals.json").write_text(json.dumps(
        {"roster_names": {p1[1]: p1[0]}, "extra_names": {"A Rookie": 12345}}))
    out = []
    rc = cli.main(["--base-path", str(base), "--first", "2016-17", "--last", "2018-19", "--check"],
                  source=fake, log=out.append)
    assert rc == 0 and fake.calls == calls
    joined = "\n".join(out)
    assert "League log: 3 player-seasons (his team had a game while he was rostered) in complete seasons; 1 missing" in joined
    assert "missing: Not In Pool (9999) 2018-19 -- not in Yahoo's pool" in joined
    assert "Today's players: 2; 1 with NBA games in the file; 1 with none (rookies, or missing): A Rookie" in joined
    assert re.search(r"2017-18  game  375  complete\s+pool   60", joined)


def test_the_real_config_gives_the_stats_and_the_keys():
    root = Path(__file__).resolve().parent.parent
    assert ns.stat_order(root) == ORDER
    keys = ns.config_game_keys(root)
    assert keys["2017-18"] == "375" and keys["2025-26"] == "466"
    seasons = ns.seasons_between(ns.FIRST_SEASON, ns.LAST_SEASON)
    assert seasons[0] == "2014-15" and seasons[-1] == "2025-26" and len(seasons) == 12
    assert set(keys) <= set(seasons)
    with pytest.raises(ns.SeasonsError):
        ns.seasons_between("2014-16", "2015-16")


# 9 ---------------------------------------------------------------------------

def no_games(year, n=30, start_id=1):
    return [(pid, name, team, 0, box(0, 0)) for pid, name, team, _, _ in pool(year, n, start_id=start_id)]


def test_a_season_with_no_games_is_unavailable_never_complete(tmp_path):
    base, fake = world(tmp_path)
    fake.pools[2016] = no_games(2016, 30)
    rc, out = run(base, fake)
    assert rc == 1
    blob = json.loads(text(base))
    p = blob["provenance"]["2016-17"]
    assert p["status"] == "unavailable"
    assert p["reason"] == ("Yahoo listed 30 players for 2016-17 and none with a game played (fewer than 5): "
                           "the season's stats did not come (through today's game too)")
    assert not any("2016-17" in r["seasons"] for r in blob["players"].values())
    assert any(line.startswith("  2016-17") and "unavailable" in line and "none with a game played" in line
               for line in out)
    assert any(line.startswith("  GAPS: 2016-17 unavailable") for line in out)
    with pytest.raises(ns.SeasonsError, match="not complete"):
        ns.load(base)


def test_a_season_with_only_a_few_games_is_unavailable(tmp_path):
    base, fake = world(tmp_path)
    fake.pools[2016] = no_games(2016, 30)[:27] + pool(2016, 3, start_id=2000)
    rc, out = run(base, fake)
    assert rc == 1
    assert "and only 3 with a game played" in json.loads(text(base))["provenance"]["2016-17"]["reason"]


def test_two_seasons_with_no_games_in_a_row_stop_the_run(tmp_path):
    base, fake = world(tmp_path)
    fake.pools[2018] = no_games(2018, 30)
    fake.pools[2017] = no_games(2017, 30)
    rc, out = run(base, fake)
    assert rc == 1
    assert any("two seasons in a row came back unavailable" in line and "--debug-raw" in line for line in out)
    assert not any("game/364" in u for u in fake.uris)


def v1_file(base, fake_good):
    """The first fetch's file: version 1, a team on every season, 2016-17
    "complete" with every player at 0 games."""
    good = json.loads(text(base))
    v1 = {"version": 1, "about": good["about"], "stats": good["stats"], "provenance": good["provenance"],
          "players": {}}
    for pid, r in good["players"].items():
        v1["players"][pid] = {"name": r["name"], "seasons": {
            s: dict(e, team="PHI") for s, e in r["seasons"].items() if s != "2016-17"}}
        if "2016-17" in r["seasons"]:
            v1["players"][pid]["seasons"]["2016-17"] = {"gp": 0, "stats": {k: 0 for k in ORDER}, "team": "PHI"}
    v1["players"] = {k: v for k, v in v1["players"].items() if v["seasons"]}
    (base / ns.RELPATH).write_text(json.dumps(v1), encoding="utf-8")
    return v1


def test_the_first_fetchs_file_is_corrected_and_only_its_empty_seasons_refetched(tmp_path):
    base, fake = world(tmp_path / "good")
    run(base, fake)
    good_text = text(base)
    base2, fake2 = world(tmp_path / "old")
    run(base2, fake2)
    v1_file(base2, fake2)
    before = text(base2)
    with pytest.raises(ns.SeasonsError, match=r"\['2016-17'\] are not complete"):
        ns.load(base2)
    out = []
    rc = cli.main(["--base-path", str(base2), "--first", "2016-17", "--last", "2018-19", "--check"],
                  source=fake2, log=out.append)
    assert rc == 1 and text(base2) == before, "--check writes nothing"
    assert any(line.startswith("  2016-17") and "none with a game played" in line for line in out)
    calls = fake2.calls
    rc, out = run(base2, fake2)
    assert rc == 0, out
    assert fake2.uris[calls:] == [ns.page_uri("364", 0, 2016), ns.page_uri("364", 25, 2016)], \
        "only the empty season, no lookup, no complete season again"
    assert text(base2) == good_text
    assert json.loads(text(base2))["version"] == 2


# 10 --------------------------------------------------------------------------

def test_debug_raw_saves_one_page_of_each_request_scrubbed(tmp_path):
    base, fake = world(tmp_path)
    run(base, fake)
    before = text(base)

    class DebugFake:
        def __init__(self):
            self.calls, self.uris = 0, []

        def get(self, uri):
            self.calls += 1
            self.uris.append(uri)
            if "average_season" in uri:
                raise RuntimeError('{"error": "bad type", "access_token": "SECRETTOKEN123"}')
            gp = "-" if "2016" in uri or "364" in uri else "61"
            return {"fantasy_content": {"xoauth_yahoo_guid": "SECRETGUID", "players": {"count": 1, "0": {
                "player": [[{"player_key": "364.p.3704"}, {"player_id": "3704"}, {"name": {"full": "LeBron James"}},
                            {"editorial_team_abbr": "PHI"}],
                           {"player_stats": {"0": {"coverage_type": "season", "season": "2016"},
                                             "stats": [{"stat": {"stat_id": "0", "value": gp}},
                                                       {"stat": {"stat_id": "12", "value": "-" if gp == "-" else "1505"}}]}}]}}}}

    d = DebugFake()
    out = []
    rc = cli.main(["--base-path", str(base), "--debug-raw", "2016-17", "2018-19"], source=d, log=out.append)
    assert rc == 0
    assert d.calls == 6 + 7, "2016-17 has no league key (no F); 2018-19 has every variant"
    assert d.uris[0] == ns.page_uri("364", 0, 2016).replace("count=25", "count=5")
    assert "players;player_keys=466.p.3704,466.p.4612/stats;type=season;season=2016" in d.uris
    assert "league/385.l.90986/players;player_keys=385.p.3704,385.p.4612/stats;type=season" in d.uris
    folder = base / "_to_delete" / "4a4"
    files = sorted(f.name for f in folder.glob("raw_*.json"))
    assert len(files) == 13 and "raw_2016-17_A_pool_type_season_season.json" in files
    saved = "".join(f.read_text() for f in folder.iterdir())
    assert "SECRETTOKEN123" not in saved and "SECRETGUID" not in saved and "SECRET" not in "\n".join(out)
    assert "LeBron James" in saved
    digest = (folder / "raw_digest.txt").read_text()
    assert "2016-17 A_pool_type_season_season: 1 players | 364.p.3704 LeBron James team=PHI " \
           "coverage=season/2016 GP='-' PTS='-'" in digest
    assert "2016-17 G_keys_average_season: ERROR RuntimeError" in digest
    assert digest.rstrip().endswith("13 Yahoo call(s).")
    assert text(base) == before, "the data file is never touched"


# 11 (11-20) ------------------------------------------------------------------
# Yahoo's old games list the pool with every stat "-"; today's game, asked by
# player key with season=YYYY, sends the real season (Nick's --debug-raw).

def players_of(base):
    return json.loads(text(base))["players"]


def test_an_old_season_is_fetched_through_todays_game_by_key(tmp_path):
    base, fake = world(tmp_path / "now")
    run(base, fake)
    base2, fake2 = world(tmp_path / "old", old_years={2016, 2017})
    rc, out = run(base2, fake2)
    assert rc == 0, out
    assert players_of(base2) == players_of(base), "the same numbers as a season whose own game sends them"
    prov = json.loads(text(base2))["provenance"]
    assert prov["2017-18"]["method"] == prov["2016-17"]["method"] == ns.TODAY_METHOD
    assert prov["2018-19"]["method"] == ns.SEASON_METHOD
    assert prov["2017-18"]["pool"] == 60
    keyed = [u for u in fake2.uris if u.startswith("players;")]
    assert keyed[0] == ns.keys_uri("466", sorted((str(r[0]) for r in fake2.pools[2017]), key=int)[:25], 2017)
    assert len(keyed) == 3 + 2, "60 ids in 3 calls, 26 in 2"
    assert any("its own game sent no stats" in line for line in out)
    assert any(line.strip() == f"from {ns.TODAY_METHOD}" for line in out)


def test_ids_todays_game_refuses_are_named_and_cost_no_batch(tmp_path):
    base, fake = world(tmp_path, old_years={2017})
    ids = [r[0] for r in fake.pools[2017]]
    gone = {ids[3], ids[40]}                     # two batches, one each
    fake.retired = gone
    rc, out = run(base, fake)
    assert rc == 0, out
    p = json.loads(text(base))["provenance"]["2017-18"]
    assert [u["player_id"] for u in p["unserved"]] == sorted(str(i) for i in gone)
    assert all(u["why"].startswith("today's game refused his key (RuntimeError") for u in p["unserved"])
    assert all(u["name"] == f"Player {u['player_id']}" for u in p["unserved"])
    stored = {pid for pid, r in players_of(base).items() if "2017-18" in r["seasons"]}
    assert not {str(i) for i in gone} & stored
    assert {str(r[0]) for r in fake.pools[2017] if r[3] > 0 and r[0] not in gone} <= stored
    assert any("not served by today's game: 2" in line for line in out)
    printed = "\n".join(out) + text(base)
    assert "SECRETTOKEN123" not in printed
    # each bad batch: the batch, its retry, five chunks of five, five singles
    keyed = [u for u in fake.uris if u.startswith("players;")]
    assert len(keyed) == 1 + 2 * (2 + 5 + 5)


def test_ids_todays_game_leaves_out_are_named(tmp_path):
    base, fake = world(tmp_path, old_years={2017}, retired_mode="omit")
    gone = fake.pools[2017][7][0]
    fake.retired = {gone}
    rc, out = run(base, fake)
    assert rc == 0
    un = json.loads(text(base))["provenance"]["2017-18"]["unserved"]
    assert un == [{"player_id": str(gone), "name": f"Player {gone}", "why": "today's game returned no line for him"}]
    assert len([u for u in fake.uris if u.startswith("players;")]) == 3, "no split when Yahoo just leaves him out"


def test_ten_refusals_in_a_row_and_lebron_refused_too_stop_and_the_batch_resumes(tmp_path):
    base, fake = world(tmp_path, old_years={2017})
    fake.retired = {r[0] for r in fake.pools[2017]} | {3704}
    rc, out = run(base, fake)
    assert rc == 1
    assert any("refused 10 single players in a row" in line and "and then LeBron James" in line for line in out)
    assert fake.uris[-1] == ns.keys_uri("466", ["3704"], 2017)
    p = json.loads(text(base))["provenance"]["2017-18"]
    assert p["status"] == "partial" and p["phase"] == "keys" and p["key_next"] == 0 and p["unserved"] == []
    fake.retired = set()                         # Yahoo is back
    rc, out = run(base, fake)
    assert rc == 0, out
    base2, fake2 = world(tmp_path / "clean", old_years={2017})
    run(base2, fake2)
    assert text(base) == text(base2)


def test_the_cap_inside_the_key_phase_resumes_to_the_same_file(tmp_path):
    base, fake = world(tmp_path / "a", old_years={2016, 2017})
    run(base, fake)
    whole, whole_calls = text(base), fake.calls
    base2, fake2 = world(tmp_path / "b", old_years={2016, 2017})
    rc, _ = run(base2, fake2, "--max-calls", "7")      # lookup, 2018 x2, 2017 listed x3, 1 key batch
    assert rc == 2
    p = json.loads(text(base2))["provenance"]["2017-18"]
    assert p["phase"] == "keys" and p["key_next"] == 25 and len(p["listing"]) == 60
    while rc == 2:
        rc, _ = run(base2, fake2, "--max-calls", "2")
    assert rc == 0
    assert fake2.calls == whole_calls and text(base2) == whole


def test_unserved_players_count_toward_the_floor_not_against_it(tmp_path, monkeypatch):
    monkeypatch.setattr(ns, "MIN_PLAYED", 50)
    base, fake = world(tmp_path, old_years={2017})
    fake.pools[2016] = pool(2016, 60)
    fake.pools[2018] = pool(2018, 60)
    played_ids = [r[0] for r in fake.pools[2017] if r[3] > 0]
    fake.retired = set(played_ids[:8])           # 55 played; 8 not served -> 47 stored + 8 named >= 50
    fake.retired_mode = "omit"
    rc, out = run(base, fake)
    assert rc == 0, out
    p = json.loads(text(base))["provenance"]["2017-18"]
    assert p["status"] == "complete" and len(p["unserved"]) == 8


def test_a_cross_check_that_differs_is_loud(tmp_path):
    base, fake = world(tmp_path, league_off={2017: 12.5})
    rc, out = run(base, fake)
    assert rc == 1
    assert any(line.startswith("  CROSS-CHECK DIFFERS in 2017-18") for line in out)
    assert any("CROSS-CHECK DIFFERS: Player" in line and "vs Yahoo's league" in line for line in out)
    assert json.loads(text(base))["provenance"]["2017-18"]["status"] == "complete", "the data is kept, the run says so"


def test_ten_real_refusals_in_a_row_go_on_when_lebron_is_served(tmp_path):
    base, fake = world(tmp_path, old_years={2017})
    ids = [r[0] for r in fake.pools[2017]]
    fake.retired = set(ids[:30])                  # the oldest 30 ids: retired
    rc, out = run(base, fake)
    assert rc == 0, out
    p = json.loads(text(base))["provenance"]["2017-18"]
    assert p["status"] == "complete" and len(p["unserved"]) == 30
    probes = [u for u in fake.uris if u == ns.keys_uri("466", ["3704"], 2017)]
    assert len(probes) == 3, "one after every ten refusals"
