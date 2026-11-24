"""5f item 6: League > Standings > Power rankings by week says why a finished
week is missing. Not a bug: power_history reads each PUBLISHED
stats_report_weekN.json, and week 5's newsletter (the weekly build) was not
built yet on Monday of week 6 (Nick's screenshot, 11-23). One muted line above
the list says when the week appears."""
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).parent))

from modules.hub_v2 import league as L, page, page_league as PL, view   # noqa: E402

LA = ZoneInfo("America/Los_Angeles")
WEEKS = [{"week": w, "start_date": f"2026-11-{2 + 7 * (w - 3):02d}", "end_date": f"2026-11-{8 + 7 * (w - 3):02d}"}
         for w in (3, 4, 5, 6)]                 # 3: 11-02..11-08, 4: 11-09..15, 5: 11-16..22, 6: 11-23..29


def _inp(now, reports=(1, 2, 3, 4)):
    return {"now": now, "weeks": WEEKS, "reports": {w: {} for w in reports}}


def test_the_latest_finished_week_without_a_report_is_named():
    monday = datetime(2026, 11, 23, 2, 15, tzinfo=LA)                      # Monday of week 6
    assert L.power_pending(_inp(monday)) == "Week 5 appears when its report is published."
    assert L.power_pending(_inp(monday, reports=(1, 2, 3, 4, 5))) == ""   # published: no line
    sunday = datetime(2026, 11, 22, 23, 0, tzinfo=LA)                      # week 5 not finished yet
    assert L.power_pending(_inp(sunday)) == ""
    later = datetime(2026, 11, 30, 9, 0, tzinfo=LA)                        # two finished, none published
    assert L.power_pending(_inp(later)) == "Weeks 5–6 appear when their reports are published."
    # the league clock decides the day: 1 AM Monday in Phoenix is still Sunday in Portland
    phx = datetime(2026, 11, 23, 0, 30, tzinfo=ZoneInfo("America/Phoenix"))
    assert L.power_pending(_inp(phx)) == ""


def test_the_line_is_in_the_payload_and_printed_muted_above_the_list():
    from test_hub_v2 import synth_payload, GEN
    import hub_v2_league_fixture as LF
    inp = LF.inputs(synth_payload())
    pw = L.power_history(inp)
    assert "pending" in pw
    inp2 = dict(inp, now=inp["now"] + timedelta(days=60))                 # every week since then finished
    pw2 = L.power_history(inp2)
    assert pw2["pending"].endswith("appear when their reports are published.") or \
        pw2["pending"].endswith("appears when its report is published.")
    p = synth_payload()
    p["v2"]["league"]["power"] = dict(p["v2"]["league"]["power"], pending="Week 5 appears when its report is published.")
    h = page.render(view.build(p, mode="preview", now=GEN + timedelta(hours=2)))
    sec = h[h.index('data-section="power-history"'):]
    sec = sec[:sec.index("</section>")]
    assert '<p class="lh-sub" data-power-pending>Week 5 appears when its report is published.</p>' in sec
    assert sec.index("data-power-pending") < sec.index("v2-lg-wk") if "v2-lg-wk" in sec else True
