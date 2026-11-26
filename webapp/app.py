"""Local-first web interface for StructuraRAG's PDF preprocessing workflow.

Jobs can use the offline heuristic baseline or an optional authenticated AI
provider. The service binds to loopback and is not a multi-user deployment.
"""
from __future__ import annotations

import base64
import json
import os
import secrets
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

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

ROOT = Path(__file__).resolve().parents[1]
CONVERTER = ROOT / "Tools_Formatting" / "convert_pdf_batch.py"
DATA_ROOT = Path(os.getenv(
    "STRUCTURARAG_WEB_DATA_DIR",
    os.getenv("KMS_WEB_DATA_DIR", str(ROOT / ".webapp-data")),
)).resolve()
JOBS_DIR = DATA_ROOT / "jobs"
DB_PATH = DATA_ROOT / "jobs.sqlite3"
MAX_UPLOAD_BYTES = int(os.getenv(
    "STRUCTURARAG_MAX_UPLOAD_BYTES",
    os.getenv("KMS_MAX_UPLOAD_BYTES", str(50 * 1024 * 1024)),
))
VERCEL_MAX_UPLOAD_BYTES = int(os.getenv("STRUCTURARAG_VERCEL_MAX_UPLOAD_BYTES", str(4 * 1024 * 1024)))
VERCEL_CONVERT_TIMEOUT = min(int(os.getenv("STRUCTURARAG_VERCEL_CONVERT_TIMEOUT", "240")), 270)
IS_VERCEL = os.getenv("VERCEL") == "1"

app = FastAPI(title="StructuraRAG", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=Path(__file__).with_name("static")), name="static")

_queue: queue.Queue[str] = queue.Queue()
_worker_started = False
_worker_lock = threading.Lock()


@app.middleware("http")
async def local_request_guard(request, call_next):
    """Apply loopback-only checks locally and host/password checks on Vercel."""
    host = request.headers.get("host", "").split(":", 1)[0].strip("[]").lower()
    origin = request.headers.get("origin")

    if IS_VERCEL:
        allowed_hosts = {
            value.strip().lower()
            for value in os.getenv("STRUCTURARAG_ALLOWED_HOSTS", "").split(",")
            if value.strip()
        }
        vercel_host = os.getenv("VERCEL_URL", "").split(":", 1)[0].lower()
        if vercel_host:
            allowed_hosts.add(vercel_host)
        if not host.endswith(".vercel.app") and host not in allowed_hosts:
            return JSONResponse({"detail": "Host tidak diizinkan."}, status_code=403)

        # Optional HTTP Basic protection. Configure STRUCTURARAG_ACCESS_PASSWORD
        # before exposing a deployment that processes private documents.
        expected_password = os.getenv("STRUCTURARAG_ACCESS_PASSWORD", "")
        if expected_password:
            auth = request.headers.get("authorization", "")
            scheme, _, encoded = auth.partition(" ")
            try:
                decoded = base64.b64decode(encoded, validate=True).decode("utf-8") if scheme.lower() == "basic" else ""
                username, separator, password = decoded.partition(":")
            except (ValueError, UnicodeDecodeError):
                username, separator, password = "", "", ""
            expected_user = os.getenv("STRUCTURARAG_ACCESS_USERNAME", "structurarag")
            if (
                not separator
                or not secrets.compare_digest(username, expected_user)
                or not secrets.compare_digest(password, expected_password)
            ):
                return JSONResponse(
                    {"detail": "Authentication required."},
                    status_code=401,
                    headers={"WWW-Authenticate": 'Basic realm="StructuraRAG", charset="UTF-8"'},
                )

        if request.method in {"POST", "PUT", "PATCH", "DELETE"} and origin:
            origin_host = (urlparse(origin).hostname or "").lower()
            if origin_host != host:
                return JSONResponse({"detail": "Origin tidak diizinkan."}, status_code=403)
    else:
        if host not in {"127.0.0.1", "localhost"}:
            return JSONResponse({"detail": "Aplikasi ini hanya menerima koneksi lokal."}, status_code=403)
        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            if request.headers.get("x-kms-request") != "1":
                return JSONResponse({"detail": "Permintaan tidak valid."}, status_code=403)
            if origin and (urlparse(origin).hostname or "").lower() not in {"127.0.0.1", "localhost"}:
                return JSONResponse({"detail": "Origin tidak diizinkan."}, status_code=403)
    return await call_next(request)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _local_ai_base_url() -> str:
    configured = os.getenv("STRUCTURARAG_LOCAL_AI_BASE_URL", "").strip()
    if configured:
        return configured.rstrip("/")
    return "" if IS_VERCEL else "http://127.0.0.1:11434/v1"


def _local_ai_configured() -> bool:
    base_url = _local_ai_base_url()
    if not base_url:
        return False
    parsed = urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return False
    if IS_VERCEL:
        if parsed.scheme != "https" or parsed.hostname.lower() in {"localhost", "127.0.0.1", "::1"}:
            return False
    return True


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
                provider TEXT NOT NULL DEFAULT 'codex',
                warnings_json TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )"""
        )
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(jobs)").fetchall()}
        if "provider" not in columns:
            connection.execute("ALTER TABLE jobs ADD COLUMN provider TEXT NOT NULL DEFAULT 'codex'")
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
        "provider": row["provider"],
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
    provider = row["provider"] if row["provider"] in {"heuristic", "local", "codex", "openai"} else "heuristic"
    provider_label = {"heuristic": "Rule-Based", "local": "AI Lokal", "codex": "Codex AI", "openai": "OpenAI API"}[provider]
    _set_job(job_id, status="running", message=f"Mengekstrak PDF dan menyusun struktur RAG dengan mode {provider_label}…")
    if not CONVERTER.is_file():
        _set_job(job_id, status="failed", message="Skrip konverter tidak ditemukan.")
        return

    command = [
        sys.executable, str(CONVERTER), "--provider", provider,
        "--input-dir", str(source_dir), "--output-dir", str(output_dir),
        "--limit", "1", "--pages-per-call", os.getenv(
            "STRUCTURARAG_PAGES_PER_CALL", os.getenv("KMS_PAGES_PER_CALL", "2")
        ),
    ]
    codex_model = os.getenv("CODEX_MODEL", "").strip() if provider == "codex" else ""
    if codex_model:
        command.extend(["--model", codex_model])
    if os.getenv("STRUCTURARAG_ENABLE_OCR", os.getenv("KMS_ENABLE_OCR", "0")) == "1":
        command.append("--ocr")
    process_env = os.environ.copy()
    if provider == "local":
        process_env["STRUCTURARAG_LOCAL_AI_BASE_URL"] = _local_ai_base_url()
    if provider == "codex" and not codex_model:
        process_env["OPENAI_MODEL"] = ""
    try:
        result = subprocess.run(command, cwd=ROOT, env=process_env, capture_output=True,
                                text=True, encoding="utf-8", errors="replace", timeout=7200, check=False)
    except subprocess.TimeoutExpired:
        _set_job(job_id, status="failed", message="Konversi melewati batas waktu 2 jam; coba PDF yang lebih kecil.")
        return
    except OSError as exc:
        _set_job(job_id, status="failed", message=f"Tidak dapat menjalankan provider {provider}: {exc}")
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
    # Vercel Functions are request-driven and may be recycled at any time.
    # The local queue/SQLite worker is only used by the persistent local app.
    if not IS_VERCEL:
        _ensure_worker()


@app.get("/", response_class=HTMLResponse)
def home() -> FileResponse:
    return FileResponse(Path(__file__).with_name("static") / "index.html")


@app.get("/api/health")
def health() -> dict[str, Any]:
    if not IS_VERCEL:
        _ensure_worker()
    return {
        "status": "ok",
        "runtime": "vercel" if IS_VERCEL else "local",
        "providers": {
            "heuristic": {"available": True, "description": "Deterministic baseline; no AI login required."},
            "local": {
                "available": _local_ai_configured(),
                "configured": _local_ai_configured(),
                "description": "Ollama or another OpenAI-compatible self-hosted model endpoint.",
            },
            "cloud_oauth": {
                "available": False,
                "configured": False,
                "provider": "Sign in with ChatGPT",
                "reason": "Remote-hosted ChatGPT plan inference requires OpenAI approval. OAuth identity sign-in alone does not grant model inference access.",
            },
            "codex": _codex_status(),
            "openai": {"configured": bool(os.getenv("OPENAI_API_KEY") or os.getenv("OPENAI_BEARER_TOKEN"))},
        },
        "max_upload_bytes": VERCEL_MAX_UPLOAD_BYTES if IS_VERCEL else MAX_UPLOAD_BYTES,
        "access_protected": bool(os.getenv("STRUCTURARAG_ACCESS_PASSWORD")) if IS_VERCEL else True,
    }


@app.post("/api/jobs", status_code=202)
async def create_job(
    file: UploadFile = File(...),
    provider: str = Form("heuristic"),
) -> dict[str, Any]:
    if IS_VERCEL:
        raise HTTPException(status_code=410, detail="Vercel deployment uses stateless /api/convert, not the local background-job queue.")
    _ensure_worker()
    if provider == "cloud_oauth":
        raise HTTPException(status_code=503, detail="AI Cloud OAuth belum diaktifkan. Untuk deployment jarak jauh, akses ChatGPT plan inference perlu persetujuan OpenAI.")
    if provider not in {"heuristic", "local", "codex", "openai"}:
        raise HTTPException(status_code=400, detail="Provider tidak dikenal.")
    if provider == "local" and not _local_ai_configured():
        raise HTTPException(status_code=503, detail="AI Lokal belum dikonfigurasi. Atur STRUCTURARAG_LOCAL_AI_BASE_URL.")
    if provider == "codex":
        codex = _codex_status()
        if not codex["available"] or not codex["authenticated"]:
            raise HTTPException(status_code=503, detail=codex["message"])
    if provider == "openai" and not (os.getenv("OPENAI_API_KEY") or os.getenv("OPENAI_BEARER_TOKEN")):
        raise HTTPException(status_code=503, detail="OPENAI_API_KEY atau OPENAI_BEARER_TOKEN belum dikonfigurasi pada server lokal.")
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
            "INSERT INTO jobs(id, source_name, status, message, provider, created_at, updated_at) VALUES (?, ?, 'queued', ?, ?, ?, ?)",
            (job_id, source_name, "PDF masuk antrean.", provider, timestamp, timestamp),
        )
    _queue.put(job_id)
    row = _fetch_job(job_id)
    assert row is not None
    return _job_dict(row)


@app.post("/api/convert")
async def convert_vercel(file: UploadFile = File(...), provider: str = Form("heuristic")) -> Response:
    """Synchronous, stateless conversion route for Vercel Functions."""
    if not IS_VERCEL:
        raise HTTPException(status_code=404, detail="Endpoint ini hanya digunakan pada deployment Vercel.")
    if provider not in {"heuristic", "local"}:
        if provider == "cloud_oauth":
            raise HTTPException(
                status_code=503,
                detail="AI Cloud OAuth belum tersedia untuk remote-hosted deployment. OpenAI approval dan implementasi token/session storage masih diperlukan.",
            )
        raise HTTPException(status_code=400, detail="Pilih Rule-Based atau AI Lokal untuk deployment Vercel.")
    if provider == "local" and not _local_ai_configured():
        raise HTTPException(
            status_code=503,
            detail="AI Lokal belum siap. Atur STRUCTURARAG_LOCAL_AI_BASE_URL ke endpoint HTTPS Ollama/OpenAI-compatible yang dapat dijangkau Vercel.",
        )

    raw = await file.read(VERCEL_MAX_UPLOAD_BYTES + 1)
    await file.close()
    if not raw:
        raise HTTPException(status_code=400, detail="File PDF kosong.")
    if len(raw) > VERCEL_MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"Ukuran PDF melewati batas deployment Vercel ({VERCEL_MAX_UPLOAD_BYTES // (1024 * 1024)} MiB).",
        )
    if not raw.startswith(b"%PDF-"):
        raise HTTPException(status_code=415, detail="Isi berkas bukan PDF yang valid.")

    source_name = _safe_filename(file.filename or "document.pdf")
    with tempfile.TemporaryDirectory(prefix="structurarag-vercel-") as temporary:
        work_root = Path(temporary)
        input_dir = work_root / "input"
        output_dir = work_root / "output"
        input_dir.mkdir()
        output_dir.mkdir()
        (input_dir / source_name).write_bytes(raw)
        command = [
            sys.executable, str(CONVERTER),
            "--provider", provider,
            "--input-dir", str(input_dir),
            "--output-dir", str(output_dir),
            "--limit", "1",
            "--pages-per-call", os.getenv("STRUCTURARAG_PAGES_PER_CALL", "1"),
        ]
        if os.getenv("STRUCTURARAG_ENABLE_OCR", "0") == "1":
            command.append("--ocr")
        process_env = os.environ.copy()
        if provider == "local":
            process_env["STRUCTURARAG_LOCAL_AI_BASE_URL"] = _local_ai_base_url()
        try:
            result = subprocess.run(
                command, cwd=ROOT, env=process_env, capture_output=True,
                text=True, encoding="utf-8", errors="replace",
                timeout=VERCEL_CONVERT_TIMEOUT, check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise HTTPException(
                status_code=504,
                detail="Konversi melewati batas waktu Vercel. Gunakan PDF lebih kecil atau layanan worker khusus untuk dokumen panjang.",
            ) from exc
        except OSError as exc:
            raise HTTPException(status_code=500, detail=f"Converter tidak dapat dijalankan: {exc}") from exc

        report_path = output_dir / "batch-report.jsonl"
        report: dict[str, Any] = {}
        if report_path.exists():
            try:
                entries = report_path.read_text(encoding="utf-8").splitlines()
                if entries:
                    report = json.loads(entries[-1])
            except (OSError, json.JSONDecodeError):
                report = {}
        output_path = output_dir / f"{Path(source_name).stem}.docx"
        if result.returncode != 0 or not output_path.is_file():
            detail = (report.get("error") or result.stderr or result.stdout or "Konversi gagal.").strip()
            raise HTTPException(status_code=422, detail=detail[-1500:])
        output_bytes = output_path.read_bytes()
        output_filename = output_path.name
        if len(output_bytes) > 4 * 1024 * 1024:
            raise HTTPException(
                status_code=413,
                detail="DOCX hasil melebihi batas respons Function. Gunakan PDF yang lebih kecil atau deployment dengan penyimpanan objek dan worker.",
            )

    warnings = report.get("warnings", [])
    headers = {
        "Content-Disposition": f'attachment; filename="{output_filename}"',
        "Cache-Control": "no-store, private",
        "X-StructuraRAG-Provider": provider,
        "X-StructuraRAG-Warnings": str(len(warnings)),
    }
    return Response(
        content=output_bytes,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers=headers,
    )


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str) -> dict[str, Any]:
    if IS_VERCEL:
        raise HTTPException(status_code=410, detail="Vercel uses stateless /api/convert and does not retain job history.")
    _ensure_worker()
    if not re.fullmatch(r"[0-9a-f]{32}", job_id):
        raise HTTPException(status_code=404, detail="Job tidak ditemukan.")
    row = _fetch_job(job_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Job tidak ditemukan.")
    return _job_dict(row)


@app.get("/api/jobs")
def list_jobs() -> list[dict[str, Any]]:
    if IS_VERCEL:
        raise HTTPException(status_code=410, detail="Vercel uses stateless /api/convert and does not retain job history.")
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
