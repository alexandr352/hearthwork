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

    def test_detached_run_returns_at_once_and_finishes(self):
        import time as _t
        t0 = _t.time()
        self.assertEqual(cli.main(["run", "-p", "demo", "--detach"]), 0)
        self.assertLess(_t.time() - t0, 3, "detach returns at once")
        for _ in range(100):
            if read_meter(self.p):
                break
            _t.sleep(0.1)
        rows = read_meter(self.p)
        self.assertEqual([r["unit"] for r in rows], [1], "the background run did its one unit")
        logs = list((Path(os.environ["HEARTHWORK_HOME"]) / "runs").glob("*.log"))
        self.assertEqual(len(logs), 1)
        for _ in range(200):  # let the background run finish writing before the folder goes
            if "spent $" in logs[0].read_text():
                break
            _t.sleep(0.05)

    def test_a_unit_whose_run_died_is_surveyed_and_judged(self):
        self.run_units(1)  # unit 1 judged
        import json as _j
        d = self.t.unit_dir(2)
        d.mkdir(parents=True)
        (d / "plan.json").write_text(_j.dumps({"action": "execute", "unit": 2, "kind": "execution",
                                              "title": "fix the total", "prompt": "x"}))
        (self.repo / "total.txt").write_text("half an edit\n")
        self.run_units(1)
        self.assertTrue((d / "verdict.json").exists(), "the orphan is judged, not skipped")
        self.assertTrue((d / "survey.md").exists())
        self.assertIn("ended before this unit was judged", (d / "facts.md").read_text())
        self.assertIn("tree: NOT clean", (d / "facts.md").read_text())
        self.assertEqual(read_meter(self.p)[-1]["recovered"], "orphan")
        self.assertFalse((self.t.unit_dir(3)).exists(), "no new unit was planned over it")

    def test_usage_is_read_from_every_call(self):
        self.run_units(1)
        from hearthwork import worklog
        from hearthwork.claude import read_usage
        u = read_usage()
        self.assertAlmostEqual(u["five_hour"]["used"], 0.42)
        self.assertAlmostEqual(u["seven_day"]["used"], 0.87)
        page = worklog.render(ui=True)
        self.assertIn("42%</span>5-hour session", page)
        self.assertIn("class=warnpct>87%</span>week", page, "a week past 80% is marked")
        for c in self.calls():
            self.assertIn("stream-json", c["argv"])

    def test_repo_settings_switch(self):
        self.run_units(1)
        ex = [c for c in self.calls() if c["cwd"] == str(self.repo)][0]["argv"]
        self.assertEqual(ex[ex.index("--setting-sources") + 1], "project,local")
        toml = self.p.dir / "project.toml"
        toml.write_text(toml.read_text().replace("repo_settings = true", "repo_settings = false"))
        self.run_units(1)
        ex = [c for c in self.calls() if c["cwd"] == str(self.repo)][-1]["argv"]
        self.assertEqual(ex[ex.index("--setting-sources") + 1], "local", "the repository's own settings and hooks are left out")

    def test_repo_hooks_are_noticed(self):
        from hearthwork import home as _home
        (self.repo / ".claude").mkdir()
        (self.repo / ".claude" / "settings.json").write_text(
            '{"hooks": {"PreToolUse": [{"matcher": "*", "hooks": [{"type": "command", "command": "python3 .claude/scripts/guard.py"}]}]}}')
        self.assertEqual(_home.repo_hooks(self.repo), ["PreToolUse: python3 .claude/scripts/guard.py  (settings.json)"])

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
            if c["cwd"] == str(self.repo):
                self.assertFalse(settings["includeCoAuthoredBy"])
                self.assertFalse(settings["attribution"]["commitTrailers"])
            self.assertIn("--tools", argv)


if __name__ == "__main__":
    unittest.main()
