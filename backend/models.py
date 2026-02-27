from __future__ import annotations

from pydantic import BaseModel
from typing import Optional


class Paper(BaseModel):
    title: str
    authors: list[str]
    year: Optional[int] = None
    abstract: Optional[str] = None
    citation_count: int = 0
    influential_citation_count: int = 0
    is_open_access: bool = False
    pdf_url: Optional[str] = None
    venue: Optional[str] = None
    semantic_scholar_id: Optional[str] = None
    doi: Optional[str] = None
    url: Optional[str] = None
    source: str  # "semantic_scholar" or "pubmed"
    quality_score: float = 0.0
    pdf_text: Optional[str] = None  # full extracted text, set after PDF fetch


class SearchResult(BaseModel):
    queries: list[str]
    field: str
    keywords: list[str]


class PrimerRequest(BaseModel):
    topic: str
    selected_papers: Optional[list[Paper]] = None


class PapersResponse(BaseModel):
    topic: str
    queries: list[str]
    field: str
    papers: list[Paper]


class PaperLookupRequest(BaseModel):
    query: str
