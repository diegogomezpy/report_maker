"""Image loading, sanitising and embedding — the security boundary.

The golden cannot reach any of this: no brand fixture sets `logo_file` or
`logo_url`, and the fixture tickers don't match anything on disk. So a report
renders pixel-identical whether these guards work or not. They are the reason
a branding config — which arrives from an upload or a watched folder, i.e. from
outside — cannot be used to read arbitrary server files or exhaust memory.
"""
from __future__ import annotations

import io
from pathlib import Path

import pytest

from reportkit.images import (
    dimensions_sane,
    fetch_image_bytes,
    logo_aspect,
    read_local_image,
    resolve_within,
    to_embeddable_png,
)

PIL = pytest.importorskip("PIL.Image")


def _png(w: int, h: int) -> bytes:
    buf = io.BytesIO()
    PIL.new("RGB", (w, h), (10, 20, 30)).save(buf, "PNG")
    return buf.getvalue()


# ── path containment ─────────────────────────────────────────────────────────

def test_resolve_within_accepts_a_path_inside_the_root(tmp_path):
    (tmp_path / "logo.png").write_bytes(_png(4, 4))
    got = resolve_within("logo.png", tmp_path)
    assert got is not None and got.name == "logo.png"


@pytest.mark.parametrize("spec", [
    "/etc/passwd",                       # absolute
    "../../../../etc/passwd",            # traversal
    "sub/../../outside.png",             # traversal via a real subdir
])
def test_resolve_within_refuses_escapes(tmp_path, spec):
    """`logo_file` is attacker-controlled. Unconstrained it is an
    arbitrary-file-read: any readable image gets embedded into a PDF the
    requester then downloads, and the failure log answers does-this-exist for
    everything else."""
    (tmp_path / "sub").mkdir()
    assert resolve_within(spec, tmp_path) is None


def test_resolve_within_refuses_a_symlink_pointing_out(tmp_path):
    outside = tmp_path.parent / "outside_secret.png"
    outside.write_bytes(_png(4, 4))
    link = tmp_path / "sneaky.png"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("symlinks unavailable")
    # resolve() follows the link, so containment is checked on the real target.
    assert resolve_within("sneaky.png", tmp_path) is None


# ── URL schemes ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("url", [
    "file:///etc/passwd",
    "ftp://example.com/logo.png",
    "data:image/png;base64,iVBORw0KGgo=",
    "gopher://example.com/",
    "FILE:///etc/passwd",                # case must not bypass it
])
def test_fetch_refuses_non_http_schemes(url):
    """urlopen honours file:// happily — that is SSRF plus arbitrary file read
    in one. Nothing legitimate here is served over anything but HTTP."""
    assert fetch_image_bytes(url) is None


def test_fetch_ignores_empty_input():
    assert fetch_image_bytes("") is None
    assert fetch_image_bytes(None) is None


# ── decompression bombs ──────────────────────────────────────────────────────

def test_dimensions_sane_passes_a_normal_image():
    assert dimensions_sane(_png(800, 600)) is True


def test_dimensions_sane_refuses_a_bomb():
    """~100 KB of PNG can declare 6000x6000 and expand to ~108 MB of RGBA.
    Pillow's own ceiling only warns below twice the limit, and the cheap
    passthrough never calls Pillow at all — so this header check is the
    defence, not a backstop."""
    bomb = _png(6000, 6000)
    assert dimensions_sane(bomb, max_px=24_000_000) is False
    assert to_embeddable_png(bomb) is None, "a bomb must not reach fpdf2"


def test_dimensions_sane_allows_undecodable_bytes_through():
    """Not decodable here means the caller's own guards apply — returning False
    would reject formats Pillow can't sniff but fpdf2 can embed."""
    assert dimensions_sane(b"not an image") is True


# ── embedding ────────────────────────────────────────────────────────────────

def test_png_passes_through_byte_identical():
    """The cheap path matters: re-encoding every logo would change embedded
    bytes on every page that has one."""
    raw = _png(40, 20)
    assert to_embeddable_png(raw) is raw


def test_unsupported_format_is_converted():
    buf = io.BytesIO()
    PIL.new("RGB", (30, 10), (5, 5, 5)).save(buf, "BMP")
    out = to_embeddable_png(buf.getvalue())
    assert out is not None and out[:4] == b"\x89PNG"


def test_garbage_is_dropped_not_raised():
    assert to_embeddable_png(b"\x00\x01\x02") is None
    assert to_embeddable_png(None) is None


def test_logo_aspect_and_its_fallback():
    assert logo_aspect(_png(200, 50)) == pytest.approx(4.0)
    assert logo_aspect(b"junk") == 1.0
    assert logo_aspect(None, default=2.5) == 2.5


def test_svg_is_skipped(tmp_path):
    """fpdf2 cannot render SVG; embedding one produces a broken page rather
    than an error, so it is refused at the door."""
    p = tmp_path / "logo.svg"
    p.write_text("<svg xmlns='http://www.w3.org/2000/svg'/>")
    assert read_local_image(p) is None


def test_read_local_image_tolerates_missing(tmp_path):
    assert read_local_image(tmp_path / "nope.png") is None
    assert read_local_image(None) is None
