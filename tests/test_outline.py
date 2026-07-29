"""Chapter numbers, the contents list, and headings that wait for content.

These are guarded as ARITHMETIC, not as drawing: the shed order, the shrink
threshold and the numbering are decisions with right answers, and each of them
was once made independently in two places that drifted apart.
"""
from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("fpdf")

import reportkit.branding as B                       # noqa: E402
import reportkit.outline as O                        # noqa: E402
from reportkit import ReportDocument                 # noqa: E402
from reportkit.document import SECTION_ROOM         # noqa: E402

FONTS = Path(B.__file__).resolve().parent / "fonts"
ORDER = ("terms", "issuer", "underlying", "mc", "bt", "live", "compare")


# ── numbering ────────────────────────────────────────────────────────────────

def test_numbers_run_gapless_in_document_order():
    got = O.plan_chapters({k: True for k in ORDER}, ORDER)
    assert list(got.values()) == ["01", "02", "03", "04", "05", "06", "07"]
    assert list(got) == list(ORDER), "numbered in the given order, not dict order"


def test_omitting_a_chapter_renumbers_the_rest():
    """The bug this replaces: literals in the body meant no issuer gave 01, 03."""
    got = O.plan_chapters({"terms": True, "underlying": True, "mc": True}, ORDER)
    assert got == {"terms": "01", "underlying": "02", "mc": "03"}


def test_an_undeclared_chapter_has_no_number_rather_than_a_wrong_one():
    got = O.plan_chapters({"terms": True}, ORDER)
    assert got.get("mc", "") == "", "a missing key must read as blank, not 02"


def test_nothing_present_is_not_an_error():
    assert O.plan_chapters({}, ORDER) == {}


# ── fitting ──────────────────────────────────────────────────────────────────

def groups(n_leaves_per_head, bare=0):
    out = [(f"H{i}", f"0{i}", [f"leaf {j}" for j in range(n)])
           for i, n in enumerate(n_leaves_per_head)]
    if bare:
        out.insert(0, (None, None, [(f"row {j}", None) for j in range(bare)]))
    return out


def test_a_list_that_already_fits_keeps_the_design_size():
    assert O.fit_rows(groups([2, 2]), avail=400.0) == (5.4, 1.2)


def test_a_tight_list_shrinks_rather_than_sheds():
    row_h, gap = O.fit_rows(groups([6, 6, 6]), avail=90.0)
    assert row_h < 5.4 and row_h >= O.MIN_ROW_H
    assert 21 * row_h + 3 * gap <= 90.0 + 1e-9


def test_shrinking_stops_at_the_legibility_floor():
    """Below MIN_ROW_H the rows stop being readable, so the answer is None and
    the caller sheds — an unreadable complete list is not a complete list."""
    assert O.fit_rows(groups([20, 20, 20]), avail=60.0) is None


def test_shedding_drops_the_fattest_group_first():
    g = groups([2, 9, 3])
    out, row_h, _ = O.shed_to_fit(g, avail=52.0)
    assert out[1][2] == [], "the 9-leaf group should go first"
    assert out[0][2] and out[2][2], "and only as far as needed"


def test_shedding_never_drops_a_numbered_head():
    """A chapter listed nowhere is the defect this module exists to prevent."""
    out, _, _ = O.shed_to_fit(groups([12, 12, 12, 12]), avail=26.0)
    assert [nm for nm, _, _ in out] == ["H0", "H1", "H2", "H3"]
    assert all(lv == [] for _, _, lv in out), "leaves shed, heads kept"


def test_heads_alone_that_still_overflow_are_drawn_tight_not_dropped():
    out, row_h, gap = O.shed_to_fit(groups([3] * 12), avail=10.0)
    assert len(out) == 12 and row_h == O.MIN_ROW_H and gap == 0.0


def test_an_empty_outline_fits_trivially():
    assert O.fit_rows([], avail=100.0) == (5.4, 1.2)


# ── drawing ──────────────────────────────────────────────────────────────────

def doc():
    d = ReportDocument(font_dir=FONTS)
    d.add_page()
    return d


def test_the_list_reports_where_it_ended():
    """The caller fills the void underneath, so the end y is the whole output."""
    d = doc()
    end = O.contents_list(d, groups([2]), x=16, y=50, w=80, row_h=5.0, gap=1.0)
    assert end == pytest.approx(50 + 1.0 + 5.0 * 3)   # gap + head + 2 leaves


def test_every_row_shares_one_left_edge():
    """The number column is reserved whether or not it is filled. Without that,
    an unnumbered row hangs `num_w` to the left of every numbered one."""
    d = doc()
    xs = []
    _orig = d.set_xy
    d.set_xy = lambda x, y: (xs.append(x), _orig(x, y))[1]
    O.contents_list(d, [(None, None, [("numbered", "01"), ("bare", None)])],
                    x=16, y=50, w=80, row_h=5.0, gap=1.0)
    titles = [x for x in xs if x != 16]      # 16 is the number column itself
    assert len(set(titles)) == 1, f"title columns diverge: {sorted(set(titles))}"


def test_sub_sections_are_not_numbered():
    """Numbering leaves is what invented the second, conflicting sequence."""
    d = doc()
    printed = []
    d.cell = lambda w, h, txt="", *a, **k: printed.append(txt)
    O.contents_list(d, [("Monte Carlo", "04", ["Payoff", "Price Paths"])],
                    x=16, y=50, w=80, row_h=5.0, gap=1.0)
    assert "04" in printed
    assert not any(p and p.strip().isdigit() and p != "04" for p in printed)


def test_a_head_with_no_leaves_still_draws_itself():
    d = doc()
    end = O.contents_list(d, [("Shed Lens", "05", [])],
                          x=16, y=50, w=80, row_h=5.0, gap=1.0)
    assert end == pytest.approx(56.0), "head drawn even after its leaves shed"


# ── lazy heads ───────────────────────────────────────────────────────────────

class Rec(ReportDocument):
    def __init__(self):
        super().__init__(font_dir=FONTS)
        self.drawn = []

    def section_divider(self, number, kicker, heading):
        self.drawn.append(("divider", heading))

    def open_section(self, title, min_room=SECTION_ROOM, level=1):
        # NOT `start_section`: that name went back to fpdf2, which uses it to
        # build the outline. A fake that shadows the old name silently records
        # nothing, and this file is where that shows up.
        self.drawn.append(("section", title))


def test_a_head_nobody_calls_is_never_drawn():
    """The whole point: a lens with every item toggled off leaves no opener."""
    d = Rec()
    O.lazy_divider(d, "04", "MONTE CARLO", "Projected Outcomes")
    O.lazy_section(d, "Payoff")
    assert d.drawn == []


def test_a_head_called_repeatedly_is_drawn_once():
    d = Rec()
    ensure = O.lazy_section(d, "Payoff")
    ensure(); ensure(); ensure()
    assert d.drawn == [("section", "Payoff")]


def test_the_first_sub_section_pulls_in_its_divider_in_order():
    d = Rec()
    div = O.lazy_divider(d, "04", "MONTE CARLO", "Projected Outcomes")
    first = O.lazy_section(d, "Payoff", before=div)
    second = O.lazy_section(d, "Price Paths", before=div)
    second(); first()
    assert d.drawn == [("divider", "Projected Outcomes"),
                       ("section", "Price Paths"),
                       ("section", "Payoff")], "divider once, before either"
