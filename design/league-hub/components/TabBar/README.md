# TabBar

The bottom navigation on the phone: Home · Matchups · Teams · Players · Market · League, always in that order.

- **Provide:** the current tab. Labels are working titles from the brief; change them in one place.
- Icon (22 px, 2 px stroke, `currentColor`) over a 10 px `tab` label. Active: `ink-strong`, weight 800, `aria-current="page"`. Inactive: `ink-3`. The weight change plus the colour means the active tab is not told by colour alone.
- Fixed to the bottom, `tabbar-height` tall including the home-indicator inset; content scrolls under nothing (pad the page bottom by `tabbar-height`).
- Desktop (≥ 900 px): the same six items become a left rail or a top bar; same order, same names.
- Icons are drawn inline (paths in the preview). No icon font, no emoji.
