"""A single-page demo using only the standard library. No framework, no CDN."""

from __future__ import annotations

import dataclasses
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .engine import Engine

PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>QueryScope — natural language to SQL, without an LLM</title>
<style>
  :root { --bg:#0b1020; --panel:#131b33; --line:#263354; --text:#e8edff; --muted:#93a2c9;
          --accent:#5eead4; --accent2:#818cf8; --warn:#fbbf24; --bad:#fb7185; }
  * { box-sizing:border-box }
  body { margin:0; background:radial-gradient(1200px 600px at 80% -10%,#1c2a55 0%,var(--bg) 55%);
         color:var(--text); font:15px/1.55 ui-sans-serif,system-ui,-apple-system,Segoe UI,Roboto,sans-serif; min-height:100vh }
  .wrap { max-width:1040px; margin:0 auto; padding:48px 24px 80px }
  .eyebrow { color:var(--accent); letter-spacing:.18em; text-transform:uppercase; font-size:11px; font-weight:700 }
  h1 { font-size:44px; line-height:1.1; margin:12px 0 8px; letter-spacing:-.02em }
  h1 span { background:linear-gradient(90deg,var(--accent),var(--accent2)); -webkit-background-clip:text;
            background-clip:text; color:transparent }
  .lede { color:var(--muted); max-width:640px; font-size:16px; margin:0 0 28px }
  .stats { display:flex; flex-wrap:wrap; gap:12px; margin:0 0 32px }
  .stat { background:var(--panel); border:1px solid var(--line); border-radius:12px; padding:14px 18px; min-width:150px }
  .stat b { display:block; font-size:22px; color:var(--accent) }
  .stat small { color:var(--muted) }
  .card { background:rgba(19,27,51,.9); border:1px solid var(--line); border-radius:16px; padding:24px;
          box-shadow:0 24px 60px rgba(0,0,0,.35) }
  form { display:flex; gap:10px }
  input { flex:1; background:#0d1428; border:1px solid var(--line); border-radius:10px; color:var(--text);
          padding:14px 16px; font-size:15px; outline:none }
  input:focus { border-color:var(--accent) }
  button { background:linear-gradient(90deg,var(--accent),var(--accent2)); color:#071022; border:0;
           border-radius:10px; padding:14px 22px; font-weight:700; cursor:pointer }
  .examples { display:flex; flex-wrap:wrap; gap:8px; margin:14px 0 26px }
  .chip { background:#0d1428; border:1px solid var(--line); color:var(--muted); border-radius:999px;
          padding:7px 13px; font-size:12px; cursor:pointer }
  .chip:hover { border-color:var(--accent); color:var(--text) }
  .badge { display:inline-block; border-radius:999px; padding:4px 11px; font-size:11px; font-weight:700;
           letter-spacing:.08em; text-transform:uppercase }
  .ok { background:rgba(94,234,212,.12); color:var(--accent) }
  .warn { background:rgba(251,191,36,.12); color:var(--warn) }
  .bad { background:rgba(251,113,133,.12); color:var(--bad) }
  .meta { color:var(--muted); font-size:12px; margin:10px 0 18px }
  pre { background:#0a1022; border:1px solid var(--line); border-radius:10px; padding:16px; overflow:auto;
        font:12.5px/1.6 ui-monospace,SFMono-Regular,Consolas,monospace; color:#b8c7ef; white-space:pre-wrap }
  table { width:100%; border-collapse:collapse; margin-top:18px; font-size:13px }
  th,td { text-align:left; padding:9px 12px; border-bottom:1px solid var(--line) }
  th { color:var(--accent); font-size:11px; letter-spacing:.08em; text-transform:uppercase }
  .msg { background:rgba(251,191,36,.08); border:1px solid rgba(251,191,36,.3); border-radius:10px;
         padding:12px 14px; color:var(--warn); font-size:13px }
  footer { color:var(--muted); font-size:12px; margin-top:26px }
  .empty { color:var(--muted); padding:30px 0 }
</style>
</head>
<body>
<div class="wrap">
  <div class="eyebrow">Consulting portfolio · systems engineering</div>
  <h1>Ask your warehouse.<br><span>No API key required.</span></h1>
  <p class="lede">A typed compiler turns plain-English business questions into validated, parameterized SQL.
     Local retrieval decides intent. Nothing is sent anywhere, and no model API is called.</p>
  <div class="stats">
    <div class="stat"><b>$0</b><small>API cost per query</small></div>
    <div class="stat"><b>8</b><small>Intent families</small></div>
    <div class="stat"><b>SELECT</b><small>Only — writes impossible</small></div>
    <div class="stat"><b>60</b><small>Measured benchmark cases</small></div>
  </div>
  <div class="card">
    <form id="f"><input id="q" autocomplete="off" placeholder="e.g. top 5 products by revenue" autofocus>
      <button type="submit">Run query</button></form>
    <div class="examples" id="examples"></div>
    <div id="out"><div class="empty">Ask a question to see the generated plan, SQL and result set.</div></div>
    <footer>Read-only SQLite · bound parameters · timeout + row caps · fully offline after install</footer>
  </div>
</div>
<script>
const examples = ["total revenue by country", "top 5 products by revenue",
  "how many orders last quarter", "distribution of orders by status",
  "compare revenue in USA and UK", "monthly revenue this year",
  "delete all orders"];
const ex = document.getElementById('examples');
examples.forEach(e => { const b=document.createElement('button'); b.className='chip'; b.textContent=e;
  b.onclick=()=>{document.getElementById('q').value=e; document.getElementById('f').requestSubmit();};
  ex.appendChild(b); });
const esc = s => String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
document.getElementById('f').addEventListener('submit', async ev => {
  ev.preventDefault();
  const q = document.getElementById('q').value.trim(); if(!q) return;
  const out = document.getElementById('out'); out.innerHTML='<div class="empty">Compiling…</div>';
  try {
    const r = await fetch('/api/ask',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({question:q})});
    const a = await r.json();
    const cls = a.status==='answered'?'ok':(a.status==='needs_clarification'?'warn':'bad');
    let html = `<span class="badge ${cls}">${esc(a.status)}</span>
      <div class="meta">intent: ${esc(a.family||'-')} · confidence: ${a.confidence.toFixed(3)} ·
      ${a.latency_ms.toFixed(1)} ms · est. scan cost ${a.estimated_cost.toFixed(0)}</div>`;
    if(a.clarification) html += `<div class="msg">${esc(a.clarification)}</div>`;
    (a.diagnostics||[]).forEach(d=>{ html += `<div class="msg">${esc(d.code)}: ${esc(d.message)}</div>`; });
    if(a.sql) html += `<pre>${esc(a.sql)}\n\n-- params: ${esc(JSON.stringify(a.params))}</pre>`;
    if((a.rows||[]).length){
      html += '<table><thead><tr>'+(a.columns||[]).map(c=>`<th>${esc(c)}</th>`).join('')+'</tr></thead><tbody>'+
        a.rows.map(row=>'<tr>'+row.map(v=>`<td>${esc(v===null?'NULL':v)}</td>`).join('')+'</tr>').join('')+'</tbody></table>';
    }
    out.innerHTML=html;
  } catch(err) { out.innerHTML='<div class="msg">Request failed: '+esc(err)+'</div>'; }
});
</script>
</body></html>"""


def run_demo_server(engine: Engine, port: int = 8765) -> None:
    owner = engine

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args) -> None:
            return

        def _send(self, body: bytes, content_type: str) -> None:
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            self._send(PAGE.encode("utf-8"), "text/html; charset=utf-8")

        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", 0))
            payload = json.loads(self.rfile.read(length) or b"{}")
            answer = owner.ask(str(payload.get("question", "")))
            body = json.dumps(dataclasses.asdict(answer), default=str).encode("utf-8")
            self._send(body, "application/json")

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"QueryScope demo -> http://127.0.0.1:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
