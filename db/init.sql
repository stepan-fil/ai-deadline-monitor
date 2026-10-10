-- ============================================================
--  Fristen- & Verpflichtungswächter — Datenbank-Schema
--  ------------------------------------------------------------
--  Eine Tabelle reicht: audit_log.
--  Wird beim ERSTEN Postgres-Start automatisch ausgeführt
--  (gemountet nach /docker-entrypoint-initdb.d/, siehe docker-compose.yml).
--  Quelle/Spec: docs/03_ARCHITECTURE.md §4
--
--  Trennung der Verantwortung (Story-Kern):
--    • Spalten "vom LLM/CSV gelesen"  → partner, stichtag, vorlauf_tage, pflicht
--    • Spalten "deterministisch berechnet" → warndatum, resttage, ampel,
--      eskalationsstufe, resttage_stichtag
-- ============================================================

CREATE TABLE IF NOT EXISTS audit_log (
  id                 SERIAL PRIMARY KEY,
  run_at             TIMESTAMPTZ DEFAULT now(),     -- Zeitpunkt des Laufs
  source_mode        TEXT,                          -- 'llm' | 'csv'
  doc_name           TEXT,                          -- z. B. "Rahmenvertrag.pdf"

  -- ----- vom LLM bzw. aus der CSV GELESEN -----
  partner            TEXT,
  stichtag           DATE,
  vorlauf_tage       INT,
  pflicht            TEXT,

  -- ----- deterministisch BERECHNET (KI-frei) -----
  warndatum          DATE,                          -- stichtag - vorlauf_tage
  resttage           INT,                           -- warndatum - heute
  resttage_stichtag  INT,                           -- stichtag  - heute (nur fürs Dashboard)
  ampel              TEXT,                           -- 'gruen' | 'gelb' | 'rot'
  eskalationsstufe   INT,                           -- gruen->0, gelb->1, rot->2

  -- ----- Mensch-Freigabe -----
  approved           BOOLEAN DEFAULT false,
  approved_at        TIMESTAMPTZ,
  resume_url         TEXT,                          -- LEGACY/ungenutzt seit M4 (ENTSCHEIDUNG-25: Freigabe
                                                    -- läuft über /webhook/freigeben + UPDATE, nicht über Wait/Resume)

  notes              TEXT
);

-- Das Dashboard liest die neuesten Zeilen (eine pro Dokument) → Index auf run_at.
CREATE INDEX IF NOT EXISTS idx_audit_log_run_at   ON audit_log (run_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_log_doc_name ON audit_log (doc_name);
