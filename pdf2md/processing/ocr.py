import os
import re
import sys
import io

try:
    import pytesseract
    from PIL import Image

    # Set Tesseract path on Windows — installer does not always add it to PATH
    if sys.platform == "win32":
        _win_path = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
        if os.path.exists(_win_path):
            pytesseract.pytesseract.tesseract_cmd = _win_path

    _OCR_IMPORT_OK = True
except ImportError:
    _OCR_IMPORT_OK = False

# Table detection thresholds (image rendered at 2x scale via fitz.Matrix(2,2))
_TSV_CONF_MIN = 30       # minimum Tesseract word confidence to include
_ROW_Y_TOL = 8           # px: y-difference to group words into the same visual row
_CELL_GAP = 20           # px: fallback gap threshold when no coverage-based boundaries found
_COVERAGE_GAP_MIN = 25   # px: minimum pixel gap in word coverage (straight scan)
_COVERAGE_GAP_DESKEWED = 10  # px: tighter threshold after skew correction
_TABLE_MIN_ROWS = 2      # minimum rows to qualify as a table
_TABLE_MIN_COLS = 2      # minimum cells per row to be a table candidate
_TABLE_MERGE_GAP = 5     # max non-table rows between two table segments to merge them

# Distinguishing a real (borderless) table from a multi-column prose layout.
# A two-column page (manual body text) fills exactly 2 cells per row; only a
# genuine table fills 3+. Margin-near coverage gaps are page margins, not columns.
_MARGIN_FRAC = 0.08          # gaps within this fraction of either edge are margins, dropped
_TABLE_MIN_FILLED = 3        # a coverage row is "tabular" only with this many filled cells
_COVERAGE_TABLE_MIN_ROWS = 3 # min consecutive tabular rows to emit a borderless table

# Bordered-grid acceptance: reject narrow illustration/barcode bands by demanding a
# real multi-column body. Measured on Manuel opti: genuine tables have >=3 columns
# and many populated rows; bogus grids (cover, drawings) have 2 cols / few rows.
_GRID_MIN_COLS = 3           # minimum columns for an accepted bordered table
_GRID_MIN_TABLE_ROWS = 4     # minimum rows with >=2 filled cells inside the grid band

# Skew detection thresholds
_SKEW_MIN_APPLY = 0.3    # degrees: below this, skip rotation (noise)
_SKEW_MAX_APPLY = 10.0   # degrees: above this, probably wrong detection

# Bordered-table grid detection (vertical rule lines)
_RULE_DARK_MAX = 180     # grayscale value below which a pixel counts as "dark"
_RULE_RUN_MIN = 60       # px: minimum continuous vertical dark run to be a rule
_RULE_RUN_FRAC = 0.045   # or this fraction of image height, whichever is larger
_RULE_MAX_WIDTH = 8      # px: rules are thin; wider dark bands are text/margins
_RULE_MERGE_DIST = 10    # px: merge rule candidates closer than this
_SLOT_DENSITY_FRAC = 0.1  # a column slot is "dense" if this fraction of rows fill it
_NARROW_COL_MAX = 60     # px: columns narrower than this hold menu-path digits only


def _run_ocr(image: "Image.Image", lang: str = "fra+eng") -> str:
    """Run Tesseract, fall back to English-only if French data is missing."""
    try:
        return pytesseract.image_to_string(image, lang=lang).strip()
    except pytesseract.TesseractError:
        return pytesseract.image_to_string(image, lang="eng").strip()


def _run_tsv(image: "Image.Image") -> dict:
    """Run Tesseract in TSV/data mode to get word-level bounding boxes."""
    try:
        return pytesseract.image_to_data(image, lang="fra+eng", output_type=pytesseract.Output.DICT)
    except pytesseract.TesseractError:
        return pytesseract.image_to_data(image, lang="eng", output_type=pytesseract.Output.DICT)


def extract_text_from_image(image_data: bytes) -> str:
    """Return OCR text from raw image bytes, or empty string if OCR unavailable."""
    if not ocr_available():
        return ""
    try:
        return _run_ocr(Image.open(io.BytesIO(image_data)))
    except Exception:
        return ""


def extract_text_from_page_pixmap(pixmap_bytes: bytes) -> str:
    """Return OCR text from a rendered page pixmap (PNG bytes)."""
    if not ocr_available():
        return ""
    try:
        return _run_ocr(Image.open(io.BytesIO(pixmap_bytes)))
    except Exception:
        return ""


def _detect_skew_angle(img: "Image.Image") -> float:
    """
    Detect skew angle using horizontal projection profile variance maximisation.

    A well-aligned page has sharp horizontal text bands → high row-sum variance.
    Two-pass search: coarse ±5° at 0.5° step, then fine ±1° at 0.1° around best coarse.
    Returns the angle to pass to img.rotate() to correct the skew.
    """
    try:
        import numpy as np
    except ImportError:
        return 0.0

    def _variance(angle: float) -> float:
        rotated = img.rotate(angle, expand=False, fillcolor=255)
        arr = np.array(rotated.convert("L"))
        binary = (arr < 200).astype(np.float32)
        return float(binary.sum(axis=1).var())

    coarse = [a * 0.5 for a in range(-10, 11)]
    best_coarse = max(coarse, key=_variance)

    fine = [best_coarse + a * 0.1 for a in range(-10, 11)]
    return max(fine, key=_variance)


def _detect_column_boundaries(words: list, gap_min: int = _COVERAGE_GAP_MIN) -> list[int]:
    """
    Find column boundaries as gaps in horizontal word coverage.

    Builds a pixel-level coverage map from all word bounding boxes, then
    returns the midpoints of gaps >= gap_min that have content on both sides.
    """
    if not words:
        return []
    min_x = min(w[0] for w in words)
    max_x = max(w[2] for w in words) + 1
    coverage = bytearray(max_x)
    for w in words:
        for x in range(max(0, w[0]), min(max_x, w[2])):
            coverage[x] = 1

    boundaries = []
    in_gap = False
    gap_start = 0
    for x in range(min_x, max_x):
        if not coverage[x] and not in_gap:
            in_gap = True
            gap_start = x
        elif coverage[x] and in_gap:
            in_gap = False
            gap_len = x - gap_start
            if gap_len >= gap_min:
                boundaries.append(gap_start + gap_len // 2)
    return sorted(boundaries)


def _assign_row_to_columns(row: list, boundaries: list[int]) -> list[str]:
    """Assign words in a row to columns using pre-detected column boundary x-positions."""
    ncols = len(boundaries) + 1
    cells: list[list[str]] = [[] for _ in range(ncols)]
    for word in row:
        x_center = (word[0] + word[2]) // 2
        col = sum(1 for b in boundaries if x_center > b)
        col = min(col, ncols - 1)
        text = word[4].lstrip("|").strip()
        if text:
            cells[col].append(text)
    return [" ".join(c) for c in cells]


def _vertical_rules(gray, height: int, width: int, smear: int) -> list[int]:
    """Locate thin vertical rule lines as columns with a long continuous dark run.

    ``smear`` widens darkness sideways by that many px so a slightly slanted scan
    rule still reads as one continuous run; 0 keeps the crisp straight-scan result.
    """
    import numpy as np

    dark = gray < _RULE_DARK_MAX
    if smear:
        smeared = dark.copy()
        for s in range(1, smear + 1):
            smeared[:, s:] |= dark[:, :-s]
            smeared[:, :-s] |= dark[:, s:]
        dark = smeared

    run = np.zeros(width, dtype=np.int32)
    best = np.zeros(width, dtype=np.int32)
    for y in range(height):
        run = np.where(dark[y], run + 1, 0)
        best = np.maximum(best, run)

    run_min = max(_RULE_RUN_MIN, int(height * _RULE_RUN_FRAC))
    rules: list[int] = []
    x = 0
    while x < width:
        if best[x] >= run_min:
            start = x
            while x < width and best[x] >= run_min:
                x += 1
            if (x - start) <= _RULE_MAX_WIDTH:
                rules.append(start + (x - start) // 2)
        else:
            x += 1

    merged: list[int] = []  # merge near-duplicate rules (slightly thick border)
    for r in rules:
        if merged and r - merged[-1] <= _RULE_MERGE_DIST:
            continue
        merged.append(r)
    return merged


def _grid_from_rules(merged: list[int], rows: list) -> tuple[int, int, list[int]] | None:
    """Pick the contiguous block of rule-delimited slots that rows actually fill.

    This discards page margins and rotated section labels sitting outside the
    table body. Returns (border_left, border_right, separators) or None.
    """
    if len(merged) < 2:
        return None

    nslots = len(merged) - 1
    slot_rows = [0] * nslots
    for row in rows:
        present = [False] * nslots
        for w in row:
            xc = (w[0] + w[2]) // 2
            for k in range(nslots):
                if merged[k] < xc <= merged[k + 1]:
                    present[k] = True
                    break
        for k in range(nslots):
            if present[k]:
                slot_rows[k] += 1

    dense_min = max(3, int(len(rows) * _SLOT_DENSITY_FRAC))
    dense = [c >= dense_min for c in slot_rows]

    best_a = best_len = 0
    cur_a = None
    for k in range(nslots):
        if dense[k]:
            if cur_a is None:
                cur_a = k
            if k - cur_a + 1 > best_len:
                best_len = k - cur_a + 1
                best_a = cur_a
        else:
            cur_a = None
    if best_len < 2:  # need at least 2 columns
        return None

    a = best_a
    b = best_a + best_len - 1
    return merged[a], merged[b + 1], merged[a + 1 : b + 1]


def _detect_table_grid(img: "Image.Image", rows: list) -> tuple[int, int, list[int]] | None:
    """
    Detect a bordered-table column grid from vertical rule lines.

    A printed table border is a thin column of pixels with a long *continuous*
    vertical dark run (unlike text, whose runs are at most one glyph tall).

    Slant tolerance is data-dependent: a deskewed scan needs some horizontal
    smear to keep slanted rules continuous, but too much smear fuses thin rules
    on a crisp page and loses columns. So we try several smear levels and keep
    the grid that resolves the most columns (widest span breaks ties).
    """
    try:
        import numpy as np
    except ImportError:
        return None

    gray = np.asarray(img.convert("L"))
    height, width = gray.shape

    best_grid = None
    best_score = (-1, -1)
    for smear in (0, 1, 2):
        grid = _grid_from_rules(_vertical_rules(gray, height, width, smear), rows)
        if grid is None:
            continue
        score = (len(grid[2]), grid[1] - grid[0])  # (n separators, span width)
        if score > best_score:
            best_score = score
            best_grid = grid
    return best_grid


def _assign_row_grid(
    row: list, border_left: int, separators: list[int], border_right: int
) -> list[str]:
    """
    Assign words to a fixed bordered-table grid.

    Cells in narrow columns (menu-path digits) are stripped to alphanumerics to
    remove border characters Tesseract glues onto digits (``|2``, ``[4``, ``7_|2``).
    Wider columns keep their text intact (brackets there are legitimate).
    """
    edges = [border_left] + separators + [border_right]
    ncols = len(separators) + 1
    narrow = [(edges[k + 1] - edges[k]) < _NARROW_COL_MAX for k in range(ncols)]
    cells: list[list[str]] = [[] for _ in range(ncols)]
    for word in row:
        xc = (word[0] + word[2]) // 2
        col = min(sum(1 for b in separators if xc > b), ncols - 1)
        if narrow[col]:
            text = re.sub(r"[^0-9A-Za-z]", "", word[4])
        else:
            text = word[4].lstrip("|").strip()
        if text:
            cells[col].append(text)
    return [" ".join(c) for c in cells]


def _collect_words(data: dict) -> list[tuple[int, int, int, int, str, int, int]]:
    """Extract confident, non-border words from a Tesseract TSV data dict."""
    word_list = []
    for i, raw_text in enumerate(data["text"]):
        text = str(raw_text).strip()
        if not text or int(data["conf"][i]) < _TSV_CONF_MIN:
            continue
        l = data["left"][i]
        t = data["top"][i]
        w = data["width"][i]
        h = data["height"][i]
        word_list.append((l, t, l + w, t + h, text, data["block_num"][i], data["par_num"][i]))
    # Remove standalone | tokens — they are vertical table borders OCR'd as characters
    return [w for w in word_list if w[4] != "|"]


def _cluster_rows(word_list: list) -> list[list]:
    """Cluster words into visual rows by y-position proximity, each sorted by x."""
    rows: list[list] = []
    row_tops: list[int] = []
    for word in sorted(word_list, key=lambda w: w[1]):
        top = word[1]
        for i, rt in enumerate(row_tops):
            if abs(top - rt) <= _ROW_Y_TOL:
                rows[i].append(word)
                break
        else:
            row_tops.append(top)
            rows.append([word])
    return [sorted(r, key=lambda w: w[0]) for r in rows]


def _interior_boundaries(word_list: list, width: int, gap_min: int) -> list[int]:
    """Coverage-gap column boundaries with page-margin gaps removed.

    A two-column body has one central gutter; only gaps that sit clearly inside
    the text area (not hugging an edge) count as real column separators.
    """
    margin = int(width * _MARGIN_FRAC)
    return [
        b for b in _detect_column_boundaries(word_list, gap_min=gap_min)
        if margin < b < width - margin
    ]


def _words_to_text(words: list) -> str:
    """Join words in reading order: cluster into lines (y proximity), each
    line left-to-right, lines top-to-bottom. Sorting by raw ``top`` alone would
    scramble within-line order, since word tops vary by a few px on one line."""
    lines: list[list] = []
    line_tops: list[int] = []
    for w in sorted(words, key=lambda w: w[1]):
        for i, lt in enumerate(line_tops):
            if abs(w[1] - lt) <= _ROW_Y_TOL:
                lines[i].append(w)
                break
        else:
            line_tops.append(w[1])
            lines.append([w])
    parts = [" ".join(x[4] for x in sorted(ln, key=lambda w: w[0])) for ln in lines]
    return " ".join(parts).strip()


def _columnar_paragraphs(words: list, boundaries: list[int]) -> list[str]:
    """Reconstruct paragraphs in reading order across columns.

    Words are bucketed into columns by x first (so a two-column scan is never
    read across the gutter, even when Tesseract merged both columns into one
    line), then grouped into paragraphs per column by Tesseract block/par.
    Columns are emitted left to right, paragraphs top to bottom within each.
    """
    ncols = len(boundaries) + 1
    cols: list[list] = [[] for _ in range(ncols)]
    for w in words:
        xc = (w[0] + w[2]) // 2
        c = min(sum(1 for b in boundaries if xc > b), ncols - 1)
        cols[c].append(w)

    paragraphs: list[str] = []
    for col in cols:
        if not col:
            continue
        groups: dict[tuple[int, int], list] = {}
        order: list[tuple[int, int]] = []
        for w in col:
            key = (w[5], w[6])  # (block_num, par_num)
            if key not in groups:
                groups[key] = []
                order.append(key)
            groups[key].append(w)
        # Emit paragraphs top-to-bottom by their first line within the column
        order.sort(key=lambda k: min(w[1] for w in groups[k]))
        for key in order:
            text = _words_to_text(groups[key])
            if text:
                paragraphs.append(text)
    return paragraphs


def _grid_is_valid(grid: tuple, rows: list) -> bool:
    """Accept a bordered grid only if it has a real multi-column body.

    Rejects narrow illustration/barcode bands (cover pages, diagrams) that
    happen to produce a couple of vertical rules: those have <3 columns or
    too few populated rows.
    """
    border_left, border_right, separators = grid
    if len(separators) + 1 < _GRID_MIN_COLS:
        return False
    populated = 0
    for r in rows:
        in_band = [w for w in r if border_left <= (w[0] + w[2]) // 2 <= border_right]
        cells = _assign_row_grid(in_band, border_left, separators, border_right)
        if sum(1 for c in cells if c) >= 2:
            populated += 1
    return populated >= _GRID_MIN_TABLE_ROWS


def _emit_grid_table(
    grid: tuple, rows: list, word_list: list, boundaries_gap: int, width: int
) -> tuple[list[str], list[list[list[str]]]]:
    """Build the bordered table and return all text outside it as paragraphs.

    Text to the left/right of the table band (e.g. a legend column beside the
    table) and above/below its vertical span is preserved as prose — never
    dropped just because a table was found on the page.
    """
    border_left, border_right, separators = grid
    table_rows: list[list[str]] = []
    spans: list[tuple[int, int]] = []
    for r in sorted(rows, key=lambda r: min(w[1] for w in r)):
        in_band = [w for w in r if border_left <= (w[0] + w[2]) // 2 <= border_right]
        cells = _assign_row_grid(in_band, border_left, separators, border_right)
        if sum(1 for c in cells if c) >= 2:
            spans.append((min(w[1] for w in in_band), max(w[3] for w in in_band)))
        if any(cells):
            table_rows.append(cells)

    y0 = min(s[0] for s in spans)
    y1 = max(s[1] for s in spans)
    outside = [
        w for w in word_list
        if not (border_left <= (w[0] + w[2]) // 2 <= border_right
                and y0 <= (w[1] + w[3]) // 2 <= y1)
    ]
    paragraphs = _columnar_paragraphs(outside, _interior_boundaries(outside, width, boundaries_gap))
    return paragraphs, ([table_rows] if table_rows else [])


def extract_structured_from_pixmap(
    pixmap_bytes: bytes,
) -> tuple[list[str], list[list[list[str]]]]:
    """
    Extract text paragraphs and table structures from a rendered page.

    Automatically detects and corrects scan skew before OCR analysis, then
    distinguishes three layouts: a bordered table (printed vertical rules), a
    borderless table (3+ aligned columns), and plain multi-column prose (a
    two-column manual body, emitted in reading order — never shredded into a
    table). Text never belonging to a table is always returned as paragraphs.

    Returns:
        paragraphs: list of text strings, in reading order
        tables: list of tables, each table is list[list[str]] (rows x cells)
    """
    if not ocr_available():
        return [], []
    try:
        img = Image.open(io.BytesIO(pixmap_bytes))
        data = _run_tsv(img)
    except Exception:
        return [], []

    word_list = _collect_words(data)
    if not word_list:
        return [], []

    # Detect and correct skew — skewed scans cause column gaps to appear narrower
    skew_angle = _detect_skew_angle(img)
    deskewed = _SKEW_MIN_APPLY <= abs(skew_angle) <= _SKEW_MAX_APPLY
    if deskewed:
        img = img.rotate(skew_angle, expand=False, fillcolor=(255, 255, 255))
        data = _run_tsv(img)
        word_list = _collect_words(data)
        if not word_list:
            return [], []

    gap_min = _COVERAGE_GAP_DESKEWED if deskewed else _COVERAGE_GAP_MIN
    width = img.size[0]
    rows = _cluster_rows(word_list)

    # 1. Bordered table — accept only a validated wide multi-column grid; keep
    #    surrounding text as prose.
    grid = _detect_table_grid(img, rows)
    if grid is not None and _grid_is_valid(grid, rows):
        return _emit_grid_table(grid, rows, word_list, gap_min, width)

    # 2. Coverage columns: tell a borderless table from a multi-column text body.
    boundaries = _interior_boundaries(word_list, width, gap_min)
    cells_per_row = [_assign_row_to_columns(r, boundaries) for r in rows]
    filled_per_row = [sum(1 for c in cells if c) for cells in cells_per_row]

    # A row is "tabular" only with _TABLE_MIN_FILLED+ filled cells — a two-column
    # prose row fills exactly two and must stay prose.
    in_table = [False] * len(rows)
    i = 0
    while i < len(rows):
        if filled_per_row[i] >= _TABLE_MIN_FILLED:
            j = i + 1
            while j < len(rows) and filled_per_row[j] >= _TABLE_MIN_FILLED:
                j += 1
            if j - i >= _COVERAGE_TABLE_MIN_ROWS:
                for k in range(i, j):
                    in_table[k] = True
            i = j
        else:
            i += 1

    # Merge table segments separated by at most _TABLE_MERGE_GAP non-table rows
    i = 0
    while i < len(in_table):
        if not in_table[i]:
            j = i
            while j < len(in_table) and not in_table[j]:
                j += 1
            before = any(in_table[:i])
            after = j < len(in_table) and any(in_table[j:])
            if before and after and (j - i) <= _TABLE_MERGE_GAP:
                for k in range(i, j):
                    in_table[k] = True
            i = j
        else:
            i += 1

    # Extract tables as grouped cell lists; drop pure-border rows (all cells empty)
    tables: list[list[list[str]]] = []
    i = 0
    while i < len(rows):
        if in_table[i]:
            j = i
            while j < len(rows) and in_table[j]:
                j += 1
            table_rows = [cells_per_row[k] for k in range(i, j) if any(cells_per_row[k])]
            if table_rows:
                tables.append(table_rows)
            i = j
        else:
            i += 1

    # Everything not in a table → prose, in column reading order
    prose_words = [w for i, row in enumerate(rows) if not in_table[i] for w in row]
    paragraphs = _columnar_paragraphs(prose_words, boundaries)
    return paragraphs, tables


def ocr_available() -> bool:
    if not _OCR_IMPORT_OK:
        return False
    try:
        pytesseract.get_tesseract_version()
        return True
    except Exception:
        return False
