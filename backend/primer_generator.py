"""
Academic primer generation using Claude Sonnet with streaming.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

from groq import AsyncGroq

from backend.models import Paper

_client: AsyncGroq | None = None


def _get_client() -> AsyncGroq:
    global _client
    if _client is None:
        _client = AsyncGroq(api_key=os.environ["GROQ_API_KEY"])
    return _client


def _build_context(papers: list[Paper]) -> str:
    sections = []
    for i, p in enumerate(papers, 1):
        authors = ", ".join(p.authors[:3])
        if len(p.authors) > 3:
            authors += " et al."
        year = p.year or "n.d."
        venue = f" — {p.venue}" if p.venue else ""
        header = f"[{i}] {p.title} ({authors}, {year}{venue})"

        if p.pdf_text:
            content = p.pdf_text
            source_note = "(full text)"
        else:
            content = p.abstract or "(no abstract available)"
            source_note = "(abstract only)"

        sections.append(f"{header} {source_note}\n{content}")
    return "\n\n---\n\n".join(sections)


def _build_further_reading(failed_papers: list[Paper]) -> str:
    if not failed_papers:
        return ""
    lines = []
    for p in failed_papers:
        authors = ", ".join(p.authors[:3])
        if len(p.authors) > 3:
            authors += " et al."
        year = p.year or "n.d."
        url_part = f" {p.url}" if p.url else ""
        lines.append(f"- {p.title} ({authors}, {year}){url_part}")
    return (
        "\n\n**The following papers were identified as relevant but their PDFs "
        "could not be retrieved. Mention them in a '## Further Reading' section "
        "at the end of the primer with a one-sentence note on their likely relevance "
        "based on title and authors:**\n"
        + "\n".join(lines)
    )


_SYSTEM_PROMPT = """\
You are a scientific writer producing academic primers for PhD-level researchers. \
Your primers are rigorous, precise, and assume graduate-level mathematical and scientific literacy. \
Do not over-explain basics. Use field-standard notation and terminology. \
Cite papers using bracketed numbers like [1], [2], [3] inline throughout the text.\
"""

_PRIMER_TEMPLATE = """\
Write a comprehensive academic primer on the following topic for a PhD-level student:

**Topic:** {topic}

**Available papers (cite these inline using [n] notation):**

{context}

---

Structure your primer with these sections:

## 1. Overview
A concise framing of the topic — what it is, why it matters, and where it sits in the broader field.

## 2. Core Concepts and Formalism
The essential definitions, mathematical formulations, and theoretical foundations. \
Be precise; do not simplify away important nuance.

## 3. Historical Development
Key milestones and how the field evolved to its current state. Focus on conceptual shifts, not just dates.

## 4. Current Methodology and State of the Art
The dominant approaches, architectures, or experimental paradigms in active use today. \
What works, what the trade-offs are, and why the community converged on these methods.

## 5. Open Problems and Active Research Directions
Unsolved questions, current debates, and where the field is heading. \
This should help a new PhD student identify where they could contribute.

## 6. Key Papers to Read
A short annotated reading list drawn from the provided papers, ordered by priority. \
For each, one sentence on what it contributes and why it should be read.

---
{further_reading}
Be specific and grounded in the literature. Cite papers throughout, not just in section 6.\
"""


def _build_prompt(
    topic: str,
    papers: list[Paper],
    failed_papers: list[Paper] | None = None,
) -> str:
    further = _build_further_reading(failed_papers or [])
    return _PRIMER_TEMPLATE.format(
        topic=topic,
        context=_build_context(papers),
        further_reading=further,
    )


async def stream_primer(
    topic: str,
    papers: list[Paper],
    failed_papers: list[Paper] | None = None,
) -> AsyncIterator[str]:
    client = _get_client()
    prompt = _build_prompt(topic, papers, failed_papers)

    stream = await client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        max_tokens=4096,
        stream=True,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
    )
    async for chunk in stream:
        text = chunk.choices[0].delta.content
        if text:
            yield text


async def generate_primer(
    topic: str,
    papers: list[Paper],
    failed_papers: list[Paper] | None = None,
) -> str:
    chunks = []
    async for chunk in stream_primer(topic, papers, failed_papers):
        chunks.append(chunk)
    return "".join(chunks)
