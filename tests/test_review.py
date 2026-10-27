from support import MediaCase
from self_media_publisher.errors import PublisherError
from self_media_publisher.plans import seal_plan, verify_plan
from self_media_publisher.review import bind_space, get_status, record_review, start_review
from self_media_publisher.storage import dump, read_json


class ReviewTests(MediaCase):
    def begin(self):
        path = self.sealed()
        plan = read_json(path)
        start_review(self.config, str(path), plan["seal"]["review_approval_phrase"])
        bind_space(self.config, str(path), "wechat_channels", 10, plan["codex_adapter"]["task_space_prefix"] + "wechat_channels")
        return path, plan

    def evidence(self, path, plan):
        assets = read_json(path.parent / "assets.json")["records"]
        data = {"space_id":10, "browser_backend":"ego", "plan_sha256":plan["seal"]["plan_sha256"], "video_sha256":assets["video"]["sha256"], "cover_sha256":assets["cover:3:4"]["sha256"], "video_uploaded":True, "cover_uploaded":True, "required_fields_readback":True, "stopped_before_publish":True, "handoff":True, "declarations_reviewed":True, "ai_declaration_required":False, "fields":plan["platform_metadata"]["wechat_channels"]}
        evidence = self.root / "evidence.json"
        evidence.write_text(dump(data), encoding="utf-8")
        return evidence

    def test_old_or_wrong_approval_cannot_start_review(self):
        path = self.sealed()
        with self.assertRaises(PublisherError):
            start_review(self.config, str(path), "old")
        self.assertFalse((path.parent / "review.json").exists())

    def test_review_freezes_rules_but_not_mutated_assets(self):
        path, plan = self.begin()
        changed_config = dict(self.config, subtitle_min_coverage=0.9)
        self.assertEqual(verify_plan(changed_config, str(path))["status"], "ready_for_review")
        with self.assertRaises(PublisherError):
            seal_plan(self.config, str(path), content_reviewed=True, covers_reviewed=True)
        self.change(path, lambda p: p["platform_metadata"]["wechat_channels"].update(title="changed"))
        self.assertEqual(verify_plan(self.config, str(path))["status"], "replan_required")

    def test_foreign_space_and_rebinding_are_rejected(self):
        path, plan = self.begin()
        for sid, name in [(11,"publisher:foreign"),(11,plan["codex_adapter"]["task_space_prefix"]+"wechat_channels")]:
            with self.subTest(sid=sid, name=name), self.assertRaises(PublisherError):
                bind_space(self.config, str(path), "wechat_channels", sid, name)

    def test_review_ready_requires_matching_page_readback(self):
        path, plan = self.begin()
        evidence = self.evidence(path, plan)
        data = read_json(evidence)
        data["fields"]["title"] = "wrong page"
        evidence.write_text(dump(data))
        with self.assertRaises(PublisherError) as error:
            record_review(self.config, str(path), "wechat_channels", "review_ready", str(evidence))
        self.assertEqual(error.exception.status, "readback_mismatch")

    def test_review_ready_is_distinct_from_manual_publish(self):
        path, plan = self.begin()
        evidence = self.evidence(path, plan)
        result = record_review(self.config, str(path), "wechat_channels", "review_ready", str(evidence))
        self.assertEqual(result["status"], "review_ready")
        evidence.write_text(dump({"space_id":10,"user_confirmed":True,"confirmation":"用户确认已在原页面手动发表"}))
        self.assertEqual(record_review(self.config, str(path), "wechat_channels", "manual_review_finished", str(evidence))["status"], "manual_review_finished")
        with self.assertRaises(PublisherError):
            record_review(self.config, str(path), "wechat_channels", "manual_review_finished", str(evidence))

    def test_incomplete_evidence_cannot_be_review_ready(self):
        path, plan = self.begin()
        evidence = self.evidence(path, plan)
        data = read_json(evidence)
        data["handoff"] = False
        evidence.write_text(dump(data))
        with self.assertRaises(PublisherError):
            record_review(self.config, str(path), "wechat_channels", "review_ready", str(evidence))

    def test_sensitive_evidence_is_not_persisted(self):
        path, plan = self.begin()
        evidence = self.root / "evidence.json"
        evidence.write_text(dump({"space_id":10,"reason":"blocked","cookie":"example-value"}))
        with self.assertRaises(PublisherError) as error:
            record_review(self.config, str(path), "wechat_channels", "blocked", str(evidence))
        self.assertEqual(error.exception.status, "sensitive_evidence")
        self.assertNotIn("example-value", (path.parent / "review.json").read_text())
