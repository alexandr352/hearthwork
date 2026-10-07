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


MODES = {
    "STABILIZATION": "fixing something broken: reproduce it, fix it the smallest safe way, guard it with a test",
    "FEATURE": "adding behaviour the product does not have: find where it goes, build it, cover it with tests",
    "REFACTOR": "changing structure while behaviour stays exactly the same",
    "CONFIGURATION": "changing configuration only, no code",
    "MIGRATION": "moving from one state to another in safe, reversible steps",
    "AUDIT": "answering a question: reading only, nothing is changed",
}
KIND_WORD = {"investigation": "reads only", "execution": "changes code", "commit": "makes the commit",
             "question": "asked you a question"}


def unit_plan(p, rec):
    try:
        return json.loads((Ticket(p, rec["ticket"]).unit_dir(rec.get("unit")) / "plan.json").read_text())
    except (OSError, ValueError, TypeError):
        return {}


def step_kind(plan):
    if plan.get("commit_expected"):
        return "commit"
    return plan.get("kind") or "investigation"


def anchor(p, tid, n):
    return f"u-{esc(p.name)}-{esc(tid)}-{n}"


def ticket_mode(p, trs):
    """The kind of work, from the newest unit that names it."""
    for r in reversed(trs):
        m = unit_plan(p, r).get("mode")
        if m:
            return m
    return None


def story(p, tid, trs, open_chain, active):
    """The ticket as a person reads it: the kind of work, then each chain's named steps,
    which read and which change code, and where the work stands."""
    plans = {r.get("unit"): unit_plan(p, r) for r in trs}
    blocks, chains = [], {}
    for r in trs:
        pl = plans[r.get("unit")]
        name = pl.get("chain")
        if name:
            c = chains.get(name)
            if c is None:
                c = chains[name] = {"name": name, "total": pl.get("chain_total") or 1, "steps": None, "at": {}}
                blocks.append(("chain", c))
            c["total"] = pl.get("chain_total") or c["total"]
            if pl.get("chain_steps"):
                c["steps"] = pl["chain_steps"]
            c["at"].setdefault(pl.get("chain_phase") or 1, []).append((r, pl))
        else:
            blocks.append(("unit", (r, pl)))
    out = []
    singles = []

    def flush():
        if singles:
            word = "unit" if len(singles) == 1 else "units"
            out.append(f'<div class=steps><span class=chainname>{word} on their own</span>' + "".join(singles) + "</div>")
            singles.clear()

    for kind, b in blocks:
        if kind == "unit":
            r, pl = b
            singles.append(pill(p, tid, r, pl, None))
            continue
        flush()
        pills, current_set = [], False
        for i in range(1, b["total"] + 1):
            runs = b["at"].get(i, [])
            label = (b["steps"][i - 1] if b["steps"] and i - 1 < len(b["steps"]) else
                     (runs[-1][1].get("role") if runs else None))
            if runs:
                r, pl = runs[-1]
                pills.append(pill(p, tid, r, pl, label, retries=len(runs) - 1))
            else:
                state = "pending"
                if not current_set and active and b["name"] == open_chain:
                    state, current_set = "current", True
                k = "commit" if i == b["total"] else "planned"
                pills.append(f'<span class="step {state} {k}" title="{esc(KIND_WORD.get(k, "planned"))}">'
                             f'<i>{i}</i> {esc(label or ("commit" if k == "commit" else f"step {i}"))}'
                             f'{" <em>commit</em>" if k == "commit" and label else ""}</span>')
        out.append(f'<div class=steps><span class=chainname>chain {esc(b["name"])}</span>'
                   + '<span class=arrow>→</span>'.join(pills) + "</div>")
    flush()
    return "".join(out)


def pill(p, tid, r, pl, label, retries=0):
    v = r.get("verdict") or {}
    k = step_kind(pl) if pl else (r.get("kind") or "investigation")
    if r.get("outcome") in ("halted", "failed") or v.get("action") == "halt":
        state = "failed"
    elif v.get("unit_done"):
        state = "done"
    else:
        state = "retry"
    if pl.get("action") == "halt":
        state, k, label = "failed", "question", "asked you"
    label = label or pl.get("role") or {"investigation": "look", "execution": "change"}.get(r.get("kind"), "unit")
    phase = pl.get("chain_phase")
    num = phase if phase else r.get("unit")
    extra = f' <small>×{retries + 1}</small>' if retries else ""
    tip = f"unit {r.get('unit')}: {r.get('title') or ''} ({KIND_WORD.get(k, k)})"
    return (f'<a class="step {state} {k}" href="#{anchor(p, tid, r.get("unit"))}" title="{esc(tip)}">'
            f'<i>{num}</i> {esc(label)}{" <em>commit</em>" if k == "commit" else ""}{extra}</a>')


FILES = (("prompt.md", "Prompt the operator wrote"), ("report.md", "Executor report"),
         ("survey.md", "Survey of the tree"), ("facts.md", "Repository facts (from git)"))
FILE_NAMES = {f for f, _ in FILES}
LAYOUT = 3  # bump when archive pages should be written again


def usage_tiles():
    """The account's 5-hour session and week, from the newest Claude call's rate-limit event."""
    from .claude import read_usage
    u = read_usage()
    if not u:
        return ('<div><span>–</span>session and week: shown after the next Claude call</div>')
    seen = time.strftime("%H:%M", time.localtime(u.get("seen") or time.time()))

    def when(epoch, week=False):
        if not epoch:
            return "reset time unknown"
        t = time.localtime(epoch)
        return "resets " + time.strftime("%a %-d %b %H:%M" if week else "%H:%M", t)

    out = []
    for key, label, week in (("five_hour", "5-hour session", False), ("seven_day", "week", True)):
        w = u.get(key)
        if not w:
            continue
        pct = w["used"] * 100
        warn = " class=warnpct" if pct >= 80 else ""
        out.append(f'<div><span{warn}>{pct:.0f}%</span>{label} · {when(w.get("resets_at"), week)}'
                   f'<small class=seen>as of {seen}</small></div>')
    return "".join(out)


def ts(r):
    try:
        return datetime.strptime(r["ts"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()
    except (KeyError, ValueError, TypeError):
        return 0


def record_path(p, tid, n, name):
    return f"projects/{p.name}/tickets/{tid}/units/{n:02d}/{name}"


def unit_card(p, rec, ui=False, files="embed", base=""):
    """files: embed (the text inside the page), lazy (fetched when opened, `operator ui`),
    or link (a link to the record on disk, the archive pages)."""
    t = Ticket(p, rec["ticket"])
    n = rec.get("unit")
    d = t.unit_dir(n) if n else None
    v = rec.get("verdict") or {}
    state = unit_state(rec)
    parts = []
    for name, label in FILES:
        f = d / name if d else None
        if not f or not f.exists():
            continue
        rel = record_path(p, rec["ticket"], n, name)
        if files == "lazy":
            parts.append(f'<details class=file data-src="{esc(rel)}"><summary>{label}</summary><pre>loading…</pre></details>')
        elif files == "link":
            parts.append(f'<a class=filelink href="{esc(base + rel)}">{label}</a>')
        else:
            parts.append(f"<details class=file><summary>{label}</summary><pre>{esc(read_text(f))}</pre></details>")
    when = esc((rec.get("ts") or "").replace("T", " ").replace("Z", " UTC"))
    git = rec.get("git") or {}
    gitline = (f"{git.get('commits', 0)} commit(s), {git.get('files', 0)} file(s), tree "
               f"{'clean' if git.get('clean') else 'dirty'}") if git else ""
    pl = unit_plan(p, rec)
    role = rec.get("role") or pl.get("role")
    k = step_kind(pl) if pl else (rec.get("kind") or "investigation")
    did = v.get("summary") or v.get("reason") or ""
    title = rec.get("title") or rec.get("outcome") or ""
    if pl.get("action") == "halt":
        title, did, role = "stopped to ask you", pl.get("reason") or did, "question"
    return f"""
<details class="unit {state}" id="u-{esc(p.name)}-{esc(rec['ticket'])}-{n}">
  <summary><span class=dot></span><b>unit {n}</b>
    {f'<span class=chip>{esc(role)}</span>' if role else ''}<span class="chip {k}">{esc(KIND_WORD.get(k, k))}</span>
    <span class=title>{esc(title)}</span>
    <span class=cost>{money(rec.get('cost_usd') or 0)}</span>
    {f'<span class=did>{esc(did)}</span>' if did else ''}</summary>
  <div class=body>
    <div class=meta>{when} · {rec.get('seconds', 0) / 60:.1f} min · {esc(gitline)}{' · recovered: ' + esc(rec['recovered']) if rec.get('recovered') else ''}</div>
    <div class=verdict><b>{esc(v.get('action') or rec.get('outcome') or '')}</b> — {esc(v.get('reason') or '')}</div>
    {f'<div class=next>next: {esc(v.get("next"))}</div>' if v.get('next') else ''}
    <div class=phases>{phase_line(rec)}</div>
    {f'<button class=ask data-ask="{esc(p.name)}|{esc(rec["ticket"])}|{n}">ask the spirit about this unit</button>' if ui else ''}
    <div class=files>{''.join(parts)}</div>
  </div>
</details>"""


def ticket_status(st, tid):
    return ("ready" if tid in (st.get("ready") or []) else
            "halted" if (st.get("halted") or {}).get("ticket") == tid else
            "active" if st.get("active_ticket") == tid else "idle")


def by_ticket(rows):
    out = {}
    for r in rows:
        out.setdefault(r.get("ticket"), []).append(r)
    for tid in out:
        out[tid].sort(key=lambda r: (r.get("unit") or 0, ts(r)))
    return out


def window(p, trs, limit):
    """The last `limit` units, reaching back to the start of the chain the first of them
    belongs to, so a chain is never shown cut in half."""
    if not limit or len(trs) <= limit:
        return trs
    i = len(trs) - limit
    chain = unit_plan(p, trs[i]).get("chain")
    while chain and i > 0 and unit_plan(p, trs[i - 1]).get("chain") == chain:
        i -= 1
    return trs[i:]


def mode_html(mode):
    if not mode:
        return ""
    return (f' <span class=mode tabindex=0 aria-label="{esc(mode)}: {esc(MODES.get(mode, ""))}" '
            f'data-tip="{esc(MODES.get(mode, ""))}">{esc(mode)}</span>')


PHASE_WORD = {"working": "a unit is in progress", "planning": "the operator is planning it", "executing": "the executor is working",
              "judging": "the operator is judging the report", "surveying": "reading the tree after a failed run"}


def running_card(p, run):
    started = run.get("started") or time.time()
    label = f"unit {esc(run.get('unit'))}" if run.get("unit") not in (None, "?") else "a unit"
    return (f'<div class=runcard data-started="{started:.0f}"><span class=spin></span><b>{label}</b> '
            f'<span class=chip>{esc(run.get("phase"))}</span> <span class=title>{esc(run.get("title") or "")}</span>'
            f'<span class=did>{esc(PHASE_WORD.get(run.get("phase"), ""))} · '
            f'<span class=elapsed>{(time.time() - started) / 60:.0f} min</span></span></div>')


def ticket_section(p, tid, trs, st, ui=False, files="embed", base="", limit=None, archive_href=None, run=None):
    t = Ticket(p, tid)
    meta = t.read("meta.json") or {}
    last_v = next((r.get("verdict") for r in reversed(trs) if r.get("verdict")), None) or {}
    done, planned = last_v.get("units_done"), last_v.get("units_planned")
    status = ticket_status(st, tid)
    shown = window(p, trs, limit)
    hidden = len(trs) - len(shown)
    chain_open = (t.read("chain.json") or {}).get("chain")
    strip = story(p, tid, shown, chain_open, status in ("active", "halted"))
    progress = f"{done} of {planned} units done" if planned else ""
    nums = " · ".join(x for x in (progress, f"{len(trs)} run{'s' if len(trs) != 1 else ''}" if trs else "no units yet",
                                 money(sum(r.get('cost_usd') or 0 for r in trs)) if trs else "") if x)
    if run and run.get("ticket") == tid:
        status = "running"
    more = (f'<a class=more href="{esc(archive_href)}">{hidden} earlier unit{"s" if hidden != 1 else ""} '
            f'of this ticket are in its archive page →</a>') if hidden and archive_href else ""
    return f"""
<section class=ticket id="t-{esc(p.name)}-{esc(tid)}">
  <header><h3>{esc(tid)}{mode_html(ticket_mode(p, trs))} <span class="badge {status}">{status}</span></h3>
    <div class=sub>{esc(meta.get('title') or '')}</div>
    <div class=nums>{nums}</div>
    <div class=strip>{strip}</div>
    {f'<div class=next>next: {esc(last_v.get("next"))}</div>' if last_v.get('next') and status != 'ready' else ''}
  </header>
  {running_card(p, run) if run and run.get("ticket") == tid else ""}
  {''.join(unit_card(p, r, ui, files, base) for r in reversed(shown))}
  {more}
</section>"""


def compact_row(p, tid, trs, st, href):
    meta = Ticket(p, tid).read("meta.json") or {}
    status = ticket_status(st, tid)
    last = max((ts(r) for r in trs), default=0)
    when = time.strftime("%Y-%m-%d", time.localtime(last)) if last else ""
    return (f'<a class=row href="{esc(href)}"><b>{esc(tid)}</b>{mode_html(ticket_mode(p, trs))}'
            f'<span class="badge {status}">{status}</span><span class=rtitle>{esc(meta.get("title") or "")}</span>'
            f'<span class=rnums>{len(trs)} units · {money(sum(r.get("cost_usd") or 0 for r in trs))} · {when}</span></a>')


def recent_units(h):
    try:
        return max(1, int((home.load_config(h).get("log") or {}).get("recent_units", 20)))
    except (TypeError, ValueError):
        return 20


def render(home_path=None, ui=False):
    h = home_path or home.home_dir()
    projects = home.projects(h)
    recent = recent_units(h)
    now = time.time()
    day_ago, week_ago = now - 86400, now - 7 * 86400
    per_project = [(p, p.read_state(), read_meter(p)) for p in projects]
    all_rows = [r for _, _, rows in per_project for r in rows]
    newest = sorted(((ts(r), p.name, r.get("ticket")) for p, _, rows in per_project for r in rows), reverse=True)
    in_window = {(name, tid) for _, name, tid in newest[:recent]}
    sections, banners = [], []
    for p, st, rows in per_project:
        if st.get("halted"):
            hl = st["halted"]
            banners.append(f"""<div class=halt><b>{esc(p.name)} is halted</b> on {esc(hl.get('ticket'))}
              {('unit ' + esc(hl.get('unit'))) if hl.get('unit') else ''}: {esc(hl.get('reason'))}
              <div class=hint>answer with <code>operator rule "…"</code>, or talk it through with the spirit
              (<code>operator chat</code>)</div>
              {f'<button class=ask data-ask="{esc(p.name)}|{esc(hl.get("ticket"))}|{esc(hl.get("unit") or "")}">talk it through here</button>' if ui else ''}</div>""")
        groups = by_ticket(rows)
        from .records import running as _running
        run = _running(p)
        for tid in {st.get("active_ticket"), (run or {}).get("ticket")}:
            if tid and tid not in groups and Ticket(p, tid).exists():
                groups[tid] = []
        order = sorted(groups, key=lambda k: max((ts(r) for r in groups[k]), default=time.time()), reverse=True)
        full, older = [], []
        for tid in order:
            href = f"archive/{p.name}/{tid}.html"
            if ticket_status(st, tid) in ("active", "halted") or (p.name, tid) in in_window or (run or {}).get("ticket") == tid:
                full.append(ticket_section(p, tid, groups[tid], st, ui, "lazy" if ui else "embed",
                                           limit=recent, archive_href=href, run=run))
            else:
                older.append(compact_row(p, tid, groups[tid], st, href))
        older_html = ""
        if older:
            head, tail = older[:20], older[20:]
            older_html = (f'<div class=older><h4>Earlier tickets</h4>{"".join(head)}'
                          + (f'<details><summary>{len(tail)} more</summary>{"".join(tail)}</details>' if tail else "")
                          + "</div>")
        link = ""
        sections.append(f"""<h2>{esc(p.name)} <span class=repo>{esc(p.repo)}</span>{link}</h2>
{''.join(full) or '<p class=empty>No units yet. <code>operator run</code> starts one.</p>'}{older_html}""")
    try:
        from . import guide
        nxt = guide.next_step(h=h)
    except Exception:
        nxt = None
    if nxt and nxt["key"] != "halt":
        btn = (f'<button class=ask data-ask="{esc(nxt["project"] or "")}|next|" data-text="{esc(nxt["ask"])}">'
               f'{esc(nxt.get("button") or "do it with the spirit")}</button>') if ui else ""
        label = "now" if nxt["key"] == "running" else "next"
        banners.insert(0, f"""<div class=nextstep><span class=nlabel>{label}</span> <b>{esc(nxt['title'])}</b>
          <div class=hint>{esc(nxt['why'])}</div>
          <div class=hint>{esc(nxt.get("yourself") or "or yourself")}: <code>{esc(nxt['command'])}</code></div>{btn}</div>""")
    day = [r for r in all_rows if ts(r) >= day_ago]
    week = [r for r in all_rows if ts(r) >= week_ago]
    rate = cache_rate(week)
    stats = f"""<div class=stats>
  <div><span>{money(sum(r.get('cost_usd') or 0 for r in day))}</span>today · {len(day)} units</div>
  <div><span>{money(sum(r.get('cost_usd') or 0 for r in week))}</span>7 days · {len(week)} units</div>
  <div><span>{f'{rate * 100:.0f}%' if rate is not None else '–'}</span>prompt cache hits, 7 days</div>
  <div><span>{money(sum(r.get('cost_usd') or 0 for r in all_rows))}</span>all time · {len(all_rows)} units</div>
  {usage_tiles()}
</div>"""
    return page(sections="".join(sections) or "<p class=empty>No projects yet.</p>", banners="".join(banners),
                stats=stats, ui=ui)


NAV = (("log", "Log", "worklog.html"), ("archive", "Archive", "archive/index.html"), ("stats", "Stats", "stats.html"))


def page(sections, banners="", stats="", ui=False, title="Hearthwork Log", note=None, root="", nav="log", crumb=""):
    tabs = "".join(f'<a href="{root}{href}"{" aria-current=page" if key == nav else ""}>{label}</a>'
                   for key, label, href in NAV) + (f'<span class=crumb>/ {crumb}</span>' if crumb else "")
    return TEMPLATE.replace("{{NAV}}", tabs).replace("{{BANNERS}}", banners).replace("{{STATS}}", stats) \
        .replace("{{SECTIONS}}", sections) \
        .replace("{{MODES}}", "".join(f"<dt>{esc(m)}</dt><dd>{esc(d)}</dd>" for m, d in MODES.items())) \
        .replace("{{UPDATED}}", time.strftime("%Y-%m-%d %H:%M", time.localtime())) \
        .replace("{{REFRESH}}", "" if ui or note else '<meta http-equiv=refresh content=60>') \
        .replace("{{NOTE}}", note or ("live" if ui else "refreshes every minute")) \
        .replace("{{TITLE}}", esc(title)).replace("{{ROOT}}", root) \
        .replace("{{TOPBTN}}", '<button id=repos-btn class=theme aria-haspopup=dialog title="the repositories\' own Claude Code settings">repository</button>'
                 '<button id=eco-btn class=theme aria-haspopup=dialog title="what Claude calls carry">economy</button>'
                 '<button id=wake class=theme title="keep this screen on while the page is in front" hidden>screen on</button>' if ui else "")


# --- the archive: one page per ticket, and an index ---------------------------------

def archive(h):
    """Write the archive pages of tickets that changed since they were last written, and
    the index. A ticket's page links to its records instead of embedding them."""
    root = h / "archive"
    stamps_path = root / ".stamps.json"
    try:
        stamps = json.loads(stamps_path.read_text())
    except (OSError, ValueError):
        stamps = {}
    index = []
    for p in home.projects(h):
        st = p.read_state()
        groups = by_ticket(read_meter(p))
        for tid, trs in groups.items():
            meta = Ticket(p, tid).read("meta.json") or {}
            status = ticket_status(st, tid)
            sig = json.dumps([LAYOUT, len(trs), trs[-1].get("ts"), status, meta.get("title"),
                              (trs[-1].get("verdict") or {}).get("action")])
            key = f"{p.name}/{tid}"
            target = root / p.name / f"{tid}.html"
            if stamps.get(key) != sig or not target.exists():
                body = ticket_section(p, tid, trs, st, files="link", base="../../")
                home.write_atomic(target, page(body, title=f"{tid} · Hearthwork", note=p.name, root="../../",
                                               nav="archive", crumb=esc(tid)))
                stamps[key] = sig
            first = min(ts(r) for r in trs)
            index.append((first, p, tid, trs, st, meta, status))
    index.sort(key=lambda x: x[0], reverse=True)
    rows, month = [], None
    for first, p, tid, trs, st, meta, status in index:
        m = time.strftime("%B %Y", time.localtime(first)) if first else "undated"
        if m != month:
            rows.append(f"<h4 class=month>{esc(m)}</h4>")
            month = m
        row = compact_row(p, tid, trs, st, f"{p.name}/{tid}.html")
        rows.append(row.replace('<a class=row ', f'<a class=row data-q="{esc((p.name + " " + tid + " " + (meta.get("title") or "")).lower())}" ', 1))
    body = ('<input id=filter class=filter placeholder="Find a ticket by id or title…" aria-label="find a ticket">'
            + "".join(rows) +
            "<script>var f=document.getElementById('filter');f.oninput=function(){var q=f.value.toLowerCase();"
            "document.querySelectorAll('a.row').forEach(function(a){a.hidden=q&&a.dataset.q.indexOf(q)<0})}</script>")
    home.write_atomic(root / "index.html", page(body, title="Archive · Hearthwork", note=f"{len(index)} tickets", root="../",
                                                nav="archive"))
    home.write_atomic(stamps_path, json.dumps(stamps))
    return root / "index.html"


def build(home_path=None):
    h = home_path or home.home_dir()
    path = h / "worklog.html"
    home.write_atomic(path, render(h))
    archive(h)
    from . import stats
    stats.build(h)
    return path


TEMPLATE = """<!doctype html>
<html lang=en><head><meta charset=utf-8>
<meta name=viewport content="width=device-width, initial-scale=1">
{{REFRESH}}
<title>{{TITLE}}</title>
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
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:10px;margin:18px 0}
.stats div{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:12px 14px;color:var(--mute);font-size:13px}
.stats span{display:block;color:var(--ink);font-size:22px;font-weight:600}
.stats span.warnpct{color:var(--red)}
.stats .seen{display:block;font-size:11px;color:var(--mute);margin-top:2px}
.halt{background:color-mix(in srgb,var(--red) 12%,var(--panel));border:1px solid var(--red);border-radius:10px;padding:12px 14px;margin:12px 0}
.halt .hint,.nextstep .hint{color:var(--mute);font-size:13px;margin-top:4px}
.nextstep{background:color-mix(in srgb,var(--accent) 9%,var(--panel));border:1px solid color-mix(in srgb,var(--accent) 45%,var(--line));border-radius:10px;padding:12px 14px;margin:12px 0}
.nlabel{font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.06em;color:var(--accent);margin-right:4px}
.ticket{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:14px;margin:12px 0}
.ticket .sub{color:var(--mute)}.nums{color:var(--mute);font-size:13px;margin-top:2px}
.badge{font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:.04em;padding:2px 7px;border-radius:99px;margin-left:6px;vertical-align:2px;border:1px solid var(--line);color:var(--mute)}
.badge.active,.badge.running{color:var(--accent);border-color:var(--accent)}
.runcard{display:flex;flex-wrap:wrap;align-items:center;gap:8px;padding:10px 12px;margin:8px 0;border:1px dashed var(--accent);border-radius:10px;background:color-mix(in srgb,var(--accent) 6%,var(--panel))}
.runcard .did{flex-basis:100%;font-size:13px;color:var(--mute);padding-left:22px}
.spin{width:12px;height:12px;border-radius:50%;border:2px solid var(--accent);border-right-color:transparent;animation:spin 1s linear infinite;flex:none}
@keyframes spin{to{transform:rotate(360deg)}}
@media (prefers-reduced-motion:reduce){.spin{animation:none;border-right-color:var(--accent)}}.badge.ready{color:var(--green);border-color:var(--green)}.badge.halted{color:var(--red);border-color:var(--red)}
.strip{margin:6px 0 4px}
.cell{width:18px;height:18px;border-radius:4px;display:block}
.cell.green,.unit.green .dot{background:var(--green)}.cell.amber,.unit.amber .dot{background:var(--amber)}.cell.red,.unit.red .dot{background:var(--red)}
.next{font-size:13px;color:var(--mute);margin-top:4px}
.files{display:flex;flex-direction:column;gap:2px}.filelink{font-size:13px;color:var(--accent);margin-right:12px}
.more{display:inline-block;margin-top:10px;font-size:13px;color:var(--accent)}
.tabs{display:flex;align-items:baseline;gap:4px;margin:14px 0 4px;border-bottom:1px solid var(--line)}
.tabs a{padding:6px 12px 8px;color:var(--mute);text-decoration:none;font-size:14px;border-bottom:2px solid transparent;margin-bottom:-1px}
.tabs a:hover{color:var(--ink)}
.tabs a[aria-current=page]{color:var(--ink);font-weight:600;border-bottom-color:var(--accent)}
.tabs .crumb{color:var(--mute);font-size:14px;padding:6px 4px 8px}
.older{margin:18px 0}.older h4{font-size:13px;color:var(--mute);margin:0 0 6px;font-weight:600}
a.row{display:flex;flex-wrap:wrap;align-items:baseline;gap:8px;padding:8px 12px;border:1px solid var(--line);border-radius:10px;background:var(--panel);color:var(--ink);text-decoration:none;margin:6px 0}
a.row:hover{border-color:var(--accent)}a.row[hidden]{display:none}
a.row .mode{color:var(--accent);font-size:12px;letter-spacing:.04em}
.rtitle{flex:1;min-width:160px;color:var(--mute)}.rnums{font-size:12px;color:var(--mute);font-variant-numeric:tabular-nums}
.older details summary{cursor:pointer;color:var(--accent);font-size:13px;margin:6px 0}
.month{font-size:13px;color:var(--mute);margin:20px 0 4px}
.back{font-size:13px}.back a{color:var(--accent)}
.filter{width:100%;padding:9px 14px;border:1px solid var(--line);border-radius:20px;background:var(--panel);color:var(--ink);font:14px system-ui,sans-serif;margin:6px 0 4px}
h3 .mode{color:var(--accent);letter-spacing:.04em;margin-left:6px;cursor:help;border-bottom:1px dotted currentColor;position:relative}
h3 .mode:hover::after,h3 .mode:focus::after{content:attr(data-tip);position:absolute;left:0;top:calc(100% + 6px);z-index:3;width:max-content;max-width:min(360px,80vw);white-space:normal;font:400 12.5px/1.45 system-ui,sans-serif;letter-spacing:0;color:var(--ink);background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:7px 10px;box-shadow:0 6px 18px rgba(0,0,0,.12)}
.steps{display:flex;flex-wrap:wrap;align-items:center;gap:6px;margin:10px 0 2px}
.chainname{font-size:12px;color:var(--mute);margin-right:4px}.arrow{color:var(--mute);font-size:12px}
.step{display:inline-flex;align-items:center;gap:6px;font-size:13px;padding:3px 10px 3px 4px;border-radius:99px;border:1.5px solid var(--line);color:var(--ink);text-decoration:none;white-space:nowrap}
.step i{font-style:normal;font-size:11px;font-weight:700;width:18px;height:18px;border-radius:50%;display:inline-flex;align-items:center;justify-content:center;border:1.5px solid currentColor}
.step em{font-style:normal;font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.05em;padding:1px 5px;border-radius:4px;background:var(--ink);color:var(--panel)}
.step small{color:var(--mute)}
.step.done{border-color:var(--green)}.step.done i{color:var(--green)}
.step.done.execution i,.step.done.commit i{background:var(--green);color:#fff;border-color:var(--green)}
.step.retry{border-color:var(--amber)}.step.retry i{color:var(--amber)}
.step.failed{border-color:var(--red)}.step.failed i{color:var(--red)}
.step.current{border-color:var(--accent);box-shadow:0 0 0 3px color-mix(in srgb,var(--accent) 22%,transparent)}.step.current i{color:var(--accent)}
.step.pending{border-style:dashed;color:var(--mute)}
dialog#help{max-width:min(620px,calc(100vw - 32px));max-height:calc(100vh - 48px);overflow:auto;background:var(--panel);color:var(--ink);border:1px solid var(--line);border-radius:14px;padding:20px 22px;box-shadow:0 20px 50px rgba(0,0,0,.25)}
dialog#help::backdrop{background:rgba(20,16,12,.45)}
dialog#help header{display:flex;justify-content:space-between;align-items:center;gap:12px}
dialog#help h2{margin:0;font-size:18px}dialog#help h3{font-size:14px;margin:18px 0 6px}
dialog#help p{margin:8px 0;font-size:14px}
.legendrow{display:flex;flex-wrap:wrap;gap:8px;margin:12px 0}
dialog#help dl{display:grid;grid-template-columns:max-content 1fr;gap:6px 14px;font-size:13.5px;margin:6px 0}
dialog#help dt{font-weight:700;color:var(--accent);letter-spacing:.03em}dialog#help dd{margin:0}
.chip{font-size:11px;padding:1px 7px;border-radius:99px;border:1px solid var(--line);color:var(--mute)}
.chip.execution,.chip.commit{border-color:var(--ink);color:var(--ink)}
.did{flex-basis:100%;font-size:13px;color:var(--mute);padding-left:18px}
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
button.theme,a.theme{background:none;border:1px solid var(--line);color:var(--mute);border-radius:8px;padding:4px 10px;cursor:pointer;font:13px system-ui,sans-serif;text-decoration:none;line-height:normal}
</style></head>
<body><main id=log>
<div class=top><h1>Hearthwork <small>updated {{UPDATED}} · {{NOTE}}</small></h1>
<span class=tools>{{TOPBTN}}<button class=theme onclick="var r=document.documentElement,d=r.dataset.theme==='dark'||(!r.dataset.theme&&matchMedia('(prefers-color-scheme: dark)').matches);r.dataset.theme=d?'light':'dark';try{localStorage.setItem('hw-theme',r.dataset.theme)}catch(e){}">theme</button><button class=theme onclick="document.getElementById('help').showModal()" aria-label="how to read this page" title="how to read this page">?</button></span></div>
<nav class=tabs aria-label="pages">{{NAV}}</nav>
{{BANNERS}}
{{STATS}}
<dialog id=help aria-labelledby=help-title>
  <header><h2 id=help-title>How to read this page</h2><button class=theme onclick="this.closest('dialog').close()" aria-label="close">close</button></header>
  <p>A <b>ticket</b> is worked in <b>units</b>. In each unit the <b>operator</b> plans one bounded step, the
  <b>executor</b> does it in your checkout, and the operator judges the report against what git shows.
  The operator never reads your code itself; it works from reports and git, so the judge stays
  independent of whoever did the work.</p>
  <p>Work that ends in one commit is a <b>chain</b> of units: the investigations it needs, the changes,
  and a last step that runs the tests and makes the one commit.</p>
  <div class=legendrow>
    <span class="step done investigation"><i>1</i> reads only</span>
    <span class="step done execution"><i>2</i> changes code</span>
    <span class="step done commit"><i>3</i> makes the commit <em>commit</em></span>
    <span class="step current planned"><i>·</i> next</span>
    <span class="step pending planned"><i>·</i> planned</span>
    <span class="step retry execution"><i>·</i> retried</span>
    <span class="step failed execution"><i>·</i> stopped</span>
  </div>
  <h3>The kind of work, named after each ticket</h3>
  <dl>{{MODES}}</dl>
  <h3>When it stops</h3>
  <p>When the operator needs a decision only you can make, the ticket <b>halts</b> with its question.
  Answer with <code>operator rule "…"</code>, or talk it through with the spirit. Your answer binds every
  later unit.</p>
  <h3>Costs</h3>
  <p>Every Claude call is metered per phase (plan, execute, judge) at the CLI's own figures. A unit done
  by your own Claude Code session (MCP mode) shows as not metered: hearthwork cannot see what your
  session costs.</p>
</dialog>

{{SECTIONS}}
</main>
<script>
try{var t=localStorage.getItem('hw-theme');if(t)document.documentElement.dataset.theme=t}catch(e){}
if(location.hash){var el=document.querySelector(location.hash);if(el&&el.tagName==='DETAILS')el.open=true}
var hd=document.getElementById('help');if(hd)hd.addEventListener('click',function(e){if(e.target===hd)hd.close()});
addEventListener('hashchange',function(){var el=document.querySelector(location.hash);if(el&&el.tagName==='DETAILS'){el.open=true}});
</script>
</body></html>
"""
