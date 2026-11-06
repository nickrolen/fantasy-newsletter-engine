"""
advice_v1_replay.py -- the 2025-26 replay: advice v2's calibration check (V1).

claude/HANDOFF_ADVICE_V1_WORTH_CHECK_2026-11-05.md phase 2. For every replay
Monday, each manager's engine pick (every weighting), "add the most games",
"add the highest projection" and the common-drop variants, all from the same
point-in-time pool (modules/advice_replay.build_monday), scored on what
really happened. Writes ONLY under --out (scratch, never a state file).

    python scripts\\advice_v1_replay.py fetch  --raw _to_delete\\v1\\bbref_daily
    python scripts\\advice_v1_replay.py parse  --raw _to_delete\\v1\\bbref_daily --out _to_delete\\v1
    python scripts\\advice_v1_replay.py run    --out _to_delete\\v1 --weeks 2-22
    python scripts\\advice_v1_replay.py report --out _to_delete\\v1

run is resumable by week: each Monday writes out/replay/week_NN.json when it
finishes, and a finished week is skipped (--force to redo). A shell call is
capped at about 3 minutes, so run a few weeks per call; --budget stops
starting new weeks after that many seconds.

fetch reads basketball-reference's daily pages (every player who logged
minutes that day), one page per 3.5 s (under its 20-a-minute limit), skipping
pages already saved; plus the 2025-26 per-game page (positions).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from modules import advice_replay as ar          # noqa: E402
from modules import advice_v2 as av              # noqa: E402

LOG = ROOT / "data" / "historical" / "HISTORICAL_PLAYERLOG.json"
MATCHUPS = ROOT / "data" / "historical" / "all_matchups.json"
SCHEDULE = ROOT / "data" / "nba_schedule_2025-26.json"
PRIOR_HTML = ROOT / "data" / ".cache" / "bbref_per_game_2024-25.html"
PREV_HTML = ROOT / "data" / ".cache" / "bbref_per_game_2023-24.html"
DRAFTS = ROOT / "data" / "historical" / "all_drafts.json"
UA = {"User-Agent": "Mozilla/5.0 (newsletter advice replay)"}
SETTINGS = av.Settings()


# -----------------------------------------------------------------------------
# fetch and parse
# -----------------------------------------------------------------------------

def cmd_fetch(a):
    raw = Path(a.raw)
    raw.mkdir(parents=True, exist_ok=True)
    games = json.loads(SCHEDULE.read_text(encoding="utf-8"))["games"]
    dates = sorted({g["date"][:10] for g in games if g.get("home") and g["date"][:10] <= a.last})
    todo = [d for d in dates if not (raw / f"{d}.html").is_file()]
    print(f"{len(dates)} game dates, {len(todo)} to fetch")
    t0 = time.time()
    for d in todo:
        if time.time() - t0 > a.budget:
            print("budget reached; run again to continue")
            return
        y, m, dd = d.split("-")
        url = (f"https://www.basketball-reference.com/friv/dailyleaders.fcgi?"
               f"month={int(m)}&day={int(dd)}&year={y}")
        body = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30).read()
        tmp = raw / f"{d}.tmp"
        tmp.write_bytes(body)
        tmp.replace(raw / f"{d}.html")
        print(d, len(body), flush=True)
        time.sleep(3.5)
    pg = raw / "per_game_2025-26.html"
    if not pg.is_file():
        url = "https://www.basketball-reference.com/leagues/NBA_2026_per_game.html"
        pg.write_bytes(urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30).read())
    print("done")


NUM = ("mp", "fg", "fga", "fg3", "fg3a", "ft", "fta", "orb", "drb", "trb", "ast", "stl", "blk", "tov",
       "pf", "pts")


def parse_daily(raw: Path) -> list:
    from bs4 import BeautifulSoup
    rows = []
    for f in sorted(raw.glob("20*.html")):
        t = BeautifulSoup(f.read_text(encoding="utf-8"), "lxml").find("table", id="stats")
        if t is None:            # All-Star weekend: no NBA games
            continue
        for r in t.find("tbody").find_all("tr"):
            if "thead" in (r.get("class") or []):
                continue
            c = {x.get("data-stat"): x for x in r.find_all(["th", "td"])}
            if "player" not in c:
                continue
            a = c["player"].find("a")
            if a is None:
                raise ValueError(f"{f.name}: a row with no player link")
            rec = {"date": f.stem, "player": c["player"].get_text().strip(),
                   "bbref_id": a["href"].split("/")[-1].replace(".html", ""),
                   "team": c["team_id"].get_text().strip(), "opp": c["opp_id"].get_text().strip()}
            for k in NUM:
                v = c[k].get_text().strip() if k in c else ""
                if k == "mp":
                    mm, _, ss = v.partition(":")
                    rec[k] = round(int(mm or 0) + int(ss or 0) / 60, 2) if v else 0.0
                else:
                    rec[k] = int(v) if v else 0
            rows.append(rec)
    return rows


def parse_per_game(path: Path) -> list:
    """basketball-reference per-game: one row per player (the combined row
    for a multi-team season, which comes first)."""
    from bs4 import BeautifulSoup
    t = BeautifulSoup(path.read_text(encoding="utf-8"), "lxml").find("table", id="per_game_stats")
    out, seen = [], set()
    for r in t.find("tbody").find_all("tr"):
        if "thead" in (r.get("class") or []):
            continue
        c = {x.get("data-stat"): x.get_text().strip() for x in r.find_all(["th", "td"])}
        name = c.get("name_display", "")
        if not name or name == "League Average" or name in seen:
            continue
        seen.add(name)
        num = lambda k: float(c.get(k) or 0)
        out.append({"player": name, "team": c.get("team_name_abbr"), "pos": c.get("pos", ""),
                    "games": int(num("games")), "pts": num("pts_per_g"), "fga": num("fga_per_g"),
                    "ft": num("ft_per_g"), "fta": num("fta_per_g"), "fg3": num("fg3_per_g"),
                    "trb": num("trb_per_g"), "ast": num("ast_per_g"), "stl": num("stl_per_g"),
                    "blk": num("blk_per_g"), "tov": num("tov_per_g")})
    return out


def cmd_parse(a):
    raw, out = Path(a.raw), Path(a.out)
    box = parse_daily(raw)
    (out / "box_2025-26.json").write_text(json.dumps(box, ensure_ascii=False), encoding="utf-8")
    prior = parse_per_game(PRIOR_HTML)
    (out / "prior_2024-25.json").write_text(json.dumps(prior, ensure_ascii=False), encoding="utf-8")
    prev = parse_per_game(PREV_HTML)
    (out / "prior_2023-24.json").write_text(json.dumps(prev, ensure_ascii=False), encoding="utf-8")
    pos = parse_per_game(raw / "per_game_2025-26.html")
    (out / "positions_2025-26.json").write_text(json.dumps([{"player": r["player"], "pos": r["pos"]}
                                                             for r in pos], ensure_ascii=False),
                                                encoding="utf-8")
    print(f"{len(box)} player-games, {len(prior)} 2024-25 per-game rows, {len(pos)} positions")


# -----------------------------------------------------------------------------
# run
# -----------------------------------------------------------------------------

def load_season(out: Path) -> ar.Season:
    rd = lambda p: json.loads(Path(p).read_text(encoding="utf-8"))
    return ar.Season.build(rd(LOG), rd(out / "box_2025-26.json"), rd(SCHEDULE), rd(MATCHUPS),
                           rd(out / "prior_2024-25.json"), rd(out / "positions_2025-26.json"),
                           rd(out / "prior_2023-24.json"), rd(DRAFTS))


def move_dict(mo):
    if mo is None:
        return None
    return {"kind": mo.kind, "add": mo.add, "drop": mo.drop, "to_il": mo.to_il,
            "screen_pts": round(mo.screen_points, 2), "screen_starts": round(mo.screen_starts, 3)}


def run_week(season, actuals, week, settings):
    t0 = time.time()
    mon = ar.build_monday(season, week, settings)
    inp = mon.inputs
    t_inputs = time.time() - t0
    stakes = ar.season_stakes(season, mon, settings)
    title0 = ar.stake_units(stakes, inp.drop_config)
    inp.stakes = {m: v for m, v in stakes.items() if m != "_title"}
    t_stakes = time.time() - t0 - t_inputs
    rec = {"week": week, "horizon": list(inp.horizon), "decision_day": mon.decision_day.isoformat(),
           "pool": len(inp.pool), "pool_all": mon.pool_all, "o_tags": sorted(mon.o_tags),
           "long_out": mon.long_out, "title0": title0,
           "rs_title_champ": stakes["_title"], "managers": {}}
    for m in sorted(inp.managers):
        tm = time.time()
        moves = av.candidate_moves(inp, m, settings)
        fin = av.finalists(moves, settings)
        priced = av.price(inp, m, fin, settings)
        fins = []
        for i, p in enumerate(priced):
            real = ar.realised(season, actuals, inp, m, p.move, p.followup_drop)
            fins.append({"id": i, **move_dict(p.move), "followup": p.followup_drop,
                         "dwp": [round(x, 4) for x in p.dwp], "dpts": [round(x, 2) for x in p.dpts],
                         "dstarts": [round(x, 3) for x in p.dstarts], "dT_h": round(p.dT_horizon, 5),
                         "dT_l": round(p.dT_later, 5), "dpl": round(p.dpts_later, 2),
                         "later_by_week": [list(x) for x in p.dpts_later_by_week],
                         "real_pts": real["pts"], "real_flip": real["flip"]})
        picks = {}
        for w in av.WEIGHTINGS:
            r = av.recommend(inp, m, settings, w, priced=priced)
            picks[w.name] = None if r.top is None else priced.index(r.top)
        rules = {}
        for name, fn in (("most_games", av.most_games), ("highest_projection", av.highest_projection)):
            mo = fn(inp, m, settings)
            rules[name] = {"move": move_dict(mo), "real": ar.realised(season, actuals, inp, m, mo)}
        # the common-drop variants: every engine drop any weighting picked, and the cheapest
        drops = {fins[i]["drop"] for i in picks.values() if i is not None and fins[i]["kind"] == "add_drop"}
        cheapest = next((mo.drop for mo in moves if mo.kind == "add_drop"), None)
        if cheapest:
            drops.add(cheapest)
        common = {}
        for d in sorted(x for x in drops if x):
            common[d] = {}
            for name, fn in (("most_games", av.most_games), ("highest_projection", av.highest_projection)):
                mo = fn(inp, m, settings, drop=d)
                common[d][name] = {"move": move_dict(mo), "real": ar.realised(season, actuals, inp, m, mo)}
        # the title-odds estimate against a full season run, for each distinct pick
        checks = []
        for i in sorted({i for i in picks.values() if i is not None}):
            p = priced[i]
            shift = {(m, w): p.dpts[k] for k, w in enumerate(inp.horizon)}
            shift.update({(m, w): d for w, d in p.dpts_later_by_week})
            full = ar.stake_units(ar.season_stakes(season, mon, settings, shift=shift), inp.drop_config)
            checks.append({"id": i, "linear": round(p.dT_horizon + p.dT_later, 5),
                           "full": round(full[m] - title0[m], 5)})
        st = inp.managers[m]
        rec["managers"][m] = {"wp_base": [round(x, 4) for x in priced[0].wp_base] if priced else None,
                              "lbar": round(priced[0].lbar, 5) if priced else 0.0,
                              "n_moves": len(moves), "finalists": fins, "picks": picks, "rules": rules,
                              "common": common, "title_check": checks,
                              "active": len(st.active), "il": len(st.il),
                              "active_capacity": st.active_capacity, "il_capacity": st.il_capacity,
                              "o_on_roster": sorted(n for n in st.roster() if n in mon.o_tags),
                              "seconds": round(time.time() - tm, 2)}
    rec["timing"] = {"inputs": round(t_inputs, 2), "stakes": round(t_stakes, 2),
                     "total": round(time.time() - t0, 2)}
    return rec


def parse_weeks(s):
    out = []
    for part in s.split(","):
        a, _, b = part.partition("-")
        out += list(range(int(a), int(b or a) + 1))
    return out


def cmd_run(a):
    out = Path(a.out)
    rdir = out / "replay"
    rdir.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    season = load_season(out)
    actuals = ar.Actuals(season.games)
    print(f"loaded in {time.time() - t0:.1f}s")
    for w in parse_weeks(a.weeks):
        f = rdir / f"week_{w:02d}.json"
        if f.is_file() and not a.force:
            continue
        if time.time() - t0 > a.budget:
            print("budget reached; run again to continue")
            return
        rec = run_week(season, actuals, w, SETTINGS)
        tmp = f.with_suffix(".tmp")
        tmp.write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")
        tmp.replace(f)
        print(f"week {w}: {rec['timing']['total']}s", flush=True)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fetch"); f.add_argument("--raw", required=True)
    f.add_argument("--last", default="2026-04-05"); f.add_argument("--budget", type=float, default=165)
    p = sub.add_parser("parse"); p.add_argument("--raw", required=True); p.add_argument("--out", required=True)
    r = sub.add_parser("run"); r.add_argument("--out", required=True); r.add_argument("--weeks", default="2-22")
    r.add_argument("--force", action="store_true"); r.add_argument("--budget", type=float, default=120)
    rp = sub.add_parser("report"); rp.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    if a.cmd == "report":
        from scripts.advice_v1_report import report    # noqa: E402
        return report(Path(a.out))
    {"fetch": cmd_fetch, "parse": cmd_parse, "run": cmd_run}[a.cmd](a)


if __name__ == "__main__":
    main()
