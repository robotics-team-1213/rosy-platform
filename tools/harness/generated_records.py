"""Read and write canonical harness records."""

from pathlib import Path


def _normalize(text: str) -> str:
    return text.removeprefix("\ufeff").replace("\r\n", "\n")


def check(repo: Path, targets: dict[Path, str]) -> list[str]:
    problems = []
    for path, content in targets.items():
        rel = path.relative_to(repo).as_posix()
        if not path.is_file():
            problems.append(f"{rel}: missing")
        elif _normalize(path.read_text(encoding="utf-8")) != content:
            problems.append(f"{rel}: stale")
    return problems


def write(repo: Path, targets: dict[Path, str]) -> list[Path]:
    root = repo.resolve()
    for path in targets:
        resolved = path.resolve()
        if (resolved == root or not resolved.is_relative_to(root)
                or ".git" in resolved.relative_to(root).parts
                or (resolved.exists() and not resolved.is_file())):
            raise ValueError(f"unsafe generated target: {path}")
    written = []
    for path, content in targets.items():
        if not path.is_file() or _normalize(path.read_text(encoding="utf-8")) != content:
            path.write_text(content, encoding="utf-8", newline="\n")
            written.append(path)
    return written
