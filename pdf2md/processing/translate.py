"""Optional automatic translation of the extracted Markdown.

The conversion pipeline produces Markdown in the source document's language.
When a target language is requested (default French, selectable in the UI/CLI),
this module rewrites each page's Markdown — and the structured table rows that
feed the JSON sidecars — into that language *after* extraction and *before*
writing, page by page.

Design — engine-agnostic on purpose (the repo is meant for open source):
the pipeline only ever talks to :class:`Translator`. The concrete backend here
is **argos-translate** — fully offline, CPU-only, MIT-licensed, models
auto-downloaded per language pair (~100-200 MB each). That keeps the feature
usable by contributors with no GPU and avoids fighting docling for the 6 GB of
VRAM (NLLB/M2M100 would). Swapping in another backend (NLLB, DeepL, …) is a
single function — ``_engine_translate`` — with no change to the pipeline or UI.

Source language is auto-detected per page with ``langdetect``; a page already
in the target language is left untouched. Both optional dependencies degrade
gracefully: if either is missing, translation no-ops with a clear message
instead of crashing the conversion.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable

# argos-translate pulls in stanza for some language pairs; on first pipeline
# load it logs informational notices ("Language en package default expects
# mwt, which has been added") at WARNING severity via logging.getLogger("stanza").
# They're harmless pipeline-setup details, but "WARNING" reads as alarming to
# non-technical users watching the conversion log — raise the bar to errors only.
logging.getLogger("stanza").setLevel(logging.ERROR)

# langdetect returns BCP-47-ish codes for some languages; argos wants the bare
# ISO-639-1 code.
_LANGDETECT_FIX = {"zh-cn": "zh", "zh-tw": "zh"}

# A line that is only a Markdown table separator: | --- | :---: | … |
_TABLE_SEP_RE = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)+\|?\s*$")
# Leading Markdown markers we keep verbatim, translating only what follows.
_LEADING_RE = re.compile(r"^(\s*(?:#{1,6}\s+|[-*+]\s+|\d+\.\s+|>\s+)?)(.*)$")


def translation_available() -> bool:
    """True when both optional deps (argostranslate + langdetect) import."""
    try:
        import argostranslate.translate  # noqa: F401
        import langdetect  # noqa: F401

        return True
    except Exception:
        return False


def detect_language(text: str) -> str | None:
    """Best-effort ISO-639-1 code for *text*, or None if undetectable."""
    t = text.strip()
    if len(t) < 20:
        return None
    try:
        from langdetect import DetectorFactory, detect

        DetectorFactory.seed = 0  # deterministic output
        code = detect(t)
        return _LANGDETECT_FIX.get(code, code)
    except Exception:
        return None


# ── argos-translate backend ─────────────────────────────────────────────────

_index_updated = False


def _ensure_pair(from_code: str, to_code: str) -> bool:
    """Make a usable ``from_code → to_code`` path available, installing the
    argos model package(s) on first use (network). Falls back to pivoting
    through English when no direct package exists. Returns False if no path
    could be assembled (offline + not cached, or unsupported pair)."""
    global _index_updated
    try:
        from argostranslate import package
    except Exception:
        return False

    installed = {(p.from_code, p.to_code) for p in package.get_installed_packages()}

    def have_path() -> bool:
        if (from_code, to_code) in installed:
            return True
        return (from_code, "en") in installed and ("en", to_code) in installed

    if have_path():
        return True

    if not _index_updated:
        try:
            package.update_package_index()
            _index_updated = True
        except Exception:
            return False  # offline and nothing cached for this pair

    available = package.get_available_packages()

    def install(f: str, t: str) -> bool:
        if (f, t) in installed:
            return True
        pkg = next(
            (p for p in available if p.from_code == f and p.to_code == t), None
        )
        if pkg is None:
            return False
        try:
            package.install_from_path(pkg.download())
        except Exception:
            return False
        installed.add((f, t))
        return True

    if install(from_code, to_code):
        return True
    # Pivot through English (argos composes installed translations transitively).
    return install(from_code, "en") and install("en", to_code)


def _engine_translate(text: str, from_code: str, to_code: str) -> str:
    """Translate a single string. The one place a different backend would plug
    in. Returns the input unchanged if the language path is unavailable."""
    try:
        from argostranslate import translate as argt

        langs = argt.get_installed_languages()
        src = next((lang for lang in langs if lang.code == from_code), None)
        tgt = next((lang for lang in langs if lang.code == to_code), None)
        if src is None or tgt is None:
            return text
        translation = src.get_translation(tgt)
        if translation is None:
            return text
        return translation.translate(text)
    except Exception:
        return text


# ── Markdown-aware translator ────────────────────────────────────────────────


class Translator:
    """Translate Markdown into ``target`` while preserving structure.

    Structure left verbatim: code fences, image links/placeholders, table
    separator rows, and every Markdown marker (``#``, ``-``, ``1.``, ``>``,
    table pipes) — only the human-readable text inside is sent to the engine.
    Identical segments are translated once and cached (headers/cells repeat).
    """

    def __init__(self, target: str = "fr"):
        self.target = target
        self._cache: dict[tuple[str, str], str] = {}
        self._ready: set[str] = set()

    def ensure(self, src: str) -> bool:
        if src in self._ready:
            return True
        if _ensure_pair(src, self.target):
            self._ready.add(src)
            return True
        return False

    # -- segment-level --------------------------------------------------------

    def _segment(self, text: str, src: str) -> str:
        if not text.strip():
            return text
        key = (src, text)
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        out = _engine_translate(text, src, self.target)
        self._cache[key] = out
        return out

    def _table_row(self, line: str, src: str) -> str:
        parts = line.split("|")
        for i in range(1, len(parts) - 1):  # skip the outer empty edges
            cell = parts[i]
            stripped = cell.strip()
            if not stripped or set(stripped) <= set("-: "):
                continue
            lead = cell[: len(cell) - len(cell.lstrip())]
            trail = cell[len(cell.rstrip()) :]
            parts[i] = f"{lead}{self._segment(stripped, src)}{trail}"
        return "|".join(parts)

    def _line(self, line: str, src: str) -> str:
        stripped = line.strip()
        if (
            not stripped
            or stripped.startswith("<!--")  # HTML comment / <!-- image -->
            or stripped.startswith("![")  # image link line
            or _TABLE_SEP_RE.match(stripped)
        ):
            return line
        if stripped.startswith("|") and stripped.endswith("|"):
            return self._table_row(line, src)
        m = _LEADING_RE.match(line)
        prefix, rest = m.group(1), m.group(2)
        if not rest.strip():
            return line
        return prefix + self._segment(rest, src)

    # -- document-level -------------------------------------------------------

    def translate_markdown(self, md: str, src: str) -> str:
        out: list[str] = []
        in_code = False
        for line in md.split("\n"):
            if line.lstrip().startswith("```"):
                in_code = not in_code
                out.append(line)
            elif in_code:
                out.append(line)
            else:
                out.append(self._line(line, src))
        return "\n".join(out)

    def translate_tables(
        self, tables: list[list[list[str]]], src: str
    ) -> list[list[list[str]]]:
        return [
            [[self._segment(c, src) if c.strip() else c for c in row] for row in t]
            for t in tables
        ]


# ── plain-text helper for language detection ─────────────────────────────────


def _plain_text(md: str) -> str:
    """Strip Markdown decoration so language detection sees clean prose."""
    out: list[str] = []
    for line in md.split("\n"):
        s = line.strip()
        if not s or s.startswith(("<!--", "|", "![", "```")):
            continue
        s = re.sub(r"^#{1,6}\s+", "", s)
        s = re.sub(r"^[-*+]\s+", "", s)
        s = re.sub(r"^\d+\.\s+", "", s)
        out.append(s)
    return " ".join(out)


# ── orchestration over a whole DoclingResult ─────────────────────────────────


def translate_result(
    result,
    target_lang: str,
    source_lang: str | None = None,
    progress_cb: Callable[[int, int], None] | None = None,
) -> int:
    """Translate every page of *result* in place into ``target_lang``.

    ``source_lang`` forces the source (skip per-page detection) when given.
    Pages already in the target language, or whose language path can't be
    built (offline + uncached), are left untouched. Returns the number of
    pages actually translated.
    """
    if not translation_available():
        print(
            "  ⚠ Traduction ignorée : dépendances absentes "
            "(`uv add argostranslate langdetect`)."
        )
        return 0

    tr = Translator(target_lang)
    total = len(result.pages)
    translated = 0
    warned_pairs: set[str] = set()

    for i, page in enumerate(result.pages, 1):
        md = page.markdown or ""
        src = source_lang or detect_language(_plain_text(md))
        if src and src != target_lang and tr.ensure(src):
            page.markdown = tr.translate_markdown(md, src)
            if page.tables:
                page.tables = tr.translate_tables(page.tables, src)
            translated += 1
        elif src and src != target_lang and src not in warned_pairs:
            warned_pairs.add(src)
            print(
                f"  ⚠ Paire {src}→{target_lang} indisponible "
                "(hors-ligne ou non prise en charge) — page laissée en l'état."
            )
        if progress_cb:
            progress_cb(i, total)

    return translated
