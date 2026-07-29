"""What the library tells a caller when a brand config is partly unusable.

`Brand.warnings` is the one diagnostic a host actually consumes — the Structured
Note adapter prints every entry after `resolve()`. It had no test at all, which
is how its docstring came to promise a case it does not deliver.

This file is written BEFORE the logging migration on purpose: it pins today's
behaviour so the migration has something to move against, and marks the one
promise that is currently false as `xfail` rather than quietly asserting the
weaker truth.
"""
from __future__ import annotations

import warnings

import pytest

pytest.importorskip("fpdf")

import reportkit.branding as B                       # noqa: E402


def resolve(cfg, **kw):
    return B.resolve(cfg, default_firm_name="Fallback", **kw)


# ── the degrade paths a host is expected to surface ──────────────────────────

def test_an_unknown_key_is_reported_and_costs_nothing_else():
    b = resolve({"nonsense": 1, "primary_color": "#0B3B2E"})
    assert any("nonsense" in w for w in b.warnings)
    assert b.primary == (11, 59, 46), "a bad key must not cost the good ones"


def test_the_network_is_opt_in_and_says_so():
    """`logo_url` without a `fetch` is the SSRF guard. Silence here means a
    brand's logo vanishes with no way to find out why."""
    b = resolve({"logo_url": "https://x.invalid/l.png"})
    assert b.logo is None
    assert any("logo_url" in w and "fetch" in w for w in b.warnings)


def test_path_access_is_opt_in_and_says_so():
    b = resolve({"logo_file": "logo.png"})
    assert b.logo is None
    assert any("logo_file" in w and "root" in w for w in b.warnings)


def test_a_clean_config_warns_about_nothing():
    """The corollary, and the one that catches a chatty regression: a valid
    brand must produce an empty list, or a host that prints warnings trains its
    operators to ignore them."""
    b = resolve({"firm_name": "Acme", "primary_color": "#0B3B2E",
                 "accent_color": "#20948A"})
    assert b.warnings == ()


# ── the promise that is not kept ─────────────────────────────────────────────

@pytest.mark.xfail(reason="C2: goes to warnings.warn, not Brand.warnings — the "
                          "docstring promises 'an unparseable colour' appears here",
                   strict=True)
def test_a_malformed_colour_is_reported_through_the_same_channel():
    """One config, one place to look. Today a bad colour raises a `UserWarning`
    instead, so a host that dutifully prints `brand.warnings` shows the operator
    nothing while the palette silently falls back to a default."""
    b = resolve({"primary_color": "#zz"})
    assert b.primary == B.DEFAULT_PRIMARY
    assert any("primary_color" in w for w in b.warnings)


def test_the_malformed_colour_still_degrades_correctly_today():
    """Whatever channel it uses, the VALUE behaviour is already right and must
    not regress while C2 moves the message."""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        b = resolve({"primary_color": "#zz", "accent_color": "#20948A"})
    assert b.primary == B.DEFAULT_PRIMARY
    assert b.accent == (32, 148, 138), "one bad colour must not cost the others"
    assert any("primary_color" in str(c.message) for c in caught)


def test_diagnostics_do_not_duplicate_across_channels():
    """A single defect should be reported once. `logo_url` currently prints AND
    appends to `warnings`; this pins the LIST as the contract so the migration
    can drop the print without anyone claiming the print was the API."""
    b = resolve({"logo_url": "https://x.invalid/l.png"})
    hits = [w for w in b.warnings if "logo_url" in w]
    assert len(hits) == 1, f"reported {len(hits)} times in one channel: {hits}"
