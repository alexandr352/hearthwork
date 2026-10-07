# Commands

Everything hearthwork does is an `operator` command; the spirit runs the same commands for
you and shows each one. Most commands take `-p <project>`; without it, the project is the one
whose repository holds your current folder, or the only one there is.

Not sure what to do? `operator next` names the one next step and its command.

## Setting up

| Command | What it does |
|---|---|
| `operator init` | Create the home (`~/.hearthwork`, or `$HEARTHWORK_HOME`). |
| `operator doctor` | Check the Claude CLI, git, the home, the sleep guard, and each project's repository and its own Claude Code hooks. |
| `operator repos` | List the git repositories found in the usual folders of your home. |
| `operator project add <name> --repo <path> [--trunk <branch>]` | Register a repository. Names any Claude Code hooks it has of its own. |
| `operator project list` | The projects, their active ticket, and any halt. |
| `operator upgrade` | After updating hearthwork: refresh the doctrine your projects and the spirit hold. Your persona, memory and records are untouched. |

## The atlas

| Command | What it does |
|---|---|
| `operator atlas [--detach] [--force]` | Draft the project's map from the repository, in one read-only session. `--detach` drafts in the background; `--force` drafts again over an atlas you have edited (the old one is kept). |
| `operator atlas questions` | The questions the draft could not answer from the repository, and which are answered. |
| `operator atlas answer <n> "<answer>"` | Record your answer under question `n` (it replaces an earlier one). |

## The lab

The one instrument that runs the project's tests, and its server if the tests need one.
Units use it too; the fence holds them to it.

| Command | What it does |
|---|---|
| `operator lab status` | What the lab is doing: READY, UP, DOWN, GATE, A/B, or RESTORE HELD; the last gate and A/B. Changes nothing. |
| `operator lab config [--from-atlas \| <key> <value>]` | Show the `[lab]` keys, take the ones the atlas proposes, or set one (`test`, `lint`, `build`, `up`, `health`, `down`, `scratch`, `ab`). |
| `operator lab gate <file...>` | Run the named test files once, under the lab's clock. Never a whole suite. |
| `operator lab lint [file...]` | The lint command. |
| `operator lab ab <file...> [--dry-run]` | The carried A/B: the named tests on your uncommitted work and on HEAD (the named files kept), and the verdict: GUARDS, PASSES-WITHOUT-CHANGE, BROKEN-BY-CHANGE or RED-AT-BOTH. `--dry-run` says what it would compare. Runs detached: closing the terminal never strands your work. |
| `operator lab ab --last` | Follow the running (or last) A/B again. |
| `operator lab restore` | Put back the work an A/B that died left saved under a git ref, and prove it. Any acting lab verb does this first anyway. |
| `operator lab up \| down \| restart \| build [--force] \| logs [n]` | The server and the build, when the project has them. `up` needs only the start command: it finds the address from what the server prints or the port it opens, waits until it answers, and saves it as `health`. A unit that needs the server says so in its plan, and the loop raises it before the unit and takes it down after. |

## Tickets

| Command | What it does |
|---|---|
| `operator ticket new <ID> [--title "..."] (--file <path> \| --text "..." \| stdin) [--use]` | Add a ticket. The first one becomes active; `--use` makes a later one active. |
| `operator ticket list` | Tickets, how many units each has, which is active, which are ready. |
| `operator ticket use <ID>` | Make a ticket the active one. |
| `operator ticket title <ID> "<title>"` | Change a ticket's title. |
| `operator ticket rename <OLD> <NEW>` | Give a ticket another id. Its records, state, cost records, the id in its own files, its knowledge tags, and its unpushed branches follow; a pushed branch is left alone. Refused while a unit runs. |

## Running

| Command | What it does |
|---|---|
| `operator run [-n <units>] [--max-cost <$>] [--detach]` | Run units on the active ticket: one by default; `-n 0` until it is ready or needs you. `--max-cost` stops once that much is spent. `--detach` runs in the background and returns at once. |
| `operator status` | Where every ticket stands: the last verdict, progress, pending recovery, the atlas, cost. |
| `operator halt "<reason>"` | Stop the loop until `resume` or `rule`. |
| `operator rule "<decision>"` | Answer a halt in your words. The ruling is kept with the ticket and binds every later unit; the halt is lifted. |
| `operator resume` | Lift a halt without a ruling. |
| `operator abandon` | Drop a unit left open by your own Claude Code session (MCP mode). |

## Seeing it

| Command | What it does |
|---|---|
| `operator ui [--port <n>] [--no-browser]` | The work log, live, with the spirit's chat, on this machine only. Prints a link carrying a one-time key. |
| `operator log` | Rebuild the static work log and the archive and stats pages, and print the log's path. |
| `operator chat [--model <model>]` | Talk to the spirit in the terminal. |
| `operator usage` | Your 5-hour session and week, with their resets, from the newest Claude call. |
| `operator statusline [--install]` | Claude Code's status line: shows your limits and the work, and keeps the page's reading fresh. `--install` sets it up (backs up your settings, never replaces a status line you have). |

## Settings

| Command | What it does |
|---|---|
| `operator economy [--mcp on\|off] [--claude-md on\|off] [--cache policy\|auto] [--reset]` | What every Claude call carries. See [safety.md](safety.md#token-economy). |
| `operator mcp` | Serve hearthwork to your own Claude Code session. See [mcp.md](mcp.md). |

Two files hold the rest, and are yours to edit:

- `~/.hearthwork/config.toml`: models per role, timeouts, the sleep guard, the log's window.
- `~/.hearthwork/projects/<name>/project.toml`: the repository, trunk, protected branches,
  branch prefix, network commands the executor may use, `mcp_allow`, `co_author`,
  `repo_settings`, and the `[lab]` table.
