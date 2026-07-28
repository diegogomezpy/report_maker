"""
reportkit.branding — resolving a brand config into a document's identity.

A brand arrives as a dict: colours as hex strings, a logo from one of three
places, copy overrides per language, fonts, cover imagery. This turns that into
the palette, bytes and strings a `ReportDocument` needs, and it is deliberately
forgiving — a branding config is written by a person and often uploaded through
a UI, so a typo should cost you a colour, not the report.

Two asymmetries here are deliberate:

* `hex_to_rgb` RAISES on a malformed value; `branding_color` catches that and
  falls back to the CALLER's default with a warning. Merging them would repaint
  a bad `primary_color` to a generic slate rather than the brand's own default.
* `load_logo` ignores `logo_file` unless the host passes a `root` to resolve
  inside. A library cannot know which directory is legitimate, and an
  unconstrained path here is an arbitrary-file-read primitive whose payload ends
  up embedded in a PDF the requester downloads.
"""
from __future__ import annotations

import base64
import warnings

from reportkit.images import (fetch_image_bytes, read_local_image,
                              resolve_within, to_embeddable_png)

#: Fallback palette for a brand that supplies nothing.
DEFAULT_PRIMARY   = (26, 46, 74)
DEFAULT_ACCENT    = (37, 99, 235)
DEFAULT_SECONDARY = (198, 148, 38)

#: Keys reportkit itself understands. A host extends this via
#: `validate_branding(cfg, extra_keys=...)` rather than editing it.
KNOWN_KEYS = {
    "firm_name", "primary_color", "accent_color", "chart_secondary_color",
    "logo_file", "logo_base64", "logo_url",
    "report_title", "website", "contact", "footer_note",
    "section_rule_color",   # NEW — color of the rule drawn under section titles
    "panel_color",          # NEW — fill of the cover sidebar + figure/callout/issuer cards
    "sidebar_bar_color",    # NEW — solid bar across the top of the cover sidebar
    "disclaimer_body",      # NEW — overrides the full disclaimer body text
    "cover_logo_base64",    # NEW — white knockout logo for the full-bleed cover
    "cover_sigil_base64",   # NEW — optional emblem/sigil shown on the cover (≠ wordmark)
    # NEW — cover logo / emblem placement, all % of page (absent ⇒ theme default):
    "cover_logo_x_pct", "cover_logo_y_pct", "cover_logo_size_pct",
    "cover_sigil_x_pct", "cover_sigil_y_pct", "cover_sigil_size_pct",
    "cover_sigil_opacity",  # 0..1 opacity of the cover emblem (absent ⇒ 0.22)
    "watermark",            # NEW — unified watermark: {image_base64, opacity, scale, anchor, surfaces}
    # Legacy flat watermark_* keys — still honoured by resolve_watermark so older
    # configs load without a spurious "unrecognised keys" warning:
    "watermark_base64", "watermark_enabled", "watermark_opacity", "watermark_scale",
    "watermark_inset", "watermark_anchor", "watermark_places",
    "cover_image_base64",   # NEW — optional full-bleed cover background photo
    "back_image_base64",    # NEW — optional full-bleed photo for the disclaimer back page
    "filler_images_base64", # NEW — pool of report photos (cover/back fallback + void-filler bands cycle through it)
    "cover_overlay_color",  # NEW — colour of the overlay drawn over the cover/back photo
    "cover_overlay_opacity",# NEW — 0..1 opacity of that overlay
    "title_font", "body_font",  # NEW — custom report fonts (see _register_brand_fonts)
    "title_font_files", "body_font_files",  # NEW — embedded {Style: base64 TTF} so
                                            # fonts travel with an uploaded config
    # NEW — chart/graph styling (see charts.set_chart_options / CHART_OPTION_DEFAULTS)
    "chart_bg_color", "chart_grid_color", "chart_axis_color", "chart_label_color",
    "chart_text_color", "chart_font_size", "chart_series_colors",
    "chart_band_opacity", "chart_line_width",
    "report_theme",         # NEW — visual-identity theme name (pdf_theme.resolve_theme);
                            # e.g. "cadiem" (hexagon) or "mercator" (default). Absent
                            # / unknown falls back to the default theme.
}


def hex_to_rgb(hex_str: str) -> tuple[int, int, int]:
    """Convert '#RGB' or '#RRGGBB' to an (R, G, B) integer tuple. Raises ValueError
    on anything that is not a clean 3- or 6-digit hex string."""
    h = hex_str.strip().lstrip("#")
    if len(h) == 3:
        h = "".join(ch * 2 for ch in h)
    if len(h) != 6:
        raise ValueError(f"not a 6-digit hex colour: {hex_str!r}")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def validate_branding(branding: dict | None, extra_keys=()) -> None:
    """Warn (don't raise) on unrecognised branding keys — mirrors the early-typo
    surfacing of NoteTerms.from_dict. A no-op when branding is empty."""
    if not branding:
        return
    unknown = [k for k in branding if k not in (KNOWN_KEYS | set(extra_keys))]
    if unknown:
        warnings.warn(
            f"branding: ignoring unrecognised keys {unknown}. "
            f"Known keys: {sorted((KNOWN_KEYS | set(extra_keys)))}.",
            stacklevel=2,
        )


def brand_text(value, lang: str):
    """Resolve a branding text field that may be a plain string (single language,
    used as-is) OR a per-language dict like {"en": "...", "es": "..."}. For a dict,
    returns the requested language; if that language is absent it returns None so
    the caller falls back to the built-in translated default — this is what lets a
    Spanish-only firm disclaimer NOT bleed into an English report. None/empty in,
    None out."""
    if isinstance(value, dict):
        v = value.get(lang)
        return v or None
    return value or None


def branding_color(branding: dict | None, key: str,
                    default: tuple[int, int, int]) -> tuple[int, int, int]:
    """Resolve one hex colour from the branding dict, falling back to `default`
    (with a warning) when absent or malformed — never raises deep inside the PDF."""
    if not branding:
        return default
    raw = branding.get(key)
    if not raw:
        return default
    try:
        return hex_to_rgb(raw)
    except (ValueError, TypeError):
        warnings.warn(
            f"branding['{key}'] = {raw!r} is not a valid hex colour "
            f"(e.g. '#003366'); using the default.",
            stacklevel=2,
        )
        return default


def resolve_palette(branding: dict | None, *, default_firm_name: str) -> tuple[
    tuple[int, int, int], tuple[int, int, int],
    tuple[int, int, int], tuple[int, int, int], str
]:
    """Return (primary, accent, secondary, section_rule, firm_name) from the
    branding dict. Malformed hex values fall back to defaults with a warning;
    never raises. section_rule defaults to the accent colour when absent."""
    if not branding:
        return DEFAULT_PRIMARY, DEFAULT_ACCENT, DEFAULT_SECONDARY, DEFAULT_ACCENT, default_firm_name
    primary      = branding_color(branding, "primary_color",         DEFAULT_PRIMARY)
    accent       = branding_color(branding, "accent_color",          DEFAULT_ACCENT)
    secondary    = branding_color(branding, "chart_secondary_color", DEFAULT_SECONDARY)
    section_rule = branding_color(branding, "section_rule_color",    accent)
    firm         = branding.get("firm_name", default_firm_name) or default_firm_name
    return primary, accent, secondary, section_rule, firm


def load_logo(branding: dict | None, *, root=None, fetch=None) -> bytes | None:
    """Resolve the firm/issuer branding logo, local-file-first.

    Order of preference (first that yields bytes wins):
      1. branding['logo_file']   — a local path, resolved INSIDE `root`. A host
         that passes no root disables this source: a library cannot know which
         directory is legitimate, and an unconstrained path here is an
         arbitrary-file-read that ends up embedded in a downloadable PDF.
      2. branding['logo_base64'] — a base64 string or data: URI
      3. branding['logo_url']    — remote URL (last-resort network fetch)

    Returns image bytes or None. Never raises — a failure simply omits the logo.
    """
    if not branding:
        return None
    # 1. Local file
    spec = branding.get("logo_file")
    if spec:
        data = to_embeddable_png(read_local_image((resolve_within(spec, root) if root else None)))
        if data:
            return data
        print(f"[reportkit.branding] logo_file unusable ({spec}); trying next source")
    # 2. Base64 / data URI
    b64 = branding.get("logo_base64")
    if b64:
        try:
            payload = b64.split(",", 1)[1] if b64.strip().startswith("data:") else b64
            data = to_embeddable_png(base64.b64decode(payload))
            if data:
                print(f"[reportkit.branding] OK  base64 -> embeddable PNG")
                return data
        except Exception as exc:
            print(f"[reportkit.branding] FAIL base64: {exc}")
    # 3. Remote URL
    url = branding.get("logo_url")
    if url:
        return to_embeddable_png((fetch or fetch_image_bytes)(url))
    return None
