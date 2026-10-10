#!/usr/bin/env python3
# =============================================================================
#  seed_demo.py — befüllt das Dashboard mit einem „gelebten" Startzustand für die
#  Aufnahme (DREHBUCH.md, Checkliste Punkt 4). Schickt die KURATIERTEN Nicht-Helden-
#  Dokumente per E-Mail an GreenMail → WF-C liest sie über den ECHTEN lokalen LLM-Pfad
#  ein (konsistente „🧠 KI"-Badges) → danach wird eine Teilmenge freigegeben.
#
#  Der HELD (Rahmenvertrag_Logistik.pdf) wird ABSICHTLICH NICHT geseedet — er kommt im
#  Recording LIVE per Mail rein (Szene 3–5).
#
#  Backdating: die geseedeten Zeilen bekommen ein run_at in der Vergangenheit, damit sie
#  NICHT als „gerade eingegangen" hervorgehoben werden — nur die Live-Helden-Mail pulst.
#
#  Seed-Variante = LLM (über echte Mail): bewusst gewählt für konsistente „🧠 KI"-Badges
#  auf allen Kacheln (passt zum Helden, der ebenfalls per KI gelesen wird). temp=0 +
#  format:json → über Resets praktisch reproduzierbar. CSV-Fallback siehe SETUP.md §9.
#
#  Voraussetzung: Stack läuft, WF-C aktiv, Ollama warm. Lauf: python3 testdata/seed_demo.py
# =============================================================================
import sys
import time

import demo_lib as L

# Welche der geseedeten Dokumente sollen vorab freigegeben sein (erscheinen extern)?
# Mischung über die Ampeln, damit die externe Ansicht rot/gelb/grün zeigt (O-5).
APPROVE = {
    "Maschinenpruefung_UVV.pdf",        # rot
    "Foerderbescheid_Digitalbonus.pdf", # gelb
    "Gewerbemietvertrag_Lager.pdf",     # grün
}
BACKDATE_RUN = "25 minutes"     # geseedete Läufe wirken „nicht frisch" (kein Highlight)
BACKDATE_APPROVE = "20 minutes" # Freigabe etwas nach dem Einlesen


def seed(do_approve: bool = True) -> int:
    docs = L.recording_docs(include_hero=False)
    names = [d["doc_name"] for d in docs]
    print(f"Seed: {len(names)} Dokumente per Mail (LLM-Pfad), Held ausgespart ({L.HERO}).")
    before = L.audit_count()

    # WICHTIG: Dokumente EINZELN senden + je auf das Einlesen warten (nicht im Schwung).
    # Grund: Treffen 5 Mails gleichzeitig ein, überfordert der Burst die WF-C/Ollama-Kette
    # (kleines 3B-Modell, 8 GB) — n8n markiert dann Mails als gelesen, ohne sie zu verarbeiten
    # (stiller Verlust). Serialisiert ist es bombensicher; es ist Off-Camera-Vorbereitung, Timing egal.
    for idx, d in enumerate(docs):
        name = d["doc_name"]
        target = before + idx + 1
        L.send_pdf_mail(name)
        print(f"  → gesendet: {name} — warte auf Einlesen …")
        deadline = time.time() + 90
        while L.audit_count() < target:
            if time.time() > deadline:
                print(f"  ! TIMEOUT bei {name}: {L.audit_count()}/{target} Zeilen. Ollama warm? WF-C aktiv?")
                return 1
            time.sleep(2)
        print(f"  ✓ eingelesen: {name}")
    print(f"  ✓ alle {len(names)} eingelesen.")

    # Backdating: geseedete Zeilen ins Vergangene schieben → nicht als „neu" markiert.
    inlist = ",".join("'" + n.replace("'", "''") + "'" for n in names)
    L.psql(f"UPDATE audit_log SET run_at = now() - interval '{BACKDATE_RUN}' WHERE doc_name IN ({inlist});")

    # Anzeige-Normalisierung der GESEEDETEN Kacheln (Seed-Variantenwahl + ENTSCHEIDUNG-31): das kleine
    # 3B-Modell verschluckt bei Eigennamen/Freitext Umlaut/ß (Süd→Söd, Verlängerung→Verlögerung). Für die
    # vorab eingelesenen, vom Menschen geprüften Kacheln werden die ANZEIGE-Textfelder `partner` und
    # `pflicht` auf den Soll-Wert des Dokuments gesetzt — exakt die Mensch-im-Loop-Korrektur, die vor der
    # Freigabe ohnehin passiert → sauberes, professionelles Board + reproduzierbar. stichtag/vorlauf
    # bleiben die ECHTE KI-Ausgabe (treiben die Ampel, im Test 100 % korrekt). Der LIVE-HELD wird NICHT
    # geseedet/normalisiert → seine Kachel zeigt unveränderte rohe KI-Ausgabe (deshalb pflicht umlautfrei).
    for d in docs:
        p = d["partner"].replace("'", "''")
        pf = d["pflicht"].replace("'", "''")
        L.psql(f"UPDATE audit_log SET partner='{p}', pflicht='{pf}' WHERE doc_name='{d['doc_name']}';")

    # Teilmenge freigeben (über den echten Freigabe-Webhook → wie im Recording, idempotent).
    if do_approve:
        for name in names:
            if name in APPROVE:
                rid = L.psql(f"SELECT id FROM audit_log WHERE doc_name='{name}' ORDER BY id DESC LIMIT 1;")
                if rid:
                    L.freigeben(int(rid))
                    print(f"  ✓ freigegeben: {name}")
        # approved_at ebenfalls zurückdatieren (Freigabe geschah „vor dem Take").
        L.psql(
            f"UPDATE audit_log SET approved_at = now() - interval '{BACKDATE_APPROVE}' "
            f"WHERE approved = true AND approved_at IS NOT NULL;"
        )

    # Zusammenfassung
    mix = L.psql(
        "SELECT ampel||':'||count(*) FROM ("
        "  SELECT DISTINCT ON (doc_name) doc_name, ampel FROM audit_log ORDER BY doc_name, run_at DESC, id DESC"
        ") t GROUP BY ampel ORDER BY ampel;"
    ).replace("\n", "  ")
    napp = L.psql("SELECT count(*) FILTER (WHERE approved) FROM audit_log;")
    print(f"\nBoard: {len(names)} Kacheln · Ampel-Mix [{mix}] · freigegeben: {napp}")
    print("Held NICHT geseedet — im Recording live per Mail einspielen (python3 testdata/send_test_mail.py).")
    return 0


if __name__ == "__main__":
    raise SystemExit(seed(do_approve="--no-approve" not in sys.argv))
