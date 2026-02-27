# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running the app

```bash
# Install dependencies
pip install -r requirements.txt

# Copy and fill in env vars
cp .env.example .env

# Start the server (serves both API and frontend)
uvicorn backend.main:app --reload
```

The app is then available at `http://localhost:8000`. The frontend is served as static files from `frontend/` — no separate build step.

## Required env vars

- `GROQ_API_KEY` — required; used for both query expansion and primer generation (Groq/llama-3.3-70b-versatile)
- `SEMANTIC_SCHOLAR_API_KEY` — optional; raises Semantic Scholar rate limit from 1 req/s to 10 req/s
- `NCBI_API_KEY` — optional; raises PubMed rate limit from 3 req/s to 10 req/s

Note: `requirements.txt` includes `anthropic` but the codebase currently uses Groq (not Anthropic) for all LLM calls.

## Architecture

The app generates PhD-level academic primers from real papers. It is a FastAPI backend + vanilla JS frontend, wired together via two API endpoints:

**Two-stage user flow:**
1. **Stage 1** — `POST /api/papers`: user submits a topic → backend expands query, searches papers, ranks them, returns JSON. Frontend shows ranked papers with checkboxes.
2. **Stage 2** — `POST /api/generate`: user confirms paper selection → backend re-runs the pipeline (or skips search if papers already selected) and streams the primer via **Server-Sent Events (SSE)**. Frontend renders SSE chunks in real time, converting markdown to HTML on `done`.

**Backend pipeline (`backend/main.py → _run_pipeline`):**
```
expand_query()         → LLM turns topic into 2-3 academic search queries + field + keywords
search_all()           → Semantic Scholar (primary) + PubMed (biomedical fields only)
filter_and_rank()      → dedup by DOI/title, score by citations/recency/OA, take top 10
enrich_papers_with_pdfs() → download + extract text from open-access PDFs (pypdf)
stream_primer()        → LLM generates 2000-2500 word primer with [n] citations, streamed
```

**SSE event types** (emitted by `_run_pipeline`, consumed by `handleEvent()` in `app.js`):
- `status` — progress message
- `queries` — expanded queries/field/keywords (shown in UI card)
- `papers` — ranked paper list (used in Stage 1 response only)
- `primer_chunk` — streaming text
- `done` — signals completion; frontend renders buffered markdown
- `error` — terminates stream with error message

**Key modules:**
- `backend/query_expander.py` — Groq tool-use call to get structured search queries
- `backend/paper_search.py` — async HTTP via `httpx`; SS queries are sequential (rate limit); PubMed is biomedical-only and also sequential
- `backend/quality_filter.py` — scoring: log-scaled citation count, influential citations, recency bonus, OA bonus, abstract requirement
- `backend/pdf_fetcher.py` — browser User-Agent headers, 15k char cap per paper, graceful fallback to abstract-only if all fetches fail
- `backend/primer_generator.py` — fixed 4-section structure: Background, Results, Discussion, Further Reading (for undownloadable PDFs)
- `backend/models.py` — Pydantic models: `Paper`, `SearchResult`, `PrimerRequest`, `PapersResponse`

**Frontend** (`frontend/`): plain HTML/CSS/JS, no build tooling. Uses `marked.js` (CDN) for markdown rendering. Primer text is buffered as plain text while streaming, then converted to HTML on `done`.

**Static file serving**: `frontend/` is mounted at `/` via FastAPI `StaticFiles`. API routes (`/api/*`) must be registered **before** this mount or they'll be shadowed.
