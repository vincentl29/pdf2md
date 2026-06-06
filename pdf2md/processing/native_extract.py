"""Fast local extraction for *native* (vector-text) PDF pages.

When a PDF page already carries a reliable text layer, there is no need to run
the heavy docling model path (layout + OCR): PyMuPDF reads the text instantly
and faithfully (no OCR word-gluing), and pdfplumber recovers vector tables.

The catch — observed on real French manuals — is that many PDFs ship a *broken*
text layer (subset fonts without a correct ToUnicode CMap), so ``get_text``
returns garbage that merely *looks* like text ("Développeur" → "SpYHORSSHXU").
``text_is_reliable`` gates the fast path so only genuinely clean pages take it;
everything else falls back to docling/OCR upstream.
"""

from __future__ import annotations

import re

_VOWELS = set("aeiouyàâäéèêëïîôöùûü")
_BULLET_RE = re.compile(r"^\s*[•▪◦‣·∙•▪⁃◦*]\s+(.*)")
_LEGEND_RE = re.compile(r"(\d+)\s*=\s*")
_IMAGE_PLACEHOLDER = "<!-- image -->"


def _split_legend(text: str) -> str | None:
    """Split an inline numbered legend ("1 = Foo 2 = Bar 3 = Baz") into list items.

    Guarded so ordinary prose containing "=" is left alone: needs ≥2 markers
    whose numbers are strictly consecutive (a real key/legend), with short
    segments. Returns the Markdown list (prefix kept) or None if it isn't one.
    """
    matches = list(_LEGEND_RE.finditer(text))
    if len(matches) < 2:
        return None
    nums = [int(m.group(1)) for m in matches]
    if nums != list(range(nums[0], nums[0] + len(nums))):
        return None
    items: list[str] = []
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        seg = text[m.start():end].strip()
        if len(seg) > 60:
            return None  # too long to be a legend entry — likely prose
        items.append("- " + seg)
    prefix = text[: matches[0].start()].strip()
    return "\n".join(([prefix] if prefix else []) + items)


def _block_markdown(lines: list[str]) -> str:
    """Join a text block's lines, turning bulleted lines into Markdown list items.

    Wrapped continuation lines (no bullet marker) are folded into the preceding
    item/paragraph rather than split, so a bullet spanning two visual lines stays
    one item. Inline numbered legends are expanded into list items too.
    """
    out: list[str] = []
    para: list[str] = []

    def flush() -> None:
        if para:
            joined = " ".join(para)
            out.append(_split_legend(joined) or joined)
            para.clear()

    for ln in lines:
        m = _BULLET_RE.match(ln)
        if m:
            flush()
            out.append("- " + m.group(1).strip())
        elif out and out[-1].startswith("- ") and not para:
            out[-1] += " " + ln.strip()  # continuation of the last bullet
        else:
            para.append(ln.strip())
    flush()
    return "\n".join(out)


def text_is_reliable(text: str) -> bool:
    """Heuristic: is this PyMuPDF text layer actually readable prose?

    Catches the two failure modes seen in the wild:
    - replacement chars '�' from undecodable glyphs,
    - glyph-scrambled text (consistent wrong-letter mapping) — flagged by an
      abnormally low vowel ratio and/or near-absent spaces.
    """
    t = text.strip()
    if len(t) < 30:
        return False
    if t.count("�") / len(t) > 0.01:
        return False
    letters = [c for c in t.lower() if c.isalpha()]
    if not letters:
        return False
    vowel_ratio = sum(c in _VOWELS for c in letters) / len(letters)
    if not (0.26 <= vowel_ratio <= 0.60):
        return False
    if t.count(" ") / len(t) <= 0.08:
        return False
    return True


def _median(values: list[float]) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    n = len(s)
    mid = n // 2
    return s[mid] if n % 2 else (s[mid - 1] + s[mid]) / 2


def _md_table(rows: list[list[str]]) -> str:
    width = max(len(r) for r in rows)
    rows = [r + [""] * (width - len(r)) for r in rows]

    def fmt(r: list[str]) -> str:
        return "| " + " | ".join(c.replace("|", "\\|") for c in r) + " |"

    out = [fmt(rows[0]), "| " + " | ".join(["---"] * width) + " |"]
    out += [fmt(r) for r in rows[1:]]
    return "\n".join(out)


def _drop_empty_cols(rows: list[list[str]]) -> list[list[str]]:
    """Remove columns that are empty in every row (pdfplumber over-segmentation)."""
    if not rows:
        return rows
    width = max(len(r) for r in rows)
    rows = [r + [""] * (width - len(r)) for r in rows]
    keep = [c for c in range(width) if any(r[c].strip() for r in rows)]
    if not keep:
        return rows
    return [[r[c] for c in keep] for r in rows]


def _ncols(rows: list[list[str]]) -> int:
    return max((len(r) for r in rows), default=0)


def _merge_adjacent_tables(
    tables: list[list[list[str]]], bboxes: list[tuple]
) -> tuple[list[list[list[str]]], list[tuple]]:
    """Stitch back tables pdfplumber split into a header band + a body band.

    Two tables are merged when they have the same column count and are nearly
    touching vertically (small gap), which is how a single ruled table often
    comes back in two pieces.
    """
    order = sorted(range(len(tables)), key=lambda i: bboxes[i][1])
    out_t: list[list[list[str]]] = []
    out_b: list[tuple] = []
    for i in order:
        rows, bb = tables[i], bboxes[i]
        if out_t:
            prev_t, prev_b = out_t[-1], out_b[-1]
            gap = bb[1] - prev_b[3]
            row_h = (prev_b[3] - prev_b[1]) / max(len(prev_t), 1)
            if _ncols(prev_t) == _ncols(rows) and -2 <= gap <= max(15.0, 1.4 * row_h):
                out_t[-1] = prev_t + rows
                out_b[-1] = (min(prev_b[0], bb[0]), prev_b[1], max(prev_b[2], bb[2]), bb[3])
                continue
        out_t.append(rows)
        out_b.append(bb)
    return out_t, out_b


def _page_tables(plumber_page) -> tuple[list[list[list[str]]], list[tuple]]:
    """pdfplumber tables → (rows-per-table, bboxes) for vector/native pages."""
    tables: list[list[list[str]]] = []
    bboxes: list[tuple] = []
    try:
        found = plumber_page.find_tables()
    except Exception:
        return tables, bboxes
    for t in found:
        try:
            data = t.extract()
        except Exception:
            continue
        rows = [
            [(c or "").strip().replace("\n", " ") for c in row]
            for row in (data or [])
        ]
        rows = [r for r in rows if any(r)]
        if len(rows) >= 1 and _ncols(rows) >= 2:
            tables.append(rows)
            bboxes.append(t.bbox)  # (x0, top, x1, bottom), top-left origin

    # Merge header/body bands first (raw widths still match), then trim empty
    # columns — otherwise a column that is empty in only one band would split
    # the widths and block the merge.
    tables, bboxes = _merge_adjacent_tables(tables, bboxes)
    out_t: list[list[list[str]]] = []
    out_b: list[tuple] = []
    for rows, bb in zip(tables, bboxes):
        rows = _drop_empty_cols(rows)
        if _ncols(rows) >= 2:
            out_t.append(rows)
            out_b.append(bb)
    return out_t, out_b


def extract_native_page(
    fitz_page, plumber_page
) -> tuple[str, list[list[list[str]]], list[tuple[bytes, str]]]:
    """Render one native PDF page to Markdown + table rows + image bytes.

    Returns ``(markdown, tables, images)`` where ``images`` is a list of
    ``(raw_bytes, ext)`` in reading order — one entry per ``<!-- image -->``
    placeholder in the returned markdown.  Images smaller than 30 pt on either
    side are skipped (decorative borders, bullet icons, etc.).
    Text overlapping a table region is dropped so cell text is not duplicated.
    """
    doc = fitz_page.get_text("dict")
    text_blocks: list[tuple[float, float, float, float, str, float]] = []
    # (iy0, ix0, ix1, iy1, raw_bytes_or_None, ext)
    raw_img_blocks: list[tuple[float, float, float, float, bytes | None, str]] = []
    all_sizes: list[float] = []

    for b in doc.get("blocks", []):
        btype = b.get("type")
        if btype == 1:  # image block
            ix0, iy0, ix1, iy1 = b["bbox"]
            if (ix1 - ix0) < 30 or (iy1 - iy0) < 30:
                continue  # too small — decorative
            raw: bytes | None = b.get("image")
            ext: str = b.get("ext", "png")
            # Some PDFs reference images as XObjects; the inline bytes may be
            # absent. Fall back to extracting via the xref.
            if not raw:
                xref = b.get("xref", 0)
                if xref:
                    try:
                        img_dict = fitz_page.parent.extract_image(xref)
                        raw = img_dict.get("image")
                        ext = img_dict.get("ext", ext)
                    except Exception:
                        pass
            if ext == "jpeg":
                ext = "jpg"
            raw_img_blocks.append((iy0, ix0, ix1, iy1, raw, ext))
            continue
        if btype != 0:  # 0 = text
            continue
        lines_txt: list[str] = []
        sizes: list[float] = []
        for ln in b.get("lines", []):
            span_txt = "".join(s.get("text", "") for s in ln.get("spans", []))
            if span_txt.strip():
                lines_txt.append(span_txt.strip())
                for s in ln.get("spans", []):
                    if s.get("text", "").strip():
                        sizes.append(s.get("size", 0))
        if not lines_txt:
            continue
        text = _block_markdown(lines_txt)
        size = sum(sizes) / len(sizes) if sizes else 0.0
        x0, y0, x1, y1 = b["bbox"]
        text_blocks.append((y0, x0, x1, y1, text, size))
        all_sizes.extend(sizes)

    body = _median([round(s) for s in all_sizes])
    tables, tbboxes = _page_tables(plumber_page)

    def _in_table(cy: float, cx: float) -> bool:
        return any(bt <= cy <= bb and bx0 <= cx <= bx1 for (bx0, bt, bx1, bb) in tbboxes)

    items: list[tuple[float, str, object]] = []
    for y0, x0, x1, y1, text, size in text_blocks:
        if _in_table((y0 + y1) / 2, (x0 + x1) / 2):
            continue  # inside a table — emitted via the table itself
        is_heading = (
            bool(body) and size >= body * 1.25 and len(text) < 80 and "\n" not in text
        )
        items.append((y0, "h" if is_heading else "p", text))

    # Each non-table image with recoverable bytes gets one placeholder (no
    # collapsing — each <!-- image --> maps 1:1 to an entry in images_out).
    images_out: list[tuple[bytes, str]] = []
    for iy0, ix0, ix1, iy1, raw, ext in raw_img_blocks:
        if _in_table((iy0 + iy1) / 2, (ix0 + ix1) / 2):
            continue  # image lives inside a table cell — skip
        if raw:
            items.append((iy0, "img", None))
            images_out.append((raw, ext))

    for (bx0, bt, bx1, bb), rows in zip(tbboxes, tables):
        items.append((bt, "t", rows))

    items.sort(key=lambda it: it[0])
    parts: list[str] = []
    for _top, kind, payload in items:
        if kind == "t":
            block = _md_table(payload)  # type: ignore[arg-type]
        elif kind == "h":
            block = "## " + payload  # type: ignore[operator]
        elif kind == "img":
            block = _IMAGE_PLACEHOLDER
        else:
            block = payload  # type: ignore[assignment]
        parts.append(block)

    return "\n\n".join(parts).strip(), tables, images_out
