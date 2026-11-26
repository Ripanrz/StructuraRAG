"""Local web interface for the RAG-ready legal PDF converter.

The web process calls the existing converter with the locally authenticated
Codex CLI. It deliberately binds to loopback by default: this prototype is
not an internet-facing multi-user service.
"""
from __future__ import annotations

import json
import os
import queue
import re
import shutil
import sqlite3
import subprocess
import sys
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

ROOT = Path(__file__).resolve().parents[1]
CONVERTER = ROOT / "Tools_Formatting" / "convert_pdf_batch.py"
DATA_ROOT = Path(os.getenv("KMS_WEB_DATA_DIR", str(ROOT / ".webapp-data"))).resolve()
JOBS_DIR = DATA_ROOT / "jobs"
DB_PATH = DATA_ROOT / "jobs.sqlite3"
MAX_UPLOAD_BYTES = int(os.getenv("KMS_MAX_UPLOAD_BYTES", str(50 * 1024 * 1024)))

app = FastAPI(title="StructuraRAG", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=Path(__file__).with_name("static")), name="static")

_queue: queue.Queue[str] = queue.Queue()
_worker_started = False
_worker_lock = threading.Lock()


@app.middleware("http")
async def local_request_guard(request, call_next):
    """Keep this single-user prototype on loopback and reject cross-site posts."""
    host = request.headers.get("host", "").split(":", 1)[0].strip("[]").lower()
    if host not in {"127.0.0.1", "localhost"}:
        return JSONResponse({"detail": "Aplikasi ini hanya menerima koneksi lokal."}, status_code=403)
    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        if request.headers.get("x-kms-request") != "1":
            return JSONResponse({"detail": "Permintaan tidak valid."}, status_code=403)
        origin = request.headers.get("origin")
        if origin and urlparse(origin).hostname not in {"127.0.0.1", "localhost"}:
            return JSONResponse({"detail": "Origin tidak diizinkan."}, status_code=403)
    return await call_next(request)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connect() -> sqlite3.Connection:
    DATA_ROOT.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH, timeout=30)
    connection.row_factory = sqlite3.Row
    return connection


def _init_db() -> None:
    with _connect() as connection:
        connection.execute(
            """CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY,
                source_name TEXT NOT NULL,
                status TEXT NOT NULL,
                message TEXT NOT NULL,
                output_name TEXT,
                warnings_json TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )"""
        )
        connection.execute(
            "UPDATE jobs SET status='failed', message='Server restarted while this job was running.', updated_at=? WHERE status='running'",
            (_now(),),
        )
        queued = connection.execute("SELECT id FROM jobs WHERE status='queued'").fetchall()
    for row in queued:
        _queue.put(row["id"])


def _fetch_job(job_id: str) -> sqlite3.Row | None:
    with _connect() as connection:
        return connection.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()


def _set_job(job_id: str, *, status: str, message: str, output_name: str | None = None,
             warnings: list[str] | None = None) -> None:
    with _connect() as connection:
        connection.execute(
            "UPDATE jobs SET status=?, message=?, output_name=COALESCE(?, output_name), warnings_json=COALESCE(?, warnings_json), updated_at=? WHERE id=?",
            (status, message, output_name,
             json.dumps(warnings, ensure_ascii=False) if warnings is not None else None,
             _now(), job_id),
        )


def _job_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"], "source_name": row["source_name"], "status": row["status"],
        "message": row["message"], "output_name": row["output_name"],
        "warnings": json.loads(row["warnings_json"]),
        "created_at": row["created_at"], "updated_at": row["updated_at"],
    }


def _safe_filename(name: str) -> str:
    leaf = Path(name.replace("\\", "/")).name
    cleaned = re.sub(r"[^A-Za-z0-9._ -]", "_", leaf).strip(" .")
    if not cleaned or cleaned in {".", ".."}:
        cleaned = "source.pdf"
    if not cleaned.lower().endswith(".pdf"):
        cleaned += ".pdf"
    return cleaned[:180]


def _codex_status() -> dict[str, Any]:
    cli = shutil.which(os.getenv("CODEX_CLI", "codex"))
    if not cli:
        return {"available": False, "authenticated": False, "message": "Codex CLI belum ditemukan di PATH."}
    try:
        result = subprocess.run([cli, "login", "status"], capture_output=True, text=True,
                                timeout=10, check=False, cwd=ROOT)
    except (OSError, subprocess.TimeoutExpired):
        return {"available": True, "authenticated": False, "message": "Status login Codex tidak dapat diperiksa."}
    authenticated = result.returncode == 0
    return {
        "available": True, "authenticated": authenticated,
        "message": "OAuth Codex aktif di mesin ini." if authenticated else "Belum login. Jalankan codex login di terminal mesin ini.",
    }


def _run_job(job_id: str) -> None:
    row = _fetch_job(job_id)
    if row is None:
        return
    job_dir = JOBS_DIR / job_id
    source_dir = job_dir / "source"
    output_dir = job_dir / "output"
    output_name = f"{Path(row['source_name']).stem}.docx"
    output_path = output_dir / output_name
    _set_job(job_id, status="running", message="Mengekstrak PDF dan menyusun struktur RAG dengan Codex…")
    if not CONVERTER.is_file():
        _set_job(job_id, status="failed", message="Skrip konverter tidak ditemukan.")
        return

    command = [
        sys.executable, str(CONVERTER), "--provider", "codex",
        "--input-dir", str(source_dir), "--output-dir", str(output_dir),
        "--limit", "1", "--pages-per-call", os.getenv("KMS_PAGES_PER_CALL", "2"),
    ]
    codex_model = os.getenv("CODEX_MODEL", "").strip()
    if codex_model:
        command.extend(["--model", codex_model])
    if os.getenv("KMS_ENABLE_OCR", "0") == "1":
        command.append("--ocr")
    process_env = os.environ.copy()
    if not codex_model:
        process_env["OPENAI_MODEL"] = ""
    try:
        result = subprocess.run(command, cwd=ROOT, env=process_env, capture_output=True,
                                text=True, encoding="utf-8", errors="replace", timeout=7200, check=False)
    except subprocess.TimeoutExpired:
        _set_job(job_id, status="failed", message="Konversi melewati batas waktu 2 jam; coba PDF yang lebih kecil.")
        return
    except OSError as exc:
        _set_job(job_id, status="failed", message=f"Tidak dapat menjalankan Codex CLI: {exc}")
        return

    report_path = output_dir / "batch-report.jsonl"
    report: dict[str, Any] = {}
    if report_path.exists():
        try:
            lines = report_path.read_text(encoding="utf-8").splitlines()
            if lines:
                report = json.loads(lines[-1])
        except (OSError, json.JSONDecodeError):
            pass
    if result.returncode != 0 or not output_path.is_file():
        detail = (report.get("error") or result.stderr or result.stdout or "Konversi gagal.").strip()
        _set_job(job_id, status="failed", message=detail[-1200:])
        return
    warnings = report.get("warnings", [])
    message = "DOCX siap diunduh." if not warnings else "DOCX selesai, tetapi ada catatan yang perlu ditinjau."
    _set_job(job_id, status="completed", message=message, output_name=output_name,
             warnings=[str(item)[:500] for item in warnings])


def _worker_loop() -> None:
    while True:
        job_id = _queue.get()
        try:
            _run_job(job_id)
        except Exception as exc:
            _set_job(job_id, status="failed", message=f"Kesalahan internal: {str(exc)[:1000]}")
        finally:
            _queue.task_done()


def _ensure_worker() -> None:
    global _worker_started
    with _worker_lock:
        if _worker_started:
            return
        _init_db()
        threading.Thread(target=_worker_loop, name="rag-converter", daemon=True).start()
        _worker_started = True


@app.on_event("startup")
def startup() -> None:
    _ensure_worker()


@app.get("/", response_class=HTMLResponse)
def home() -> FileResponse:
    return FileResponse(Path(__file__).with_name("static") / "index.html")


@app.get("/api/health")
def health() -> dict[str, Any]:
    _ensure_worker()
    return {"status": "ok", "provider": "Codex OAuth via local CLI", "codex": _codex_status(),
            "max_upload_bytes": MAX_UPLOAD_BYTES}


@app.post("/api/jobs", status_code=202)
async def create_job(file: UploadFile = File(...)) -> dict[str, Any]:
    _ensure_worker()
    codex = _codex_status()
    if not codex["available"] or not codex["authenticated"]:
        raise HTTPException(status_code=503, detail=codex["message"])
    source_name = _safe_filename(file.filename or "source.pdf")
    job_id = uuid.uuid4().hex
    job_dir = JOBS_DIR / job_id
    source_dir = job_dir / "source"
    source_dir.mkdir(parents=True, exist_ok=False)
    source_path = source_dir / source_name
    total = 0
    header = b""
    try:
        with source_path.open("wb") as target:
            while chunk := await file.read(1024 * 1024):
                if len(header) < 8:
                    header += chunk[:8 - len(header)]
                total += len(chunk)
                if total > MAX_UPLOAD_BYTES:
                    shutil.rmtree(job_dir, ignore_errors=True)
                    raise HTTPException(status_code=413, detail=f"Ukuran maksimal {MAX_UPLOAD_BYTES // (1024 * 1024)} MB.")
                target.write(chunk)
    except HTTPException:
        raise
    except OSError as exc:
        shutil.rmtree(job_dir, ignore_errors=True)
        raise HTTPException(status_code=500, detail="Gagal menyimpan PDF pada mesin ini.") from exc
    finally:
        await file.close()
    if not header.startswith(b"%PDF-"):
        shutil.rmtree(job_dir, ignore_errors=True)
        raise HTTPException(status_code=415, detail="Isi berkas bukan PDF yang valid.")

    timestamp = _now()
    with _connect() as connection:
        connection.execute(
            "INSERT INTO jobs(id, source_name, status, message, created_at, updated_at) VALUES (?, ?, 'queued', ?, ?, ?)",
            (job_id, source_name, "PDF masuk antrean.", timestamp, timestamp),
        )
    _queue.put(job_id)
    row = _fetch_job(job_id)
    assert row is not None
    return _job_dict(row)


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str) -> dict[str, Any]:
    _ensure_worker()
    if not re.fullmatch(r"[0-9a-f]{32}", job_id):
        raise HTTPException(status_code=404, detail="Job tidak ditemukan.")
    row = _fetch_job(job_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Job tidak ditemukan.")
    return _job_dict(row)


@app.get("/api/jobs")
def list_jobs() -> list[dict[str, Any]]:
    _ensure_worker()
    with _connect() as connection:
        rows = connection.execute("SELECT * FROM jobs ORDER BY created_at DESC LIMIT 20").fetchall()
    return [_job_dict(row) for row in rows]


@app.get("/api/jobs/{job_id}/download")
def download_job(job_id: str) -> FileResponse:
    job = get_job(job_id)
    if job["status"] != "completed" or not job["output_name"]:
        raise HTTPException(status_code=409, detail="DOCX belum siap.")
    path = JOBS_DIR / job_id / "output" / job["output_name"]
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Berkas hasil tidak ditemukan.")
    return FileResponse(path, media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                        filename=job["output_name"])
