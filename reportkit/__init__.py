"""
reportkit — a reusable toolkit for themed, brandable PDF reports.

Nothing here knows about any one project's domain. You drive a themed document
imperatively (or hand over a document spec) and feed in your own content; the
*look* is a swappable theme, which is data rather than code.

    reportkit.theme    the visual-identity layer: `ReportTheme`, the declarative
                       `SpecTheme`, palette-derived `ThemeTokens`, shape and
                       gradient primitives, and the theme registry.
    reportkit.images   dependency-light image helpers (aspect-correct crops).

Extraction in progress — `reportkit.document` (the themed builder and its
blocks), `reportkit.branding`, `reportkit.fonts`, `reportkit.spec` and the
optional `reportkit.charts` are being lifted out of the application this grew
inside, one slice at a time. Each slice is guarded by a byte-level fingerprint
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
from reportkit.images import cover_crop  # noqa: F401

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
    "cover_crop",
]
