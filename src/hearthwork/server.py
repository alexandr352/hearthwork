"""`operator ui`: the work log and the spirit's chat, served on this machine only.

It listens on 127.0.0.1, never on the network. Each start makes a random key and
prints a link carrying it; the page sets a cookie from it, and every API call must
also carry the key in a header, which a page on another site cannot send. Requests
whose Host is not this server's are refused (that stops DNS-rebinding tricks).

The chat is the same spirit as `operator chat`: same fence, same memory, same
commands, one ongoing session that a "new conversation" button starts afresh.
"""

import json
import os
import secrets
import shutil
import subprocess
import threading
import time
import webbrowser
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from . import awake, claude, economy, home, spirit, worklog

KEY = secrets.token_urlsafe(24)
CHAT_LOCK = threading.Lock()
MAX_BODY = 64 * 1024


def stamp(h):
    """Changes whenever any record the page shows changes."""
    m = 0.0
    for p in home.projects(h):
        for f in (p.units_log, p.state_path, p.dir / "atlas.md", p.dir / "running.json", p.dir / ".lock",
                  h / "usage.json"):
            try:
                m = max(m, f.stat().st_mtime)
            except OSError:
                pass
        try:
            m = max(m, p.tickets.stat().st_mtime)
        except OSError:
            pass
    return m


def repo_rows(h):
    return [{"project": p.name, "override": not p.repo_settings, "hooks": home.repo_hooks(p.repo)}
            for p in home.projects(h)]


def chat_session_path(h):
    return spirit.spirit_dir(h) / "chat-session"


def history_path(h):
    return spirit.spirit_dir(h) / "chat-history.jsonl"


HISTORY_KEEP = 300


def history_add(h, kind, text):
    """The conversation as the page shows it, so a reload brings it back."""
    with open(history_path(h), "a", encoding="utf-8") as f:
        f.write(json.dumps({"kind": kind, "text": text}) + "\n")


def history_read(h):
    try:
        lines = history_path(h).read_text(encoding="utf-8").splitlines()[-HISTORY_KEEP:]
    except OSError:
        return []
    out = []
    for line in lines:
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def describe_tool(name, inp):
    inp = inp or {}
    if name == "Bash":
        return "$ " + str(inp.get("command", ""))[:160]
    for k in ("file_path", "path", "pattern"):
        if inp.get(k):
            return f"{name.lower()} {str(inp[k])[:160]}"
    return name


class Handler(BaseHTTPRequestHandler):
    server_version = "hearthwork"
    h = None
    cfg = None
    awake = None

    def log_message(self, fmt, *args):
        pass

    # --- guards --------------------------------------------------------------

    def host_ok(self):
        host = (self.headers.get("Host") or "").lower()
        port = self.server.server_address[1]
        return host in (f"127.0.0.1:{port}", f"localhost:{port}")

    def cookie_key(self):
        c = SimpleCookie(self.headers.get("Cookie") or "")
        return c["hw"].value if "hw" in c else None

    def authed(self, api=False):
        if not self.host_ok():
            return False
        if api:
            return secrets.compare_digest(self.headers.get("X-HW-Key") or "", KEY)
        return secrets.compare_digest(self.cookie_key() or "", KEY)

    def send(self, code, body, ctype="text/plain; charset=utf-8", extra=None):
        data = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    # --- routes --------------------------------------------------------------

    def do_GET(self):
        url = urlparse(self.path)
        q = parse_qs(url.query)
        if url.path == "/" and q.get("k") and self.host_ok():
            if not secrets.compare_digest(q["k"][0], KEY):
                return self.send(HTTPStatus.FORBIDDEN, "wrong key: use the link `operator ui` printed")
            self.send_response(HTTPStatus.SEE_OTHER)
            self.send_header("Set-Cookie", f"hw={KEY}; HttpOnly; SameSite=Strict; Path=/")
            self.send_header("Location", "/")
            self.end_headers()
            return
        if url.path == "/":
            if not self.authed():
                return self.send(HTTPStatus.FORBIDDEN, "open the link `operator ui` printed (it carries the key)")
            page = worklog.render(self.h, ui=True).replace("</body>", CHAT_UI.replace("{{KEY}}", KEY) + "</body>")
            return self.send(HTTPStatus.OK, page, "text/html; charset=utf-8",
                             {"Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; "
                                                         "script-src 'unsafe-inline'; connect-src 'self'; img-src 'self' data:"})
        if url.path == "/worklog.html":
            self.send_response(HTTPStatus.SEE_OTHER)
            self.send_header("Location", "/")
            self.end_headers()
            return
        if url.path == "/stats.html":
            if not self.authed():
                return self.send(HTTPStatus.FORBIDDEN, "open the link `operator ui` printed (it carries the key)")
            from . import stats
            return self.send(HTTPStatus.OK, stats.build(self.h).read_bytes(), "text/html; charset=utf-8")
        if url.path.startswith("/archive/") or url.path.startswith("/projects/"):
            if not self.authed():
                return self.send(HTTPStatus.FORBIDDEN, "open the link `operator ui` printed (it carries the key)")
            return self.static(url.path)
        if url.path == "/api/stamp":
            if not self.authed(api=True):
                return self.send(HTTPStatus.FORBIDDEN, "no")
            return self.send(HTTPStatus.OK, json.dumps({"stamp": stamp(self.h)}), "application/json")
        if url.path == "/api/history":
            if not self.authed(api=True):
                return self.send(HTTPStatus.FORBIDDEN, "no")
            return self.send(HTTPStatus.OK, json.dumps(history_read(self.h)), "application/json")
        if url.path == "/api/repos":
            if not self.authed(api=True):
                return self.send(HTTPStatus.FORBIDDEN, "no")
            return self.send(HTTPStatus.OK, json.dumps(repo_rows(self.h)), "application/json")
        if url.path == "/api/economy":
            if not self.authed(api=True):
                return self.send(HTTPStatus.FORBIDDEN, "no")
            eco = economy.load(self.h)
            return self.send(HTTPStatus.OK, json.dumps({"economy": eco, "label": economy.label(eco)}), "application/json")
        if url.path == "/api/log":
            if not self.authed(api=True):
                return self.send(HTTPStatus.FORBIDDEN, "no")
            return self.send(HTTPStatus.OK, worklog.render(self.h, ui=True), "text/html; charset=utf-8")
        return self.send(HTTPStatus.NOT_FOUND, "not found")

    def do_POST(self):
        url = urlparse(self.path)
        if not self.authed(api=True):
            return self.send(HTTPStatus.FORBIDDEN, "no")
        n = int(self.headers.get("Content-Length") or 0)
        if n > MAX_BODY:
            return self.send(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "too long")
        try:
            body = json.loads(self.rfile.read(n) or b"{}")
        except ValueError:
            return self.send(HTTPStatus.BAD_REQUEST, "bad json")
        if url.path == "/api/new":
            for f in (chat_session_path(self.h), history_path(self.h)):
                try:
                    f.unlink()
                except FileNotFoundError:
                    pass
            return self.send(HTTPStatus.OK, '{"ok":true}', "application/json")
        if url.path == "/api/economy":
            try:
                eco = economy.save({k: body[k] for k in ("mcp", "claude_md", "cache") if k in body}, self.h)
            except ValueError as e:
                return self.send(HTTPStatus.BAD_REQUEST, str(e))
            return self.send(HTTPStatus.OK, json.dumps({"economy": eco, "label": economy.label(eco)}), "application/json")
        if url.path == "/api/repos":
            name, override = body.get("project"), body.get("override")
            p = next((x for x in home.projects(self.h) if x.name == name), None)
            if p is None or not isinstance(override, bool):
                return self.send(HTTPStatus.BAD_REQUEST, "project and override (true/false) are needed")
            home.set_repo_settings(p, not override)
            return self.send(HTTPStatus.OK, json.dumps(repo_rows(self.h)), "application/json")
        if url.path == "/api/chat":
            return self.chat(str(body.get("message") or "").strip(), body.get("about"))
        return self.send(HTTPStatus.NOT_FOUND, "not found")

    def static(self, path):
        """An archive page, or one record of a unit. Nothing else under the home is served."""
        import re as _re
        m = _re.fullmatch(r"/archive/(?:index\.html|([a-z0-9][a-z0-9._-]{0,63})/([A-Za-z0-9][A-Za-z0-9._-]{0,63})\.html)", path)
        if m:
            f = self.h / path.lstrip("/")
            ctype = "text/html; charset=utf-8"
        else:
            m = _re.fullmatch(r"/projects/([a-z0-9][a-z0-9._-]{0,63})/tickets/([A-Za-z0-9][A-Za-z0-9._-]{0,63})"
                              r"/units/(\d{2,4})/([a-z]+\.md)", path)
            if not m or m.group(4) not in worklog.FILE_NAMES:
                return self.send(HTTPStatus.NOT_FOUND, "not found")
            f = self.h / path.lstrip("/")
            ctype = "text/plain; charset=utf-8"
        try:
            f = f.resolve()
            f.relative_to(self.h.resolve())
            data = f.read_bytes()
        except (OSError, ValueError):
            return self.send(HTTPStatus.NOT_FOUND, "not found")
        return self.send(HTTPStatus.OK, data, ctype)

    # --- the chat --------------------------------------------------------------

    def chat(self, message, about):
        if not message:
            return self.send(HTTPStatus.BAD_REQUEST, "empty")
        if not CHAT_LOCK.acquire(blocking=False):
            return self.send(HTTPStatus.CONFLICT, "the spirit is still answering the last message")
        try:
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/x-ndjson")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            with self.awake:
                self.stream_spirit(message, about)
        finally:
            CHAT_LOCK.release()

    def emit(self, obj):
        try:
            self.wfile.write((json.dumps(obj) + "\n").encode("utf-8"))
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass

    def stream_spirit(self, message, about):
        h = self.h
        sdir = spirit.spirit_dir(h)
        prompt = message
        if about and isinstance(about, dict) and about.get("ticket") == "next":
            prompt = ("[The person clicked the page's next-step banner. Run `operator next`, and help them do "
                      "that step: do it for them where they ask, and show the command each time.]\n\n" + message)
        elif about and isinstance(about, dict) and about.get("ticket") == "atlas":
            prompt = (f"[The person wants to work through the open questions of project {about.get('project')}'s "
                      f"atlas: ../projects/{about.get('project')}/atlas.md, and `operator atlas questions`.]\n\n" + message)
        elif about and isinstance(about, dict):
            ctx = (f"[The person is looking at project {about.get('project')}, ticket {about.get('ticket')}"
                   + (f", unit {about.get('unit')}" if about.get("unit") else "")
                   + ". Its records are under ../projects/{0}/tickets/{1}/.]".format(about.get("project"), about.get("ticket")))
            prompt = ctx + "\n\n" + message
        sid_path = chat_session_path(h)
        sid = sid_path.read_text().strip() if sid_path.exists() else None
        tail, env = spirit.launch(h)
        bin_ = shutil.which(self.cfg["claude"]["bin"]) or self.cfg["claude"]["bin"]
        cmd = [bin_, "--print", "--output-format", "stream-json", "--verbose", "--include-partial-messages",
               "--model", self.cfg["models"]["spirit"], *tail]
        if sid:
            cmd += ["--resume", sid]
        t0 = time.time()
        try:
            p = subprocess.Popen(cmd, cwd=sdir, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE, text=True, bufsize=1)
        except FileNotFoundError:
            return self.emit({"type": "error", "text": f"the Claude Code CLI was not found: {bin_}"})
        p.stdin.write(prompt)
        p.stdin.close()
        history_add(h, "me", message)
        final = None
        said = ""
        for line in p.stdout:
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            t = ev.get("type")
            if t == "stream_event":
                e = ev.get("event") or {}
                d = e.get("delta") or {}
                if e.get("type") == "content_block_delta" and d.get("type") == "text_delta":
                    said += d.get("text", "")
                    self.emit({"type": "text", "text": d.get("text", "")})
            elif t == "assistant":
                for block in (ev.get("message") or {}).get("content") or []:
                    if block.get("type") == "tool_use":
                        if said.strip():
                            history_add(h, "spirit", said)
                            said = ""
                        line = describe_tool(block.get("name"), block.get("input"))
                        history_add(h, "tool", line)
                        self.emit({"type": "tool", "text": line})
            elif t == "rate_limit_event":
                claude.note_usage(ev.get("rate_limit_info"))
            elif t == "result":
                final = ev
        p.wait(timeout=30)
        if said.strip():
            history_add(h, "spirit", said)
        if final is None:
            err = (p.stderr.read() or "").strip()[:400]
            return self.emit({"type": "error", "text": err or f"the spirit exited with {p.returncode}"})
        new_sid = final.get("session_id")
        if new_sid:
            home.write_atomic(sid_path, new_sid + "\n")
        costs = claude.CostLedger(sdir / "session-cost.json")
        cost, basis = costs.cost(new_sid, final.get("total_cost_usd"), bool(sid))
        rec = {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "session_id": new_sid, "resumed": bool(sid),
               "seconds": round(time.time() - t0, 1), "cost_usd": cost, "cost_basis": basis,
               "is_error": final.get("is_error"), "chars_in": len(message)}
        with open(sdir / "chat.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(rec) + "\n")
        if final.get("is_error"):
            self.emit({"type": "error", "text": str(final.get("result"))[:400]})
        history_add(h, "meta", f"${(cost or 0):.3f} · {rec['seconds']}s")
        self.emit({"type": "done", "cost_usd": cost, "seconds": rec["seconds"]})


def serve(port=0, open_browser=True):
    h = home.home_dir()
    Handler.h = h
    Handler.cfg = home.load_config(h)
    Handler.awake = awake.from_config(Handler.cfg, why="the hearthwork spirit is answering")
    try:
        httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    except OSError as e:
        print(f"operator: cannot listen on 127.0.0.1:{port}: {e.strerror} "
              "(another `operator ui` may be running; omit --port to take a free one)", flush=True)
        return 2
    link = f"http://127.0.0.1:{httpd.server_address[1]}/?k={KEY}"
    print(f"hearthwork is served on this machine only:\n\n  {link}\n\nCtrl-C stops it.", flush=True)
    if open_browser and os.environ.get("DISPLAY") or open_browser and os.uname().sysname == "Darwin":
        threading.Timer(0.5, lambda: webbrowser.open(link)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
    return 0


CHAT_UI = r"""
<aside id=chat>
  <header><b>Spirit</b><span id=chat-cost></span><button id=chat-new title="start a new conversation">new</button><button id=chat-min title="hide">–</button></header>
  <div id=chat-log><div class="msg sys">Ask about any ticket or unit, a halt, what something cost, or what to do next. The spirit reads the records and acts only through <code>operator</code> commands.</div></div>
  <div id=chat-about hidden><span></span><button title="clear">×</button></div>
  <form id=chat-form><textarea id=chat-in rows=1 placeholder="Ask the spirit…"></textarea><button class=pill>Send</button></form>
</aside>
<button id=chat-open class=pill hidden>Spirit</button>
<div id=repos hidden role=dialog aria-label="repository settings">
  <h4>Repository settings</h4>
  <p class=eco-note>A repository's own Claude Code settings and hooks also run for the executor. A hook written for people at the keyboard can refuse what a unit needs. Changes apply from the next unit.</p>
  <div id=repo-rows></div>
  <p class=eco-note>The repository's CLAUDE.md is read either way.</p>
</div>
<div id=eco hidden role=dialog aria-label="token economy">
  <h4>Token economy <span id=eco-label></span></h4>
  <p class=eco-note>Changes apply from the next unit.</p>
  <label class=eco-row><input type=checkbox data-k=mcp><b>Disable MCP servers</b>
    <span>Saves tokens on every unit: your MCP servers' tool lists are left out of the executor's starting context (3,200 tokens measured with four connectors). Drawback: the executor can't use your servers (database, browser, tracker).</span></label>
  <label class=eco-row><input type=checkbox data-k=claude_md><b>Control CLAUDE.md loading</b>
    <span>Leaves out your global <code>~/.claude/CLAUDE.md</code> and any CLAUDE.md in folders above the repository, and loads only what the task needs: hearthwork's doctrine and the repository's own CLAUDE.md. Drawback: your personal global coding preferences don't reach the executor.</span></label>
  <label class=eco-row><input type=checkbox data-k=cache><b>Control prompt cache lifetime</b>
    <span>Hearthwork picks the cache lifetime per role: 1 hour for the operator, which resumes after a whole unit, and 5 minutes for the executor, whose turns are seconds apart. A 5-minute cache write costs 37.5% less than a 1-hour one.</span></label>
  <p class=eco-note>Always enabled: each role gets only the tools it needs · no background tasks · the fence.</p>
</div>
<style>
body{padding-right:400px}@media(max-width:900px){body{padding-right:0}}
#chat{position:fixed;top:0;right:0;width:400px;height:100vh;background:var(--panel);border-left:1px solid var(--line);display:flex;flex-direction:column;z-index:5}
@media(max-width:900px){#chat{width:100%;height:70vh;top:auto;bottom:0;border-left:0;border-top:1px solid var(--line);box-shadow:0 -8px 24px rgba(0,0,0,.15)}}
#chat header{display:flex;align-items:center;gap:8px;padding:12px 14px;border-bottom:1px solid var(--line)}
#chat header b{flex:1}#chat-cost{color:var(--mute);font-size:12px}
#chat header button,#chat-about button{background:none;border:1px solid var(--line);color:var(--mute);border-radius:6px;padding:2px 8px;cursor:pointer}
#chat-log{flex:1;overflow:auto;padding:12px 14px;display:flex;flex-direction:column;gap:10px}
.msg{white-space:pre-wrap;word-break:break-word;font-size:14px;line-height:1.5}
.msg.me{align-self:flex-end;background:color-mix(in srgb,var(--accent) 14%,var(--panel));border-radius:12px 12px 2px 12px;padding:8px 11px;max-width:85%}
.msg.sys{color:var(--mute);font-size:13px}
.msg.md{white-space:normal}.msg.md p{margin:0 0 8px}.msg.md ul,.msg.md ol{margin:0 0 8px;padding-left:20px}.msg.md li{margin:2px 0}
.msg.md code{font:12.5px ui-monospace,Menlo,monospace;background:var(--bg);border:1px solid var(--line);border-radius:4px;padding:0 4px}
.mdpre{background:var(--bg);border:1px solid var(--line);border-radius:6px;padding:6px 8px;margin:4px 0 8px;overflow-x:auto;white-space:pre}
.msg.md .mdpre code{border:0;padding:0;background:none;border-radius:0}
table.md{border-collapse:collapse;font-size:12.5px;margin:4px 0 8px;width:100%}table.md th,table.md td{border-bottom:1px solid var(--line);padding:4px 6px;text-align:left}
table.md th{color:var(--mute);font-weight:600}.msg.err{color:var(--red)}
.tool{font:12px ui-monospace,Menlo,monospace;color:var(--mute);border-left:2px solid var(--line);padding-left:8px;white-space:pre-wrap;word-break:break-all}
.meta-line{font-size:11px;color:var(--mute)}
#chat-about{display:flex;align-items:center;gap:8px;margin:0 14px;padding:6px 10px;border:1px dashed var(--accent);border-radius:8px;font-size:12px;color:var(--accent)}
#chat-about span{flex:1}
#chat-about[hidden],.pill[hidden],button[hidden]{display:none}
#chat-form{display:flex;align-items:flex-end;gap:8px;padding:12px 16px 16px 14px;border-top:1px solid var(--line)}
#chat-in{flex:1;height:40px;min-height:40px;max-height:120px;resize:none;background:var(--bg);color:var(--ink);border:1px solid var(--line);border-radius:20px;padding:9px 16px;font:14px/20px system-ui,sans-serif;overflow-y:hidden;box-sizing:border-box}
#chat-in:focus{outline:none;border-color:var(--accent)}
.pill{height:40px;min-width:80px;padding:0 18px;border:0;border-radius:20px;background:var(--accent);color:#fff;font:600 14px/40px system-ui,sans-serif;cursor:pointer;box-sizing:border-box}
.pill:disabled{opacity:.5;cursor:wait}
#chat-open{position:fixed;right:16px;bottom:16px;z-index:5}
#eco{position:fixed;top:64px;right:416px;width:min(380px,calc(100vw - 32px));background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:14px 16px;box-shadow:0 14px 36px rgba(0,0,0,.18);z-index:6}
@media(max-width:900px){#eco{right:16px}}body.chat-hidden #eco{right:16px}
#eco h4{margin:0 0 4px;font-size:15px}#eco-label{font-weight:400;color:var(--mute);font-size:12px}
.eco-row{display:grid;grid-template-columns:auto 1fr;gap:3px 10px;align-items:start;margin:12px 0;cursor:pointer}
.eco-row input{grid-row:span 2;margin-top:2px;accent-color:var(--accent);width:16px;height:16px}
.eco-row b{font-size:13.5px}
.eco-row span{grid-column:2;font-size:12.5px;color:var(--mute);line-height:1.45}
.eco-note{font-size:12px;color:var(--mute);margin:4px 0}
#eco[hidden],#repos[hidden]{display:none}
#repos{position:fixed;top:64px;right:416px;width:min(400px,calc(100vw - 32px));background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:14px 16px;box-shadow:0 14px 36px rgba(0,0,0,.18);z-index:6}
@media(max-width:900px){#repos{right:16px}}body.chat-hidden #repos{right:16px}
#repos h4{margin:0 0 4px;font-size:15px}
#repos .hooks{grid-column:2;font:12px ui-monospace,Menlo,monospace;color:var(--mute);margin-top:4px;word-break:break-all}
button.ask{background:none;border:1px solid var(--accent);color:var(--accent);border-radius:6px;padding:2px 8px;margin:6px 0;cursor:pointer;font-size:12px}
body.chat-hidden{padding-right:0}body.chat-hidden #chat{display:none}
</style>
<script>
function hwMarkdown(src){
  function esc(t){return t.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')}
  function inline(t){return esc(t).replace(/`([^`]+)`/g,'<code>$1</code>').replace(/\*\*([^*]+)\*\*/g,'<b>$1</b>').replace(/(^|[\s(])\*([^*\s][^*]*)\*(?=[\s).,;:!?]|$)/g,'$1<i>$2</i>')}
  var out=[],lines=src.replace(/\r/g,'').split('\n'),i=0;
  while(i<lines.length){var l=lines[i];
    if(/^\s*```/.test(l)){var code=[];i++;while(i<lines.length&&!/^\s*```/.test(lines[i])){code.push(lines[i]);i++}i++;
      out.push('<pre class=mdpre><code>'+esc(code.join('\n'))+'</code></pre>');continue}
    if(/^\s*\|/.test(l)){var rows=[];while(i<lines.length&&/^\s*\|/.test(lines[i])){rows.push(lines[i]);i++}
      var cells=function(r){return r.trim().replace(/^\||\|$/g,'').split('|').map(function(c){return c.trim()})};
      var body=rows.filter(function(r){return !/^\s*\|[\s:|-]+\|\s*$/.test(r)});
      var h=cells(body[0]||'');out.push('<table class=md><thead><tr>'+h.map(function(c){return '<th>'+inline(c)+'</th>'}).join('')+'</tr></thead><tbody>'+
        body.slice(1).map(function(r){return '<tr>'+cells(r).map(function(c){return '<td>'+inline(c)+'</td>'}).join('')+'</tr>'}).join('')+'</tbody></table>');continue}
    if(/^\s*[-*] /.test(l)){var items=[];while(i<lines.length&&(/^\s*[-*] /.test(lines[i])||(/^\s{2,}\S/.test(lines[i])&&items.length))){
        if(/^\s*[-*] /.test(lines[i]))items.push(lines[i].replace(/^\s*[-*] /,''));else items[items.length-1]+=' '+lines[i].trim();i++}
      out.push('<ul>'+items.map(function(t){return '<li>'+inline(t)+'</li>'}).join('')+'</ul>');continue}
    if(/^\s*\d+\. /.test(l)){var its=[];while(i<lines.length&&/^\s*\d+\. /.test(lines[i])){its.push(lines[i].replace(/^\s*\d+\. /,''));i++}
      out.push('<ol>'+its.map(function(t){return '<li>'+inline(t)+'</li>'}).join('')+'</ol>');continue}
    if(/^#{1,6} /.test(l)){out.push('<p><b>'+inline(l.replace(/^#+ /,''))+'</b></p>');i++;continue}
    if(!l.trim()){i++;continue}
    var para=[];while(i<lines.length&&lines[i].trim()&&!/^\s*(\||[-*] |\d+\. |#{1,6} )/.test(lines[i])){para.push(lines[i]);i++}
    out.push('<p>'+inline(para.join(' '))+'</p>')}
  return out.join('')}
window.hwMarkdown=hwMarkdown;
(function(){
var KEY="{{KEY}}",log=document.getElementById('chat-log'),form=document.getElementById('chat-form'),input=document.getElementById('chat-in'),
    aboutBox=document.getElementById('chat-about'),about=null,spent=0,costEl=document.getElementById('chat-cost');
function add(cls,text){var d=document.createElement('div');d.className=cls;d.textContent=text;log.appendChild(d);log.scrollTop=log.scrollHeight;return d}
function setAbout(a){about=a;aboutBox.hidden=!a;if(a)aboutBox.querySelector('span').textContent=a.ticket==='next'?'the next step':a.ticket==='atlas'?'about '+a.project+' / the atlas questions':'about '+a.project+' / '+a.ticket+(a.unit?' / unit '+a.unit:'');}
aboutBox.querySelector('button').onclick=function(){setAbout(null)};
document.addEventListener('click',function(e){var b=e.target.closest('button.ask');if(!b)return;var p=b.dataset.ask.split('|');
  setAbout({project:p[0],ticket:p[1],unit:p[2]||null});show(true);input.focus();if(!input.value&&b.dataset.text)input.value=b.dataset.text;if(!input.value)input.value=p[1]==='atlas'?'Let\'s go through the open atlas questions, one at a time.':p[2]?'What happened in this unit, and what comes next?':'Why did this halt, and what should I decide?';});
function show(on){document.body.classList.toggle('chat-hidden',!on);setTimeout(function(){try{fit()}catch(e){}},0);document.getElementById('chat-open').hidden=on;try{localStorage.setItem('hw-chat',on?'1':'0')}catch(e){}}
document.getElementById('chat-min').onclick=function(){show(false)};document.getElementById('chat-open').onclick=function(){show(true)};
try{if(localStorage.getItem('hw-chat')==='0')show(false)}catch(e){}
document.getElementById('chat-new').onclick=function(){fetch('/api/new',{method:'POST',headers:{'X-HW-Key':KEY},body:'{}'});log.innerHTML='';add('msg sys','A new conversation. The spirit still remembers what it wrote to its memory.');};
input.addEventListener('keydown',function(e){if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();form.requestSubmit()}});
function fit(){input.style.height='40px';var h=Math.min(input.scrollHeight+2,120);input.style.height=(h>42?h:40)+'px';input.style.overflowY=input.scrollHeight+2>120?'auto':'hidden'}
input.addEventListener('input',fit);window.addEventListener('resize',fit);
if(document.fonts&&document.fonts.ready)document.fonts.ready.then(fit);setTimeout(fit,0);
form.onsubmit=async function(e){e.preventDefault();var text=input.value.trim();if(!text)return;input.value='';fit();add('msg me',text);
  var btn=form.querySelector('button');btn.disabled=true;var out=add('msg','…'),got=false,a=about;setAbout(null);
  try{var r=await fetch('/api/chat',{method:'POST',headers:{'X-HW-Key':KEY,'Content-Type':'application/json'},body:JSON.stringify({message:text,about:a})});
    if(!r.ok){out.className='msg err';out.textContent=await r.text();return}
    var rd=r.body.getReader(),dec=new TextDecoder(),buf='';
    while(true){var c=await rd.read();if(c.done)break;buf+=dec.decode(c.value,{stream:true});var lines=buf.split('\n');buf=lines.pop();
      lines.forEach(function(l){if(!l)return;var ev=JSON.parse(l);
        if(ev.type==='text'){if(!got){out.dataset.raw='';got=true}out.dataset.raw+=ev.text;out.className='msg md';out.innerHTML=hwMarkdown(out.dataset.raw)}
        else if(ev.type==='tool'){var t=document.createElement('div');t.className='tool';t.textContent=ev.text;log.insertBefore(t,out);if(got){out=add('msg','');got=false}}
        else if(ev.type==='error'){add('msg err',ev.text)}
        else if(ev.type==='done'){spent+=ev.cost_usd||0;costEl.textContent='$'+spent.toFixed(2)+' this page';add('meta-line','$'+(ev.cost_usd||0).toFixed(3)+' · '+ev.seconds+'s');if(window.hwCheckNow)window.hwCheckNow()}
        log.scrollTop=log.scrollHeight;});}
    if(!got&&out.textContent==='…')out.remove();
  }catch(err){add('msg err',String(err))}finally{btn.disabled=false;input.focus()}};
fetch('/api/history',{headers:{'X-HW-Key':KEY}}).then(function(r){return r.json()}).then(function(items){
  if(!items.length)return;items.forEach(function(m){
    if(m.kind==='me')add('msg me',m.text);else if(m.kind==='tool')add('tool',m.text);else if(m.kind==='meta')add('meta-line',m.text);
    else{var d=add('msg md','');d.innerHTML=hwMarkdown(m.text)}});log.scrollTop=log.scrollHeight}).catch(function(){});
setInterval(function(){document.querySelectorAll('.runcard[data-started]').forEach(function(c){var e=c.querySelector('.elapsed');
  if(e)e.textContent=Math.max(0,Math.round((Date.now()/1000-Number(c.dataset.started))/60))+' min'})},20000);
var repoBox=document.getElementById('repos');
function paintRepos(rows){var c=document.getElementById('repo-rows');c.innerHTML='';
  if(!rows.length){c.innerHTML='<p class=eco-note>No projects yet.</p>';return}
  rows.forEach(function(r){var l=document.createElement('label');l.className='eco-row';
    var i=document.createElement('input');i.type='checkbox';i.checked=r.override;i.dataset.project=r.project;
    var b=document.createElement('b');b.textContent='Override '+r.project+'\'s repository settings — rely on the fence';
    var s=document.createElement('span');s.textContent=r.override?'The executor works under hearthwork\'s fence only.':'The repository\'s own settings and hooks run for the executor too.';
    var h=document.createElement('div');h.className='hooks';h.textContent=r.hooks.length?r.hooks.map(function(x){return x.split('  (')[0]}).join('\n'):'no hooks found in this repository';
    l.appendChild(i);l.appendChild(b);l.appendChild(s);l.appendChild(h);c.appendChild(l)})}
window.hwPaintRepos=paintRepos;function loadRepos(){fetch('/api/repos',{headers:{'X-HW-Key':KEY}}).then(function(r){return r.json()}).then(paintRepos).catch(function(){})}
repoBox.addEventListener('change',function(e){var i=e.target;if(!i.dataset.project)return;
  fetch('/api/repos',{method:'POST',headers:{'X-HW-Key':KEY,'Content-Type':'application/json'},body:JSON.stringify({project:i.dataset.project,override:i.checked})}).then(function(r){return r.json()}).then(paintRepos)});
var ecoBox=document.getElementById('eco'),lastEco=null,wl=null,wantWake=false;
function ecoBtn(){return document.getElementById('eco-btn')}
function paintEco(d){if(d)lastEco=d;d=lastEco;if(!d)return;ecoBox.querySelectorAll('input').forEach(function(i){var k=i.dataset.k;i.checked=k==='cache'?d.economy.cache==='policy':!d.economy[k]});
  document.getElementById('eco-label').textContent='· '+d.label;var b=ecoBtn();if(b)b.textContent='economy: '+d.label}
function paintWake(){var b=document.getElementById('wake');if(!b)return;b.hidden=!('wakeLock' in navigator);b.textContent=wl?'screen on ✓':'screen on';b.style.color=wl?'var(--green)':''}
async function takeWake(){try{wl=await navigator.wakeLock.request('screen');wl.addEventListener('release',function(){wl=null;paintWake()})}catch(e){wl=null}paintWake()}
function paintTop(){paintEco();paintWake()}
fetch('/api/economy',{headers:{'X-HW-Key':KEY}}).then(function(r){return r.json()}).then(paintEco).catch(function(){});
paintWake();
document.addEventListener('click',async function(e){
  if(e.target.closest('#repos-btn')){e.stopPropagation();ecoBox.hidden=true;repoBox.hidden=!repoBox.hidden;if(!repoBox.hidden)loadRepos();return}
  if(e.target.closest('#eco-btn')){e.stopPropagation();repoBox.hidden=true;ecoBox.hidden=!ecoBox.hidden;return}
  if(!repoBox.hidden&&!repoBox.contains(e.target))repoBox.hidden=true;
  if(e.target.closest('#wake')){wantWake=!wantWake;if(wantWake)await takeWake();else if(wl){await wl.release();wl=null;paintWake()}return}
  if(!ecoBox.hidden&&!ecoBox.contains(e.target))ecoBox.hidden=true});
document.addEventListener('keydown',function(e){if(e.key==='Escape'){ecoBox.hidden=true;repoBox.hidden=true}});
ecoBox.addEventListener('change',function(e){var i=e.target,k=i.dataset.k,b={};b[k]=k==='cache'?(i.checked?'policy':'auto'):!i.checked;
  fetch('/api/economy',{method:'POST',headers:{'X-HW-Key':KEY,'Content-Type':'application/json'},body:JSON.stringify(b)}).then(function(r){return r.json()}).then(paintEco)});
document.addEventListener('visibilitychange',function(){if(wantWake&&document.visibilityState==='visible'&&!wl)takeWake()});
document.addEventListener('toggle',function(e){var d=e.target;if(!d.open||!d.dataset||!d.dataset.src||d.dataset.loaded)return;d.dataset.loaded='1';
  fetch(d.dataset.src).then(function(r){return r.ok?r.text():Promise.reject(r.status)}).then(function(t){d.querySelector('pre').textContent=t}).catch(function(x){d.querySelector('pre').textContent='could not load ('+x+')'})},true);
var last=null;async function check(){try{var r=await fetch('/api/stamp',{headers:{'X-HW-Key':KEY}});var s=(await r.json()).stamp;
  if(last!==null&&s!==last){var html=await (await fetch('/api/log',{headers:{'X-HW-Key':KEY}})).text();var doc=new DOMParser().parseFromString(html,'text/html');
    var open=[].slice.call(document.querySelectorAll('#log details[open]')).map(function(d){return d.id});var fresh=doc.getElementById('log');
    if(fresh){document.getElementById('log').replaceWith(fresh);open.forEach(function(id){var d=id&&document.getElementById(id);if(d)d.open=true});paintTop()}}
  last=s}catch(e){}};window.hwCheckNow=check;setInterval(check,4000);
})();
</script>
"""
