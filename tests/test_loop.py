import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))

from hearthwork import cli, home  # noqa: E402
from hearthwork.records import Ticket, read_meter  # noqa: E402


class Fixture(unittest.TestCase):
    """A throwaway home, a repository, a project and one ticket, wired to the fake CLI."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.state = root / "fake"
        os.environ["HEARTHWORK_HOME"] = str(root / "home")
        os.environ["HEARTHWORK_NO_AWAKE"] = "1"
        os.environ["FAKE_STATE"] = str(self.state)
        self.repo = root / "repo"
        self.repo.mkdir()
        for args in (["init", "-q", "-b", "main"], ["config", "user.email", "t@example.com"],
                     ["config", "user.name", "T"]):
            subprocess.run(["git", "-C", str(self.repo), *args], check=True)
        (self.repo / "total.txt").write_text("total = price\n")
        subprocess.run(["git", "-C", str(self.repo), "add", "."], check=True)
        subprocess.run(["git", "-C", str(self.repo), "commit", "-q", "-m", "start"], check=True)
        self.assertEqual(cli.main(["init"]), 0)
        (root / "home" / "config.toml").write_text(f'[claude]\nbin = "{HERE / "fake_claude.py"}"\n')
        self.assertEqual(cli.main(["project", "add", "demo", "--repo", str(self.repo)]), 0)
        self.assertEqual(cli.main(["ticket", "new", "T-1", "--text", "Totals must include tax."]), 0)
        self.p = home.resolve_project("demo")
        self.t = Ticket(self.p, "T-1")

    def tearDown(self):
        self.tmp.cleanup()

    def flag(self, name):
        self.state.mkdir(parents=True, exist_ok=True)
        (self.state / name).write_text("1")

    def calls(self):
        return [json.loads(l) for l in (self.state / "calls.jsonl").read_text().splitlines()]

    def run_units(self, n=1):
        return cli.main(["run", "-p", "demo", "--units", str(n)])


class LoopTest(Fixture):

    def test_two_units_to_ticket_ready(self):
        self.assertEqual(self.run_units(0), 0)
        st = self.p.read_state()
        self.assertIsNone(st.get("active_ticket"))
        self.assertIn("T-1", st["ready"])
        rows = read_meter(self.p)
        self.assertEqual([r["unit"] for r in rows], [1, 2])
        self.assertEqual(rows[1]["git"]["commits"], 1)
        facts = (self.t.unit_dir(2) / "facts.md").read_text()
        self.assertIn("Totals include tax", facts)
        self.assertFalse(self.t.path("chain.json").exists(), "the chain closed on its commit")
        self.assertFalse(self.t.path("session").exists(), "the operator session dropped at the commit")
        # The judge of unit 1 resumed the session the plan of unit 1 opened.
        ops = [c for c in self.calls() if c["cwd"] == str(self.p.dir)]
        self.assertIsNone(ops[0]["resume"])
        self.assertIsNotNone(ops[1]["resume"])
        page = (Path(os.environ["HEARTHWORK_HOME"]) / "worklog.html").read_text()
        self.assertIn("T-1", page)
        self.assertIn("ready", page)

    def test_plan_and_judge_see_where_the_checkout_stands(self):
        self.run_units(1)
        self.run_units(1)  # unit 2 commits on T-1-total, which main does not have
        subprocess.run(["git", "-C", str(self.repo), "checkout", "-q", "main"], check=True)
        cli.main(["ticket", "new", "T-2", "--use", "--text", "Count items."])
        self.run_units(1)
        plans = [c["prompt"] for c in self.calls() if c["prompt"].startswith("PHASE: PLAN")]
        self.assertIn("REPOSITORY FACTS AT PLAN", plans[0])
        self.assertIn("unmerged branches: none", plans[0])
        self.assertIn("checkout: branch main", plans[-1])
        self.assertIn("T-1-total: 1 commit(s) ahead", plans[-1])
        self.assertIn("unmerged branches", (self.t.unit_dir(2) / "facts.md").read_text())

    def test_every_cost_is_the_call_not_the_session(self):
        self.run_units(1)
        rows = read_meter(self.p)
        for calls in rows[0]["phases"].values():
            for c in calls:
                self.assertAlmostEqual(c["cost_usd"], 0.10, places=6)

    def test_broken_plan_is_reconsidered_in_the_same_session(self):
        self.flag("plan-bad-once")
        self.assertEqual(self.run_units(1), 0)
        plans = read_meter(self.p)[0]["phases"]["plan"]
        self.assertEqual(len(plans), 2)
        ops = [c for c in self.calls() if c["cwd"] == str(self.p.dir)]
        self.assertTrue(ops[1]["prompt"].startswith("DEVIATION"))
        self.assertEqual(ops[1]["resume"], plans[0]["session_id"])

    def test_usage_limit_resumes_the_executor(self):
        self.run_units(1)  # unit 1
        self.flag("exec-wall")
        self.run_units(1)  # unit 2 walls in execute
        rs = self.t.read("resume.json")
        self.assertEqual(rs["unit"], 2)
        self.assertFalse((self.t.unit_dir(2) / "verdict.json").exists())
        self.run_units(1)  # resumes, then judges
        self.assertFalse(self.t.path("resume.json").exists())
        self.assertTrue((self.t.unit_dir(2) / "verdict.json").exists())
        resumed = [c for c in self.calls() if c["prompt"].startswith("Your session was interrupted")]
        self.assertEqual(resumed[0]["resume"], rs["session_id"])

    def test_crash_is_surveyed_and_judged(self):
        self.run_units(1)
        self.flag("exec-crash")
        self.run_units(1)
        d = self.t.unit_dir(2)
        self.assertIn("EXECUTOR FAILED", (d / "report.md").read_text())
        self.assertTrue((d / "survey.md").exists())
        self.assertIn("tree: NOT clean", (d / "facts.md").read_text())
        judge = [c for c in self.calls() if c["prompt"].startswith("PHASE: JUDGE")][-1]
        self.assertIn("SURVEY:", judge["prompt"])

    def test_halt_and_rule(self):
        self.flag("plan-halt")
        self.assertEqual(self.run_units(1), 1)
        st = self.p.read_state()
        self.assertIn("currency", st["halted"]["reason"])
        self.assertEqual(self.run_units(1), 1, "a halted project does not run")
        self.assertEqual(cli.main(["rule", "-p", "demo", "Use EUR."]), 0)
        self.assertIn("Use EUR.", self.t.path("rulings.md").read_text())
        self.assertNotIn("halted", self.p.read_state())
        self.assertEqual(self.run_units(1), 0)
        plan = [c for c in self.calls() if c["prompt"].startswith("PHASE: PLAN")][-1]
        self.assertIn("RULINGS:", plan["prompt"])

    def test_operator_and_executor_are_fenced(self):
        self.run_units(1)
        for c in self.calls():
            argv = c["argv"]
            settings = json.loads(argv[argv.index("--settings") + 1])
            hook = settings["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
            self.assertIn("fence.py", hook)
            self.assertIn("--strict-mcp-config", argv)
            self.assertIn("--tools", argv)


if __name__ == "__main__":
    unittest.main()
