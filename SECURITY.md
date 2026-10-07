# Security

hearthwork runs Claude Code sessions with `--dangerously-skip-permissions` and relies on its
own fence (a PreToolUse hook) to keep each session inside its lane. A way around the fence,
or around the local server's key, is a security bug, and I want to hear about it.

## Reporting

Please report privately, through GitHub: the **Security** tab of this repository, then
**Report a vulnerability**. Do not open a public issue for it.

Say what you ran, what the fence (or the server) allowed, and what it should have refused;
the smallest command that shows it is the most useful report. I read every report and answer
as soon as I can; this is a one-person project, so there is no fixed response time.

## What counts

- **A fence bypass:** an executor session that reads a secret (`~/.ssh`, `~/.aws`, `.env`, ...),
  writes outside the checkout and `/tmp`, pushes, rewrites history, reaches the network, runs a
  background job or escalates privilege, by a command the fence allows. The same for a reading
  session (atlas, survey) that changes anything, an operator session that reaches the
  repository, or a spirit session that writes outside its memory.
- **The local server (`operator ui`):** any way for a page on another site, another user on
  the machine, or the network to read the log, the records, or drive the chat, without the
  key the server printed.
- **Secrets in records:** a token or password that ends up in the ledger, the work log, the
  archive pages or a commit made by the loop.

## What the fence does not promise

The fence is a guard rail, not a sandbox, and the README says so. It stops an honest session
from wandering and the common accidents; it reads tool calls, not what a program does once it
runs. These are known and documented, so they are not vulnerabilities on their own:

- Code an allowed interpreter runs (`python3 script.py`, a test that reads a file) is not
  inspected beyond the command line that starts it.
- A commit message written to a file and committed with `git commit -F` is not read for
  attribution trailers.
- MCP server tools, when you switch your servers on, act where the fence cannot see; the fence
  only limits which of them may be called (`mcp_allow`).
- Your own Claude Code session in MCP mode is not fenced by hearthwork: you approve its edits.

For unattended runs, use a separate OS user that owns only the checkout. That is the boundary
that holds when a guard rail does not.

## Supported versions

Only the latest version on `main` gets fixes.
