"""The 44-point tap area of a `.v2-tap` element (its ::after) is positioned
against the element itself, never against the page.

Found on the live hub, 11-20 (Nick): rules like `.v2-forget{all:unset;...}`
come after `.v2-tap{position:relative}` with equal or higher specificity, so
`all:unset` put the element back to `position:static`. Its ::after (absolute,
left 0, right 0, top 50%) then took the initial containing block: an invisible
full-width strip across the first screenful. The footer's "Forget this phone"
button came last in the page, so its strip lay on top of everything there:
a tap on the Standings, a History chip or Records cleared the remembered key
and showed the passphrase page.

The rule: every CSS rule that unsets a class worn by a `.v2-tap` element sets
`position:relative` again after `all:unset`.
"""
import re

import test_hub_v2 as T2

RULE = re.compile(r"([^{}]+)\{([^{}]*)\}")
RESTORED = re.compile(r"all:unset;(?:[^}]*;)?position:relative")


def _tap_classes(html: str) -> set:
    out = set()
    for m in re.finditer(r'class="([^"]*)"', html):
        cls = m.group(1).split()
        if "v2-tap" in cls:
            out.update(cls)
    for m in re.finditer(r"'([\w\- ]*\bv2-tap\b[\w\- ]*)'", html):       # the page script's own elements
        out.update(m.group(1).split())
    out.discard("v2-tap")
    return out


def test_every_unset_rule_on_a_tap_element_restores_its_position():
    tap = _tap_classes(T2.render()) | {"v2-forget"}       # the footer's button: publish mode only
    assert {"v2-pl", "lh-name"} <= tap, sorted(tap)
    bad = []
    for m in RULE.finditer(T2.ALL_CSS):
        sel, body = m.group(1).strip(), m.group(2).replace(" ", "")
        if "all:unset" not in body:
            continue
        for one in sel.split(","):
            last = re.split(r"[\s>+~]+", one.strip())[-1]
            if set(re.findall(r"\.([\w-]+)", last)) & tap and not RESTORED.search(body):
                bad.append(one.strip())
    assert not bad, f"all:unset without position:relative on a tap element: {bad}"


def test_the_forget_button_keeps_its_tap_area_on_itself():
    rule = re.search(r"\.v2-forget\{([^}]*)\}", T2.ALL_CSS.replace(" ", "")).group(1)
    assert RESTORED.search(rule), rule
