ATLAS BUILD — READ-ONLY.

You are drafting the ATLAS of this repository: the short, practical map that every later
session reads before the tree, so that no session has to re-learn the project. A person
will review your draft and fix what is wrong. Write what a capable engineer new to this
repository needs on day one, and nothing more.

DO NOT edit, create, delete, stage or commit anything, and do not install anything. Read
only. You may run commands that only read or list (git log, ls, a test runner's
list/collect-only mode, `--help` and `--version`), but do not run builds or test suites.

SCOPE CONSTRAINT: Read at most 25 files. Read at most 200 lines per file. Prefer, in this
order: the README and any docs index; the repository's own CLAUDE.md or AGENTS.md files;
package and build manifests (package.json, pyproject.toml, Cargo.toml, go.mod, Makefile,
Gemfile, pom.xml, build.gradle, ...); CI workflows; lint, format and test configuration;
the top of the main entry points; one or two representative tests.

EVERY FACT NAMES ITS SOURCE in brackets: `[package.json:12]`, `[README.md]`, `[ls src/]`.
A fact you could not confirm is written as `unknown` with what would settle it. Never
guess a command: a command you write must appear in a file you read, or be what a
manifest's own script names.

RETURN EXACTLY THIS MARKDOWN, these headings in this order, and nothing before or after it:

# Atlas

## What this is
Two or three sentences: what the project does, its languages and frameworks.

## How to run things
- Install: <command> [source]
- Build: <command> [source]
- Run one test file: <the exact form, with a real example path> [source]
- Run tests matching a name: <form> [source]
- Lint / format / typecheck: <commands> [source]
- Anything that must be running first (a database, a service, an env file): [source]

## Where things are
The top-level layout, one line per meaningful directory, then the 3 to 8 places most
changes land, each with what lives there.

## Conventions
Code style, test style and location, naming, error handling, anything a reviewer would
insist on, read from config and from the code itself. Branch and commit conventions if
the repository states them.

## The lab
How a unit runs this repository's tests, each line the exact command, `{files}` standing for
one or more test files (write `unknown` when the repository does not show it):
- lab test: <the command that runs only the named test files, with {files}> [source]
- lab lint: <the lint command, with {files} if it takes files> [source]
- lab build: <only if tests need a build first> [source]
- lab up: <only if tests need a running server: the command that starts it in the foreground> [source]
- lab health: <the local URL that answers once that server is up, when the dev server's config, an
  env example or a script names its port; else unknown: the lab finds it when the server starts> [source]
- lab scratch: <a folder that does NOT exist yet, where the test runner finds a throwaway test
  named on its command line (it will be excluded from git whole, so never an existing folder):
  e.g. tests/_scratch when the runner only collects under tests/; else .hearthwork-scratch> [source]
- lab ab: worktree, or in-place when the tests run against the lab's server
Each value is the bare command in backticks, or the single word unknown; never a sentence.
Then two or three lines on writing a throwaway probe test here: the framework, which fixture
or helper sets up the code under test, and one existing test to copy the setup from.

## Traps
Things that would cost a newcomer an hour: generated files not to edit, slow or flaky
suites, environment variables, ordering constraints, unusual tooling. Only what you saw
evidence of.

## Questions for the person
Numbered questions only the person can answer, for the facts you could not find in the
repository: which tests are slow, what must run locally, which env file to use, which
areas are off limits, how they like commits and branches named. At most 8, most
important first.
