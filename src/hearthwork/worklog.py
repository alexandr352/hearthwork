"""The work log: one self-contained HTML page in the home, rebuilt from the records
after every unit. The model never writes it, so it can only show what the records hold.
"""

import html
import json
import time
from datetime import datetime, timezone

from . import home
from .records import Ticket, read_meter

CLIP = 16000


def esc(s):
    return html.escape(str(s if s is not None else ""))


def read_text(path, clip=CLIP):
    try:
        t = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    return t if len(t) <= clip else t[:clip] + f"\n\n[... {len(t) - clip} more characters in {path.name}]"


def money(x):
    return f"${x:,.2f}"


def cache_rate(rows):
    read = total = 0
    for r in rows:
        for calls in (r.get("phases") or {}).values():
            for c in calls:
                u = c.get("usage") or {}
                cr = u.get("cache_read_input_tokens") or 0
                read += cr
                total += cr + (u.get("input_tokens") or 0) + (u.get("cache_creation_input_tokens") or 0)
    return (read / total) if total else None


def unit_state(rec):
    v = rec.get("verdict") or {}
    o = rec.get("outcome")
    if o in ("halted", "failed") or v.get("action") == "halt":
        return "red"
    if o == "walled" or rec.get("recovered") or not v.get("unit_done", True) or any(
            len(calls) > 1 for k, calls in (rec.get("phases") or {}).items() if k in ("plan", "judge")):
        return "amber"
    return "green"


def phase_line(rec):
    parts = []
    for name in ("plan", "execute", "survey", "judge"):
        calls = (rec.get("phases") or {}).get(name)
        if not calls:
            continue
        metered = [c for c in calls if c.get("cost_usd") is not None]
        cost = money(sum(c["cost_usd"] for c in metered)) if metered else "not metered"
        secs = sum(c.get("seconds") or 0 for c in calls)
        tries = f" ×{len(calls)}" if len(calls) > 1 else ""
        model = calls[-1].get("model", "")
        parts.append(f"<span class=ph><b>{name}</b>{tries} {esc(model)} · {secs / 60:.1f} min · {cost}</span>")
    return "".join(parts)


def unit_card(p, rec, ui=False):
    t = Ticket(p, rec["ticket"])
    n = rec.get("unit")
    d = t.unit_dir(n) if n else None
    v = rec.get("verdict") or {}
    state = unit_state(rec)
    files = []
    for name, label in (("prompt.md", "Prompt the operator wrote"), ("report.md", "Executor report"),
                        ("survey.md", "Survey of the tree"), ("facts.md", "Repository facts (from git)")):
        txt = read_text(d / name) if d else None
        if txt:
            files.append(f"<details class=file><summary>{label}</summary><pre>{esc(txt)}</pre></details>")
    when = esc((rec.get("ts") or "").replace("T", " ").replace("Z", " UTC"))
    git = rec.get("git") or {}
    gitline = (f"{git.get('commits', 0)} commit(s), {git.get('files', 0)} file(s), tree "
               f"{'clean' if git.get('clean') else 'dirty'}") if git else ""
    return f"""
<details class="unit {state}" id="u-{esc(p.name)}-{esc(rec['ticket'])}-{n}">
  <summary><span class=dot></span><b>unit {n}</b> <span class=kind>{esc(rec.get('kind') or '')}</span>
    <span class=title>{esc(rec.get('title') or rec.get('outcome') or '')}</span>
    <span class=cost>{money(rec.get('cost_usd') or 0)}</span></summary>
  <div class=body>
    <div class=meta>{when} · {rec.get('seconds', 0) / 60:.1f} min · {esc(gitline)}{' · recovered: ' + esc(rec['recovered']) if rec.get('recovered') else ''}</div>
    <div class=verdict><b>{esc(v.get('action') or rec.get('outcome') or '')}</b> — {esc(v.get('reason') or '')}</div>
    {f'<div class=next>next: {esc(v.get("next"))}</div>' if v.get('next') else ''}
    <div class=phases>{phase_line(rec)}</div>
    {f'<button class=ask data-ask="{esc(p.name)}|{esc(rec["ticket"])}|{n}">ask the spirit about this unit</button>' if ui else ''}
    {''.join(files)}
  </div>
</details>"""


def render(home_path=None, ui=False):
    h = home_path or home.home_dir()
    projects = home.projects(h)
    now = time.time()
    day_ago, week_ago = now - 86400, now - 7 * 86400

    def ts(r):
        try:
            return datetime.strptime(r["ts"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()
        except (KeyError, ValueError):
            return 0

    all_rows = []
    sections, banners = [], []
    for p in projects:
        st = p.read_state()
        rows = read_meter(p)
        all_rows += rows
        if st.get("halted"):
            hl = st["halted"]
            banners.append(f"""<div class=halt><b>{esc(p.name)} is halted</b> on {esc(hl.get('ticket'))}
              {('unit ' + esc(hl.get('unit'))) if hl.get('unit') else ''}: {esc(hl.get('reason'))}
              <div class=hint>answer with <code>operator rule "…"</code>, or talk it through with the spirit
              (<code>operator chat</code>)</div>
              {f'<button class=ask data-ask="{esc(p.name)}|{esc(hl.get("ticket"))}|{esc(hl.get("unit") or "")}">talk it through here</button>' if ui else ''}</div>""")
        by_ticket = {}
        for r in rows:
            by_ticket.setdefault(r.get("ticket"), []).append(r)
        order = sorted(by_ticket, key=lambda k: max(ts(r) for r in by_ticket[k]), reverse=True)
        tickets_html = []
        for tid in order:
            trs = sorted(by_ticket[tid], key=lambda r: (r.get("unit") or 0, ts(r)))
            t = Ticket(p, tid)
            meta = t.read("meta.json") or {}
            last_v = next((r.get("verdict") for r in reversed(trs) if r.get("verdict")), None) or {}
            done, planned = last_v.get("units_done"), last_v.get("units_planned")
            status = ("ready" if tid in (st.get("ready") or []) else
                      "halted" if (st.get("halted") or {}).get("ticket") == tid else
                      "active" if st.get("active_ticket") == tid else "idle")
            strip = "".join(
                f'<a class="cell {unit_state(r)}" href="#u-{esc(p.name)}-{esc(tid)}-{r.get("unit")}" '
                f'title="unit {r.get("unit")}: {esc(r.get("title") or r.get("outcome"))}"></a>' for r in trs)
            progress = f"{done} of {planned} units done" if planned else ""
            tickets_html.append(f"""
<section class=ticket>
  <header><h3>{esc(tid)} <span class="badge {status}">{status}</span></h3>
    <div class=sub>{esc(meta.get('title') or '')}</div>
    <div class=nums>{progress} · {len(trs)} runs · {money(sum(r.get('cost_usd') or 0 for r in trs))}</div>
    <div class=strip>{strip}</div>
    {f'<div class=next>next: {esc(last_v.get("next"))}</div>' if last_v.get('next') and status != 'ready' else ''}
  </header>
  {''.join(unit_card(p, r, ui) for r in reversed(trs))}
</section>""")
        sections.append(f"""<h2>{esc(p.name)} <span class=repo>{esc(p.repo)}</span></h2>
{''.join(tickets_html) or '<p class=empty>No units yet. <code>operator run</code> starts one.</p>'}""")

    day = [r for r in all_rows if ts(r) >= day_ago]
    week = [r for r in all_rows if ts(r) >= week_ago]
    rate = cache_rate(week)
    stats = f"""<div class=stats>
  <div><span>{money(sum(r.get('cost_usd') or 0 for r in day))}</span>today · {len(day)} units</div>
  <div><span>{money(sum(r.get('cost_usd') or 0 for r in week))}</span>7 days · {len(week)} units</div>
  <div><span>{f'{rate * 100:.0f}%' if rate is not None else '–'}</span>prompt cache hits, 7 days</div>
  <div><span>{money(sum(r.get('cost_usd') or 0 for r in all_rows))}</span>all time · {len(all_rows)} units</div>
</div>"""
    page = TEMPLATE.replace("{{BANNERS}}", "".join(banners)).replace("{{STATS}}", stats) \
        .replace("{{SECTIONS}}", "".join(sections) or "<p class=empty>No projects yet.</p>") \
        .replace("{{UPDATED}}", time.strftime("%Y-%m-%d %H:%M", time.localtime())) \
        .replace("{{REFRESH}}", "" if ui else '<meta http-equiv=refresh content=60>') \
        .replace("{{NOTE}}", "live" if ui else "refreshes every minute") \
        .replace("{{TOPBTN}}", '<button id=wake class=theme title="keep this screen on while the page is in front" hidden>screen on</button>' if ui else "")
    return page


def build(home_path=None):
    h = home_path or home.home_dir()
    path = h / "worklog.html"
    home.write_atomic(path, render(h))
    return path


TEMPLATE = """<!doctype html>
<html lang=en><head><meta charset=utf-8>
<meta name=viewport content="width=device-width, initial-scale=1">
{{REFRESH}}
<title>Hearthwork Log</title>
<style>
:root{--bg:#f7f5f0;--panel:#fff;--ink:#22201c;--mute:#6f6a60;--line:#e4dfd4;--green:#2f8f5b;--amber:#c98a12;--red:#c2412d;--accent:#b5532a}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){--bg:#171513;--panel:#211e1b;--ink:#ece6dc;--mute:#9b9488;--line:#34302b;--green:#4fb37d;--amber:#e0a63a;--red:#e2614b;--accent:#e08a5a}}
:root[data-theme=dark]{--bg:#171513;--panel:#211e1b;--ink:#ece6dc;--mute:#9b9488;--line:#34302b;--green:#4fb37d;--amber:#e0a63a;--red:#e2614b;--accent:#e08a5a}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:980px;margin:0 auto;padding:24px 16px 64px}
h1{font-size:22px;margin:0}h1 small{color:var(--mute);font-weight:400;font-size:13px;margin-left:8px}
h2{font-size:18px;margin:36px 0 12px}h2 .repo{color:var(--mute);font-weight:400;font-size:13px;margin-left:6px;word-break:break-all}
h3{margin:0;font-size:16px}
.top{display:flex;justify-content:space-between;align-items:baseline;gap:12px;flex-wrap:wrap}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:10px;margin:18px 0}
.stats div{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:12px 14px;color:var(--mute);font-size:13px}
.stats span{display:block;color:var(--ink);font-size:22px;font-weight:600}
.halt{background:color-mix(in srgb,var(--red) 12%,var(--panel));border:1px solid var(--red);border-radius:10px;padding:12px 14px;margin:12px 0}
.halt .hint{color:var(--mute);font-size:13px;margin-top:4px}
.ticket{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:14px;margin:12px 0}
.ticket .sub{color:var(--mute)}.nums{color:var(--mute);font-size:13px;margin-top:2px}
.badge{font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:.04em;padding:2px 7px;border-radius:99px;margin-left:6px;vertical-align:2px;border:1px solid var(--line);color:var(--mute)}
.badge.active{color:var(--accent);border-color:var(--accent)}.badge.ready{color:var(--green);border-color:var(--green)}.badge.halted{color:var(--red);border-color:var(--red)}
.strip{display:flex;flex-wrap:wrap;gap:4px;margin:10px 0 4px}
.cell{width:18px;height:18px;border-radius:4px;display:block}
.cell.green,.unit.green .dot{background:var(--green)}.cell.amber,.unit.amber .dot{background:var(--amber)}.cell.red,.unit.red .dot{background:var(--red)}
.next{font-size:13px;color:var(--mute);margin-top:4px}
.unit{border-top:1px solid var(--line);padding:8px 0}
.unit>summary{cursor:pointer;list-style:none;display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.unit>summary::-webkit-details-marker{display:none}
.dot{width:10px;height:10px;border-radius:50%;flex:none}
.kind{font-size:12px;color:var(--mute)}.title{flex:1;min-width:200px}.cost{color:var(--mute);font-variant-numeric:tabular-nums}
.body{padding:8px 0 4px 18px}.meta{font-size:12px;color:var(--mute)}.verdict{margin:6px 0}
.phases{display:flex;flex-wrap:wrap;gap:6px;margin:6px 0}.ph{font-size:12px;border:1px solid var(--line);border-radius:6px;padding:2px 7px;color:var(--mute)}.ph b{color:var(--ink);font-weight:600}
.file{margin:6px 0}.file summary{cursor:pointer;font-size:13px;color:var(--accent)}
pre{white-space:pre-wrap;word-break:break-word;background:var(--bg);border:1px solid var(--line);border-radius:8px;padding:10px;font:12.5px/1.45 ui-monospace,SFMono-Regular,Menlo,monospace;max-height:520px;overflow:auto}
code{font:13px ui-monospace,Menlo,monospace}.empty{color:var(--mute)}
.tools{display:flex;gap:8px}
button.theme{background:none;border:1px solid var(--line);color:var(--mute);border-radius:8px;padding:4px 10px;cursor:pointer;font:13px system-ui,sans-serif}
</style></head>
<body><main id=log>
<div class=top><h1>Hearthwork <small>updated {{UPDATED}} · {{NOTE}}</small></h1>
<span class=tools>{{TOPBTN}}<button class=theme onclick="var r=document.documentElement,d=r.dataset.theme==='dark'||(!r.dataset.theme&&matchMedia('(prefers-color-scheme: dark)').matches);r.dataset.theme=d?'light':'dark';try{localStorage.setItem('hw-theme',r.dataset.theme)}catch(e){}">theme</button></span></div>
{{BANNERS}}
{{STATS}}
{{SECTIONS}}
</main>
<script>
try{var t=localStorage.getItem('hw-theme');if(t)document.documentElement.dataset.theme=t}catch(e){}
if(location.hash){var el=document.querySelector(location.hash);if(el&&el.tagName==='DETAILS')el.open=true}
addEventListener('hashchange',function(){var el=document.querySelector(location.hash);if(el&&el.tagName==='DETAILS'){el.open=true}});
</script>
</body></html>
"""
