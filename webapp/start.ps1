$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot '.venv\Scripts\python.exe'

if (-not (Test-Path -LiteralPath $python)) {
    throw "Virtual environment not found. From the project root run: python -m venv .venv"
}

& $python -c "import fastapi, uvicorn, multipart" 2>$null
if ($LASTEXITCODE -ne 0) {
    throw "Web dependencies are missing. Run: .\.venv\Scripts\python.exe -m pip install -r webapp\requirements.txt"
}

Write-Host 'Starting E-Hukum RAG Converter on http://127.0.0.1:8000'
Write-Host 'Keep this window open. Stop the app with Ctrl+C.'
Push-Location $projectRoot
try {
    & $python -m uvicorn webapp.app:app --host 127.0.0.1 --port 8000
} finally {
    Pop-Location
}
