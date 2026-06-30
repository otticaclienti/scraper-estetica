#!/bin/bash
# Doppio click per avviare lo Scraper Email su Mac.
cd "$(dirname "$0")"

echo "============================================"
echo "   SCRAPER EMAIL - avvio in corso..."
echo "============================================"
echo

# --- Controlla Python 3 ---
if ! command -v python3 >/dev/null 2>&1; then
  echo "[!] Python 3 non e' installato."
  echo "    Aprira' la pagina per scaricarlo. Installa e poi rilancia questo file."
  open "https://www.python.org/downloads/"
  read -n 1 -s -r -p "Premi un tasto per chiudere..."
  exit 1
fi

echo "[1/3] Installo i componenti necessari (solo la prima volta)..."
python3 -m pip install --quiet --upgrade pip
python3 -m pip install --quiet -r requirements.txt

echo "[2/3] Preparo il browser per il render JavaScript..."
python3 -m playwright install chromium

# OCR (facoltativo): se c'e' Homebrew e manca tesseract, prova a installarlo.
if ! command -v tesseract >/dev/null 2>&1; then
  if command -v brew >/dev/null 2>&1; then
    echo "      Installo Tesseract per l'OCR..."
    brew install tesseract tesseract-lang >/dev/null 2>&1 || true
  fi
fi

echo "[3/3] Avvio l'applicazione e apro il browser..."
echo
echo "  Se il browser non si apre da solo, vai su:  http://127.0.0.1:5000"
echo "  Per chiudere il programma: chiudi questa finestra del Terminale."
echo
python3 app.py
