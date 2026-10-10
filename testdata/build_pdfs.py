#!/usr/bin/env python3
# =============================================================================
#  Erzeugt die 10 Demo-PDFs + die Ground-Truth-CSV (fristen.csv) — alles aus EINER
#  Quelle (die Liste DOCS unten), lokal via reportlab. Single Source: dieses Skript
#  schreibt sowohl die PDFs (testdata/*.pdf) als auch fristen.csv (CSV-Pfad-Eingabe
#  UND Ground-Truth für die Treffer-Quote, ENTSCHEIDUNG-21).
#
#  Alle Firmen/Stellen sind FIKTIV (R5). Jede Seite: "BEISPIELDOKUMENT" + Disclaimer.
#  Felder stehen im FLIESSTEXT (Datum als "17. August 2026" → LLM muss nach ISO wandeln).
#  Stichtage geben relativ zu „heute" einen Ampel-Mix; der echte Aufnahmetag wird in M6
#  per Skript nachgesetzt (Risiko R3).
#
#  Lauf:  python3 testdata/build_pdfs.py
# =============================================================================
import csv
from datetime import date, timedelta
from pathlib import Path
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_JUSTIFY
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib import colors

HERE = Path(__file__).resolve().parent
CSV_PATH = HERE / "fristen.csv"

MONATE = ["", "Januar", "Februar", "März", "April", "Mai", "Juni",
          "Juli", "August", "September", "Oktober", "November", "Dezember"]

# "heute" als Europe/Berlin-Kalendertag — passend zur KI-freien Logik in Knoten 8
# (n8n bildet "heute" ebenfalls in Europe/Berlin). zoneinfo wenn vorhanden, sonst lokal.
try:
    from datetime import datetime
    from zoneinfo import ZoneInfo
    TODAY = datetime.now(ZoneInfo("Europe/Berlin")).date()
except Exception:
    TODAY = date.today()

# Ampel-Logik (gespiegelt aus Knoten 8): warndatum = stichtag - vorlauf_tage,
# resttage = warndatum - heute = warn_offset. resttage<=0 -> rot, 1..14 -> gelb, >=15 -> gruen.
GELB_SCHWELLE_TAGE = 14
def ampel_of(warn_offset: int) -> str:
    if warn_offset <= 0:
        return "rot"
    if warn_offset <= GELB_SCHWELLE_TAGE:
        return "gelb"
    return "gruen"

def stichtag_iso(warn_offset: int, vorlauf_tage: int) -> str:
    """Stichtag heute-relativ: warndatum = heute + warn_offset, stichtag = warndatum + vorlauf."""
    return (TODAY + timedelta(days=warn_offset + vorlauf_tage)).isoformat()

def datum_lang(iso: str) -> str:
    y, m, d = (int(x) for x in iso.split("-"))
    return f"{d}. {MONATE[m]} {y}"

# Brief-Körper: {partner} {datum} {vorlauf} {pflicht} werden eingesetzt. Keine weiteren { }.
B_RAHMEN = ("Sehr geehrte Damen und Herren,<br/><br/>wir möchten Sie auf die Laufzeitregelung des mit "
    "der {partner} geschlossenen Rahmenvertrags über Logistikdienstleistungen hinweisen.<br/><br/>"
    "Der Vertrag verlängert sich automatisch um ein weiteres Jahr, sofern er nicht rechtzeitig gekündigt "
    "wird. Maßgeblicher Stichtag (Ablauf der aktuellen Laufzeit) ist der <b>{datum}</b>.<br/><br/>"
    "Eine Kündigung muss spätestens <b>{vorlauf} Tage</b> vor diesem Stichtag schriftlich vorliegen — "
    "andernfalls greift die automatische Verlängerung.<br/><br/>Erforderliche Maßnahme: {pflicht}.<br/><br/>"
    "Mit freundlichen Grüßen<br/>{partner}")
B_UVV = ("Sehr geehrte Damen und Herren,<br/><br/>als zuständige Prüforganisation weist die {partner} Sie "
    "auf die nächste fällige wiederkehrende Prüfung Ihrer Förderanlage hin (UVV-Prüfung gemäß DGUV V3)."
    "<br/><br/>Der Stichtag, bis zu dem die Prüfung durchgeführt sein muss, ist der <b>{datum}</b>.<br/><br/>"
    "Bitte vereinbaren Sie den Prüftermin spätestens <b>{vorlauf} Tage</b> vor diesem Stichtag.<br/><br/>"
    "Gegenstand: {pflicht}.<br/><br/>Mit freundlichen Grüßen<br/>{partner}")
B_STK = ("Sehr geehrte Damen und Herren,<br/><br/>für die in Ihrem Bestand geführte Infusionspumpe ist "
    "gemäß Medizinprodukte-Betreiberverordnung (MPBetreibV) die nächste Sicherheitstechnische Kontrolle "
    "(STK) fällig. Verantwortliche Stelle: {partner}.<br/><br/>Der Stichtag für die Durchführung ist der "
    "<b>{datum}</b>.<br/><br/>Wir bitten darum, den Termin spätestens <b>{vorlauf} Tage</b> vor dem Stichtag "
    "anzumelden.<br/><br/>Durchzuführende Maßnahme: {pflicht}.<br/><br/>Mit freundlichen Grüßen<br/>{partner}")
B_FOERDER = ("Sehr geehrte Damen und Herren,<br/><br/>im Rahmen des bewilligten Digitalbonus weist die "
    "{partner} auf die Frist zur Einreichung des Verwendungsnachweises hin.<br/><br/>Der Verwendungsnachweis "
    "ist bis zum Stichtag <b>{datum}</b> einzureichen.<br/><br/>Wir empfehlen, die Unterlagen spätestens "
    "<b>{vorlauf} Tage</b> vor diesem Stichtag vorzubereiten.<br/><br/>Erforderlich: {pflicht}.<br/><br/>"
    "Mit freundlichen Grüßen<br/>{partner}")
B_VERS = ("Sehr geehrte Damen und Herren,<br/><br/>Ihre Betriebshaftpflicht bei der {partner} verlängert "
    "sich automatisch, falls keine Kündigung erfolgt. Stichtag des Ablaufs ist der <b>{datum}</b>. Eine "
    "Kündigung muss spätestens <b>{vorlauf} Tage</b> vorher eingehen.<br/><br/>Maßnahme: {pflicht}.<br/><br/>"
    "Mit freundlichen Grüßen<br/>{partner}")
B_MIETE = ("Sehr geehrte Mieterin, sehr geehrter Mieter,<br/><br/>der Mietvertrag über die Lagerfläche läuft "
    "zum <b>{datum}</b> aus. Die {partner} weist darauf hin, dass eine Verlängerungsoption spätestens "
    "<b>{vorlauf} Tage</b> vor diesem Stichtag ausgeübt werden muss.<br/><br/>Erforderlich: {pflicht}.<br/><br/>"
    "Mit freundlichen Grüßen<br/>{partner}")
B_ISO = ("Sehr geehrte Damen und Herren,<br/><br/>Ihr durch die {partner} ausgestelltes Zertifikat nach "
    "ISO/IEC 27001 verliert zum Stichtag <b>{datum}</b> seine Gültigkeit. Das Rezertifizierungs-Audit sollte "
    "spätestens <b>{vorlauf} Tage</b> vorher beauftragt werden.<br/><br/>Maßnahme: {pflicht}.<br/><br/>"
    "Mit freundlichen Grüßen<br/>{partner}")
B_LEASING = ("Sehr geehrte Damen und Herren,<br/><br/>der Leasingvertrag für Ihren Fuhrpark bei der {partner} "
    "endet am <b>{datum}</b>. Bitte klären Sie spätestens <b>{vorlauf} Tage</b> vor diesem Stichtag das weitere "
    "Vorgehen.<br/><br/>Zu veranlassen: {pflicht}.<br/><br/>Mit freundlichen Grüßen<br/>{partner}")
B_BRAND = ("Sehr geehrte Damen und Herren,<br/><br/>die {partner} erinnert an die wiederkehrende Prüfung Ihrer "
    "Feuerlöscher nach DIN 14406-4. Der Stichtag der nächsten Prüfung ist der <b>{datum}</b>; bitte den Termin "
    "spätestens <b>{vorlauf} Tage</b> vorher vereinbaren.<br/><br/>Gegenstand: {pflicht}.<br/><br/>"
    "Mit freundlichen Grüßen<br/>{partner}")
B_EICH = ("Sehr geehrte Damen und Herren,<br/><br/>die Eichung Ihrer Ladenwaage läuft zum Stichtag <b>{datum}</b> "
    "ab (MessEG/MessEV). Das {partner} empfiehlt, die Nacheichung spätestens <b>{vorlauf} Tage</b> vorher zu "
    "beauftragen.<br/><br/>Erforderlich: {pflicht}.<br/><br/>Mit freundlichen Grüßen<br/>{partner}")

# Alle 10 Demo-Dokumente. Stichtage werden HEUTE-RELATIV berechnet (warn_offset = Tage von heute
# bis zum Warndatum) → der Ampel-Mix stimmt automatisch am Tag des Laufs. Am echten Aufnahmetag
# einfach erneut `python3 testdata/build_pdfs.py` laufen lassen (Risiko R3 erledigt sich von selbst).
#
# KURATIERUNG (~6 Kacheln, ENTSCHEIDUNG-26): fürs Recording zeigt das Seed-
# Skript (testdata/seed_demo.py) nur die mit recording=True markierten 6 → exakt 2 rot / 2 gelb / 2 grün.
# Der HELD (Rahmenvertrag_Logistik) ist recording=True, wird aber NICHT geseedet, sondern live per Mail
# eingespielt. Die übrigen 4 PDFs bleiben erhalten (Retake-Reserve, ENTSCHEIDUNG-26), erscheinen aber
# nicht auf dem kuratierten Board.
#   warn_offset <= 0  -> rot (Warndatum erreicht/überschritten)
#   1..14             -> gelb (Vorwarnung)
#   >= 15             -> grün
DOCS = [
    # HELD (live per Mail): pflicht bewusst UMLAUTFREI gehalten, damit die ROHE KI-Ausgabe im Take
    # sauber liest (das 3B-Modell verschluckt sonst Umlaute, z. B. Verlängerung→Verlögerung). Der
    # Held wird NICHT geseedet/normalisiert → seine Anzeige ist echte, unveränderte KI-Ausgabe (R3/R4).
    {"doc_name":"Rahmenvertrag_Logistik.pdf", "partner":"Spedition Nordfracht GmbH",
     "warn_offset":-5, "vorlauf_tage":90, "recording":True, "held":True,
     "pflicht":"Rahmenvertrag fristgerecht beenden",
     "betreff":"Rahmenvertrag Logistikdienstleistungen — Hinweis zur Vertragslaufzeit", "body":B_RAHMEN},
    {"doc_name":"Maschinenpruefung_UVV.pdf", "partner":"Prüfstelle Süd GmbH",
     "warn_offset":-8, "vorlauf_tage":30, "recording":True,
     "pflicht":"Wiederkehrende UVV-Prüfung Förderanlage (DGUV V3)",
     "betreff":"Wiederkehrende UVV-/DGUV-V3-Prüfung Ihrer Förderanlage", "body":B_UVV},
    {"doc_name":"Medizingeraet_STK.pdf", "partner":"Klinikum Lindenau",
     "warn_offset":6, "vorlauf_tage":30, "recording":True,
     "pflicht":"Sicherheitstechnische Kontrolle STK Infusionspumpe (MPBetreibV)",
     "betreff":"Sicherheitstechnische Kontrolle (STK) — Infusionspumpe", "body":B_STK},
    {"doc_name":"Foerderbescheid_Digitalbonus.pdf", "partner":"Förderbank Musterland AöR",
     "warn_offset":11, "vorlauf_tage":30, "recording":True,
     "pflicht":"Verwendungsnachweis Digitalbonus einreichen",
     "betreff":"Förderbescheid Digitalbonus — Frist zum Verwendungsnachweis", "body":B_FOERDER},
    {"doc_name":"Gewerbemietvertrag_Lager.pdf", "partner":"Immobilienverwaltung Hansestraße GbR",
     "warn_offset":60, "vorlauf_tage":180, "recording":True,
     "pflicht":"Verlängerungsoption Gewerbemietvertrag schriftlich ausüben",
     "betreff":"Gewerbemietvertrag Lagerfläche — Verlängerungsoption", "body":B_MIETE},
    {"doc_name":"Zertifikat_ISO27001.pdf", "partner":"CertNord Zertifizierungsstelle GmbH",
     "warn_offset":40, "vorlauf_tage":30, "recording":True,
     "pflicht":"Rezertifizierungs-Audit ISO 27001 beauftragen",
     "betreff":"ISO/IEC 27001 — Ablauf des Zertifikats", "body":B_ISO},
    # --- Retake-Reserve (nicht auf dem kuratierten Board) ---
    {"doc_name":"Versicherung_Betriebshaftpflicht.pdf", "partner":"Musterland Sachversicherung AG",
     "warn_offset":50, "vorlauf_tage":90,
     "pflicht":"Kündigung Betriebshaftpflicht zum Ablauf (sonst Verlängerung um ein Jahr)",
     "betreff":"Betriebshaftpflicht — Hinweis auf Kündigungsfrist", "body":B_VERS},
    {"doc_name":"Leasing_Fuhrpark.pdf", "partner":"AutoLease Musterland GmbH",
     "warn_offset":9, "vorlauf_tage":30,
     "pflicht":"Rückgabe oder Anschlussvertrag Fuhrpark-Leasing klären",
     "betreff":"Leasingvertrag Fuhrpark — Vertragsende", "body":B_LEASING},
    {"doc_name":"Brandschutz_Feuerloescher.pdf", "partner":"Brandschutz Technik Mustermann e.K.",
     "warn_offset":-2, "vorlauf_tage":30,
     "pflicht":"Wiederkehrende Prüfung der Feuerlöscher (DIN 14406-4)",
     "betreff":"Wartung Feuerlöscher — nächster Prüftermin", "body":B_BRAND},
    {"doc_name":"Eichung_Ladenwaage.pdf", "partner":"Eichamt Musterland",
     "warn_offset":35, "vorlauf_tage":45,
     "pflicht":"Eichung der Ladenwaage erneuern (MessEG/MessEV)",
     "betreff":"Eichfrist Ladenwaage — Ablauf", "body":B_EICH},
]

def wasserzeichen(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica-Bold", 54)
    canvas.setFillColor(colors.Color(0.86, 0.86, 0.89))
    canvas.translate(A4[0] / 2, A4[1] / 2)
    canvas.rotate(45)
    canvas.drawCentredString(0, 0, "BEISPIELDOKUMENT")
    canvas.restoreState()
    canvas.saveState()
    canvas.setFont("Helvetica", 7.5)
    canvas.setFillColor(colors.Color(0.45, 0.45, 0.5))
    canvas.drawCentredString(A4[0] / 2, 12 * mm,
        "Beispieldokument für eine Demo — fiktive Firma/Stelle, keine realen personenbezogenen Daten.")
    canvas.restoreState()

_styles = getSampleStyleSheet()
BODY = ParagraphStyle("Body", parent=_styles["Normal"], fontName="Helvetica", fontSize=11, leading=16, alignment=TA_JUSTIFY)
ABS  = ParagraphStyle("Abs", parent=_styles["Normal"], fontName="Helvetica-Bold", fontSize=13, leading=16, textColor=colors.HexColor("#0f172a"))
BETR = ParagraphStyle("Betr", parent=_styles["Normal"], fontName="Helvetica-Bold", fontSize=11, leading=15, spaceBefore=4, spaceAfter=10)

def render_pdf(out_path, partner, betreff, body_filled):
    doc = SimpleDocTemplate(str(out_path), pagesize=A4, topMargin=28*mm, bottomMargin=24*mm,
                            leftMargin=25*mm, rightMargin=25*mm, title=out_path.name, author=partner)
    doc.build([Paragraph(partner, ABS), Spacer(1, 6*mm), Paragraph(betreff, BETR), Paragraph(body_filled, BODY)],
              onFirstPage=wasserzeichen, onLaterPages=wasserzeichen)

def main():
    print(f"heute = {TODAY.isoformat()} (Europe/Berlin) — Stichtage werden heute-relativ berechnet\n")
    mix = {"rot": 0, "gelb": 0, "gruen": 0}
    with CSV_PATH.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        # recording-Spalte: 1 = gehört aufs kuratierte Board (Seed-Skript filtert darauf), 0 = Reserve.
        w.writerow(["doc_name", "partner", "stichtag", "vorlauf_tage", "pflicht", "recording"])
        for d in DOCS:
            stichtag = stichtag_iso(d["warn_offset"], d["vorlauf_tage"])
            rec = 1 if d.get("recording") else 0
            f = {"partner": d["partner"], "datum": datum_lang(stichtag),
                 "vorlauf": str(d["vorlauf_tage"]), "pflicht": d["pflicht"]}
            render_pdf(HERE / d["doc_name"], d["partner"], d["betreff"].format(**f), d["body"].format(**f))
            w.writerow([d["doc_name"], d["partner"], stichtag, d["vorlauf_tage"], d["pflicht"], rec])
            ampel = ampel_of(d["warn_offset"])
            if rec:
                mix[ampel] += 1
            mark = "★ Board" if rec else "  Reserve"
            held = " (HELD → per Mail)" if d.get("held") else ""
            print(f"  ✓ {mark} {ampel:5} {d['doc_name']}  (Stichtag {stichtag}, Warndatum heute{d['warn_offset']:+d}){held}")
    print(f"\n{len(DOCS)} PDF(s) + fristen.csv in {HERE}")
    print(f"Kuratiertes Board (recording=1): {mix['rot']} rot / {mix['gelb']} gelb / {mix['gruen']} grün")

if __name__ == "__main__":
    main()
