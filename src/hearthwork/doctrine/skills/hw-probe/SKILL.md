---
name: hw-probe
description: How to write and run a DISPOSABLE probe — a throwaway test in the git-excluded scratch folder that measures one behaviour of the running code and prints what it measured — and how to read it into a report. Use when a unit asks for a reproduction, a runtime measurement, or "what does the code actually do", instead of reasoning from the source.
---

# The disposable probe

A probe is a test that exists to MEASURE, not to guard. It lives in the project's scratch
folder (the atlas names it; by default `.hearthwork-scratch/`), which git ignores in this
checkout only, so it never shows as a change and never ends up in a commit. It runs ONCE
through the lab, and what it printed goes into the report.

## Shape

Write it in the project's own test framework (the atlas names it, and how to run one
file), so it runs exactly the way the real tests run:

- one file, named after what it measures: `probe_total_with_tax.<ext>`
- set up only what the measurement needs, with the project's own fixtures and helpers
  (read one existing test near the code first, and copy its imports and setup)
- drive the REAL code path a user would hit, never a demo page or a mock of the thing
  being measured
- print what you measured on one line that starts with `PROBE`, as JSON:
  `PROBE {"input": 10, "total": 10, "expected": 12}`
- assert nothing you are not sure of: a probe that passes and prints is the normal case;
  a probe that fails is fine too, when the failure IS the measurement (the reproduction)

## Run

    operator lab gate <scratch>/probe_total_with_tax.<ext>

Foreground, with the shell tool's timeout at its maximum (600000 ms). If `operator lab
status` says the lab's server is DOWN and the probe needs it, that is your finding: report
it and stop.

## Rules

- ONE probe, one purpose, one run. A product result is never re-run for a nicer number.
  ONE exception: the probe crashed on its OWN code (a typo, a wrong import, a helper that
  does not exist): fix the probe and run it once more.
- Wait on conditions, never on time: a fixed sleep measures the machine, not the code.
- Never edit product code, the real tests, configuration or anything outside the scratch
  folder to make a probe work. If it cannot measure without that, it is a finding.
- Never git: no add, commit, stash, checkout or restore.
- The probe is never moved into the real tests. A guard is written deliberately, in the
  guard step, from what the probe showed.

## Report

Open with the probe's own output, verbatim: every `PROBE` line and the exit code. Then the
facts, one per line:

    [N] File: <the probe file> | Line: <the PROBE line> | Finding: <what was measured> | Confidence: high

What you believe but did not measure goes under OPEN QUESTIONS, never as a finding.
