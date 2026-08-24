#!/usr/bin/env python3
"""
Pulizia una tantum di data/cinetel_boxoffice.csv: rimuove le righe con
posizione oltre la 10 (rimaste da run precedenti all'introduzione del
filtro TOP_N in scrape_cinetel.py). Da lanciare una sola volta, poi non
serve più: gli scrape successivi salvano già solo la top ten.
"""

import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CSV_PATH = ROOT / "data" / "cinetel_boxoffice.csv"
TOP_N = 10


def main():
    if not CSV_PATH.exists():
        print("Nessun file CSV trovato, niente da pulire.")
        return

    with CSV_PATH.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        rows = list(reader)

    kept = [r for r in rows if int(r["pos"]) <= TOP_N]
    removed = len(rows) - len(kept)

    with CSV_PATH.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(kept)

    print(f"Righe totali prima: {len(rows)}")
    print(f"Righe rimosse (pos > {TOP_N}): {removed}")
    print(f"Righe rimaste: {len(kept)}")


if __name__ == "__main__":
    sys.exit(main())
