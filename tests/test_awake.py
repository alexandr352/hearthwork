import os
import stat
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from hearthwork.awake import Awake  # noqa: E402

FAKE = """#!/bin/sh
echo "$0 $*" >> "$AWAKE_LOG"
exec sleep 60
"""


class AwakeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        for name in ("caffeinate", "systemd-inhibit"):
            f = d / name
            f.write_text(FAKE)
            f.chmod(f.stat().st_mode | stat.S_IEXEC)
        self.log = d / "awake.log"
        self.env = {"PATH": f"{d}:{os.environ['PATH']}", "AWAKE_LOG": str(self.log)}
        self.saved = {k: os.environ.get(k) for k in (*self.env, "HEARTHWORK_NO_AWAKE")}
        os.environ.update(self.env)
        os.environ.pop("HEARTHWORK_NO_AWAKE", None)

    def tearDown(self):
        for k, v in self.saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self.tmp.cleanup()

    def wait_log(self):
        for _ in range(50):
            if self.log.exists() and self.log.read_text().strip():
                return self.log.read_text()
            time.sleep(0.05)
        return ""

    def test_mac_holds_and_releases(self):
        a = Awake(system="Darwin")
        self.assertEqual(a.command(), ["caffeinate", "-i", "-w", str(os.getpid())])
        with a:
            self.assertTrue(a.holding)
            self.assertIn(f"-i -w {os.getpid()}", self.wait_log())
        self.assertFalse(a.holding)

    def test_mac_on_ac(self):
        self.assertIn("-s", Awake(system="Darwin", on_ac=True).command())

    def test_linux(self):
        cmd = Awake(system="Linux").command()
        self.assertEqual(cmd[0], "systemd-inhibit")
        self.assertIn(f"--pid={os.getpid()}", cmd)

    def test_counted(self):
        a = Awake(system="Darwin")
        a.acquire()
        first = a.proc
        a.acquire()
        self.assertIs(a.proc, first, "one lock for two holders")
        a.release()
        self.assertTrue(a.holding, "still held by the second holder")
        a.release()
        self.assertFalse(a.holding)

    def test_disabled_and_unknown(self):
        with Awake(system="Darwin", enabled=False) as a:
            self.assertFalse(a.holding)
        self.assertIsNone(Awake(system="Windows").command())
        os.environ["HEARTHWORK_NO_AWAKE"] = "1"
        with Awake(system="Darwin") as a:
            self.assertFalse(a.holding)


if __name__ == "__main__":
    unittest.main()
