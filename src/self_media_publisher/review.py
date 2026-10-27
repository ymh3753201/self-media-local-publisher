from __future__ import annotations

import json
from pathlib import Path
import re

from .errors import PublisherError
from .plans import load_plan, now, review_state, verify_plan
from .rules import TAG_KEY
from .storage import atomic_write, digest, dump, read_json, run_lock

STATUSES = {"review_ready", "manual_required", "blocked", "failed", "manual_review_finished"}
SENSITIVE = re.compile(r"(?i)(cookie|password|secret|token|authorization)|(?:gh[pousr]_|github_pat_|sk-)[A-Za-z0-9_-]{15,}|-----BEGIN .*PRIVATE KEY")


def clean_evidence(path: str) -> dict:
    source = Path(path).expanduser()
    if not source.is_file() or source.stat().st_size > 65536:
        raise PublisherError("证据需为不超过 64KB 的本地 JSON。", "invalid_evidence")
    data = read_json(source)
    if SENSITIVE.search(json.dumps(data, ensure_ascii=False)):
        raise PublisherError("证据可能含凭据字段；请移除敏感内容，只保留页面读回。", "sensitive_evidence")
    return data


def checked(config, raw):
    result = verify_plan(config, raw)
    if result["status"] != "ready_for_review":
        raise PublisherError("当前计划不能进入或继续审核。", "replan_required", issues=result["issues"])
    path, plan = load_plan(config, raw)
    if digest({k: v for k, v in plan.items() if k != "seal"}) != result["plan_sha256"]:
        raise PublisherError("检查期间计划发生变化。", "approval_invalidated")
    return path, plan, result


def start_review(config: dict, raw: str, phrase: str) -> dict:
    path, plan, verification = checked(config, raw)
    if phrase != verification["review_approval_phrase"]:
        raise PublisherError("确认语句不属于当前计划。", "approval_invalidated")
    with run_lock(path.parent):
        if review_state(path):
            raise PublisherError("已存在审核记录，请使用 review-status 继续原任务。", "review_already_started")
        if read_json(path)["seal"] != plan["seal"]:
            raise PublisherError("计划发生变化。", "approval_invalidated")
        state = {"schema_version": "2.0", "run_id": plan["run_id"], "plan_sha256": verification["plan_sha256"], "started_at": now(), "frozen_context": plan["context"]["context_sha256"], "platforms": {p: {"status": "pending", "space_id": None, "events": []} for p in plan["platform_metadata"]}}
        atomic_write(path.parent / "review.json", dump(state))
    return {"status": "review_started", "review_path": str(path.parent / "review.json"), "next": "加载 ego-browser 技能；检查空间冲突，创建并绑定各平台原空间。此命令本身不启动浏览器。"}


def bind_space(config: dict, raw: str, platform: str, space_id: int, space_name: str) -> dict:
    path, plan, _ = checked(config, raw)
    expected = plan["codex_adapter"]["task_space_prefix"] + platform
    if space_id <= 0 or space_name != expected:
        raise PublisherError("只能绑定本任务指定名称的正整数 Ego Space ID。", "unsafe_space")
    with run_lock(path.parent):
        state = review_state(path)
        if not state or platform not in state["platforms"]:
            raise PublisherError("需先确认并启动本平台审核。", "review_not_started")
        item = state["platforms"][platform]
        if item["space_id"] not in {None, space_id}:
            raise PublisherError("本平台必须复用原 Space ID。", "unsafe_space")
        if any(p != platform and v["space_id"] == space_id for p, v in state["platforms"].items()):
            raise PublisherError("不同平台不能共用一个 Space。", "unsafe_space")
        item["space_id"] = space_id
        item["space_name"] = expected
        atomic_write(path.parent / "review.json", dump(state))
    return {"status": "space_bound", "platform": platform, "space_id": space_id}


def record_review(config: dict, raw: str, platform: str, status: str, evidence_raw: str) -> dict:
    path, plan, _ = checked(config, raw)
    evidence = clean_evidence(evidence_raw)
    if status not in STATUSES:
        raise PublisherError("无效的平台状态。", "invalid_status")
    with run_lock(path.parent):
        state = review_state(path)
        if not state or platform not in state["platforms"]:
            raise PublisherError("该平台未启动审核。", "review_not_started")
        item = state["platforms"][platform]
        if not item["space_id"] or type(evidence.get("space_id")) is not int or evidence["space_id"] != item["space_id"]:
            raise PublisherError("证据必须来自已绑定的原数字 Space ID。", "unsafe_space")
        if item["status"] == "manual_review_finished":
            raise PublisherError("已确认完成的平台不能重复操作。", "review_finished")
        if status == "review_ready":
            for key in ("video_uploaded", "cover_uploaded", "required_fields_readback", "stopped_before_publish", "handoff"):
                if evidence.get(key) is not True:
                    raise PublisherError(f"缺少页面检查证据：{key}", "incomplete_evidence")
            if evidence.get("browser_backend") != "ego" or evidence.get("plan_sha256") != plan["seal"]["plan_sha256"]:
                raise PublisherError("证据后端或计划指纹不一致。", "invalid_evidence")
            assets = read_json(path.parent / "assets.json")["records"]
            ratio = plan["codex_adapter"]["platform_ui_contracts"][platform]["cover_ratio"]
            if evidence.get("video_sha256") != assets["video"]["sha256"] or evidence.get("cover_sha256") != assets["cover:"+ratio]["sha256"]:
                raise PublisherError("上传素材证据与本轮素材不一致。", "invalid_evidence")
            observed = evidence.get("fields")
            expected = plan["platform_metadata"][platform]
            keys = ["title", "description", TAG_KEY[platform]]
            if platform == "bilibili":
                keys.append("category")
            if platform == "youtube":
                keys.extend(["audience", "visibility"])
            if not isinstance(observed, dict) or any(observed.get(k) != expected.get(k) for k in keys):
                raise PublisherError("页面字段读回与计划不一致。", "readback_mismatch")
            if evidence.get("declarations_reviewed") is not True:
                raise PublisherError("原创、AI、版权等声明尚未完成人工检查。", "incomplete_evidence")
            if plan["content_declarations"]["ai_generated_content"] == "unspecified" and evidence.get("ai_declaration_required") is not False:
                raise PublisherError("平台需要 AI 声明时须先由用户明确事实。", "manual_required")
        elif status == "manual_review_finished":
            if item["status"] != "review_ready" or evidence.get("user_confirmed") is not True or not str(evidence.get("confirmation", "")).strip():
                raise PublisherError("仅可在 review_ready 后，依据用户明确的人工完成确认登记。", "incomplete_evidence")
        elif not str(evidence.get("reason", "")).strip():
            raise PublisherError("需记录页面阻塞或失败的原因。", "incomplete_evidence")
        allowed = {"space_id", "browser_backend", "plan_sha256", "video_sha256", "cover_sha256", "video_uploaded", "cover_uploaded", "required_fields_readback", "stopped_before_publish", "handoff", "fields", "declarations_reviewed", "ai_declaration_required", "reason", "user_confirmed", "confirmation"}
        safe = {k: v for k, v in evidence.items() if k in allowed}
        item["events"].append({"at": now(), "status": status, "evidence": safe})
        item["status"] = status
        atomic_write(path.parent / "review.json", dump(state))
    return {"status": status, "platform": platform, "space_id": item["space_id"], "evidence_source": "operator_page_readback"}


def get_status(config: dict, raw: str) -> dict:
    path, _ = load_plan(config, raw)
    state = review_state(path)
    return {"status": "review_status" if state else "review_not_started", "verification": verify_plan(config, raw), "review": state}
