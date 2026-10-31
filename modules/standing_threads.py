"""
The four races, every week (display only).

Nick, 10-07: the standing thread shows all four races from the first
newsletter, with their current state; races that resolve become settled
history rather than dropping off. The probabilistic side -- expected
exposure per pot, per manager -- is money_section() below (10-29), read from
the season pass's ledger.

  1. Regular season, weeks 1-15: the $180 pot (3rd and 4th pay), and read
     from the bottom, next year's draft order.
  2. Playoffs, weeks 16-21, best of 3: the $90 pot (each semifinal loser
     pays $45). Not set until the regular season ends.
  3. Cup, seeded on total points over weeks 1-21; played weeks 22-23. No
     cash: the winner keeps one more player than the other three, from the
     following season. 2026-27's is the first Cup this league has played.
  4. Next year's draft order: race 1 read from the bottom -- no term of its
     own. Traded picks give a manager a stake in someone else's finish.

Every money line names the pot and the window (LEAGUE_RULES language rule).
All rules and amounts come from league_config via league_rule().

Dollar figures go by SURFACE (Nick, 10-28, refining 10-14):
  * The Money and Exposure section (money_section) carries its figures every
    week -- that is what a reader goes there for.
  * Everywhere else -- these threads and the newsletter's prose -- an amount
    appears only in the week money was decided (money_events), or when
    something meaningful is genuinely worth saying. The dry run's week 16
    printed every pot and liability again although nothing had moved since
    week 15, and the draft duly said Nick could still pay $45 -- true, scoped,
    and true of all four managers. The rest name the pot ("the
    regular-season pot") without one. The claim check enforces it: a dollar
    figure outside the Money and Exposure block, in a week with no money
    event, is a finding.
The language rule stops a liability line being wrong; this stops it being
obvious.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Optional

from modules.angles import (_cumulative, _game_winner, _records as _wlt,
                            bracket_structure, decided_status, final_order,
                            magic_number)


def _ord(n: int) -> str:
    return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


def _back(x) -> str:
    """Games back: '2', or '1.5' when a T leaves a half game."""
    x = float(x)
    return str(int(x)) if x == int(x) else f"{x:.1f}"


# A settled race in a later week: history, without its dollars.
SETTLED_HISTORY = {
    "clinched_title": "{m} clinched the regular-season title in week {w}",
    "out_of_title": "{m} out of the regular-season title race since week {w}",
    "safe_from_paying": "{m} can't finish {payers} of the regular season "
                        "(settled week {w})",
    "will_pay": "{m} will finish {payers} of the regular season (settled "
                "week {w})",
}

SETTLED = {
    "clinched_title": "{m} clinched the regular-season title and its ${t} in week {w}",
    "out_of_title": "{m} out of the regular-season title race since week {w}",
    "safe_from_paying": "{m} can't finish {payers} of the regular season "
                        "(settled week {w}): won't pay into its ${t} pot",
    "will_pay": "{m} will finish {payers} of the regular season (settled "
                "week {w}): pays ${per} into its ${t} pot",
}


def _decided_series(sm, br, seeds, upto) -> dict:
    """{round kind: [(winner, loser), ...]} for series settled by `upto`."""
    need = lambda r: (r["weeks"][1] - r["weeks"][0]) // 2 + 1  # noqa: E731
    by = {v: k for k, v in seeds.items()}
    out = {}
    semis = next(r for r in br["rounds"] if r["kind"] == "semis")
    winners, losers = [], []
    for s1, s2 in ((1, 4), (2, 3)):
        a, b = by[s1], by[s2]
        wa, wb = _series(sm, a, b, semis["weeks"], upto, seeds, br["tie"])
        if max(wa, wb) >= need(semis):
            w, l = (a, b) if wa > wb else (b, a)
            out.setdefault("semis", []).append((w, l))
            winners.append(w)
            losers.append(l)
    for r in br["rounds"]:
        if r["kind"] == "semis" or upto < r["weeks"][0]:
            continue
        pair = winners if r["kind"] == "final" else losers
        if len(pair) < 2:
            continue
        a, b = pair
        wa, wb = _series(sm, a, b, r["weeks"], upto, seeds, br["tie"])
        if max(wa, wb) >= need(r):
            out.setdefault(r["kind"], []).append((a, b) if wa > wb else (b, a))
    return out


def money_events(sm: list, week: int, season: Optional[str],
                 reg_last: int, pairings=None) -> list:
    """[(event, manager)] that decided money THIS week, and nothing older.

    Regular season: the decided_status delta (clinched or out of the title,
    safe from or bound to pay into its pot). Playoffs: a semifinal settled
    this week (the loser pays into the playoff pot, the winner is clear of
    it) or the final (the champion collects). The Cup pays no money.
    """
    out = []
    if 1 <= week <= reg_last:
        now = decided_status(sm, week, reg_last, pairings)
        before = decided_status(sm, week - 1, reg_last, pairings) if week > 1 else set()
        out += sorted(now - before)
    br = next((b for b in bracket_structure(season) if b["stage"] ==
               "playoffs"), None) if season else None
    if br and week > reg_last:
        seeds = {m: i + 1 for i, m in enumerate(final_order(sm, reg_last))}
        now = _decided_series(sm, br, seeds, week)
        before = _decided_series(sm, br, seeds, week - 1)
        for w, l in now.get("semis", []):
            if (w, l) not in before.get("semis", []):
                out += [("semifinal_lost", l), ("semifinal_won", w)]
        for w, l in now.get("final", []):
            if (w, l) not in before.get("final", []):
                out.append(("playoff_title", w))
    return out


def regular_season(sm, week, reg_last, rules, money=(), pairings=None) -> list[str]:
    upto = min(week, reg_last)
    reg = [m for m in sm if m["week"] <= upto]
    recs, _h2h, _pts = _wlt(reg, upto)
    order = final_order(reg, upto) if reg else []
    rs = rules["league_champion"]
    payers = " or ".join(_ord(p) for p in rules["payer_places"])
    payers_and = " and ".join(_ord(p) for p in rules["payer_places"])
    left = reg_last - upto
    head = (f"Regular season (weeks 1-{reg_last}; the regular-season pot, "
            f"paid into by {payers_and}, and read from the bottom, next "
            f"year's draft order)")
    if not order:
        return [f"{head}: not started."]
    lead = recs[order[0]].standing
    state = " | ".join(f"{m} {recs[m]}"
                       + ("" if i == 0 else f" ({_back(lead - recs[m].standing)} back)")
                       for i, m in enumerate(order))
    out = [f"{head}: {state}"
           + (f"; {left} weeks left." if left else "; final.")]
    mn = magic_number(sm, upto, reg_last)
    first = {}
    for w in range(1, upto + 1):
        for ev, m in decided_status(sm, w, reg_last, pairings):
            first.setdefault((ev, m), w)
    if mn and mn[1] > 0 and not any(ev == "clinched_title"
                                    for ev, _ in first):
        out.append(f"{mn[0]}'s magic number for the title: {mn[1]}.")
    for (ev, m), w in sorted(first.items(), key=lambda x: (x[1], x[0])):
        if (ev, m) not in money:
            out.append("Settled: " + SETTLED_HISTORY[ev].format(
                m=m, w=w, payers=payers) + ".")
            continue
        out.append("Settled this week: " + SETTLED[ev].format(
            m=m, w=w, t=rs["total"], per=rs["per_payer"], payers=payers)
            + (f"; the ${rules['playoff_champion']['total']} playoff pot is "
               "a separate question, open until the semifinals."
               if ev in ("safe_from_paying", "will_pay") and
               week < rules["semis_end"] else "."))
    return out


def _series(sm, a, b, weeks, upto, seeds, tie):
    wa = wb = 0
    for m in sm:
        if weeks[0] <= m["week"] <= min(upto, weeks[1]) and \
                {m["manager_a"], m["manager_b"]} == {a, b}:
            if _game_winner(m, seeds, tie) == a:
                wa += 1
            else:
                wb += 1
    return wa, wb


def bracket(sm, week, br, seeds, rules, title, money=()) -> list[str]:
    """Series and games of one bracket, as far as `week`."""
    by = {v: k for k, v in seeds.items()}
    semis = next(r for r in br["rounds"] if r["kind"] == "semis")
    need = lambda r: (r["weeks"][1] - r["weeks"][0]) // 2 + 1  # noqa: E731
    out, winners, losers = [], [], []
    for s1, s2 in ((1, 4), (2, 3)):
        a, b = by[s1], by[s2]
        wa, wb = _series(sm, a, b, semis["weeks"], week, seeds, br["tie"])
        if max(wa, wb) >= need(semis):
            w, l = (a, b) if wa > wb else (b, a)
            winners.append(w)
            losers.append(l)
            extra = ""
            if br["stage"] == "playoffs" and ("semifinal_lost", l) in money:
                po = rules["playoff_champion"]
                extra = (f" {l} pays ${po['per_payer']} into the "
                         f"${po['total']} playoff pot; {w} is clear of it.")
            out.append(f"{semis['name']}: {w} ({seeds[w]}) beat {l} "
                       f"({seeds[l]}), {max(wa, wb)}-{min(wa, wb)}.{extra}")
        elif wa or wb:
            out.append(f"{semis['name']}: {a} ({s1}) v {b} ({s2}), "
                       f"{wa}-{wb}.")
        else:
            out.append(f"{semis['name']}: {a} ({s1}) v {b} ({s2}).")
    for r in br["rounds"]:
        if r["kind"] == "semis" or week < r["weeks"][0]:
            continue
        pair = winners if r["kind"] == "final" else losers
        if len(pair) < 2:
            continue
        a, b = pair
        wa, wb = _series(sm, a, b, r["weeks"], week, seeds, br["tie"])
        if max(wa, wb) >= need(r):
            w, l = (a, b) if wa > wb else (b, a)
            if r["kind"] == "final":
                po = rules["playoff_champion"]
                cash = (f", and the ${po['total']} playoff pot"
                        if br["stage"] == "playoffs" and
                        ("playoff_title", w) in money else "")
                out.append(f"{r['name']}: {w} won the {title}{cash}, "
                           f"{max(wa, wb)}-{min(wa, wb)} over {l}.")
            else:
                out.append(f"{r['name']}: {w} over {l}, "
                           f"{max(wa, wb)}-{min(wa, wb)} (no stake).")
        else:
            out.append(f"{r['name']}: {a} v {b}, {wa}-{wb}.")
    return out


def playoffs(sm, week, season, reg_last, rules, money=()) -> list[str]:
    br = next((b for b in bracket_structure(season)
               if b["stage"] == "playoffs"), None)
    if br is None:
        return []
    first = min(r["weeks"][0] for r in br["rounds"])
    last = max(r["weeks"][1] for r in br["rounds"])
    head = (f"Playoffs (weeks {first}-{last}; the playoff pot, paid into by "
            f"each semifinal loser)")
    upto = min(week, reg_last)
    reg = [m for m in sm if m["week"] <= upto]
    order = final_order(reg, upto) if reg else []
    if week < first:
        if not order:
            return [f"{head}: not set."]
        return [f"{head}: not set until week {reg_last} ends. If the "
                f"regular season ended today: 1 {order[0]} v 4 {order[3]}, "
                f"2 {order[1]} v 3 {order[2]}."]
    seeds = {m: i + 1 for i, m in enumerate(final_order(sm, reg_last))}
    return [f"{head}:"] + bracket(sm, week, br, seeds, rules,
                                  "playoff championship", money)


def cup(sm, week, season, cup_last, reg_last, rules) -> list[str]:
    br = next((b for b in bracket_structure(season) if b["stage"] == "cup"),
              None)
    prize = ("one more keeper than the other three, from the following "
             "season")
    first_cup = rules.get("cup_first_played") == season
    head = (f"Cup (seeded on total points, weeks 1-{cup_last}; prize: "
            f"{prize}" + ("; the first Cup this league has played" if
                          first_cup else "") + ")")
    upto = min(week, cup_last)
    pts, _ = _cumulative(sm, upto)
    if not pts:
        return [f"{head}: not started."]
    reg_order = final_order([m for m in sm if m["week"] <= min(week, reg_last)],
                            min(week, reg_last))
    finish = {m: i for i, m in enumerate(reg_order)}
    order = sorted(pts, key=lambda m: (-pts[m], finish.get(m, 99)))
    top = pts[order[0]]
    state = " | ".join(f"{m} {pts[m]:.2f}" + ("" if i == 0 else
                                              f" ({top - pts[m]:.2f} back)")
                       for i, m in enumerate(order))
    left = cup_last - upto
    out = [f"{head}: {state}" + (f"; {left} weeks left." if left else
                                  "; seeding final.")]
    if br and week > cup_last:
        seeds = {m: i + 1 for i, m in enumerate(order)}
        out += bracket(sm, week, br, seeds, rules, "Cup")
    return out


def draft_order(sm, week, season, reg_last, pick_ownership) -> list[str]:
    upto = min(week, reg_last)
    reg = [m for m in sm if m["week"] <= upto]
    year = str(int(season[:4]) + 1) if season else ""
    out = []
    if reg:
        order = list(reversed(final_order(reg, upto)))
        out.append(f"Draft order ({year}, from the regular season read from "
                   f"the bottom -- 4th picks first, every round)"
                   + (": " if upto == reg_last else ", if it ended today: ")
                   + ", ".join(order) + ".")
    picks = (pick_ownership or {}).get(year) or {}
    held = defaultdict(list)
    for key, owner in sorted(picks.items()):
        if key.startswith("_"):
            continue
        rnd, orig = key.split("_", 1)
        held[owner].append((int(rnd), orig))
    if held:
        out.append("Traded picks -- a stake in someone else's finish: " +
                   "; ".join(f"{o} holds " + ", ".join(
                       f"{orig}'s round {r}" for r, orig in sorted(v))
                       for o, v in sorted(held.items())) + ".")
    return out


def rules_from_config() -> dict:
    import re
    from modules.data_loader import league_rule, stage_weeks, CURRENT_SEASON
    rs = league_rule("payouts", "league_champion")
    po = league_rule("payouts", "playoff_champion")
    payers = sorted(int(x) for x in re.findall(r"(\d)(?:st|nd|rd|th)",
                                               rs.get("paid_by") or ""))
    semis = next((r for r in league_rule("postseason_format", "stages",
                                         "playoffs", "rounds")
                  if "semi" in r["name"].lower()), None)
    return {"league_champion": {"total": int(rs["total"]),
                                "per_payer": int(rs["per_payer"])},
            "playoff_champion": {"total": int(po["total"]),
                                 "per_payer": int(po["per_payer"])},
            "payer_places": payers,
            "semis_end": semis["weeks"][1] if semis else 0,
            "cup_first_played": league_rule("payouts", "cup_champion").get(
                "first_played")}


def lines(sm: list, week: int, season: Optional[str], cup_last: Optional[int],
          reg_last: int, pick_ownership: Optional[dict] = None,
          rules: Optional[dict] = None, pairings: Optional[list] = None) -> list[str]:
    rules = dict(rules or rules_from_config())
    # the semifinals of THIS season's bracket (2025-26's were week 22)
    br = next((b for b in bracket_structure(season) if b["stage"] ==
               "playoffs"), None) if season else None
    if br:
        rules["semis_end"] = next(r["weeks"][1] for r in br["rounds"]
                                  if r["kind"] == "semis")
    money = set(money_events(sm, week, season, reg_last, pairings))
    out = regular_season(sm, week, reg_last, rules, money, pairings)
    out += playoffs(sm, week, season, reg_last, rules, money)
    if cup_last:
        out += cup(sm, week, season, cup_last, reg_last, rules)
    out += draft_order(sm, week, season, reg_last, pick_ownership)
    return out



# =============================================================================
# MONEY AND EXPOSURE -- the ledger, as a section (Nick, 10-29)
# =============================================================================
#
# Two currencies, never summed (LEAGUE_RULES.md): dollars from the regular
# season and the playoff bracket; the Cup's prize is a sixth keeper, shown as
# its own probability. Every figure the section prints is written here at the
# precision it is printed (the claim check traces prose to the stats report).
# Clinch and elimination come from races_exact, never from a sampled 1.0.

MONEY_HEADER = "Money and Exposure"
CONFIDENCE_NOTE = ("This early in the season the model runs a little confident: it takes "
                   "today's projections and rosters as right, so the favourites' odds are "
                   "likely a few points high.")
TOTALS_NOTE = ("Season totals hold every roster as it stands apart from the moves the "
               "league's rules force (IL stints and the replacement-level fill-ins they "
               "open), and they run low by design.")
EXACT_TEXT = {
    ("title", "clinched"): "has clinched the regular-season title and its pot",
    ("title", "eliminated"): "is out of the regular-season title race",
    ("league_pot", "safe"): "can't finish in the regular-season pot's paying places",
    ("league_pot", "will_pay"): "will finish in the regular-season pot's paying places",
    ("playoff_pot", "safe"): "won his semifinal and is clear of the playoff pot",
    ("playoff_pot", "will_pay"): "lost his semifinal and owes into the playoff pot",
    ("playoff_champion", "clinched"): "won the playoff championship and its pot",
    ("cup_champion", "clinched"): "won the Cup and its sixth keeper",
}


def _half_up(x: float, nd: int = 0) -> float:
    import math
    f = 10 ** nd
    v = math.floor(abs(x) * f + 0.5) / f
    return v if x >= 0 else -v


def _pc1(p: float) -> float:
    """A probability (0-1) as a percent at one decimal, half up."""
    return _half_up(100.0 * float(p), 1)


def _usd(x: float) -> str:
    v = int(_half_up(float(x)))
    return f"+${v}" if v > 0 else (f"-${-v}" if v < 0 else "$0")


def _poss(name: str) -> str:
    return f"{name}'" if name.endswith("s") else f"{name}'s"


def money_section(sp, without_standins: Optional[dict] = None,
                  rules: Optional[dict] = None, early: Optional[bool] = None) -> dict:
    """The Money and Exposure section's data, every figure at its printed
    precision, and its lines (money_lines). sp: a season pass through the
    playoffs at least (dollars need the bracket). without_standins: {manager:
    title odds (percent) with none of HIS stand-ins} -- the counterfactual the
    assumption line states; required for every manager the plan gave one.
    early: whether to say the model runs a little confident this early in
    the season (default: through the regular season's mid week)."""
    import math
    from modules.data_loader import CURRENT_SEASON
    if sp.through not in ("playoffs", "cup"):
        raise ValueError("the money section needs a pass through the playoffs (dollars come "
                         "from the bracket); this one stopped at the regular season")
    rules = dict(rules or rules_from_config())
    without = dict(without_standins or {})
    need = sorted(m for m, v in (sp.standins or {}).items() if v and m not in without)
    if need:
        raise ValueError(f"no without-stand-ins odds for {need}: the assumption line must "
                         "state what the odds are without them")
    L = sp.ledger()
    exact = sp.exact()
    lc, pc = rules["league_champion"], rules["playoff_champion"]
    most_gain = lc["total"] + pc["total"]
    most_loss = lc["per_payer"] + pc["per_payer"]
    case = lc["total"] - pc["per_payer"]                   # win the pot, lose the semi
    mans = list(sp.managers)
    reg_pts = {m: int(_half_up(float(sp.reg_points[:, i].mean()))) for i, m in enumerate(mans)}
    rows = {}
    for m in mans:
        d = L[m]["dollars"]
        dist = d["distribution"]
        mode_v, mode_p = max(dist.items(), key=lambda kv: (kv[1], kv[0]))
        st = []
        for x in (sp.standins or {}).get(m, []):
            st.append({"week": x["week"], "covers": x["covers"], "level": x["level"]})
        rows[m] = {
            "title_odds": _pc1(d["p_league_champion"]),
            "title_odds_rounded": int(_half_up(100.0 * d["p_league_champion"])),
            "expected_dollars": int(_half_up(d["expected"])),
            "min_dollars": int(d["min"]), "max_dollars": int(d["max"]),
            "most_likely_dollars": int(mode_v), "most_likely_pct": _pc1(mode_p),
            "p_win_rs_lose_semi": _pc1(d["p_win_regular_season_lose_semifinal"]),
            "p_into_league_pot": _pc1(d["p_pays_league_pot"]),
            "p_playoff_champion": _pc1(d["p_playoff_champion"]),
            "p_into_playoff_pot": _pc1(d["p_pays_playoff_pot"]),
            "p_sixth_keeper": _pc1(L[m]["keeper"]["p_sixth_keeper_next_season"]),
            "season_points": reg_pts[m],
            "standins": st,
            "title_odds_without_standins": (int(_half_up(without[m])) if m in without else None),
            "exact": exact.get(m, {}),
        }
    order = sorted(mans, key=lambda m: (-rows[m]["title_odds"], m))
    if early is None:
        from modules.data_loader import SEASON_STRUCTURE
        R = int((SEASON_STRUCTURE.get(CURRENT_SEASON) or {}).get("regular_through") or 0)
        early = bool(R) and sp.current_week <= math.ceil(R / 2)
    out = {
        "header": MONEY_HEADER, "week": int(sp.current_week), "season": CURRENT_SEASON,
        "sims": int(sp.num_simulations), "seed": int(sp.seed),
        "pots": {"regular_season": {"total": lc["total"], "per_payer": lc["per_payer"],
                                    "payer_places": list(rules["payer_places"])},
                 "playoff": {"total": pc["total"], "per_payer": pc["per_payer"]},
                 "cup": "no cash: the winner keeps a sixth player the following season"},
        "range": {"most_gain": most_gain, "most_loss": most_loss},
        "win_rs_lose_semi_dollars": case,
        "order": order, "managers": rows, "early": early,
        "confidence_note": CONFIDENCE_NOTE if early else None,
        "totals_note": TOTALS_NOTE,
    }
    out["lines"] = money_lines(out)
    return out


def _covers_text(st: list) -> str:
    il = [_poss(x["covers"]) + " IL stint" for x in st if x["covers"]]
    opn = sum(1 for x in st if not x["covers"])
    parts = il + (["an open roster spot"] if opn == 1 else
                  [f"{opn} open roster spots"] if opn else [])
    return parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " and " + parts[-1]


def money_lines(ms: dict) -> list:
    """The section's sentences, in the order the handoff set: what is still
    movable; the named outcome, the +$135 case first; the title odds with
    what they assume; expected dollars; season points with what they are
    conditional on; the Cup in its own currency."""
    rows, order = ms["managers"], ms["order"]
    nxt = f"{int(ms['season'][:4]) + 1}-{(int(ms['season'][:4]) + 2) % 100:02d}"
    pr = ms["pots"]
    out = []
    # 1. what is still movable (races_exact)
    settled = [(m, race, st) for m in order for race, st in rows[m]["exact"].items()
               if (race, st) in EXACT_TEXT]
    if not settled:
        out.append(f"Nothing is settled: every manager can still finish anywhere from "
                   f"-${ms['range']['most_loss']} to +${ms['range']['most_gain']} across the "
                   f"regular-season pot and the playoff pot.")
    else:
        out.append("Settled so far: " + "; ".join(
            f"{m} {EXACT_TEXT[(race, st)]}" for m, race, st in settled) + ".")
    # 2. the named outcome: win the regular season, lose the semifinal
    case = ms["win_rs_lose_semi_dollars"]
    by_case = sorted(order, key=lambda m: (-rows[m]["p_win_rs_lose_semi"], m))
    top = by_case[0]
    r = rows[top]
    mode = r["most_likely_dollars"] == case
    out.append(
        (f"{_poss(top)} single most likely outcome is +${case} ({r['p_win_rs_lose_semi']}%)"
         if mode else
         f"The likeliest +${case} finish is {_poss(top)} ({r['p_win_rs_lose_semi']}%)")
        + f": he wins the regular-season pot (${pr['regular_season']['total']}, from "
          f"{' and '.join(_ord(x) for x in pr['regular_season']['payer_places'])}) and loses "
          f"his playoff semifinal (${pr['playoff']['per_payer']} into the playoff pot). "
          f"The same finish for the others: "
        + ", ".join(f"{m} {rows[m]['p_win_rs_lose_semi']}%" for m in by_case[1:]) + ".")
    # 3. title odds, rounded, and what they assume
    out.append("Regular-season title odds: " + ", ".join(
        f"{m} about {rows[m]['title_odds_rounded']}%" for m in order) + "."
        + (f" {ms['confidence_note']}" if ms.get("confidence_note") else ""))
    for m in order:
        st = rows[m]["standins"]
        if not st:
            continue
        lvl = max(x["level"] for x in st if x["level"] is not None)
        wk = min(x["week"] for x in st)
        one = len(st) == 1
        out.append(f"{_poss(m)} odds assume he fills {_covers_text(st)} with "
                   + ("a replacement-level free agent" if one else "replacement-level free agents")
                   + f" ({lvl} FPPG) from week {wk}, as the league's rules allow; without "
                   + ("that pickup" if one else "those pickups")
                   + f" he is at about {rows[m]['title_odds_without_standins']}%, and a better "
                   "real pickup raises it.")
    # 4. expected dollars
    out.append("Expected net dollars across both pots, an average over the simulated seasons "
               "rather than a forecast of any one: "
               + ", ".join(f"{m} {_usd(rows[m]['expected_dollars'])}" for m in order) + ".")
    # 5. season points, with what they are conditional on
    out.append("Projected regular-season points: " + ", ".join(
        f"{m} {rows[m]['season_points']:,}" for m in order) + f". {ms['totals_note']}")
    # 6. the Cup, its own currency
    out.append(f"The Cup carries no cash; its winner keeps a sixth player in {nxt}. Chance of "
               "that sixth keeper, never added to the dollars: "
               + ", ".join(f"{m} {rows[m]['p_sixth_keeper']}%" for m in order) + ".")
    return out


MONEY_COLUMNS = ("Manager", "Title odds %", "Expected net $", "Range $", "Most likely $",
                 "Win RS, lose semi %", "Into RS pot %", "Playoff champion %",
                 "Into playoff pot %", "Cup: sixth keeper %")


def money_table_rows(ms: dict) -> list:
    """[[cell text]] for the section's table, one row per manager, in order."""
    rows = []
    for m in ms["order"]:
        r = ms["managers"][m]
        rows.append([m, f"{r['title_odds']:.1f}", _usd(r["expected_dollars"]),
                     f"{_usd(r['min_dollars'])} to {_usd(r['max_dollars'])}",
                     f"{_usd(r['most_likely_dollars'])} ({r['most_likely_pct']:.1f}%)",
                     f"{r['p_win_rs_lose_semi']:.1f}", f"{r['p_into_league_pot']:.1f}",
                     f"{r['p_playoff_champion']:.1f}", f"{r['p_into_playoff_pot']:.1f}",
                     f"{r['p_sixth_keeper']:.1f}"])
    return rows


# The page's two tables (Nick, 10-30: the one 10-column table scrolled
# sideways even on a desktop, and managers read this on their phones). The
# Range column is gone from the page -- it is the same for every manager
# every week (the pots' rule: -$135 to +$270), and the drafter's paragraph
# states it. The md (Step 6.5) keeps MONEY_COLUMNS, Range included.
MONEY_PAGE_TABLES = (
    ("Title and money", ("Manager", "Title odds %", "Expected net $", "Most likely $")),
    ("Pots and the Cup", ("Manager", "Win RS, lose semi %", "Into RS pot %", "Playoff champ %",
                          "Into playoff pot %", "Cup 6th keeper %")),
)


def money_page_rows(ms: dict) -> tuple:
    """([[cells]] of the title-and-money table, [[cells]] of the pots table),
    one row per manager, in order."""
    title, pots = [], []
    for m in ms["order"]:
        r = ms["managers"][m]
        title.append([m, f"{r['title_odds']:.1f}", _usd(r["expected_dollars"]),
                      f"{_usd(r['most_likely_dollars'])} ({r['most_likely_pct']:.1f}%)"])
        pots.append([m, f"{r['p_win_rs_lose_semi']:.1f}", f"{r['p_into_league_pot']:.1f}",
                     f"{r['p_playoff_champion']:.1f}", f"{r['p_into_playoff_pot']:.1f}",
                     f"{r['p_sixth_keeper']:.1f}"])
    return title, pots


def render_money_html(ms: Optional[dict], summary_html: str = "") -> str:
    """The section as the page shows it: the heading, the two tables, then
    the drafter's paragraph(s) -- prose after the tables it describes (Nick,
    10-30), and nothing after it. The section's own sentences (ms["lines"])
    stay in the report and Step 6.5's md, where the writer works from them;
    the paragraphs are written from the same facts and claim-checked.
    "" without data."""
    import html as _h
    if not ms or not ms.get("managers"):
        return ""
    tables = []
    for (caption, cols), rows, cls in zip(MONEY_PAGE_TABLES, money_page_rows(ms),
                                          ("mx-money", "mx-pots")):
        head = "".join(f"<th>{_h.escape(c)}</th>" for c in cols)
        body = "".join("<tr>" + "".join(f"<td>{_h.escape(c)}</td>" for c in row) + "</tr>"
                       for row in rows)
        tables.append(f'<h4 class="mx-caption">{_h.escape(caption)}</h4>'
                      f'<div class="table-wrapper"><table class="mx-table {cls}"><thead><tr>'
                      f'{head}</tr></thead><tbody>{body}</tbody></table></div>')
    summ = f'<div class="mx-summary">{summary_html}</div>' if summary_html else ""
    return f"""
    <div class="mx-block" data-viz="money-exposure">
      <h3 class="section-title">{_h.escape(MONEY_HEADER)}</h3>
      {"".join(tables)}
      {summ}
    </div>"""
