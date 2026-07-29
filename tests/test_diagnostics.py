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

def test_a_malformed_colour_is_reported_through_the_same_channel():
    """One config, one place to look.

    This was `xfail(strict=True)` until C2: a bad colour raised a `UserWarning`,
    so a host that dutifully printed `brand.warnings` showed the operator
    nothing while the palette silently fell back to a default."""
    b = resolve({"primary_color": "#zz"})
    assert b.primary == B.DEFAULT_PRIMARY
    assert any("primary_color" in w for w in b.warnings)


def test_one_bad_colour_does_not_cost_the_others():
    """The VALUE behaviour, which C2 must not disturb while it moves the message."""
    b = resolve({"primary_color": "#zz", "accent_color": "#20948A"})
    assert b.primary == B.DEFAULT_PRIMARY
    assert b.accent == (32, 148, 138)


def test_the_package_no_longer_reaches_for_the_warnings_machinery():
    """Two channels survive the freeze: `logging` for operational events,
    `Brand.warnings` for config validation. A third — `warnings.warn` — meant a
    host had to install a filter to see what its own config had been told."""
    import reportkit.branding as _b
    assert not hasattr(_b, "warnings"), "warnings is back in branding"
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        resolve({"primary_color": "#zz", "nonsense": 1,
                 "logo_url": "https://x.invalid/l.png"})
    assert caught == [], f"package raised UserWarnings: {[str(c.message) for c in caught]}"


def test_diagnostics_do_not_duplicate_across_channels():
    """A single defect should be reported once. `logo_url` currently prints AND
    appends to `warnings`; this pins the LIST as the contract so the migration
    can drop the print without anyone claiming the print was the API."""
    b = resolve({"logo_url": "https://x.invalid/l.png"})
    hits = [w for w in b.warnings if "logo_url" in w]
    assert len(hits) == 1, f"reported {len(hits)} times in one channel: {hits}"


# ── logging ──────────────────────────────────────────────────────────────────

def test_the_package_is_silent_until_a_host_opts_in():
    """A library must not print to stdout and must not configure logging for its
    host. NullHandler is the contract: nothing is emitted until someone attaches
    a handler."""
    import logging
    lg = logging.getLogger("reportkit")
    assert any(isinstance(h, logging.NullHandler) for h in lg.handlers)


def test_nothing_writes_to_stdout(capsys):
    """`print` was the diagnostic channel for 28 messages. It is not any more —
    and a host on Cloud Run cares, because stdout and stderr get different
    severities."""
    resolve({"primary_color": "#zz", "logo_file": "nope.png",
             "logo_url": "https://x.invalid/l.png", "nonsense": 1})
    assert capsys.readouterr().out == ""


def test_a_degrade_is_logged_at_a_level_that_can_be_filtered(caplog):
    """The point of levels: an operator can ask for warnings without drowning in
    per-image debug lines."""
    import logging
    with caplog.at_level(logging.DEBUG, logger="reportkit"):
        resolve({"logo_base64": "not-valid-base64!!"})
    assert any(r.levelno >= logging.WARNING for r in caplog.records), \
        "an undecodable logo must be reported above DEBUG"


def test_an_opt_in_policy_is_not_reported_as_a_failure(caplog):
    """`logo_file` with no `root` was logged as "unusable" — blaming the file for
    a policy decision, and contradicting the `Brand.warnings` entry from the
    same call, which says the right thing."""
    import logging
    with caplog.at_level(logging.DEBUG, logger="reportkit"):
        b = resolve({"logo_file": "logo.png"})
    assert not [r for r in caplog.records
                if r.levelno >= logging.WARNING and "unusable" in r.getMessage()]
    assert any("logo_file" in w and "root" in w for w in b.warnings)
