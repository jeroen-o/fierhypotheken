#!/usr/bin/env python3
"""Ververst de nieuwsitems per geldverstrekker in index.html uit hun openbare nieuwspagina's.

Bronnen: Obvion, NN, Florius, NIBC en Jens. Per bron worden de nieuwste berichten
(titel, datum, link) gelezen, gecontroleerd en in het blok "Actueel voor adviseurs"
gezet. Het tabblad "Nieuws verstrekkers" en de "Nieuw"-labels lezen dat blok.

Veiligheid:
  - Verandert de opbouw van een nieuwspagina (0 berichten gevonden), dan blijft het
    oude blok van die verstrekker staan en wordt de bron als mislukt gemeld.
  - Alleen https-links naar het eigen domein van de verstrekker.
  - Titels met een procent- of eurobedrag worden overgeslagen (geen cijfers van rentes
    en tarieven op de site).
  - Alleen berichten van de laatste 180 dagen, maximaal 3 per verstrekker.

Gebruik: python3 scripts/nieuws_update.py [index.html] [rapport.md] [--write]
Zonder --write wordt alleen gerapporteerd. Exitcode 0 = alles goed, 2 = minstens één bron mislukt.
Omgevingsvariabele NIEUWS_VANDAAG=YYYY-MM-DD overschrijft de datum van vandaag (voor tests).
"""
import html, os, re, subprocess, sys
from datetime import date, timedelta
from urllib.parse import urljoin, urlparse

args = [a for a in sys.argv[1:] if not a.startswith("--")]
WRITE = "--write" in sys.argv
src = args[0] if args else "index.html"
out = args[1] if len(args) > 1 else "nieuws-rapport.md"
VANDAAG = date.fromisoformat(os.environ.get("NIEUWS_VANDAAG", date.today().isoformat()))
VENSTER = 180
MAX_ITEMS = 3
MND = ["januari", "februari", "maart", "april", "mei", "juni", "juli", "augustus", "september", "oktober", "november", "december"]
KORT = {"jan": 1, "feb": 2, "mrt": 3, "apr": 4, "mei": 5, "jun": 6, "jul": 7, "aug": 8, "sep": 9, "okt": 10, "nov": 11, "dec": 12}


def get(url):
    r = subprocess.run(["curl", "-sS", "-m", "30", "-L", "--max-redirs", "5", "-A",
                        "Mozilla/5.0 (compatible; fierhypotheken-nieuws)", "-w", "\n%{http_code}", url],
                       capture_output=True, text=True, timeout=60)
    body, _, code = r.stdout.rpartition("\n")
    if not code.strip().startswith("2"):
        raise RuntimeError(f"HTTP {code.strip() or '000'} bij {url}")
    return body


def schoon(t):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", t))).strip()


def nl_datum(t):
    """'3 november 2026' of '03 nov. 2026, 09:00 CET' -> date"""
    m = re.search(r"(\d{1,2})\s+([a-z]+)\.?\s+(20\d\d)", t.lower())
    if not m:
        raise ValueError(f"geen datum in {t[:40]!r}")
    d, mnd, j = int(m.group(1)), m.group(2), int(m.group(3))
    n = MND.index(mnd) + 1 if mnd in MND else KORT[mnd[:3]]
    return date(j, n, d)


def p_obvion(base):
    t = get(base)
    res = []
    for li in re.findall(r'<li class="news-archive__item">(.*?)</li>', t, re.S):
        d = re.search(r'news-archive__item__date">\s*(20\d\d-\d\d-\d\d)', li)
        a = re.search(r'<a href="([^"]+)"[^>]*news-archive__item__link[^>]*>(.*?)</a>', li, re.S)
        if d and a:
            res.append((date.fromisoformat(d.group(1)), schoon(a.group(2)), urljoin(base, a.group(1))))
    return res


def p_nibc(base):
    t = get(base)
    res = {}
    for m in re.finditer(r'<a class="c-card-image[^"]*"\s+href="([^"]+)"(.*?)</a>', t, re.S):
        href, inner = m.group(1), m.group(2)
        d = re.search(r'c-card-image__date">([^<]+)<', inner)
        ti = re.search(r'<h3 class="c-card-image__title[^"]*">(.*?)</h3>', inner, re.S)
        if d and ti:
            res[urljoin(base, href)] = (nl_datum(d.group(1)), schoon(ti.group(1)), urljoin(base, href))
    return list(res.values())


NN_ONDERWERP = re.compile(r"hypothe|starterslening|\bnhg\b|woningfinanc|aflossingsvrij|restschuld", re.I)


def p_nn(base):
    """Het NN-adviseursnieuws gaat ook over pensioen en verzekeringen: alleen hypotheekonderwerpen houden."""
    res = []
    for pg in (1, 2, 3):
        try:
            t = get(f"{base}?page={pg}")
        except RuntimeError:
            if pg == 1:
                raise
            break
        for m in re.finditer(r'<article[^>]*>\s*<a href="(/nieuws/[^"]+)"(.*?)</article>', t, re.S):
            d = re.search(r"<time[^>]*>([^<]+)</time>", m.group(2))
            ti = re.search(r"<h3[^>]*>(.*?)</h3>", m.group(2), re.S)
            if d and ti and NN_ONDERWERP.search(schoon(ti.group(1))):
                res.append((nl_datum(d.group(1)), schoon(ti.group(1)), urljoin(base, m.group(1))))
    return res


def p_florius(base):
    t = get(base)
    links = []
    for h in re.findall(r'<li><a href="(/adviseurs/nieuws/[^"]+)">', t):
        u = urljoin(base, h)
        if u not in links:
            links.append(u)
    res = []
    for u in links[:6]:
        a = get(u)
        m = re.search(r'<hero-inleiding[^>]*titel="([^"]+)"[^>]*tekst="([^"]+)"', a)
        if m:
            res.append((nl_datum(schoon(m.group(2))), schoon(m.group(1)), u))
    return res


def p_jens(base):
    t = get(base)
    links = []
    for h in re.findall(r'<a[^>]+href="(https://jens\.nl/[^"]+)"[^>]*>\s*<span[^>]*>\s*<span[^>]*>\s*Bekijk artikel', t):
        if h not in links:
            links.append(h)
    res = []
    for u in links[:6]:
        a = get(u)
        d = re.search(r'article:published_time"\s+content="(20\d\d-\d\d-\d\d)', a)
        h1 = re.search(r"<h1[^>]*>(.*?)</h1>", a, re.S)
        if d and h1:
            res.append((date.fromisoformat(d.group(1)), schoon(h1.group(1)), u))
    return res


BRONNEN = [
    ("obvion", "Obvion", "https://obvion.nl/adviseur/nieuws/", p_obvion, "obvion.nl"),
    ("nationale-nederlanden", "Nationale-Nederlanden", "https://adviseur.nn.nl/nieuws", p_nn, "nn.nl"),
    ("florius", "Florius", "https://www.florius.nl/adviseurs/nieuws", p_florius, "florius.nl"),
    ("nibc", "NIBC", "https://nibc.nl/intermediair/nieuwsberichten", p_nibc, "nibc.nl"),
    ("jens", "Jens", "https://jens.nl/blog/", p_jens, "jens.nl"),
]

e = lambda t: html.escape(t, quote=True)
tekst = open(src, encoding="utf-8").read()
orig = tekst
rapport, fouten, gewijzigd = [], [], []


def vorm(items):
    h = '      <div class="act-news"><h4>Recent op de site van de verstrekker</h4><ul>\n'
    for d, ti, u in items:
        h += '        <li><time datetime="%s">%s</time><a href="%s" target="_blank" rel="noopener">%s</a></li>\n' % (
            d.isoformat(), f"{d.day} {MND[d.month - 1]} {d.year}", e(u), e(ti))
    return h + "      </ul></div>\n"


for slug, naam, url, parser, domein in BRONNEN:
    try:
        kand = parser(url)
        if not kand:
            raise RuntimeError("0 berichten gevonden: de opbouw van de pagina is waarschijnlijk veranderd")
        keuze, genegeerd = [], []
        for d, ti, u in sorted(set(kand), key=lambda x: x[0], reverse=True):
            host = urlparse(u).hostname or ""
            if urlparse(u).scheme != "https" or not (host == domein or host.endswith("." + domein)):
                genegeerd.append(f"{ti[:40]} (link buiten {domein})"); continue
            if re.search(r"%|€", ti):
                genegeerd.append(f"{ti[:40]} (bedrag/percentage in titel)"); continue
            if d > VANDAAG + timedelta(days=1) or d < VANDAAG - timedelta(days=VENSTER):
                continue
            if len(ti) > 160 or not ti:
                genegeerd.append(f"{ti[:40]} (titellengte)"); continue
            keuze.append((d, ti, u))
            if len(keuze) == MAX_ITEMS:
                break
        m = re.search(r'(<div class="act" id="act-%s">)(.*?)(\n    </div>\n)' % re.escape(slug), tekst, re.S)
        if not m:
            raise RuntimeError(f"blok act-{slug} niet gevonden in {src}")
        blok = m.group(2)
        blok_nieuw = re.sub(r'\n      <div class="act-news">.*?</ul></div>', "", blok, flags=re.S)
        if keuze:
            ins = vorm(keuze).rstrip("\n")
            sub = re.search(r'\n      <p class="act-sub">.*?</p>', blok_nieuw, re.S)
            if sub:
                blok_nieuw = blok_nieuw[:sub.end()] + "\n" + ins + blok_nieuw[sub.end():]
            else:
                blok_nieuw = blok_nieuw.replace('\n      <div class="act-grid">', "\n" + ins + '\n      <div class="act-grid">', 1)
        if blok_nieuw != blok:
            gewijzigd.append(slug)
            tekst = tekst[:m.start(2)] + blok_nieuw + tekst[m.end(2):]
        rapport.append(f"- **{naam}**: {len(kand)} berichten gelezen, {len(keuze)} getoond"
                       + (" (gewijzigd)" if slug in gewijzigd else " (ongewijzigd)")
                       + ("".join(f"\n  - {d.isoformat()} {ti}" for d, ti, u in keuze))
                       + ("".join(f"\n  - overgeslagen: {g}" for g in genegeerd)))
    except Exception as ex:
        fouten.append(f"{naam}: {ex}")
        rapport.append(f"- **{naam}**: MISLUKT, oud blok blijft staan. {ex}")

if gewijzigd:
    dat = f"{VANDAAG.day} {MND[VANDAAG.month - 1]} {VANDAAG.year}"
    tekst, n = re.subn(r'(<span id="nw-bijgewerkt">)[^<]*(</span>)', r"\g<1>" + dat + r"\g<2>", tekst)
    if n == 0:
        fouten.append("marker nw-bijgewerkt niet gevonden in index.html")

if WRITE and tekst != orig:
    open(src, "w", encoding="utf-8").write(tekst)

tekst_rapport = f"# Nieuwscontrole {VANDAAG.isoformat()}\n\n" + "\n".join(rapport) + "\n"
if fouten:
    tekst_rapport += "\n## Mislukte bronnen\n" + "\n".join(f"- {f}" for f in fouten) + "\nHet bestaande nieuws van die verstrekkers is niet aangepast. Controleer de pagina en pas `scripts/nieuws_update.py` aan.\n"
open(out, "w", encoding="utf-8").write(tekst_rapport)
print(tekst_rapport)
print("GEWIJZIGD:", ",".join(gewijzigd) or "geen")
sys.exit(2 if fouten else 0)
