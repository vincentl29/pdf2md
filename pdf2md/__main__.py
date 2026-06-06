import argparse
import sys
from pathlib import Path
from .converter import Converter

# Accepted inputs: PDF plus any common raster image (Pillow handles the rest)
_SUPPORTED_SUFFIXES = {
    ".pdf",
    ".tif", ".tiff", ".png", ".jpg", ".jpeg", ".jfif", ".bmp", ".gif",
    ".webp", ".ppm", ".pgm", ".pbm", ".pnm", ".jp2", ".j2k", ".jpx",
    ".ico", ".tga", ".psd",
}


def _prompt_pdf() -> Path:
    while True:
        raw = input("Fichier source (PDF ou image) : ").strip().strip('"')
        path = Path(raw)
        if not path.exists():
            print(f"  Introuvable : {path}")
            continue
        if path.suffix.lower() not in _SUPPORTED_SUFFIXES:
            print("  Format non pris en charge (PDF, TIFF, PNG, JPG, BMP)")
            continue
        return path


def _prompt_output(default: Path) -> Path:
    raw = input(f"Dossier de sortie [{default}] : ").strip().strip('"')
    return Path(raw) if raw else default


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(
        prog="pdf2md",
        description="Convertit un PDF en fichiers Markdown structurés pour Claude.",
    )
    parser.add_argument("pdf", nargs="?", help="Fichier PDF à convertir")
    parser.add_argument(
        "-o", "--output",
        help="Dossier de sortie (créé automatiquement si inexistant)",
    )
    parser.add_argument(
        "-l", "--lang",
        metavar="CODE",
        help="Traduire la sortie vers cette langue (ex: fr, en, es, de). "
             "Par défaut : aucune traduction (langue d'origine conservée).",
    )
    parser.add_argument(
        "--from-lang",
        metavar="CODE",
        help="Forcer la langue source au lieu de la détecter automatiquement.",
    )
    args = parser.parse_args()

    print("\npdf2md — convertisseur PDF → Markdown\n")

    # Source
    if args.pdf:
        pdf_path = Path(args.pdf)
        if not pdf_path.exists():
            print(f"Erreur : fichier introuvable — {pdf_path}", file=sys.stderr)
            return 1
        if pdf_path.suffix.lower() not in _SUPPORTED_SUFFIXES:
            print(
                f"Erreur : format non pris en charge — {pdf_path}\n"
                "Formats acceptés : PDF, TIFF, PNG, JPG, BMP",
                file=sys.stderr,
            )
            return 1
    else:
        pdf_path = _prompt_pdf()

    # Destination (dossier — le .md y sera créé)
    default_out = pdf_path.parent
    if args.output:
        out_dir = Path(args.output)
    else:
        out_dir = _prompt_output(default_out)

    print(f"\nConversion de : {pdf_path.name}")
    out_files = Converter().convert(
        pdf_path, out_dir, target_lang=args.lang, source_lang=args.from_lang
    )
    print(f"\nFichiers crees ({len(out_files)}) :")
    for f in out_files:
        print(f"  {f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
