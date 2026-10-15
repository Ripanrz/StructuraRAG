"""Inspect DOCX paragraph/table patterns without needing python-docx."""
from __future__ import annotations

import json
import re
import zipfile
from collections import Counter, defaultdict
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
DOCX_DIR = ROOT / "docx-e-hukum"
OUT = ROOT / "Tools_Formatting" / "gold_standard_profile.json"
SUMMARY = ROOT / "Tools_Formatting" / "gold_standard_summary.md"
NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
TAG = "{" + NS["w"] + "}"


def text_of(node: ET.Element) -> str:
    return "".join(t.text or "" for t in node.iter(TAG + "t")).strip()


def get_style(p: ET.Element) -> str:
    ppr = p.find("w:pPr", NS)
    ps = ppr.find("w:pStyle", NS) if ppr is not None else None
    if ps is None:
        return "Normal"
    return ps.attrib.get(TAG + "val", "Normal")


def get_outline(p: ET.Element) -> int | None:
    ppr = p.find("w:pPr", NS)
    outline = ppr.find("w:outlineLvl", NS) if ppr is not None else None
    if outline is None:
        return None
    try:
        return int(outline.attrib[TAG + "val"])
    except (KeyError, ValueError):
        return None


def parse_doc(path: Path) -> dict:
    with zipfile.ZipFile(path) as zf:
        root = ET.fromstring(zf.read("word/document.xml"))
        styles = ET.fromstring(zf.read("word/styles.xml")) if "word/styles.xml" in zf.namelist() else None
    style_names = {}
    if styles is not None:
        for style in styles.findall("w:style", NS):
            sid = style.attrib.get(TAG + "styleId", "")
            name = style.find("w:name", NS)
            style_names[sid] = name.attrib.get(TAG + "val", sid) if name is not None else sid

    paragraphs = []
    style_counts = Counter()
    outline_counts = Counter()
    text_samples = defaultdict(list)
    table_counts = []
    body = root.find("w:body", NS)
    for child in list(body) if body is not None else []:
        if child.tag == TAG + "p":
            value = text_of(child)
            if not value:
                continue
            sid = get_style(child)
            style = style_names.get(sid, sid)
            outline = get_outline(child)
            style_counts[style] += 1
            if outline is not None:
                outline_counts[outline] += 1
            sample = {"text": value[:240], "style": style, "outline_level_0_based": outline}
            paragraphs.append(sample)
            if len(text_samples[style]) < 8:
                text_samples[style].append(value[:240])
        elif child.tag == TAG + "tbl":
            rows = []
            for row in child.findall(".//w:tr", NS):
                cells = [text_of(c) for c in row.findall("w:tc", NS)]
                if any(cells):
                    rows.append(cells)
            table_counts.append({"rows": len(rows), "columns_max": max(map(len, rows), default=0), "sample": rows[:3]})
    return {
        "file": path.name,
        "paragraph_count": len(paragraphs),
        "table_count": len(table_counts),
        "style_counts": dict(style_counts),
        "outline_level_counts_0_based": dict(outline_counts),
        "style_samples": dict(text_samples),
        "paragraphs": paragraphs,
        "tables": table_counts,
    }


def main() -> None:
    # Ignore Office lock/owner files (e.g. ~$document.docx).
    docs = sorted(p for p in DOCX_DIR.glob("*.docx") if not p.name.startswith("~$"))
    if not docs:
        raise SystemExit(f"No DOCX references found at {DOCX_DIR}")
    parsed = [parse_doc(p) for p in docs]
    styles = Counter()
    outlines = Counter()
    table_shapes = Counter()
    heading_samples = defaultdict(list)
    inline_tag_counts = Counter()
    inline_tag_samples = defaultdict(list)
    first_paragraph_samples = []
    inline_tags = re.compile(r"@[A-Za-z][A-Za-z0-9_]*")
    candidates = [
        re.compile(r"^BAB\s+[IVXLCDM0-9]+\b", re.I),
        re.compile(r"^[A-Z]\.\s+"),
        re.compile(r"^\d+(?:\.\d+)*[.)]?\s+"),
        re.compile(r"^[a-z][.)]\s+", re.I),
        re.compile(r"^[ivxlcdm]+[.)]\s+", re.I),
    ]
    for doc in parsed:
        styles.update(doc["style_counts"])
        outlines.update(doc["outline_level_counts_0_based"])
        for table in doc["tables"]:
            table_shapes[(table["rows"], table["columns_max"])] += 1
        for p in doc["paragraphs"]:
            if len(first_paragraph_samples) < 70:
                first_paragraph_samples.append({"file": doc["file"], **p})
            for tag in inline_tags.findall(p["text"]):
                inline_tag_counts[tag] += 1
                if len(inline_tag_samples[tag]) < 8:
                    inline_tag_samples[tag].append({"text": p["text"][:300], "file": doc["file"]})
            for i, pattern in enumerate(candidates):
                if pattern.match(p["text"]):
                    if len(heading_samples[str(i + 1)]) < 30:
                        heading_samples[str(i + 1)].append({"text": p["text"], "style": p["style"], "file": doc["file"]})
                    break
    result = {
        "reference_directory": str(DOCX_DIR),
        "document_count": len(parsed),
        "aggregate_paragraph_count": sum(x["paragraph_count"] for x in parsed),
        "aggregate_table_count": sum(x["table_count"] for x in parsed),
        "aggregate_style_counts": styles.most_common(),
        "aggregate_outline_level_counts_0_based": dict(outlines),
        "common_table_shapes_row_count_column_count": table_shapes.most_common(30),
        "inline_tag_counts": inline_tag_counts.most_common(),
        "inline_tag_samples": dict(inline_tag_samples),
        "initial_paragraph_samples": first_paragraph_samples,
        "numbering_pattern_samples": dict(heading_samples),
        "documents": parsed,
    }
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    tag_counts = dict(inline_tag_counts)
    heading_tags = sorted((k for k in tag_counts if re.fullmatch(r"@h\d+", k)), key=lambda x: int(x[2:]))
    page_tags = tag_counts.get("@PAGE", 0)
    table_starts, table_ends = tag_counts.get("@TABLE_START", 0), tag_counts.get("@TABLE_END", 0)
    sample_table = []
    for doc in parsed:
        ps = doc["paragraphs"]
        for index, paragraph in enumerate(ps):
            if paragraph["text"] == "@TABLE_START":
                sample_table = [p["text"] for p in ps[index:index + 12]]
                break
        if sample_table:
            break
    summary = [
        "# Gold standard format profile",
        "",
        f"Source: `{DOCX_DIR}`. Inspected {len(parsed)} DOCX files.",
        "",
        "## Observed structure",
        "",
        f"- Paragraphs: {result['aggregate_paragraph_count']:,}; native Word tables: 0 (tables are serialized as DSL paragraphs).",
        f"- Every inspected paragraph used style `Normal`; Word outline levels were not set.",
        f"- `@PAGE`: {page_tags:,} occurrences.",
        f"- Table markers: `{table_starts:,}` starts and `{table_ends:,}` ends (some references are incomplete or unbalanced).",
        f"- Observed heading tags: {', '.join(heading_tags)}. No deeper heading tag was found in this corpus.",
        "",
        "## Heading hierarchy",
        "",
        "| Tag | Corpus count | Observed convention |",
        "|---|---:|---|",
        "| `@h0` | " + str(tag_counts.get("@h0", 0)) + " | Main document title, generally uppercase |",
        "| `@h1` | " + str(tag_counts.get("@h1", 0)) + " | `BAB <Roman numeral> – <title>` |",
        "| `@h2` | " + str(tag_counts.get("@h2", 0)) + " | Lettered section, e.g. `A. Latar Belakang` |",
        "| `@h3` | " + str(tag_counts.get("@h3", 0)) + " | Numbered sub-section, e.g. `1. Divisi Treasury` |",
        "| `@h4` | " + str(tag_counts.get("@h4", 0)) + " | Lowercase letter item, e.g. `a. ...` |",
        "| `@h5` | " + str(tag_counts.get("@h5", 0)) + " | Deeper subpoint; both lettered (`a.`) and numbered (`1)`) forms observed |",
        "",
        "The observed gold standard ends at `@h5`; levels `@h6+` are not supported by corpus evidence and must not be invented. Numbering markers and consistent sibling groups are evidence for heading classification; unmatched prose stays a normal paragraph.",
        "",
        "## Table DSL",
        "",
        "Reference table blocks begin with `@TABLE_START` and end with `@TABLE_END`. The first row can be a merged/group label before `KOLOM:`; data rows use `|` between cells. Preserve such contextual rows instead of forcing them into the header. Some source DOCX have unbalanced markers, so generated files should enforce balanced pairs.",
        "",
        "```text",
        *sample_table,
        "```",
        "",
        "## Layout and conversion implications",
        "",
        "- Keep each source page boundary as `@PAGE n` and retain source reading order.",
        "- Output remains plain `Normal` paragraphs containing the inline tags; this matches the DOCX references better than native Word heading/table styles.",
        "- The corpus has no observed `@IMAGE` marker. The converter adds `@IMAGE [filename | page and anchor]` as a documented extension and inserts the embedded image at the same paragraph position.",
        "- DOCX extraction shows no native table objects; table DSL is already flattened into paragraphs in the gold files.",
    ]
    SUMMARY.write_text("\n".join(summary) + "\n", encoding="utf-8")
    print(f"Analyzed {len(parsed)} DOCX; wrote {OUT}")
    print("Paragraphs:", result["aggregate_paragraph_count"], "Tables:", result["aggregate_table_count"])
    print("Styles:", result["aggregate_style_counts"][:20])
    print("Outline levels:", result["aggregate_outline_level_counts_0_based"])
    print("Heading marker samples:", {k: len(v) for k, v in result["numbering_pattern_samples"].items()})
    print(f"Wrote summary {SUMMARY}")


if __name__ == "__main__":
    main()
