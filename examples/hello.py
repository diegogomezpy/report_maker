"""The smallest useful report — no domain code, no config files, no setup.

    python examples/hello.py    # writes hello.pdf

This doubles as the acceptance test for "drop the library into a new project":
it imports only reportkit, and everything it draws is a block the library owns.
"""
from __future__ import annotations

import io

from reportkit import ReportDocument, resolve_theme


def placeholder_png(w: int, h: int, shade=(226, 232, 237)) -> bytes:
    """Stand-in for whatever your project plots. reportkit takes PNG bytes, so
    the chart library is entirely your choice — matplotlib, Plotly, an image
    someone emailed you."""
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (w, h), shade).save(buf, "PNG")
    return buf.getvalue()


def main() -> None:
    doc = ReportDocument(
        lang="en",
        doc_ref="Q3 Review | Growth Fund II",
        firm_name="Acme Capital",
        # The whole visual identity is three colours plus a theme name.
        primary_color=(11, 59, 46),
        accent_color=(32, 148, 138),
        section_rule_color=(163, 200, 63),
        theme=resolve_theme("mercator"),      # or "hexagon"
    )

    doc.add_page()
    doc.section_title("Performance")
    doc.metric_band([
        ("Net return", "8.4%"),
        ("Volatility", "11.2%"),
        ("Sharpe", "0.74"),
        ("Max drawdown", "-6.1%"),
    ])

    doc.subsection("Holdings")
    doc.data_table(
        ["Asset class", "Weight", "Return"],
        [["Equities", "62%", "+11.1%"],
         ["Credit", "28%", "+3.9%"],
         ["Cash", "10%", "+0.4%"]],
        aligns=["L", "R", "R"],
    )

    doc.figure(placeholder_png(900, 380), "Cumulative return", "Acme, monthly")
    doc.callout("Note", "Past performance is not indicative of future results.")

    with open("hello.pdf", "wb") as fh:
        fh.write(bytes(doc.output()))
    print("wrote hello.pdf")


if __name__ == "__main__":
    main()
