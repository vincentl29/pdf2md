import json
from pathlib import Path
from ..input.models import Section, Document, ImageBlock, TableBlock
from .serializer import slugify, blocks_to_text, table_to_markdown, table_to_json
from ..processing.ocr import extract_text_from_image, ocr_available

HEADING_MD = {1: "#", 2: "##", 3: "###"}


class FileSplitter:
    def __init__(self, output_dir: Path):
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.generated: list[dict] = []
        self._img_n = 0
        self._tbl_n = 0
        self._ocr = ocr_available()

    def split(self, doc: Document) -> list[dict]:
        self.generated = []
        self._img_n = 0
        self._tbl_n = 0

        # Preamble (content before first heading)
        has_preamble = doc.preamble or doc.preamble_tables or doc.preamble_images
        if has_preamble:
            preamble_section = Section(
                heading=doc.title,
                level=1,
                page_num=0,
                text_blocks=doc.preamble,
                tables=doc.preamble_tables,
                images=doc.preamble_images,
            )
            self._write_section(preamble_section, prefix="00")

        for i, section in enumerate(doc.root_sections, start=1):
            self._recurse(section, prefix=f"{i:02d}")

        return self.generated

    def _recurse(self, section: Section, prefix: str) -> None:
        self._write_section(section, prefix)
        for j, child in enumerate(section.children, start=1):
            self._recurse(child, prefix=f"{prefix}_{j:02d}")

    def _write_section(self, section: Section, prefix: str) -> None:
        slug = slugify(section.heading)
        filepath = self.output_dir / f"{prefix}_{slug}.md"
        hmark = HEADING_MD.get(section.level, "#")

        lines: list[str] = [f"{hmark} {section.heading}", ""]

        body = blocks_to_text(section.text_blocks)
        if body:
            lines += [body, ""]

        for table in section.tables:
            self._tbl_n += 1
            tbl_prefix = f"{prefix}_table_{self._tbl_n:03d}"
            self._write_table(table, tbl_prefix)
            lines += [table_to_markdown(table.rows), ""]

        for image in section.images:
            self._img_n += 1
            img_prefix = f"{prefix}_img_{self._img_n:03d}"
            img_path, ocr_text = self._write_image(image, img_prefix)
            lines += [f"![{img_prefix}]({img_path.name})", ""]
            if ocr_text:
                lines += [ocr_text, ""]

        filepath.write_text("\n".join(lines), encoding="utf-8")
        self.generated.append({
            "path": filepath,
            "title": section.heading,
            "type": "section",
            "level": section.level,
        })

    def _write_table(self, table: TableBlock, prefix: str) -> None:
        json_path = self.output_dir / f"{prefix}.json"
        json_path.write_text(
            json.dumps(table_to_json(table.rows), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        self.generated.append({"path": json_path, "title": prefix, "type": "table_json"})

    def _write_image(self, image: ImageBlock, prefix: str) -> tuple[Path, str]:
        img_path = self.output_dir / f"{prefix}.{image.ext}"
        img_path.write_bytes(image.data)
        ocr_text = extract_text_from_image(image.data) if self._ocr else ""
        self.generated.append({"path": img_path, "title": prefix, "type": "image"})
        return img_path, ocr_text
