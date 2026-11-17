"""H51 C: "IL-eligible" and "out" are different sets since 11-16 (Yahoo's
"Additional IL-eligible statuses": roster_moves.il_eligible_tags is O, OFS, Q,
D). Advice v2 reads IL eligibility from the one definition
(move_ledger.tag_il_eligible) and keeps "out" (O/OFS) for its pool filter.
Advice is in shadow: nothing user-visible changes."""
import ast
import inspect
from types import SimpleNamespace

from modules import advice_v2 as av
from modules import move_ledger, roster_plan


def test_the_config_makes_q_and_d_il_eligible_and_not_p():
    assert set(move_ledger.il_eligible_tags()) == {"O", "OFS", "Q", "D"}


def test_a_monday_moves_il_eligibility_is_the_configured_set():
    st = {"Oh": "O", "Ofs": "OFS", "Quinn": "Q", "Dee": "D", "Pea": "P", "Well": "HEALTHY"}
    assert av.monday_il_eligible(list(st), st) == {"Oh", "Ofs", "Quinn", "Dee"}


def test_il_ok_at_a_monday_window_takes_a_q_tag():
    """A Q-tagged active may go into IL at a Monday window (il_add moves),
    and a Q-tagged IL occupant is still IL-eligible there: he stays in."""
    inputs = SimpleNamespace(il_eligible=None, kind=av.MONDAY,
                             statuses={"Quinn": "Q", "Dee": "D", "Pea": "P"})
    assert av.MondayInputs.il_ok(inputs, "Quinn") and av.MondayInputs.il_ok(inputs, "Dee")
    assert not av.MondayInputs.il_ok(inputs, "Pea")
    # the plan's rule at an open window (roster_plan._tag_ok) agrees
    assert roster_plan._tag_ok("Q", roster_plan.rules())


def test_a_q_free_agent_stays_in_the_pool_and_an_o_one_does_not():
    inputs = SimpleNamespace(pool=["Quinn", "Oh", "Well"],
                             status=lambda n: {"Quinn": "Q", "Oh": "O", "Well": "HEALTHY"}[n])
    assert av._healthy_pool(inputs) == ["Quinn", "Well"]


def test_advice_v2_has_no_hard_coded_il_set():
    """OUT_TAGS is "out" and only the pool filter reads it; IL eligibility is
    move_ledger's."""
    src = inspect.getsource(av)
    assert "IL_TAGS" not in src
    users = [n.name for n in ast.walk(ast.parse(src)) if isinstance(n, ast.FunctionDef)
             and "OUT_TAGS" in ast.unparse(n)]
    assert users == ["_healthy_pool"], users
