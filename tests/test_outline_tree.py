"""The PDF outline (bookmarks) and the contents-page links.

Neither existing guard can see either of these. The pixel golden rasterises
PAGES, and an outline lives in the document catalog; the pagination sweep looks
at where content landed. So both would stay green if the tree silently
disappeared, came out mis-nested, or every contents row linked to page 1 — which
is what fpdf does with a link nobody bound.

Hence direct assertions on `pdf._outline` and on the link table.
"""
from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("fpdf")

import reportkit.branding as B                       # noqa: E402
import reportkit.outline as O                        # noqa: E402
from reportkit.document import ReportDocument        # noqa: E402

FONTS = Path(B.__file__).resolve().parent / "fonts"


def doc(**kw) -> ReportDocument:
    d = ReportDocument(font_dir=FONTS, **kw)
    d.add_page()
    return d


def tree(pdf):
    return [(s.level, s.name) for s in pdf._outline]


# ── nesting ──────────────────────────────────────────────────────────────────

def test_sub_sections_of_one_chapter_are_siblings():
    """The bug a naive `min(level, last + 1)` clamp produces: the second
    sub-section nests UNDER the first, so a reader's sidebar shows
    Concentration inside Positions."""
    d = doc()
    d.section_divider("02", "HOLDINGS", "What we own")
    d.subsection("Positions")
    d.subsection("Concentration")
    assert tree(d) == [(0, "02 · What we own"), (1, "Positions"), (1, "Concentration")]


def test_a_new_chapter_closes_the_previous_one():
    d = doc()
    d.section_divider("01", "A", "First")
    d.subsection("Under first")
    d.section_divider("02", "B", "Second")
    d.subsection("Under second")
    assert [lv for lv, _ in tree(d)] == [0, 1, 0, 1]


def test_a_subsection_with_no_chapter_above_it_is_top_level():
    """A sub-section is semantically level 2, but depth is decided by how many
    ancestors are OPEN — not by the semantic number."""
    d = doc()
    d.subsection("Orphan")
    assert tree(d) == [(0, "Orphan")]


def test_a_blank_title_is_not_an_entry():
    d = doc()
    d.subsection("   ")
    assert tree(d) == []


# ── anchors ──────────────────────────────────────────────────────────────────

def test_a_bookmark_points_at_its_heading_not_below_it():
    """fpdf anchors at the LIVE cursor, and the theme hook has already advanced
    it. Without capturing the position before the hook, every bookmark lands
    18-36mm below the thing it names."""
    d = doc()
    d.set_y(90.0)
    d.subsection("Positions")
    top_mm = (d.h_pt - d._outline[-1].dest.top) / d.k
    assert top_mm == pytest.approx(90.0, abs=0.5)


def test_a_heading_that_breaks_the_page_anchors_on_the_new_one():
    """The pre-break y belongs to a page that is no longer current, so it must
    not be used — the entry would point into the middle of the previous page."""
    d = doc()
    d.set_y(250.0)
    d.subsection("Positions")
    entry = d._outline[-1]
    assert entry.dest.page_number == d.page_no() == 2
    assert (d.h_pt - entry.dest.top) / d.k == pytest.approx(d.t_margin, abs=0.5)


def test_registering_an_entry_does_not_disturb_the_cursor():
    d = doc()
    d.set_y(90.0)
    d.subsection("Positions")
    after_heading = d.get_y()
    d._mark_outline("Extra", 2, (d.page_no(), 50.0))
    assert d.get_y() == after_heading, "the outline moved the drawing cursor"


# ── the opt-out and the deprecated name ──────────────────────────────────────

def test_the_outline_can_be_switched_off():
    d = ReportDocument(font_dir=FONTS, outline=False)
    d.add_page()
    d.subsection("Positions")
    assert tree(d) == []


def test_start_section_still_works_but_warns():
    """It shadowed `FPDF.start_section` — the method fpdf2 uses to BUILD the
    outline. The shim keeps a 0.6 consumer working for one release."""
    d = doc()
    with pytest.deprecated_call():
        d.start_section("Legacy")
    assert tree(d) == [(0, "Legacy")]


def test_open_section_is_the_new_name_and_does_not_warn(recwarn):
    d = doc()
    d.open_section("Modern")
    assert tree(d) == [(0, "Modern")]
    assert not [w for w in recwarn if issubclass(w.category, DeprecationWarning)]


# ── contents links ───────────────────────────────────────────────────────────

def test_every_contents_row_resolves_to_its_heading():
    """An unbound link is not an error — fpdf silently resolves it to page 1.
    A numbered head registers as "01 · Holdings" while the contents row says
    "Holdings", so both spellings have to bind."""
    d = doc()
    O.contents_list(d, [("Holdings", "01", ["Positions"])],
                    x=16, y=40, w=100, row_h=5, gap=1)
    d.add_page()
    d.section_divider("01", "HOLDINGS", "Holdings")
    d.subsection("Positions")
    assert d.unbound_links() == []


def test_a_contents_row_with_no_heading_is_reported_not_silent():
    d = doc()
    O.contents_list(d, [(None, None, [("Nowhere", None)])],
                    x=16, y=40, w=100, row_h=5, gap=1)
    assert d.unbound_links() == ["Nowhere"]


def test_a_link_id_is_stable_for_one_title():
    d = doc()
    assert d.link_for("Positions") == d.link_for("Positions")
    assert d.link_for("Positions") != d.link_for("Concentration")


# ── end to end ───────────────────────────────────────────────────────────────

def test_the_sample_document_has_a_gapless_tree():
    from reportkit import testing as rkt
    with rkt.stub_figures():
        rkt.sample_document("mercator")     # renders; smoke only
    d = doc()
    for i, (num, name) in enumerate([("01", "Overview"), ("02", "Holdings")], 1):
        d.section_divider(num, name.upper(), name)
        d.subsection(f"Part {i}")
    levels = [lv for lv, _ in tree(d)]
    # No entry may be more than one level deeper than its predecessor, which is
    # what `FPDF.start_section(strict=True)` refuses and readers render oddly.
    assert all(b <= a + 1 for a, b in zip(levels, levels[1:]))
