# Scraper email da lista di siti

Estrae tutte le email da una lista di siti web (anche migliaia). Per ogni sito
scarica la homepage e le pagine "contatti / chi siamo / privacy", cerca le email
nel testo e nei link `mailto:`, e salva tutto in un CSV.

> 🟢 **Vuoi usarlo dal browser, gratis e senza installare niente?**
> Segui la **[GUIDA.md](GUIDA.md)**: carichi il CSV su GitHub, premi un pulsante
> nella scheda *Actions*, e scarichi le email. Tutto online.
>
> Il resto di questo file spiega invece come usarlo a riga di comando sul tuo PC.

## Installazione (una volta sola)

```bash
pip3 install -r requirements.txt
```

## Come si usa

1. Prepara un file CSV con i siti, ad esempio `siti.csv`. Basta una colonna con
   gli indirizzi. Esempi di formato accettati:

   ```csv
   sito
   www.studioestetica.it
   https://centrobenessere.com
   esempio.it
   ```

   Funziona anche se il CSV ha più colonne (es. `Nome;Website;Città`): lo script
   trova da solo la colonna con i siti. Accetta separatori `,` `;` o tab.

2. Lancia lo scraper:

   ```bash
   python3 scraper.py --input siti.csv --output emails.csv
   ```

3. Al termine trovi `emails.csv` con tre colonne:

   | sito | email | stato |
   |------|-------|-------|
   | www.studioestetica.it | info@studioestetica.it | ok |
   | centrobenessere.com | | nessuna-email |
   | sitorotto.it | | irraggiungibile |

   Se un sito ha più email, vengono scritte su più righe (una email per riga).

## Ripresa automatica

Su 7000 siti il processo può durare a lungo. Se lo interrompi (Ctrl+C, caduta di
rete, ecc.), **rilancia lo stesso identico comando**: lo script salta i siti già
presenti in `emails.csv` e riparte da dove era rimasto.

## Opzioni

| Opzione | Default | Descrizione |
|---------|---------|-------------|
| `--input`, `-i` | `siti.csv` | CSV di ingresso con i siti |
| `--output`, `-o` | `emails.csv` | CSV di uscita |
| `--column`, `-c` | auto | Nome o indice (0-based) della colonna con i siti |
| `--concurrency` | `30` | Siti scaricati in parallelo. Alzalo per andare più veloce, abbassalo se la rete soffre |
| `--timeout` | `15` | Secondi massimi di attesa per pagina |
| `--max-pages` | `5` | Pagine massime visitate per sito (home + contatti) |

Esempio più veloce:

```bash
python3 scraper.py -i siti.csv -o emails.csv --concurrency 50
```

Specificare la colonna a mano (se l'auto-detect sbaglia):

```bash
python3 scraper.py -i siti.csv -c Website
# oppure per indice (la prima colonna è 0)
python3 scraper.py -i siti.csv -c 1
```

## Note

- Le email vengono ripulite da finte catture (es. `logo@2x.png`, indirizzi di
  esempio tipo `nome@example.com`).
- Lo script tenta `https` e, se fallisce, ripiega su `http`.
- Lo scraping legge solo pagine pubbliche del sito; non aggira login o protezioni.
```

```text
Tempo indicativo: con --concurrency 30 e 7000 siti, considera circa 1-2 ore
(dipende da quanti siti sono lenti o irraggiungibili).
```
