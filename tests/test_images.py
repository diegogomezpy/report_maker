"""Image helpers: aspect-correct cropping, and the memo that makes it affordable."""
from __future__ import annotations

import io

import pytest

from reportkit.images import _cover_crop_cached, cover_crop

PIL = pytest.importorskip("PIL.Image")


def _png(w: int, h: int, colour=(120, 30, 200)) -> bytes:
    buf = io.BytesIO()
    PIL.new("RGB", (w, h), colour).save(buf, "PNG")
    return buf.getvalue()


def _size(raw: bytes) -> tuple[int, int]:
    return PIL.open(io.BytesIO(raw)).size


@pytest.mark.parametrize("src,aspect", [
    ((800, 200), 1.0),      # wide source, square box   -> crop the sides
    ((200, 800), 1.0),      # tall source, square box   -> crop top/bottom
    ((400, 400), 2.0),      # square source, wide box   -> crop top/bottom
    ((400, 400), 0.5),      # square source, tall box   -> crop the sides
])
def test_crop_hits_the_requested_aspect_without_stretching(src, aspect):
    w, h = _size(cover_crop(_png(*src), aspect))
    assert w / h == pytest.approx(aspect, rel=0.02)
    # "cover", not "contain": the crop never invents pixels, so each side must
    # still fit inside the source.
    assert w <= src[0] and h <= src[1]


def test_matching_aspect_is_returned_untouched():
    raw = _png(400, 200)
    assert cover_crop(raw, 2.0) is raw


def test_bias_moves_the_crop_window():
    """Successive filler bands crop the same photo at different offsets so a
    repeated image doesn't read as identical. Left and right crops of a
    gradient must therefore differ."""
    im = PIL.new("RGB", (900, 300))
    for x in range(900):                       # horizontal gradient
        for y in range(0, 300, 60):
            im.putpixel((x, y), (x % 256, 0, 0))
    buf = io.BytesIO(); im.save(buf, "PNG")
    raw = buf.getvalue()
    left = cover_crop(raw, 1.0, bias_x=-1.0)
    right = cover_crop(raw, 1.0, bias_x=1.0)
    assert left != right
    assert _size(left) == _size(right)


def test_bad_input_degrades_instead_of_raising():
    """A crop runs deep inside a drawing routine; an exception there takes out
    the whole document. Garbage in must give the input straight back."""
    assert cover_crop(None, 1.0) is None
    assert cover_crop(b"", 1.0) == b""
    junk = b"not an image at all"
    assert cover_crop(junk, 1.0) is junk


def test_repeat_calls_are_memoised():
    """A report crops the same few images over and over — this was a third of
    build time before the memo. The cache must be big enough for the working
    set: an LRU smaller than the photo pool evicts exactly the entry it is
    about to need and scores zero hits."""
    _cover_crop_cached.cache_clear()
    raw = _png(600, 200)
    for _ in range(5):
        cover_crop(raw, 1.5)
    info = _cover_crop_cached.cache_info()
    assert info.hits == 4 and info.misses == 1
    assert info.maxsize >= 32, "cache too small to survive a photo pool"


def test_float_noise_still_hits_the_cache():
    """Call sites compute the aspect from page geometry, so the 'same' crop
    arrives with a hair of float noise. The key is quantised for exactly this."""
    _cover_crop_cached.cache_clear()
    raw = _png(600, 200)
    cover_crop(raw, 1.5)
    cover_crop(raw, 1.5 + 1e-9)
    assert _cover_crop_cached.cache_info().hits == 1
