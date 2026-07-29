# reportkit

Build **themed, brandable PDF reports** in Python. Drop it into a project, hand
it a palette and some content, and get a document that looks designed rather
than generated.

It grew out of a structured-note analytics app whose report generator was worth
more than the app it lived in. This is that generator with the finance taken out.

```bash
pip install "reportkit @ git+https://github.com/diegogomezpy/report_maker@v1.1.0"
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
doc.figure(png_bytes, "Cumulative return", "Acme, monthly")   # any PNG bytes
doc.callout("Note", "Past performance is not indicative of future results.")

open("report.pdf", "wb").write(bytes(doc.output()))
```

`png_bytes` is whatever your plotting library produced — reportkit takes PNG
bytes and never imports a chart library. `examples/hello.py` is this same
report, runnable, with a `placeholder_png` helper so it needs no data:

```bash
python examples/hello.py    # writes hello.pdf
```

Same content, different identity — change the three colours and the theme name,
not the code.

Requires Python 3.12+.

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
| `reportkit.color` | CSS colour parsing, hue-aware palette remapping, and the default palette. In the core, not behind the charts extra — recolouring artwork is string rewriting, not plotting. |
| `reportkit.text` | Sanitising strings for the PDF text layer, including the Latin-1 path a Helvetica fallback needs. |
| `reportkit.charts` | *(extra)* Re-colour a Plotly figure into the brand palette and rasterise it. |
| `reportkit.testing` | Deterministic inputs for rendering under test: seeded stand-in imagery, a figure stub that honours the requested pixel size, and `sample_document()` — a report touching every block, including a table long enough to split and one that carries inline logos. `rasterise()` needs `pypdfium2` or PyMuPDF (both in the `dev` extra). |

## Design

- **Content is imperative, look is declarative.** You drive the document; the
  theme is swappable data. No chrome knows anything about your domain.
- **Palette-driven.** Every identity colour derives from the brand palette, so a
  new brand inherits a whole theme rather than a stylesheet to fill in.
- **Light core.** `fpdf2` and `Pillow`. Charts are an extra
  (`pip install "reportkit[charts]"`) because Kaleido drives a headless Chrome
  and most projects would rather hand over a PNG.
- **Tested where it counts.** Colour parsing, the image security guards (path
  containment, URL schemes, decompression bombs), font registration, the spec
  validator, the diagnostics contract and the outline tree all have direct
  tests. On top of those, `reportkit.testing` builds a sample document that
  exercises every block, and two suites guard it: a per-page **pixel golden**,
  and a keep-together **pagination sweep** over table size × starting height.
  Both are checked by MUTATION, which is the only way to know a regression test
  earns its runtime — a deliberately broken `table_room` must turn each of them
  red. The first draft of each did not, and both were rewritten:

  | mutation | pagination sweep | pixel golden |
  | --- | --- | --- |
  | `SPLIT_ROOM` 40 → 20 | 13 failures | — |
  | `table_room` capped at 130mm | 13 failures | — |
  | ignore the claim in `data_table` | 1 failure | — |
  | table row height 8.0 → 8.4 | — | 3 failures |
  | `table_room` raises | — | 4 failures |

## Status

`1.1.0` — extracted from a working production report generator, which still
uses it. **The API is frozen**: names will not move again without a major
version. See [CHANGELOG.md](CHANGELOG.md) for the 0.7 → 1.0 migration table.

Known gaps, so you can judge fit:

- **Two diagnostic channels, and you must choose where they go.** `logging` for
  operational events (silent behind a `NullHandler` until you attach one) and
  `Brand.warnings` for config validation. `logging` writes to stderr by default;
  if your platform grades stderr as an error (Cloud Run does), attach your own
  stdout handler to the `reportkit` logger.
- **`reportkit.spec` covers a subset of the imperative API.** Blocks not in its
  registry need `render_spec(spec, blocks={...})`.

Closed since `0.2.x`, in case you read an older copy of this file: a brand
config is now applied whole (`0.3.0`), covers and back pages have a builder
(`0.4.0`), chapter numbering plus the contents list are in (`0.5.0`), the
package has its own pixel and pagination guards (`0.6.0`), and PDF bookmarks,
clickable contents rows and `logging` all arrived in (`0.7.0`).

## Writing a theme

A theme draws through a small protocol the document exposes. If you subclass
`ReportTheme` or hand `SpecTheme` your own spec, these are the names you can
rely on — everything else on the document is an implementation detail:

| | |
| --- | --- |
| `pdf.t(key)` | a chrome label in the document's language |
| `pdf.safe(text)` | sanitise for the PDF text layer |
| `pdf.sf(size, weight)` | set font by semantic weight |
| `pdf.fit_font(...)` | shrink a size until the text fits |
| `pdf.eyebrow(...)` | the small tracked-out label |
| `pdf.ink` / `lime` / `teal` / `amber` / `panel` / `muted` / `body_ink` / `rule_soft` | palette-derived tokens |
| `pdf.primary_color` / `accent_color` / `section_rule_color` | the brand palette |

Frozen at 1.0: these names will not move again without a major version.

## Licence

MIT — see [LICENSE](LICENSE). Use it in anything, including closed-source and
commercial work; just keep the copyright notice.

Bundled IBM Plex Sans is separately under the SIL Open Font License 1.1
(`reportkit/fonts/OFL.txt`), which permits redistribution as long as that
licence travels with the font files.
