"""Docling-based conversion backend.

Replaces the Tesseract OCR + hand-rolled layout pipeline with docling's
deep-learning models (layout analysis, TableFormer table structure, RapidOCR).
Produces, per page, ready-to-write Markdown plus machine-readable table rows.

Models (~0.5 GB) download on first run and are cached by HuggingFace; the
DocumentConverter is built lazily and reused, since model loading is the
expensive part. Inference runs on the GPU when available (see `_pick_device`),
a few minutes for a 20-page scan; the OCR render dpi is capped to keep the CPU
preprocess bitmap within system RAM (see `_OCR_RENDER_SCALE`).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

_converter = None  # lazily-built singleton — model load is expensive

# RapidOCR renders each page bitmap at scale * 72 dpi for OCR. docling hardcodes
# 3 (216 dpi); we lower it to 2 (144 dpi) because the full-page render is the
# memory hog — a large scan at 216 dpi can exhaust system RAM at the CPU
# preprocess stage (`std::bad_alloc`), especially now that CUDA torch raises the
# process baseline. 144 dpi cuts that bitmap by ~55% with no measurable loss on
# the dense parameter tables (validated on Manuel opti p11). Raise back to 3 if
# you ever need maximum OCR fidelity and have the RAM headroom.
_OCR_RENDER_SCALE = 2
_ocr_scale_patched = False


def docling_available() -> bool:
    try:
        import docling  # noqa: F401

        return True
    except Exception:
        return False


def _apply_ocr_scale() -> None:
    """Lower RapidOCR's page-render scale (docling exposes no option for it)."""
    global _ocr_scale_patched
    if _ocr_scale_patched:
        return
    try:
        from docling.models.stages.ocr import rapid_ocr_model as rom

        _orig_init = rom.RapidOcrModel.__init__

        def _init(self, *args, **kwargs):
            _orig_init(self, *args, **kwargs)
            self.scale = _OCR_RENDER_SCALE

        rom.RapidOcrModel.__init__ = _init
        _ocr_scale_patched = True
    except Exception:
        pass  # docling internals moved — keep default scale, no crash


def _pick_device():
    """CUDA when a GPU is present, else CPU. docling propagates this to the layout
    + TableFormer models *and* to RapidOCR (Det/Cls/Rec .use_cuda)."""
    from docling.datamodel.pipeline_options import AcceleratorDevice

    try:
        import torch

        if torch.cuda.is_available():
            return AcceleratorDevice.CUDA
    except Exception:
        pass
    return AcceleratorDevice.CPU


def _build_converter():
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import (
        AcceleratorOptions,
        PdfPipelineOptions,
    )
    from docling.document_converter import DocumentConverter, PdfFormatOption

    opts = PdfPipelineOptions()
    opts.do_ocr = True              # pages here are scans
    opts.do_table_structure = True  # recover the parameter tables
    # OCR engine: docling's default (RapidOCR / PP-OCRv4) is kept on purpose.
    # It reads the dense bordered parameter tables cleanly — the most valuable,
    # information-dense content here. Tesseract (fra+eng) spaces French prose
    # better but reads printed table borders as '|' and garbles those cells, so
    # it loses table data; for this document clean tables win. (To favour prose
    # instead, set opts.ocr_options = TesseractCliOcrOptions(lang=["fra","eng"]).)

    # Run every model stage on the GPU when one is available (≈5-10× faster than
    # CPU). flash-attention 2 is left off — the GTX 1660 is Turing (sm_75) and
    # only Ampere+ supports it.
    device = _pick_device()
    opts.accelerator_options = AcceleratorOptions(device=device)
    _apply_ocr_scale()  # cap OCR render dpi to keep the preprocess bitmap in RAM

    # Bound peak memory, one page at a time through each stage. Matters on CPU
    # (system RAM OOM'd at higher batch sizes) and on the 6 GB GTX 1660 (VRAM).
    for attr in ("layout_batch_size", "ocr_batch_size", "table_batch_size"):
        if hasattr(opts, attr):
            setattr(opts, attr, 1)

    pdf_opt = PdfFormatOption(pipeline_options=opts)
    return DocumentConverter(
        format_options={InputFormat.PDF: pdf_opt, InputFormat.IMAGE: pdf_opt}
    )


def _get_converter():
    global _converter
    if _converter is None:
        _converter = _build_converter()
    return _converter


@dataclass
class DoclingPage:
    page_no: int
    markdown: str
    tables: list[list[list[str]]] = field(default_factory=list)
    images: list[tuple[bytes, str]] = field(default_factory=list)  # (raw_bytes, ext)


@dataclass
class DoclingResult:
    title: str
    page_count: int
    pages: list[DoclingPage]


def _table_rows(table, doc) -> list[list[str]]:
    """A docling TableItem → list of row cell-strings, header included."""
    try:
        df = table.export_to_dataframe(doc)
    except Exception:
        return []
    header = [str(c).strip() for c in df.columns]
    body = [
        ["" if v is None else str(v).strip() for v in row]
        for row in df.values.tolist()
    ]
    rows = [header, *body] if any(header) else body
    return [r for r in rows if any(c for c in r)]


def _tables_by_page(doc) -> dict[int, list[list[list[str]]]]:
    by_page: dict[int, list[list[list[str]]]] = {}
    for table in doc.tables:
        if not table.prov:
            continue
        rows = _table_rows(table, doc)
        if rows:
            by_page.setdefault(table.prov[0].page_no, []).append(rows)
    return by_page


def _free_memory() -> None:
    """Release the transient peak between pages so a retry has the best chance."""
    import gc

    gc.collect()
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:
        pass


def _page_count(path: str) -> int:
    """Fast page count via PyMuPDF — no docling model load needed."""
    import fitz

    with fitz.open(path) as doc:
        return len(doc)


def _images_for_page(doc, page_no: int) -> list[tuple[bytes, str]]:
    """Extract image bytes in reading order for one page from a docling document.

    Iterates ``doc.pictures`` (reading order), calls ``get_image`` or falls back
    to ``picture.image.pil_image``, and converts to PNG bytes.  Matches the
    ``<!-- image -->`` placeholders that ``export_to_markdown`` emits for that page.
    """
    import io

    images: list[tuple[bytes, str]] = []
    for picture in getattr(doc, "pictures", []):
        if not picture.prov or picture.prov[0].page_no != page_no:
            continue
        try:
            pil_img = None
            if hasattr(picture, "get_image"):
                pil_img = picture.get_image(doc)
            elif hasattr(picture, "image") and hasattr(picture.image, "pil_image"):
                pil_img = picture.image.pil_image
            if pil_img is None:
                continue
            buf = io.BytesIO()
            pil_img.save(buf, format="PNG")
            images.append((buf.getvalue(), "png"))
        except Exception:
            pass
    return images


def _convert_one_page(conv, path: str, page_no: int) -> DoclingPage | None:
    """Convert a single page; return None on failure or empty output."""
    try:
        doc = conv.convert(path, page_range=(page_no, page_no)).document
    except Exception:
        return None
    md = doc.export_to_markdown(page_no=page_no).strip()
    if not md:
        return None
    return DoclingPage(
        page_no,
        md,
        _tables_by_page(doc).get(page_no, []),
        _images_for_page(doc, page_no),
    )


def docling_pages(
    path: str | Path,
    page_range: tuple[int, int] | None = None,
    progress_cb: Callable[[int, int], None] | None = None,
) -> list[DoclingPage]:
    """Run docling over a PDF/image and return its pages as ``DoclingPage``.

    Pages are converted **one at a time** so only one page bitmap lives in RAM
    during the CPU preprocess stage (converting the whole range at once caused
    ``std::bad_alloc`` when a run covers many large scanned pages).  The
    ``DocumentConverter`` singleton keeps its model weights in VRAM between
    calls, so there is no model reload between pages.

    ``page_range`` is a 1-based inclusive ``(start, end)``; original page
    numbers are preserved on the returned pages.  When ``page_range`` is None
    the whole document is converted.

    Pages that fail (OOM or empty output) are retried once after a memory flush;
    pages still empty after the retry get a visible warning and an empty entry.
    """
    path = str(path)
    conv = _get_converter()

    page_nos = (
        list(range(page_range[0], page_range[1] + 1))
        if page_range
        else list(range(1, _page_count(path) + 1))
    )

    pages: list[DoclingPage] = []
    for i, page_no in enumerate(page_nos, 1):
        page = _convert_one_page(conv, path, page_no)
        if page is None:
            # First attempt empty — free memory and try once more.
            _free_memory()
            page = _convert_one_page(conv, path, page_no)
        if page is None:
            print(
                f"  ⚠ page {page_no} vide après reprise (mémoire insuffisante ?) "
                f"— libérez de la RAM ou baissez _OCR_RENDER_SCALE"
            )
            pages.append(DoclingPage(page_no, "", []))
        else:
            pages.append(page)
        if progress_cb:
            progress_cb(i, len(page_nos))
        # Release this page's bitmaps before the next page renders its own.
        _free_memory()

    return pages


def convert_document(
    path: str | Path,
    title: str,
    progress_cb: Callable[[int, int], None] | None = None,
) -> DoclingResult:
    """Convert a whole PDF/image to per-page Markdown + table rows via docling."""
    pages = docling_pages(path, progress_cb=progress_cb)
    return DoclingResult(title=title, page_count=len(pages), pages=pages)
