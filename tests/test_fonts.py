"""Font registration — the whole-document failure mode.

These run against the TTFs this package ships, which is also the
default an external install gets.

If the default family fails to register, every page renders in Helvetica:
Latin-1 only, so Spanish copy and typographic punctuation degrade or raise. It
is the single largest silent behaviour change available in this codebase, and
until now nothing tested it.

`register_brand_fonts` was likewise unguarded: no brand fixture sets
`title_font`, so the golden renders identically whether it works or not.
"""
from __future__ import annotations

import pytest

pytest.importorskip("fpdf")

import reportkit.fonts as F                                     # noqa: E402
from reportkit.text import _safe                                # noqa: E402


class Doc:
    """Minimal stand-in: registration only needs add_font and a style map."""

    def __init__(self):
        self.registered = []
        self._sf_map = dict(F.DEFAULT_STYLE_MAP)
        # register_brand_fonts only routes brand faces on the Unicode path.
        self._font_family = F.FAMILY

    def add_font(self, family, style="", fname="", uni=True):
        self.registered.append((family, style))


def test_default_family_registers_all_six_weights(tmp_path):
    doc = Doc()
    assert F.register_default_family(doc, font_dir=F._BUNDLED_DIR) is True
    assert doc.registered == [
        (F.FAMILY, ""), (F.FAMILY, "B"), (F.FAMILY, "I"), (F.FAMILY, "BI"),
        (F.FAMILY_SEMIBOLD, ""), (F.FAMILY_LIGHT, ""),
    ], "registration order determines PDF font-object numbering — keep it stable"


def test_a_missing_weight_fails_the_whole_family(tmp_path):
    """All six or none. A partial registration would leave `sf('light')`
    pointing at a family that was never added, and fpdf2 raises mid-draw —
    after pages have already been emitted."""
    (tmp_path / "IBMPlexSans-Regular.ttf").write_bytes(b"x")
    assert F.register_default_family(Doc(), font_dir=tmp_path) is False


def test_empty_font_dir_falls_back(tmp_path):
    assert F.register_default_family(Doc(), font_dir=tmp_path) is False


def test_helvetica_map_covers_every_weight_the_default_map_does():
    """The fallback has to answer every `sf(weight)` the document asks for, or
    a Helvetica render dies on the first semibold heading."""
    assert set(F.HELVETICA_STYLE_MAP) == set(F.DEFAULT_STYLE_MAP)


def test_latin1_sanitisation_is_what_makes_the_fallback_survivable():
    """On the Helvetica path every glyph outside Latin-1 must be transliterated
    first — the two are one mechanism, which is why they moved together."""
    hard = "Rendimiento — 12,5% · κ ≥ 0,5 … “quoted”"
    out = _safe(hard, latin1=True)
    out.encode("latin-1")            # must not raise; that is the whole point
    assert "kappa" in out and ">=" in out and "—" not in out


def test_unicode_path_leaves_typography_alone():
    s = "Rendimiento — 12,5% · κ ≥ 0,5"
    assert _safe(s) == s, "with a Unicode face nothing should be transliterated"


def test_brand_font_overrides_the_weight_map(tmp_path):
    """A brand names a face and supplies the files; the map is rebound to it.
    This runs AFTER the default family by construction — running it earlier
    changes which face draws what on every page."""
    import shutil

    brand = tmp_path / "brand"
    brand.mkdir()
    for suffix in ("Regular", "Bold"):
        shutil.copy(F._BUNDLED_DIR / f"IBMPlexSans-{suffix}.ttf",
                    brand / f"AcmeSans-{suffix}.ttf")

    doc = Doc()
    F.register_brand_fonts(doc, {"body_font": "Acme Sans"}, brand_dir=brand)
    assert doc._sf_map["regular"][0] != F.FAMILY, "body font did not take"
    assert doc._sf_map["bold"][0] != F.FAMILY, "no title font ⇒ body bold heads"


def test_brand_font_with_no_regular_weight_is_refused(tmp_path):
    """Bold-only is not a usable body face. Falling back beats rendering the
    whole document in a display weight."""
    import shutil

    brand = tmp_path / "brand"
    brand.mkdir()
    shutil.copy(F._BUNDLED_DIR / "IBMPlexSans-Bold.ttf", brand / "AcmeSans-Bold.ttf")

    doc = Doc()
    F.register_brand_fonts(doc, {"body_font": "Acme Sans"}, brand_dir=brand)
    assert doc._sf_map["regular"] == F.DEFAULT_STYLE_MAP["regular"]


def test_no_branding_leaves_the_map_untouched():
    doc = Doc()
    F.register_brand_fonts(doc, None)
    F.register_brand_fonts(doc, {})
    assert doc._sf_map == F.DEFAULT_STYLE_MAP
