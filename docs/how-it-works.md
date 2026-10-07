# How it works

## The unit

The atom of work is a **unit**: one bounded executor session, about 45 minutes at most, with
one prompt and one report. Every unit is three phases:

1. **Plan.** The operator, a Claude session that never reads your code, reads the ticket, the
   plan so far, its knowledge of the repository, your rulings and the git facts of the moment,
   and writes the prompt for one unit.
2. **Execute.** The executor, a separate session in your checkout behind the fence, does that
   unit and writes a report.
3. **Judge.** The program reads git itself (commits made, files touched, a clean or dirty
   tree) and hands those facts to the operator with the report. The operator judges the unit,
   updates the plan, writes down what it learned, and says what comes next.

The operator is never the one doing the work, and it judges against what git shows, not what
the report claims.

## Investigation before execution

No change is written on a hypothesis. A unit that changes code may be planned only when its
scope, invariants and target files are known and no open question blocks a safe change;
otherwise the unit is an **investigation**, read-only, and its findings come back as numbered
facts, each with a file and a line.

Work that ends in one commit is a **chain**: the investigations it needs, the changes (left
uncommitted on purpose between phases), and a last unit that runs the named tests once and
makes the one commit. Each chain has a **kind of work**, chosen by an ordered test:

| Kind | When |
|---|---|
| STABILIZATION | something is broken: reproduce it, fix it the smallest safe way, guard it with a test |
| FEATURE | the product lacks a behaviour: find where it goes, build it, cover it with tests |
| CONFIGURATION | the whole change is configuration files |
| MIGRATION | moving from one state to another in safe steps |
| REFACTOR | structure changes, behaviour stays exactly the same |
| AUDIT | a question: reading only, nothing is changed |

## Contracts

Every answer the operator gives is one JSON object with a declared shape, and the program
checks it before anything runs: an investigation without its scope line or findings
grammar, an execution without target files, a commit outside the chain's last phase. A broken
answer goes back to the **same** session with the deviation named, so it fixes exactly that;
three broken answers in a row halt the loop and ask you.

## Recovery

Nothing is lost when something stops midway.

| What happened | What the next run does |
|---|---|
| A usage limit stopped the executor | Resumes the same executor session, which finishes the unit. |
| The operator could not judge a finished report | Judges it before planning anything new. |
| The executor crashed or timed out | Asks a read-only session what the tree now holds, and the operator judges that. |
| The whole run died (terminal closed, laptop restarted) | Finds the unit that was planned but never judged, surveys the tree, and judges it. |
| The laptop went to sleep | Nothing to recover: the sleep guard keeps it awake while work is in flight. |

## Memory between units

The operator's session is resumed while its prompt cache is warm, and dropped after a commit:
the next unit starts fresh from files, not from a long conversation. After every verdict the
operator rewrites a short **handover** (`context-full.md`: what was decided and why, what was
tried and abandoned, where the work stands), so a fresh session picks up without re-reading
everything.

Two files carry what lasts:

- **The atlas** (`atlas.md`): the short map every executor reads before the code. Drafted by
  `operator atlas` from the repository, answered by you, kept current by the operator.
- **The knowledge** (`knowledge.md`): what the operator has learned about the repository, every
  fact with its source. Facts learned on a branch the trunk does not have yet are tagged
  `[on <branch>]` until it merges, so they are never mistaken for the trunk's truth.

## The records

Everything is plain files under `~/.hearthwork/projects/<name>/`:

```
project.toml  knowledge.md  atlas.md  units.jsonl  state.json
tickets/<ID>/
  ticket.md  rulings.md  plan.md  context-full.md
  units/NN/  plan.json  prompt.md  report.md  facts.md  verdict.json  before.json
```

`units.jsonl` has one line per unit: each phase's model, seconds, tokens, cost and cache
lifetime, the git facts, the verdict, and which economy switches were on. The work log, the
archive and the stats pages are built from these files by code, never by a model.

## Cost

A unit is three or more Claude calls. With `--resume`, the Claude CLI reports a session's
running total; hearthwork records each call's own increment. A small investigation costs
cents; a large change on a big codebase can cost a few dollars. `--max-cost` stops a run once
the spend reaches the limit.
