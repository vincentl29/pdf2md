"""Per-page routing pipeline: cheap local extraction vs. docling OCR.

A PDF is rarely uniform. Pages that already carry a reliable text layer can be
read instantly by PyMuPDF/pdfplumber (no model load, no OCR, no word-gluing);
scanned/image pages need docling's layout + OCR + TableFormer models.

``convert_document`` classifies every page, extracts the native ones locally,
and runs docling only over the scanned ones (in contiguous runs, original page
numbers preserved). A genuinely-native PDF therefore never loads the docling
models at all — seconds instead of minutes, and far less RAM. Images and
fully-scanned PDFs behave exactly as before (docling for everything).

The native fast path is gated by ``text_is_reliable``: many PDFs ship a broken
text layer (subset fonts without ToUnicode), so those pages are deliberately
routed to OCR rather than emitting scrambled text.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from .docling_engine import DoclingPage, DoclingResult, docling_pages
from .native_extract import extract_native_page, text_is_reliable


def _contiguous_runs(pages: list[int]) -> list[tuple[int, int]]:
    """[2,3,4,7,8] → [(2,4),(7,8)]."""
    runs: list[tuple[int, int]] = []
    start = prev = pages[0]
    for p in pages[1:]:
        if p == prev + 1:
            prev = p
        else:
            runs.append((start, prev))
            start = prev = p
    runs.append((start, prev))
    return runs


def _classify(pdf_path: Path) -> list[bool]:
    """Per page: True if it has a reliable native text layer (→ fast path)."""
    import fitz

    doc = fitz.open(str(pdf_path))
    try:
        return [text_is_reliable(doc[i].get_text("text")) for i in range(doc.page_count)]
    finally:
        doc.close()


def convert_document(
    path: str | Path,
    title: str,
    progress_cb: Callable[[int, int], None] | None = None,
) -> DoclingResult:
    path = Path(path)

    # Images are always scans → docling for everything (no native text layer).
    if path.suffix.lower() != ".pdf":
        pages = docling_pages(path, progress_cb=progress_cb)
        return DoclingResult(title=title, page_count=len(pages), pages=pages)

    native_flags = _classify(path)
    total = len(native_flags)
    page_map: dict[int, DoclingPage] = {}

    done = 0

    def bump() -> None:
        nonlocal done
        done += 1
        if progress_cb:
            progress_cb(done, total)

    # Native pages: instant local extraction (no docling, no model load).
    if any(native_flags):
        import fitz
        import pdfplumber

        fdoc = fitz.open(str(path))
        pdoc = pdfplumber.open(str(path))
        try:
            for i, native in enumerate(native_flags):
                if native:
                    md, tables, images = extract_native_page(fdoc[i], pdoc.pages[i])
                    page_map[i + 1] = DoclingPage(i + 1, md, tables, images)
                    bump()
        finally:
            fdoc.close()
            pdoc.close()

    # Scanned pages: docling, one call per contiguous run (original numbering).
    scanned = [i + 1 for i, native in enumerate(native_flags) if not native]
    if scanned:
        for start, end in _contiguous_runs(scanned):
            base = done

            def run_cb(i: int, _n: int, base: int = base) -> None:
                if progress_cb:
                    progress_cb(min(base + i, total), total)

            for dp in docling_pages(path, page_range=(start, end), progress_cb=run_cb):
                page_map[dp.page_no] = dp
            done = base + (end - start + 1)

    pages = [page_map[p] for p in range(1, total + 1)]
    return DoclingResult(title=title, page_count=total, pages=pages)
