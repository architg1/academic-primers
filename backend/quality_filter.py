"""
Quality filtering and ranking for discovered papers.

Scoring factors (higher = better):
  - Citation impact (log-scaled so old classics don't dominate)
  - Influential citation count (Semantic Scholar's measure of real impact)
  - Recency (bonus for papers from last 5-10 years, gated on ≥2 citations)
  - Peer-reviewed venue (bonus); known preprint servers (small penalty)
  - Open access (small bonus — we can fetch full text)
  - Abstract length (graduated — longer abstracts indicate more substantial papers)

Deduplication:
  - By DOI (exact match)
  - By normalized title (catches same paper from multiple sources)
"""

import math
import re
from typing import Optional

from backend.models import Paper


def extract_quoted_phrases(topic: str) -> list[str]:
    """Return all double-quoted phrases from a topic string, e.g. '"attention mechanism"' → ['attention mechanism']."""
    return re.findall(r'"([^"]+)"', topic)

def _normalize_title(title: str) -> str:
    return re.sub(r"\W+", "", title.lower())


def score_paper(paper: Paper) -> float:
    score = 0.0

    # Citation impact — log scale to prevent a 10k-cited paper from drowning everything
    if paper.citation_count > 0:
        score += math.log1p(paper.citation_count) * 5

    # Influential citations are weighted more (these are papers that built on this work
    # in a substantial way, as judged by Semantic Scholar's model)
    if paper.influential_citation_count > 0:
        score += math.log1p(paper.influential_citation_count) * 10

    # Recency bonus — gated on ≥2 citations so zero-citation preprints don't get
    # an unearned boost over validated older work
    if paper.year and paper.citation_count >= 2:
        if paper.year >= 2020:
            score += 12
        elif paper.year >= 2015:
            score += 7
        elif paper.year >= 2010:
            score += 3

    # Venue quality — peer-reviewed venue bonus (preprints are excluded upstream)
    if paper.venue:
        score += 5

    # Open access — we can attach the PDF to the primer context
    if paper.is_open_access:
        score += 4

    # Abstract quality — graduated score; longer abstracts indicate more substantial papers
    if paper.abstract:
        length = len(paper.abstract)
        if length > 1000:
            score += 10
        elif length > 300:
            score += 7
        elif length > 50:
            score += 3

    return score


def deduplicate(papers: list[Paper]) -> list[Paper]:
    seen_dois: set[str] = set()
    seen_titles: set[str] = set()
    unique: list[Paper] = []

    for paper in papers:
        norm_title = _normalize_title(paper.title)

        if paper.doi and paper.doi in seen_dois:
            continue
        if norm_title in seen_titles:
            continue

        if paper.doi:
            seen_dois.add(paper.doi)
        seen_titles.add(norm_title)
        unique.append(paper)

    return unique


def filter_and_rank(
    papers: list[Paper],
    top_n: int = 10,
    required_phrases: Optional[list[str]] = None,
) -> list[Paper]:
    """
    Remove papers without abstracts, enforce required phrases, deduplicate, score, and return the top N.

    required_phrases: phrases that must appear (case-insensitive) in the title or abstract of every returned paper.
    """
    # Hard requirement: must have a meaningful abstract for primer generation
    with_abstracts = [p for p in papers if p.abstract and len(p.abstract) > 50]

    # Enforce quoted phrases from the original topic — each phrase must appear in title or abstract
    if required_phrases:
        def matches(paper: Paper) -> bool:
            haystack = f"{paper.title} {paper.abstract or ''}".lower()
            return all(phrase.lower() in haystack for phrase in required_phrases)
        with_abstracts = [p for p in with_abstracts if matches(p)]

    unique = deduplicate(with_abstracts)

    # Score and attach
    for paper in unique:
        paper.quality_score = score_paper(paper)

    ranked = sorted(unique, key=lambda p: p.quality_score, reverse=True)
    return ranked[:top_n]
