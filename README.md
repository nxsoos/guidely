# Guidely

Guidely is a team knowledge assistant with a React/TypeScript interface and a FastAPI backend. Administrators upload small documents, index them, and manage reader accounts. Readers ask questions and inspect numbered source citations. Conversations, tags/categories, document editing, original downloads, query-log export, and metrics remain part of the application.

The deployment architecture uses **Vercel Hobby + Supabase Free PostgreSQL/pgvector/private Storage + Gemini API Free Tier**. The existing username/password login is retained with persistent database sessions. The browser does not receive backend credentials. Production does not depend on SQLite, Chroma, local uploads, or a background thread.

Follow **[DEPLOYMENT.md](DEPLOYMENT.md)** for exact setup, environment variables, migrations, secure administrator creation, free-plan limits, migration choices, and the hosted verification checklist. **The repository being prepared does not mean it has been deployed.**

## Run locally

Install Python 3.11 and Node.js 22. Configure a private root `.env` using `.env.example` and the Supabase setup in the deployment guide. Preserve your existing Gemini key. Apply migrations and create an administrator before launching:

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python -m backend.cli create-admin --username admin
.\.venv\Scripts\python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

In a second terminal:

```powershell
npm ci --prefix frontend
npm run dev --prefix frontend
```

Open `http://127.0.0.1:5173`. Start with the fictional Markdown files in `data/sample-docs/`. Upload, select Index, then ask a question. Editing text hides it from retrieval until re-indexing. Reader accounts cannot manage content or users.

## Data and document limits

The cloud database starts empty; existing `runtime/` data is preserved and is not automatically imported. Back it up before switching. See the deployment guide for re-upload and history limitations.

The demo caps originals at 1 MiB, PDFs at 10 pages, extracted text at 24,000 characters, and indexing at 12 chunks. Gemini embedding vectors have 768 dimensions and use cosine similarity. One indexing/mutation operation runs across server instances at a time. Failed or interrupted indexing supports explicit safe retries; no background worker runs after a request ends.

## Checks

```powershell
.\.venv\Scripts\python -m pip install -r requirements-dev.txt
.\.venv\Scripts\python -m pytest backend/tests -q
npm run build --prefix frontend
npm audit --prefix frontend
python scripts/check_secrets.py
```

Offline tests use isolated local adapters and deterministic fake embeddings. They test application behavior, not real semantic quality or hosted service integration. `data/evaluation.json` contains sample evaluation questions; perform real retrieval/answer-quality evaluation after configuring accounts and indexing sample files. Historical local benchmark numbers have not been carried forward as cloud deployment claims.

Never commit real environment files or keys. No resources are created, Git history rewritten, commits pushed, or paid billing enabled by this preparation.
