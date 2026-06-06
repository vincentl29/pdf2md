import re
from ..input.models import TextBlock, TableBlock

# Bullet characters that Markdown doesn't natively recognise
_BULLET_CHARS = frozenset('•·▪▸›◦▹‣⁃')

# Matches: "- text", "* text", "+ text", "1. text", "1) text", "a. text", "a) text"
_LIST_PREFIX_RE = re.compile(r'^(\d+[.)]\s|\(?[a-z][.)]\s|[-*+]\s)')

# TOC entry: "Some title .... 12" or "Some title   12"
_TOC_ENTRY_RE = re.compile(r'^(.+?)[\s.]{2,}(\d{1,4})\s*$')


def slugify(text: str, max_len: int = 50) -> str:
    text = text.lower()
    text = re.sub(r"[^\w\s-]", "", text, flags=re.UNICODE)
    text = re.sub(r"[\s_-]+", "_", text)
    return text.strip("_")[:max_len]


def _is_list_item(text: str) -> bool:
    if not text:
        return False
    if text[0] in _BULLET_CHARS:
        return True
    return bool(_LIST_PREFIX_RE.match(text))


def _normalize_list_item(text: str) -> str:
    """Convert any bullet character to Markdown '- '."""
    if text and text[0] in _BULLET_CHARS:
        return "- " + text[1:].lstrip()
    return text


def _is_toc_entry(text: str) -> bool:
    return bool(_TOC_ENTRY_RE.match(text))


def blocks_to_text(blocks: list[TextBlock]) -> str:
    """Join paragraph blocks, normalising list items and grouping consecutive items."""
    if not blocks:
        return ""

    items: list[tuple[str, str]] = []  # (kind, text)  kind = 'list' | 'toc' | 'para'
    for b in blocks:
        text = b.text.strip()
        if not text:
            continue
        if _is_list_item(text):
            items.append(("list", _normalize_list_item(text)))
        elif _is_toc_entry(text):
            items.append(("toc", text))
        else:
            items.append(("para", text))

    if not items:
        return ""

    result = [items[0][1]]
    for i in range(1, len(items)):
        prev_kind = items[i - 1][0]
        cur_kind = items[i][0]
        # Consecutive list/toc items → single newline; otherwise paragraph gap
        same_run = cur_kind == prev_kind and cur_kind in ("list", "toc")
        result.append(("\n" if same_run else "\n\n") + items[i][1])

    return "".join(result)


def table_to_plain_text(rows: list[list]) -> str:
    """Extract table content as plain text — one row per line, cells separated by spaces."""
    lines = []
    for row in rows:
        cells = [str(cell or "").strip() for cell in row if str(cell or "").strip()]
        if cells:
            lines.append("  ".join(cells))
    return "\n".join(lines)


def _esc(text: str) -> str:
    """Escape pipe characters inside a table cell."""
    return text.replace("|", r"\|")


def table_to_markdown(rows: list[list]) -> str:
    if not rows:
        return ""
    cleaned = [[str(cell or "").strip() for cell in row] for row in rows]
    # Column count is defined by the first row; other rows are padded or truncated
    ncols = len(cleaned[0])
    if ncols == 0:
        return ""
    lines = [
        "| " + " | ".join(_esc(c) for c in cleaned[0]) + " |",
        "| " + " | ".join(["---"] * ncols) + " |",
    ]
    for row in cleaned[1:]:
        row = (row + [""] * ncols)[:ncols]
        lines.append("| " + " | ".join(_esc(c) for c in row) + " |")
    return "\n".join(lines)
