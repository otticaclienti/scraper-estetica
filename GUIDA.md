# Guida: usare lo scraper dal browser (gratis, con GitHub Actions)

Questo metodo gira **sui server di GitHub**, è **gratuito**, si usa **tutto dal
browser** e **non devi installare niente** sul tuo computer.

Risultato finale: scarichi un file `emails.csv` con i siti e le email trovate.

---

## Passo 1 — Carica la tua lista di siti

1. Vai sulla pagina del repository su GitHub (nel browser).
2. Assicurati di essere sul branch giusto (in alto a sinistra, il menù dei
   branch): **`claude/extract-emails-7k-sites-wztsbl`**.
3. Premi **Add file** → **Upload files**.
4. Trascina il tuo file CSV con i 7000 siti.
   - **Importante:** chiamalo **`siti.csv`** (così non devi cambiare niente dopo).
   - Basta che dentro ci sia una colonna con gli indirizzi dei siti.
5. In basso premi **Commit changes**.

---

## Passo 2 — Avvia lo scraper

1. In alto nel repository, apri la scheda **Actions**.
2. Nella colonna a sinistra clicca su **"Estrai email dai siti"**.
3. A destra premi il pulsante **Run workflow**.
4. Si apre un piccolo riquadro:
   - **branch**: scegli `claude/extract-emails-7k-sites-wztsbl`
   - **Nome del file CSV**: lascia `siti.csv` (o scrivi il nome che hai usato)
   - **Potenza**: lascia `massima` per trovare il massimo delle email (usa anche
     render JavaScript e OCR sulle immagini). Scegli `base` solo se vuoi andare
     molto più veloce accontentandoti del download semplice.
   - gli altri campi puoi lasciarli così come sono
5. Premi il pulsante verde **Run workflow**.

> ⚙️ **Cosa fa la modalità "massima"** per trovare quante più email possibile:
> oltre al testo normale, decodifica le email protette da Cloudflare, le entità
> HTML, gli offuscamenti tipo `info [at] sito [punto] it`, quelle costruite via
> JavaScript, **apre i siti con un vero browser** (per le email caricate
> dinamicamente) e **legge le email messe come immagini con l'OCR**. È più lenta
> ma molto più completa.

Parte tutto da solo. ☕

---

## Passo 3 — Guarda l'avanzamento in tempo reale

1. Sempre nella scheda **Actions**, clicca sull'esecuzione appena partita
   (quella con il pallino giallo che gira).
2. Clicca sul job **scrape** → step **"Esegui lo scraper"**.
3. Vedi scorrere l'avanzamento, per esempio:
   ```
   ...250/7000 siti | 180 con email | 240 email totali
   ...300/7000 siti | 215 con email | 290 email totali
   ```

Puoi chiudere la pagina: continua a girare da solo sui server di GitHub.

---

## Passo 4 — Scarica le email

1. Quando l'esecuzione finisce (pallino verde ✓), torna nella pagina di
   quell'esecuzione.
2. Scendi in fondo: trovi la sezione **Artifacts** con un file **`emails.csv`**.
3. Cliccalo per scaricarlo. Dentro trovi tre colonne: **sito, email, stato**.

Trovi anche un riepilogo (siti con email, email uniche) nella pagina del
risultato.

---

## Domande frequenti

**Quanto costa?** Niente. GitHub Actions è gratis per il tuo uso (il tuo piano
include ampiamente le ore necessarie: 7000 siti ≈ 1–2 ore di elaborazione).

**Quanto dura?** Indicativamente 1–2 ore per 7000 siti. Per andare più veloce,
al Passo 2 metti un valore più alto in "Siti in parallelo" (es. `50`).

**Posso rilanciarlo?** Sì, tutte le volte che vuoi. Se cambi la lista, ricarica
`siti.csv` e premi di nuovo Run workflow.

**E se si interrompe?** Lo scraper salva man mano; rilanciandolo riprende dai
siti non ancora fatti (se conservi il file dei risultati). Con GitHub Actions
di solito non serve: l'esecuzione arriva fino in fondo.

**Colonna dei siti diversa?** Se il CSV ha più colonne, lo script trova da solo
quella con i siti. Funziona con separatori `,` `;` o tab.
