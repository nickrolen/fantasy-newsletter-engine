"""
hub_moves.py -- the hub's moves: every move of the season, by budget week (task 43).

The hub's "Moves" section used to show the last 7 days. It now shows every
move of the season under a week picker, each move under the BUDGET WEEK it
counts in (LEAGUE_RULES rules 6-7, 14; Nick, 11-05):

  - a Yahoo add is placed by transaction_rulings.add_budget_week, the one
    function that decides an add's week, with the same `ledger` argument
    adds_by_budget_week uses (transaction_rulings.ledger_by_mode: the move
    ledger's claims in "on" mode, the claim_week rulings alone in "shadow").
    Never a second rule;
  - a drop paired with an add (one Yahoo add/drop) is shown with its add;
    a standalone drop and a trade are shown under the week they happened in;
  - a voided add (TRANSACTION_RULINGS "void": Paul George 10-26, Franz Wagner
    10-25) counts nowhere and is HIDDEN (Nick, 11-05: hidden completely, not
    struck). A real drop in the same Yahoo transaction is a real move: it is
    shown as an ordinary drop under the week it happened in (Hayden's
    Wagner add/drop: the Buzelis drop). A move that was only the voided add
    is not shown at all. A later, separate drop of the same player is its own
    transaction and stays (Garrett's Paul George drop, 10-26 07:29);
  - a pre-season move (before the season's first fantasy day; rule 14:
    counted nowhere) is shown under "Pre-season";
  - a group-chat entry in the move ledger that is not applied yet (pending),
    or was flagged (missing, conflict), is shown under its claim week with its
    state. An applied entry is its Yahoo transaction, shown once; a pending
    entry whose adds are already in Yahoo's log (Monday, before the night's
    verification) is shown once, as the Yahoo move. A ledger void is Nick's
    typo (never posted), not a move: not shown;
  - each week opens with the adds each manager used of the budget: the one
    counter's totals (adds_by_budget_week), plus, in "on" mode, the week's
    live chat claims not yet in Yahoo (the power table's own rule). The
    Yahoo adds placed here must equal adds_by_budget_week's, week by week and
    manager by manager, or the build RAISES: the transaction log and the
    synced waivers files disagree, and the page would show two counts.

The page computes nothing: every week's tab is built here, every value a
string (hub_page prints them).
"""

from __future__ import annotations

from datetime import date, datetime

PRE = "pre"


class MovesError(RuntimeError):
    """The moves cannot be placed; the reason is named."""


def _first_day(schedule: dict) -> date:
    starts = [date.fromisoformat(str(w["start_date"])[:10]) for w in (schedule or {}).get("weeks", [])]
    if not starts:
        raise MovesError("no fantasy weeks in config/SCHEDULE.json: no move can be placed")
    return min(starts)


def _weeks(schedule: dict) -> dict:
    return {int(w["week"]): (date.fromisoformat(str(w["start_date"])[:10]),
                             date.fromisoformat(str(w["end_date"])[:10]))
            for w in (schedule or {}).get("weeks", [])}


def week_label(w: int, weeks: dict) -> str:
    a, b = weeks[w]
    tail = f"{b.day}" if b.month == a.month else f"{b.strftime('%b')} {b.day}"
    return f"Week {w} \u00b7 {a.strftime('%b')} {a.day}\u2013{tail}"


def happened_in(t: dict, first: date):
    """The week a transaction happened in (its logged fantasy week, the league
    clock), PRE before the season, else RAISES (after the season, or a
    logged week of None inside it)."""
    if t.get("fantasy_week") is not None:
        return int(t["fantasy_week"])
    if date.fromisoformat(t["league_day"]) < first:
        return PRE
    raise MovesError(f"transaction {t['key']} ({t['league_day']}) is in no fantasy week and not "
                     "before the season: it cannot be placed")


def _voided(rulings, day: str, manager: str, player: str) -> bool:
    return any(r.kind == "void" and r.matches(day, manager, "add", player) for r in rulings)


def place(t: dict, rulings, schedule: dict, ledger, first: date) -> dict:
    """Where one logged transaction is shown: {"bucket": week | PRE, "adds":
    [(manager, player)] that count there, "void": [players whose add is
    voided]}. Adds through add_budget_week; RAISES on an add that counts
    nowhere for no recorded reason, and on two adds of one transaction
    counting in different weeks (one move, one week)."""
    from . import transaction_rulings as tr
    when = happened_in(t, first)
    adds = [p for p in t["players"] if p["action"] == "add" and (p.get("to") or {}).get("type") == "team"]
    if t["type"] == "trade" or not adds:
        return {"bucket": when, "adds": [], "void": []}
    buckets, counted, void = set(), [], []
    for p in adds:
        m, n = p["to"]["manager"], p["name"]
        bw = tr.add_budget_week({"date": t["league_day"], "manager": m, "player": n}, rulings, schedule,
                                ledger)
        if bw is not None:
            buckets.add(int(bw))
            counted.append((m, n))
        elif _voided(rulings, t["league_day"], m, n):
            buckets.add(when)
            void.append(n)
        elif when == PRE:
            buckets.add(PRE)
        else:
            raise MovesError(f"the add {t['league_day']} {m} {n} counts in no week, and it is neither "
                             "voided nor pre-season: it cannot be placed")
    if len(buckets) != 1:
        raise MovesError(f"transaction {t['key']} has adds counting in different weeks "
                         f"({sorted(map(str, buckets))}): one move is shown in one week")
    return {"bucket": buckets.pop(), "adds": counted, "void": void}


def yahoo_item(t: dict, pl: dict, schedule: dict):
    """transaction_log.feed_item with every voided add left out (task 45:
    hidden, not struck), or None when nothing else was in the move. What is
    left of an add/drop is shown as what it now is (a drop). When the add
    counts in a week other than the one it happened in and no ruling says so:
    "week N claim"."""
    from . import transaction_log as tlog
    it = tlog.feed_item(t, schedule)
    it["parts"] = [dict(x) for x in it["parts"]]
    for n in pl["void"]:
        hit = [x for x in it["parts"] if x["kind"] == "add" and x["text"] == f"added {n}"]
        if len(hit) != 1:
            raise MovesError(f"transaction {t['key']}: the voided add of {n} is not one part of its move")
        it["parts"].remove(hit[0])
    if pl["void"]:
        if not it["parts"]:
            return None                                  # only the voided add: no move to show
        it["what"] = ", ".join(x["text"] for x in it["parts"])
        it["note"] = "; ".join(x for x in it["note"].split("; ") if x and x != "voided: counts nowhere")
        kinds = {x["kind"] for x in it["parts"]}
        it["kind"] = "add" if kinds == {"add"} else "drop" if kinds == {"drop"} else "add-drop"
    when = t.get("fantasy_week")
    if isinstance(pl["bucket"], int) and when is not None and pl["bucket"] != int(when) \
            and f"week {pl['bucket']}" not in it["note"]:
        it["note"] = "; ".join(x for x in (it["note"], f"week {pl['bucket']} claim") if x)
    return it


def by_week(transactions: list, rulings, schedule: dict, ledger, counts: dict, *, week: int,
            managers, budget: int, mode: str, ledger_entries=(), ledger_states=(),
            live_claims=()) -> dict:
    """The moves block: one tab per week from Pre-season (if any move is
    pre-season) to `week`, the current one by default. `counts` is
    adds_by_budget_week's {budget week: {manager: [players]}} (by mode);
    `live_claims` the hub view's live chat claims (move_ledger.hub_view)."""
    from . import move_ledger as ml
    first = _first_day(schedule)
    weeks = _weeks(schedule)
    if mode not in ml.MODES:
        raise MovesError(f"ledger mode {mode!r}: one of {ml.MODES}")
    buckets: dict = {}
    placed: dict = {}
    for t in transactions:
        pl = place(t, rulings, schedule, ledger, first)
        it = yahoo_item(t, pl, schedule)
        if it is not None:
            buckets.setdefault(pl["bucket"], []).append(it)
        for m, n in pl["adds"]:
            placed.setdefault(pl["bucket"], {}).setdefault(m, []).append(n)

    # the one counter's totals and the log's placement must be the same adds
    def norm(c):
        from .transaction_log import strip_accents
        return {int(w): {m: sorted(strip_accents(n) for n in v) for m, v in by.items() if v}
                for w, by in c.items() if any(by.values())}
    if norm(placed) != norm(counts):
        a, b = norm(placed), norm(counts)
        diff = [f"week {w} {m}: log {a.get(w, {}).get(m, [])} vs counter {b.get(w, {}).get(m, [])}"
                for w in sorted(set(a) | set(b)) for m in sorted(set(a.get(w, {})) | set(b.get(w, {})))
                if a.get(w, {}).get(m, []) != b.get(w, {}).get(m, [])]
        raise MovesError("the transaction log's adds, placed by add_budget_week, differ from "
                         "adds_by_budget_week's (the synced waivers files): " + "; ".join(diff)
                         + ". Run python scripts\\nightly.py (or python scripts\\state.py pull)")

    # the ledger: entries not yet applied (or flagged), under their claim week
    for e in ledger_entries:
        st = ml.state_of(e, ledger_states)
        if st not in ("pending", "missing", "conflict"):
            continue
        claims = [{"manager": e["parsed"]["manager"], "player": n, "window": e["window"]}
                  for n in (e["parsed"].get("add") or [])] if e["kind"] == "move" else []
        if st == "pending" and claims and all(ml.claim_in_log(transactions, c) for c in claims):
            continue                                   # Yahoo's move shows it
        claimed = datetime.fromisoformat(e["claimed_at"])
        it = ml.feed_item(e, st, claimed, date.fromisoformat(e["window"]))
        buckets.setdefault(int(e["claim_week"]), []).append(it)

    pending = {}
    if mode == "on":                                   # a claim is used once posted (rule 12)
        for c in live_claims:
            if not ml.claim_in_log(transactions, c):
                pending.setdefault(int(c["claim_week"]), {}).setdefault(c["manager"], []).append(c["player"])

    bad = [k for k in buckets if k != PRE and (int(k) > int(week) or int(k) not in weeks)]
    if bad:
        raise MovesError(f"moves placed in week(s) {sorted(bad)}, after the current week {week}: "
                         "a move counts in the week it was made or claimed, never a later one")
    keys = ([PRE] if PRE in buckets else []) + [w for w in sorted(weeks) if w <= int(week)]
    if int(week) not in weeks:
        raise MovesError(f"week {week} is not in config/SCHEDULE.json")
    tabs = []
    for k in keys:
        items = sorted(buckets.get(k, []), key=lambda x: x["_ts"], reverse=True)
        items = [{kk: vv for kk, vv in x.items() if kk != "_ts"} for x in items]
        if k == PRE:
            tabs.append({"key": PRE, "label": "Pre-season", "used": None,
                         "used_note": "Pre-season moves count in no week and have no limit (rule 14).",
                         "items": items})
            continue
        used = []
        for m in managers:
            n = len((counts.get(k) or {}).get(m, [])) + len((pending.get(k) or {}).get(m, []))
            used.append({"manager": m, "text": f"{m} {n} of {budget}", "over": n > int(budget)})
        tabs.append({"key": str(k), "label": week_label(k, weeks), "used": used,
                     "used_note": ("Adds used: a group-chat claim counts the moment it is posted."
                                   if mode == "on" else
                                   "Adds used: a group-chat claim counts in the week it was made "
                                   "once its claim-week ruling is written; listed as Pending until "
                                   "then (the ledger runs in shadow mode)."),
                     "items": items})
    return {"weeks": tabs, "default": str(int(week)),
            "empty": "No moves in this week.",
            "note": ("Every move of the season, under the week whose add budget it used: a "
                     "group-chat claim under the week it was claimed in, though it joins the roster "
                     "the next Monday (rule 7); a drop with the add it was paired with; a drop or a "
                     "trade on its own under the week it happened. Times are Pacific.")}


def build(base_path, schedule: dict, week: int, *, managers, budget: int, live_claims=()) -> dict:
    """by_week from the league folder: the transaction log, the rulings, the
    ledger (entries and states) and the mode. RAISES if the log is missing
    (the nightly sync writes it)."""
    from pathlib import Path
    from . import transaction_log as tlog, transaction_rulings as tr, move_ledger as ml
    base = Path(base_path)
    if not (base / tlog.LOG_FILE).is_file():
        raise MovesError(f"{tlog.LOG_FILE.as_posix()} is missing: run python scripts\\nightly.py "
                         "(or python scripts\\sync_transactions.py --nightly)")
    rows = ml.read_rows(base)
    return by_week(tlog.transactions(base), tr.load_all(base, schedule), schedule,
                   tr.ledger_by_mode(base), tr.adds_by_budget_week(base, schedule), week=week,
                   managers=managers, budget=budget, mode=ml.mode(), ledger_entries=ml.entries(rows),
                   ledger_states=ml.read_states(base), live_claims=live_claims)
