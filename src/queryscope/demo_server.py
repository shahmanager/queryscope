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
<title>QueryScope — Natural language to SQL</title>
<style>
  :root {
    --bg: #f4f6f9;
    --surface: #ffffff;
    --border: #dce3ec;
    --border-strong: #c4cfdd;
    --text: #1b2434;
    --muted: #64748b;
    --faint: #94a3b8;
    --accent: #1d4ed8;
    --accent-hover: #1e40af;
    --accent-soft: #eff4ff;
    --success-bg: #e8f6ee;
    --success-fg: #17653c;
    --warn-bg: #fdf3dd;
    --warn-fg: #8a5a08;
    --bad-bg: #fdeaea;
    --bad-fg: #a12b2b;
    --code-bg: #f7f9fc;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0;
    background: var(--bg);
    color: var(--text);
    font: 14px/1.55 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
  }
  .topbar {
    background: var(--surface);
    border-bottom: 1px solid var(--border);
    height: 52px;
    display: flex;
    align-items: center;
    padding: 0 28px;
    gap: 12px;
  }
  .logo {
    width: 24px; height: 24px;
    background: var(--accent);
    color: #fff;
    border-radius: 4px;
    display: flex; align-items: center; justify-content: center;
    font-weight: 700; font-size: 13px;
  }
  .brand { font-weight: 650; letter-spacing: -0.01em; }
  .brand span { color: var(--faint); font-weight: 400; }
  .env {
    margin-left: auto;
    font-size: 11px;
    color: var(--muted);
    border: 1px solid var(--border);
    border-radius: 3px;
    padding: 3px 8px;
    background: var(--code-bg);
  }
  .wrap { max-width: 1040px; margin: 0 auto; padding: 36px 24px 72px; }
  .page-title { font-size: 26px; line-height: 1.2; margin: 0 0 6px; letter-spacing: -0.02em; font-weight: 650; }
  .page-sub { color: var(--muted); margin: 0 0 24px; max-width: 660px; }
  .stats { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-bottom: 24px; }
  .stat {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 5px;
    padding: 14px 16px;
  }
  .stat b { display: block; font-size: 20px; font-weight: 650; line-height: 1.2; }
  .stat small { color: var(--muted); font-size: 12px; }
  .panel {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 6px;
    box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
  }
  .panel-head {
    padding: 12px 18px;
    border-bottom: 1px solid var(--border);
    font-size: 12px;
    font-weight: 650;
    letter-spacing: 0.04em;
    text-transform: uppercase;
    color: var(--muted);
  }
  .panel-body { padding: 18px; }
  form { display: flex; gap: 8px; }
  input {
    flex: 1;
    background: #fff;
    border: 1px solid var(--border-strong);
    border-radius: 4px;
    color: var(--text);
    padding: 10px 12px;
    font-size: 14px;
    outline: none;
    font-family: inherit;
  }
  input:focus { border-color: var(--accent); box-shadow: 0 0 0 3px var(--accent-soft); }
  button.primary {
    background: var(--accent);
    color: #fff;
    border: 1px solid var(--accent);
    border-radius: 4px;
    padding: 10px 18px;
    font: inherit;
    font-weight: 600;
    cursor: pointer;
  }
  button.primary:hover { background: var(--accent-hover); border-color: var(--accent-hover); }
  .examples { display: flex; flex-wrap: wrap; gap: 6px; margin: 14px 0 4px; }
  .chip {
    background: #fff;
    border: 1px solid var(--border);
    color: var(--muted);
    border-radius: 4px;
    padding: 5px 10px;
    font: 12px inherit;
    cursor: pointer;
  }
  .chip:hover { border-color: var(--accent); color: var(--accent); }
  .result { border-top: 1px solid var(--border); margin-top: 18px; padding-top: 18px; }
  .badge {
    display: inline-block;
    border-radius: 3px;
    padding: 3px 9px;
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.05em;
    text-transform: uppercase;
  }
  .ok { background: var(--success-bg); color: var(--success-fg); }
  .warn { background: var(--warn-bg); color: var(--warn-fg); }
  .bad { background: var(--bad-bg); color: var(--bad-fg); }
  .meta { color: var(--muted); font-size: 12px; margin: 10px 0 14px; font-family: ui-monospace, SFMono-Regular, Consolas, monospace; }
  pre {
    background: var(--code-bg);
    border: 1px solid var(--border);
    border-radius: 4px;
    padding: 14px;
    overflow: auto;
    font: 12.5px/1.6 ui-monospace, SFMono-Regular, Consolas, monospace;
    color: #273449;
    white-space: pre-wrap;
    margin: 0;
  }
  table { width: 100%; border-collapse: collapse; margin-top: 18px; font-size: 13px; }
  th, td { text-align: left; padding: 9px 12px; border-bottom: 1px solid var(--border); }
  th {
    color: var(--muted);
    font-size: 11px;
    letter-spacing: 0.06em;
    text-transform: uppercase;
    background: var(--code-bg);
    border-top: 1px solid var(--border);
  }
  td:last-child, th:last-child { text-align: right; font-variant-numeric: tabular-nums; }
  .msg { border: 1px solid var(--border); border-left: 3px solid var(--warn-fg); background: var(--code-bg); border-radius: 3px; padding: 10px 12px; color: var(--text); font-size: 13px; margin-bottom: 8px; }
  .empty { color: var(--muted); padding: 28px 0; text-align: center; border-top: 1px solid var(--border); margin-top: 18px; }
  footer { color: var(--faint); font-size: 12px; margin-top: 20px; }
  @media (max-width: 720px) { .stats { grid-template-columns: repeat(2, 1fr); } }
</style>
</head>
<body>
<header class="topbar">
  <div class="logo">Q</div>
  <div class="brand">QueryScope <span>/ Workspace</span></div>
  <div class="env">LOCAL · READ-ONLY</div>
</header>
<div class="wrap">
  <h1 class="page-title">Query console</h1>
  <p class="page-sub">Ask a business question in plain English. The system resolves intent locally, compiles a validated query, and returns the result set.</p>

  <div class="stats">
    <div class="stat"><b>$0.00</b><small>API cost per query</small></div>
    <div class="stat"><b>8</b><small>Intent families</small></div>
    <div class="stat"><b>SELECT</b><small>Only — writes blocked</small></div>
    <div class="stat"><b>64</b><small>Benchmark cases</small></div>
  </div>

  <div class="panel">
    <div class="panel-head">New query</div>
    <div class="panel-body">
      <form id="f">
        <input id="q" autocomplete="off" placeholder="e.g. top 5 products by revenue" autofocus>
        <button class="primary" type="submit">Run query</button>
      </form>
      <div class="examples" id="examples"></div>
      <div id="out"><div class="empty">No query run yet.</div></div>
      <footer>All execution is read-only · values are bound parameters · no network calls</footer>
    </div>
  </div>
</div>
<script>
const examples = ["total revenue by country", "top 5 products by revenue",
  "how many orders last quarter", "distribution of orders by status",
  "compare revenue in USA and UK", "monthly revenue this year",
  "delete all orders"];
const ex = document.getElementById('examples');
examples.forEach(e => { const b=document.createElement('button'); b.className='chip'; b.type='button'; b.textContent=e;
  b.onclick=()=>{document.getElementById('q').value=e; document.getElementById('f').requestSubmit();};
  ex.appendChild(b); });
const esc = s => String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
document.getElementById('f').addEventListener('submit', async ev => {
  ev.preventDefault();
  const q = document.getElementById('q').value.trim(); if(!q) return;
  const out = document.getElementById('out'); out.innerHTML='<div class="empty">Running…</div>';
  try {
    const r = await fetch('/api/ask',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({question:q})});
    const a = await r.json();
    const cls = a.status==='answered'?'ok':(a.status==='needs_clarification'?'warn':'bad');
    let html = '<div class="result"><span class="badge '+cls+'">'+esc(a.status)+'</span>'+
      '<div class="meta">intent: '+esc(a.family||'-')+' · confidence: '+a.confidence.toFixed(3)+
      ' · '+a.latency_ms.toFixed(1)+' ms · scan cost '+a.estimated_cost.toFixed(0)+'</div>';
    if(a.clarification) html += '<div class="msg">'+esc(a.clarification)+'</div>';
    (a.diagnostics||[]).forEach(d=>{ html += '<div class="msg">'+esc(d.code)+': '+esc(d.message)+'</div>'; });
    if(a.sql) html += '<pre>'+esc(a.sql)+'\\n\\n-- params: '+esc(JSON.stringify(a.params))+'</pre>';
    if((a.rows||[]).length){
      html += '<table><thead><tr>'+(a.columns||[]).map(c=>'<th>'+esc(c)+'</th>').join('')+'</tr></thead><tbody>'+
        a.rows.map(row=>'<tr>'+row.map(v=>'<td>'+esc(v===null?'NULL':v)+'</td>').join('')+'</tr>').join('')+'</tbody></table>';
    }
    out.innerHTML=html+'</div>';
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
