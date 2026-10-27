from __future__ import annotations

import json
import math
from pathlib import Path
import re
import subprocess

from .errors import PublisherError

VIDEO_EXTS = {".mp4", ".mov", ".mkv"}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}
RATIOS = {"9:16": 9 / 16, "3:4": 3 / 4, "4:3": 4 / 3, "16:9": 16 / 9}
TIMING = re.compile(r"^(\d{2,}):([0-5]\d):([0-5]\d)[,.](\d{3})\s*-->\s*(\d{2,}):([0-5]\d):([0-5]\d)[,.](\d{3})(?:\s+.*)?$")


def existing_file(raw, suffixes: set[str]) -> Path:
    path = Path(raw).expanduser().resolve()
    if not path.is_file() or path.suffix.lower() not in suffixes:
        raise PublisherError("素材不存在或文件格式不支持。", "invalid_material")
    return path


def probe(path: Path) -> dict:
    try:
        result = subprocess.run(["ffprobe", "-v", "error", "-protocol_whitelist", "file,pipe", "-show_streams", "-show_format", "-of", "json", str(path)], capture_output=True, text=True, timeout=30, check=False)
    except FileNotFoundError as exc:
        raise PublisherError("请安装 FFmpeg（其中包含 ffprobe）。", "dependency_missing") from exc
    except subprocess.TimeoutExpired as exc:
        raise PublisherError("媒体检查超过 30 秒，请检查本地素材。", "media_probe_failed") from exc
    if result.returncode:
        # ffprobe stderr may contain arbitrary paths/URLs; do not echo it.
        raise PublisherError("ffprobe 无法解析素材。", "invalid_material")
    try:
        data = json.loads(result.stdout)
        streams = data.get("streams", [])
        video = next(s for s in streams if s.get("codec_type") == "video")
        duration = float(video.get("duration") or data.get("format", {}).get("duration") or 0)
        width, height = int(video.get("width", 0)), int(video.get("height", 0))
        rotations = [s.get("rotation", 0) for s in video.get("side_data_list", []) if "rotation" in s]
        rotation = int(float(rotations[0] if rotations else video.get("tags", {}).get("rotate", 0))) % 360
        if rotation in {90, 270}:
            width, height = height, width
        if not math.isfinite(duration) or duration < 0 or width <= 0 or height <= 0:
            raise ValueError("Invalid dimensions or duration")
        return {"width": width, "height": height, "duration_seconds": round(duration, 3), "codec": video.get("codec_name", ""), "has_audio": any(s.get("codec_type") == "audio" for s in streams), "frame_rate": video.get("avg_frame_rate", "")}
    except (ValueError, TypeError, StopIteration, KeyError) as exc:
        raise PublisherError("素材缺少有效视频流或媒体信息。", "invalid_material") from exc


def required_ratios(width: int, height: int) -> list[str]:
    if width <= 0 or height <= 0:
        raise PublisherError("无法判断视频宽高。", "invalid_material")
    return ["9:16", "3:4", "4:3"] if width < height else ["16:9", "4:3", "3:4"]


def classify_ratio(width: int, height: int) -> str | None:
    if width <= 0 or height <= 0:
        return None
    name = min(RATIOS, key=lambda k: abs(width / height - RATIOS[k]))
    return name if abs(width / height - RATIOS[name]) <= 0.035 else None


def parse_srt(path: Path, duration: float | None = None) -> dict:
    try:
        text = path.read_text(encoding="utf-8-sig")
    except (UnicodeError, OSError) as exc:
        raise PublisherError("字幕需为 UTF-8 编码 SRT。", "invalid_subtitle") from exc
    cues = []
    for block in re.split(r"\n\s*\n", text.replace("\r\n", "\n").strip()):
        lines = [line.strip() for line in block.splitlines()]
        if lines and lines[0].isdigit():
            lines = lines[1:]
        match = TIMING.fullmatch(lines[0]) if lines else None
        if not match or len(lines) < 2:
            raise PublisherError("字幕段落缺少合法时间轴或正文。", "invalid_subtitle")
        v = list(map(int, match.groups()))
        start = v[0]*3600 + v[1]*60 + v[2] + v[3]/1000
        end = v[4]*3600 + v[5]*60 + v[6] + v[7]/1000
        body = re.sub(r"<[^>]+>", "", " ".join(lines[1:])).strip()
        if start >= end or not body or (cues and start < cues[-1]["start"]):
            raise PublisherError("字幕时间轴倒序、零时长或正文为空。", "invalid_subtitle")
        if duration is not None and (start >= duration or end > duration + 0.25):
            raise PublisherError("字幕时间轴超出视频范围。", "invalid_subtitle")
        cues.append({"start": start, "end": end, "text": body})
    if not cues:
        raise PublisherError("字幕不能为空。", "invalid_subtitle")
    covered, left, right, max_gap = 0.0, cues[0]["start"], cues[0]["end"], cues[0]["start"]
    for cue in cues[1:]:
        if cue["start"] > right:
            covered += right - left
            max_gap = max(max_gap, cue["start"] - right)
            left = cue["start"]
        right = max(right, cue["end"])
    covered += right - left
    if duration is not None:
        max_gap = max(max_gap, duration - right)
    return {"cue_count": len(cues), "first_start_seconds": cues[0]["start"], "last_end_seconds": right, "captioned_seconds": round(covered, 3), "coverage_ratio": round(min(1, covered / duration), 4) if duration else None, "last_position_ratio": round(min(1, right / duration), 4) if duration else None, "max_unsubtitled_gap_seconds": round(max_gap, 3), "cues": cues, "text": "\n".join(c["text"] for c in cues)}


def inspect_inputs(video_raw, subtitle_raw, covers_raw) -> dict:
    video = existing_file(video_raw, VIDEO_EXTS)
    subtitle = existing_file(subtitle_raw, {".srt"})
    vi = probe(video)
    if vi["duration_seconds"] <= 0:
        raise PublisherError("视频必须具有有效时长。", "invalid_material")
    si = parse_srt(subtitle, vi["duration_seconds"])
    covers = {}
    for raw in covers_raw:
        path = existing_file(raw, IMAGE_EXTS)
        info = probe(path)
        if info["codec"] not in {"png", "mjpeg", "webp"}:
            raise PublisherError("封面必须是可识别的 PNG、JPEG 或 WebP 图片，不能只改扩展名。", "invalid_cover")
        ratio = classify_ratio(info["width"], info["height"])
        if ratio is None:
            raise PublisherError("封面比例不属于支持的四种比例。", "invalid_cover_ratio")
        if ratio in covers:
            raise PublisherError("同一封面比例存在多个文件。", "ambiguous_cover_ratio")
        covers[ratio] = {"path": str(path), **info}
    ratios = required_ratios(vi["width"], vi["height"])
    missing = [r for r in ratios if r not in covers]
    return {"status": "cover_generation_required" if missing else "materials_ready", "video": {"path": str(video), **vi, "orientation": "vertical" if vi["width"] < vi["height"] else "horizontal"}, "subtitle": {"path": str(subtitle), **si}, "covers": covers, "required_cover_ratios": ratios, "missing_cover_ratios": missing}
