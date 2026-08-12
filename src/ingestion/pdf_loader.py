"""Deterministic PDF text extraction for earnings call transcripts.

No LLM calls — this module only reads bytes off disk and extracts a text layer.
Per CLAUDE.md's deterministic-before-LLM principle, this must stay pure/testable
and never guess: a PDF with no usable text layer (e.g. a scanned image with no
OCR'd text) raises a clear, typed error instead of silently returning near-empty
or garbage text for downstream stages to choke on.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pymupdf

# Below this average non-whitespace character count per page, we treat the PDF
# as having no real text layer. A real transcript page has hundreds to
# thousands of characters; a scanned page with no text layer yields ~0.
# 50 is a conservative floor — even a mostly-blank cover page tends to clear it
# if there's a title/date line, while an actually-scanned page reliably won't.
MIN_CHARS_PER_PAGE = 50


class PDFTextExtractionError(Exception):
    """Raised when a PDF can't be opened, or yields no usable text layer."""


@dataclass(frozen=True)
class LoadedDocument:
    """Raw extracted text plus basic provenance for downstream ingestion stages."""

    source_path: str
    page_count: int
    text: str


def load_pdf_text(path: str | Path) -> LoadedDocument:
    """Extract the text layer from a PDF transcript, page by page, joined with newlines.

    Args:
        path: Path to the PDF file.

    Returns:
        A LoadedDocument with the full extracted text and basic provenance.

    Raises:
        PDFTextExtractionError: if the path doesn't exist, the file isn't a
            readable PDF, it has zero pages, or its extracted text is near-empty
            (the scanned-image / no-text-layer case this function exists to catch).
    """
    pdf_path = Path(path)
    if not pdf_path.exists():
        raise PDFTextExtractionError(f"PDF not found: {pdf_path}")

    try:
        doc = pymupdf.open(pdf_path)
    except pymupdf.FileDataError as exc:
        # Covers both a corrupt/non-PDF file (FileDataError) and a zero-byte
        # file (EmptyFileError, a subclass of FileDataError in pymupdf).
        raise PDFTextExtractionError(f"Could not open '{pdf_path}' as a PDF: {exc}") from exc

    try:
        page_count = doc.page_count
        if page_count == 0:
            raise PDFTextExtractionError(f"PDF has zero pages: {pdf_path}")
        page_texts = [page.get_text() for page in doc]
    finally:
        doc.close()

    text = "\n".join(page_texts)
    avg_chars_per_page = len(text.strip()) / page_count

    if avg_chars_per_page < MIN_CHARS_PER_PAGE:
        raise PDFTextExtractionError(
            f"'{pdf_path}' yielded almost no extractable text "
            f"(avg {avg_chars_per_page:.1f} chars/page across {page_count} page(s)). "
            "This is most likely a scanned/image-only PDF with no text layer — "
            "OCR is not supported by this pipeline. Provide a text-layer PDF instead."
        )

    return LoadedDocument(source_path=str(pdf_path), page_count=page_count, text=text)
