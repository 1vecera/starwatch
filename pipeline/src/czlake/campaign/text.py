"""Readable text from HTML and PDF sources, and verbatim quote lookup.

Quotes are accepted only when they occur in the extracted source text. Matching folds
whitespace, soft hyphens and typographic quote/dash variants; the stored quote is always the
source's own characters with whitespace collapsed, never the model's spelling.
"""

from __future__ import annotations

import io
import logging
import re
import unicodedata
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlsplit

import trafilatura
from lxml import html as lxml_html
from pypdf import PdfReader

logging.getLogger("pypdf").setLevel(logging.ERROR)
PAGE_MARK = re.compile(r"\s*\[\[page \d+\]\]\s*")
_FOLD = {
    "­": "", "​": "", "‌": "", "‍": "", "⁠": "", "﻿": "",
    "„": '"', "“": '"', "”": '"', "«": '"', "»": '"', "″": '"',
    "‚": "'", "‘": "'", "’": "'", "´": "'", "`": "'", "′": "'",
    "–": "-", "—": "-", "‑": "-", "‐": "-", "−": "-",
    "…": "...",
}
_HYPHEN_BREAK = re.compile(r"(?<=[a-záčďéěíňóřšťúůýž])-\n(?=[a-záčďéěíňóřšťúůýž])")
_SKIP_TAGS = {"script", "style", "noscript", "template", "svg", "iframe", "head"}
_BLOCK_TAGS = {
    "p", "div", "section", "article", "li", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6",
    "tr", "table", "br", "header", "footer", "main", "aside", "blockquote", "dd", "dt", "figcaption",
}


@dataclass
class Document:
    """Extracted text of one fetched source. HTML pages have one page; PDFs one per PDF page."""

    url: str
    format: str  # "html" | "pdf"
    title: str
    pages: list[str]
    fetched_at: str
    via: str = "http"
    links: list[tuple[str, str]] = field(default_factory=list)

    @property
    def chars(self) -> int:
        return sum(len(page) for page in self.pages)

    def for_model(self, limit: int) -> tuple[str, bool]:
        """Text with ``[[page N]]`` markers for PDFs, cut at ``limit`` characters."""
        if self.format == "pdf":
            text = "\n\n".join(f"[[page {index}]]\n{page}" for index, page in enumerate(self.pages, 1))
        else:
            text = "\n\n".join(self.pages)
        return (text[:limit], True) if len(text) > limit else (text, False)

    def source_url(self, page: int | None) -> str:
        return f"{self.url}#page={page}" if self.format == "pdf" and page else self.url


def clean(text: str) -> str:
    text = unicodedata.normalize("NFC", text).replace("\r\n", "\n").replace("\r", "\n")
    text = "\n".join(line.strip() for line in text.split("\n"))
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def collapse(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _lxml_text(tree) -> str:
    parts: list[str] = []

    def walk(node) -> None:
        tag = node.tag if isinstance(node.tag, str) else ""
        if tag.lower() in _SKIP_TAGS:
            if node.tail:
                parts.append(node.tail)
            return
        block = tag.lower() in _BLOCK_TAGS
        if block:
            parts.append("\n")
        if node.text:
            parts.append(node.text)
        for child in node:
            walk(child)
        if block:
            parts.append("\n")
        if node.tail:
            parts.append(node.tail)

    body = tree.find(".//body")
    walk(body if body is not None else tree)
    lines = [collapse(line) for line in "".join(parts).split("\n")]
    return "\n".join(line for line in lines if line)


def html_document(data: bytes, url: str, fetched_at: str, via: str = "http") -> Document:
    """Main text via trafilatura; full visible text when the main-text pass is thin."""
    tree = trafilatura.load_html(data)
    if tree is None:
        return Document(url, "html", "", [""], fetched_at, via)
    main = trafilatura.extract(
        tree, url=url, include_tables=True, include_comments=False, favor_recall=True,
        deduplicate=False, output_format="txt",
    ) or ""
    full = _lxml_text(tree)
    text = main if len(main) >= 1500 or len(main) >= 0.5 * len(full) else full
    titles = tree.xpath("//meta[@property='og:title']/@content") or tree.xpath("//title/text()")
    title = collapse(titles[0]) if titles else ""
    links = []
    for anchor in tree.xpath("//a[@href]"):
        href = anchor.get("href", "").strip()
        if href and not href.startswith(("mailto:", "tel:", "javascript:", "#")):
            links.append((urljoin(url, href).split("#")[0], collapse(anchor.text_content())[:120]))
    return Document(url, "html", title, [clean(text)], fetched_at, via, links)


def text_document(text: str, url: str, title: str, fetched_at: str, via: str) -> Document:
    return Document(url, "html", collapse(title), [clean(text)], fetched_at, via)


def pdf_document(data: bytes, url: str, fetched_at: str, via: str = "http") -> Document:
    """One text per PDF page; joins words hyphenated across line breaks."""
    reader = PdfReader(io.BytesIO(data))
    pages = []
    for page in reader.pages:
        try:
            raw = page.extract_text() or ""
        except Exception:  # noqa: BLE001 - a broken page must not lose the others
            raw = ""
        pages.append(clean(_HYPHEN_BREAK.sub("", unicodedata.normalize("NFC", raw))))
    title = ""
    try:
        title = collapse(str((reader.metadata or {}).get("/Title") or ""))
    except Exception:  # noqa: BLE001
        title = ""
    return Document(url, "pdf", title, pages, fetched_at, via)


def is_pdf(data: bytes, content_type: str | None) -> bool:
    return data[:5] == b"%PDF-" or "pdf" in (content_type or "").lower()


def _fold(text: str) -> tuple[str, list[int]]:
    """Folded text plus, for each folded character, its index in the original."""
    chars: list[str] = []
    origin: list[int] = []
    pending_space = False
    for index, char in enumerate(text):
        if char.isspace():
            pending_space = bool(chars)
            continue
        replacement = _FOLD.get(char, char)
        if not replacement:
            continue
        if pending_space:
            chars.append(" ")
            origin.append(index)
            pending_space = False
        for piece in replacement:
            chars.append(piece)
            origin.append(index)
    return "".join(chars), origin


def _prepare_quote(quote: str) -> str:
    quote = PAGE_MARK.sub(" ", unicodedata.normalize("NFC", quote))
    folded, _ = _fold(quote)
    return folded.strip(" .\"'").removeprefix("...").removesuffix("...").strip(" \"'")


@dataclass(frozen=True)
class QuoteMatch:
    quote: str  # source characters, whitespace collapsed
    page: int | None  # 1-based PDF page, None for HTML


def find_quote(quote: str, document: Document, min_chars: int = 20) -> QuoteMatch | None:
    """Locate ``quote`` in the document text; return the verbatim source span or None."""
    needle = _prepare_quote(quote)
    if len(needle) < min_chars:
        return None
    joined = ""
    starts: list[int] = []
    for page in document.pages:
        if joined:
            joined += "\n"
        starts.append(len(joined))
        joined += page
    folded, origin = _fold(joined)
    position = folded.find(needle)
    if position < 0:
        return None
    begin = origin[position]
    end = origin[position + len(needle) - 1] + 1
    stated = quote.rstrip()
    if stated and stated[-1] in ".!?" and joined[end:end + 1] == stated[-1]:
        end += 1  # keep the sentence's own final punctuation when the model quoted it
    page = None
    if document.format == "pdf":
        page = max(index for index, start in enumerate(starts, 1) if start <= begin)
    return QuoteMatch(collapse(joined[begin:end]), page)


def registered_domain(url: str) -> str:
    host = (urlsplit(url).hostname or "").lower().removeprefix("www.")
    parts = host.split(".")
    return ".".join(parts[-2:]) if len(parts) >= 2 else host
