"""
reportkit — a reusable toolkit for themed, brandable PDF reports.

Nothing here knows about any one project's domain. You drive a themed document
imperatively (or hand over a document spec) and feed in your own content; the
*look* is a swappable theme, which is data rather than code.

    reportkit.theme    the visual-identity layer: `ReportTheme`, the declarative
                       `SpecTheme`, palette-derived `ThemeTokens`, shape and
                       gradient primitives, and the theme registry.
    reportkit.images   image loading, sanitising and embedding — including the
                       path-containment, URL-scheme and decompression-bomb guards.
    reportkit.color    CSS colour parsing and brand palette remapping.
    reportkit.charts   [charts extra] Plotly figure -> brand-coloured PNG bytes.

    reportkit.document  `ReportDocument` — the themed builder: covers, section
                        heads, tables, metric bands, figures, callouts, and the
                        pagination that keeps a heading with its content.
    reportkit.fonts     font registration; ships IBM Plex Sans under the OFL.
    reportkit.text      string sanitisation for the PDF text layer.
    reportkit.spec      describe a document as data; `render_spec(dict)`.
    reportkit.branding  resolve a brand config — palette, logo, copy, fonts.

Extracted from a working application, every slice guarded by a byte-level fingerprint of that application's
rendered reports, so a move that changes output fails.

Only `fpdf2` and `Pillow` are required. Plotly figure rendering lives behind the
`charts` extra because Kaleido drives a headless Chrome; the core takes PNG
bytes and never imports it.
"""
from __future__ import annotations

# Single-sourced from the installed distribution metadata, which pyproject.toml
# is the authority for. Hard-coding it here too gave two versions that drift:
# 0.2.0 shipped reporting 0.1.0 because only one of the pair got bumped.
try:                                    # installed (wheel / editable)
    from importlib.metadata import version as _dist_version
    __version__ = _dist_version("reportkit")
except Exception:                       # running from a source checkout
    __version__ = "0.0.0+source"

# Keep the top-level surface small and stable — import the submodules for the
# rest. Everything re-exported here is something a host application is expected
# to touch directly.
from reportkit.theme import (  # noqa: F401
    ReportTheme,
    SpecTheme,
    ThemeTokens,
    build_tokens,
    resolve_theme,
    resolve_color,
    paint_shape,
    register_theme,
    known_themes,
    DEFAULT_THEME,
    HEXAGON_SPEC,
    MERCATOR_SPEC,
)
from reportkit.images import cover_crop, configure_limits  # noqa: F401
from reportkit.color import parse_rgb, remap_color, rgb_to_hue  # noqa: F401
from reportkit.document import ReportDocument, CHROME_LABELS  # noqa: F401
from reportkit.text import _safe as sanitise  # noqa: F401
from reportkit.spec import render as render_spec, SpecError  # noqa: F401
from reportkit.branding import (  # noqa: F401
    load_logo, resolve_palette, validate_branding,
)

__all__ = [
    "__version__",
    "ReportTheme",
    "SpecTheme",
    "ThemeTokens",
    "build_tokens",
    "resolve_theme",
    "resolve_color",
    "paint_shape",
    "register_theme",
    "known_themes",
    "DEFAULT_THEME",
    "HEXAGON_SPEC",
    "MERCATOR_SPEC",
    "ReportDocument",
    "CHROME_LABELS",
    "sanitise",
    "render_spec",
    "load_logo",
    "resolve_palette",
    "validate_branding",
    "SpecError",
    "cover_crop",
    "configure_limits",
    "parse_rgb",
    "remap_color",
    "rgb_to_hue",
]
