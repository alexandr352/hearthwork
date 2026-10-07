<!-- An example: the atlas `operator atlas` drafted of this very repository, in one read-only
     Sonnet session costing $0.12, shown as drafted and not edited. A real one is then reviewed,
     its questions answered, and kept current by the operator. -->

# Atlas

## What this is
hearthwork is a plan → execute → judge loop for Claude Code. An "operator" session plans and judges, a fenced "executor" session does the work in a git checkout, and a "spirit" chat session sits beside them. It is pure-stdlib Python (3.11+, no dependencies) and ships a CLI named `operator`, a stdio MCP mode, and a local web UI that shows the work log. [README.md] [pyproject.toml:`requires-python`, `dependencies = []`, `[project.scripts]`]

## How to run things
- Install: `pipx install git+https://github.com/alexandr352/hearthwork` or `pip install --user git+https://github.com/alexandr352/hearthwork`, then `operator doctor` [README.md]. A local editable install is not documented: `unknown`. A `.venv/` exists but is gitignored [ls -a, .gitignore].
- Build: no build step. setuptools backend; the doctrine `.md` files are packaged as package-data [pyproject.toml].
- Run one test file: `python -m unittest tests/test_fence.py` is `unknown`; no test command appears in any file I read. The tests are `unittest.TestCase` classes with `unittest.main()` at the bottom [tests/test_contract.py:2,28,80]. `python tests/test_contract.py` should therefore work, but I did not run it. Some tests insert `src` into `sys.path` themselves [tests/test_loop.py:12], and `test_fence.py` runs `src/hearthwork/fence.py` as a subprocess [tests/test_fence.py:9,15].
- Run tests matching a name: `unknown`. With unittest the form would be `python tests/test_fence.py ExecutorFence.test_quoted_paths_do_not_hide`, but nothing in the repository states it. No pytest config exists [pyproject.toml].
- Lint / format / typecheck: none configured. pyproject has no `[tool.*]` section besides setuptools, and there is no CI directory [pyproject.toml; ls -a, `.github` absent].
- Must be running first: nothing for the tests. They use a throwaway `HEARTHWORK_HOME`, a temp git repo and `tests/fake_claude.py` in place of the real `claude` CLI [tests/test_loop.py:15-30, tests/fake_claude.py:1]. Real use needs git and a logged-in `claude` CLI [README.md "Install"].

## Where things are
- `src/hearthwork/`: the package [git ls-files]
- `src/hearthwork/doctrine/`: markdown prompts per role, shipped as package-data: `executor/` (EXECUTOR.md, ATLAS-BUILD.md), `operator/` (CLAUDE.md, seeds, skill-* files), `spirit/` [git ls-files]
- `tests/`: unittest tests and `fake_claude.py`, a stand-in for the Claude CLI [git ls-files]
- Runtime data is not in the repo. It lives in `~/.hearthwork/` or `$HEARTHWORK_HOME` and holds `config.toml`, `projects/<name>/…` and the spirit's files [README.md "The home"; src/hearthwork/home.py:77].

Where changes land:
- `cli.py` (430 lines): argparse subcommands such as init, project, ticket, run, rule, status, doctor, atlas, ui, chat, mcp [src/hearthwork/cli.py].
- `loop.py` (420 lines): the plan/execute/judge loop, retries and recovery. It builds the fence policy passed in `HEARTHWORK_FENCE_POLICY` [src/hearthwork/loop.py:86].
- `fence.py` (404 lines): the PreToolUse hook, default-deny, with modes executor, read-only, operator and spirit. It is run as a standalone script [README.md "The fence"; tests/test_fence.py].
- `contract.py`: checks that plans and verdicts have the required shape [tests/test_contract.py].
- `home.py`, `records.py`: home and project layout, and the Ticket and unit records. `gitinfo.py` reads the git facts the judge sees.
- `claude.py`: invokes the `claude` CLI. `mcp.py`: MCP stdio mode. `server.py` and `worklog.py`: the web UI and `worklog.html`. `atlas.py`: atlas drafting. `awake.py`: the sleep guard.
- `doctrine/*.md`: edit these to change what each session is told.

## Conventions
- Module docstring at the top of each file, short comments, no third-party dependencies [src/hearthwork/cli.py:1; pyproject.toml].
- Tests are `unittest` classes in `tests/test_<module>.py`. Tests that need the loop build a temp home, repo and ticket and set the `HEARTHWORK_HOME`, `HEARTHWORK_NO_AWAKE` and `FAKE_STATE` env vars [tests/test_loop.py:15-30].
- CLI errors go through `fail(msg)`, which prints `operator: <msg>` to stderr and returns exit code 2 [src/hearthwork/cli.py:19-21].
- Files in the home are written atomically with `home.write_atomic` [src/hearthwork/cli.py:90].
- Ticket IDs match `home.TICKET_ID`: letters, digits, `.`, `_` or `-` [src/hearthwork/cli.py:75-76].
- Commits carry the person's own git identity, with no co-author trailer unless `co_author = true` is set in `project.toml` [git log f2a06c0]. Commit subjects are plain descriptive sentences with no prefix [git log].
- Executor work goes on a ticket branch that the executor never pushes. The atlas-branch form is `unknown` (see questions). The only example seen is `T-1-work` in a fence test [tests/test_fence.py:25].

## Traps
- `fence.py` is a security-relevant, default-deny guard that tests execute as a subprocess. With no `HEARTHWORK_FENCE_POLICY` it denies everything [tests/test_fence.py:150 `NoPolicyDenies`; src/hearthwork/fence.py:361]. Its own README says it is a guard rail, not a sandbox [README.md].
- `test_fence.py` uses the real `Path.home()` and asserts denial of paths like `~/.ssh` [tests/test_fence.py:10,36-39]. It reads paths but does not modify them.
- Setting `HEARTHWORK_HOME` is what keeps tests from touching `~/.hearthwork`. New tests must set it [tests/test_loop.py:19].
- The `doctrine/` markdown is prompt text that code reads at runtime. `operator upgrade` copies it into each project's operator directory (`home.refresh_doctrine`), so edits here don't reach existing projects until then [src/hearthwork/cli.py:64-68].
- `HEARTHWORK_NO_AWAKE` disables the sleep guard (`caffeinate` or `systemd-inhibit`) [src/hearthwork/awake.py:26].
- `__pycache__` holds `cpython-314` bytecode, so the local Python is 3.14. It is gitignored [ls; .gitignore].
- The README says the fence is also what keeps executors from pushing. The git repo has a single branch, `main`, and no CI [git branch -a].

## Questions for the person
1. What is the exact command to run one test file and one test by name (unittest or pytest)? The repository states neither.
2. How should ticket branches be named (for example `T-12-short-title`), and is `main` the trunk?
3. Do you want a linter, formatter or type checker used (ruff, mypy)? None is configured, so should a session add none?
4. Is an editable install (`pip install -e .` in `.venv`) the expected dev setup?
5. Which areas are off limits or need extra care, such as `fence.py` and the doctrine prompts?
6. Is any test slow or flaky? `test_loop.py` and `test_mcp.py` drive subprocesses and may be.
7. Should commits ever carry a co-author trailer, or is the default of none right for this repository?
8. Does `operator upgrade` need to be run after changing a doctrine file, or does something else handle that?
