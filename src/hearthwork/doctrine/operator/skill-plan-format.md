---
name: plan-format
description: The format of tickets/<TICKET>/plan.md — the header, the Units list grammar (done, pending, failed; chain annotations), and the working notes. Use when creating plan.md on a ticket's first unit, or when a re-plan restructures the plan.
---

# plan.md

Once plan.md exists it is its own template: read it and keep its shape.

    # <TICKET> — <title>
    Status: active | ready | halted
    ## Ticket
    <a faithful summary of ticket.md; quote acceptance criteria verbatim>
    ## Units
    1. [done] investigation — locate the defect surface (units/01)
    2. [done] investigation — trace the callers (units/02)
    3. [pending] execution — the model change (chain cart-total 1/2)
    4. [pending] execution — the tests, the gates and the one commit (chain cart-total 2/2)
    ## Working notes
    <durable context for this ticket that does not belong in knowledge.md>

Rules:
- Unit numbers never restart and never repeat; a failed unit stays in the list as
  `[failed]` with one line of why, and its retry is a new unit.
- A chain's units carry `(chain <name> <phase>/<total>)` on their line.
- The counts you report in JUDGE are read from this list: units_done is the number
  of `[done]` lines, units_planned the number of unit lines.
