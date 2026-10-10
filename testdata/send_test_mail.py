#!/usr/bin/env python3
# =============================================================================
#  send_test_mail.py — schickt EIN Demo-Dokument als E-Mail an den lokalen
#  GreenMail-Server. Damit lässt sich der Mail-Eingang "auf Kommando" auslösen
#  (wichtig für die chronologische Aufnahme: Mail rein -> n8n -> Dashboard).
#
#  Alles bleibt LOKAL: Versand geht an 127.0.0.1:3025 (GreenMail-SMTP), das
#  Postfach liegt im Container. Keine Cloud, kein echtes Konto (ENTSCHEIDUNG-28).
#
#  Nutzung:
#    python3 testdata/send_test_mail.py                      # Standard-PDF
#    python3 testdata/send_test_mail.py Maschinenpruefung_UVV.pdf
#
#  Voraussetzung: der Stack läuft (docker compose up -d), GreenMail ist oben.
#  Nur Python-Standardbibliothek — keine Installation nötig.
# =============================================================================
import os
import sys
import smtplib
from pathlib import Path
from email.message import EmailMessage

# --- Konfiguration (Defaults passen zu .env.example / docker-compose.yml) ---
HERE = Path(__file__).resolve().parent


def env(name: str, default: str) -> str:
    """Liest einen Wert aus der echten .env (Projekt-Root), sonst Umgebung, sonst Default."""
    env_file = HERE.parent / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith(name + "="):
                return line.split("=", 1)[1].strip()
    return os.environ.get(name, default)


SMTP_HOST = env("SMTP_HOST", "127.0.0.1")
SMTP_PORT = int(env("SMTP_PORT", "3025"))           # GreenMail-SMTP (Test-Port)
MAIL_USER = env("MAIL_USER", "fristen")
MAIL_PASS = env("MAIL_PASS", "demo_mail_passwort_lokal")
MAIL_DOMAIN = env("MAIL_DOMAIN", "fristenwaechter.local")

RECIPIENT = f"{MAIL_USER}@{MAIL_DOMAIN}"             # das Demo-Postfach, das n8n abfragt
SENDER = "vertragspartner@beispiel.example"          # frei erfundener Absender

DEFAULT_PDF = "Rahmenvertrag_Logistik.pdf"           # robust extrahierbares "Helden"-Dokument

# Erzählerische Partner-Mail für den Helden (deckungsgleich mit SETUP.md §9.11 / Thunderbird-
# Variante). Der From-Header ist für WF-C egal (liest aus dem PDF, B1) — rein fürs Video-Bild,
# damit die Held-Kachel im Posteingang als echte Partner-Mail erscheint.
HERO_FROM = "Spedition Nordfracht GmbH <vertrag@spedition-nordfracht.example>"
HERO_SUBJECT = "Neuer Rahmenvertrag — bitte Frist prüfen"
HERO_BODY = (
    "Guten Tag,\n\n"
    "anbei unser neuer Rahmenvertrag über Logistikdienstleistungen als PDF.\n"
    "Bitte die Kündigungsfrist erfassen und überwachen.\n\n"
    "Mit freundlichen Grüßen\n"
    "Spedition Nordfracht GmbH"
)


def main() -> int:
    pdf_name = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_PDF
    pdf_path = HERE / pdf_name
    if not pdf_path.exists():
        print(f"FEHLER: PDF nicht gefunden: {pdf_path}")
        print("Vorhandene PDFs:", ", ".join(p.name for p in sorted(HERE.glob("*.pdf"))))
        return 1

    # Der Held (Rahmenvertrag) bekommt die erzählerische Partner-Mail (SETUP §9.11), damit er
    # im Posteingang/„Zu prüfen" als echte Partner-Mail erscheint; andere PDFs die neutrale.
    if pdf_name == DEFAULT_PDF:
        sender, subject, body = HERO_FROM, HERO_SUBJECT, HERO_BODY
    else:
        sender = SENDER
        subject = f"Neues Dokument zur Fristenprüfung: {pdf_name}"
        body = (
            "Guten Tag,\n\n"
            "anbei das Dokument zur automatischen Fristenprüfung (Beispieldokument).\n"
            "Bitte einlesen und die Frist überwachen.\n\n"
            "Mit freundlichen Grüßen\n"
            "Beispiel-Vertragspartner"
        )

    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = RECIPIENT
    msg["Subject"] = subject
    msg.set_content(body)
    msg.add_attachment(
        pdf_path.read_bytes(),
        maintype="application",
        subtype="pdf",
        filename=pdf_name,
    )

    print(f"Sende '{pdf_name}' an {RECIPIENT} über {SMTP_HOST}:{SMTP_PORT} …")
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=15) as smtp:
        smtp.ehlo()
        # GreenMail akzeptiert Test-Mails i. d. R. ohne Login; falls Auth verlangt wird,
        # versuchen wir den Demo-Login (rein lokal, kein echtes Secret).
        try:
            smtp.login(MAIL_USER, MAIL_PASS)
        except smtplib.SMTPException:
            pass
        smtp.send_message(msg)

    print("OK — Mail abgeschickt. n8n (WF-C, aktiv) sollte sie gleich abholen.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
