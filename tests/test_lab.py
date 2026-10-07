import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "src"))

from test_loop import Fixture  # noqa: E402
from hearthwork import cli, contract, home, lab, worklog  # noqa: E402

OLD = "def total(x):\n    return x\n"
NEW = "def total(x):\n    return x * 1.2\n"
GUARD = "import sys\nsys.path.insert(0, '.')\nfrom app import total\nassert abs(total(10) - 12) < 1e-9\n"


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True).stdout


class LabFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        os.environ["HEARTHWORK_HOME"] = str(root / "home")
        os.environ["HEARTHWORK_NO_AWAKE"] = "1"
        self.repo = root / "repo"
        self.repo.mkdir()
        git(self.repo, "init", "-q", "-b", "main")
        git(self.repo, "config", "user.email", "t@example.com")
        git(self.repo, "config", "user.name", "T")
        (self.repo / ".gitignore").write_text("__pycache__/\n")
        (self.repo / "app.py").write_text(OLD)
        git(self.repo, "add", ".")
        git(self.repo, "commit", "-q", "-m", "start")
        home.init_home()
        self.p = home.add_project("shop", self.repo)
        lab.set_keys(self.p, {"test": f"{sys.executable} {{files}}"})
        self.p = home.resolve_project("shop")

    def tearDown(self):
        self.tmp.cleanup()

    def carry(self):
        (self.repo / "app.py").write_text(NEW)
        (self.repo / "test_tax.py").write_text(GUARD)

    def lab_cli(self, *args):
        return subprocess.run([sys.executable, "-m", "hearthwork", "lab", "-p", "shop", *args], capture_output=True,
                              text=True, cwd=str(self.repo), env=dict(os.environ, PYTHONPATH=str(HERE.parent / "src")))


class Config(LabFixture):
    def test_project_add_excludes_the_scratch_folder(self):
        self.assertIn("/.hearthwork-scratch/", (self.repo / ".git" / "info" / "exclude").read_text())
        (self.repo / ".hearthwork-scratch").mkdir()
        (self.repo / ".hearthwork-scratch" / "probe.py").write_text("print('PROBE {}')\n")
        self.assertEqual(git(self.repo, "status", "--porcelain"), "", "a probe never shows as a change")

    def test_keys_land_in_the_lab_table(self):
        lab.set_keys(self.p, {"lint": "ruff check {files}", "ab": "in-place"})
        p = home.resolve_project("shop")
        self.assertEqual(lab.conf(p)["lint"], "ruff check {files}")
        self.assertEqual(lab.conf(p)["ab"], "in-place")
        self.assertEqual(p.trunk, "main", "the top-level keys stay top-level")

    def test_the_atlas_prose_is_not_taken_for_a_command(self):
        atlas = ("## The lab\n- lab test: `python3 -m unittest {files}` [README.md:5, which gives the form `x`]\n"
                 "- lab lint: unknown (no linter is configured)\n- lab build: not needed\n"
                 "- lab scratch: `tests/`. unittest discovery works from there\n- lab ab: worktree, since there is no server.\n")
        self.assertEqual(lab.from_atlas(atlas), {"test": "python3 -m unittest {files}", "scratch": "tests/",
                                                 "ab": "worktree"})

    def test_an_older_atlas_falls_back_to_its_run_line(self):
        old = ("# Atlas\n\n## How to run things\n- Install: `npm ci` [package.json]\n"
               "- Run one test file: `npx vitest run src/cart/cart.spec.ts` [package.json:9]\n\n## Traps\nnone\n")
        self.assertEqual(lab.from_atlas(old), {"test": "npx vitest run {files}"})
        self.assertFalse(lab.has_lab_section(old))
        self.assertEqual(lab.test_from_run_line("- Run one test file: python3 -m unittest tests/test_cart.py [README.md]"),
                         "python3 -m unittest {files}")
        self.assertEqual(lab.test_from_run_line("- Run one test file: pytest -q tests/test_a.py::test_b -x"),
                         "pytest -q {files} -x")
        self.assertIsNone(lab.test_from_run_line("- Run one test file: unknown, no runner found"))
        self.assertIsNone(lab.test_from_run_line("- Run one test file: npm test"), "no path: nothing to replace")
        both = old + "\n## The lab\n- lab test: `pytest {files}`\n"
        self.assertEqual(lab.from_atlas(both)["test"], "pytest {files}", "a lab section wins")

    def test_a_scratch_folder_never_hides_tracked_files(self):
        (self.repo / "tests").mkdir()
        (self.repo / "tests" / "test_a.py").write_text("")
        git(self.repo, "add", ".")
        git(self.repo, "commit", "-q", "-m", "tests")
        with self.assertRaises(lab.LabError):
            lab.set_keys(self.p, {"scratch": "tests/"})
        lab.set_keys(self.p, {"scratch": "tests/_scratch"})
        lab.ensure_scratch(home.resolve_project("shop"))
        self.assertIn("/tests/_scratch/", (self.repo / ".git" / "info" / "exclude").read_text())

    def test_the_atlas_proposes_the_lab(self):
        atlas = ("# Atlas\n\n## The lab\n- lab test: `pytest -q {files}` [pyproject.toml]\n- lab lint: ruff check {files}\n"
                 "- lab up: unknown\n- lab scratch: tests/_scratch [pyproject.toml]\n\n## Traps\n- lab test: not this one\n")
        self.assertEqual(lab.from_atlas(atlas), {"test": "pytest -q {files}", "lint": "ruff check {files}",
                                                 "scratch": "tests/_scratch"})


class Gate(LabFixture):
    def test_a_gate_names_its_files(self):
        with self.assertRaises(lab.LabError) as e:
            lab.gate(self.p, [], echo=False)
        self.assertEqual(e.exception.code, 2)
        with self.assertRaises(lab.LabError):
            lab.gate(self.p, ["nope.py"], echo=False)

    def test_a_gate_runs_and_is_recorded(self):
        self.carry()
        self.assertEqual(lab.gate(self.p, [str(self.repo / "test_tax.py")], echo=False), 0)
        (self.repo / "app.py").write_text(OLD)
        self.assertNotEqual(lab.gate(self.p, ["test_tax.py"], cwd=self.repo, echo=False), 0)
        self.assertEqual(lab.status(self.p)["gate_last"]["files"], ["test_tax.py"])
        self.assertEqual(lab.summary(self.p)[0], "READY")


class CarriedAB(LabFixture):
    def verdict(self, files=("test_tax.py",)):
        r = self.lab_cli("ab", *files)
        self.assertIn("AB VERDICT", r.stdout, r.stdout + r.stderr)
        return lab._last_ab(self.p)["verdict"], r

    def test_worktree_proves_a_guard_and_never_touches_the_checkout(self):
        self.carry()
        before = git(self.repo, "status", "--porcelain")
        v, r = self.verdict()
        self.assertEqual(v, "GUARDS")
        self.assertEqual(r.returncode, 0)
        self.assertEqual((self.repo / "app.py").read_text(), NEW)
        self.assertEqual(git(self.repo, "status", "--porcelain"), before)
        self.assertNotIn("ab-worktree", git(self.repo, "worktree", "list"))

    def test_a_test_that_passes_anyway_is_named(self):
        (self.repo / "app.py").write_text(NEW)
        (self.repo / "test_any.py").write_text("assert True\n")
        v, _ = self.verdict(("test_any.py",))
        self.assertEqual(v, "PASSES-WITHOUT-CHANGE")

    def test_in_place_restores_the_work_and_the_index_verified(self):
        lab.set_keys(self.p, {"ab": "in-place"})
        self.carry()
        git(self.repo, "add", "test_tax.py")
        before = git(self.repo, "status", "--porcelain")
        v, r = self.verdict()
        self.assertEqual(v, "GUARDS")
        self.assertIn("RESTORE: VERIFIED", r.stdout)
        self.assertEqual((self.repo / "app.py").read_text(), NEW)
        self.assertEqual(git(self.repo, "status", "--porcelain"), before, "the staged file is staged again")
        self.assertEqual(git(self.repo, "for-each-ref", "refs/hearthwork"), "", "the saved ref is dropped once proven")

    def test_a_killed_in_place_ab_is_recovered_by_the_next_verb(self):
        lab.set_keys(self.p, {"ab": "in-place", "test": f"sleep 3; {sys.executable} {{files}}"})
        self.carry()
        env = dict(os.environ, PYTHONPATH=str(HERE.parent / "src"))
        subprocess.Popen([sys.executable, "-m", "hearthwork", "lab", "-p", "shop", "ab", "test_tax.py"],
                         cwd=str(self.repo), env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        marker = Path(self.p.dir) / "lab" / "ab-inflight.json"
        for _ in range(200):  # wait until BASE has swapped the files
            if marker.exists() and (self.repo / "app.py").read_text() == OLD:
                break
            time.sleep(0.05)
        self.assertEqual((self.repo / "app.py").read_text(), OLD, "BASE runs on HEAD's file")
        pid = json.loads(marker.read_text())["pid"]
        os.killpg(os.getpgid(pid), 9)
        time.sleep(0.5)
        self.assertEqual(lab.summary(home.resolve_project("shop"))[0], "RESTORE HELD")
        r = self.lab_cli("status")
        self.assertIn("operator lab restore", r.stdout, "status names the leftover and touches nothing")
        self.assertEqual((self.repo / "app.py").read_text(), OLD)
        r = self.lab_cli("restore")
        self.assertIn("RESTORE: VERIFIED", r.stdout + r.stderr)
        self.assertEqual((self.repo / "app.py").read_text(), NEW, "the work is back")
        self.assertTrue((self.repo / "test_tax.py").exists())
        self.assertEqual(git(self.repo, "for-each-ref", "refs/hearthwork"), "")

    def test_refusals(self):
        r = self.lab_cli("ab", "app.py")
        self.assertEqual(r.returncode, 2)
        self.assertIn("clean", r.stdout + r.stderr)
        (self.repo / "test_tax.py").write_text(GUARD)
        r = self.lab_cli("ab", "test_tax.py")
        self.assertEqual(r.returncode, 2, "only the named file changed: BASE would equal CARRIED")


class Server(LabFixture):
    def test_up_waits_for_health_and_down_stops_the_group(self):
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        lab.set_keys(self.p, {"up": f"{sys.executable} -m http.server {port} --bind 127.0.0.1",
                              "health": f"http://127.0.0.1:{port}/"})
        p = home.resolve_project("shop")
        self.assertEqual(lab.summary(p)[0], "DOWN")
        self.assertIn("up", lab.up(p, owner=999999))
        self.assertEqual(lab.summary(p)[0], "UP")
        self.assertIn("lab: <span", worklog.lab_chip([p]))
        r = subprocess.run([sys.executable, "-m", "hearthwork", "lab", "-p", "shop", "status"], capture_output=True,
                           text=True, env=dict(os.environ, PYTHONPATH=str(HERE.parent / "src")))
        self.assertIn(f"health: http://127.0.0.1:{port}/ — HTTP 200", r.stdout)
        self.assertTrue(lab.reap_orphan_server(p, echo=None), "a server whose run died is taken down")
        self.assertIn("no answer", lab.health_probe(lab.conf(p), timeout=1)[1])
        self.assertEqual(lab.summary(p)[0], "DOWN")


SERVER = """import http.server, socketserver, sys
class H(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass
s = socketserver.TCPServer(("127.0.0.1", 0), H)
port = s.server_address[1]
if sys.argv[1] == "url":
    print("\\x1b[32m  Local:   http://localhost:%d/\\x1b[0m" % port, flush=True)
elif sys.argv[1] == "port":
    print("app listening on port %d" % port, flush=True)
s.serve_forever()
"""


class FindsTheAddress(LabFixture):
    """`operator lab up` with no health URL: the address is found and saved."""

    def bring_up(self, how, timeout=20):
        (self.repo / "serve.py").write_text(SERVER)
        lab.set_keys(self.p, {"up": f"{sys.executable} serve.py {how}", "up_timeout": timeout})
        self.raised = p = home.resolve_project("shop")
        return p, lab.up(p, echo=False)

    def tearDown(self):
        if getattr(self, "raised", None):
            lab.down(self.raised)  # before the home is removed: down reads the server's state there
        super().tearDown()

    def test_from_what_the_server_prints(self):
        p, msg = self.bring_up("url")
        self.assertIn("found in the server's output; saved as health", msg)
        saved = home.resolve_project("shop").lab["health"]
        self.assertRegex(saved, r"^http://localhost:\d+/$")
        self.assertEqual(lab.summary(home.resolve_project("shop"))[0], "UP")

    def test_from_a_port_line(self):
        _, msg = self.bring_up("port")
        self.assertIn("found in the server's output", msg)

    @unittest.skipUnless(shutil.which("lsof") or shutil.which("ss"), "needs lsof or ss")
    def test_from_the_port_it_opens_when_it_prints_nothing(self):
        _, msg = self.bring_up("silent")
        self.assertIn("found from the port it listens on", msg)

    def test_a_server_that_never_answers_fails_with_its_log(self):
        (self.repo / "quiet.py").write_text("import time\nprint('starting...', flush=True)\ntime.sleep(60)\n")
        lab.set_keys(self.p, {"up": f"{sys.executable} quiet.py", "up_timeout": 5})
        with self.assertRaises(lab.LabError) as e:
            lab.up(home.resolve_project("shop"), echo=False)
        self.assertIn("printed no local address and listens on no TCP port", str(e.exception))
        self.assertIn("starting...", str(e.exception))
        self.assertEqual(lab.summary(home.resolve_project("shop"))[0], "DOWN")

    def test_reading_addresses(self):
        self.assertEqual(lab.url_from_output("  ➜  Local:   http://localhost:5173/\n"), "http://localhost:5173/")
        self.assertEqual(lab.url_from_output("Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C)"),
                         "http://localhost:8000/")
        self.assertEqual(lab.url_from_output("Server started on 0.0.0.0:3355? no: listening on port 3355"),
                         "http://localhost:3355/")
        self.assertIsNone(lab.url_from_output("compiling 412 modules"))


class Contract(unittest.TestCase):
    def test_a_stabilization_commit_proves_its_guard(self):
        plan = {"action": "execute", "unit": 3, "kind": "execution", "title": "guard and commit", "mode": "STABILIZATION",
                "role": "guard", "budget": "NONE", "commit_expected": True, "chain": "c", "chain_phase": 3,
                "chain_total": 3, "prompt": "Totals include tax.\nTARGET FILES: app.py\nINVARIANTS: none\nGATES: test_tax.py"}
        self.assertEqual(contract.check_plan(plan, 3), [], "no lab, no requirement")
        devs = contract.check_plan(plan, 3, lab_ready=True)
        self.assertTrue(any("operator lab ab" in d for d in devs))
        plan["prompt"] += "\nPROVE: operator lab ab test_tax.py, commit only on GUARDS"
        self.assertEqual(contract.check_plan(plan, 3, lab_ready=True), [])
        plan["lab"] = "yes"
        self.assertTrue(contract.check_plan(plan, 3, lab_ready=True))


class LoopWithLab(Fixture):
    def test_the_unit_carries_the_kit_and_the_lab_facts(self):
        os.environ["HW_PY"] = sys.executable
        p = home.resolve_project("demo")
        lab.set_keys(p, {"test": f"{sys.executable} {{files}}"})
        self.run_units(1)
        self.flag("exec-lab-ab")
        self.run_units(1)
        ex = [c for c in self.calls() if c["cwd"] == str(self.repo) and "TARGET FILES" in c["prompt"]][-1]
        self.assertIn("--agents", ex["argv"])
        agents = json.loads(ex["argv"][ex["argv"].index("--agents") + 1])
        self.assertEqual(sorted(agents), ["hw-investigator", "hw-prober", "hw-reviewer"])
        self.assertEqual(agents["hw-prober"]["model"], "sonnet")
        plug = Path(ex["argv"][ex["argv"].index("--plugin-dir") + 1])
        self.assertTrue((plug / "skills" / "hw-probe" / "SKILL.md").exists())
        self.assertTrue((plug / ".claude-plugin" / "plugin.json").exists())
        policy = json.loads(ex["policy"])
        self.assertEqual((policy["kind"], policy["role"]), ("execution", "guard"))
        self.assertTrue(policy["scratch"].endswith(".hearthwork-scratch"))
        facts = (self.t.unit_dir(2) / "facts.md").read_text()
        self.assertIn("lab ab: GUARDS on test_total.py", facts)
        self.assertIn("lab gate: rc 0 on test_total.py", facts)
        self.assertIn("sub-agents: hw-prober x1, hw-reviewer x1", facts)
        from hearthwork.records import read_meter
        row = read_meter(p)[-1]
        self.assertEqual(row["lab"]["ab"][0]["verdict"], "GUARDS")
        page = (Path(os.environ["HEARTHWORK_HOME"]) / "worklog.html").read_text()
        self.assertIn("A/B guards", page)
        self.assertIn("lab: <span class=\"lab good\"", page)
        inv = [c for c in self.calls() if c["cwd"] == str(self.repo)][0]
        self.assertEqual(json.loads(inv["policy"])["kind"], "investigation")


if __name__ == "__main__":
    unittest.main()
