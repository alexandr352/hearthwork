---
name: knowledge-contract
description: The discipline for writing knowledge.md — target section, operation (prefer Replace), replacement target, ticket tag — and the rules that bind every write. Use in PHASE JUDGE before the first write to knowledge.md, and at a ticket's close pass.
---

# Writing knowledge.md

Settle all four before each update:
- TARGET SECTION: the one section the fact belongs in.
- OPERATION: Add, Replace, Remove or Convert. PREFER REPLACE. Appending a corrector
  beside a stale entry is the failure, not the fix.
- REPLACEMENT TARGET: named, whenever you Replace or Remove.
- TICKET TAG: a fact useful only while this ticket is open is tagged `[<TICKET>]`, so it
  can be promoted or retired at the close.

Rules:
- ONE PLACE PER FACT. Two entries that disagree are forbidden; the older is replaced.
- RESOLVED MEANS GONE. A fixed bug is removed and its durable lesson converted into a
  structural section; an answered question is removed, not marked answered.
- NOT A CHANGELOG. git log is the history. Keep only what still matters for work.
- "Now" IS A SUMMARY. It refers to other sections by name and never copies them.
- CLOSE PASS (before ticket-ready): every `[<TICKET>]` entry is promoted (rewritten
  free of the ticket), retired, or carried. The file should leave the ticket no larger
  than the repository's real gain in understanding.
- SIZE IS A SYMPTOM. Growth that tracks tickets closed rather than understanding gained
  means the close pass was skipped. You pay for this file on every cold start.
