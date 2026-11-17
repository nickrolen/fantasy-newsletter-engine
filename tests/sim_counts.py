"""Small simulation counts for tests that exercise code paths, not counts
(task 50, 11-16). Production counts are config (league_config.json
roster_moves.longrun_sims 200, longrun_escalated_sims 800); a real-data
plumbing test that builds the week's report only needs every path to run,
so it states smaller ones. Tests ABOUT a count keep the real one.
"""
from modules import data_loader as dl

LONGRUN_SIMS = 20            # >= 2 (roster_plan.longrun_rules)
LONGRUN_ESCALATED_SIMS = 40  # must exceed LONGRUN_SIMS (roster_plan.escalation_rules)


def small(mp):
    """mp: a pytest MonkeyPatch the caller undoes."""
    rm = dl._LEAGUE_CONFIG["roster_moves"]
    mp.setitem(rm, "longrun_sims", LONGRUN_SIMS)
    mp.setitem(rm, "longrun_escalated_sims", LONGRUN_ESCALATED_SIMS)
