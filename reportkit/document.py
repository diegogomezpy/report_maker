"""
reportkit.document — the themed document and its building blocks.

`ReportDocument` is an FPDF subclass that knows about *report shapes* — covers,
section heads, tables, metric bands, figures with captions, callouts — and
nothing about any particular subject matter. Every chrome surface delegates to
the active theme, so swapping the look never touches a call site.

The pagination rules are the part worth reusing. A heading must never be
separated from the block it introduces, and that is not one check but a chain:

    subsection() claims the page  ->  head_claimed() consumes the claim
                                  ->  data_table() skips its own break rule
                                  ->  table_room() reserves using the SAME
                                      constants data_table breaks on

Those constants live in this module for that reason. Splitting them from the
blocks that read them is exactly how the orphaned-heading bug happened: two
independent estimates of one quantity, agreeing for most table sizes and
disagreeing between roughly 16 and 29 rows.

Geometry note: several bottom-margin literals (h-28, h-30, h-32, h-55) look like
they should derive from `b_margin`. They do not agree with it, and they are what
the rendered output currently is — deriving them is a pixel change, not a
cleanup.
"""
from __future__ import annotations

import logging

import io

from fpdf import FPDF

import reportkit.cover as _rk_cover
import reportkit.fonts as _rk_fonts
from reportkit.images import (logo_aspect as _logo_aspect)
from reportkit.text import _safe
from reportkit.color import (DEFAULT_ACCENT as _DEFAULT_ACCENT,
                             DEFAULT_PRIMARY as _DEFAULT_PRIMARY)
from reportkit.theme import (
    ROW_ALT as _ROW_ALT, TEXT as _TEXT,
    WHITE as _WHITE,
    build_tokens, resolve_theme, resolve_watermark, blend as _blend,
    ReportTheme,
)


_log = logging.getLogger(__name__)


#: The only copy reportkit's own chrome emits. A host overrides any of these by
#: injecting `labels=`; anything it doesn't cover falls back here, so a document
#: is never rendered with a raw key showing.
CHROME_LABELS = {
    "figure_word":      {"en": "Figure",        "es": "Figura"},
    "page_of":          {"en": "Page",          "es": "Página"},
    "page_of_mid":      {"en": "of",            "es": "de"},
    "in_this_report":   {"en": "In this report", "es": "En este informe"},
    "glossary_title":   {"en": "Glossary",      "es": "Glosario"},
    "disclaimer_title": {"en": "Disclaimer",    "es": "Aviso legal"},
    "footer_line":      {"en": "", "es": ""},
    "yes":              {"en": "Yes",           "es": "Sí"},
    "no":               {"en": "No",            "es": "No"},
}


#: The table geometry the keep-together chain is expressed in. PUBLIC at 1.0:
#: a call site cannot honour `subsection(min_room=table_room(n))` without them,
#: so they are contract, not implementation. `data_table` draws with these too —
#: it used to draw with hard-coded 8 and 9, two copies of one quantity that
#: agreed by coincidence.
TBL_ROW_H  = 8.0
TBL_HEAD_H = 9.0
TBL_PAD    = 6.0
PAGE_CAP   = 246.0   # h(297) - footer(30) - running header(21): a fresh page's room
HEAD_ROOM  = 10.0    # vertical space a sub-heading itself consumes (ln+cell+ln)
#: The room `start_section` reserves by default: a title plus a full-width
#: figure. Defined here rather than repeated at each call site — `outline.py`
#: had its own copy of this number.
SECTION_ROOM = 146.0
# Minimum a heading must see before a table that is going to split anyway.
# Derived, not chosen: data_table gives up and breaks when y > h - 55, so the
# heading has to leave the cursor at or above that. It draws at
# `h - b_margin - SPLIT_ROOM` in the worst case and consumes HEAD_ROOM, giving
#   h - 28 - SPLIT_ROOM + HEAD_ROOM  <=  h - 55   ⇒  SPLIT_ROOM >= 37.
# 40 keeps a little slack so the two are not exactly equal.
SPLIT_ROOM = 40.0


def table_room(n_rows: int, row_h: float = TBL_ROW_H, head_h: float = TBL_HEAD_H) -> float:
    """Room a sub-heading must see before drawing, for a table of `n_rows`.

    Includes the heading's own height, so call sites pass this straight to
    `min_room=` — do NOT add a further allowance.

    This has to predict what `_NotePDF.data_table` will actually do:
      * a table that fits a fresh page is kept WHOLE, so the heading must
        reserve the table's full height or the table will bounce to the next
        page and leave the heading stranded on a decorated empty one;
      * a longer table is going to split anyway, so the heading only needs
        enough room for the header row and a few lines of it.

    The previous version capped at 130mm while data_table measured the full
    height uncapped, so every table of roughly 16-29 rows orphaned its heading.

    Note the threshold is `PAGE_CAP - HEAD_ROOM`, not `PAGE_CAP`: a table kept
    whole UNDER A HEADING starts ~10mm lower than one on a bare page, so a table
    that fits 246mm but not 236mm cannot be kept whole here at all. Promising to
    reserve it anyway just moved the collision one page along — the heading broke
    to a fresh page, drew, and the table broke out from under it again.
    """
    full = head_h + n_rows * row_h + TBL_PAD
    return (full + 12.0) if full <= PAGE_CAP - HEAD_ROOM else SPLIT_ROOM


# Deprecated aliases, kept for one release so a consumer pinned to 0.6 keeps
# working. Removed at 1.0 — see CHANGELOG "Upgrading to 1.0".
def chrome_labels() -> dict:
    """A COPY of reportkit's own chrome copy, for a host building a label table.

    `CHROME_LABELS` is a module global; handing it out is handing out the
    package's fallbacks by reference.
    """
    import copy as _copy
    return _copy.deepcopy(CHROME_LABELS)


_TBL_ROW_H, _TBL_HEAD_H, _TBL_PAD = TBL_ROW_H, TBL_HEAD_H, TBL_PAD
_PAGE_CAP, _HEAD_ROOM, _SPLIT_ROOM = PAGE_CAP, HEAD_ROOM, SPLIT_ROOM
_table_room = table_room


class ReportDocument(FPDF):
    """A4 portrait document: themed chrome, IBM Plex Sans, and pagination that
    keeps a heading with the block it introduces."""

    def __init__(self, lang: str = "en", doc_ref: str = "",
                 primary_color: tuple = _DEFAULT_PRIMARY,
                 accent_color: tuple = _DEFAULT_ACCENT,
                 firm_name: str = "Structured Note Analytics",
                 firm_logo_bytes: bytes | None = None,
                 report_title: str | None = None,
                 website: str = "", contact: str = "",
                 footer_note: str | None = None,
                 section_rule_color: tuple = _DEFAULT_ACCENT,
                 panel_color: tuple | None = None,
                 sidebar_bar_color: tuple | None = None,
                 theme: "ReportTheme | None" = None,
                 font_dir=None, labels=None, brand=None,
                 outline: bool = True):
        # A Brand, if given, supplies the palette BEFORE tokens are derived.
        # It cannot arrive afterwards: `build_tokens` runs once in this
        # constructor, and a second derivation site is the duplicated-state bug
        # class this package was extracted to remove.
        if brand is not None:
            primary_color      = brand.primary
            accent_color       = brand.accent
            section_rule_color = brand.section_rule
            panel_color        = brand.panel if brand.panel else panel_color
            sidebar_bar_color  = brand.sidebar_bar if brand.sidebar_bar else sidebar_bar_color
            firm_name          = brand.firm_name or firm_name
            if theme is None and brand.theme_name is not None:
                theme = resolve_theme(brand.theme_name)
        super().__init__(orientation="P", unit="mm", format="A4")
        self._labels = labels
        # Declared, not left to getattr: the theme layer reads these by name, so
        # a document that never sees a Brand must still have them. Absent
        # declarations are how half the theme became unreachable for anyone but
        # the original host.
        self.cover_logo_bytes = None
        self.cover_logo_aspect = 1.0
        self.cover_sigil_bytes = None
        self.cover_image_bytes = None
        self.back_image_bytes = None
        self.filler_image_list = []
        self.watermark = {}
        self.cover_overlay_color = None
        self.cover_overlay_opacity = 0.55
        self.disclaimer_body = ""
        for _k in ("cover_logo_x_pct", "cover_logo_y_pct", "cover_logo_size_pct",
                   "cover_sigil_x_pct", "cover_sigil_y_pct",
                   "cover_sigil_size_pct", "cover_sigil_opacity"):
            setattr(self, _k, None)
        # Pluggable visual identity — the theme draws every "look" surface
        # (header/footer, section heads, dividers, cover masthead, void decor)
        # through this instance. Defaults to the CADIEM hexagon language so an
        # un-themed document renders exactly as before.
        self.theme         = theme if theme is not None else resolve_theme(None)
        self.lang          = lang
        self.doc_ref       = doc_ref
        self.primary_color = primary_color
        self.accent_color  = accent_color
        self.section_rule_color = section_rule_color
        # ── Palette-derived design tokens ──────────────────────────────────
        # build_tokens() (pdf_theme.py) is the single source for the identity
        # colour derivation, shared by every theme: `ink` = a darkened primary
        # (mastheads / banners / stat values); `lime` = the section-rule colour
        # (keylines, number chips, accents); `teal` = the accent (secondary
        # series, kickers); downside stays amber (the brand has no red). `panel`
        # = the card/tile fill (an explicit brand `panel_color` wins, else a very
        # light PRIMARY tint so a bold accent never yields a pink card — CADIEM
        # pins its mint that a 7% teal tint would wash out); `sidebar_bar` = the
        # solid bar atop the cover sidebar (defaults to PRIMARY, matching the
        # table headers). The tokens are also kept on `self.tokens` for the theme.
        tok = build_tokens(primary_color, accent_color, section_rule_color,
                           panel=panel_color, sidebar_bar=sidebar_bar_color)
        self.tokens        = tok
        self.sidebar_bar_color = tok.sidebar_bar
        self.panel_color   = tok.panel
        self.ink           = tok.ink
        self.lime          = tok.lime
        self.teal          = tok.teal
        self.amber         = tok.amber
        self.amber_dark    = tok.amber_dark
        self.muted         = tok.muted
        self.body_ink      = tok.body_ink
        self.rule_soft     = tok.rule_soft
        self.footnote_grey = tok.footnote_grey
        self.firm_name     = firm_name
        self.firm_logo_bytes = firm_logo_bytes
        # Optional branding content (B5). report_title overrides the default
        # "Structured Note Analytics" eyebrow/subtitle; footer_note overrides the
        # default footer disclaimer line; website/contact print on the cover.
        self.report_title  = report_title
        self.website       = website or ""
        self.contact       = contact or ""
        self.footer_note   = footer_note
        # Aspect ratio so a wide wordmark isn't squashed into a square box.
        self.firm_logo_aspect = _logo_aspect(firm_logo_bytes, default=1.0)
        # PDF outline (bookmarks). `_outline_open` is the stack of semantic
        # levels still open, which is what turns "this is a subsection" into
        # "emit at depth N" without assuming every level in between was used.
        self.outline_enabled = bool(outline)
        self._outline_open: list = []
        # Internal links, so a designed contents page is clickable. Created by
        # `link_for` when the row is drawn, bound by `_mark_outline` when the
        # heading is.
        self._links: dict = {}
        self._links_bound: set = set()
        if self.outline_enabled:
            self.page_mode = "USE_OUTLINES"
        self._is_cover     = False
        self._cover_pages  = set()   # page numbers with no running header/footer (covers)
        # `{chapter_key: "01"}` from `_plan_chapters` — the numbers the contents
        # page prints. Empty until `_build_pdf_report` sets it, so a head drawn
        # without one prints no number rather than a number that means nothing.
        self.chapter_nums  = {}
        self._fig_no       = 0
        # Round-robin cursor into `filler_image_list` so successive egregious-void
        # photo bands cycle through the chosen images instead of repeating one.
        self._void_photo_idx = 0
        self.set_margins(16, 16, 16)
        self.set_auto_page_break(auto=True, margin=28)
        self.alias_nb_pages()
        # IBM Plex Sans (Unicode); last resort the built-in Helvetica (Latin-1).
        # The FONT FILES are this repo's (fonts/), not reportkit's bundled copy —
        # identical bytes either way, but keeping the host's directory as the
        # source means the extraction cannot change which glyphs get embedded.
        if _rk_fonts.register_default_family(self, font_dir=font_dir):
            self._font_family = _rk_fonts.FAMILY
            self._use_unicode = True
            self._sf_map = dict(_rk_fonts.DEFAULT_STYLE_MAP)
            _log.debug("Using IBM Plex Sans")
        else:
            # Every page renders in Helvetica from here — Latin-1 only, so
            # `_safe(latin1=True)` becomes load-bearing. This is a whole-document
            # event, not a detail.
            self._font_family = "Helvetica"
            self._use_unicode = False
            self._sf_map = dict(_rk_fonts.HELVETICA_STYLE_MAP)
            _log.error("Using Helvetica fallback")

    # ------------------------------------------------------------------
    # Font helpers
    # ------------------------------------------------------------------
    def _sf(self, size: float, weight: str = "regular") -> None:
        """Set font by semantic weight via the active font map — IBM Plex Sans
        (or Helvetica) by default, overridden by custom brand fonts when a brand
        registers them (see _register_brand_fonts)."""
        family, style = self._sf_map.get(weight, self._sf_map["regular"])
        self.set_font(family, style, size)

    def _fit_font(self, text: str, max_w: float, size: float,
                  weight: str = "regular", min_size: float = 5.5) -> None:
        """Set the font to the largest size <= `size` at which `text` fits in
        `max_w` mm on one line, never going below `min_size`. Prevents the
        single-line name cells (calibration table, cover sidebar) from either
        overflowing into the neighbouring column or being clipped — long names
        shrink just enough to fit instead."""
        s = size
        self._sf(s, weight)
        safe = self._safe(text)
        while s > min_size and self.get_string_width(safe) > max_w:
            s -= 0.25
            self._sf(s, weight)

    def _safe(self, text: object) -> str:
        return _safe(text, latin1=not self._use_unicode)

    def apply_brand(self, brand, *, font_dir=None) -> None:
        """Apply everything in a `Brand` that is not the palette.

        Owns three orderings a host gets wrong on its own, each of which fails
        silently rather than loudly:

        * brand faces AFTER the default family — `register_brand_fonts` no-ops
          unless the Unicode family is already registered, so running it first
          leaves the document in the default type with no error;
        * the watermark config AFTER its image is decoded, since the resolver
          folds the image into the surfaces it gates;
        * the filler pool AFTER cover/back selection, or the cover photograph
          reappears as a body band halfway through the report.

        Writes exactly `reportkit.branding.APPLIED_ATTRS`.
        """

        self.firm_name = brand.firm_name or self.firm_name
        self.firm_logo_bytes = brand.logo
        self.firm_logo_aspect = _logo_aspect(brand.logo, default=1.0)
        self.cover_logo_bytes = brand.cover_logo
        self.cover_logo_aspect = _logo_aspect(brand.cover_logo,
                                              default=self.firm_logo_aspect)
        self.cover_sigil_bytes = brand.cover_sigil

        # Selection first, pool second — see the docstring.
        self.cover_image_bytes = brand.cover_image
        self.back_image_bytes = brand.back_image
        self.filler_image_list = list(brand.fillers)

        self.watermark = resolve_watermark(brand.raw, brand.watermark_image)
        self.cover_overlay_color = brand.overlay_color or self.primary_color
        self.cover_overlay_opacity = brand.overlay_opacity

        self.report_title = brand.report_title or self.report_title
        self.website = brand.website or self.website
        self.contact = brand.contact or self.contact
        self.footer_note = brand.footer_note or self.footer_note
        self.disclaimer_body = brand.disclaimer_body

        for key, value in brand.placement.items():
            setattr(self, key, value)

        # Brand faces LAST: they overwrite the weight map the default family set.
        if brand.title_font or brand.body_font:
            _rk_fonts.register_brand_fonts(self, brand.raw, brand_dir=font_dir)

    def t(self, key: str) -> str:
        """Resolve a chrome label in this document's language.

        The theme layer reaches copy through this, so it needs no dependency on
        any particular translation table. A host injects `labels=` — a
        `(key, lang) -> str` callable — and it wins; reportkit's own defaults
        cover only the handful of strings the chrome itself emits.
        """
        if self._labels is not None:
            got = self._labels(key, self.lang)
            if got is not None and got != key:
                return got
        return CHROME_LABELS.get(key, {}).get(self.lang) \
            or CHROME_LABELS.get(key, {}).get("en") or key

    # ------------------------------------------------------------------
    # Cell/multi_cell overrides for automatic text sanitisation
    # ------------------------------------------------------------------
    def cell(self, *args, **kwargs):
        if len(args) >= 3 and isinstance(args[2], str):
            args = (args[0], args[1], self._safe(args[2]), *args[3:])
        for k in ("text", "txt"):
            if k in kwargs and isinstance(kwargs[k], str):
                kwargs[k] = self._safe(kwargs[k])
        return super().cell(*args, **kwargs)

    def multi_cell(self, *args, **kwargs):
        if len(args) >= 3 and isinstance(args[2], str):
            args = (args[0], args[1], self._safe(args[2]), *args[3:])
        for k in ("text", "txt"):
            if k in kwargs and isinstance(kwargs[k], str):
                kwargs[k] = self._safe(kwargs[k])
        return super().multi_cell(*args, **kwargs)

    # ------------------------------------------------------------------
    # Page chrome — running header / footer
    # ------------------------------------------------------------------
    # ------------------------------------------------------------------
    # Page chrome & section heads — all delegated to the active theme
    # (pdf_theme.py). These wrappers keep the _NotePDF method surface (and every
    # call site) unchanged while the drawing lives in the swappable theme.
    # ------------------------------------------------------------------
    def header(self):
        return self.theme.header(self)

    def footer(self):
        return self.theme.footer(self)

    # ------------------------------------------------------------------
    # Building blocks
    # ------------------------------------------------------------------
    def open_section(self, text: str, min_room: float = SECTION_ROOM,
                     level: int = 1):
        """Begin a major section, breaking to a new page only when needed.

        ``min_room`` is the space the section title PLUS its first block need; we
        break to a fresh page when fewer than that many mm remain, so a title is
        never left stranded at the foot of a page with its chart/table overleaf.
        The default (`SECTION_ROOM`, 146) covers a title + a full-width chart
        (~120mm); sections
        whose first block is short (issuer panel, glossary, disclaimer) pass a
        smaller value so they don't leave a big void.
        """
        if self.page_no() == 0:
            self.add_page()
        elif self.get_y() > self.h - self.b_margin - min_room:
            self.add_page()
        else:
            self.ln(6)   # generous separation between stacked sections
        self.section_title(text, _outline_level=level)

    def start_section(self, text: str, min_room: float = SECTION_ROOM):
        """Deprecated alias for `open_section`. Removed at 1.0.

        The rename is the point, not cosmetics: this method SHADOWED
        `FPDF.start_section`, which is how fpdf2 builds the PDF outline (the
        bookmark tree a reader shows in its sidebar). While it shadowed, no
        reportkit document could have one, and `write_html()` — which calls the
        base method for `<h1>`..`<h6>` — silently got a pagination decision
        instead of a heading.
        """
        import warnings as _w
        _w.warn("ReportDocument.start_section is deprecated; use open_section. "
                "The name is being returned to fpdf2, whose start_section builds "
                "the document outline.", DeprecationWarning, stacklevel=2)
        return self.open_section(text, min_room=min_room)

    # ------------------------------------------------------------------
    # Document outline (PDF bookmarks)
    # ------------------------------------------------------------------
    def _mark_outline(self, title: str, sem_level: int, anchor=None,
                      link_key: str | None = None) -> None:
        """Register one outline entry for a heading that was just drawn.

        Three things here are load-bearing:

        * **Cursor rewind.** fpdf2 anchors the destination at the LIVE cursor
          (`DestinationXYZ(..., top=h_pt - y*k)`), and the theme hook has
          already moved it past the heading. Without rewinding, every bookmark
          lands 18-36mm BELOW the thing it names.
        * **An open-level stack, not a clamp.** `min(level, last+1)` nests a
          sibling under its predecessor whenever an intermediate level is
          absent. The stack answers "how many ancestors are still open?".
        * **No `section_title_styles`.** A non-empty style list makes
          `FPDF.start_section` re-render the name through `multi_cell` — every
          heading printed twice, possibly with a page break between.
        """
        if not self.outline_enabled or self.page_no() == 0:
            return
        title = (title or "").strip()
        if not title:
            return
        stack = [lv for lv in self._outline_open if lv < sem_level]
        emitted = len(stack)
        # `FPDF.start_section` raises on a level more than one deeper than the
        # last entry. That can happen if anything appended to `_outline` behind
        # our back — the base method is reachable, and fpdf2's own
        # `insert_toc_placeholder` uses it. Clamp rather than abort a render.
        if self._outline:
            emitted = min(emitted, self._outline[-1].level + 1)
        # `anchor` is (page_no, y) captured BEFORE the theme hook drew the
        # heading. Taking it here instead would anchor every bookmark below the
        # thing it names, because the hook has already advanced the cursor —
        # and if the hook broke to a new page, the pre-break y belongs to a page
        # that is no longer current, so fall back to the top margin.
        x_before, y_before = self.x, self.y
        page_at, y_at = anchor if anchor else (self.page_no(), self.y)
        try:
            self.y = y_at if page_at == self.page_no() else self.t_margin
            super().start_section(self._safe(title), level=emitted, strict=False)
            self._outline_open = stack + [sem_level]
            # Bind any contents row that named this heading. A numbered head
            # registers as "01 · Holdings" while the contents row says
            # "Holdings", so bind BOTH spellings — otherwise every chapter row
            # links to page 1, which is what fpdf does with an unbound link.
            for key in {title, (link_key or "").strip()} - {""}:
                if key in self._links:
                    self.set_link(self._links[key], y=self.y, page=self.page_no())
                    self._links_bound.add(key)
        except Exception as exc:                 # never lose a report to a bookmark
            _log.warning("outline entry %r skipped: %s", title, exc)
        finally:
            self.x, self.y = x_before, y_before

    def link_for(self, title: str) -> int:
        """A stable internal-link id for a heading title, created on demand.

        The contents list draws rows before the headings exist, so the id has to
        come first and be bound later — `_mark_outline` calls `set_link` when
        the heading is actually drawn. A title that never gets a heading leaves
        its link unbound, which fpdf resolves to page 1; `unbound_links()`
        reports those rather than leaving them to be discovered by clicking.
        """
        key = (title or "").strip()
        got = self._links.get(key)
        if got is None:
            got = self._links[key] = self.add_link()
        return got

    def unbound_links(self) -> list:
        """Contents rows whose heading was never drawn — a link to nowhere."""
        return sorted(k for k in self._links if k not in self._links_bound)

    def bookmark(self, title: str, level: int = 0) -> None:
        """Add an outline entry by hand, for a page no theme hook draws a head on.

        Covers and back pages are the reason this is public: they are laid out
        by the host, so nothing in the package sees a heading to hook.
        """
        self._mark_outline(title, level)

    def _eyebrow(self, x: float, y: float, text: str, color: tuple,
                 size: float = 7.0, tracking: float = 0.4,
                 w: float = 0.0, align: str = "L") -> None:
        return self.theme.eyebrow(self, x, y, text, color,
                                  size=size, tracking=tracking, w=w, align=align)

    def section_title(self, text: str, _outline_level: int = 1):
        at = (self.page_no(), self.y)
        out = self.theme.section_title(self, text)
        self._mark_outline(text, _outline_level, at)
        return out

    def secondary_head(self, number: str, kicker: str, title: str,
                       min_room: float = 40.0, badge: str | None = None,
                       badge_color: tuple | None = None,
                       badge_logo: bytes | None = None):
        at = (self.page_no(), self.y)
        out = self.theme.secondary_head(self, number, kicker, title,
                                        min_room=min_room, badge=badge,
                                        badge_color=badge_color, badge_logo=badge_logo)
        self._mark_outline(f"{number} · {title}" if number else title, 0, at,
                           link_key=title)
        return out

    def _decorate_void(self, variant: int = 0, min_gap: float = 44.0) -> None:
        return self.theme.decorate_void(self, variant=variant, min_gap=min_gap)

    def _decorate_void_photo(self, x0: float, x1: float, y: float,
                             floor: float, gap: float, filler: bytes) -> bool:
        return self.theme.decorate_void_photo(self, x0, x1, y, floor, gap, filler)

    # Decorate the page we're leaving (cursor is at the content end here) so any
    # short content page gets its void filled automatically — except covers.
    #
    # The test is `_cover_pages` alone. `_is_cover` describes the page ABOUT to
    # be drawn (every cover builder raises it before calling here), so asking it
    # about the page being left skipped the last content page ahead of any cover.
    def add_page(self, *args, **kwargs):
        if self.page_no() > 0 and self.page_no() not in self._cover_pages:
            self._decorate_void(variant=self.page_no() % 3)
        return super().add_page(*args, **kwargs)

    # ------------------------------------------------------------------
    # Full-bleed pages — covers and back pages
    # ------------------------------------------------------------------
    # Thin delegations to reportkit.cover, which owns the painting order. See
    # its module docstring: every step of that order fails silently when a
    # caller improvises, so the sequence is a context manager rather than a
    # recipe in a docstring.
    def full_bleed_page(self, image: bytes | None = None):
        """Context manager: a painted, chrome-free page. Yields `(w, h)`."""
        return _rk_cover.full_bleed(self, image)

    def draw_logo_fit(self, logo_b, x: float, y: float, max_h: float,
                      max_w: float, *, cover: bool = False) -> None:
        return _rk_cover.draw_logo_fit(self, logo_b, x, y, max_h, max_w,
                                       cover=cover)

    def cover_logo(self) -> None:
        """The brand's cover wordmark, in the brand's chosen place."""
        return _rk_cover.draw_cover_logo(self, self.w, self.h)

    def cover_sigil(self) -> None:
        """The brand's emblem, bleeding off an edge as a faint motif."""
        return _rk_cover.draw_sigil(self, self.w, self.h)

    def cover_left_photo(self, x0: float, top: float, w: float, bottom: float,
                         img: bytes) -> bool:
        """A banded brand photo down a tall column. False ⇒ fall back."""
        return _rk_cover.left_photo(self, x0, top, w, bottom, img)

    def section_divider(self, number: str, kicker: str, heading: str):
        at = (self.page_no(), self.y)
        out = self.theme.section_divider(self, number, kicker, heading)
        self._mark_outline(f"{number} · {heading}" if number else heading, 0, at,
                           link_key=heading)
        return out

    def subsection(self, text: str, min_room: float = 27.0):
        at = (self.page_no(), self.y)
        out = self.theme.subsection(self, text, min_room=min_room)
        self._mark_outline(text, 2, at)
        # Claim the page for whatever block comes next — see _head_claimed().
        self._head_page = self.page_no()
        return out

    def _head_claimed(self) -> bool:
        """True (once) if a heading was just drawn on THIS page.

        A block that is introduced by a heading must not run its own
        keep-together check: the heading already made that decision, using
        `_table_room` to reserve the room, and a second opinion taken 10mm
        further down the page can only ever disagree — which is precisely how a
        heading ends up alone on a page the block it introduces has left.
        Consumed on read, so it applies to the FIRST block only.
        """
        claimed = getattr(self, "_head_page", None) == self.page_no()
        self._head_page = None
        return claimed

    def body(self, text: str, h: float = 4.5):
        """8.5pt regular body text."""
        self._sf(8.5, "regular")
        self.set_text_color(*_TEXT)
        self.multi_cell(0, h, text)
        self.ln(1.5)

    def bullet(self, text: str):
        """8.5pt bullet point with proper indent."""
        self._sf(8.5, "regular")
        self.set_text_color(*_TEXT)
        x0 = self.get_x()
        self.cell(5, 5, "•" if self._use_unicode else chr(149))
        self.multi_cell(self.w - self.r_margin - x0 - 5, 5, text)
        self.ln(1.5)

    def kv_table(self, rows: list[tuple[str, str]], col_w: tuple[float, float] = (78, 100)):
        """Label/value table with thin rules and consistent alignment."""
        self.set_text_color(*_TEXT)
        for row_idx, (k, v) in enumerate(rows):
            y0 = self.get_y()
            if y0 > self.h - 32:
                self.add_page()
                y0 = self.get_y()
            # Light zebra on alternating rows — subtle background
            if row_idx % 2 == 0:
                self.set_fill_color(*_ROW_ALT)
                self.rect(self.l_margin, y0, col_w[0] + col_w[1], 8.5, style="F")
            self._sf(8.5, "regular")    # label — reference uses regular weight in table cells
            self.set_text_color(*_TEXT)
            self.cell(col_w[0], 8.5, k)
            self._sf(8.5, "regular")
            self.cell(col_w[1], 8.5, v, new_x="LMARGIN", new_y="NEXT")
        self.ln(3)

    def data_table(self, headers: list[str], rows: list[list[str]],
                   col_widths: list[float] | None = None,
                   aligns: list[str] | None = None,
                   rounded: bool = True):
        """Filled-header table with zebra rows and proper number alignment.

        rounded=True (default) draws a rounded-rect card behind the whole table
        so the outer corners round off; pass rounded=False for plain rects.
        """
        n = len(headers)
        usable = self.w - self.l_margin - self.r_margin
        if col_widths is None:
            col_widths = [usable / n] * n
        if aligns is None:
            aligns = ["L"] + ["R"] * (n - 1)
        tbl_w  = sum(col_widths)
        _CR    = 3.0   # corner radius (mm)
        # _use_round flips off when the table can't fully fit (multi-page) — a
        # rounded card across a page break looks broken, so fall back to rects.
        _use_round = [False]

        def _header_row(rounded_card: bool = False):
            # Header strip: rounded-top ink card (so the table's top corners round)
            # with transparent text cells, else a plain ink filled row. First column
            # header reads in lime, the rest white (per the prototype).
            if rounded_card:
                self.set_fill_color(*self.ink)
                try:
                    self.rect(self.l_margin, self.get_y(), tbl_w, TBL_HEAD_H, style="F",
                              round_corners=("TOP_LEFT", "TOP_RIGHT"), corner_radius=_CR)
                except TypeError:
                    self.rect(self.l_margin, self.get_y(), tbl_w, TBL_HEAD_H, style="F")
            else:
                self.set_fill_color(*self.ink)
            self._sf(7.5, "body_bold")
            for idx, (h, w, a) in enumerate(zip(headers, col_widths, aligns)):
                self.set_text_color(*(self.lime if idx == 0 else _WHITE))
                self.cell(w, TBL_HEAD_H, f" {h} ", border=0, fill=not rounded_card, align=a)
            self.ln()
            self.set_text_color(*_TEXT)
            self._sf(8, "regular")

        # Keep the whole table together when it can fit on one page: if the
        # header + all rows won't fit in the space left but WOULD fit on a fresh
        # page, break first instead of splitting a short table across pages.
        # `_table_room` above predicts this rule for the sub-heading that
        # introduces the table; the two MUST stay in step or the heading gets
        # orphaned on the page the table just left.
        _needed = TBL_HEAD_H + len(rows) * TBL_ROW_H + TBL_PAD
        _avail  = self.h - 30 - self.get_y()
        if self._head_claimed():
            # A heading directly above already reserved for us; only break if we
            # cannot even start here (which its reservation should have avoided).
            if self.get_y() > self.h - 55:
                self.add_page()
        elif _needed > _avail and _needed <= PAGE_CAP:
            self.add_page()
        elif self.get_y() > self.h - 55:
            self.add_page()

        # Rounded card: a white rounded rect behind the whole table rounds the
        # bottom corners; the header's rounded-top green strip rounds the top.
        # Header text and white rows draw transparent over it; only alt zebra
        # rows get an opaque fill (the last one rounded so it doesn't square the
        # bottom). Only when the whole table fits the page; older fpdf2 → rects.
        if rounded:
            _ch = 9 + len(rows) * 8
            _cy = self.get_y()
            if _cy + _ch <= self.h - 28:
                try:
                    self.set_fill_color(*_WHITE)
                    self.rect(self.l_margin, _cy, tbl_w, _ch, style="F",
                              round_corners=True, corner_radius=_CR)
                    _use_round[0] = True
                except TypeError:
                    _use_round[0] = False
        _header_row(_use_round[0])

        _last = len(rows) - 1
        for i, row in enumerate(rows):
            if self.get_y() > self.h - 30:
                self.add_page()
                _header_row(False)   # continuation header is always a plain row
            is_alt = (i % 2 == 0)
            if _use_round[0]:
                # Transparent cells over the white card; paint only alt rows.
                if is_alt:
                    self.set_fill_color(*_ROW_ALT)
                    if i == _last:
                        try:
                            self.rect(self.l_margin, self.get_y(), tbl_w, TBL_ROW_H, style="F",
                                      round_corners=("BOTTOM_LEFT", "BOTTOM_RIGHT"),
                                      corner_radius=_CR)
                        except TypeError:
                            self.rect(self.l_margin, self.get_y(), tbl_w, TBL_ROW_H, style="F")
                    else:
                        self.rect(self.l_margin, self.get_y(), tbl_w, TBL_ROW_H, style="F")
                for cell_val, w, a in zip(row, col_widths, aligns):
                    self.cell(w, TBL_ROW_H, f" {cell_val} ", border=0, fill=False, align=a)
                self.ln()
            else:
                self.set_fill_color(*(_ROW_ALT if is_alt else _WHITE))
                for cell_val, w, a in zip(row, col_widths, aligns):
                    self.cell(w, TBL_ROW_H, f" {cell_val} ", border=0, fill=True, align=a)
                self.ln()

    def logo_row_table(self, headers: list[str], rows: list[list[str]],
                       logos: dict, col_widths: list[float] | None = None,
                       aligns: list[str] | None = None):
        """Like data_table but draws a small inline ticker logo to the left of the
        first-column name. `rows[i][0]` is the asset name and `logos[name]` its
        PNG bytes (or None). Rounded outer corners match data_table."""
        n = len(headers)
        usable = self.w - self.l_margin - self.r_margin
        if col_widths is None:
            col_widths = [usable / n] * n
        if aligns is None:
            aligns = ["L"] + ["R"] * (n - 1)
        LW = LH = 6.0
        ROW_H  = 10.0
        HEAD_H = 9.0
        tbl_w  = sum(col_widths)
        _CR    = 3.0
        # Rounded card disables on a multi-page split (a rounded card across a
        # page break looks broken) — same fallback as data_table.
        _use_round = [False]

        def _header_row(rounded_card: bool = False):
            if rounded_card:
                self.set_fill_color(*self.ink)
                try:
                    self.rect(self.l_margin, self.get_y(), tbl_w, HEAD_H, style="F",
                              round_corners=("TOP_LEFT", "TOP_RIGHT"), corner_radius=_CR)
                except TypeError:
                    self.rect(self.l_margin, self.get_y(), tbl_w, HEAD_H, style="F")
            else:
                self.set_fill_color(*self.ink)
            self._sf(7.5, "body_bold")
            for idx, (h, w, a) in enumerate(zip(headers, col_widths, aligns)):
                self.set_text_color(*(self.lime if idx == 0 else _WHITE))
                self.cell(w, HEAD_H, f" {h} ", border=0, fill=not rounded_card, align=a)
            self.ln()
            self.set_text_color(*_TEXT)
            self._sf(8, "regular")

        # Keep the whole table together when it fits on one page — the same
        # three-way decision as `data_table`, and it must be the same one: a
        # heading above reserved room using `table_room`, and a second opinion
        # taken here can only disagree with it.
        #
        # Consuming the claim is not optional even where the branch is a no-op.
        # This method used not to call `_head_claimed()` at all, so the claim
        # stayed set and the NEXT `data_table` on the page skipped its own
        # keep-together rule with no heading above it — a stale reservation
        # spent by a block that never made one.
        _needed   = HEAD_H + len(rows) * ROW_H + 6
        _avail    = self.h - 30 - self.get_y()
        _page_cap = self.h - 30 - 21
        if self._head_claimed():
            if self.get_y() > self.h - 55:
                self.add_page()
        elif _needed > _avail and _needed <= _page_cap:
            self.add_page()
        elif self.get_y() > self.h - 55:
            self.add_page()

        # White rounded card behind the whole table rounds the bottom corners;
        # the header's rounded-top strip rounds the top. Only when it fits the
        # page; older fpdf2 (no round_corners kwarg) → plain rects.
        _ch = HEAD_H + len(rows) * ROW_H
        _cy = self.get_y()
        if _cy + _ch <= self.h - 28:
            try:
                self.set_fill_color(*_WHITE)
                self.rect(self.l_margin, _cy, tbl_w, _ch, style="F",
                          round_corners=True, corner_radius=_CR)
                _use_round[0] = True
            except TypeError:
                _use_round[0] = False
        _header_row(_use_round[0])

        _last = len(rows) - 1
        for i, row in enumerate(rows):
            if self.get_y() > self.h - 30:
                self.add_page()
                _header_row(False)   # continuation header is a plain row
            name  = str(row[0])
            is_alt = (i % 2 == 0)
            row_y = self.get_y()
            # Full-width row background: alt rows get a zebra fill (the last one
            # rounded at the bottom so the card's corners stay round); white rows
            # are transparent over the white card.
            if _use_round[0]:
                if is_alt:
                    self.set_fill_color(*_ROW_ALT)
                    if i == _last:
                        try:
                            self.rect(self.l_margin, row_y, tbl_w, ROW_H, style="F",
                                      round_corners=("BOTTOM_LEFT", "BOTTOM_RIGHT"),
                                      corner_radius=_CR)
                        except TypeError:
                            self.rect(self.l_margin, row_y, tbl_w, ROW_H, style="F")
                    else:
                        self.rect(self.l_margin, row_y, tbl_w, ROW_H, style="F")
            else:
                self.set_fill_color(*(_ROW_ALT if is_alt else _WHITE))
                self.rect(self.l_margin, row_y, tbl_w, ROW_H, style="F")
            # First column: inline logo, then name
            ldata  = (logos or {}).get(name)
            text_x = self.l_margin + 2
            if ldata:
                try:
                    self.image(io.BytesIO(ldata), x=self.l_margin + 1,
                               y=row_y + (ROW_H - LH) / 2, w=LW, h=LH)
                    text_x = self.l_margin + LW + 3
                except Exception:
                    pass
            self.set_xy(text_x, row_y + (ROW_H - 4) / 2)
            _name_w = col_widths[0] - (text_x - self.l_margin) - 1
            self._fit_font(name, _name_w, 8, "semibold")
            self.set_text_color(*_TEXT)
            self.cell(_name_w, 4, self._safe(name))
            # Remaining columns — transparent text over the row background
            self._sf(8, "regular")
            self.set_text_color(*_TEXT)
            self.set_xy(self.l_margin + col_widths[0], row_y)
            for cell_val, w, a in zip(row[1:], col_widths[1:], aligns[1:]):
                self.cell(w, ROW_H, f" {cell_val} ", border=0, fill=False, align=a)
            self.set_y(row_y + ROW_H)

        self.ln(4)

    def metric_band(self, metrics: list[tuple[str, str]]):
        """A row of metric tiles — each an ECF1F6 card with a tracked muted label
        and an ink (or amber, when negative) Neulis value. Mirrors the prototype's
        MC / Backtest / Current-Performance metric strips."""
        n = len(metrics)
        usable = self.w - self.l_margin - self.r_margin
        gap = 3.0
        # BALANCED rows, max 4 across. Filling rows of 3 until the tiles run out
        # left a ragged tail — 7 metrics rendered 3 + 3 + 1, stranding one tile
        # on a row of its own, and it read as an accident rather than a layout.
        # Spread n over ceil(n/4) rows as evenly as possible instead, so 7 is
        # 4 + 3, 5 is 3 + 2 and no row is ever shorter than the one below it by
        # more than one tile. Each row is stretched to the full measure, so the
        # band keeps a flush left AND right edge whatever the count.
        nrows = max(1, (n + 3) // 4)
        base, extra = divmod(n, nrows)
        counts = [base + (1 if r < extra else 0) for r in range(nrows)]
        # (row index, column index, columns in that row) per tile, in order.
        slots, _i = [], 0
        for r, cnt in enumerate(counts):
            for c in range(cnt):
                slots.append((r, c, cnt))
                _i += 1
        y0 = self.get_y()
        h = 19.0
        for i, (label, value) in enumerate(metrics):
            r, c, cnt = slots[i]
            w = (usable - gap * (cnt - 1)) / cnt
            x = self.l_margin + c * (w + gap)
            yr = y0 + r * (h + gap)
            self.set_fill_color(*self.panel_color)
            try:
                self.rect(x, yr, w, h, style="F", round_corners=True, corner_radius=2)
            except TypeError:
                self.rect(x, yr, w, h, style="F")
            # Tracked muted label.
            lbl = self._safe(label.upper())
            size = 6.3
            self._sf(size, "body_bold")
            while self.get_string_width(lbl) > (w - 6) and size > 4.4:
                size -= 0.2
                self._sf(size, "body_bold")
            self.set_xy(x + 4, yr + 3.6)
            self.set_text_color(*self.muted)
            try:
                self.set_char_spacing(0.3)
            except Exception:
                pass
            self.cell(w - 6, 3.3, lbl)
            try:
                self.set_char_spacing(0)
            except Exception:
                pass
            # Value — ink, or amber when negative; shrink/wrap a long free-text value.
            val = self._safe(str(value))
            self.set_text_color(*(self.amber if val.strip().startswith("-") else self.ink))
            vsize = 14.0
            self._sf(vsize, "bold")
            while self.get_string_width(val) > (w - 6) and vsize > 8.5:
                vsize -= 0.3
                self._sf(vsize, "bold")
            if self.get_string_width(val) > (w - 6):
                self.set_xy(x + 4, yr + 8.2)
                self.multi_cell(w - 6, vsize * 0.42, val,
                                align="L", new_x="LMARGIN", new_y="TOP")
            else:
                self.set_xy(x + 4, yr + 9.6)
                self.cell(w - 6, 7, val)

        self.set_y(y0 + nrows * h + (nrows - 1) * gap)
        self.set_text_color(*_TEXT)
        self.ln(5)

    def figure(self, img_bytes: bytes | None, caption: str, source: str,
               w: float = 172, h: float | None = None, max_h: float = 118):
        if img_bytes is None:
            return
        self._fig_no += 1
        # Derive the placement height from the PNG's true pixel aspect ratio so
        # charts keep their natural proportions instead of being squashed into a
        # fixed box. A very tall chart is fitted by height and re-centred.
        if h is None:
            try:
                from PIL import Image
                iw, ih = Image.open(io.BytesIO(img_bytes)).size
                h = w * ih / iw
                if h > max_h:
                    h = max_h
                    w = h * iw / ih
            except Exception:
                h = 80
        _fpad = 3.0   # padding between the chart and its panel edge
        needed = h + 18 + 2 * _fpad
        if self.get_y() + needed > self.h - 28:
            self.add_page()
        # Caption above figure — SemiBold 8.5pt in the brand primary colour
        # (matches the section titles). Deliberately NOT the accent: the accent
        # now drives the chart series palette, and a caption that tracks the chart
        # lines looked off — the caption is chrome, so it stays on the brand head
        # colour like every other heading.
        self._sf(8.5, "bold")
        self.set_text_color(*self.ink)
        self.multi_cell(0, 4.5, f"{self.t('figure_word')} {self._fig_no}: {caption}", align="C")
        self.ln(1)
        x = (self.w - w) / 2
        # White rounded card with a hairline border behind the chart (the
        # prototype frames every figure in a white bordered card).
        self.ln(_fpad)
        _img_y = self.get_y()
        self.set_fill_color(*_WHITE)
        self.set_draw_color(*self.rule_soft)
        self.set_line_width(0.2)
        try:
            self.rect(x - _fpad, _img_y - _fpad, w + 2 * _fpad, h + 2 * _fpad,
                      style="DF", round_corners=True, corner_radius=2)
        except TypeError:
            self.rect(x - _fpad, _img_y - _fpad, w + 2 * _fpad, h + 2 * _fpad, style="DF")
        self.image(io.BytesIO(img_bytes), x=x, y=_img_y, w=w, h=h)
        self.set_y(_img_y + h + _fpad)
        self.ln(1.5)
        # Source line — italic muted, like the prototype caption source.
        self._sf(7, "italic")
        self.set_text_color(*self.muted)
        self.cell(0, 3.5, source, align="C", new_x="LMARGIN", new_y="NEXT")
        self.set_text_color(*_TEXT)
        self.ln(3.5)

    def callout(self, title: str, text: str, w: float | None = None):
        """A light-tinted blurb panel with a green left keyline (the prototype's
        'Model & Methodology' box). Title in ink, body in body-ink."""
        if w is None:
            w = self.w - self.l_margin - self.r_margin
        x0, y0 = self.l_margin, self.get_y()
        self._sf(8, "regular")
        lines = self.multi_cell(w - 12, 4.3, self._safe(text), dry_run=True, output="LINES")
        box_h = 11 + len(lines) * 4.3 + 4
        if y0 + box_h > self.h - 28:
            self.add_page()
            y0 = self.get_y()
        # Very light green-tinted panel + a 1.4mm green left bar.
        self.set_fill_color(*_blend(self.primary_color, _WHITE, 0.94))
        try:
            self.rect(x0, y0, w, box_h, style="F", round_corners=True, corner_radius=2)
        except TypeError:
            self.rect(x0, y0, w, box_h, style="F")
        self.set_fill_color(*self.primary_color)
        self.rect(x0, y0, 1.4, box_h, style="F")
        self.set_xy(x0 + 7, y0 + 4.0)
        self._sf(8.5, "bold")
        self.set_text_color(*self.ink)
        self.cell(w - 11, 5, title)
        self.set_xy(x0 + 7, y0 + 10.5)
        self._sf(8, "regular")
        self.set_text_color(*self.body_ink)
        self.multi_cell(w - 11, 4.3, text)
        self.set_y(y0 + box_h + 4)
