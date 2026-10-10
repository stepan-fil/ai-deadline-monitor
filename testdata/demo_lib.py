#!/usr/bin/env python3
# =============================================================================
#  demo_lib.py — gemeinsame Helfer für seed_demo.py / reset_demo.py (M7).
#  Alles LOKAL: SMTP/IMAP gegen GreenMail (127.0.0.1), Freigabe über den lokalen
#  n8n-Webhook, DB über `docker exec fw_postgres psql`. Kein Cloud-Dienst.
#  Nur Python-Standardbibliothek — keine Installation nötig.
# =============================================================================
import csv
import imaplib
import json
import re
import smtplib
import subprocess
import time
import urllib.request
from email.message import EmailMessage
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
CSV_PATH = HERE / "fristen.csv"

# Das „Helden"-Dokument wird im Recording LIVE per Mail eingespielt → NICHT seeden.
HERO = "Rahmenvertrag_Logistik.pdf"
N8N = "http://localhost:5678"
PG_CONTAINER = "fw_postgres"


def load_env() -> dict:
    env = {}
    f = ROOT / ".env"
    if f.exists():
        for line in f.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    return env


ENV = load_env()
MAIL_USER = ENV.get("MAIL_USER", "fristen")
MAIL_PASS = ENV.get("MAIL_PASS", "demo_mail_passwort_lokal")
MAIL_DOMAIN = ENV.get("MAIL_DOMAIN", "fristenwaechter.local")
SMTP_HOST = ENV.get("SMTP_HOST", "127.0.0.1")
SMTP_PORT = int(ENV.get("SMTP_PORT", "3025"))
IMAP_HOST = "127.0.0.1"
IMAP_PORT = 3143
RECIPIENT = f"{MAIL_USER}@{MAIL_DOMAIN}"
PG_USER = ENV.get("POSTGRES_USER", "fristenwaechter")
PG_DB = ENV.get("POSTGRES_DB", "fristenwaechter")


# ---------- Testdaten (kuratiertes Board) ----------
def recording_docs(include_hero: bool = False):
    """Dokumente mit recording=1 aus fristen.csv (Reihenfolge wie im CSV). Held optional."""
    docs = []
    with CSV_PATH.open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            if row.get("recording", "0") == "1":
                if row["doc_name"] == HERO and not include_hero:
                    continue
                docs.append(row)
    return docs


# ---------- Mail (SMTP gegen GreenMail) ----------
def send_pdf_mail(pdf_name: str, sender: str = "vertragspartner@beispiel.example") -> None:
    p = HERE / pdf_name
    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = RECIPIENT
    msg["Subject"] = f"Neues Dokument zur Fristenprüfung: {pdf_name}"
    msg.set_content(
        "Guten Tag,\n\nanbei das Dokument zur automatischen Fristenprüfung (Beispieldokument).\n"
        "Bitte einlesen und die Frist überwachen.\n\nMit freundlichen Grüßen\nBeispiel-Vertragspartner"
    )
    msg.add_attachment(p.read_bytes(), maintype="application", subtype="pdf", filename=pdf_name)
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=15) as s:
        try:
            s.login(MAIL_USER, MAIL_PASS)
        except smtplib.SMTPException:
            pass
        s.send_message(msg)


# ---------- IMAP (Postfach) ----------
def _imap():
    M = imaplib.IMAP4(IMAP_HOST, IMAP_PORT)
    M.login(MAIL_USER, MAIL_PASS)
    return M


def clear_inbox() -> int:
    """Alle Mails aus dem Demo-Postfach löschen (für saubere Retakes). Gibt Anzahl zurück."""
    M = _imap()
    M.select("INBOX")
    _typ, data = M.search(None, "ALL")
    ids = data[0].split() if data and data[0] else []
    for i in ids:
        M.store(i, "+FLAGS", "\\Deleted")
    M.expunge()
    M.logout()
    return len(ids)


def unseen_count() -> int:
    M = _imap()
    M.select("INBOX")
    _typ, data = M.search(None, "UNSEEN")
    n = len(data[0].split()) if data and data[0] else 0
    M.logout()
    return n


# ---------- Freigabe (lokaler n8n-Webhook) ----------
def freigeben(row_id: int) -> int:
    with urllib.request.urlopen(f"{N8N}/webhook/freigeben?id={int(row_id)}", timeout=10) as r:
        return r.status


# ---------- Postgres (über docker exec psql) ----------
def psql(sql: str) -> str:
    out = subprocess.run(
        ["docker", "exec", PG_CONTAINER, "psql", "-U", PG_USER, "-d", PG_DB, "-tA", "-c", sql],
        capture_output=True, text=True, check=True,
    )
    return out.stdout.strip()


def audit_count() -> int:
    return int(psql("SELECT count(*) FROM audit_log;") or "0")


# ---------- WF-C IMAP-Tracking (Kaltstart-Selbstheilung, defensiv) ----------
# Hintergrund: GreenMail ist In-Memory → bei jedem (Kalt-)Start resetten die Mail-UIDs auf niedrige
# Werte. Würde n8n eine alte, hohe UID (staticData.lastMessageUid) >= UIDNEXT des frischen Postfachs
# behalten, hielte WF-C alle neuen Mails für „schon gesehen" und läse nichts ein (stiller Kaltstart-Bug).
# PRIMÄRER FIX (build_workflows.mjs): der IMAP-Trigger hat `trackLastMessageId:false` → n8n setzt die UID
# beim Neustart/Aktivieren ZURÜCK (verifiziert: nach Kaltstart ist tracked=None), der Bug ist damit weg.
# Die folgenden Helfer sind ein zusätzliches DEFENSIVES Netz (sollte eine Alt-WF-C/Alt-staticData doch
# eine stale UID tragen): erkennen + zurücksetzen via Re-Import der live exportierten WF-C mit staticData={}
# — bei GESTOPPTEM n8n, damit der laufende Server die alte In-Memory-staticData nicht zurückschreibt.
N8N_CONTAINER = "fw_n8n"


def _docker(*args):
    return subprocess.run(["docker", *args], capture_output=True, text=True)


def wfc_id() -> str | None:
    """Workflow-ID von WF-C (per Namens-Match — IDs sind maschinenspezifisch)."""
    r = _docker("exec", N8N_CONTAINER, "n8n", "list:workflow")
    for ln in r.stdout.splitlines():
        if "Mail-Ingestion" in ln and "|" in ln:
            return ln.split("|", 1)[0].strip()
    return None


def imap_uidnext() -> int | None:
    """UIDNEXT des Demo-Postfachs (nächste vom Server zu vergebende UID)."""
    try:
        M = _imap()
        M.select("INBOX")
        _typ, data = M.status("INBOX", "(UIDNEXT)")
        M.logout()
        m = re.search(rb"UIDNEXT (\d+)", data[0] if data and data[0] else b"")
        return int(m.group(1)) if m else None
    except Exception:
        return None


def wfc_tracked_uid() -> int | None:
    """Die von WF-C gemerkte lastMessageUid (aus staticData), oder None."""
    wid = wfc_id()
    if not wid:
        return None
    _docker("exec", N8N_CONTAINER, "n8n", "export:workflow", f"--id={wid}", "--output=/tmp/_wfc_chk.json")
    raw = _docker("exec", N8N_CONTAINER, "cat", "/tmp/_wfc_chk.json").stdout
    _docker("exec", "-u", "root", N8N_CONTAINER, "rm", "-f", "/tmp/_wfc_chk.json")
    try:
        data = json.loads(raw)
        wf = data[0] if isinstance(data, list) else data
        node = (wf.get("staticData") or {}).get("node:Email Trigger (IMAP)") or {}
        u = node.get("lastMessageUid")
        return int(u) if u is not None else None
    except Exception:
        return None


def imap_tracking_stale() -> bool:
    """True, wenn WF-C eine UID >= UIDNEXT merkt → GreenMail-UIDs wurden (kalt) zurückgesetzt."""
    t = wfc_tracked_uid()
    n = imap_uidnext()
    if t is None or n is None:
        return False
    return t >= n


def restart_n8n(wait_ready: bool = True) -> None:
    """n8n neu starten + auf Bereitschaft warten. Nötig nach einem Postfach-Expunge: ein
    Expunge über eine separate IMAP-Verbindung legt WF-Cs offene IDLE-Verbindung still
    („No mailbox is currently selected"); der Neustart gibt WF-C eine frische Verbindung,
    sodass danach gesendete Seed-Mails wieder zuverlässig (per IDLE) eingelesen werden."""
    subprocess.run(["docker", "compose", "restart", "n8n"], cwd=str(ROOT), capture_output=True, text=True)
    if wait_ready:
        for _ in range(40):
            try:
                if urllib.request.urlopen(f"{N8N}/webhook/dashboard", timeout=5).status == 200:
                    time.sleep(2)  # dem IMAP-Trigger kurz Zeit zum Verbinden geben
                    return
            except Exception:
                pass
            time.sleep(1.5)


def _n8n_volume_and_image() -> tuple[str, str]:
    vol = _docker("inspect", N8N_CONTAINER, "--format",
                  '{{range .Mounts}}{{if eq .Destination "/home/node/.n8n"}}{{.Name}}{{end}}{{end}}').stdout.strip()
    img = _docker("inspect", N8N_CONTAINER, "--format", "{{.Config.Image}}").stdout.strip()
    return vol, img


def reset_imap_tracking(wait_ready: bool = True) -> bool:
    """WF-C staticData (lastMessageUid) zurücksetzen. Re-Import der live exportierten WF-C
    (echte Cred-Referenzen bleiben erhalten — n8n export enthält KEINE Passwörter) mit
    staticData={} bei GESTOPPTEM n8n. Lokal, keine Secrets in der Ausgabe."""
    wid = wfc_id()
    vol, img = _n8n_volume_and_image()
    if not wid or not vol or not img:
        print("  ! WF-C/Volume/Image nicht ermittelbar — IMAP-Reset übersprungen.")
        return False
    _docker("exec", N8N_CONTAINER, "n8n", "export:workflow", f"--id={wid}", "--output=/tmp/_wfc_live.json")
    raw = _docker("exec", N8N_CONTAINER, "cat", "/tmp/_wfc_live.json").stdout
    _docker("exec", "-u", "root", N8N_CONTAINER, "rm", "-f", "/tmp/_wfc_live.json")
    try:
        data = json.loads(raw)
    except Exception:
        print("  ! WF-C-Export nicht lesbar — IMAP-Reset übersprungen.")
        return False
    wf = data[0] if isinstance(data, list) else data
    wf["staticData"] = {}
    wf["active"] = True
    tmp = Path("/tmp/_wfc_reset.json")
    tmp.write_text(json.dumps(data if isinstance(data, list) else wf))
    subprocess.run(["docker", "compose", "stop", "n8n"], cwd=str(ROOT))
    subprocess.run(["docker", "run", "--rm", "-v", f"{vol}:/home/node/.n8n", "-v", "/tmp:/imp:ro",
                    img, "import:workflow", "--input=/imp/_wfc_reset.json"])
    subprocess.run(["docker", "run", "--rm", "-v", f"{vol}:/home/node/.n8n",
                    img, "update:workflow", f"--id={wid}", "--active=true"])
    subprocess.run(["docker", "compose", "start", "n8n"], cwd=str(ROOT))
    try:
        tmp.unlink()
    except OSError:
        pass
    if wait_ready:
        for _ in range(40):
            try:
                if urllib.request.urlopen(f"{N8N}/webhook/dashboard", timeout=5).status == 200:
                    return True
            except Exception:
                pass
            time.sleep(1.5)
    return True
