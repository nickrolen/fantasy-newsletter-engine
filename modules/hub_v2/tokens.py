"""
hub_v2/tokens.py -- one source for every value: design/league-hub/tokens.json
compiled into CSS custom properties at build time, the fonts embedded, then
components/bundle.css appended as it is.

    css()  ->  @font-face (latin, from tokens.json type.fonts, each a base64
               data URI with its unicode-range)
               :root { --canvas: #F3F4F6; ... --type-display-xl-size: 34px; ... }
               bundle.css, byte for byte except its two latin-ext font URLs
               (url(../fonts/X.woff2)), which become the same files as data
               URIs: the page makes no font request (offline once unlocked).
               Any other url( in bundle.css RAISES.

THE RENDERER'S OWN CSS (page.LAYOUT_CSS) may use no hex colour and no px
literal: only var(--token). A media query cannot read a custom property, so
its width is written as {{token-name}} and filled here from tokens.json
(fill()); an unknown name RAISES. tests/test_hub_v2.py pins both.

Token additions for 4b (a value the page needed that was not a token; the
reviewing session copies them to the design-system artifact):
    sizing  bp-mid 600px, bp-wide 900px    the README's breakpoints
    sizing  hairline 1px                   the border width the cards use
    type.fonts[].unicodeRange              the latin files' range, so the
                                           latin-ext files take Jokic's c-acute
"""

from __future__ import annotations

import base64
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DESIGN = ROOT / "design" / "league-hub"
TOKENS = DESIGN / "tokens.json"
BUNDLE = DESIGN / "components" / "bundle.css"
FONTS = DESIGN / "fonts"


class TokenError(RuntimeError):
    pass


def load(path: Path = TOKENS) -> dict:
    if not path.is_file():
        raise TokenError(f"{path} is missing: the design system lives in design/league-hub/")
    return json.loads(path.read_text(encoding="utf-8"))


def values(tok: dict = None) -> dict:
    """{token name: CSS value}, aliases ("{surface-sunken}") resolved."""
    tok = tok or load()
    out = {}
    for t in tok["color"]["tokens"]:
        out[t["name"]] = t["value"]
    for grp in ("spacing", "radius", "shadow", "sizing"):
        for t in tok[grp]["tokens"]:
            out[t["name"]] = t["value"]
    for k, v in tok["type"]["families"].items():
        out[f"font-{k}"] = v
    for g in tok["type"]["groups"]:
        for s in g["styles"]:
            n = s["name"]
            out[f"type-{n}-size"] = s["fontSize"]
            out[f"type-{n}-lh"] = str(s["lineHeight"])
            out[f"type-{n}-weight"] = str(s["fontWeight"])
            if s.get("letterSpacing"):
                out[f"type-{n}-ls"] = s["letterSpacing"]
    for _ in range(5):                                   # aliases, a few levels at most
        for k, v in list(out.items()):
            m = re.fullmatch(r"\{([a-z0-9-]+)\}", str(v))
            if m:
                if m.group(1) not in out:
                    raise TokenError(f"token {k} refers to unknown {m.group(1)}")
                out[k] = out[m.group(1)]
    left = [k for k, v in out.items() if re.fullmatch(r"\{[a-z0-9-]+\}", str(v))]
    if left:
        raise TokenError(f"unresolved token aliases: {left}")
    return out


def root_css(tok: dict = None) -> str:
    v = values(tok)
    return ":root{" + "".join(f"--{k}:{val};" for k, val in v.items()) + "}"


def _data_uri(name: str) -> str:
    p = FONTS / name
    if not p.is_file():
        raise TokenError(f"font file {p} is missing")
    return "data:font/woff2;base64," + base64.b64encode(p.read_bytes()).decode("ascii")


def font_faces(tok: dict = None) -> str:
    tok = tok or load()
    out = []
    for f in tok["type"]["fonts"]:
        rng = f.get("unicodeRange")
        if not rng:
            raise TokenError(f"tokens.json type.fonts {f['family']}: no unicodeRange (4b addition)")
        out.append(f"@font-face{{font-family:'{f['family']}';font-style:{f['style']};font-weight:{f['weight']};"
                   f"font-display:swap;src:url({_data_uri(Path(f['file']).name)}) format('woff2');"
                   f"unicode-range:{rng};}}")
    return "".join(out)


def bundle_css() -> str:
    """bundle.css with its font URLs embedded; nothing else changed."""
    css = BUNDLE.read_text(encoding="utf-8")
    css = re.sub(r"url\(\.\./fonts/([A-Za-z0-9_.-]+\.woff2)\)", lambda m: f"url({_data_uri(m.group(1))})", css)
    stray = [u for u in re.findall(r"url\(([^)]*)\)", css) if not u.startswith("data:")]
    if stray:
        raise TokenError(f"bundle.css asks for {stray}: the hub makes no requests")
    return css


def fill(css: str, tok: dict = None) -> str:
    """{{token-name}} -> its value (media queries, which cannot read var())."""
    v = values(tok)

    def one(m):
        if m.group(1) not in v:
            raise TokenError(f"unknown token {{{{{m.group(1)}}}}} in the renderer's CSS")
        return v[m.group(1)]
    return re.sub(r"\{\{([a-z0-9-]+)\}\}", one, css)


def css(own: str) -> str:
    """The page's whole stylesheet: fonts, tokens, bundle.css, then the
    renderer's own layout CSS (tokens only)."""
    tok = load()
    return font_faces(tok) + root_css(tok) + bundle_css() + fill(own, tok)
