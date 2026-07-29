"""The declarative layer.

A spec is data, and data that describes a document usually came from somewhere
outside the program — a config file, a form, another service. So the interesting
tests are the malformed ones: the failure has to name the path, not die inside
fpdf2 with a stack trace about a float.
"""
from __future__ import annotations

import io

import pytest

pytest.importorskip("fpdf")
pypdfium2 = pytest.importorskip("pypdfium2")

from reportkit.spec import BLOCKS, SpecError, render_spec  # noqa: E402


def png(w=400, h=200) -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (w, h), (220, 226, 232)).save(buf, "PNG")
    return buf.getvalue()


def text_of(pdf: bytes) -> str:
    doc = pypdfium2.PdfDocument(pdf)
    return " ".join(" ".join(doc[i].get_textpage().get_text_range().split())
                    for i in range(len(doc)))


def test_a_minimal_spec_renders():
    out = render_spec({"sections": [{"title": "Performance", "blocks": [
        {"text": "The fund returned 8.4% net of fees."}]}]})
    assert out[:4] == b"%PDF"
    body = text_of(out)
    assert "Performance" in body and "8.4%" in body


def test_every_block_type_draws():
    out = render_spec({
        "brand": {"firm_name": "Acme", "primary": "#0B3B2E", "theme": "mercator"},
        "sections": [{"title": "Everything", "blocks": [
            {"text": "Opening paragraph."},
            {"bullets": ["First point", "Second point"]},
            {"heading": "Holdings"},
            {"metrics": [["Net return", "8.4%"], ["Sharpe", "0.74"]]},
            {"table": {"headers": ["Asset", "Weight"],
                       "rows": [["Equities", "62%"], ["Credit", "28%"]]}},
            {"figure": {"png": png(), "caption": "Cumulative return",
                        "source": "Acme"}},
            {"callout": {"title": "Note", "text": "Not investment advice."}},
            {"page_break": True},
            {"text": "On the second page."},
        ]}]})
    body = text_of(out)
    for expected in ("Opening paragraph", "First point", "HOLDINGS", "8.4%",
                     "Equities", "Cumulative return", "Not investment advice",
                     "On the second page"):
        assert expected in body, expected
    assert len(pypdfium2.PdfDocument(out)) == 2


@pytest.mark.parametrize("bad,fragment", [
    ({"sections": [{"blocks": [{"nope": 1}]}]}, "unknown block 'nope'"),
    ({"sections": [{"blocks": [{"metrics": "not a list"}]}]}, "sections[0].blocks[0].metrics"),
    ({"sections": [{"blocks": [{"table": {"rows": "no"}}]}]}, "table.rows"),
    ({"sections": "not a list"}, "sections"),
    ({"sections": [{"blocks": [{"figure": {}}]}]}, "figure.png"),
])
def test_a_malformed_spec_names_the_path(bad, fragment):
    with pytest.raises(SpecError) as e:
        render_spec(bad)
    assert fragment in str(e.value), str(e.value)


def test_unknown_block_lists_what_is_known():
    """The error is the documentation most people will actually read."""
    with pytest.raises(SpecError) as e:
        render_spec({"sections": [{"blocks": [{"tabel": {}}]}]})
    for name in ("table", "metrics", "figure"):
        assert name in str(e.value)


def test_numbers_and_none_survive_a_json_round_trip():
    """A spec that came from JSON or a spreadsheet has ints and nulls in its
    rows; coercing them is the layer's job, not the caller's."""
    out = render_spec({"sections": [{"blocks": [
        {"table": {"headers": ["Year", "Return"], "rows": [[2024, 0.084], [2025, None]]}}]}]})
    assert "2024" in text_of(out)


def test_base64_figure_is_decoded():
    import base64
    out = render_spec({"sections": [{"blocks": [
        {"figure": {"png": base64.b64encode(png()).decode(), "caption": "Chart"}}]}]})
    assert "Chart" in text_of(out)


def test_custom_block_escape_hatch():
    """No fixed vocabulary survives a real project — there is always one
    bespoke drawing. It must not push you off the declarative path."""
    seen = {}

    def draw_gauge(doc, value, path):
        seen["value"] = value
        doc.body(f"gauge at {value['level']}")

    out = render_spec({"sections": [{"blocks": [{"gauge": {"level": "72%"}}]}]},
                 blocks={"gauge": draw_gauge})
    assert seen["value"] == {"level": "72%"}
    assert "gauge at 72%" in text_of(out)


def test_custom_can_shadow_a_builtin():
    def loud_text(doc, value, path):
        doc.body(str(value).upper())

    out = render_spec({"sections": [{"blocks": [{"text": "quiet"}]}]},
                 blocks={"text": loud_text})
    assert "QUIET" in text_of(out)
    assert BLOCKS["text"] is not loud_text, "the registry must not be mutated"


def test_bad_brand_colour_does_not_abort_the_document():
    """Brand config is user input. A typo in a hex code must not lose the
    report."""
    out = render_spec({"brand": {"primary": "#zzz", "accent": "nonsense"},
                  "sections": [{"blocks": [{"text": "still here"}]}]})
    assert "still here" in text_of(out)


def test_empty_spec_is_a_valid_empty_document():
    out = render_spec({})
    assert out[:4] == b"%PDF"
