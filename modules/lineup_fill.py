"""
lineup_fill.py -- the one exact daily lineup fill.

Three lineup models used to coexist: a player-first greedy in
schedule_strength, a slot-first greedy in lineup_optimizer, and an
unconstrained top-10 in the simulators. Neither greedy is a maximum
matching: on 26 of 627 manager-days in 2025-26 the player-first greedy
benched a player who could have started (5-12 starts per team), and in the
C5 grid that showed up as a hole sitting next to benched players with games.

WHY THIS IS EXACT
-----------------
A daily lineup is a matching of players to seats. The sets of players that
can all be seated at once form a transversal matroid. Value sits on the
player (his projection), not on the seat he takes, so the matroid greedy --
take players in descending projection, keep each one if an augmenting path
seats him -- returns a maximum-weight independent set. Since every weight
is positive, that set is also maximum-cardinality. One pass gives both:
the most starters, and the most projected points among lineups that size.

On 20,000 random rosters it was never worse than the old greedy on
projected points. About 40 microseconds a manager-day.

Ties in projection break by input order, so callers that need a stable
answer pass players in a stable order.

marginal_value (C1) is a DIFFERENCE of two fills; any fill error lands in
the answer whole. That is why this exists before C1.
"""

from __future__ import annotations

from typing import Hashable, Sequence

# (slot name, eligible positions, capacity). Most restrictive first: the
# seat search tries them in this order, which keeps flexible seats (G, F,
# Util) open when a choice exists -- only cosmetic, for which seats are
# reported open; the started SET does not depend on it.
SEAT_DEFINITIONS = (
    ("PG", frozenset({"PG"}), 1),
    ("SG", frozenset({"SG"}), 1),
    ("SF", frozenset({"SF"}), 1),
    ("PF", frozenset({"PF"}), 1),
    ("C", frozenset({"C"}), 2),
    ("G", frozenset({"PG", "SG"}), 1),
    ("F", frozenset({"SF", "PF"}), 1),
    ("Util", frozenset({"PG", "SG", "SF", "PF", "C"}), 2),
)

SEATS = tuple((name, elig) for name, elig, cap in SEAT_DEFINITIONS for _ in range(cap))
NUM_SEATS = len(SEATS)  # 10


def exact_fill(
    players: Sequence[tuple[Hashable, frozenset | set, float]],
    seats: Sequence[tuple[str, frozenset]] = SEATS,
) -> tuple[list, list, dict[int, Hashable]]:
    """Optimal lineup for one day.

    Args:
        players: (key, positions, projection). Any order.
        seats: (slot name, eligible positions), one entry per seat.

    Returns:
        (started keys, benched keys, {seat index: key}). Started and benched
        are in descending projection order.
    """
    order = sorted(range(len(players)), key=lambda i: -players[i][2])
    seat_of: dict[int, int] = {}   # seat index -> player index

    def augment(pi: int, seen: set) -> bool:
        pos = players[pi][1]
        for si, (_name, elig) in enumerate(seats):
            if si in seen or not (pos & elig):
                continue
            seen.add(si)
            if si not in seat_of or augment(seat_of[si], seen):
                seat_of[si] = pi
                return True
        return False

    started, benched = [], []
    for pi in order:
        (started if augment(pi, set()) else benched).append(players[pi][0])
    return started, benched, {si: players[pi][0] for si, pi in seat_of.items()}


def open_seats(assignment: dict[int, Hashable],
               seats: Sequence[tuple[str, frozenset]] = SEATS) -> list[str]:
    """Slot names of the seats nobody took, in seat order."""
    return [seats[si][0] for si in range(len(seats)) if si not in assignment]


def max_starters(position_sets: Sequence[frozenset | set],
                 seats: Sequence[tuple[str, frozenset]] = SEATS) -> int:
    """How many of these players can start at once."""
    return len(exact_fill([(i, p, 0.0) for i, p in enumerate(position_sets)], seats)[0])
