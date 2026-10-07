import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from hearthwork import server  # noqa: E402

ANSWER = """**What changed:** an item with no `qty` counts as 1.

- **Fix:** `cart.py:14` reads `i.get("qty", 1)`.
- **Tests:** 7 new tests.

| Unit | Cost |
|---|---:|
| 1 | $0.21 |

1. first
2. second"""


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class ChatMarkdown(unittest.TestCase):
    """The chat's markdown renderer, tested as the browser receives it."""

    def render(self, text):
        js = server.CHAT_UI
        js = js[js.index("function hwMarkdown"):js.index("window.hwMarkdown")]
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as f:
            f.write(js + "process.stdout.write(hwMarkdown(JSON.parse(process.argv[1])));")
        try:
            return subprocess.run(["node", f.name, json.dumps(text)], capture_output=True, text=True, check=True).stdout
        finally:
            Path(f.name).unlink()

    def test_formats(self):
        h = self.render(ANSWER)
        self.assertIn("<b>What changed:</b>", h)
        self.assertIn("<code>cart.py:14</code>", h)
        self.assertIn("<ul><li><b>Fix:</b>", h)
        self.assertIn("<table class=md>", h)
        self.assertNotIn("---", h, "the separator row is not a row")
        self.assertIn("<ol><li>first</li>", h)

    def test_escapes_before_formatting(self):
        self.assertEqual(self.render("<img src=x onerror=alert(1)>"), "<p>&lt;img src=x onerror=alert(1)&gt;</p>")
        self.assertNotIn("<script", self.render("**<script>x</script>**"))


if __name__ == "__main__":
    unittest.main()
