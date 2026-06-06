# Politique de sécurité

## Avertissement

pdf2md est un projet **open source en cours de développement**, fourni tel quel,
sans garantie d'aucune sorte. Le mainteneur ne peut être tenu responsable de
tout dysfonctionnement, perte de données, faille de sécurité ou tout autre
problème découlant de l'utilisation de ce logiciel, que ce soit directement ou
indirectement. L'utilisation se fait à vos propres risques.

## Versions prises en charge

Seule la dernière version de la branche `main` reçoit des correctifs de sécurité.
Les versions antérieures ne sont pas maintenues.

| Version             | Prise en charge |
|---------------------|---|
| `master` (dernière) | ✅ |
| Antérieures         | ❌ |

## Signaler une vulnérabilité

**Merci de ne pas ouvrir d'issue publique pour une faille de sécurité.**

Utilisez l'onglet **Security → Report a vulnerability** de GitHub pour un
signalement confidentiel. Merci d'inclure :

- une description du problème et de son impact potentiel ;
- les étapes de reproduction (fichier d'exemple, commande, configuration) ;
- la version / le commit concerné.

Ce projet est maintenu bénévolement, dans le temps disponible. Les signalements
seront traités au mieux, sans engagement de délai.

## Périmètre

pdf2md traite des fichiers fournis par l'utilisateur (PDF et images) et
télécharge des modèles (docling, argos-translate) depuis des sources tierces.
Les vecteurs d'attaque les plus pertinents sont les suivants.

**Fichiers d'entrée malveillants** : un PDF ou une image spécialement conçu
pourrait exploiter une vulnérabilité dans PyMuPDF, pdfplumber, Pillow ou docling.
Ne traitez pas de fichiers provenant de sources non fiables sans précautions.

**Intégrité des modèles téléchargés** : les modèles docling et argos-translate
sont téléchargés depuis HuggingFace au premier lancement. Aucune vérification
cryptographique de leur intégrité n'est effectuée par pdf2md ; vous dépendez de
la sécurité de la chaîne d'approvisionnement amont.

**Exécution de code via les dépendances** : le projet s'appuie sur PyTorch,
docling et d'autres bibliothèques lourdes. Une dépendance compromise ou mal
épinglée pourrait introduire du code malveillant lors d'un `uv sync`.

**Chemins de sortie** : les noms de fichiers d'entrée influencent les noms des
fichiers générés. Un nom de fichier contenant des séquences de traversée de
répertoire (ex. `../`) pourrait écrire hors du répertoire de sortie prévu si
l'entrée n'est pas correctement assainie.

## Bonnes pratiques recommandées

- Exécutez pdf2md dans un environnement isolé (conteneur, VM) si vous traitez
  des fichiers de sources inconnues.
- Épinglez les versions des dépendances (`uv lock`) et vérifiez régulièrement
  les mises à jour de sécurité (`uv lock --upgrade`).
- Ne lancez pas le programme avec des privilèges élevés.
