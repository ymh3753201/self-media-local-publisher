from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from self_media_publisher.cli import parser
from self_media_publisher.config import load_config
from self_media_publisher.plans import create_plan, seal_plan
from self_media_publisher.storage import dump, read_json

OUTPUT = ROOT / ".publisher-runs" / "tests"


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "integration tests require FFmpeg")
class MediaCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        OUTPUT.mkdir(parents=True, exist_ok=True)
        cls.fixture_tmp = tempfile.TemporaryDirectory(dir=OUTPUT)
        cls.fixtures = Path(cls.fixture_tmp.name)

        def ffmpeg(*args):
            subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args], check=True, capture_output=True, timeout=30)

        cls.video = cls.fixtures / "video.mp4"
        ffmpeg("-f", "lavfi", "-i", "color=c=navy:s=160x90:r=5:d=4", "-f", "lavfi", "-i", "anullsrc=r=8000:cl=mono", "-t", "4", "-c:v", "libx264", "-c:a", "aac", "-pix_fmt", "yuv420p", str(cls.video))
        cls.alt = cls.fixtures / "other.mp4"
        ffmpeg("-f", "lavfi", "-i", "color=c=green:s=160x90:r=5:d=4", "-t", "4", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(cls.alt))
        cls.subtitle = cls.fixtures / "subtitle.srt"
        cls.subtitle.write_text("1\n00:00:00,000 --> 00:00:02,000\n今天记录花园里的植物生长。\n\n2\n00:00:02,000 --> 00:00:04,000\n观察叶片颜色和土壤湿度。\n", encoding="utf-8")
        cls.covers = []
        for size in ("160x90", "120x90", "90x120"):
            target = cls.fixtures / f"cover-{size}.png"
            ffmpeg("-f", "lavfi", "-i", f"color=c=navy:s={size}", "-frames:v", "1", str(target))
            cls.covers.append(target)

    @classmethod
    def tearDownClass(cls):
        cls.fixture_tmp.cleanup()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=OUTPUT)
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.config = load_config(self.root)

    def make_plan(self, platform="wechat_channels", subtitle=None, extra=None):
        args = ["plan", "--video", str(self.video), "--subtitle", str(subtitle or self.subtitle), "--cover-title", "植物观察"]
        if platform:
            args.extend(["--platform", platform])
        for cover in self.covers:
            args.extend(["--cover", str(cover)])
        args.extend(extra or [])
        result = create_plan(self.config, parser().parse_args(args))
        return Path(result["plan_path"])

    def sealed(self, platform="wechat_channels", **kwargs):
        path = self.make_plan(platform, **kwargs)
        seal_plan(self.config, str(path), content_reviewed=True, covers_reviewed=True)
        return path

    def change(self, path, mutation):
        plan = read_json(path)
        mutation(plan)
        path.write_text(dump(plan), encoding="utf-8")
