"""The positional image-slot algorithm — the branch table.

These are the subtlest ~45 lines in brand-config handling and, in the
application this was extracted from, three of their branches were executed by
NO test: every brand fixture there sets both an explicit cover and an explicit
back image, so the positional path, the deliberate-blank sentinel and the
one-photo fallback were all covered by luck rather than by design.

Bytes here are sentinels (`b"A"`, `b"B"`) rather than real images, which is the
point: the algorithm is pure, so its whole branch table is testable without a
PDF, a font or a decode.
"""
from __future__ import annotations

import pytest

from reportkit.branding import ImageRoles, assign_images, decode_slots

A, B, C = b"A", b"B", b"C"


def slots(*items):
    """Build slots without base64 — `decode` is the seam that makes this cheap."""
    return decode_slots(list(items), decode=lambda x: x or None)


# ── decode_slots ─────────────────────────────────────────────────────────────

def test_a_blank_holds_its_position():
    """The whole reason this is not a list comprehension. If a blank vanished,
    the next photo would shift up into the cover role and a brand that chose
    'no cover photo' would get one."""
    assert slots("", A) == [None, A]
    assert slots(A, "", B) == [A, None, B]


def test_real_images_dedupe_but_blanks_do_not():
    assert slots(A, A, B) == [A, B]
    assert slots("", "", A) == [None, None, A]


def test_a_bare_string_is_a_one_entry_pool():
    """Hand-written configs do this."""
    assert decode_slots(A, decode=lambda x: x or None) == [A]


@pytest.mark.parametrize("empty", [None, [], "", 0])
def test_no_pool_is_no_slots(empty):
    assert decode_slots(empty) == []


def test_undecodable_entries_become_blanks_not_exceptions():
    """A corrupt photo should cost a photo, not the report."""
    assert decode_slots(["!!!not base64!!!", ""]) == [None, None]


# ── assign_images: the positional roles ──────────────────────────────────────

def test_slot_zero_is_the_cover_and_slot_one_is_the_back():
    r = assign_images(slots(A, B, C))
    assert (r.cover, r.back) == (A, B)
    assert r.fillers == [C], "cover/back must not reappear inside the report"


def test_explicit_images_win_over_slots():
    r = assign_images(slots(A, B), cover=C, back=A)
    assert (r.cover, r.back) == (C, A)
    assert r.fillers == [B]


def test_a_blank_cover_slot_is_honoured():
    """Slot 0 blank = 'themed background, no photo'. It must NOT promote slot 1."""
    r = assign_images(slots("", A))
    assert r.cover is None
    assert r.back is A


def test_a_blank_back_slot_is_honoured():
    """Distinct from having no back slot — see the next test."""
    r = assign_images(slots(A, ""))
    assert (r.cover, r.back) == (A, None)


def test_one_photo_reuses_it_for_the_back():
    """No SECOND SLOT AT ALL is different from a blank second slot: a one-photo
    brand should still get a back page rather than a bare one."""
    r = assign_images(slots(A))
    assert (r.cover, r.back) == (A, A)


def test_the_explicit_cover_is_truthiness_tested_not_sentinel_tested():
    """A deliberate asymmetry, preserved because it is current behaviour: the
    blank sentinel is honoured for SLOTS but not for the explicit key, so an
    explicit-but-blank cover falls through to slot 0."""
    r = assign_images(slots(A, B), cover=None)
    assert r.cover is A, "explicit blank should fall through to slot 0"


# ── assign_images: the filler pool ───────────────────────────────────────────

def test_fillers_exclude_whatever_cover_and_back_consumed():
    r = assign_images(slots(A, B, C, b"D"))
    assert r.fillers == [C, b"D"]


def test_fillers_fall_back_to_cover_and_back_when_nothing_is_left():
    """A two-photo brand still gets a filler band rather than an empty void."""
    r = assign_images(slots(A, B))
    assert r.fillers == [A, B]


def test_the_fallback_dedupes():
    r = assign_images(slots(A))
    assert r.fillers == [A], "cover == back must not be listed twice"


def test_blanks_never_reach_the_filler_pool():
    r = assign_images(slots(A, B, "", C))
    assert None not in r.fillers and r.fillers == [C]


def test_no_images_at_all_is_valid_and_empty():
    r = assign_images([])
    assert (r.cover, r.back, r.fillers) == (None, None, [])


# ── the whole table, as one grid ─────────────────────────────────────────────

@pytest.mark.parametrize("pool,cover,back,expect", [
    # pool           explicit cover / back      -> (cover, back, fillers)
    ([],             None, None,                (None, None, [])),
    ([A],            None, None,                (A,    A,    [A])),
    ([A, B],         None, None,                (A,    B,    [A, B])),
    ([A, B, C],      None, None,                (A,    B,    [C])),
    (["", A],        None, None,                (None, A,    [A])),
    ([A, ""],        None, None,                (A,    None, [A])),
    (["", ""],       None, None,                (None, None, [])),
    # An explicit cover does not CONSUME the pooled photo, so A stays a body
    # filler. Correct: A was never shown as the cover or the back page.
    ([A],            C,    None,                (C,    C,    [A])),
    ([A, B],         C,    None,                (C,    B,    [A])),
    ([A, B],         None, C,                   (A,    C,    [B])),
    ([A, A, B],      None, None,                (A,    B,    [A, B])),
])
def test_branch_table(pool, cover, back, expect):
    r = assign_images(slots(*pool), cover=cover, back=back)
    assert (r.cover, r.back, r.fillers) == expect


def test_image_roles_repr_is_readable_in_a_failure():
    """These assertions compare opaque byte blobs; the repr has to say something
    other than a wall of base64 when one fails."""
    text = repr(assign_images(slots(A, B, C)))
    assert "cover=<1b>" in text and "fillers=[<1b>]" in text
