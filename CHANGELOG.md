# Changelog

To update: `~/.hearthwork-venv/bin/pip install --upgrade git+https://github.com/alexandr352/hearthwork`,
then `operator upgrade`, then restart `operator ui`. Versions marked **upgrade** change the doctrine
the operator or the spirit reads, so `operator upgrade` matters for them.

## 0.6.0 (upgrade)
- **VISUAL**, an eighth kind of work: a ticket you released from the inspector is worked one chain per
  released test file, tested before every other kind. **look** (an investigation: it pictures the page as
  the checkout stands, reads the frames the inspector cited, and answers SIGHTING: still drawn, gone or
  cannot show, with CANDIDATES) -> **fix** (product code only) -> **guard** (the test gains an assertion
  that sees the defect, the page is pictured again, `operator lab ab` proves the test, the commit).
- The program reads the SIGHTING line of every investigation while the chain is open and accepts a fix
  only on "still drawn" at high confidence; "gone" voids the chain. A released ticket's plan input names
  each released file with the frames its findings cite, copied into the scratch folder for the executor.
  The inspector closes it: its next look at the newer commit says fixed or still seen.
- One SIGHTING line per released finding: a fix may follow when any finding is still drawn at high
  confidence, and answers those. The words name the state of the DEFECT ("still drawn" = the user still
  meets it, even when what is missing is a ring), and the look's prompt must define them so.
- `operator lab frames <test file>`: one UI test file run as the checkout stands (uncommitted work
  included), on the inspector's port, printing the frames a user sees after each step and the settled end
  screenshot, saved in the scratch folder. No judge, nothing spent; the executor may run it.

## 0.5.0 (upgrade)
- **The inspector**: `operator inspect` runs your Playwright UI tests in a git worktree of its own, on a
  port of its own, cuts the frames a user would see after each step from the trace (each with its timing;
  a frame too soon after its step never proves an absence), and has one judge call per test file read
  them against your rubric. The judge holds Read on those frames and nothing else; its answer is checked,
  and a broken one goes back to the same session, three times at most. See docs/inspector.md.
- **The rubric** is the project's `inspect/rubric.md`, written on first use: WCAG 2.2, levels A and AA.
  A `fails` or `measure` finding must cite one of its listed criteria; anything else is `other`.
- **The box**: one report per test file, replaced by each new look. One control's defect seen in several
  files counts once. `operator box` shows what waits; `operator release <N | file> --ticket <ID>` writes
  the chosen findings into a new ticket; the next look at a newer commit says fixed or still seen.
- The work log page shows the box, with the frame each finding was seen in (served by `operator ui` too).
- `operator inspect config` sets it up (`tests`, `port_env`, `port`; optional `command`, `cwd`, `config`,
  `up`, `build`, `relook_hours`); `[models] inspector` picks the judge's model (default opus).
- The spirit knows the inspector's commands, and that releasing is the person's decision.

## 0.4.0 (upgrade)
- **FAMILY**, a seventh kind of work: a fix for a defect has already shipped, and more places carry the same
  defect. Tested before STABILIZATION (a family site is a defect too, and STABILIZATION would always win).
  One chain, one commit: **census** (the shipped fix read from its commit; every further site measured and
  grouped by what it is built from) -> one **site-fix** per group (the fix applied as it shipped; no test,
  no commit) -> **guard** (one test over every site, proven by `operator lab ab`).
- The program checks the shape: a FAMILY opens on `pattern_commit`, a commit it finds in the repository;
  it counts the census's SITES rows and groups itself, tells the judge, and lets the chain grow once, to one
  site-fix per group plus two. A site-fix names its `site_group`, carries the census's blocks and reports
  every site that does not fit; that site leaves the family as its own STABILIZATION chain. The fence
  refuses a test in a site-fix, as in a fix.
- A judge can void a chain whose premise turned out false (`"chain_void": true`): the defect does not
  reproduce, no further site carries it. The program closes the chain only when the unit made no commit and
  left the tree clean.
- The census skill gained the site census: PATTERN, SITES and BLOCKED blocks, every site measured.

## 0.3.7
- The browser tab says hearthwork in lower case too: "hearthwork log", "stats · hearthwork", "archive · hearthwork".

## 0.3.6
- The page's title reads hearth**work**, as on the social card: lower case, "work" in the accent colour.

## 0.3.5
- Docs: the lab's server (only the start command is needed), the lab in MCP mode, a development section,
  a new example atlas with its "The lab" section, a current screenshot.

## 0.3.4 (upgrade)
- `operator lab up` finds the server's address itself: from what it prints as it starts
  (`Local: http://localhost:5173/`, `listening on port 3355`), else from the TCP port it opens. It is up only
  when that address answers, and the address is saved as `health`. A server-backed project needs one thing
  from you: the command that starts it.

## 0.3.3 (upgrade)
- `operator lab status` asks the health URL itself and prints what came back (`HTTP 200`, `no answer`), and
  names a missing health URL when the lab has a server.
- The spirit knows its shell cannot reach the network or localhost (its fence, not the machine) and asks
  `operator lab status` instead of guessing.

## 0.3.2
- `operator lab config --from-atlas` works with an atlas drafted before 0.3.0: with no lab section, the
  test command comes from its "Run one test file" line, the example path replaced by `{files}`. It says so;
  check it with `operator lab gate <a test file>`.

## 0.3.1
- Updating is a plain `pip install --upgrade`: every release has a new version number.

## 0.3.0 (upgrade)
- **The lab**: `operator lab`, one instrument for a project's tests and, if they need one, its
  server: `gate` runs named test files once, `ab` runs them on the uncommitted work and on HEAD
  and says whether the test GUARDS the change. Kill-safe; a died A/B is finished by the next
  lab command (`operator lab restore`). Set it up from the atlas: `operator lab config --from-atlas`.
  The page shows `lab: …` beside "updated", live.
- **Shapes**: each kind of work has its steps (STABILIZATION: reproduce → fix → guard), and a
  STABILIZATION commit must prove its guard with the A/B. The judge reads the lab's verdicts from
  the program's own records.
- **Sub-agents and skills** on every executor call: a reader, a prober and a reviewer (Sonnet by
  default, `reader` in config.toml), and the probe, census and self-review skills. Nothing is
  written into your repository. The unit card shows which ran.
- **The fence by step**: investigations write only probes in the git-excluded scratch folder; a
  fix writes no test; `git stash`, `git restore` and `git checkout -- <file>` are refused in favour
  of the A/B; the executor runs no `operator` command but `operator lab`.
- The atlas drafts a "The lab" section; `operator next` and the spirit walk through setting it up.

## 0.2.6
- A **repository** panel on the page: per project, override the repository's own Claude Code
  settings and rely on the fence. It names the hooks it finds and writes `project.toml`.

## 0.2.5
- `repo_settings = false` in `project.toml` runs the executor without the repository's own Claude
  Code settings and hooks; its CLAUDE.md still loads. `project add` and `doctor` name such hooks.

## 0.2.4 (upgrade)
- `operator ticket rename <OLD> <NEW>`: the ticket's records, state, cost records, the id in its own
  files, its knowledge tags and its unpushed branches follow. `operator ticket title`.

## 0.2.3
- The chat input grows to five lines, then scrolls.

## 0.2.2
- The chat input no longer clips its placeholder.

## 0.2.1
- `operator statusline [--install]`: Claude Code's status line shows your limits and the work, and
  feeds hearthwork the documented `rate_limits`.

## 0.2.0
- Your 5-hour session and week, with their resets, on the page and in `operator usage`, read from
  the rate-limit event every call already carries. Every call now uses `stream-json` output.

## 0.1.9
- While a unit runs, the banner reads NOW and offers to ask the spirit about it.

## 0.1.8
- A command block in the chat is one box.

## 0.1.7
- A unit whose run died (a closed terminal, a restart) is surveyed and judged on the next run,
  instead of being skipped. Every unit records the repository's state before it starts.

## 0.1.6
- A held run lock counts as running, so a unit started by an older version still shows.

## 0.1.5
- A running unit shows as it runs: its ticket at once, with a live card (phase, title, minutes).
  The chat survives a page reload. Code blocks render in the chat.

## 0.1.4 (upgrade)
- `operator next`: the one next step, the same for the command line, the page's banner and the
  spirit. `operator repos`. The spirit starts from the next step and shows every command it runs.
  `operator atlas --detach`.

## 0.1.3 (upgrade)
- The spirit runs units in the background (`operator run --detach`) and creates a ticket from text
  you paste, unchanged.

## 0.1.2
- The page refreshes when an atlas answer is recorded and after every spirit reply.

## 0.1.1 (upgrade)
- The atlas in the spirit, the status and the page: `operator atlas questions` and
  `operator atlas answer`. `operator upgrade` also refreshes the spirit's doctrine.

## 0.1.0
- The loop (plan, execute, judge), contracts checked in code, recovery, the fence, the work log with
  the spirit's chat (`operator ui`), MCP mode, the atlas, token economy, the archive and stats pages,
  the sleep guard.
