# Sample transcript provenance

Both PDFs in this directory are official, publicly-hosted earnings call
transcripts, fetched directly from each company's investor-relations CDN
(no login/paywall) for use as test fixtures in `tests/test_pdf_loader.py`
and `tests/test_segmentation.py`. Chosen specifically because they use two
different vendor transcript formats — see `src/ingestion/segmentation.py`'s
module docstring — which is what the ingestion module's regex heuristics are
designed against.

| File | Source | Fetched |
|---|---|---|
| `META-Q4-2024-Earnings-Call-Transcript.pdf` | https://s21.q4cdn.com/399680738/files/doc_financials/2024/q4/META-Q4-2024-Earnings-Call-Transcript.pdf | 2026-08-12 |
| `Assurant-Q325-Earnings-Call-Transcript.pdf` | https://s21.q4cdn.com/997934001/files/doc_financials/2025/q3/Assurant-Q325-Earnings-Call-Transcript.pdf | 2026-08-12 |

Used here strictly for development/testing of the ingestion pipeline (public
company disclosure documents, used non-commercially as parser test input) —
not redistributed as a product feature.
