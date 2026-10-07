import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from test_loop import Fixture  # noqa: E402
from hearthwork import atlas, cli  # noqa: E402


class AtlasTest(Fixture):
    def atlas_text(self):
        return (self.p.dir / "atlas.md").read_text()

    def test_draft_on_a_new_project(self):
        self.assertTrue(atlas.is_seed(self.atlas_text()))
        self.assertEqual(cli.main(["atlas", "-p", "demo"]), 0)
        text = self.atlas_text()
        self.assertIn("python3 -m unittest test_cart", text)
        self.assertIn("## Questions for the person", text)
        call = [c for c in self.calls() if c["prompt"].startswith("ATLAS BUILD")][0]
        self.assertEqual(call["cwd"], str(self.repo), "the executor reads the repository")
        self.assertTrue((self.p.dir / "atlas-runs.jsonl").exists())

    def test_broken_draft_is_fixed_in_the_same_session(self):
        self.flag("atlas-bad-once")
        self.assertEqual(cli.main(["atlas", "-p", "demo"]), 0)
        fixes = [c for c in self.calls() if c["prompt"].startswith("DEVIATION: return the atlas")]
        self.assertEqual(len(fixes), 1)
        self.assertIsNotNone(fixes[0]["resume"])
        self.assertIn("# Atlas", self.atlas_text())

    def test_edited_atlas_needs_force_and_is_kept(self):
        (self.p.dir / "atlas.md").write_text("# Atlas\n\nmy own notes\n")
        self.assertEqual(cli.main(["atlas", "-p", "demo"]), 2)
        self.assertIn("my own notes", self.atlas_text())
        self.assertEqual(cli.main(["atlas", "-p", "demo", "--force"]), 0)
        backups = list(self.p.dir.glob("atlas.2*.md"))
        self.assertEqual(len(backups), 1)
        self.assertIn("my own notes", backups[0].read_text())

    def test_extract(self):
        self.assertIsNone(atlas.extract("no atlas here"))
        good = "# Atlas\n" + "\n".join(h + "\nx\n" for h in atlas.HEADINGS)
        self.assertIsNotNone(atlas.extract("preamble\n" + good))
        swapped = good.replace("## Traps", "## TEMP").replace("## Conventions", "## Traps").replace("## TEMP", "## Conventions")
        self.assertIsNone(atlas.extract(swapped), "headings out of order")


del Fixture

if __name__ == "__main__":
    unittest.main()
