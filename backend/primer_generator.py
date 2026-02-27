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
    for i, p in enumerate(failed_papers, 1):
        authors = ", ".join(p.authors[:3])
        if len(p.authors) > 3:
            authors += " et al."
        year = p.year or "n.d."
        url_part = f" {p.url}" if p.url else ""
        lines.append(f"{i}. {p.title} ({authors}, {year}){url_part}")
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
Cite papers using bracketed numbers like [1], [2], [3] inline throughout the text. \
Every paper provided to you must be cited at least once — do not omit any reference. \
Be concise — every sentence should add information.\
"""

_PRIMER_TEMPLATE = """\
Write an academic primer on the following topic for a PhD-level student.
Target length: 2000-2500 words total across all sections.

**Topic:** {topic}

**Available papers — you MUST cite every one of them at least once:**

{context}

---

Use exactly these four sections with the headings shown:

## Background
Approximately 500 words. Establish the scientific context: why this topic matters, \
what problem it addresses, and how it fits within the broader field. \
Cover the key historical developments and the conceptual arc that led to the current state of research. \
Cite liberally.

## Results
Approximately 1000 words. Summarize the principal empirical and theoretical findings reported across the papers. \
What has been demonstrated, measured, or proven? Group related findings. \
Be specific: report effect sizes, model names, experimental conditions, or key equations where relevant. \
Cite each finding to its source.

## Discussion
Approximately 500 words. Interpret the results in aggregate. What do they collectively reveal? \
Where do findings converge or conflict? What are the open questions and active debates? \
What should a new researcher in this area focus on first?
{further_reading}
## References
List every paper you cited inline, in order of their citation number. Use this format exactly:
[n] Title (Authors, Year) URL

Include the URL if one is available in the paper metadata provided above. Do not add any sections beyond these.\
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
        max_tokens=3000,
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
