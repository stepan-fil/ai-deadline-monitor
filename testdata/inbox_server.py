#!/usr/bin/env python3
# =============================================================================
#  inbox_server.py — Visueller Posteingang für die Aufnahme (DREHBUCH Szene 3).
#  Zeigt das ECHTE GreenMail-Demo-Postfach (fristen@…) wie ein Mail-Client,
#  damit man im Screen-Recording sieht: „da kommt eine Mail rein".
#
#  WICHTIG — NUR LESEND:
#    Öffnet IMAP read-only (EXAMINE) + BODY.PEEK → setzt KEIN \Seen, löscht
#    nichts, expunged nichts. Der verifizierte Mailweg (WF-C liest UNSEEN und
#    markiert selbst als gelesen) bleibt damit völlig unberührt.
#
#  Alles LOKAL (127.0.0.1), kein Egress. Das Mail-Passwort wird NUR zum lokalen
#  IMAP-Login benutzt und NIE an den Browser geschickt (keine Secrets in der UI).
#  Nur Python-Standardbibliothek — keine Installation nötig.
#
#  Start:   python3 testdata/inbox_server.py
#  Öffnen:  http://localhost:8099      (in Chrome, Vollbild für die Aufnahme)
#  Stoppen: Strg+C
# =============================================================================
import email
import email.utils
import html
import imaplib
import json
import re
import time
from email.header import decode_header, make_header
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

import demo_lib as L

HOST, PORT = "127.0.0.1", 8099
NEW_WINDOW_S = 180  # so lange gilt eine Mail als „gerade eingegangen" (wie das Dashboard-Highlight)


# ---------------------------------------------------------------------------
#  IMAP lesen (read-only)
# ---------------------------------------------------------------------------
def _decode(value: str) -> str:
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value)))
    except Exception:
        return value


def _text_body(msg) -> str:
    """Erste text/plain-Komponente (sonst leer)."""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain" and "attachment" not in str(
                part.get("Content-Disposition") or ""
            ).lower():
                raw = part.get_payload(decode=True) or b""
                return raw.decode(part.get_content_charset() or "utf-8", "replace")
        return ""
    raw = msg.get_payload(decode=True) or b""
    return raw.decode(msg.get_content_charset() or "utf-8", "replace")


def _attachments(msg):
    out = []
    if not msg.is_multipart():
        return out
    for part in msg.walk():
        fname = part.get_filename()
        cdisp = str(part.get("Content-Disposition") or "").lower()
        if fname or "attachment" in cdisp:
            payload = part.get_payload(decode=True) or b""
            out.append(
                {
                    "name": _decode(fname) or "anhang",
                    "type": part.get_content_type(),
                    "size": len(payload),
                }
            )
    return out


def fetch_inbox():
    """Liest das Postfach READ-ONLY und liefert eine Liste Mails (neueste zuerst)."""
    M = imaplib.IMAP4(L.IMAP_HOST, L.IMAP_PORT)
    M.login(L.MAIL_USER, L.MAIL_PASS)
    try:
        M.select("INBOX", readonly=True)  # EXAMINE → read-only, kein \Seen
        typ, data = M.search(None, "ALL")
        ids = data[0].split() if data and data[0] else []
        mails = []
        for sid in ids:
            typ, msgdata = M.fetch(sid, "(BODY.PEEK[] FLAGS INTERNALDATE)")
            if typ != "OK" or not msgdata or not msgdata[0]:
                continue
            meta, raw = b"", None
            for part in msgdata:
                if isinstance(part, tuple):
                    meta += part[0] or b""
                    if part[1] is not None:
                        raw = part[1]
                elif isinstance(part, (bytes, bytearray)):
                    meta += part
            if raw is None:
                continue
            msg = email.message_from_bytes(raw)
            name, addr = email.utils.parseaddr(msg.get("From", ""))
            seen = b"\\Seen" in meta
            try:
                tt = imaplib.Internaldate2tuple(meta)
            except Exception:
                tt = None
            epoch = time.mktime(tt) if tt else 0
            mails.append(
                {
                    "id": int(sid),
                    "from_name": _decode(name) or addr or "(unbekannt)",
                    "from_addr": addr,
                    "subject": _decode(msg.get("Subject", "")) or "(kein Betreff)",
                    "body": _text_body(msg).strip(),
                    "attachments": _attachments(msg),
                    "seen": bool(seen),
                    "time": time.strftime("%H:%M", tt) if tt else "",
                    "epoch": epoch,
                }
            )
        mails.sort(key=lambda m: m["id"], reverse=True)  # höchste Sequenz = neueste
        now = time.time()
        for m in mails:
            m["is_new"] = bool(m["epoch"]) and (now - m["epoch"] < NEW_WINDOW_S)
        return mails
    finally:
        try:
            M.logout()
        except Exception:
            pass


def fetch_attachment(mail_id: int, idx: int):
    """Liefert (filename, content_type, bytes) eines Anhangs — read-only."""
    M = imaplib.IMAP4(L.IMAP_HOST, L.IMAP_PORT)
    M.login(L.MAIL_USER, L.MAIL_PASS)
    try:
        M.select("INBOX", readonly=True)
        typ, msgdata = M.fetch(str(mail_id).encode(), "(BODY.PEEK[])")
        if typ != "OK" or not msgdata or not msgdata[0]:
            return None
        raw = msgdata[0][1]
        msg = email.message_from_bytes(raw)
        atts = [p for p in msg.walk() if p.get_filename() or "attachment" in str(p.get("Content-Disposition") or "").lower()]
        if idx < 0 or idx >= len(atts):
            return None
        part = atts[idx]
        return (_decode(part.get_filename()) or "anhang", part.get_content_type(), part.get_payload(decode=True) or b"")
    finally:
        try:
            M.logout()
        except Exception:
            pass


# ---------------------------------------------------------------------------
#  HTML / CSS / JS  (eine selbstständige Seite; nur System-Fonts → egress-frei)
# ---------------------------------------------------------------------------
PAGE = """<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Posteingang — Fristenwächter</title>
<style>
  :root{
    --bg:#eef1f6; --panel:#ffffff; --ink:#1d2330; --muted:#6b7280; --line:#e6e9f0;
    --accent:#6d4aff; --accent-soft:#f3efff; --accent-line:#cbbcff;
    --unread:#2563eb; --pdf:#e2483d;
  }
  *{box-sizing:border-box}
  html,body{margin:0;height:100%}
  body{
    background:var(--bg); color:var(--ink); padding:28px 18px 60px;
    font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
    -webkit-font-smoothing:antialiased;
  }
  .wrap{max-width:1140px;margin:0 auto}
  .app{
    background:var(--panel); border:1px solid var(--line); border-radius:18px; overflow:hidden;
    box-shadow:0 18px 50px rgba(29,35,48,.10),0 2px 6px rgba(29,35,48,.05);
  }
  /* Kopfzeile */
  .top{display:flex;align-items:center;gap:14px;padding:20px 26px;border-bottom:1px solid var(--line)}
  .logo{width:44px;height:44px;border-radius:12px;background:linear-gradient(135deg,#7c5cff,#5b3df0);
    display:flex;align-items:center;justify-content:center;font-size:22px;color:#fff;flex:0 0 auto;
    box-shadow:0 6px 16px rgba(109,74,255,.35)}
  .acct{display:flex;flex-direction:column;line-height:1.25}
  .acct b{font-size:18px}
  .acct span{font-size:13.5px;color:var(--muted)}
  .live{margin-left:auto;display:flex;align-items:center;gap:8px;font-size:13px;color:var(--muted)}
  .dot{width:9px;height:9px;border-radius:50%;background:#23c552;box-shadow:0 0 0 0 rgba(35,197,82,.55);
    animation:pulse 2.2s infinite}
  @keyframes pulse{0%{box-shadow:0 0 0 0 rgba(35,197,82,.5)}70%{box-shadow:0 0 0 10px rgba(35,197,82,0)}100%{box-shadow:0 0 0 0 rgba(35,197,82,0)}}
  /* Titelzeile */
  .head{display:flex;align-items:baseline;gap:12px;padding:18px 26px 8px}
  .head h1{font-size:21px;margin:0;letter-spacing:.2px}
  .head .count{font-size:14px;color:var(--muted)}
  .badge{display:inline-flex;align-items:center;justify-content:center;min-width:22px;height:22px;
    padding:0 7px;border-radius:11px;background:var(--unread);color:#fff;font-size:13px;font-weight:700}
  /* Liste */
  .list{padding:8px 14px 18px}
  .row{display:flex;gap:16px;align-items:flex-start;padding:16px 14px;border-radius:14px;cursor:pointer;
    border:1px solid transparent;transition:background .15s,border-color .15s,transform .12s}
  .row:hover{background:#f7f8fb}
  .row+.row{margin-top:2px}
  .avatar{width:46px;height:46px;border-radius:50%;flex:0 0 auto;display:flex;align-items:center;
    justify-content:center;color:#fff;font-weight:700;font-size:18px;background:#9aa3b2}
  .main{flex:1 1 auto;min-width:0}
  .line1{display:flex;align-items:center;gap:10px}
  .from{font-size:18px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .time{margin-left:auto;font-size:13.5px;color:var(--muted);white-space:nowrap}
  .subj{font-size:16.5px;margin-top:3px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .snip{font-size:14.5px;color:var(--muted);margin-top:3px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .clip{font-size:14px;color:var(--muted);margin-left:8px}
  .rdot{width:12px;height:12px;border-radius:50%;background:var(--unread);flex:0 0 auto;
    align-self:center;margin-left:10px;box-shadow:0 0 0 4px rgba(37,99,235,.14)}
  .row.unseen .from{font-weight:800}
  .row.unseen .subj{font-weight:700}
  /* gerade eingegangen */
  .row.new{background:var(--accent-soft);border-color:var(--accent-line)}
  .row.new .avatar{background:linear-gradient(135deg,#7c5cff,#5b3df0);box-shadow:0 6px 16px rgba(109,74,255,.35)}
  .newpill{display:inline-flex;align-items:center;gap:6px;font-size:12px;font-weight:700;color:var(--accent);
    background:#fff;border:1px solid var(--accent-line);border-radius:999px;padding:2px 9px;margin-left:4px}
  .newpill .d{width:7px;height:7px;border-radius:50%;background:var(--accent)}
  @keyframes pop{0%{opacity:0;transform:translateY(-8px) scale(.99)}100%{opacity:1;transform:none}}
  .row.pop{animation:pop .45s ease both}
  /* aufgeklappte Mail */
  .body{padding:2px 14px 12px 76px}
  .bodycard{background:#fbfbfe;border:1px solid var(--line);border-radius:12px;padding:18px 20px}
  .bodytext{font-size:15.5px;line-height:1.6;white-space:pre-wrap;margin:0}
  .atts{margin-top:14px;display:flex;flex-wrap:wrap;gap:10px}
  .att{display:flex;align-items:center;gap:10px;text-decoration:none;color:var(--ink);
    border:1px solid var(--line);border-radius:10px;padding:9px 12px;background:#fff;font-size:14px}
  .att:hover{border-color:var(--accent-line);background:var(--accent-soft)}
  .att .ic{width:30px;height:30px;border-radius:7px;background:var(--pdf);color:#fff;font-size:11px;font-weight:800;
    display:flex;align-items:center;justify-content:center;flex:0 0 auto}
  .att .sz{color:var(--muted)}
  .empty{padding:46px 26px 56px;text-align:center;color:var(--muted)}
  .empty .big{font-size:44px;opacity:.5}
  .hide{display:none}
</style>
</head>
<body>
  <div class="wrap">
    <div class="app">
      <div class="top">
        <div class="logo">✉️</div>
        <div class="acct">
          <b>Posteingang</b>
          <span>fristen@fristenwaechter.local</span>
        </div>
        <div class="live"><span class="dot"></span> Live · aktualisiert automatisch</div>
      </div>
      <div class="head">
        <h1>Eingang</h1>
        <span class="count" id="count"></span>
      </div>
      <div class="list" id="list">
        <div class="empty"><div class="big">📭</div><div>Postfach wird geladen …</div></div>
      </div>
    </div>
  </div>
<script>
  const known = new Set();
  let first = true;
  let openId = null;

  function esc(s){const d=document.createElement('div');d.textContent=s||'';return d.innerHTML;}
  function fmtSize(n){ if(!n) return ''; if(n<1024) return n+' B'; if(n<1048576) return (n/1024).toFixed(0)+' KB'; return (n/1048576).toFixed(1)+' MB'; }
  function initial(s){ s=(s||'?').trim(); return (s[0]||'?').toUpperCase(); }
  const COLORS=['#6d4aff','#2563eb','#0ea5a4','#d97706','#db2777','#4f46e5','#0891b2'];
  function color(s){ let h=0; for(const c of (s||'')) h=(h*31+c.charCodeAt(0))>>>0; return COLORS[h%COLORS.length]; }

  function render(mails){
    const list=document.getElementById('list');
    const unread=mails.filter(m=>!m.seen).length;
    document.getElementById('count').innerHTML =
      mails.length + ' Nachricht' + (mails.length===1?'':'en') +
      (unread? ' · <span class="badge">'+unread+'</span> ungelesen':'');

    if(!mails.length){
      list.innerHTML='<div class="empty"><div class="big">📭</div><div>Noch keine Nachrichten im Posteingang.</div></div>';
      return;
    }
    list.innerHTML = mails.map(m=>{
      const isNewArrival = !first && !known.has(m.id) && m.is_new;
      const cls = ['row', m.seen?'':'unseen', m.is_new?'new':'', isNewArrival?'pop':''].join(' ').trim();
      const clip = m.attachments && m.attachments.length ? '<span class="clip">📎 '+m.attachments.length+'</span>' : '';
      const newpill = m.is_new ? '<span class="newpill"><span class="d"></span>gerade eingegangen</span>' : '';
      const rdot = m.seen ? '' : '<span class="rdot" title="ungelesen"></span>';
      const opened = (m.id===openId);
      const atts = (m.attachments||[]).map((a,i)=>
        '<a class="att" href="/att?id='+m.id+'&n='+i+'" target="_blank" rel="noopener" onclick="event.stopPropagation()">'+
        '<span class="ic">PDF</span><span>'+esc(a.name)+'</span><span class="sz">'+fmtSize(a.size)+'</span></a>'
      ).join('');
      return (
        '<div class="'+cls+'" onclick="toggle('+m.id+')">'+
          '<div class="avatar" style="background:'+(m.is_new?'':color(m.from_name))+'">'+initial(m.from_name)+'</div>'+
          '<div class="main">'+
            '<div class="line1"><span class="from">'+esc(m.from_name)+'</span>'+newpill+'<span class="time">'+esc(m.time)+'</span></div>'+
            '<div class="subj">'+esc(m.subject)+clip+'</div>'+
            '<div class="snip">'+esc((m.body||'').replace(/\\s+/g,' ').slice(0,120))+'</div>'+
          '</div>'+rdot+
        '</div>'+
        '<div class="body '+(opened?'':'hide')+'">'+
          '<div class="bodycard"><p class="bodytext">'+esc(m.body||'(kein Text)')+'</p>'+
          (atts?('<div class="atts">'+atts+'</div>'):'')+'</div>'+
        '</div>'
      );
    }).join('');
    mails.forEach(m=>known.add(m.id));
    first=false;
  }

  function toggle(id){ openId = (openId===id? null : id); poll(true); }

  async function poll(immediate){
    try{
      const r = await fetch('/api/inbox',{cache:'no-store'});
      const mails = await r.json();
      render(mails);
    }catch(e){ /* still — nächster Tick versucht es erneut */ }
  }
  poll();
  setInterval(poll, 2500);
</script>
</body>
</html>"""


# ---------------------------------------------------------------------------
#  HTTP-Server
# ---------------------------------------------------------------------------
class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # leise (kein Request-Log-Spam im Terminal)
        pass

    def _send(self, code, ctype, body: bytes, extra=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urlparse(self.path)
        if u.path in ("/", "/index.html"):
            self._send(200, "text/html; charset=utf-8", PAGE.encode("utf-8"))
            return
        if u.path == "/api/inbox":
            try:
                body = json.dumps(fetch_inbox()).encode("utf-8")
            except Exception as e:
                body = json.dumps({"error": str(e)}).encode("utf-8")
            self._send(200, "application/json; charset=utf-8", body)
            return
        if u.path == "/att":
            q = parse_qs(u.query)
            try:
                mid = int(q.get("id", ["0"])[0])
                idx = int(q.get("n", ["0"])[0])
                got = fetch_attachment(mid, idx)
            except Exception:
                got = None
            if not got:
                self._send(404, "text/plain; charset=utf-8", b"Anhang nicht gefunden")
                return
            fname, ctype, data = got
            disp = f'inline; filename="{fname}"'
            self._send(200, ctype or "application/octet-stream", data, {"Content-Disposition": disp})
            return
        self._send(404, "text/plain; charset=utf-8", b"not found")


def main():
    srv = ThreadingHTTPServer((HOST, PORT), Handler)
    print("─" * 58)
    print("  POSTEINGANG (read-only) läuft.")
    print(f"  → in Chrome öffnen:  http://localhost:{PORT}")
    print(f"  Postfach: {L.MAIL_USER}@{L.MAIL_DOMAIN}  (IMAP {L.IMAP_HOST}:{L.IMAP_PORT}, read-only)")
    print("  Stoppen: Strg+C")
    print("─" * 58)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n  Posteingang gestoppt.")
        srv.shutdown()


if __name__ == "__main__":
    main()
