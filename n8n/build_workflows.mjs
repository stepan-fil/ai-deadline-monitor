// =============================================================================
//  Build-Skript für die beiden n8n-Workflows.
//  EINZIGE QUELLE der Wahrheit fürs Dashboard ist ../dashboard/dashboard.html —
//  dieses Skript bettet es in WF-B ein (kein doppeltes Pflegen, kein Drift).
//
//  M2: WF-A nur CSV-Zweig (linear).
//  M3: WF-A bekommt den mode-Schalter (ENTSCHEIDUNG-05/-18): Set "Modus wählen" → IF →
//      LLM-Zweig (PDFs lesen → Text → Ollama → JSON prüfen) ODER CSV-Zweig; beide münden
//      in DENSELBEN Knoten 8 (KI-freie Rechenlogik). Knoten 8 nimmt source_mode aus dem
//      Item ('llm'|'csv') statt es hart zu setzen.
//
//  M7: + WF-C "Mail-Ingestion" (IMAP-Trigger → DERSELBE LLM-Zweig → Knoten 8 → Postgres) und
//      + externe Read-only-Ansicht in WF-B (/webhook/extern + /webhook/extern-data, nur approved).
//      Mail bleibt lokal (GreenMail). Siehe ENTSCHEIDUNG-28/-29/-30.
//
//  Lauf:   FW_PG_CRED_ID=<pg-cred> [FW_IMAP_CRED_ID=<imap-cred>] [FW_DEFAULT_MODE=csv|llm] node n8n/build_workflows.mjs
//  Ergebnis: workflow_csv_ingestion.json + workflow_dashboard_server.json + workflow_mail_ingestion.json
//  Import: in n8n über "Import from File", danach den Postgres-Credential im Knoten neu
//          auswählen, falls die Credential-ID rechnerspezifisch abweicht. Siehe SETUP.md §7.
//  FW_DEFAULT_MODE: Startwert des Schalters. 'csv' = recording-sicherer Default (ENTSCHEIDUNG-10);
//                   'llm' nur zum Testen des LLM-Pfads.
// =============================================================================
import { readFileSync, writeFileSync } from 'node:fs';

const proj = new URL('..', import.meta.url);                 // Projekt-Root (Elternordner von n8n/)
const readP  = rel => readFileSync(new URL(rel, proj), 'utf8');
const writeP = (rel, s) => writeFileSync(new URL(rel, proj), s);

const credId = process.env.FW_PG_CRED_ID || 'REPLACE_WITH_POSTGRES_CREDENTIAL_ID';
const defaultMode = (process.env.FW_DEFAULT_MODE === 'llm') ? 'llm' : 'csv';
// Optionale feste Workflow-ID nur für den CLI-Import (überschreibt einen bestehenden Workflow).
// Ohne ENV bleibt die committete JSON ID-frei (portabel; n8n vergibt beim UI-Import eine ID).
const wfId = process.env.FW_WF_ID || null;
const wfIdB = process.env.FW_WF_ID_B || null;   // feste ID für den WF-B-Import (überschreibt den bestehenden)
const wfIdC = process.env.FW_WF_ID_C || null;   // feste ID für den WF-C-Import (Mail-Ingestion, M7)
// Modell wird zur BAUZEIT fest in den Workflow geschrieben — NICHT $env im Knoten, weil n8n den
// Env-Zugriff in Node-Code blockt (Sicherheits-Default, R5: sonst läge der DB-Pass/Encryption-Key
// für Workflow-Code offen). Quelle: .env (OLLAMA_MODEL), sonst process.env, sonst Default.
let ollamaModel = process.env.OLLAMA_MODEL || 'llama3.2:3b';
try { const m = readP('.env').match(/^\s*OLLAMA_MODEL\s*=\s*(.+?)\s*$/m); if (m) ollamaModel = m[1].trim(); } catch {}
const html       = readP('dashboard/dashboard.html');
const htmlExtern = readP('dashboard/extern.html');     // externe Read-only-Ansicht (M7, ENTSCHEIDUNG-29)
const pgCred = { postgres: { id: credId, name: 'Fristenwaechter Postgres' } };
// IMAP-Credential für den Mail-Eingang (WF-C). Wie der Postgres-Cred NICHT committen — nur Platzhalter;
// die echte Credential-ID wird beim Import in n8n gesetzt (SETUP.md §9). R5: kein Secret im Repo.
const imapCredId = process.env.FW_IMAP_CRED_ID || 'REPLACE_WITH_IMAP_CREDENTIAL_ID';
const imapCred = { imap: { id: imapCredId, name: 'Fristenwaechter Mail (IMAP)' } };

// ---------- KNOTEN 8: KI-freie Logik + INSERT-Bau (läuft in der n8n-Code-Node) ----------
// Unverändert gegenüber M2 — EINZIGE Änderung: source_mode kommt aus dem Item (sm), nicht hart 'csv'.
const logikCode = `
const GELB_SCHWELLE_TAGE = 14;
const tageDiff = (vonISO, bisISO) => Math.round((Date.parse(bisISO+'T00:00:00Z') - Date.parse(vonISO+'T00:00:00Z'))/86400000);
const q = v => "'" + String(v).replace(/'/g, "''") + "'"; // SQL-String sicher escapen
// "heute" als Berlin-Kalendertag (Container läuft auf UTC) → keine Mitternachts-Verschiebung
const heuteISO = new Intl.DateTimeFormat('en-CA', { timeZone: 'Europe/Berlin' }).format(new Date());

return $input.all().map(item => {
  const f = item.json;
  const sm = (f.source_mode === 'llm') ? 'llm' : 'csv';   // Quelle aus dem Item; Default csv
  // --- Eingabe-Validierung: sprechender Fehler statt kryptischem SQL-Abbruch ---
  const fehler = [];
  if (!f.doc_name) fehler.push('doc_name fehlt');
  if (!/^\\d{4}-\\d{2}-\\d{2}$/.test(String(f.stichtag||''))) fehler.push('stichtag kein YYYY-MM-DD');
  if (!Number.isFinite(Number(f.vorlauf_tage))) fehler.push('vorlauf_tage keine Zahl');
  if (fehler.length) throw new Error(sm.toUpperCase() + '-Zeile "' + (f.doc_name||'?') + '": ' + fehler.join(', '));

  const vorlauf = Number(f.vorlauf_tage);
  const warn = new Date(f.stichtag + 'T00:00:00Z');
  warn.setUTCDate(warn.getUTCDate() - vorlauf);                // warndatum = stichtag - vorlauf_tage
  const warndatum = warn.toISOString().slice(0,10);
  const resttage = tageDiff(heuteISO, warndatum);              // Tage bis Warndatum
  const resttage_stichtag = tageDiff(heuteISO, f.stichtag);    // Tage bis Stichtag
  let ampel, eskalationsstufe;
  if (resttage <= 0) { ampel='rot'; eskalationsstufe=2; }
  else if (resttage <= GELB_SCHWELLE_TAGE) { ampel='gelb'; eskalationsstufe=1; }
  else { ampel='gruen'; eskalationsstufe=0; }

  const query =
    "INSERT INTO audit_log (source_mode,doc_name,partner,stichtag,vorlauf_tage,pflicht,warndatum,resttage,resttage_stichtag,ampel,eskalationsstufe) VALUES ("
    + q(sm) + "," + q(f.doc_name) + "," + q(f.partner) + ",'" + f.stichtag + "'," + vorlauf + "," + q(f.pflicht) + ",'"
    + warndatum + "'," + resttage + "," + resttage_stichtag + ",'" + ampel + "'," + eskalationsstufe + ")";

  return { json: { source_mode:sm, doc_name:f.doc_name, partner:f.partner, stichtag:f.stichtag,
    vorlauf_tage:vorlauf, pflicht:f.pflicht, warndatum, resttage, resttage_stichtag, ampel, eskalationsstufe, query } };
});`.trim();

// ---------- KNOTEN 6a: Prompt bauen (runOnceForEachItem) ----------
// Liest PDF-Text + Dateiname, baut den Ollama-Request. Modell aus ENV (ENTSCHEIDUNG-17, tauschbar).
// Derselbe Prompt wie in scripts/extract_test.py (Treffer-Quote, ENTSCHEIDUNG-21) — synchron halten.
// Parametrisiert: derselbe Prompt-Bau für den PDF-Ordner-Pfad (WF-A: Quelle "PDFs lesen", Binary "data")
// UND für den Mail-Pfad (WF-C: Quelle "Email Trigger (IMAP)", Binary "attachment_0"). Single Source.
const makePromptCode = (sourceNode, binaryKey) => `
const text = ($json.text || '').toString();
// Dateiname (= doc_name) vom Quell-Knoten holen (PDF-Ordner ODER Mail-Anhang) — "Text aus PDF"
// reicht die Binärdaten (mit fileName) nicht durch. Cross-Node-Referenz via pairedItem.
let fileName = 'unbekannt.pdf';
try { const up = $('${sourceNode}').item; if (up && up.binary && up.binary['${binaryKey}'] && up.binary['${binaryKey}'].fileName) fileName = up.binary['${binaryKey}'].fileName; } catch (e) {}
if (fileName === 'unbekannt.pdf') { const b = ($input.item && $input.item.binary) || {}; if (b['${binaryKey}'] && b['${binaryKey}'].fileName) fileName = b['${binaryKey}'].fileName; }

const anweisung = [
  'Du bist ein präzises Extraktionswerkzeug für deutsche Geschäftsdokumente.',
  'Lies das Dokument unten und gib AUSSCHLIESSLICH ein JSON-Objekt mit genau diesen vier Schlüsseln zurück:',
  '- "partner": Name der absendenden Firma oder Stelle (String).',
  '- "stichtag": der maßgebliche Stichtag / die Frist, im Format YYYY-MM-DD.',
  '- "vorlauf_tage": Vorlauf in Tagen vor dem Stichtag (ganze Zahl).',
  '- "pflicht": kurze Beschreibung der erforderlichen Maßnahme/Pflicht (String).',
  'Regeln: Wandle Datumsangaben wie "17. August 2026" nach "2026-08-17" um. Gib Firmen-, Stellen- und Eigennamen EXAKT wie im Dokument wieder — übersetze sie nicht und behalte deutsche Umlaute (ä, ö, ü, ß) bei. Gib nur das JSON zurück, keinen weiteren Text.',
  'Beispiel für ein ANDERES Dokument:',
  '{"partner":"Aufzugswartung Beispiel GmbH","stichtag":"2026-05-04","vorlauf_tage":21,"pflicht":"Wartungstermin Aufzug vereinbaren"}'
].join('\\n');

const prompt = anweisung + '\\n\\nDOKUMENT:\\n"""\\n' + text + '\\n"""';
const model = '${ollamaModel}';   // zur Bauzeit aus .env fest eingesetzt (kein $env im Knoten, R5)

return { json: { doc_name: fileName, model,
  body: { model, prompt, stream: false, format: 'json', options: { temperature: 0 }, keep_alive: '10m' } } };`.trim();

// ---------- KNOTEN 7a: JSON parsen + validieren (runOnceForEachItem) ----------
// Ollama liefert dank format:json einen JSON-String in $json.response. Ungültige Dokumente werden
// markiert (_ok:false) und vom Filter VOR Knoten 8 entfernt → ein Fehl-Extrakt killt nicht den Batch.
const parseCode = `
const raw = $json.response;
const docName = $('Prompt bauen').item.json.doc_name;
let parsed;
try { parsed = (typeof raw === 'string') ? JSON.parse(raw) : raw; }
catch (e) { return { json: { source_mode: 'llm', doc_name: docName, _ok: false, _fehler: 'JSON nicht parsebar' } }; }
parsed = parsed || {};
const partner = (parsed.partner != null ? String(parsed.partner) : '').trim();
const stichtag = (parsed.stichtag != null ? String(parsed.stichtag) : '').trim();
const vorlaufRaw = parsed.vorlauf_tage;
const pflicht = (parsed.pflicht != null ? String(parsed.pflicht) : '').trim();
const fehler = [];
if (!partner) fehler.push('partner leer');
if (!/^\\d{4}-\\d{2}-\\d{2}$/.test(stichtag)) fehler.push('stichtag kein YYYY-MM-DD');
if (!Number.isFinite(Number(vorlaufRaw))) fehler.push('vorlauf_tage keine Zahl');
if (!pflicht) fehler.push('pflicht leer');
if (fehler.length) return { json: { source_mode: 'llm', doc_name: docName, _ok: false, _fehler: fehler.join(', '),
  partner, stichtag, vorlauf_tage: vorlaufRaw, pflicht } };
return { json: { source_mode: 'llm', doc_name: docName, partner, stichtag, vorlauf_tage: Number(vorlaufRaw), pflicht, _ok: true } };`.trim();

// Neueste Zeile je Dokument; Tie-Breaker id DESC → bei gleichem run_at deterministisch (R4-Review)
const selectQuery =
`SELECT * FROM (
  SELECT DISTINCT ON (doc_name)
    id, doc_name, partner, pflicht, stichtag, vorlauf_tage, source_mode,
    warndatum, resttage, resttage_stichtag, ampel, eskalationsstufe, run_at,
    approved, approved_at
  FROM audit_log
  ORDER BY doc_name, run_at DESC, id DESC
) t
ORDER BY eskalationsstufe DESC, resttage ASC`;

// Volles Audit-Log (alle Läufe) für die aufklappbare Tabelle im Dashboard (M4).
const auditQuery =
`SELECT id, run_at, source_mode, doc_name, partner, stichtag, vorlauf_tage,
        warndatum, resttage, ampel, eskalationsstufe, approved, approved_at
 FROM audit_log
 ORDER BY run_at DESC, id DESC
 LIMIT 200`;

// Externe Read-only-Ansicht (M7, ENTSCHEIDUNG-29): NUR vom Menschen freigegebene Einträge,
// neueste freigegebene Zeile je Dokument. Unfreigegebenes erreicht die externe Seite gar nicht
// (Filter in der DB-Abfrage, nicht erst im Browser) → sauberer Human-in-the-Loop-Beweis.
// R5-Auflage: nach außen NUR die angezeigten Felder liefern — KEIN id (= Freigabe-Handle für
// /webhook/freigeben), kein run_at, kein approved-Flag. Minimal-Exposure für die Datenschutz-Story.
const selectQueryExtern =
`SELECT doc_name, partner, pflicht, stichtag, vorlauf_tage, source_mode,
        warndatum, resttage, resttage_stichtag, ampel, eskalationsstufe, approved_at
 FROM (
  SELECT DISTINCT ON (doc_name)
    doc_name, partner, pflicht, stichtag, vorlauf_tage, source_mode,
    warndatum, resttage, resttage_stichtag, ampel, eskalationsstufe,
    approved_at, run_at, id
  FROM audit_log
  WHERE approved = true
  ORDER BY doc_name, run_at DESC, id DESC
) t
ORDER BY eskalationsstufe DESC, resttage ASC`;

// =================== WF-A: Ingestion (LLM + CSV mit mode-Schalter) ===================
const wfA = {
  ...(wfId ? { id: wfId } : {}),
  name: 'Fristenwächter — Ingestion LLM+CSV (M3)',
  settings: { executionOrder: 'v1' },
  nodes: [
    { id:'trg', name:'Manueller Start', type:'n8n-nodes-base.manualTrigger', typeVersion:1, position:[0,300], parameters:{} },
    { id:'setmode', name:'Modus wählen', type:'n8n-nodes-base.set', typeVersion:3.4, position:[200,300],
      parameters:{ assignments:{ assignments:[ { id:'m1', name:'mode', value:defaultMode, type:'string' } ] }, options:{} } },
    { id:'ifmode', name:'Quelle (LLM/CSV)', type:'n8n-nodes-base.if', typeVersion:2, position:[420,300],
      parameters:{ conditions:{ options:{ caseSensitive:true, leftValue:'', typeValidation:'strict' },
        conditions:[ { id:'c1', leftValue:'={{ $json.mode }}', rightValue:'llm', operator:{ type:'string', operation:'equals' } } ],
        combinator:'and' }, options:{} } },

    // --- LLM-Zweig (IF-Ausgang 0 = true) ---
    { id:'pdfread', name:'PDFs lesen', type:'n8n-nodes-base.readWriteFile', typeVersion:1, position:[640,160],
      parameters:{ operation:'read', fileSelector:'/data/testdata/*.pdf', options:{} } },
    { id:'pextract', name:'Text aus PDF', type:'n8n-nodes-base.extractFromFile', typeVersion:1, position:[860,160],
      parameters:{ operation:'pdf', binaryPropertyName:'data', options:{} } },
    { id:'promptbuild', name:'Prompt bauen', type:'n8n-nodes-base.code', typeVersion:2, position:[1080,160],
      parameters:{ mode:'runOnceForEachItem', jsCode: makePromptCode('PDFs lesen', 'data') } },
    { id:'ollama', name:'Ollama (Extraktion)', type:'n8n-nodes-base.httpRequest', typeVersion:4.2, position:[1300,160],
      parameters:{ method:'POST', url:'http://host.docker.internal:11434/api/generate',
        sendBody:true, specifyBody:'json', jsonBody:'={{ $json.body }}', options:{ timeout:60000 } } },
    { id:'parse', name:'JSON prüfen (7a)', type:'n8n-nodes-base.code', typeVersion:2, position:[1520,160],
      parameters:{ mode:'runOnceForEachItem', jsCode: parseCode } },
    { id:'filter', name:'Nur gültige (LLM)', type:'n8n-nodes-base.filter', typeVersion:2, position:[1740,160],
      parameters:{ conditions:{ options:{ caseSensitive:true, typeValidation:'loose' },
        conditions:[ { id:'f1', leftValue:'={{ $json._ok }}', rightValue:'', operator:{ type:'boolean', operation:'true', singleValue:true } } ],
        combinator:'and' }, options:{} } },

    // --- CSV-Zweig (IF-Ausgang 1 = false) ---
    { id:'csvread', name:'CSV lesen', type:'n8n-nodes-base.readWriteFile', typeVersion:1, position:[640,440],
      parameters:{ operation:'read', fileSelector:'/data/testdata/fristen.csv', options:{} } },
    { id:'csvparse', name:'CSV → Felder', type:'n8n-nodes-base.extractFromFile', typeVersion:1, position:[860,440],
      parameters:{ operation:'csv', binaryPropertyName:'data', options:{} } },

    // --- gemeinsamer Tail: Knoten 8 (KI-frei) + INSERT ---
    { id:'logic', name:'Knoten 8 — Logik (KI-frei)', type:'n8n-nodes-base.code', typeVersion:2, position:[1960,300],
      parameters:{ mode:'runOnceForAllItems', jsCode: logikCode } },
    { id:'pginsert', name:'In audit_log schreiben', type:'n8n-nodes-base.postgres', typeVersion:2.6, position:[2180,300],
      parameters:{ operation:'executeQuery', query:'={{ $json.query }}', options:{} }, credentials: pgCred },
  ],
  connections: {
    'Manueller Start': { main:[[{ node:'Modus wählen', type:'main', index:0 }]] },
    'Modus wählen':    { main:[[{ node:'Quelle (LLM/CSV)', type:'main', index:0 }]] },
    'Quelle (LLM/CSV)':{ main:[
      [{ node:'PDFs lesen', type:'main', index:0 }],   // Ausgang 0 = true  → LLM
      [{ node:'CSV lesen',  type:'main', index:0 }],   // Ausgang 1 = false → CSV
    ] },
    'PDFs lesen':           { main:[[{ node:'Text aus PDF', type:'main', index:0 }]] },
    'Text aus PDF':         { main:[[{ node:'Prompt bauen', type:'main', index:0 }]] },
    'Prompt bauen':         { main:[[{ node:'Ollama (Extraktion)', type:'main', index:0 }]] },
    'Ollama (Extraktion)':  { main:[[{ node:'JSON prüfen (7a)', type:'main', index:0 }]] },
    'JSON prüfen (7a)':     { main:[[{ node:'Nur gültige (LLM)', type:'main', index:0 }]] },
    'Nur gültige (LLM)':    { main:[[{ node:'Knoten 8 — Logik (KI-frei)', type:'main', index:0 }]] },
    'CSV lesen':            { main:[[{ node:'CSV → Felder', type:'main', index:0 }]] },
    'CSV → Felder':         { main:[[{ node:'Knoten 8 — Logik (KI-frei)', type:'main', index:0 }]] },
    'Knoten 8 — Logik (KI-frei)': { main:[[{ node:'In audit_log schreiben', type:'main', index:0 }]] },
  },
};

// =================== WF-B: Dashboard-Server (+ Freigabe + Audit-Log, M4) ===================
const wfB = {
  ...(wfIdB ? { id: wfIdB } : {}),
  name: 'Fristenwächter — Dashboard-Server (M4 + Extern)',
  settings: { executionOrder: 'v1' },
  nodes: [
    { id:'whdata', name:'Webhook Daten', type:'n8n-nodes-base.webhook', typeVersion:2, position:[0,0],
      webhookId:'fw-data-webhook',
      parameters:{ httpMethod:'GET', path:'fristen-data', responseMode:'responseNode', options:{} } },
    { id:'pgselect', name:'audit_log lesen', type:'n8n-nodes-base.postgres', typeVersion:2.6, position:[240,0],
      parameters:{ operation:'executeQuery', query: selectQuery, options:{} }, credentials: pgCred },
    { id:'respjson', name:'Antwort JSON', type:'n8n-nodes-base.respondToWebhook', typeVersion:1, position:[480,0],
      parameters:{ respondWith:'allIncomingItems', options:{} } },

    { id:'whdash', name:'Webhook Dashboard', type:'n8n-nodes-base.webhook', typeVersion:2, position:[0,200],
      webhookId:'fw-dash-webhook',
      parameters:{ httpMethod:'GET', path:'dashboard', responseMode:'responseNode', options:{} } },
    { id:'resphtml', name:'Antwort HTML', type:'n8n-nodes-base.respondToWebhook', typeVersion:1, position:[240,200],
      parameters:{ respondWith:'text', responseBody: html,
        options:{ responseHeaders:{ entries:[ { name:'Content-Type', value:'text/html; charset=utf-8' } ] } } } },

    // --- Mensch-Freigabe (M4): GET /webhook/freigeben?id=NN → UPDATE approved=true ---
    { id:'whfrei', name:'Webhook Freigeben', type:'n8n-nodes-base.webhook', typeVersion:2, position:[0,400],
      webhookId:'fw-freigeben-webhook',
      parameters:{ httpMethod:'GET', path:'freigeben', responseMode:'responseNode', options:{} } },
    { id:'pgupd', name:'Freigabe schreiben', type:'n8n-nodes-base.postgres', typeVersion:2.6, position:[240,400],
      parameters:{ operation:'executeQuery',
        query:'UPDATE audit_log SET approved = true, approved_at = now() WHERE id = $1::int AND approved = false',
        options:{ queryReplacement: '={{ [$json.query.id] }}' } }, credentials: pgCred },
    { id:'respfrei', name:'Antwort Freigabe', type:'n8n-nodes-base.respondToWebhook', typeVersion:1, position:[480,400],
      parameters:{ respondWith:'text', responseBody:'{ "ok": true }',
        options:{ responseHeaders:{ entries:[ { name:'Content-Type', value:'application/json; charset=utf-8' } ] } } } },

    // --- Audit-Log voll (M4): GET /webhook/audit-log → alle Läufe als JSON ---
    { id:'whaudit', name:'Webhook Audit-Log', type:'n8n-nodes-base.webhook', typeVersion:2, position:[0,600],
      webhookId:'fw-audit-webhook',
      parameters:{ httpMethod:'GET', path:'audit-log', responseMode:'responseNode', options:{} } },
    { id:'pgaudit', name:'audit_log voll lesen', type:'n8n-nodes-base.postgres', typeVersion:2.6, position:[240,600],
      parameters:{ operation:'executeQuery', query: auditQuery, options:{} }, credentials: pgCred },
    { id:'respaudit', name:'Antwort Audit-Log', type:'n8n-nodes-base.respondToWebhook', typeVersion:1, position:[480,600],
      parameters:{ respondWith:'allIncomingItems', options:{} } },

    // --- Externe Read-only-Ansicht (M7): /webhook/extern (HTML) + /webhook/extern-data (nur approved) ---
    { id:'whextdata', name:'Webhook Extern-Daten', type:'n8n-nodes-base.webhook', typeVersion:2, position:[0,800],
      webhookId:'fw-extern-data-webhook',
      parameters:{ httpMethod:'GET', path:'extern-data', responseMode:'responseNode', options:{} } },
    { id:'pgextsel', name:'Freigegebene lesen', type:'n8n-nodes-base.postgres', typeVersion:2.6, position:[240,800],
      parameters:{ operation:'executeQuery', query: selectQueryExtern, options:{} }, credentials: pgCred },
    { id:'respextjson', name:'Antwort Extern-JSON', type:'n8n-nodes-base.respondToWebhook', typeVersion:1, position:[480,800],
      parameters:{ respondWith:'allIncomingItems', options:{} } },

    { id:'whext', name:'Webhook Extern', type:'n8n-nodes-base.webhook', typeVersion:2, position:[0,1000],
      webhookId:'fw-extern-webhook',
      parameters:{ httpMethod:'GET', path:'extern', responseMode:'responseNode', options:{} } },
    { id:'respexthtml', name:'Antwort Extern-HTML', type:'n8n-nodes-base.respondToWebhook', typeVersion:1, position:[240,1000],
      parameters:{ respondWith:'text', responseBody: htmlExtern,
        options:{ responseHeaders:{ entries:[ { name:'Content-Type', value:'text/html; charset=utf-8' } ] } } } },
  ],
  connections: {
    'Webhook Daten':        { main:[[{ node:'audit_log lesen', type:'main', index:0 }]] },
    'audit_log lesen':      { main:[[{ node:'Antwort JSON', type:'main', index:0 }]] },
    'Webhook Dashboard':    { main:[[{ node:'Antwort HTML', type:'main', index:0 }]] },
    'Webhook Freigeben':    { main:[[{ node:'Freigabe schreiben', type:'main', index:0 }]] },
    'Freigabe schreiben':   { main:[[{ node:'Antwort Freigabe', type:'main', index:0 }]] },
    'Webhook Audit-Log':    { main:[[{ node:'audit_log voll lesen', type:'main', index:0 }]] },
    'audit_log voll lesen': { main:[[{ node:'Antwort Audit-Log', type:'main', index:0 }]] },
    'Webhook Extern-Daten': { main:[[{ node:'Freigegebene lesen', type:'main', index:0 }]] },
    'Freigegebene lesen':   { main:[[{ node:'Antwort Extern-JSON', type:'main', index:0 }]] },
    'Webhook Extern':       { main:[[{ node:'Antwort Extern-HTML', type:'main', index:0 }]] },
  },
};

// =================== WF-C: Mail-Ingestion (IMAP → KI-Extraktion → Knoten 8) ===================
// M7 (ENTSCHEIDUNG-28/-30): Dokumente kommen per E-Mail an den LOKALEN GreenMail-Server. Der
// IMAP-Trigger holt Mail + PDF-Anhang (Binary "attachment_0"), danach läuft DERSELBE LLM-Zweig wie
// in WF-A und mündet in DENSELBEN KI-freien Knoten 8. WF-A (Button/CSV) bleibt unangetastet (Backup).
// Muss zum Aufnehmen AKTIV sein (Polling-Trigger läuft nur bei aktivem Workflow) → unmittelbar vor
// dem Take frisch aktivieren (SETUP.md §9). source_mode = 'llm' (die KI liest das Dokument).
const wfC = {
  ...(wfIdC ? { id: wfIdC } : {}),
  name: 'Fristenwächter — Mail-Ingestion (IMAP→KI) (M7)',
  settings: { executionOrder: 'v1' },
  // staticData leer mitgeben: ein WF-C-Import setzt damit die getrackte IMAP-UID (lastMessageUid)
  // ZURÜCK. Nötig, weil GreenMail In-Memory ist und seine UIDs beim (Kalt-)Start auf niedrige Werte
  // resettet — eine aus einer früheren Session gemerkte hohe UID würde sonst alle neuen Mails als
  // "schon gesehen" überspringen (Kaltstart-Bug, 2026-06-24). Import bei GESTOPPTEM n8n ausführen,
  // damit der laufende Server die alte In-Memory-staticData nicht zurückschreibt (SETUP §9.2a).
  staticData: {},
  nodes: [
    // Idempotenz über IMAP-Suche "UNSEEN" + postProcessAction:'read' (verarbeitete Mail wird SEEN → nicht
    // erneut geholt). trackLastMessageId EXPLIZIT auf false (n8n-Default wäre true!): sonst merkt n8n die
    // zuletzt gesehene UID in staticData und holt nur UID>lastUID. GreenMail ist aber In-Memory und setzt
    // seine UIDs bei jedem (Kalt-)Start zurück → eine über die Session hinaus gemerkte hohe UID würde alle
    // neuen, niedriger nummerierten Mails als "schon gesehen" überspringen (stiller Kaltstart-Bug, R1
    // 2026-06-24). Mit false trackt n8n keine UID über Neustarts → kein hängenbleibender Filter. staticData:{}
    // (unten) räumt zusätzlich beim Import jeden Alt-Stand weg.
    { id:'imap', name:'Email Trigger (IMAP)', type:'n8n-nodes-base.emailReadImap', typeVersion:2.1, position:[0,300],
      parameters:{ mailbox:'INBOX', postProcessAction:'read', format:'resolved',
        dataPropertyAttachmentsPrefixName:'attachment_',
        options:{ customEmailConfig:'["UNSEEN"]', forceReconnect:1, trackLastMessageId:false } },
      credentials: imapCred },
    // Robustheit: nur weiter, wenn ein PDF-Anhang da ist (leere/fremde Mails kippen den Lauf nicht).
    { id:'haspdf', name:'Hat PDF-Anhang?', type:'n8n-nodes-base.if', typeVersion:2, position:[240,300],
      parameters:{ conditions:{ options:{ caseSensitive:false, typeValidation:'loose' },
        conditions:[ { id:'p1',
          leftValue:'={{ $binary.attachment_0 ? $binary.attachment_0.fileName : "" }}',
          rightValue:'.pdf', operator:{ type:'string', operation:'endsWith' } } ],
        combinator:'and' }, options:{} } },
    // Hinweis (R1 B1): Die PDF-Extraktion schreibt ihren Text nach $json.text und ÜBERSCHREIBT damit
    // den E-Mail-Body (PDF-Operation hat in n8n KEIN "Destination Field"). "Prompt bauen" liest daher
    // korrekt den PDF-Text. Am Aufnahmetag in Claude Code 1× gegenprüfen (partner/stichtag aus dem PDF).
    { id:'pextract', name:'Text aus PDF', type:'n8n-nodes-base.extractFromFile', typeVersion:1, position:[480,220],
      parameters:{ operation:'pdf', binaryPropertyName:'attachment_0', options:{} } },
    { id:'promptbuild', name:'Prompt bauen', type:'n8n-nodes-base.code', typeVersion:2, position:[700,220],
      parameters:{ mode:'runOnceForEachItem', jsCode: makePromptCode('Email Trigger (IMAP)', 'attachment_0') } },
    { id:'ollama', name:'Ollama (Extraktion)', type:'n8n-nodes-base.httpRequest', typeVersion:4.2, position:[920,220],
      parameters:{ method:'POST', url:'http://host.docker.internal:11434/api/generate',
        sendBody:true, specifyBody:'json', jsonBody:'={{ $json.body }}', options:{ timeout:60000 } } },
    { id:'parse', name:'JSON prüfen (7a)', type:'n8n-nodes-base.code', typeVersion:2, position:[1140,220],
      parameters:{ mode:'runOnceForEachItem', jsCode: parseCode } },
    { id:'filter', name:'Nur gültige (LLM)', type:'n8n-nodes-base.filter', typeVersion:2, position:[1360,220],
      parameters:{ conditions:{ options:{ caseSensitive:true, typeValidation:'loose' },
        conditions:[ { id:'f1', leftValue:'={{ $json._ok }}', rightValue:'', operator:{ type:'boolean', operation:'true', singleValue:true } } ],
        combinator:'and' }, options:{} } },
    { id:'logic', name:'Knoten 8 — Logik (KI-frei)', type:'n8n-nodes-base.code', typeVersion:2, position:[1580,300],
      parameters:{ mode:'runOnceForAllItems', jsCode: logikCode } },
    { id:'pginsert', name:'In audit_log schreiben', type:'n8n-nodes-base.postgres', typeVersion:2.6, position:[1800,300],
      parameters:{ operation:'executeQuery', query:'={{ $json.query }}', options:{} }, credentials: pgCred },
  ],
  connections: {
    'Email Trigger (IMAP)': { main:[[{ node:'Hat PDF-Anhang?', type:'main', index:0 }]] },
    'Hat PDF-Anhang?': { main:[
      [{ node:'Text aus PDF', type:'main', index:0 }],   // true  → PDF vorhanden
      [],                                                 // false → ignorieren
    ] },
    'Text aus PDF':        { main:[[{ node:'Prompt bauen', type:'main', index:0 }]] },
    'Prompt bauen':        { main:[[{ node:'Ollama (Extraktion)', type:'main', index:0 }]] },
    'Ollama (Extraktion)': { main:[[{ node:'JSON prüfen (7a)', type:'main', index:0 }]] },
    'JSON prüfen (7a)':    { main:[[{ node:'Nur gültige (LLM)', type:'main', index:0 }]] },
    'Nur gültige (LLM)':   { main:[[{ node:'Knoten 8 — Logik (KI-frei)', type:'main', index:0 }]] },
    'Knoten 8 — Logik (KI-frei)': { main:[[{ node:'In audit_log schreiben', type:'main', index:0 }]] },
  },
};

// NUR ZUM TESTEN: einen Webhook-Trigger ergänzen, weil die n8n-CLI bei laufendem Server keine
// manuellen Trigger ausführen kann. Die committete/Recording-Version hat NUR den manuellen Start.
if (process.env.FW_ADD_WEBHOOK_TRIGGER === '1') {
  wfA.nodes.push({ id:'whrun', name:'WH Test ausführen', type:'n8n-nodes-base.webhook', typeVersion:2,
    position:[0,140], webhookId:'fw-run-webhook',
    parameters:{ httpMethod:'GET', path:'fw-run', responseMode:'lastNode', options:{} } });
  wfA.connections['WH Test ausführen'] = { main:[[{ node:'Modus wählen', type:'main', index:0 }]] };
  wfA.active = true;  // direkt aktiv importieren → Test-Webhook nach EINEM Neustart registriert
}

writeP('n8n/workflow_csv_ingestion.json', JSON.stringify(wfA, null, 2));
writeP('n8n/workflow_dashboard_server.json', JSON.stringify(wfB, null, 2));
writeP('n8n/workflow_mail_ingestion.json', JSON.stringify(wfC, null, 2));
console.log('Postgres-Credential-ID:', credId === 'REPLACE_WITH_POSTGRES_CREDENTIAL_ID' ? '(Platzhalter — via FW_PG_CRED_ID setzen)' : credId);
console.log('IMAP-Credential-ID: ', imapCredId === 'REPLACE_WITH_IMAP_CREDENTIAL_ID' ? '(Platzhalter — via FW_IMAP_CRED_ID setzen)' : imapCredId);
console.log('Default-Modus (Set "Modus wählen"):', defaultMode);
console.log('dashboard.html eingebettet:', html.length, 'Zeichen; extern.html:', htmlExtern.length, 'Zeichen');
console.log('geschrieben: workflow_csv_ingestion.json, workflow_dashboard_server.json, workflow_mail_ingestion.json');
