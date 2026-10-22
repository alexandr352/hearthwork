---
name: hw-census
description: Recipes for a consumer census — who imports a file, calls a function, uses a component, reads a setting or a CSS variable — and the fan-in count, including the cases an import search misses (registration by name, string lookups, re-exports); and the site census of a FAMILY (every further place a shipped fix should repeat, measured and grouped). Use when a unit asks for blast radius, consumers, call sites, "what else is built from this", or the sites of a FAMILY.
---

# Consumer census

Answer "who uses this?" from the files, with every site cited. Prefer `git grep` (it reads
only tracked files, so build output and dependencies stay out); fall back to `grep -rn`
with explicit excludes.

## Recipes

    git grep -n -E "<symbol>\b"                                  # every mention
    git grep -l -E "from ['\"].*<module>['\"]|import .*<module>" | wc -l   # fan-in by import
    git grep -n -E "<name>" -- '*.<ext>' ':!*test*' ':!*spec*'   # product code only
    git grep -n -E "['\"]<name>['\"]"                            # string lookups: registries, routes, DI keys

What an import search misses — look for each explicitly:
- registration by name (plugins, components or directives registered globally, routes)
- re-exports (an index file that re-exports the symbol under the same or another name)
- dynamic access (getattr, `obj[name]`, reflection, templates resolving names at runtime)
- configuration that names it (YAML, JSON, env)
- other languages in the repository calling it (a CLI, an API client, SQL)

## Report

One line per site, in the findings grammar, then the counts:

    [N] File: <path> | Line: <line> | Finding: <how it uses it> | Confidence: <high|medium|low>
    COUNT: <n> files, <m> sites (product code); <k> in tests

Rules:
- a file counts once per census, however many sites it has;
- say what you did NOT count (tests, generated files, examples) explicitly;
- a site you inferred but did not see goes under OPEN QUESTIONS.

## Site census (a FAMILY)

When the unit asks for every further place that carries a defect a shipped commit already
fixed once:

1. Read the shipped commit itself (`git show <sha>`) and the test that guards it: what it
   changed, in which primitive, with which words. That is the PATTERN; never describe it
   from memory or from the ticket.
2. Find the candidates: the same primitive used elsewhere, the same markup or call shape
   without the fix, the same deviation named in the ticket (the recipes above).
3. MEASURE each candidate where the product runs (the probe skill, a disposable probe in
   the scratch folder): what a user would meet there today. A site read only from the
   source is a candidate, and its row says `unmeasured`.
4. Group like sites: sites built from the same component, helper or style take one fix
   together. A site that shares nothing names itself as its group.
5. Say what a site that does NOT fit the pattern looks like here, so a fix step can tell.

Return these blocks by name, after the findings:

    PATTERN: <sha> | <what it changed> | <known side effects>
    SITES:
    [1] <file> | <line> | <measured state, or unmeasured> | <deviation from the pattern> | <group>
    [2] ...
    BLOCKED: <what kept a site from being measured | how to enable it>   (or: BLOCKED: none)

Every row has five fields; the program counts the rows and the groups from the last field.
"THE PATTERN DID NOT SHIP" and "NO FURTHER SITE CARRIES THE DEVIATION" are complete answers;
name what you searched.
