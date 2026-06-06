import io
import re
from collections import Counter
from collections.abc import Callable
from pathlib import Path
import fitz
from .models import TextBlock, TableBlock, ImageBlock
from ..processing.ocr import extract_structured_from_pixmap, ocr_available


def _open_document(filepath: Path) -> "fitz.Document":
    """
    Open a PDF or image as a fitz document.

    MuPDF reads most raster formats directly; for anything it rejects
    (e.g. WEBP, ICO) fall back to Pillow and hand MuPDF a PNG stream, so
    effectively any Pillow-readable image is supported.
    """
    try:
        return fitz.open(str(filepath))
    except Exception:
        from PIL import Image

        with Image.open(filepath) as im:
            buf = io.BytesIO()
            im.convert("RGB").save(buf, format="PNG")
        return fitz.open(stream=buf.getvalue(), filetype="png")

_GARBLED_UPPERCASE_THRESHOLD = 0.6
_GARBLED_MIN_ALPHA = 20
_GARBLED_SPARSE_MAX = 8          # fewer alpha chars than this → assume garbled
_GARBLE_INDICATOR_CHARS = frozenset('€ÿþ')  # non-standard encoding artifacts
_GARBLE_EMBED_RE = re.compile(r'[A-Za-z][!|}\[\]][A-Za-z]')  # special char between letters

_OCR_TITLE_SIZE = 20.0    # first heading-like block of page 1
_OCR_HEADING_SIZE = 15.0  # other heading-like blocks
_OCR_BODY_SIZE = 11.0


class PDFLoader:
    MIN_IMAGE_SIZE = 50  # pixels — skip decorative icons

    def __init__(self):
        self._ocr = ocr_available()

    def load(
        self,
        filepath: Path,
        progress_cb: Callable[[int, int], None] | None = None,
    ) -> tuple[list[TextBlock], list[TableBlock], list[ImageBlock], int]:
        text_blocks: list[TextBlock] = []
        table_blocks: list[TableBlock] = []
        image_blocks: list[ImageBlock] = []

        doc = _open_document(filepath)
        page_count = len(doc)
        # Image inputs (TIFF/PNG/JPG) render as a page with no embedded image
        # object and no text — they must always go through page-level OCR.
        is_image_doc = not doc.is_pdf

        ocr_pages: set[int] = set()        # pages where page-level OCR was applied
        ocr_table_pages: set[int] = set()  # pages where OCR returned tables

        for page_num, page in enumerate(doc, start=1):
            page_text = self._extract_text(page, page_num)

            if self._is_garbled(page_text):
                # Text present but encoding is scrambled
                ocr_text, ocr_tables = self._ocr_fallback(page, page_num)
                if ocr_text or ocr_tables:
                    page_text = ocr_text
                    ocr_pages.add(page_num)
                    table_blocks.extend(ocr_tables)
                    if ocr_tables:
                        ocr_table_pages.add(page_num)
                    print(f"    [OCR] page {page_num} — encodage de police non standard, texte extrait par OCR")
                else:
                    print(f"    [WARN] page {page_num} — encodage non standard, OCR vide")
                    print(f"           Installez Tesseract OCR : https://github.com/UB-Mannheim/tesseract/wiki")

            elif not page_text and (page.get_images(full=False) or is_image_doc):
                # No text at all but the page is a scan (embedded image, or the
                # whole document is an image file) → use page-level OCR.
                # get_pixmap() respects page rotation unlike raw image bytes
                ocr_text, ocr_tables = self._ocr_fallback(page, page_num)
                if ocr_text or ocr_tables:
                    page_text = ocr_text
                    ocr_pages.add(page_num)
                    table_blocks.extend(ocr_tables)
                    if ocr_tables:
                        ocr_table_pages.add(page_num)
                    print(f"    [OCR] page {page_num} — page image, texte extrait par OCR")

            text_blocks.extend(page_text)
            # Skip native table extraction when OCR already returned tables for this page
            if page_num not in ocr_table_pages:
                table_blocks.extend(self._extract_tables(page, page_num))
            # Skip raw image extraction for OCR'd pages to avoid duplicate content
            if page_num not in ocr_pages:
                image_blocks.extend(self._extract_images(doc, page, page_num))

            if progress_cb:
                progress_cb(page_num, page_count)

        doc.close()
        return text_blocks, table_blocks, image_blocks, page_count

    @staticmethod
    def _is_garbled(blocks: list[TextBlock]) -> bool:
        text = " ".join(b.text for b in blocks)
        if not text.strip():
            return False
        alpha = [c for c in text if c.isalpha()]

        # Very sparse alpha extraction: garbled encoding maps most glyphs to non-alpha chars
        if 0 < len(alpha) < _GARBLED_SPARSE_MAX:
            return True

        # Characters that only appear from non-standard font mappings
        if any(c in _GARBLE_INDICATOR_CHARS for c in text):
            return True

        # Special char embedded between letters (e.g. "ag!DOSSe", "ainppa]T")
        if _GARBLE_EMBED_RE.search(text):
            return True

        # Classic garbled: font maps mostly to uppercase codepoints
        if len(alpha) >= _GARBLED_MIN_ALPHA:
            return sum(1 for c in alpha if c.isupper()) / len(alpha) > _GARBLED_UPPERCASE_THRESHOLD

        return False

    def _ocr_fallback(
        self, page, page_num: int
    ) -> tuple[list[TextBlock], list[TableBlock]]:
        if not self._ocr:
            return [], []
        mat = fitz.Matrix(2, 2)
        pix = page.get_pixmap(matrix=mat)
        paragraphs, raw_tables = extract_structured_from_pixmap(pix.tobytes("png"))
        if not paragraphs and not raw_tables:
            return [], []

        text_blocks: list[TextBlock] = []
        y = 0.0
        is_first = True
        for para in paragraphs:
            para = " ".join(para.split())
            if not para:
                continue
            is_heading = self._looks_like_ocr_heading(para)
            if is_first and page_num == 1 and is_heading:
                font_size = _OCR_TITLE_SIZE
            elif is_heading:
                font_size = _OCR_HEADING_SIZE
            else:
                font_size = _OCR_BODY_SIZE
            is_first = False
            text_blocks.append(TextBlock(
                text=para, font_size=font_size, is_bold=False,
                page_num=page_num, y_pos=y,
            ))
            y += 25.0

        table_blocks = [TableBlock(rows=t, page_num=page_num) for t in raw_tables]
        return text_blocks, table_blocks

    @staticmethod
    def _looks_like_ocr_heading(text: str) -> bool:
        """Short line without trailing punctuation and not a list item = likely heading."""
        text = text.strip()
        if not text:
            return False
        if text[0] in ('+', '-', '*', '•', '·', '–', '—', '»', '>'):
            return False
        if text[-1] in ('.', ',', ';', ':'):
            return False
        return len(text.split()) <= 7

    def _extract_text(self, page, page_num: int) -> list[TextBlock]:
        """Extract text at block level — one TextBlock per PDF paragraph block."""
        result = []
        text_dict = page.get_text("dict", sort=True)
        for block in text_dict["blocks"]:
            if block["type"] != 0:
                continue

            line_texts: list[str] = []
            char_sizes: list[float] = []
            bold_chars = 0
            total_chars = 0

            for line in block["lines"]:
                line_text = self._join_line_spans(line["spans"])
                if line_text.strip():
                    line_texts.append(line_text.strip())
                for span in line["spans"]:
                    n = len(span.get("text", ""))
                    char_sizes.extend([span["size"]] * n)
                    if span["flags"] & 16:
                        bold_chars += n
                    total_chars += n

            full_text = " ".join(line_texts)
            if not full_text.strip():
                continue

            # Dominant font size across all characters in the block
            font_size = Counter(round(s, 1) for s in char_sizes).most_common(1)[0][0] if char_sizes else 12.0
            is_bold = total_chars > 0 and bold_chars / total_chars > 0.5

            result.append(TextBlock(
                text=full_text,
                font_size=font_size,
                is_bold=is_bold,
                page_num=page_num,
                y_pos=block["bbox"][1],
            ))
        return result

    @staticmethod
    def _join_line_spans(spans: list) -> str:
        """Join spans within a line, adding spaces only where there is a visible gap."""
        if not spans:
            return ""
        parts: list[str] = []
        last_span: dict | None = None
        for span in spans:
            text = span.get("text", "")
            if not text:
                continue
            if parts and last_span is not None:
                gap = span["bbox"][0] - last_span["bbox"][2]
                if gap > 1.0 and not parts[-1].endswith(" ") and not text.startswith(" "):
                    parts.append(" ")
            parts.append(text)
            last_span = span
        return "".join(parts)

    def _extract_tables(self, page, page_num: int) -> list[TableBlock]:
        try:
            tables = page.find_tables()
            result = []
            for table in tables:
                rows = table.extract()
                if rows and len(rows) > 1:
                    result.append(TableBlock(rows=rows, page_num=page_num))
            return result
        except Exception:
            return []

    def _extract_images(self, doc, page, page_num: int) -> list[ImageBlock]:
        images = []
        seen_xrefs: set[int] = set()
        for idx, img_info in enumerate(page.get_images(full=True)):
            xref = img_info[0]
            if xref in seen_xrefs:
                continue
            seen_xrefs.add(xref)
            try:
                img_dict = doc.extract_image(xref)
                w, h = img_dict["width"], img_dict["height"]
                if w < self.MIN_IMAGE_SIZE or h < self.MIN_IMAGE_SIZE:
                    continue
                images.append(ImageBlock(
                    data=img_dict["image"],
                    ext=img_dict["ext"],
                    width=w,
                    height=h,
                    page_num=page_num,
                    img_index=idx,
                ))
            except Exception:
                continue
        return images
