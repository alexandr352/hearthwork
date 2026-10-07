"""The stats page: the whole history in numbers, week against week.

Built from the same records as the log (units.jsonl), by code, after every unit. It
shows what the log does not: totals over everything, a row per week to compare, and
where the money goes (by phase, by model, by kind of work).
"""

import time
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

from . import home, worklog
from .records import read_meter
from .worklog import esc, money, ts

WEEKS_CHARTED = 26


def week_of(t):
    d = datetime.fromtimestamp(t, tz=timezone.utc).date()
    y, w, _ = d.isocalendar()
    return y, w


def week_label(y, w):
    start = date.fromisocalendar(y, w, 1)
    end = start + timedelta(days=6)
    return f"{start:%b %-d}–{end:%b %-d}" if start.month != end.month else f"{start:%b %-d}–{end:%-d}"


def calls(r):
    for name, cs in (r.get("phases") or {}).items():
        for c in cs:
            yield name, c


def usage_totals(rows):
    read = total = 0
    for r in rows:
        for _, c in calls(r):
            u = c.get("usage") or {}
            cr = u.get("cache_read_input_tokens") or 0
            read += cr
            total += cr + (u.get("input_tokens") or 0) + (u.get("cache_creation_input_tokens") or 0)
    return read, total


def pct(a, b):
    return f"{a / b * 100:.0f}%" if b else "–"


def reconsidered(r):
    return any(len(cs) > 1 for name, cs in (r.get("phases") or {}).items() if name in ("plan", "judge"))


def halted(r):
    return r.get("outcome") in ("halted", "failed") or (r.get("verdict") or {}).get("action") == "halt"


def recovered(r):
    return bool(r.get("recovered")) or r.get("outcome") == "walled" or "survey" in (r.get("phases") or {})


def first_try(r):
    return not (reconsidered(r) or recovered(r) or halted(r))


def bar_chart(points, fmt, label):
    """Vertical bars, one per week; a tooltip on each; the newest on the right."""
    if not points:
        return "<p class=empty>No weeks yet.</p>"
    w, h, pad_l, pad_b, pad_t = 760, 180, 44, 24, 10
    n = len(points)
    top = max(v for _, v, _ in points) or 1
    slot = (w - pad_l) / n
    bw = max(6.0, min(28.0, slot - 2))
    marks, labels = [], []
    for i, (wk, v, tip) in enumerate(points):
        x = pad_l + i * slot + (slot - bw) / 2
        bh = (h - pad_b - pad_t) * (v / top)
        y = h - pad_b - bh
        r = min(4.0, bw / 2, bh / 2) if bh > 0 else 0
        path = (f"M{x:.1f},{h - pad_b:.1f} V{y + r:.1f} Q{x:.1f},{y:.1f} {x + r:.1f},{y:.1f} "
                f"H{x + bw - r:.1f} Q{x + bw:.1f},{y:.1f} {x + bw:.1f},{y + r:.1f} V{h - pad_b:.1f} Z") if bh > 0 else ""
        hit = f'<rect class=hit x="{pad_l + i * slot:.1f}" y="{pad_t}" width="{slot:.1f}" height="{h - pad_b - pad_t}" data-tip="{esc(tip)}"/>'
        marks.append((f'<path class=bar d="{path}"/>' if path else "") + hit)
        if i == n - 1 or i % max(1, n // 6) == 0:
            labels.append(f'<text class=xl x="{pad_l + i * slot + slot / 2:.1f}" y="{h - 6}">{esc(wk)}</text>')
    grid = "".join(f'<line class=grid x1="{pad_l}" x2="{w}" y1="{h - pad_b - (h - pad_b - pad_t) * f:.1f}" '
                   f'y2="{h - pad_b - (h - pad_b - pad_t) * f:.1f}"/><text class=yl x="{pad_l - 6}" '
                   f'y="{h - pad_b - (h - pad_b - pad_t) * f + 4:.1f}">{esc(fmt(top * f))}</text>' for f in (0.5, 1.0))
    base = f'<line class=axis x1="{pad_l}" x2="{w}" y1="{h - pad_b}" y2="{h - pad_b}"/>'
    return (f'<figure class=chart><figcaption>{esc(label)}</figcaption><svg viewBox="0 0 {w} {h}" role=img '
            f'aria-label="{esc(label)}, one bar per week; the table below has every value">'
            f"{grid}{base}{''.join(marks)}{''.join(labels)}</svg></figure>")


def share_rows(items, total, cols):
    """Table rows with an inline bar for the share of the total."""
    out = []
    for key, vals in items:
        share = (vals[-1] / total) if total else 0
        cells = "".join(f"<td class=num>{esc(v)}</td>" for v in cols(vals))
        out.append(f"<tr><th>{esc(key)}</th>{cells}<td class=sharecell><span class=share style='width:{share * 100:.1f}%'></span>"
                   f"<span class=sharepct>{share * 100:.0f}%</span></td></tr>")
    return "".join(out)


def build(h=None):
    h = h or home.home_dir()
    rows = []
    for p in home.projects(h):
        for r in read_meter(p):
            r = dict(r)
            r["_project"] = p
            rows.append(r)
    rows.sort(key=ts)
    cost = sum(r.get("cost_usd") or 0 for r in rows)
    ready = [r for r in rows if (r.get("verdict") or {}).get("action") == "ticket-ready"]
    tickets = {(r["_project"].name, r.get("ticket")) for r in rows}
    exec_hours = sum(c.get("seconds") or 0 for r in rows for n, c in calls(r) if n == "execute") / 3600
    cr, ctot = usage_totals(rows)
    tiles = f"""<div class=stats>
  <div><span>{money(cost)}</span>all time · {len(rows)} units</div>
  <div><span>{len(ready)}</span>tickets ready, of {len(tickets)} worked</div>
  <div><span>{money(cost / len(ready)) if ready else '–'}</span>per ready ticket, on average</div>
  <div><span>{pct(sum(first_try(r) for r in rows), len(rows))}</span>units done on the first try</div>
  <div><span>{pct(cr, ctot)}</span>of input tokens read from cache</div>
  <div><span>{f"{exec_hours:.1f} h" if exec_hours >= 1 else f"{exec_hours * 60:.0f} min"}</span>of executor work</div>
</div>"""

    # week by week
    weeks = defaultdict(list)
    for r in rows:
        if ts(r):
            weeks[week_of(ts(r))].append(r)
    keys = sorted(weeks)
    table, points_cost, points_units = [], [], []
    prev_cpu = None
    for y, w in keys:
        wr = weeks[(y, w)]
        c = sum(r.get("cost_usd") or 0 for r in wr)
        cpu = c / len(wr)
        a, b = usage_totals(wr)
        trend = ""
        if prev_cpu:
            change = (cpu - prev_cpu) / prev_cpu * 100
            trend = f"<span class={'up' if change > 0 else 'down'}>{'▲' if change > 0 else '▼'} {abs(change):.0f}%</span>" if abs(change) >= 1 else ""
        prev_cpu = cpu
        lbl = week_label(y, w)
        current = (y, w) == week_of(time.time())
        nready = sum((r.get("verdict") or {}).get("action") == "ticket-ready" for r in wr)
        table.append(f"<tr><th>{y}-W{w:02d}{'<span class=sofar>so far</span>' if current else ''}<small>{esc(lbl)}</small></th><td class=num>{len(wr)}</td><td class=num>{nready}</td>"
                     f"<td class=num>{money(c)}</td><td class=num>{money(cpu)} {trend}</td><td class=num>{pct(a, b)}</td>"
                     f"<td class=num>{pct(sum(first_try(r) for r in wr), len(wr))}</td><td class=num>{sum(reconsidered(r) for r in wr)}</td>"
                     f"<td class=num>{sum(recovered(r) for r in wr)}</td><td class=num>{sum(halted(r) for r in wr)}</td></tr>")
        sofar = " so far this week" if current else ""
        points_cost.append((lbl, c, f"{y}-W{w:02d} ({lbl}): {money(c)} over {len(wr)} units{sofar}"))
        points_units.append((lbl, len(wr), f"{y}-W{w:02d} ({lbl}): {len(wr)} units, {nready} tickets ready{sofar}"))
    week_table = ("<table class=data><thead><tr><th>week</th><th>units</th><th>tickets ready</th><th>cost</th>"
                  "<th>per unit</th><th>cache</th><th>first try</th><th>reconsidered</th><th>recovered</th><th>halted</th>"
                  "</tr></thead><tbody>" + "".join(reversed(table)) + "</tbody></table>") if table else ""
    charts = (bar_chart(points_cost[-WEEKS_CHARTED:], lambda v: f"${v:,.0f}" if v >= 10 else f"${v:,.2f}", "Cost per week")
              + bar_chart(points_units[-WEEKS_CHARTED:], lambda v: f"{v:,.0f}", "Units per week"))

    # where the money goes
    phases = defaultdict(lambda: [0, 0.0])
    models = defaultdict(lambda: [0, 0, 0.0])
    for r in rows:
        for name, c in calls(r):
            phases[name][0] += 1
            phases[name][1] += c.get("cost_usd") or 0
            m = models[c.get("model") or "?"]
            m[0] += 1
            u = c.get("usage") or {}
            m[1] += sum(u.get(k) or 0 for k in ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"))
            m[2] += c.get("cost_usd") or 0
    order = ["plan", "execute", "survey", "judge"]
    phase_items = sorted(phases.items(), key=lambda kv: order.index(kv[0]) if kv[0] in order else 9)
    phase_table = ("<table class=data><thead><tr><th>phase</th><th>calls</th><th>cost</th><th>share of cost</th></tr></thead><tbody>"
                   + share_rows(phase_items, cost, lambda v: (v[0], money(v[1]))) + "</tbody></table>")
    model_items = sorted(models.items(), key=lambda kv: -kv[1][2])
    model_table = ("<table class=data><thead><tr><th>model</th><th>calls</th><th>input tokens</th><th>cost</th><th>share of cost</th></tr></thead><tbody>"
                   + share_rows(model_items, cost, lambda v: (v[0], f"{v[1]:,}", money(v[2]))) + "</tbody></table>")

    # by kind of work, per ticket
    per_ticket = defaultdict(list)
    for r in rows:
        per_ticket[(r["_project"].name, r.get("ticket"))].append(r)
    kinds = defaultdict(lambda: [0, 0, 0, 0.0])
    for (pname, tid), trs in per_ticket.items():
        mode = worklog.ticket_mode(trs[0]["_project"], trs) or "not labelled"
        k = kinds[mode]
        k[0] += 1
        k[1] += any((r.get("verdict") or {}).get("action") == "ticket-ready" for r in trs)
        k[2] += len(trs)
        k[3] += sum(r.get("cost_usd") or 0 for r in trs)
    kind_items = sorted(kinds.items(), key=lambda kv: -kv[1][3])
    kind_table = ("<table class=data><thead><tr><th>kind of work</th><th>tickets</th><th>ready</th><th>units per ticket</th>"
                  "<th>cost per ticket</th><th>share of cost</th></tr></thead><tbody>"
                  + share_rows(kind_items, cost, lambda v: (v[0], v[1], f"{v[2] / v[0]:.1f}", money(v[3] / v[0])))
                  + "</tbody></table>")

    projects = home.projects(h)
    project_table = ""
    if len(projects) > 1:
        pitems = []
        for p in projects:
            pr = [r for r in rows if r["_project"] is p or r["_project"].name == p.name]
            if pr:
                pitems.append((p.name, [len(pr), sum((r.get("verdict") or {}).get("action") == "ticket-ready" for r in pr),
                                        sum(r.get("cost_usd") or 0 for r in pr)]))
        project_table = ("<h3>By project</h3><table class=data><thead><tr><th>project</th><th>units</th><th>tickets ready</th>"
                         "<th>cost</th><th>share of cost</th></tr></thead><tbody>"
                         + share_rows(pitems, cost, lambda v: (v[0], v[1], money(v[2]))) + "</tbody></table>")

    body = f"""{tiles}
<h3>Week by week</h3>
{charts}
{week_table or '<p class=empty>No units yet.</p>'}
<p class=hint>Per unit: the change against the week before. First try: no answer sent back for reconsideration, no
recovery, no halt. Reconsidered: an operator answer that broke its contract and was returned once or more. Recovered: a
usage limit resumed, a report judged on a later run, or a survey after a crash.</p>
<h3>Where the money goes</h3>
{phase_table}
{model_table}
<h3>By kind of work</h3>
{kind_table}
{project_table}"""
    page = worklog.page(body, title="Stats · Hearthwork", note="the whole history", nav="stats").replace("</style>", STYLE + "</style>", 1) \
        .replace("</body>", SCRIPT + "</body>", 1)
    path = h / "stats.html"
    home.write_atomic(path, page)
    return path


STYLE = """
:root{--bar:#b5532a}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){--bar:#d47a4c}}
:root[data-theme=dark]{--bar:#d47a4c}
.stats{grid-template-columns:repeat(auto-fit,minmax(140px,1fr))}
.sofar{font-size:11px;color:var(--mute);font-weight:400;margin-left:4px}
.chart{margin:14px 0 6px;background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:12px 14px 6px}
.chart figcaption{font-size:13px;font-weight:600;margin-bottom:4px}
.chart svg{width:100%;height:auto;display:block;overflow:visible}
.bar{fill:var(--bar)}.hit{fill:transparent}.hit:hover{fill:color-mix(in srgb,var(--bar) 14%,transparent)}
.grid{stroke:var(--line);stroke-width:1;stroke-dasharray:2 3}.axis{stroke:var(--line);stroke-width:1}
.xl,.yl{fill:var(--mute);font:11px system-ui,sans-serif}.xl{text-anchor:middle}.yl{text-anchor:end}
table.data{width:100%;border-collapse:collapse;margin:10px 0 18px;font-size:13.5px;background:var(--panel);border:1px solid var(--line);border-radius:10px;overflow:hidden}
table.data th,table.data td{padding:7px 10px;border-bottom:1px solid var(--line);text-align:left;vertical-align:baseline}
table.data thead th{font-size:12px;color:var(--mute);font-weight:600}
table.data tbody th small{display:block;color:var(--mute);font-weight:400;font-size:11.5px}
td.num{font-variant-numeric:tabular-nums;white-space:nowrap}
.up{color:var(--red);font-size:11.5px}.down{color:var(--green);font-size:11.5px}
.sharecell{min-width:140px;position:relative}.share{display:inline-block;height:8px;border-radius:0 4px 4px 0;background:var(--bar);vertical-align:middle}
.sharepct{font-size:12px;color:var(--mute);margin-left:6px;font-variant-numeric:tabular-nums}
.hint{font-size:12.5px;color:var(--mute);margin:-8px 0 10px}
#tip{position:fixed;pointer-events:none;background:var(--panel);color:var(--ink);border:1px solid var(--line);border-radius:8px;padding:6px 9px;font-size:12.5px;box-shadow:0 6px 18px rgba(0,0,0,.15);z-index:9;display:none}
@media(max-width:640px){table.data{display:block;overflow-x:auto}}
"""

SCRIPT = """<div id=tip role=tooltip></div><script>
(function(){var tip=document.getElementById('tip');
document.addEventListener('mousemove',function(e){var t=e.target.closest&&e.target.closest('[data-tip]');
  if(!t||!t.closest('svg')){tip.style.display='none';return}
  tip.textContent=t.dataset.tip;tip.style.display='block';
  var x=Math.min(e.clientX+12,innerWidth-tip.offsetWidth-8),y=e.clientY-tip.offsetHeight-12;tip.style.left=x+'px';tip.style.top=(y<8?e.clientY+16:y)+'px'});
})();</script>"""
