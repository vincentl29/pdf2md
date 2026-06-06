from collections.abc import Callable
from pathlib import Path
from ..input.loader import PDFLoader
from ..input.models import Document
from .structure import detect_heading_thresholds, build_section_tree, max_depth_for_pages


class ContentExtractor:
    def __init__(self):
        self._loader = PDFLoader()

    def extract(
        self,
        filepath: str | Path,
        progress_cb: Callable[[int, int], None] | None = None,
    ) -> Document:
        path = Path(filepath)
        text_blocks, table_blocks, image_blocks, page_count = self._loader.load(path, progress_cb)

        max_depth = max_depth_for_pages(page_count)
        body_size, thresholds = detect_heading_thresholds(text_blocks, max_depth)

        root_sections, preamble, preamble_tables, preamble_images = build_section_tree(
            text_blocks, table_blocks, image_blocks, body_size, thresholds
        )

        return Document(
            title=path.stem,
            path=path,
            page_count=page_count,
            split_depth=max_depth,
            root_sections=root_sections,
            preamble=preamble,
            preamble_tables=preamble_tables,
            preamble_images=preamble_images,
        )
