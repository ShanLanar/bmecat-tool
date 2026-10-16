"""Crawlt die NK_-Kategorieseiten von www.officexl.de parallel und gibt den Baum aus.

Aufruf:  python tools/officexl_tree.py [baum.txt]   (schreibt zusaetzlich baum.csv mit Elternseite/Pfad)
Regeln:  NK_-Links werden geladen und rekursiv verfolgt; Links mit "CategoryPath"
         sind Blaetter (werden gelistet, nicht geladen). Erste Entdeckung (BFS) gewinnt,
         so landen Navigationslinks, die auf jeder Seite stehen, nicht als Kinder.
"""
import logging
import re
import sys
import urllib.request
from collections import Counter, deque
from concurrent.futures import ThreadPoolExecutor
from html.parser import HTMLParser

BASE = "https://www.officexl.de/"
ROOTS = ["NK_Buerobedarf", "NK_Papier", "search?filterCategoryPathROOT=Tinte+%26+Toner&keyword=*&sort=_",
         "NK_Schreibwaren", "NK_Ordnen", "NK_Versand",
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
    """Relative ('../../NK_Papier') und absolute (https://officexl.de/NK_Papier) Links -> BASE + Pfad."""
    h = href.replace("&amp;", "&").strip()
    h = re.sub(r"^https?://(www\.)?officexl\.de/*", "", h)
    return BASE + re.sub(r"^(\.{1,2}/)+", "", h).lstrip("/")


def extract(html):
    """Liefert [(url, text)] fuer NK_- und CategoryPath-Links."""
    p = _Links()
    p.feed(html)
    return [(normalize(h), t) for h, t in p.links if "NK_" in h or "CategoryPath" in h]


def fetch(url):
    try:
        with urllib.request.urlopen(url, timeout=30) as r:
            return r.read().decode("utf-8", "replace")
    except Exception as e:  # eine kaputte Seite soll den Lauf nicht abbrechen
        log.error("Fehler %s: %s", url, e)
        return ""


def crawl():
    """Runde 1: Wurzelseiten laden; Links, die auf > der Haelfte davon stehen, sind Navigation
    (Mega-Menue) und werden nie als Kind gewertet. Danach BFS; erste Entdeckung gewinnt."""
    children, names = {}, {}
    roots = [BASE + r for r in ROOTS if "CategoryPath" not in r]
    with ThreadPoolExecutor(WORKERS) as ex:
        pages = dict(zip(roots, ex.map(fetch, roots)))
        links = {u: extract(h) for u, h in pages.items()}
        count = Counter(l for ls in links.values() for l in {x[0] for x in ls})
        nav = {u for u, c in count.items() if c > len(roots) / 2}
        for ls in links.values():  # Anzeigenamen der Wurzeln stehen im Menue
            for u, t in ls:
                if u in roots and t:
                    names.setdefault(u, t)
        seen = set(roots) | nav
        queue = deque()
        for u in roots:
            queue.append((u, links[u]))
        while queue:
            batch = [queue.popleft() for _ in range(len(queue))]
            nxt = []
            for url, ls in batch:
                kids = []
                for u, t in ls:
                    if u in seen:
                        continue
                    seen.add(u)
                    names[u] = t
                    kids.append(u)
                    if "CategoryPath" not in u:
                        nxt.append(u)
                children[url] = kids
                log.info("%s: %d Unterseiten", url, len(kids))
            for u, h in zip(nxt, ex.map(fetch, nxt)):
                queue.append((u, extract(h)))
    return children, names


def _roots():
    return [BASE + r for r in ROOTS]


def render(children, names):
    lines = []

    def walk(u, depth, parent):
        n = names.get(u) or u[len(BASE):]
        lines.append("  " * depth + f"{n}  <- {parent}  <{u}>" if parent else f"{n}  <{u}>")
        for k in children.get(u, []):
            walk(k, depth + 1, n)

    for r in _roots():
        walk(r, 0, "")
    return "\n".join(lines)


def write_csv(path, children, names):
    """Eine Zeile je Seite mit Elternseite und Pfad (Breadcrumb) -> filterbar in Excel."""
    import csv
    rows = []

    def walk(u, trail):
        t = trail + [names.get(u) or u[len(BASE):]]
        rows.append([len(t) - 1, " > ".join(t), names.get(u, ""), u, trail and t[-2] or "",
                     "Blatt" if "CategoryPath" in u else "Kategorie"])
        for k in children.get(u, []):
            walk(k, t)

    for r in _roots():
        walk(r, [])
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["Ebene", "Pfad", "Name", "URL", "Elternseite", "Typ"])
        w.writerows(rows)


def _selftest():
    html = ('<a title="x" href="../../NK_Papier"><img/> <span>Papier</span></a>'
            '<a href="../../search?filterCategoryPathROOT=Tinte+%26+Toner&amp;keyword=*">T</a>'
            '<a href="/impressum">x</a>')
    assert normalize("https://officexl.de/NK_Papier") == BASE + "NK_Papier"
    assert normalize("https://www.officexl.de/NK_Papier") == BASE + "NK_Papier"
    assert extract(html) == [
        (BASE + "NK_Papier", "Papier"),
        (BASE + "search?filterCategoryPathROOT=Tinte+%26+Toner&keyword=*", "T")]


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    _selftest()
    data = crawl()
    tree = render(*data)
    if len(sys.argv) > 1:
        open(sys.argv[1], "w", encoding="utf-8").write(tree)
        write_csv(sys.argv[1].rsplit(".", 1)[0] + ".csv", *data)
    print(tree)
