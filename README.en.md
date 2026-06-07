# pdf2md

[Français](README.md) · **English**

*A **fully local, offline** PDF → Markdown converter: per-page routing, deep-learning OCR (docling), tables, images, and built-in translation — no API key, no data sent to the cloud.*

![Python](https://img.shields.io/badge/python-3.12%2B-blue)
![uv](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/uv/main/assets/badge/v0.json)
[![License: AGPL v3](https://img.shields.io/badge/License-AGPL_v3-blue.svg)](LICENSE.md)

Converts a PDF (or an image scan) into structured Markdown files, ready to feed to an LLM.

- **Per-page routing**: pages with a genuine text layer are extracted locally and instantly (PyMuPDF + pdfplumber, no OCR, no model load); scanned pages go through **docling** (IBM, deep-learning: layout analysis + TableFormer + RapidOCR).
- One `.md` file per page plus an `_index.md` summary, inside a dedicated subfolder `{output}/{filename}/`.
- **Tables** rendered as Markdown *and* exported as a `{name}_pNN.tables.json` sidecar (for machine consumption).
- **Images** extracted into `md_images/` with a `![image](…)` link replacing the placeholder.
- **Optional automatic translation** (offline) to French by default, or any other language.
- Automatic **GPU acceleration** (CUDA) when an NVIDIA card is present, otherwise CPU.
- Real-time progress bar (extraction then writing) in the GUI.

---

## Why pdf2md?

Most PDF → Markdown converters fall into one of two families: those relying on a **remote vision LLM** (high quality, but an API key is required, there's a per-page cost, and data is sent to the cloud), and those that stay **local but with basic OCR**. pdf2md aims for the gap left between them: **staying fully local while keeping quality OCR**.

In practice, it's the only one to combine these four traits:

- **Per-page routing** — a heavy model is loaded only on the pages that need it; a 100% native PDF never loads docling (seconds, not minutes).
- **Fully local** — no API key, no data leaves the machine, with automatic NVIDIA GPU acceleration (CPU otherwise).
- **Built-in offline translation** in the pipeline (argos-translate), Markdown structure preserved.
- **Graphical interface** in addition to the CLI.

| | Approach | Local | No API key | Offline translation | GUI |
|---|---|:---:|:---:|:---:|:---:|
| "LLM vision" tools (e.g. MarkPDFdown, zyocum) | remote vision | ❌ | ❌ | ❌ | ❌ |
| "Lightweight local" tools (e.g. AlcheMark, browser-based) | simple OCR/heuristics | ✅ | ✅ | ❌ | ~ |
| **pdf2md** | **native / docling routing** | ✅ | ✅ | ✅ | ✅ |

> pdf2md is not a docling "wrapper": docling is just one of the two engines, called **only** on scanned pages or pages with a broken text layer. The value lies in the **orchestration** — routing, broken-text-layer detection, unified Markdown normalization, `.tables.json` sidecars, translation and GUI.

---

## Requirements

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)
- *(optional)* NVIDIA GPU + CUDA 12.8 drivers — otherwise everything runs on CPU (slower).

No Tesseract installation is required: OCR is provided by docling (RapidOCR). The docling models (~0.5 GB) download automatically on first launch and are cached (HuggingFace). Translation models (~100–200 MB per language pair) download on first use of translation.

---

## Installation

```powershell
git clone <repo>
cd pdf2md
uv sync
```

> **Without an NVIDIA GPU** — remove these two sections from `pyproject.toml` before `uv sync`:
>
> ```toml
> [[tool.uv.index]]
> name = "pytorch-cu128"
> url = "https://download.pytorch.org/whl/cu128"
> explicit = true
>
> [tool.uv.sources]
> torch = [{ index = "pytorch-cu128" }]
> torchvision = [{ index = "pytorch-cu128" }]
> ```
>
> `uv sync` will install the CPU build of PyTorch. Everything works, but processing scanned pages will be noticeably slower.

---

## Usage

### Graphical interface

Double-click `launch.bat` (or `uv run python -m pdf2md.gui`).

1. **Source PDF file** — *Browse…* (PDF or image: TIFF, PNG, JPG, BMP, GIF, WEBP…).
2. **Output folder** — the file's parent folder is suggested by default.
3. *(optional)* Tick **Translate output to:** and choose the target language.
4. Click **Convert** — the bar shows progress (extraction then writing).

### Command line

```powershell
# Interactive mode
uv run python -m pdf2md

# With arguments
uv run python -m pdf2md report.pdf
uv run python -m pdf2md report.pdf -o C:\output

# With translation (disabled by default)
uv run python -m pdf2md report.pdf -l fr               # auto-detect → French
uv run python -m pdf2md report.pdf -l en               # → English
uv run python -m pdf2md report.pdf -l en --from-lang de # force source language (German)
```

| Option | Role |
|---|---|
| `-o, --output` | Output folder (created if missing) |
| `-l, --lang CODE` | Translate output to this language (`fr`, `en`, `es`, `de`, `it`, `pt`, `nl`, `ru`, `zh`, `ar`, `ja`…). Default: no translation. |
| `--from-lang CODE` | Force the source language instead of detecting it |

---

## Output

For `report.pdf`, the folder `output/report/` contains:

```
report/
├── report_index.md          — index of all pages (with titles)
├── report_p01.md            — page 1
├── report_p02.md            — page 2
│   ...
├── report_p05.tables.json   — tables from page 5 (machine sidecar)
└── md_images/               — extracted figures
    ├── report_p05_img01.png
    └── report_p12_img01.png
```

Example page file:

```markdown
## Section title

Paragraph body text…

- List item
- Another item

| Parameter | Value |
| --- | --- |
| Voltage | 230 V |

![image](md_images/report_p05_img01.png)
```

---

## Behaviour by page type

Classification is done **page by page** (a single PDF can mix both):

| Page type | Extraction | Details |
|---|---|---|
| Reliable text layer | PyMuPDF + pdfplumber | Instant, no model. Headings detected by font size, lists and legends normalized, vector tables. |
| Broken text layer (font without ToUnicode) | docling | The "readable" text is actually scrambled → routed to OCR rather than emitting gibberish. |
| Scanned page (full-page image) | docling | Layout + OCR + TableFormer. Rotation respected. |
| Image input (TIFF/PNG/JPG…) | docling | Treated as a full scan. |

---

## Translation (optional)

Disabled by default. When a target language is requested (GUI checkbox or `-l`), each page's Markdown **and** its table cells are rewritten *after* extraction and *before* writing — so `_index.md` and the `.tables.json` files come out translated too.

- **argos-translate** engine: 100% offline, CPU, MIT-licensed, models downloaded on demand. The layer is deliberately abstracted (a single touchpoint) so the engine can be swapped without touching the pipeline.
- Source language is **auto-detected** per page (`langdetect`); a page already in the target language is left untouched. `--from-lang` forces the source.
- **Structure preserved**: headings, lists, tables, code blocks, `<!-- image -->` and image links stay intact — only readable text is translated.
- If a language pair is unavailable (offline + not cached, or unsupported), the affected page is left as-is with a warning — never a crash.

---

## Architecture

```
pdf2md/
├── processing/
│   ├── pipeline.py        — per-page router (native vs docling)
│   ├── native_extract.py  — fast path (PyMuPDF + pdfplumber), text_is_reliable gate
│   ├── docling_engine.py  — docling backend (layout + TableFormer + RapidOCR), GPU, 1 page at a time
│   └── translate.py       — optional translation (argos-translate, markdown-aware)
├── output/
│   └── docling_writer.py  — {stem}_pNN.md + .tables.json + _index.md + md_images/
├── converter.py           — orchestration, progress callbacks, translation hook
├── gui.py                 — tkinter interface (progress bar, language selector)
└── __main__.py            — CLI entry point
```

Flow: `__main__` → `Converter.convert` → `convert_document()` (`pipeline.py`) → *(optional translation)* → `write_docling()`.

> The legacy modules (`input/loader.py`, `processing/ocr.py`, `extractor.py`, `structure.py`, `output/serializer.py`, `writer.py`) are kept but **inactive**: they made up the Tesseract/numpy pipeline that docling replaced.

---

## Troubleshooting

### "Failed to hardlink files" warning at launch

When the project and the `uv` cache live on different drives (typically the project on a secondary drive and the cache on the system drive), `uv` cannot create hard links from one to the other and prints:

> warning: Failed to hardlink files; falling back to full copy.

This is **harmless**: `uv` simply copies the files, and both installation and launch work normally. `launch.bat` already suppresses this message; to silence it on the command line too, set the variable once and for all:

```powershell
setx UV_LINK_MODE copy
```

then reopen the terminal. Users whose project and cache are on the same drive will never see this warning and have nothing to do.

---

## Development

```powershell
uv run pytest
uv run ruff check .
uv run ruff format .
```
