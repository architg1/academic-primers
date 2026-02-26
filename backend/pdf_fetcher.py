"""
Fetch and extract full text from open-access PDFs.

For each open-access paper with a pdf_url:
  1. Download the PDF
  2. Extract text with pypdf

Papers whose PDFs cannot be fetched are returned separately so the primer
can list them as further reading.
"""

from __future__ import annotations

import asyncio
import io
from typing import Optional

import httpx
from pypdf import PdfReader

from backend.models import Paper

FETCH_TIMEOUT = httpx.Timeout(30.0)

# Cap per paper to keep total LLM context manageable (~3,750 tokens each)
MAX_CHARS_PER_PAPER = 15_000

# Many publishers block non-browser user agents; mimic a real browser.
_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/pdf,*/*",
    "Accept-Language": "en-US,en;q=0.9",
}


async def _download_and_extract(url: str, client: httpx.AsyncClient) -> Optional[str]:
    try:
        resp = await client.get(
            url,
            headers=_BROWSER_HEADERS,
            timeout=FETCH_TIMEOUT,
            follow_redirects=True,
        )
        resp.raise_for_status()
        pdf_bytes = resp.content
    except Exception as exc:
        print(f"[pdf_fetcher] download failed {url!r}: {exc}")
        return None

    try:
        reader = PdfReader(io.BytesIO(pdf_bytes))
        pages = []
        for page in reader.pages:
            text = page.extract_text()
            if text:
                pages.append(text.strip())
        full_text = "\n\n".join(pages).strip()
        return full_text[:MAX_CHARS_PER_PAPER] if full_text else None
    except Exception as exc:
        print(f"[pdf_fetcher] parse failed {url!r}: {exc}")
        return None


async def enrich_papers_with_pdfs(
    papers: list[Paper],
) -> tuple[list[Paper], list[Paper]]:
    """
    Attempt to fetch full text for every open-access paper that has a pdf_url.

    Returns:
        enriched  — papers to use in the primer:
                      · OA papers where fetch succeeded → pdf_text is set
                      · non-OA papers → included as-is (abstract used by generator)
        failed    — OA papers whose PDF could not be fetched; show as further reading
    """
    oa = [(i, p) for i, p in enumerate(papers) if p.is_open_access and p.pdf_url]
    non_oa_indices = set(range(len(papers))) - {i for i, _ in oa}

    if not oa:
        return list(papers), []

    async with httpx.AsyncClient() as client:
        results = await asyncio.gather(
            *[_download_and_extract(p.pdf_url, client) for _, p in oa],
            return_exceptions=True,
        )

    enriched: list[Paper] = [papers[i] for i in sorted(non_oa_indices)]
    failed: list[Paper] = []

    for (_, paper), result in zip(oa, results):
        if isinstance(result, Exception) or not result:
            failed.append(paper)
        else:
            paper.pdf_text = result
            enriched.append(paper)

    # If every OA fetch failed and there are no non-OA papers, fall back to
    # using abstracts for all papers so we still generate something useful.
    if not enriched:
        print("[pdf_fetcher] all PDF fetches failed — falling back to abstracts")
        return list(papers), []

    return enriched, failed
