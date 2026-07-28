"""
reportkit.theme
---------------
Pluggable, domain-agnostic visual-identity layer for themed PDF reports.

A report's *content* (tables, metric bands, figures, cover copy, …) is theme-
agnostic. Everything that is a *look* — the shape vocabulary (e.g. chamfered
hexagons or rounded cards), the running header/footer chrome, section heads and
chapter dividers, the cover masthead, and empty-space decorations — is owned by a
ReportTheme here, so a brand can swap the entire visual language without touching
content code.

The theme is handed palette-derived ThemeTokens and draws through the host's live
document instance (passed as `pdf`, any FPDF subclass exposing the small surface
the hooks use: `.t(key)`, `._safe`, `._sf`, tokens like `.ink`/`.lime`/…), so it
has full access to fpdf primitives, fonts, and page geometry. The host module in
this repo is app/pdf_report.py (the Structured Note Simulator's report adapter),
but nothing here depends on that — reportkit is reusable by any project.

Themes
------
- HexagonTheme  — a chamfer-hexagon language (dark mastheads, lime number-chips,
  hex-cluster watermarks). CADIEM selects it via branding["report_theme"].
- MercatorTheme — a cleaner, website-inspired language (rounded cards, accent
  keylines, no chamfers/hexagons). The default for un-themed brands.

Selection: branding["report_theme"] → resolve_theme(); an absent/unknown value
falls back to DEFAULT_THEME.

Regression contract: HexagonTheme reproduces the reference CADIEM output; a
hermetic golden pixel-diff harness (scratchpad/golden.py) guards against drift.
"""
from __future__ import annotations

import io
import math
from dataclasses import dataclass

from fpdf.drawing import DeviceRGB
from fpdf.pattern import LinearGradient, RadialGradient

from reportkit.images import _cover_crop


# ──────────────────────────────────────────────────────────────────────────────
# Design tokens — the palette-derived colour vocabulary every theme shares.
# ──────────────────────────────────────────────────────────────────────────────
# Brand-neutral constants (the design has NO red; downside is amber). These are
# the canonical home; pdf_report.py re-imports them so there is one source.
WHITE         = (255, 255, 255)
BLACK         = (0,   0,   0)
AMBER         = (201, 119,  45)  # #C9772D — downside / capital-loss
AMBER_DARK    = (154, 123,  18)  # #9A7B12 — deep amber (knock-in)
MUTED         = (139, 151, 160)  # #8B97A0 — eyebrow/label grey
BODY_INK      = ( 36,  59,  51)  # #243B33 — paragraph text on white
RULE_SOFT     = (201, 210, 204)  # #C9D2CC — secondary-head hairline
FOOTNOTE_GREY = (166, 176, 184)  # #A6B0B8 — footnote / caption
TEXT          = ( 43,  61,  79)  # #2B3D4F — default body/running text ink


def blend(rgb: tuple, target: tuple, f: float) -> tuple:
    """Linear blend of `rgb` toward `target` by fraction `f` (0..1), rounded."""
    return tuple(round(rgb[i] * (1 - f) + target[i] * f) for i in range(3))


@dataclass
class ThemeTokens:
    """Palette-derived colour tokens handed to a ReportTheme. `ink` = darkened
    primary (mastheads/banners/stat values); `lime` = the section-rule colour
    (keylines, number chips, accents); `teal` = the accent (secondary series,
    kickers). The neutral tokens match the reference's grey-green family; `panel`
    is the card/tile fill; `sidebar_bar` the solid bar atop the cover sidebar."""
    primary: tuple
    accent: tuple
    section_rule: tuple
    ink: tuple
    lime: tuple
    teal: tuple
    amber: tuple
    amber_dark: tuple
    muted: tuple
    body_ink: tuple
    rule_soft: tuple
    footnote_grey: tuple
    panel: tuple
    sidebar_bar: tuple


def build_tokens(primary: tuple, accent: tuple, section_rule: tuple,
                 panel: tuple | None = None,
                 sidebar_bar: tuple | None = None) -> ThemeTokens:
    """Derive the full token set from the resolved brand palette. `panel` and
    `sidebar_bar` may be pinned by the brand; otherwise `panel` is a very light
    tint of PRIMARY (so a bold accent never yields a pink card) and `sidebar_bar`
    is the primary (matching the table headers). Mirrors the original
    _NotePDF.__init__ derivation exactly — byte-identity depends on it."""
    return ThemeTokens(
        primary=primary,
        accent=accent,
        section_rule=section_rule,
        ink=blend(primary, BLACK, 0.46),
        lime=section_rule,
        teal=accent,
        amber=AMBER,
        amber_dark=AMBER_DARK,
        muted=MUTED,
        body_ink=BODY_INK,
        rule_soft=RULE_SOFT,
        footnote_grey=FOOTNOTE_GREY,
        panel=(panel if panel is not None else blend(primary, WHITE, 0.93)),
        sidebar_bar=(sidebar_bar if sidebar_bar is not None else primary),
    )


# ──────────────────────────────────────────────────────────────────────────────
# The CADIEM "hexagon" — a rectangular chamfer (rectangle with the top-right and
# bottom-left corners cut at 45°, all corners rounded). Reproduced as a true
# vector path (PaintedPath) so it scales crisply at any size — used for the dark
# mastheads/banners, the lime number chips, and faint watermark clusters.
# ──────────────────────────────────────────────────────────────────────────────
def _dev_rgb(t: tuple[int, int, int]) -> DeviceRGB:
    return DeviceRGB(t[0] / 255.0, t[1] / 255.0, t[2] / 255.0)


def _chamfer_outline(path, x: float, y: float, w: float, h: float,
                     c: float, q: float, r: float) -> None:
    """Trace the chamfer path into `path`. Transcribes the prototype's
    hexPath(W,H,c,q,r): chamfer depth `c`, chamfer-corner round `q`, normal
    corner radius `r`. (x, y) = top-left in mm."""
    s = q * 0.70710678
    X = lambda v: x + v
    Y = lambda v: y + v
    path.move_to(X(r), Y(0))
    path.line_to(X(w - c - q), Y(0))
    path.quadratic_curve_to(X(w - c), Y(0), X(w - c + s), Y(s))
    path.line_to(X(w - s), Y(c - s))
    path.quadratic_curve_to(X(w), Y(c), X(w), Y(c + q))
    path.line_to(X(w), Y(h - r))
    path.quadratic_curve_to(X(w), Y(h), X(w - r), Y(h))
    path.line_to(X(c + q), Y(h))
    path.quadratic_curve_to(X(c), Y(h), X(c - s), Y(h - s))
    path.line_to(X(s), Y(h - c + s))
    path.quadratic_curve_to(X(0), Y(h - c), X(0), Y(h - c - q))
    path.line_to(X(0), Y(r))
    path.quadratic_curve_to(X(0), Y(0), X(r), Y(0))
    path.close()


def _chamfer_dims(w: float, h: float, c=None, q=None, r=None):
    """Default chamfer parameters proportional to the shape; any may be pinned."""
    m = min(w, h)
    if c is None:
        c = m * 0.14
    if q is None:
        q = c * 0.28
    if r is None:
        r = min(m * 0.10, 6.0)
    return c, q, r


def _fill_chamfer(pdf, x: float, y: float, w: float, h: float,
                  rgb: tuple[int, int, int], c=None, q=None, r=None,
                  opacity: float = 1.0) -> None:
    """Draw a filled chamfer-hexagon panel (banner / chip / masthead)."""
    c, q, r = _chamfer_dims(w, h, c, q, r)
    with pdf.new_path() as p:
        p.style.fill_color = _dev_rgb(rgb)
        p.style.stroke_color = None
        if opacity != 1.0:
            p.style.fill_opacity = opacity
        _chamfer_outline(p, x, y, w, h, c, q, r)


def _stroke_chamfer(pdf, x: float, y: float, w: float, h: float,
                    rgb: tuple[int, int, int], c=None, q=None, r=None,
                    line_w: float = 0.4, opacity: float = 1.0) -> None:
    """Draw an unfilled chamfer-hexagon outline (watermark decoration)."""
    c, q, r = _chamfer_dims(w, h, c, q, r)
    with pdf.new_path() as p:
        p.style.fill_color = None
        p.style.stroke_color = _dev_rgb(rgb)
        p.style.stroke_width = line_w
        if opacity != 1.0:
            p.style.stroke_opacity = opacity
        _chamfer_outline(p, x, y, w, h, c, q, r)


def _hex_cluster(pdf, x: float, y: float, scale: float,
                 rgb: tuple[int, int, int], variant: int = 0,
                 opacity: float = 0.5) -> None:
    """A faint decorative cluster of 2–3 varied chamfer-hexagons (outlines plus
    one filled), bleeding from (x, y). Brand-graphic only — callers place it in
    genuinely empty space, behind content, never over text. `variant` 0/1/2
    picks one of three arrangements so the clusters differ page-to-page."""
    # (dx, dy, size, filled) tuples in `scale` units — three hand-tuned layouts.
    layouts = [
        [(0.0, 0.0, 1.0, False), (0.72, 0.46, 0.62, True), (0.30, 0.92, 0.44, False)],
        [(0.0, 0.30, 0.82, False), (0.58, 0.0, 1.0, False), (0.94, 0.66, 0.5, True)],
        [(0.0, 0.0, 0.7, True), (0.46, 0.36, 1.0, False), (1.04, 0.10, 0.5, False)],
    ]
    for dx, dy, sz, filled in layouts[variant % len(layouts)]:
        s = scale * sz
        bx, by = x + scale * dx, y + scale * dy
        if filled:
            _fill_chamfer(pdf, bx, by, s, s, rgb,
                          c=s * 0.2, q=s * 0.06, r=s * 0.2, opacity=opacity)
        else:
            _stroke_chamfer(pdf, bx, by, s, s, rgb,
                            c=s * 0.2, q=s * 0.06, r=s * 0.2,
                            line_w=max(0.25, s * 0.02), opacity=opacity)


# ── watermark: ONE brand mark, ONE config, ONE gate ───────────────────────────
# The watermark is a single faint brand decoration painted behind text on up to
# four surfaces (masthead / divider / empty space / cover). It is either an
# uploaded IMAGE (any brand) or the theme's own drawn hex cluster (e.g. CADIEM's
# hexagons — never a generic option). ONE resolved config lives on the pdf as
# `pdf.watermark` = {image, opacity, scale, anchor, surfaces:set}; every surface
# reads the SAME values. There is no separate enable flag, no per-surface
# appearance, and no second gate — an empty `surfaces` set means "off".
WM_SURFACES = ("masthead", "divider", "void", "cover")
WM_DEFAULTS = {"opacity": 0.13, "scale": 0.58, "anchor": "right"}


def resolve_watermark(brand: dict | None, image: bytes | None) -> dict:
    """Resolve the single watermark config from a brand dict (+ its already-
    decoded image). Reads the nested `watermark` block, falling back to the
    legacy flat `watermark_*` keys so old configs keep rendering identically.
    `image` is None when there is no upload OR the brand disabled it."""
    b = brand or {}
    wm = b.get("watermark") if isinstance(b.get("watermark"), dict) else {}

    def _num(key, lo, hi, dflt):
        v = wm.get(key, b.get(f"watermark_{key}"))
        try:
            return max(lo, min(hi, float(v)))
        except (TypeError, ValueError):
            return dflt

    anchor = str(wm.get("anchor") or b.get("watermark_anchor") or "right").lower()
    if anchor not in ("left", "center", "right"):
        anchor = "right"
    # `surfaces` (new) or legacy `watermark_places`; absent → every surface.
    sf = wm.get("surfaces", b.get("watermark_places"))
    surfaces = ({s for s in sf if s in WM_SURFACES}
                if isinstance(sf, (list, tuple, set)) else set(WM_SURFACES))
    return {"image": image,
            "opacity": _num("opacity", 0.0, 1.0, WM_DEFAULTS["opacity"]),
            "scale":   _num("scale", 0.05, 1.0, WM_DEFAULTS["scale"]),
            "anchor":  anchor, "surfaces": surfaces}


def _wm_image(pdf, px: float, py: float, pw: float, ph: float,
              image: bytes, opacity: float, scale: float, anchor: str) -> None:
    """Draw the uploaded watermark image inside (px, py, pw, ph): sized to a
    fraction of the panel HEIGHT (never stretched), aspect-preserved, edge-
    anchored with an inset that clears the chamfer, vertically centred, low
    opacity so it sits behind the text."""
    try:
        from PIL import Image as _PILImage
        with _PILImage.open(io.BytesIO(image)) as _im:
            iw, ih = _im.size
        asp = (iw / ih) if ih else 1.0                      # width / height
        h = ph * max(0.05, min(1.0, scale))
        w = h * asp
        if w > pw * 0.42:                                   # never dominate the panel
            w = pw * 0.42
            h = (w / asp) if asp else h
        inset = ph * 0.16
        x = (px + inset if anchor == "left"
             else px + (pw - w) / 2.0 if anchor == "center"
             else px + pw - inset - w)
        y = py + (ph - h) / 2.0
        with pdf.local_context(fill_opacity=max(0.0, min(1.0, opacity))):
            pdf.image(io.BytesIO(image), x=x, y=y, w=w, h=h)
    except Exception:
        pass


def _watermark(pdf, px: float, py: float, pw: float, ph: float, surface: str,
               *, hex: tuple | None = None) -> None:
    """Draw the brand watermark on `surface` inside the rect (px, py, pw, ph).

    The ONE gate is `pdf.watermark['surfaces']`. The mark is the uploaded image
    when there is one, else the theme's hex cluster — `hex` is that cluster's
    (x, y, scale, rgb, variant, opacity) args, or None when the theme draws no
    hex on this surface. Appearance (opacity/scale/anchor) comes from the single
    resolved config and is identical on every surface."""
    wm = getattr(pdf, "watermark", None)
    if not wm or surface not in wm["surfaces"]:
        return
    if wm.get("image") is not None:
        _wm_image(pdf, px, py, pw, ph, wm["image"], wm["opacity"], wm["scale"], wm["anchor"])
    elif hex is not None:
        _hex_cluster(pdf, *hex)


# ──────────────────────────────────────────────────────────────────────────────
# ReportTheme — the pluggable visual-identity interface.
# ──────────────────────────────────────────────────────────────────────────────
# A theme owns every "look" decision. Each hook receives the live _NotePDF
# instance (`pdf`) and draws through it — so it has full access to fpdf
# primitives, the active fonts, page geometry, and the palette tokens on
# pdf.tokens / pdf.ink / pdf.lime / … . Content code (tables, figures, copy)
# never calls these directly; it calls the _NotePDF wrappers which delegate to
# pdf.theme, so swapping the theme swaps the entire identity.
#
# Cross-module note: a couple of hooks need report helpers that live in
# pdf_report.py (the translated footer strings via pdf.t(); the photo cropper).
# These are reached through the `pdf` instance or a deferred import to avoid an
# import cycle (pdf_report imports this module at top level).
class ReportTheme:
    """Base interface. Subclasses implement the chrome hooks. The default
    implementations raise so a partial theme fails loudly rather than silently
    drawing nothing."""

    name = "base"

    # Voids at/above this height read as egregiously empty — fill them with an
    # actual brand photo band rather than only a faint graphic composition.
    EGREGIOUS_VOID = 70.0

    # ── theme-specific hooks (subclasses MUST implement) ───────────────────
    def header(self, pdf) -> None:
        raise NotImplementedError

    def section_title(self, pdf, text) -> None:
        raise NotImplementedError

    def secondary_head(self, pdf, number, kicker, title, min_room=40.0,
                       badge=None, badge_color=None, badge_logo=None) -> None:
        raise NotImplementedError

    def section_divider(self, pdf, number, kicker, heading) -> None:
        raise NotImplementedError

    def decorate_void(self, pdf, variant=0, min_gap=44.0) -> None:
        raise NotImplementedError

    def cover_masthead(self, pdf, x0, y_m, W, MH) -> None:
        """Draw the cover masthead background panel (the eyebrow / note-name /
        KPI text is drawn on top by the cover builder, in white)."""
        raise NotImplementedError

    def cover_left_void_fill(self, pdf, x0, sc, bottom) -> None:
        """Fill the cover's empty left column (below the rail) when no photo took
        it — a faint brand-graphic composition."""
        raise NotImplementedError

    # ── shared hooks (identical across themes; concrete here) ──────────────
    def footer(self, pdf) -> None:
        # The cover renders its own self-contained bottom disclaimer band; the
        # running footer would overprint it, so skip it on cover pages.
        #
        # `_cover_pages` and NOT `_is_cover`: fpdf2 renders the CLOSING page's
        # footer from inside `add_page()`, and every cover builder sets
        # `_is_cover = True` *before* its `add_page()` — so consulting the flag
        # here asks "is the page I am about to draw a cover?" when the question
        # is "is the page I am finishing one?". That stripped the footer off the
        # last content page before any cover, most visibly the glossary's.
        # `_cover_pages` is keyed by page number, so it cannot be ambiguous; a
        # cover is registered in it immediately after `add_page()` and covers
        # disable auto page break, so nothing can break out of one before the
        # entry lands.
        if pdf.page_no() in pdf._cover_pages:
            return
        pdf.set_draw_color(*pdf.rule_soft)
        pdf.set_line_width(0.2)
        pdf.line(pdf.l_margin, pdf.h - 22, pdf.w - pdf.r_margin, pdf.h - 22)
        pdf.set_y(-20)
        pdf._sf(6, "light")
        pdf.set_text_color(*pdf.footnote_grey)
        pdf.multi_cell(0, 2.9, pdf.footer_note or pdf.t("footer_line"), align="L")
        pdf.set_y(-11)
        pdf._sf(6.5, "light")
        pdf.set_text_color(*pdf.footnote_grey)
        _page = pdf.t("page_of")
        _mid  = pdf.t("page_of_mid")
        pdf.cell(0, 4.5, f"{_page} {pdf.page_no()} {_mid} {{nb}}", align="R")
        pdf.set_text_color(*TEXT)

    def eyebrow(self, pdf, x, y, text, color, size=7.0, tracking=0.4,
                w=0.0, align="L") -> None:
        """A tracked uppercase label — the design's 'eyebrow' / kicker."""
        pdf._sf(size, "body_bold")
        pdf.set_text_color(*color)
        try:
            pdf.set_char_spacing(tracking)
        except Exception:
            pass
        pdf.set_xy(x, y)
        pdf.cell(w, size * 0.55, pdf._safe(str(text).upper()), align=align)
        try:
            pdf.set_char_spacing(0)
        except Exception:
            pass

    def subsection(self, pdf, text, min_room=27.0) -> None:
        """SemiBold 9pt sub-header."""
        if pdf.get_y() > pdf.h - pdf.b_margin - min_room:
            pdf.add_page()
        pdf.ln(2)
        pdf._sf(9, "semibold")
        pdf.set_text_color(*TEXT)
        pdf.cell(0, 6, text.upper(), new_x="LMARGIN", new_y="NEXT")
        pdf.set_text_color(*TEXT)
        pdf.ln(2)

    def decorate_void_photo(self, pdf, x0, x1, y, floor, gap, filler) -> bool:
        """Render the egregious-void photo band (see decorate_void). Shape-neutral
        (image + brand tint + accent top rule), so it's shared by every theme."""
        try:
            pad_top = 13.0                       # breathing room below the content
            band_w = x1 - x0
            band_h = min(gap - pad_top, 104.0)   # a band, not a giant square
            if band_h < 52.0:
                return False
            by = floor - band_h                  # anchored at the floor
            _bx = (-0.6, 0.0, 0.6)[pdf.page_no() % 3]
            _by = (0.0, -0.5, 0.5)[(pdf.page_no() // 3) % 3]
            cropped = _cover_crop(filler, band_w / band_h, bias_x=_bx, bias_y=_by) or filler
            try:
                from PIL import Image
                _bim = Image.open(io.BytesIO(cropped)).convert("RGB")
                _buf = io.BytesIO(); _bim.save(_buf, "JPEG", quality=78, optimize=True)
                cropped = _buf.getvalue()
            except Exception:
                pass
            pdf.image(io.BytesIO(cropped), x=x0, y=by, w=band_w, h=band_h)
            tint = getattr(pdf, "cover_overlay_color", pdf.primary_color)
            with pdf.local_context(fill_opacity=0.30):
                pdf.set_fill_color(*tint)
                pdf.rect(x0, by, band_w, band_h, style="F")
            with pdf.local_context(fill_opacity=0.34):
                pdf.set_fill_color(*pdf.ink)
                pdf.rect(x0, floor - 16.0, band_w, 16.0, style="F")
            pdf.set_fill_color(*pdf.lime)
            pdf.rect(x0, by, band_w, 1.5, style="F")
            sig = getattr(pdf, "cover_sigil_bytes", None)
            if sig:
                from PIL import Image
                iw, ih = Image.open(io.BytesIO(sig)).size
                sh = min(band_h * 0.42, 26.0)
                sw = sh * iw / ih
                with pdf.local_context(fill_opacity=0.55):
                    pdf.image(io.BytesIO(sig), x=x1 - sw - 6.0,
                              y=floor - sh - 3.5, w=sw, h=sh)
            return True
        except Exception:
            return False

    # ── cover (summary page) brand graphics ────────────────────────────────
    def cover_masthead(self, pdf, x0, y_m, W, MH) -> None:
        """Draw the cover masthead background panel (the eyebrow / note-name /
        KPI text is drawn on top by the cover builder, in white)."""
        raise NotImplementedError

    def cover_left_void_fill(self, pdf, x0, sc, bottom) -> None:
        """Fill the cover's empty left column (below the rail) when no photo took
        it — a faint brand-graphic composition."""
        raise NotImplementedError


# ══════════════════════════════════════════════════════════════════════════════
# Declarative theme spec engine
# ══════════════════════════════════════════════════════════════════════════════
# A theme is DATA: a spec dict describing each report surface (shape, fill,
# geometry, watermark). `SpecTheme` interprets it, so a brand can author entirely
# new themes — including gradient fills and custom geometry — without writing
# code. The two built-in looks (HEXAGON_SPEC / MERCATOR_SPEC) are specs like any
# other; a branding config may pass a name, or an inline spec (optionally with a
# "base" to inherit-and-override).
#
# Colour references in a spec resolve against the document's palette tokens, so a
# theme stays palette-driven (any brand's colours flow through it). A colour ref
# is: a token name ("ink"/"lime"/"primary"/…), "#rrggbb", an (r,g,b) tuple, or a
# dict {"token": n} | {"hex": s} | {"mix": [a, b, f]} (blend a→b by fraction f).
# A fill is {"type":"solid","color":ref} or {"type":"linear"|"radial", "angle":
# deg, "stops":[{"color":ref}, …]}. A shape is {"kind":"chamfer"|"rounded"|
# "square", …geometry…}.

_TOKEN_ATTR = {
    "primary": "primary_color", "accent": "accent_color",
    "section_rule": "section_rule_color", "panel": "panel_color",
    "sidebar_bar": "sidebar_bar_color",
    "ink": "ink", "lime": "lime", "teal": "teal", "amber": "amber",
    "amber_dark": "amber_dark", "muted": "muted", "body_ink": "body_ink",
    "rule_soft": "rule_soft", "footnote_grey": "footnote_grey",
}
_CONST_TOKEN = {"white": WHITE, "black": BLACK, "text": TEXT}


def _parse_hex(s, default: tuple = TEXT) -> tuple:
    """Parse `#rgb`/`#rrggbb`, falling back rather than raising.

    Theme specs are user-authored JSON, so a malformed colour is a typo, not a
    programming error — and every one of these is reached deep inside a drawing
    routine where an exception aborts the whole document. `"#zz"` used to raise
    ValueError out of int(..., 16) and take the report with it.
    """
    try:
        h = str(s).strip().lstrip("#")
        if len(h) == 3:
            h = "".join(ch * 2 for ch in h)
        if len(h) != 6:
            raise ValueError(f"expected 3 or 6 hex digits, got {h!r}")
        return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
    except Exception:
        print(f"[reportkit.theme] unparseable colour {s!r}; using the default")
        return default


def _hexstr(rgb) -> str:
    return "#%02x%02x%02x" % (int(rgb[0]), int(rgb[1]), int(rgb[2]))


def _luma(c) -> float:
    """Relative luminance, 0 (black) → 1 (white)."""
    r, g, b = (max(0.0, min(255.0, float(v))) / 255.0 for v in c[:3])
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def readable_on(fg, bg, fallback, min_delta: float = 0.22) -> tuple:
    """`fg`, unless it would be invisible against `bg` — then `fallback`.

    A theme spec carries the colour of a piece of text and the colour of the
    thing behind it as INDEPENDENT keys, and nothing forces them to agree. The
    divider is the sharp edge: its "banner" style paints a dark band and so
    defaults its heading to white, while its "editorial" style paints no band at
    all and defaults to ink. A spec that switches style to editorial but keeps
    the banner's `heading_color: white` then writes white text on a white page —
    the heading is in the PDF's text layer, selectable and searchable, and
    completely invisible. That is a config a library can't validate away (the
    brand configs are user-authored and live outside this repo), so guard at the
    point of drawing instead: any text whose luminance is within `min_delta` of
    its background falls back to a colour that is known to read.
    """
    try:
        return fg if abs(_luma(fg) - _luma(bg)) >= min_delta else fallback
    except Exception:
        return fallback


def resolve_color(ref, pdf) -> tuple:
    """Resolve a spec colour reference against a document's palette tokens."""
    if ref is None:
        return pdf.ink
    if isinstance(ref, (list, tuple)) and len(ref) == 3 and all(isinstance(v, (int, float)) for v in ref):
        return (int(ref[0]), int(ref[1]), int(ref[2]))
    if isinstance(ref, str):
        if ref.startswith("#"):
            return _parse_hex(ref)
        if ref in _CONST_TOKEN:
            return _CONST_TOKEN[ref]
        got = getattr(pdf, _TOKEN_ATTR.get(ref, ""), None)
        return got if got is not None else pdf.ink
    if isinstance(ref, dict):
        if "hex" in ref:
            return _parse_hex(ref["hex"])
        if "mix" in ref:
            a, b, f = ref["mix"]
            return blend(resolve_color(a, pdf), resolve_color(b, pdf), float(f))
        if "token" in ref:
            return resolve_color(ref["token"], pdf)
    return pdf.ink


def _grad_endpoints(x, y, w, h, angle):
    a = math.radians(angle)
    dx, dy = math.cos(a), math.sin(a)
    cx, cy = x + w / 2.0, y + h / 2.0
    half = (abs(dx) * w + abs(dy) * h) / 2.0
    return (cx - dx * half, cy - dy * half, cx + dx * half, cy + dy * half)


def _shape_kind(shape):
    if isinstance(shape, str):
        return shape, {}
    if isinstance(shape, dict):
        return shape.get("kind", "rounded"), shape
    return "rounded", {}


def _shape_into(p, kind, geom, x, y, w, h):
    if kind == "chamfer":
        c, q, r = _chamfer_dims(w, h, geom.get("c"), geom.get("q"), geom.get("r"))
        _chamfer_outline(p, x, y, w, h, c, q, r)
    elif kind in ("rounded", "soft"):
        p.rectangle(x, y, w, h, rx=geom.get("radius", 3.0), ry=geom.get("radius", 3.0))
    else:  # square / rect
        p.rectangle(x, y, w, h)


def paint_shape(pdf, x, y, w, h, shape, fill, opacity: float = 1.0) -> None:
    """Fill a shape (chamfer / rounded / square) with a solid or gradient fill.
    Solid fills reproduce the original _fill_chamfer / rounded-rect output
    byte-for-byte; gradient fills clip a linear/radial pattern to the shape."""
    kind, geom = _shape_kind(shape)
    fill = fill or {"type": "solid", "color": "ink"}
    ftype = fill.get("type", "solid")
    if ftype == "solid":
        rgb = resolve_color(fill.get("color", "ink"), pdf)
        if kind == "chamfer":
            _fill_chamfer(pdf, x, y, w, h, rgb,
                          c=geom.get("c"), q=geom.get("q"), r=geom.get("r"),
                          opacity=opacity)
        elif kind in ("rounded", "soft"):
            rad = geom.get("radius", 3.0)
            if opacity != 1.0:
                with pdf.local_context(fill_opacity=opacity):
                    pdf.set_fill_color(*rgb)
                    pdf.rect(x, y, w, h, style="F", round_corners=True, corner_radius=rad)
            else:
                pdf.set_fill_color(*rgb)
                pdf.rect(x, y, w, h, style="F", round_corners=True, corner_radius=rad)
        else:
            if opacity != 1.0:
                with pdf.local_context(fill_opacity=opacity):
                    pdf.set_fill_color(*rgb); pdf.rect(x, y, w, h, style="F")
            else:
                pdf.set_fill_color(*rgb); pdf.rect(x, y, w, h, style="F")
        return
    # gradient
    stops = fill.get("stops") or []
    colors = [_hexstr(resolve_color(s.get("color") if isinstance(s, dict) else s, pdf))
              for s in stops]
    if not colors:
        colors = [_hexstr(pdf.ink), _hexstr(pdf.ink)]
    elif len(colors) == 1:
        colors = colors * 2
    if ftype == "radial":
        cx, cy = x + w / 2.0, y + h / 2.0
        # Radius must reach the CORNERS, not the edge midpoints. `max(w,h)/2`
        # only reaches the nearer edges, so on a non-square shape the four
        # corners fall outside the outer circle and — since fpdf2's radial
        # shading doesn't paint past it (extend_after defaults False) — are left
        # unfilled, showing whatever's behind. Half the diagonal circumscribes
        # the rectangle (this is CSS's default `farthest-corner`); extend_after
        # then guards the corner that sits exactly on the boundary.
        r = math.hypot(w, h) / 2.0
        grad = RadialGradient(cx, cy, 0, cx, cy, r, colors, extend_after=True)
    else:
        fx, fy, tx, ty = _grad_endpoints(x, y, w, h, fill.get("angle", 90))
        grad = LinearGradient(fx, fy, tx, ty, colors)
    # `opacity` has to be honoured here too. It was applied only on the solid
    # branch, so a gradient painted with an opacity came out fully opaque — which
    # is what made a gradient cover tint hide the cover photo completely instead
    # of sitting over it.
    if opacity != 1.0:
        with pdf.local_context(fill_opacity=opacity):
            with pdf.use_pattern(grad):
                with pdf.new_path() as p:
                    _shape_into(p, kind, geom, x, y, w, h)
        return
    with pdf.use_pattern(grad):
        with pdf.new_path() as p:
            _shape_into(p, kind, geom, x, y, w, h)


class SpecTheme(ReportTheme):
    """Interprets a declarative theme spec. Reproduces the built-in looks when
    given HEXAGON_SPEC / MERCATOR_SPEC, and renders any brand-authored spec."""

    def __init__(self, spec: dict):
        self.spec = spec or {}
        self.name = self.spec.get("name", "custom")

    def _s(self, key, default=None):
        v = self.spec.get(key)
        return v if v is not None else (default if default is not None else {})

    # ── running header ─────────────────────────────────────────────────────
    def header(self, pdf) -> None:
        if pdf._is_cover:
            return
        if pdf.firm_logo_bytes:
            try:
                h = 6.0
                w = min(h * pdf.firm_logo_aspect, 46.0)
                pdf.image(io.BytesIO(pdf.firm_logo_bytes), x=pdf.l_margin, y=8, w=w, h=h)
            except Exception:
                pass
        pdf._sf(7, "regular")
        pdf.set_text_color(*pdf.muted)
        pdf.set_xy(pdf.w - pdf.r_margin - 95, 8.75)
        note_label = pdf._safe(pdf.doc_ref.split("|")[-1].strip() if "|" in pdf.doc_ref else pdf.doc_ref)
        pdf.cell(95, 4.5, note_label, align="R")
        hd = self._s("header")
        rule = hd.get("rule", {"color": "primary", "weight": 0.6, "y": 16.5})
        ry = rule.get("y", 16.5)
        pdf.set_draw_color(*resolve_color(rule.get("color", "primary"), pdf))
        pdf.set_line_width(rule.get("weight", 0.6))
        pdf.line(pdf.l_margin, ry, pdf.w - pdf.r_margin, ry)
        tick = hd.get("tick")
        if tick:
            pdf.set_fill_color(*resolve_color(tick.get("color", "lime"), pdf))
            pdf.rect(pdf.l_margin, tick.get("y", 16.1), tick.get("w", 15), tick.get("h", 0.8),
                     style="F", round_corners=True, corner_radius=tick.get("radius", 0.4))
        pdf.set_text_color(*TEXT)
        pdf.set_y(21)

    # ── generic section title ──────────────────────────────────────────────
    def section_title(self, pdf, text) -> None:
        st = self._s("section_title")
        if pdf.get_y() > pdf.h - 60:
            pdf.add_page()
        pdf.ln(4)
        if st.get("mode") == "tabAbove":
            y0 = pdf.get_y()
            tab = st.get("tab", {"color": "lime", "w": 9, "h": 1.0, "radius": 0.5})
            pdf.set_fill_color(*resolve_color(tab.get("color", "lime"), pdf))
            pdf.rect(pdf.l_margin, y0, tab.get("w", 9), tab.get("h", 1.0),
                     style="F", round_corners=True, corner_radius=tab.get("radius", 0.5))
            pdf.set_y(y0 + 2.4)
        pdf._sf(13, "bold")
        pdf.set_text_color(*pdf.ink)
        pdf.cell(0, 8, text, new_x="LMARGIN", new_y="NEXT")
        band_w = pdf.w - pdf.l_margin - pdf.r_margin
        y = pdf.get_y()
        pdf.set_fill_color(*pdf.rule_soft)
        pdf.rect(pdf.l_margin, y + 0.4, band_w, st.get("rule_weight", 0.4), style="F")
        if st.get("mode") != "tabAbove":
            kl = st.get("keyline", {"color": "lime", "w": 22, "h": 1.2})
            pdf.set_fill_color(*resolve_color(kl.get("color", "lime"), pdf))
            pdf.rect(pdf.l_margin, y, kl.get("w", 22), kl.get("h", 1.2), style="F")
        pdf.ln(5)
        pdf.set_text_color(*TEXT)

    # ── numbered reference head (chip + kicker + title) ────────────────────
    def secondary_head(self, pdf, number, kicker, title, min_room=40.0,
                       badge=None, badge_color=None, badge_logo=None) -> None:
        sh = self._s("secondary_head")
        if pdf.page_no() == 0:
            pdf.add_page()
        elif pdf.get_y() > pdf.h - pdf.b_margin - min_room:
            pdf.add_page()
        else:
            pdf.ln(4)
        x0 = pdf.l_margin
        w = pdf.w - pdf.l_margin - pdf.r_margin
        y0 = pdf.get_y()
        chip = sh.get("chip", {})
        chip_sz = chip.get("size", 12.0)
        paint_shape(pdf, x0, y0, chip_sz, chip_sz, chip.get("shape"), chip.get("fill"))
        pdf.set_xy(x0, y0 + 2.6)
        pdf._sf(11, "bold")
        pdf.set_text_color(*resolve_color(chip.get("number_color", "ink"), pdf))
        pdf.cell(chip_sz, 7, number, align="C")
        tx = x0 + chip_sz + 5
        tw = w - chip_sz - 5
        self.eyebrow(pdf, tx, y0 + 0.5, kicker, resolve_color(sh.get("kicker_color", "primary"), pdf),
                     size=7.0, tracking=0.5, w=tw)
        if badge_logo:
            try:
                lw = 12.0
                pdf.image(io.BytesIO(badge_logo), x=x0 + w - lw, y=y0, w=lw, h=lw)
                tw -= lw + 3
                badge = None
            except Exception:
                badge_logo = None
        if badge:
            bc = badge_color or pdf.primary_color
            pdf._sf(8, "bold")
            bw = pdf.get_string_width(pdf._safe(badge)) + 5
            pdf.set_fill_color(*bc)
            pdf.rect(x0 + w - bw, y0 + 4.5, bw, 6.5, style="F",
                     round_corners=True, corner_radius=1.4)
            pdf.set_xy(x0 + w - bw, y0 + 5.0)
            pdf.set_text_color(*WHITE)
            pdf.cell(bw, 5.5, pdf._safe(badge), align="C")
            tw -= bw + 3
        pdf.set_xy(tx, y0 + 4.8)
        pdf._fit_font(pdf._safe(title), tw, 15, "bold")
        pdf.set_text_color(*resolve_color(sh.get("title_color", "ink"), pdf))
        pdf.cell(tw, 7, pdf._safe(title))
        ry = y0 + chip_sz + 2
        pdf.set_fill_color(*resolve_color(sh.get("rule_color", "rule_soft"), pdf))
        pdf.rect(x0, ry, w, sh.get("rule_weight", 0.4), style="F")
        pdf.set_y(ry + 4)
        pdf.set_text_color(*TEXT)

    # ── analytical chapter divider ─────────────────────────────────────────
    def section_divider(self, pdf, number, kicker, heading) -> None:
        dv = self._s("divider")
        if pdf.page_no() == 0:
            pdf.add_page()
        elif pdf.get_y() > pdf.t_margin + 2:
            pdf.add_page()
        x0 = pdf.l_margin
        w = pdf.w - pdf.l_margin - pdf.r_margin
        y0 = pdf.get_y() + 2
        if dv.get("style") == "editorial":
            H = dv.get("height", 30.0)
            num = dv.get("number", {"size": 34, "color": {"mix": ["lime", "white", 0.66]}})
            # The editorial style paints NO band — everything sits on the bare
            # page. A spec carried over from the banner style brings
            # `heading_color: white` with it and the chapter title disappears,
            # so every colour here is checked against the page before it is used.
            pdf.set_xy(x0, y0 + 2)
            pdf._sf(num.get("size", 34), "bold")
            pdf.set_text_color(*readable_on(resolve_color(num.get("color"), pdf),
                                            WHITE, blend(pdf.ink, WHITE, 0.55)))
            pdf.cell(26, 20, str(number), align="L")
            tx = x0 + 30
            self.eyebrow(pdf, tx, y0 + 4.5, kicker,
                         readable_on(resolve_color(dv.get("kicker_color", "lime"), pdf),
                                     WHITE, pdf.primary_color),
                         size=7.5, tracking=0.6, w=w - 30)
            pdf.set_xy(tx, y0 + 9.5)
            pdf._sf(dv.get("heading_size", 17), "bold")
            pdf.set_text_color(*readable_on(resolve_color(dv.get("heading_color", "ink"), pdf),
                                            WHITE, pdf.ink))
            pdf.cell(w - 30, 9, pdf._safe(heading))
            ry = y0 + H - 2
            pdf.set_fill_color(*resolve_color(dv.get("rule_color", "rule_soft"), pdf))
            pdf.rect(x0, ry, w, 0.4, style="F")
            pdf.set_fill_color(*resolve_color(dv.get("tick_color", "lime"), pdf))
            pdf.rect(x0, ry - 0.1, 26, 0.9, style="F", round_corners=True, corner_radius=0.4)
            pdf.set_y(y0 + H + 6)
            pdf.set_text_color(*TEXT)
            return
        # banner style
        H = dv.get("height", 30.0)
        _fill = dv.get("fill", {"type": "solid", "color": "ink"})
        paint_shape(pdf, x0, y0, w, H, dv.get("shape", {"kind": "chamfer", "c": 4.4, "q": 1.3, "r": 3.4}),
                    _fill)
        # Text here sits on the band, so contrast is checked against the band's
        # own colour (a gradient is judged on its first stop — close enough to
        # catch "invisible", which is all this guard is for).
        _band = resolve_color(_fill.get("color") if isinstance(_fill, dict) else _fill, pdf)
        if isinstance(_fill, dict) and _fill.get("stops"):
            try:
                _band = resolve_color(_fill["stops"][0].get("color"), pdf)
            except Exception:
                pass
        try:
            _var = int(str(number)) % 3
        except ValueError:
            _var = 0
        _watermark(pdf, x0, y0, w, H, "divider",
                   hex=(x0 + w - 30, y0 - 5, 20, WHITE, _var, 0.10)
                       if dv.get("watermark") == "hexCluster" else None)
        num = dv.get("number", {"size": 26, "color": "lime", "x": 9})
        pdf.set_xy(x0 + num.get("x", 9), y0 + 9)
        pdf._sf(num.get("size", 26), "bold")
        pdf.set_text_color(*readable_on(resolve_color(num.get("color", "lime"), pdf),
                                        _band, WHITE))
        pdf.cell(20, 12, str(number), align="L")
        if dv.get("vline"):
            pdf.set_fill_color(*resolve_color(dv.get("vline_color", {"mix": ["ink", "white", 0.30]}), pdf))
            pdf.rect(x0 + 31, y0 + 7, 0.5, H - 14, style="F")
        self.eyebrow(pdf, x0 + 37, y0 + 7.5, kicker,
                     readable_on(resolve_color(dv.get("kicker_color", "lime"), pdf), _band, WHITE),
                     size=7.0, tracking=0.6, w=w - 50)
        pdf.set_xy(x0 + 37, y0 + 12.5)
        pdf._sf(dv.get("heading_size", 16), "bold")
        pdf.set_text_color(*readable_on(resolve_color(dv.get("heading_color", "white"), pdf),
                                        _band, WHITE))
        pdf.cell(w - 50, 9, pdf._safe(heading))
        pdf.set_y(y0 + H + 6)
        pdf.set_text_color(*TEXT)

    # ── empty-space decoration ─────────────────────────────────────────────
    def decorate_void(self, pdf, variant=0, min_gap=44.0) -> None:
        # `_cover_pages`, not `_is_cover` — same reason as `footer()`: the void of
        # the page being LEFT is filled from inside `add_page()`, where the flag
        # already describes the cover about to be drawn. That is why the glossary
        # had to fill its own trailing void by hand.
        if pdf.page_no() in pdf._cover_pages:
            return
        y = pdf.get_y() + 4.0
        floor = pdf.h - 28.0
        gap = floor - y
        if gap < min_gap:
            return
        x0 = pdf.l_margin
        x1 = pdf.w - pdf.r_margin
        pool = getattr(pdf, "filler_image_list", None) or [
            b for b in (getattr(pdf, "cover_image_bytes", None),
                        getattr(pdf, "back_image_bytes", None)) if b]
        if gap >= self.EGREGIOUS_VOID and pool:
            filler = pool[pdf._void_photo_idx % len(pool)]
            if self.decorate_void_photo(pdf, x0, x1, y, floor, gap, filler):
                pdf._void_photo_idx += 1
                return
        deco = self._s("void").get("decoration", "hexCluster")
        # The empty-space watermark filler ("watermark" = image-only, "hexCluster"
        # = image if uploaded else the theme's drawn cluster) honours the single
        # surface gate. "accentKeyline" is a separate, non-watermark filler.
        wm = getattr(pdf, "watermark", None) or {}
        if deco in ("watermark", "hexCluster"):
            if "void" not in wm.get("surfaces", ()):
                return
            if wm.get("image") is not None:
                sc = min(gap * 0.62, 60.0)
                if sc >= 12:
                    _watermark(pdf, x0, floor - sc, x1 - x0, sc, "void")
                return
            if deco == "watermark":         # image-only filler, but no image loaded
                return
        try:
            if deco == "hexCluster":
                HEX_VEXT = 1.45
                sig = getattr(pdf, "cover_sigil_bytes", None)
                if sig:
                    from PIL import Image
                    iw, ih = Image.open(io.BytesIO(sig)).size
                    sh = min(gap * 0.92, 150.0)
                    sw = sh * iw / ih
                    with pdf.local_context(fill_opacity=0.07):
                        pdf.image(io.BytesIO(sig), x=x1 - sw * 0.60,
                                  y=y + (gap - sh) / 2.0, w=sw, h=sh)
                scale = min(gap / HEX_VEXT, 52.0)
                if scale >= 12:
                    _watermark(pdf, x0, floor - scale, scale, scale, "void",
                               hex=(x0 - scale * 0.22, floor - scale * HEX_VEXT,
                                    scale, pdf.primary_color, variant, 0.13))
                if gap > 120:
                    cxm = (x0 + x1) / 2
                    _stroke_chamfer(pdf, cxm - 10, y + gap * 0.28, 18, 18,
                                    pdf.primary_color, c=3.6, q=1.1, r=3.6,
                                    line_w=0.45, opacity=0.11)
                    _stroke_chamfer(pdf, cxm + 20, y + gap * 0.28 + 17, 11, 11,
                                    pdf.lime, c=2.2, q=0.7, r=2.2,
                                    line_w=0.45, opacity=0.18)
            elif deco == "accentKeyline":
                sig = getattr(pdf, "cover_sigil_bytes", None)
                if sig:
                    from PIL import Image
                    iw, ih = Image.open(io.BytesIO(sig)).size
                    sh = min(gap * 0.9, 140.0)
                    sw = sh * iw / ih
                    with pdf.local_context(fill_opacity=0.05):
                        pdf.image(io.BytesIO(sig), x=x1 - sw * 0.60,
                                  y=y + (gap - sh) / 2.0, w=sw, h=sh)
                ry = floor - 10.0
                pdf.set_fill_color(*pdf.rule_soft)
                pdf.rect(x0, ry, x1 - x0, 0.3, style="F")
                pdf.set_fill_color(*pdf.lime)
                pdf.rect(x0, ry - 0.1, 22, 0.8, style="F", round_corners=True, corner_radius=0.4)
        except Exception:
            pass

    def decorate_void_photo(self, pdf, x0, x1, y, floor, gap, filler) -> bool:
        ph = self._s("void").get("photo", {})
        tint_op = ph.get("tint_opacity", 0.30)
        wash_op = ph.get("wash_opacity", 0.34)
        top_rule = ph.get("top_rule", 1.5)
        try:
            pad_top = 13.0
            band_w = x1 - x0
            band_h = min(gap - pad_top, 104.0)
            if band_h < 52.0:
                return False
            by = floor - band_h
            _bx = (-0.6, 0.0, 0.6)[pdf.page_no() % 3]
            _by = (0.0, -0.5, 0.5)[(pdf.page_no() // 3) % 3]
            cropped = _cover_crop(filler, band_w / band_h, bias_x=_bx, bias_y=_by) or filler
            try:
                from PIL import Image
                _bim = Image.open(io.BytesIO(cropped)).convert("RGB")
                _buf = io.BytesIO(); _bim.save(_buf, "JPEG", quality=78, optimize=True)
                cropped = _buf.getvalue()
            except Exception:
                pass
            pdf.image(io.BytesIO(cropped), x=x0, y=by, w=band_w, h=band_h)
            tint = getattr(pdf, "cover_overlay_color", pdf.primary_color)
            with pdf.local_context(fill_opacity=tint_op):
                pdf.set_fill_color(*tint)
                pdf.rect(x0, by, band_w, band_h, style="F")
            with pdf.local_context(fill_opacity=wash_op):
                pdf.set_fill_color(*pdf.ink)
                pdf.rect(x0, floor - 16.0, band_w, 16.0, style="F")
            pdf.set_fill_color(*pdf.lime)
            pdf.rect(x0, by, band_w, top_rule, style="F")
            sig = getattr(pdf, "cover_sigil_bytes", None)
            if sig:
                from PIL import Image
                iw, ih = Image.open(io.BytesIO(sig)).size
                sh = min(band_h * 0.42, 26.0)
                sw = sh * iw / ih
                with pdf.local_context(fill_opacity=0.55):
                    pdf.image(io.BytesIO(sig), x=x1 - sw - 6.0,
                              y=floor - sh - 3.5, w=sw, h=sh)
            return True
        except Exception:
            return False

    # ── cover (summary page) brand graphics ────────────────────────────────
    def cover_masthead(self, pdf, x0, y_m, W, MH) -> None:
        cm = self._s("cover_masthead")
        paint_shape(pdf, x0, y_m, W, MH,
                    cm.get("shape", {"kind": "chamfer", "c": 7.5, "q": 2.0, "r": 5.0}),
                    cm.get("fill", {"type": "solid", "color": "ink"}))
        _watermark(pdf, x0, y_m, W, MH, "masthead",
                   hex=(x0 + W - 42, y_m - 6, 30, WHITE, 0, 0.12)
                       if cm.get("watermark") == "hexCluster" else None)
        # No `accent_rule`: the coloured bar it drew along the masthead's bottom
        # edge read as a stray solid border (especially over a gradient fill) and
        # was unwanted. The spec key is ignored if a saved theme still carries it.

    def cover_left_void_fill(self, pdf, x0, sc, bottom) -> None:
        dec = self._s("cover_left_void").get("decoration", "hexCluster")
        wm = getattr(pdf, "watermark", None) or {}
        if dec in ("watermark", "hexCluster"):
            if "cover" not in wm.get("surfaces", ()):
                return
            if wm.get("image") is not None:
                _watermark(pdf, x0, bottom - sc, sc, sc, "cover")
                return
            if dec == "hexCluster":
                _watermark(pdf, x0, bottom - sc, sc, sc, "cover",
                           hex=(x0 - sc * 0.2, bottom - sc, sc, pdf.primary_color, 1, 0.13))
            return
        if dec == "accentKeyline":
            ry = bottom - 6.0
            pdf.set_fill_color(*pdf.lime)
            pdf.rect(x0, ry, min(sc, 40.0), 0.9, style="F",
                     round_corners=True, corner_radius=0.4)


# ── built-in theme specs ──────────────────────────────────────────────────────
HEXAGON_SPEC = {
    "name": "Hexagon",
    "header": {"rule": {"color": "primary", "weight": 0.6, "y": 16.5}},
    "section_title": {"mode": "over", "rule_weight": 0.4,
                      "keyline": {"color": "lime", "w": 22, "h": 1.2}},
    "secondary_head": {
        "chip": {"size": 12.0, "shape": {"kind": "chamfer", "c": 2.4, "q": 0.9, "r": 2.4},
                 "fill": {"type": "solid", "color": "lime"}, "number_color": "ink"},
        "kicker_color": "primary", "title_color": "ink",
        "rule_color": "rule_soft", "rule_weight": 0.4},
    "divider": {"style": "banner", "height": 30.0,
                "shape": {"kind": "chamfer", "c": 4.4, "q": 1.3, "r": 3.4},
                "fill": {"type": "solid", "color": "ink"}, "watermark": "hexCluster",
                "number": {"size": 26, "color": "lime", "x": 9},
                "vline": True, "vline_color": {"mix": ["ink", "white", 0.30]},
                "kicker_color": "lime", "heading_color": "white", "heading_size": 16},
    "void": {"decoration": "hexCluster",
             "photo": {"tint_opacity": 0.30, "wash_opacity": 0.34, "top_rule": 1.5}},
    "cover_masthead": {"shape": {"kind": "chamfer", "c": 7.5, "q": 2.0, "r": 5.0},
                       "fill": {"type": "solid", "color": "ink"}, "watermark": "hexCluster"},
    "cover_left_void": {"decoration": "hexCluster"},
}

MERCATOR_SPEC = {
    "name": "Mercator",
    "header": {"rule": {"color": "rule_soft", "weight": 0.3, "y": 16.5},
               "tick": {"color": "lime", "w": 15, "h": 0.8, "y": 16.1, "radius": 0.4}},
    "section_title": {"mode": "tabAbove", "rule_weight": 0.3,
                      "tab": {"color": "lime", "w": 9, "h": 1.0, "radius": 0.5}},
    "secondary_head": {
        "chip": {"size": 12.0, "shape": {"kind": "rounded", "radius": 2.6},
                 "fill": {"type": "solid", "color": {"mix": ["lime", "white", 0.86]}},
                 "number_color": "lime"},
        "kicker_color": "lime", "title_color": "ink",
        "rule_color": "rule_soft", "rule_weight": 0.3},
    "divider": {"style": "editorial", "height": 30.0,
                "number": {"size": 34, "color": {"mix": ["lime", "white", 0.66]}},
                "kicker_color": "lime", "heading_color": "ink", "heading_size": 17,
                "rule_color": "rule_soft", "tick_color": "lime"},
    "void": {"decoration": "accentKeyline",
             "photo": {"tint_opacity": 0.28, "wash_opacity": 0.32, "top_rule": 1.2}},
    "cover_masthead": {"shape": {"kind": "rounded", "radius": 3.0},
                       "fill": {"type": "solid", "color": "ink"}},
    "cover_left_void": {"decoration": "accentKeyline"},
}


# ── theme registry ────────────────────────────────────────────────────────────
# resolve_theme(name_or_spec) → a SpecTheme. `name_or_spec` is either a built-in
# name ("hexagon"/"cadiem"/"mercator"), an inline spec dict (optionally with a
# "base" naming a built-in to inherit-and-override), or None. Unknown/absent →
# DEFAULT_THEME. CADIEM embeds its hexagon spec in its branding config.
DEFAULT_THEME = "mercator"
_BUILTIN_SPECS: dict[str, dict] = {
    "hexagon":  HEXAGON_SPEC,
    "cadiem":   HEXAGON_SPEC,   # alias
    "mercator": MERCATOR_SPEC,
}


def _merge_spec(base: dict, over: dict) -> dict:
    """Deep-merge `over` onto a copy of `base` (dicts merge; other values replace)."""
    out = dict(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge_spec(out[k], v)
        else:
            out[k] = v
    return out


def register_theme(name: str, spec: dict) -> None:
    """Register a named built-in theme spec (so `resolve_theme(name)` finds it)."""
    _BUILTIN_SPECS[name.strip().lower()] = spec


def resolve_theme(name_or_spec) -> ReportTheme:
    if isinstance(name_or_spec, dict):
        base = _BUILTIN_SPECS.get(str(name_or_spec.get("base", "")).strip().lower())
        spec = _merge_spec(base, name_or_spec) if base else name_or_spec
        return SpecTheme(spec)
    key = (name_or_spec or "").strip().lower()
    return SpecTheme(_BUILTIN_SPECS.get(key) or _BUILTIN_SPECS[DEFAULT_THEME])


def known_themes() -> list[str]:
    return sorted(_BUILTIN_SPECS)
