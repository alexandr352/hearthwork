---
name: hw-census
description: Recipes for a consumer census — who imports a file, calls a function, uses a component, reads a setting or a CSS variable — and the fan-in count, including the cases an import search misses (registration by name, string lookups, re-exports). Use when a unit asks for blast radius, consumers, call sites, or "what else is built from this".
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
