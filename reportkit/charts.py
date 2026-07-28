"""
reportkit.charts — turn a Plotly figure into brand-coloured PNG bytes.

**Optional.** `pip install "reportkit[charts]"`. Everything here imports fine
without Plotly or Kaleido installed — every plotly import is inside a function
body, deliberately, so that `import reportkit.charts` never drags a headless
Chrome into a project that only wants to hand over PNG bytes it already has.
The core's CI asserts plotly is absent and still imports this module.

Two things live here rather than in the core:

* **`FIG_HOOK`** — a ContextVar the host can set to intercept rasterisation.
  A live preview sets it to return a flat placeholder at the requested size; a
  test sets it to make renders hermetic. It sits here, with its only reader,
  and hosts must alias the *same object* rather than construct a second one.
* **The Kaleido session** — Kaleido drives a persistent Chrome, which is
  process-wide state. `kaleido_session()` reference-counts it under a lock so
  concurrent report builds can't tear the browser out from under each other,
  which produced complete-looking PDFs with every chart silently blank.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading
import warnings
from contextlib import contextmanager
from contextvars import ContextVar

from reportkit.color import remap_color, rgb_to_hue  # noqa: F401  (host re-exports)

# Fallback palette, used only when a caller passes no colours. Identical to the
# host's historical defaults — these reach real output, so they are values, not
# placeholders.
DEFAULT_PRIMARY   = (26, 46, 74)
DEFAULT_ACCENT    = (37, 99, 235)
DEFAULT_SECONDARY = (198, 148, 38)

# Set by a host to intercept figure rasterisation; see the module docstring.
# Signature: hook(fig, width, height, *colors) -> bytes | None. Returning None
# falls through to the real rasteriser.
FIG_HOOK: ContextVar = ContextVar("fig_hook", default=None)


@contextmanager
def kaleido_session():
    """Hold the shared Kaleido/Chrome server up for the duration of a build.

    Reference-counted: nested and concurrent builds share one browser, and it is
    torn down only when the last one leaves. Without the count, the first build
    to finish stopped the server that its neighbours were still using and their
    figures came back empty.
    """
    started = _acquire_kaleido()
    try:
        yield started
    finally:
        _release_kaleido()


def theme_figure(fig, primary_color: tuple, accent_color: tuple,
                 secondary_color: tuple = DEFAULT_SECONDARY, rebrand=None):
    """Apply the print theme to a Plotly figure before rasterising: white
    backgrounds, report typography, light gridlines, no Plotly logo — and remap
    the source navy/blue palette onto the branding colours (no-op for the default
    palette). Semantic colours (red KI line, grey autocall, orange coupon) and
    the fan-chart band alpha hierarchy are preserved by the injected `rebrand` callable.
    """
    try:
        if rebrand is not None:
            rebrand(fig, primary_color, accent_color, secondary_color)
    except Exception:
        pass
    try:
        fig.update_layout(
            # Transparent so the chart blends into its brand-tinted figure card
            # instead of stamping an opaque white rectangle that clashes with the
            # panel. fpdf2 composites the PNG's alpha over the card fill, so the
            # panel colour shows through the plot area and margins.
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            font=dict(family="IBM Plex Sans, Arial, sans-serif", size=10, color="#1a1a2e"),
            modebar_remove=["logo", "toImage", "sendDataToCloud"],
        )
        # Clean, understated legend: a single horizontal strip along the bottom
        # (clears the P1/P2.. observation labels pinned to the top of the path/fan
        # charts), no "variable" group title, muted slate text at a readable-but-
        # not-shouty size, no box. Replaces the heavy 13pt bold navy legend.
        # Only for charts that actually show a legend — a legend-less chart (the
        # correlation heatmap, the per-underlying price line) keeps its own tight
        # margins instead of reserving 78mm of empty space at the bottom.
        if getattr(fig.layout, "showlegend", None) is not False:
            fig.update_layout(
                legend=dict(
                    orientation="h",
                    yanchor="top", y=-0.18, xanchor="center", x=0.5,
                    title=dict(text=""),
                    font=dict(family="IBM Plex Sans, Arial, sans-serif",
                              size=11, color="#5b6675"),
                    bgcolor="rgba(0,0,0,0)", borderwidth=0,
                    itemsizing="constant",
                ),
                margin=dict(b=78),
            )
        # Axes: cool-grey, semi-transparent so gridlines stay legible on the
        # tinted card now that the opaque white plot background is gone (a near-
        # white grid would vanish against the panel). Per-axis ranges/tickformats
        # set in charts.py are untouched.
        fig.update_xaxes(linecolor="rgba(71,85,105,0.35)",
                         gridcolor="rgba(71,85,105,0.14)",
                         zerolinecolor="rgba(71,85,105,0.35)")
        fig.update_yaxes(linecolor="rgba(71,85,105,0.35)",
                         gridcolor="rgba(71,85,105,0.14)",
                         zerolinecolor="rgba(71,85,105,0.35)")
    except Exception:
        pass


# Kaleido v1 drives an external Chrome/Chromium (unlike the self-contained
# v0.2.x). On a headless host with no browser — every export raises and the
# report silently drops all figures. The Docker image installs `chromium` (and
# points kaleido at it via BROWSER_PATH); as a belt-and-suspenders fallback for
# other environments we attempt a one-time runtime Chrome download so the report
# still renders charts when the system package is missing. Guarded to try once.
_CHROME_FETCH_TRIED = False


def _ensure_chrome() -> None:
    """Best-effort: make sure Kaleido has a Chrome to drive. No-op on failure.

    Tries kaleido.get_chrome_sync() once (downloads Chromium into Kaleido's
    cache). Only runs once per process; safe when a system Chromium already
    exists (Kaleido prefers it and this is skipped after the first attempt)."""
    global _CHROME_FETCH_TRIED
    if _CHROME_FETCH_TRIED:
        return
    _CHROME_FETCH_TRIED = True
    try:
        import kaleido
        get_chrome = getattr(kaleido, "get_chrome_sync", None)
        if get_chrome is not None:
            get_chrome()
            print("[reportkit.charts] fetched Chromium for Kaleido")
    except Exception as exc:
        print(f"[reportkit.charts] Chrome fetch unavailable: {exc}")


# Persistent Kaleido server. Plotly's pio.to_image boots a fresh headless
# Chrome on EVERY call (~3s of startup each); a full report exports ~13 figures,
# so cold-booting per figure is ~40s of pure overhead. Starting Kaleido's sync
# server once keeps a single Chrome alive for the whole build — pio.to_image
# auto-detects the running server, so _fig_to_png itself needs no change — and
# the export collapses to one ~2.7s boot plus ~0.2s per figure (~5s total).
# generate_pdf_report starts it before rendering and tears it down in a finally,
# so the Chrome subprocess never lingers past a build. Best-effort: if the
# server can't start (no Chrome on a headless host), exports fall back to the
# per-call path in _fig_to_png unchanged.
def _start_kaleido_server() -> bool:
    """Start Kaleido's persistent sync server. Returns True on success."""
    try:
        import kaleido
        kaleido.start_sync_server()
        return True
    except Exception as exc:
        print(f"[reportkit.charts] persistent Kaleido server unavailable "
              f"({type(exc).__name__}: {exc}); exporting per figure")
        return False


def _stop_kaleido_server() -> None:
    """Tear down the persistent Kaleido server (and its Chrome subprocess)."""
    try:
        import kaleido
        kaleido.stop_sync_server()
    except Exception:
        pass


# The Kaleido server is per-PROCESS, but report builds are per-REQUEST and the
# API serves them concurrently. Started and stopped naively, the first build to
# finish tears Chrome out from under every other one still running, and their
# remaining figures come back empty — a complete-looking PDF with no charts in
# it, which is the failure mode CLAUDE.md already warns about for the proof
# endpoint. Reference-count instead: the last build out turns off the lights.
_KALEIDO_LOCK = threading.Lock()
_KALEIDO_USERS = 0
_KALEIDO_UP = False


def _acquire_kaleido() -> bool:
    """Ensure the shared server is up and register this build as a user."""
    global _KALEIDO_USERS, _KALEIDO_UP
    with _KALEIDO_LOCK:
        if _KALEIDO_USERS == 0:
            _KALEIDO_UP = _start_kaleido_server()
        if not _KALEIDO_UP:
            return False
        _KALEIDO_USERS += 1
        return True


def _release_kaleido() -> None:
    """Deregister this build; stop the server only when it is the last one."""
    global _KALEIDO_USERS, _KALEIDO_UP
    with _KALEIDO_LOCK:
        if _KALEIDO_USERS <= 0:
            return
        _KALEIDO_USERS -= 1
        if _KALEIDO_USERS == 0 and _KALEIDO_UP:
            _stop_kaleido_server()
            _KALEIDO_UP = False


def fig_to_png(fig, width: int = 900, height: int = 500,
               primary_color: tuple = DEFAULT_PRIMARY,
               accent_color: tuple = DEFAULT_ACCENT,
               secondary_color: tuple = DEFAULT_SECONDARY,
               rebrand=None) -> bytes | None:
    """Rasterise a Plotly figure to PNG bytes at 3× scale (~300 dpi equivalent).

    Applies `_theme_figure` before rendering so all charts use the report's
    branded color scheme and white background regardless of app theme.

    Returns None on failure, but logs why first — a swallowed exception here
    silently empties the whole report of charts, which is near-impossible to
    diagnose after the fact. The most common cause is a missing Chrome for
    Kaleido v1 on a headless deploy; we retry once after fetching one.
    """
    # Proof/preview interception. It has to happen HERE, not by putting bytes in
    # the `figures` dict, because the next line wraps whatever it was given in
    # go.Figure(). A placeholder must honour the requested size: figure() derives
    # its placement height from the image's aspect and only then tests whether
    # the block still fits, so a wrong aspect shifts every later page break and
    # the proof stops matching the real document's pagination.
    _hook = FIG_HOOK.get()
    if _hook is not None:
        _out = _hook(fig, width, height, primary_color, accent_color, secondary_color)
        if _out is not None:
            return _out

    import plotly.io as pio
    import plotly.graph_objects as go
    fig = go.Figure(fig)
    fig.update_layout(title=None, margin=dict(t=24, b=40))
    theme_figure(fig, primary_color, accent_color, secondary_color, rebrand=rebrand)
    # When the persistent server is running, plotly warns once per figure that
    # "kopts is ignored if using a server" — harmless (width/height/scale are
    # respected via the figure layout) but it floods the logs. Mute just that.
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message=".*kopts.*", category=UserWarning)
        try:
            return pio.to_image(fig, format="png", width=width, height=height, scale=3)
        except Exception as exc:
            print(f"[reportkit.charts] to_image failed ({type(exc).__name__}: {exc}); "
                  "retrying after Chrome fetch")
            _ensure_chrome()
            try:
                return pio.to_image(fig, format="png", width=width, height=height, scale=3)
            except Exception as exc2:
                print(f"[reportkit.charts] to_image failed again: {type(exc2).__name__}: {exc2}")
                return None
