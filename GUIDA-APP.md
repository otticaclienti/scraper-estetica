# Guida: l'app con interfaccia grafica (apri in Chrome)

Questa è l'app visiva: la apri nel **browser** (Chrome), **trascini** la lista
dei siti, premi **Avvia** e vedi l'avanzamento in tempo reale con le email che
compaiono in una tabella. Gira sul **tuo computer** (nessun costo, nessun sito da
pubblicare).

---

## Prima volta: scaricare i file

1. Nella pagina del repository su GitHub, premi il pulsante verde **Code** →
   **Download ZIP**.
2. Estrai lo ZIP in una cartella sul tuo computer (es. sul Desktop).

> Serve **Python** installato (gratis). Se non ce l'hai, l'avviatore ti manda
> da solo alla pagina giusta: scaricalo da
> [python.org/downloads](https://www.python.org/downloads/) e — su Windows —
> ricordati di spuntare **"Add Python to PATH"** durante l'installazione.

---

## Avviare l'app

- **Windows:** doppio click su **`Avvia-Windows.bat`**
- **Mac:** doppio click su **`Avvia-Mac.command`**
  - se Mac dice che non può aprirlo: tasto destro → **Apri** → **Apri**.

La prima volta installa da sola i componenti necessari (ci mette qualche minuto),
poi **apre il browser** sulla pagina dell'app. Le volte successive parte subito.

Si apre su **http://127.0.0.1:5000** (se non si apre da solo, copia questo
indirizzo in Chrome).

---

## Usare l'app (3 passi nella pagina)

1. **Carica la lista** → trascina il file CSV nel riquadro (o clicca per
   sceglierlo). Ti dice quanti siti ha trovato.
2. **Scegli la potenza** e premi **Avvia scraping**:
   - **🚀 Massima** — usa tutte le tecniche (Cloudflare, JavaScript, render con
     browser, OCR sulle immagini). Trova più email, è più lenta.
   - **⚡ Base** — solo download veloce. Più rapida, trova meno.
3. **Guarda l'avanzamento** → barra di completamento, contatori (siti analizzati,
   siti con email, email totali), tempo stimato rimasto e la **tabella delle
   email** che si riempie in tempo reale.

Alla fine premi **⬇ Scarica emails.csv** per salvare il file con tutte le email.

---

## Funzioni utili

- **Ferma**: interrompe in qualsiasi momento.
- **Riprendi (dai mancanti)**: se hai fermato o chiuso, riparte solo dai siti non
  ancora fatti (non rifà da capo).
- **Chiudere il programma**: chiudi la finestra nera (Windows) o del Terminale
  (Mac).

---

## Note

- Il **render JavaScript** funziona ovunque (lo installa l'avviatore).
- L'**OCR** (leggere le email dalle immagini) richiede il programma *Tesseract*:
  su Mac con Homebrew viene installato in automatico; su Windows è facoltativo.
  Se manca, l'app continua a funzionare lo stesso, semplicemente senza OCR
  (te lo segnala nella schermata).
- Tutto resta sul tuo computer: la lista e le email non vengono inviate a nessuno.

---

### Preferisci non installare niente?

C'è anche il metodo **100% online con GitHub Actions** (gira sui server di
GitHub, gratis): vedi **[GUIDA.md](GUIDA.md)**. Quello non ha l'interfaccia
grafica ma non richiede installazioni sul tuo PC.
