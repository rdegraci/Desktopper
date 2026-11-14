import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


class CliHelpTest(unittest.TestCase):
    def test_help_prints_usage_and_does_not_touch_appdir(self):
        with tempfile.TemporaryDirectory() as tmp:
            appdir = Path(tmp) / "appdir"
            env = {**os.environ, "DESKTOPPER_APPDIR": str(appdir)}
            proc = subprocess.run(
                [sys.executable, "-m", "app.server", "--help"],
                cwd=REPO, env=env, capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertIn("usage: desktopper", proc.stdout)
            self.assertIn("--help", proc.stdout)
            self.assertIn("Start the Desktopper local web server", proc.stdout)
            self.assertFalse(appdir.exists())


if __name__ == "__main__":
    unittest.main()
