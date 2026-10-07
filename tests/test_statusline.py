import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from test_loop import Fixture  # noqa: E402
from hearthwork import statusline  # noqa: E402
from hearthwork.claude import read_usage  # noqa: E402

SNAP = {"workspace": {"current_dir": None}, "rate_limits": {
    "five_hour": {"used_percentage": 23.5, "resets_at": 1791397800},
    "seven_day": {"used_percentage": 41.2, "resets_at": 1791954000}}}


class StatusLine(Fixture):
    def say(self, data):
        buf = io.StringIO()
        with redirect_stdout(buf):
            statusline.run(io.StringIO(json.dumps(data) if isinstance(data, dict) else data))
        return buf.getvalue().strip()

    def test_keeps_the_documented_reading_and_shows_the_work(self):
        snap = dict(SNAP, workspace={"current_dir": str(self.repo)})
        text = self.say(snap)
        u = read_usage()
        self.assertAlmostEqual(u["five_hour"]["used"], 0.235)
        self.assertEqual(u["source"], "statusline")
        self.assertIn("5h 24%", text)
        self.assertIn("week 41%", text)
        self.assertIn("demo: T-1", text, "inside a project's repo it names the active ticket")

    def test_never_fails(self):
        self.assertTrue(self.say("not json").startswith("hearthwork"))
        self.assertTrue(self.say({}).startswith("hearthwork"))

    def test_install_is_careful(self):
        with tempfile.TemporaryDirectory() as fake:
            old = os.environ["HOME"]
            os.environ["HOME"] = fake
            try:
                ok, msg = statusline.install()
                self.assertTrue(ok, msg)
                s = json.loads((Path(fake) / ".claude" / "settings.json").read_text())
                self.assertTrue(s["statusLine"]["command"].endswith(" statusline"))
                ok, msg = statusline.install()
                self.assertIn("already installed", msg)
                (Path(fake) / ".claude" / "settings.json").write_text(json.dumps(
                    {"model": "opus", "statusLine": {"type": "command", "command": "~/my-line.sh"}}))
                ok, msg = statusline.install()
                self.assertFalse(ok)
                self.assertIn("left alone", msg)
                s = json.loads((Path(fake) / ".claude" / "settings.json").read_text())
                self.assertEqual(s["statusLine"]["command"], "~/my-line.sh", "a person's own status line is kept")
                (Path(fake) / ".claude" / "settings.json").write_text(json.dumps({"model": "opus"}))
                ok, _ = statusline.install()
                s = json.loads((Path(fake) / ".claude" / "settings.json").read_text())
                self.assertEqual(s["model"], "opus", "other settings are kept")
                self.assertTrue(list((Path(fake) / ".claude").glob("settings.json.bak-*")), "a backup is made")
            finally:
                os.environ["HOME"] = old


del Fixture

if __name__ == "__main__":
    unittest.main()
