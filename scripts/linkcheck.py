#!/usr/bin/env python3
"""Controleert alle externe links in index.html en schrijft een rapport.

Uitkomst per link:
  ok       eindstatus 2xx (na redirects)
  geblokkeerd  401/403/429/999: de site weigert robots; geen oordeel, handmatig kijken
  dood     404/410, 5xx, DNS-/SSL-fout of timeout (na twee pogingen)

Gebruik: python3 scripts/linkcheck.py [index.html] [rapport.md]
Exitcode 1 als er dode links zijn.
"""
import html, json, re, subprocess, sys
from concurrent.futures import ThreadPoolExecutor
from datetime import date

src = sys.argv[1] if len(sys.argv) > 1 else "index.html"
out = sys.argv[2] if len(sys.argv) > 2 else "linkcheck-rapport.md"
text = open(src, encoding="utf-8").read()

# link -> waar hij staat (verstrekker of tabblad)
where = {}
for m in re.finditer(r'<section class="lender-detail" id="d-([a-z0-9-]+)".*?</section>', text, re.S):
    for u in re.findall(r'href="(https?://[^"]+)"', m.group(0)):
        where.setdefault(html.unescape(u), set()).add(m.group(1))
for u in re.findall(r'href="(https?://[^"]+)"', text):
    where.setdefault(html.unescape(u), set())
for u, w in where.items():
    if not w:
        w.add("overig (tabbladen)")
urls = sorted(where)


def check(u):
    last = "000"
    for _ in range(2):
        try:
            r = subprocess.run(
                ["curl", "-sS", "-m", "25", "-L", "--max-redirs", "8", "-A",
                 "Mozilla/5.0 (compatible; fierhypotheken-linkcheck)", "-o", "/dev/null",
                 "-w", "%{http_code}", u],
                capture_output=True, text=True, timeout=40)
            last = (r.stdout or "000").strip()[-3:]
        except Exception:
            last = "000"
        if last.startswith("2"):
            return u, last
    return u, last


with ThreadPoolExecutor(max_workers=10) as ex:
    res = list(ex.map(check, urls))

ok, geblokkeerd, dood = [], [], []
for u, c in res:
    if c.startswith("2"):
        ok.append(u)
    elif c in ("401", "403", "429", "999"):
        geblokkeerd.append((u, c))
    else:
        dood.append((u, c))


def lines(items):
    return "\n".join(f"- `{c}` {u}  \n  op: {', '.join(sorted(where[u]))}" for u, c in items)


rapport = f"""# Linkcontrole {date.today().isoformat()}

Gecontroleerd: **{len(urls)}** externe links in `{src}`.
Werkend: {len(ok)} · Dood: **{len(dood)}** · Geblokkeerd voor robots (geen oordeel): {len(geblokkeerd)}

## Dode links ({len(dood)})
{lines(dood) if dood else "Geen."}

## Geblokkeerd voor robots ({len(geblokkeerd)})
Deze sites weigeren geautomatiseerd bezoek (403/429). Open ze af en toe handmatig.
{lines(geblokkeerd) if geblokkeerd else "Geen."}

`000` = geen verbinding (DNS-fout, SSL-fout of timeout).
Alleen of een pagina bestaat is gecontroleerd, niet of de inhoud nog actueel is. Controleer ook de datum bij "Gecontroleerd op" in het blok "Actueel voor adviseurs".
"""
open(out, "w", encoding="utf-8").write(rapport)
print(rapport)
sys.exit(1 if dood else 0)
