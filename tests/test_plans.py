import copy
import os
from unittest.mock import patch

from support import MediaCase
from self_media_publisher.context import snapshot
from self_media_publisher.errors import PublisherError
from self_media_publisher.plans import create_plan, seal_plan, verify_plan
from self_media_publisher.storage import read_json


class PlanTests(MediaCase):
    def test_end_to_end_local_plan_is_independent(self):
        path = self.sealed()
        result = verify_plan(self.config, str(path))
        self.assertEqual(result["status"], "ready_for_review")
        plan = read_json(path)
        self.assertEqual(plan["context"]["mode"], "standalone")
        self.assertEqual(plan["context"]["hermes_context"]["files"], [])
        self.assertNotIn("publisher_agent_dir", plan["context"]["configuration"])

    def test_initial_plan_cannot_skip_review_and_seal(self):
        path = self.make_plan()
        self.assertEqual(read_json(path)["status"], "draft")
        self.assertEqual(verify_plan(self.config, str(path))["status"], "replan_required")

    def test_forbidden_content_stays_unsealed(self):
        subtitle = self.root / "bad.srt"
        subtitle.write_text("1\n00:00:00,000 --> 00:00:04,000\n保证赚钱的测试内容\n", encoding="utf-8")
        path = self.make_plan("douyin", subtitle)
        self.assertFalse(read_json(path)["validations"]["douyin"]["ok"])
        with self.assertRaises(PublisherError) as error:
            seal_plan(self.config, str(path), content_reviewed=True, covers_reviewed=True)
        self.assertEqual(error.exception.status, "validation_failed")

    def test_video_path_swap_is_blocked(self):
        path = self.sealed()
        self.change(path, lambda p: p["materials"].update(video_path=str(self.alt)))
        with self.assertRaises(PublisherError) as error:
            seal_plan(self.config, str(path), content_reviewed=True, covers_reviewed=True)
        self.assertEqual(error.exception.status, "material_changed")

    def test_video_disguised_as_a_cover_is_rejected(self):
        from self_media_publisher.media import inspect_inputs
        image = self.root / "fake.png"
        image.write_bytes(self.video.read_bytes())
        with self.assertRaises(PublisherError) as error:
            inspect_inputs(str(self.video), str(self.subtitle), [str(image)])
        self.assertEqual(error.exception.status, "invalid_cover")

    def test_empty_asset_records_are_blocked(self):
        path = self.sealed()
        (path.parent / "assets.json").write_text('{"records":{}}')
        self.assertEqual(verify_plan(self.config, str(path))["status"], "replan_required")

    def test_changed_source_bytes_are_blocked(self):
        local_subtitle = self.root / "local.srt"
        local_subtitle.write_bytes(self.subtitle.read_bytes())
        path = self.sealed(subtitle=local_subtitle)
        local_subtitle.write_text("changed")
        result = verify_plan(self.config, str(path))
        self.assertEqual(result["status"], "replan_required")
        self.assertEqual(result["issues"][0]["kind"], "material_changed")

    def test_twenty_four_character_wechat_title_cannot_be_resealed(self):
        path = self.sealed()
        self.change(path, lambda p: p["platform_metadata"]["wechat_channels"].update(title="视频号短标题测试" * 3))
        with self.assertRaises(PublisherError) as error:
            seal_plan(self.config, str(path), content_reviewed=True, covers_reviewed=True)
        self.assertEqual(error.exception.status, "validation_failed")

    def test_changed_confirmation_phrase_is_rejected(self):
        path = self.sealed()
        self.change(path, lambda p: p["seal"].update(review_approval_phrase="old approval"))
        self.assertEqual(verify_plan(self.config, str(path))["status"], "replan_required")

    def test_missing_human_content_or_cover_review_is_blocked(self):
        path = self.make_plan()
        for flags in ({}, {"content_reviewed":True}, {"covers_reviewed":True}):
            with self.subTest(flags=flags), self.assertRaises(PublisherError):
                seal_plan(self.config, str(path), **flags)

    def test_sparse_subtitles_require_an_explanation(self):
        subtitle = self.root / "sparse.srt"
        subtitle.write_text("1\n00:00:03,900 --> 00:00:04,000\n植物观察\n", encoding="utf-8")
        path = self.make_plan(subtitle=subtitle)
        with self.assertRaises(PublisherError) as error:
            seal_plan(self.config, str(path), content_reviewed=True, covers_reviewed=True)
        self.assertEqual(error.exception.status, "subtitle_review_required")
        seal_plan(self.config, str(path), content_reviewed=True, covers_reviewed=True, subtitle_note="已核对：前段无口播，仅展示植物。")
        self.assertEqual(verify_plan(self.config, str(path))["status"], "ready_for_review")

    def test_non_ai_bilibili_category_and_youtube_audience_are_explicit(self):
        path = self.make_plan(None)
        with self.assertRaises(PublisherError):
            seal_plan(self.config, str(path), content_reviewed=True, covers_reviewed=True)
        self.change(path, lambda p: (p["platform_metadata"]["bilibili"].update(category="生活 / 日常"), p["platform_metadata"]["youtube"].update(audience="not_made_for_kids")))
        seal_plan(self.config, str(path), content_reviewed=True, covers_reviewed=True)
        result = read_json(path)
        self.assertEqual(result["codex_adapter"]["platform_ui_contracts"]["bilibili"]["category_ui_label"], "生活 / 日常")
        self.assertEqual(verify_plan(self.config, str(path))["status"], "ready_for_review")

    def test_unknown_originality_does_not_imply_no_ai(self):
        path = self.make_plan(extra=["--original"])
        declarations = read_json(path)["content_declarations"]
        self.assertEqual(declarations["originality_basis"], "user_statement")
        self.assertEqual(declarations["ai_generated_content"], "unspecified")

    def test_preview_tampering_and_incomplete_bundle_are_detected(self):
        path = self.sealed()
        (path.parent / "publish_preview.md").write_text("wrong preview")
        self.assertEqual(verify_plan(self.config, str(path))["issues"][0]["kind"], "preview_changed")
        seal_plan(self.config, str(path), content_reviewed=True, covers_reviewed=True)
        (path.parent / "manifest.json").write_text("{}")
        self.assertEqual(verify_plan(self.config, str(path))["issues"][0]["kind"], "incomplete_bundle")

    def test_interrupted_write_never_looks_committed(self):
        from self_media_publisher.plans import atomic_write
        path = self.sealed()
        self.change(path, lambda p: p["platform_metadata"]["wechat_channels"].update(description="字幕摘录：植物观察。"))
        def fail_manifest(target, text):
            if target.name == "manifest.json":
                raise OSError("simulated disk failure")
            atomic_write(target, text)
        with patch("self_media_publisher.plans.atomic_write", side_effect=fail_manifest), self.assertRaises(OSError):
            seal_plan(self.config, str(path), content_reviewed=True, covers_reviewed=True)
        self.assertEqual(verify_plan(self.config, str(path))["issues"][0]["kind"], "incomplete_bundle")

    def test_code_or_config_change_invalidates_unstarted_plan(self):
        path = self.sealed()
        changed = dict(self.config, subtitle_min_coverage=0.8)
        self.assertEqual(verify_plan(changed, str(path))["issues"][0]["kind"], "context_changed")

    def test_embedded_context_cannot_lower_subtitle_threshold(self):
        path = self.make_plan()
        self.change(path, lambda p: p["context"]["configuration"].update(subtitle_min_coverage=0.001))
        with self.assertRaises(PublisherError) as error:
            seal_plan(self.config, str(path), content_reviewed=True, covers_reviewed=True)
        self.assertEqual(error.exception.status, "context_changed")

    def test_mtime_only_change_does_not_change_rule_context(self):
        doc = self.root / "AGENTS.md"
        doc.write_text("local rules")
        before = snapshot(self.config)
        os.utime(doc, (1000000, 1000000))
        self.assertEqual(before, snapshot(self.config))

    def test_same_process_rapid_plans_have_unique_ids(self):
        self.assertNotEqual(self.make_plan().parent.name, self.make_plan().parent.name)

    def test_legacy_plan_is_not_silently_migrated(self):
        path = self.make_plan()
        self.change(path, lambda p: p.update(schema_version="1.0"))
        with self.assertRaises(PublisherError) as error:
            verify_plan(self.config, str(path))
        self.assertEqual(error.exception.status, "legacy_plan_requires_replan")

    def test_symlinked_output_cannot_overwrite_another_file(self):
        path = self.make_plan()
        sentinel = self.root / "keep.md"
        sentinel.write_text("keep")
        target = path.parent / "publish_preview.md"
        target.unlink()
        try:
            target.symlink_to(sentinel)
        except OSError:
            self.skipTest("symlink creation unavailable")
        with self.assertRaises(PublisherError):
            seal_plan(self.config, str(path), content_reviewed=True, covers_reviewed=True)
        self.assertEqual(sentinel.read_text(), "keep")
