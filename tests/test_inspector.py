import json
import os
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))
sys.path.insert(0, str(HERE))
from hearthwork import box, cli, home, inspector  # noqa: E402
from test_loop import Fixture  # noqa: E402


def trace(path, steps, frames, resources):
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("test.trace", "\n".join(json.dumps(e) for e in steps))
        z.writestr("1-trace.trace", "\n".join(json.dumps(e) for e in frames))
        for k, v in resources.items():
            z.writestr("resources/" + k, v)


class Frames(unittest.TestCase):
    def test_frames_after_steps_carry_their_timing(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            steps = [{"type": "before", "callId": "1", "startTime": 0, "title": "Click getByRole('button')", "category": "pw:api"},
                     {"type": "after", "callId": "1", "endTime": 10},
                     {"type": "before", "callId": "2", "startTime": 100, "title": "Press Tab", "category": "pw:api"},
                     {"type": "after", "callId": "2", "endTime": 110},
                     {"type": "before", "callId": "3", "startTime": 900, "title": "Expect \"toBeFocused\"", "category": "expect"},
                     {"type": "after", "callId": "3", "endTime": 920},
                     {"type": "before", "callId": "4", "startTime": 950, "title": "inner", "category": "pw:api", "parentId": "3"}]
            frames = [{"type": "screencast-frame", "timestamp": 50, "sha1": "a"},
                      {"type": "screencast-frame", "timestamp": 600, "sha1": "b"}]
            trace(d / "t.zip", steps, frames, {"a": b"\xff\xd8A", "b": b"\x89PNG....B"})
            out = inspector.key_frames(d / "t.zip", d / "frames", "t01")
            self.assertEqual([f["frame"] for f in out], ["t01-001.jpeg", "t01-002.png"])
            self.assertIn("TRANSIENT", out[0]["flags"], "the click's state lasted 90 ms")
            self.assertEqual(out[1]["after"], ["Press Tab", 'Expect "toBeFocused"'], "one picture, two moments")
            self.assertEqual((d / "frames" / "t01-002.png").read_bytes(), b"\x89PNG....B")

    def test_a_step_with_no_frame_after_it_is_stale(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            steps = [{"type": "before", "callId": "1", "startTime": 0, "title": "Press Tab", "category": "pw:api"},
                     {"type": "after", "callId": "1", "endTime": 500}]
            trace(d / "t.zip", steps, [{"type": "screencast-frame", "timestamp": 100, "sha1": "a"}], {"a": b"\xff\xd8A"})
            self.assertEqual(inspector.key_frames(d / "t.zip", d / "f", "t01")[0]["flags"], ["STALE"])


class Parts(unittest.TestCase):
    def test_test_sources(self):
        src = "import x\n\ntest('one', async () => {\n a\n});\ntest.skip(\"two\", () => {});\n"
        b = inspector.test_sources(src)
        self.assertEqual(sorted(b), ["", "one", "two"])
        self.assertIn("a\n", b["one"])

    def test_the_rubric_names_its_criteria(self):
        crit = inspector.criteria(home.doctrine("inspector", "rubric-wcag.md"))
        self.assertEqual(len(crit), 10)
        self.assertIn("2.4.7", crit)
        self.assertEqual(inspector.criteria("# mine\nlook at the logo"), set())

    def test_validate(self):
        good = {"verdict": "findings", "summary": "s", "findings": [
            {"test": "a › pay", "frame": "t01-001.jpeg", "finding": "no ring", "element": "Pay · button",
             "judgement": "fails", "criterion": "2.4.7 Focus Visible", "severity": "high", "confidence": "high"}]}
        names, titles, crit = {"t01-001.jpeg"}, {"a › pay"}, {"2.4.7"}
        self.assertIsNone(inspector.validate(json.loads(json.dumps(good)), names, titles, crit))
        bad = json.loads(json.dumps(good)); bad["findings"][0]["criterion"] = "2.4.13"
        self.assertIn("rubric's criteria", inspector.validate(bad, names, titles, crit))
        other = json.loads(json.dumps(good)); other["findings"][0].update(judgement="other", criterion="2.4.13")
        self.assertIsNone(inspector.validate(other, names, titles, crit))
        self.assertEqual(other["findings"][0]["criterion"], "none")
        short = json.loads(json.dumps(good)); short["findings"][0]["test"] = "pay"
        self.assertIsNone(inspector.validate(short, names, titles, crit))
        self.assertEqual(short["findings"][0]["test"], "a › pay", "a unique short title is normalised")
        frame = json.loads(json.dumps(good)); frame["findings"][0]["frame"] = "t09.png"
        self.assertIn("not in the frame list", inspector.validate(frame, names, titles, crit))
        self.assertIn("contradicts", inspector.validate(dict(good, verdict="seen-ok"), names, titles, crit))


class Unit(Fixture):
    def setUp(self):
        super().setUp()
        (self.repo / "e2e").mkdir()
        (self.repo / "playwright.config.js").write_text("export default { use: {} };\n")
        (self.repo / "e2e" / "pay.spec.js").write_text("import { test } from '@playwright/test';\n"
                                                      "test('the pay button shows focus', async () => {});\n"
                                                      "test('the menu opens', async () => {});\n")
        subprocess.run(["git", "-C", str(self.repo), "add", "."], check=True)
        subprocess.run(["git", "-C", str(self.repo), "commit", "-q", "-m", "ui tests"], check=True)
        os.environ["FAKE_PW_LOG"] = str(self.state.parent / "pw.json")

    def tearDown(self):
        subprocess.run(["git", "-C", str(self.repo), "worktree", "prune"], capture_output=True)
        super().tearDown()

    def config(self):
        for k, v in (("tests", "e2e/**/*.spec.js"), ("port_env", "APP_PORT"), ("port", "4180"),
                     ("command", f"{sys.executable} {HERE / 'fake_playwright.py'}")):
            self.assertEqual(cli.main(["inspect", "config", k, v, "-p", "demo"]), 0)

    def test_refuses_until_it_has_a_port_of_its_own(self):
        self.assertEqual(cli.main(["inspect", "config", "tests", "e2e/**/*.spec.js", "-p", "demo"]), 0)
        self.assertEqual(cli.main(["inspect", "-p", "demo"]), 2)

    def test_one_look_fills_the_box_and_a_release_makes_a_ticket(self):
        self.config()
        self.assertEqual(cli.main(["inspect", "-p", "demo", "--dry-run"]), 0)
        self.flag("judge-bad-once")
        self.assertEqual(cli.main(["inspect", "-p", "demo"]), 0)
        p = home.resolve_project("demo")
        rec = json.loads((box.idir(p) / "units.jsonl").read_text().splitlines()[-1])
        self.assertEqual((rec["outcome"], rec["verdict"], rec["findings"]), ("judged", "findings", 1))
        self.assertEqual(len(rec["phases"]["judge"]["calls"]), 2, "one call, and one reconsideration in its session")
        self.assertIsNotNone(rec["phases"]["judge"]["calls"][1]["resumed"])
        pw = json.loads(Path(os.environ["FAKE_PW_LOG"]).read_text())
        self.assertEqual(pw["port"], "4180", "Playwright runs on the inspector's own port")
        self.assertTrue(pw["cwd"].endswith("inspect/work"), "in its own worktree")
        self.assertIn("--config=hearthwork.inspect.config.mjs", pw["args"])
        r = box.load(p)["reports"]["e2e/pay.spec.js"]
        self.assertEqual(r["state"], "open")
        self.assertTrue(Path(r["findings"][0]["frame"]).exists())
        self.assertEqual(r["findings"][0]["criterion"], "2.4.7")
        judge = [c for c in self.calls() if "inspector" in (c.get("policy") or "")]
        self.assertTrue(all(json.loads(c["policy"])["mode"] == "inspector" for c in judge))
        self.assertIn("Read", judge[0]["argv"][judge[0]["argv"].index("--tools") + 1])
        self.assertEqual(cli.main(["inspect", "-p", "demo"]), 0, "nothing due: the file is current")
        self.assertEqual(cli.main(["release", "pay", "--ticket", "UI-1", "-p", "demo"]), 0)
        self.assertIn("No focus ring on the Pay button", (p.dir / "tickets" / "UI-1" / "ticket.md").read_text())
        self.assertEqual(box.load(p)["reports"]["e2e/pay.spec.js"]["state"], "released")
        page = (Path(os.environ["HEARTHWORK_HOME"]) / "worklog.html").read_text()
        self.assertIn("Inspector", page)

    def test_a_released_ticket_is_worked_as_visual(self):
        self.config()
        self.assertEqual(cli.main(["inspect", "-p", "demo"]), 0)
        self.assertEqual(cli.main(["release", "pay", "--ticket", "UI-1", "-p", "demo"]), 0)
        self.assertEqual(cli.main(["ticket", "use", "UI-1", "-p", "demo"]), 0)
        self.flag("visual")
        (self.state / "visual").write_text("e2e/pay.spec.js")
        self.assertEqual(cli.main(["run", "-p", "demo"]), 0)
        p = home.resolve_project("demo")
        brief = (self.state / "plan-prompt.txt").read_text()
        self.assertIn("RELEASED FROM THE INSPECTOR", brief)
        self.assertIn(".hearthwork-scratch/released/pay/", brief)
        self.assertTrue(list((self.repo / ".hearthwork-scratch" / "released" / "pay").iterdir()), "the cited frames were copied")
        from hearthwork.records import Ticket
        t = Ticket(p, "UI-1")
        chain = json.loads(t.path("chain.json").read_text())
        self.assertEqual((chain["mode"], chain["sighting"], chain["sighting_confidence"], chain["released_file"]),
                         ("VISUAL", "still drawn", "high", "e2e/pay.spec.js"))
        self.assertIn("VISUAL SIGHTING (read by the program): still drawn, confidence high: a fix may follow",
                      (t.unit_dir(1) / "facts.md").read_text())


if __name__ == "__main__":
    unittest.main()
