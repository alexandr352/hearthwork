# Safety, settings and what each session may do

## The fence

Every tool call of every session passes a PreToolUse hook (`fence.py`), default-deny:

| Session | May | May not |
|---|---|---|
| executor | edit inside the checkout and /tmp; a shell; git add, commit and branch on the ticket's branch; sub-agents in the foreground | push, fetch, reset, rebase, amend, skip hooks; touch protected branches; read or write elsewhere in your home; read secrets (`~/.ssh`, `~/.aws`, `.env`, ...); the network; sudo; background jobs; a Co-Authored-By trailer (unless `co_author = true`) |
| reading sessions (atlas, survey) | read and list | anything that changes the repository |
| operator | read and write its own directory | anything else, including your repository |
| spirit | read the home and the repositories; write its memory; `operator ...`; read-only git | everything else |

The unit's step narrows the executor further: an **investigation** writes only in the scratch
folder and never operates the lab's server; a **fix** writes no test outside the scratch folder
(the guard step writes the real one); and no step takes work out of the tree by hand
(`git stash`, `git restore`, `git checkout -- <file>`): the one road to a baseline is
`operator lab ab`, which saves the work first and proves the restore. The executor may run
`operator lab ...` and no other `operator` command.

A path is checked by its real location, so quotes, `$HOME`, `~` and symbolic links (macOS's
`/tmp`) do not hide it. Commands are judged by what actually runs: `timeout 60 git push` is a
push.

**It is a guard rail, not a sandbox.** It stops an honest session from wandering and the
common accidents; it reads tool calls, not what a program does once it runs. For unattended
runs, use a separate OS user that owns only the checkout. Reporting a way around it:
[SECURITY.md](../SECURITY.md).

## Your repository's own Claude Code settings

A repository's `.claude/settings.json`, with any hooks in it, applies to the executor too. A
hook written for people at the keyboard can refuse what an unattended unit needs, such as
deleting a file it just moved. `operator project add` and `operator doctor` name such hooks.
To run the executor under hearthwork's fence only, tick the project in the page's
**repository** panel, or set `repo_settings = false` in its `project.toml`. The repository's
CLAUDE.md is read either way.

## Commits

Commits carry the identity your git is configured with and nothing else: Claude Code's own
attribution is switched off for the executor, and the fence refuses a Co-Authored-By trailer.
`co_author = true` in `project.toml` allows one. Nothing hearthwork does pushes: a ticket ends
as a local commit on its own branch, for you to review and push.

## Token economy

Every call carries only what its role needs. Three switches, in the page's **economy** panel
or `operator economy`; ticked (the default) is the token-saving choice:

- **Disable MCP servers.** Your MCP servers' tool lists stay out of every call (measured: four
  claude.ai connectors cost 3,200 tokens per executor call). Unticked, the executor gets your
  servers, and may call only the tools a project lists in `mcp_allow`
  (`["postgres__query", "browser__*"]`); reading sessions never get them.
- **Control CLAUDE.md loading.** Your global `~/.claude/CLAUDE.md` and any CLAUDE.md in folders
  above the repository stay out; the executor reads hearthwork's doctrine and the repository's
  own CLAUDE.md. Unticked, your personal instructions join the executor's.
- **Control prompt cache lifetime.** The operator and the spirit keep a 1-hour cache (they pick
  up again after long gaps); the executor, survey and atlas a 5-minute one, whose writes cost
  37.5% less. Unticked, the Claude CLI picks one lifetime for every call.

Always on: each role's own short tool list, no background tasks, the fence. Each unit's record
says which switches were on; a switch applies from the next unit.

## Your limits

The page shows your 5-hour session and your week, with their resets, at no extra cost: every
Claude call hearthwork makes already reports them in a rate-limit event of Claude Code's
`stream-json` output. That event works today but is not yet in Claude Code's documented output
schema; if a version drops it, the tiles say there is no reading and nothing else changes. A
documented second source: `operator statusline --install`, which hands hearthwork the
documented `rate_limits` from your interactive sessions.

## Laptops and sleep

While a unit runs or the spirit answers, hearthwork holds the system's own sleep guard
(`caffeinate -i` on macOS, `systemd-inhibit` on Linux), tied to its process: the machine stays
awake for exactly as long as work is in flight; the screen may still lock. A closed lid still
sleeps a laptop. `[awake] on_ac = true` in `config.toml` also keeps a Mac awake on mains
power, and the page's **screen on** button keeps the display lit while the tab is in front.

## The page

`operator ui` listens on 127.0.0.1 only, never on the network. Each start makes a random key
and prints a link carrying it; every request needs it, a request whose Host is not the server's
own is refused, and only the archive pages and four kinds of unit record are served from the
home.
