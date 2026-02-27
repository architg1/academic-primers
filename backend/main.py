"""
FastAPI application — wires all backend components together.

Endpoints:
  POST /api/papers   — query expansion + paper search + ranking; returns JSON
  POST /api/generate — full pipeline with SSE streaming
  GET  /health       — liveness check
  GET  /             — serves frontend/index.html
"""

from __future__ import annotations

import json
import os

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles

from backend.models import PapersResponse, PrimerRequest
from backend.paper_search import search_all
from backend.pdf_fetcher import enrich_papers_with_pdfs
from backend.primer_generator import stream_primer
from backend.quality_filter import extract_quoted_phrases, filter_and_rank
from backend.query_expander import expand_query

load_dotenv()

app = FastAPI(title="Academic Primer Generator", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sse(event_type: str, data: dict) -> str:
    payload = json.dumps({"type": event_type, **data})
    return f"data: {payload}\n\n"


async def _run_pipeline(topic: str, selected_papers: list | None = None):
    if selected_papers:
        # User already curated the paper list — skip search entirely
        top_papers = selected_papers
        yield _sse("status", {"message": f"Using {len(top_papers)} selected papers…"})
    else:
        yield _sse("status", {"message": "Expanding your topic into search queries…"})
        try:
            search_result = await expand_query(topic)
        except Exception as exc:
            yield _sse("error", {"message": f"Query expansion failed: {exc}"})
            return

        yield _sse("queries", {
            "queries": search_result.queries,
            "field": search_result.field,
            "keywords": search_result.keywords,
        })

        yield _sse("status", {"message": f"Searching papers across {len(search_result.queries)} queries…"})
        try:
            raw_papers = await search_all(search_result.queries, field=search_result.field)
        except Exception as exc:
            yield _sse("error", {"message": f"Paper search failed: {exc}"})
            return

        if not raw_papers:
            yield _sse("error", {"message": "No papers found. Try a more specific topic."})
            return

        yield _sse("status", {"message": f"Ranking {len(raw_papers)} papers by quality…"})
        required = extract_quoted_phrases(topic)
        top_papers = filter_and_rank(raw_papers, top_n=10, required_phrases=required or None)

        if not top_papers:
            yield _sse("error", {"message": "Found papers but none had usable abstracts. Try a different topic."})
            return

    # Fetch full text for open-access papers
    oa_count = sum(1 for p in top_papers if p.is_open_access and p.pdf_url)
    if oa_count:
        yield _sse("status", {"message": f"Fetching full text for {oa_count} open-access papers…"})
        try:
            enriched_papers, failed_papers = await enrich_papers_with_pdfs(top_papers)
        except Exception as exc:
            print(f"[pipeline] PDF enrichment error: {exc}")
            enriched_papers, failed_papers = top_papers, []
    else:
        enriched_papers, failed_papers = top_papers, []

    # Send all papers to the frontend (exclude full text — too large for SSE)
    all_papers = enriched_papers + failed_papers
    yield _sse("papers", {
        "papers": [p.model_dump(exclude={"pdf_text"}) for p in all_papers],
        "failed_pdf_count": len(failed_papers),
    })

    full_text_count = sum(1 for p in enriched_papers if p.pdf_text)
    status_msg = f"Generating primer from {len(enriched_papers)} papers"
    if full_text_count:
        status_msg += f" ({full_text_count} with full text)"
    status_msg += "…"
    yield _sse("status", {"message": status_msg})

    try:
        async for chunk in stream_primer(topic, enriched_papers, failed_papers):
            yield _sse("primer_chunk", {"content": chunk})
    except Exception as exc:
        yield _sse("error", {"message": f"Primer generation failed: {exc}"})
        return

    yield _sse("done", {})


# ---------------------------------------------------------------------------
# API routes (must come BEFORE the static files mount)
# ---------------------------------------------------------------------------

@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/api/papers", response_model=PapersResponse)
async def get_papers(req: PrimerRequest):
    if not req.topic.strip():
        raise HTTPException(status_code=400, detail="Topic cannot be empty.")

    search_result = await expand_query(req.topic)
    raw_papers = await search_all(search_result.queries, field=search_result.field)

    if not raw_papers:
        raise HTTPException(status_code=404, detail="No papers found for this topic.")

    required = extract_quoted_phrases(req.topic)
    top_papers = filter_and_rank(raw_papers, top_n=10, required_phrases=required or None)

    return PapersResponse(
        topic=req.topic,
        queries=search_result.queries,
        field=search_result.field,
        papers=top_papers,
    )


@app.post("/api/generate")
async def generate(req: PrimerRequest):
    if not req.topic.strip():
        raise HTTPException(status_code=400, detail="Topic cannot be empty.")

    return StreamingResponse(
        _run_pipeline(req.topic, req.selected_papers),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ---------------------------------------------------------------------------
# Serve frontend — must be LAST (catches all unmatched paths)
# ---------------------------------------------------------------------------

app.mount("/", StaticFiles(directory="frontend", html=True), name="frontend")
