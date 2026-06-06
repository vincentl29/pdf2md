@echo off
setlocal
cd /d "%~dp0"

rem Si le projet et le cache uv sont sur des disques differents, le lien physique
rem est impossible et uv affiche un avertissement avant de recopier. On force donc
rem directement la copie pour eviter ce message au lancement.
set "UV_LINK_MODE=copy"

where uv >nul 2>&1
if errorlevel 1 (
    echo uv introuvable. Installez-le via : winget install astral-sh.uv
    pause
    exit /b 1
)

uv run python -m pdf2md.gui
if errorlevel 1 (
    echo.
    echo Erreur lors du lancement de l'interface.
    pause
)
