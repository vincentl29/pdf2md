from datetime import datetime
from pathlib import Path


def generate_index(
    doc_title: str,
    source_path: Path,
    output_dir: Path,
    generated: list[dict],
) -> Path:
    sections = [f for f in generated if f["type"] == "section"]
    tables_json = [f for f in generated if f["type"] == "table_json"]
    images = [f for f in generated if f["type"] == "image"]

    total = len(generated) + 1  # +1 for the index itself

    lines = [
        f"# Index — {doc_title}",
        "",
        f"- **Source** : `{source_path.name}`",
        f"- **Généré** : {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"- **Fichiers** : {total}",
        "",
        "---",
        "",
        "## Sections",
        "",
    ]

    for entry in sections:
        indent = "  " * (entry["level"] - 1)
        name = entry["path"].name
        lines.append(f"{indent}- [{entry['title']}]({name})")

    if tables_json:
        lines += ["", "## Tableaux (JSON)", ""]
        for j in tables_json:
            lines.append(f"- [{j['title']}]({j['path'].name})")

    if images:
        lines += ["", "## Images", ""]
        for img in images:
            lines.append(f"- [{img['title']}]({img['path'].name})")

    lines += [
        "",
        "---",
        "",
        "## Envoyer à Claude",
        "",
        "1. Envoyer les sections dans l'ordre (préfixes numériques).",
        "2. Joindre les `.json` des tableaux si une analyse structurée est nécessaire.",
    ]

    index_path = output_dir / "00_index.md"
    index_path.write_text("\n".join(lines), encoding="utf-8")
    return index_path
