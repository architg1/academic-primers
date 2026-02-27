"""
Paper discovery via Semantic Scholar and PubMed APIs.

Semantic Scholar: primary source — 200M+ papers, citation counts, open access info.
PubMed: secondary source — authoritative for biomedical, peer-reviewed only.
"""

import asyncio
import os
import xml.etree.ElementTree as ET
from typing import Optional

import httpx

from backend.models import Paper

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SS_SEARCH_URL = "https://api.semanticscholar.org/graph/v1/paper/search"
SS_FIELDS = ",".join([
    "title", "authors", "year", "abstract",
    "citationCount", "influentialCitationCount",
    "isOpenAccess", "openAccessPdf", "venue", "externalIds", "paperId",
])

PUBMED_ESEARCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
PUBMED_EFETCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"

TIMEOUT = httpx.Timeout(20.0)

# Preprint servers to exclude — checked against Semantic Scholar's externalIds keys and venue strings
_PREPRINT_EXTERNAL_ID_KEYS = {"ArXiv", "bioRxiv", "medRxiv", "chemRxiv"}
_PREPRINT_VENUE_SUBSTRINGS = {"arxiv", "biorxiv", "medrxiv", "ssrn", "chemrxiv", "techrxiv", "preprint"}


def _is_preprint(data: dict) -> bool:
    """Return True if the Semantic Scholar record is a preprint rather than a published paper."""
    external_ids = data.get("externalIds") or {}
    if any(k in external_ids for k in _PREPRINT_EXTERNAL_ID_KEYS):
        return True
    venue = (data.get("venue") or "").lower()
    return any(p in venue for p in _PREPRINT_VENUE_SUBSTRINGS)


def _ss_headers() -> dict:
    headers = {"Accept": "application/json"}
    key = os.environ.get("SEMANTIC_SCHOLAR_API_KEY", "")
    if key:
        headers["x-api-key"] = key
    return headers


def _ncbi_base_params() -> dict:
    params = {}
    key = os.environ.get("NCBI_API_KEY", "")
    if key:
        params["api_key"] = key
    return params


# ---------------------------------------------------------------------------
# Semantic Scholar
# ---------------------------------------------------------------------------

def _parse_ss_paper(data: dict) -> Optional[Paper]:
    title = data.get("title") or ""
    if not title:
        return None
    if _is_preprint(data):
        return None

    authors = [a["name"] for a in data.get("authors", []) if a.get("name")]
    external_ids = data.get("externalIds") or {}
    doi = external_ids.get("DOI")

    open_access_pdf = data.get("openAccessPdf") or {}
    pdf_url = open_access_pdf.get("url")

    ss_id = data.get("paperId")
    url = f"https://www.semanticscholar.org/paper/{ss_id}" if ss_id else None

    return Paper(
        title=title,
        authors=authors,
        year=data.get("year"),
        abstract=data.get("abstract"),
        citation_count=data.get("citationCount") or 0,
        influential_citation_count=data.get("influentialCitationCount") or 0,
        is_open_access=data.get("isOpenAccess") or False,
        pdf_url=pdf_url,
        venue=data.get("venue"),
        semantic_scholar_id=ss_id,
        doi=doi,
        url=url,
        source="semantic_scholar",
    )


async def search_semantic_scholar(
    query: str,
    client: httpx.AsyncClient,
    limit: int = 50,
    max_retries: int = 3,
) -> list[Paper]:
    params = {
        "query": query,
        "fields": SS_FIELDS,
        "limit": limit,
        "sort": "citationCount",
        "minCitationCount": 2,
    }
    for attempt in range(max_retries):
        try:
            resp = await client.get(SS_SEARCH_URL, params=params, headers=_ss_headers(), timeout=TIMEOUT)
            resp.raise_for_status()
            data = resp.json()
            papers = []
            for item in data.get("data", []):
                paper = _parse_ss_paper(item)
                if paper:
                    papers.append(paper)
            return papers
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 429 and attempt < max_retries - 1:
                wait = 2 ** (attempt + 1)  # 2s, 4s, 8s
                print(f"[semantic_scholar] rate limited, retrying in {wait}s…")
                await asyncio.sleep(wait)
            else:
                print(f"[semantic_scholar] query={query!r} error: {exc}")
                return []
        except Exception as exc:
            print(f"[semantic_scholar] query={query!r} error: {exc}")
            return []
    return []


# ---------------------------------------------------------------------------
# PubMed
# ---------------------------------------------------------------------------

def _parse_pubmed_xml(xml_text: str) -> list[Paper]:
    papers = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []

    for article in root.findall(".//PubmedArticle"):
        medline = article.find("MedlineCitation")
        if medline is None:
            continue

        art = medline.find("Article")
        if art is None:
            continue

        title_el = art.find("ArticleTitle")
        title = "".join(title_el.itertext()).strip() if title_el is not None else ""
        if not title:
            continue

        abstract_parts = []
        abstract_el = art.find("Abstract")
        if abstract_el is not None:
            for text_el in abstract_el.findall("AbstractText"):
                label = text_el.get("Label", "")
                text = "".join(text_el.itertext()).strip()
                abstract_parts.append(f"{label}: {text}" if label else text)
        abstract = " ".join(abstract_parts) or None

        authors = []
        author_list = art.find("AuthorList")
        if author_list is not None:
            for author in author_list.findall("Author"):
                last = author.findtext("LastName", "")
                fore = author.findtext("ForeName", "")
                name = f"{fore} {last}".strip()
                if name:
                    authors.append(name)

        year = None
        pub_date = art.find(".//PubDate")
        if pub_date is not None:
            year_el = pub_date.find("Year")
            if year_el is not None:
                try:
                    year = int(year_el.text)
                except (ValueError, TypeError):
                    pass

        journal = art.find("Journal")
        venue = None
        if journal is not None:
            venue = journal.findtext("Title") or journal.findtext("ISOAbbreviation")

        doi = None
        for id_el in article.findall(".//ArticleId"):
            if id_el.get("IdType") == "doi":
                doi = id_el.text
                break

        pmid = medline.findtext("PMID")
        url = f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/" if pmid else None

        papers.append(Paper(
            title=title,
            authors=authors,
            year=year,
            abstract=abstract,
            citation_count=0,
            influential_citation_count=0,
            is_open_access=False,
            pdf_url=None,
            venue=venue,
            doi=doi,
            url=url,
            source="pubmed",
        ))

    return papers


async def search_pubmed(
    query: str,
    client: httpx.AsyncClient,
    limit: int = 25,
) -> list[Paper]:
    base = _ncbi_base_params()

    try:
        search_params = {**base, "db": "pubmed", "term": query, "retmax": limit, "retmode": "json"}
        resp = await client.get(PUBMED_ESEARCH, params=search_params, timeout=TIMEOUT)
        resp.raise_for_status()
        ids = resp.json().get("esearchresult", {}).get("idlist", [])
    except Exception as exc:
        print(f"[pubmed esearch] query={query!r} error: {exc}")
        return []

    if not ids:
        return []

    try:
        fetch_params = {**base, "db": "pubmed", "id": ",".join(ids), "rettype": "abstract", "retmode": "xml"}
        resp = await client.get(PUBMED_EFETCH, params=fetch_params, timeout=TIMEOUT)
        resp.raise_for_status()
        xml_text = resp.text
    except Exception as exc:
        print(f"[pubmed efetch] error: {exc}")
        return []

    return _parse_pubmed_xml(xml_text)


# ---------------------------------------------------------------------------
# Combined search
# ---------------------------------------------------------------------------

async def search_all(queries: list[str], field: str = "") -> list[Paper]:
    biomedical_fields = {"biology", "medicine", "neuroscience", "biochemistry", "genetics", "pharmacology"}
    include_pubmed = any(f in field.lower() for f in biomedical_fields)

    # Semantic Scholar rate limit: 1 req/s without an API key.
    # Run SS queries sequentially with a gap to avoid 429s.
    has_ss_key = bool(os.environ.get("SEMANTIC_SCHOLAR_API_KEY", ""))
    # Without a key the limit is 1 req/s; use 2s to give the rolling window room.
    # Retry logic in search_semantic_scholar handles any remaining 429s.
    ss_delay = 0.0 if has_ss_key else 2.0

    has_ncbi_key = bool(os.environ.get("NCBI_API_KEY", ""))
    # Without a key PubMed allows 3 req/s; serialize with a conservative gap.
    pm_delay = 0.0 if has_ncbi_key else 0.4

    papers: list[Paper] = []

    async with httpx.AsyncClient() as client:
        # Semantic Scholar — sequential with delay + retry on 429
        for i, query in enumerate(queries):
            if i > 0 and ss_delay:
                await asyncio.sleep(ss_delay)
            result = await search_semantic_scholar(query, client)
            papers.extend(result)

        # PubMed — sequential with delay (parallel triggers 429 without a key)
        if include_pubmed:
            for i, query in enumerate(queries):
                if i > 0 and pm_delay:
                    await asyncio.sleep(pm_delay)
                try:
                    result = await search_pubmed(query, client)
                    papers.extend(result)
                except Exception as exc:
                    print(f"[search_all] pubmed error: {exc}")

    return papers
