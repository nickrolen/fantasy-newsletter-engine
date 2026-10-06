"""
advice_render.py -- Section 10's C2/C3 block, from the stats-report JSON.

Numbers go straight from the JSON into the HTML; the drafting chat gets a
markdown copy it may cite but must not retype (same rule as the games grid).

What the block always says (claude/C2_C3_DESIGN.md):
  - both sides' gains AND the differential, and that the two managers not
    in a trade are unchanged -- a trade is a two-on-two move; nothing here
    calls a trade fair;
  - the order is the smaller side's gain, labelled as how likely the
    reluctant side is to say yes;
  - how many eligible trades were not shown (one per pair), never silently;
  - who else a free agent was recommended to;
  - how long a recommendation has been on the table;
  - and, when the engine did not run or is not published, that and why.
"""

from __future__ import annotations

import html
from typing import Optional

_e = html.escape


def _pts(x: Optional[float]) -> str:
    return "-" if x is None else f"{x:+.0f}"


def _since(item: dict, week: int) -> str:
    first = item.get("first_shown_week")
    if first is None or first >= week:
        return ""
    return f"on the table since week {first}"


def status_line(advice: Optional[dict]) -> Optional[str]:
    """The sentence Section 10 prints when the engine's output is not in it,
    or None when it is (or when nothing should be said: pre-launch)."""
    if not advice:
        return None
    if advice.get("published"):
        return None
    if not advice.get("launched"):
        return None                      # pre-launch: Section 10 unchanged
    why = advice.get("publish_reason") or advice.get("reason") or "unknown"
    return f"Trade finder and waiver plans are not in this issue: {why}."


def _trade_lines(t: dict, week: int) -> dict:
    a, b = t["manager_a"], t["manager_b"]
    sends_a = " + ".join(t["a_sends"])
    sends_b = " + ".join(t["b_sends"])
    drops = [f"{m} drops {d}" for m, d in ((a, t.get("a_drops")), (b, t.get("b_drops"))) if d]
    lead = a if t["differential"] > 0 else b
    behind = b if lead == a else a
    diff = abs(t["differential"])
    return {"a": a, "b": b, "sends_a": sends_a, "sends_b": sends_b, "drops": drops,
            "lead": lead, "behind": behind, "diff": diff, "since": _since(t, week)}


def render_markdown(advice: Optional[dict], managers: list) -> str:
    if not advice:
        return ""
    line = status_line(advice)
    if line:
        return f"**{line}**\n"
    if not advice.get("published"):
        return ""
    wk = advice["week"]
    bar = advice.get("bar", {})
    out = [f"**TRADE FINDER AND WAIVER PLANS -- for week {advice['for_week']}** "
           "(rendered automatically in the HTML -- do NOT reproduce the tables. You "
           "may cite them. NEVER call a trade fair or say both sides 'win': gains "
           "are against not trading; always say who moves ahead of whom.)", ""]
    out.append(f"Bar: points > {bar.get('se_mult', 2):g} SE and >= "
               f"{bar.get('per_week', 10):g} per week of the window "
               f"(this week {bar.get('this_week_floor')}, regular season "
               f"{bar.get('season_floor')}).")
    out.append("")
    tc = advice.get("trade_counts", {})
    trades = advice.get("trades", [])
    if trades:
        out.append("Trades (order = the smaller side's gain: how likely the reluctant "
                   "side is to say yes; not a fairness score):")
        for i, t in enumerate(trades, 1):
            L = _trade_lines(t, wk)
            tag = " [commissioner is a party]" if t.get("involves_commissioner") else ""
            out.append(f"{i}. {L['a']} sends {L['sends_a']} <-> {L['b']} sends "
                       f"{L['sends_b']}{tag}" + (f" ({'; '.join(L['drops'])})" if L["drops"] else ""))
            out.append(f"   - Regular season: {L['a']} {_pts(t['gain_a'])} (+/-{t['se_a']:.0f}), "
                       f"{L['b']} {_pts(t['gain_b'])} (+/-{t['se_b']:.0f}). "
                       f"{L['lead']} moves {L['diff']:.0f} ahead of {L['behind']}; the other "
                       f"two managers are unchanged, so both parties gain on them.")
            if t.get("cup"):
                c = t["cup"]
                out.append(f"   - Cup seeding: {L['a']} {_pts(c['gain_a'])}, {L['b']} {_pts(c['gain_b'])}.")
            if t.get("keepability_delta_a") is not None:
                out.append(f"   - Keepability (separate, not added to points): "
                           f"{L['a']} {t['keepability_delta_a']:+.1f}, {L['b']} {t['keepability_delta_b']:+.1f}.")
            for f in t.get("keeper_flags", []):
                out.append(f"   - FLAG: {f}.")
            if L["since"]:
                out.append(f"   - {L['since'].capitalize()}.")
    else:
        out.append("Trades: none cleared the bar for both sides this week.")
    if tc.get("not_shown"):
        out.append(f"({tc['not_shown']} more trades cleared the bar for both sides; one per pair is shown.)")
    out.append("")
    out.append("Waiver plans:")
    for p in advice.get("plans", []):
        out.append(f"- {p['manager']} ({p['adds_remaining']} adds):")
        if p.get("note"):
            out.append(f"  - {p['note']}")
        for r in p.get("this_week", []):
            out.append("  - " + _rec_text(r, wk, "this week"))
        for r in p.get("regular_season", []):
            out.append("  - " + _rec_text(r, wk, "season"))
        if not p.get("this_week") and not p.get("regular_season"):
            out.append("  - Nothing clears the bar.")
    return "\n".join(out) + "\n"


def _rec_text(r: dict, week: int, label: str) -> str:
    drop = f", drop {r['drop']}" if r.get("drop") else " (before your drop)"
    per = f" ({r['per_week']:+.0f}/wk)" if label == "season" else ""
    s = (f"{label} {r['step']}: add {r['add']}{drop}: {_pts(r['points'])}{per} "
         f"(+/-{r['se']:.0f}), {r['starts']:+.1f} starts")
    if r.get("contested_with"):
        s += f". Also recommended to {' and '.join(r['contested_with'])}"
        if r.get("runner_up"):
            s += f"; if he's gone: {r['runner_up']['add']} ({_pts(r['runner_up']['points'])})"
    since = _since(r, week)
    if since:
        s += f". {since.capitalize()}"
    return s


def render_html(advice: Optional[dict]) -> str:
    if not advice:
        return ""
    line = status_line(advice)
    if line:
        return f'<div class="adv adv-status">{_e(line)}</div>'
    if not advice.get("published") and not advice.get("_preview"):
        return ""
    wk = advice["week"]
    out = ['<div class="adv" data-viz="advice">']
    trades = advice.get("trades", [])
    out.append(f'<div class="adv-h">Trade finder &middot; week {advice["for_week"]}</div>')
    if trades:
        out.append('<div class="adv-sub">Gains are against not trading, over the regular season. '
                   'Ordered by the smaller side\'s gain &mdash; how likely the reluctant side is '
                   'to say yes. Not a fairness score.</div>')
        for t in trades:
            L = _trade_lines(t, wk)
            tag = ('<span class="adv-tag">commissioner is a party</span>'
                   if t.get("involves_commissioner") else "")
            out.append('<div class="adv-trade">')
            out.append(f'<div class="adv-deal"><b>{_e(L["a"])}</b> sends {_e(L["sends_a"])} '
                       f'&harr; <b>{_e(L["b"])}</b> sends {_e(L["sends_b"])} {tag}</div>')
            if L["drops"]:
                out.append(f'<div class="adv-note">{_e("; ".join(L["drops"]))}</div>')
            out.append('<table class="adv-t"><tr><th></th>'
                       f'<th>{_e(L["a"])}</th><th>{_e(L["b"])}</th></tr>')
            out.append(f'<tr><td>Regular season</td><td>{_pts(t["gain_a"])}</td>'
                       f'<td>{_pts(t["gain_b"])}</td></tr>')
            if t.get("cup"):
                out.append(f'<tr><td>Cup seeding</td><td>{_pts(t["cup"]["gain_a"])}</td>'
                           f'<td>{_pts(t["cup"]["gain_b"])}</td></tr>')
            if t.get("keepability_delta_a") is not None:
                out.append(f'<tr class="adv-dim"><td>Keepability</td>'
                           f'<td>{t["keepability_delta_a"]:+.1f}</td>'
                           f'<td>{t["keepability_delta_b"]:+.1f}</td></tr>')
            out.append('</table>')
            out.append(f'<div class="adv-diff"><b>{_e(L["lead"])}</b> moves {L["diff"]:.0f} ahead '
                       f'of {_e(L["behind"])}. The other two are unchanged &mdash; both parties gain on them.</div>')
            for f in t.get("keeper_flags", []):
                out.append(f'<div class="adv-flag">{_e(f)}</div>')
            if L["since"]:
                out.append(f'<div class="adv-note">{_e(L["since"].capitalize())}</div>')
            out.append('</div>')
    else:
        out.append('<div class="adv-sub">No trade cleared the bar for both sides this week.</div>')
    nshown = advice.get("trade_counts", {}).get("not_shown")
    if nshown:
        out.append(f'<div class="adv-note">{nshown} more trades cleared the bar for both sides; '
                   'one per pair is shown.</div>')

    out.append(f'<div class="adv-h">Waiver plans &middot; week {advice["for_week"]}</div>')
    for p in advice.get("plans", []):
        out.append(f'<div class="adv-plan"><div class="adv-mgr">{_e(p["manager"])} '
                   f'<span class="adv-dim">{p["adds_remaining"]} adds</span></div>')
        if p.get("note"):
            out.append(f'<div class="adv-note">{_e(p["note"])}</div>')
        rows = [("This week", r) for r in p.get("this_week", [])] + \
               [("Season", r) for r in p.get("regular_season", [])]
        if not rows:
            out.append('<div class="adv-note">Nothing clears the bar.</div>')
        for label, r in rows:
            out.append('<div class="adv-rec">')
            drop = f' for {_e(r["drop"])}' if r.get("drop") else ' <span class="adv-dim">(before your drop)</span>'
            per = f' <span class="adv-dim">{r["per_week"]:+.0f}/wk</span>' if label == "Season" else ""
            out.append(f'<span class="adv-lbl">{label}</span> <b>{_e(r["add"])}</b>{drop}: '
                       f'<b>{_pts(r["points"])}</b>{per}')
            if r.get("contested_with"):
                alt = r.get("runner_up")
                out.append(f'<div class="adv-contested">Also recommended to '
                           f'{_e(" and ".join(r["contested_with"]))}'
                           + (f'; if he&#39;s gone: {_e(alt["add"])} ({_pts(alt["points"])})' if alt else "")
                           + '</div>')
            since = _since(r, wk)
            if since:
                out.append(f'<div class="adv-note">{_e(since.capitalize())}</div>')
            out.append('</div>')
        out.append('</div>')
    bar = advice.get("bar", {})
    out.append(f'<div class="adv-foot">Shown only when worth at least {bar.get("per_week", 10):g} points '
               f'a week of the window and clear of simulation noise. Values are over the regular season '
               f'unless marked this week. One add, applied in order; drops never touch next season\'s keepers.</div>')
    out.append('</div>')
    return "\n".join(out)


def get_css() -> str:
    return """
        .adv { margin: 0 0 28px; font-size: 0.95em; }
        .adv-status { padding: 10px 12px; border-left: 3px solid var(--accent-gold); background: var(--light-gray); }
        .adv-h { font-weight: 700; color: var(--primary-blue); margin: 14px 0 4px; }
        .adv-sub, .adv-note, .adv-foot { font-size: 0.82em; color: var(--text-secondary, #666); margin: 2px 0 6px; }
        .adv-foot { margin-top: 10px; }
        .adv-trade, .adv-plan { border: 1px solid var(--border-color, #ddd); border-radius: 6px; padding: 8px 10px; margin: 8px 0; text-align: left; }
        .adv-deal { margin-bottom: 4px; }
        .adv-tag { font-size: 0.75em; padding: 1px 6px; border-radius: 3px; background: var(--light-gray); margin-left: 4px; }
        .adv-t { border-collapse: collapse; margin: 4px 0; font-variant-numeric: tabular-nums; }
        .adv-t th, .adv-t td { padding: 2px 10px 2px 0; text-align: left; border: none; }
        .adv-t th { font-weight: 600; font-size: 0.85em; background: none; color: inherit; }
        .adv-dim { color: var(--text-secondary, #777); font-size: 0.9em; }
        .adv-diff { font-size: 0.9em; }
        .adv-flag { font-size: 0.85em; color: #b4540a; }
        .adv-mgr { font-weight: 700; margin-bottom: 2px; }
        .adv-rec { margin: 3px 0; }
        .adv-lbl { display: inline-block; min-width: 72px; font-size: 0.8em; color: var(--text-secondary, #777); }
        .adv-contested { font-size: 0.82em; color: #b4540a; margin-left: 76px; }
    """


def render_preview_page(advice: dict) -> str:
    """Standalone page for the dark-launch read (weeks 1 and 2)."""
    body = render_html(dict(advice, _preview=True, launched=False))
    head = (f"Section 10 PREVIEW -- report week {advice.get('week')} "
            f"(not in the newsletter: {html.escape(str(advice.get('publish_reason', '')))})")
    return f"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Section 10 preview</title>
<style>
:root {{ --primary-blue:#1f4e79; --accent-gold:#e6b93d; --light-gray:#f3f4f6; --border-color:#ddd; --text-secondary:#666; }}
@media (prefers-color-scheme: dark) {{ :root {{ --primary-blue:#5b9bd5; --light-gray:#2d2d2d; --border-color:#404040; --text-secondary:#c0c0c0; }}
 body {{ background:#1a1a1a; color:#f0f0f0; }} }}
body {{ font-family: Inter, system-ui, sans-serif; max-width: 760px; margin: 24px auto; padding: 0 16px; line-height: 1.45; }}
{get_css()}
</style></head><body>
<p style="font-size:.85em;color:var(--text-secondary)">{head}</p>
{body}
</body></html>"""
