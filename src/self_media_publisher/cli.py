from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import subprocess
import sys

from . import __version__
from .config import load_config, runtime_root
from .context import snapshot
from .errors import PublisherError
from .media import inspect_inputs
from .plans import create_plan, seal_plan, verify_plan
from .review import STATUSES, bind_space, get_status, record_review, start_review
from .rules import PLATFORMS
from .storage import dump


def command_available(command: str) -> bool:
    if not shutil.which(command):
        return False
    try:
        result = subprocess.run([command, "-version" if command == "ffprobe" else "--version"], capture_output=True, timeout=10, check=False)
        return result.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def doctor(config: dict, browser=False) -> dict:
    checks = {"python_3_11_or_newer": sys.version_info >= (3, 11), "ffprobe": command_available("ffprobe"), "runtime_is_project_local": runtime_root(config).parent == Path(config["project_root"])}
    issues = []
    try:
        context = snapshot(config)
        checks["planning_rules"] = True
    except PublisherError as exc:
        context = None
        checks["planning_rules"] = False
        issues.append({"kind": exc.status, "message": str(exc)})
    if browser:
        checks["ego_browser_cli"] = command_available("ego-browser")
    for name, ok in checks.items():
        if not ok:
            issues.append({"kind": name, "message": "请参照 README 的安装或诊断说明。"})
    return {"status": "ready" if all(checks.values()) else "dependency_missing", "version": __version__, "mode": config["mode"], "scope": "browser_prerequisites" if browser else "local_planning", "checks": checks, "issues": issues, "context_sha256": context["context_sha256"] if context else None, "note": "浏览器依赖检查不代表账号登录或平台页面已通过。"}


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="独立本地自媒体发布规划与人工审核助手")
    p.add_argument("--version", action="version", version=__version__)
    p.add_argument("--project-root", type=Path, default=Path.cwd(), help="运行项目目录；默认当前目录")
    sub = p.add_subparsers(dest="command", required=True)

    def command(name):
        cmd = sub.add_parser(name)
        cmd.add_argument("--json", action="store_true")
        return cmd

    command("context")
    command("doctor").add_argument("--browser", action="store_true")
    for name in ("inspect", "plan"):
        cmd = command(name)
        cmd.add_argument("--video", required=True)
        cmd.add_argument("--subtitle", required=True)
        cmd.add_argument("--cover", action="append", default=[])
        if name == "plan":
            cmd.add_argument("--platform", action="append", choices=PLATFORMS)
            cmd.add_argument("--cover-title", required=True)
            cmd.add_argument("--original", action="store_true", help="仅在用户明确声明原创时使用")
            cmd.add_argument("--ai-content", choices=["yes", "no", "unspecified"], default="unspecified")
            cmd.add_argument("--bilibili-category")
            cmd.add_argument("--youtube-audience", choices=["made_for_kids", "not_made_for_kids", "unspecified"], default="unspecified")
            cmd.add_argument("--youtube-visibility", choices=["private", "unlisted", "public"], default="private")
    for name in ("seal", "verify", "review-start", "review-bind", "review-record", "review-status"):
        cmd = command(name)
        cmd.add_argument("--plan", required=True)
        if name == "seal":
            cmd.add_argument("--content-reviewed", action="store_true")
            cmd.add_argument("--covers-reviewed", action="store_true")
            cmd.add_argument("--subtitle-note", default="")
        if name == "review-start":
            cmd.add_argument("--approval", required=True)
        if name in {"review-bind", "review-record"}:
            cmd.add_argument("--platform", choices=PLATFORMS, required=True)
        if name == "review-bind":
            cmd.add_argument("--space-id", type=int, required=True)
            cmd.add_argument("--space-name", required=True)
        if name == "review-record":
            cmd.add_argument("--status", choices=sorted(STATUSES), required=True)
            cmd.add_argument("--evidence", required=True)
    return p


def main(argv=None) -> int:
    args = parser().parse_args(argv)
    try:
        config = load_config(args.project_root)
        if args.command == "doctor":
            result = doctor(config, args.browser)
        elif args.command == "context":
            result = {"status": "ready", **snapshot(config)}
        elif args.command == "inspect":
            result = inspect_inputs(args.video, args.subtitle, args.cover)
        elif args.command == "plan":
            result = create_plan(config, args)
        elif args.command == "seal":
            result = seal_plan(config, args.plan, content_reviewed=args.content_reviewed, covers_reviewed=args.covers_reviewed, subtitle_note=args.subtitle_note)
        elif args.command == "verify":
            result = verify_plan(config, args.plan)
        elif args.command == "review-start":
            result = start_review(config, args.plan, args.approval)
        elif args.command == "review-bind":
            result = bind_space(config, args.plan, args.platform, args.space_id, args.space_name)
        elif args.command == "review-record":
            result = record_review(config, args.plan, args.platform, args.status, args.evidence)
        else:
            result = get_status(config, args.plan)
        print(dump(result) if args.json else f"状态：{result['status']}\n{dump(result)}", end="")
        return 2 if result["status"] in {"dependency_missing", "replan_required", "cover_generation_required"} else 0
    except PublisherError as exc:
        print(dump({"status": exc.status, "error": str(exc), **exc.details}), end="")
        return 2
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(dump({"status": "unexpected_error", "error": "操作未完成，请检查本地配置和计划结构。", "exception_type": type(exc).__name__}), end="")
        return 1
