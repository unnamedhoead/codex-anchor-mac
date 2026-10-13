import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

SCRIPT = pathlib.Path(__file__).resolve().parent / "register_mcp.py"


def fake_home(versions=("0.1.0",)):
    """A CODEX_HOME with the plugin 'installed'.

    The tests must not depend on whether this machine happens to have the
    plugin installed; CI does not, and a test that only passes on the
    author's laptop is not a test.
    """
    home = tempfile.mkdtemp()
    for v in versions:
        d = pathlib.Path(home, "plugins", "cache", "codex-anchor-mac",
                         "codex-anchor-mac", v, "server")
        d.mkdir(parents=True)
        (d / "anchor_mcp.py").write_text("", encoding="utf-8")
    return home


def run(codex_home, args=()):
    env = {**os.environ, "ANCHOR_REGISTER_DRY_RUN": "1"}
    if codex_home is None:
        env["CODEX_HOME"] = "/nonexistent/.codex"
    else:
        env["CODEX_HOME"] = codex_home
    return subprocess.run([sys.executable, str(SCRIPT), *args],
                          capture_output=True, text=True, timeout=30, env=env)


class Resolve(unittest.TestCase):
    def test_registers_the_installed_server_by_absolute_path(self):
        p = run(fake_home())
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("codex mcp add codex_anchor", p.stdout)
        self.assertIn("server/anchor_mcp.py", p.stdout)
        self.assertNotIn("${PLUGIN_ROOT}", p.stdout,
                         "PLUGIN_ROOT must be resolved, not passed through")

    def test_picks_the_newest_version_numerically(self):
        # A string sort puts 0.10.0 below 0.9.0, which would register a path
        # that an upgrade has already replaced.
        p = run(fake_home(("0.9.0", "0.10.0")))
        self.assertIn("/0.10.0/server", p.stdout)
        self.assertNotIn("/0.9.0/server", p.stdout)

    def test_removes_a_stale_registration_before_adding(self):
        p = run(fake_home())
        self.assertLess(p.stdout.index("codex mcp remove"),
                        p.stdout.index("codex mcp add"),
                        "must retire the old entry first, or add is a no-op")

    def test_reports_clearly_when_the_plugin_is_not_installed(self):
        p = run(None)
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("codex plugin add", p.stderr + p.stdout)


if __name__ == "__main__":
    unittest.main()
