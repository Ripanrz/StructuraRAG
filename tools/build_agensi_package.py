#!/usr/bin/env python3
"""Build and validate the Agensi.io StructuraRAG skill ZIP using stdlib only."""
from __future__ import annotations

import argparse
import hashlib
import re
import sys
import zipfile
from pathlib import Path, PurePosixPath

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = REPOSITORY_ROOT / "agensi"
DEFAULT_OUTPUT = REPOSITORY_ROOT / "dist" / "structurarag-pdf-to-rag-1.0.0.zip"
MAX_ARCHIVE_BYTES = 50 * 1024 * 1024
MAX_FILES = 1000
MAX_SCRIPT_BYTES = 20 * 1024
ALLOWED_SUFFIXES = {".md", ".py", ".txt", ".json", ".yaml", ".yml", ".toml"}
EXCLUDED_PARTS = {
    ".git", ".venv", "venv", "__pycache__", "node_modules",
    ".pytest_cache", ".mypy_cache", ".ruff_cache",
}
SECRET_PATTERNS = [
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----", re.I),
    re.compile(r"\bsk-[A-Za-z0-9_-]{24,}\b"),
    re.compile(r"\bhf_[A-Za-z0-9]{24,}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{30,}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b"),
]


def validate_frontmatter(skill_text: str) -> None:
    if not skill_text.startswith("---\n"):
        raise ValueError("SKILL.md must start with YAML frontmatter.")
    pieces = skill_text.split("---", 2)
    if len(pieces) < 3:
        raise ValueError("SKILL.md has an unclosed YAML frontmatter block.")
    frontmatter = pieces[1]
    for key in ("name", "description"):
        match = re.search(rf"(?m)^{key}:\s*(.+?)\s*$", frontmatter)
        if not match or not match.group(1).strip().strip("\"'"):
            raise ValueError(f"YAML frontmatter must define a non-empty {key}.")
    name = re.search(r"(?m)^name:\s*([a-z0-9-]+)\s*$", frontmatter)
    if not name:
        raise ValueError("Skill name must use lowercase letters, numbers, and hyphens.")


def collect_files(source: Path) -> list[Path]:
    if not source.is_dir():
        raise ValueError(f"Skill source directory does not exist: {source}")
    candidates = []
    for path in source.rglob("*"):
        if not path.is_file() or path.is_symlink():
            continue
        relative = path.relative_to(source)
        if any(part in EXCLUDED_PARTS for part in relative.parts):
            continue
        if path.name == ".DS_Store" or path.name.startswith(".env"):
            continue
        if path.suffix.lower() not in ALLOWED_SUFFIXES:
            continue
        candidates.append(path)
    return sorted(candidates, key=lambda p: p.relative_to(source).as_posix())


def validate_files(source: Path, files: list[Path]) -> None:
    relative_names = {path.relative_to(source).as_posix() for path in files}
    if "SKILL.md" not in relative_names:
        raise ValueError("SKILL.md must be at the root of the skill source directory.")
    skill_text = (source / "SKILL.md").read_text(encoding="utf-8")
    validate_frontmatter(skill_text)

    if len(files) > MAX_FILES:
        raise ValueError(f"Skill contains {len(files)} files; maximum is {MAX_FILES}.")

    for path in files:
        relative = path.relative_to(source).as_posix()
        if path.stat().st_size == 0:
            raise ValueError(f"Empty file is not allowed: {relative}")
        if relative.startswith("scripts/") and path.stat().st_size >= MAX_SCRIPT_BYTES:
            raise ValueError(
                f"Agensi script must be smaller than 20 KB: {relative} "
                f"({path.stat().st_size} bytes)"
            )
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError(f"Skill packages may contain text files only: {relative}") from exc
        for pattern in SECRET_PATTERNS:
            if pattern.search(content):
                raise ValueError(f"Possible credential detected in {relative}; remove it before packaging.")

    if not any(name.startswith("references/") for name in relative_names):
        raise ValueError("Include at least one progressive-disclosure reference under references/.")
    if not any(name.startswith("scripts/") for name in relative_names):
        raise ValueError("Include at least one executable helper under scripts/.")


def build_archive(source: Path, output: Path) -> dict:
    files = collect_files(source)
    validate_files(source, files)

    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        output.unlink()

    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in files:
            arcname = path.relative_to(source).as_posix()
            info = zipfile.ZipInfo.from_file(path, arcname=arcname)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (0o100644 & 0xFFFF) << 16
            archive.writestr(info, path.read_bytes())

    if output.stat().st_size > MAX_ARCHIVE_BYTES:
        output.unlink(missing_ok=True)
        raise ValueError(f"Archive exceeds {MAX_ARCHIVE_BYTES // (1024 * 1024)} MB.")
    if len(files) > MAX_FILES:
        output.unlink(missing_ok=True)
        raise ValueError(f"Archive contains more than {MAX_FILES} files.")

    with zipfile.ZipFile(output, "r") as archive:
        corrupt = archive.testzip()
        if corrupt:
            output.unlink(missing_ok=True)
            raise ValueError(f"ZIP CRC verification failed at {corrupt}.")
        names = set(archive.namelist())
        if "SKILL.md" not in names:
            raise ValueError("SKILL.md is not at the archive root.")
        if any(name.startswith("/") or ".." in PurePosixPath(name).parts for name in names):
            raise ValueError("Unsafe archive path detected.")

    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    return {
        "path": str(output),
        "size_bytes": output.stat().st_size,
        "file_count": len(files),
        "sha256": digest,
        "files": [path.relative_to(source).as_posix() for path in files],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    try:
        report = build_archive(args.source.expanduser().resolve(), args.output.expanduser().resolve())
    except (OSError, ValueError) as exc:
        print(f"Package build failed: {exc}", file=sys.stderr)
        return 1
    print(f"Built Agensi skill: {report['path']}")
    print(f"Files: {report['file_count']} | Size: {report['size_bytes']:,} bytes")
    print(f"SHA-256: {report['sha256']}")
    for name in report["files"]:
        print(f"  {name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
