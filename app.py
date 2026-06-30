#!/usr/bin/env python3
"""
Interfaccia grafica (web) per lo scraper di email.

Avvia un piccolo server locale e apre il browser. Da li' carichi il CSV con i
siti, premi "Avvia" e vedi l'avanzamento in tempo reale, con tabella delle email
trovate e pulsante per scaricare il risultato.

Avvio:
    python3 app.py
poi apri http://127.0.0.1:5000 (si apre da solo).
"""

import csv
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

from flask import (Flask, Response, jsonify, request,
                   send_file, send_from_directory)

BASE = Path(__file__).resolve().parent
WORK = BASE / "_dati"
WORK.mkdir(exist_ok=True)
INPUT_CSV = WORK / "siti.csv"
OUTPUT_CSV = WORK / "emails.csv"

app = Flask(__name__, static_folder=None)

# Stato condiviso del job in corso.
STATE = {
    "running": False,
    "finished": False,
    "total": 0,
    "done": 0,
    "with_email": 0,
    "emails": 0,
    "started_at": None,
    "message": "",
    "error": "",
    "render": False,
    "ocr": False,
}
PROC = {"p": None}
LOCK = threading.Lock()

PROGRESS_RE = re.compile(
    r"\.\.\.(\d+)/(\d+)\s+siti\s+\|\s+(\d+)\s+con email\s+\|\s+(\d+)\s+email")
TOTAL_RE = re.compile(r"da processare:\s+(\d+)")


def has_tesseract():
    return shutil.which("tesseract") is not None


def has_playwright():
    try:
        import playwright  # noqa: F401
        return True
    except Exception:
        return False


def count_input_sites(path):
    try:
        from scraper import read_sites
        return len(read_sites(str(path), None))
    except Exception:
        try:
            with open(path, encoding="utf-8-sig", errors="replace") as f:
                return max(0, sum(1 for _ in f) - 1)
        except Exception:
            return 0


def run_scraper(render, ocr, concurrency):
    """Esegue scraper.py come sottoprocesso e aggiorna lo STATE leggendo l'output."""
    cmd = [sys.executable, "-u", str(BASE / "scraper.py"),
           "--input", str(INPUT_CSV), "--output", str(OUTPUT_CSV),
           "--concurrency", str(concurrency)]
    if render:
        cmd.append("--render")
    if ocr:
        cmd.append("--ocr")

    env = dict(os.environ, PYTHONUNBUFFERED="1")
    try:
        p = subprocess.Popen(cmd, stderr=subprocess.PIPE, stdout=subprocess.DEVNULL,
                             text=True, bufsize=1, env=env)
    except Exception as e:
        with LOCK:
            STATE["running"] = False
            STATE["finished"] = True
            STATE["error"] = f"Impossibile avviare lo scraper: {e}"
        return
    PROC["p"] = p

    for line in p.stderr:
        line = line.strip()
        m = PROGRESS_RE.search(line)
        if m:
            with LOCK:
                STATE["done"] = int(m.group(1))
                STATE["total"] = int(m.group(2))
                STATE["with_email"] = int(m.group(3))
                STATE["emails"] = int(m.group(4))
            continue
        mt = TOTAL_RE.search(line)
        if mt:
            with LOCK:
                STATE["total"] = int(mt.group(1))
            continue
        if line:
            with LOCK:
                STATE["message"] = line

    p.wait()
    # conteggi finali precisi leggendo il file
    done, with_email, emails = read_result_stats()
    with LOCK:
        if done:
            STATE["done"] = max(STATE["done"], done)
            STATE["with_email"] = with_email
            STATE["emails"] = emails
        STATE["running"] = False
        STATE["finished"] = True
        if p.returncode not in (0, None) and not STATE["error"]:
            STATE["message"] = "Completato."


def read_result_stats():
    """Legge emails.csv e ritorna (siti_processati, siti_con_email, email_totali)."""
    if not OUTPUT_CSV.exists():
        return 0, 0, 0
    sites = set()
    with_email = set()
    emails = 0
    try:
        with open(OUTPUT_CSV, newline="", encoding="utf-8") as f:
            reader = csv.reader(f)
            next(reader, None)
            for row in reader:
                if not row:
                    continue
                sites.add(row[0])
                if len(row) > 1 and row[1].strip():
                    with_email.add(row[0])
                    emails += 1
    except Exception:
        pass
    return len(sites), len(with_email), emails


def read_recent(limit=200):
    """Ritorna le ultime righe con email per la tabella live."""
    if not OUTPUT_CSV.exists():
        return []
    rows = []
    try:
        with open(OUTPUT_CSV, newline="", encoding="utf-8") as f:
            reader = csv.reader(f)
            next(reader, None)
            for row in reader:
                if len(row) >= 2 and row[1].strip():
                    rows.append({"sito": row[0], "email": row[1],
                                 "stato": row[2] if len(row) > 2 else ""})
    except Exception:
        pass
    return rows[-limit:][::-1]


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return send_from_directory(str(BASE / "web"), "index.html")


@app.route("/api/capabilities")
def capabilities():
    return jsonify({"tesseract": has_tesseract(), "playwright": has_playwright()})


@app.route("/api/upload", methods=["POST"])
def upload():
    with LOCK:
        if STATE["running"]:
            return jsonify({"ok": False, "error": "Scraping in corso."}), 400
    f = request.files.get("file")
    if not f:
        return jsonify({"ok": False, "error": "Nessun file ricevuto."}), 400
    f.save(str(INPUT_CSV))
    n = count_input_sites(INPUT_CSV)
    if n == 0:
        return jsonify({"ok": False,
                        "error": "Non ho trovato siti validi nel CSV."}), 400
    return jsonify({"ok": True, "count": n, "filename": f.filename})


@app.route("/api/start", methods=["POST"])
def start():
    with LOCK:
        if STATE["running"]:
            return jsonify({"ok": False, "error": "Gia' in esecuzione."}), 400
    if not INPUT_CSV.exists():
        return jsonify({"ok": False, "error": "Carica prima un CSV."}), 400

    data = request.get_json(force=True, silent=True) or {}
    power = data.get("power", "massima")
    concurrency = int(data.get("concurrency", 30))
    resume = bool(data.get("resume", False))

    render = power == "massima" and has_playwright()
    ocr = power == "massima" and has_tesseract()

    if not resume and OUTPUT_CSV.exists():
        try:
            OUTPUT_CSV.unlink()
        except Exception:
            pass

    with LOCK:
        STATE.update({"running": True, "finished": False, "total": 0, "done": 0,
                      "with_email": 0, "emails": 0, "started_at": time.time(),
                      "message": "Avvio...", "error": "",
                      "render": render, "ocr": ocr})

    t = threading.Thread(target=run_scraper, args=(render, ocr, concurrency),
                         daemon=True)
    t.start()
    return jsonify({"ok": True, "render": render, "ocr": ocr})


@app.route("/api/status")
def status():
    with LOCK:
        s = dict(STATE)
    s["elapsed"] = int(time.time() - s["started_at"]) if s["started_at"] else 0
    s["recent"] = read_recent()
    return jsonify(s)


@app.route("/api/stop", methods=["POST"])
def stop():
    p = PROC.get("p")
    if p and p.poll() is None:
        try:
            p.terminate()
        except Exception:
            pass
    with LOCK:
        STATE["running"] = False
        STATE["finished"] = True
        STATE["message"] = "Interrotto. Puoi riprendere con 'Riprendi'."
    return jsonify({"ok": True})


@app.route("/api/download")
def download():
    if not OUTPUT_CSV.exists():
        return "Nessun risultato disponibile.", 404
    return send_file(str(OUTPUT_CSV), as_attachment=True,
                     download_name="emails.csv", mimetype="text/csv")


def open_browser(port):
    time.sleep(1.0)
    try:
        webbrowser.open(f"http://127.0.0.1:{port}")
    except Exception:
        pass


def main():
    port = int(os.environ.get("PORT", "5000"))
    if "--no-browser" not in sys.argv:
        threading.Thread(target=open_browser, args=(port,), daemon=True).start()
    print(f"\n  Scraper email - interfaccia web")
    print(f"  Apri nel browser:  http://127.0.0.1:{port}\n")
    app.run(host="127.0.0.1", port=port, threaded=True)


if __name__ == "__main__":
    main()
