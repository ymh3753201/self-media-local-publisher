#!/usr/bin/env python3
"""Inspect/export only public allowlisted files; never walk runtime data."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
TOP = {"AGENTS.md", "README.md", "LICENSE", "THIRD_PARTY.md", "SECURITY.md", "CONTRIBUTING.md", "CHANGELOG.md", "pyproject.toml", "MANIFEST.in", ".gitignore"}
TREES = {"src": {".py", ".json"}, "tests": {".py"}, "scripts": {".py"}, "config": {".json"}, "examples": {".json", ".srt"}, ".agents": {".md"}, ".github": {".yml", ".yaml"}}
PATTERNS = {
    "private_home_path": re.compile(r"/(?:Users|home)/[A-Za-z0-9_.-]+/"),
    "github_credential": re.compile(r"(?:gh[pousr]_|github_pat_)[A-Za-z0-9_]{20,}"),
    "api_credential": re.compile(r"sk-[A-Za-z0-9_-]{24,}"),
    "private_key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
}


def allowed(relative: Path) -> bool:
    if relative.as_posix() in TOP:
        return True
    if len(relative.parts) < 2 or relative.parts[0] not in TREES:
        return False
    if "__pycache__" in relative.parts or any(p.endswith(".egg-info") for p in relative.parts):
        return False
    if relative.name.endswith(".local.json") or relative.suffix not in TREES[relative.parts[0]]:
        return False
    if relative.parts[0] == "config":
        return relative.name in {"adapter.json", "adapter.example.json"} and len(relative.parts) == 2
    return True


def candidates() -> list[Path]:
    paths = set()
    # Scan intended source files, and every indexed path if a Git repository exists.
    for name in TOP:
        if (ROOT / name).is_file():
            paths.add(Path(name))
    for directory in TREES:
        for path in (ROOT / directory).rglob("*"):
            rel = path.relative_to(ROOT)
            if path.is_file() and allowed(rel):
                paths.add(rel)
    if (ROOT / ".git").exists():
        result = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True)
        paths.update(Path(p.decode("utf-8")) for p in result.stdout.split(b"\0") if p)
    return sorted(paths)


def inspect(paths: list[Path]) -> list[dict]:
    issues = []
    for rel in paths:
        path = ROOT / rel
        if not allowed(rel):
            issues.append({"file": rel.as_posix(), "kind": "path_not_allowlisted"})
            continue
        cursor = ROOT
        has_symlink = False
        for part in rel.parts:
            cursor /= part
            has_symlink |= cursor.is_symlink()
        if has_symlink or not path.is_file() or path.stat().st_size > 1024 * 1024:
            issues.append({"file": rel.as_posix(), "kind": "symlink_missing_or_oversized"})
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeError:
            issues.append({"file": rel.as_posix(), "kind": "non_text_public_file"})
            continue
        for kind, pattern in PATTERNS.items():
            for match in pattern.finditer(text):
                issues.append({"file": rel.as_posix(), "line": text[:match.start()].count("\n") + 1, "kind": kind})
    return issues


def inspect_index() -> list[dict]:
    """Scan staged bytes too, even when the worktree was later cleaned."""
    if not (ROOT / ".git").exists():
        return []
    result = subprocess.run(["git", "ls-files", "--stage", "-z"], cwd=ROOT, capture_output=True, check=True)
    issues = []
    for row in result.stdout.split(b"\0"):
        if not row:
            continue
        header, name = row.split(b"\t", 1)
        mode, object_id, stage = header.decode().split()
        rel = Path(name.decode("utf-8"))
        if not allowed(rel) or mode not in {"100644", "100755"} or stage != "0":
            issues.append({"file":rel.as_posix(),"kind":"unsafe_index_entry"})
            continue
        blob = subprocess.run(["git", "cat-file", "blob", object_id], cwd=ROOT, capture_output=True, check=True).stdout
        try:
            text = blob.decode("utf-8")
        except UnicodeError:
            issues.append({"file":rel.as_posix(),"kind":"binary_index_entry"})
            continue
        if len(blob) > 1024 * 1024:
            issues.append({"file":rel.as_posix(),"kind":"oversized_index_entry"})
        for kind, pattern in PATTERNS.items():
            for match in pattern.finditer(text):
                issues.append({"file":rel.as_posix(),"line":text[:match.start()].count("\n")+1,"kind":"index_"+kind})
    return issues


def main():
    parser = argparse.ArgumentParser(description="检查公开文件并按白名单导出源码包")
    parser.add_argument("--archive", type=Path)
    args = parser.parse_args()
    paths = candidates()
    issues = inspect(paths) + inspect_index()
    if issues:
        print(json.dumps({"status": "blocked", "issues": issues}, ensure_ascii=False, indent=2))
        return 2
    archive = None
    if args.archive:
        sys.path.insert(0, str(ROOT / "src"))
        from self_media_publisher.config import load_config, runtime_root
        from self_media_publisher.storage import safe_child
        archive = safe_child(runtime_root(load_config(ROOT)), args.archive.absolute())
        if archive.exists():
            parser.error("导出文件已存在，请指定新文件名。")
        archive.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(archive, "x", compression=zipfile.ZIP_DEFLATED) as out:
            for rel in paths:
                out.write(ROOT / rel, rel.as_posix())
    print(json.dumps({"status":"passed", "public_file_count":len(paths), "archive":str(archive) if archive else None, "note":"有限模式检查；仍需人工核对提交差异和文件。"}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
