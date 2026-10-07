---
name: hw-self-review
description: The self-review step before a commit — run ONCE over the whole uncommitted diff after the gates are green: call the hw-reviewer sub-agent, put its cited findings in the report under SELF-REVIEW, then commit unless a finding is a defect in the change itself. Use in every unit that commits, before `git commit`.
---

# Self-review before the commit

A reviewer reads a pull request with a few lenses. This step applies them to the whole
change BEFORE it becomes a commit, so the pull request finds less. It is a read, not a
repair.

1. WHEN: after the named gates are green, before `git commit`. Once per commit.
2. CALL THE REVIEWER, in the foreground: the Agent tool with `subagent_type: hw-reviewer`
   and a prompt of exactly this shape:
   "Review the current uncommitted diff. Untracked files to include: <the new files you
   wrote>. What the change must do: <the acceptance criteria from your prompt, or
   'none given'>."
   One call. Never a second one hoping for another answer.
3. Copy its findings VERBATIM into your report under `SELF-REVIEW:`. Do not add your own,
   and do not drop any.
4. DECIDE, and say which:
   - a finding is a DEFECT IN YOUR CHANGE (wrong behaviour, a rule of the repository's
     CLAUDE.md broken, a criterion the change was meant to meet and does not): fix it in
     this unit only if it is inside your TARGET FILES and is one small hunk, then run the
     named gates again, once; otherwise COMMIT NOTHING, report it, and stop. The operator
     plans the follow-up.
   - a finding is OUTSIDE your change (the same pattern elsewhere, a file that usually
     changes together, a problem that was there before): report it under SELF-REVIEW and
     commit as planned. It becomes a later unit, never a widening of yours.
5. The commit message does not mention the review.
