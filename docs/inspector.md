# The inspector

Your UI tests pass on what they check: the page's structure, its computed styles. They do not
look at what they draw. A focus ring can be switched off, a placeholder can be nearly white on
white, a ring can be clipped by its container, and every test stays green. The inspector looks.

## One look

One inspector unit takes one test file and:

1. runs it under Playwright in a git worktree of its own (`inspect/work` in the project's
   folder, detached at the commit it looks at: your checkout's HEAD unless you say `--at`),
   with tracing on and a screenshot at the end of every test. It does this through an
   untracked config beside yours that imports yours and changes only that;
2. cuts from each test's trace the frames a user would see: the picture after every action
   and at every assertion, each with its timing. A frame taken too soon after its step, or a
   state that lasted too short to be painted, is flagged, and a flagged frame never proves
   that something is missing;
3. hands the frames and the test's source to ONE judge call (`inspector` in config.toml,
   Opus by default), fenced to read those frames and nothing else, which judges them against
   your rubric and answers in a checked JSON shape. A broken answer goes back to the same
   session with the deviation named, three times at most;
4. puts what it found in the box, replacing that file's previous report.

The judge never sees your repository, and it judges only what a picture shows. A claim no
picture can show (an accessible name, a role) is the passing test's, not the judge's.

## The rubric

`inspect/rubric.md` in the project's folder, written on first use: WCAG 2.2, levels A and AA,
the criteria a screenshot can test, with rulings on what passes. It is yours. A finding the
judge marks `fails` or `measure` must cite an id listed under its `## Criteria` heading;
everything else is `other`. Replace it with a rubric of your own (your brand, your layout
rules) in the same shape.

## The box

One report per test file: the findings of its latest look. A new look replaces it; findings
are never matched to an earlier look. The judge names each finding's element ("Checkout page ·
Pay button"), and a defect of one control seen in several files counts once, under the first
file, with the others listed as also seen there.

`operator box` shows what is waiting. `operator release 1 --ticket UI-1` (or `release pay
--ticket UI-1`) writes the chosen files' findings into a new ticket, ready for `operator run`.
The operator works a released ticket as VISUAL, one chain per file: a **look** (`operator lab
frames <file>` pictures the page as your checkout stands, beside the frames the inspector
cited, copied into the scratch folder), a **fix**, and a **guard** that makes the test assert
what the picture showed, so it catches the defect next time.
The next look at a newer commit decides: **fixed** when nothing to fix is left, **still seen**
when something is, and a still-seen file waits in the box again.

What is due a look, in order: a file never looked at; a released file at a newer commit; a
file whose copies of a control were counted under another file that has been looked at again;
a test file that changed; an old look (`relook_hours`, 24 by default) whose code has moved.

## Setup

    operator inspect config tests "e2e/**/*.spec.ts"   # which files to look at
    operator inspect config port_env PORT               # the variable your app reads its port from
    operator inspect config port 4180                   # the inspector's own port
    operator inspect --dry-run                          # what is due
    operator inspect -n 0 --max-cost 5                  # look until none is due, or $5

The inspector raises its own server, never yours: Playwright's `webServer` (if your config has
one) runs from the worktree with the port variable set, or `operator inspect config up
"<command>"` starts one through the lab's machinery. Your app and your Playwright config must
read the port from that variable; if they hardcode it, the inspector would meet your own
server, so it asks for the variable instead of guessing. Folders like `node_modules` are linked
from your checkout into the worktree (`share`).

Playwright only: the frames come from Playwright's trace.

## The records

Under the project's `inspect/` folder: `units.jsonl` (one line per unit: the file, the commit,
the verdict, every judge call's cost), `captures/<commit>/uNNNN/` (the frames, the manifest,
and `judge.md` with every prompt and answer), `roster.json` (what each file's latest look
said), `box.json`. Traces are deleted once the frames are cut; captures no finding cites are
deleted after 14 days. The work log page shows the box with the frame each finding was seen in.
