"""
reportkit.testing — deterministic inputs for rendering a document under test.

A PDF is only diffable if it is reproducible, and the two things that usually
are not are FIGURES (a real chart means Kaleido, a headless Chrome, and
antialiasing that differs between machines) and IMAGES (a photograph is a
licensed asset that does not belong in a test suite).

So: `stub_figures()` intercepts the rasteriser and returns a flat block **at
exactly the pixel size the call site asked for** — size fidelity is the whole
point, because a figure's aspect ratio decides where the page breaks and a stub
of the wrong shape silently guards a different document. `flat_png` /
`gradient_png` generate deterministic stand-ins from a seed with no numpy and
no assets.

`sample_document()` is a report that exercises every block the package draws,
including the awkward ones — a table long enough to split, a heading close
enough to the bottom margin to be at risk, a full-bleed cover and back page.
It is what this package's own golden renders, and it doubles as a smoke test
for a host: if your theme survives it, it survives a real report.

Import cost is deliberately low (Pillow only), so a consumer can use these in
their own suite without taking on the charts extra.
"""
from __future__ import annotations

import hashlib
import io
from contextlib import contextmanager


# ── deterministic images ─────────────────────────────────────────────────────

def flat_png(width: int, height: int, rgb: tuple = (206, 212, 218)) -> bytes:
    """A flat block at EXACTLY the requested pixel size.

    The size is the contract. `figure()` derives its drawn height from the
    image's aspect ratio, so a stub that rounds or squares off moves page
    breaks and the golden then guards a document nobody ships.
    """
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (max(1, int(width)), max(1, int(height))), rgb).save(buf, "PNG")
    return buf.getvalue()


def gradient_png(width: int, height: int, seed: int = 1) -> bytes:
    """A deterministic soft gradient — a stand-in for a photograph.

    Seeded by hand rather than by numpy: this module is imported by consumers
    who may not have it, and a 40-line LCG costs less than a dependency.
    """
    from PIL import Image
    w, h = max(1, int(width)), max(1, int(height))
    state = (seed * 1103515245 + 12345) & 0x7FFFFFFF
    px = bytearray(w * h * 3)
    for y in range(h):
        for x in range(w):
            state = (state * 1103515245 + 12345) & 0x7FFFFFFF
            jitter = (state >> 16) % 13 - 6
            base = int(255 * x / max(1, w - 1))
            i = (y * w + x) * 3
            for c in range(3):
                px[i + c] = max(0, min(255, base + jitter + 8 * c))
    buf = io.BytesIO()
    Image.frombytes("RGB", (w, h), bytes(px)).save(buf, "PNG")
    return buf.getvalue()


def labelled_png(width: int, height: int, label: str,
                 rgb: tuple = (18, 62, 64)) -> bytes:
    """A bordered, labelled block — a stand-in for a logo or wordmark."""
    from PIL import Image, ImageDraw
    w, h = max(1, int(width)), max(1, int(height))
    im = Image.new("RGB", (w, h), rgb)
    d = ImageDraw.Draw(im)
    inv = tuple(255 - c for c in rgb)
    d.rectangle([2, 2, w - 3, h - 3], outline=inv, width=3)
    d.text((10, max(0, h // 2 - 6)), label, fill=inv)
    buf = io.BytesIO(); im.save(buf, "PNG")
    return buf.getvalue()


# ── figure interception ──────────────────────────────────────────────────────

@contextmanager
def stub_figures(factory=flat_png):
    """Replace figure rasterisation for the duration of the block.

    Uses the package's own `FIG_HOOK` ContextVar rather than monkeypatching, so
    a test exercises the real interception path — the same one a host's preview
    mode uses — instead of a seam that only exists under test.
    """
    from reportkit import charts
    token = charts.FIG_HOOK.set(lambda fig, w, h, *colors: factory(w, h))
    try:
        yield
    finally:
        charts.FIG_HOOK.reset(token)


# ── rasterising ──────────────────────────────────────────────────────────────

def rasterise(pdf_bytes: bytes, dpi: int = 110):
    """PDF → `[(sha256, png_bytes)]`, one per page.

    Prefers pypdfium2 and falls back to PyMuPDF. The two do NOT agree pixel for
    pixel — they antialias differently, so a digest taken with one and compared
    against the other reports every page as changed, every glyph edge lighting
    up. Compare like with like, and raise rather than guess if neither is here.
    """
    try:
        import pypdfium2 as pdfium
    except ImportError:
        pass
    else:
        out = []
        for page in pdfium.PdfDocument(pdf_bytes):
            pil = page.render(scale=dpi / 72.0).to_pil().convert("RGB")
            buf = io.BytesIO(); pil.save(buf, "PNG")
            out.append((hashlib.sha256(pil.tobytes()).hexdigest(), buf.getvalue()))
        return out
    try:
        import fitz
    except ImportError:
        raise RuntimeError(
            "no rasteriser: install pypdfium2 (preferred) or PyMuPDF") from None
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    out = []
    for page in doc:
        pix = page.get_pixmap(dpi=dpi)
        out.append((hashlib.sha256(pix.samples).hexdigest(), pix.tobytes("png")))
    doc.close()
    return out


# ── a document that exercises the package ────────────────────────────────────

SAMPLE_BRAND = {
    "firm_name": "Meridian Partners",
    "primary_color": "#0B3B2E", "accent_color": "#20948A",
    "section_rule_color": "#A3C83F", "panel_color": "#ECF1F6",
    "report_title": "Quarterly Review",
    "website": "meridian.example", "contact": "ir@meridian.example",
    "footer_note": "Confidential — not for distribution",
    "disclaimer_body": ("This document is provided for information only.\n\n"
                        "Past performance is not indicative of future results."),
    "cover_overlay_opacity": 0.62,
}


def sample_brand(theme: str | None = None, *, imagery: bool = True) -> dict:
    """A brand config with generated imagery. `imagery=False` exercises the
    themes' drawn fallbacks, which are otherwise unreachable in a fixture that
    always supplies a photograph."""
    import base64
    cfg = dict(SAMPLE_BRAND)
    if theme:
        cfg["report_theme"] = theme
    b64 = lambda b: base64.b64encode(b).decode()          # noqa: E731
    cfg["logo_base64"] = b64(labelled_png(320, 96, "LOGO"))
    cfg["cover_logo_base64"] = b64(labelled_png(560, 120, "COVER", (255, 255, 255)))
    if imagery:
        cfg["cover_sigil_base64"] = b64(labelled_png(200, 200, "S", (255, 255, 255)))
        cfg["cover_image_base64"] = b64(gradient_png(900, 600, 11))
        cfg["back_image_base64"] = b64(gradient_png(900, 600, 29))
        cfg["filler_images_base64"] = [b64(gradient_png(700, 460, 41)),
                                       b64(gradient_png(700, 460, 53))]
        cfg["watermark_base64"] = b64(labelled_png(300, 300, "WM", (255, 255, 255)))
    return cfg


#: A table long enough to split across pages, which is the case `_table_room`
#: exists for — and the size band (roughly 16–29 rows) where a capped estimate
#: used to orphan the heading it was reserving room for.
LONG_TABLE = [[f"Position {i:02d}", f"{i * 3.1:.1f}%", f"{100 - i * 2:.2f}",
               "Yes" if i % 3 else "No"] for i in range(1, 27)]


def sample_document(theme: str | None = None, *, imagery: bool = True,
                    font_dir=None):
    """Build a report that touches every block, and return the PDF bytes.

    Call inside `stub_figures()` — it draws figures, and without the hook it
    would want a real rasteriser.
    """
    from pathlib import Path

    import reportkit.branding as branding
    import reportkit.outline as outline
    from reportkit.document import ReportDocument, _table_room

    if font_dir is None:
        font_dir = Path(__file__).resolve().parent / "fonts"

    brand = branding.resolve(sample_brand(theme, imagery=imagery),
                             default_firm_name="Meridian Partners")
    pdf = ReportDocument(brand=brand, font_dir=font_dir, doc_ref="SAMPLE-001")
    pdf.apply_brand(brand, font_dir=font_dir)

    order = ("overview", "holdings", "risk")
    nums = outline.plan_chapters({k: True for k in order}, order)
    pdf.chapter_nums = nums

    # ── cover ────────────────────────────────────────────────────────────
    with pdf.full_bleed_page(pdf.cover_image_bytes) as (w, h):
        pdf.cover_sigil()
        pdf.cover_logo()
        pdf._eyebrow(pdf.l_margin, h * 0.42, "QUARTERLY REVIEW",
                     pdf.section_rule_color, size=11.0, tracking=1.6,
                     w=w - 2 * pdf.l_margin)
        pdf.set_xy(pdf.l_margin, h * 0.46)
        pdf._sf(34, "bold"); pdf.set_text_color(255, 255, 255)
        pdf.multi_cell(w - 2 * pdf.l_margin, 14, "Meridian Balanced Fund")

    # ── contents ─────────────────────────────────────────────────────────
    pdf.add_page()
    pdf.section_title(pdf.t("in_this_report"))
    groups = [
        ("Overview", nums["overview"], ["Summary", "Commentary"]),
        ("Holdings", nums["holdings"], ["Positions", "Concentration"]),
        ("Risk", nums["risk"], ["Exposures"]),
        (None, None, [(pdf.t("glossary_title"), None),
                      (pdf.t("disclaimer_title"), None)]),
    ]
    groups, row_h, gap = outline.shed_to_fit(groups, avail=pdf.h - 60.0 - pdf.get_y())
    outline.contents_list(pdf, groups, x=pdf.l_margin, y=pdf.get_y() + 4,
                          w=pdf.w - 2 * pdf.l_margin, row_h=row_h, gap=gap)

    # ── numbered reference head + the blocks ─────────────────────────────
    pdf.add_page()
    pdf.secondary_head(nums["overview"], "OVERVIEW", "Summary")
    pdf.metric_band([("Net return", "8.4%"), ("Volatility", "11.2%"),
                     ("Sharpe", "0.74"), ("Max drawdown", "-6.1%")])
    pdf.body("A short standing paragraph, so the body style is in the diff and "
             "the blocks below start from a realistic cursor position.")
    pdf.bullet("Bulleted lines have their own indent and marker.")
    pdf.bullet("Two of them, so the spacing between is guarded too.")
    pdf.kv_table([("Inception", "2019-04-01"), ("Base currency", "USD"),
                  ("Benchmark", "60/40")])
    pdf.callout("Note", "A callout wraps its own box and must not straddle a "
                        "page break.")
    pdf.figure(flat_png(900, 500), "Cumulative return", "Meridian, monthly")

    # ── the pagination case ──────────────────────────────────────────────
    # A heading immediately followed by a table too long to fit under it. This
    # is what `_table_room` is for, and getting it wrong strands the heading on
    # a page the table has left.
    #
    # `min_room=_table_room(...)` is the documented call-site contract, and
    # passing it here is the point: without it this sample takes `subsection`'s
    # 27mm default, never enters the reservation chain, and the pixel golden
    # renders identically to one built with `table_room` rebound to *raise*.
    pdf.section_divider(nums["holdings"], "HOLDINGS", "What we own")
    pdf.subsection("Positions", min_room=_table_room(len(LONG_TABLE)))
    pdf.data_table(["Name", "Weight", "Price", "Held"], LONG_TABLE)
    pdf.subsection("Concentration", min_room=_table_room(2))
    pdf.data_table(["Bucket", "Weight"], [["Top 5", "31%"], ["Top 10", "48%"]])

    # The logo-row variant: 110 lines of public drawing code that no test in
    # this package reached before it appeared here.
    pdf.subsection("By holding", min_room=_table_room(3, row_h=10.0))
    pdf.logo_row_table(["Name", "Weight", "Return"],
                       [["Alpha Corp", "12.0%", "+4.1%"],
                        ["Beta SA", "9.5%", "-1.2%"],
                        ["Gamma Inc", "7.25%", "+8.8%"]],
                       {"Alpha Corp": labelled_png(64, 64, "A"),
                        "Beta SA": None,          # the missing-logo branch
                        "Gamma Inc": labelled_png(64, 64, "G")})

    pdf.section_divider(nums["risk"], "RISK", "Exposures")
    pdf.subsection("By factor", min_room=_table_room(2))
    pdf.data_table(["Factor", "Beta"], [["Equity", "0.61"], ["Rates", "-0.12"]])

    # ── back page ────────────────────────────────────────────────────────
    with pdf.full_bleed_page(pdf.back_image_bytes) as (w, h):
        pdf.draw_logo_fit(pdf.cover_logo_bytes or pdf.firm_logo_bytes,
                          pdf.l_margin, 15, 12.0, 58.0, cover=True)
        pdf.set_xy(pdf.l_margin, 45)
        pdf._sf(16, "bold"); pdf.set_text_color(255, 255, 255)
        pdf.cell(0, 8, pdf.t("disclaimer_title"), new_x="LMARGIN", new_y="NEXT")
        pdf.set_xy(pdf.l_margin, 58)
        pdf._sf(8, "regular"); pdf.set_text_color(255, 255, 255)
        pdf.multi_cell(w - 2 * pdf.l_margin, 4.2, pdf.disclaimer_body, align="J")

    return bytes(pdf.output())
