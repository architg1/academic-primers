/* ─────────────────────────────────────────────────────────────────
   Academic Primer Generator — two-stage frontend

   Stage 1: "Find Papers"  → POST /api/papers  → show papers + checkboxes
   Stage 2: "Generate Primer" → POST /api/generate (with selected papers) → SSE stream
───────────────────────────────────────────────────────────────── */

const $ = id => document.getElementById(id);

// ── State ────────────────────────────────────────────────────────
let currentPapers  = [];   // papers returned from /api/papers
let currentTopic   = '';
let primerBuffer   = '';
let isSearching    = false;
let isGenerating   = false;
let lookupPaperMap = {};   // idx → Paper for lookup results

// ── Elements ─────────────────────────────────────────────────────
const form             = $('primer-form');
const topicInput       = $('topic-input');
const charCount        = $('char-count');
const submitBtn        = $('submit-btn');
const btnSpinner       = $('btn-spinner');
const btnArrow         = submitBtn.querySelector('.btn-arrow');
const statusSection    = $('status-section');
const statusText       = $('status-text');
const queriesSection   = $('queries-section');
const queriesList      = $('queries-list');
const fieldBadge       = $('field-badge');
const keywordsText     = $('keywords-text');
const papersSection    = $('papers-section');
const paperCount       = $('paper-count');
const papersGrid       = $('papers-grid');
const generateConfirm  = $('generate-confirm');
const selectedCount    = $('selected-count');
const generateBtn      = $('generate-btn');
const generateSpinner  = $('generate-spinner');
const primerSection    = $('primer-section');
const primerContent    = $('primer-content');
const copyBtn          = $('copy-btn');
const errorBox            = $('error-box');
const errorText           = $('error-text');
const paperLookup         = $('paper-lookup');
const paperLookupForm     = $('paper-lookup-form');
const paperLookupInput    = $('paper-lookup-input');
const paperLookupBtn      = $('paper-lookup-btn');
const paperLookupSpinner  = $('paper-lookup-spinner');
const paperLookupResults  = $('paper-lookup-results');

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

// ── Reset ────────────────────────────────────────────────────────
function reset() {
  currentPapers  = [];
  primerBuffer   = '';
  lookupPaperMap = {};
  hide(statusSection);
  hide(queriesSection);
  hide(papersSection);
  hide(primerSection);
  hide(errorBox);
  hide(copyBtn);
  hide(generateConfirm);
  hide(paperLookup);
  queriesList.innerHTML        = '';
  papersGrid.innerHTML         = '';
  primerContent.innerHTML      = '';
  paperLookupInput.value       = '';
  paperLookupResults.innerHTML = '';
  hide(paperLookupResults);
  primerContent.classList.remove('streaming');
  fieldBadge.textContent    = '';
  keywordsText.textContent  = '';
  paperCount.textContent    = '';
  selectedCount.textContent = '';
}

// ── Loading states ───────────────────────────────────────────────
function setSearchLoading(on) {
  isSearching = on;
  submitBtn.disabled = on;
  btnArrow.style.display = on ? 'none' : '';
  on ? show(btnSpinner) : hide(btnSpinner);
}

function setGenerateLoading(on) {
  isGenerating = on;
  generateBtn.disabled = on;
  const arrow = generateBtn.querySelector('.btn-arrow');
  arrow.style.display = on ? 'none' : '';
  on ? show(generateSpinner) : hide(generateSpinner);
}

// ── Selection helpers ────────────────────────────────────────────
function getCheckedIndices() {
  return Array.from(document.querySelectorAll('.paper-checkbox:checked'))
    .map(cb => parseInt(cb.dataset.index));
}

function updateSelectedCount() {
  const n = getCheckedIndices().length;
  selectedCount.textContent = `${n} of ${currentPapers.length} papers selected`;
}

// ── Checkbox change ──────────────────────────────────────────────
function onCheckboxChange(e) {
  const idx = parseInt(e.target.dataset.index);
  const card = document.querySelector(`.paper-card[data-index="${idx}"]`);
  if (card) card.classList.toggle('excluded', !e.target.checked);
  updateSelectedCount();
}

// ── Skeleton cards ───────────────────────────────────────────────
function renderSkeletonCards(n) {
  const card = `
    <div class="paper-card skeleton-card" aria-hidden="true">
      <div class="paper-check"><div class="skel skel-box"></div></div>
      <div class="paper-rank"><div class="skel skel-circle"></div></div>
      <div class="paper-body">
        <div class="skel skel-line" style="width:68%"></div>
        <div class="skel skel-line" style="width:42%;margin-top:6px"></div>
        <div class="skel skel-line" style="width:100%;margin-top:10px"></div>
        <div class="skel skel-line" style="width:85%;margin-top:5px"></div>
        <div class="skel skel-line" style="width:55%;margin-top:5px"></div>
      </div>
    </div>`;
  return Array(n).fill(card).join('');
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
    <div class="paper-card" data-index="${index}">
      <div class="paper-check">
        <input type="checkbox" class="paper-checkbox" data-index="${index}" checked />
      </div>
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

// ── Stage 1: Find papers ─────────────────────────────────────────
form.addEventListener('submit', async e => {
  e.preventDefault();
  const topic = topicInput.value.trim();
  if (!topic || isSearching || isGenerating) return;
  await findPapers(topic);
});

async function findPapers(topic) {
  currentTopic = topic;
  reset();
  setSearchLoading(true);

  show(statusSection);
  statusText.textContent = 'Searching for papers…';

  // Show skeleton cards immediately so the page feels responsive
  papersGrid.innerHTML = renderSkeletonCards(6);
  show(papersSection);
  papersSection.scrollIntoView({ behavior: 'smooth', block: 'start' });

  try {
    const resp = await fetch('/api/papers', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ topic }),
    });

    if (!resp.ok) {
      let msg = `Server error (${resp.status})`;
      try { msg = (await resp.json()).detail || msg; } catch { /* ignore */ }
      throw new Error(msg);
    }

    const data = await resp.json();
    currentPapers = data.papers;

    // Show queries card
    if (data.queries?.length) {
      queriesList.innerHTML = data.queries.map(q => `<li>${escapeHtml(q)}</li>`).join('');
      fieldBadge.textContent = data.field || '';
      keywordsText.textContent = data.keywords?.length ? 'Keywords: ' + data.keywords.join(', ') : '';
      show(queriesSection);
    }

    // Show papers with checkboxes
    paperCount.textContent = `(${currentPapers.length})`;
    papersGrid.innerHTML = currentPapers.map((p, i) => renderPaperCard(p, i)).join('');

    // Attach checkbox listeners
    document.querySelectorAll('.paper-checkbox').forEach(cb => {
      cb.addEventListener('change', onCheckboxChange);
    });

    updateSelectedCount();
    show(papersSection);
    show(paperLookup);
    show(generateConfirm);
    hide(statusSection);

    // Scroll to papers
    papersSection.scrollIntoView({ behavior: 'smooth', block: 'start' });

  } catch (err) {
    errorText.textContent = err.message;
    show(errorBox);
    hide(statusSection);
  } finally {
    setSearchLoading(false);
  }
}

// ── Paper lookup ─────────────────────────────────────────────────
function isAlreadyAdded(paper) {
  return currentPapers.some(p =>
    (paper.semantic_scholar_id && p.semantic_scholar_id === paper.semantic_scholar_id) ||
    (paper.doi && p.doi === paper.doi)
  );
}

function renderLookupResult(paper, idx) {
  const authors = paper.authors.length
    ? escapeHtml(paper.authors.slice(0, 3).join(', ') + (paper.authors.length > 3 ? ' et al.' : ''))
    : 'Unknown authors';
  const year  = paper.year || 'n.d.';
  const venue = paper.venue ? ` · ${escapeHtml(paper.venue)}` : '';
  const added = isAlreadyAdded(paper);
  return `
    <div class="lookup-result">
      <div class="lookup-result-body">
        <div class="lookup-result-title">${escapeHtml(paper.title)}</div>
        <div class="lookup-result-meta">${authors} · ${year}${venue}</div>
      </div>
      <button class="lookup-add-btn${added ? ' lookup-add-btn--added' : ''}"
        data-lookup-idx="${idx}" ${added ? 'disabled' : ''}>
        ${added ? 'Added ✓' : 'Add'}
      </button>
    </div>`;
}

function addLookupPaper(paper, btn) {
  if (isAlreadyAdded(paper)) return;
  const index = currentPapers.length;
  currentPapers.push(paper);
  papersGrid.insertAdjacentHTML('beforeend', renderPaperCard(paper, index));
  const newCheckbox = papersGrid.querySelector(`.paper-checkbox[data-index="${index}"]`);
  if (newCheckbox) newCheckbox.addEventListener('change', onCheckboxChange);
  paperCount.textContent = `(${currentPapers.length})`;
  updateSelectedCount();
  btn.textContent = 'Added ✓';
  btn.classList.add('lookup-add-btn--added');
  btn.disabled = true;
}

paperLookupForm.addEventListener('submit', async e => {
  e.preventDefault();
  const query = paperLookupInput.value.trim();
  if (!query || isSearching || isGenerating) return;

  paperLookupBtn.disabled = true;
  show(paperLookupSpinner);
  hide(paperLookupResults);
  lookupPaperMap = {};

  try {
    const resp = await fetch('/api/paper/lookup', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query }),
    });
    if (!resp.ok) throw new Error(`Server error (${resp.status})`);
    const data = await resp.json();

    if (!data.papers.length) {
      paperLookupResults.innerHTML = '<p class="lookup-empty">No papers found. Try a different title or DOI.</p>';
    } else {
      data.papers.forEach((p, i) => { lookupPaperMap[i] = p; });
      paperLookupResults.innerHTML = data.papers.map((p, i) => renderLookupResult(p, i)).join('');
      paperLookupResults.querySelectorAll('.lookup-add-btn:not([disabled])').forEach(btn => {
        btn.addEventListener('click', () => addLookupPaper(lookupPaperMap[+btn.dataset.lookupIdx], btn));
      });
    }
    show(paperLookupResults);
  } catch (err) {
    paperLookupResults.innerHTML = `<p class="lookup-empty">${escapeHtml(err.message)}</p>`;
    show(paperLookupResults);
  } finally {
    paperLookupBtn.disabled = false;
    hide(paperLookupSpinner);
  }
});

// ── Stage 2: Generate primer ─────────────────────────────────────
generateBtn.addEventListener('click', async () => {
  if (isGenerating) return;

  const indices = getCheckedIndices();
  if (indices.length === 0) {
    errorText.textContent = 'Please select at least one paper.';
    show(errorBox);
    return;
  }

  hide(errorBox);
  const selectedPapers = indices.map(i => currentPapers[i]);
  await streamPrimer(currentTopic, selectedPapers);
});

async function streamPrimer(topic, papers) {
  // Reset only the primer/status sections, leave papers visible
  primerBuffer = '';
  hide(primerSection);
  hide(copyBtn);
  hide(errorBox);
  primerContent.innerHTML = '';
  primerContent.classList.remove('streaming');

  setGenerateLoading(true);

  show(statusSection);
  statusText.textContent = `Preparing primer from ${papers.length} papers…`;

  try {
    const resp = await fetch('/api/generate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ topic, selected_papers: papers }),
    });

    if (!resp.ok) {
      let msg = `Server error (${resp.status})`;
      try { msg = (await resp.json()).detail || msg; } catch { /* ignore */ }
      throw new Error(msg);
    }

    const reader  = resp.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const frames = buffer.split('\n\n');
      buffer = frames.pop();

      for (const frame of frames) {
        const line = frame.trim();
        if (!line.startsWith('data: ')) continue;
        try { handleEvent(JSON.parse(line.slice(6))); }
        catch (e) { console.warn('SSE parse error:', e); }
      }
    }
  } catch (err) {
    errorText.textContent = err.message;
    show(errorBox);
    hide(statusSection);
  } finally {
    setGenerateLoading(false);
  }
}

// ── SSE event dispatcher ─────────────────────────────────────────
function handleEvent(data) {
  switch (data.type) {

    case 'status':
      show(statusSection);
      statusText.textContent = data.message;
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
