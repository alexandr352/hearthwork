# Working from your own Claude Code session (MCP)

Instead of a fenced executor running on its own, your interactive Claude Code session can do
the units, in front of you: you see each edit and approve it as usual. The operator still plans
and judges in its own session, and the program still reads git itself, so the judge stays
independent of whoever did the work.

## Set up, once per repository

```sh
cd ~/code/shop
claude mcp add hearthwork -- operator mcp
```

## Work

```sh
cd ~/code/shop
claude
> work the next unit with hearthwork
```

Your session calls hearthwork's tools:

| Tool | What it does |
|---|---|
| `next` | Plans the next unit and hands your session its prompt, the executor's rules and the atlas, under a lease. Called again while a unit is open, it returns the same unit. |
| `submit` | Takes your session's report for the open lease. The program reads git; the operator judges and says what comes next. |
| `status` | Where the work stands. |
| `rule` | Records your answer to a halt, in your words. |

Planning and judging take minutes. Rather than hang, the tools answer "still planning, call
again" after about 50 seconds, and the work continues; the next call picks it up.

## The lab

`operator lab` works the same from your own session: named tests through `operator lab gate`,
a guard proven with `operator lab ab`, the server with `operator lab up`. The `next` tool hands
your session the lab's state with the unit. hearthwork's reader, prober and reviewer sub-agents
ride only on its own executor; in your session, your Claude Code does that work itself, under
the same rules (probes only in the scratch folder, one review of the diff before a commit).

## Good to know

- `operator run` never touches a unit that is open in your session. `operator abandon` drops
  one you walked away from, and the next plan is told so.
- Your own session is not fenced by hearthwork: you approve its edits. The page shows its
  units as "your session · not metered", since hearthwork cannot see what your session costs.
- Start `claude` inside the repository: that is how `operator mcp` knows which project it
  serves.
