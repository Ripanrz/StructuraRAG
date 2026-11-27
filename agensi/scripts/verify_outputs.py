#!/usr/bin/env python3
"""Verify StructuraRAG DOCX, DSL, JSONL chunks, manifest, and batch report."""
from __future__ import annotations

import argparse
import json
import re
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

PAGE_RE = re.compile(r"^@PAGE\s+(\d+)\s*$", re.MULTILINE)
IMAGE_RE = re.compile(r"^@IMAGE\s+\[([^|\]]+)", re.MULTILINE)
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def load_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Cannot read JSON file {path.name}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{path.name} must contain a JSON object")
    return value


def verify_docx(path: Path) -> dict:
    try:
        with zipfile.ZipFile(path) as archive:
            bad_member = archive.testzip()
            if bad_member:
                raise ValueError(f"DOCX CRC check failed at {bad_member}")
            root = ET.fromstring(archive.read("word/document.xml"))
            media = [
                name for name in archive.namelist()
                if name.startswith("word/media/") and not name.endswith("/")
            ]
    except (OSError, KeyError, zipfile.BadZipFile, ET.ParseError) as exc:
        raise ValueError(f"Invalid DOCX package {path.name}: {exc}") from exc

    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    paragraphs = len(root.findall(".//w:p", ns))
    tables = len(root.findall(".//w:tbl", ns))
    drawings = len(root.findall(".//w:drawing", ns))
    text = "\n".join(node.text or "" for node in root.findall(".//w:t", ns))
    if paragraphs == 0:
        raise ValueError(f"DOCX {path.name} contains no paragraphs")
    if drawings and not media:
        raise ValueError(f"DOCX {path.name} contains drawing anchors but no word/media assets")
    if re.search(r"(?m)^@(PAGE|h[0-5]\b|TABLE_START|TABLE_END|IMAGE\b)", text):
        raise ValueError(f"DOCX {path.name} exposes internal DSL control markers as visible text")
    return {
        "paragraphs": paragraphs,
        "tables": tables,
        "drawings": drawings,
        "media_files": len(media),
    }


def verify_chunks(path: Path, page_count: int) -> dict:
    chunks = []
    seen_ids = set()
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ValueError(f"Cannot read chunks {path.name}: {exc}") from exc

    for line_number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path.name}:{line_number}: invalid JSON ({exc})") from exc
        if not isinstance(item, dict):
            raise ValueError(f"{path.name}:{line_number}: chunk must be a JSON object")
        chunk_id = item.get("chunk_id")
        content = item.get("content")
        metadata = item.get("metadata")
        if not isinstance(chunk_id, str) or not chunk_id:
            raise ValueError(f"{path.name}:{line_number}: missing chunk_id")
        if chunk_id in seen_ids:
            raise ValueError(f"{path.name}:{line_number}: duplicate chunk_id {chunk_id}")
        seen_ids.add(chunk_id)
        if not isinstance(content, str) or not content.strip():
            raise ValueError(f"{path.name}:{line_number}: chunk content is empty")
        if not isinstance(metadata, dict):
            raise ValueError(f"{path.name}:{line_number}: metadata must be an object")
        pages = metadata.get("source_pages")
        if not isinstance(pages, list) or not pages:
            raise ValueError(f"{path.name}:{line_number}: source_pages must be a non-empty list")
        if any(not isinstance(page, int) or page < 1 or page > page_count for page in pages):
            raise ValueError(f"{path.name}:{line_number}: source_pages contains an invalid page")
        if not isinstance(metadata.get("heading_path", []), list):
            raise ValueError(f"{path.name}:{line_number}: heading_path must be a list")
        if not isinstance(metadata.get("image_anchors", []), list):
            raise ValueError(f"{path.name}:{line_number}: image_anchors must be a list")
        chunks.append(item)

    if not chunks:
        raise ValueError(f"{path.name} contains no chunks")
    return {"count": len(chunks), "ids_unique": True}


def verify_one(docx_path: Path) -> dict:
    stem = docx_path.stem
    text_path = docx_path.with_suffix(".txt")
    manifest_path = docx_path.with_suffix(".manifest.json")
    chunks_path = docx_path.with_suffix(".chunks.jsonl")
    missing = [
        path.name for path in (text_path, manifest_path, chunks_path)
        if not path.is_file()
    ]
    if missing:
        raise ValueError(f"{stem}: missing sidecar(s): {', '.join(missing)}")

    dsl = text_path.read_text(encoding="utf-8")
    manifest = load_json(manifest_path)
    pages = [int(value) for value in PAGE_RE.findall(dsl)]
    expected_pages = manifest.get("pages")
    if not pages:
        raise ValueError(f"{stem}: DSL contains no @PAGE markers")
    if pages != list(range(1, len(pages) + 1)):
        raise ValueError(f"{stem}: page markers are missing, duplicated, or out of order: {pages}")
    if isinstance(expected_pages, int) and expected_pages != len(pages):
        raise ValueError(f"{stem}: manifest says {expected_pages} pages, DSL contains {len(pages)}")

    table_starts = dsl.count("@TABLE_START")
    table_ends = dsl.count("@TABLE_END")
    if table_starts != table_ends:
        raise ValueError(f"{stem}: unbalanced table markers ({table_starts} starts, {table_ends} ends)")

    dsl_images = IMAGE_RE.findall(dsl)
    manifest_images = manifest.get("images", [])
    if not isinstance(manifest_images, list):
        raise ValueError(f"{stem}: manifest.images must be a list")
    if len(dsl_images) != len(manifest_images):
        raise ValueError(
            f"{stem}: image-anchor count {len(dsl_images)} does not match "
            f"manifest image count {len(manifest_images)}"
        )

    source_hash = manifest.get("source_sha256")
    if source_hash is not None and not SHA256_RE.fullmatch(str(source_hash)):
        raise ValueError(f"{stem}: manifest source_sha256 is not a SHA-256 hex digest")

    docx_report = verify_docx(docx_path)
    chunks_report = verify_chunks(chunks_path, len(pages))
    if dsl_images and docx_report["media_files"] == 0:
        raise ValueError(f"{stem}: DSL has image anchors but DOCX contains no media assets")
    if docx_report["tables"] != table_starts:
        raise ValueError(
            f"{stem}: DOCX contains {docx_report['tables']} native tables, "
            f"but DSL contains {table_starts} table blocks"
        )

    warnings = manifest.get("warnings", [])
    if not isinstance(warnings, list):
        warnings = ["manifest.warnings is not a list"]
    return {
        "file": docx_path.name,
        "status": "warning" if warnings else "ok",
        "pages": len(pages),
        **docx_report,
        "table_blocks": table_starts,
        "image_anchors": len(dsl_images),
        "chunks": chunks_report["count"],
        "warnings": warnings,
    }


def verify_batch_report(path: Path) -> tuple[int, list[str]]:
    if not path.is_file():
        return 0, []
    latest_by_source = {}
    rows = 0
    issues = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError as exc:
            issues.append(f"{path.name}:{line_number}: invalid JSON ({exc})")
            continue
        if not isinstance(item, dict):
            issues.append(f"{path.name}:{line_number}: row must be a JSON object")
            continue
        rows += 1
        source = str(item.get("source") or f"line {line_number}")
        latest_by_source[Path(source.replace("\\", "/")).name] = item
    for source_name, item in latest_by_source.items():
        if item.get("status") == "error":
            issues.append(f"{source_name}: {item.get('error', 'conversion failed')}")
    return rows, issues


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    output_dir = args.output_dir.expanduser().resolve()
    if not output_dir.is_dir():
        parser.error(f"Output directory does not exist: {output_dir}")

    results = []
    issues = []
    docx_files = sorted(output_dir.glob("*.docx"))
    for path in docx_files:
        try:
            results.append(verify_one(path))
        except (OSError, ValueError, zipfile.BadZipFile) as exc:
            issues.append(str(exc))

    report_rows, report_issues = verify_batch_report(output_dir / "batch-report.jsonl")
    issues.extend(report_issues)
    if not docx_files:
        issues.append("No DOCX files found in output directory")

    summary = {
        "result": "failed" if issues else (
            "passed_with_warnings"
            if any(item["status"] == "warning" for item in results) else "passed"
        ),
        "output_dir": str(output_dir),
        "docx_count": len(docx_files),
        "report_rows": report_rows,
        "files": results,
        "issues": issues,
    }
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print(f"StructuraRAG output verification: {summary['result']}")
        print(f"DOCX files: {len(docx_files)} | batch report rows: {report_rows}")
        for item in results:
            print(
                f"  {item['status'].upper()} {item['file']}: pages={item['pages']} "
                f"paragraphs={item['paragraphs']} tables={item['tables']} chunks={item['chunks']}"
            )
            for warning in item["warnings"]:
                print(f"    WARNING: {warning}")
        for issue in issues:
            print(f"  ERROR: {issue}", file=sys.stderr)
    return 1 if issues else 0


if __name__ == "__main__":
    raise SystemExit(main())
