from __future__ import annotations

import copy
from pathlib import Path

from .errors import PublisherError
from .storage import read_json, safe_child

DEFAULTS = {
    "schema_version": "2.0",
    "mode": "standalone",
    "runtime_dir": ".publisher-runs",
    "browser_backend": "ego",
    "final_publish": "user_only",
    "hermes_profile_dir": None,
    "subtitle_min_coverage": 0.5,
}


def load_config(root: Path) -> dict:
    root = root.expanduser().resolve()
    config = copy.deepcopy(DEFAULTS)
    for name in ("adapter.json", "adapter.local.json"):
        path = root / "config" / name
        if path.exists():
            values = read_json(path)
            if set(values) - set(DEFAULTS):
                raise PublisherError("配置含旧版或未知字段；请参照 adapter.example.json 迁移。", "invalid_configuration")
            config.update(values)
    if config["schema_version"] != "2.0" or config["mode"] not in {"standalone", "hermes_read_only"}:
        raise PublisherError("不支持的配置版本或运行模式。", "invalid_configuration")
    if (config["runtime_dir"], config["browser_backend"], config["final_publish"]) != (".publisher-runs", "ego", "user_only"):
        raise PublisherError("运行目录、浏览器与人工提交边界不能更改。", "unsafe_configuration")
    coverage = config["subtitle_min_coverage"]
    if isinstance(coverage, bool) or not isinstance(coverage, (int, float)) or not 0 < coverage <= 1:
        raise PublisherError("字幕最低覆盖率必须大于 0 且不超过 1。", "invalid_configuration")
    profile = config["hermes_profile_dir"]
    if config["mode"] == "hermes_read_only" and (not isinstance(profile, str) or not profile.strip()):
        raise PublisherError("只读兼容模式需在本机配置中指定 Hermes Profile。", "dependency_missing")
    config["project_root"] = str(root)
    runtime_root(config)
    return config


def runtime_root(config: dict) -> Path:
    root = Path(config["project_root"]).resolve()
    return safe_child(root, root / ".publisher-runs")
