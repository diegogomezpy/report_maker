# Changelog

Notable changes to `reportkit`. Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
versioning is [semver](https://semver.org/), with the caveat that **the API is not
frozen until 1.0** — minor versions before then may move names, and each one says so.

## [Unreleased] — towards 1.0

1.0 is a **rename-and-freeze release**: no new behaviour, no moved pixels. Its
deliverable is that the host application's 20-document byte fingerprint passes
with no re-baseline, which proves the release changed names and nothing else.

Planned, with old → new in [Upgrading to 1.0](#upgrading-to-10) below:

- The theme-author protocol loses its underscores: `_sf` → `sf`, `_safe` → `safe`,
  `_eyebrow` → `eyebrow`, `_fit_font` → `fit_font`. These are not internals — a
  theme draws through them, so a freeze must not lock them in as private.
- `ReportDocument.start_section` (the 0.7 deprecation shim) is **deleted**. This
  is what finally returns the name to `FPDF.start_section`.
- `resolve_color(ref, pdf)` → `resolve_color(pdf, ref)`, matching every other
  `pdf`-taking function in the package.
- `ReportDocument.__init__` takes keyword-only arguments after `doc_ref`.
- The underscore aliases added in 0.7 (`_table_room`, `_TBL_*`, `_PAGE_CAP`,
  `_HEAD_ROOM`, `_SPLIT_ROOM`) are removed.
- Every module gets an `__all__`, so `from reportkit.x import *` stops
  re-exporting `FPDF` and friends.

## [0.7.0] — 2026-07-29

The release that made the package honest about what it does and how it reports.

### Added

- **PDF bookmarks.** `ReportDocument` builds the outline tree a reader shows in
  its sidebar. Registered from `section_title`, `secondary_head`,
  `section_divider`, `subsection` and `open_section`; `bookmark(title, level)` is
  public for pages no heading hook sees (covers, back pages); `outline=False`
  opts out.
- **A clickable contents page.** `link_for()` plus `contents_list(link=)`; heads
  get a link region. `unbound_links()` reports rows whose heading never appeared,
  which fpdf would otherwise resolve silently to page 1.
- `open_section()` — the pagination helper's real name (see Deprecated).
- `reportkit.testing` now exercises `logo_row_table` and passes
  `min_room=table_room(n)`, so the goldens reach the reservation chain.
- `builtin_spec(name)` and `chrome_labels()` — copies of package state that used
  to be handed out by reference.
- The pagination contract is public: `table_room`, `TBL_ROW_H`, `TBL_HEAD_H`,
  `TBL_PAD`, `PAGE_CAP`, `HEAD_ROOM`, `SPLIT_ROOM`, `SECTION_ROOM`. Underscore
  aliases remain for one release.
- `unknown_keys()`; `validate_branding()` now **returns** its messages.

### Changed

- **All 28 `print` calls became `logging`**, at levels chosen from what each
  event means. `__init__` installs a `NullHandler`, so the package is silent
  until a host opts in. Note `print` went to stdout and `logging` defaults to
  stderr — a host on a platform that grades stderr as ERROR (Cloud Run) should
  attach its own stdout handler.
- **`warnings.warn` is gone from the package.** Config defects now reach
  `Brand.warnings`, the channel the docstring always promised. Two channels
  survive: `logging` for operational events, `Brand.warnings` for config.
- `DEFAULT_PRIMARY` / `DEFAULT_ACCENT` / `DEFAULT_SECONDARY` live in
  `reportkit.color`, re-exported from `branding` and `charts` for one release.
- `ImageRoles` is a frozen dataclass; `fillers` is a tuple.
- `SpecTheme`, `_merge_spec` and `register_theme` deep-copy their spec.

### Fixed

- **`logo_row_table` never consumed the heading claim**, so the next
  `data_table` on the page skipped its own keep-together rule — spending a
  reservation made for a different block.
- **The core imported from the optional extra**: `document.py` took its palette
  defaults from `charts.py`. Worse, the same three constants were defined twice,
  identically, in `branding` and `charts`.
- `spec.render` defaulted the section rule to a hard-coded lime that was a
  **test-fixture colour**, disagreeing with the two other places that default it
  to the accent. *(Behaviour change for `render_spec` callers who omit
  `brand.section_rule`.)*
- `resolve_theme("hexagon").spec` **was** the module global, so editing it was a
  process-wide edit — and `hexagon`/`cadiem` are one object, so editing one
  re-themed the other.
- `fig_to_png` used `warnings.catch_warnings()`, which snapshots and restores the
  process-global filter list and is not thread-safe, in a module that locks
  Chrome precisely because hosts render concurrently.
- `logo_file` with no `root` was logged as "unusable" — blaming the file for a
  policy decision, and contradicting the `Brand.warnings` entry from the same call.
- `logo_url ignored` was reported three times: printed, appended to
  `Brand.warnings`, and printed again by the host.
- 21 dead imports; two duplicate `ReportTheme` hook definitions where the first
  was unreachable. ruff `F401`/`F811` now runs in CI.

### Deprecated

- `ReportDocument.start_section` → **`open_section`**. It shadowed
  `FPDF.start_section`, which is how fpdf2 builds the outline — while it
  shadowed, no document could have bookmarks and `write_html()` silently got a
  pagination decision instead of a heading. The shim warns and will be removed
  in 1.0. If you use `reportkit.outline.lazy_section`, you are affected without
  naming the method: it calls it for you.

## [0.6.0]

The package gained its own guards. `reportkit.testing` (deterministic imagery, a
figure stub that honours the requested pixel size, `sample_document()`), a
per-page pixel golden, and a keep-together pagination sweep over table size ×
starting height — all verified by mutation.

That mutation testing found a real defect: `_table_room` reserved using
`TBL_ROW_H` while `data_table` **drew** with a hard-coded `8`. Two copies of one
quantity, agreeing only by coincidence.

## [0.5.0]

`reportkit.outline`: `plan_chapters` (the single place a chapter number is
decided), `fit_rows` / `shed_to_fit` / `contents_list` (shrink, then shed
optional sub-sections biggest-first — numbered chapters are never shed), and
`lazy_section` / `lazy_divider` (a heading exists exactly when something
followed it).

## [0.4.0]

`reportkit.cover`: `full_bleed()` as a context manager over the open / paint /
photo / tint order a cover has to get right — every step of which fails silently
when done wrong. Also fixed a `getattr(pdf, "cover_overlay_color", ...)` whose
default never fired, because the attribute existed and was `None`.

## [0.3.0]

A brand config is applied **whole**. `Brand` (frozen), `branding.resolve()`,
`ReportDocument(brand=…)` reading the palette before token derivation, and
`apply_brand()` owning three orderings that fail silently when wrong.

Before this, `KNOWN_KEYS` recognised 51 keys and the module applied two: a brand
handed over its cover art, sigil, watermark and copy and got back colours and a
logo. `APPLIED_ATTRS` plus a test asserting every brand attribute `theme.py`
reads is one `apply_brand` writes keeps that gap closed.

## [0.2.x]

Network access off by default (`logo_url` requires an explicit `fetch`), `py.typed`,
the version single-sourced from distribution metadata, and the positional
image-slot algorithm frozen as pure functions.

## [0.1.0]

Extracted from a structured-note analytics application, one slice at a time,
each guarded by a byte-level fingerprint of that application's rendered reports.

---

## Upgrading to 1.0

*(This section is written as 1.0 lands. The 0.7 → 1.0 step is renames only —
if a name below still resolves, you are on 0.7.)*

| 0.7 | 1.0 |
| --- | --- |
| `ReportDocument.start_section(text, min_room)` | `open_section(text, min_room, level)` |
| `doc._sf(size, weight)` | `doc.sf(size, weight)` |
| `doc._safe(text)` | `doc.safe(text)` |
| `doc._eyebrow(...)` | `doc.eyebrow(...)` |
| `doc._fit_font(...)` | `doc.fit_font(...)` |
| `reportkit.text._safe` | `reportkit.text.sanitise` |
| `document._table_room` | `document.table_room` |
| `document._TBL_ROW_H` (and `_TBL_HEAD_H`, `_TBL_PAD`, `_PAGE_CAP`, `_HEAD_ROOM`, `_SPLIT_ROOM`) | same names without the underscore |
| `resolve_color(ref, pdf)` | `resolve_color(pdf, ref)` |
| `spec.render` | `spec.render_spec` |
| `images._cover_crop` | `images.cover_crop_uncached` |

**`start_section` deserves care.** Deleting the shim makes `FPDF.start_section`
reachable again — so a call site you miss does **not** raise. It resolves to the
inherited method, registers a level-0 bookmark, and draws no heading. Grep for
the bare string; the only surviving hit should be `super().start_section(...)`
inside `_mark_outline`.
