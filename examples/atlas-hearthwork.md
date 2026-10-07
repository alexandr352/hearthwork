<!-- An example: the atlas `operator atlas` drafted of this very repository (0.3.4), in one read-only
     Sonnet session costing $0.10, shown as drafted and not edited. A real one is then reviewed, its
     questions answered, its "The lab" lines taken with `operator lab config --from-atlas`, and kept
     current by the operator. -->

# Atlas

## What this is
hearthwork is a plan → execute → judge loop for Claude Code. An "operator" plans units of work, a fenced "executor" does them in a checkout, and the operator judges the report against git facts. It also has a work-log web page, a chat "spirit", an MCP mode and a "lab" that runs tests and A/B proofs [README.md]. It is pure Python ≥3.10 with no runtime dependencies except `tomli` on <3.11, and its tests use `unittest` [pyproject.toml:11,20] [README.md].

## How to run things
- Install: `python3 -m venv .venv && .venv/bin/pip install -e .` [README.md "Development"]
- Build: unknown. It is a setuptools package with no build step for tests [pyproject.toml:1-3]. Doctrine `.md` files are shipped as package data [pyproject.toml:31-32].
- Run one test file: `.venv/bin/python -m unittest tests/test_lab.py` [README.md]
- Run tests matching a name: `.venv/bin/python -m unittest -k <pattern> tests/test_fence.py`. `-k` is listed in `python3 -m unittest --help`; the README does not show it.
- Lint / format / typecheck: unknown. No linter, formatter or type-checker config exists [ls -a]. Some files carry `# noqa: E402` [tests/test_lab.py:16], so flake8 or ruff may be used informally. Ask the person.
- Anything that must be running first: nothing. The tests use a stand-in for the Claude CLI, `tests/fake_claude.py`, and spend nothing [README.md]. The real tool needs `git` and a logged-in `claude` CLI [README.md "Install"]. The whole suite takes about a minute [README.md].

## Where things are
- `src/hearthwork/`: the package. The entry point is `operator = hearthwork.cli:main` [pyproject.toml:22-23] [ls src/].
- `docs/`: commands.md, how-it-works.md, safety.md, mcp.md and images [git ls-files].
- `examples/atlas-hearthwork.md`: an atlas previously drafted of this repo [README.md].
- `tests/`: one `test_<module>.py` per module, plus `fake_claude.py` [git ls-files].
- `CHANGELOG.md`: per-version notes. Versions marked "upgrade" change the doctrine [CHANGELOG.md:5-6].

Where most changes land:
- `src/hearthwork/cli.py` (802 lines): the argparse command surface [wc -l].
- `src/hearthwork/loop.py` (600 lines): the plan/execute/judge loop [wc -l].
- `src/hearthwork/lab.py` (1025 lines): `gate`, `ab`, `up`/`down`, `config`, restore [wc -l] [CHANGELOG.md].
- `src/hearthwork/fence.py` (491 lines): the executor's permission hook, run as a script with the policy passed via `HEARTHWORK_FENCE_POLICY` [tests/test_fence.py:9-17].
- `src/hearthwork/server.py` and `worklog.py`: the live page and work log [ls src/].
- `src/hearthwork/doctrine/`: the markdown prompts that get installed: `executor/`, `operator/`, `spirit/`, `agents/`, `skills/` [git ls-files].
- `contract.py`, `atlas.py`, `home.py`, `tickets.py`, `records.py`, `gitinfo.py`, `mcp.py`: the answer contracts, atlas handling, home directory and projects, tickets, records, git facts and MCP mode [ls src/].

## Conventions
- Tests use stdlib `unittest` classes. Shared fixtures are imported across test files, e.g. `from test_loop import Fixture` [tests/test_lab.py:16]. Test files insert `src` into `sys.path` [tests/test_lab.py:13-14].
- Tests isolate state with a temp dir and `HEARTHWORK_HOME`, and set `HEARTHWORK_NO_AWAKE=1` [tests/test_lab.py:32-33]. They build throwaway git repos with `git init -b main` [tests/test_lab.py:36].
- Tests drive the CLI as a subprocess: `python -m hearthwork lab -p shop ...` [tests/test_lab.py:56].
- The code style is plain stdlib Python with module-level `from . import ...` [src/hearthwork/cli.py:11-12]. Formatting config is unknown.
- Commits are plain subjects that start with the version, e.g. "0.3.4: lab up finds the server's address itself..." [git log]. Docs commits start with "Docs:" [git log]. Every release gets a new version number in `pyproject.toml`, and a `CHANGELOG.md` entry [CHANGELOG.md:23-24].
- The tool's own ticket branches look like `T-1-work` [tests/test_fence.py:25]. Whether this repo's own work uses ticket branches is unknown. The trunk is `main` [git status].
- Nothing is pushed by the tool; the person reviews and pushes [README.md].

## The lab
- lab test: `.venv/bin/python -m unittest {files}` [README.md]
- lab lint: unknown
- lab build: unknown
- lab up: unknown
- lab health: unknown
- lab scratch: `tests/_scratch` [tests/ holds the tests, and the README runs them by path]
- lab ab: worktree

Writing a throwaway probe: use `unittest.TestCase`. For code that needs a project, copy the `LabFixture.setUp` setup from `tests/test_lab.py:28-46`. It makes a temp `HEARTHWORK_HOME`, a temp git repo, `home.init_home()` and `home.add_project(...)`. For fence behaviour, copy the `ask()` helper from `tests/test_fence.py:13-17`. Note that a scratch file under `tests/_scratch/` needs the same `sys.path.insert(0, ".../src")` as `tests/test_lab.py:13-14`. Run it by path with `-m unittest`, since the README shows only path-based runs. `unittest discover -s tests` would not enter a folder without `__init__.py`, so name the file explicitly.

## Traps
- `HEARTHWORK_HOME` and `HEARTHWORK_NO_AWAKE` must be set in any test that touches the home directory. Without them a test could touch the real `~/.hearthwork` or keep the machine awake [tests/test_lab.py:32-33] [src/hearthwork/awake.py]. The default home location is unknown.
- `fence.py` is invoked as a standalone script by Claude Code hooks, so it needs to work without package imports [tests/test_fence.py:15]. Check that before adding imports to it.
- The doctrine `.md` files are package data that the installed tool reads. Edits there change the behaviour of every later session, and `operator upgrade` is needed after changes [pyproject.toml:31-32] [CHANGELOG.md:5-6].
- `HEARTHWORK_AB_OUT` is an environment variable used by the A/B path [grep src tests]. Its role is unknown, so read `lab.py` before touching the A/B.
- `git stash`, `git restore` and `git checkout -- <file>` are refused by the fence for executors. Baselines come from `operator lab ab` [tests/test_fence.py:59] [CHANGELOG.md].
- The full suite takes about a minute [README.md]. Use per-file runs.
- No CI workflow exists in the repo [ls -a: no .github].

## Questions for the person
1. Is there a linter, formatter or type-checker you want run (ruff, flake8, mypy)? None is configured.
2. Should work on this repo use ticket branches such as `T-<n>-...`, or short-lived branches off `main`? Which form do you prefer?
3. Do you want a `CHANGELOG.md` entry and a version bump in `pyproject.toml` on every change, or only for releases?
4. Which test files are slow or flaky? `test_lab.py`, `test_running.py` and `test_loop.py` look heaviest, but I did not run them.
5. Are any areas off limits, such as `fence.py` or the `doctrine/` prompts?
6. Is `.venv/bin/python` the right interpreter for the lab, or should it use another path?
7. What is the default `HEARTHWORK_HOME` location, and should tests ever run against it?
8. May `tests/_scratch` be used as the throwaway probe folder?
