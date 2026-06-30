# Guida: la Dashboard (fai tutto da un'unica pagina)

La dashboard è una pagina sola da cui fai **tutto**: colleghi GitHub, carichi la
lista, premi avvia, vedi l'avanzamento in tempo reale e scarichi le email. Il
lavoro pesante gira **gratis sui server di GitHub** (GitHub Actions), tu non
installi niente.

---

## Una volta sola: il token di GitHub

Serve a dare alla pagina il permesso di lavorare sul tuo repository.

1. Apri **[questa pagina](https://github.com/settings/personal-access-tokens/new)**
   (GitHub → Settings → Developer settings → Fine-grained tokens → *Generate new token*).
2. **Token name**: un nome qualsiasi (es. `scraper`).
3. **Expiration**: scegli ad es. 90 giorni.
4. **Repository access** → **Only select repositories** → scegli **`scraper-estetica`**.
5. **Permissions** → **Repository permissions**:
   - **Contents** → **Read and write**
   - **Actions** → **Read and write**
   - (Metadata resta su *Read*, è automatico)
6. In fondo premi **Generate token** e **copia** il codice (inizia con
   `github_pat_...`).

Il token resta salvato **solo nel tuo browser**.

---

## Aprire la dashboard

- **Online:** se il repository è pubblico e GitHub Pages è attivo, vai su
  `https://otticaclienti.github.io/scraper-estetica/`.
- **In locale (sempre funziona):** scarica il file `docs/index.html` dal
  repository e **aprilo con doppio click** (si apre in Chrome). Non serve
  installare nulla.

---

## Usare la dashboard

1. **Collega**: incolla il token e premi **🔌 Collega**. Vedi “✓ collegato”.
2. **Carica la lista**: trascina il CSV nel riquadro. Ti dice quanti siti ha
   trovato (li carica su GitHub da solo).
3. **Scegli la potenza** (🚀 Massima consigliata) e premi **▶ Avvia scraping**.
4. **Guarda l'avanzamento**: barra, contatori e tabella delle email si aggiornano
   da soli ogni pochi secondi. C'è anche il link “vedi log su GitHub”.
5. A fine corsa premi **⬇ Scarica emails.csv**.

Puoi chiudere la pagina e riaprirla più tardi: se lo scraping è ancora in corso,
si riaggancia da solo e continua a mostrarti l'avanzamento.

---

## Domande frequenti

**È gratis?** Sì: gira su GitHub Actions, incluso nel tuo account.

**I miei dati?** La lista e le email restano nel tuo repository GitHub. Il token
sta solo nel tuo browser.

**“Avvio non riuscito / progetto non attivo sul branch principale”** → significa
che il programma non è ancora pubblicato sul branch principale del repo. Una volta
pubblicato lì, il pulsante Avvia funziona.

**Quanto dura?** Indicativamente 1–2 ore per 7000 siti in modalità massima.
