"""
hub_page.py -- the hub as one self-contained page, and its decrypt shell
(Step 1b; design s.3). Built on live_lines_page's rules.

THE PAGE DISPLAYS; THE ENGINE COMPUTES
    Every number on the page is a string from output/hub_state.json, printed
    as is. Sorting a roster reorders rows by orders the payload carries;
    nothing is compared or rounded here. The one value the page works out is
    the payload's AGE in words ("updated 3 hours ago"), because it depends on
    the reader's clock, not the engine's: the renderer writes it for the
    moment of rendering, and the page's script refreshes it when opened, with
    the stale banner over STALE_HOURS. That is the only arithmetic in it.

FRESHNESS IS ALWAYS SHOWN, and a payload older than STALE_HOURS puts a
banner above everything else (design s.3 invariant).

NO EXTERNAL ANYTHING: system fonts, inline styles and script, no images. The
page works offline once decrypted.

PLAYER CARDS (task 40): every player name in a table or list carries its card
key (data-card, from the payload; hub_cards.annotate). A tap loads the card
bundle once -- in preview, inline (render's `cards`); published, the shell's
HUB.cards(), an encrypted file fetched on the first tap -- then the player's
earlier seasons and headshot (HUB.part, HUB.photo), and opens the
newsletter's own modal (player_card_modal, whose script and style come in the
bundle, not in this page). The loader computes nothing: it joins the two
lists of games the engine wrote and hands the card to the modal.
A card, history or photo file that is gone (HTTP 404: a publish replaced
the files an open page names, hub_deploy.stage) shows "The hub has been
updated: reload the page to open player cards." with a Reload button
(HUB.reload: the unlocked key rides one reload in sessionStorage, so no
passphrase again); any other failure keeps "That player card could not be
opened." (40b s.2, 11-13).

LORE NEVER REACHES IT: every payload string passes live_lines_page.clean
(VOICE rule 21's tag strip, then HTML escaping).

TWO MODES
    preview  output/hub_preview.html: plaintext, for review on Nick's machine;
             issues link to the archive's plaintext files. Never published.
    publish  the same page, encrypted inside the decrypt shell
             (shell_html); issues open through window.HUB, which decrypts them
             on tap.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Optional

from .live_lines_page import clean

STALE_HOURS = 36

FONT = ('-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"Helvetica Neue",Arial,'
        'system-ui,sans-serif')

# The moves feed's colours (task 39; Nick, 11-04): added bright green, dropped
# bright red, trades purple, each also marked + / minus / two-way arrow (the
# marker is in the payload), so colour is never the only signal. Every one is
# at least 4.5:1 against the card (#FFFFFF) and the page (#F4F5F7), WCAG AA
# for body text: tests/test_hub.py pins it.
MOVE_COLOURS = {"add": "#008033", "drop": "#D50000", "trade": "#8A2BE2"}

# The trade block's mode chips (task 49): (background, text). Each text colour
# is at least 4.5:1 on its own background (tests/test_trade_block.py), and
# the word itself (Buying / Selling / Neutral) carries the meaning.
MODE_CHIP_COLOURS = {"buy": ("#DDF3E4", "#11592A"), "sell": ("#FBE3CF", "#8A3F06"),
                     "neu": ("#EEF0F3", "#3A404A")}

CSS = """
*{box-sizing:border-box}
body{margin:0;background:#F4F5F7;color:#121417;font-family:%(font)s;
font-variant-numeric:tabular-nums;-webkit-text-size-adjust:100%%}
a{color:#1D5FD1;text-decoration:none}
button{font:inherit;color:inherit}
.wrap{max-width:560px;margin:0 auto;padding-bottom:28px}
.stale{background:#7A1E14;color:#fff;padding:14px 18px;font-size:15px;font-weight:700;line-height:1.4}
.stale .reload{margin-left:8px;min-height:36px;padding:6px 14px;border-radius:8px;border:0;background:#fff;color:#7A1E14;font-size:14px;font-weight:700;font-family:inherit}
.mismatch{background:#4a1714;color:#ffd9d6;padding:12px 18px;font-size:13px;line-height:1.4}
header.top{background:#121417;color:#fff;padding:20px 20px 18px;display:flex;flex-direction:column;gap:10px}
.row-b{display:flex;justify-content:space-between;align-items:baseline;gap:8px}
.h-title{font-size:22px;font-weight:800;letter-spacing:-.02em}
.h-sub{font-size:13px;color:#C9CED6}
.fresh{display:flex;align-items:center;gap:8px;font-size:13px;color:#C9CED6}
.dot{width:8px;height:8px;border-radius:4px;background:#4C9AFF;display:inline-block;flex:none}
.lock{background:#2A2F37;border-radius:10px;padding:10px 12px;font-size:13px;line-height:1.4;color:#E6E9EE}
.lock.on{background:#3A2A12;color:#FFE2B8}
section{padding:20px 16px 4px;display:flex;flex-direction:column;gap:12px}
h2{margin:0;font-size:13px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:#5B6270}
.aside{font-size:12px;color:#5B6270}
.card{background:#fff;border-radius:14px;box-shadow:0 1px 2px rgba(18,20,23,.06);overflow:hidden}
.m-card{padding:16px;display:flex;flex-direction:column;gap:12px}
.m-side{display:flex;justify-content:space-between;align-items:center}
.m-side .l,.m-side .r{display:flex;flex-direction:column}
.m-side .r{text-align:right}
.big{font-size:16px;font-weight:700}
.dim{color:#5B6270;font-weight:500}
.small{font-size:13px;color:#5B6270}
.bar{display:flex;height:8px;border-radius:4px;overflow:hidden;background:#E3E6EB}
.bar .a{background:#1D5FD1}.bar .b{flex-grow:1;background:#E8A15C}
.bets{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px}
.bet{background:#F4F5F7;border-radius:8px;padding:8px;display:flex;flex-direction:column;gap:2px}
.lbl{font-size:11px;font-weight:600;color:#5B6270;text-transform:uppercase;letter-spacing:.06em}
.bet .v{font-size:14px;font-weight:600}
.clock{font-size:12px;color:#5B6270}
.pr-h,.pr-row{display:grid;grid-template-columns:16px minmax(0,1fr) 34px 44px 56px 34px;gap:4px;
padding:10px 10px;align-items:center}
.pr-h{font-size:11px;font-weight:600;color:#5B6270;text-transform:uppercase;letter-spacing:.06em;
border-bottom:1px solid #E3E6EB}
.pr-h .odds-h{all:unset;cursor:pointer;text-align:right;color:#1D5FD1;font-size:11px;font-weight:700;
text-transform:uppercase;letter-spacing:.06em}
.pr-row{all:unset;box-sizing:border-box;display:grid;grid-template-columns:16px minmax(0,1fr) 34px 44px 56px 34px;
gap:4px;align-items:center;padding:12px 10px;min-height:44px;border-bottom:1px solid #EEF0F3;cursor:pointer;width:100%%}
.pfc{text-align:right;display:flex;flex-direction:column;font-size:13px}.pfc .s{font-size:11px;color:#5B6270}
.rank{font-size:15px;font-weight:800}
.tm{display:flex;flex-direction:column;min-width:0}
.tm .n{font-size:15px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.num{text-align:right;font-size:14px}
.oddc{text-align:right;display:flex;flex-direction:column}
.oddc .o{font-size:15px;font-weight:700}
.oddc .d{font-size:12px;font-weight:600}
.d.up{color:#1D5FD1}.d.down{color:#B4560C}.d.flat,.d.none{color:#5B6270}
.adds-over{color:#B3261E;font-weight:700}
.link{display:block;padding:12px 14px;font-size:13px;font-weight:600}
.note{font-size:12px;color:#5B6270;line-height:1.5}
.tabs{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:4px;background:#E3E6EB;padding:4px;border-radius:10px}
.tab{all:unset;cursor:pointer;text-align:center;min-height:40px;display:flex;align-items:center;justify-content:center;
border-radius:8px;font-size:14px;font-weight:600;color:#5B6270}
.tab.on{background:#fff;color:#121417}
.g-h,.g-r{display:grid;gap:2px;padding:6px 10px;align-items:center}
.g-h{font-size:11px;font-weight:600;color:#5B6270;padding-top:10px}
.g-h .d{text-align:center;display:flex;flex-direction:column}
.g-h .d span:last-child{font-weight:500}
.g-r{border-top:1px solid #EEF0F3}
.g-r .m{font-size:13px;font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.c{text-align:center;font-size:13px;padding:6px 0;border-radius:6px;font-weight:500}
.c.light{background:#FBE3CF}.c.over{background:#E3ECFB;font-weight:700}.c.off{color:#9AA1AC}
.c.est{font-style:italic;outline:1px dashed #8A919C;outline-offset:-2px}
.c.rng{font-size:11px;letter-spacing:-.3px}.k.rng{font-size:12px;letter-spacing:-.3px}
.c sup{font-size:9px;color:#B42318;margin-left:1px}
.nbanote{font-size:12px;line-height:1.4;color:#5B6270}.nbanote .fl{color:#B42318;font-weight:600}
.legend .sw.est{outline:1px dashed #8A919C;outline-offset:-1px;background:#fff}
.snote{font-size:12px;font-weight:600;color:#7A4A00}
.k{text-align:right;font-size:14px;font-weight:700}.k.i{font-size:13px;color:#5B6270;font-weight:500}
.legend{display:flex;flex-wrap:wrap;gap:6px 14px;padding:10px;font-size:11px;color:#5B6270;border-top:1px solid #EEF0F3}
.legend .sw{width:12px;height:12px;border-radius:3px;display:inline-block;vertical-align:-2px;margin-right:6px}
.fa-h,.fa-r{display:grid;grid-template-columns:minmax(0,1fr) 32px 30px 30px 30px 44px;gap:3px;padding:10px 10px;align-items:center}
.fa-h span{font-size:10px}
.st-h,.st-r{display:grid;grid-template-columns:minmax(0,1fr) 44px;gap:4px;padding:10px 12px;align-items:center}
.st-h{font-size:11px;font-weight:600;color:#5B6270;text-transform:uppercase;letter-spacing:.06em;border-bottom:1px solid #E3E6EB}
.st-r{border-bottom:1px solid #EEF0F3}
.wk{font:inherit;font-size:14px;font-weight:600;min-height:40px;padding:0 10px;border-radius:8px;border:1px solid #C9CED6;
background:#fff;color:#121417}
.used{display:flex;flex-wrap:wrap;gap:6px 14px;padding:12px 14px;border-bottom:1px solid #EEF0F3;font-size:13px;font-weight:600}
.fa-r .tags{display:flex;gap:4px;align-items:center;flex-wrap:wrap}
.fa-r .pts{font-weight:700;color:#121417}
.fa-h{font-size:11px;font-weight:600;color:#5B6270;text-transform:uppercase;letter-spacing:.06em;border-bottom:1px solid #E3E6EB}
.fa-r{border-bottom:1px solid #EEF0F3}
.pn{display:flex;flex-direction:column;min-width:0}
.pn .n{font-size:14px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.pn .s{font-size:11px;color:#5B6270}
.empty{padding:14px;font-size:14px;color:#5B6270;line-height:1.5}
.mv{display:flex;gap:12px;padding:12px 14px;border-bottom:1px solid #EEF0F3}
.mv .when{width:52px;flex:none;display:flex;flex-direction:column;font-size:12px;color:#5B6270}
.mv .when b{color:#121417}
.mv .body{display:flex;flex-direction:column;gap:4px;min-width:0;font-size:14px;line-height:1.4}
.mvp{font-weight:600}.mvp .mk{display:inline-block;width:1.1em;font-weight:800}
.mvp.add{color:%(add)s}.mvp.drop{color:%(drop)s}.mvp.trade{color:%(trade)s}
.chip{font-size:10px;font-weight:700;padding:1px 5px;border-radius:4px;background:#E3ECFB;color:#17489E;white-space:nowrap}
.chip.il,.chip.out{background:#FBE3CF;color:#8A3F06}.chip.q{background:#FFF1C9;color:#6B4E00}
.chip.st{background:#E3ECFB;color:#17489E}
.chip.buy{background:%(buy_bg)s;color:%(buy_fg)s}.chip.sell{background:%(sell_bg)s;color:%(sell_fg)s}
.chip.neu{background:%(neu_bg)s;color:%(neu_fg)s}
.tb-h{display:flex;justify-content:space-between;align-items:flex-start;gap:8px;padding:12px 14px;
border-bottom:1px solid #EEF0F3}
.tb-t{display:flex;flex-direction:column;gap:2px;min-width:0}
.tb-t .n{font-size:15px;font-weight:700;overflow-wrap:anywhere}
.tb-t .s,.tb-m .s,.tb-r .s{font-size:11px;color:#5B6270}
.tb-m{display:flex;flex-direction:column;align-items:flex-end;gap:2px;flex:none}
.tb-m .chip{font-size:12px;padding:2px 7px}
.tb-l{padding:8px 14px 10px}
.tb-k{font-size:11px;font-weight:700;color:#5B6270;text-transform:uppercase;letter-spacing:.06em;padding-bottom:2px}
.tb-r{display:flex;justify-content:space-between;align-items:center;gap:8px;padding:6px 0;border-top:1px solid #EEF0F3}
.tb-r .pn{display:flex;flex-direction:column;min-width:0}
.ad-b{padding:8px 14px 12px;border-top:1px solid #EEF0F3}
.ad-k{font-size:11px;font-weight:700;color:#5B6270;text-transform:uppercase;letter-spacing:.06em}
.ad-m{font-size:15px;font-weight:700;padding-top:4px;overflow-wrap:anywhere}
.ad-n{font-size:13px;font-weight:600;padding-top:4px;overflow-wrap:anywhere}
.ad-s{font-size:12px;color:#5B6270;padding-top:3px;overflow-wrap:anywhere}
.tb-r .pn .n{white-space:normal;overflow-wrap:anywhere}
.tb-r .since{flex:none;white-space:nowrap}
.issue{all:unset;box-sizing:border-box;cursor:pointer;background:#121417;color:#fff;border-radius:14px;padding:16px;
display:flex;justify-content:space-between;align-items:center;min-height:44px;width:100%%}
.issue .t{display:flex;flex-direction:column;gap:2px}
.issue .k1{font-size:12px;color:#C9CED6;text-transform:uppercase;letter-spacing:.06em}
.issue .k2{font-size:17px;font-weight:700}
.arch{padding:4px 14px}
.arch .row{all:unset;box-sizing:border-box;cursor:pointer;display:flex;justify-content:space-between;padding:10px 0;
border-top:1px solid #EEF0F3;font-size:14px;color:#1D5FD1;width:100%%}
.arch .hd{padding:10px 0;font-size:13px;color:#5B6270}
footer{padding:20px 16px;font-size:11px;color:#8F96A3;line-height:1.6}
.view[hidden]{display:none}
.rh{background:#121417;color:#fff;padding:16px 20px 18px;display:flex;flex-direction:column;gap:12px}
.back{color:#9CC2FF;font-size:14px;font-weight:600}
.stats{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px}
.stat{background:#2A2F37;border-radius:10px;padding:8px 10px;display:flex;flex-direction:column;gap:2px}
.stat .lbl{color:#C9CED6}.stat .v{font-size:16px;font-weight:700}
.size{font-size:13px;color:#E6E9EE}
.rt-h,.rt-r{display:grid;grid-template-columns:minmax(0,1fr) 44px 44px 44px 30px 44px;gap:2px;align-items:center;padding:4px 10px}
.rt-h{border-bottom:1px solid #E3E6EB}
.sb{all:unset;cursor:pointer;min-height:40px;display:flex;align-items:center;justify-content:flex-end;font-size:11px;
font-weight:700;color:#5B6270;text-transform:uppercase}
.sb.first{justify-content:flex-start;letter-spacing:.06em}
.sb.on{color:#1D5FD1}
.rt-r{padding:9px 10px;border-bottom:1px solid #EEF0F3}
.rt-r.il{background:#FBF8F5}
.rt-r .tags{display:flex;gap:4px;align-items:center;flex-wrap:wrap}
.rt-r .v{text-align:right;font-size:14px;color:#3A404A}
.rt-r .v.f{font-weight:600;color:#121417}
.rt-r .v.ks{color:#1D5FD1;font-weight:600}
.mbtns{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:6px}
.mbtn{all:unset;box-sizing:border-box;cursor:pointer;text-align:center;min-height:36px;display:flex;align-items:center;
justify-content:center;border-radius:8px;border:1px solid #C9CED6;font-size:13px;font-weight:600;color:#1D5FD1;background:#fff}
.lastw{all:unset;cursor:pointer;display:block;padding:4px 2px;font-size:13px;font-weight:600;color:#1D5FD1}
.res{font-size:13px;font-weight:700}
.para{padding:14px;display:flex;flex-direction:column;gap:6px;border-bottom:1px solid #EEF0F3}
.para .ph{font-size:11px;font-weight:700;color:#5B6270;text-transform:uppercase;letter-spacing:.06em}
.para .pt{font-size:15px;line-height:1.55}
.chart{padding:10px 8px 12px}
.chart svg{display:block;width:100%%;height:auto}
.chart .tip{font-size:13px;line-height:1.45;padding:8px 6px 0;min-height:40px}
.chart .g-line{stroke:#EEF0F3;stroke-width:1}.chart .g-mid{stroke:#9AA1AC;stroke-width:1;stroke-dasharray:3 3}
.chart .g-tick{stroke:#C9CED6;stroke-width:.5}.chart .g-week{stroke:#8A919C;stroke-width:1}
.chart .g-day{stroke:#EEF0F3;stroke-width:1}.chart .g-mark{stroke:#5B6270;stroke-width:1;stroke-dasharray:2 2}
.chart .g-now{stroke:#5B6270;stroke-width:1}
.chart .ax{font-size:9px;fill:#5B6270}.chart .ax-mark{font-size:9px;fill:#3A404A;font-weight:700}
.chart .lab{font-size:10px;font-weight:700;fill:#121417}
.chart rect.hit{fill:transparent;cursor:pointer}
#issue-view{position:fixed;inset:0;background:#fff;z-index:10;display:flex;flex-direction:column}
#issue-view[hidden]{display:none}
#issue-view .bar2{background:#121417;padding:10px 16px}
#issue-view iframe{flex:1;border:0;width:100%%}
[data-card]{cursor:pointer;text-decoration:underline dotted #9AA1AC;text-underline-offset:3px}
""" % {"font": FONT, "add": MOVE_COLOURS["add"], "drop": MOVE_COLOURS["drop"],
       "trade": MOVE_COLOURS["trade"],
       **{f"{k}_{w}": v[i] for k, v in MODE_CHIP_COLOURS.items() for i, w in ((0, "bg"), (1, "fg"))}}


def age_words(generated_at: datetime, now: datetime) -> tuple:
    """(words, stale) -- the same rule as the page's script."""
    seconds = (now - generated_at).total_seconds()
    minutes = int(seconds // 60)
    if seconds < 60:
        words = "just now"
    elif minutes < 60:
        words = f"{minutes} minute{'' if minutes == 1 else 's'} ago"
    else:
        hours = int(round(seconds / 3600.0))
        if seconds / 3600.0 < STALE_HOURS:
            words = f"{hours} hour{'' if hours == 1 else 's'} ago"
        else:
            days = int(round(seconds / 86400.0))
            words = f"{days} day{'' if days == 1 else 's'} ago"
    return words, seconds >= STALE_HOURS * 3600


STALE_TEXT = ("This hub is more than %d hours old and may be wrong. The nightly update has not "
              "run since %s." % (STALE_HOURS, "%s"))


def _move_parts(parts) -> str:
    """One line per part. A voided add is not in the payload at all (task 45:
    hidden, not struck; modules/hub_moves.yahoo_item)."""
    return "".join(f'<span class="mvp {clean(x["kind"])}"><span class="mk">{clean(x["marker"])}</span>'
                   f'{_segs(x["segs"]) if x.get("segs") else clean(x["text"])}</span>' for x in parts)


def _nba_note(nb) -> str:
    """The header's NBA-report note (step 3b): payload strings only."""
    if not nb or not (nb.get("text") or nb.get("flags")):
        return ""
    return ('<div class="nbanote">' + clean(nb.get("text") or "")
            + "".join(f'<div class="fl">{clean(f)}</div>' for f in nb.get("flags") or []) + "</div>")


def _mbtns(ids: dict, labels: dict) -> str:
    """The three buttons under a matchup card (tasks 48a-48c)."""
    return ('<div class="mbtns">' + "".join(
        f'<button class="mbtn" data-open="{clean(ids[k])}">{clean(labels[k])}</button>' for k in ("sum", "win", "flow"))
        + "</div>")


def _svg(ch: dict) -> str:
    """A chart from hub_charts, printed as given: every coordinate, path and
    label is a payload string. Tapping a target shows its text below."""
    o = [f'<div class="chart"><svg viewBox="{clean(ch["vb"])}" role="img" aria-label="{clean(ch["aria"])}">']
    o += [f'<line x1="{clean(g["x1"])}" y1="{clean(g["y1"])}" x2="{clean(g["x2"])}" y2="{clean(g["y2"])}" '
          f'class="{clean(g["cls"])}"/>' for g in ch["grid"]]
    o += [f'<path d="{clean(p["d"])}" fill="none" stroke="{clean(p["stroke"])}" stroke-width="{clean(p["w"])}"'
          + (f' stroke-dasharray="{clean(p["dash"])}"' if p["dash"] else "") + ' stroke-linejoin="round"/>'
          for p in ch["paths"]]
    o += [f'<circle cx="{clean(d["cx"])}" cy="{clean(d["cy"])}" r="{clean(d["r"])}" fill="{clean(d["fill"])}"/>'
          for d in ch["dots"]]
    o += [f'<text x="{clean(t["x"])}" y="{clean(t["y"])}" text-anchor="{clean(t["anchor"])}" class="{clean(t["cls"])}"'
          + (f' style="fill:{clean(t["fill"])}"' if t["fill"] else "") + f'>{clean(t["t"])}</text>' for t in ch["texts"]]
    o += [f'<rect class="hit" x="{clean(r["x"])}" y="{clean(r["y"])}" width="{clean(r["w"])}" height="{clean(r["h"])}" '
          f'data-tip="{clean(r["tip"])}"/>' for r in ch["hits"]]
    o.append(f'</svg><div class="tip">{clean(ch["tip0"])}</div></div>')
    return "".join(o)


def _tags(chips) -> str:
    return "".join(f'<span class="chip {clean(c["kind"])}">{clean(c["text"])}</span>' for c in chips)


def _card_attr(row) -> str:
    """ data-card="key" when the payload gives the name a card (task 40)."""
    k = row.get("card") if isinstance(row, dict) else None
    return f' data-card="{clean(k)}"' if k else ""


def _spaced(t: str) -> str:
    """clean(t) with t's own leading and trailing spaces kept (clean strips them)."""
    lead, trail = t[:len(t) - len(t.lstrip())], t[len(t.rstrip()):]
    return (lead + clean(t) + trail) if t.strip() else t.replace("<", "").replace(">", "")


def _segs(segs) -> str:
    """A text cut into plain pieces and tappable player names (hub_cards.segments)."""
    return "".join(f'<span class="pl" data-card="{clean(x["card"])}">{clean(x["t"])}</span>' if x.get("card")
                   else _spaced(x["t"]) for x in segs)


def _text(row: dict, field: str) -> str:
    """row[field], with its players tappable when the payload cut it (field_segs)."""
    segs = row.get(f"{field}_segs")
    return _segs(segs) if segs else clean(row[field])


def render(payload: dict, *, now: datetime = None, mode: str = "preview",
           archive_href: str = "hub_archive/", cards: dict = None) -> str:
    """The page as one HTML string. mode "preview" or "publish". cards: the
    preview's plaintext card bundle (hub_cards.preview_bundle), embedded;
    never in publish mode, where the cards are their own encrypted files."""
    if mode not in ("preview", "publish"):
        raise ValueError(f"mode {mode!r}")
    if cards is not None and mode != "preview":
        raise ValueError("the cards are embedded only in the plaintext preview")
    gen = datetime.fromisoformat(payload["generated_at"])
    now = now or datetime.now(gen.tzinfo)
    words, stale = age_words(gen, now)
    h = payload["header"]
    o = ["<!DOCTYPE html>", '<html lang="en"><head><meta charset="utf-8">',
         '<meta name="viewport" content="width=device-width,initial-scale=1">',
         '<meta name="robots" content="noindex">',
         f"<title>{clean(h['title'])}</title>", f"<style>{CSS}</style></head><body>",
         f'<div class="wrap" id="hub" data-epoch="{int(payload["generated_epoch_ms"])}" '
         f'data-stale-hours="{STALE_HOURS}">']
    o.append(f'<div class="stale" id="stale"{"" if stale else " hidden"}>'
             f'{clean(STALE_TEXT % payload["generated_text"])}</div>')

    # ---------------------------------------------------------------- main view
    o.append('<div class="view" id="v-main">')
    if h.get("engine_mismatch"):
        o.append(f'<div class="mismatch"><b>Do not price anything off this page.</b> '
                 f'{clean(h["engine_mismatch"])}.</div>')
    o.append('<header class="top">'
             f'<div class="row-b"><div class="h-title">{clean(h["title"])}</div>'
             f'<div class="h-sub">{clean(h["week_label"])}</div></div>'
             f'<div class="fresh"><span class="dot"></span><span>Updated <span id="age">{clean(words)}</span>'
             f' ({clean(payload["generated_text"])})</span></div>'
             f'<div class="lock{" on" if h["lock"]["locked"] else ""}">{clean(h["lock"]["text"])}</div>'
             + (f'<div class="lock">{clean(h["engine_note"])}</div>' if h.get("engine_note") else "")
             + _nba_note(h.get("nba"))
             + '</header>')

    # "This week's matchups" is always the first section (F6, 11-09: the Monday
    # checklist is Nick's alone now -- python scripts\ledger.py checklist)
    mu = payload["matchups"]
    o.append("<section><h2>This week's matchups</h2>")
    for c in mu["cards"]:
        o.append('<div class="card m-card"><div style="display:flex;flex-direction:column;gap:8px">')
        for s in ("a", "b"):
            x = c[s]
            o.append(f'<div class="m-side"><div class="l"><span class="big">{clean(x["team"])}</span>'
                     f'<span class="small">{clean(x["manager"])}</span></div>'
                     f'<div class="r"><span class="big">{clean(x["now"])} <span class="dim">&rarr; '
                     f'{clean(x["proj"])}</span></span><span class="small">{clean(x["win"])} to win</span>'
                     "</div></div>")
        o.append(f'</div><div class="bar"><div class="a" style="width:{clean(c["bar_a"])}"></div>'
                 '<div class="b"></div></div><div class="bets">'
                 f'<div class="bet"><span class="lbl">Spread</span><span class="v">{clean(c["spread"])}</span></div>'
                 f'<div class="bet"><span class="lbl">O/U</span><span class="v">{clean(c["total"])}</span></div>'
                 f'<div class="bet"><span class="lbl">Moneyline</span><span class="v">{clean(c["moneyline"])}</span></div>'
                 f'</div><div class="clock">{clean(mu["clock"])} &middot; {clean(h["line_text"])}</div>'
                 + _mbtns(c["views"], mu["buttons"]) + '</div>')
    if mu.get("last"):
        o.append(f'<button class="lastw" data-open="{clean(mu["last"]["view"])}">{clean(mu["last"]["link"])} &rarr;</button>')
    o.append("</section>")

    pw = payload["power"]
    o.append('<section><div class="row-b"><h2>Power rankings</h2>'
             '<span class="aside">Tap a team for its roster</span></div><div class="card">'
             '<div class="pr-h"><span>#</span><span>Team</span><span style="text-align:right">W-L</span>'
             '<span style="text-align:right">PF</span>'
             f'<button class="odds-h" data-open="v-chart">{clean(pw["label"])} &rsaquo;</button>'
             '<span style="text-align:right">Adds</span></div>')
    for r in pw["rows"]:
        o.append(f'<button class="pr-row" data-open="v-roster-{clean(r["manager"])}">'
                 f'<span class="rank">{clean(r["rank"])}</span>'
                 f'<span class="tm"><span class="n">{clean(r["team"])}</span>'
                 f'<span class="small" style="font-size:12px">{clean(r["manager"])}</span></span>'
                 f'<span class="num">{clean(r["record"])}</span>'
                 f'<span class="pfc"><span>{clean(r["pf"])}</span></span>'
                 f'<span class="oddc"><span class="o">{clean(r["odds"])}</span>'
                 f'<span class="d {clean(r["delta_dir"])}">{clean(r["delta"])}</span></span>'
                 f'<span class="num{" adds-over" if r["adds_over"] else ""}">{clean(r["adds"])}</span></button>')
    o.append(f'<button class="link" data-open="v-chart" style="all:unset;cursor:pointer;display:block;'
             f'padding:12px 14px;font-size:13px;font-weight:600;color:#1D5FD1">'
             f'{clean(pw["chart_title"])} over the season &rarr;</button>'
             # task 49: the trade block's own view, from the bottom of this card
             f'<button class="link" data-open="v-block" style="all:unset;cursor:pointer;display:block;'
             f'padding:12px 14px;font-size:13px;font-weight:600;color:#1D5FD1;border-top:1px solid #EEF0F3">'
             f'{clean(payload["trade_block"]["link"])} &rarr;</button>'
             # advice v2 (V2 s.7): beside the trade block's link, only when the switch is on
             + (f'<button class="link" data-open="v-advice" style="all:unset;cursor:pointer;display:block;'
                f'padding:12px 14px;font-size:13px;font-weight:600;color:#1D5FD1;border-top:1px solid #EEF0F3">'
                f'{clean(payload["advice"]["link"])} &rarr;</button>' if payload.get("advice") is not None else "")
             + '</div>'
             f'<div class="note">{clean(pw["as_of"])}. {clean(pw["note"])}</div></section>')

    gr = payload["grid"]
    o.append('<section><h2>Games grid</h2><div class="tabs">')
    for i, t in enumerate(gr["tabs"]):
        o.append(f'<button class="tab{" on" if i == 0 else ""}" data-tab="{clean(t["key"])}">{clean(t["label"])}</button>')
    o.append("</div>")
    for i, t in enumerate(gr["tabs"]):
        cols = f'grid-template-columns:52px repeat({len(t["days"])},minmax(0,1fr)) 40px 32px'
        o.append(f'<div class="card tabp" data-tabp="{clean(t["key"])}"{"" if i == 0 else " hidden"}>')
        o.append(f'<div class="g-h" style="{cols}"><span>{clean(t["range"])}</span>')
        for d in t["days"]:
            o.append(f'<span class="d"><span>{clean(d["dow"])}</span><span>{clean(d["day"])}</span></span>')
        o.append('<span style="text-align:right">Starts</span><span style="text-align:right">Idle</span></div>')
        for r in t["rows"]:
            o.append(f'<div class="g-r" style="{cols}"><span class="m">{clean(r["manager"])}</span>')
            for c in r["cells"]:
                cls = f'c {clean(c["kind"])}' + (" est" if c["est"] else "") + (" rng" if c.get("rng") else "")
                tip = "estimated" if c["est"] else ""
                if c.get("nba"):
                    tip = (tip + "; " if tip else "") + f'NBA report: {c.get("nba_names", "")} out'
                mark = "<sup>&dagger;</sup>" if c.get("nba") else ""
                o.append(f'<span class="{cls}"' + (f' title="{clean(tip)}"' if tip else "")
                         + f'>{clean(c["n"])}{mark}</span>')
            kr = " rng" if r.get("rng") else ""
            o.append(f'<span class="k{kr}">{clean(r["starts"])}</span>'
                     f'<span class="k i{kr}">{clean(r["idle"])}</span></div>')
        if not t["days"]:
            o.append('<div class="empty">No days left in this week.</div>')
        # under the grid, only the two marks that need explaining, and only on a
        # tab that shows them (Nick, 11-11: "get rid of pretty much all the text
        # we have under the chart"; the notes, the colour legend, the Cup note
        # and the footer are gone)
        keys = [k for k, on in (("range", t.get("has_range")), ("nba", t.get("has_nba"))) if on]
        o.append(('<div class="legend">' + "".join(f'<span>{clean(gr["legend"][k])}</span>' for k in keys)
                  + '</div>' if keys else "") + '</div>')
    o.append("</section>")

    fa = payload["free_agents"]
    o.append(f'<section><div class="row-b"><h2>Best free agents</h2><span class="aside">{clean(fa["aside"])}'
             '</span></div><div class="card"><div class="fa-h"><span>Player</span><span style="text-align:right">'
             f'Proj</span><span style="text-align:right">{clean(fa["cols"][0])}</span>'
             f'<span style="text-align:right">{clean(fa["cols"][1])}</span>'
             f'<span style="text-align:right">{clean(fa["cols"][2])}</span>'
             f'<span style="text-align:right">{clean(fa["pts_label"])}</span></div>')
    if not fa["rows"]:
        o.append(f'<div class="empty">{clean(fa["empty"])}</div>')
    for r in fa["rows"]:
        o.append(f'<div class="fa-r" data-status="{clean(r["status"])}"><span class="pn">'
                 f'<span class="n"{_card_attr(r)}>{clean(r["name"])}</span><span class="tags">'
                 f'<span class="s">{clean(r["pos"])} &middot; {clean(r["nba"])}</span>{_tags(r["tags"])}</span></span>'
                 f'<span class="num">{clean(r["proj"])}</span>'
                 f'<span class="num">{clean(r["g1"])}</span><span class="num">{clean(r["g2"])}</span>'
                 f'<span class="num">{clean(r["g3"])}</span>'
                 f'<span class="num pts">{clean(r["pts"])}</span></div>')
    o.append(f'<div class="empty" style="font-size:12px">{clean(fa["note"])}</div></div></section>')

    # the stash candidates (task 42), under the free agents
    st = payload["stash"]
    o.append(f'<section><div class="row-b"><h2>Stash candidates</h2><span class="aside">{clean(st["aside"])}'
             f'</span></div><div class="card"><div class="empty" style="font-size:13px">{clean(st["open_il"])}</div>'
             '<div class="st-h"><span>Player</span><span style="text-align:right">Proj</span></div>')
    if not st["rows"]:
        o.append(f'<div class="empty">{clean(st["empty"])}</div>')
    for r in st["rows"]:
        o.append(f'<div class="st-r" data-status="{clean(r["status"])}"><span class="pn">'
                 f'<span class="n"{_card_attr(r)}>{clean(r["name"])}</span><span class="tags">'
                 f'<span class="s">{clean(r["pos"])} &middot; {clean(r["nba"])}</span>{_tags(r["tags"])}</span>'
                 + (f'<span class="s">{clean(r["season_note"])}</span>' if r["season"] else "")
                 + f'</span><span class="num">{clean(r["proj"])}</span></div>')
    o.append(f'<div class="empty" style="font-size:12px">{clean(st["note"])}</div></div></section>')

    if payload.get("advice") is None:             # advice.hub "off": the empty slot, as before
        o.append(f'<section><h2>Advice</h2><div class="card"><div class="empty" id="advice-empty">'
                 f'{clean(payload["advice_empty"])}</div></div></section>')

    mv = payload["moves"]
    o.append('<section><div class="row-b"><h2>Moves</h2><select class="wk" id="mv-week" aria-label="Budget week">')
    for t in mv["weeks"]:
        sel = " selected" if t["key"] == mv["default"] else ""
        o.append(f'<option value="{clean(t["key"])}"{sel}>{clean(t["label"])}</option>')
    o.append("</select></div>")
    for t in mv["weeks"]:
        hid = "" if t["key"] == mv["default"] else " hidden"
        o.append(f'<div class="card" data-mvw="{clean(t["key"])}"{hid}>')
        if t["used"] is not None:
            o.append('<div class="used">' + "".join(
                f'<span class="{"adds-over" if u["over"] else ""}">{clean(u["text"])}</span>' for u in t["used"])
                + "</div>")
        o.append(f'<div class="empty" style="font-size:12px;padding:8px 14px">{clean(t["used_note"])}</div>')
        if not t["items"]:
            o.append(f'<div class="empty">{clean(mv["empty"])}</div>')
        for x in t["items"]:
            o.append(f'<div class="mv"><div class="when"><b>{clean(x["day"])}</b><span>{clean(x["date"])}</span>'
                     f'<span>{clean(x["time"])}</span></div>'
                     f'<div class="body"><b>{clean(x["who"])}</b>{_move_parts(x["parts"])}'
                     f'<span style="display:flex;gap:6px;flex-wrap:wrap"><span class="chip st">{clean(x["state"])}</span>'
                     f'<span class="small" style="font-size:11px">{clean(x["note"])}</span></span></div></div>')
        o.append("</div>")
    o.append(f'<div class="note">{clean(mv["note"])}</div></section>')

    nl = payload["newsletter"]
    o.append("<section><h2>The newsletter</h2>")

    def issue_attr(i):
        if mode == "publish":
            return f'data-issue="{clean(i["file"])}"'
        return f'data-href="{clean(archive_href + i["file"].replace(".enc", ".html"))}"'

    if nl["current"]:
        c = nl["current"]
        o.append(f'<button class="issue" {issue_attr(c)}><span class="t"><span class="k1">Latest issue</span>'
                 f'<span class="k2">{clean(c["label"])}</span></span><span style="font-size:20px;color:#9CC2FF">'
                 f'&rarr;</span></button>')
    else:
        o.append(f'<div class="card"><div class="empty">{clean(nl["empty"])}</div></div>')
    o.append(f'<div class="card arch"><div class="hd">{clean(nl["note"])}</div>')
    for i in nl["archive"]:
        o.append(f'<button class="row" {issue_attr(i)}><span>{clean(i["label"])}</span>'
                 f'<span class="small">{clean(i["size"])}</span></button>')
    if not nl["archive"]:
        o.append('<div class="row" style="cursor:default;color:#5B6270">The latest issue is the only one so far.</div>')
    o.append("</div></section>")

    eng = payload["engine"]
    o.append(f'<footer>Engine {clean(eng["key"])} &middot; {clean(payload["sources"]["line"])} &middot; '
             f'actual points through {clean(payload["sources"]["actuals_through"])}'
             + (' &middot; <a href="#" id="forget">Forget this phone</a>' if mode == "publish" else
                " &middot; local preview, not published")
             + "</footer>")
    o.append("</div>")

    # ---------------------------------------------------------------- roster views
    cols = [("name", "Player"), ("fppg", "FPPG"), ("proj", "Proj"), ("l14", "L14"), ("gl", "GL"),
            ("keep", "Keep")]
    for m, rb in payload["rosters"].items():
        o.append(f'<div class="view" id="v-roster-{clean(m)}" hidden>'
                 '<div class="rh"><a href="#" class="back" data-open="v-main">&larr; Power rankings</a>'
                 f'<div style="display:flex;flex-direction:column;gap:2px"><div class="h-title">{clean(rb["team"])}</div>'
                 f'<div class="h-sub">{clean(rb["subtitle"])}</div></div><div class="stats">'
                 f'<div class="stat"><span class="lbl">{clean(rb["odds_label"])}</span><span class="v">{clean(rb["odds"])}</span></div>'
                 f'<div class="stat"><span class="lbl">Adds</span><span class="v">{clean(rb["adds"])}</span></div>'
                 f'<div class="stat"><span class="lbl">Games left</span><span class="v">{clean(rb["starts"])}</span></div>'
                 f'</div><div class="size">{clean(rb["size"])}</div></div>'
                 '<section style="padding:16px 12px 24px;gap:10px"><div class="row-b" style="padding:0 4px">'
                 '<h2>Roster</h2><span class="aside">Sorted by <span class="sortlbl">'
                 f'{dict(cols)[rb["default_order"]]}</span> &middot; tap a column</span></div>'
                 f'<div class="card rt" data-orders=\'{clean(json.dumps(rb["orders"]))}\' '
                 f'data-default="{clean(rb["default_order"])}"><div class="rt-h">')
        for key, label in cols:
            on = " on" if key == rb["default_order"] else ""
            first = " first" if key == "name" else ""
            o.append(f'<button class="sb{first}{on}" data-sort="{key}">{label}</button>')
        o.append('</div><div class="rt-body">')
        order = rb["orders"][rb["default_order"]]
        for i in order:
            p = rb["players"][i]
            o.append(f'<div class="rt-r{" il" if p["in_il"] else ""}" data-i="{i}">'
                     f'<div class="pn"><span class="n"{_card_attr(p)}>{clean(p["name"])}</span><span class="tags">'
                     f'<span class="s">{clean(p["pos"])} &middot; {clean(p["nba"])}</span>{_tags(p["tags"])}</span></div>'
                     f'<span class="v f">{clean(p["fppg"])}</span><span class="v">{clean(p["proj"])}</span>'
                     f'<span class="v">{clean(p["l14"])}</span><span class="v" style="color:#121417">{clean(p["gl"])}</span>'
                     f'<span class="v{" ks" if p["keep_strong"] else ""}">{clean(p["keep"])}</span></div>')
        o.append('</div></div>')
        for j in rb["pending"]:
            o.append(f'<div class="note" style="padding:0 4px"><span class="chip new">{clean(j["text"])}</span></div>')
        o.append(f'<div class="note" style="padding:0 4px">{clean(rb["note"])}</div></section></div>')

    # ---------------------------------------------------------------- the chart view
    ch = pw["chart"]
    o.append('<div class="view" id="v-chart" hidden><div class="rh">'
             '<a href="#" class="back" data-open="v-main">&larr; Power rankings</a>'
             f'<div class="h-title">{clean(pw["chart_title"])}</div></div>'
             f'<section><div class="card">{_svg(ch)}</div><div class="note">{clean(ch["note"])}</div></section></div>')

    # ---------------------------------------------------------------- the trade block view (task 49)
    tbv = payload["trade_block"]
    o.append('<div class="view" id="v-block" hidden><div class="rh">'
             '<a href="#" class="back" data-open="v-main">&larr; Power rankings</a>'
             f'<div class="h-title">{clean(tbv["title"])}</div></div><section>')
    for c in tbv["cards"]:
        o.append(f'<div class="card tb" data-manager="{clean(c["manager"])}"><div class="tb-h">'
                 f'<span class="tb-t"><span class="n">{clean(c["team"])}</span>'
                 f'<span class="s">{clean(c["manager"])}</span></span>'
                 f'<span class="tb-m"><span class="chip {clean(c["mode"]["kind"])}">{clean(c["mode"]["text"])}</span>'
                 + (f'<span class="s">{clean(c["mode_since"])}</span>' if c["mode_since"] else "")
                 + '</span></div>')
        for lst in c["lists"]:
            o.append(f'<div class="tb-l" data-list="{clean(lst["key"])}"><div class="tb-k">{clean(lst["label"])}</div>')
            for r in lst["rows"]:
                o.append(f'<div class="tb-r"><span class="pn"><span class="n"{_card_attr(r)}>{clean(r["name"])}</span>'
                         f'<span class="s">{clean(r["pos"])} &middot; {clean(r["nba"])}</span></span>'
                         f'<span class="s since">{clean(r["since"])}</span></div>')
            o.append("</div>")
        if c["empty"]:
            o.append(f'<div class="empty">{clean(c["empty"])}</div>')
        o.append("</div>")
    o.append(f'<div class="note">{clean(tbv["foot"])}</div></section></div>')

    # ---------------------------------------------------------------- the advice view (advice v2, V2 s.7)
    adv = payload.get("advice")
    if adv is not None:
        o.append('<div class="view" id="v-advice" hidden><div class="rh">'
                 '<a href="#" class="back" data-open="v-main">&larr; Power rankings</a>'
                 f'<div class="h-title">{clean(adv["title"])}</div></div><section>')
        for c in adv["cards"]:
            o.append(f'<div class="card ad" data-manager="{clean(c["manager"])}"><div class="tb-h">'
                     f'<span class="tb-t"><span class="n">{clean(c["team"])}</span>'
                     f'<span class="s">{clean(c["manager"])}</span></span></div><div class="ad-b">'
                     + (f'<div class="ad-k">{clean(c["heading"])}</div>' if c["heading"] else ""))
            if c.get("step"):             # 44a: the plan's activation, before the pick
                o.append(f'<div class="ad-s">{_text(c, "step")}</div>')
            if c["move"]:
                o.append(f'<div class="ad-m">{_text(c, "move")}</div>'
                         + (f'<div class="ad-s">{_text(c, "followup")}</div>' if c["followup"] else "")
                         + f'<div class="ad-n">{clean(c["numbers"])}</div>'
                         + f'<div class="ad-s">{clean(c["reason"])}</div>'
                         + (f'<div class="ad-s">{clean(c["also"])}</div>' if c["also"] else "")
                         + (f'<div class="ad-s">{_text(c, "backup")}</div>' if c["backup"] else ""))
            else:
                o.append(f'<div class="empty">{clean(c["empty"])}</div>')
            o.append("</div></div>")
        o.append(f'<div class="note">{clean(adv["foot"])}</div><div class="note">{clean(adv["note"])}</div>'
                 '</section></div>')

    # ---------------------------------------------------------------- last week and the matchup views (48a-48c)
    lw = mu.get("last")
    if lw:
        o.append(f'<div class="view" id="{clean(lw["view"])}" hidden><div class="rh">'
                 '<a href="#" class="back" data-open="v-main">&larr; Hub</a>'
                 f'<div class="h-title">{clean(lw["link"])}</div><div class="h-sub">{clean(lw["title"])}</div></div>'
                 '<section>')
        for c in lw["cards"]:
            o.append('<div class="card m-card">')
            for sd in ("a", "b"):
                x = c[sd]
                o.append(f'<div class="m-side"><div class="l"><span class="big">{clean(x["team"])}</span>'
                         f'<span class="small">{clean(x["manager"])}</span></div>'
                         f'<div class="r"><span class="big">{clean(x["score"])}</span></div></div>')
            o.append(f'<div class="res">{clean(c["result"])}</div>' + _mbtns(c["views"], mu["buttons"]) + '</div>')
        o.append(f'<div class="note">{clean(lw["note"])}</div></section></div>')
    for v in payload["matchup_views"]:
        o.append(f'<div class="view" id="{clean(v["id"])}" hidden><div class="rh">'
                 f'<a href="#" class="back" data-open="{clean(v["back"])}">&larr; {clean(v["back_label"])}</a>'
                 f'<div class="h-title">{clean(v["title"])}</div><div class="h-sub">{clean(v["sub"])}</div></div>'
                 '<section><div class="card">')
        if v["kind"] == "summary":
            for para in v["paras"]:
                o.append('<div class="para">' + (f'<span class="ph">{clean(para["head"])}</span>' if para["head"] else "")
                         + f'<span class="pt">{clean(para["text"])}</span></div>')
            o.append("</div>")
        else:
            o.append(f'{_svg(v["chart"])}</div><div class="note">{clean(v["chart"]["note"])}</div>')
        o.append("</section></div>")

    o.append('<div id="issue-view" hidden><div class="bar2"><a href="#" class="back" id="issue-close">'
             '&larr; Back to the hub</a></div><iframe id="issue-frame" title="Newsletter"></iframe></div>')
    o.append("</div>")
    if cards is not None:                       # the preview's cards, plaintext (never published)
        blob = json.dumps(cards, separators=(",", ":"), ensure_ascii=True).replace("</", "<\\/")
        o.append(f'<script type="application/json" id="hub-cards">{blob}</script>')
    o.append(f"<script>{PAGE_JS}</script></body></html>")
    return "\n".join(o)


PAGE_JS = r"""
(function(){
var hub=document.getElementById('hub');
function show(id){
  var vs=document.querySelectorAll('.view');
  for(var i=0;i<vs.length;i++){vs[i].hidden=(vs[i].id!==id);}
  window.scrollTo(0,0);
}
function route(){var h=location.hash.replace('#','');show(document.getElementById(h)?h:'v-main');}
window.addEventListener('hashchange',route);
function age(){
  var ms=Date.now()-Number(hub.getAttribute('data-epoch'));
  var lim=Number(hub.getAttribute('data-stale-hours'))*3600000, w;
  var m=Math.floor(ms/60000);
  if(ms<60000){w='just now';}
  else if(m<60){w=m+(m===1?' minute':' minutes')+' ago';}
  else if(ms<lim){var h=Math.round(ms/3600000);w=h+(h===1?' hour':' hours')+' ago';}
  else{var d=Math.round(ms/86400000);w=d+(d===1?' day':' days')+' ago';}
  document.getElementById('age').textContent=w;
  document.getElementById('stale').hidden=!(ms>=lim);
}
age();setInterval(age,60000);
function sortTable(card,key){
  var orders=JSON.parse(card.getAttribute('data-orders'));
  var body=card.querySelector('.rt-body');
  var rows={};var rs=body.children;
  for(var i=0;i<rs.length;i++){rows[rs[i].getAttribute('data-i')]=rs[i];}
  var ord=orders[key];
  for(var j=0;j<ord.length;j++){body.appendChild(rows[String(ord[j])]);}
  var bs=card.querySelectorAll('.sb');
  for(var k=0;k<bs.length;k++){bs[k].classList.toggle('on',bs[k].getAttribute('data-sort')===key);}
  var view=card.closest('.view');
  view.querySelector('.sortlbl').textContent=card.querySelector('.sb[data-sort="'+key+'"]').textContent;
}
// player cards (task 40): the bundle once, then the player's earlier seasons
// and headshot; the newsletter's modal draws the card. Nothing computed here.
var cardsP=null;
function cardsBundle(){
  if(cardsP){return cardsP;}
  var el=document.getElementById('hub-cards');
  var p=el?Promise.resolve(JSON.parse(el.textContent)):
    ((window.HUB&&window.HUB.cards)?window.HUB.cards():Promise.reject(new Error('no cards')));
  cardsP=p.then(function(b){
    return (b.code?window.HUB.part(b.code):Promise.resolve(b)).then(function(code){
      var st=document.createElement('style');st.textContent=code.css;document.head.appendChild(st);
      var sc=document.createElement('script');sc.textContent=code.js;document.body.appendChild(sc);
      window.pcPhotoLoader=(window.HUB&&window.HUB.photo)?function(ref){
        return window.HUB.photo(ref).catch(function(err){if(err&&err.message==='gone'){movedBox();}throw err;});}:null;
      return b;});});
  cardsP.catch(function(){cardsP=null;});
  return cardsP;
}
function openCard(key){
  cardsBundle().then(function(b){
    var c=b.cards[key];
    if(!c){throw new Error('no card');}
    if(c.hist&&!c.histIn){return window.HUB.part(c.hist).then(function(prior){
      c.sparkline=prior.concat(c.sparkline);c.histIn=true;return c;});}
    return c;
  }).then(function(c){window.pcShow(c);},function(err){
    if(err&&err.message==='gone'){movedBox();return;}
    alertBox((err&&err.message==='old browser')?'This browser is too old to open player cards.':
      'That player card could not be opened.');});
}
document.addEventListener('click',function(e){
  var t=e.target.closest('[data-card]');
  if(t){e.preventDefault();openCard(t.getAttribute('data-card'));return;}
  t=e.target.closest('[data-open]');
  if(t){e.preventDefault();var id=t.getAttribute('data-open');
    if(id==='v-main'){history.pushState('',document.title,location.pathname+location.search);show('v-main');}
    else{location.hash=id;}
    return;}
  t=e.target.closest('[data-tab]');
  if(t){var key=t.getAttribute('data-tab');
    var ts=document.querySelectorAll('[data-tab]');for(var i=0;i<ts.length;i++){ts[i].classList.toggle('on',ts[i]===t);}
    var ps=document.querySelectorAll('[data-tabp]');for(var j=0;j<ps.length;j++){ps[j].hidden=(ps[j].getAttribute('data-tabp')!==key);}
    return;}
  t=e.target.closest('[data-tip]');
  if(t){t.closest('.chart').querySelector('.tip').textContent=t.getAttribute('data-tip');return;}
  t=e.target.closest('[data-sort]');
  if(t){sortTable(t.closest('.rt'),t.getAttribute('data-sort'));return;}
  t=e.target.closest('[data-href]');
  if(t){openFrame(t.getAttribute('data-href'));return;}
  t=e.target.closest('[data-issue]');
  if(t){var f=t.getAttribute('data-issue');
    if(!window.HUB){return;}
    t.disabled=true;
    window.HUB.openIssue(f).then(function(url){t.disabled=false;openFrame(url);},
      function(){t.disabled=false;alertBox('That issue could not be opened.');});
    return;}
  if(e.target.id==='issue-close'){e.preventDefault();document.getElementById('issue-view').hidden=true;
    document.getElementById('issue-frame').removeAttribute('src');return;}
  if(e.target.id==='forget'){e.preventDefault();if(window.HUB){window.HUB.forget();}return;}
});
var wk=document.getElementById('mv-week');
if(wk){wk.addEventListener('change',function(){
  var ps=document.querySelectorAll('[data-mvw]');
  for(var i=0;i<ps.length;i++){ps[i].hidden=(ps[i].getAttribute('data-mvw')!==wk.value);}
});}
function openFrame(url){var v=document.getElementById('issue-view');document.getElementById('issue-frame').src=url;v.hidden=false;}
function alertBox(msg){var d=document.createElement('div');
  d.className='stale';d.textContent=msg;document.body.insertBefore(d,document.body.firstChild);}
// 40b s.2: a card, history or photo file that is gone (HTTP 404) means a
// publish replaced the files this page names: say so once, with a reload
// that keeps the unlocked key (HUB.reload; no passphrase again)
function movedBox(){
  if(document.getElementById('hub-moved')){return;}
  var d=document.createElement('div');d.className='stale';d.id='hub-moved';
  d.appendChild(document.createTextNode('The hub has been updated: reload the page to open player cards. '));
  var b=document.createElement('button');b.type='button';b.className='reload';b.textContent='Reload';
  b.addEventListener('click',function(){if(window.HUB&&window.HUB.reload){window.HUB.reload();}else{location.reload();}});
  d.appendChild(b);document.body.insertBefore(d,document.body.firstChild);
}
route();
})();
"""


# =============================================================================
# the decrypt shell
# =============================================================================

SHELL_CSS = """
*{box-sizing:border-box}
html,body{margin:0;background:#121417;color:#fff;font-family:%(font)s}
.u{max-width:420px;min-height:100vh;margin:0 auto;display:flex;flex-direction:column;justify-content:center;
padding:32px 28px;gap:28px}
.t{font-size:30px;font-weight:800;letter-spacing:-.02em}
.s{font-size:15px;color:#C9CED6;line-height:1.5}
label{font-size:13px;font-weight:600;color:#C9CED6}
input[type=password]{width:100%%;height:50px;border-radius:12px;border:1px solid #3A404A;background:#1E2228;
color:#fff;font-size:17px;padding:0 14px;font-family:inherit}
.rem{display:flex;gap:10px;align-items:center;font-size:14px;color:#C9CED6;min-height:44px;font-weight:400}
.rem input{width:20px;height:20px}
button{height:52px;border-radius:12px;background:#4C9AFF;color:#0B1B33;font-size:17px;font-weight:700;border:0;
width:100%%;font-family:inherit;cursor:pointer}
button:disabled{opacity:.6}
.msg{min-height:20px;font-size:14px;color:#FFB4A8}
.f{font-size:12px;color:#8F96A3;line-height:1.5}
""" % {"font": FONT}

SHELL_JS = r"""
(function(){
var B=JSON.parse(document.getElementById('hub-bundle').textContent);
var STORE='hub-key-v1';
function unb64(s){var b=atob(s),u=new Uint8Array(b.length);for(var i=0;i<b.length;i++){u[i]=b.charCodeAt(i);}return u;}
function b64(u){var s='';for(var i=0;i<u.length;i++){s+=String.fromCharCode(u[i]);}return btoa(s);}
function getStored(){try{var v=JSON.parse(localStorage.getItem(STORE)||'null');return v;}catch(e){return null;}}
function setStored(v){try{localStorage.setItem(STORE,JSON.stringify(v));}catch(e){}}
function clearStored(){try{localStorage.removeItem(STORE);}catch(e){}}
function derive(pass){
  return crypto.subtle.importKey('raw',new TextEncoder().encode(pass),'PBKDF2',false,['deriveBits'])
  .then(function(k){return crypto.subtle.deriveBits({name:'PBKDF2',hash:'SHA-256',salt:unb64(B.salt),iterations:B.iter},k,256);})
  .then(function(bits){return new Uint8Array(bits);});
}
function openWith(raw){
  return crypto.subtle.importKey('raw',raw,'AES-GCM',false,['decrypt'])
  .then(function(k){return crypto.subtle.decrypt({name:'AES-GCM',iv:unb64(B.iv)},k,unb64(B.ct));})
  .then(function(pt){return JSON.parse(new TextDecoder().decode(pt));});
}
var RELOAD='hub-key-reload',cur=null;
function sealed(file,k){
  return fetch(file).then(function(r){
    if(r.status===404){throw new Error('gone');}
    if(!r.ok){throw new Error('fetch');}return r.arrayBuffer();})
  .then(function(buf){var u=new Uint8Array(buf);
    return crypto.subtle.importKey('raw',unb64(k),'AES-GCM',false,['decrypt']).then(function(key){
      return crypto.subtle.decrypt({name:'AES-GCM',iv:u.slice(0,12)},key,u.slice(12));});});
}
function part(ref){
  if(typeof DecompressionStream==='undefined'){return Promise.reject(new Error('old browser'));}
  return sealed(ref.file,ref.key).then(function(pt){
    return new Response(new Blob([pt]).stream().pipeThrough(new DecompressionStream('gzip'))).text();})
  .then(function(t){return JSON.parse(t);});
}
function mount(inner){
  window.HUB={
    cards:function(){return inner.cards?part(inner.cards):Promise.reject(new Error('no cards'));},
    part:part,
    photo:function(ref){return sealed(ref.file,ref.key).then(function(pt){
      return URL.createObjectURL(new Blob([pt],{type:'image/webp'}));});},
    openIssue:function(file){
      var k=inner.issues[file];
      if(!k){return Promise.reject(new Error('unknown issue'));}
      return fetch('issues/'+file).then(function(r){if(!r.ok){throw new Error('fetch');}return r.arrayBuffer();})
      .then(function(buf){var u=new Uint8Array(buf);
        return crypto.subtle.importKey('raw',unb64(k),'AES-GCM',false,['decrypt']).then(function(key){
          return crypto.subtle.decrypt({name:'AES-GCM',iv:u.slice(0,12)},key,u.slice(12));});})
      .then(function(pt){return URL.createObjectURL(new Blob([pt],{type:'text/html'}));});
    },
    forget:function(){clearStored();location.reload();},
    reload:function(){
      try{if(cur){sessionStorage.setItem(RELOAD,JSON.stringify({salt:B.salt,key:b64(cur)}));}}catch(e){}
      location.reload();}
  };
  var doc=new DOMParser().parseFromString(inner.page,'text/html');
  document.title=doc.title;
  var st=doc.querySelectorAll('style');
  for(var i=0;i<st.length;i++){document.head.appendChild(st[i].cloneNode(true));}
  var old=document.getElementById('shell-style');if(old){old.remove();}
  document.body.innerHTML=doc.body.innerHTML;
  var ss=document.body.querySelectorAll('script');
  for(var j=0;j<ss.length;j++){var n=document.createElement('script');n.textContent=ss[j].textContent;ss[j].replaceWith(n);}
}
var form=document.getElementById('unlock'),msg=document.getElementById('msg'),btn=document.getElementById('go');
function takeReload(){
  var v=null;try{v=JSON.parse(sessionStorage.getItem(RELOAD)||'null');sessionStorage.removeItem(RELOAD);}catch(e){v=null;}
  return(v&&v.salt===B.salt)?v:null;
}
function tryStored(){
  var r=takeReload();
  if(r){return openWith(unb64(r.key)).then(function(inner){cur=unb64(r.key);mount(inner);return true;},
    function(){return tryRemembered();});}
  return tryRemembered();
}
function tryRemembered(){
  var s=getStored();
  if(!s){return Promise.resolve(false);}
  if(s.salt!==B.salt){clearStored();return Promise.resolve(false);}
  return openWith(unb64(s.key)).then(function(inner){cur=unb64(s.key);mount(inner);return true;},
    function(){clearStored();return false;});
}
tryStored().then(function(ok){if(!ok){form.hidden=false;document.getElementById('pass').focus();}});
form.addEventListener('submit',function(e){
  e.preventDefault();msg.textContent='';btn.disabled=true;btn.textContent='Opening...';
  var pass=document.getElementById('pass').value;
  derive(pass).then(function(raw){
    return openWith(raw).then(function(inner){
      if(document.getElementById('remember').checked){setStored({salt:B.salt,key:b64(raw)});}else{clearStored();}
      cur=raw;mount(inner);
    });
  }).catch(function(){msg.textContent='Wrong passphrase.';btn.disabled=false;btn.textContent='Open the hub';});
});
})();
"""


def shell_html(bundle_json: str) -> str:
    """The published index.html: the unlock form, the encrypted bundle and
    the WebCrypto decryptor. It holds no league content: no name, no number."""
    if "</" in bundle_json:
        raise ValueError("bundle JSON must not contain '</'")
    return "\n".join([
        "<!DOCTYPE html>", '<html lang="en"><head><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width,initial-scale=1">',
        '<meta name="robots" content="noindex">',
        "<meta http-equiv=\"Content-Security-Policy\" content=\"default-src 'none'; "
        "script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'; "
        "frame-src blob:; img-src data: blob:\">",
        "<title>League Hub</title>", f'<style id="shell-style">{SHELL_CSS}</style></head><body>',
        '<form class="u" id="unlock" hidden autocomplete="off">',
        '<div style="display:flex;flex-direction:column;gap:8px"><div class="t">League Hub</div>',
        '<div class="s">Enter the league passphrase. This phone can remember it after the first time.</div></div>',
        '<div style="display:flex;flex-direction:column;gap:10px"><label for="pass">Passphrase</label>',
        '<input id="pass" type="password" placeholder="four words, spaces OK" autocapitalize="none" '
        'autocorrect="off" spellcheck="false">',
        '<label class="rem"><input type="checkbox" id="remember" checked> Remember on this phone</label></div>',
        '<button id="go" type="submit">Open the hub</button><div class="msg" id="msg"></div>',
        '<div class="f">Everything on this page is encrypted. Without the passphrase, all the site holds '
        'is scrambled data.</div></form>',
        f'<script type="application/json" id="hub-bundle">{bundle_json}</script>',
        f"<script>{SHELL_JS}</script></body></html>"])
