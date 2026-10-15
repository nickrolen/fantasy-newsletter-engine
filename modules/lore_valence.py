"""lore_valence.py -- whose entry is favourable, and to whom.

Valence was a single string per entry. That is wrong for any entry naming
two managers, because the same sentence is favourable to one and damning to
the other:

    "Nick has been known to reach in trades, especially when dealing with
     Benton."                                 valence: negative

Negative about Nick. Flattering to Benton. Tallied by manager, the scalar
counted it as a negative for BOTH, so Benton looked more harshly drawn than
he is and Garrett looked kinder. Measured 10-15: the scalar tally said
Benton 2 positive / 4 negative and Garrett 3/3, while the true figures are
Benton 3/3 and Garrett 2/4.

So valence is now a mapping, manager -> positive | negative | neutral:

    "valence": {"Nick": "negative", "Benton": "positive"}

Only managers are keyed. Entries also name NBA players in `entities`, and a
player has no standing in the balance the field exists to measure.

This module is the ONE place the tally is computed. The bug above was a
by-hand count done twice; a second implementation of balance() is how it
comes back.
"""

from __future__ import annotations

import collections
from typing import Iterable, Optional

from modules.data_loader import MANAGERS

LABELS = ("positive", "negative", "neutral")


def managers_in(entry: dict) -> list[str]:
    """Managers named in an entry, in MANAGERS order."""
    named = set(entry.get("entities") or [])
    return [m for m in MANAGERS if m in named]


def valence_for(entry: dict, manager: str) -> Optional[str]:
    """This entry's valence toward one manager, or None if unlabelled.

    Accepts the retired scalar form so a half-migrated file reads rather
    than raising -- but a scalar is only honoured when the entry names
    exactly one manager. On a multi-manager entry the scalar is precisely
    the ambiguity this module exists to remove, so it is refused.
    """
    v = entry.get("valence")
    if isinstance(v, dict):
        got = v.get(manager)
        return got if got in LABELS else None
    if v in LABELS:
        named = managers_in(entry)
        if len(named) == 1 and named[0] == manager:
            return v
    return None


def balance(entries: Iterable[dict]) -> dict[str, collections.Counter]:
    """{manager: Counter({positive, negative, neutral})} over the entries given.

    Filter for status and kind before calling: this counts what it is handed.
    """
    out = {m: collections.Counter() for m in MANAGERS}
    for e in entries:
        for m in managers_in(e):
            v = valence_for(e, m)
            if v:
                out[m][v] += 1
    return out


def missing_labels(entries: Iterable[dict]) -> list[tuple[str, str]]:
    """(entry id, manager) for every manager named without a valence.

    An unlabelled manager is not the same as a neutral one: neutral is a
    judgement, missing is an omission, and a tally cannot tell them apart
    unless one of them is reported.
    """
    out = []
    for e in entries:
        for m in managers_in(e):
            if valence_for(e, m) is None:
                out.append((e.get("id", "<no id>"), m))
    return out


def format_balance(entries: Iterable[dict]) -> str:
    """The tally as text, for review_lore and the drafting chat."""
    bal = balance(entries)
    width = max((len(m) for m in bal), default=8)
    lines = []
    for m, c in bal.items():
        total = sum(c.values())
        lines.append(f"  {m:<{width}}  n={total:<3} "
                     f"positive={c['positive']:<3} negative={c['negative']:<3} "
                     f"neutral={c['neutral']}")
    gaps = [m for m, c in bal.items() if c["positive"] and not c["negative"]]
    gaps += [m for m, c in bal.items() if c["negative"] and not c["positive"]]
    if gaps:
        lines.append(f"  one-sided: {', '.join(sorted(set(gaps)))}")
    return "\n".join(lines)
