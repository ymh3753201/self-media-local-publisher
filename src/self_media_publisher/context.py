from __future__ import annotations

from importlib.resources import files
import json
from pathlib import Path

from . import __version__
from .errors import PublisherError
from .storage import digest, file_hash


def load_rules() -> dict:
    return json.loads(files("self_media_publisher").joinpath("data/platform_rules.json").read_text(encoding="utf-8"))


def snapshot(config: dict) -> dict:
    """Content-only fingerprints. Never load accounts, tokens or profile.yaml."""
    package = Path(__file__).resolve().parent
    sources = {p.relative_to(package).as_posix(): file_hash(p) for p in sorted(package.rglob("*.py"))}
    sources["data/platform_rules.json"] = digest(load_rules())
    root = Path(config["project_root"])
    for name in ("AGENTS.md", ".agents/skills/self-media-publisher/SKILL.md", ".agents/skills/self-media-publisher/references/runtime-contract.md", ".agents/skills/self-media-publisher/references/cover-policy.md"):
        path = root / name
        if path.is_file():
            sources[name] = file_hash(path)
    public_config = {k: v for k, v in config.items() if k not in {"project_root", "hermes_profile_dir"}}
    hermes = {"mode": "disabled", "files": []}
    if config["mode"] == "hermes_read_only":
        profile = Path(config["hermes_profile_dir"]).expanduser().resolve()
        candidates = [profile / "SOUL.md"]
        for pattern in ("*video*publish*", "*platform-video-review*", "publisher-agent-*", "social-video-*"):
            candidates.extend((profile / "skills/productivity").glob(pattern + "/SKILL.md"))
        candidates = sorted(set(candidates))
        if not (profile / "SOUL.md").is_file() or len(candidates) < 2:
            raise PublisherError("只读兼容规则缺少 SOUL 或发布 Skill。", "dependency_missing")
        records = []
        for path in candidates:
            if path.is_symlink() or not path.resolve().is_relative_to(profile) or not path.is_file():
                raise PublisherError("只读参考文件无效。", "unsafe_reference")
            records.append({"path": str(path), "sha256": file_hash(path)})
        hermes = {"mode": "read_only", "files": records}
    result = {"version": __version__, "mode": config["mode"], "rules_version": load_rules()["version"], "sources": sources, "configuration": public_config, "hermes_context": hermes}
    result["context_sha256"] = digest(result)
    return result
