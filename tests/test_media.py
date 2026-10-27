from pathlib import Path
import tempfile
import unittest
import json
import subprocess
from unittest.mock import patch

from support import OUTPUT
from self_media_publisher.errors import PublisherError
from self_media_publisher.media import classify_ratio, parse_srt, required_ratios, probe


class SubtitleTests(unittest.TestCase):
    def parse(self, text, duration=4):
        OUTPUT.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=OUTPUT) as raw:
            path = Path(raw) / "test.srt"
            path.write_text(text, encoding="utf-8")
            return parse_srt(path, duration)

    def test_sparse_subtitle_does_not_claim_full_coverage(self):
        result = self.parse("1\n00:00:03,900 --> 00:00:04,000\n植物\n")
        self.assertEqual(result["coverage_ratio"], 0.025)
        self.assertEqual(result["last_position_ratio"], 1)

    def test_overlapping_cues_are_not_double_counted(self):
        result = self.parse("1\n00:00:00,000 --> 00:00:03,000\n植物\n\n2\n00:00:02,000 --> 00:00:04,000\n叶片\n")
        self.assertEqual(result["captioned_seconds"], 4)

    def test_invalid_time_or_body_is_rejected(self):
        for text in ("", "只有文字", "1\n00:00:03,000 --> 00:00:01,000\n植物", "1\n00:70:00,000 --> 00:00:04,000\n植物", "1\n00:00:00,000 --> 00:00:05,000\n植物", "1\n00:00:00,000 --> 00:00:04,000", "1\n00:00:00,000 --> 00:00:00,000\n植物", "1\n00:00:00,000 --> 00:00:04,000\n<i></i>"):
            with self.subTest(text=text), self.assertRaises(PublisherError):
                self.parse(text)

    def test_out_of_order_cues_are_rejected(self):
        with self.assertRaises(PublisherError):
            self.parse("1\n00:00:02,000 --> 00:00:03,000\n植物\n\n2\n00:00:00,000 --> 00:00:01,000\n叶片")

    def test_orientation_and_supported_cover_ratios(self):
        self.assertEqual(required_ratios(1080, 1920), ["9:16", "3:4", "4:3"])
        self.assertEqual(required_ratios(1920, 1080), ["16:9", "4:3", "3:4"])
        for dims, expected in [((1080,1920),"9:16"),((1080,1440),"3:4"),((1440,1080),"4:3"),((1920,1080),"16:9"),((1000,1000),None)]:
            self.assertEqual(classify_ratio(*dims), expected)

    def test_phone_video_rotation_is_used_for_cover_orientation(self):
        data = {"streams":[{"codec_type":"video","width":1920,"height":1080,"duration":"4", "side_data_list":[{"rotation":-90}]}]}
        with patch("self_media_publisher.media.subprocess.run", return_value=subprocess.CompletedProcess([],0,json.dumps(data),"")):
            info = probe(Path("fixture.mov"))
        self.assertEqual(required_ratios(info["width"],info["height"]), ["9:16","3:4","4:3"])
