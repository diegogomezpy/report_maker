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

Extraction in progress — `reportkit.branding` and `reportkit.spec` are still
being lifted out of the application this grew inside, one slice at a time. Each slice is guarded by a byte-level fingerprint
of that application's rendered reports, so a move that changes output fails.

Only `fpdf2` and `Pillow` are required. Plotly figure rendering lives behind the
`charts` extra because Kaleido drives a headless Chrome; the core takes PNG
bytes and never imports it.
"""
from __future__ import annotations

__version__ = "0.1.0"

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
    "cover_crop",
    "configure_limits",
    "parse_rgb",
    "remap_color",
    "rgb_to_hue",
]
