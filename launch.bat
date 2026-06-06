@echo off
setlocal
cd /d "%~dp0"

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
