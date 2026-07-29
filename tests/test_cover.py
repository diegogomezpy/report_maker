"""Full-bleed pages.

The thing worth testing here is not that a rectangle got painted — it is the
ORDER, because every step of a cover fails silently when it is done wrong. A
missing `_cover_pages` entry prints a running footer across the artwork. A
missing overlay throws the brand's colour away and leaves whatever the
photograph happened to contain. `_is_cover` raised after `add_page` misses the
header hook entirely. None of those raise; all of them ship.
"""
from __future__ import annotations

import base64
import io
from pathlib import Path

import pytest

pytest.importorskip("fpdf")

import reportkit.branding as B                       # noqa: E402
import reportkit.cover as C                          # noqa: E402
from reportkit import ReportDocument                 # noqa: E402
from reportkit.theme import SpecTheme                # noqa: E402

FONTS = Path(B.__file__).resolve().parent / "fonts"


def png(w=1200, h=800, rgb=(200, 80, 40)) -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (w, h), rgb).save(buf, "PNG")
    return buf.getvalue()


def doc(**kw) -> ReportDocument:
    return ReportDocument(font_dir=FONTS, **kw)


# ── the opening/closing protocol ─────────────────────────────────────────────

def test_the_page_registers_itself_as_a_cover():
    """`_cover_pages` is what the footer and the void decorator consult. A cover
    that isn't in it gets a page number and a footer rule across its artwork."""
    d = doc()
    d.add_page()                                   # an ordinary content page
    with d.full_bleed():
        assert d.page_no() in d._cover_pages
    assert d._cover_pages == {2}, "only the full-bleed page is a cover"


def test_is_cover_is_raised_before_add_page_and_lowered_after():
    """fpdf2 calls the NEW page's `header()` from inside `add_page`, so the flag
    has to be up by then — it is the theme's only signal to skip the running
    header. Recorded from inside the hook, which is the only honest witness."""
    seen = []

    class Probe(ReportDocument):
        def header(self):
            seen.append(self._is_cover)
            return super().header()

    d = Probe(font_dir=FONTS)
    with d.full_bleed():
        pass
    assert seen == [True], "header ran without _is_cover raised"
    assert d._is_cover is False, "the flag must not leak past the page"


def test_the_flag_is_lowered_even_when_the_body_raises():
    d = doc()
    with pytest.raises(ValueError):
        with d.full_bleed():
            raise ValueError("boom")
    assert d._is_cover is False


def test_auto_page_break_is_off_so_content_cannot_spill():
    d = doc()
    with d.full_bleed():
        assert d.auto_page_break is False
    assert d.page_no() == 1, "nothing may break off a full-bleed page"


def test_it_yields_the_page_size():
    d = doc()
    with d.full_bleed() as (w, h):
        assert (w, h) == (d.w, d.h)


# ── painting ─────────────────────────────────────────────────────────────────

def test_the_overlay_runs_even_when_the_photo_fails_to_draw():
    """A cover that silently loses its colour is worse than one that loses its
    photograph, so the tint is not inside the image's try/except."""
    d = doc()
    d.cover_overlay_opacity = 0.6
    calls = []
    d.image = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("bad image"))
    _orig = C.paint_overlay
    C.paint_overlay = lambda pdf, w, h: calls.append("overlay")
    try:
        with d.full_bleed(image=b"not a png"):
            pass
    finally:
        C.paint_overlay = _orig
    assert calls == ["overlay"]


def test_no_image_means_no_overlay():
    """Without a photo the background IS the fill; tinting it would double it."""
    d = doc()
    d.cover_overlay_opacity = 0.6
    calls = []
    _orig = C.paint_overlay
    C.paint_overlay = lambda pdf, w, h: calls.append("overlay")
    try:
        with d.full_bleed():
            pass
    finally:
        C.paint_overlay = _orig
    assert calls == []


def test_zero_opacity_paints_nothing():
    d = doc()
    d.cover_overlay_opacity = 0.0
    d.rect = lambda *a, **k: pytest.fail("painted at zero opacity")
    C.paint_overlay(d, d.w, d.h)          # must simply return


def test_a_gradient_theme_tints_as_a_gradient():
    """The overlay is the theme's own cover fill at opacity — a linear fill has
    to tint as a linear, not collapse to a flat wash of its first stop."""
    spec = {"name": "Grad", "cover": {"fill": {
        "type": "linear", "angle": 90,
        "stops": [{"color": "#0B3B2E", "at": 0}, {"color": "#20948A", "at": 1}]}}}
    d = doc(theme=SpecTheme(spec))
    d.cover_overlay_opacity = 0.5
    assert C.cover_fill(d)["type"] == "linear"
    seen = {}
    import reportkit.cover as _c
    _orig = _c.paint_shape
    _c.paint_shape = lambda pdf, x, y, w, h, shape, fill, **kw: seen.update(kw, fill=fill)
    try:
        C.paint_overlay(d, d.w, d.h)
    finally:
        _c.paint_shape = _orig
    assert seen["fill"]["type"] == "linear" and seen["opacity"] == 0.5


def test_a_themeless_brand_still_gets_a_legible_wash():
    """No `cover.fill` at all ⇒ fall back to the flat brand colour, so text over
    a photograph stays readable instead of sitting on bare pixels.

    Note NO built-in theme declares a `cover.fill`, so this is the branch every
    stock report actually takes — not an exotic fallback.
    """
    d = doc()
    d.cover_overlay_color = (11, 59, 46)
    d.cover_overlay_opacity = 0.55
    fills = []
    d.set_fill_color = lambda *c: fills.append(c)
    C.paint_overlay(d, d.w, d.h)
    assert fills == [(11, 59, 46)]


def test_an_unset_overlay_colour_falls_back_instead_of_raising():
    """`cover_overlay_color` is DECLARED and defaults to None, so the getattr
    default never fires. Before this fell back, `set_fill_color(*None)` raised
    from the middle of a half-painted cover for any document built without
    `apply_brand` — which is exactly how a new consumer starts."""
    d = doc(primary_color=(11, 59, 46))
    assert d.cover_overlay_color is None, "the None hole this guards"
    d.add_page()
    C.paint_overlay(d, d.w, d.h)          # must not raise
    assert C._overlay_color(d) == (11, 59, 46)


# ── logo / sigil placement ───────────────────────────────────────────────────

def test_the_cover_logo_uses_its_own_aspect_not_the_header_logos():
    """A wide cover wordmark squished into the header logo's box is the bug this
    guards; the two are independent images with independent shapes."""
    d = doc()
    d.firm_logo_bytes = png(100, 100)
    d.firm_logo_aspect = 1.0
    d.cover_logo_bytes = png(600, 100)
    d.cover_logo_aspect = 6.0
    drawn = {}
    d.image = lambda b, x=0, y=0, w=0, h=0, **k: drawn.update(w=w, h=h)
    d.draw_cover_logo()
    assert drawn["w"] / drawn["h"] == pytest.approx(6.0)


def test_placement_percentages_are_of_the_page():
    d = doc()
    d.cover_logo_bytes = png(300, 100)
    d.cover_logo_aspect = 3.0
    d.cover_logo_x_pct, d.cover_logo_y_pct = 25.0, 50.0
    at = {}
    d.image = lambda b, x=0, y=0, w=0, h=0, **k: at.update(x=x, y=y)
    d.draw_cover_logo()
    assert at["x"] == pytest.approx(d.w * 0.25)
    assert at["y"] == pytest.approx(d.h * 0.50)


def test_no_sigil_is_not_an_error():
    d = doc()
    d.image = lambda *a, **k: pytest.fail("drew a sigil that does not exist")
    d.draw_sigil()


def test_the_sigil_bleeds_off_the_top_right_by_default():
    d = doc()
    d.add_page()                # local_context needs a page to write into
    d.cover_sigil_bytes = png(200, 200)
    at = {}
    d.image = lambda b, x=0, y=0, w=0, h=0, **k: at.update(x=x, y=y, w=w, h=h)
    d.draw_sigil()
    assert at["y"] < 0, "should bleed off the top edge"
    assert at["x"] + at["w"] > d.w, "should bleed off the right edge"


# ── the tall left column ─────────────────────────────────────────────────────

def test_the_left_photo_declines_a_column_too_small_to_fill():
    d = doc()
    assert C.left_photo(d, 16, 100, 60, 140, png()) is False   # 40mm of height
    assert C.left_photo(d, 16, 60, 20, 240, png()) is False    # 20mm of width


def test_the_left_photo_reports_failure_rather_than_raising():
    """It is decoration on a page that has already been laid out — a bad image
    must cost the photo, not the report."""
    d = doc()
    assert C.left_photo(d, 16, 40, 60, 240, b"not an image") is False


def test_the_left_photo_draws_and_reports_success():
    d = doc()
    d.add_page()
    assert C.left_photo(d, 16, 40, 60, 240, png()) is True


# ── end to end ───────────────────────────────────────────────────────────────

def test_a_branded_cover_renders():
    b = B.resolve({
        "firm_name": "Acme", "primary_color": "#0B3B2E", "accent_color": "#20948A",
        "cover_logo_base64": base64.b64encode(png(560, 120)).decode(),
        "cover_sigil_base64": base64.b64encode(png(200, 200)).decode(),
        "cover_image_base64": base64.b64encode(png(1200, 800)).decode(),
        "cover_overlay_opacity": 0.6,
    }, default_firm_name="X")
    d = ReportDocument(brand=b, font_dir=FONTS)
    d.apply_brand(b, font_dir=FONTS)
    with d.full_bleed(image=d.cover_image_bytes) as (w, h):
        d.draw_sigil()
        d.draw_cover_logo()
        d.eyebrow(d.l_margin, h * 0.5, "QUARTERLY REVIEW", d.section_rule_color)
    d.add_page()
    d.section_title("Body")
    out = bytes(d.output())
    assert out[:4] == b"%PDF"
    assert d._cover_pages == {1}, "the body page must not be marked a cover"
