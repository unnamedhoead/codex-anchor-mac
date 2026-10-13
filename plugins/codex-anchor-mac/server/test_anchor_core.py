import json
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import anchor_core as core


class TimeMath(unittest.TestCase):
    def test_system_zone_is_identity(self):
        self.assertEqual(core.to_local(4, 30, core.system_timezone()), (4, 30))

    def test_unknown_zone_does_not_raise(self):
        self.assertEqual(core.to_local(4, 30, "Nowhere/Nothing"), (4, 30))

    def test_wake_wraps_past_midnight(self):
        self.assertEqual(core.wake_time(0, 1), (23, 58))


class Timezones(unittest.TestCase):
    def test_one_entry_per_rule_set_not_per_zone(self):
        names = [c["name"] for c in core.timezone_choices()]
        self.assertLess(len(names), 100)
        self.assertGreater(len(names), 40)

    def test_system_zone_is_always_offered(self):
        names = [c["name"] for c in core.timezone_choices()]
        self.assertIn(core.system_timezone(), names)


class Home(unittest.TestCase):
    def test_paths_live_under_dot_codex_anchor(self):
        self.assertEqual(core.HOME_DIR, pathlib.Path.home() / ".codex-anchor")
        self.assertEqual(core.LOG.parent, core.HOME_DIR)
        self.assertEqual(core.CONFIG.parent, core.HOME_DIR)


class Config(unittest.TestCase):
    def setUp(self):
        self.saved = core.CONFIG.read_bytes() if core.CONFIG.exists() else None

    def tearDown(self):
        if self.saved is None:
            core.CONFIG.unlink(missing_ok=True)
        else:
            core.CONFIG.write_bytes(self.saved)

    def test_corrupt_config_falls_back_instead_of_raising(self):
        # Review Focus 5: a truncated write must not take the server down.
        core.CONFIG.parent.mkdir(parents=True, exist_ok=True)
        core.CONFIG.write_text('{"timezone": "Asia/Sh', encoding="utf-8")
        cfg = core.load_config()
        self.assertEqual(cfg["hour"], 4)
        self.assertTrue(cfg["timezone"])
        self.assertIn("_error", cfg)

    def test_null_timezone_resolves_to_the_system_zone(self):
        core.CONFIG.parent.mkdir(parents=True, exist_ok=True)
        core.CONFIG.write_text(
            json.dumps({"timezone": None, "hour": 6, "minute": 15}),
            encoding="utf-8")
        cfg = core.load_config()
        self.assertEqual(cfg["timezone"], core.system_timezone())
        self.assertEqual((cfg["hour"], cfg["minute"]), (6, 15))

    def test_save_creates_the_home_directory(self):
        core.save_config({"timezone": "Asia/Shanghai", "hour": 4, "minute": 30})
        self.assertTrue(core.CONFIG.exists())


if __name__ == "__main__":
    unittest.main()
