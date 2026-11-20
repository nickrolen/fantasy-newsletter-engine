"""
hub_v2/text.py -- clean() for the new hub's renderers (5c): the payload
string, lore-tag-free and HTML-escaped (live_lines_page.clean, rule 21), and
NOTHING ELSE.

Why (5c, Nick's phone, 11-20): League > History > Champions printed a team's
whole dict as its name -- "{'cls': 'lh-t-orange', 'slot': ...}" -- because the
view replaced a string with a dict and str() printed it. The renderers print
strings; a dict, a list, a bool, None or a number reaching one is a bug at its
source (the engine or the view), so this clean() RAISES on anything that is
not a str instead of printing its repr. Fix the source, never convert at the
call.
"""
from __future__ import annotations

from ..live_lines_page import clean as _clean


class NotAString(TypeError):
    """A renderer was handed something that is not a payload string."""


def clean(value) -> str:
    if type(value) is not str:
        r = repr(value)
        raise NotAString(f"clean() takes a payload string, not {type(value).__name__}: "
                         f"{r[:80] + '...' if len(r) > 80 else r}")
    return _clean(value)
