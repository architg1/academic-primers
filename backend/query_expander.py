"""
LLM-based query expansion using Claude Haiku.

Turns a natural-language topic description into 2-3 precise academic search
queries, identifies the research field, and extracts key technical keywords.
Uses tool use for structured JSON output.
"""

from __future__ import annotations

import json
import os

from groq import AsyncGroq

from backend.models import SearchResult

_client: AsyncGroq | None = None


def _get_client() -> AsyncGroq:
    global _client
    if _client is None:
        _client = AsyncGroq(api_key=os.environ["GROQ_API_KEY"])
    return _client


_EXPAND_TOOL = {
    "type": "function",
    "function": {
        "name": "formulate_search_queries",
        "description": (
            "Given a research topic description, produce precise search queries for academic "
            "paper databases (Semantic Scholar, PubMed). Queries should use technical terminology "
            "that would appear in paper titles and abstracts."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "queries": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "2-3 search queries targeting distinct angles of the topic. "
                        "Use technical academic phrasing, not conversational language."
                    ),
                },
                "field": {
                    "type": "string",
                    "description": (
                        "The primary research field (e.g. 'neuroscience', 'machine learning', "
                        "'condensed matter physics'). Used to route to the right databases."
                    ),
                },
                "keywords": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "4-8 key technical terms that define the topic.",
                },
            },
            "required": ["queries", "field", "keywords"],
        },
    },
}

_SYSTEM_PROMPT = (
    "You are an expert academic librarian helping a PhD-level researcher find papers. "
    "Given a topic description, formulate precise search queries for academic databases. "
    "Prefer technical terminology over colloquial phrasing. "
    "Each query should cover a different facet of the topic."
)


async def expand_query(topic: str) -> SearchResult:
    client = _get_client()

    try:
        response = await client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            max_tokens=512,
            tools=[_EXPAND_TOOL],
            tool_choice={"type": "function", "function": {"name": "formulate_search_queries"}},
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": f"Topic: {topic}"},
            ],
        )
    except Exception as exc:
        print(f"[query_expander] API error: {exc}")
        return _fallback(topic)

    msg = response.choices[0].message
    if msg.tool_calls:
        inp = json.loads(msg.tool_calls[0].function.arguments)
        return SearchResult(
            queries=inp.get("queries", [topic]),
            field=inp.get("field", ""),
            keywords=inp.get("keywords", []),
        )

    return _fallback(topic)


def _fallback(topic: str) -> SearchResult:
    return SearchResult(queries=[topic], field="", keywords=[])
