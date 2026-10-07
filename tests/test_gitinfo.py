import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from hearthwork import gitinfo  # noqa: E402


def g(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


class BranchFacts(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name)
        for args in (["init", "-q", "-b", "main"], ["config", "user.email", "t@example.com"], ["config", "user.name", "T"]):
            g(self.repo, *args)
        (self.repo / "a.txt").write_text("a\n")
        g(self.repo, "add", ".")
        g(self.repo, "commit", "-q", "-m", "start")

    def tearDown(self):
        self.tmp.cleanup()

    def test_no_unmerged(self):
        facts = gitinfo.plan_facts(self.repo, "main")
        self.assertIn("checkout: branch main", facts)
        self.assertIn("unmerged branches: none", facts)

    def test_unmerged_branch_is_named_until_merged(self):
        g(self.repo, "checkout", "-q", "-b", "T-1-tax")
        (self.repo / "a.txt").write_text("a with tax\n")
        g(self.repo, "commit", "-q", "-am", "Totals include tax")
        g(self.repo, "checkout", "-q", "main")
        facts = gitinfo.plan_facts(self.repo, "main")
        self.assertIn("T-1-tax: 1 commit(s) ahead, last: Totals include tax", facts)
        self.assertIn("NOT in main", facts)
        g(self.repo, "merge", "-q", "--no-ff", "-m", "merge", "T-1-tax")
        self.assertIn("unmerged branches: none", gitinfo.plan_facts(self.repo, "main"))

    def test_missing_trunk(self):
        self.assertIn("(not found)", gitinfo.plan_facts(self.repo, "develop"))
        self.assertEqual(gitinfo.unmerged_branches(self.repo, "develop"), [])


if __name__ == "__main__":
    unittest.main()
