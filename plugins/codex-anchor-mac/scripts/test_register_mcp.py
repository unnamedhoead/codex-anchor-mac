import os
import pathlib
import subprocess
import sys
import unittest

SCRIPT = pathlib.Path(__file__).resolve().parent / "register_mcp.py"


def run(extra_env=None, args=()):
    env = {**os.environ, "ANCHOR_REGISTER_DRY_RUN": "1"}
    env.update(extra_env or {})
    return subprocess.run([sys.executable, str(SCRIPT), *args],
                          capture_output=True, text=True, timeout=30, env=env)


class Resolve(unittest.TestCase):
    def test_registers_the_installed_server_by_absolute_path(self):
        p = run()
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("codex mcp add codex_anchor", p.stdout)
        self.assertIn("server/anchor_mcp.py", p.stdout)
        self.assertNotIn("${PLUGIN_ROOT}", p.stdout,
                         "PLUGIN_ROOT must be resolved, not passed through")

    def test_uses_the_newest_installed_version(self):
        # The cache is scoped by version; registering an old path is how the
        # registration silently rots after a plugin upgrade.
        p = run()
        self.assertRegex(p.stdout, r"codex-anchor-mac/\d+\.\d+\.\d+/server")

    def test_removes_a_stale_registration_before_adding(self):
        p = run()
        self.assertLess(p.stdout.index("codex mcp remove"),
                        p.stdout.index("codex mcp add"),
                        "must retire the old entry first, or add is a no-op")

    def test_reports_clearly_when_the_plugin_is_not_installed(self):
        p = run({"CODEX_HOME": "/nonexistent/.codex"})
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("codex plugin add", p.stderr + p.stdout)


if __name__ == "__main__":
    unittest.main()
