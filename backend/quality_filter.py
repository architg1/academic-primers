"""
Quality filtering and ranking for discovered papers.

Scoring factors (higher = better):
  - Citation impact (log-scaled so old classics don't dominate)
  - Influential citation count (Semantic Scholar's measure of real impact)
  - Recency (bonus for papers from last 5-10 years)
  - Open access (small bonus — we can fetch full text)
  - Has abstract (required for primer generation)

Deduplication:
  - By DOI (exact match)
  - By normalized title (catches same paper from multiple sources)
"""

import math
import re

from backend.models import Paper


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

    # Recency bonus — recent work is more likely to reflect current understanding
    if paper.year:
        if paper.year >= 2020:
            score += 12
        elif paper.year >= 2015:
            score += 7
        elif paper.year >= 2010:
            score += 3

    # Open access — we can attach the PDF to the primer context
    if paper.is_open_access:
        score += 4

    # Has abstract — essential for primer generation; skip papers without one
    if paper.abstract and len(paper.abstract) > 50:
        score += 8

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


def filter_and_rank(papers: list[Paper], top_n: int = 10) -> list[Paper]:
    """
    Remove papers without abstracts, deduplicate, score, and return the top N.
    """
    # Hard requirement: must have a meaningful abstract for primer generation
    with_abstracts = [p for p in papers if p.abstract and len(p.abstract) > 50]

    unique = deduplicate(with_abstracts)

    # Score and attach
    for paper in unique:
        paper.quality_score = score_paper(paper)

    ranked = sorted(unique, key=lambda p: p.quality_score, reverse=True)
    return ranked[:top_n]
