"""Colour parsing and palette remapping.

The golden is blind to this: `_remap_color` is only reached from
`_rebrand_figure`, which the stubbed figure hook short-circuits, so a report can
render pixel-identical with this layer completely broken. These are the tests
that actually cover it.
"""
from __future__ import annotations

import pytest

from reportkit.color import BLUE_RAMP_WINDOW, parse_rgb, remap_color, rgb_to_hue

NAVY = (26, 46, 74)
BLUE = (37, 99, 235)
BRAND = (11, 59, 46)


@pytest.mark.parametrize("text,expected", [
    ("#1a2e4a", (26, 46, 74, None)),
    ("#1A2E4A", (26, 46, 74, None)),
    ("#abc", (170, 187, 204, None)),          # 3-digit shorthand expands
    ("rgb(37, 99, 235)", (37, 99, 235, None)),
    ("rgba(37,99,235,0.4)", (37, 99, 235, 0.4)),
    ("  rgb(1,2,3)  ", (1, 2, 3, None)),      # surrounding space tolerated
])
def test_parse_rgb_accepts_the_css_forms_plotly_emits(text, expected):
    assert parse_rgb(text) == expected


@pytest.mark.parametrize("text", [
    "", "#", "#12", "#12345", "#gggggg", "hsl(200,50%,50%)",
    "papayawhip", None, 42, ("r", "g", "b"),
])
def test_parse_rgb_returns_none_for_anything_it_does_not_know(text):
    """None, not a default. The caller's correct response to an unrecognised
    colour is to leave the string alone — substituting a default here would
    repaint named colours and gradients."""
    assert parse_rgb(text) is None


def test_remap_swaps_a_known_source_colour():
    assert remap_color("#1a2e4a", {NAVY: BRAND}, 160.0) == "rgb(11,59,46)"


def test_remap_preserves_alpha():
    """Band fills are semi-transparent; dropping alpha turns a translucent
    confidence band into an opaque block that hides the series under it."""
    got = remap_color("rgba(37,99,235,0.4)", {BLUE: BRAND}, 160.0)
    assert got == "rgba(11,59,46,0.4)"


def test_unknown_colours_pass_through_untouched():
    """This is what keeps semantic colours safe. Red means loss regardless of
    the brand palette, so it must not be in the remap and must survive it."""
    for c in ("#dc2626", "rgb(220,38,38)", "grey", "#000000"):
        assert remap_color(c, {NAVY: BRAND}, 160.0) == c


@pytest.mark.parametrize("hue,rotated", [
    (195.0, True), (220.0, True), (255.0, True),     # inclusive at both ends
    (194.9, False), (255.1, False), (0.0, False), (120.0, False),
])
def test_only_the_blue_family_ramp_is_hue_rotated(hue, rotated):
    """A sequential ramp has generated stops, so it can't be remapped
    value-by-value — it is recognised by hue and rotated wholesale. A ramp
    authored in another hue is deliberate and must be left alone."""
    got = remap_color(f"hsl({hue},60%,50%)", {}, 160.0)
    assert (got != f"hsl({hue},60%,50%)") is rotated
    if rotated:
        assert got == "hsl(160,60%,50%)", "saturation/lightness must survive"


def test_ramp_window_is_a_parameter_not_a_hidden_constant():
    c = "hsl(300,60%,50%)"
    assert remap_color(c, {}, 160.0) == c
    assert remap_color(c, {}, 160.0, ramp_window=(290.0, 310.0)) == "hsl(160,60%,50%)"
    assert BLUE_RAMP_WINDOW == (195.0, 255.0)


def test_rgb_to_hue_matches_the_colour_wheel():
    assert rgb_to_hue((255, 0, 0)) == pytest.approx(0.0)
    assert rgb_to_hue((0, 255, 0)) == pytest.approx(120.0)
    assert rgb_to_hue((0, 0, 255)) == pytest.approx(240.0)
    assert 195 <= rgb_to_hue(BLUE) <= 255, "the source blue must sit in the ramp window"
