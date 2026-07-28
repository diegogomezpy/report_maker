"""
reportkit.fonts — registering the type a document draws with.

Two tiers. The **default family** is IBM Plex Sans, six weights, shipped with
this package under the OFL so a fresh install renders correct text with no
setup. Without it fpdf2 falls back to its built-in Helvetica, which is Latin-1
only and mangles ordinary Spanish — so this is not a nicety, and
`register_default_family` returning False is a visible, whole-document event
rather than a detail.

The **brand faces** are the host's: licensed typefaces reportkit must never
vendor. A brand names them and supplies either a directory of TTFs or base64
blobs in its config; anything missing falls back to the default family, per
weight, rather than failing the build.

Ordering matters. Brand registration OVERWRITES the weight map, so it has to run
after the default family is in place — running it earlier changes which face
draws what, on every page.
"""
from __future__ import annotations

import base64
import os
import re
import tempfile
from pathlib import Path

# The six OFL-licensed TTFs that ship inside this package.
_BUNDLED_DIR = Path(__file__).resolve().parent / "fonts"

#: Family names the weight map refers to. One place, so a rename can't drift.
FAMILY = "IBMPlexSans"
FAMILY_SEMIBOLD = "IBMPlexSansSB"
FAMILY_LIGHT = "IBMPlexSansLight"

#: Weight -> (family, fpdf style code). The document's `sf()` reads this.
DEFAULT_STYLE_MAP = {
    "regular":     (FAMILY,          ""),
    "bold":        (FAMILY,          "B"),
    "body_bold":   (FAMILY,          "B"),
    "bold_italic": (FAMILY,          "BI"),
    "italic":      (FAMILY,          "I"),
    "semibold":    (FAMILY_SEMIBOLD, ""),
    "light":       (FAMILY_LIGHT,    ""),
}

HELVETICA_STYLE_MAP = {
    "regular":     ("Helvetica", ""),
    "bold":        ("Helvetica", "B"),
    "body_bold":   ("Helvetica", "B"),
    "bold_italic": ("Helvetica", "BI"),
    "italic":      ("Helvetica", "I"),
    "semibold":    ("Helvetica", "B"),
    "light":       ("Helvetica", ""),
}


def register_default_family(pdf, font_dir=None) -> bool:
    """Register IBM Plex Sans TTF files. Returns True if all variants loaded."""
    d = Path(font_dir) if font_dir else _BUNDLED_DIR
    files = {k: d / f"IBMPlexSans-{k}.ttf" for k in
             ("Regular", "Bold", "SemiBold", "Light", "Italic", "BoldItalic")}
    _required = list(files.values())
    if not all(p.exists() for p in _required):
        return False
    try:
        pdf.add_font("IBMPlexSans",      "",   str(files["Regular"]),    uni=True)
        pdf.add_font("IBMPlexSans",      "B",  str(files["Bold"]),       uni=True)
        pdf.add_font("IBMPlexSans",      "I",  str(files["Italic"]),     uni=True)
        pdf.add_font("IBMPlexSans",      "BI", str(files["BoldItalic"]), uni=True)
        pdf.add_font("IBMPlexSansSB",    "",   str(files["SemiBold"]),   uni=True)
        pdf.add_font("IBMPlexSansLight", "",   str(files["Light"]),      uni=True)
        return True
    except Exception as exc:
        print(f"[reportkit.fonts] IBM Plex Sans registration failed: {exc}")
        return False


def register_brand_fonts(pdf, branding: dict | None, brand_dir=None) -> None:
    """Route the report's title / body type to custom brand fonts when the brand
    provides them. The branding keys `title_font` / `body_font` name a font (e.g.
    "Neulis Alt", "Gantari"); the TTF for each weight comes from EITHER an embedded
    base64 blob in `title_font_files` / `body_font_files` ({Style: base64 TTF}, so
    the fonts travel with an uploaded config and work on the deploy) OR the local
    file fonts/brand/<AlnumName>-<Style>.ttf (Style in Regular/Bold/Italic/
    BoldItalic). Embedded data wins; the local file is the fallback.

    Title type is the bold/semibold (heading) weights; body type is regular/light/
    italic. Anything that can't be loaded silently keeps the IBM Plex mapping, so
    a brand that only ships some weights — or none — never breaks the report."""
    # Brand faces are Unicode TTFs; on the Helvetica fallback there is no
    # TTF path to route them through, so the map stays as it is.
    if getattr(pdf, "_font_family", "") != FAMILY:
        return
    b = branding or {}
    if not (b.get("title_font") or b.get("body_font")):
        return

    def _tmp_font(raw: bytes, alnum: str, suffix: str) -> str:
        # Write an embedded TTF to a temp dir tied to the pdf's lifetime (cleaned
        # when the pdf is GC'd, i.e. after output()), so fpdf can read/embed it.
        d = getattr(pdf, "_brand_font_tmp", None)
        if d is None:
            d = pdf._brand_font_tmp = tempfile.TemporaryDirectory(prefix="brandfont_")
        path = os.path.join(d.name, f"{alnum}-{suffix}.ttf")
        with open(path, "wb") as fh:
            fh.write(raw)
        return path

    def _register(font_name: str | None, files: dict | None, styles: list[tuple[str, str]]):
        if not font_name:
            return None
        alnum = "".join(c for c in str(font_name) if c.isalnum())
        fam = "Brand" + alnum
        files = files if isinstance(files, dict) else {}
        loaded: set[str] = set()
        for code, suffix in styles:
            path = None
            # 1) embedded base64 (keyed by Style name, or the fpdf style code)
            blob = files.get(suffix) or files.get(code)
            if blob:
                try:
                    _pl = blob.split(",", 1)[1] if str(blob).strip().startswith("data:") else blob
                    path = _tmp_font(base64.b64decode(_pl), alnum, suffix)
                except Exception as e:
                    print(f"[reportkit.fonts] {font_name} {suffix} embedded decode failed: {e}")
                    path = None
            # 2) local file fallback
            if path is None:
                cand = (Path(brand_dir) if brand_dir else _BUNDLED_DIR / "brand") / f"{alnum}-{suffix}.ttf"
                path = str(cand) if cand.exists() else None
            if path:
                try:
                    pdf.add_font(fam, code, path, uni=True)
                    loaded.add(code)
                except Exception as e:
                    print(f"[reportkit.fonts] {font_name} {suffix} failed: {e}")
        if "" not in loaded:
            print(f"[reportkit.fonts] brand font '{font_name}' has no usable regular weight — using IBM Plex")
            return None
        print(f"[reportkit.fonts] brand font '{font_name}' registered ({sorted(loaded)})")
        return fam, loaded

    title = _register(b.get("title_font"), b.get("title_font_files"), [("", "Bold")])
    body  = _register(b.get("body_font"), b.get("body_font_files"),
                      [("", "Regular"), ("B", "Bold"), ("I", "Italic"), ("BI", "BoldItalic")])
    if title:
        tfam, _ = title
        pdf._sf_map["bold"] = (tfam, "")
        pdf._sf_map["semibold"] = (tfam, "")
    if body:
        bfam, bl = body
        pdf._sf_map["regular"] = (bfam, "")
        pdf._sf_map["light"]   = (bfam, "")
        # Tracked eyebrows/kickers use the BODY font bold (per the reference),
        # not the title face — keep a dedicated semantic weight for them.
        pdf._sf_map["body_bold"] = (bfam, "B" if "B" in bl else "")
        pdf._sf_map["italic"]  = (bfam, "I" if "I" in bl else "")
        pdf._sf_map["bold_italic"] = (bfam, "BI" if "BI" in bl else ("I" if "I" in bl else ""))
        if not title and "B" in bl:   # no title font → body bold also carries headings
            pdf._sf_map["bold"] = (bfam, "B")
            pdf._sf_map["semibold"] = (bfam, "B")


# ──────────────────────────────────────────────────────────────────────────────
# FPDF subclass
# ──────────────────────────────────────────────────────────────────────────────
