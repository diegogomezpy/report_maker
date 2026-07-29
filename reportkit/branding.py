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

import logging

import base64
from dataclasses import dataclass, field

from reportkit.images import (read_local_image,
                              resolve_within, to_embeddable_png)

_log = logging.getLogger(__name__)


#: Fallback palette for a brand that supplies nothing. Defined in
#: `reportkit.color` and re-exported here for one release; import it from there.
from reportkit.color import (  # noqa: E402,F401
    DEFAULT_ACCENT, DEFAULT_PRIMARY, DEFAULT_SECONDARY, DEFAULT_SECTION_RULE,
)

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


def unknown_keys(branding: dict | None, extra_keys=()) -> list[str]:
    """Keys the library does not recognise. The single predicate — `resolve` and
    `validate_branding` used to carry their own copies of it."""
    if not branding:
        return []
    known = KNOWN_KEYS | set(extra_keys)
    return [k for k in branding if k not in known]


def validate_branding(branding: dict | None, extra_keys=()) -> list[str]:
    """Report unrecognised branding keys, one message per key.

    RETURNS the messages rather than raising a `UserWarning`. A config defect is
    data about the caller's input, not an event in the interpreter, and routing
    it through `warnings.warn` meant a host had to install a warnings filter to
    show its users what it had ignored. `Brand.warnings` is now the only channel
    for this class, so there is one place to look.
    """
    return [f"unrecognised branding key {k!r} — ignored"
            for k in unknown_keys(branding, extra_keys)]


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
                    default: tuple[int, int, int],
                    sink: list | None = None) -> tuple[int, int, int]:
    """Resolve one hex colour, falling back to `default` when absent or
    malformed — never raises deep inside the PDF.

    `sink` collects the fallback message. Absent, the fallback is silent: a
    caller reading one colour has its own way of reporting, and `resolve`
    passes a sink so the message reaches `Brand.warnings`.
    """
    if not branding:
        return default
    raw = branding.get(key)
    if not raw:
        return default
    try:
        return hex_to_rgb(raw)
    except (ValueError, TypeError):
        if sink is not None:
            sink.append(f"branding[{key!r}] = {raw!r} is not a valid hex colour "
                        f"(e.g. '#003366'); using the default")
        return default


def resolve_palette(branding: dict | None, *, default_firm_name: str,
                    sink: list | None = None) -> tuple[
    tuple[int, int, int], tuple[int, int, int],
    tuple[int, int, int], tuple[int, int, int], str
]:
    """Return (primary, accent, secondary, section_rule, firm_name) from the
    branding dict. Malformed hex values fall back to defaults with a warning;
    never raises. section_rule defaults to the accent colour when absent."""
    if not branding:
        return DEFAULT_PRIMARY, DEFAULT_ACCENT, DEFAULT_SECONDARY, DEFAULT_ACCENT, default_firm_name
    primary      = branding_color(branding, "primary_color",         DEFAULT_PRIMARY, sink)
    accent       = branding_color(branding, "accent_color",          DEFAULT_ACCENT, sink)
    secondary    = branding_color(branding, "chart_secondary_color", DEFAULT_SECONDARY, sink)
    section_rule = branding_color(branding, "section_rule_color",    accent, sink)
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
      3. branding['logo_url']    — a remote URL, fetched ONLY if the host passes
         a `fetch` callable. Same reasoning as `root`: left on by default this
         is an SSRF read with an exfil channel — a config you did not write
         names a URL, reportkit requests it, and the response is embedded in a
         PDF the requester downloads. Opt in with
         `fetch=reportkit.images.fetch_image_bytes`.

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
        # `root is None` means the file was never OPENED — path access is
        # opt-in. Reporting it as "unusable" blamed the file for a policy
        # decision, and contradicted the `Brand.warnings` entry from this very
        # call, which says the right thing.
        if root is None:
            _log.debug("logo_file ignored: no `root` supplied (path access is opt-in)")
        else:
            _log.warning("logo_file unusable (%s); trying next source", spec)
    # 2. Base64 / data URI
    b64 = branding.get("logo_base64")
    if b64:
        try:
            payload = b64.split(",", 1)[1] if b64.strip().startswith("data:") else b64
            data = to_embeddable_png(base64.b64decode(payload))
            if data:
                _log.debug("OK  base64 -> embeddable PNG")
                return data
        except Exception as exc:
            _log.warning(f"FAIL base64: {exc}")
    # 3. Remote URL
    url = branding.get("logo_url")
    if url:
        if fetch is None:
            # Deliberately silent here: `resolve` already appends this exact
            # condition to `Brand.warnings`, which the host renders. Saying it
            # twice trained operators to skim.
            return None
        return to_embeddable_png(fetch(url))
    return None


# ──────────────────────────────────────────────────────────────────────────────
# The positional image-slot algorithm
# ──────────────────────────────────────────────────────────────────────────────
# A brand supplies a POOL of report photos. Its slots are positional —
# 0 = cover, 1 = back page, the rest = void-filler bands — and a slot can be a
# deliberate BLANK meaning "no photo here, themed background instead".
#
# The blank is the whole reason this is not a list comprehension. A picker's
# "No image" choice arrives as an empty string, and it has to HOLD its position:
# if a failed or blank entry simply vanished, the next photo would shift up into
# the cover role and a brand that explicitly chose no cover photo would get one.
#
# Pure functions over bytes, deliberately: no PDF, no fpdf, no document. That is
# what makes the branch table below testable at all.


@dataclass(frozen=True)
class ImageRoles:
    """Which photo plays which part. `cover`/`back` may be None (deliberately).

    Frozen, and `fillers` is a tuple: this is the OUTPUT of the slot algorithm,
    and a caller that reassigned a role after the fact would be re-deciding the
    assignment somewhere the algorithm cannot see.
    """

    cover: bytes | None
    back: bytes | None
    fillers: tuple = ()

    def __repr__(self):                       # helpful in a failing assertion
        def n(b):
            return None if b is None else f"<{len(b)}b>"
        return (f"ImageRoles(cover={n(self.cover)}, back={n(self.back)}, "
                f"fillers=[{', '.join(n(f) for f in self.fillers)}])")


def decode_slots(raw, decode=None) -> list:
    """Pool config → positional slots, blanks preserved as None.

    `decode` turns one entry into bytes-or-None (base64, a data URI, whatever
    the host stores); it defaults to a base64/data-URI reader. A bare string is
    tolerated as a one-entry pool, because configs written by hand do that.
    Real images are deduped BY CONTENT — the same photo picked twice occupies
    one slot, but two distinct blanks each keep theirs.
    """
    if not raw:
        return []
    if isinstance(raw, (str, bytes)):
        raw = [raw]
    decode = decode or _decode_b64
    slots, seen = [], set()
    for item in raw:
        img = decode(item)
        if img is None:
            slots.append(None)                # blank slot — keeps its position
        elif img not in seen:
            seen.add(img)
            slots.append(img)
        # else: the same image again — drop the duplicate, do not add a slot
    return slots


def assign_images(slots, *, cover=None, back=None) -> ImageRoles:
    """Positional slots (+ explicit overrides) → cover / back / filler pool.

    Four rules, each of which exists because of a real config:

    * The cover is the explicit image, else slot 0. Note the explicit one is
      tested for TRUTHINESS, so an explicit-but-blank cover falls through to
      slot 0 — the sentinel is honoured for slots but not for the explicit key.
      That asymmetry is preserved deliberately; it is current behaviour.
    * The back is the explicit image, else slot 1 — which may be a deliberate
      blank, and is honoured as one. Only when there is NO second slot at all
      does it fall back to the cover, so a one-photo brand still gets a back
      page without overriding an explicit "no image".
    * Fillers are the real images not already spent on cover or back, so the
      cover photo never reappears mid-report.
    * If that leaves nothing, fall back to the cover/back photos — a two-photo
      brand still gets a filler band rather than a bare void.
    """
    cover_img = cover if cover else (slots[0] if slots else None)

    if back:
        back_img = back
    elif len(slots) > 1:
        back_img = slots[1]                   # may be None → deliberate blank
    else:
        back_img = cover_img

    used = {b for b in (cover_img, back_img) if b}
    fillers = [img for img in slots if img and img not in used]
    if not fillers:
        fillers, seen = [], set()
        for img in (cover_img, back_img):
            if img and img not in seen:
                seen.add(img)
                fillers.append(img)
    return ImageRoles(cover_img, back_img, tuple(fillers))


def _decode_b64(value):
    """Base64 / data-URI string → PNG bytes, or None for blank or undecodable.

    None rather than raising: a blank entry is a legitimate choice, and a
    corrupt one should cost a photo, not the report.
    """
    if not value:
        return None
    try:
        if isinstance(value, bytes):
            return to_embeddable_png(value)
        payload = value.split(",", 1)[1] if str(value).strip().startswith("data:") else value
        return to_embeddable_png(base64.b64decode(payload))
    except Exception:
        return None


# ──────────────────────────────────────────────────────────────────────────────
# Brand — a config resolved once, applied once
# ──────────────────────────────────────────────────────────────────────────────
# Before this existed, `KNOWN_KEYS` recognised 51 keys and the module applied
# two. That is worse than not knowing about them: a config was accepted whole
# and then silently honoured in part, and the ~30 attributes the theme layer
# reads had exactly one writer anywhere — the application this was extracted
# from. For every other consumer, watermarks, the cover sigil and cover
# photography were unreachable.
#
# `Brand` is PURE DATA: no fpdf import, no document. That is what lets a host
# resolve a config, inspect it, cache it or diff it without building a PDF —
# and what keeps this module off the document's import graph.

#: Every document attribute `apply_brand` writes. The theme layer reads brand
#: state off the document by name, so this list and those reads must agree — the
#: test suite asserts it, which is what stops the recognised-but-ignored gap
#: from quietly reopening the next time a key is added.
APPLIED_ATTRS = (
    "firm_name", "firm_logo_bytes", "firm_logo_aspect",
    "cover_logo_bytes", "cover_logo_aspect", "cover_sigil_bytes",
    "cover_image_bytes", "back_image_bytes", "filler_image_list",
    "watermark", "cover_overlay_color", "cover_overlay_opacity",
    "report_title", "website", "contact", "footer_note", "disclaimer_body",
    "cover_logo_x_pct", "cover_logo_y_pct", "cover_logo_size_pct",
    "cover_sigil_x_pct", "cover_sigil_y_pct", "cover_sigil_size_pct",
    "cover_sigil_opacity",
)


@dataclass(frozen=True)
class Brand:
    """A resolved brand: colours, imagery, copy and type, ready to apply.

    `warnings` collects everything that degraded — an unparseable colour, a
    refused logo source, an unknown key — so a host can surface them instead of
    discovering the problem in a client's PDF. `extras` carries whatever the
    host declared via `extra_keys`; reportkit never interprets it.
    """
    primary: tuple = DEFAULT_PRIMARY
    accent: tuple = DEFAULT_ACCENT
    secondary: tuple = DEFAULT_SECONDARY
    section_rule: tuple = DEFAULT_ACCENT
    panel: tuple | None = None
    sidebar_bar: tuple | None = None
    firm_name: str = ""
    theme_name: object = None            # name, inline spec dict, or None

    logo: bytes | None = None
    cover_logo: bytes | None = None
    cover_sigil: bytes | None = None
    cover_image: bytes | None = None
    back_image: bytes | None = None
    fillers: tuple = ()

    watermark_image: bytes | None = None
    raw: dict = field(default_factory=dict)     # the config, for resolve_watermark
    overlay_color: tuple | None = None
    overlay_opacity: float = 0.55
    placement: dict = field(default_factory=dict)

    report_title: str = ""
    website: str = ""
    contact: str = ""
    footer_note: str = ""
    disclaimer_body: str = ""

    title_font: str = ""
    body_font: str = ""

    extras: dict = field(default_factory=dict)
    warnings: tuple = ()


def _opt_float(cfg, key):
    try:
        return float(cfg[key])
    except (KeyError, TypeError, ValueError):
        return None


def resolve(cfg: dict | None, *, lang: str = "en", root=None, fetch=None,
            extra_keys=(), default_firm_name: str = "") -> Brand:
    """A brand config → a `Brand`. Never raises; degrades and records why.

    `default_firm_name` is REQUIRED of the caller rather than defaulted here.
    It reaches the running header of every page, and a library that supplied
    its own would silently print someone else's product name across a client's
    document.

    `root` and `fetch` gate the two sources that touch the outside world — see
    `load_logo`. Passing neither means base64 payloads only, which is the right
    default for a config you did not author.
    """
    cfg = cfg or {}
    # One predicate for "unknown key" — this loop used to be a second copy of
    # `validate_branding`'s, and the host calls BOTH with the same extra_keys.
    warn: list[str] = validate_branding(cfg, extra_keys)

    primary, accent, secondary, section_rule, firm = resolve_palette(
        cfg, default_firm_name=default_firm_name, sink=warn)

    slots = decode_slots(cfg.get("filler_images_base64"))
    roles = assign_images(slots,
                          cover=_decode_b64(cfg.get("cover_image_base64")),
                          back=_decode_b64(cfg.get("back_image_base64")))

    # A legacy flat `watermark_enabled: false` drops the image so the theme's
    # own drawn mark shows instead. Kept because old configs still say it.
    wm_cfg = cfg.get("watermark") if isinstance(cfg.get("watermark"), dict) else {}
    wm_b64 = wm_cfg.get("image_base64") or cfg.get("watermark_base64")
    if cfg.get("watermark_enabled", True) is False:
        wm_b64 = None

    logo = load_logo(cfg, root=root, fetch=fetch)
    if cfg.get("logo_url") and fetch is None and logo is None:
        warn.append("logo_url ignored: no `fetch` supplied (network is opt-in)")
    if cfg.get("logo_file") and root is None:
        warn.append("logo_file ignored: no `root` supplied (path access is opt-in)")

    return Brand(
        primary=primary, accent=accent, secondary=secondary,
        section_rule=section_rule,
        panel=branding_color(cfg, "panel_color", None) if cfg.get("panel_color") else None,
        sidebar_bar=(branding_color(cfg, "sidebar_bar_color", None)
                     if cfg.get("sidebar_bar_color") else None),
        firm_name=firm,
        theme_name=cfg.get("report_theme"),
        logo=logo,
        cover_logo=_decode_b64(cfg.get("cover_logo_base64")),
        cover_sigil=_decode_b64(cfg.get("cover_sigil_base64")),
        cover_image=roles.cover, back_image=roles.back, fillers=roles.fillers,
        watermark_image=_decode_b64(wm_b64), raw=dict(cfg),
        overlay_color=(branding_color(cfg, "cover_overlay_color", None)
                       if cfg.get("cover_overlay_color") else None),
        overlay_opacity=(_opt_float(cfg, "cover_overlay_opacity") or 0.55),
        placement={k: _opt_float(cfg, k) for k in (
            "cover_logo_x_pct", "cover_logo_y_pct", "cover_logo_size_pct",
            "cover_sigil_x_pct", "cover_sigil_y_pct", "cover_sigil_size_pct",
            "cover_sigil_opacity")},
        report_title=brand_text(cfg.get("report_title"), lang) or "",
        website=str(cfg.get("website") or ""),
        contact=str(cfg.get("contact") or ""),
        footer_note=brand_text(cfg.get("footer_note"), lang) or "",
        disclaimer_body=brand_text(cfg.get("disclaimer_body"), lang) or "",
        title_font=str(cfg.get("title_font") or ""),
        body_font=str(cfg.get("body_font") or ""),
        extras={k: cfg[k] for k in extra_keys if k in cfg},
        warnings=tuple(warn),
    )
