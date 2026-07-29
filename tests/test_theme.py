"""The theme layer: registry, palette derivation, and colour resolution.

These are the guarantees a host application leans on. `build_tokens` in
particular is load-bearing — every identity colour in a document derives from
it, so a change here restyles every report ever generated.
"""
from __future__ import annotations

import pytest

import reportkit
from reportkit.theme import (
    DEFAULT_THEME,
    MERCATOR_SPEC,
    build_tokens,
    known_themes,
    register_theme,
    resolve_color,
    resolve_theme,
)

NAVY = (21, 41, 79)
LIME = (163, 200, 63)
TEAL = (32, 148, 138)


class FakeDoc:
    """Stands in for the live document a theme draws through.

    `resolve_color` reads brand tokens off it by attribute name, and falls back
    to `.ink` for anything it can't resolve — so a stub missing one attribute
    fails with an AttributeError that looks like a library bug and isn't.
    """

    def __init__(self):
        t = build_tokens(NAVY, TEAL, LIME)
        self.primary_color = t.primary
        self.accent_color = t.accent
        self.section_rule_color = t.section_rule
        self.panel_color = t.panel
        self.sidebar_bar_color = t.sidebar_bar
        for tok in ("ink", "lime", "teal", "amber", "amber_dark", "muted",
                    "body_ink", "rule_soft", "footnote_grey"):
            setattr(self, tok, getattr(t, tok))


def test_package_exposes_a_version():
    assert reportkit.__version__


def test_the_two_builtin_themes_resolve():
    names = known_themes()
    assert {"mercator", "hexagon"} <= set(names), names
    for name in ("mercator", "hexagon"):
        assert resolve_theme(name) is not None


def test_unknown_theme_falls_back_rather_than_raising():
    """A brand config is user-authored data. A typo must not take out the whole
    document — the report still renders, in the default identity.

    Note `.name` is the theme's DISPLAY name ("Mercator"), not its registry key
    ("mercator"); compare resolved themes to each other, not to the key.
    """
    default = resolve_theme(DEFAULT_THEME).name
    assert resolve_theme(None).name == default
    assert resolve_theme("no-such-theme").name == default
    assert resolve_theme("").name == default


def test_cadiem_is_an_alias_for_hexagon():
    assert resolve_theme("cadiem").name == resolve_theme("hexagon").name


def test_tokens_derive_the_whole_palette_from_three_colours():
    t = build_tokens(NAVY, TEAL, LIME)
    assert t.primary == NAVY and t.accent == TEAL and t.section_rule == LIME
    assert t.lime == LIME and t.teal == TEAL
    # `ink` is a darkened primary — used for mastheads and stat values, so it
    # must be materially darker than the primary or headings vanish into panels.
    assert sum(t.ink) < sum(t.primary)
    # `panel` is a near-white tint of the PRIMARY, never of the accent: deriving
    # it from a bold accent gave pink cards on a navy brand.
    assert sum(t.panel) > 3 * 200


def test_pinned_panel_and_sidebar_win_over_the_derivation():
    t = build_tokens(NAVY, TEAL, LIME, panel=(1, 2, 3), sidebar_bar=(4, 5, 6))
    assert t.panel == (1, 2, 3)
    assert t.sidebar_bar == (4, 5, 6)


@pytest.mark.parametrize("spec", ["#a3c83f", "#A3C83F"])
def test_resolve_color_accepts_hex(spec):
    assert resolve_color(spec, FakeDoc()) == LIME


def test_resolve_color_reads_brand_tokens_by_name():
    doc = FakeDoc()
    assert resolve_color("primary", doc) == NAVY
    assert resolve_color("accent", doc) == TEAL
    assert resolve_color("section_rule", doc) == LIME
    assert resolve_color("white", doc) == (255, 255, 255)


def test_hex_requires_the_leading_hash():
    """Documenting a sharp edge rather than asserting a wish: a bare `a3c83f` is
    NOT parsed as a colour — it is treated as an unknown token name and resolves
    to the ink fallback. Worth knowing when hand-authoring a theme spec."""
    doc = FakeDoc()
    assert resolve_color("a3c83f", doc) == doc.ink


def test_malformed_colour_does_not_abort_the_document():
    """`#zz` in a hand-written theme spec used to raise ValueError and kill the
    whole render. A bad colour must degrade to something drawable."""
    doc = FakeDoc()
    for bad in ("#zz", "", "#", "#12345"):
        got = resolve_color(bad, doc)
        assert isinstance(got, tuple) and len(got) == 3, (bad, got)
        assert all(isinstance(v, int) and 0 <= v <= 255 for v in got), (bad, got)


def test_register_theme_adds_to_the_registry():
    spec = dict(MERCATOR_SPEC, name="acme")
    register_theme("acme", spec)
    assert "acme" in known_themes()
    assert resolve_theme("acme").name == "acme"


# ── shared mutable state ─────────────────────────────────────────────────────

def test_a_resolved_theme_does_not_alias_the_registry():
    """`resolve_theme("hexagon").spec` used to BE the module global, so
    `t.spec[...] = x` was a process-wide edit visible to every later resolve —
    and `hexagon` and `cadiem` map to the same object, so editing one silently
    re-themed the other."""
    from reportkit.theme import HEXAGON_SPEC, resolve_theme
    t = resolve_theme("hexagon")
    assert t.spec is not HEXAGON_SPEC
    t.spec["probe"] = 99
    t.spec.setdefault("header", {})["probe"] = 99
    assert "probe" not in HEXAGON_SPEC
    assert "probe" not in resolve_theme("cadiem").spec
    assert "probe" not in (HEXAGON_SPEC.get("header") or {}), "nested dict aliased"


def test_builtin_spec_hands_out_a_copy_to_build_on():
    from reportkit.theme import HEXAGON_SPEC, builtin_spec
    a, b = builtin_spec("hexagon"), builtin_spec("hexagon")
    assert a == b and a is not b and a is not HEXAGON_SPEC
    a["name"] = "mine"
    assert HEXAGON_SPEC.get("name") != "mine"


def test_registering_a_theme_copies_the_spec():
    from reportkit.theme import known_themes, register_theme, resolve_theme
    mine = {"name": "Probe"}
    register_theme("probe-theme", mine)
    mine["name"] = "edited after registering"
    assert resolve_theme("probe-theme").spec["name"] == "Probe"
    assert "probe-theme" in known_themes()


def test_chrome_labels_are_handed_out_by_value():
    from reportkit.document import CHROME_LABELS, chrome_labels
    got = chrome_labels()
    assert got == CHROME_LABELS and got is not CHROME_LABELS
    got["figure_word"]["en"] = "Plate"
    assert CHROME_LABELS["figure_word"]["en"] == "Figure"


def test_image_roles_is_a_frozen_value():
    """It is the OUTPUT of the slot algorithm; reassigning a role afterwards is
    re-deciding the assignment where the algorithm cannot see it."""
    import dataclasses
    import pytest as _pytest
    from reportkit.branding import ImageRoles
    r = ImageRoles(b"cover", b"back", (b"filler",))
    with _pytest.raises(dataclasses.FrozenInstanceError):
        r.cover = b"other"
    assert isinstance(r.fillers, tuple)
