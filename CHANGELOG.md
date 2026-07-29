# Changelog

Notable changes to `reportkit`. Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
versioning is [semver](https://semver.org/). **The API is frozen at 1.0** — names
will not move again without a major version.

## [1.1.0] — 2026-07-29

### Removed

- **Watermarks, as a concept.** The uploaded watermark image, the drawn
  hex-cluster marks, the faint sigil washes, `resolve_watermark`, `_wm_image`,
  `pdf.watermark`, `Brand.watermark_image` and the six drawing call sites across
  mastheads, chapter dividers, empty-space fillers and the cover column.

  The `watermark*` keys stay in `KNOWN_KEYS` deliberately — inert, but
  recognised, so a brand config saved before this release does not start warning
  about keys it was told to write. A theme spec asking for `"watermark"` or
  `"hexCluster"` decoration now draws nothing rather than failing.

  Void fillers default to `accentKeyline`. One golden case moved
  (`hexagon/imagery` — the only fixture that drew a mark), re-baselined.

## [1.0.0] — 2026-07-29

**The API is frozen.** Renames, deletions and signature changes only — no new
behaviour, and no moved pixels. The deliverable is that the host application's
20-document byte fingerprint passed with **no re-baseline**, which proves this
release changed names and nothing else.

### Removed

- **`ReportDocument.start_section`.** The 0.7 deprecation shim is gone, and the
  name belongs to `FPDF.start_section` again — which is what builds the outline
  and what `write_html()` calls for `<h1>`..`<h6>`. `ReportDocument.start_section
  is FPDF.start_section` is now asserted by a test.
  **Use `open_section(text, min_room, level)`.**
  A missed call site does NOT raise: it resolves to the inherited method,
  registers a level-0 bookmark and draws no heading. Grep for the bare name.
- The 0.7 underscore aliases: `_table_room`, `_TBL_ROW_H`, `_TBL_HEAD_H`,
  `_TBL_PAD`, `_PAGE_CAP`, `_HEAD_ROOM`, `_SPLIT_ROOM`.
- `reportkit.text._safe` (now `sanitise`) and `_EMOJI_STRIP` (now `EMOJI_STRIP`).

### Changed — renames

The theme-author protocol loses its underscores. A theme draws THROUGH these,
so freezing them as private would have been the wrong contract to lock in:

| was | is |
| --- | --- |
| `doc._sf` | `doc.sf` |
| `doc._safe` | `doc.safe` |
| `doc._eyebrow` | `doc.eyebrow` |
| `doc._fit_font` | `doc.fit_font` |
| `doc._head_claimed` | `doc.head_claimed` |
| `doc._decorate_void`, `_decorate_void_photo` | `decorate_void`, `decorate_void_photo` |
| `doc.full_bleed_page` | `doc.full_bleed` |
| `doc.cover_logo()`, `cover_sigil()`, `cover_left_photo()` | `draw_cover_logo()`, `draw_sigil()`, `draw_left_photo()` |
| `spec.render` | `spec.render_spec` |
| `images._cover_crop` | `images.cover_crop_uncached` |

The cover verbs mattered because `cover_logo()` sat beside the DATA attribute
`cover_logo_bytes` that `apply_brand` writes — a verb and a noun one character
apart.

### Changed — signatures

- **`resolve_color(pdf, ref)`** — was `(ref, pdf)`. Every other pdf-taking
  function in the package puts `pdf` first, and argument order is precisely
  what a freeze locks in. 33 call sites; three needed hand-swapping because the
  first argument was a conditional expression.
- **`ReportDocument.__init__` is keyword-only after `doc_ref`.** It took 17
  positional parameters with `brand` last, while `brand` overwrites seven of the
  others. This is what buys the freedom to deprecate those seven later.
- `firm_name` defaults to `""`, not a host's firm name.
- **`labels` miss sentinel is `None`, and only `None`.** `t()` also used to
  treat "the table returned the key itself" as a miss, so a host whose
  vocabulary legitimately maps `figure_word` to `"figure_word"` silently got
  reportkit's word instead of its own.

### Added

- `install_figure_hook` / `reset_figure_hook` / `figure_hook` — the supported
  way to reach `charts.FIG_HOOK`, whose **identity** is the contract. A host
  aliasing the ContextVar and `.set()`-ing through the alias depends on there
  being exactly one object; binding a second silently disables interception,
  which in the host that shipped this meant a real headless Chrome in CI.
- **Every module has an `__all__`.** `from reportkit.document import *` used to
  re-export `FPDF`, `build_tokens`, `resolve_theme` and `_safe`.

### Fixed

- `__version__` falls back to `0.0.0+unknown`, which compares lower than any
  release. It was `0.0.0+source` — returned from exactly the install shape the
  host uses (`git+…@tag`), so a consumer gating on `__version__ >= "1.0"` got a
  false negative and silently took the 0.x branch.

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
