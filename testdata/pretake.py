#!/usr/bin/env python3
# =============================================================================
#  pretake.py — EIN Kommando für den Aufnahmetag. Bringt die Demo in den
#  drehbuchreifen Startzustand und prüft alles, was der Take braucht.
#  Reihenfolge (DREHBUCH.md §2 / SETUP.md §9.10):
#    (a) build_pdfs.py        → Stichtage heute-relativ, Ampel-Mix 2 rot/2 gelb/2 grün
#    (b) 3 Container laufen?   → fw_postgres (healthy), fw_n8n, fw_greenmail
#    (c) Ollama warm?          → Modell resident (sonst warmlaufen + erneut prüfen)
#    (d) reset_demo.py         → audit_log+Postfach leeren, 5 Docs seeden, 3 freigegeben, Held ausgespart
#    (e) Health-Checks         → WF-B+WF-C aktiv; Webhooks 200; 3 Ansichten da; Seed-Stand; Postfach leer
#    (f) Klartext: READY ✅ / NICHT READY ❌  (+ was fehlt)
#
#  Idempotent (beliebig oft laufbar), komplett LOKAL (nur 127.0.0.1 + docker/ollama-CLI),
#  gibt KEINE Secrets aus. Exit-Code 0 = READY, 1 = NICHT READY.
#
#  Lauf:  python3 testdata/pretake.py            (Standard: 3 vorab freigeben)
#         python3 testdata/pretake.py --no-approve   (externe Ansicht startet leer, Szene-7-Variante)
# =============================================================================
import subprocess
import sys
import time
import urllib.request

import demo_lib as L

OLLAMA_MODEL = L.ENV.get("OLLAMA_MODEL", "llama3.2:3b")
CONTAINERS = ["fw_postgres", "fw_n8n", "fw_greenmail"]
WEBHOOKS = ["dashboard", "fristen-data", "extern", "extern-data", "audit-log"]
NO_APPROVE = "--no-approve" in sys.argv

# Erwarteter Seed-Stand nach reset (Held ausgespart): 5 Nicht-Helden-Docs, davon 3 freigegeben
# (bei --no-approve: 0 freigegeben). Werte aus den Skripten abgeleitet, nicht hartcodiert geraten.
SEED_DOCS = len(L.recording_docs(include_hero=False))           # = 5
SEED_APPROVED = 0 if NO_APPROVE else 3                          # APPROVE-Set in seed_demo.py


# ---------- kleine Helfer ----------
def hr():
    print("─" * 60)


def run(cmd, **kw):
    """subprocess.run mit Text-Ausgabe; FileNotFoundError sauber abfangen."""
    try:
        return subprocess.run(cmd, text=True, **kw)
    except FileNotFoundError as e:
        return subprocess.CompletedProcess(cmd, 127, "", str(e))


def http_status(path: str) -> int:
    try:
        with urllib.request.urlopen(f"{L.N8N}/webhook/{path}", timeout=10) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except Exception:
        return 0


def fetch(path: str) -> str:
    try:
        with urllib.request.urlopen(f"{L.N8N}/webhook/{path}", timeout=10) as r:
            return r.read().decode("utf-8", "replace")
    except Exception:
        return ""


checks = []  # (ok: bool, zeile: str)


def ok(zeile):
    checks.append((True, zeile))
    print(f"    ✓ {zeile}")


def bad(zeile):
    checks.append((False, zeile))
    print(f"    ✗ {zeile}")


# =============================================================================
def main() -> int:
    print("═" * 60)
    print("  PRE-TAKE — Fristen- & Verpflichtungswächter")
    print(f"  Variante: {'externe Ansicht startet LEER (--no-approve)' if NO_APPROVE else 'Standard (3 vorab freigegeben)'}")
    print("═" * 60)

    # ---- (a) PDFs neu bauen (heute-relativer Ampel-Mix) ----
    print("\n[a] PDFs + fristen.csv neu bauen (Stichtage heute-relativ) …")
    r = run([sys.executable, str(L.HERE / "build_pdfs.py")], capture_output=True)
    mix_line = next((ln for ln in (r.stdout or "").splitlines() if "Kuratiertes Board" in ln), "")
    if r.returncode == 0 and "2 rot / 2 gelb / 2 grün" in mix_line:
        ok(f"Board-Ampel-Mix stimmt: {mix_line.split(':',1)[-1].strip()}")
    elif r.returncode == 0:
        bad(f"Board-Ampel-Mix NICHT 2/2/2: {mix_line or '(keine Mix-Zeile)'}")
    else:
        bad(f"build_pdfs.py fehlgeschlagen (reportlab installiert? `pip3 install reportlab`): {(r.stderr or '').strip()[:160]}")

    # ---- (b) Container ----
    print("\n[b] Container (3) prüfen …")
    ps = run(["docker", "ps", "--format", "{{.Names}}|{{.Status}}"], capture_output=True)
    status_by_name = {}
    for ln in (ps.stdout or "").splitlines():
        if "|" in ln:
            n, s = ln.split("|", 1)
            status_by_name[n.strip()] = s.strip()
    containers_ok = True
    for c in CONTAINERS:
        s = status_by_name.get(c, "")
        if s.startswith("Up") and (c != "fw_postgres" or "healthy" in s):
            ok(f"{c}: {s}")
        else:
            bad(f"{c}: {s or 'NICHT GEFUNDEN'}")
            containers_ok = False

    # ---- (c) Ollama warm ----
    print("\n[c] Ollama warmlaufen + resident prüfen …")
    def ollama_resident() -> bool:
        r = run(["ollama", "ps"], capture_output=True)
        return any(OLLAMA_MODEL in ln for ln in (r.stdout or "").splitlines()[1:])
    ollama_ok = False
    if ollama_resident():
        ok(f"{OLLAMA_MODEL} bereits resident")
        ollama_ok = True
    else:
        print(f"      … nicht resident — warmlaufen ({OLLAMA_MODEL}) …")
        run(["ollama", "run", OLLAMA_MODEL, "Sag nur: bereit"], capture_output=True)
        if ollama_resident():
            ok(f"{OLLAMA_MODEL} warmgelaufen (resident)")
            ollama_ok = True
        else:
            bad(f"{OLLAMA_MODEL} NICHT resident — läuft die Ollama-App? (`ollama ps`)")

    # ---- (c+) IMAP-Tracking (Kaltstart-Selbstheilung, vor dem Seeden!) ----
    print("\n[c+] IMAP-Tracking prüfen (GreenMail-Kaltstart) …")
    if containers_ok:
        if L.imap_tracking_stale():
            t, n = L.wfc_tracked_uid(), L.imap_uidnext()
            print(f"      … WF-C merkt UID {t} ≥ UIDNEXT {n} (GreenMail neu gestartet) → staticData "
                  f"zurücksetzen (kurzer n8n-Neustart) …")
            L.reset_imap_tracking()
            if L.imap_tracking_stale():
                bad("IMAP-Tracking weiter veraltet — Mail-Einlesen würde scheitern (manuell prüfen)")
            else:
                ok("IMAP-Tracking zurückgesetzt — WF-C liest neue Mails wieder ein")
        else:
            ok("IMAP-Tracking aktuell (kein Reset nötig)")
    else:
        bad("IMAP-Tracking-Prüfung übersprungen — Container nicht bereit")

    # ---- (d) reset_demo (braucht Stack + Ollama) ----
    print("\n[d] Demo zurücksetzen (audit_log + Postfach leeren, neu seeden) …")
    if containers_ok and ollama_ok:
        cmd = [sys.executable, str(L.HERE / "reset_demo.py")] + (["--no-approve"] if NO_APPROVE else [])
        rr = run(cmd)  # Fortschritt sichtbar lassen (LLM-Einlesen dauert ein paar Sekunden)
        if rr.returncode == 0:
            ok("reset_demo erfolgreich (Board geseedet, Held ausgespart)")
        else:
            bad("reset_demo fehlgeschlagen — Seed-Stand unten prüfen")
    else:
        bad("reset_demo ÜBERSPRUNGEN — Stack/Ollama nicht bereit (siehe oben)")

    # ---- (e) Health-Checks ----
    print("\n[e] Health-Checks …")

    # WF-B + WF-C aktiv?
    wf = run(["docker", "exec", "fw_n8n", "n8n", "list:workflow", "--active=true"], capture_output=True)
    wf_out = wf.stdout or ""
    (ok if "Dashboard-Server" in wf_out else bad)("WF-B (Dashboard-Server) aktiv")
    (ok if "Mail-Ingestion" in wf_out else bad)("WF-C (Mail-Ingestion) aktiv")

    # Webhooks → HTTP 200
    codes = {p: http_status(p) for p in WEBHOOKS}
    if all(c == 200 for c in codes.values()):
        ok("Webhooks 200: " + " · ".join(f"/{p}" for p in WEBHOOKS))
    else:
        bad("Webhooks NICHT alle 200: " + " · ".join(f"/{p}={c}" for p, c in codes.items()))

    # Drei Ansichten im ausgelieferten Dashboard?
    html = fetch("dashboard")
    drei = [('view-pruefen', 'Zu prüfen'), ('view-frei', 'Freigegeben'), ('view-audit', 'Audit-Log')]
    fehlend = [name for vid, name in drei if vid not in html]
    if not fehlend and "switchView('pruefen')" in html:
        ok("Drei Ansichten erreichbar: Zu prüfen · Freigegeben · Audit-Log (Default = Zu prüfen)")
    else:
        bad(f"Ansichten fehlen im HTML: {', '.join(fehlend) or '(switchView pruefen?)'}")

    # Seed-Stand: Anzahl Docs, Freigegebene, Held nicht im Board
    import json
    try:
        rows = json.loads(fetch("fristen-data") or "[]")
    except Exception:
        rows = []
    docs = {r.get("doc_name") for r in rows}
    n_app = sum(1 for r in rows if r.get("approved") in (True, "t", "true", 1))
    held_da = L.HERO in docs
    if len(rows) == SEED_DOCS and not held_da:
        ok(f"Seed-Stand: {len(rows)} Kacheln, Held ({L.HERO}) NICHT im Board")
    else:
        bad(f"Seed-Stand falsch: {len(rows)} Kacheln (erwartet {SEED_DOCS}), Held im Board: {held_da}")
    if n_app == SEED_APPROVED:
        ok(f"Freigegeben: {n_app} (erwartet {SEED_APPROVED})")
    else:
        bad(f"Freigegeben: {n_app} (erwartet {SEED_APPROVED})")

    # Keine UNGELESENEN (UNSEEN) Mails offen? Die geseedeten Mails sind nach dem Einlesen SEEN und
    # bleiben als „Historie" im Postfach (postProcessAction:'read' löscht nicht — war im Original ebenso);
    # sie stören den Take nicht (das Board kommt aus der DB). Relevant ist nur: keine PENDING/Held-Mail offen.
    try:
        n_unseen = L.unseen_count()
    except Exception:
        n_unseen = -1
    if n_unseen == 0:
        ok("Keine ungelesenen Mails offen (Held-Mail noch nicht gesendet)")
    elif n_unseen < 0:
        bad("Postfach nicht erreichbar (GreenMail/IMAP?)")
    else:
        bad(f"{n_unseen} ungelesene Mail(s) offen — Probelauf/Reset vor dem Take prüfen")

    # ---- (f) Verdikt ----
    print()
    hr()
    fehler = [z for okk, z in checks if not okk]
    if not fehler:
        print("READY ✅  — aufnahmebereit.")
        print("Nächster Schritt (Probelauf):  python3 testdata/send_test_mail.py")
        print('→ erscheint die hervorgehobene Held-Kachel in „Zu prüfen“? Dann nochmal:')
        print("   python3 testdata/pretake.py   (sauberer Startzustand) und aufnehmen (DREHBUCH.md).")
        hr()
        return 0
    print(f"NICHT READY ❌  — {len(fehler)} Punkt(e) offen:")
    for z in fehler:
        print(f"   • {z}")
    hr()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
