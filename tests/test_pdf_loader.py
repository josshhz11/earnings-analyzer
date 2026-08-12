"""Tests for src.ingestion.pdf_loader — deterministic PDF text extraction.

Exercises real sample transcripts in data/sample_transcripts/ (see that
directory's provenance note) plus synthetic edge cases: missing file, corrupt
file, empty file, and a no-text-layer ("scanned") PDF.
"""

from pathlib import Path

import pymupdf
import pytest

from src.ingestion.pdf_loader import PDFTextExtractionError, load_pdf_text

SAMPLE_DIR = Path(__file__).parent.parent / "data" / "sample_transcripts"
META_PDF = SAMPLE_DIR / "META-Q4-2024-Earnings-Call-Transcript.pdf"
ASSURANT_PDF = SAMPLE_DIR / "Assurant-Q325-Earnings-Call-Transcript.pdf"


def test_loads_real_meta_transcript():
    doc = load_pdf_text(META_PDF)
    assert doc.page_count > 0
    assert len(doc.text) > 10_000
    assert "Zuckerberg" in doc.text
    assert "Operator" in doc.text


def test_loads_real_assurant_transcript():
    doc = load_pdf_text(ASSURANT_PDF)
    assert doc.page_count > 0
    assert len(doc.text) > 10_000
    assert "Assurant" in doc.text
    assert "Operator" in doc.text


def test_missing_file_raises():
    with pytest.raises(PDFTextExtractionError, match="not found"):
        load_pdf_text(SAMPLE_DIR / "does-not-exist.pdf")


def test_corrupt_file_raises(tmp_path):
    bad_pdf = tmp_path / "bad.pdf"
    bad_pdf.write_bytes(b"this is not a pdf, just garbage bytes")
    with pytest.raises(PDFTextExtractionError, match="Could not open"):
        load_pdf_text(bad_pdf)


def test_empty_file_raises(tmp_path):
    empty_pdf = tmp_path / "empty.pdf"
    empty_pdf.write_bytes(b"")
    with pytest.raises(PDFTextExtractionError):
        load_pdf_text(empty_pdf)


def test_no_text_layer_raises(tmp_path):
    """A valid PDF with blank pages and no text layer should raise, not
    silently return near-empty text — this is the scanned-transcript case.
    """
    scanned_pdf = tmp_path / "scanned.pdf"
    doc = pymupdf.open()
    for _ in range(2):
        doc.new_page(width=612, height=792)
    doc.save(scanned_pdf)
    doc.close()

    with pytest.raises(PDFTextExtractionError, match="scanned"):
        load_pdf_text(scanned_pdf)


# Note: a zero-page PDF is defended against in load_pdf_text, but pymupdf
# itself refuses to save a zero-page document ("cannot save with zero
# pages"), so there's no way to construct a real fixture file for it — that
# branch is defensive/untested by design.
