"""
reportkit.cover — full-bleed pages: the painting spine behind covers and back
pages.

A cover is the one page in a report where the brand's imagery is the content.
Everything a host has to get right to paint one lives here, because each step
fails *silently* when it is done in the wrong order or skipped:

    open the page      auto page break off, `_is_cover` raised BEFORE `add_page`
                       (the header hook runs for the new page), then the page
                       number registered in `_cover_pages` — which is what the
                       footer and the void decorator actually test.
    paint              the theme's `cover.fill` — solid, linear or radial —
                       under everything.
    the photograph     aspect-cropped to the page, drawn opaque, which HIDES the
                       fill entirely.
    the overlay        so re-tints the photo with that same fill at the
                       configured opacity. Skip it and a brand's cover is
                       whatever colours its photograph happened to contain.
    close              lower `_is_cover`.

`full_bleed()` is that sequence as a context manager, so a caller writes the
content and cannot get the frame wrong. The individual primitives are exported
too — a host with its own cover layout still wants the same painting.

Nothing here decides *layout*. Where a title sits, what the metric strip says,
which copy appears — that is the host's, and the primitives take coordinates.
"""
from __future__ import annotations

import io
from contextlib import contextmanager

from reportkit.images import cover_crop, logo_aspect as _logo_aspect
from reportkit.theme import paint_shape, resolve_color


#: Muted sub-line colour on a dark full bleed (underlyings line, metric labels,
#: the copyright rule). A literal rather than a token: it is a fixed mint that
#: reads against any brand primary, and deriving it would move every cover.
MINT = (159, 196, 179)


def _overlay_color(pdf) -> tuple:
    """The flat tint for a cover photo, never None.

    `getattr(pdf, "cover_overlay_color", pdf.primary_color)` reads as safe and
    is not: the attribute is DECLARED on every document, defaulting to None, so
    the default never fires and `set_fill_color(*None)` raises out of the middle
    of a half-painted cover. `apply_brand` happens to fill it in, which is why
    the hole only opens for a document driven by the primitives directly.
    """
    return getattr(pdf, "cover_overlay_color", None) or pdf.primary_color


def cover_fill(pdf):
    """The active theme's `cover.fill`, or None when it declares nothing."""
    spec = getattr(getattr(pdf, "theme", None), "spec", None)
    if isinstance(spec, dict):
        return (spec.get("cover") or {}).get("fill")
    return None


def paint_background(pdf, w: float, h: float) -> None:
    """Fill a full-bleed page with the theme's cover background — a solid brand
    colour by default, or a gradient when the active theme spec sets
    `cover.fill`. Falls back to solid primary if anything is off."""
    fill = cover_fill(pdf)
    try:
        if fill and fill.get("type") in ("linear", "radial"):
            paint_shape(pdf, 0, 0, w, h, {"kind": "square"}, fill)
            return
        if fill and fill.get("type") == "solid":
            pdf.set_fill_color(*resolve_color(fill.get("color", "primary"), pdf))
            pdf.rect(0, 0, w, h, style="F")
            return
    except Exception:
        pass
    pdf.set_fill_color(*pdf.primary_color)
    pdf.rect(0, 0, w, h, style="F")


def paint_overlay(pdf, w: float, h: float) -> None:
    """Tint a full-bleed photo with the cover's colour identity.

    A cover photo is drawn opaque over the whole page, so it completely hides
    the background painted underneath — which means the tint drawn ON TOP of the
    photo is the only thing that carries the cover's colour. That tint IS the
    theme's cover-background fill at the configured opacity: a gradient tints as
    a gradient, a radial as a radial, a solid as that solid colour. The photo
    and the themed background compose (photo shows through at opacity < 1)
    instead of the photo throwing the fill away.

    There is deliberately a SINGLE source for the cover's colour — the theme's
    `cover.fill`. A brand's flat `cover_overlay_color` is only the fallback tint
    when the theme declares no cover fill at all, so older configs still render
    and a themeless brand keeps a legible primary wash over its photo.
    """
    op = getattr(pdf, "cover_overlay_opacity", 0.0)
    if not op or op <= 0:
        return
    fill = cover_fill(pdf)
    if isinstance(fill, dict) and fill.get("type") in ("linear", "radial"):
        try:
            paint_shape(pdf, 0, 0, w, h, {"kind": "square"}, fill, opacity=op)
            return
        except Exception:
            pass
    if isinstance(fill, dict) and fill.get("type") == "solid":
        try:
            pdf.set_fill_color(*resolve_color(fill.get("color", "primary"), pdf))
        except Exception:
            pdf.set_fill_color(*_overlay_color(pdf))
    else:
        pdf.set_fill_color(*_overlay_color(pdf))
    try:
        with pdf.local_context(fill_opacity=op):
            pdf.rect(0, 0, w, h, style="F")
    except Exception:
        pass


def draw_logo_fit(pdf, logo_b, x: float, y: float, max_h: float, max_w: float,
                  *, cover: bool = False) -> None:
    """Draw a logo at (x, y) fit inside (max_w, max_h) preserving aspect — never
    stretched. The cover wordmark uses its OWN aspect (cover_logo_aspect), not
    the header logo's, so a wide cover logo isn't squished into the header's
    box."""
    if not logo_b:
        return
    if cover and getattr(pdf, "cover_logo_bytes", None):
        asp = getattr(pdf, "cover_logo_aspect", None) or pdf.firm_logo_aspect
    else:
        asp = pdf.firm_logo_aspect
    asp = asp or 1.0
    h, w = max_h, max_h * asp
    if w > max_w:
        w, h = max_w, (max_w / asp if asp else max_h)
    try:
        pdf.image(io.BytesIO(logo_b), x=x, y=y, w=w, h=h)
    except Exception:
        pass


def draw_sigil(pdf, w: float, h: float) -> None:
    """The brand's emblem, bleeding off an edge as a faint decorative motif.

    Size / position / opacity are brand-overridable as percentages of the page;
    absent values reproduce a top-right bleed at 0.22 opacity. Silent when the
    brand supplies no sigil — it is decoration, and a cover without one is a
    perfectly good cover.
    """
    sig_b = getattr(pdf, "cover_sigil_bytes", None)
    if not sig_b:
        return
    try:
        _ssz = getattr(pdf, "cover_sigil_size_pct", None)
        sw = w * (_ssz / 100.0) if _ssz is not None else w * 0.58
        sh = sw * _logo_aspect(sig_b, default=1.0)
        _sx = getattr(pdf, "cover_sigil_x_pct", None)
        _sy = getattr(pdf, "cover_sigil_y_pct", None)
        sx = w * (_sx / 100.0) if _sx is not None else (w - sw * 0.62)
        sy = h * (_sy / 100.0) if _sy is not None else (-sh * 0.30)
        _sop = getattr(pdf, "cover_sigil_opacity", None)
        op = _sop if _sop is not None else 0.22
        with pdf.local_context(fill_opacity=op):
            pdf.image(io.BytesIO(sig_b), x=sx, y=sy, w=sw, h=sh)
    except Exception:
        pass


def draw_cover_logo(pdf, w: float, h: float) -> None:
    """The cover wordmark, in the brand's chosen place.

    Prefers a white-knockout `cover_logo_bytes` over the header logo, since the
    cover is dark. Position is a percentage of the page and size a percentage of
    its WIDTH, with the max height held at the original 16:90 box ratio so an
    unset size reproduces a 16x90 mm fit box exactly.
    """
    logo_b = getattr(pdf, "cover_logo_bytes", None) or pdf.firm_logo_bytes
    _lsz = getattr(pdf, "cover_logo_size_pct", None)
    max_w = w * (_lsz / 100.0) if _lsz is not None else 90.0
    max_h = max_w * (16.0 / 90.0)
    _lx = getattr(pdf, "cover_logo_x_pct", None)
    _ly = getattr(pdf, "cover_logo_y_pct", None)
    x = w * (_lx / 100.0) if _lx is not None else pdf.l_margin
    y = h * (_ly / 100.0) if _ly is not None else h * 0.07
    draw_logo_fit(pdf, logo_b, x, y, max_h, max_w, cover=True)


def left_photo(pdf, x0: float, top: float, w: float, bottom: float,
               img: bytes) -> bool:
    """Fill a tall, narrow column with a brand photo, banded and tinted.

    For a page whose left column would otherwise sit half empty. Brand tint +
    accent rule + a corner sigil, so it reads as part of the document rather
    than as a stock photograph dropped in. Returns True on success; False means
    the caller should fall back to a lighter composition — too little room, or
    an image that would not decode.
    """
    try:
        avail = bottom - top
        if avail < 58.0 or w < 40.0:
            return False
        cropped = cover_crop(img, w / avail) or img
        # Re-encode as JPEG so a photo on the cover doesn't bloat the PDF.
        try:
            from PIL import Image
            _im = Image.open(io.BytesIO(cropped)).convert("RGB")
            _buf = io.BytesIO(); _im.save(_buf, "JPEG", quality=80, optimize=True)
            cropped = _buf.getvalue()
        except Exception:
            pass
        pdf.image(io.BytesIO(cropped), x=x0, y=top, w=w, h=avail)
        # Light brand tint so the photo harmonises with the palette without
        # hiding it — meant to read as an image, not a colour block.
        tint = _overlay_color(pdf)
        with pdf.local_context(fill_opacity=0.26):
            pdf.set_fill_color(*tint)
            pdf.rect(x0, top, w, avail, style="F")
        # Darker brand wash along the bottom edge grounds the band + corner sigil.
        with pdf.local_context(fill_opacity=0.34):
            pdf.set_fill_color(*pdf.ink)
            pdf.rect(x0, bottom - 18.0, w, 18.0, style="F")
        # Accent rule across the top edge — the brand's signature line.
        pdf.set_fill_color(*pdf.lime)
        pdf.rect(x0, top, w, 1.5, style="F")
        # White-knockout sigil tucked into the bottom-left corner.
        sig = getattr(pdf, "cover_sigil_bytes", None)
        if sig:
            from PIL import Image
            iw, ih = Image.open(io.BytesIO(sig)).size
            sh = min(avail * 0.30, 24.0); sw = sh * iw / ih
            with pdf.local_context(fill_opacity=0.55):
                pdf.image(io.BytesIO(sig), x=x0 + 5.0, y=bottom - sh - 4.0,
                          w=sw, h=sh)
        return True
    except Exception:
        return False


@contextmanager
def full_bleed(pdf, image: bytes | None = None):
    """Open a painted full-bleed page; yield `(w, h)`; close it.

    The ordering is the whole point, and every step of it is a bug someone has
    already shipped:

    * `_is_cover` is raised BEFORE `add_page`, because fpdf2 calls the new
      page's `header()` from inside it — the flag is how the theme knows not to
      draw a running header on a cover.
    * the page number goes into `_cover_pages` AFTER, because that is the set
      the footer and the void decorator consult. They must key on the page
      NUMBER: `add_page` renders the *closing* page's footer, so a flag
      describing the page about to be drawn answers the wrong question.
    * the overlay runs whenever an image was offered, even if drawing it raised
      — a half-drawn photo still needs its tint, and a cover that silently loses
      its colour is worse than one that loses its photograph.
    """
    pdf.set_auto_page_break(auto=False)
    pdf._is_cover = True
    pdf.add_page()
    pdf._cover_pages.add(pdf.page_no())
    w, h = pdf.w, pdf.h
    paint_background(pdf, w, h)
    if image:
        try:
            pdf.image(io.BytesIO(cover_crop(image, w / h)), x=0, y=0, w=w, h=h)
        except Exception:
            pass
        paint_overlay(pdf, w, h)
    try:
        yield w, h
    finally:
        pdf._is_cover = False
