"""Write a DoclingResult to the project's output layout.

Mirrors DocumentWriter's contract: one ``{stem}_pNN.md`` per page, a
``{stem}_pNN.tables.json`` sidecar for pages that contain a table, and a
``{stem}_index.md`` linking every page (labelled by its first heading).
"""

import json
from collections.abc import Callable
from pathlib import Path

from ..processing.docling_engine import DoclingResult

_IMAGE_PLACEHOLDER = "<!-- image -->"


def _first_heading(markdown: str) -> str | None:
    for line in markdown.splitlines():
        if line.lstrip().startswith("#"):
            return line.lstrip("#").strip()
    return None


def _save_page_images(
    markdown: str,
    images: list[tuple[bytes, str]],
    out_dir: Path,
    stem: str,
    page_no: int,
    pad: int,
) -> tuple[str, list[Path]]:
    """Save images to ``md_images/`` and replace ``<!-- image -->`` markers.

    Each ``<!-- image -->`` in *markdown* is replaced (left to right) with a
    real ``![image](md_images/{filename})`` link corresponding to the image at
    the same position in *images*.  Extra placeholders (no matching image) are
    left as-is; extra images (no matching placeholder) are saved but not linked.

    Returns ``(updated_markdown, list_of_saved_paths)``.
    """
    if not images:
        return markdown, []

    img_dir = out_dir / "md_images"
    img_dir.mkdir(exist_ok=True)
    saved: list[Path] = []
    md = markdown

    for idx, (raw, ext) in enumerate(images):
        img_name = f"{stem}_p{page_no:0{pad}d}_img{idx + 1:02d}.{ext}"
        img_path = img_dir / img_name
        img_path.write_bytes(raw)
        saved.append(img_path)
        md = md.replace(_IMAGE_PLACEHOLDER, f"![image](md_images/{img_name})", 1)

    return md, saved


def write_docling(
    result: DoclingResult,
    out_dir: Path,
    stem: str,
    progress_cb: Callable[[int, int], None] | None = None,
) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    pad = max(len(str(result.page_count)), 2)

    out_files: list[Path] = []
    page_md_files: list[Path] = []
    page_headings: dict[int, str] = {}
    img_dir_added = False  # add md_images/ to out_files at most once

    for page in result.pages:
        raw_md = page.markdown or ""
        md, img_paths = _save_page_images(
            raw_md, page.images, out_dir, stem, page.page_no, pad
        )
        if img_paths and not img_dir_added:
            out_files.append(out_dir / "md_images")
            img_dir_added = True

        md_file = out_dir / f"{stem}_p{page.page_no:0{pad}d}.md"
        md_file.write_text(md, encoding="utf-8")
        page_md_files.append(md_file)
        out_files.append(md_file)

        heading = _first_heading(md)
        if heading:
            page_headings[page.page_no] = heading

        if page.tables:
            json_file = out_dir / f"{stem}_p{page.page_no:0{pad}d}.tables.json"
            payload = {"page": page.page_no, "tables": page.tables}
            json_file.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            out_files.append(json_file)

        if progress_cb:
            progress_cb(page.page_no, result.page_count)

    index_file = _write_index(out_dir, stem, result, page_md_files, page_headings)
    return out_files + [index_file]


def _write_index(
    out_dir: Path,
    stem: str,
    result: DoclingResult,
    page_files: list[Path],
    page_headings: dict[int, str],
) -> Path:
    lines = [
        f"# {result.title}",
        "",
        f"Source : `{result.title}` — {result.page_count} page(s)",
        "",
        "## Pages",
        "",
    ]
    for i, page_file in enumerate(page_files):
        page_no = i + 1
        label = page_headings.get(page_no, f"Page {page_no}")
        lines.append(f"- [Page {page_no} — {label}]({page_file.name})")

    index_file = out_dir / f"{stem}_index.md"
    index_file.write_text("\n".join(lines), encoding="utf-8")
    return index_file
