import json
import re
from collections.abc import Callable
from pathlib import Path
from ..input.models import Document, ImageBlock, Section, TextBlock
from .serializer import blocks_to_text, table_to_markdown
from ..processing.ocr import extract_text_from_image, ocr_available

_MIN_MEANINGFUL_ALPHA = 20
_MAX_GARBLED_UPPER_RATIO = 0.55
_GARBLE_INDICATOR_CHARS = frozenset('€ÿþ')
_GARBLE_EMBED_RE = re.compile(r'[A-Za-z][!|}\[\]][A-Za-z]')


_GRAPHIC_MIN_AREA = 50_000       # px² — smaller images are never treated as "graphic"
_GRAPHIC_ALPHA_DENSITY = 3_000   # 1 alpha char per N pixels — below this → graphic


def _looks_like_graphic(image: ImageBlock, ocr_text: str) -> bool:
    """Large image with sparse OCR text → diagram/chart, not a text block."""
    area = image.width * image.height
    if area < _GRAPHIC_MIN_AREA:
        return False
    alpha = sum(1 for c in ocr_text if c.isalpha())
    return alpha < area / _GRAPHIC_ALPHA_DENSITY


def _is_meaningful_ocr(text: str) -> bool:
    if not text or not text.strip():
        return False
    alpha = [c for c in text if c.isalpha()]
    if len(alpha) < _MIN_MEANINGFUL_ALPHA:
        return False
    if sum(1 for c in alpha if c.isupper()) / len(alpha) > _MAX_GARBLED_UPPER_RATIO:
        return False
    # Reject garbled OCR output (e.g. from upside-down images)
    if any(c in _GARBLE_INDICATOR_CHARS for c in text):
        return False
    if _GARBLE_EMBED_RE.search(text):
        return False
    return True


def _group_by_page(blocks: list[TextBlock]) -> dict[int, list[TextBlock]]:
    result: dict[int, list[TextBlock]] = {}
    for b in blocks:
        if b.text.strip():
            result.setdefault(b.page_num, []).append(b)
    return result


class DocumentWriter:
    def __init__(self):
        self._ocr = ocr_available()

    def write(
        self,
        doc: Document,
        out_dir: Path,
        stem: str,
        progress_cb: Callable[[int, int], None] | None = None,
    ) -> list[Path]:
        """Write one MD file per page + an index file inside out_dir.

        Pages that contain tables also get a sibling ``_pNN.tables.json`` holding
        the raw table rows (cells as strings), for machine consumption.
        """
        img_dir = out_dir / "md_images"
        pages: dict[int, list[str]] = {}
        page_tables: dict[int, list[list[list[str]]]] = {}

        # Preamble: group by page so blocks_to_text can detect consecutive list items
        for page_num, p_blocks in _group_by_page(doc.preamble).items():
            text = blocks_to_text(p_blocks)
            if text:
                pages.setdefault(page_num, []).append(text)

        for table in doc.preamble_tables:
            text = table_to_markdown(table.rows)
            if text:
                pages.setdefault(table.page_num, []).append(text)
                page_tables.setdefault(table.page_num, []).append(table.rows)

        for image in doc.preamble_images:
            rendered = self._render_image(image, img_dir)
            if rendered:
                pages.setdefault(image.page_num, []).append(rendered)

        for section in doc.root_sections:
            self._collect_section(section, pages, img_dir, page_tables)

        for page_num in range(1, doc.page_count + 1):
            pages.setdefault(page_num, [])

        pad = max(len(str(doc.page_count)), 2)
        page_md_files: list[Path] = []   # one .md per page, in page order (for the index)
        out_files: list[Path] = []       # everything written (.md + .tables.json)
        page_headings: dict[int, str] = {}

        for page_num in sorted(pages):
            parts = [p for p in pages[page_num] if p.strip()]
            for part in parts:
                if part.startswith("#") and page_num not in page_headings:
                    page_headings[page_num] = part.lstrip("#").strip()
                    break
            out_file = out_dir / f"{stem}_p{page_num:0{pad}d}.md"
            out_file.write_text("\n\n".join(parts), encoding="utf-8")
            page_md_files.append(out_file)
            out_files.append(out_file)

            tables = page_tables.get(page_num)
            if tables:
                json_file = out_dir / f"{stem}_p{page_num:0{pad}d}.tables.json"
                payload = {"page": page_num, "tables": tables}
                json_file.write_text(
                    json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                out_files.append(json_file)

            if progress_cb:
                progress_cb(page_num, doc.page_count)

        index_file = self._write_index(out_dir, stem, doc, page_md_files, page_headings)
        return out_files + [index_file]

    def _collect_section(
        self,
        section: Section,
        pages: dict[int, list[str]],
        img_dir: Path,
        page_tables: dict[int, list[list[list[str]]]],
    ):
        heading_mark = "#" * section.level
        pages.setdefault(section.page_num, []).append(f"{heading_mark} {section.heading}")

        # Group text blocks by page — preserves page placement and enables list detection
        for page_num, p_blocks in sorted(_group_by_page(section.text_blocks).items()):
            text = blocks_to_text(p_blocks)
            if text:
                pages.setdefault(page_num, []).append(text)

        for table in section.tables:
            text = table_to_markdown(table.rows)
            if text:
                pages.setdefault(table.page_num, []).append(text)
                page_tables.setdefault(table.page_num, []).append(table.rows)

        for image in section.images:
            rendered = self._render_image(image, img_dir)
            if rendered:
                pages.setdefault(image.page_num, []).append(rendered)

        for child in section.children:
            self._collect_section(child, pages, img_dir, page_tables)

    def _render_image(self, image: ImageBlock, img_dir: Path) -> str | None:
        """Try OCR; save as file if result is not meaningful or image looks like a graphic."""
        if not image.data:
            return None
        if self._ocr:
            text = extract_text_from_image(image.data)
            if _is_meaningful_ocr(text) and not _looks_like_graphic(image, text):
                return text
        return self._save_image_file(image, img_dir)

    def _save_image_file(self, image: ImageBlock, img_dir: Path) -> str:
        img_dir.mkdir(exist_ok=True)
        filename = f"p{image.page_num:02d}_{image.img_index:02d}.{image.ext}"
        (img_dir / filename).write_bytes(image.data)
        rel = f"{img_dir.name}/{filename}"
        return f"![Image p{image.page_num} #{image.img_index + 1}](<{rel}>)"

    def _write_index(
        self,
        out_dir: Path,
        stem: str,
        doc: Document,
        page_files: list[Path],
        page_headings: dict[int, str],
    ) -> Path:
        img_dir = out_dir / "md_images"
        lines: list[str] = [
            f"# {doc.title}",
            "",
            f"Source : `{doc.path.name}` — {doc.page_count} page(s)",
            "",
        ]
        if img_dir.exists():
            img_count = sum(1 for _ in img_dir.iterdir())
            lines += [f"Images extraites : {img_count} fichier(s) dans `{img_dir.name}/`", ""]

        lines += ["## Pages", ""]
        for i, page_file in enumerate(page_files):
            page_num = i + 1
            label = page_headings.get(page_num, f"Page {page_num}")
            lines.append(f"- [Page {page_num} — {label}]({page_file.name})")

        index_file = out_dir / f"{stem}_index.md"
        index_file.write_text("\n".join(lines), encoding="utf-8")
        return index_file
