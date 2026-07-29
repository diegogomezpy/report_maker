"""Per-page pixel golden for a document built entirely from this package.

The pagination suite proves the keep-together RULES; this proves the drawing.
Between them, a change to reportkit that moves pixels it did not mean to move
fails here rather than in whatever application happens to notice first.

Hermetic by construction: no network, no Chrome, no licensed assets. Figures go
through `stub_figures()`, which returns a flat block at exactly the pixel size
the call site asked for — the aspect ratio decides where pages break, so a stub
of the wrong shape would silently guard a different document. Imagery is
generated from a seed.

    pytest tests/test_golden.py                        # check
    REPORTKIT_GOLDEN_UPDATE=1 pytest tests/test_golden.py   # re-baseline

Re-baselining is deliberate and manual. On failure the run writes every
rendered page to a temp directory and prints the path; look at them before you
accept them.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest

pytest.importorskip("fpdf")
pytest.importorskip("PIL")

from reportkit import testing as rkt                  # noqa: E402

BASELINE = Path(__file__).resolve().parent / "golden" / "pages.json"

#: Both built-in themes, plus one run with no imagery at all — the themes draw
#: their own fallbacks for a brand with no photograph or watermark, and a
#: fixture that always supplies one leaves that whole path unrendered.
CASES = [("mercator", True), ("hexagon", True), ("mercator", False)]


def _render(theme: str, imagery: bool) -> bytes:
    with rkt.stub_figures():
        return rkt.sample_document(theme, imagery=imagery)


def _load() -> dict:
    return json.loads(BASELINE.read_text()) if BASELINE.exists() else {}


@pytest.mark.parametrize("theme,imagery", CASES)
def test_the_sample_document_is_pixel_identical(theme, imagery):
    key = f"{theme}/{'imagery' if imagery else 'plain'}"
    # Render OUTSIDE the skip guard. `rasterise` raises RuntimeError when no
    # rasteriser is installed, which is a legitimate skip — but building the
    # document raises RuntimeError too, and catching both here reported a
    # document that failed to build as "no rasteriser installed" and skipped.
    # A broken render must be a failure, not a quiet pass.
    pdf_bytes = _render(theme, imagery)
    try:
        pages = rkt.rasterise(pdf_bytes)
    except RuntimeError as exc:                        # no rasteriser installed
        pytest.skip(str(exc))
    digests = [h for h, _ in pages]

    if os.environ.get("REPORTKIT_GOLDEN_UPDATE"):
        base = _load(); base[key] = digests
        BASELINE.parent.mkdir(parents=True, exist_ok=True)
        BASELINE.write_text(json.dumps(base, indent=2, sort_keys=True) + "\n")
        pytest.skip(f"baselined {key}: {len(digests)} pages")

    base = _load()
    assert key in base, (
        f"no baseline for '{key}' — run: "
        f"REPORTKIT_GOLDEN_UPDATE=1 pytest {__file__}")
    expected = base[key]
    if digests == expected:
        return

    out = Path(tempfile.mkdtemp(prefix=f"rk_golden_{theme}_"))
    for i, (_, png) in enumerate(pages, 1):
        (out / f"p{i:02d}.png").write_bytes(png)
    if len(digests) != len(expected):
        pytest.fail(f"{key}: page COUNT changed {len(expected)} → {len(digests)}. "
                    f"Pages written to {out}")
    bad = [i + 1 for i, (a, b) in enumerate(zip(digests, expected)) if a != b]
    pytest.fail(f"{key}: {len(bad)} page(s) changed: {bad}. Pages written to "
                f"{out}. If intended, review them, then re-baseline with "
                f"REPORTKIT_GOLDEN_UPDATE=1.")


def test_the_sample_document_is_reproducible():
    """Two renders in one process must agree, or the golden is measuring noise.

    Worth its own test: a stray `Date.now()`-alike, a set iterated in hash
    order, or an unseeded RNG makes the baseline fail intermittently, and an
    intermittent golden gets deleted rather than debugged.
    """
    a, b = _render("mercator", True), _render("mercator", True)
    # The trailer's /ID and /CreationDate vary by design; compare the pages.
    try:
        da = [h for h, _ in rkt.rasterise(a)]
        db = [h for h, _ in rkt.rasterise(b)]
    except RuntimeError as exc:
        pytest.skip(str(exc))
    assert da == db


def test_the_figure_stub_is_the_size_it_was_asked_for():
    """Aspect fidelity is what makes the stub safe: `figure()` derives its drawn
    height from the image, so a stub that squared off would move page breaks and
    the golden would guard a document nobody ships."""
    from PIL import Image
    import io
    seen = []
    with rkt.stub_figures(lambda w, h: seen.append((w, h)) or rkt.flat_png(w, h)):
        from reportkit.charts import fig_to_png
        png = fig_to_png(object(), 900, 360, (0, 0, 0), (0, 0, 0), (0, 0, 0))
    assert seen == [(900, 360)]
    assert Image.open(io.BytesIO(png)).size == (900, 360)
