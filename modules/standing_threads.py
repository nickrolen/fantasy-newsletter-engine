"""
The four races, every week (display only).

Nick, 10-07: the standing thread shows all four races from the first
newsletter, with their current state; races that resolve become settled
history rather than dropping off. Display only -- the probabilistic model
(expected exposure per pot, per manager) comes in November.

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

Dollar figures appear only in the week money was decided (Nick, 10-14).
The dry run's week 16 printed every pot and liability again although
nothing had moved since week 15, and the draft duly said Nick could still
pay $45 -- true, scoped, and true of all four managers. money_events() is
what was decided THIS week; only lines about those carry an amount. The rest
name the pot ("the regular-season pot") without one. The language rule
stops a liability line being wrong; this stops it being obvious.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Optional

from modules.angles import (_cumulative, _game_winner, bracket_structure,
                            check_no_ties, decided_status, final_order,
                            magic_number)


def _ord(n: int) -> str:
    return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


def _records(sm, upto):
    """Wins and losses (check_no_ties has already refused a tied week)."""
    _, wins = _cumulative(sm, upto)
    games = defaultdict(int)
    for m in sm:
        if m["week"] <= upto:
            games[m["manager_a"]] += 1
            games[m["manager_b"]] += 1
    return wins, {m: games[m] - wins[m] for m in games}


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
                 reg_last: int) -> list:
    """[(event, manager)] that decided money THIS week, and nothing older.

    Regular season: the decided_status delta (clinched or out of the title,
    safe from or bound to pay into its pot). Playoffs: a semifinal settled
    this week (the loser pays into the playoff pot, the winner is clear of
    it) or the final (the champion collects). The Cup pays no money.
    """
    out = []
    if 1 <= week <= reg_last:
        now = decided_status(sm, week, reg_last)
        before = decided_status(sm, week - 1, reg_last) if week > 1 else set()
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


def regular_season(sm, week, reg_last, rules, money=()) -> list[str]:
    upto = min(week, reg_last)
    reg = [m for m in sm if m["week"] <= upto]
    wins, losses = _records(reg, upto)
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
    lead = wins[order[0]]
    state = " | ".join(f"{m} {wins[m]}-{losses[m]}"
                       + ("" if i == 0 else f" ({lead - wins[m]} back)")
                       for i, m in enumerate(order))
    out = [f"{head}: {state}"
           + (f"; {left} weeks left." if left else "; final.")]
    mn = magic_number(sm, upto, reg_last)
    first = {}
    for w in range(1, upto + 1):
        for ev, m in decided_status(sm, w, reg_last):
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
          rules: Optional[dict] = None) -> list[str]:
    check_no_ties(sm, reg_last)
    rules = dict(rules or rules_from_config())
    # the semifinals of THIS season's bracket (2025-26's were week 22)
    br = next((b for b in bracket_structure(season) if b["stage"] ==
               "playoffs"), None) if season else None
    if br:
        rules["semis_end"] = next(r["weeks"][1] for r in br["rounds"]
                                  if r["kind"] == "semis")
    money = set(money_events(sm, week, season, reg_last))
    out = regular_season(sm, week, reg_last, rules, money)
    out += playoffs(sm, week, season, reg_last, rules, money)
    if cup_last:
        out += cup(sm, week, season, cup_last, reg_last, rules)
    out += draft_order(sm, week, season, reg_last, pick_ownership)
    return out
