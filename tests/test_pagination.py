"""Keep-together pagination: a heading must never be stranded from its block.

This is the package's most load-bearing logic and, until now, its only guard
lived in the application reportkit was extracted from. That is the wrong way
round: `table_room` is library code, so a consumer who changes it here finds
out downstream or not at all.

The rule is not one check but a chain — `subsection()` claims the page,
`head_claimed()` consumes the claim, `data_table()` skips its own break rule,
and `table_room()` reserves using the SAME constants `data_table` breaks on.

Two distinct failures, and they need different tests:

* **Orphan.** The reservation lets the heading draw so low that `data_table`
  breaks anyway (it still bails when `y > h - 55`), stranding the heading on a
  page its table has left. Caught by sweeping rows x starting room.
* **Split.** The reservation is too small for a table meant to be kept whole.
  Because the claim suppresses `data_table`'s break rule, the table does not
  bounce — it just starts too low and splits across the page boundary. No
  orphan, no error, and the reservation quietly did nothing.

These tests were verified by mutation, which is the only way to know a
regression test is worth its runtime — the first draft of this file passed
against a deliberately broken `table_room` and was guarding nothing:

    SPLIT_ROOM 40 -> 20          13 failures   (orphan)
    table_room capped at 130mm   13 failures   (split)
    drop the +12mm slack           1 failure
    ignore the claim in data_table 1 failure

Note the reservation is the CALL SITE's job: `subsection(min_room=table_room(n))`
is the documented usage, and a caller that forgets it gets `subsection`'s 27mm
default — enough for a heading and nothing else. That is not a bug in the chain,
it is the chain not being used, and these tests exercise it as documented.
"""
from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("fpdf")

import reportkit.branding as B                       # noqa: E402
from reportkit.document import (                     # noqa: E402
    HEAD_ROOM, PAGE_CAP, SPLIT_ROOM, TBL_HEAD_H, TBL_ROW_H, table_room,
    ReportDocument,
)

FONTS = Path(B.__file__).resolve().parent / "fonts"


class Recorder(ReportDocument):
    """Records the page every drawn cell of CONTENT landed on.

    Instrumenting `cell` rather than the block methods is deliberate: it
    observes where content ACTUALLY came out, after every break decision the
    chain made, instead of trusting the call site's own view of the page.

    Header and footer draws are excluded. A footer is emitted when the page
    CLOSES, so it is the last cell on every page — leave it in and "what came
    last on this page" answers "the footer", every time, and the orphan check
    can never fail.
    """

    def __init__(self, **kw):
        super().__init__(font_dir=FONTS, **kw)
        self.seen = []                       # [(page_no, text)]
        self._chrome = False

    def header(self):
        self._chrome = True
        try:
            return super().header()
        finally:
            self._chrome = False

    def footer(self):
        self._chrome = True
        try:
            return super().footer()
        finally:
            self._chrome = False

    def cell(self, *args, **kwargs):
        txt = args[2] if len(args) >= 3 else (kwargs.get("text") or kwargs.get("txt"))
        if not self._chrome and isinstance(txt, str) and txt.strip():
            self.seen.append((self.page_no(), txt.strip()))
        return super().cell(*args, **kwargs)

    def page_of(self, needle: str):
        # Case-insensitive: themes set headings in caps, and asserting against
        # the cased string silently matches nothing and passes a None through.
        low = needle.lower()
        for page, txt in self.seen:
            if low in txt.lower():
                return page
        return None

    def by_page(self) -> dict:
        out = {}
        for page, txt in self.seen:
            out.setdefault(page, []).append(txt)
        return out


def rows(n: int):
    return [[f"Row {i:02d}", f"{i}", f"{i * 2}"] for i in range(1, n + 1)]


def fill_to(pdf: ReportDocument, remaining: float):
    """Leave roughly `remaining` mm of room on the current page."""
    pdf.set_y(max(pdf.t_margin, pdf.h - pdf.b_margin - remaining))


# ── the sweep ────────────────────────────────────────────────────────────────

#: Room left on the page when the heading is drawn. This axis is NOT optional
#: and the reason is worth spelling out: an orphan needs the remaining room to
#: fall BETWEEN what the heading reserved and what the table actually needs. Fix
#: the room at some comfortable value and every row count passes — the heading
#: either breaks cleanly to a fresh page or fits with its table — and the sweep
#: proves nothing. A capped 130mm reservation was verified to survive a
#: rows-only sweep and to be caught within one row of entering this one.
ROOMS = [float(r) for r in range(30, 245, 10)]


def orphans(n: int, rooms=ROOMS):
    """Row counts x starting rooms where the heading loses its table."""
    bad = []
    for room in rooms:
        pdf = Recorder()
        pdf.add_page()
        fill_to(pdf, room)
        pdf.subsection("Positions", min_room=table_room(n))
        pdf.data_table(["Name", "A", "B"], rows(n))
        head, first = pdf.page_of("Positions"), pdf.page_of("Row 01")
        if head is None or first is None or head != first:
            bad.append((room, head, first))
    return bad


@pytest.mark.parametrize("n", list(range(1, 41)))
def test_a_heading_is_never_left_without_its_table(n):
    """Across every table size AND every height the heading can start at, the
    heading and the table's first row come out on one page.

    The band that used to fail is 16-29 rows, which no hand-picked row count
    covers by luck — and only at the starting heights ROOMS sweeps.
    """
    bad = orphans(n)
    assert not bad, (
        f"{n} rows orphaned at "
        + ", ".join(f"{r:.0f}mm (head p{h}, table p{f})" for r, h, f in bad))


def test_a_heading_is_not_the_last_thing_on_its_page():
    """The visible symptom: a heading alone on an otherwise empty page."""
    pdf = Recorder()
    pdf.add_page()
    for i in range(4):
        fill_to(pdf, 55.0)
        pdf.subsection(f"Block {i}", min_room=table_room(18 + i))
        pdf.data_table(["Name", "A", "B"], rows(18 + i))
        pdf.add_page()
    stranded = [p for p, content in pdf.by_page().items()
                if len(content) == 1 and content[0].lower().startswith("block ")]
    assert not stranded, f"heading alone on page(s) {stranded}"


def splits(n: int, rooms=ROOMS):
    """Starting rooms at which a KEPT-WHOLE table gets split anyway."""
    bad = []
    for room in rooms:
        pdf = Recorder()
        pdf.add_page()
        fill_to(pdf, room)
        pdf.subsection("Positions", min_room=table_room(n))
        pdf.data_table(["Name", "A", "B"], rows(n))
        first, last = pdf.page_of("Row 01"), pdf.page_of(f"Row {n:02d}")
        if first != last:
            bad.append((room, first, last))
    return bad


@pytest.mark.parametrize("n", [n for n in range(1, 30) if table_room(n) != SPLIT_ROOM])
def test_a_table_short_enough_to_keep_whole_is_never_split(n):
    """The other half of the contract, and the half a rows x rooms orphan sweep
    cannot see.

    Since `head_claimed()` suppresses `data_table`'s own break rule, a
    reservation that is too SMALL no longer strands the heading — the table just
    starts too low and splits. Quieter than an orphan and still wrong: the whole
    point of reserving the full height is that a short table stays in one piece.
    A capped reservation (the historical bug) is invisible to the sweep above and
    lights this one up.
    """
    bad = splits(n)
    assert not bad, (
        f"{n} rows split at " + ", ".join(f"{r:.0f}mm (p{a}-p{b})" for r, a, b in bad))


def test_the_split_allowance_leaves_the_cursor_where_data_table_will_accept_it():
    """`SPLIT_ROOM` is derived, not chosen, and this is the derivation as code.

    `data_table` gives up and breaks when `y > h - 55`. A heading drawing at the
    worst position its reservation allows, `h - b_margin - SPLIT_ROOM`, consumes
    `HEAD_ROOM` and must still leave the cursor at or above that line:

        h - 28 - SPLIT_ROOM + HEAD_ROOM  <=  h - 55   =>   SPLIT_ROOM >= 37
    """
    assert SPLIT_ROOM >= 37.0, (
        f"SPLIT_ROOM={SPLIT_ROOM} lets a heading draw low enough that "
        "data_table breaks out from under it")


# ── the reservation itself ───────────────────────────────────────────────────

def test_a_table_that_fits_a_page_is_reserved_whole():
    """A short table is kept whole, so the heading must reserve ALL of it — not
    a capped estimate, which is what let the table bounce out from under it."""
    n = 10
    full = TBL_HEAD_H + n * TBL_ROW_H + 6.0
    assert table_room(n) >= full


def test_a_table_too_long_to_keep_whole_only_reserves_a_foothold():
    """It is going to split anyway; demanding its full height would break the
    heading to a fresh page for no gain and leave a void behind it."""
    assert table_room(200) == SPLIT_ROOM


def test_the_switch_between_the_two_is_where_a_table_stops_fitting():
    """The threshold is `PAGE_CAP - HEAD_ROOM`, not `PAGE_CAP`: a table under
    a heading starts ~10mm lower than one on a bare page, so a table that fits
    246mm but not 236mm cannot be kept whole here at all. Promising to reserve
    it anyway just moves the collision one page along."""
    small = [n for n in range(1, 60) if table_room(n) != SPLIT_ROOM]
    large = [n for n in range(1, 60) if table_room(n) == SPLIT_ROOM]
    assert small and large, "both regimes must be reachable"
    assert max(small) + 1 == min(large), "one clean switch, not a ragged edge"
    kept = max(small)
    assert TBL_HEAD_H + kept * TBL_ROW_H + 6.0 <= PAGE_CAP


def test_the_reservation_grows_with_the_table():
    kept = [n for n in range(1, 60) if table_room(n) != SPLIT_ROOM]
    got = [table_room(n) for n in kept]
    assert got == sorted(got), "a longer kept-whole table must reserve more"


# ── the logo-row variant ─────────────────────────────────────────────────────

def test_logo_row_table_consumes_the_claim_it_was_given():
    """It is introduced by a heading that reserved for it with `table_room`, so
    it must consume that reservation like `data_table` does.

    It used not to. The claim then stayed set, and the next `data_table` on the
    page skipped its own keep-together rule — spending a reservation made for a
    different block, with no heading above it.
    """
    pdf = Recorder()
    pdf.add_page()
    pdf.subsection("Holdings", min_room=table_room(3, row_h=10.0))
    pdf.logo_row_table(["Name", "Weight"], [["A", "1%"], ["B", "2%"]], {})
    assert pdf.head_claimed() is False, "claim leaked to the next block"


@pytest.mark.parametrize("n", [2, 8, 16, 23, 24, 30])
def test_a_heading_keeps_its_logo_row_table(n):
    """Includes 23 rows, where the reservation and `logo_row_table`'s own rule
    provably disagree — the size the host's ticker table reaches once a note has
    enough underlyings, and the one a smoke test would miss."""
    bad = []
    for room in ROOMS:
        pdf = Recorder()
        pdf.add_page()
        fill_to(pdf, room)
        pdf.subsection("Holdings", min_room=table_room(n, row_h=10.0))
        pdf.logo_row_table(["Name", "Weight"],
                           [[f"Row {i:02d}", f"{i}%"] for i in range(1, n + 1)], {})
        head, first = pdf.page_of("Holdings"), pdf.page_of("Row 01")
        if head is None or first is None or head != first:
            bad.append((room, head, first))
    assert not bad, f"{n} rows orphaned at {bad}"


# ── the claim protocol ───────────────────────────────────────────────────────

def test_the_claim_is_consumed_once():
    """`_head_claimed` applies to the FIRST block only. If it stuck, every later
    block on the page would skip its own break rule and run off the bottom."""
    pdf = ReportDocument(font_dir=FONTS)
    pdf.add_page()
    pdf.subsection("Head")
    assert pdf.head_claimed() is True
    assert pdf.head_claimed() is False


def test_a_claim_does_not_survive_a_page_break():
    pdf = ReportDocument(font_dir=FONTS)
    pdf.add_page()
    pdf.subsection("Head")
    pdf.add_page()
    assert pdf.head_claimed() is False, "a claim is for the page it was made on"
