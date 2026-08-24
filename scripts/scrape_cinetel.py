#!/usr/bin/env python3
"""
Cinetel Box Office daily scraper.

Scarica la pagina pubblica https://cinetel.it/homepage (box office giornaliero
del mercato cinematografico italiano), estrae la classifica e salva SOLO i
primi TOP_N film (di default 10, la "top ten") — gli eventuali film oltre la
decima posizione vengono scartati:

  - data/raw/<data-riferimento>.json   -> snapshot grezzo del giorno
  - data/cinetel_boxoffice.csv         -> storico cumulativo (append, senza duplicati)

Il sito è una single-page app che renderizza i dati via JavaScript, quindi
uso Playwright (browser headless reale) invece di una semplice richiesta HTTP.

La tabella reale (verificata su una run effettiva) ha, per ogni film, queste
colonne in quest'ordine: Pos., Titolo, Prima Programmazione, Nazione,
Distribuzione, Incasso (del giorno), Presenze (del giorno), Incasso al
<data> (cumulato dall'uscita in sala), Presenze al <data> (cumulato).
L'estrazione legge il testo della pagina riga per riga e riconosce un nuovo
film quando trova: numero di posizione, poi titolo, poi una data
gg/mm/aaaa (prima programmazione), poi un codice nazione in maiuscolo, ecc.
Questo è più robusto delle classi CSS (che framework come Angular possono
rigenerare) perché si basa sul formato e sull'ordine dei dati, che Cinetel
mantiene stabile.
"""

import csv
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import sync_playwright

URL = "https://cinetel.it/homepage"
TOP_N = 10  # teniamo solo i primi 10 film in classifica (top ten), non l'intera lista
ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw"
CSV_PATH = ROOT / "data" / "cinetel_boxoffice.csv"

FIELDS = [
    "data_riferimento",
    "pos",
    "titolo",
    "prima_programmazione",
    "nazione",
    "distribuzione",
    "incasso_eur",
    "presenze",
    "incasso_totale_eur",
    "presenze_totale",
    "scraped_at_utc",
]


def parse_euro(value: str) -> float:
    """'€ 885.276' (formato italiano, punto = migliaia) -> 885276.0"""
    cleaned = value.replace("€", "").strip()
    cleaned = cleaned.replace(".", "").replace(",", ".")
    try:
        return float(cleaned)
    except ValueError:
        return None


def parse_int_it(value: str):
    cleaned = value.replace(".", "").strip()
    try:
        return int(cleaned)
    except ValueError:
        return None


def extract_rows(page_text: str):
    """
    Il testo della pagina contiene una riga di intestazione seguita da
    blocchi ripetuti, uno per film, del tipo (verificato su una run reale):

        1
        OCEANIA (MOANA)
        19/08/2026
        USA
        WALT DISNEY S.M.P. ITALIA
        € 885.276
        109.188
        € 5.091.982
        650.830

    cioè: Pos., Titolo, Prima Programmazione (gg/mm/aaaa), Nazione,
    Distribuzione, Incasso del giorno, Presenze del giorno, Incasso totale
    dall'uscita, Presenze totali dall'uscita.
    """
    pattern = re.compile(
        r"^(\d+)\r?\n"                    # pos
        r"(.+?)\r?\n"                     # titolo
        r"(\d{2}/\d{2}/\d{4})\r?\n"       # prima programmazione
        r"([A-Za-z]{2,4})\r?\n"           # nazione (codice)
        r"(.+?)\r?\n"                     # distribuzione
        r"€\s*([\d.,]+)\r?\n"             # incasso del giorno
        r"([\d.,]+)\r?\n"                 # presenze del giorno
        r"€\s*([\d.,]+)\r?\n"             # incasso totale dall'uscita
        r"([\d.,]+)",                     # presenze totali dall'uscita
        re.MULTILINE,
    )
    rows = []
    for m in pattern.finditer(page_text):
        pos, titolo, prima_progr, nazione, distribuzione, incasso, presenze, incasso_tot, presenze_tot = m.groups()
        rows.append(
            {
                "pos": int(pos),
                "titolo": titolo.strip(),
                "prima_programmazione": prima_progr.strip(),
                "nazione": nazione.strip(),
                "distribuzione": distribuzione.strip(),
                "incasso_eur": parse_euro(incasso),
                "presenze": parse_int_it(presenze),
                "incasso_totale_eur": parse_euro(incasso_tot),
                "presenze_totale": parse_int_it(presenze_tot),
            }
        )
    return rows


def extract_reference_date(page_text: str):
    """Cerca 'Box Office al 23/08/2026' e ritorna '2026-08-23'."""
    m = re.search(r"Box Office al (\d{2})/(\d{2})/(\d{4})", page_text)
    if not m:
        return None
    dd, mm, yyyy = m.groups()
    return f"{yyyy}-{mm}-{dd}"


def fetch_page_text() -> str:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(URL, wait_until="networkidle", timeout=60000)
        # I dati sono caricati via JS dopo il load iniziale: aspettiamo che
        # compaia la prima riga della tabella prima di leggere il testo.
        page.wait_for_selector("text=Box Office al", timeout=30000)
        page.wait_for_timeout(2000)  # margine per il rendering completo delle righe
        text = page.inner_text("body")
        browser.close()
        return text


def append_csv(rows, reference_date, scraped_at):
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    CSV_PATH.parent.mkdir(parents=True, exist_ok=True)

    existing_keys = set()
    file_exists = CSV_PATH.exists()
    if file_exists:
        with CSV_PATH.open("r", newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                existing_keys.add((row["data_riferimento"], row["pos"]))

    with CSV_PATH.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        if not file_exists:
            writer.writeheader()
        added = 0
        for r in rows:
            key = (reference_date, str(r["pos"]))
            if key in existing_keys:
                continue  # già salvato in un run precedente, evita duplicati
            writer.writerow(
                {
                    "data_riferimento": reference_date,
                    "pos": r["pos"],
                    "titolo": r["titolo"],
                    "prima_programmazione": r["prima_programmazione"],
                    "nazione": r["nazione"],
                    "distribuzione": r["distribuzione"],
                    "incasso_eur": r["incasso_eur"],
                    "presenze": r["presenze"],
                    "incasso_totale_eur": r["incasso_totale_eur"],
                    "presenze_totale": r["presenze_totale"],
                    "scraped_at_utc": scraped_at,
                }
            )
            added += 1
    return added


def main():
    scraped_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    text = fetch_page_text()

    reference_date = extract_reference_date(text)
    rows = extract_rows(text)
    rows = [r for r in rows if r["pos"] <= TOP_N]  # solo la top ten, non la lista completa

    if not reference_date or not rows:
        print("ERRORE: non sono riuscito a trovare dati nella pagina.", file=sys.stderr)
        print("--- primi 2000 caratteri del testo estratto (debug) ---", file=sys.stderr)
        print(text[:2000], file=sys.stderr)
        sys.exit(1)

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    raw_path = RAW_DIR / f"{reference_date}.json"
    raw_path.write_text(
        json.dumps(
            {"data_riferimento": reference_date, "scraped_at_utc": scraped_at, "film": rows},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    added = append_csv(rows, reference_date, scraped_at)

    print(f"Data di riferimento: {reference_date}")
    print(f"Film trovati: {len(rows)}")
    print(f"Nuove righe aggiunte al CSV: {added}")
    print(f"Snapshot salvato in: {raw_path}")


if __name__ == "__main__":
    main()
