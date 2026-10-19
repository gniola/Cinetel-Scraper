#!/usr/bin/env python3
"""
Numero di schermi per film, da ComingSoon (https://www.comingsoon.it/cinema/boxoffice/).

Cinetel non pubblica gli schermi nella homepage, ComingSoon sì: la sua
classifica è WEEKEND (es. "dal 8 al 11 ottobre 2026", cioè giovedì-domenica,
la stessa finestra del nostro report) e per ogni film riporta
"Settimane", "Distribuzione", "Inc. weekend", "Schermi" e "Inc. totale".

Cosa fa questo modulo:
  - scarica la pagina (HTTP semplice, niente browser) e la converte in testo;
  - estrae le righe usando le ETICHETTE ("Settimane:", "Schermi:" ...) e non
    le classi CSS, che possono cambiare;
  - salva tutto in data/comingsoon_schermi.csv, una riga per film per
    weekend (si aggiorna se ComingSoon corregge i numeri nei giorni dopo);
  - espone match_schermi() che abbina i film del nostro report (titoli
    Cinetel, in maiuscolo) a quelli di ComingSoon.

Se la pagina non si legge o cambia struttura, NON blocca nulla: il report
mostra semplicemente "n.d." negli schermi.

Uso da riga di comando (lo fa il workflow giornaliero):
    python scripts/scrape_schermi.py
"""

import csv
import difflib
import re
import sys
import unicodedata
import urllib.request
from datetime import date, datetime, timezone
from html.parser import HTMLParser
from pathlib import Path

URL = "https://www.comingsoon.it/cinema/boxoffice/"
ROOT = Path(__file__).resolve().parent.parent
CSV_PATH = ROOT / "data" / "comingsoon_schermi.csv"

FIELDS = [
    "weekend_start",
    "weekend_end",
    "titolo_cs",
    "distribuzione",
    "incasso_weekend_eur",
    "schermi",
    "incasso_totale_eur",
    "scraped_at_utc",
]

MESI = {
    "gennaio": 1, "febbraio": 2, "marzo": 3, "aprile": 4, "maggio": 5,
    "giugno": 6, "luglio": 7, "agosto": 8, "settembre": 9, "ottobre": 10,
    "novembre": 11, "dicembre": 12,
}


# ---------------------------------------------------------------- download

def fetch_html() -> str:
    req = urllib.request.Request(
        URL,
        headers={
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
            "Accept-Language": "it-IT,it;q=0.9",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = resp.read()
    return raw.decode("utf-8", errors="replace")


class _TextExtractor(HTMLParser):
    BLOCK = {"p", "div", "li", "tr", "td", "th", "br", "h1", "h2", "h3", "h4",
             "section", "article", "ul", "ol", "table", "span", "a", "strong", "b"}

    def __init__(self):
        super().__init__()
        self.parts = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript"):
            self._skip += 1
        elif tag in self.BLOCK:
            self.parts.append(" ")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript"):
            self._skip = max(0, self._skip - 1)
        elif tag in self.BLOCK:
            self.parts.append(" ")

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)


def html_to_flat_text(html: str) -> str:
    p = _TextExtractor()
    p.feed(html)
    text = "".join(p.parts)
    return re.sub(r"\s+", " ", text).strip()


# ----------------------------------------------------------------- parsing

def parse_euro(s):
    if s is None:
        return None
    s = s.replace("€", "").strip().replace(".", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def parse_int_it(s):
    if s is None:
        return None
    s = s.replace(".", "").strip()
    return int(s) if s.isdigit() else None


def parse_weekend_dates(flat: str):
    """'dal 8 al 11 ottobre 2026' -> (date(2026,10,8), date(2026,10,11))."""
    m = re.search(
        r"dal\s+(\d{1,2})(?:\s+([A-Za-zàè]+))?\s+al\s+(\d{1,2})\s+([A-Za-zàè]+)\s+(\d{4})",
        flat,
        re.IGNORECASE,
    )
    if not m:
        return None
    d1, mese1, d2, mese2, anno = m.groups()
    mese2_n = MESI.get(mese2.lower())
    if not mese2_n:
        return None
    anno = int(anno)
    try:
        end = date(anno, mese2_n, int(d2))
        if mese1 and MESI.get(mese1.lower()):
            m1 = MESI[mese1.lower()]
            y1 = anno - 1 if m1 > mese2_n else anno
        else:
            m1 = mese2_n
            y1 = anno
            if int(d1) > int(d2):  # es. "dal 30 al 2": il mese iniziale è il precedente
                m1 = mese2_n - 1 or 12
                y1 = anno if mese2_n > 1 else anno - 1
        start = date(y1, m1, int(d1))
    except ValueError:
        return None
    return start, end


def _dedupe_title(t: str) -> str:
    """'Mammina Mammina' -> 'Mammina' (ComingSoon ripete il titolo nel link)."""
    t = t.strip()
    words = t.split()
    n = len(words)
    if n >= 2 and n % 2 == 0 and [w.lower() for w in words[: n // 2]] == [w.lower() for w in words[n // 2:]]:
        return " ".join(words[: n // 2])
    return t


TAIL = re.compile(
    r"Settimane:\s*(\d+)\s+Distribuzione:\s*(.+?)\s+"
    r"Inc\.\s*weekend:\s*(€?\s*[\d.,]+|\S+)\s+"
    r"Schermi:\s*([\d.]+|\S+)\s+"
    r"Inc\.\s*totale:\s*(€?\s*[\d.,]+|\S+)",
    re.IGNORECASE,
)


def extract_rows(flat: str):
    rows = []
    prev_end = 0
    first_tail = TAIL.search(flat)
    if first_tail:
        # il blocco prima della prima riga contiene intestazioni della pagina:
        # tengo solo l'ultimo pezzo, dove sta "1 <titolo>".
        prev_end = max(0, first_tail.start() - 160)
    for i, m in enumerate(TAIL.finditer(flat)):
        head = flat[prev_end:m.start()].strip()
        prev_end = m.end()
        if i == 0:
            cut = list(re.finditer(r"(?<!\S)1\s+", head))
            title = head[cut[-1].end():] if cut else head[-80:]
        else:
            title = re.sub(r"^\d{1,3}\s+", "", head)
        title = _dedupe_title(title)
        if not title:
            continue
        rows.append(
            {
                "titolo_cs": title,
                "distribuzione": m.group(2).strip(),
                "incasso_weekend_eur": parse_euro(m.group(3)),
                "schermi": parse_int_it(m.group(4)),
                "incasso_totale_eur": parse_euro(m.group(5)),
            }
        )
    return rows


def scrape():
    """Ritorna (weekend_start, weekend_end, righe) oppure solleva ValueError."""
    flat = html_to_flat_text(fetch_html())
    dates = parse_weekend_dates(flat)
    rows = extract_rows(flat)
    if not dates or not rows:
        raise ValueError("pagina ComingSoon non riconosciuta (date o righe non trovate)")
    # sanity: l'incasso del weekend non può superare il totale
    rows = [
        r for r in rows
        if r["schermi"] is not None
        and not (r["incasso_weekend_eur"] and r["incasso_totale_eur"]
                 and r["incasso_weekend_eur"] > r["incasso_totale_eur"])
    ]
    if not rows:
        raise ValueError("nessuna riga valida dopo i controlli")
    return dates[0], dates[1], rows


# ----------------------------------------------------------------- storage

def load_csv():
    if not CSV_PATH.exists():
        return []
    with CSV_PATH.open("r", newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def save_rows(weekend_start, weekend_end, rows):
    """Aggiunge le righe nuove o cambiate (tiene lo storico delle correzioni)."""
    CSV_PATH.parent.mkdir(parents=True, exist_ok=True)
    existing = load_csv()
    latest = {}
    for r in existing:
        latest[(r["weekend_end"], r["titolo_cs"])] = r  # l'ultima in file vince
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    new_rows = []
    for r in rows:
        key = (weekend_end.isoformat(), r["titolo_cs"])
        old = latest.get(key)
        if old and str(old["schermi"]) == str(r["schermi"]) and \
                str(old["incasso_weekend_eur"]) == str(r["incasso_weekend_eur"]):
            continue
        new_rows.append(
            {
                "weekend_start": weekend_start.isoformat(),
                "weekend_end": weekend_end.isoformat(),
                "titolo_cs": r["titolo_cs"],
                "distribuzione": r["distribuzione"],
                "incasso_weekend_eur": r["incasso_weekend_eur"],
                "schermi": r["schermi"],
                "incasso_totale_eur": r["incasso_totale_eur"],
                "scraped_at_utc": now,
            }
        )
    write_header = not CSV_PATH.exists()
    with CSV_PATH.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if write_header:
            w.writeheader()
        w.writerows(new_rows)
    return len(new_rows)


def rows_for_weekend(weekend_end: date, stored_rows, live=None):
    """Righe ComingSoon per il weekend che finisce a weekend_end.
    'live' = (start, end, rows) appena scaricato: se coincide col weekend
    richiesto ha la precedenza sul salvato."""
    out = {}
    for r in stored_rows:
        if r["weekend_end"] == weekend_end.isoformat():
            out[r["titolo_cs"]] = {
                "titolo_cs": r["titolo_cs"],
                "distribuzione": r["distribuzione"],
                "incasso_weekend_eur": float(r["incasso_weekend_eur"]) if r["incasso_weekend_eur"] else None,
                "schermi": int(r["schermi"]) if r["schermi"] else None,
            }
    if live and live[1] == weekend_end:
        for r in live[2]:
            out[r["titolo_cs"]] = r
    return list(out.values())


# ---------------------------------------------------------------- matching

def norm_title(t: str) -> str:
    t = unicodedata.normalize("NFKD", t)
    t = "".join(c for c in t if not unicodedata.combining(c)).upper()
    t = re.sub(r"\(.*?\)", " ", t)          # '(MOANA)' ecc.
    t = re.sub(r"[^A-Z0-9 ]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def _tokens(s):
    return {w for w in norm_title(s).split() if len(w) > 2}


def match_schermi(titolo_cinetel, distribuzione, incasso_weekend, cs_rows):
    """Trova la riga ComingSoon del film Cinetel, oppure None.
    1) titolo normalizzato uguale / contenuto / molto simile;
    2) in alternativa: stesso incasso weekend (±3%) e distributore compatibile."""
    nt = norm_title(titolo_cinetel)
    best, best_score = None, 0.0
    for r in cs_rows:
        nc = norm_title(r["titolo_cs"])
        if not nc or not nt:
            continue
        if nc == nt:
            score = 1.0
        elif nc in nt or nt in nc:
            score = 0.9
        else:
            score = difflib.SequenceMatcher(None, nt, nc).ratio()
        if score > best_score:
            best, best_score = r, score
    if best and best_score >= 0.82:
        return best
    if incasso_weekend:
        for r in cs_rows:
            g = r.get("incasso_weekend_eur")
            if g and abs(g - incasso_weekend) / incasso_weekend <= 0.03 \
                    and _tokens(distribuzione or "") & _tokens(r.get("distribuzione") or ""):
                return r
    return None


# -------------------------------------------------------------------- main

def main():
    try:
        start, end, rows = scrape()
    except Exception as e:  # non deve mai rompere lo scrape giornaliero
        print(f"ATTENZIONE: schermi ComingSoon non salvati: {e}", file=sys.stderr)
        return 0
    added = save_rows(start, end, rows)
    print(f"ComingSoon: weekend {start} – {end}, {len(rows)} film, {added} righe nuove/aggiornate.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
