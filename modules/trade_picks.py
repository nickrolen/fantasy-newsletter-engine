"""trade_picks.py -- the draft picks in the league's trades, from Yahoo's own
transaction records (H56 Part 2; claude/HANDOFF_56_DRAFT_ORDER_PUNT_2026-11-20.md
s.4.1).

data/historical/all_trades.json has players only for 2017-18 to 2024-25. Nick
(11-20): every pick trade went through Yahoo, never only in the group chat, and
his screenshot of Yahoo's 2023-24 trades shows picks ("Round 1", "Round 3")
moving with players. The original pull (scripts/pull_historical_data.py
extract_trades) read trades through yahoo_fantasy_api's League.transactions,
which merges each transaction's parts into one dict, and then read players
only: its "Structure 1: picks" branch treated a pick as a player, and a
trade whose picks it saw would have lost its players, so no pick ever reached
the file (H56_RESULT says which, from the raw responses).

This module only PARSES: scripts/pull_trade_picks.py fetches (one call per
season, Nick runs it) and saves Yahoo's raw JSON; parse() reads it offline.
Nothing here guesses: an unknown shape, a pick without a round or teams, or a
trade that matches no row of all_trades.json RAISES or is reported by name.

WHICH DRAFT A PICK BELONGS TO is not obviously in Yahoo's record. parse()
keeps every field Yahoo gives on the pick; draft_of() decides the draft only
from an explicit field, else from the rule draft_rule states (a pick traded
before a season's opening day is for that season's draft, after it for the
next one), and marks which. Nick confirms the rule in the result.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Optional

PICK_FIELDS = ("round", "source_team_key", "destination_team_key")
DRAFT_FIELDS = ("season", "draft_season", "year", "draft_year")      # an explicit draft, if Yahoo gives one


class TradeShapeError(ValueError):
    """Yahoo's transaction JSON is not in a shape this parser knows."""


class TradeMatchError(ValueError):
    """A Yahoo trade and all_trades.json disagree."""


class KeeperRoundPick(ValueError):
    """A traded pick numbered in a keeper round. Keeper rounds can't be traded
    (Nick, 11-21: "its literally impossible to trade a keeper round pick"), so
    this is a data error: corrected by a ruling (ROUND_CORRECTIONS) or raised,
    never shown or valued (LEAGUE_RULES "Traded draft picks")."""


# Nick's rulings on Yahoo's pick records (LEAGUE_RULES "Traded draft picks", 11-21).
# Keyed by Yahoo's transaction key and the pick's (original team key, Yahoo round).
ROUND_CORRECTIONS = {
    ("466.l.42309.tr.203", "466.l.42309.t.3", 15): {
        "round": 9, "note": "Yahoo records round 15 (a keeper round); it was Hayden's 9th: the label, "
                            "TRADES.json and the 2026-27 draft agree (Nick, 11-21)"},
}

# Picks Yahoo records in a trade that the league reversed outside Yahoo (Nick's
# rulings). Keyed like ROUND_CORRECTIONS, by Yahoo's transaction key and the
# pick's (original team key, Yahoo round). A reversed pick leaves the trade:
# add_picks moves it from "draft_picks" to "draft_picks_reversed" with the
# note, so nothing shows it, values it or counts it, and the record of what
# Yahoo says and why it doesn't stand stays in the file. A ruling that matches
# no pick RAISES (add_picks), so a stale one can't silently do nothing.
_FEB26_2024 = ("Reversed outside Yahoo (Nick, 11-21): the 2024-25 draft doesn't reflect this swap "
               "(Nick picked twice in round 3, at 9 and 12, the second from the Jan 15 trade; Benton "
               "made his own round-4 pick at 13), so both picks come off this trade")
PICK_REVERSALS = {
    ("428.l.83508.tr.220", "428.l.83508.t.1", 3): {"note": _FEB26_2024},     # Nick's 2024 3rd, to Benton
    ("428.l.83508.tr.220", "428.l.83508.t.4", 4): {"note": _FEB26_2024},     # Benton's 2024 4th, to Nick
}


class StaleRuling(ValueError):
    """A ruling in ROUND_CORRECTIONS or PICK_REVERSALS that matches no pick."""


COMPLETED = "successful"        # Yahoo's status for a completed trade; anything else (vetoed) is not a trade


# ---------------------------------------------------------------------------
# Yahoo's JSON
# ---------------------------------------------------------------------------

def _items(node) -> list:
    """Yahoo's collections: {"0": {...}, "1": {...}, "count": n} or a list."""
    if isinstance(node, list):
        return node
    if isinstance(node, dict):
        keys = sorted((k for k in node if str(k).isdigit()), key=int)
        if keys or "count" in node:
            return [node[k] for k in keys]
        return [node]
    return []


def _flat(parts) -> dict:
    """A Yahoo object given as a list of one-key dicts (and nested lists) -> one dict."""
    out: dict = {}
    if isinstance(parts, dict):
        return dict(parts)
    for p in parts or []:
        if isinstance(p, list):
            out.update(_flat(p))
        elif isinstance(p, dict):
            out.update(p)
    return out


def transactions(raw: dict) -> list:
    """Every transaction element in a league transactions response: a list of
    its parts (Yahoo gives [meta, {"players": ...}, ...] or a dict)."""
    found = []

    def walk(o):
        if isinstance(o, dict):
            for k, v in o.items():
                if k == "transaction":
                    found.append(v if isinstance(v, list) else [v])
                else:
                    walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(raw)
    return found


def _pick(node) -> dict:
    p = node.get("pick", node) if isinstance(node, dict) else _flat(node)
    p = _flat(p) if isinstance(p, list) else dict(p)
    missing = [f for f in PICK_FIELDS if p.get(f) in (None, "")]
    if missing:
        raise TradeShapeError(f"a traded pick lacks {missing}; its fields are {sorted(p)}")
    try:
        rnd = int(p["round"])
    except (TypeError, ValueError):
        raise TradeShapeError(f"a traded pick's round is {p['round']!r}") from None
    out = {"round": rnd, "source_team_key": str(p["source_team_key"]),
           "destination_team_key": str(p["destination_team_key"]),
           "original_team_key": None if p.get("original_team_key") in (None, "") else str(p["original_team_key"]),
           "fields": sorted(p)}
    for f in DRAFT_FIELDS:
        if p.get(f) not in (None, ""):
            out["draft_field"] = (f, str(p[f]))
            break
    return out


def _player(node) -> dict:
    pl = node.get("player", node) if isinstance(node, dict) else node
    if not isinstance(pl, list) or not pl:
        raise TradeShapeError(f"a traded player is not Yahoo's [meta, transaction_data] list: {type(pl).__name__}")
    meta = _flat(pl[0])
    td = {}
    for part in pl[1:]:
        if isinstance(part, dict) and "transaction_data" in part:
            t = part["transaction_data"]
            td = _flat(t) if isinstance(t, list) else dict(t)
    name = meta.get("name")
    full = name.get("full") if isinstance(name, dict) else name
    if not full or not td.get("source_team_key") or not td.get("destination_team_key"):
        raise TradeShapeError(f"a traded player lacks a name or teams (fields {sorted(meta)}, {sorted(td)})")
    return {"name": str(full), "player_key": meta.get("player_key"),
            "source_team_key": str(td["source_team_key"]), "destination_team_key": str(td["destination_team_key"])}


def not_completed(raw: dict) -> list:
    """[(transaction_key, timestamp, status)] for every trade Yahoo does NOT
    mark completed (vetoed): rows for them are removed from all_trades.json."""
    out = []
    for parts in transactions(raw):
        meta = parts[0] if parts and isinstance(parts[0], dict) else {}
        if meta.get("type") == "trade" and meta.get("status") != COMPLETED:
            out.append((meta.get("transaction_key"), str(meta.get("timestamp")), meta.get("status")))
    return out


def parse(raw: dict) -> list:
    """Every successful trade in one season's raw response, oldest first:
    {"transaction_key", "timestamp", "trader_team_key", "tradee_team_key",
     "players": [...], "picks": [...], "parts": [the keys of each part]}."""
    out = []
    for parts in transactions(raw):
        meta = {}
        players, picks = [], []
        keys = []
        for part in parts:
            if not isinstance(part, dict):
                raise TradeShapeError(f"a transaction part is a {type(part).__name__}")
            keys.append(sorted(part))
            for k, v in part.items():
                if k == "players":
                    players += [_player(x) for x in _items(v)]
                elif k == "picks":
                    picks += [_pick(x) for x in _items(v)]
                else:
                    meta[k] = v
        if meta.get("type") != "trade" or meta.get("status") != COMPLETED:
            continue                     # only completed trades: a vetoed trade is not a trade (Nick, 11-21)
        for f in ("transaction_key", "timestamp", "trader_team_key", "tradee_team_key"):
            if not meta.get(f):
                raise TradeShapeError(f"a trade lacks {f}; its fields are {sorted(meta)}")
        out.append({"transaction_key": meta["transaction_key"], "timestamp": str(meta["timestamp"]),
                    "trader_team_key": meta["trader_team_key"], "tradee_team_key": meta["tradee_team_key"],
                    "players": players, "picks": picks, "parts": keys})
    return sorted(out, key=lambda t: int(t["timestamp"]))


# ---------------------------------------------------------------------------
# which draft, who
# ---------------------------------------------------------------------------

def _next(season: str) -> str:
    a = int(season[:4]) + 1
    return f"{a}-{(a + 1) % 100:02d}"


def draft_of(pick: dict, season: str, traded_on: str, opening_day: Optional[str]) -> tuple:
    """(draft season, how): Yahoo's explicit field if the pick has one, else
    the rule: traded before `season`'s opening day -> `season`'s draft; on or
    after it -> the next season's. Raises without an opening day."""
    if pick.get("draft_field"):
        f, v = pick["draft_field"]
        m = re.fullmatch(r"(\d{4})", v) or re.fullmatch(r"(\d{4})-\d{2}", v)
        if not m:
            raise TradeShapeError(f"a pick's {f} is {v!r}")
        y = int(m.group(1))
        return f"{y}-{(y + 1) % 100:02d}", f"yahoo {f}"
    if not opening_day:
        raise TradeShapeError(f"{season}: no opening day to place a traded pick's draft")
    if traded_on < opening_day:
        return season, "rule: traded before the season's opening day, so this season's draft"
    return _next(season), "rule: traded after the season's opening day, so the next draft"


def day_of(ts: str) -> str:
    """A Yahoo timestamp (epoch seconds) as the league's calendar day (Pacific)."""
    from zoneinfo import ZoneInfo
    return datetime.fromtimestamp(int(ts), tz=timezone.utc).astimezone(ZoneInfo("America/Los_Angeles")).date().isoformat()


def picks_for_file(trade: dict, season: str, managers: dict, opening_day: Optional[str]) -> list:
    """The trade's picks in the file's form: {"round", "draft", "draft_how",
    "original_manager", "from_manager", "to_manager", "source": "yahoo"}
    (+ "corrected" when a ruling fixed Yahoo's round). managers: {team key:
    manager} for the season (data_loader.team_key_managers). A pick in a
    keeper round of a keeper-era draft RAISES KeeperRoundPick unless ruled."""
    from . import draft_history as DH
    out = []
    for p in trade["picks"]:
        who = {}
        for k in ("source_team_key", "destination_team_key", "original_team_key"):
            if p.get(k) is None:
                who[k] = None
                continue
            if p[k] not in managers:
                raise TradeMatchError(f"{season}: team key {p[k]} is in no manager map ({sorted(managers)})")
            who[k] = managers[p[k]]
        draft, how = draft_of(p, season, day_of(trade["timestamp"]), opening_day)
        rnd, fix = p["round"], ROUND_CORRECTIONS.get((trade["transaction_key"], p.get("original_team_key"), p["round"]))
        if fix:
            rnd = fix["round"]
        if DH.keeper_era(draft) and rnd > DH.live_rounds(draft):
            raise KeeperRoundPick(f"{season} {day_of(trade['timestamp'])} {trade['transaction_key']}: "
                                  f"{who['original_team_key']}'s {draft} round {rnd} is a keeper round "
                                  f"({DH.live_rounds(draft)} live): keeper rounds can't be traded; add a ruling")
        e = {"round": rnd, "draft": draft, "draft_how": how, "original_manager": who["original_team_key"],
             "from_manager": who["source_team_key"], "to_manager": who["destination_team_key"], "source": "yahoo"}
        if fix:
            e["corrected"] = fix["note"]
        rev = PICK_REVERSALS.get((trade["transaction_key"], p.get("original_team_key"), p["round"]))
        if rev:
            e["reversed"] = rev["note"]          # add_picks moves it out of the trade
        out.append(e)
    return out


def rulings_used(matched_trades) -> set:
    """The ruling keys (ROUND_CORRECTIONS and PICK_REVERSALS) that match a
    pick in these Yahoo trades."""
    keys = {(t["transaction_key"], p.get("original_team_key"), p["round"]) for t in matched_trades for p in t["picks"]}
    return {k for k in list(ROUND_CORRECTIONS) + list(PICK_REVERSALS) if k in keys}


def split_reversed(picks: list) -> tuple:
    """(standing picks, reversed picks): a pick with a PICK_REVERSALS ruling
    is not part of the trade."""
    return [p for p in picks if not p.get("reversed")], [p for p in picks if p.get("reversed")]


def label_picks(row: dict, season: str) -> list:
    """Every pick in a row's hand-typed labels ({sender: ["2026 2nd (Nick)"]}),
    structured as picks_for_file's are: this season's trades, from
    config/TRADES.json, before they reach all_trades.json."""
    nxt = _next(season)
    out = []
    for sender, labels in sorted((row.get("picks") or {}).items()):
        ms = [row["trader_manager"], row["tradee_manager"]]
        if sender not in ms:
            raise TradeMatchError(f"{row.get('date')}: a label's sender {sender} is not in the trade {ms}")
        for lab in labels:
            m = re.fullmatch(r"(\d{4}) (\d+)(?:st|nd|rd|th) \((\w+)\)", str(lab).strip())
            if not m:
                raise TradeShapeError(f"a pick label {lab!r} is not 'YYYY Nth (Manager)'")
            y = int(m.group(1))
            draft = f"{y}-{(y + 1) % 100:02d}"
            out.append({"round": int(m.group(2)), "draft": draft,
                        "draft_how": "label" if draft <= nxt else "chat: a draft beyond the next (TRADES.json label)",
                        "original_manager": m.group(3), "from_manager": sender,
                        "to_manager": ms[1] if sender == ms[0] else ms[0],
                        "source": "label" if draft <= nxt else "chat"})
    return out


def chat_picks(row: dict, season: str) -> list:
    """Picks for a draft beyond the next, agreed in the group chat only
    (Nick, 11-21; from 2025-26 on): the row's hand-typed labels ("2027 2nd
    (Hayden)", keyed by the manager who SENT them) for any draft after the
    next one. Their only record; Yahoo has none."""
    nxt = _next(season)
    out = []
    for sender, labels in sorted((row.get("picks") or {}).items()):
        for lab in labels:
            m = re.fullmatch(r"(\d{4}) (\d+)(?:st|nd|rd|th) \((\w+)\)", lab.strip())
            if not m:
                raise TradeShapeError(f"a pick label {lab!r} is not 'YYYY Nth (Manager)'")
            y = int(m.group(1))
            draft = f"{y}-{(y + 1) % 100:02d}"
            if draft <= nxt:
                continue
            ms = [a for a in (row["trader_manager"], row["tradee_manager"])]
            if sender not in ms:
                raise TradeMatchError(f"{row['date']}: a label's sender {sender} is not in the trade {ms}")
            out.append({"round": int(m.group(2)), "draft": draft,
                        "draft_how": "chat: a draft beyond the next (TRADES.json label)",
                        "original_manager": m.group(3), "from_manager": sender,
                        "to_manager": ms[1] if sender == ms[0] else ms[0], "source": "chat"})
    return out


# ---------------------------------------------------------------------------
# all_trades.json
# ---------------------------------------------------------------------------

def _row_key(row: dict) -> tuple:
    return (row["season"], frozenset((p["player_name"], p["from_manager"], p["to_manager"]) for p in row["players"]))


def match(rows: list, yahoo: dict, managers_by_season: dict, names=None) -> tuple:
    """({row index: Yahoo trade}, report). yahoo: {season: parse()'s list}.
    A row matches by Yahoo's timestamp when it has one, else by the season and
    its players moved (name, from, to). names: a callable that canonicalises
    a player name (accents); identity by default."""
    canon = names or (lambda n: n)
    by_ts, by_key = {}, {}
    for s, trades in yahoo.items():
        mg = managers_by_season[s]
        for t in trades:
            by_ts[(s, t["timestamp"])] = t
            moved = frozenset((canon(p["name"]), mg.get(p["source_team_key"]), mg.get(p["destination_team_key"]))
                              for p in t["players"])
            by_key.setdefault((s, moved), []).append(t)
    got, used = {}, set()
    unmatched_rows = []
    for i, r in enumerate(rows):
        if r["season"] not in yahoo:
            continue
        t = by_ts.get((r["season"], str(r.get("timestamp")))) if r.get("timestamp") else None
        if t is None:
            k = (r["season"], frozenset((canon(p["player_name"]), p["from_manager"], p["to_manager"]) for p in r["players"]))
            cands = [x for x in by_key.get(k, []) if x["transaction_key"] not in used]
            t = cands[0] if len(cands) == 1 else None
        if t is None:
            unmatched_rows.append(i)
            continue
        got[i] = t
        used.add(t["transaction_key"])
    extra = [(s, t["transaction_key"], len(t["players"]), len(t["picks"]))
             for s, ts in yahoo.items() for t in ts if t["transaction_key"] not in used]
    return got, {"matched": len(got), "unmatched_rows": unmatched_rows, "yahoo_only": extra}


def add_picks(rows: list, matched: dict, managers_by_season: dict, opening_days: dict, field: str = "draft_picks") -> list:
    """A copy of rows with `field` added to every matched row (an empty list
    when Yahoo shows no pick); nothing else changes."""
    out = []
    for i, r in enumerate(rows):
        r2 = dict(r)
        if i in matched:
            s = r["season"]
            stand, gone = split_reversed(picks_for_file(matched[i], s, managers_by_season[s], opening_days.get(s)))
            r2[field] = stand + chat_picks(r, s)
            if gone:
                r2[field + "_reversed"] = gone
        out.append(r2)
    # a ruling whose transaction is here but whose pick isn't (Yahoo's record moved under it) RAISES
    here = {t["transaction_key"] for t in matched.values()}
    stale = {k for k in set(ROUND_CORRECTIONS) | set(PICK_REVERSALS) if k[0] in here} - rulings_used(matched.values())
    if stale:
        raise StaleRuling(f"rulings that match no pick in these trades: {sorted(stale)}")
    return out


WRITTEN = ("draft_picks", "draft_picks_reversed")       # the fields add_picks writes (a re-run rewrites them)


def players_unchanged(before: list, after: list, written=WRITTEN) -> bool:
    """Every row's players, byte for byte, and every other field but the ones add_picks writes."""
    if len(before) != len(after):
        return False
    for a, b in zip(before, after):
        if json.dumps(a["players"], ensure_ascii=False) != json.dumps(b["players"], ensure_ascii=False):
            return False
        if {k: v for k, v in b.items() if k in a and k not in written} != {k: v for k, v in a.items() if k not in written}:
            return False
    return True


# Nick's screenshot of Yahoo's 2023-24 trades (11-20), as the handoff gives it:
# Jan 15: Stephen Curry + Round 1 to Benton's team; CJ McCollum + Kawhi
# Leonard + Round 3 to Nick's. Feb 26 and Mar 8 also carry picks (rounds not
# given in the handoff): they must carry at least one; their rounds are printed
# for Nick to check against the screenshot.
SCREENSHOT = {"season": "2023-24",
              "2024-01-15": {("Nick", "Benton"): [1], ("Benton", "Nick"): [3]},
              "with_picks": ("2024-02-26",), "no_picks": ("2024-03-07",)}   # Mar 8 (stored Mar 7): none (Nick, 11-21)


def screenshot_check(rows: list, field: str = "draft_picks") -> dict:
    """{"jan15": bool, "rows": {date: [(round, from, to)]}} for 2023-24."""
    out = {"rows": {}, "jan15": False, "later_have_picks": {}}
    for r in rows:
        if r["season"] != SCREENSHOT["season"] or field not in r:
            continue
        # what Yahoo records, reversed picks included (Feb 26: Yahoo has them; a ruling takes them off)
        out["rows"][r["date"]] = [(p["round"], p["from_manager"], p["to_manager"])
                                  for p in r[field] + r.get(field + "_reversed", [])]
    j = out["rows"].get("2024-01-15")
    if j is not None:
        want = sorted((rd, a, b) for (a, b), rds in SCREENSHOT["2024-01-15"].items() for rd in rds)
        out["jan15"] = sorted(j) == want
    for d in SCREENSHOT["with_picks"]:
        if d in out["rows"]:
            out["later_have_picks"][d] = bool(out["rows"][d])
    for d in SCREENSHOT["no_picks"]:
        if d in out["rows"]:
            out["later_have_picks"][d] = not out["rows"][d]          # True = as the screenshot: no pick
    return out


# ---------------------------------------------------------------------------
# showing a pick (H56 s.4.2): "Benton's 2024 3rd", and from the 2024-25 draft
# on what it became: "-> Jalen Duren, 2.03"
# ---------------------------------------------------------------------------

def ordinal(n: int) -> str:
    n = int(n)
    suf = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suf}"


def pick_label(p: dict) -> str:
    """Whose pick, which draft (its year), which round."""
    return f"{p['original_manager']}'s {p['draft'][:4]} {ordinal(p['round'])}"


class Became:
    """What a traded pick became, for drafts whose order is trusted: the pick
    in its round at the ORIGINAL owner's slot (a straight draft: each team's
    slot is the same every round, read from the rounds where every team made
    exactly one pick), made by the pick's final owner. None when the draft's
    order is punted, the draft hasn't happened, or the slot can't be read."""

    def __init__(self, drafts: dict):
        """drafts: {season: [pick rows with pick_number, round, manager,
        player_name, is_keeper]} for trusted seasons (draft_history.order),
        the current season's included."""
        from . import draft_history as DH
        self.slots, self.rows = {}, {}
        for s, rows in drafts.items():
            if not rows or not DH.order_trusted(s):
                continue
            live = [r for r in sorted(rows, key=lambda r: int(r["pick_number"])) if not r.get("is_keeper")]
            by_round: dict = {}
            for r in live:
                by_round.setdefault(int(r["round"]), []).append(r)
            seen: dict = {}
            for rd, ps in by_round.items():
                ms = [r["manager"] for r in ps]
                if len(set(ms)) == len(ms):                       # one pick each: slots readable
                    for i, m in enumerate(ms, 1):
                        seen.setdefault(m, []).append(i)
            slot = {}
            for m, xs in seen.items():
                best = max(set(xs), key=xs.count)
                slot[m] = best
            self.slots[s] = slot
            self.rows[s] = by_round

    def of(self, p: dict) -> Optional[str]:
        s = p["draft"]
        if s not in self.slots:
            return None
        i = self.slots[s].get(p["original_manager"])
        ps = self.rows[s].get(int(p["round"])) or []
        if i is None or i > len(ps):
            return None
        hit = ps[i - 1]
        if hit["manager"] != p["to_manager"] and hit["manager"] != p.get("final_owner"):
            return None
        return f"{hit['player_name']}, {int(p['round'])}.{i:02d}"


def show(p: dict, became: Optional["Became"] = None) -> str:
    """'Benton's 2024 3rd' + ' -> Jalen Duren, 3.02' when known."""
    b = became.of(p) if became is not None else None
    return pick_label(p) + (f" \u2192 {b}" if b else "")
