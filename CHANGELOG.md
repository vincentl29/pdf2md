# Changelog

Tous les changements notables de ce projet sont consignés dans ce fichier.

Le format s'inspire de [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/)
et le projet vise le [versionnage sémantique](https://semver.org/lang/fr/).

## [Unreleased]

## [1.0.0] — 2026-06-27

Première version officielle publique — pipeline stable, interface graphique,
traduction hors-ligne, accélération GPU.

### Fixed
- **`launch.bat`** : reconstruction automatique du `.venv` incomplet ou corrompu.
  `uv sync` est exécuté silencieusement à chaque lancement ; en cas d'échec,
  `.venv` est supprimé et recréé avant d'ouvrir l'interface graphique.

## [0.1.0] — 2026-06-05

Première version publiée. Conversion PDF → Markdown avec pipeline hybride
(texte natif + OCR deep-learning), support des images en entrée, traduction
hors-ligne optionnelle et interface graphique.

### Added
- **Routage page par page** (`processing/pipeline.py`) : les pages au calque
  texte fiable sont extraites localement (PyMuPDF + pdfplumber), instantanément
  et sans chargement de modèle ; seules les pages scannées passent par docling.
- **Backend docling** (`processing/docling_engine.py`) : analyse de mise en page
  + TableFormer + OCR RapidOCR, avec **accélération GPU CUDA** automatique
  (repli CPU si pas de GPU NVIDIA).
- **Extraction native** (`processing/native_extract.py`) : détection de texte
  cassé (polices sous-ensembles sans CMap), interleaving blocs texte / tableaux
  pdfplumber par position verticale, détection des titres par taille de police,
  listes, légendes numérotées, images inline.
- **Extraction des images** vers un sous-dossier `md_images/`, avec remplacement
  des marqueurs `<!-- image -->` par des liens `![image](md_images/…)`.
- **Traduction automatique optionnelle hors-ligne** (`processing/translate.py`) :
  moteur argos-translate, détection de langue source par page (langdetect),
  traduction *markdown-aware* préservant la structure (blocs de code, images,
  séparateurs de tableaux intacts). Pilotée par `-l/--lang` et `--from-lang`
  (CLI) ou la case « Traduire la sortie vers : » (GUI).
- **Sidecars `*_pNN.tables.json`** pour les pages contenant des tableaux
  (consommables par machine).
- **Entrées image** (TIFF/PNG/JPG/BMP/GIF/WEBP…) en plus des PDF.
- Sortie paginée : un `.md` par page + `_index.md` dans un sous-dossier dédié
  `{output_dir}/{stem}/`.
- Interface graphique **redimensionnable** avec barre de progression animée
  (pulse « busy » pendant le chargement des modèles) et bouton « Ouvrir le
  dossier de sortie ».
- CLI : `uv run python -m pdf2md fichier.pdf [-o DOSSIER] [-l LANG] [--from-lang LANG]`.

### Changed
- Remplacement du pipeline Tesseract/numpy fait main par **docling**, qui
  restitue correctement l'ordre de lecture, les vrais tableaux et la table des
  matières (l'ancien découpait la prose multi-colonnes en faux tableaux).

### Fixed
- **OOM `std::bad_alloc`** au préchargement CPU : conversion **une page à la
  fois** (`_convert_one_page`), plafonnement du rendu OCR à 144 dpi
  (`_OCR_RENDER_SCALE = 2`) et libération mémoire après chaque page
  (`_free_memory`). Les pages vides sont réessayées une fois après purge.
- **`pypdfium2` épinglé à `4.30.0`** — les wheels 5.x n'embarquent pas le binaire
  natif `pdfium` sur cette configuration Windows/uv.

[0.1.0]: https://github.com/vincentl29/pdf2md/releases/tag/v0.1.0
