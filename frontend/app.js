/* ─────────────────────────────────────────────────────────────────
   Academic Primer Generator — frontend logic
───────────────────────────────────────────────────────────────── */

const $ = id => document.getElementById(id);

// ── State ────────────────────────────────────────────────────────
let primerBuffer = '';
let isGenerating = false;

// ── Elements ─────────────────────────────────────────────────────
const form          = $('primer-form');
const topicInput    = $('topic-input');
const charCount     = $('char-count');
const submitBtn     = $('submit-btn');
const btnSpinner    = $('btn-spinner');
const btnArrow      = submitBtn.querySelector('.btn-arrow');
const statusSection = $('status-section');
const statusText    = $('status-text');
const queriesSection= $('queries-section');
const queriesList   = $('queries-list');
const fieldBadge    = $('field-badge');
const keywordsText  = $('keywords-text');
const papersSection = $('papers-section');
const paperCount    = $('paper-count');
const papersGrid    = $('papers-grid');
const primerSection = $('primer-section');
const primerContent = $('primer-content');
const copyBtn       = $('copy-btn');
const errorBox      = $('error-box');
const errorText     = $('error-text');

// ── Marked config ────────────────────────────────────────────────
marked.setOptions({ breaks: true });

// ── Helpers ──────────────────────────────────────────────────────
const show = el => el.classList.remove('hidden');
const hide = el => el.classList.add('hidden');

function escapeHtml(str) {
  const div = document.createElement('div');
  div.textContent = str;
  return div.innerHTML;
}

function safeUrl(url) {
  if (!url) return null;
  try {
    const u = new URL(url);
    return (u.protocol === 'https:' || u.protocol === 'http:') ? url : null;
  } catch { return null; }
}

function formatNum(n) {
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + 'M';
  if (n >= 1_000)     return (n / 1_000).toFixed(1) + 'k';
  return String(n);
}

// ── Character counter ────────────────────────────────────────────
topicInput.addEventListener('input', () => {
  charCount.textContent = `${topicInput.value.length} / 500`;
});

// ── Copy button ──────────────────────────────────────────────────
copyBtn.addEventListener('click', () => {
  navigator.clipboard.writeText(primerBuffer).then(() => {
    copyBtn.textContent = 'Copied!';
    setTimeout(() => { copyBtn.textContent = 'Copy'; }, 2000);
  });
});

// ── Form submit ──────────────────────────────────────────────────
form.addEventListener('submit', async e => {
  e.preventDefault();
  const topic = topicInput.value.trim();
  if (!topic || isGenerating) return;
  await run(topic);
});

// ── Reset UI ─────────────────────────────────────────────────────
function reset() {
  primerBuffer = '';
  hide(statusSection);
  hide(queriesSection);
  hide(papersSection);
  hide(primerSection);
  hide(errorBox);
  hide(copyBtn);
  queriesList.innerHTML   = '';
  papersGrid.innerHTML    = '';
  primerContent.innerHTML = '';
  primerContent.classList.remove('streaming');
  fieldBadge.textContent   = '';
  keywordsText.textContent = '';
  paperCount.textContent   = '';
}

// ── Loading state ────────────────────────────────────────────────
function setLoading(loading) {
  isGenerating = loading;
  submitBtn.disabled = loading;
  btnArrow.style.display = loading ? 'none' : '';
  loading ? show(btnSpinner) : hide(btnSpinner);
}

// ── SSE event dispatcher ─────────────────────────────────────────
function handleEvent(data) {
  switch (data.type) {

    case 'status':
      show(statusSection);
      statusText.textContent = data.message;
      break;

    case 'queries':
      queriesList.innerHTML = (data.queries || [])
        .map(q => `<li>${escapeHtml(q)}</li>`)
        .join('');
      fieldBadge.textContent = data.field || '';
      keywordsText.textContent = data.keywords?.length
        ? 'Keywords: ' + data.keywords.join(', ')
        : '';
      show(queriesSection);
      break;

    case 'papers':
      paperCount.textContent = `(${data.papers.length})`;
      papersGrid.innerHTML = data.papers
        .map((paper, i) => renderPaperCard(paper, i))
        .join('');
      show(papersSection);
      break;

    case 'primer_chunk':
      show(primerSection);
      primerContent.classList.add('streaming');
      primerBuffer += data.content;
      primerContent.textContent = primerBuffer;
      break;

    case 'done':
      primerContent.classList.remove('streaming');
      primerContent.innerHTML = marked.parse(primerBuffer);
      show(copyBtn);
      hide(statusSection);
      primerSection.scrollIntoView({ behavior: 'smooth', block: 'start' });
      break;

    case 'error':
      errorText.textContent = data.message;
      show(errorBox);
      hide(statusSection);
      break;
  }
}

// ── Paper card renderer ──────────────────────────────────────────
function renderPaperCard(paper, index) {
  const authors = paper.authors.length
    ? escapeHtml(paper.authors.slice(0, 3).join(', ') + (paper.authors.length > 3 ? ' et al.' : ''))
    : 'Unknown authors';

  const year    = paper.year || 'n.d.';
  const venue   = paper.venue ? ` · ${escapeHtml(paper.venue)}` : '';
  const paperUrl = safeUrl(paper.url);
  const pdfUrl   = safeUrl(paper.pdf_url);

  const abstract = paper.abstract
    ? escapeHtml(paper.abstract.slice(0, 220)) + (paper.abstract.length > 220 ? '…' : '')
    : '';

  const titleHtml = paperUrl
    ? `<a href="${paperUrl}" target="_blank" rel="noopener noreferrer">${escapeHtml(paper.title)}</a>`
    : escapeHtml(paper.title);

  const badges = [
    paper.citation_count > 0
      ? `<span class="badge">${formatNum(paper.citation_count)} citations</span>` : '',
    paper.influential_citation_count > 0
      ? `<span class="badge badge-green">${paper.influential_citation_count} influential</span>` : '',
    paper.is_open_access
      ? `<span class="badge badge-blue">Open Access</span>` : '',
  ].filter(Boolean).join('');

  const links = [
    paperUrl ? `<a href="${paperUrl}" target="_blank" rel="noopener noreferrer">View paper ↗</a>` : '',
    pdfUrl   ? `<a href="${pdfUrl}"   target="_blank" rel="noopener noreferrer">PDF ↗</a>`       : '',
  ].filter(Boolean).join('');

  return `
    <div class="paper-card">
      <div class="paper-rank">${index + 1}</div>
      <div class="paper-body">
        <div class="paper-title">${titleHtml}</div>
        <div class="paper-meta">${authors} · ${year}${venue}</div>
        ${badges ? `<div class="badges">${badges}</div>` : ''}
        ${abstract ? `<div class="paper-abstract">${abstract}</div>` : ''}
        ${links ? `<div class="paper-links">${links}</div>` : ''}
      </div>
    </div>`;
}

// ── Main run ─────────────────────────────────────────────────────
async function run(topic) {
  reset();
  setLoading(true);

  try {
    const response = await fetch('/api/generate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ topic }),
    });

    if (!response.ok) {
      let msg = `Server error (${response.status})`;
      try { msg = (await response.json()).detail || msg; } catch { /* ignore */ }
      throw new Error(msg);
    }

    const reader  = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const frames = buffer.split('\n\n');
      buffer = frames.pop(); // hold incomplete tail

      for (const frame of frames) {
        const line = frame.trim();
        if (!line.startsWith('data: ')) continue;
        try {
          handleEvent(JSON.parse(line.slice(6)));
        } catch (e) {
          console.warn('Failed to parse SSE frame:', line, e);
        }
      }
    }
  } catch (err) {
    errorText.textContent = err.message;
    show(errorBox);
    hide(statusSection);
  } finally {
    setLoading(false);
  }
}
