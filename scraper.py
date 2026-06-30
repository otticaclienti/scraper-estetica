#!/usr/bin/env python3
"""
Scraper di email da una lista di siti web — versione "potente".

Per ogni sito scarica homepage + pagine contatti (e prova pagine tipiche tipo
/contatti, /privacy), poi estrae le email con molte tecniche:

- testo normale e link mailto: (anche con %40 al posto di @)
- entita' HTML (&#64; = @) e caratteri invisibili
- decodifica dell'offuscamento Cloudflare (data-cfemail / cdn-cgi/email-protection)
- offuscamenti testuali: "info [at] dominio [punto] it", (at), chiocciola, dot...
- email costruite via JavaScript ("info" + "@" + "sito.it")
- RENDER JavaScript con browser headless (email caricate dinamicamente) [opzionale]
- OCR sulle immagini (email messe come foto)                            [opzionale]

Uso base:
    python3 scraper.py --input siti.csv --output emails.csv

Massima potenza (piu' lento ma trova di piu'):
    python3 scraper.py -i siti.csv -o emails.csv --render --ocr

Ripresa: se interrotto, rilancia lo stesso comando e riparte dai siti mancanti.
"""

import argparse
import asyncio
import csv
import glob
import html as html_module
import io
import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import unquote, urljoin, urlparse

import aiohttp
from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# Estrazione email
# ---------------------------------------------------------------------------

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,24}")

BAD_DOMAIN_SUFFIXES = (
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp",
    ".css", ".js", ".json", ".ico", ".tif", ".tiff", ".mp4", ".pdf",
)

JUNK_LOCAL_PARTS = {
    "example", "email", "your", "yourname", "name", "nome", "mail",
    "user", "username", "test", "esempio", "info@example",
}

# Domini tecnici / di terze parti da scartare (non sono contatti reali).
JUNK_DOMAIN_SUBSTRINGS = (
    "example.com", "example.org", "example.net", "domain.com", "domain.it",
    "sentry.io", "sentry-next.wixpress.com", "wixpress.com", "wix.com",
    "googleapis.com", "gstatic.com", "schema.org", "w3.org", "sentry.wixpress",
    "yourdomain", "email.com", "tuodominio", "tuosito", "namedomain",
    "godaddy.com", "squarespace.com", "wordpress.org", "wordpress.com",
    "core.trac.wordpress.org", "@2x", "@3x", "@sx", "u003e", "u0040",
    "placeholder", "test.com", "abc.com", "mail.example",
)

ZERO_WIDTH = dict.fromkeys(
    map(ord, "​‌‍⁠﻿­"), None
)

# TLD comuni: usati per "ritagliare" un dominio quando del testo si incolla
# subito dopo (es. "info@sito.itorario" -> "info@sito.it").
COMMON_TLDS = [
    "com", "it", "org", "net", "eu", "info", "biz", "name", "pro", "shop",
    "online", "store", "site", "cloud", "app", "io", "co", "tv", "me",
    "fr", "de", "es", "uk", "ch", "at", "be", "nl", "us", "email",
    # TLD piu' lunghi ma reali: vanno protetti dal "ritaglio"
    "company", "center", "group", "clinic", "studio", "salon", "beauty",
    "design", "academy", "digital", "events", "care", "life", "world",
    "agency", "solutions", "srl", "moda", "boutique", "club", "fit",
]
COMMON_TLDS_SET = set(COMMON_TLDS)
COMMON_TLDS_BYLEN = sorted(COMMON_TLDS, key=len, reverse=True)


def _fix_glued_tld(domain):
    """Se l'ultima etichetta e' un TLD noto seguito da una parola incollata,
    taglia alla fine del TLD (es. 'sito.itorario' -> 'sito.it')."""
    parts = domain.split(".")
    last = parts[-1]
    if last in COMMON_TLDS_SET:
        return domain
    for tld in COMMON_TLDS_BYLEN:
        if last.startswith(tld) and len(last) > len(tld) and last[len(tld):].isalpha():
            parts[-1] = tld
            return ".".join(parts)
    return domain


def decode_cfemail(hexstr):
    """Decodifica una stringa Cloudflare email-protection (esadecimale)."""
    try:
        hexstr = hexstr.strip()
        r = int(hexstr[:2], 16)
        out = []
        for i in range(2, len(hexstr), 2):
            out.append(chr(int(hexstr[i:i + 2], 16) ^ r))
        return "".join(out)
    except Exception:
        return None


def clean_emails(raw_emails):
    """Normalizza e filtra una lista di email candidate."""
    out = set()
    for e in raw_emails:
        if not e:
            continue
        e = e.translate(ZERO_WIDTH)
        e = e.strip().strip(".,;:<>()[]{}\"'").lower()
        e = e.replace("mailto:", "")
        if "@" not in e:
            continue
        # se ci sono piu' @ tieni la prima coppia local@domain plausibile
        m = EMAIL_RE.search(e)
        if not m:
            continue
        e = m.group(0).strip(".")
        local, _, domain = e.partition("@")
        if not local or not domain or "." not in domain:
            continue
        domain = _fix_glued_tld(domain)
        e = local + "@" + domain
        if e.endswith(BAD_DOMAIN_SUFFIXES):
            continue
        if local in JUNK_LOCAL_PARTS:
            continue
        if any(j in e for j in JUNK_DOMAIN_SUBSTRINGS):
            continue
        if domain.startswith((".", "-")) or domain.endswith((".", "-")):
            continue
        if ".." in domain:
            continue
        # tld finale di lettere
        tld = domain.rsplit(".", 1)[-1]
        if not tld.isalpha() or len(tld) < 2:
            continue
        # scarta immagini retina tipo logo@2x
        if re.fullmatch(r"\d+x?", local):
            continue
        # local part troppo lungo = probabile spazzatura
        if len(local) > 64 or len(e) > 100:
            continue
        out.add(e)
    return out


def _deobfuscate_text(text):
    """Sostituisce gli offuscamenti testuali piu' comuni con @ e . ."""
    t = text
    # @  ->  varianti
    t = re.sub(r"\s*[\(\[\{<]\s*(?:at|chiocciola|arobase|apestaartje)\s*[\)\]\}>]\s*",
               "@", t, flags=re.IGNORECASE)
    t = re.sub(r"\s+(?:at|chiocciola)\s+", "@", t, flags=re.IGNORECASE)
    # .  ->  varianti
    t = re.sub(r"\s*[\(\[\{<]\s*(?:dot|punto|point)\s*[\)\]\}>]\s*",
               ".", t, flags=re.IGNORECASE)
    t = re.sub(r"\s+(?:dot|punto)\s+", ".", t, flags=re.IGNORECASE)
    return t


def extract_emails_from_html(html, base_url=None):
    """Estrae email da una pagina HTML con molte tecniche."""
    if not html:
        return set(), []

    found = set()

    # 0) entita' HTML (&#64; ecc.) -> testo reale
    unescaped = html_module.unescape(html)

    # 1) testo grezzo + entita'
    found |= set(EMAIL_RE.findall(html))
    found |= set(EMAIL_RE.findall(unescaped))

    # 2) Cloudflare email protection: data-cfemail="..."
    for hx in re.findall(r'data-cfemail="([0-9a-fA-F]+)"', html):
        dec = decode_cfemail(hx)
        if dec:
            found.add(dec)
    # /cdn-cgi/l/email-protection#<hex> oppure ...protection?<hex>
    for hx in re.findall(r'email-protection[#?]([0-9a-fA-F]+)', html):
        dec = decode_cfemail(hx)
        if dec:
            found.add(dec)

    # 3) mailto: (anche con encoding %40 = @, %2E = .)
    for m in re.findall(r'mailto:([^"\'?>\s]+)', unescaped, flags=re.IGNORECASE):
        found.add(unquote(m))

    # 4) attributi data-* tipici (data-email, data-mail, data-e-mail)
    for m in re.findall(r'data-(?:e-?mail|mail)\s*=\s*["\']([^"\']+)["\']',
                        unescaped, flags=re.IGNORECASE):
        found.add(unquote(m))

    # 5) email costruite via JS:  "info" + "@" + "sito.it"
    glued = re.sub(r"['\"]\s*\+\s*['\"]", "", unescaped)
    found |= set(EMAIL_RE.findall(glued))

    # 6) de-offuscamento testuale: info [at] dominio [dot] it
    deobf = _deobfuscate_text(unescaped)
    found |= set(EMAIL_RE.findall(deobf))

    emails = clean_emails(found)

    # raccogli URL di immagini candidate (per eventuale OCR)
    image_urls = []
    if base_url:
        try:
            soup = BeautifulSoup(html, "html.parser")
            for img in soup.find_all("img"):
                src = img.get("src") or img.get("data-src") or ""
                if not src:
                    continue
                alt = (img.get("alt") or "").lower()
                hay = (src + " " + alt).lower()
                full = urljoin(base_url, src)
                if any(k in hay for k in ("mail", "email", "contatt", "contact",
                                          "scrivi", "@")):
                    image_urls.append((full, 2))   # priorita' alta
                else:
                    image_urls.append((full, 1))   # priorita' bassa
        except Exception:
            pass

    return emails, image_urls


# ---------------------------------------------------------------------------
# Scelta delle pagine
# ---------------------------------------------------------------------------

CONTACT_KEYWORDS = (
    "contatt", "contact", "chi-siamo", "chisiamo", "about", "privacy",
    "dove-siamo", "dovesiamo", "info", "azienda", "team", "staff",
    "impressum", "support", "assistenza", "note-legali", "cookie",
    "prenota", "appuntament", "scrivi", "recapiti", "sede",
)

GUESS_PATHS = (
    "/contatti", "/contatto", "/contact", "/contact-us", "/contacts",
    "/chi-siamo", "/about", "/about-us", "/privacy", "/privacy-policy",
    "/note-legali", "/cookie-policy", "/dove-siamo", "/recapiti",
)


def normalize_url(site):
    site = (site or "").strip().strip('"').strip("'")
    if not site:
        return None
    if not re.match(r"^https?://", site, re.IGNORECASE):
        site = "https://" + site
    return site


def pick_contact_links(base_url, html, limit):
    try:
        soup = BeautifulSoup(html, "html.parser")
    except Exception:
        return []
    base_host = urlparse(base_url).netloc.lower()
    out, seen = [], set()
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith(("mailto:", "tel:", "javascript:", "#")):
            continue
        text = (a.get_text() or "").lower()
        full = urljoin(base_url, href)
        parsed = urlparse(full)
        if parsed.scheme not in ("http", "https"):
            continue
        if parsed.netloc.lower() != base_host:
            continue
        key = parsed.path.lower().rstrip("/")
        if key in seen:
            continue
        if any(k in (href + " " + text).lower() for k in CONTACT_KEYWORDS):
            seen.add(key)
            out.append(full)
        if len(out) >= limit:
            break
    return out


# ---------------------------------------------------------------------------
# Scraper
# ---------------------------------------------------------------------------

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "it-IT,it;q=0.9,en;q=0.8",
}


def find_chromium():
    for p in sorted(glob.glob("/opt/pw-browsers/chromium-*/chrome-linux/chrome")):
        return p
    return None


class Scraper:
    def __init__(self, args):
        self.args = args
        self.timeout = args.timeout
        self.max_pages = args.max_pages
        self.use_render = args.render
        self.use_ocr = args.ocr
        self.browser = None
        self._pw = None
        self.render_sem = asyncio.Semaphore(max(1, args.render_concurrency))
        self._browser_lock = asyncio.Lock()
        self.ocr_executor = ThreadPoolExecutor(max_workers=args.ocr_workers) \
            if args.ocr else None

    # ---- fetch statico -------------------------------------------------
    async def fetch(self, session, url):
        try:
            async with session.get(
                url, timeout=aiohttp.ClientTimeout(total=self.timeout),
                ssl=False, allow_redirects=True,
            ) as resp:
                ctype = resp.headers.get("Content-Type", "")
                if ctype and "html" not in ctype and "text" not in ctype \
                        and "xml" not in ctype:
                    return None, str(resp.url)
                data = await resp.content.read(3_000_000)
                charset = resp.charset or "utf-8"
                return data.decode(charset, errors="replace"), str(resp.url)
        except Exception:
            return None, None

    async def fetch_bytes(self, session, url, limit=4_000_000):
        try:
            async with session.get(
                url, timeout=aiohttp.ClientTimeout(total=self.timeout),
                ssl=False, allow_redirects=True,
            ) as resp:
                return await resp.content.read(limit)
        except Exception:
            return None

    # ---- render JS -----------------------------------------------------
    async def ensure_browser(self):
        if self.browser is not None:
            return
        async with self._browser_lock:
            if self.browser is not None:
                return
            from playwright.async_api import async_playwright
            self._pw = await async_playwright().start()
            exe = find_chromium()
            launch_args = ["--no-sandbox", "--disable-dev-shm-usage",
                           "--disable-gpu",
                           "--disable-blink-features=AutomationControlled"]
            try:
                self.browser = await self._pw.chromium.launch(
                    headless=True, args=launch_args,
                    **({"executable_path": exe} if exe else {}),
                )
            except Exception:
                self.browser = await self._pw.chromium.launch(
                    headless=True, args=launch_args)

    async def _render_page(self, ctx, url):
        page = await ctx.new_page()
        await page.goto(url, timeout=self.timeout * 1000,
                        wait_until="domcontentloaded")
        await page.wait_for_timeout(1500)
        content = await page.content()
        try:
            hrefs = await page.eval_on_selector_all(
                "a[href^='mailto:']",
                "els => els.map(e => e.getAttribute('href'))")
            content += "\n" + "\n".join(h or "" for h in hrefs)
        except Exception:
            pass
        return content

    async def render(self, url):
        """Apre l'URL in un browser headless e ritorna l'HTML renderizzato.

        Tutto e' protetto da timeout: nessun sito puo' bloccare il render
        (e quindi gli altri worker) all'infinito."""
        async with self.render_sem:
            ctx = None
            try:
                await asyncio.wait_for(self.ensure_browser(), timeout=60)
                ctx = await self.browser.new_context(
                    user_agent=HEADERS["User-Agent"],
                    locale="it-IT", ignore_https_errors=True,
                )
                return await asyncio.wait_for(
                    self._render_page(ctx, url), timeout=self.timeout + 10)
            except Exception:
                return None
            finally:
                if ctx is not None:
                    try:
                        await asyncio.wait_for(ctx.close(), timeout=10)
                    except Exception:
                        pass

    # ---- OCR -----------------------------------------------------------
    def _ocr_sync(self, data):
        try:
            import pytesseract
            from PIL import Image, ImageOps
            img = Image.open(io.BytesIO(data))
            img = img.convert("L")
            img = ImageOps.autocontrast(img)
            # ingrandisci immagini piccole per leggere meglio
            if img.width < 1000:
                ratio = max(1, 1000 // max(1, img.width))
                if ratio > 1:
                    img = img.resize((img.width * ratio, img.height * ratio))
            txt = pytesseract.image_to_string(img, lang="ita+eng")
            return txt
        except Exception:
            return ""

    async def ocr_images(self, session, image_urls, loop, limit):
        """Scarica ed esegue OCR su un numero limitato di immagini candidate."""
        # ordina per priorita' (mail/contact prima), dedup
        seen, ordered = set(), []
        for u, prio in sorted(image_urls, key=lambda x: -x[1]):
            if u in seen:
                continue
            seen.add(u)
            ordered.append(u)
        ordered = ordered[:limit]

        emails = set()
        for u in ordered:
            data = await self.fetch_bytes(session, u, limit=3_000_000)
            if not data or len(data) < 200:
                continue
            txt = await loop.run_in_executor(self.ocr_executor, self._ocr_sync, data)
            if txt and "@" in txt:
                emails |= extract_emails_from_html(_deobfuscate_text(txt))[0]
                emails |= clean_emails(EMAIL_RE.findall(_deobfuscate_text(txt)))
        return emails

    # ---- un sito -------------------------------------------------------
    async def scrape_site(self, session, site, loop):
        url = normalize_url(site)
        if not url:
            return site, set(), "url-non-valido"

        emails = set()
        methods = set()
        all_images = []

        html, final_url = await self.fetch(session, url)
        if html is None and url.lower().startswith("https://"):
            html, final_url = await self.fetch(
                session, "http://" + url[len("https://"):])
        if html is None:
            # ultimo tentativo: render diretto (alcuni siti bloccano i bot semplici)
            if self.use_render:
                html = await self.render(url)
                final_url = url
                if html:
                    methods.add("render")
            if html is None:
                return site, set(), "irraggiungibile"

        base = final_url or url
        e, imgs = extract_emails_from_html(html, base)
        emails |= e
        all_images += imgs
        if e:
            methods.add("statico")

        # pagine da visitare: link contatti + percorsi tipici
        links = pick_contact_links(base, html, self.max_pages)
        link_paths = {urlparse(l).path.lower().rstrip("/") for l in links}
        root = "{0.scheme}://{0.netloc}".format(urlparse(base))
        for gp in GUESS_PATHS:
            if len(links) >= self.max_pages:
                break
            if gp.rstrip("/") in link_paths:
                continue
            links.append(root + gp)

        for link in links[:self.max_pages]:
            chtml, _ = await self.fetch(session, link)
            if chtml:
                e, imgs = extract_emails_from_html(chtml, link)
                if e:
                    emails |= e
                    methods.add("statico")
                all_images += imgs

        # FALLBACK render JS se non abbiamo trovato nulla
        if self.use_render and not emails:
            rhtml = await self.render(base)
            if rhtml:
                e, imgs = extract_emails_from_html(rhtml, base)
                if e:
                    emails |= e
                    methods.add("render")
                all_images += imgs
            # prova anche la prima pagina contatti renderizzata
            if not emails and links:
                rhtml = await self.render(links[0])
                if rhtml:
                    e, imgs = extract_emails_from_html(rhtml, links[0])
                    if e:
                        emails |= e
                        methods.add("render")
                    all_images += imgs

        # FALLBACK OCR sulle immagini se ancora nulla (o sempre, se --ocr-all)
        if self.use_ocr and (not emails or self.args.ocr_all):
            ocr_emails = await self.ocr_images(
                session, all_images, loop, self.args.ocr_max_images)
            if ocr_emails:
                emails |= ocr_emails
                methods.add("ocr")

        status = "+".join(sorted(methods)) if emails else "nessuna-email"
        return site, emails, status

    async def close(self):
        if self.browser:
            try:
                await self.browser.close()
            except Exception:
                pass
        if self._pw:
            try:
                await self._pw.stop()
            except Exception:
                pass
        if self.ocr_executor:
            self.ocr_executor.shutdown(wait=False)


# ---------------------------------------------------------------------------
# Input / output con ripresa
# ---------------------------------------------------------------------------

def read_sites(path, column):
    sites = []
    with open(path, newline="", encoding="utf-8-sig", errors="replace") as f:
        sample = f.read(4096)
        f.seek(0)
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
        except csv.Error:
            dialect = csv.excel
        rows = list(csv.reader(f, dialect))
    if not rows:
        return sites

    header = rows[0]
    col_idx, data_start = None, 0

    if column is not None:
        if column.isdigit():
            col_idx = int(column)
        else:
            lh = [h.strip().lower() for h in header]
            if column.lower() in lh:
                col_idx = lh.index(column.lower()); data_start = 1
        if col_idx is None:
            print(f"Colonna '{column}' non trovata, uso auto-detect.", file=sys.stderr)

    if col_idx is None:
        lh = [h.strip().lower() for h in header]
        url_names = ("sito", "site", "url", "website", "web", "dominio",
                     "domain", "link", "indirizzo")
        for i, h in enumerate(lh):
            if any(n in h for n in url_names):
                col_idx = i; data_start = 1; break
        if col_idx is None:
            for i, cell in enumerate(rows[0]):
                if re.search(r"\.[a-z]{2,}", cell.lower()):
                    col_idx = i; break
            if col_idx is None:
                col_idx = 0
            data_start = 0

    seen = set()
    for row in rows[data_start:]:
        if col_idx >= len(row):
            continue
        val = row[col_idx].strip()
        if not val:
            continue
        k = val.lower()
        if k in seen:
            continue
        seen.add(k)
        sites.append(val)
    return sites


def load_done(output_path):
    """Ritorna (siti_gia_fatti, siti_con_email, email_totali) dall'output."""
    done = set()
    with_email = set()
    emails = 0
    if not os.path.exists(output_path):
        return done, 0, 0
    try:
        with open(output_path, newline="", encoding="utf-8") as f:
            reader = csv.reader(f)
            next(reader, None)
            for row in reader:
                if not row:
                    continue
                site = row[0].strip().lower()
                done.add(site)
                if len(row) > 1 and row[1].strip():
                    with_email.add(site)
                    emails += 1
    except Exception:
        pass
    return done, len(with_email), emails


class CsvSink:
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


def write_progress(path, counters, running=True, finished=False):
    if not path:
        return
    try:
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({
                "total": counters["total"],
                "done": counters["done"],
                "with_email": counters["with_email"],
                "emails": counters["emails"],
                "running": running,
                "finished": finished,
            }, f)
        os.replace(tmp, path)
    except Exception:
        pass


async def worker(queue, scraper, session, sink, lock, counters, loop):
    while True:
        site = await queue.get()
        if site is None:
            queue.task_done()
            return
        try:
            site, emails, status = await asyncio.wait_for(
                scraper.scrape_site(session, site, loop),
                timeout=scraper.args.site_timeout)
        except asyncio.TimeoutError:
            site, emails, status = site, set(), "timeout"
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
            if counters["done"] % 25 == 0:
                sink.flush()
                print(f"  ...{counters['done']}/{counters['total']} siti | "
                      f"{counters['with_email']} con email | "
                      f"{counters['emails']} email totali", file=sys.stderr)
                write_progress(counters.get("progress_file"), counters)
        queue.task_done()


async def run(args):
    sites = read_sites(args.input, args.column)
    if not sites:
        print("Nessun sito trovato nel file di input.", file=sys.stderr)
        return 1

    done, done_with_email, done_emails = load_done(args.output)
    todo = [s for s in sites if s.strip().lower() not in done]
    print(f"Siti totali: {len(sites)} | gia' fatti: {len(done)} | "
          f"da processare: {len(todo)}", file=sys.stderr)
    if args.render:
        print("Render JavaScript: ATTIVO (fallback sui siti senza email)", file=sys.stderr)
    if args.ocr:
        print(f"OCR immagini: ATTIVO ({'tutte' if args.ocr_all else 'fallback'})",
              file=sys.stderr)
    if not todo:
        print("Tutti i siti sono gia' stati processati.", file=sys.stderr)
        return 0

    new_file = not os.path.exists(args.output) or os.path.getsize(args.output) == 0
    out_f = open(args.output, "a", newline="", encoding="utf-8")
    sink = CsvSink(out_f)
    if new_file:
        sink.writerow(["sito", "email", "stato"])

    # conteggi cumulativi: includono cio' che era gia' stato fatto (ripresa)
    counters = {"total": len(sites), "done": len(done),
                "with_email": done_with_email, "emails": done_emails,
                "progress_file": args.progress_file}
    write_progress(args.progress_file, counters, running=True)
    lock = asyncio.Lock()
    queue = asyncio.Queue()
    for s in todo:
        queue.put_nowait(s)

    scraper = Scraper(args)
    loop = asyncio.get_event_loop()
    connector = aiohttp.TCPConnector(
        limit=args.concurrency, ttl_dns_cache=300,
        force_close=True, enable_cleanup_closed=True,
    )
    async with aiohttp.ClientSession(headers=HEADERS, connector=connector) as session:
        workers = [
            asyncio.create_task(
                worker(queue, scraper, session, sink, lock, counters, loop))
            for _ in range(args.concurrency)
        ]
        await queue.join()
        for _ in workers:
            queue.put_nowait(None)
        await asyncio.gather(*workers, return_exceptions=True)

    await scraper.close()
    out_f.flush()
    out_f.close()
    write_progress(args.progress_file, counters, running=False, finished=True)
    print(f"\nFatto. {counters['done']} siti processati | "
          f"{counters['with_email']} con almeno un'email | "
          f"{counters['emails']} email totali.\n"
          f"Risultato in: {args.output}", file=sys.stderr)
    return 0


def main():
    p = argparse.ArgumentParser(description="Estrae email da una lista di siti (versione potente).")
    p.add_argument("--input", "-i", default="siti.csv")
    p.add_argument("--output", "-o", default="emails.csv")
    p.add_argument("--column", "-c", default=None,
                   help="nome o indice colonna con i siti (default: auto)")
    p.add_argument("--concurrency", type=int, default=30,
                   help="richieste statiche in parallelo (default: 30)")
    p.add_argument("--timeout", type=int, default=15,
                   help="timeout per pagina in secondi (default: 15)")
    p.add_argument("--max-pages", type=int, default=8,
                   help="pagine massime per sito (default: 8)")
    p.add_argument("--progress-file", default=None,
                   help="scrive l'avanzamento in un file JSON (per la dashboard)")
    p.add_argument("--site-timeout", type=int, default=90,
                   help="tempo massimo per singolo sito in secondi (default: 90)")
    # render
    p.add_argument("--render", action="store_true",
                   help="attiva il rendering JavaScript (browser headless)")
    p.add_argument("--render-concurrency", type=int, default=6,
                   help="browser/pagine in parallelo per il render (default: 6)")
    # ocr
    p.add_argument("--ocr", action="store_true",
                   help="attiva l'OCR sulle immagini")
    p.add_argument("--ocr-all", action="store_true",
                   help="esegui OCR su tutti i siti, non solo quelli senza email")
    p.add_argument("--ocr-max-images", type=int, default=6,
                   help="immagini massime per sito su cui fare OCR (default: 6)")
    p.add_argument("--ocr-workers", type=int, default=4,
                   help="processi OCR in parallelo (default: 4)")
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
