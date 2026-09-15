# Cinetel Box Office Tracker

Raccoglie automaticamente, ogni giorno, i dati box office pubblicati su
[cinetel.it](https://cinetel.it/homepage) (posizione, titolo, distribuzione,
incasso, presenze) e li salva in questo repository come storico consultabile.

Funziona in modo completamente indipendente da Claude o dal tuo computer:
gira su **GitHub Actions**, quindi una volta impostato prosegue da solo ogni
giorno, gratuitamente, anche a computer spento.

## Come funziona

- `scripts/scrape_cinetel.py` apre la pagina con un browser headless
  (Playwright), legge la tabella del box office ed estrae i dati dal testo
  visibile della pagina (non da classi CSS, che possono cambiare). Salva
  solo la **top ten** (i primi 10 film in classifica); quelli oltre la
  decima posizione vengono scartati. Per cambiare quanti film tenere, modifica
  la costante `TOP_N` in cima al file.
- Prima di salvare, `validate_rows()` controlla che i numeri abbiano senso
  (l'incasso/le presenze di un giorno non possono mai superare il totale
  dall'uscita in sala) e scarta con un avviso qualsiasi riga con dati
  incoerenti, invece di salvarla in silenzio nel CSV.
- `.github/workflows/daily-scrape.yml` esegue lo script ogni giorno alle
  05:30 UTC (06:30/07:30 ora italiana) e salva il risultato direttamente nel
  repository con un commit automatico.
- I dati finiscono in due posti:
  - `data/raw/<AAAA-MM-GG>.json` — snapshot completo del giorno.
  - `data/cinetel_boxoffice.csv` — storico cumulativo, una riga per film per
    giorno, pronto per essere aperto in Excel/Google Sheets o caricato in un
    notebook per l'elaborazione.

## Setup (una tantum, ~5 minuti)

1. **Crea un repository su GitHub** (puoi renderlo privato se vuoi che i
   dati non siano pubblici — funziona lo stesso).
2. Carica tutto il contenuto di questa cartella nel repository:
   ```bash
   cd cinetel-tracker
   git init
   git add .
   git commit -m "Setup iniziale"
   git branch -M main
   git remote add origin https://github.com/<tuo-utente>/<tuo-repo>.git
   git push -u origin main
   ```
3. Su GitHub, vai in **Settings → Actions → General → Workflow permissions**
   e seleziona **"Read and write permissions"** (serve perché il workflow
   deve poter fare commit dei dati nel repo).
4. Fatto. Il workflow partirà automaticamente ogni giorno. Per testarlo
   subito senza aspettare: vai nella tab **Actions** del repository, apri
   "Cinetel daily scrape" e clicca **"Run workflow"**.

## Modificare l'orario

L'orario è impostato per catturare i dati del giorno precedente quando sono
ormai definitivi. Se vuoi cambiarlo, modifica la riga `cron` in
`.github/workflows/daily-scrape.yml` (orari sempre in UTC).

## Report settimanale via email

Ogni lunedì alle **8:30 (ora italiana, CEST)** (`.github/workflows/weekly-report.yml`) lo script
`scripts/weekly_report.py` legge lo storico raccolto, aggrega per film la
settimana appena conclusa (lunedì-domenica) e invia una email HTML a
**gabriele.niola@gmail.com** con questa tabella:

| # | Titolo | Distribuzione | Incasso settimana | Presenze settimana | Incasso weekend (ven-dom) | Presenze weekend (ven-dom) | Incasso totale dall'uscita* |
|---|--------|----------------|--------------------|---------------------|----------------------------|------------------------------|-------------------------------|

\* "Incasso totale dall'uscita" è il dato ufficiale che Cinetel pubblica per
ogni film (colonna "Incasso al [data]" sulla pagina), non un cumulato
calcolato da noi — quindi è corretto fin dalla prima settimana di utilizzo
del tracker.

Se in una settimana mancano dei giorni (es. il workflow giornaliero ha fallito
un giorno), l'email lo segnala in rosso in cima e calcola i totali solo sui
giorni effettivamente disponibili.

### Setup dell'invio email (una tantum)

L'invio usa il tuo Gmail via SMTP con una **App Password** di Google (non la
tua password normale — è una password dedicata solo per questo, revocabile
in qualsiasi momento):

1. Assicurati di avere la **verifica in due passaggi** attiva sul tuo account
   Google (necessaria per generare le App Password):
   https://myaccount.google.com/security
2. Vai su https://myaccount.google.com/apppasswords, crea una nuova app
   password (nome a piacere, es. "Cinetel tracker") e copia il codice di 16
   caratteri che ti viene mostrato.
3. Nel repository GitHub vai in **Settings → Secrets and variables →
   Actions → New repository secret** e crea:
   - `GMAIL_ADDRESS` → il tuo indirizzo, `gabriele.niola@gmail.com`
   - `GMAIL_APP_PASSWORD` → il codice di 16 caratteri appena generato
4. Fatto. Per testare subito senza aspettare lunedì: tab **Actions** →
   "Cinetel weekly report" → **Run workflow**.

Nota: se in quel momento non ci sono ancora 7 giorni di dati raccolti (es.
appena impostato il tracker), il report verrà comunque inviato ma con
l'avviso "dati parziali" e i totali calcolati sui giorni disponibili.

### Nota sull'ora legale

Il cron di GitHub Actions è sempre in **UTC** e non si adatta da solo
all'ora legale/solare italiana. È impostato su `30 6 * * 1`, che corrisponde
alle **8:30** in CEST (ora legale, marzo-ottobre — il periodo in cui uscirà
la maggior parte dei report). In inverno (ora solare, CET) l'email arriverà
alle 9:30 invece che alle 8:30. Se vuoi l'orario fisso anche in inverno,
basta cambiare manualmente il valore del cron due volte l'anno (o dirlo a
Claude, che aggiorna il file).

## Nota

I dati su cinetel.it sono pubblicamente visibili senza login. Verifica comunque
i termini d'uso del sito prima di un utilizzo continuativo o commerciale dei
dati raccolti.
