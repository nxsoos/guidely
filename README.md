# Guidely

Guidely is a local knowledge assistant for a team. Upload company guides, ask a question in everyday language, and read an answer with document references you can inspect.

It includes a React/TypeScript website, a FastAPI backend, reader/admin accounts, document editing and indexing, source snippets, conversation history, tags and categories, query-log export, and operational metrics.

## Start on Windows

Install Python 3.11 and Node.js 22 or newer. Run commands from the project root unless a command says otherwise. These instructions use the virtual environment directly, so PowerShell activation is not required.

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt -c requirements-lock.txt
Copy-Item .env.example .env
```

Gemini is the default AI provider. Create a key in [Google AI Studio](https://aistudio.google.com/apikey), then edit `.env`:

```env
GUIDELY_PROVIDER=gemini
GEMINI_API_KEY=paste_your_google_key_here
GEMINI_EMBEDDING_MODEL=gemini-embedding-001
GEMINI_CHAT_MODEL=gemini-2.5-flash-lite
```

Keep the key on the backend; never put it in frontend files or commit `.env`. Gemini offers free-tier access to selected models subject to account, region, and quota limits; it is not unlimited or guaranteed. Check [Google pricing](https://ai.google.dev/gemini-api/docs/pricing) and your AI Studio limits. Free-tier content may be used to improve Google products, so use the fictional sample documents when learning. Relevant passages and bounded conversation context are sent to the selected provider.

To retain OpenAI instead, set `GUIDELY_PROVIDER=openai` and configure `OPENAI_API_KEY`, `OPENAI_EMBEDDING_MODEL` (default `text-embedding-3-small`), and `OPENAI_CHAT_MODEL` (default `gpt-4.1-mini`). OpenAI billing is separate from Gemini. No additional Python dependencies are needed for Gemini.

Create your administrator account. The command prompts for a password of 10–128 characters without displaying it:

```powershell
.\.venv\Scripts\python -m backend.cli create-admin --username admin
```

Start the backend in the first terminal:

```powershell
.\.venv\Scripts\python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

Start the website in a second terminal:

```powershell
cd frontend
npm ci
npm run dev
```

Open **http://127.0.0.1:5173** and sign in with the account you created. Keep using `127.0.0.1` consistently for cookies. The frontend proxies API requests to the backend. Do not start multiple backend worker processes against the same data directory.

### First walkthrough

1. Open **Documents** and upload the five Markdown files in `data/sample-docs/`.
2. Select **Index** for each file and wait for **ready**. Uploading alone does not make a file searchable.
3. Open **Ask Guidely** and ask “How early should I request time off?”
4. Expand a numbered source to inspect the supporting passage or download its original file.
5. Ask a follow-up such as “Who approves it?” Reopen the conversation from the sidebar later.
6. In **Documents**, edit a document's extracted text, category, or comma-separated tags. Changed text is hidden from search until re-indexed.
7. Use **People & access** to create reader/admin accounts, change roles, or reset passwords.
8. Use **Activity** to inspect counts and latency or download the query log as CSV.

For a local password recovery:

```powershell
.\.venv\Scripts\python -m backend.cli reset-password --username admin
```

Password resets invalidate that user's sessions. The last administrator cannot be demoted. There is no public registration or email-based recovery.

### Offline workflow demo

To try uploads and the interface without an API key, set `GUIDELY_PROVIDER=fake` in `.env`, then restart the backend. A prominent banner identifies this mode. It uses deterministic word hashing and repeats a retrieved passage; it is **not real AI or a valid semantic-quality benchmark**. Fake and real embeddings use different Chroma collections. Switch back to `gemini` (or `openai`) and re-index documents for real AI.

## How it works

```text
Upload → extract readable text → split into overlapping passages
       → create/cache embeddings → persist in Chroma

Question → resolve follow-up context → create/cache question embedding
         → retrieve matching passages → request a grounded AI answer
         → validate citation IDs → show answer, references, and ranked passages
```

An embedding is a numerical representation of text used to compare meaning. The LLM (large language model) writes the readable answer from retrieved passages. The system does not train its own language model.

- **Parsing:** UTF-8 TXT/Markdown and PDFs with selectable text, up to 10 MB. Empty, corrupt, encrypted, and image-only PDFs receive actionable errors. Extracted text is limited to two million characters. Scanned-document recognition is excluded.
- **Chunking:** heading-aware passages up to approximately 700 tokens, with 100-token overlap within long sections. PDF page numbers and Markdown headings are retained. Empty heading-only sections are skipped.
- **Indexing:** one background worker, persistent jobs, safe retry, and startup recovery of interrupted jobs. Text edits immediately mark a document changed. Replacement vectors are not exposed until indexing succeeds.
- **Caching:** document and question embeddings have separate counters and cache keys containing the provider, embedding model, text, and cache kind. Unchanged indexed files are skipped. Answer generation is never cached, so latency measurements include the hosted model.
- **Retrieval:** cosine similarity, top five passages, optional category and all-selected-tags filters. `GUIDELY_MIN_SIMILARITY` defaults to **0.25 provisionally**; calibrate it with the live evaluation tool below. Changing the provider or embedding model requires re-indexing all documents. Provider/model-specific collections prevent OpenAI, Gemini, and fake vectors from being mixed.
- **Answers:** JSON-schema responses, server-provided source IDs, inline citation checks, insufficient-evidence errors, and protection against displaying an answer if a source changes while it is generated. Valid source IDs do not prove every claim is true; human review remains necessary.
- **History:** each user owns their conversations. Only the last four exchanges, with bounded answer lengths, are used to rewrite follow-ups for retrieval. Documents are shared among authenticated users.

## Project layout and storage

| Location | Responsibility |
|---|---|
| `frontend/` | React interface, Vite proxy, TypeScript, Playwright workflows |
| `backend/` | API, authentication, parsing, provider interface, indexing and search services, tests |
| `data/sample-docs/` | Five fictional Cedarworks company documents; no actual company data |
| `data/evaluation.json` | Twenty paraphrased questions, expected files, sections, and evidence |
| `runtime/` | Ignored local SQLite database, Chroma vectors, original uploads, and evaluation results |

SQLite stores accounts, hashed sessions, document text/metadata, indexing jobs, embedding caches, conversations, counters, and query logs. Chroma stores passage vectors and metadata. Original uploads are retained unchanged; editing changes the searchable extracted text. Stop the backend before backing up the entire runtime directory. There are no pre-existing schemas or migrations to apply for this initial release.

The SQLite database uses WAL mode and parameterized queries. Passwords use scrypt with random salts. Session tokens are random, stored hashed, expire after 24 hours, and are sent in HTTP-only, SameSite=Strict cookies. Mutating requests require `X-Guidely: 1`; cross-origin access is not enabled. The local HTTP default uses `GUIDELY_COOKIE_SECURE=false`; this project is configured for localhost, not public hosting.

## API

Interactive API documentation: **http://127.0.0.1:8000/docs**. For manual writes in Swagger, supply the `X-Guidely: 1` header using a request client, or use browser requests from the website. The session cookie is required except for login and health.

| Method and path | Access | Behavior |
|---|---|---|
| `POST /api/auth/login`, `POST /api/auth/logout`, `GET /api/auth/me` | Login/public; otherwise current session | Sign in/out and current identity |
| `GET /api/users`, `POST /api/users`, `PATCH /api/users/{id}` | Admin | List/create accounts, role changes, password resets |
| `GET /api/documents`, `GET /api/documents/{id}` | Signed in | Metadata and extracted text; readers open ready documents only |
| `GET /api/documents/{id}/original` | Signed in | Download original; readers access ready documents only |
| `POST /api/documents`, `PATCH /api/documents/{id}` | Admin | Multipart upload; edit extracted text, tags, category |
| `POST /api/documents/{id}/index`, `GET /api/index-jobs/{id}` | Admin | Generate/persist embeddings; inspect job state and timing |
| `POST /api/search` | Signed in | Retrieve stored passages with similarity scores |
| `POST /api/questions` | Signed in | Answer with validated sources and optional conversation context |
| `GET /api/conversations`, `GET/DELETE /api/conversations/{id}` | Owner | List, reopen, or delete conversations |
| `GET /api/query-logs/export` | Admin | CSV with timestamp, question, latency, retrieved sources, outcome |
| `GET /health` | Public | Storage readiness, worker readiness, provider configuration status |
| `GET /metrics` | Admin | Counts, median/p95 latency, cache counters, and error counts |

Search/question input: `{ "question": "How do I request leave?", "tags": [], "category": "", "conversation_id": null }`. A question response contains `answer`, `conversation_id`, `references`, `passages`, and `elapsed_ms`. Sources include filename, document/chunk IDs, snippet, section, optional page, similarity score, and source revision information.

Errors follow `{ "error": { "code": "no_results", "message": "..." } }`. Invalid input returns 422; authentication/permissions use 401/403; missing results use 404; indexing conflicts use 409; unsupported files use 415; file limits use 413; provider errors use 502/503/504. Detailed stack traces stay on the backend. The CSV export escapes question cells that could be interpreted as spreadsheet formulas.

## Automated verification

From the project root:

```powershell
.\.venv\Scripts\python -m pytest -q
cd frontend
npm run build
npx playwright install chromium
npm run test:e2e
```

Playwright starts isolated backend/frontend servers on ports **8001/5174** and creates test-only accounts/data under `runtime/browser-tests/`. It never changes regular uploaded documents. Leave those ports free. Test traces are retained on failure. Backend tests use temporary storage and a deterministic fake provider; no API key or paid calls are required.

## Live evaluation and human review

The automated suite checks application behavior, not whether real AI answers are accurate. With a valid API key, run from the project root:

```powershell
.\.venv\Scripts\python -m backend.evaluate
```

This uses the provider selected in `.env` to make real embedding and answer requests (subject to its free-tier limits or billing) using an isolated copy of the five sample documents. It writes `report.json` and `review.csv` under a new `runtime/evaluations/<run-id>/` directory. It records indexing throughput, full request latency, five repeated questions with warm embeddings, generated/cache-hit counts, ranked passages, answers, and provider failures.

The report sweeps similarity thresholds against the 20 answerable questions plus five unrelated/unanswerable questions. Review the score distributions and suggested threshold, set `GUIDELY_MIN_SIMILARITY`, restart, and rerun the evaluation. The suggested threshold favors negative rejection while retaining at least 80% automatic Retrieval@3; a suggestion is not a substitute for reviewing passages.

Open `review.csv` and fill **yes/no** for `retrieval_at_3_correct`, `reference_correct`, and `snippet_supports_answer`. Review all 20 for retrieval/reference quality and at least 10 for snippet support. Summarize completed reviews with:

```powershell
.\.venv\Scripts\python -m backend.evaluate --review runtime/evaluations/<run-id>/review.csv
```

For an unpaid test of the evaluation machinery itself, use `python -m backend.evaluate --fake`. Reports explicitly label fake results as invalid for measuring AI quality.

### Testing & Metrics

| Check | Target | Result / evidence |
|---|---|---|
| Backend workflow tests | Pass | 58 passing tests; parsing, caching, persistence, permissions, citations, provider HTTP contracts, and error handling |
| Browser workflows | Pass | 2 passing Chromium workflows; admin/reader journeys, sources, follow-ups, filters, export, and mobile layout |
| Retrieval@3 | ≥80% | Pending live-provider run and human review of 20 questions |
| Correct reference coverage | ≥90% | Pending human review; source IDs are checked automatically for every generated answer |
| Snippet support | ≥80% over 10 results | Pending human review |
| Warm-cache response latency | Median <3s; p95 <5s | Pending hosted-provider measurements; backend logs and `/metrics` record actual times |
| Document embedding reuse | 100% for unchanged content | Automated cache assertions; live evaluation records generated embeddings during repeats |
| Repeated question embeddings | Cache hits after first use | Automated repeated-question assertions and separate counters |
| Failure handling | Clear errors + UI states | Tests cover empty query, missing key, corrupt upload, no results, timeout, invalid citations |
| Indexing throughput | Five files without errors | Evaluation report records elapsed indexing time; unchanged re-indexing is tested |

Do not copy fake-provider timings into the hosted-AI latency row. Median and p95 on the Activity page include all recorded question attempts; the evaluation report separately records its successful warm-cache sample. Hosted latency varies with network and provider conditions and is not guaranteed by this implementation.

## Provider references

The optional OpenAI adapter uses the documented [OpenAI Responses API](https://developers.openai.com/api/reference/python/resources/responses/methods/create) and [embeddings API](https://developers.openai.com/api/reference/python/resources/embeddings/methods/create). `backend/provider.py` defines the provider interface, so another provider can be added without rewriting document management or the UI. OpenAI requests set `store=False` for model responses; provider retention policies still apply. The Gemini adapter uses the official [embedding API](https://ai.google.dev/api/embeddings) and [generateContent API](https://ai.google.dev/api/generate-content) with structured JSON answers. It uses synchronous `batchEmbedContents`, not the separate asynchronous paid Batch API. Gemini answers with missing or mismatched inline citations are regenerated once; the backend still rejects the answer if validation fails. The evaluation tool respects the selected provider.


## Switching an existing installation to Gemini

1. Keep your existing `.env`; do not overwrite it with the example.
2. Set `GUIDELY_PROVIDER=gemini` and add your key as `GEMINI_API_KEY`.
3. Stop the backend with Ctrl+C and restart it using the command above.
4. Refresh the website and click **Index** for each uploaded document. No re-upload or new administrator account is needed. Existing ready badges can refer to an older provider's index until you re-index.
5. Ask a question and inspect the sources. Existing conversations remain available.

If Gemini reports missing credentials, check `GEMINI_API_KEY` and restart. If it rejects a model, check model availability in your Google AI Studio project. A request/quota-limit error can mean you must wait for a reset; a zero quota can require a different available model or project configuration. Repeated retries do not increase your quota. Use `GUIDELY_PROVIDER=fake` if you only want to test the UI without an external service.
