# Contribuer à pdf2md

Ce projet est développé et maintenu par une seule personne. Les contributions
externes sont les bienvenues dans la mesure du possible, mais les réponses et
les décisions de merge restent à la discrétion du mainteneur.

La langue de travail du projet est le **français** (issues, PR, commits).

---

## Prérequis

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)
- *(optionnel)* GPU NVIDIA + CUDA 12.8 — sinon tout tourne sur CPU.

## Installation

```powershell
git clone <repo>
cd pdf2md
uv sync
```

> **Sans GPU NVIDIA** — supprimer ces deux sections de `pyproject.toml` avant `uv sync` :
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
> `uv sync` installera la build CPU de PyTorch. Tout fonctionne, mais le traitement des pages scannées est sensiblement plus lent.

## Lancer le projet

```powershell
uv run pdf2md                          # CLI interactif
uv run pdf2md fichier.pdf -o C:\sortie
uv run pdf2md-gui                      # interface graphique
```

---

## Tests et qualité

Avant toutes PR, ces trois commandes doivent passer :

```powershell
uv run pytest          # tests
uvx ruff check .       # lint (ou `uv run ruff check .` si ruff est synchronisé)
uvx ruff format .      # formatage
```

Configuration `ruff` (voir `pyproject.toml`) : `line-length = 100`, règles
`E, F, W, I` (dont le tri des imports), cible `py312`, guillemets doubles.

## Style de code

- Respecter le formatage `ruff format` (guillemets doubles, indentation espaces).
- Imports triés (`ruff` règle `I`).
- Les docstrings expliquent **pourquoi** une chose est faite, pas seulement quoi —
  le code de ce projet documente les pièges (calques texte cassés, OOM, choix du
  moteur OCR…). Suivre cette habitude.
- Privilégier les fonctions pures et testables ; isoler les effets de bord
  (I/O fichier, modèles) dans `converter.py` / `output/` / `processing/`.

## Conventions de commit

Le projet suit les [Conventional Commits](https://www.conventionalcommits.org/),
**rédigés en français** :

```
feat: extraction des images vers md_images/
fix: OOM std::bad_alloc — conversion une page à la fois
docs: mise à jour README.md
refactor: …      test: …      chore: …
```

## Pull requests

1. Créer une branche dédiée depuis `main`.
2. `pytest` vert + `ruff check`/`ruff format` propres.
3. Si l'architecture change, **mettre à jour `README.md`** en conséquence.
4. Ajouter une entrée sous `## [Unreleased]` dans `CHANGELOG.md`.
5. Décrire le *pourquoi* du changement dans la PR.

---

## Repères d'architecture

Le pipeline actif est routé **page par page** : chemin natif rapide
(PyMuPDF + pdfplumber) vs **docling** (deep learning) pour les pages scannées.
La traduction est une couche optionnelle hors-ligne (argos-translate).

- Vue utilisateur et structure de sortie : **`README.md`**.

Modules clés : `processing/pipeline.py` (routeur), `processing/native_extract.py`
(chemin rapide), `processing/docling_engine.py` (backend docling),
`processing/translate.py` (traduction), `output/docling_writer.py` (écriture).

> Les modules `input/loader.py`, `processing/ocr.py`, `extractor.py`,
> `structure.py`, `output/serializer.py`, `writer.py` sont **legacy et inactifs**
> (ancien pipeline Tesseract). Ne pas s'appuyer dessus pour de nouveaux travaux.

## Ajouter une dépendance

```powershell
uv add <package>          # runtime
uv add --group dev <pkg>  # outils de développement
```
