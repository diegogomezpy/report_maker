# Bundled fonts

## IBM Plex Sans

`IBMPlexSans-*.ttf` in this directory are **IBM Plex Sans**, © IBM Corp,
licensed under the **SIL Open Font License, Version 1.1**.

The full licence text is in **`OFL.txt`** alongside this file, verbatim from the
upstream distribution — the OFL requires it to travel with the fonts, so keep it
in any copy, wheel or vendored drop of this package.

Upstream: https://github.com/IBM/plex

reportkit bundles them so that a fresh install renders correct text with no
setup. Without a Unicode font, fpdf2 falls back to its built-in Helvetica, which
is Latin-1 only and mangles anything outside it (including ordinary Spanish and
typographic punctuation).

Note the OFL's Reserved Font Name clause: "Plex" is reserved, so a *modified*
build of these files must be renamed. Shipping them unmodified, as here, is
fine.

## Brand fonts

`reportkit/fonts/brand/` is **gitignored on purpose**. A host application points
reportkit at its own licensed typefaces at runtime (see `reportkit.fonts`); they
are the host's assets and must never be vendored into a reusable library.
