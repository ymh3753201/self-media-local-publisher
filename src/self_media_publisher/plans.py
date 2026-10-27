from __future__ import annotations

import copy
import datetime as dt
from pathlib import Path
import shutil
import uuid

from .config import runtime_root
from .context import load_rules, snapshot
from .errors import PublisherError
from .media import inspect_inputs
from .rules import generate_metadata, ui_contracts, validate_metadata
from .storage import atomic_write, digest, dump, file_hash, read_json, run_lock, safe_child

SCHEMA = "2.0"


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def payload(plan: dict) -> dict:
    data = copy.deepcopy(plan)
    data.pop("seal", None)
    return data


def approval_phrase(hash_value: str) -> str:
    return f"确认启动 Ego 审核 {hash_value[:12]}"


def load_plan(config: dict, raw: str) -> tuple[Path, dict]:
    path = safe_child(runtime_root(config), Path(raw).expanduser().absolute())
    if path.name != "publish_plan.json" or path.parent.parent != runtime_root(config):
        raise PublisherError("只接受 .publisher-runs/<任务编号>/publish_plan.json。", "unsafe_plan_path")
    plan = read_json(path)
    if plan.get("schema_version") != SCHEMA:
        raise PublisherError("旧版计划不能直接进入独立版审核；请使用原始素材重新生成。", "legacy_plan_requires_replan")
    if plan.get("run_id") != path.parent.name:
        raise PublisherError("任务编号与所在目录不一致。", "invalid_plan")
    for name in ("assets.json", "manifest.json", "publish_preview.md", "review.json", ".operation.lock"):
        safe_child(runtime_root(config), path.parent / name)
    return path, plan


def preview(plan: dict) -> str:
    lines = ["# 多平台发布计划", "", f"任务：{plan['run_id']}", f"状态：{plan['status']}", "", "此文件用于人工查看；以计划和完整验证结果为准。", "", f"统一封面标题：{plan['cover_title']}", f"视频：{plan['materials']['video_path']}", f"字幕：{plan['materials']['subtitle_path']}", "", "## 封面"]
    for ratio, path in plan["materials"]["cover_variants"].items():
        lines.extend([f"{ratio}：", f"![{ratio}](<{path}>)", ""])
    subtitle = plan["inspection"]["subtitle"]
    lines.extend(["## 素材检查", f"字幕实际覆盖：{subtitle['coverage_ratio']:.1%}", f"字幕末尾位置：{subtitle['last_position_ratio']:.1%}", f"最长无字幕间隔：{subtitle['max_unsubtitled_gap_seconds']} 秒", f"原创：{plan['content_declarations']['originality']}", f"AI 内容：{plan['content_declarations']['ai_generated_content']}", "", "文案是字幕摘录草稿；逐个平台核对事实、分区、受众、可见性和封面裁切。", ""])
    for platform, meta in plan["platform_metadata"].items():
        lines.extend([f"## {platform}", "", f"标题：{meta['title']}", "", meta["description"], "", f"标签：{', '.join(meta.get('tags', meta.get('hashtags', [])))}"])
        for field in ("category", "audience", "visibility"):
            if field in meta:
                lines.append(f"{field}：{meta[field] or '待人工确认'}")
        for err in plan["validations"].get(platform, {}).get("errors", []):
            lines.append(f"待修正：{err}")
        lines.append("")
    lines.extend(["## 审核要求", "", "默认只上传、填表、读回并交接；最终按钮由用户点击。", "未明确的 AI、原创协议、版权或平台声明必须交给用户。"])
    if plan.get("seal"):
        lines.extend(["", f"本轮确认语句：{plan['seal']['review_approval_phrase']}"])
    return "\n".join(lines) + "\n"


def write_bundle(path: Path, plan: dict) -> None:
    # Commit marker is replaced last. An interrupted bundle is rejected by verify.
    run = path.parent
    text = preview(plan)
    marker = {"schema_version": SCHEMA, "run_id": plan["run_id"], "status": plan["status"], "plan_payload_sha256": digest(payload(plan)), "seal": plan.get("seal"), "preview_sha256": digest({"text": text}), "assets_sha256": plan["assets_sha256"]}
    atomic_write(path, dump(plan))
    atomic_write(run / "publish_preview.md", text)
    atomic_write(run / "manifest.json", dump(marker))


def create_plan(config: dict, args) -> dict:
    inspected = inspect_inputs(args.video, args.subtitle, args.cover)
    if inspected["missing_cover_ratios"]:
        raise PublisherError("请先补齐统一封面并检查画面。", "cover_generation_required", missing_cover_ratios=inspected["missing_cover_ratios"])
    selected = list(dict.fromkeys(args.platform or load_rules()["platforms"]))
    runtime = runtime_root(config)
    runtime.mkdir(parents=True, exist_ok=True)
    run = runtime / (dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:12])
    run.mkdir(mode=0o700)
    inp = run / "input"
    inp.mkdir()
    source_subtitle = Path(inspected["subtitle"]["path"])
    subtitle = inp / "subtitle.srt"
    shutil.copyfile(source_subtitle, subtitle)
    variants, records = {}, {}

    def record(role, path):
        records[role] = {"path": str(path), "sha256": file_hash(path)}

    record("video", Path(inspected["video"]["path"]))
    record("subtitle", subtitle)
    record("source_subtitle", source_subtitle)
    for ratio in inspected["required_cover_ratios"]:
        source = Path(inspected["covers"][ratio]["path"])
        target = inp / ("cover-" + ratio.replace(":", "-") + source.suffix.lower())
        shutil.copyfile(source, target)
        variants[ratio] = str(target)
        record("cover:" + ratio, target)
        record("source_cover:" + ratio, source)
    # Copy races are detected before a plan can be sealed.
    assets = {"schema_version": SCHEMA, "run_id": run.name, "records": records}
    atomic_write(run / "assets.json", dump(assets))
    inspected = inspect_inputs(records["video"]["path"], str(subtitle), list(variants.values()))
    metadata = generate_metadata(inspected["subtitle"], selected, args.cover_title, args.bilibili_category, args.youtube_audience, args.youtube_visibility)
    declarations = {"originality": "original" if args.original else "unspecified", "originality_basis": "user_statement" if args.original else "not_provided", "ai_generated_content": args.ai_content}
    plan = {"schema_version": SCHEMA, "run_id": run.name, "created_at": now(), "status": "draft", "materials": {"video_path": records["video"]["path"], "subtitle_path": str(subtitle), "cover_variants": variants}, "assets_sha256": digest(assets), "inspection": inspected, "cover_title": args.cover_title, "content_declarations": declarations, "platform_metadata": metadata, "codex_adapter": {"browser_backend": "ego", "final_publish": "user_only", "platform_ui_contracts": ui_contracts(metadata, inspected["video"]["orientation"]), "task_space_prefix": f"codex-publisher:{run.name}:"}, "context": snapshot(config), "rules_snapshot": load_rules(), "review_checks": {"content_reviewed": False, "covers_reviewed": False, "subtitle_note": ""}, "validations": validate_metadata(metadata, args.cover_title, declarations)}
    write_bundle(run / "publish_plan.json", plan)
    return {"status": "draft", "plan_path": str(run / "publish_plan.json"), "preview_path": str(run / "publish_preview.md"), "validations": plan["validations"], "next": "检查文案和封面后执行 seal --content-reviewed --covers-reviewed；再 verify。"}


def check_assets(config: dict, path: Path, plan: dict) -> dict:
    assets = read_json(path.parent / "assets.json")
    if digest(assets) != plan.get("assets_sha256") or assets.get("run_id") != plan["run_id"]:
        raise PublisherError("原始素材清单已变化，请重新生成任务。", "asset_manifest_changed")
    records = assets.get("records")
    if not isinstance(records, dict) or not records:
        raise PublisherError("素材指纹清单不能为空。", "invalid_assets")
    try:
        m = plan["materials"]
        covers = m["cover_variants"]
        required = set(plan["inspection"]["required_cover_ratios"])
        if set(covers) != required:
            raise ValueError("cover roles")
        refs = {"video": m["video_path"], "subtitle": m["subtitle_path"], **{"cover:"+r: p for r, p in covers.items()}}
        expected_roles = set(refs) | {"source_subtitle"} | {"source_cover:"+r for r in required}
        if set(records) != expected_roles:
            raise ValueError("asset roles")
        for role, raw in refs.items():
            if records[role]["path"] != raw:
                raise ValueError("path binding")
            if role != "video":
                p = safe_child(runtime_root(config), Path(raw))
                if p.parent != path.parent / "input":
                    raise ValueError("input directory")
        for record in records.values():
            source = Path(record["path"])
            if not source.is_file() or source.is_symlink() or file_hash(source) != record["sha256"]:
                raise ValueError("changed file")
        if records["subtitle"]["sha256"] != records["source_subtitle"]["sha256"]:
            raise ValueError("subtitle copy")
        if any(records["cover:"+r]["sha256"] != records["source_cover:"+r]["sha256"] for r in required):
            raise ValueError("cover copy")
    except (KeyError, TypeError, ValueError, OSError) as exc:
        raise PublisherError("素材缺失、被替换或与原始指纹清单不一致，请重新生成任务。", "material_changed") from exc
    return inspect_inputs(m["video_path"], m["subtitle_path"], list(covers.values()))


def review_state(path: Path) -> dict | None:
    return read_json(path.parent / "review.json") if (path.parent / "review.json").exists() else None


def validate_plan(config: dict, path: Path, plan: dict, *, frozen=False) -> tuple[dict, dict]:
    try:
        if plan["codex_adapter"]["browser_backend"] != "ego" or plan["codex_adapter"]["final_publish"] != "user_only":
            raise PublisherError("计划越过人工发布边界。", "unsafe_plan")
        if plan["codex_adapter"]["task_space_prefix"] != f"codex-publisher:{path.parent.name}:":
            raise PublisherError("浏览器空间前缀不一致。", "invalid_plan")
        if not frozen and plan["context"] != snapshot(config):
            raise PublisherError("代码、技能、配置或规则已变化，请重新生成任务。", "context_changed")
        if not frozen and plan["rules_snapshot"] != load_rules():
            raise PublisherError("规则快照与当前规则不一致。", "context_changed")
        inspected = check_assets(config, path, plan)
        if inspected != plan["inspection"]:
            raise PublisherError("媒体信息或字幕检查记录被改动，请重新生成任务。", "inspection_changed")
        checks = plan["review_checks"]
        if checks.get("content_reviewed") is not True or checks.get("covers_reviewed") is not True:
            raise PublisherError("需完成文案和封面的实际检查。", "manual_review_required")
        coverage = inspected["subtitle"]["coverage_ratio"]
        threshold = plan["context"]["configuration"]["subtitle_min_coverage"]
        if coverage < threshold and not str(checks.get("subtitle_note", "")).strip():
            raise PublisherError("字幕实际覆盖不足，需人工核对并填写原因；不能补造事实。", "subtitle_review_required", coverage_ratio=coverage)
        meta = plan["platform_metadata"]
        expected_contracts = ui_contracts(meta, inspected["video"]["orientation"])
        if plan["codex_adapter"]["platform_ui_contracts"] != expected_contracts:
            raise PublisherError("平台字段与页面约束不一致，请运行 seal 刷新后重新确认。", "ui_contract_changed")
        validations = validate_metadata(meta, plan["cover_title"], plan["content_declarations"], plan["rules_snapshot"])
        if any(not item["ok"] for item in validations.values()):
            raise PublisherError("平台文案或必需字段未通过检查。", "validation_failed", validations=validations)
        return inspected, validations
    except (KeyError, TypeError, AttributeError) as exc:
        raise PublisherError("计划结构不完整，请重新生成或修正。", "invalid_plan") from exc


def seal_plan(config: dict, raw: str, *, content_reviewed=False, covers_reviewed=False, subtitle_note="") -> dict:
    path, plan = load_plan(config, raw)
    with run_lock(path.parent):
        if review_state(path):
            raise PublisherError("已进入浏览器审核的计划不可修改；如需修改请创建新任务。", "review_frozen")
        plan["review_checks"] = {"content_reviewed": content_reviewed, "covers_reviewed": covers_reviewed, "subtitle_note": subtitle_note.strip()}
        plan["codex_adapter"]["platform_ui_contracts"] = ui_contracts(plan["platform_metadata"], plan["inspection"]["video"]["orientation"])
        _, validations = validate_plan(config, path, plan)
        plan["validations"] = validations
        plan["status"] = "plan_sealed"
        plan["sealed_at"] = now()
        h = digest(payload(plan))
        plan["seal"] = {"plan_sha256": h, "review_approval_phrase": approval_phrase(h)}
        write_bundle(path, plan)
    return {"status": "plan_sealed", "plan_path": str(path), "preview_path": str(path.parent / "publish_preview.md"), **plan["seal"]}


def verify_plan(config: dict, raw: str) -> dict:
    path, plan = load_plan(config, raw)
    try:
        if (path.parent / ".operation.lock").exists():
            raise PublisherError("任务正在写入，请稍后重试。", "run_busy")
        h = digest(payload(plan))
        seal = {"plan_sha256": h, "review_approval_phrase": approval_phrase(h)}
        if plan.get("status") != "plan_sealed" or plan.get("seal") != seal:
            raise PublisherError("计划未封存或封存后被改动。", "plan_changed_after_seal")
        marker = read_json(path.parent / "manifest.json")
        if marker.get("plan_payload_sha256") != h or marker.get("seal") != seal or marker.get("assets_sha256") != plan.get("assets_sha256"):
            raise PublisherError("计划与保存清单不一致，可能上次写入未完成。", "incomplete_bundle")
        preview_path = path.parent / "publish_preview.md"
        if marker.get("preview_sha256") != digest({"text": preview_path.read_text(encoding="utf-8")}) or preview_path.read_text(encoding="utf-8") != preview(plan):
            raise PublisherError("预览与计划不一致，请重新封存。", "preview_changed")
        state = review_state(path)
        if state and state.get("plan_sha256") != h:
            raise PublisherError("当前计划与已确认审核不一致。", "approval_invalidated")
        validate_plan(config, path, plan, frozen=bool(state))
        return {"status": "ready_for_review", "plan_path": str(path), **seal, "context_frozen": bool(state)}
    except (PublisherError, OSError, ValueError) as exc:
        return {"status": "replan_required", "plan_path": str(path), "issues": [{"kind": getattr(exc, "status", "invalid_plan"), "message": str(exc), **getattr(exc, "details", {})}]}
