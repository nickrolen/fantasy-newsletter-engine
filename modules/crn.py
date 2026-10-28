"""
crn.py -- common random numbers. The one implementation.

Every keyed draw in the engine comes from here: marginal_value (C1), the
absence model (A2) and the betting simulator. A draw is a pure function of
its key; there is no shared stream, so asking another question, adding a
player, tagging one or pricing matchups in another order cannot move it.

    keyed_rng(*parts)                    a numpy Generator for that key
    keyed_uniforms(seed, ns, *key, n=)   n uniforms in [0, 1)
    keyed_normals(seed, ns, *key, n=)    n standard normals

The key is "|".join of the parts (dates as ISO strings), hashed with
blake2b-64. The ITERATION is the array position, never part of the key: one
call per entity returns all n simulations, and simulation i reads index i.
The same key with a larger n extends the same sequence (numpy's Generator
is a stream), so n=500 is a prefix of n=5000.

Namespaces in use (one per kind of draw, so two kinds never share numbers):
    absence   (seed, "absence", player, anchor)   A2 block length
    avail     (seed, "avail", player, date)       return_games pro-rating
    game      (seed, "game", player, date)        a game's fantasy points
    noise     (seed, "noise", manager, week_start) team-level weekly noise
    tie       (seed, "tie", matchup_id, week)     simulated-tie coin flip
    projection_error (seed, "projection_error", player)  his true level for
                                                  the whole simulated season
                                                  (one draw; no week, no date)
    baseline  (seed, "baseline", season, player)  untagged absences, the
                                                  whole season's chain; drawn
                                                  as an [n, games + 1] block
                                                  (row-major, so still
                                                  prefix-stable in n)
Both engines (simulator_betting, marginal_value) draw availability from these
same keys, so for one seed and n they agree on who is out.
"""

from __future__ import annotations

import hashlib
from datetime import date

import numpy as np


def _part(x) -> str:
    return x.isoformat() if isinstance(x, date) else str(x)


def key_string(*parts) -> str:
    return "|".join(_part(p) for p in parts)


def keyed_rng(*parts) -> np.random.Generator:
    h = hashlib.blake2b(key_string(*parts).encode(), digest_size=8).digest()
    return np.random.default_rng(int.from_bytes(h, "little"))


def keyed_uniforms(seed, namespace: str, *key, n: int) -> np.ndarray:
    return keyed_rng(seed, namespace, *key).random(n)


def keyed_normals(seed, namespace: str, *key, n: int) -> np.ndarray:
    return keyed_rng(seed, namespace, *key).standard_normal(n)
