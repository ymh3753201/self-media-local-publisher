from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from support import OUTPUT, ROOT
from self_media_publisher.cli import doctor, main
from self_media_publisher.config import load_config
from self_media_publisher.errors import PublisherError
from self_media_publisher.storage import dump


class ConfigTests(unittest.TestCase):
    def setUp(self):
        OUTPUT.mkdir(parents=True, exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=OUTPUT)
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def local_config(self, data):
        (self.root / "config").mkdir(exist_ok=True)
        (self.root / "config/adapter.local.json").write_text(dump(data))

    def test_no_external_project_is_needed_for_default_config(self):
        cfg = load_config(self.root)
        with patch("self_media_publisher.cli.command_available", return_value=True):
            self.assertEqual(doctor(cfg)["status"], "ready")
        self.assertIsNone(cfg["hermes_profile_dir"])

    def test_invalid_and_unsafe_configuration_is_rejected(self):
        for config in [{"runtime_dir":"../outside"},{"final_publish":"automatic"},{"subtitle_min_coverage":0},{"subtitle_min_coverage":True},{"publisher_agent_dir":"old"},{"mode":"hermes_read_only"}]:
            with self.subTest(config=config):
                self.local_config(config)
                with self.assertRaises(PublisherError):
                    load_config(self.root)

    def test_browser_missing_does_not_block_local_planning(self):
        cfg = load_config(self.root)
        with patch("self_media_publisher.cli.command_available", side_effect=lambda name: name == "ffprobe"):
            self.assertEqual(doctor(cfg)["status"], "ready")
            self.assertEqual(doctor(cfg, browser=True)["status"], "dependency_missing")

    def test_symlinked_runtime_is_rejected(self):
        outside = self.root / "outside"
        outside.mkdir()
        try:
            (self.root / ".publisher-runs").symlink_to(outside, target_is_directory=True)
        except OSError:
            self.skipTest("symlink unavailable")
        with self.assertRaises(PublisherError):
            load_config(self.root)

    def test_hermes_compatibility_reads_only_rule_hashes(self):
        from self_media_publisher.context import snapshot
        profile = self.root / "hermes-fixture"
        skill = profile / "skills/productivity/social-video-publisher/SKILL.md"
        skill.parent.mkdir(parents=True)
        skill.write_text("publish rule")
        (profile / "SOUL.md").write_text("read only")
        (profile / "profile.yaml").write_text("not-for-reading")
        self.local_config({"mode":"hermes_read_only","hermes_profile_dir":str(profile)})
        data = snapshot(load_config(self.root))
        self.assertEqual(len(data["hermes_context"]["files"]), 2)
        self.assertNotIn("not-for-reading", dump(data))

    def test_source_cli_runs_from_a_different_directory(self):
        result = subprocess.run([sys.executable, str(ROOT/"scripts/publisherctl.py"), "--project-root", str(self.root), "context", "--json"], cwd=self.root, capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('"mode": "standalone"', result.stdout)

    def test_cli_does_not_offer_a_publish_or_cookie_command(self):
        from self_media_publisher.cli import parser
        for name in ("publish", "login", "export-cookies"):
            with self.subTest(name=name), patch("sys.stderr"), self.assertRaises(SystemExit):
                parser().parse_args([name])
