"""
reportkit.images — small, dependency-light image helpers for PDF layout.

Domain-agnostic; the only third-party dependency is Pillow, imported lazily so
importing this module is cheap and never fails when Pillow is absent (the
helpers degrade to returning their input unchanged).
"""
from __future__ import annotations

import functools
import io


def cover_crop(raw: bytes | None, aspect: float,
               bias_x: float = 0.0, bias_y: float = 0.0) -> bytes | None:
    """Memoised `_cover_crop`. See that function for the geometry.

    A report calls this once per empty-space photo band and once per cover, and
    the same few source images come round again and again — in a profile of a
    24-page render it was 0.46s of a 1.5s build, a third of the whole document,
    spent decoding and re-encoding pictures that had already been decoded and
    re-encoded. The bias is quantised so the near-identical calls that differ
    only in float noise still hit.

    Memory: the cache key retains `raw`, but the branding config holds those
    bytes for the document's lifetime anyway, so the marginal cost is the
    cropped outputs.

    `maxsize` must stay comfortably ABOVE the working set. A report cycles
    round-robin through its photo pool, so a cache smaller than the pool evicts
    exactly the entry it is about to need — an LRU sized at 12 against 13
    distinct crops scored zero hits in several thousand calls, strictly worse
    than no cache at all.
    """
    if not raw:
        return raw
    return _cover_crop_cached(raw, round(float(aspect), 4),
                              round(float(bias_x), 3), round(float(bias_y), 3))


@functools.lru_cache(maxsize=96)
def _cover_crop_cached(raw: bytes, aspect: float, bias_x: float, bias_y: float):
    return _cover_crop(raw, aspect, bias_x, bias_y)


def _cover_crop(raw: bytes | None, aspect: float,
                bias_x: float = 0.0, bias_y: float = 0.0) -> bytes | None:
    """Crop an image to `aspect` (= width / height) so a full-bleed placement
    fills the box without stretching (CSS object-fit: cover). `bias_x`/`bias_y`
    in [-1, 1] shift the crop window off-centre (0 = centred, -1 = left/top,
    +1 = right/bottom) — used to show different regions of the same source on
    successive pages so a repeated filler photo doesn't read as identical.
    Returns PNG bytes; on any failure returns the input unchanged."""
    if not raw:
        return raw
    try:
        from PIL import Image
        im = Image.open(io.BytesIO(raw)).convert("RGB")
        w, h = im.size
        cur = w / h
        if abs(cur - aspect) < 1e-3 and not (bias_x or bias_y):
            return raw
        if cur > aspect:                       # too wide → crop the sides
            nw = int(round(h * aspect))
            x0 = int(round((w - nw) * (0.5 + 0.5 * max(-1.0, min(1.0, bias_x)))))
            x0 = max(0, min(w - nw, x0))
            im = im.crop((x0, 0, x0 + nw, h))
        else:                                  # too tall → crop top/bottom
            nh = int(round(w / aspect))
            y0 = int(round((h - nh) * (0.5 + 0.5 * max(-1.0, min(1.0, bias_y)))))
            y0 = max(0, min(h - nh, y0))
            im = im.crop((0, y0, w, y0 + nh))
        buf = io.BytesIO(); im.save(buf, "PNG")
        return buf.getvalue()
    except Exception as e:
        print(f"[reportkit.images] crop skipped: {e}")
        return raw
