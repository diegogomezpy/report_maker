"""
reportkit.images — small, dependency-light image helpers for PDF layout.

Domain-agnostic; the only third-party dependency is Pillow, imported lazily so
importing this module is cheap and never fails when Pillow is absent (the
helpers degrade to returning their input unchanged).
"""
from __future__ import annotations

import functools
import io
import urllib.request
from pathlib import Path


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


# ──────────────────────────────────────────────────────────────────────────────
# Loading, sanitising and embedding
# ──────────────────────────────────────────────────────────────────────────────
# Report artwork arrives from three untrusted places — a base64 blob inside a
# user-supplied branding config, a URL, and a local path — so every entry point
# here is a security boundary as much as a convenience. The three guards, and
# why each exists, are documented on the functions themselves.

# Ceiling on decoded pixels for any embedded image. ~24 MPx is far above any
# real logo or cover photo and far below what it takes to exhaust memory.
MAX_IMAGE_PX = 24_000_000


def configure_limits(max_px: int | None = None) -> None:
    """Set the process-wide image ceiling.

    Also raises Pillow's own `MAX_IMAGE_PIXELS` to match, because Pillow's
    default (~89 MPx) only *warns* below twice the limit and would otherwise
    fire before ours. A library mutating another library's global is rude, so
    it happens only when a host explicitly asks — reportkit never does it at
    import time.
    """
    global MAX_IMAGE_PX
    if max_px is not None:
        MAX_IMAGE_PX = int(max_px)
    try:
        from PIL import Image
        Image.MAX_IMAGE_PIXELS = max(MAX_IMAGE_PX * 2, Image.MAX_IMAGE_PIXELS or 0)
    except Exception:
        pass

# Formats fpdf2 embeds directly, no decode needed.
_EMBEDDABLE_MAGIC = (b"\x89PNG", b"\xff\xd8\xff", b"GIF8")  # PNG / JPEG / GIF


def dimensions_sane(raw: bytes, max_px: int | None = None) -> bool:
    """Reject a decompression bomb by reading the HEADER, before any pixels.

    Branding art arrives base64-encoded inside a user-supplied config, and a
    ~100 KB PNG can declare 6000x6000 and expand to ~108 MB of RGBA. Pillow's
    MAX_IMAGE_PIXELS is not the defence: it only *warns* until twice the limit,
    and the cheap path below hands PNG/JPEG straight to fpdf2 without ever
    calling Pillow, so the allocation happens later and elsewhere.

    `Image.open` is lazy — it parses the header and stops — so `.size` costs
    nothing. Reject rather than downscale: a brand asset this large is a mistake
    or an attack, and silently shipping a resampled logo hides both.
    """
    max_px = MAX_IMAGE_PX if max_px is None else max_px
    try:
        from PIL import Image
        with Image.open(io.BytesIO(raw)) as im:
            w, h = im.size
    except Exception:
        return True          # not decodable here; the caller's own guards apply
    if w * h > max_px:
        print(f"[reportkit.images] refused {w}x{h} ({w * h / 1e6:.0f} MPx) — over the "
              f"{max_px / 1e6:.0f} MPx ceiling")
        return False
    return True


def to_embeddable_png(raw: bytes | None) -> bytes | None:
    """Return PNG bytes fpdf2 can embed, or None.

    If `raw` is already a PNG/JPEG/GIF it is returned unchanged (cheap path).
    Otherwise — ICO, WEBP, BMP, TIFF, multi-frame favicon … — it is decoded by
    Pillow and re-encoded as a single RGBA PNG. Any decode failure returns None
    so a bad image is dropped rather than crashing the report.
    """
    if not raw:
        return None
    if not dimensions_sane(raw):
        return None
    if raw[:4] in _EMBEDDABLE_MAGIC:
        return raw
    try:
        from PIL import Image
        im = Image.open(io.BytesIO(raw))
        # ICO files carry several sizes; Pillow opens the first — pick the
        # largest available frame for the crispest logo.
        sizes = getattr(im, "ico", None)
        if sizes is not None:
            try:
                biggest = max(im.ico.sizes())
                im = im.ico.getimage(biggest)
            except Exception:
                pass
        im = im.convert("RGBA")
        out = io.BytesIO()
        im.save(out, format="PNG")
        data = out.getvalue()
        print(f"[reportkit.images] converted {len(raw):,}b -> PNG {len(data):,}b ({im.size[0]}x{im.size[1]})")
        return data
    except Exception as exc:
        print(f"[reportkit.images] convert FAIL ({len(raw)}b): {exc}")
        return None


def logo_aspect(png: bytes | None, default: float = 1.0) -> float:
    """Width/height aspect ratio of a logo, so it can be sized without squashing
    a wide wordmark into a square box. Falls back to `default` on any error."""
    if not png:
        return default
    try:
        from PIL import Image
        w, h = Image.open(io.BytesIO(png)).size
        return (w / h) if h else default
    except Exception:
        return default


def fetch_image_bytes(url: str, timeout: int = 8) -> bytes | None:
    """Download an image from a URL. Returns raw bytes or None on failure.

    Uses a browser-like User-Agent so Google Favicon and other CDNs don't
    redirect or block the request.  Validates that the response body is
    non-empty before returning.
    """
    if not url:
        return None
    # http(s) only. `branding.logo_url` is user-supplied, and urlopen happily
    # honours file:// (read any file on the server and embed it in the PDF the
    # requester downloads) as well as ftp:// and data:. Nothing legitimate here
    # is served over anything but HTTP.
    if not str(url).lower().startswith(("http://", "https://")):
        print(f"[reportkit.images] refused non-http URL scheme: {str(url)[:60]!r}")
        return None
    # Upgrade Google favicon requests to sz=256 for crisper logos
    if "google.com/s2/favicons" in url:
        import re as _re
        url = _re.sub(r"sz=\d+", "sz=256", url)
    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0 Safari/537.36"
                ),
                "Accept": "image/png,image/jpeg,image/webp,image/*,*/*",
            },
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read()
        if not data:
            print(f"[reportkit.images] Empty response from {url}")
            return None
        print(f"[reportkit.images] OK  {len(data):,} bytes  {url}")
        return data
    except Exception as exc:
        print(f"[reportkit.images] FAIL {url!r}: {exc}")
        return None


def read_local_image(path: Path | None) -> bytes | None:
    """Read a local image file as raw bytes. fpdf2 cannot render SVG natively,
    so SVG files are skipped (returns None) with a diagnostic. Any failure is
    swallowed and returns None so a missing/bad file never crashes the PDF."""
    try:
        if path is None or not path.exists() or not path.is_file():
            return None
        if path.suffix.lower() == ".svg":
            print(f"[reportkit.images] SKIP SVG (not renderable by fpdf2): {path}")
            return None
        data = path.read_bytes()
        if not data:
            return None
        print(f"[reportkit.images] OK  {len(data):,} bytes  {path}")
        return data
    except Exception as exc:
        print(f"[reportkit.images] FAIL local {path!r}: {exc}")
        return None


def resolve_within(spec: str, root: Path) -> Path | None:
    """Resolve a branding `logo_file` to an absolute path INSIDE the repo root.

    A branding config is user-supplied — uploaded through the web UI or dropped
    into a connected folder — so `logo_file` is attacker-controlled input, not
    an operator-only setting. Left unconstrained it is an arbitrary-file-read
    primitive: any readable image on the server could be resolved and embedded
    into a PDF the requester then downloads, and the "unusable" log line answers
    does-this-path-exist for everything else.

    Both absolute paths and `../` escapes are refused. The documented contract
    was always "local path, repo-root relative", so this narrows the code to
    what the docs already promised. Configs embed their artwork as
    `logo_base64` (the web UI only ever writes that), so this path is for local
    development.
    """
    try:
        root = Path(root).resolve()
        p = (Path(spec) if Path(spec).is_absolute() else (root / spec)).resolve()
        p.relative_to(root)          # raises if p is outside the repo root
        return p
    except Exception:
        print(f"[reportkit.images] logo_file refused (outside the repo root): {spec!r}")
        return None
