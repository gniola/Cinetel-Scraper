#!/usr/bin/env python3
"""
Report settimanale Cinetel via email.

Da eseguire ogni lunedì (dopo lo scrape giornaliero). Legge lo storico
accumulato in data/cinetel_boxoffice.csv, aggrega per film la settimana
appena conclusa (lunedì-domenica) e invia una email HTML con la tabella a
gabriele.niola@gmail.com.

Colonne del report:
  1. Titolo
  2. Distribuzione
  3. Incasso settimana (lun-dom)
  4. Presenze settimana (lun-dom)
  5. Incasso weekend (ven-dom)
  6. Presenze weekend (ven-dom)
  7. Incasso totale cumulato (da quando il tracker raccoglie dati — NON
     l'incasso totale dall'uscita del film, di cui non abbiamo storico)

Richiede due secret d'ambiente per l'invio SMTP via Gmail:
  GMAIL_ADDRESS       -> l'indirizzo gmail mittente (e destinatario)
  GMAIL_APP_PASSWORD  -> App Password generata su myaccount.google.com/apppasswords
"""

import csv
import os
import smtplib
import sys
from collections import defaultdict
from datetime import date, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CSV_PATH = ROOT / "data" / "cinetel_boxoffice.csv"

RECIPIENT = "gabriele.niola@gmail.com"


def it_number(n) -> str:
    """1234567.5 -> '1.234.567' (arrotondato, formato italiano)"""
    if n is None:
        return "-"
    return f"{round(n):,}".replace(",", ".")


def euro(n) -> str:
    return f"€ {it_number(n)}"


def load_rows():
    if not CSV_PATH.exists():
        return []
    with CSV_PATH.open("r", newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def previous_week_range(today: date):
    """Dato un lunedì (today), ritorna (lunedì, domenica) della settimana
    appena conclusa, cioè i 7 giorni precedenti a oggi."""
    this_monday = today - timedelta(days=today.weekday())  # weekday(): lun=0
    week_start = this_monday - timedelta(days=7)
    week_end = this_monday - timedelta(days=1)
    return week_start, week_end


def build_report(rows, week_start: date, week_end: date):
    weekend_start = week_end - timedelta(days=2)  # venerdì della stessa settimana

    per_film = defaultdict(lambda: {
        "distribuzione": "",
        "incasso_settimana": 0.0,
        "presenze_settimana": 0,
        "incasso_weekend": 0.0,
        "presenze_weekend": 0,
        "incasso_totale": 0.0,
        "giorni_settimana_trovati": set(),
    })

    for r in rows:
        try:
            d = date.fromisoformat(r["data_riferimento"])
        except ValueError:
            continue
        titolo = r["titolo"]
        incasso = float(r["incasso_eur"]) if r["incasso_eur"] not in ("", None) else 0.0
        presenze = int(r["presenze"]) if r["presenze"] not in ("", None) else 0

        entry = per_film[titolo]
        entry["distribuzione"] = r["distribuzione"] or entry["distribuzione"]

        # cumulato dall'inizio del tracking (tutte le righe disponibili)
        entry["incasso_totale"] += incasso

        if week_start <= d <= week_end:
            entry["incasso_settimana"] += incasso
            entry["presenze_settimana"] += presenze
            entry["giorni_settimana_trovati"].add(d.isoformat())
            if d >= weekend_start:
                entry["incasso_weekend"] += incasso
                entry["presenze_weekend"] += presenze

    # Teniamo solo i film che hanno almeno un giorno di dati nella settimana
    result = [
        {"titolo": titolo, **data}
        for titolo, data in per_film.items()
        if data["giorni_settimana_trovati"]
    ]
    result.sort(key=lambda x: x["incasso_settimana"], reverse=True)
    return result


def days_covered(rows, week_start: date, week_end: date):
    found = set()
    for r in rows:
        try:
            d = date.fromisoformat(r["data_riferimento"])
        except ValueError:
            continue
        if week_start <= d <= week_end:
            found.add(d)
    return sorted(found)


def render_html(report, week_start, week_end, covered_days):
    period = f"{week_start.strftime('%d/%m/%Y')} – {week_end.strftime('%d/%m/%Y')}"
    missing = 7 - len(covered_days)
    warning = ""
    if missing > 0:
        warning = (
            f"<p style='color:#b00;font-family:Arial,sans-serif;font-size:13px;'>"
            f"Attenzione: per questa settimana ho trovato dati per {len(covered_days)}/7 giorni "
            f"(mancano {missing} giorni). I totali qui sotto sono calcolati solo sui giorni disponibili."
            f"</p>"
        )

    rows_html = ""
    for i, f in enumerate(report, start=1):
        rows_html += f"""
        <tr style="background:{'#f7f7f7' if i % 2 == 0 else '#ffffff'};">
          <td style="padding:6px 10px;border:1px solid #ddd;">{i}</td>
          <td style="padding:6px 10px;border:1px solid #ddd;">{f['titolo']}</td>
          <td style="padding:6px 10px;border:1px solid #ddd;">{f['distribuzione']}</td>
          <td style="padding:6px 10px;border:1px solid #ddd;text-align:right;">{euro(f['incasso_settimana'])}</td>
          <td style="padding:6px 10px;border:1px solid #ddd;text-align:right;">{it_number(f['presenze_settimana'])}</td>
          <td style="padding:6px 10px;border:1px solid #ddd;text-align:right;">{euro(f['incasso_weekend'])}</td>
          <td style="padding:6px 10px;border:1px solid #ddd;text-align:right;">{it_number(f['presenze_weekend'])}</td>
          <td style="padding:6px 10px;border:1px solid #ddd;text-align:right;">{euro(f['incasso_totale'])}</td>
        </tr>"""

    html = f"""
    <html><body style="font-family:Arial,sans-serif;color:#222;">
      <h2 style="margin-bottom:4px;">Report settimanale Cinetel</h2>
      <p style="margin-top:0;color:#555;">Settimana {period}</p>
      {warning}
      <table style="border-collapse:collapse;width:100%;font-size:13px;">
        <thead>
          <tr style="background:#1f3a5f;color:#fff;">
            <th style="padding:6px 10px;border:1px solid #1f3a5f;">#</th>
            <th style="padding:6px 10px;border:1px solid #1f3a5f;">Titolo</th>
            <th style="padding:6px 10px;border:1px solid #1f3a5f;">Distribuzione</th>
            <th style="padding:6px 10px;border:1px solid #1f3a5f;">Incasso settimana</th>
            <th style="padding:6px 10px;border:1px solid #1f3a5f;">Presenze settimana</th>
            <th style="padding:6px 10px;border:1px solid #1f3a5f;">Incasso weekend (ven-dom)</th>
            <th style="padding:6px 10px;border:1px solid #1f3a5f;">Presenze weekend (ven-dom)</th>
            <th style="padding:6px 10px;border:1px solid #1f3a5f;">Incasso totale cumulato*</th>
          </tr>
        </thead>
        <tbody>
          {rows_html if rows_html else '<tr><td colspan="8" style="padding:10px;">Nessun dato disponibile per questa settimana.</td></tr>'}
        </tbody>
      </table>
      <p style="font-size:11px;color:#888;margin-top:12px;">
        * "Incasso totale cumulato" = somma di tutti i giorni raccolti dal tracker da quando è attivo,
        non l'incasso totale del film dalla sua uscita in sala (di cui non abbiamo storico pregresso).
      </p>
    </body></html>
    """
    return html


def send_email(html_body: str, subject: str):
    gmail_address = os.environ.get("GMAIL_ADDRESS")
    gmail_app_password = os.environ.get("GMAIL_APP_PASSWORD")
    if not gmail_address or not gmail_app_password:
        print("ERRORE: variabili d'ambiente GMAIL_ADDRESS / GMAIL_APP_PASSWORD mancanti.", file=sys.stderr)
        sys.exit(1)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = gmail_address
    msg["To"] = RECIPIENT
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(gmail_address, gmail_app_password)
        server.sendmail(gmail_address, [RECIPIENT], msg.as_string())


def main():
    today = date.today()
    week_start, week_end = previous_week_range(today)

    rows = load_rows()
    covered_days = days_covered(rows, week_start, week_end)
    report = build_report(rows, week_start, week_end)

    html = render_html(report, week_start, week_end, covered_days)
    subject = f"Cinetel – Report settimanale ({week_start.strftime('%d/%m')} – {week_end.strftime('%d/%m/%Y')})"

    send_email(html, subject)
    print(f"Email inviata a {RECIPIENT} — {len(report)} film, {len(covered_days)}/7 giorni di dati coperti.")


if __name__ == "__main__":
    main()
