from __future__ import annotations

import re

from .context import load_rules

PLATFORMS = tuple(load_rules()["platforms"])
TAG_KEY = {p: ("tags" if p in {"bilibili", "youtube"} else "hashtags") for p in PLATFORMS}


def ui_contracts(metadata: dict, orientation: str) -> dict:
    result = {}
    for platform, meta in metadata.items():
        ratio = "3:4" if platform in {"xiaohongshu", "wechat_channels"} else "4:3" if platform == "bilibili" else "9:16" if orientation == "vertical" else "16:9"
        result[platform] = {"cover_ratio": ratio, "final_publish": "user_only", "ai_declaration": "handoff_if_required_and_unspecified", "readback_required": True}
        if platform == "wechat_channels":
            result[platform].update(short_title_max_chars=16, clear_default_location_unless_requested=True, original_declaration_requires_handoff=True)
        if platform == "bilibili":
            result[platform].update(clear_prefilled_title_description_and_tags=True, category_ui_label=meta.get("category"), sync_cover_crops=True)
        if platform == "youtube":
            result[platform].update(visibility=meta.get("visibility"), audience=meta.get("audience"), copyright_claim_policy="handoff_for_review", cover_upload_policy="confirm_actual_studio_support; otherwise_manual_required")
    return result


def generate_metadata(subtitle: dict, selected: list[str], cover_title: str, category=None, audience="unspecified", visibility="private") -> dict:
    """Conservative drafts composed from verbatim subtitle excerpts, no claims."""
    text = subtitle["text"]
    topic = re.split(r"[。！？!?\n]", text)[0].strip() or "视频内容"
    tags = []
    for cue in subtitle["cues"]:
        for word in re.findall(r"[A-Za-z][A-Za-z0-9_+-]{1,20}|[\u4e00-\u9fff]{2,6}", cue["text"]):
            if word not in tags:
                tags.append(word)
    # These describe the format, rather than inventing video capabilities.
    for tag in ("视频记录", "字幕摘录", "内容分享", "视频内容", "观看记录"):
        if tag not in tags:
            tags.append(tag)
    prefixes = {"douyin": "", "xiaohongshu": "记录｜", "bilibili": "内容分享｜", "wechat_channels": "分享：", "youtube": "视频记录｜"}
    descriptions = {"douyin": "本期片段：", "xiaohongshu": "这期记录的内容：", "bilibili": "本期字幕摘录：", "wechat_channels": "本期分享：", "youtube": "视频内容 / Subtitle excerpt："}
    rules = load_rules()["platforms"]
    result = {}
    for platform in selected:
        rule = rules[platform]
        prefix = prefixes[platform]
        meta = {"title": (prefix + topic)[:rule["title_max_chars"]], "description": descriptions[platform] + "\n" + text[:350], TAG_KEY[platform]: tags[:max(5, rule["tags_min"])], "cover_text": cover_title, "source": "subtitle_excerpt; review against full transcript"}
        if platform == "bilibili":
            meta["category"] = category
        if platform == "youtube":
            meta.update(audience=audience, visibility=visibility)
        result[platform] = meta
    return result


def validate_metadata(metadata: dict, cover_title: str, declarations: dict, rules=None) -> dict:
    rules = (rules or load_rules())["platforms"]
    results = {}
    global_errors = []
    if not isinstance(metadata, dict) or not metadata or set(metadata) - set(PLATFORMS):
        return {"__global__": {"ok": False, "errors": ["平台列表为空或含未知平台。"]}}
    titles = []
    for platform, meta in metadata.items():
        errors = []
        if not isinstance(meta, dict):
            results[platform] = {"ok": False, "errors": ["平台文案必须是对象。"]}
            continue
        rule = rules[platform]
        title, desc = meta.get("title"), meta.get("description")
        if not isinstance(title, str) or not title.strip() or len(title) > rule["title_max_chars"]:
            errors.append(f"标题不能为空且最多 {rule['title_max_chars']} 字。")
        else:
            titles.append(re.sub(r"\s+", "", title).lower())
        if not isinstance(desc, str) or not desc.strip():
            errors.append("简介不能为空。")
        elif len(desc) > rule.get("description_max_chars", 100000) or len(desc.encode()) > rule.get("description_max_bytes", 100000):
            errors.append("简介超过项目预检长度限制。")
        tags = meta.get(TAG_KEY[platform])
        if not isinstance(tags, list) or any(not isinstance(t, str) or not t.strip() or len(t) > 50 for t in tags):
            errors.append("标签需为非空短文本列表。")
        elif not rule["tags_min"] <= len(tags) <= rule["tags_max"] or len(set(t.strip().lower().lstrip('#') for t in tags)) != len(tags):
            errors.append("标签数量不合格或重复。")
        combined = str(title) + str(desc) + str(tags)
        if any(w.lower() in combined.lower() for w in rule["forbidden_words"]):
            errors.append("命中项目高风险表达预检，请修改后再审核。")
        if meta.get("cover_text") != cover_title:
            errors.append("封面标题与统一标题不一致。")
        if platform == "bilibili" and (not isinstance(meta.get("category"), str) or not meta["category"].strip() or len(meta["category"]) > 60):
            errors.append("B站分区需按视频内容明确填写。")
        if platform == "youtube":
            if meta.get("audience") not in {"made_for_kids", "not_made_for_kids"}:
                errors.append("YouTube 受众需按事实明确选择。")
            if meta.get("visibility") not in {"private", "unlisted", "public"}:
                errors.append("YouTube 可见性无效。")
        results[platform] = {"ok": not errors, "errors": errors}
    if len(titles) != len(set(titles)):
        global_errors.append("不同平台的标题不能完全相同。")
    if not isinstance(cover_title, str) or not cover_title.strip() or len(cover_title) > 80:
        global_errors.append("必须设置统一封面标题（最多 80 字）。")
    if not isinstance(declarations, dict) or declarations.get("originality") not in {"original", "unspecified"} or declarations.get("ai_generated_content") not in {"yes", "no", "unspecified"}:
        global_errors.append("原创与 AI 声明格式无效。")
    elif declarations["originality"] == "original" and declarations.get("originality_basis") != "user_statement":
        global_errors.append("原创必须有用户明确声明。")
    results["__global__"] = {"ok": not global_errors, "errors": global_errors}
    return results
