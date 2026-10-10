#!/usr/bin/env python3
# =============================================================================
#  M3 — Extraktions-Messung: Ollama-Ausgabe vs. CSV-Ground-Truth (ENTSCHEIDUNG-21)
#  -------------------------------------------------------------------------
#  Misst, wie zuverlässig das LOKALE Modell die 4 Felder ausliest — über ALLE
#  Demo-Dokumente in testdata/fristen.csv (Single Source). Seit M4 konsolidiert: 10 Dokumente
#  (die frühere eval/-Aufteilung gibt es nicht mehr; alle 10 sind echte Demo-Dokumente).
#
#  Extrahiert den PDF-Text (pypdf ≈ n8n-pdf-parse) und schickt ihn mit GENAU dem Prompt
#  an Ollama, der im n8n-Code-Knoten "Prompt bauen" steht (synchron halten!).
#
#  Lauf:  python3 scripts/extract_test.py     (lokal, kein Cloud-API; Ollama auf :11434)
# =============================================================================
import csv, json, re, time, urllib.request
from pathlib import Path
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parent.parent
TESTDATA = ROOT / "testdata"
OLLAMA = "http://localhost:11434/api/generate"
MODEL = "llama3.2:3b"   # ENTSCHEIDUNG-17

PROMPT_VORLAGE = (
    "Du bist ein präzises Extraktionswerkzeug für deutsche Geschäftsdokumente.\n"
    "Lies das Dokument unten und gib AUSSCHLIESSLICH ein JSON-Objekt mit genau diesen "
    "vier Schlüsseln zurück:\n"
    '- "partner": Name der absendenden Firma oder Stelle (String).\n'
    '- "stichtag": der maßgebliche Stichtag / die Frist, im Format YYYY-MM-DD.\n'
    '- "vorlauf_tage": Vorlauf in Tagen vor dem Stichtag (ganze Zahl).\n'
    '- "pflicht": kurze Beschreibung der erforderlichen Maßnahme/Pflicht (String).\n'
    'Regeln: Wandle Datumsangaben wie "17. August 2026" nach "2026-08-17" um. '
    "Gib Firmen-, Stellen- und Eigennamen EXAKT wie im Dokument wieder — "
    "übersetze sie nicht und behalte deutsche Umlaute (ä, ö, ü, ß) bei. "
    "Gib nur das JSON zurück, keinen weiteren Text.\n"
    "Beispiel für ein ANDERES Dokument:\n"
    '{"partner":"Aufzugswartung Beispiel GmbH","stichtag":"2026-05-04",'
    '"vorlauf_tage":21,"pflicht":"Wartungstermin Aufzug vereinbaren"}\n\n'
    'DOKUMENT:\n"""\n{text}\n"""'
)

def pdf_text(path: Path) -> str:
    return "\n".join(p.extract_text() or "" for p in PdfReader(str(path)).pages)

def ollama(prompt: str) -> str:
    body = json.dumps({
        "model": MODEL, "prompt": prompt, "stream": False,
        "format": "json", "options": {"temperature": 0}, "keep_alive": "10m",
    }).encode("utf-8")
    req = urllib.request.Request(OLLAMA, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=180) as r:
        return json.loads(r.read())["response"]

def norm(s: str) -> str:
    return re.sub(r"\s+", " ", str(s or "")).strip().casefold()

_UML = str.maketrans({"ä": "a", "ö": "o", "ü": "u"})
def tokens(s: str):
    # Umlaute falten → faire Bewertung des Freitext-Felds (Modell verhaspelt Umlaute, trifft Sinn).
    return set(re.findall(r"\w+", norm(s).translate(_UML)))

def pflicht_score(a, b) -> float:
    ta, tb = tokens(a), tokens(b)
    return len(ta & tb) / len(ta | tb) if (ta | tb) else 0.0

def measure(csv_path: Path, pdf_dir: Path, label: str):
    truth = {r["doc_name"]: r for r in csv.DictReader(csv_path.open(encoding="utf-8"))}
    out = []
    for name, t in truth.items():
        pdf = pdf_dir / name
        if not pdf.exists():
            print(f"  ! {label}/{name} fehlt"); continue
        t0 = time.time()
        try:
            got = json.loads(ollama(PROMPT_VORLAGE.replace("{text}", pdf_text(pdf)))); ok = True
        except Exception as e:
            got, ok = {}, False; print(f"  ! {label}/{name}: {e}")
        dt = time.time() - t0
        p = norm(got.get("partner")) == norm(t["partner"])
        s = str(got.get("stichtag", "")).strip() == t["stichtag"]
        try:
            v = int(got.get("vorlauf_tage")) == int(t["vorlauf_tage"])
        except (TypeError, ValueError):
            v = False
        out.append([label, name, ok, p, s, v, pflicht_score(got.get("pflicht"), t["pflicht"]), dt, got, t])
    return out

def print_table(rows):
    print(f"\n{'Set':<6}{'Dokument':<36}{'JSON':>5}{'Part':>6}{'Stchtg':>7}{'Vorl':>6}{'Pfl~':>7}{'s':>6}")
    print("-" * 86)
    mk = lambda b: " OK" if b else " --"
    for label, name, ok, p, s, v, pf, dt, got, t in rows:
        print(f"{label:<6}{name:<36}{mk(ok):>5}{mk(p):>6}{mk(s):>7}{mk(v):>6}{pf:>6.2f}{dt:>6.1f}")

def summary(rows, title):
    n = len(rows)
    if not n:
        return
    hh = sum(r[3] + r[4] + r[5] for r in rows); ht = 3 * n
    docok = sum(1 for r in rows if r[3] and r[4] and r[5])
    js = sum(1 for r in rows if r[2])
    ps = sum(1 for r in rows if r[3]); ss = sum(1 for r in rows if r[4]); vs = sum(1 for r in rows if r[5])
    print(f"\n[{title}]  n={n}")
    print(f"  JSON {js}/{n} | partner {ps}/{n} | stichtag {ss}/{n} | vorlauf {vs}/{n}")
    print(f"  HARTE FELDER {hh}/{ht} = {100*hh/ht:.0f}%  |  Dokumente komplett {docok}/{n} = {100*docok/n:.0f}%")

def main():
    allrows = measure(TESTDATA / "fristen.csv", TESTDATA, "DOK")

    print("=" * 86)
    print_table(allrows)
    print("-" * 86)
    summary(allrows, "Alle Demo-Dokumente (fristen.csv)")
    print("\npflicht = Freitext (Token-Überlappung, umlaut-tolerant), NICHT in der harten Quote.")

    print("\nAbweichungen (harte Felder):")
    dev = False
    for label, name, ok, p, s, v, pf, dt, got, t in allrows:
        if not p:
            print(f"  {label}/{name} · partner: '{got.get('partner')}' != '{t['partner']}'"); dev = True
        if not s:
            print(f"  {label}/{name} · stichtag: '{got.get('stichtag')}' != '{t['stichtag']}'"); dev = True
        if not v:
            print(f"  {label}/{name} · vorlauf_tage: '{got.get('vorlauf_tage')}' != '{t['vorlauf_tage']}'"); dev = True
    if not dev:
        print("  keine — alle harten Felder korrekt.")

if __name__ == "__main__":
    main()
