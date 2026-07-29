"""
reportkit.outline — chapter numbers, the contents list, and headings that only
appear if something follows them.

Three problems that look unrelated and are the same problem: a report's
structure is decided in one place and *printed* in several, and every copy that
counts for itself eventually disagrees with the others.

**Numbering.** `plan_chapters` turns "which chapters are present" into
"01, 02, 03…". It is meant to be the ONLY place a chapter number is decided.
The failure it replaces: a body that numbered from hard-coded literals (so it
skipped a number whenever a chapter was switched off) and a contents page that
numbered every leaf independently — two sequences, agreeing on nothing past the
first entry, with the same numeral meaning different things on facing pages.

**The contents list.** A designed page has auto page break OFF, so a list too
long for its column does not wrap — it draws off the bottom edge and is simply
gone. `fit_rows` shrinks the rows to fit; `shed_to_fit` drops optional
sub-sections, biggest group first, only once shrinking has bottomed out. A
squeezed list beats an incomplete one, and an incomplete one beats a list that
runs off the page. Numbered chapters are never shed: they are what the body's
headings refer to.

**Headings with nothing under them.** When content is toggleable, a heading
emitted eagerly can end up alone on a decorated empty page. `lazy_section` and
`lazy_divider` return an idempotent `ensure()` that draws on first call, so a
heading exists exactly when something followed it.

Nothing here knows what a chapter IS — the caller names them and supplies the
order.
"""
from __future__ import annotations

from reportkit.document import SECTION_ROOM
from reportkit.text import _safe
from reportkit.theme import RULE_SOFT as _RULE_SOFT


#: Below this the 8pt rows stop being legible; shed instead of shrinking past it.
MIN_ROW_H = 3.9
#: Width reserved for the number column, filled or not.
NUM_W = 7.0


def plan_chapters(present: dict, order) -> dict:
    """`{key: bool}` + an order → `{key: "01"}`, numbered in that order.

    Absent/false chapters get no entry, so a caller that renders a chapter it
    did not declare present prints an empty number rather than a wrong one.
    """
    out, n = {}, 0
    for key in order:
        if present.get(key):
            n += 1
            out[key] = f"{n:02d}"
    return out


def fit_rows(groups, avail: float, *, row_h: float = 5.4, gap: float = 1.2,
             min_row_h: float = MIN_ROW_H):
    """Row height / gap that fit `groups` in `avail` mm, or None if they can't.

    Shrink first, shed only when even the minimum row height overflows — a
    squeezed list is better than an incomplete one.

    `groups` is `[(name | None, number | None, leaves)]`: a named group is a
    head plus its leaves, an unnamed one is bare rows.
    """
    heads = sum(1 for nm, _, _ in groups if nm is not None)
    rows = sum(len(lv) for _, _, lv in groups) + heads
    if rows <= 0 or rows * row_h + heads * gap <= avail:
        return row_h, gap
    scale = min(1.0, max(0.0, avail - heads * gap) / (rows * row_h))
    row_h, gap = row_h * scale, gap * scale
    if row_h >= min_row_h:
        return row_h, gap
    row_h = min_row_h
    return (row_h, gap) if rows * row_h + heads * gap <= avail else None


def shed_to_fit(groups, avail: float, *, row_h: float = 5.4, gap: float = 1.2,
                min_row_h: float = MIN_ROW_H):
    """Shrink, then drop optional sub-sections until the list fits.

    Returns `(groups, row_h, gap)`; `groups` is mutated in place, its shed
    entries left as heads with no leaves.

    Only the LEAVES of named groups are shed, biggest group first. The heads
    themselves always survive — they carry the chapter numbers the body's
    headings refer to, and a chapter listed nowhere is the defect this module
    exists to prevent. If heads alone still overflow, the list is drawn at the
    minimum height and allowed to be tight: at that point every remaining row
    is load-bearing.
    """
    fitted = fit_rows(groups, avail, row_h=row_h, gap=gap, min_row_h=min_row_h)
    while fitted is None:
        fat = max((i for i, (nm, _, lv) in enumerate(groups) if nm is not None and lv),
                  key=lambda i: len(groups[i][2]), default=None)
        if fat is None:
            fitted = (min_row_h, 0.0)
            break
        groups[fat] = (groups[fat][0], groups[fat][1], [])
        fitted = fit_rows(groups, avail, row_h=row_h, gap=gap, min_row_h=min_row_h)
    return groups, fitted[0], fitted[1]


def contents_list(pdf, groups, *, x: float, y: float, w: float,
                  row_h: float, gap: float, num_w: float = NUM_W) -> float:
    """Draw the contents list; return the y it ended at.

    A named group draws a head carrying the chapter number, with its
    sub-sections hanging under it — deliberately UNNUMBERED, because nothing
    numbers them on the page either. Numbering them here is exactly what
    invented the second, conflicting sequence.
    """
    yc = y

    def leaf(text, number=None, indent=0.0):
        nonlocal yc
        # The number column is RESERVED whether or not it is filled, so an
        # unnumbered row still lines its title up with every numbered one
        # instead of hanging `num_w` to the left.
        if number:
            pdf.set_xy(x + indent, yc)
            pdf._sf(7.5, "bold"); pdf.set_text_color(*pdf.lime)
            pdf.cell(num_w, row_h, number)
        indent += num_w
        pdf.set_xy(x + indent, yc)
        pdf._sf(8.0, "regular"); pdf.set_text_color(*pdf.body_ink)
        # `link=` makes the row clickable. The library drew a designed table of
        # contents that a reader could not use — the more discoverable half of
        # navigation, missing while the bookmark tree got all the attention.
        pdf.cell(w - indent, row_h, _safe(text),
                 link=pdf.link_for(text) if hasattr(pdf, "link_for") else None)
        pdf.set_draw_color(*_RULE_SOFT); pdf.set_line_width(0.2)
        pdf.line(x, yc + row_h, x + w, yc + row_h)
        yc += row_h

    def head(name, number=None):
        nonlocal yc
        yc += gap
        ind = 0.0
        if number:
            pdf.set_xy(x, yc)
            pdf._sf(7.5, "bold"); pdf.set_text_color(*pdf.lime)
            pdf.cell(num_w, row_h, number)
            ind = num_w
        pdf._eyebrow(x + ind, yc + 0.4, name, pdf.primary_color,
                     size=7.0, tracking=0.5, w=w - ind)
        # A head is drawn through the theme's eyebrow hook, which takes no
        # `link=`. Lay a link REGION over the row instead — the chapter rows are
        # the ones a reader most wants to click, so leaving only the leaves
        # clickable would be the wrong half.
        if hasattr(pdf, "link_for"):
            pdf.link(x, yc, w, row_h, pdf.link_for(name))
        yc += row_h

    for name, number, leaves in groups:
        if name is not None:
            head(name, number)
            for lf in leaves:
                leaf(lf)
        else:
            for lf, lf_no in leaves:
                leaf(lf, lf_no)
    return yc


def lazy_divider(pdf, number: str, kicker: str, heading: str):
    """A chapter divider drawn at most once, on first `ensure()`.

    A lens whose every item is switched off must leave no divider behind — an
    opener for a chapter that isn't there.
    """
    state = {"done": False}

    def ensure():
        if not state["done"]:
            pdf.section_divider(number, kicker, heading)
            state["done"] = True
    return ensure


def lazy_section(pdf, title: str, min_room: float = SECTION_ROOM, before=None):
    """A section heading drawn at most once, on first `ensure()`.

    `before` is another lazy head fired first (they are idempotent), so
    whichever sub-section renders first also draws its chapter's divider — in
    document order, without the caller tracking which came first.
    """
    state = {"done": False}

    def ensure():
        if before is not None:
            before()
        if not state["done"]:
            pdf.open_section(title, min_room=min_room)
            state["done"] = True
    return ensure
