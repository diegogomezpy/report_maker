"""A brand config, resolved once and applied once.

The bug this exists to prevent is not a crash. It is a config being ACCEPTED
WHOLE and honoured in part: `KNOWN_KEYS` recognised 51 keys while the module
applied two, so a brand handed over its cover art, sigil, watermark and copy and
got back colours and a logo, silently. `test_theme_reads_only_what_apply_writes`
is the structural guard against that reopening.
"""
from __future__ import annotations

import base64
import io
import re
from pathlib import Path

import pytest

pytest.importorskip("fpdf")

import reportkit.branding as B                       # noqa: E402
from reportkit import ReportDocument                 # noqa: E402

FONTS = Path(B.__file__).resolve().parent / "fonts"


def png_b64(w=40, h=20, rgb=(30, 60, 90)) -> str:
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (w, h), rgb).save(buf, "PNG")
    return base64.b64encode(buf.getvalue()).decode()


def full_config() -> dict:
    """A config exercising every family of key a brand can set."""
    return {
        "firm_name": "Acme Capital",
        "primary_color": "#0B3B2E", "accent_color": "#20948A",
        "chart_secondary_color": "#C69426", "section_rule_color": "#A3C83F",
        "panel_color": "#ECF1F6", "sidebar_bar_color": "#0B3B2E",
        "report_theme": "hexagon",
        "logo_base64": png_b64(320, 96),
        "cover_logo_base64": png_b64(560, 120),
        "cover_sigil_base64": png_b64(200, 200),
        "filler_images_base64": [png_b64(90, 60), png_b64(90, 61), png_b64(90, 62)],
        "watermark_base64": png_b64(100, 100),
        "cover_overlay_color": "#0B3B2E", "cover_overlay_opacity": 0.7,
        "cover_logo_x_pct": 0.1, "cover_sigil_opacity": 0.3,
        "report_title": "Quarterly Review", "website": "acme.example",
        "contact": "ir@acme.example", "footer_note": "Confidential",
        "disclaimer_body": "Not investment advice.",
    }


# ── the structural guard ─────────────────────────────────────────────────────

def test_theme_reads_only_what_apply_writes():
    """Every brand attribute the THEME layer reads must be one `apply_brand`
    writes — or it is dead for every consumer that isn't the original host.

    That was literally true before this: `theme.py` read `watermark` 38 times
    and `cover_sigil_bytes` four, and nothing in the package wrote either.
    """
    src = (Path(B.__file__).resolve().parent / "theme.py").read_text()
    read = set(re.findall(r'getattr\(pdf,\s*"([a-z_]+)"', src))
    read |= set(re.findall(r"\bpdf\.([a-z_][a-z_0-9]*)\b", src))

    # Not brand state, by PATTERN rather than by list — an enumeration rots the
    # first time fpdf or the document grows a method, and the failure looks like
    # a real finding. Excluded: fpdf's verb surface, page geometry, the token
    # palette (derived in the constructor FROM the palette, not applied), and
    # document internals.
    verbs = re.compile(r"^(set|get|add|new|use|is|has)_")
    not_brand = {
        # The theme-author protocol — methods a theme draws THROUGH, not brand
        # state. Public since 1.0, so the verb-prefix rule no longer excludes
        # them and they have to be named.
        "sf", "safe", "eyebrow", "fit_font", "head_claimed", "decorate_void",
        "decorate_void_photo", "draw_cover_logo", "draw_sigil", "draw_left_photo",
        "full_bleed", "bookmark", "link_for", "open_section", "start_section",
        "cell", "multi_cell", "rect", "line", "image", "text", "write", "ln",
        "local_context", "drawing", "pattern", "page_no", "output", "dashed_line",
        "w", "h", "k", "x", "y", "l_margin", "r_margin", "t_margin", "b_margin",
        "font_family", "font_size", "font_style", "font_size_pt",
        "theme", "tokens", "t", "lang", "doc_ref", "chapter_nums",
        # Palette tokens: derived once in __init__, never "applied".
        "primary_color", "accent_color", "section_rule_color", "panel_color",
        "sidebar_bar_color", "ink", "lime", "teal", "amber", "amber_dark",
        "muted", "body_ink", "rule_soft", "footnote_grey", "panel", "sidebar_bar",
    }
    brand_reads = {a for a in read
                   if not a.startswith("_") and not verbs.match(a)} - not_brand
    unwritten = sorted(brand_reads - set(B.APPLIED_ATTRS))
    assert not unwritten, (
        f"theme.py reads brand attributes nothing applies: {unwritten}. "
        "Either apply_brand should write them (and APPLIED_ATTRS list them), "
        "or the theme should not read them — but 'recognised and ignored' is "
        "the failure this test exists to prevent.")


def test_a_bare_document_has_every_attribute_the_theme_reads():
    """A document built with no Brand at all must still render: the theme reads
    these by name, and an AttributeError mid-draw abandons a half-written PDF."""
    doc = ReportDocument(font_dir=FONTS)
    missing = [a for a in B.APPLIED_ATTRS if not hasattr(doc, a)]
    assert not missing, f"undeclared on a bare document: {missing}"


# ── resolve ──────────────────────────────────────────────────────────────────

def test_resolve_reads_the_whole_config():
    b = B.resolve(full_config(), default_firm_name="Fallback")
    assert b.primary == (11, 59, 46) and b.section_rule == (163, 200, 63)
    assert b.firm_name == "Acme Capital" and b.theme_name == "hexagon"
    assert b.logo and b.cover_logo and b.cover_sigil and b.watermark_image
    assert b.cover_image and b.back_image and len(b.fillers) == 1
    assert b.report_title == "Quarterly Review" and b.website == "acme.example"
    assert b.disclaimer_body == "Not investment advice."
    assert b.overlay_opacity == 0.7
    assert b.placement["cover_logo_x_pct"] == 0.1
    assert not b.warnings


def test_an_empty_config_resolves_to_defaults_not_an_error():
    b = B.resolve({}, default_firm_name="Fallback")
    assert b.primary == B.DEFAULT_PRIMARY and b.firm_name == "Fallback"
    assert b.logo is None and b.fillers == ()


def test_unknown_keys_are_reported_not_silently_dropped():
    b = B.resolve({"nonsense": 1, "primary_color": "#0B3B2E"},
                  default_firm_name="X")
    assert any("nonsense" in w for w in b.warnings)
    assert b.primary == (11, 59, 46), "a bad key must not cost the good ones"


def test_host_keys_pass_through_extras_without_warning():
    b = B.resolve({"cover_metrics": ["a"], "underlying_labels": "name"},
                  extra_keys=("cover_metrics", "underlying_labels"),
                  default_firm_name="X")
    assert b.extras["underlying_labels"] == "name"
    assert not b.warnings


def test_the_two_outside_world_sources_are_opt_in_and_say_so():
    b = B.resolve({"logo_url": "https://x.invalid/l.png",
                   "logo_file": "logo.png"}, default_firm_name="X")
    assert b.logo is None
    assert any("logo_url" in w for w in b.warnings)
    assert any("logo_file" in w for w in b.warnings)


def test_a_malformed_colour_costs_a_colour_not_the_brand():
    b = B.resolve({"primary_color": "#zz", "accent_color": "#20948A"},
                  default_firm_name="X")
    assert b.primary == B.DEFAULT_PRIMARY
    assert b.accent == (32, 148, 138)


def test_legacy_watermark_enabled_false_drops_the_image():
    """Old configs still say this, and it means 'use the theme's drawn mark'."""
    cfg = dict(full_config(), watermark_enabled=False)
    assert B.resolve(cfg, default_firm_name="X").watermark_image is None


def test_brand_is_frozen():
    b = B.resolve({}, default_firm_name="X")
    with pytest.raises(Exception):
        b.primary = (1, 2, 3)


def test_copy_is_language_resolved_at_resolve_time():
    cfg = {"footer_note": {"en": "Confidential", "es": "Confidencial"}}
    assert B.resolve(cfg, lang="es", default_firm_name="X").footer_note == "Confidencial"
    assert B.resolve(cfg, lang="en", default_firm_name="X").footer_note == "Confidential"


# ── apply_brand ──────────────────────────────────────────────────────────────

def test_apply_writes_every_applied_attr():
    b = B.resolve(full_config(), default_firm_name="X")
    doc = ReportDocument(brand=b, font_dir=FONTS)
    doc.apply_brand(b, font_dir=FONTS)
    assert doc.cover_image_bytes and doc.back_image_bytes
    assert doc.cover_sigil_bytes and doc.watermark
    assert doc.filler_image_list and doc.report_title == "Quarterly Review"
    assert doc.cover_overlay_opacity == 0.7
    assert doc.cover_logo_x_pct == 0.1


def test_the_palette_arrives_at_construction_not_after():
    """`build_tokens` runs once in __init__; a palette applied later would need
    a second derivation site, which is the bug class this package removed."""
    b = B.resolve({"primary_color": "#0B3B2E"}, default_firm_name="X")
    doc = ReportDocument(brand=b, font_dir=FONTS)
    assert doc.primary_color == (11, 59, 46)
    assert sum(doc.ink) < sum(doc.primary_color), "tokens derived from the brand"


def test_the_cover_photo_does_not_reappear_as_a_body_band():
    """Filler pool AFTER cover/back selection — the ordering apply_brand owns."""
    b = B.resolve(full_config(), default_firm_name="X")
    doc = ReportDocument(brand=b, font_dir=FONTS)
    doc.apply_brand(b, font_dir=FONTS)
    assert doc.cover_image_bytes not in doc.filler_image_list
    assert doc.back_image_bytes not in doc.filler_image_list


def test_a_full_brand_renders_a_document():
    b = B.resolve(full_config(), default_firm_name="X")
    doc = ReportDocument(brand=b, font_dir=FONTS)
    doc.apply_brand(b, font_dir=FONTS)
    doc.add_page()
    doc.section_title("Performance")
    doc.metric_band([("Return", "8.4%"), ("Vol", "11.2%")])
    doc.data_table(["A", "B"], [["1", "2"]])
    out = bytes(doc.output())
    assert out[:4] == b"%PDF" and len(out) > 5000
