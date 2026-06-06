from collections import Counter
from ..input.models import TextBlock, TableBlock, ImageBlock, Section

SIZE_MARGIN = 1.0  # pt above body to qualify as heading
SIZE_TOLERANCE = 0.5  # pt tolerance when matching a threshold


def max_depth_for_pages(page_count: int) -> int:
    return 3


def detect_heading_thresholds(text_blocks: list[TextBlock], max_depth: int = 3) -> tuple[float, list[float]]:
    """Return (body_size, heading_thresholds) sorted largest-first, capped at max_depth levels.

    Weights each font size by character count so short headings don't distort the body-size estimate.
    """
    size_weights: Counter = Counter()
    for b in text_blocks:
        if b.text.strip():
            size_weights[round(b.font_size, 1)] += len(b.text)
    if not size_weights:
        return 12.0, []

    body_size = size_weights.most_common(1)[0][0]
    heading_sizes = sorted(
        {s for s in size_weights if s > body_size + SIZE_MARGIN},
        reverse=True,
    )
    return body_size, heading_sizes[:max_depth]


def _heading_level(block: TextBlock, body_size: float, thresholds: list[float]) -> int:
    for level, threshold in enumerate(thresholds, start=1):
        if block.font_size >= threshold - SIZE_TOLERANCE:
            return level
    # Bold text slightly above body = deepest heading level
    if block.is_bold and block.font_size > body_size + 0.3 and thresholds:
        return len(thresholds)
    return 0


def build_section_tree(
    text_blocks: list[TextBlock],
    table_blocks: list[TableBlock],
    image_blocks: list[ImageBlock],
    body_size: float,
    thresholds: list[float],
) -> tuple[list[Section], list[TextBlock], list[TableBlock], list[ImageBlock]]:
    """
    Build section hierarchy from flat block lists.
    Returns (root_sections, preamble_text, preamble_tables, preamble_images).
    """
    root_sections: list[Section] = []
    preamble_text: list[TextBlock] = []
    preamble_tables: list[TableBlock] = []
    preamble_images: list[ImageBlock] = []
    stack: list[Section] = []  # current ancestor chain

    for block in text_blocks:
        level = _heading_level(block, body_size, thresholds)
        if level == 0:
            (stack[-1].text_blocks if stack else preamble_text).append(block)
            continue

        section = Section(heading=block.text, level=level, page_num=block.page_num)

        while stack and stack[-1].level >= level:
            stack.pop()

        if stack:
            stack[-1].children.append(section)
        else:
            root_sections.append(section)
        stack.append(section)

    # Assign tables and images to the nearest preceding section by page
    def section_for_page(page_num: int) -> Section | None:
        def _search(sections: list[Section], best: Section | None) -> Section | None:
            for s in sections:
                if s.page_num <= page_num:
                    best = s
                best = _search(s.children, best)
            return best
        return _search(root_sections, None)

    for table in table_blocks:
        target = section_for_page(table.page_num)
        (target.tables if target else preamble_tables).append(table)

    for image in image_blocks:
        target = section_for_page(image.page_num)
        (target.images if target else preamble_images).append(image)

    return root_sections, preamble_text, preamble_tables, preamble_images
