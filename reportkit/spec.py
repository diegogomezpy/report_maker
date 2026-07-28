"""
reportkit.spec — describe a document as data, get a PDF back.

The imperative API (`ReportDocument`) is the whole library; this is a thin layer
over it for the common case where a report's *shape* comes from somewhere other
than the Python you're writing — a config file, a UI, another service.

    render({
        "brand": {"firm_name": "Acme", "primary": "#0B3B2E", "theme": "mercator"},
        "sections": [
            {"title": "Performance", "blocks": [
                {"metrics": [["Net return", "8.4%"], ["Sharpe", "0.74"]]},
                {"table": {"headers": ["Asset", "Weight"],
                           "rows": [["Equities", "62%"]]}},
            ]},
        ],
    })

Two design choices worth stating.

**A spec is data, so it is untrusted.** Every block is validated before it draws;
an unknown block type or a malformed one raises `SpecError` naming the path
(`sections[1].blocks[0].table`) rather than failing somewhere inside fpdf2 with
a stack trace about a float. A report is often generated from user input, and
"which key did I get wrong" is the only question worth answering.

**There is an escape hatch.** No fixed vocabulary survives contact with a real
project — there is always one bespoke diagram. A `{"custom": "name"}` block
dispatches to a callable you pass in `blocks=`, so one unusual drawing does not
push you off the declarative path for the other 95% of the document.
"""
from __future__ import annotations

from reportkit.document import ReportDocument
from reportkit.theme import resolve_theme


class SpecError(ValueError):
    """A document spec was malformed. The message names the offending path."""


def _hex(v, default):
    if not isinstance(v, str):
        return default
    s = v.strip().lstrip("#")
    if len(s) == 3:
        s = "".join(c * 2 for c in s)
    if len(s) != 6:
        return default
    try:
        return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16))
    except ValueError:
        return default


def _need(obj, kind, path):
    if not isinstance(obj, kind):
        raise SpecError(f"{path}: expected {kind.__name__}, got {type(obj).__name__}")
    return obj


def _rows(raw, path):
    """Normalise a rows table to list[list[str]] — accepts tuples and numbers,
    because a spec that came through JSON or a spreadsheet will have both."""
    out = []
    for i, row in enumerate(_need(raw, list, path)):
        _need(row, (list, tuple), f"{path}[{i}]")
        out.append([("" if c is None else str(c)) for c in row])
    return out


# ── block renderers ──────────────────────────────────────────────────────────
# Each takes (doc, value, path). Keys are the block names a spec may use.

def _blk_text(doc, v, path):
    doc.body(str(v))


def _blk_bullets(doc, v, path):
    for item in _need(v, list, path):
        doc.bullet(str(item))


def _blk_heading(doc, v, path):
    doc.subsection(str(v))


def _blk_metrics(doc, v, path):
    pairs = [(str(a), str(b)) for a, b in
             (_need(p, (list, tuple), f"{path}[{i}]") for i, p in
              enumerate(_need(v, list, path)))]
    doc.metric_band(pairs)


def _blk_table(doc, v, path):
    _need(v, dict, path)
    headers = [str(h) for h in _need(v.get("headers", []), list, f"{path}.headers")]
    rows = _rows(v.get("rows", []), f"{path}.rows")
    kw = {}
    if v.get("aligns"):
        kw["aligns"] = list(v["aligns"])
    if v.get("col_widths"):
        kw["col_widths"] = [float(w) for w in v["col_widths"]]
    doc.data_table(headers, rows, **kw)


def _blk_figure(doc, v, path):
    _need(v, dict, path)
    png = v.get("png")
    if png is None:
        raise SpecError(f"{path}.png: a figure block needs PNG bytes")
    if isinstance(png, str):                       # base64, as JSON must encode it
        import base64
        png = base64.b64decode(png.split(",", 1)[-1])
    doc.figure(png, str(v.get("caption", "")), str(v.get("source", "")))


def _blk_callout(doc, v, path):
    _need(v, dict, path)
    doc.callout(str(v.get("title", "")), str(v.get("text", "")))


def _blk_page_break(doc, v, path):
    doc.add_page()


BLOCKS = {
    "text": _blk_text,
    "bullets": _blk_bullets,
    "heading": _blk_heading,
    "metrics": _blk_metrics,
    "table": _blk_table,
    "figure": _blk_figure,
    "callout": _blk_callout,
    "page_break": _blk_page_break,
}


def render(spec: dict, blocks: dict | None = None) -> bytes:
    """Render a document spec to PDF bytes.

    `blocks` adds or overrides block renderers, each a `(doc, value, path)`
    callable, reached from a spec via `{"custom": ...}` or by shadowing a
    built-in name.
    """
    _need(spec, dict, "spec")
    registry = dict(BLOCKS)
    if blocks:
        registry.update(blocks)

    brand = _need(spec.get("brand", {}) or {}, dict, "brand")
    doc = ReportDocument(
        lang=str(spec.get("lang", "en")),
        doc_ref=str(brand.get("doc_ref", "") or spec.get("title", "")),
        firm_name=str(brand.get("firm_name", "") or ""),
        primary_color=_hex(brand.get("primary"), (26, 46, 74)),
        accent_color=_hex(brand.get("accent"), (37, 99, 235)),
        section_rule_color=_hex(brand.get("section_rule"), (163, 200, 63)),
        theme=resolve_theme(brand.get("theme")),
    )
    doc.add_page()

    for si, section in enumerate(_need(spec.get("sections", []), list, "sections")):
        spath = f"sections[{si}]"
        _need(section, dict, spath)
        if section.get("title"):
            doc.section_title(str(section["title"]))
        for bi, block in enumerate(_need(section.get("blocks", []), list,
                                         f"{spath}.blocks")):
            bpath = f"{spath}.blocks[{bi}]"
            _need(block, dict, bpath)
            if not block:
                continue
            # One key per block keeps the spec readable and the error precise.
            name = next(iter(block))
            fn = registry.get(name)
            if fn is None:
                raise SpecError(
                    f"{bpath}: unknown block {name!r}. "
                    f"Known: {', '.join(sorted(registry))}")
            fn(doc, block[name], f"{bpath}.{name}")

    return bytes(doc.output())
