# LLM-Treffer-Quote — Ollama-Extraktion vs. CSV-Ground-Truth

> Belegt ENTSCHEIDUNG-21. Misst, wie zuverlässig das **lokale** Modell die 4 Felder aus PDF-Dokumenten
> ausliest. Reproduzierbar: `python3 scripts/extract_test.py`.

## Rahmen
- **Modell:** `llama3.2:3b` (lokal über Ollama, ENTSCHEIDUNG-17) · **Temperatur:** 0 · **`format: json`**
- **Eingabe:** PDF-Text, extrahiert wie in n8n (pdf-parse/pdfjs ≈ pypdf)
- **Rechner:** Apple M2, 8 GB · **Latenz:** Kaltstart ~7 s, danach ~2,5 s/Dokument
- **Stichprobe:** **10 Demo-Dokumente** aus verschiedenen Branchen (Logistik, Prüfwesen, Medizintechnik,
  Förderung, Versicherung, Gewerbemiete, ISO-Zertifizierung, Leasing, Brandschutz, Eichung). Seit M4 sind
  alle 10 echte Demo-Dokumente — Single Source `testdata/build_pdfs.py` → PDFs **und** `testdata/fristen.csv`;
  die frühere eval/-Aufteilung entfällt (ENTSCHEIDUNG-26).
- **Gemessen am:** 2026-06-19. Ground-Truth = `fristen.csv` (dieselben 10 Dokumente).

## Ergebnis

| Auswertung | n | JSON gültig | stichtag | vorlauf_tage | partner | **harte Felder** | Dok. komplett |
|---|---:|---:|---:|---:|---:|---:|---:|
| **Alle Demo-Dokumente** | 10 | 100 % | **100 %** | **100 %** | 80 % | **28/30 = 93 %** | 8/10 = 80 % |

*„Harte Felder" = partner + stichtag + vorlauf_tage. `pflicht` ist Freitext → separat als
Token-Überlappung (umlaut-tolerant) ausgewiesen, nicht in der harten Quote.*

### Die beiden Abweichungen (über alle 10 Dokumente)
| Dokument | Feld | LLM | SOLL |
|---|---|---|---|
| Maschinenpruefung_UVV | partner | `Prüfstelle Söd GmbH` | `Prüfstelle Süd GmbH` |
| Gewerbemietvertrag_Lager | partner | `…Hansestra∶ GbR` | `…Hansestraße GbR` |

Beide sind **dasselbe Muster: Umlaut/ß in einem Eigennamen** (ü→ö, ß→Sonderzeichen).

## Einordnung (Story-Kern)
- **Alle 10 Stichtage und alle 10 Vorlaufzeiten — die sicherheitskritischen, deterministisch
  weiterverrechneten Werte — sind 100 % korrekt.** Genau diese Werte gehen in Knoten 8
  (Warndatum/Ampel/Eskalation). Das kleine Modell liefert der Engine also durchgängig korrekte Inputs.
- Die einzige Schwäche sind **Umlaute/ß in Eigennamen** — ein bekanntes Verhalten kleiner Modelle.
  Das untermauert die Architektur:
  - **Mensch-Freigabe** (M4) fängt solche Lesefehler vor jeder Eskalation ab.
  - **CSV-Pfad** (ENTSCHEIDUNG-10/-12) garantiert einen fehlerfreien Take (LLM ist nicht-deterministisch).
  - Der LLM-Pfad ist das **„die KI liest direkt aus dem PDF"-Wow**, nicht das Zuverlässigkeits-Rückgrat.

## Prompt-Tuning (Verlauf)
1. Basis (`format:json`, temp 0): ein Fehler war eine **Übersetzung** des Eigennamens (`Süd`→`South`).
2. Regel „Eigennamen exakt, nicht übersetzen, Umlaute behalten": Übersetzung weg; Restfehler =
   Umlaut-Verhaspler. Diese Regel steht **identisch** im n8n-Knoten „Prompt bauen".

## Methodik-Hinweis
- Alle 10 sind echte Demo-Dokumente und laufen durch n8n (CSV-Pfad: 10 Zeilen live verifiziert; der
  LLM-Pfad wurde für die ursprünglichen Demo-Docs end-to-end bestätigt — `source_mode='llm'` in `audit_log`,
  gleiche Treffer wie offline).
- Die Messung ist eine **Extraktions-Benchmark** mit **wortgleichem** Prompt/Modell/Extraktor wie im
  n8n-Knoten „Prompt bauen" (synchron halten).
- **`partner` wird EXAKT gewertet** (umlaut-empfindlich, nur Whitespace/Groß-Klein normalisiert) — `Söd`
  zählt als Fehler, obwohl semantisch fast richtig. Die Quote ist also eher streng als geschönt.
- **Determinismus:** `temperature:0` reduziert Streuung, garantiert aber **keinen** Bit-Determinismus
  (Sampling/GPU/llama.cpp). Die 93 % sind an **einem** Lauf (2026-06-19) gemessen und können um ±1 Feld
  schwanken; **Stichtag und Vorlauf waren über die beobachteten Läufe stabil 100 %**. Stichprobe n=10 =
  Demo-Maßstab, keine Produktions-Kennzahl. Kein Daten-Tuning zum „Schönen" der Zahl.
