# E-Hukum RAG Document Tools

This workspace contains the gold-standard profiler, PDF-to-RAG-DOCX converter, and a single-user local web interface.

## Run the web app

In PowerShell, from this folder:

```powershell
.\.venv\Scripts\Activate.ps1
python -m pip install -r Tools_Formatting\requirements.txt
python -m pip install -r webapp\requirements.txt
codex login
.\webapp\start.ps1
```

Open <http://127.0.0.1:8000>. The web app calls the local Codex CLI OAuth session for page-group parsing. Start with one PDF, then manually review its DOCX and warnings before using it as a RAG source. More setup and OAuth/deployment boundaries are in [webapp/README.md](webapp/README.md).

## Privacy and deployment

Source PDFs, gold DOCX files, generated DOCX/XLSX files, the virtual environment, and local web-job data are excluded from Git. Review `git status` before any commit. The current web app is intentionally loopback-only and is not a production Vercel deployment: an online version needs durable storage, authentication, and a persistent worker, and remotely hosted use of ChatGPT-plan OAuth requires OpenAI access/eligibility.
