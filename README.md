# reportkit

Build **themed, brandable PDF reports** in Python. Drop it into a project, hand
it a palette and some content, and get a document that looks designed rather
than generated.

It grew out of a structured-note analytics app whose report generator was worth
more than the app it lived in. This is that generator with the finance taken out.

```bash
pip install "reportkit @ git+https://github.com/diegogomezpy/report_maker@v0.5.0"
```

## Hello, report

```python
from reportkit import ReportDocument, resolve_theme

doc = ReportDocument(firm_name="Acme Capital",
                     primary_color=(11, 59, 46),
                     accent_color=(32, 148, 138),
                     section_rule_color=(163, 200, 63),
                     theme=resolve_theme("mercator"))     # or "hexagon"
doc.add_page()
doc.section_title("Performance")
doc.metric_band([("Net return", "8.4%"), ("Volatility", "11.2%"), ("Sharpe", "0.74")])
doc.subsection("Holdings")
doc.data_table(["Asset", "Weight", "Return"],
               [["Equities", "62%", "+11.1%"], ["Credit", "28%", "+3.9%"]])
doc.figure(png_bytes, "Cumulative return", "Acme, monthly")
doc.callout("Note", "Past performance is not indicative of future results.")

open("report.pdf", "wb").write(bytes(doc.output()))
```

Runnable as `examples/hello.py`. Same content, different identity — change the
three colours and the theme name, not the code.

## Or describe the document as data

```python
from reportkit import render_spec

pdf = render_spec({
    "brand": {"firm_name": "Acme Capital", "primary": "#0B3B2E", "theme": "mercator"},
    "sections": [
        {"title": "Performance", "blocks": [
            {"metrics": [["Net return", "8.4%"], ["Sharpe", "0.74"]]},
            {"table": {"headers": ["Asset", "Weight"],
                       "rows": [["Equities", "62%"]]}},
            {"callout": {"title": "Note", "text": "Not investment advice."}},
        ]},
    ],
})
```

Useful when a report's shape comes from config, a UI, or another service rather
than from Python you control. Blocks: `text`, `bullets`, `heading`, `metrics`,
`table`, `figure`, `callout`, `page_break` — plus your own, passed as
`render_spec(spec, blocks={"gauge": draw_gauge})`, because there is always one
bespoke drawing and it should not cost you the other 95% of the document.

A spec is data, so it is treated as untrusted: a malformed one raises
`SpecError` naming the path (`sections[1].blocks[0].table.rows`) instead of
failing somewhere inside the PDF engine.

## What you get

| Module | Responsibility |
| --- | --- |
| `reportkit.document` | `ReportDocument` — the themed builder. Covers, section heads, tables, metric bands, figures, callouts, body copy, and the pagination rules that keep a heading with its content. |
| `reportkit.theme` | The visual identity: `ReportTheme`, the declarative `SpecTheme`, palette-derived tokens, shape/gradient primitives, and the theme registry. Two themes ship: `mercator` (clean, editorial) and `hexagon` (chamfered, dark mastheads). |
| `reportkit.branding` | Resolving a brand: palette, logos, cover imagery, fonts, copy overrides. |
| `reportkit.outline` | Chapter numbering, the contents list, and headings that draw only if something follows them. One place decides a chapter's number; the body and the contents page both read it. |
| `reportkit.cover` | Full-bleed pages. `full_bleed()` is a context manager over the open / paint / photo / tint order a cover has to get right — every step of which fails silently when it is done wrong. |
| `reportkit.fonts` | Font registration. Ships IBM Plex Sans; points at your licensed brand faces when you have them. |
| `reportkit.images` | Fetch, sanitise and embed images safely — including refusing decompression bombs and non-HTTP URLs. |
| `reportkit.spec` | The declarative layer: a document spec (dict/JSON) → a rendered PDF. |
| `reportkit.charts` | *(extra)* Re-colour a Plotly figure into the brand palette and rasterise it. |

## Design

- **Content is imperative, look is declarative.** You drive the document; the
  theme is swappable data. No chrome knows anything about your domain.
- **Palette-driven.** Every identity colour derives from the brand palette, so a
  new brand inherits a whole theme rather than a stylesheet to fill in.
- **Light core.** `fpdf2` and `Pillow`. Charts are an extra
  (`pip install "reportkit[charts]"`) because Kaleido drives a headless Chrome
  and most projects would rather hand over a PNG.
- **Tested where it counts.** Colour parsing, the image security guards (path
  containment, URL schemes, decompression bombs), font registration and the
  spec validator all have direct tests. A per-page pixel golden for the document
  itself is **not here yet** — it currently lives in the application this was
  extracted from, which means `reportkit`'s own pagination is guarded downstream
  rather than in this repo. That is the top item on the roadmap.

## Status

`0.5.0` — extracted from a working production report generator, which still
uses it. The API is young and will move before `1.0`.

Known gaps, so you can judge fit:

- **No golden of its own.** The pixel and pagination guards for this code live
  in the application it was extracted from, so `reportkit`'s own keep-together
  rules are proven downstream rather than here. Being fixed next; until then,
  treat the pagination constants as load-bearing and change them carefully.
- **No PDF bookmarks.** `start_section` is a pagination helper and shadows
  fpdf2's outline API of the same name, so the document tree a reader shows in
  its sidebar is not built. Renaming it is a breaking change held for `1.0`.
- **Diagnostics go to `print`.** There is no logger; a host that wants brand
  warnings in its log has to capture stdout.

Closed since `0.2.x`, in case you read an older copy of this file: a brand
config is now applied whole (`0.3.0`), covers and back pages have a builder
(`0.4.0`), and chapter numbering plus the contents list are in (`0.5.0`).

## Licence

MIT — see [LICENSE](LICENSE). Use it in anything, including closed-source and
commercial work; just keep the copyright notice.

Bundled IBM Plex Sans is separately under the SIL Open Font License 1.1
(`reportkit/fonts/OFL.txt`), which permits redistribution as long as that
licence travels with the font files.
