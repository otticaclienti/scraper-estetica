#!/usr/bin/env python3
"""
Scraper di email da una lista di siti web.

Legge un CSV con una colonna di siti/domini, per ogni sito scarica la homepage
e alcune pagine "contatti", estrae le email e scrive un CSV con le coppie
(sito, email).

Caratteristiche:
- asincrono (veloce su migliaia di siti)
- ripresa automatica: se interrotto, riparte dai siti non ancora processati
- robusto agli errori di rete / timeout / SSL

Uso:
    python3 scraper.py --input siti.csv --output emails.csv

Opzioni principali:
    --input        CSV di ingresso (default: siti.csv)
    --output       CSV di uscita con sito,email (default: emails.csv)
    --column       nome o indice della colonna con i siti (default: auto-detect)
    --concurrency  numero di richieste in parallelo (default: 30)
    --timeout      timeout per richiesta in secondi (default: 15)
    --max-pages    pagine massime da visitare per sito (default: 5)
"""

import argparse
import asyncio
import csv
import os
import re
import sys
from urllib.parse import urljoin, urlparse

import aiohttp
from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# Estrazione email
# ---------------------------------------------------------------------------

# Regex email abbastanza permissiva ma sensata.
EMAIL_RE = re.compile(
    r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,24}\b"
)

# Estensioni di file che a volte vengono "catturate" come email finte
# (es. logo@2x.png) o domini di immagini/asset da scartare.
BAD_DOMAIN_SUFFIXES = (
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp",
    ".css", ".js", ".json", ".webp", ".ico",
)

# Email "spazzatura" tipiche da scartare.
JUNK_LOCAL_PARTS = {
    "example", "email", "your", "yourname", "name", "nome",
    "user", "username", "info@example", "test",
}

JUNK_SUBSTRINGS = (
    "example.com", "example.org", "domain.com", "sentry.io", "wixpress.com",
    "yourdomain", "email.com", "tuodominio", "mail.com@",
)


def clean_emails(raw_emails):
    """Normalizza e filtra una lista di email candidate."""
    out = set()
    for e in raw_emails:
        e = e.strip().strip(".").lower()
        if not e or "@" not in e:
            continue
        # scarta finte email che finiscono con estensioni di file
        if e.endswith(BAD_DOMAIN_SUFFIXES):
            continue
        local, _, domain = e.partition("@")
        if not local or not domain or "." not in domain:
            continue
        if local in JUNK_LOCAL_PARTS:
            continue
        if any(j in e for j in JUNK_SUBSTRINGS):
            continue
        # un dominio sensato non inizia/finisce con punto o trattino
        if domain.startswith((".", "-")) or domain.endswith((".", "-")):
            continue
        # scarta sequenze numeriche tipo 2x (es. immagini retina)
        if re.fullmatch(r"\d+x?", local):
            continue
        out.add(e)
    return out


def extract_emails_from_html(html):
    """Estrae email dal testo HTML e dai link mailto:."""
    found = set(EMAIL_RE.findall(html))

    # mailto: links (catturano anche email offuscate via attributo href)
    for m in re.findall(r"mailto:([^\"'?>\s]+)", html, flags=re.IGNORECASE):
        found.add(m)

    # de-offuscamento semplice: "info [at] dominio [dot] it"
    deobf = re.sub(r"\s*\[?\(?\s*at\s*\)?\]?\s*", "@", html, flags=re.IGNORECASE)
    deobf = re.sub(r"\s*\[?\(?\s*dot\s*\)?\]?\s*", ".", deobf, flags=re.IGNORECASE)
    found |= set(EMAIL_RE.findall(deobf))

    return clean_emails(found)


# ---------------------------------------------------------------------------
# Scelta delle pagine da visitare
# ---------------------------------------------------------------------------

# Parole chiave nei link che indicano pagine utili per trovare email.
CONTACT_KEYWORDS = (
    "contatt", "contact", "chi-siamo", "chisiamo", "about", "privacy",
    "dove-siamo", "dovesiamo", "info", "azienda", "team", "staff",
    "impressum", "support", "assistenza",
)


def normalize_url(site):
    """Trasforma un dominio/URL grezzo in un URL http(s) valido."""
    site = site.strip()
    if not site:
        return None
    # rimuovi eventuali wrapping
    site = site.strip().strip('"').strip("'")
    if not site:
        return None
    if not re.match(r"^https?://", site, re.IGNORECASE):
        site = "https://" + site
    return site


def pick_contact_links(base_url, html, max_links):
    """Trova i link interni che probabilmente contengono contatti/email."""
    try:
        soup = BeautifulSoup(html, "html.parser")
    except Exception:
        return []

    base_host = urlparse(base_url).netloc.lower()
    candidates = []
    seen = set()
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith(("mailto:", "tel:", "javascript:", "#")):
            continue
        text = (a.get_text() or "").lower()
        full = urljoin(base_url, href)
        parsed = urlparse(full)
        if parsed.scheme not in ("http", "https"):
            continue
        # solo link interni allo stesso dominio
        if parsed.netloc.lower() != base_host:
            continue
        key = parsed.path.lower()
        if key in seen:
            continue
        haystack = (href + " " + text).lower()
        if any(k in haystack for k in CONTACT_KEYWORDS):
            seen.add(key)
            candidates.append(full)
        if len(candidates) >= max_links:
            break
    return candidates


# ---------------------------------------------------------------------------
# Fetch
# ---------------------------------------------------------------------------

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "it-IT,it;q=0.9,en;q=0.8",
}


async def fetch(session, url, timeout):
    """Scarica una pagina, ritorna (html, final_url) o (None, None)."""
    try:
        async with session.get(
            url, timeout=aiohttp.ClientTimeout(total=timeout),
            ssl=False, allow_redirects=True,
        ) as resp:
            ctype = resp.headers.get("Content-Type", "")
            if "html" not in ctype and "text" not in ctype and ctype:
                return None, str(resp.url)
            # limita la dimensione letta (~2MB) per evitare pagine enormi
            data = await resp.content.read(2_000_000)
            html = data.decode(resp.charset or "utf-8", errors="replace")
            return html, str(resp.url)
    except Exception:
        return None, None


async def scrape_site(session, site, timeout, max_pages):
    """Scarica un sito (homepage + pagine contatti) e ritorna le email trovate."""
    url = normalize_url(site)
    if not url:
        return site, set(), "url-non-valido"

    emails = set()
    status = "ok"

    html, final_url = await fetch(session, url, timeout)
    if html is None:
        # riprova in http se era https
        if url.lower().startswith("https://"):
            html, final_url = await fetch(
                session, "http://" + url[len("https://"):], timeout
            )
        if html is None:
            return site, set(), "irraggiungibile"

    emails |= extract_emails_from_html(html)

    # visita le pagine contatti
    contact_links = pick_contact_links(final_url or url, html, max_pages - 1)
    for link in contact_links:
        chtml, _ = await fetch(session, link, timeout)
        if chtml:
            emails |= extract_emails_from_html(chtml)

    if not emails:
        status = "nessuna-email"
    return site, emails, status


# ---------------------------------------------------------------------------
# Lettura input / scrittura output con ripresa
# ---------------------------------------------------------------------------

def read_sites(path, column):
    """Legge i siti dal CSV. Auto-detect della colonna se non specificata."""
    sites = []
    with open(path, newline="", encoding="utf-8-sig", errors="replace") as f:
        sample = f.read(4096)
        f.seek(0)
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
        except csv.Error:
            dialect = csv.excel
        reader = csv.reader(f, dialect)
        rows = list(reader)

    if not rows:
        return sites

    # determina la colonna
    header = rows[0]
    col_idx = None
    data_start = 0

    if column is not None:
        # indice numerico o nome colonna
        if column.isdigit():
            col_idx = int(column)
        else:
            lower_header = [h.strip().lower() for h in header]
            if column.lower() in lower_header:
                col_idx = lower_header.index(column.lower())
                data_start = 1
        if col_idx is None:
            print(f"Colonna '{column}' non trovata, uso auto-detect.", file=sys.stderr)

    if col_idx is None:
        # auto-detect: cerca header che sembra un sito/url
        lower_header = [h.strip().lower() for h in header]
        url_names = ("sito", "site", "url", "website", "web", "dominio", "domain", "link")
        for i, h in enumerate(lower_header):
            if any(n in h for n in url_names):
                col_idx = i
                data_start = 1
                break
        if col_idx is None:
            # nessun header riconoscibile: scegli la colonna che sembra contenere URL
            # guardando la prima riga di dati
            first = rows[0]
            for i, cell in enumerate(first):
                if re.search(r"\.[a-z]{2,}", cell.lower()):
                    col_idx = i
                    break
            if col_idx is None:
                col_idx = 0
            data_start = 0  # nessun header riconosciuto -> tratta tutto come dati

    seen = set()
    for row in rows[data_start:]:
        if col_idx >= len(row):
            continue
        val = row[col_idx].strip()
        if not val:
            continue
        key = val.lower()
        if key in seen:
            continue
        seen.add(key)
        sites.append(val)
    return sites


def load_done(output_path):
    """Carica i siti già processati (per la ripresa)."""
    done = set()
    if not os.path.exists(output_path):
        return done
    try:
        with open(output_path, newline="", encoding="utf-8") as f:
            reader = csv.reader(f)
            next(reader, None)  # header
            for row in reader:
                if row:
                    done.add(row[0].strip().lower())
    except Exception:
        pass
    return done


class CsvSink:
    """Piccolo wrapper attorno a csv.writer per poter fare flush del file."""

    def __init__(self, file_obj):
        self.file = file_obj
        self.writer = csv.writer(file_obj)

    def writerow(self, row):
        self.writer.writerow(row)

    def flush(self):
        try:
            self.file.flush()
        except Exception:
            pass


async def worker(name, queue, session, sink, lock, timeout, max_pages, counters):
    while True:
        site = await queue.get()
        if site is None:
            queue.task_done()
            return
        try:
            site, emails, status = await scrape_site(session, site, timeout, max_pages)
        except Exception as e:
            site, emails, status = site, set(), f"errore:{type(e).__name__}"

        async with lock:
            if emails:
                for em in sorted(emails):
                    sink.writerow([site, em, status])
                counters["emails"] += len(emails)
                counters["with_email"] += 1
            else:
                sink.writerow([site, "", status])
            counters["done"] += 1
            if counters["done"] % 50 == 0:
                sink.flush()
                print(
                    f"  ...{counters['done']}/{counters['total']} siti | "
                    f"{counters['with_email']} con email | "
                    f"{counters['emails']} email totali",
                    file=sys.stderr,
                )
        queue.task_done()


async def run(args):
    sites = read_sites(args.input, args.column)
    if not sites:
        print("Nessun sito trovato nel file di input.", file=sys.stderr)
        return 1

    done = load_done(args.output)
    todo = [s for s in sites if s.strip().lower() not in done]

    print(
        f"Siti totali: {len(sites)} | già fatti: {len(done)} | "
        f"da processare: {len(todo)}",
        file=sys.stderr,
    )
    if not todo:
        print("Tutti i siti sono già stati processati. Nulla da fare.", file=sys.stderr)
        return 0

    # apri output in append se esiste, altrimenti scrivi header
    new_file = not os.path.exists(args.output) or os.path.getsize(args.output) == 0
    out_f = open(args.output, "a", newline="", encoding="utf-8")
    sink = CsvSink(out_f)
    if new_file:
        sink.writerow(["sito", "email", "stato"])

    counters = {
        "total": len(todo), "done": 0,
        "with_email": 0, "emails": 0,
    }
    lock = asyncio.Lock()
    queue = asyncio.Queue()
    for s in todo:
        queue.put_nowait(s)

    connector = aiohttp.TCPConnector(
        limit=args.concurrency, ttl_dns_cache=300, force_close=True,
        enable_cleanup_closed=True,
    )
    async with aiohttp.ClientSession(headers=HEADERS, connector=connector) as session:
        workers = [
            asyncio.create_task(
                worker(f"w{i}", queue, session, sink, lock,
                       args.timeout, args.max_pages, counters)
            )
            for i in range(args.concurrency)
        ]
        await queue.join()
        for _ in workers:
            queue.put_nowait(None)
        await asyncio.gather(*workers, return_exceptions=True)

    out_f.flush()
    out_f.close()
    print(
        f"\nFatto. {counters['done']} siti processati | "
        f"{counters['with_email']} con almeno un'email | "
        f"{counters['emails']} email totali trovate.\n"
        f"Risultato salvato in: {args.output}",
        file=sys.stderr,
    )
    return 0


def main():
    p = argparse.ArgumentParser(description="Estrae email da una lista di siti.")
    p.add_argument("--input", "-i", default="siti.csv", help="CSV di ingresso")
    p.add_argument("--output", "-o", default="emails.csv", help="CSV di uscita")
    p.add_argument("--column", "-c", default=None,
                   help="nome o indice colonna con i siti (default: auto)")
    p.add_argument("--concurrency", type=int, default=30,
                   help="richieste in parallelo (default: 30)")
    p.add_argument("--timeout", type=int, default=15,
                   help="timeout per richiesta in secondi (default: 15)")
    p.add_argument("--max-pages", type=int, default=5,
                   help="pagine massime per sito (default: 5)")
    args = p.parse_args()

    if not os.path.exists(args.input):
        print(f"File di input non trovato: {args.input}", file=sys.stderr)
        sys.exit(1)

    try:
        rc = asyncio.run(run(args))
    except KeyboardInterrupt:
        print("\nInterrotto. Rilancia lo stesso comando per riprendere.", file=sys.stderr)
        rc = 130
    sys.exit(rc)


if __name__ == "__main__":
    main()
