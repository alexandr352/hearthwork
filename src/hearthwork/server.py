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

from . import awake, claude, home, spirit, worklog

KEY = secrets.token_urlsafe(24)
CHAT_LOCK = threading.Lock()
MAX_BODY = 64 * 1024


def stamp(h):
    """Changes whenever any record the page shows changes."""
    m = 0.0
    for p in home.projects(h):
        for f in (p.units_log, p.state_path):
            try:
                m = max(m, f.stat().st_mtime)
            except OSError:
                pass
        try:
            m = max(m, p.tickets.stat().st_mtime)
        except OSError:
            pass
    return m


def chat_session_path(h):
    return spirit.spirit_dir(h) / "chat-session"


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
        if url.path == "/api/stamp":
            if not self.authed(api=True):
                return self.send(HTTPStatus.FORBIDDEN, "no")
            return self.send(HTTPStatus.OK, json.dumps({"stamp": stamp(self.h)}), "application/json")
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
            try:
                chat_session_path(self.h).unlink()
            except FileNotFoundError:
                pass
            return self.send(HTTPStatus.OK, '{"ok":true}', "application/json")
        if url.path == "/api/chat":
            return self.chat(str(body.get("message") or "").strip(), body.get("about"))
        return self.send(HTTPStatus.NOT_FOUND, "not found")

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
        if about and isinstance(about, dict):
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
        final = None
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
                    self.emit({"type": "text", "text": d.get("text", "")})
            elif t == "assistant":
                for block in (ev.get("message") or {}).get("content") or []:
                    if block.get("type") == "tool_use":
                        self.emit({"type": "tool", "text": describe_tool(block.get("name"), block.get("input"))})
            elif t == "result":
                final = ev
        p.wait(timeout=30)
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
        self.emit({"type": "done", "cost_usd": cost, "seconds": rec["seconds"]})


def serve(port=0, open_browser=True):
    h = home.home_dir()
    Handler.h = h
    Handler.cfg = home.load_config(h)
    Handler.awake = awake.from_config(Handler.cfg, why="the hearthwork spirit is answering")
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
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
.msg.sys{color:var(--mute);font-size:13px}.msg.err{color:var(--red)}
.tool{font:12px ui-monospace,Menlo,monospace;color:var(--mute);border-left:2px solid var(--line);padding-left:8px;white-space:pre-wrap;word-break:break-all}
.meta-line{font-size:11px;color:var(--mute)}
#chat-about{display:flex;align-items:center;gap:8px;margin:0 14px;padding:6px 10px;border:1px dashed var(--accent);border-radius:8px;font-size:12px;color:var(--accent)}
#chat-about span{flex:1}
#chat-about[hidden],.pill[hidden],button[hidden]{display:none}
#chat-form{display:flex;align-items:center;gap:8px;padding:12px 16px 16px 14px;border-top:1px solid var(--line)}
#chat-in{flex:1;height:40px;resize:none;background:var(--bg);color:var(--ink);border:1px solid var(--line);border-radius:20px;padding:9px 16px;font:14px/20px system-ui,sans-serif;overflow-y:auto}
#chat-in:focus{outline:none;border-color:var(--accent)}
.pill{height:40px;min-width:80px;padding:0 18px;border:0;border-radius:20px;background:var(--accent);color:#fff;font:600 14px/40px system-ui,sans-serif;cursor:pointer;box-sizing:border-box}
.pill:disabled{opacity:.5;cursor:wait}
#chat-open{position:fixed;right:16px;bottom:16px;z-index:5}
button.ask{background:none;border:1px solid var(--accent);color:var(--accent);border-radius:6px;padding:2px 8px;margin:6px 0;cursor:pointer;font-size:12px}
body.chat-hidden{padding-right:0}body.chat-hidden #chat{display:none}
</style>
<script>
(function(){
var KEY="{{KEY}}",log=document.getElementById('chat-log'),form=document.getElementById('chat-form'),input=document.getElementById('chat-in'),
    aboutBox=document.getElementById('chat-about'),about=null,spent=0,costEl=document.getElementById('chat-cost');
function add(cls,text){var d=document.createElement('div');d.className=cls;d.textContent=text;log.appendChild(d);log.scrollTop=log.scrollHeight;return d}
function setAbout(a){about=a;aboutBox.hidden=!a;if(a)aboutBox.querySelector('span').textContent='about '+a.project+' / '+a.ticket+(a.unit?' / unit '+a.unit:'');}
aboutBox.querySelector('button').onclick=function(){setAbout(null)};
document.addEventListener('click',function(e){var b=e.target.closest('button.ask');if(!b)return;var p=b.dataset.ask.split('|');
  setAbout({project:p[0],ticket:p[1],unit:p[2]||null});show(true);input.focus();if(!input.value)input.value=p[2]?'What happened in this unit, and what comes next?':'Why did this halt, and what should I decide?';});
function show(on){document.body.classList.toggle('chat-hidden',!on);document.getElementById('chat-open').hidden=on;try{localStorage.setItem('hw-chat',on?'1':'0')}catch(e){}}
document.getElementById('chat-min').onclick=function(){show(false)};document.getElementById('chat-open').onclick=function(){show(true)};
try{if(localStorage.getItem('hw-chat')==='0')show(false)}catch(e){}
document.getElementById('chat-new').onclick=function(){fetch('/api/new',{method:'POST',headers:{'X-HW-Key':KEY},body:'{}'});log.innerHTML='';add('msg sys','A new conversation. The spirit still remembers what it wrote to its memory.');};
input.addEventListener('keydown',function(e){if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();form.requestSubmit()}});
form.onsubmit=async function(e){e.preventDefault();var text=input.value.trim();if(!text)return;input.value='';add('msg me',text);
  var btn=form.querySelector('button');btn.disabled=true;var out=add('msg','…'),got=false,a=about;setAbout(null);
  try{var r=await fetch('/api/chat',{method:'POST',headers:{'X-HW-Key':KEY,'Content-Type':'application/json'},body:JSON.stringify({message:text,about:a})});
    if(!r.ok){out.className='msg err';out.textContent=await r.text();return}
    var rd=r.body.getReader(),dec=new TextDecoder(),buf='';
    while(true){var c=await rd.read();if(c.done)break;buf+=dec.decode(c.value,{stream:true});var lines=buf.split('\n');buf=lines.pop();
      lines.forEach(function(l){if(!l)return;var ev=JSON.parse(l);
        if(ev.type==='text'){if(!got){out.textContent='';got=true}out.textContent+=ev.text}
        else if(ev.type==='tool'){var t=document.createElement('div');t.className='tool';t.textContent=ev.text;log.insertBefore(t,out);if(got){out=add('msg','');got=false}}
        else if(ev.type==='error'){add('msg err',ev.text)}
        else if(ev.type==='done'){spent+=ev.cost_usd||0;costEl.textContent='$'+spent.toFixed(2)+' this page';add('meta-line','$'+(ev.cost_usd||0).toFixed(3)+' · '+ev.seconds+'s')}
        log.scrollTop=log.scrollHeight;});}
    if(!got&&out.textContent==='…')out.remove();
  }catch(err){add('msg err',String(err))}finally{btn.disabled=false;input.focus()}};
var wl=null,wantWake=false,wb=document.getElementById('wake');
wb.hidden=!('wakeLock' in navigator);
async function takeWake(){try{wl=await navigator.wakeLock.request('screen');wl.addEventListener('release',function(){wl=null;paintWake()})}catch(e){wl=null}paintWake()}
function paintWake(){wb.textContent=wl?'screen on ✓':'screen on';wb.style.color=wl?'var(--green)':''}
wb.onclick=async function(){wantWake=!wantWake;if(wantWake)await takeWake();else if(wl){await wl.release();wl=null;paintWake()}};
document.addEventListener('visibilitychange',function(){if(wantWake&&document.visibilityState==='visible'&&!wl)takeWake()});
var last=null;setInterval(async function(){try{var r=await fetch('/api/stamp',{headers:{'X-HW-Key':KEY}});var s=(await r.json()).stamp;
  if(last!==null&&s!==last){var html=await (await fetch('/api/log',{headers:{'X-HW-Key':KEY}})).text();var doc=new DOMParser().parseFromString(html,'text/html');
    var open=[].slice.call(document.querySelectorAll('#log details[open]')).map(function(d){return d.id});var fresh=doc.getElementById('log');
    if(fresh){document.getElementById('log').replaceWith(fresh);open.forEach(function(id){var d=id&&document.getElementById(id);if(d)d.open=true})}}
  last=s}catch(e){}},4000);
})();
</script>
"""
