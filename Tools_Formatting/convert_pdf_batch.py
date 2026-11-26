"""Convert regulatory PDFs to the observed DOCX DSL format.

LLM providers:
  openai  - Responses API using OPENAI_API_KEY (or OPENAI_BEARER_TOKEN)
  codex   - codex exec using the locally authenticated Codex CLI

Only the batch page text/layout is sent to the configured model provider.
Images are extracted locally and inserted into DOCX at their DSL anchor.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path
from typing import Any

import pymupdf as fitz
from docx import Document
from docx.shared import Inches

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = ROOT / "pdf-e-hukum"
DEFAULT_OUTPUT = ROOT / "docx-e-hukum-generated"
PROFILE_PATH = Path(__file__).with_name("gold_standard_profile.json")
SUMMARY_PATH = Path(__file__).with_name("gold_standard_rules.md")
NOISE_PATTERNS = [
    # Remove only standalone watermark/metadata blocks. A substantive paragraph
    # that merely mentions "E-Hukum" or a registration number must be retained.
    re.compile(r"^\s*e[\s-]?hukum\s*$", re.I),
    re.compile(r"^\s*\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\s+\d{1,2}:\d{2}(?::\d{2})?\s*$"),
    re.compile(r"^\s*diverifikasi\s+oleh(?:\s+.*)?$", re.I),
    re.compile(r"^\s*nomor\s+registrasi(?:\s+.*)?$", re.I),
]
IMAGE_TOKEN_RE = re.compile(r"\[\[IMAGE:([A-Za-z0-9_-]+)\]\]")
TABLE_TOKEN_RE = re.compile(r"@TABLE_(?:START|END)")


def normalized(text: str) -> str:
    text = text.replace("\u00a0", " ").replace("\ufffd", "�")
    return "\n".join(re.sub(r"[ \t]+", " ", part).strip() for part in text.splitlines()).strip()


def is_noise(text: str, repeated: set[str]) -> bool:
    cleaned = normalized(text)
    if not cleaned:
        return True
    if cleaned.casefold() in repeated:
        return True
    return any(pattern.fullmatch(cleaned) for pattern in NOISE_PATTERNS)


def repeated_margin_text(pdf: fitz.Document) -> set[str]:
    counts: Counter[str] = Counter()
    for page in pdf:
        height = page.rect.height
        for block in page.get_text("dict").get("blocks", []):
            if block.get("type") != 0:
                continue
            text = normalized("\n".join(
                " ".join(span.get("text", "") for span in line.get("spans", []))
                for line in block.get("lines", [])
            ))
            y0, y1 = block["bbox"][1], block["bbox"][3]
            if text and len(text) < 180 and (y0 < height * .12 or y1 > height * .88):
                counts[text.casefold()] += 1
    minimum = max(2, (len(pdf) + 3) // 4)
    return {value for value, count in counts.items() if count >= minimum}


def extract_page_events(page: fitz.Page, page_number: int, repeated: set[str], images_dir: Path,
                        use_ocr: bool = False) -> tuple[list[dict[str, Any]], dict[str, Path]]:
    events: list[dict[str, Any]] = []
    image_paths: dict[str, Path] = {}
    tables = page.find_tables().tables
    table_rects = [fitz.Rect(t.bbox) for t in tables]
    for idx, table in enumerate(tables, 1):
        rows = [[normalized(str(cell or "")) for cell in row] for row in table.extract()]
        rows = [row for row in rows if any(row)]
        if rows:
            events.append({"y": float(table.bbox[1]), "x": float(table.bbox[0]), "kind": "table", "rows": rows, "source_order": idx})

    image_index = 0
    textpage = None
    if use_ocr and len(page.get_text().strip()) < 40:
        try:
            textpage = page.get_textpage_ocr(language="ind+eng", dpi=300, full=True)
        except Exception as exc:
            raise RuntimeError(f"OCR diminta tetapi gagal pada halaman {page_number}; pastikan Tesseract dan data bahasa ind+eng terpasang: {exc}") from exc
    blocks = page.get_text("dict", textpage=textpage).get("blocks", [])
    for order, block in enumerate(blocks):
        bbox = fitz.Rect(block.get("bbox", (0, 0, 0, 0)))
        if block.get("type") == 0:
            if any(bbox.intersects(rect) for rect in table_rects):
                continue
            text = normalized("\n".join(
                " ".join(span.get("text", "") for span in line.get("spans", []))
                for line in block.get("lines", [])
            ))
            if is_noise(text, repeated):
                continue
            events.append({"y": bbox.y0, "x": bbox.x0, "kind": "text", "text": text, "source_order": order})
        elif block.get("type") == 1 and block.get("image"):
            image_index += 1
            token = f"P{page_number}I{image_index}"
            ext = (block.get("ext") or "png").lower()
            if ext not in {"png", "jpg", "jpeg", "tif", "tiff", "bmp", "webp"}:
                ext = "png"
            filename = f"page_{page_number:04d}_image_{image_index:03d}.{ext}"
            path = images_dir / filename
            path.write_bytes(block["image"])
            image_paths[filename] = path
            events.append({"y": bbox.y0, "x": bbox.x0, "kind": "image", "token": token,
                           "filename": filename, "anchor_y": round(bbox.y0, 1), "source_order": order,
                           "_bbox": (bbox.x0, bbox.y0, bbox.x1, bbox.y1)})

    # Vector diagrams are made from drawing paths rather than image XObjects.
    # Rasterize only substantial clusters and skip table/image regions.
    groups: list[dict[str, Any]] = []
    for drawing in page.get_drawings():
        rect = fitz.Rect(drawing.get("rect", (0, 0, 0, 0)))
        if rect.is_empty or rect.is_infinite:
            continue
        near = rect + (-7, -7, 7, 7)
        matched = [group for group in groups if (group["rect"] + (-7, -7, 7, 7)).intersects(near)]
        if not matched:
            groups.append({"rect": rect, "count": 1})
        else:
            primary = matched[0]
            primary["rect"] |= rect
            primary["count"] += 1
            for extra in matched[1:]:
                primary["rect"] |= extra["rect"]
                primary["count"] += extra["count"]
                groups.remove(extra)
    for group_index, group in enumerate(groups, 1):
        rect = group["rect"] & page.rect
        if group["count"] < 8 or rect.width < 90 or rect.height < 60:
            continue
        if rect.width * rect.height < page.rect.width * page.rect.height * .01:
            continue
        def overlap_ratio(other: fitz.Rect) -> float:
            intersection = rect & other
            return intersection.width * intersection.height / max(1, rect.width * rect.height)
        if any(overlap_ratio(table_rect) > .55 for table_rect in table_rects):
            continue
        image_rects = [fitz.Rect(event["_bbox"]) for event in events if event["kind"] == "image" and "_bbox" in event]
        if any(overlap_ratio(image_rect) > .75 for image_rect in image_rects):
            continue
        image_index += 1
        token = f"P{page_number}I{image_index}"
        filename = f"page_{page_number:04d}_vector_{group_index:03d}.png"
        path = images_dir / filename
        page.get_pixmap(matrix=fitz.Matrix(2, 2), clip=rect, alpha=False).save(path)
        image_paths[filename] = path
        events.append({"y": rect.y0, "x": rect.x0, "kind": "image", "token": token,
                       "filename": filename, "anchor_y": round(rect.y0, 1), "source_order": len(blocks) + group_index,
                       "_bbox": (rect.x0, rect.y0, rect.x1, rect.y1)})

    events.sort(key=lambda event: (event["y"], event["x"], event["source_order"]))
    return events, image_paths


def events_to_prompt_text(page_events: dict[int, list[dict[str, Any]]]) -> str:
    chunks: list[str] = []
    for page_number, events in page_events.items():
        chunks.append(f"SOURCE PAGE {page_number}")
        if not events:
            chunks.append("(No extractable text/layout objects.)")
        for event in events:
            if event["kind"] == "text":
                chunks.append(f"TEXT y={event['y']:.1f}: {event['text']}")
            elif event["kind"] == "table":
                chunks.append(f"TABLE y={event['y']:.1f} ROWS={json.dumps(event['rows'], ensure_ascii=False)}")
            else:
                chunks.append(f"IMAGE_ANCHOR y={event['y']:.1f}: [[IMAGE:{event['token']}]]")
    return "\n".join(chunks)


def get_format_rules() -> str:
    if SUMMARY_PATH.exists():
        return SUMMARY_PATH.read_text(encoding="utf-8")
    return "Observed format: all content is normal DOCX paragraphs. Use @PAGE n; observed headings @h0 through @h5; table DSL uses @TABLE_START, KOLOM:, pipe-separated data rows, @TABLE_END."


def make_prompt(page_events: dict[int, list[dict[str, Any]]], previous_headings: list[str], use_vision: bool = False) -> str:
    page_ids = list(page_events)
    all_image_tokens = [e["token"] for events in page_events.values() for e in events if e["kind"] == "image"]
    rules = get_format_rules()
    context = "\n".join(previous_headings[-12:]) or "(Belum ada; awal dokumen.)"
    return f"""Anda adalah parser dokumen regulasi untuk menyiapkan chunk RAG. Ubah layout source menjadi DSL berdasarkan format acuan berikut.

ATURAN GOLD STANDARD:
{rules}

KONTEKS HEADING DARI SEGMEN SEBELUMNYA (jangan diulang):
{context}

ATURAN WAJIB:
1. Keluarkan hanya DSL sebagai teks biasa, tanpa markdown fence/komentar.
2. Mulai setiap halaman sumber dengan tepat satu `@PAGE <nomor halaman asli>`; urutan halaman dan isi tidak boleh tertukar.
3. Pertahankan semua isi substantif, angka, istilah, dan urutan baca. Jangan merangkum, mengarang, atau membuang isi selain noise yang jelas (watermark, timestamp, header/footer berulang).
4. Gunakan hanya level heading yang dibuktikan penanda dan konsistensi sibling: h0 judul dokumen; h1 BAB; h2 subbab huruf besar; h3 butir angka; h4/h5 turunan (pada h5 acuan memuat bentuk huruf dan angka). Jangan membuat h6+ karena tidak teramati dalam acuan. Jika satu kelompok sibling bercampur teks tanpa penanda, pertahankan item kelompok itu sebagai paragraf biasa.
5. Tabel: `@TABLE_START`, pertahankan baris kelompok/judul tabel sebelum `KOLOM:` jika ada, header sebagai `KOLOM: A | B`, setiap baris data pipe-separated, lalu `@TABLE_END`. Jangan menghilangkan sel kosong atau menggabungkan kolom berbeda.
6. Setiap token gambar berikut harus dipertahankan persis satu kali dan di urutan vertikal sumber. Letakkan token di antara paragraf sebelum dan sesudah gambar. Jangan mengganti/menerjemahkan token: {', '.join(all_image_tokens) if all_image_tokens else '(tidak ada gambar pada segmen ini)'}.
7. Keluarkan semua halaman yang diminta, termasuk halaman yang hanya berisi gambar/tabel.
{('8. Gunakan juga render visual tiap halaman untuk membaca struktur tabel/diagram dan posisi blok; jangan menimpa teks hasil ekstraksi tanpa bukti visual. ' if use_vision else '')}

INPUT LAYOUT TERURUT:
{events_to_prompt_text(page_events)}

Nomor halaman segmen ini: {', '.join(map(str, page_ids))}
"""


def response_text(payload: dict[str, Any]) -> str:
    if isinstance(payload.get("output_text"), str):
        return payload["output_text"].strip()
    texts = []
    for item in payload.get("output", []):
        for content in item.get("content", []):
            if content.get("type") in {"output_text", "text"}:
                texts.append(content.get("text", ""))
    result = "\n".join(texts).strip()
    if not result:
        raise RuntimeError("Responses API mengembalikan output teks kosong.")
    return result


def openai_response(prompt: str, model: str, base_url: str, page_images: list[bytes] | None = None) -> str:
    token = os.getenv("OPENAI_API_KEY") or os.getenv("OPENAI_BEARER_TOKEN")
    if not token:
        raise RuntimeError("Atur OPENAI_API_KEY (API key) atau OPENAI_BEARER_TOKEN (short-lived bearer token) untuk provider openai.")
    if page_images:
        content: list[dict[str, str]] = [{"type": "input_text", "text": prompt}]
        content.extend({"type": "input_image", "detail": "high",
                        "image_url": "data:image/png;base64," + base64.b64encode(image).decode("ascii")}
                       for image in page_images)
        model_input: Any = [{"role": "user", "content": content}]
    else:
        model_input = prompt
    body = json.dumps({"model": model, "input": model_input, "max_output_tokens": 12000}).encode("utf-8")
    request = urllib.request.Request(
        base_url.rstrip("/") + "/responses", data=body,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"}, method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=300) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:1500]
        raise RuntimeError(f"OpenAI API HTTP {exc.code}: {detail}") from exc
    return response_text(result)


def local_ai_response(prompt: str, model: str, base_url: str, api_key: str | None = None,
                     timeout: int = 300) -> str:
    """Call an OpenAI-compatible local/self-hosted chat-completions endpoint."""
    body = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": "You are a careful document-structure parser. Preserve source wording, order, numbers, and all supplied markers exactly."},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.0,
        "stream": False,
    }).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request = urllib.request.Request(
        base_url.rstrip("/") + "/chat/completions",
        data=body,
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:1500]
        raise RuntimeError(f"Local AI HTTP {exc.code}: {detail}") from exc
    choices = payload.get("choices", [])
    content = choices[0].get("message", {}).get("content") if choices else None
    if isinstance(content, list):
        content = "\n".join(
            item.get("text", "") for item in content if isinstance(item, dict)
        )
    if not isinstance(content, str) or not content.strip():
        raise RuntimeError("Local AI endpoint returned empty chat content.")
    return content.strip()


def codex_response(prompt: str, model: str | None, timeout: int) -> str:
    cli = shutil.which(os.getenv("CODEX_CLI", "codex"))
    if not cli:
        raise RuntimeError("Codex CLI tidak ditemukan. Install @openai/codex lalu login dengan `codex login`.")
    with tempfile.TemporaryDirectory(prefix="kms-codex-") as temporary:
        answer = Path(temporary) / "answer.txt"
        command = [cli, "exec", "--json", "--sandbox", "read-only", "--ask-for-approval", "never",
                   "--output-last-message", str(answer)]
        if model:
            command.extend(["--model", model])
        command.append("-")
        use_shell = cli.lower().endswith((".cmd", ".bat"))
        completed = subprocess.run(command, input=prompt, text=True, encoding="utf-8", errors="replace",
                                   capture_output=True, timeout=timeout, check=False, shell=use_shell)
        if completed.returncode != 0:
            raise RuntimeError("Codex CLI gagal: " + (completed.stderr or completed.stdout)[-1500:])
        if not answer.exists() or not answer.read_text(encoding="utf-8").strip():
            raise RuntimeError("Codex CLI tidak menghasilkan final message. Periksa output `codex exec`.")
        return answer.read_text(encoding="utf-8").strip()


def fallback_page_dsl(page_number: int, events: list[dict[str, Any]]) -> str:
    """Loss-minimizing fallback for diagnosis; never gold-standard output."""
    output = [f"@PAGE {page_number}"]
    for event in events:
        if event["kind"] == "text":
            for line in event["text"].splitlines():
                line = line.strip()
                if not line:
                    continue
                if re.match(r"^BAB\s+[IVXLCDM]+\s*[–—-]\s*\S+", line, re.I):
                    output.append("@h1 " + line)
                else:
                    output.append(line)
        elif event["kind"] == "table":
            rows = event["rows"]
            output.append("@TABLE_START")
            if rows:
                output.append("KOLOM: " + " | ".join(rows[0]))
                output.extend(" | ".join(row) for row in rows[1:])
            output.append("@TABLE_END")
        else:
            output.append(f"@IMAGE [{event['filename']} | page {page_number}, y={event['anchor_y']:.1f}]")
    return "\n".join(output)


def validate_llm_output(text: str, page_events: dict[int, list[dict[str, Any]]]) -> str:
    text = text.strip()
    text = re.sub(r"^```(?:text|dsl|markdown)?\s*|\s*```$", "", text, flags=re.I).strip()
    expected_pages = [f"@PAGE {number}" for number in page_events]
    actual_pages = re.findall(r"^@PAGE\s+\d+\s*$", text, flags=re.M)
    actual_pages = [re.sub(r"\s+", " ", line.strip()) for line in actual_pages]
    if actual_pages != expected_pages:
        raise ValueError(f"Marker halaman tidak sesuai. Diharapkan {expected_pages}; didapat {actual_pages}.")
    expected_tokens = [event["token"] for events in page_events.values() for event in events if event["kind"] == "image"]
    actual_tokens = IMAGE_TOKEN_RE.findall(text)
    if Counter(actual_tokens) != Counter(expected_tokens):
        raise ValueError(f"Marker gambar berubah/hilang/duplikat: expected={expected_tokens}, actual={actual_tokens}")
    if text.count("@TABLE_START") != text.count("@TABLE_END"):
        raise ValueError("Marker tabel tidak berpasangan.")
    if re.search(r"^@h(\d+)", text, re.M) and any(int(n) > 5 for n in re.findall(r"^@h(\d+)", text, re.M)):
        raise ValueError("LLM menghasilkan heading lebih dalam daripada gold standard h5.")
    source_text = " ".join(
        event.get("text", "") if event["kind"] == "text" else
        " ".join(cell for row in event.get("rows", []) for cell in row) if event["kind"] == "table" else ""
        for events in page_events.values() for event in events
    )
    clean_output = IMAGE_TOKEN_RE.sub(" ", text)
    clean_output = re.sub(r"^\s*@PAGE\s+\d+\s*$", " ", clean_output, flags=re.M)
    clean_output = re.sub(r"^\s*@h\d+\s+", "", clean_output, flags=re.M)
    clean_output = re.sub(r"^\s*@TABLE_(?:START|END)\s*$", " ", clean_output, flags=re.M)
    clean_output = re.sub(r"^\s*@IMAGE\s+\[.*?\]\s*$", " ", clean_output, flags=re.M)
    clean_output = re.sub(r"^\s*KOLOM:\s*", "", clean_output, flags=re.M)
    source_counts = Counter(w.casefold() for w in re.findall(r"[\w]+", source_text, flags=re.UNICODE) if len(w) > 1)
    output_counts = Counter(w.casefold() for w in re.findall(r"[\w]+", clean_output, flags=re.UNICODE) if len(w) > 1)
    source_total = sum(source_counts.values())
    coverage = sum(min(count, output_counts[word]) for word, count in source_counts.items()) / source_total if source_total else 1.0
    if coverage < .78:
        raise ValueError(f"Pemeriksaan retensi teks gagal: hanya {coverage:.0%} token sumber dipertahankan (ambang 78%).")

    # Legal references and quantities are especially sensitive to small edits.
    number_pattern = r"(?<!\w)\d+(?:[./-]\d+)*(?!\w)"
    source_numbers = Counter(re.findall(number_pattern, source_text))
    output_numbers = Counter(re.findall(number_pattern, clean_output))
    missing_numbers = {
        number: count - output_numbers[number]
        for number, count in source_numbers.items()
        if output_numbers[number] < count
    }
    if missing_numbers:
        raise ValueError(f"Pemeriksaan preservasi angka gagal: angka/nomor sumber hilang atau berubah {missing_numbers}.")

    return text


def resolve_image_tokens(text: str, events: dict[int, list[dict[str, Any]]]) -> tuple[str, dict[str, dict[str, Any]]]:
    lookup = {event["token"]: event for page in events.values() for event in page if event["kind"] == "image"}
    metadata = {}
    def replace(match: re.Match[str]) -> str:
        event = lookup[match.group(1)]
        filename = event["filename"]
        metadata[filename] = {"token": event["token"], "anchor_y": event["anchor_y"]}
        return f"@IMAGE [{filename} | page {event['token'].split('I')[0][1:]}, y={event['anchor_y']:.1f}]"
    return IMAGE_TOKEN_RE.sub(replace, text), metadata


def write_docx(dsl: str, destination: Path, image_paths: dict[str, Path]) -> None:
    document = Document()
    document.core_properties.title = destination.stem.replace("_", " ")
    for line in dsl.splitlines():
        paragraph = document.add_paragraph()
        paragraph.paragraph_format.space_after = Inches(.02)
        match = re.match(r"^@IMAGE\s+\[([^|\]]+)(?:\|[^\]]*)?\]$", line.strip())
        if match:
            filename = match.group(1).strip()
            image = image_paths.get(filename)
            if image and image.exists():
                paragraph.add_run(line + "\n")
                paragraph.add_run().add_picture(str(image), width=Inches(5.8))
            else:
                paragraph.add_run(line)
        else:
            paragraph.add_run(line)
    document.save(destination)


def convert_one(pdf_path: Path, output_path: Path, args: argparse.Namespace, run_dir: Path) -> dict[str, Any]:
    image_dir = run_dir / (pdf_path.stem + "_images")
    image_dir.mkdir(parents=True, exist_ok=True)
    pdf = fitz.open(pdf_path)
    repeated = repeated_margin_text(pdf)
    page_events: dict[int, list[dict[str, Any]]] = {}
    images: dict[str, Path] = {}
    warnings = (["Provider heuristik aktif: output hanya untuk diagnosis ekstraksi dan tidak dinyatakan memenuhi gold standard."]
                if args.provider == "heuristic" else [])
    for page_number, page in enumerate(pdf, start=1):
        events, extracted = extract_page_events(page, page_number, repeated, image_dir, use_ocr=args.ocr)
        page_events[page_number] = events
        images.update(extracted)
        if not any(event["kind"] in {"text", "table"} for event in events):
            warnings.append(f"Page {page_number} has no extractable text/table; scanned source may need OCR." )
    pdf.close()

    output_parts = []
    prior_headings: list[str] = []
    pages = list(page_events)
    for start in range(0, len(pages), args.pages_per_call):
        page_ids = pages[start:start + args.pages_per_call]
        group = {number: page_events[number] for number in page_ids}
        prompt = make_prompt(group, prior_headings, use_vision=args.vision)
        try:
            if args.provider == "openai":
                page_images = []
                if args.vision:
                    source_doc = fitz.open(pdf_path)
                    try:
                        for number in page_ids:
                            pix = source_doc[number - 1].get_pixmap(matrix=fitz.Matrix(1.4, 1.4), alpha=False)
                            page_images.append(pix.tobytes("png"))
                    finally:
                        source_doc.close()
                raw = openai_response(prompt, args.model, args.base_url, page_images or None)
            elif args.provider == "codex":
                raw = codex_response(prompt, args.model, args.timeout)
            elif args.provider == "local":
                local_base_url = os.getenv("STRUCTURARAG_LOCAL_AI_BASE_URL", "http://127.0.0.1:11434/v1")
                local_model = os.getenv("STRUCTURARAG_LOCAL_AI_MODEL", "qwen2.5:7b-instruct")
                local_api_key = os.getenv("STRUCTURARAG_LOCAL_AI_API_KEY")
                raw = local_ai_response(
                    prompt, local_model, local_base_url, local_api_key, args.timeout
                )
            else:
                raw = ""
            converted = validate_llm_output(raw, group) if args.provider != "heuristic" else ""
            if args.provider == "heuristic":
                converted = "\n\n".join(fallback_page_dsl(n, group[n]) for n in page_ids)
        except Exception as exc:
            if not args.allow_fallback:
                raise
            warnings.append(f"Pages {page_ids}: LLM failed; low-confidence fallback used ({exc})")
            converted = "\n\n".join(fallback_page_dsl(n, group[n]) for n in page_ids)
        converted, _ = resolve_image_tokens(converted, group)
        output_parts.append(converted.strip())
        prior_headings.extend(re.findall(r"^@h\d+\s+.+$", converted, flags=re.M))

    full_dsl = "\n\n".join(output_parts).strip() + "\n"
    if args.provider != "heuristic" and full_dsl.count("@h0 ") != 1:
        raise RuntimeError(f"Pemeriksaan gold standard gagal: harus ada tepat satu @h0 judul utama; ditemukan {full_dsl.count('@h0 ')}.")
    if full_dsl.count("@TABLE_START") != full_dsl.count("@TABLE_END"):
        raise RuntimeError("Pemeriksaan akhir gagal: jumlah marker tabel tidak berpasangan.")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    write_docx(full_dsl, output_path, images)
    text_path = output_path.with_suffix(".txt")
    text_path.write_text(full_dsl, encoding="utf-8")
    manifest_path = output_path.with_suffix(".manifest.json")
    manifest_path.write_text(json.dumps({"source": str(pdf_path), "output": str(output_path),
                                         "pages": len(page_events), "images": list(images),
                                         "warnings": warnings}, ensure_ascii=False, indent=2), encoding="utf-8")
    status = "heuristic" if args.provider == "heuristic" else ("warning" if warnings else "ok")
    return {"source": str(pdf_path), "output": str(output_path), "pages": len(page_events),
            "images": len(images), "warnings": warnings, "status": status}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--provider", choices=("openai", "codex", "heuristic", "local"), default="openai")
    parser.add_argument("--model", default=os.getenv("OPENAI_MODEL", "gpt-4.1"), help="Responses API model or optional Codex CLI model")
    parser.add_argument("--base-url", default=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"))
    parser.add_argument("--pages-per-call", type=int, default=2)
    parser.add_argument("--timeout", type=int, default=300, help="Codex CLI timeout, seconds")
    parser.add_argument("--allow-fallback", action="store_true", help="Explicitly allow low-confidence local extraction when an LLM request fails")
    parser.add_argument("--ocr", action="store_true", help="OCR scan-only pages with local Tesseract (Indonesian + English language packs required)")
    parser.add_argument("--vision", action="store_true", help="Send rendered page images to OpenAI for visual layout/table interpretation (image tokens may add cost)")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--limit", type=int, help="Process at most N PDFs (for a controlled pilot)")
    args = parser.parse_args()
    if args.pages_per_call < 1:
        parser.error("--pages-per-call must be >= 1")
    if args.vision and args.provider != "openai":
        parser.error("--vision saat ini hanya tersedia dengan --provider openai")
    if args.provider == "local" and not os.getenv("STRUCTURARAG_LOCAL_AI_BASE_URL"):
        if os.getenv("VERCEL"):
            parser.error("Atur STRUCTURARAG_LOCAL_AI_BASE_URL ke endpoint HTTPS model lokal/self-hosted yang dapat diakses Vercel.")

    if not args.input_dir.is_dir():
        parser.error(f"Input directory not found: {args.input_dir}")
    pdfs = sorted(p for p in args.input_dir.glob("*.pdf") if not p.name.startswith("._"))
    if args.limit:
        pdfs = pdfs[:args.limit]
    if not pdfs:
        print(f"No PDF files found in {args.input_dir}", file=sys.stderr)
        return 2
    args.output_dir.mkdir(parents=True, exist_ok=True)
    run_dir = args.output_dir / ".work"
    run_dir.mkdir(exist_ok=True)
    results = []
    for index, source in enumerate(pdfs, 1):
        destination = args.output_dir / f"{source.stem}.docx"
        if destination.exists() and not args.overwrite:
            print(f"[{index}/{len(pdfs)}] SKIP (already exists): {destination.name}")
            continue
        print(f"[{index}/{len(pdfs)}] Converting {source.name} ...", flush=True)
        try:
            result = convert_one(source, destination, args, run_dir)
            results.append(result)
            print(f"    {result['status'].upper()} pages={result['pages']} images={result['images']} -> {destination.name}")
            for warning in result["warnings"]:
                print("    WARNING:", warning[:500])
        except Exception as exc:
            result = {"source": str(source), "status": "error", "error": str(exc)}
            results.append(result)
            print(f"    ERROR: {exc}", file=sys.stderr)
        with (args.output_dir / "batch-report.jsonl").open("a", encoding="utf-8") as report:
            report.write(json.dumps(result, ensure_ascii=False) + "\n")
    succeeded = sum(r["status"] in {"ok", "warning"} for r in results)
    failed = sum(r["status"] == "error" for r in results)
    print(f"Finished: {succeeded} converted, {failed} failed. Output: {args.output_dir}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
