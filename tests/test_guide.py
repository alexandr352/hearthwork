import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from test_loop import Fixture  # noqa: E402
from hearthwork import cli, guide, home  # noqa: E402


class NextStep(Fixture):
    def test_walks_the_stages(self):
        self.assertEqual(guide.next_step()["key"], "atlas", "a project with no atlas")
        cli.main(["atlas", "-p", "demo"])
        self.assertEqual(guide.next_step()["key"], "questions")
        cli.main(["atlas", "-p", "demo", "answer", "1", "none are slow"])
        self.assertEqual(guide.next_step()["key"], "run", "T-1 is active")
        self.flag("plan-halt")
        cli.main(["run", "-p", "demo"])
        self.assertEqual(guide.next_step()["key"], "halt")
        cli.main(["rule", "-p", "demo", "EUR"])
        st = self.p.read_state()
        st["active_ticket"] = None
        self.p.write_state(st)
        self.assertEqual(guide.next_step()["key"], "ticket")

    def test_page_shows_the_step(self):
        from hearthwork import worklog
        page = worklog.render(ui=True)
        self.assertIn("class=nextstep", page)
        self.assertIn("Draft demo", page)
        self.assertIn('data-ask="demo|next|"', page)

    def test_no_project(self):
        empty = Path(self.tmp.name) / "empty-home"
        os.environ["HEARTHWORK_HOME"] = str(empty)
        home.init_home()
        self.assertEqual(guide.next_step()["key"], "project")


del Fixture


class FindRepos(unittest.TestCase):
    def test_finds_repos_and_skips_their_insides(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            for rel in ("a", "group/b", "group/b/vendor/c", "deep/x/y/z/too-deep"):
                (root / rel).mkdir(parents=True)
                subprocess.run(["git", "init", "-q", str(root / rel)], check=True)
            (root / "node_modules" / "pkg").mkdir(parents=True)
            subprocess.run(["git", "init", "-q", str(root / "node_modules" / "pkg")], check=True)
            found = [p for p, _ in guide.find_repos(roots=[root], depth=3)]
            self.assertIn(str(root / "a"), found)
            self.assertIn(str(root / "group" / "b"), found)
            self.assertNotIn(str(root / "group" / "b" / "vendor" / "c"), found, "not inside another repo")
            self.assertNotIn(str(root / "deep" / "x" / "y" / "z" / "too-deep"), found, "depth is bounded")
            self.assertFalse(any("node_modules" in p for p in found))


if __name__ == "__main__":
    unittest.main()
