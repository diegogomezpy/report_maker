"""
reportkit.color — CSS colour parsing and palette remapping.

A themed report re-colours artwork it did not draw: a chart arrives in whatever
palette its plotting library used, and has to come out in the brand's. That is a
string-rewriting problem over CSS colour notation, and it is entirely separate
from *how* the artwork was produced — so it lives in the core, not behind the
optional `charts` extra. Nothing here imports Plotly.

The one piece of domain knowledge encoded here is the **blue-family hue window**:
sequential colour ramps are conventionally authored in blues, and a ramp cannot
be remapped value-by-value the way a discrete series can (its stops are
generated, not enumerated). So a ramp is recognised by hue and rotated wholesale
onto the brand's hue, preserving saturation and lightness.
"""
from __future__ import annotations

import colorsys
import re

# The hue band, in degrees, treated as "this is a blue ramp, rotate it".
# Deliberately a parameter rather than a constant at the call site: it is the
# only tunable in the remap, and hard-coding it was how the behaviour became
# invisible.
BLUE_RAMP_WINDOW = (195.0, 255.0)

_RGB_FUNC = re.compile(
    r"rgba?\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*(?:,\s*([\d.]+)\s*)?\)")
_HSL_FUNC = re.compile(
    r"hsl\(\s*(\d+(?:\.\d+)?)\s*,\s*([\d.]+)%\s*,\s*([\d.]+)%\s*\)")


def rgb_to_hue(rgb: tuple) -> float:
    """HSL hue in degrees [0, 360) for an (R, G, B) 0-255 tuple."""
    r, g, b = (c / 255.0 for c in rgb[:3])
    h, _l, _s = colorsys.rgb_to_hls(r, g, b)
    return h * 360.0


def parse_rgb(c: str):
    """`(r, g, b, alpha_or_None)` for a hex or `rgb()`/`rgba()` string, else None.

    Note this is NOT `reportkit.theme._parse_hex`, and the two must not be
    merged: that one returns a 3-tuple and substitutes a default for anything
    malformed, because it feeds a drawing call that must not raise. This one
    returns None on anything it doesn't recognise, because its caller's correct
    response to "not a colour I know" is to leave the string alone.
    """
    if not isinstance(c, str):
        return None
    s = c.strip().lower()
    if s.startswith("#"):
        s = s[1:]
        if len(s) == 3:
            s = "".join(ch * 2 for ch in s)
        if len(s) == 6:
            try:
                return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16), None)
            except ValueError:
                return None
        return None
    m = _RGB_FUNC.match(s)
    if m:
        r, g, b = (int(float(m.group(i))) for i in (1, 2, 3))
        a = float(m.group(4)) if m.group(4) is not None else None
        return (r, g, b, a)
    return None


def remap_color(c, remap: dict, ramp_hue: float,
                ramp_window: tuple = BLUE_RAMP_WINDOW):
    """Map one colour through `remap`, preserving any alpha.

    `remap` is keyed by (r, g, b) source tuple. A colour whose RGB is not a known
    source value is returned UNCHANGED — that is what keeps semantic colours
    (a red loss bar, a grey gridline) from being repainted by a brand palette.

    An `hsl()` colour inside `ramp_window` is hue-rotated to `ramp_hue` instead,
    since a generated ramp has no enumerable stops to look up.
    """
    if isinstance(c, str):
        h = _HSL_FUNC.match(c.strip().lower())
        if h:
            hue = float(h.group(1))
            if ramp_window[0] <= hue <= ramp_window[1]:
                return f"hsl({ramp_hue:.0f},{h.group(2)}%,{h.group(3)}%)"
            return c
    p = parse_rgb(c)
    if p is None:
        return c
    rgb, alpha = p[:3], p[3]
    tgt = remap.get(rgb)
    if tgt is None:
        return c
    if alpha is None:
        return f"rgb({tgt[0]},{tgt[1]},{tgt[2]})"
    return f"rgba({tgt[0]},{tgt[1]},{tgt[2]},{alpha})"
