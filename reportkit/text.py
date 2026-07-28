"""
reportkit.text — sanitising strings for a PDF.

Two failure modes this guards. A glyph the embedded font lacks renders as a
blank box, silently, in a document that otherwise looks finished. And when no
Unicode font is available at all, fpdf2 falls back to Latin-1 Helvetica, where
an em-dash or a Greek letter raises rather than degrades — one stray character
in a translated label takes out the whole build.

So the caller passes `latin1=True` only on the fallback path, and that flag is
fed by whether a Unicode face actually registered. Splitting those two apart is
how the decision loses its input.
"""
from __future__ import annotations

_EMOJI_STRIP = {
    "✅": "OK", "⚠️": "!", "❌": "x", "🚀": ">>", "⏳": "...",
    "®": "", "™": "", "©": "",
}


def _safe(text: object, *, latin1: bool = False) -> str:
    """Sanitise text for the PDF.

    With IBM Plex Sans (Unicode font) only emojis need neutralising.
    Pass latin1=True only for the Helvetica fallback path.
    """
    s = str(text)
    for bad, good in _EMOJI_STRIP.items():
        s = s.replace(bad, good)
    if latin1:
        _LATIN1_MAP = {
            "—": "-", "–": "-", "−": "-", "·": "-", "•": "-",
            "→": "->", "←": "<-", "≥": ">=", "≤": "<=",
            "“": '"', "”": '"', "‘": "'", "’": "'",
            "…": "...", "×": "x", "÷": "/",
            "€": "EUR", "£": "GBP",
            "κ": "kappa", "θ": "theta", "ξ": "xi", "ρ": "rho",
            "σ": "sigma", "μ": "mu", "ν": "nu", "₀": "0", "√": "sqrt ",
        }
        for bad, good in _LATIN1_MAP.items():
            s = s.replace(bad, good)
        s = s.encode("latin-1", "ignore").decode("latin-1")
    return s
