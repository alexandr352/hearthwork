# Changelog

To update: `~/.hearthwork-venv/bin/pip install --upgrade git+https://github.com/alexandr352/hearthwork`,
then `operator upgrade`, then restart `operator ui`. Versions marked **upgrade** change the doctrine
the operator or the spirit reads, so `operator upgrade` matters for them.

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
