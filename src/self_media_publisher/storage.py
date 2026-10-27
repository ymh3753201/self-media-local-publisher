from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import tempfile

from .errors import PublisherError


def dump(data) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n"


def digest(data) -> str:
    raw = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode()).hexdigest()


def file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        raise PublisherError(f"无法读取有效 JSON：{path.name}", "invalid_json") from exc
    if not isinstance(data, dict):
        raise PublisherError(f"JSON 顶层必须是对象：{path.name}", "invalid_json")
    return data


def safe_child(root: Path, path: Path) -> Path:
    """Reject writes through symlinks, including ones pointing inside the root."""
    root = root.resolve()
    path = path.absolute()
    try:
        parts = path.relative_to(root).parts
    except ValueError as exc:
        raise PublisherError("运行文件必须位于本项目 .publisher-runs。", "unsafe_path") from exc
    cursor = root
    for part in parts:
        if part in {".", ".."}:
            raise PublisherError("运行路径含非法目录。", "unsafe_path")
        cursor /= part
        if cursor.is_symlink():
            raise PublisherError("运行路径不能通过符号链接读写。", "unsafe_path")
    if not path.resolve().is_relative_to(root):
        raise PublisherError("运行路径越界。", "unsafe_path")
    return path


def atomic_write(path: Path, text: str) -> None:
    if path.is_symlink():
        raise PublisherError("不能覆盖符号链接。", "unsafe_path")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".write-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


@contextmanager
def run_lock(run: Path):
    lock = run / ".operation.lock"
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise PublisherError("该任务正在写入；若上次异常退出，请核实无运行进程后移除 .operation.lock。", "run_busy") from exc
    try:
        os.close(fd)
        yield
    finally:
        lock.unlink(missing_ok=True)
