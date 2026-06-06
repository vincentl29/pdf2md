from collections.abc import Callable
from pathlib import Path

from .processing.pipeline import convert_document
from .output.docling_writer import write_docling


class Converter:
    """PDF/image → Markdown via per-page routing (native fast path + docling OCR)."""

    def convert(
        self,
        pdf_path: str | Path,
        output_dir: str | Path | None = None,
        progress_cb: Callable[[int, int], None] | None = None,
        extract_progress_cb: Callable[[int, int], None] | None = None,
        target_lang: str | None = None,
        source_lang: str | None = None,
    ) -> list[Path]:
        pdf_path = Path(pdf_path)
        base_dir = Path(output_dir) if output_dir else pdf_path.parent
        # Dedicated subfolder named after the source file
        out_dir = base_dir / pdf_path.stem
        out_dir.mkdir(parents=True, exist_ok=True)

        print(f"  Analyse : {pdf_path.name} — pages natives extraites localement, pages scannées via docling (modèles IA)…")
        result = convert_document(pdf_path, title=pdf_path.stem, progress_cb=extract_progress_cb)

        n_tables = sum(len(p.tables) for p in result.pages)
        print(f"  Pages : {result.page_count}  |  Tableaux détectés : {n_tables}")
        print(f"  dossier : {out_dir}")

        # Optional translation: rewrite each page's Markdown + table rows into
        # target_lang before writing (offline argos-translate; no-op if the
        # source is already target_lang or the deps/models are unavailable).
        if target_lang:
            from .processing.translate import translate_result

            print(f"  Traduction → {target_lang} (peut télécharger un modèle au 1er usage)…")
            n = translate_result(result, target_lang, source_lang)
            print(f"  Pages traduites : {n} / {result.page_count}")

        out_files = write_docling(result, out_dir, pdf_path.stem, progress_cb)
        n_json = sum(1 for f in out_files if f.suffix == ".json")
        n_pages = sum(1 for f in out_files if f.suffix == ".md") - 1  # minus index
        extra = f" + {n_json} JSON" if n_json else ""
        print(f"  Fichiers : {len(out_files)} ({n_pages} page(s) + index{extra})")
        return out_files
