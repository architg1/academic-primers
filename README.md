# Academic Primer Generator

> **This entire repository was built by [Claude](https://claude.ai).**

A web app that generates PhD-level academic primers from real research literature. Give it a topic, and it searches academic databases, ranks the most impactful papers, and writes a structured 2000–2500 word primer with inline citations — all streamed live to your browser.

---

## How it works

The app runs in two stages:

**Stage 1 — Find Papers**
Enter a research topic. The app uses an LLM to expand your topic into 2–3 precise academic search queries, then searches [Semantic Scholar](https://www.semanticscholar.org/) (200M+ papers) and [PubMed](https://pubmed.ncbi.nlm.nih.gov/) (biomedical fields only). Preprints (arXiv, bioRxiv, medRxiv, etc.) are excluded — only peer-reviewed journal and conference papers are returned. Results are ranked by citation impact, influential citations, recency, venue quality, and abstract length. The top 10 papers are shown with checkboxes so you can curate the selection.

You can also add specific papers manually using the search bar below the results — search by title, keywords, or DOI.

> **Tip:** Wrapping a phrase in quotes (e.g. `"sparse attention"`) forces every returned paper to contain that exact phrase in its title or abstract.

**Stage 2 — Generate Primer**
Click "Generate Primer". The app first queries [Unpaywall](https://unpaywall.org) to find legal open-access PDFs for any paper with a DOI (author pages, institutional repositories, PubMed Central, etc.), then downloads and extracts full text (up to 15,000 characters per paper). The LLM writes a structured primer using full text where available, falling back to abstracts otherwise. The primer streams to your browser in real time and is rendered as formatted markdown.

The primer always follows five sections: **Background**, **Results**, **Discussion**, **Further Reading** (papers whose PDFs could not be retrieved), and **References** (numbered list of all cited papers).

---

## Components

```
academic-primers/
├── backend/
│   ├── main.py             # FastAPI app; API routes and SSE pipeline
│   ├── models.py           # Pydantic data models (Paper, PrimerRequest, etc.)
│   ├── query_expander.py   # LLM call to turn a topic into search queries
│   ├── paper_search.py     # Semantic Scholar + PubMed API clients; paper lookup
│   ├── quality_filter.py   # Preprint exclusion, deduplication, scoring, ranking
│   ├── pdf_fetcher.py      # Unpaywall lookup + PDF download and text extraction
│   └── primer_generator.py # Streaming LLM call that writes the primer
├── frontend/
│   ├── index.html          # Single-page UI
│   ├── app.js              # Two-stage flow, SSE handling, paper cards, lookup bar
│   └── style.css           # Styles
├── requirements.txt
└── .env.example
```

**Backend:** Python, [FastAPI](https://fastapi.tiangolo.com/), [httpx](https://www.python-httpx.org/) for async HTTP, [pypdf](https://pypdf.readthedocs.io/) for PDF text extraction. LLM calls go through [Groq](https://groq.com/) (`llama-3.3-70b-versatile`) for both query expansion and primer generation.

**Frontend:** Plain HTML/CSS/JavaScript — no framework, no build step. Uses [marked.js](https://marked.js.org/) (loaded from CDN) to render the streamed markdown primer.

---

## Local setup

### Prerequisites

- Python 3.9+
- A [Groq API key](https://console.groq.com/) (free tier available)

### 1. Clone and install dependencies

```bash
git clone <repo-url>
cd academic-primers
pip install -r requirements.txt
```

### 2. Configure environment variables

```bash
cp .env.example .env
```

Open `.env` and fill in your keys:

```
GROQ_API_KEY=your_groq_key_here

# Strongly recommended — required for Unpaywall PDF discovery
UNPAYWALL_EMAIL=you@example.com

# Optional — raises Semantic Scholar rate limit from 1 req/s to 10 req/s
# Get one at: https://www.semanticscholar.org/product/api
SEMANTIC_SCHOLAR_API_KEY=

# Optional — raises PubMed rate limit from 3 req/s to 10 req/s
# Get one at: https://www.ncbi.nlm.nih.gov/account/
NCBI_API_KEY=
```

`GROQ_API_KEY` is the only strictly required key. `UNPAYWALL_EMAIL` is free (no registration — just a valid email address) and significantly increases how many papers have full text available for the primer. The Semantic Scholar and NCBI keys are free and worth getting if you plan to run many queries.

### 3. Start the server

```bash
uvicorn backend.main:app --reload
```

Then open [http://localhost:8000](http://localhost:8000) in your browser.

The `--reload` flag automatically restarts the server when you edit backend files. Remove it in any production-like environment.

---

## API endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/papers` | Expand query, search, rank, and return papers as JSON. |
| `POST` | `/api/paper/lookup` | Find a specific paper by title, keywords, or DOI. Returns up to 5 results. |
| `POST` | `/api/generate` | Full pipeline with SSE streaming. Body accepts `topic` and optional `selected_papers`. |
| `GET` | `/health` | Liveness check. Returns `{"status": "ok"}`. |
| `GET` | `/` | Serves the frontend. |
