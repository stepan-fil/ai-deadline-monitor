#!/usr/bin/env python3
# =============================================================================
#  reset_demo.py — setzt die Demo auf den Aufnahme-Startzustand zurück (für beliebig
#  viele Takes). Reihenfolge:
#    1) audit_log leeren (TRUNCATE … RESTART IDENTITY) — reine Demo-Daten.
#    2) Demo-Postfach leeren (alte/SEEN-Mails raus, damit Retakes sauber starten).
#    3) neu seeden (seed_demo.seed) — kuratiertes Board, Held ausgespart.
#
#  Danach: internes Dashboard zeigt das geseedete Board, externe Ansicht die Freigegebenen,
#  Posteingang leer, Held NICHT drin → bereit für die Live-Helden-Mail im Take.
#
#  Voraussetzung: Stack läuft, WF-C aktiv, Ollama warm. Lauf: python3 testdata/reset_demo.py
# =============================================================================
import sys

import demo_lib as L
import seed_demo


def reset() -> int:
    print("1) audit_log leeren …")
    L.psql("TRUNCATE audit_log RESTART IDENTITY;")
    print(f"   audit_log Zeilen: {L.audit_count()}")

    print("2) Demo-Postfach leeren …")
    n = L.clear_inbox()
    print(f"   {n} Mail(s) entfernt; UNSEEN jetzt: {L.unseen_count()}")

    print("3) WF-C-IMAP-Verbindung auffrischen (n8n-Neustart nach Postfach-Expunge) …")
    L.restart_n8n()
    print("   n8n bereit.")

    print("4) neu seeden …")
    return seed_demo.seed(do_approve="--no-approve" not in sys.argv)


if __name__ == "__main__":
    raise SystemExit(reset())
