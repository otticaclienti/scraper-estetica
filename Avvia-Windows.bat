@echo off
chcp 65001 >nul
title Scraper Email
cd /d "%~dp0"

echo ============================================
echo    SCRAPER EMAIL - avvio in corso...
echo ============================================
echo.

REM --- Controlla Python ---
python --version >nul 2>&1
if errorlevel 1 (
  echo [!] Python non e' installato.
  echo     Scaricalo da https://www.python.org/downloads/
  echo     IMPORTANTE: durante l'installazione spunta "Add Python to PATH".
  echo.
  pause
  start https://www.python.org/downloads/
  exit /b
)

echo [1/3] Installo i componenti necessari (solo la prima volta)...
python -m pip install --quiet --upgrade pip
python -m pip install --quiet -r requirements.txt

echo [2/3] Preparo il browser per il render JavaScript...
python -m playwright install chromium

echo [3/3] Avvio l'applicazione e apro il browser...
echo.
echo  Se il browser non si apre da solo, vai su:  http://127.0.0.1:5000
echo  Per chiudere il programma: chiudi questa finestra nera.
echo.
python app.py

pause
