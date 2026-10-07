"""Keep the machine awake while work is in flight, and only then.

A laptop that sleeps mid-unit drops the Claude call; the loop recovers (a survey, a
judgement), but the half-unit is wasted. So while a unit runs or the spirit answers,
hearthwork holds the operating system's own "do not idle-sleep" lock:

  macOS   caffeinate -i -w <pid>      (add -s to stay awake on mains power too)
  Linux   systemd-inhibit --what=idle:sleep, held until this process exits

The lock is a child process tied to ours, so it is released when the work ends, and by
the system if hearthwork crashes. The screen may still turn off and lock. Closing a
laptop's lid still sleeps it: nothing here overrides that.
"""

import os
import platform
import shutil
import subprocess
import threading


class Awake:
    """A counted hold: the lock is taken by the first holder and released by the last."""

    def __init__(self, enabled=True, on_ac=False, system=None, why="hearthwork is working"):
        self.enabled = enabled and not os.environ.get("HEARTHWORK_NO_AWAKE")
        self.on_ac = on_ac
        self.system = system or platform.system()
        self.why = why
        self.count = 0
        self.proc = None
        self.lock = threading.Lock()

    def command(self):
        pid = str(os.getpid())
        if self.system == "Darwin" and shutil.which("caffeinate"):
            return ["caffeinate", "-i"] + (["-s"] if self.on_ac else []) + ["-w", pid]
        if self.system == "Linux" and shutil.which("systemd-inhibit") and shutil.which("tail"):
            return ["systemd-inhibit", "--what=idle:sleep", "--who=hearthwork", f"--why={self.why}",
                    "--mode=block", "tail", f"--pid={pid}", "-f", "/dev/null"]
        return None

    def acquire(self):
        with self.lock:
            self.count += 1
            if self.count == 1 and self.enabled and self.proc is None:
                cmd = self.command()
                if cmd:
                    try:
                        self.proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                                     stderr=subprocess.DEVNULL)
                    except OSError:
                        self.proc = None

    def release(self):
        with self.lock:
            self.count = max(0, self.count - 1)
            if self.count == 0 and self.proc is not None:
                self.proc.terminate()
                try:
                    self.proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.proc.kill()
                self.proc = None

    @property
    def holding(self):
        return self.proc is not None and self.proc.poll() is None

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, *exc):
        self.release()


def from_config(cfg, why="hearthwork is working"):
    a = cfg.get("awake") or {}
    return Awake(enabled=bool(a.get("enabled", True)), on_ac=bool(a.get("on_ac", False)), why=why)
