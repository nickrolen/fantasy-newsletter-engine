"""
hub_v2 -- the new hub (the redesign, step 4b; claude/HUB_REDESIGN_BRIEF.md,
design/league-hub/), built BESIDE the current page (modules/hub_page.py),
which keeps running untouched until the switch-over (step 5).

Why a package and not one hub_page_v2.py: the three jobs live apart, so each
keeps one rule.

    data.py    ENGINE SIDE. payload["v2"]: the new keys the design needs that
               the payload lacked (team slots and monograms, sparklines,
               chart series, the third grid week, KPI context lines...),
               built inside hub_state.build from the same run's inputs. Every
               number shown is a string formatted here; floats ride along only
               for scaling a mark.
    view.py    THE VIEW MODEL. payload -> the screens: joins, routes, team
               classes, and chart geometry (the one arithmetic the brief
               allows: scaling a mark to its number). No new numbers.
    page.py    THE RENDERER. view model -> one HTML string. Prints strings; no
               arithmetic (tests pin it), every string through clean().
    tokens.py  design/league-hub/tokens.json -> CSS custom properties, the
               fonts as base64 @font-face, then components/bundle.css as is.
    publish.py the same page inside the existing decrypt shell, built only to
               a scratch folder until the switch-over, to measure its size.
    infotips.py the InfoTip explanations, in one place (for Nick to approve).
    league.py, page_league.py  the League tab (4c4): its strings (engine side)
               and its renderer; History's chips are lazy encrypted parts.
"""
