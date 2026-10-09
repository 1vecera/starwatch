"""Quote verification and text extraction for the programme collector."""

from __future__ import annotations

import io

import pytest
from pypdf import PdfWriter

from czlake.campaign.text import Document, find_quote, html_document, pdf_document


def doc(*pages: str, fmt: str = "html") -> Document:
    return Document("https://list.example/program", fmt, "Program", list(pages), "2026-10-01T00:00:00+00:00")


def test_quote_found_across_whitespace_and_typography():
    source = doc("Zavedeme\n„Family pas“  pro rodiny – s výhodami­v MHD.\nDalší věta.")
    match = find_quote('Zavedeme "Family pas" pro rodiny - s výhodamiv MHD', source)
    assert match is not None
    # The stored quote keeps the source's own characters, with whitespace collapsed.
    assert match.quote == "Zavedeme „Family pas“ pro rodiny – s výhodami­v MHD"
    assert match.page is None


def test_quote_not_in_source_is_rejected():
    source = doc("Postavíme 500 nových městských bytů do roku 2030.")
    assert find_quote("Postavíme 800 nových městských bytů do roku 2030.", source) is None


def test_paraphrased_or_elided_quote_is_rejected():
    source = doc("Opravíme všechny školy na sídlištích a rozšíříme kapacitu školek o 300 míst.")
    assert find_quote("Opravíme všechny školy ... kapacitu školek o 300 míst", source) is None
    assert find_quote("opravíme všechny školy na sídlištích", source) is None  # case matters


def test_short_fragments_do_not_count_as_quotes():
    assert find_quote("školy", doc("Opravíme všechny školy na sídlištích.")) is None


def test_pdf_quote_reports_page_and_crosses_page_breaks():
    source = doc("Úvod programu a obecné hodnoty.", "Doprava: prodloužíme tramvajovou trať", "do Líšně a na Kampus.",
                 fmt="pdf")
    match = find_quote("prodloužíme tramvajovou trať [[page 3]] do Líšně a na Kampus", source)
    assert match is not None
    assert match.page == 2
    assert source.source_url(match.page) == "https://list.example/program#page=2"


def test_model_text_marks_pdf_pages_and_reports_truncation():
    source = doc("a" * 50, "b" * 50, fmt="pdf")
    text, cut = source.for_model(1000)
    assert text.startswith("[[page 1]]") and "[[page 2]]" in text and not cut
    assert source.for_model(30) == (text[:30], True)


def test_html_main_text_falls_back_to_full_text_when_thin():
    html = b"""<html><head><title>Program 2026</title><script>var x = 'nic';</script></head><body>
    <nav>Menu</nav><div id="app"><ul><li>Postavime park na Strelecke ulici.</li>
    <li>Snizime poplatek za odpad pro rodiny s detmi.</li></ul>
    <a href="/program.pdf">Cely program ke stazeni</a></div></body></html>"""
    page = html_document(html, "https://list.example/", "2026-10-01T00:00:00+00:00")
    assert page.title == "Program 2026"
    assert "Postavime park na Strelecke ulici." in page.pages[0]
    assert "var x" not in page.pages[0]
    assert ("https://list.example/program.pdf", "Cely program ke stazeni") in page.links


def test_pdf_document_has_one_text_per_page():
    writer = PdfWriter()
    writer.add_blank_page(200, 200)
    writer.add_blank_page(200, 200)
    buffer = io.BytesIO()
    writer.write(buffer)
    pdf = pdf_document(buffer.getvalue(), "https://list.example/p.pdf", "2026-10-01T00:00:00+00:00")
    assert pdf.format == "pdf"
    assert len(pdf.pages) == 2


@pytest.mark.parametrize("hyphenated", ["dostup-\nného bydlení"])
def test_pdf_line_hyphenation_is_joined(hyphenated):
    from czlake.campaign.text import _HYPHEN_BREAK

    assert _HYPHEN_BREAK.sub("", hyphenated) == "dostupného bydlení"
    assert _HYPHEN_BREAK.sub("", "Frýdek-\nMístek") == "Frýdek-\nMístek"
