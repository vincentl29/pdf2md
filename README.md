# pdf2md

**Français** · [English](README.en.md)

*Convertisseur PDF → Markdown **100 % local et hors-ligne** : routage page par page, OCR deep-learning (docling), tableaux, images, et traduction intégrée — sans clé API, sans envoi de données dans le cloud.*

![Python](https://img.shields.io/badge/python-3.12%2B-blue)
![uv](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/uv/main/assets/badge/v0.json)
[![License: AGPL v3](https://img.shields.io/badge/License-AGPL_v3-blue.svg)](LICENSE.md)

Convertit un PDF (ou un scan image) en fichiers Markdown structurés, prêts à être envoyés à un LLM.

- **Routage page par page** : les pages avec un vrai calque texte sont extraites localement et instantanément (PyMuPDF + pdfplumber, sans OCR ni chargement de modèle) ; les pages scannées passent par **docling** (IBM, deep-learning : analyse de mise en page + TableFormer + OCR RapidOCR).
- Un fichier `.md` par page + un `_index.md` récapitulatif, dans un sous-dossier dédié `{sortie}/{nom_du_fichier}/`.
- **Tableaux** rendus en Markdown *et* exportés en sidecar `{nom}_pNN.tables.json` (pour consommation machine).
- **Images** extraites dans `md_images/` avec un lien `![image](…)` à la place du marqueur.
- **Traduction automatique** (hors-ligne) vers le français par défaut, ou toute autre langue.
- **Accélération GPU** (CUDA) automatique si une carte NVIDIA est présente, sinon CPU.
- Barre de progression temps réel (extraction puis écriture) dans l'interface graphique.

---

## Pourquoi pdf2md ?

La plupart des convertisseurs PDF → Markdown tombent dans l'une de deux familles : ceux qui s'appuient sur un **LLM de vision distant** (qualité élevée, mais clé API obligatoire, coût par page et données envoyées dans le cloud), et ceux qui restent **locaux mais à OCR basique**. pdf2md vise l'angle laissé vide entre les deux : **rester entièrement local tout en gardant un OCR de qualité**.

Concrètement, il est le seul à combiner ces quatre traits :

- **Routage page par page** — un modèle lourd n'est chargé que sur les pages qui en ont besoin ; un PDF 100 % natif ne charge jamais docling (quelques secondes, pas quelques minutes).
- **Tout en local** — aucune clé API, aucune donnée ne quitte la machine, avec accélération GPU NVIDIA automatique (sinon CPU).
- **Traduction hors-ligne intégrée** au pipeline (argos-translate), structure Markdown préservée.
- **Interface graphique** en plus de la CLI.

| | Approche | Local | Sans clé API | Trad. offline | GUI |
|---|---|:---:|:---:|:---:|:---:|
| Outils « LLM vision » (ex. MarkPDFdown, zyocum) | vision distante | ❌ | ❌ | ❌ | ❌ |
| Outils « locaux légers » (ex. AlcheMark, navigateur) | OCR/heuristique simple | ✅ | ✅ | ❌ | ~ |
| **pdf2md** | **routage natif / docling** | ✅ | ✅ | ✅ | ✅ |

> pdf2md n'est pas un « wrapper » de docling : docling n'est qu'un des deux moteurs, appelé **uniquement** sur les pages scannées ou au calque texte cassé. La valeur ajoutée est l'**orchestration** — routage, détection du calque cassé, normalisation Markdown unifiée, sidecars `.tables.json`, traduction et GUI.

---

## Prérequis

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)
- *(optionnel)* GPU NVIDIA + pilotes CUDA 12.8 — sinon tout tourne sur CPU (plus lent).

Aucune installation de Tesseract n'est requise : l'OCR est fourni par docling (RapidOCR). Les modèles docling (~0,5 Go) se téléchargent automatiquement au premier lancement et sont mis en cache (HuggingFace). Les modèles de traduction (~100-200 Mo par paire de langues) se téléchargent à la première utilisation de la traduction.

---

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
> `uv sync` installera la build CPU de PyTorch. Tout fonctionne, mais le traitement des pages scannées sera sensiblement plus lent.

---

## Utilisation

### Interface graphique

Double-cliquer sur `launch.bat` (ou `uv run pdf2md-gui`).

1. **Fichier PDF source** — *Parcourir…* (PDF ou image : TIFF, PNG, JPG, BMP, GIF, WEBP…).
2. **Dossier de sortie** — le dossier parent du fichier est proposé par défaut.
3. *(optionnel)* Cocher **Traduire la sortie vers :** et choisir la langue cible.
4. Cliquer sur **Convertir** — la barre indique l'avancement (extraction puis écriture). À la fin, le dossier de sortie s'ouvre automatiquement dans l'Explorateur.

### Ligne de commande

```powershell
# Mode interactif
uv run pdf2md

# Avec arguments
uv run pdf2md rapport.pdf
uv run pdf2md rapport.pdf -o C:\sortie

# Avec traduction (désactivée par défaut)
uv run pdf2md rapport.pdf -l fr               # détection auto → français
uv run pdf2md rapport.pdf -l en               # → anglais
uv run pdf2md rapport.pdf -l fr --from-lang de # forcer la langue source (allemand)
```

| Option | Rôle |
|---|---|
| `-o, --output` | Dossier de sortie (créé si absent) |
| `-l, --lang CODE` | Traduire la sortie vers cette langue (`fr`, `en`, `es`, `de`, `it`, `pt`, `nl`, `ru`, `zh`, `ar`, `ja`…). Par défaut : aucune traduction. |
| `--from-lang CODE` | Forcer la langue source au lieu de la détecter |

---

## Sortie

Pour `rapport.pdf`, le dossier `sortie/rapport/` contient :

```
rapport/
├── rapport_index.md          — index de toutes les pages (avec titres)
├── rapport_p01.md            — page 1
├── rapport_p02.md            — page 2
│   ...
├── rapport_p05.tables.json   — tableaux de la page 5 (sidecar machine)
└── md_images/                — figures extraites
    ├── rapport_p05_img01.png
    └── rapport_p12_img01.png
```

Exemple de fichier page :

```markdown
## Titre de section

Contenu textuel du paragraphe…

- Élément de liste
- Autre élément

| Paramètre | Valeur |
| --- | --- |
| Tension | 230 V |

![image](md_images/rapport_p05_img01.png)
```

---

## Comportement selon le type de page

La classification est faite **page par page** (un même PDF peut mélanger les deux) :

| Type de page | Extraction | Détails |
|---|---|---|
| Calque texte fiable | PyMuPDF + pdfplumber | Instantané, sans modèle. Titres détectés par taille de police, listes et légendes normalisées, tableaux vectoriels. |
| Calque texte cassé (police sans ToUnicode) | docling | Le texte « lisible » est en réalité brouillé → routé vers l'OCR plutôt que d'émettre du charabia. |
| Page scannée (image pleine page) | docling | Layout + OCR + TableFormer. Rotation respectée. |
| Image en entrée (TIFF/PNG/JPG…) | docling | Traitée comme un scan intégral. |

---

## Traduction

Désactivée par défaut. Quand une langue cible est demandée (case GUI ou `-l`), le Markdown de chaque page **et** les cellules des tableaux sont réécrits *après* extraction et *avant* écriture — l'`_index.md` et les `.tables.json` ressortent donc traduits eux aussi.

- Moteur **argos-translate** : 100 % hors-ligne, CPU, licence MIT, modèles téléchargés à la demande. La couche est volontairement abstraite (un seul point de branchement) pour pouvoir basculer vers un autre moteur sans toucher au pipeline.
- Langue source **détectée automatiquement** par page (`langdetect`) ; une page déjà dans la langue cible est laissée intacte. `--from-lang` force la source.
- **Structure préservée** : titres, listes, tableaux, blocs de code, `<!-- image -->` et liens d'images restent intacts — seul le texte lisible est traduit.
- Si une paire de langues est indisponible (hors-ligne + non mise en cache, ou non prise en charge), la page concernée est laissée telle quelle avec un avertissement — jamais de plantage.

---

## Architecture

```
pdf2md/
├── processing/
│   ├── pipeline.py        — routeur page-par-page (natif vs docling)
│   ├── native_extract.py  — chemin rapide (PyMuPDF + pdfplumber), gate text_is_reliable
│   ├── docling_engine.py  — backend docling (layout + TableFormer + RapidOCR), GPU, 1 page/fois
│   └── translate.py       — traduction (argos-translate, markdown-aware)
├── output/
│   └── docling_writer.py  — {stem}_pNN.md + .tables.json + _index.md + md_images/
├── converter.py           — orchestration, callbacks de progression, hook traduction
├── gui.py                 — interface tkinter (barre de progression, sélecteur de langue)
└── __main__.py            — point d'entrée CLI
```

Flux : `__main__` → `Converter.convert` → `convert_document()` (`pipeline.py`) → *(traduction)* → `write_docling()`.

> Les anciens modules (`input/loader.py`, `processing/ocr.py`, `extractor.py`, `structure.py`, `output/serializer.py`, `writer.py`) sont conservés mais **inactifs** : ils constituaient le pipeline Tesseract/numpy remplacé par docling.

---

## Dépannage

### Avertissement « Failed to hardlink files » au lancement

Quand le projet et le cache de `uv` se trouvent sur des disques différents (typiquement le projet sur un disque secondaire et le cache sur le disque système), `uv` ne peut pas créer de liens physiques de l'un vers l'autre et affiche :

> warning: Failed to hardlink files; falling back to full copy.

C'est **sans conséquence** : `uv` recopie simplement les fichiers, l'installation comme le lancement fonctionnent normalement. `launch.bat` neutralise déjà ce message ; pour le supprimer aussi en ligne de commande, définissez la variable une fois pour toutes :

```powershell
setx UV_LINK_MODE copy
```

puis rouvrez le terminal. Les utilisateurs dont le projet et le cache sont sur le même disque ne verront jamais cet avertissement et n'ont rien à faire.

---

## Développement

```powershell
uv run pytest
uv run ruff check .
uv run ruff format .
```
