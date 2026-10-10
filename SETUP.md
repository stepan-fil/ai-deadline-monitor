# SETUP — Fristenwächter lokal starten (Mac, Apple Silicon)

Diese Anleitung bringt den Stack von Null auf einem **Mac mit Apple Silicon** (M1–M4) zum Laufen.
Annahme: der Rechner ist „leer" (kein Docker/n8n/Ollama). Wir installieren im Kern nur **zwei** Dinge
nativ — **Docker Desktop** und **Ollama** — der Rest kommt als Container.

> **Warum Ollama nativ statt im Container?** Auf Apple Silicon haben Docker-Container keinen Zugriff
> auf die Metal-GPU. Ollama im Container liefe CPU-only und damit langsam (sieht in der Aufnahme aus
> wie ein Hänger). Nativ nutzt Ollama die GPU → schnell.

---

## 0. Voraussetzungen

- macOS auf Apple Silicon (M1/M2/M3/M4).
- Genug freier RAM fürs Modell: ~8 GB reichen für ein 3B-Modell; für `llama3.1:8b` lieber 16 GB+.
- Admin-Rechte (für die Installation).

---

## 1. Docker Desktop installieren

**Variante A — mit Homebrew (empfohlen):**

```bash
# Homebrew installieren, falls noch nicht vorhanden:
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# Docker Desktop installieren:
brew install --cask docker
```

**Variante B — manuell:** Docker Desktop für **Apple Silicon** von der offiziellen Docker-Seite laden
und installieren.

Danach **Docker Desktop einmal über die App starten** (Wal-Icon in der Menüleiste muss „running"
zeigen). Prüfen:

```bash
docker --version
docker compose version
```

---

## 2. Ollama installieren, Modell ziehen, warmlaufen

**Variante A — als App (empfohlen, klickbar aus dem Launchpad):** Ollama für macOS von ollama.com
laden (.dmg), installieren, einmal öffnen. Die App sitzt dann in der Menüleiste und startet den
Server (Port 11434) automatisch — `ollama serve` brauchst du dann **nicht**.

**Variante B — nur CLI (Terminal, kein App-Icon):**

```bash
brew install ollama
ollama serve   # Server starten, Terminal-Fenster offen lassen
```

In einem **zweiten** Terminal das Modell ziehen (Wert aus `.env`, Standard `llama3.2:3b`):

```bash
ollama pull llama3.2:3b
# Mehr RAM (16 GB+)? Optional ein größeres Modell (dann OLLAMA_MODEL in .env anpassen
# und die Workflows mit build_workflows.mjs neu erzeugen):
# ollama pull llama3.1:8b

# Warmlauf (lädt das Modell in den RAM → später kein Kaltstart in der Aufnahme):
ollama run llama3.2:3b "Sag nur: bereit"
```

Erreichbarkeit testen:

```bash
curl http://localhost:11434/api/tags
```

---

## 3. Repo holen / in den Projektordner wechseln

```bash
cd ai-deadline-monitor
```

> Frisch von GitHub: `git clone https://github.com/stepan-fil/ai-deadline-monitor.git && cd ai-deadline-monitor`

---

## 4. Konfiguration anlegen (`.env`)

```bash
cp .env.example .env
```

Dann `.env` öffnen und Werte setzen. Mindestens:

```bash
# sicheres Postgres-Passwort + n8n-Encryption-Key erzeugen:
openssl rand -hex 24    # Ausgabe als N8N_ENCRYPTION_KEY eintragen
openssl rand -hex 16    # Ausgabe als POSTGRES_PASSWORD eintragen
```

`OLLAMA_BASE_URL` bleibt auf `http://host.docker.internal:11434` (so erreicht der n8n-Container das
native Ollama). Die echte `.env` wird **nicht** committet (steht in `.gitignore`).

---

## 5. Stack starten

```bash
docker compose up -d
```

Beim ersten Start legt Postgres automatisch die Tabelle `audit_log` an (`db/init.sql`).

---

## 6. Prüfen, dass alles läuft

```bash
# Container-Status (postgres sollte "healthy" sein):
docker compose ps

# n8n im Browser öffnen:
open http://localhost:5678

# Audit-Log-Tabelle vorhanden?
docker exec -it fw_postgres psql -U fristenwaechter -d fristenwaechter -c "\dt"

# Ollama antwortet?
curl http://localhost:11434/api/tags
```

Erwartung: n8n-Oberfläche lädt, `audit_log` ist gelistet, Ollama gibt JSON zurück.

> **Beim ersten Öffnen von n8n** legst du einmalig ein **lokales Owner-Konto** an (E-Mail +
> Passwort). Das bleibt komplett lokal — kein Cloud-Login, keine Registrierung nach außen.

---

## 7. Workflows importieren (M2 — CSV-Pfad + Dashboard)

In M2 entstehen **zwei** Workflows:
- `n8n/workflow_csv_ingestion.json` — **WF-A**: Manueller Start → CSV (`/data/testdata/fristen.csv`)
  → Knoten 8 (KI-freie Logik) → Postgres `audit_log`.
- `n8n/workflow_dashboard_server.json` — **WF-B**: liefert Dashboard (`/webhook/dashboard`) + Daten
  (`/webhook/fristen-data`). **Muss aktiv sein.**

Voraussetzung: `testdata/` ist read-only in den Container gemountet (`/data/testdata`) und
`N8N_RESTRICT_FILE_ACCESS_TO` gibt es frei — beides ist in `docker-compose.yml` bereits gesetzt.

Schritte in n8n (http://localhost:5678):
1. **Owner-Konto** anlegen (einmalig, lokal — siehe §6).
2. **Postgres-Credential** anlegen: Typ *Postgres*, Host `postgres`, Port `5432`, Datenbank + User
   `fristenwaechter`, Passwort = `POSTGRES_PASSWORD` aus `.env` (n8n erreicht die DB über den
   Compose-Servicenamen `postgres`).
3. Beide JSON über **Import from File** laden; in den Postgres-Knoten beider Workflows das Credential
   aus Schritt 2 auswählen.
4. **WF-B aktivieren** (Toggle oben rechts). WF-A bleibt manuell (Button „Test workflow").
5. WF-A einmal ausführen → 10 Zeilen in `audit_log`. Dashboard: **http://localhost:5678/webhook/dashboard**.

> **JSON neu erzeugen** (z. B. nach Änderung an `dashboard/dashboard.html`):
> `FW_PG_CRED_ID=<credential-id> node n8n/build_workflows.mjs` — das Skript bettet das aktuelle
> Dashboard in WF-B ein (einzige Quelle, kein doppeltes Pflegen).

---

## 8. Stoppen / Aufräumen

```bash
docker compose down            # stoppt die Container (Daten bleiben im Volume)
docker compose down -v         # ACHTUNG: löscht auch die Volumes (DB wird zurückgesetzt)
```

---

## Troubleshooting

- **n8n erreicht Ollama nicht:** Läuft `ollama serve`? Steht `OLLAMA_BASE_URL` auf
  `http://host.docker.internal:11434`? Testen aus dem Container:
  `docker exec -it fw_n8n wget -qO- http://host.docker.internal:11434/api/tags`
- **n8n-Login akzeptiert Cookie nicht:** Wir setzen `N8N_SECURE_COOKIE=false` (für http/localhost).
  Stelle sicher, dass das in `docker-compose.yml` aktiv ist.
- **Port belegt (5678 / 5432 / 11434):** anderen Prozess beenden oder den Port-Mapping-Wert in
  `docker-compose.yml` ändern.
- **Postgres-Schema-Änderung greift nicht:** `init.sql` läuft nur beim **ersten** Start (leeres
  Volume). Nach Schema-Änderungen: `docker compose down -v` und neu hoch (löscht die Demo-Daten).
- **Modell zu langsam / zu wenig RAM:** kleineres Modell ziehen (`llama3.2:3b`) und `OLLAMA_MODEL`
  in `.env` anpassen.
- **Webhook „URL path … already taken" / neuer Workflow wird nicht aktiv:** In n8n 2.26 einen
  Workflow **vor dem Löschen erst deaktivieren** (Toggle aus). Sonst bleibt eine verwaiste
  `webhook_entity`-Registrierung zurück und blockiert den Pfad für den Nachfolger. Erkennen:
  `docker compose logs n8n` zeigt „… is already taken" + „Could not find workflow …". Beheben: alten
  Workflow sauber löschen, dann `docker compose restart n8n`.
- **`docker compose up` / `docker pull` hängt beim Image-Ziehen (z. B. GreenMail) — und danach lädt GAR KEIN Image mehr**
  (auch `docker pull hello-world` hängt): Docker Desktops interne Pull-/Proxy-Schicht ist „wedged", typischerweise weil ein
  vorheriger Pull **mittendrin abgebrochen** wurde. **Gegenmittel/Vorbeugung:**
  1. **GreenMail-Image ZUERST einzeln + überwacht ziehen, BEVOR du `compose up` startest:**
     `docker pull greenmail/standalone:2.1.0` — so kann ein langsamer Download den `compose up` nicht blockieren.
  2. Hängt der Pull trotzdem: prüfen, ob es am Daemon liegt (nicht am Netz): `docker pull hello-world` — hängt auch das,
     ist es Docker Desktop, nicht dein Netz (Gegencheck: `curl -s https://hub.docker.com/v2/repositories/greenmail/standalone/tags`
     vom **Host** geht trotzdem). **Fix:** Docker Desktop über die **GUI** neu starten/zurücksetzen (Wal-Menü → Quit, ~10 s,
     neu öffnen; auf 8 GB RAM vorher schwere Apps schließen) **oder** „Troubleshoot → Restart". Reines `docker desktop restart`
     auf der CLI reicht oft **nicht** (setzt die VM-Netzschicht nicht vollständig zurück).
  3. Erst wenn das Image lokal liegt (`docker images greenmail/standalone`), `docker compose up -d`.

---

## 9. Mail-Eingang (M7) + externe Ansicht + Aufnahme-Choreografie

> Neu in M7 (ENTSCHEIDUNG-28/-29/-30): Dokumente kommen **per E-Mail an einen lokalen Mailserver** rein und
> werden automatisch eingelesen; zusätzlich gibt es eine **externe Read-only-Ansicht** (nur Freigegebenes).
> Diese Schritte laufen in **Claude Code** auf dem Docker-Mac. Reihenfolge wichtig.

### 9.1 `.env` ergänzen (Mail-Demo-Postfach)
Die echte `.env` braucht den Mail-Block (steht in `.env.example`, **reine lokale Demo-Werte**, kein echtes Konto):
```bash
MAIL_USER=fristen
MAIL_PASS=demo_mail_passwort_lokal
MAIL_DOMAIN=fristenwaechter.local
```

### 9.2 Stack inkl. GreenMail hochfahren
```bash
docker compose up -d
docker compose ps   # erwartet jetzt 3 Container: fw_postgres (healthy), fw_n8n, fw_greenmail
```
GreenMail hört auf `127.0.0.1:3025` (SMTP) + `127.0.0.1:3143` (IMAP). n8n erreicht ihn intern als `greenmail:3143`.

### 9.3 Workflows neu erzeugen + importieren
WF-B hat **neue** Webhooks (extern), und **WF-C** ist neu. JSON neu bauen (IMAP-Cred-ID optional, sonst Platzhalter):
```bash
FW_PG_CRED_ID=<pg-cred> [FW_IMAP_CRED_ID=<imap-cred>] node n8n/build_workflows.mjs
```
- **WF-B** neu importieren/überschreiben (wegen extern-Webhooks) — vorher **deaktivieren**, dann ersetzen, Cred zuweisen, **aktivieren** (sonst „URL path already taken", siehe Troubleshooting).
- **WF-C** (`n8n/workflow_mail_ingestion.json`) importieren.

### 9.4 IMAP-Credential in n8n anlegen
Typ **IMAP**: Host `greenmail`, Port `3143`, User = `MAIL_USER` (`fristen`), Passwort = `MAIL_PASS`,
**SSL/TLS = aus**, „Allow Self-Signed Certificates" = an. Im WF-C-Trigger dieses Credential auswählen,
im Postgres-Knoten den Postgres-Cred. **WF-C aktivieren** (Polling-Trigger läuft nur aktiv!).

### 9.5 Test-Mail senden
```bash
python3 testdata/send_test_mail.py                      # Standard: Rahmenvertrag_Logistik.pdf
python3 testdata/send_test_mail.py Maschinenpruefung_UVV.pdf
```
n8n holt die Mail (nur **UNSEEN**) ab, liest den PDF-Anhang, schreibt eine Zeile (`source_mode='llm'`) in `audit_log`.

### 9.6 Externe Ansicht öffnen
- Intern: `http://localhost:5678/webhook/dashboard`
- **Extern (nur Freigegebenes):** `http://localhost:5678/webhook/extern`

### 9.7 Aufnahme-Choreografie (chronologisch, ENTSCHEIDUNG-30)
1. **Vorbereitung (off-camera):** Ollama **warmlaufen** (`ollama run <modell> "bereit"`); WF-C **frisch aktivieren**;
   `audit_log` ggf. leeren; Stichtage am Aufnahmetag nachsetzen (`testdata/build_pdfs.py`, R3); **einmal Probelauf**
   mit der echten Test-Mail → prüfen, dass die Kachel erscheint.
2. **Take:** internes Dashboard groß zeigen → kurz Terminal: `python3 testdata/send_test_mail.py` („ein Dokument
   kommt per Mail") → optional 3–5 s n8n-Canvas auf **Knoten 8 (KI-frei)** als Beweis → zurück aufs Dashboard: neue
   Kachel („🧠 KI") → **„✋ Freigeben"** klicken → zweites Fenster **externe Ansicht**: erst leer, nach Freigabe
   erscheint die Box („nur Freigegebenes wird extern sichtbar") → Audit-Log-Sicht zeigt den Lauf + die Freigabe.
3. **Tipp:** Mail wegen Polling-Latenz lieber **kurz vorher** senden (oder Poll-Intervall klein stellen). Für jeden
   **Retake** eine **neue** Mail senden (alte ist `\SEEN` und wird nicht erneut geholt).
4. **Sicherheitsnetz (off-camera):** Wenn der Mail-/LLM-Pfad zickt → WF-A (Button, `csv`-Default) liefert in <2 Min
   ein volles Dashboard (den „umschaltbar"-Beweis, Vorgabe 3). **Mail-Story und CSV nicht im selben Take mischen.**
- **Ampel-Mix extern:** Die externe Ansicht zeigt nur Freigegebenes → für grün/gelb/rot **mehrere** Dokumente
  freigeben, **oder** den Mix nur im internen Dashboard erzählen.

### 9.8 Testliste (am laufenden Stack abhaken — aus R4-Review)
1. **Happy Path:** Test-Mail mit PDF → genau **1** neue `audit_log`-Zeile (`source_mode='llm'`), `partner/stichtag`
   stammen **aus dem PDF** (nicht aus dem Mailtext — **B1-Gegenprüfung!**), Ampel korrekt.
2. **Idempotenz:** dieselbe Mail nicht erneut geholt (UNSEEN+Mark-as-Read) → keine zweite Zeile.
3. **Mail ohne Anhang / mit `.txt`:** IF „Hat PDF-Anhang?" → kein Insert, **kein** Fehler, Execution „success".
4. **Null-Lauf:** Ollama stoppen → Mail kommt, alle Items ungültig → **0 Inserts, keine Meldung** (bekannte Auflage:
   vor dem Take Warmlauf + Zeilenzahl-Check).
5. **Mehrere Mails** (3 verschiedene PDFs) → 3 Zeilen, je 1 pro Dokument; 3 neue Kacheln.
6. **Extern nur nach Freigabe:** `/webhook/extern` vorher leer; nach Freigabe genau diese Box; `/webhook/extern-data`
   enthält **keine** `approved=false`-Zeile und **kein `id`**.
7. **0-Zeilen-Rendering:** `audit_log` leer → beide Seiten zeigen sauberen Leer-Zustand, keine JS-Fehler.

> **Stand 2026-06-23 (M7-Live-Bau):** T1–T7 **alle bestanden** am laufenden Stack.
> Präzisierung zu T4: Der getestete Fall war „inhaltsloses PDF" (Ollama antwortet, Extraktion ungültig → Filter → **0 Inserts**,
> Execution **success**). Der Fall **„Ollama wirklich unreachable"** ist **anders**: der HTTP-Knoten wirft → die WF-C-Execution endet
> mit **sichtbarem Fehler** in n8n (kein Insert, aber kein stiller Erfolg). Timeout wurde auf **60 s** gesenkt, damit ein toter Ollama
> nicht 2 Min im Take hängt. **Es gibt kein UI-Signal bei 0 Zeilen** → das Sicherheitsnetz ist der **Warmlauf + Probelauf** vor dem Take.
> *Empirisch (2026-06-23): Die Ollama-**App startet ihren Server nach einem Prozess-Kill in ~2 s automatisch neu** — ein
> transienter Absturz heilt also selbst; ein dauerhaft „unreachable" Ollama ließe sich nur durch Beenden der App erzeugen.*

### 9.9 IMAP-Credential headless per CLI anlegen (wenn kein n8n-Login zur Hand ist)
Alternativ zur UI (§9.4) — nützlich in Claude Code ohne Owner-Passwort. Schreibt das Cred verschlüsselt in n8n; **kein Secret ins Repo**:
```bash
# JSON in /tmp bauen (NICHT im Repo), Passwort aus .env lesen:
python3 - <<'PY'
import json, pathlib
env={l.split('=',1)[0].strip():l.split('=',1)[1].strip() for l in pathlib.Path('.env').read_text().splitlines() if l.strip() and not l.startswith('#') and '=' in l}
cred=[{"id":"FwImapGreenmail01","name":"Fristenwaechter Mail (IMAP)","type":"imap",
  "data":{"host":"greenmail","port":3143,"user":env["MAIL_USER"],"password":env["MAIL_PASS"],"secure":False,"allowUnauthorizedCerts":True}}]
pathlib.Path("/tmp/imapcred.json").write_text(json.dumps(cred))
PY
docker cp /tmp/imapcred.json fw_n8n:/tmp/imapcred.json && docker exec fw_n8n n8n import:credentials --input=/tmp/imapcred.json
docker exec -u root fw_n8n rm -f /tmp/imapcred.json && rm -f /tmp/imapcred.json   # Temp-Dateien sofort löschen (R5)
```
Workflow-Import analog per CLI: `docker cp n8n/workflow_*.json fw_n8n:/tmp/… && docker exec fw_n8n n8n import:workflow --input=…`
(die JSON braucht eine `id` → mit `FW_WF_ID_B`/`FW_WF_ID_C` bauen), danach `n8n update:workflow --id=<id> --active=true` + `docker compose restart n8n`.

### 9.10 Aufnahmetag-Routine — EIN Kommando: `pretake.py`
Der **Pre-Take-Befehl** bündelt die komplette Aufnahmetag-Vorbereitung und meldet am Ende `READY ✅` / `NICHT READY ❌`:
```bash
python3 testdata/pretake.py                 # ← VOR jedem Take ausführen (idempotent)
python3 testdata/pretake.py --no-approve     # Variante: externe Ansicht startet leer (Szene-7-Reveal)
```
Reihenfolge im Skript (alles lokal, nur Stdlib): **(a)** `build_pdfs.py` (heute-relative Stichtage → Ampel-Mix 2 rot/2 gelb/2 grün) ·
**(b)** prüft die 3 Container · **(c)** Ollama warmlaufen + Resident-Check · **(c+)** IMAP-Tracking-Kaltstart-Check (s. u.) ·
**(d)** `reset_demo.py` (Board seeden, Held ausgespart) · **(e)** Health-Checks (WF-B+WF-C aktiv; `dashboard`/`fristen-data`/`extern`/
`extern-data`/`audit-log` → 200; **drei Ansichten** erreichbar, Default „Zu prüfen"; Seed-Stand 5 Kacheln / 3 freigegeben / Held draußen;
keine offenen Mails). **Erst aufnehmen, wenn `READY ✅`.** Danach Probelauf `send_test_mail.py`, dann erneut `pretake.py` (DREHBUCH §2).

Die zugrunde liegenden Skripte (von `pretake.py` orchestriert, einzeln nur zum Debuggen):
```bash
python3 testdata/reset_demo.py     # audit_log + Postfach leeren → n8n-Neustart → neu seeden
python3 testdata/build_pdfs.py     # PDFs + fristen.csv neu (heute-relativ)
python3 testdata/send_test_mail.py # EINE Held-Mail (Live-Auslöser im Take)
```
- **Seed-Verhalten (ENTSCHEIDUNG-31):** schickt die kuratierten Nicht-Helden-Docs per Mail (echter LLM-Pfad → „🧠 KI"-Badges),
  **einzeln mit Bestätigung** (nicht im Schwung — ein Mail-Burst überfordert sonst die WF-C/Ollama-Kette auf 8 GB), datiert sie zurück
  (→ **kein** „gerade eingegangen"-Highlight), gibt 3 frei (extern sichtbar, Ampel-Mix), **lässt den Helden aus**. `partner`+`pflicht`
  der Seed-Kacheln werden auf den Soll-Wert normalisiert (Mensch-im-Loop-Korrektur; das 3B-Modell verschluckt sonst Umlaute).
  **Immer `pretake.py`/`reset_demo.py` statt nacktem `seed_demo.py`** (Seed-Abschluss ist zählerbasiert → braucht sauberen Start).
- **Kaltstart & IMAP (wichtig, 2026-06-24):** GreenMail ist **In-Memory** → bei jedem (Kalt-)Start beginnen die Mail-UIDs wieder
  niedrig. Damit WF-C neue Mails nicht für „schon gesehen" hält, trägt der IMAP-Trigger **kein** `trackLastMessageId` mehr (Idempotenz
  rein über `UNSEEN` + `postProcessAction:'read'`), und die committete WF-C-JSON führt `staticData:{}` (ein Re-Import setzt das Tracking
  zurück). `pretake.py` prüft zusätzlich (Schritt c+), ob doch eine veraltete UID gemerkt ist, und setzt sie nötigenfalls zurück.
- **Reset = n8n-Neustart nach Postfach-Leeren:** `reset_demo.py` leert das Postfach (IMAP-Expunge) und **startet n8n danach kurz neu**.
  Grund: ein Expunge über eine separate Verbindung legt WF-Cs offene IDLE-Verbindung still („No mailbox is currently selected"); der
  Neustart gibt WF-C eine **frische** Verbindung, danach werden die Seed-Mails wieder zuverlässig eingelesen. (Faustregel: **GreenMail
  nie unter laufendem n8n neu starten** — sonst n8n danach neu starten.)
- **Hinweis (harmlos):** Bei der PDF-Extraktion loggt n8n Warnungen `@napi-rs/canvas`/`standardFontDataUrl` — reine Font-Render-Warnungen,
  die **Textextraktion funktioniert** (der Held wird korrekt gelesen). Kein Handlungsbedarf.

### 9.11 Thunderbird als Mail-Auslöser (Szene 3) — Konto + exakter Mail-Inhalt
Szene 3 zeigt eine **echte** E-Mail mit PDF-Anhang, die abgeschickt wird (Variante A des DREHBUCHs — der verständlichste Auslöser).
Thunderbird sendet über **denselben** lokalen SMTP wie `send_test_mail.py` (localhost:3025) ins selbe Postfach — WF-C verarbeitet die
Mail **identisch** (filtert NICHT nach Absender). Parität verifiziert (2026-06-24): Mail mit fremdem From-Header + Helden-PDF →
WF-C liest ein → hervorgehobene Held-Kachel in „Zu prüfen" (Beleg: `docs/screenshots/`).

**Konto in Thunderbird einrichten** (einmalig; „Manuell einrichten", NICHT die Auto-Erkennung):
| | Server | Port | Verbindungssicherheit | Authentifizierung | Benutzer |
|---|---|---|---|---|---|
| **IMAP (Posteingang)** | `localhost` | `3143` | **Keine** | Passwort, normal | `fristen` |
| **SMTP (Postausgang)** | `localhost` | `3025` | **Keine** | Passwort, normal *(oder „Keine")* | `fristen` |

- **E-Mail-Adresse/Identität:** `fristen@fristenwaechter.local` · **Passwort:** Wert von `MAIL_PASS` aus `.env` (lokal, kein echtes Konto).
- Thunderbird **warnt vor der unverschlüsselten Verbindung** (krumme Ports, keine TLS) → bewusst **bestätigen/„Trotzdem fortfahren"**.
  Das ist gewollt: alles bleibt lokal (127.0.0.1). Ggf. „Verbindungssicherheit: Keine" + „Unsichere Authentifizierung erlauben".
- **Optik-Tipp:** Für die Erzähl-Story „ein Partner schickt seinen Vertrag" kann der **Anzeigename der Identität** auf z. B.
  *Spedition Nordfracht GmbH* gesetzt werden — der From-Header ist für WF-C aber egal.

**Die Demo-Mail (Szene 3) — exakt so verfassen + senden:**
- **An:** `fristen@fristenwaechter.local`
- **Betreff:** `Neuer Rahmenvertrag — bitte Frist prüfen`
- **Text:**
  > Guten Tag,
  >
  > anbei unser neuer Rahmenvertrag über Logistikdienstleistungen als PDF.
  > Bitte die Kündigungsfrist erfassen und überwachen.
  >
  > Mit freundlichen Grüßen
  > Spedition Nordfracht GmbH
- **Anhang:** `testdata/Rahmenvertrag_Logistik.pdf` (das Helden-PDF) → **Senden**.
- Sekunden später erscheint die **hervorgehobene** Held-Kachel im internen Dashboard unter **„Zu prüfen"**.

**Retake-Regel:** Pro Take eine **neue** Mail senden — eine bereits geholte Mail ist `\SEEN` und wird nicht erneut verarbeitet.
Vor jedem Take ohnehin `python3 testdata/pretake.py` (leert Postfach + Board, Held wieder draußen). Wer kein Thunderbird aufsetzen
will, nutzt die **bombensichere Variante B**: `python3 testdata/send_test_mail.py` (gleiche Mail per Skript).
