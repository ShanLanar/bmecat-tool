"""Crawlt die NK_-Kategorieseiten von www.officexl.de parallel und gibt den Baum aus.

Aufruf:  python tools/officexl_tree.py [ausgabe.txt]
Regeln:  NK_-Links werden geladen und rekursiv verfolgt; Links mit "CategoryPath"
         sind Blaetter (werden gelistet, nicht geladen). Erste Entdeckung (BFS) gewinnt,
         so landen Navigationslinks, die auf jeder Seite stehen, nicht als Kinder.
"""
import logging
import re
import sys
import urllib.request
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from html.parser import HTMLParser

BASE = "https://www.officexl.de/"
ROOTS = ["NK_Buerobedarf", "NK_Papier", "NK_Schreibwaren", "NK_Ordnen", "NK_Versand",
         "NK_Praesentation", "NK_SchuleundStudium", "NK_Technik", "NK_Hygiene", "NK_Drogerie",
         "NK_HaushaltUCatering", "NK_Lebensmittel", "NK_HausUHandwerk",
         "NK_WerkzeugeUWerkstatt", "NK_Arbeitsschutz", "NK_Bueroeinrichtung", "NK_Freizeit"]
WORKERS = 16
log = logging.getLogger("officexl")


class _Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links, self._href, self._text = [], None, []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self._href, self._text = dict(attrs).get("href"), []

    def handle_data(self, data):
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self._href is not None:
            self.links.append((self._href, " ".join("".join(self._text).split())))
            self._href = None


def normalize(href):
    """'../../NK_Papier' -> BASE + 'NK_Papier' (relative Tiefe der Seite ist egal)."""
    return BASE + re.sub(r"^(\.{1,2}/)+", "", href.replace("&amp;", "&"))


def extract(html):
    """Liefert [(url, text)] fuer NK_- und CategoryPath-Links."""
    p = _Links()
    p.feed(html)
    out = [(normalize(h), t) for h, t in p.links if "NK_" in h or "CategoryPath" in h]
    return out


def fetch(url):
    try:
        with urllib.request.urlopen(url, timeout=30) as r:
            return r.read().decode("utf-8", "replace")
    except Exception as e:  # eine kaputte Seite soll den Lauf nicht abbrechen
        log.error("Fehler %s: %s", url, e)
        return ""


def crawl():
    children, names = {}, {}
    seen = {BASE + r for r in ROOTS}
    queue = deque(sorted(seen, key=lambda u: ROOTS.index(u[len(BASE):])))
    with ThreadPoolExecutor(WORKERS) as ex:
        while queue:
            batch = [queue.popleft() for _ in range(len(queue))]
            for url, html in zip(batch, ex.map(fetch, batch)):
                kids = []
                for u, t in extract(html):
                    if u in seen:
                        continue
                    seen.add(u)
                    names[u] = t
                    kids.append(u)
                    if "CategoryPath" not in u:
                        queue.append(u)
                children[url] = kids
                log.info("%s: %d neue Links", url, len(kids))
    return children, names


def render(children, names):
    lines = []

    def walk(u, depth):
        lines.append("  " * depth + f"{names.get(u) or u[len(BASE):]}  <{u}>")
        for k in children.get(u, []):
            walk(k, depth + 1)

    for r in ROOTS:
        walk(BASE + r, 0)
    return "\n".join(lines)


def _selftest():
    html = ('<a title="x" href="../../NK_Papier"><img/> <span>Papier</span></a>'
            '<a href="../../search?filterCategoryPathROOT=Tinte+%26+Toner&amp;keyword=*">T</a>'
            '<a href="/impressum">x</a>')
    assert extract(html) == [
        (BASE + "NK_Papier", "Papier"),
        (BASE + "search?filterCategoryPathROOT=Tinte+%26+Toner&keyword=*", "T")]


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    _selftest()
    tree = render(*crawl())
    if len(sys.argv) > 1:
        open(sys.argv[1], "w", encoding="utf-8").write(tree)
    print(tree)
