// One appeal's page: its facts in plain words, grouped by topic, each with the passages of the decisions behind
// it. A passage opens its document beside the facts, at its page, with the passage highlighted. The server puts
// the page's data in #page-data, so nothing else loads until a document is opened.
const BASE = document.currentScript.dataset.base;
const SITE = document.currentScript.dataset.site || `${location.origin}${BASE}`;   // the public address, from the server
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const data = JSON.parse($('page-data').textContent);
const main = $('main');
const plural = (n, one, many) => `${n.toLocaleString('en-US')} ${n === 1 ? one : (many || `${one}s`)}`;
const sayDate = (iso) => {
  if (!iso) return '';
  const [y, m, d] = String(iso).split('-').map(Number);
  return new Date(Date.UTC(y, (m || 1) - 1, d || 1)).toLocaleDateString('en-US',
    { timeZone: 'UTC', year: 'numeric', ...(m ? { month: 'long' } : {}), ...(d ? { day: 'numeric' } : {}) });
};

// ---- facts, found by field ------------------------------------------------------------------------

const items = (data.sections || []).flatMap((s) => s.items);
const fact = (field) => items.find((i) => i.field === field);
const known = (field) => (fact(field) && fact(field).known ? fact(field) : null);
const docs = Object.fromEntries((data.documents || []).map((d) => [d.document, d]));
// Court titles read "Case name - Kind of decision": the page is headed by the case, each document by its kind.
const caseName = (title) => String(title || '').split(/\s+-\s+/)[0];
const docKind = (title) => (/\s+-\s+/.test(title || '') ? title.split(/\s+-\s+/).slice(1).join(' - ') : title);

// ---- the page --------------------------------------------------------------------------------------

function notFound() {
  document.title = `Not found · ${document.title.split(' · ').pop()}`;
  const where = data.no_release ? `There is no data with the version <b>${esc(data.version)}</b>.`
    : `There is no docket <b>${esc(data.docket)}</b> in version ${esc(data.version)}.`;
  main.innerHTML = `<div class="notfound">
    <p class="label">Not found</p><h1>We couldn't find that case</h1>
    <p>${where} Docket numbers look like <code>25-ENV-00114</code> or <code>134-7-04 Vtec</code>. Try searching the list of appeals instead.</p>
    <form class="find" action="${BASE}/latest/" method="get" role="search">
      <label for="q">Look for a docket, town or project</label>
      <div><input id="q" name="q" type="search" value="${esc(data.docket)}"><button class="btn btn-primary">Search</button></div>
    </form></div>`;
}

function heading() {
  const town = known('municipality');
  const place = known('place_within_town');
  const years = [...new Set([data.documents[0]?.posted, data.documents.at(-1)?.posted].filter(Boolean)
    .map((d) => d.slice(0, 4)))].join('–');
  const status = data.in_scope === true ? '' : '<span class="tag tag-quiet">Set aside: not an appeal about new housing</span>';
  return `<div class="case-head">
    <p class="label"><a href="${BASE}/${esc(data.version)}/">Appeals</a> <span aria-hidden="true">/</span> Docket ${esc(data.docket)} ${status}</p>
    <h1>${esc(caseName(data.title) || `Docket ${data.docket}`)}</h1>
    <p class="case-meta">${[town && `${esc(town.value)}${place ? `, ${esc(place.value)}` : ''}`, years,
      plural(data.documents.length, 'published ruling')].filter(Boolean).join('<span aria-hidden="true"> · </span>')}</p>
    ${data.note ? `<p class="note">${esc(data.note)}</p>` : ''}
  </div>`;
}

function outcomeTone(value) {
  const v = String(value || '').toLowerCase();
  if (v.startsWith('approved') || v.startsWith('granted')) return v.includes('part') ? 'mixed' : 'yes';
  if (v === 'denied') return 'no';
  if (v === 'sent back') return 'mixed';
  return 'unknown';
}

function story() {
  if (data.in_scope !== true) return '';
  const town = fact('town_decision'), court = fact('court_result'), ended = known('how_ended');
  const townDate = known('town_decision_date'), courtDate = known('final_decision_date');
  const filed = known('filing_date') || known('docket_filing');
  const mix = known('appellant_mix');
  const cell = (label, f, sub) => `<div class="beat">
      <p class="label">${label}</p>
      <p class="outcome tone-${f && f.known ? outcomeTone(f.value) : 'unknown'}">${esc(f && f.known ? f.value : 'Not stated')}</p>
      ${sub.filter(Boolean).map((t) => `<p class="beat-sub">${esc(t)}</p>`).join('')}</div>`;
  const duration = fact('duration');
  const [took, about] = duration && duration.known ? (duration.value.match(/^(.*?)(?: \((.*)\))?$/) || []).slice(1) : [];
  const units = ['units_added_proposed', 'units_added_town_approved', 'units_added_court_approved'].map(fact);
  const lots = known('housing_lots');
  const changed = known('court_changed_outcome');
  return `<section class="ledger" aria-label="The case at a glance">
    <div class="beats">
      ${cell('The town', town, [townDate && townDate.value])}
      <span class="beat-arrow" aria-hidden="true">→</span>
      <div class="beat"><p class="label">The appeal</p>
        <p class="outcome tone-neutral">${esc(mix ? mix.value.split(':')[0].replace(/^./, (c) => c.toUpperCase()) : 'Appealed')}</p>
        ${filed ? `<p class="beat-sub">Filed ${esc(filed.value)}</p>` : ''}</div>
      <span class="beat-arrow" aria-hidden="true">→</span>
      ${cell('The court', court, [courtDate && courtDate.value, ended && ended.value])}
    </div>
    <div class="figures">
      <div class="figure"><p class="label">How long it took</p>
        <p class="figure-value">${esc(took || 'Not known')}</p>${about ? `<p class="beat-sub">${esc(about)}</p>` : ''}
        ${duration && duration.days ? `<span class="span-bar ${duration.bound === 'at least' ? 'open' : ''}" style="--w:${Math.min(100, 6 + duration.days / 18)}%" aria-hidden="true"><i></i></span>` : ''}</div>
      ${units.some((u) => u && u.known) ? `<div class="figure"><p class="label">New homes</p>
        <div class="units">${units.map((u, i) => `<span class="unit"><b>${esc(u && u.known ? u.value : '–')}</b>${['proposed', 'town approved', 'court approved'][i]}</span>`).join('<span class="unit-arrow" aria-hidden="true">→</span>')}</div>
        ${lots && lots.value !== '0' ? `<p class="beat-sub">and ${esc(lots.value)} new housing ${lots.value === '1' ? 'lot' : 'lots'}</p>` : ''}</div>` : ''}
      ${changed ? `<div class="figure"><p class="label">Court ended somewhere different from the town</p>
        <p class="figure-value">${esc(changed.value)}</p></div>` : ''}
    </div>
  </section>`;
}

function contents() {
  const links = [...(data.sections || []).map((s, i) => [`topic-${i}`, s.topic]), ['timeline', 'Timeline'],
    ['documents', 'Documents']];
  if (data.linked.length) links.push(['linked', 'Linked cases']);
  return `<nav class="contents" aria-label="On this page"><p class="label">On this page</p>
    ${links.map(([id, label]) => `<a href="#${id}" data-spy="${id}">${esc(label)}</a>`).join('')}
    <label class="toggle"><input type="checkbox" id="show-quiet"> Also show questions the rulings don't answer</label>
  </nav>`;
}

// ---- quotes ----------------------------------------------------------------------------------------

function quotesBlock(item, id) {
  if (!item.quotes || !item.quotes.length) return '';
  return `<div class="sources" id="${id}" hidden>
    ${item.quotes.map((q) => {
      const doc = docs[q.document] || {};
      const pdf = doc.url ? `${doc.url}#page=${q.page}` : null;
      return `<figure class="source">
        <blockquote><button type="button" class="quote-open" data-doc="${q.document}" data-page="${q.page}"
          data-quote="${esc(q.quote)}">“${esc(q.quote)}”</button></blockquote>
        <figcaption>Document ${q.document}${doc.title ? `, ${esc(doc.title)}` : ''} · page ${q.page}
          <span class="source-links"><button type="button" class="linkish" data-doc="${q.document}" data-page="${q.page}"
            data-quote="${esc(q.quote)}">Read it in place</button>${pdf ? ` · <a href="${esc(pdf)}" target="_blank" rel="noopener">PDF, page ${q.page} ↗</a>` : ''}</span>
        </figcaption></figure>`;
    }).join('')}</div>`;
}

function sourceButton(item, id) {
  const n = item.quotes ? item.quotes.length : 0;
  if (!n) return '';
  return `<button type="button" class="source-toggle" aria-expanded="false" aria-controls="${id}">
    <span class="qmark" aria-hidden="true">“</span>${plural(n, 'source')}<span class="caret" aria-hidden="true"></span></button>`;
}

// ---- sections ----------------------------------------------------------------------------------------

let uid = 0;

function factRow(item) {
  const id = `src-${uid++}`;
  return `<div class="fact ${item.known ? '' : 'quiet'}">
    <div class="fact-label">${esc(item.label)}</div>
    <div class="fact-value"><b>${esc(item.value)}</b>
      ${item.detail ? `<span class="fact-detail">${esc(item.detail)}</span>` : ''}
      ${item.meaning ? `<button type="button" class="fact-meaning" aria-expanded="false" title="Show the full definition">${esc(item.meaning)}</button>` : ''}</div>
    <div class="fact-source">${sourceButton(item, id)}</div>
    ${quotesBlock(item, id)}
  </div>`;
}

function listBlock(item, topic) {
  const id = `src-${uid++}`;
  let body;
  if (item.not_stated) body = '<p class="muted">Not stated.</p>';
  else if (item.empty) body = '<p class="muted">None.</p>';
  else {
    body = `<div class="table-wrap"><table><thead><tr>${item.columns.map((c) => `<th scope="col">${esc(c)}</th>`).join('')}</tr></thead>
      <tbody>${item.rows.map((r) => `<tr>${r.map((v) => `<td class="${v === 'Not stated' ? 'muted' : ''}">${esc(v)}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`;
  }
  return `<div class="block ${item.empty || item.not_stated ? 'quiet' : ''}">
    <div class="block-head">${item.label === topic ? '<span></span>' : `<h3>${esc(item.label)}</h3>`}${sourceButton(item, id)}</div>
    ${body}${quotesBlock(item, id)}</div>`;
}

function chip(answer) {
  const a = String(answer).toLowerCase();
  const tone = /^(yes|decided, disputed|met|granted|upheld)/.test(a) ? 'yes'
    : /^(no|not at issue|not decided|—)/.test(a) ? 'none' : /not met|denied|struck/.test(a) ? 'no' : 'mid';
  return `<span class="chip-answer tone-${tone}">${esc(answer)}</span>`;
}

function gridBlock(item, topic) {
  const id = `src-${uid++}`;
  const single = item.columns.length === 1;
  let body = '';
  if (item.rows.length) {
    body = single
      ? `<ul class="pills">${item.rows.map((r) => `<li title="${esc(r.meaning || '')}"><b>${esc(r.item)}</b>${r.answers[0] === 'Yes' ? '' : ` ${chip(r.answers[0])}`}</li>`).join('')}</ul>`
      : `<div class="table-wrap"><table class="grid"><thead><tr><th scope="col">Issue</th>${item.columns.map((c) => `<th scope="col">${esc(c)}</th>`).join('')}</tr></thead>
        <tbody>${item.rows.map((r) => `<tr><th scope="row"><span title="${esc(r.meaning || '')}">${esc(r.item)}</span></th>${r.answers.map((a) => `<td>${chip(a)}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`;
  }
  const quiet = item.quiet.length ? `<p class="quiet-items"><span>${esc(item.quiet_answer ? item.quiet_answer[0].toUpperCase() + item.quiet_answer.slice(1) : 'None')}:</span> ${item.quiet.map(esc).join(', ')}</p>` : '';
  return `<div class="block">
    <div class="block-head">${item.label === topic ? '<span></span>' : `<h3>${esc(item.label)}</h3>`}${sourceButton(item, id)}</div>
    ${body || (item.quiet.length ? '' : '<p class="muted">Not stated.</p>')}${quiet}${quotesBlock(item, id)}</div>`;
}

function sections() {
  return (data.sections || []).map((s, i) => {
    const facts = s.items.filter((it) => !it.kind);
    const blocks = s.items.filter((it) => it.kind);
    const quiet = facts.filter((f) => !f.known).length;
    return `<section class="topic" id="topic-${i}" aria-labelledby="topic-${i}-title">
      <h2 id="topic-${i}-title">${esc(s.topic)}</h2>
      ${facts.length ? `<div class="facts-list">${facts.map(factRow).join('')}</div>` : ''}
      ${quiet ? `<p class="quiet-note">${quiet === 1 ? 'One question' : `${quiet} questions`} the rulings don't answer ${quiet === 1 ? 'is' : 'are'} hidden.</p>` : ''}
      ${blocks.map((b) => (b.kind === 'grid' ? gridBlock(b, s.topic) : listBlock(b, s.topic))).join('')}
    </section>`;
  }).join('');
}

function timeline() {
  const events = data.timeline || [];
  if (!events.length) return '';
  return `<section class="topic" id="timeline" aria-labelledby="timeline-title"><h2 id="timeline-title">Timeline</h2>
    <ol class="timeline">${events.map((e) => `<li class="ev-${e.kind}">
      <time datetime="${esc(e.date)}">${esc(e.say)}</time>
      <span>${e.kind === 'document' ? `<button type="button" class="linkish" data-doc="${e.document}" data-page="1">${esc(e.label)}</button>${docs[e.document]?.title ? `<span class="muted">: ${esc(docKind(docs[e.document].title))}</span>` : ''}` : esc(e.label)}</span>
    </li>`).join('')}</ol></section>`;
}

function documentsList() {
  return `<section class="topic" id="documents" aria-labelledby="documents-title"><h2 id="documents-title">Documents</h2>
    <p class="muted small">The court's published rulings in this case, numbered in the order they were posted. Sources above refer to these numbers.</p>
    <ol class="doc-list">${data.documents.map((d) => `<li>
      <span class="doc-n">${d.document}</span>
      <div><b title="${esc(d.title || '')}">${esc(docKind(d.title) || 'Untitled decision')}</b>
        <span class="muted">Posted ${esc(sayDate(d.posted) || 'on an unknown date')} · ${plural(d.pages || 0, 'page')}</span></div>
      <div class="doc-actions">${data.has_pages && data.in_scope === true ? `<button type="button" class="btn btn-small" data-doc="${d.document}" data-page="1">Read</button>` : ''}
        ${d.url ? `<a class="btn-link small" href="${esc(d.url)}" target="_blank" rel="noopener">PDF ↗</a>` : ''}</div>
    </li>`).join('')}</ol></section>`;
}

function linked() {
  if (!data.linked.length) return '';
  return `<section class="topic" id="linked" aria-labelledby="linked-title"><h2 id="linked-title">Linked cases</h2>
    <p class="muted small">These cases share a ruling with this one, which usually means they concern the same
      project. Adding up homes across them would count the same homes twice.</p>
    <ul class="linked">${data.linked.map((l) => `<li><a href="${BASE}/${esc(data.version)}/${esc(l.slug)}">${esc(l.linked_docket)}</a>
      <span class="muted">${plural(l.shared_documents, 'shared ruling')}${l.linked_in_scope ? '' : ' · not a housing appeal'}</span></li>`).join('')}</ul></section>`;
}

function askAndCite() {
  const address = data.address || `${SITE}/${data.version}/${data.slug}`;
  return `<section class="topic closing" aria-labelledby="ask-title"><h2 id="ask-title">Ask about this case, or cite it</h2>
    <div class="closing-grid">
      <div><p class="label">Ask your AI assistant</p>
        <p class="closing-quote" id="ask-prompt">Tell me about docket ${esc(data.docket)} in the Vermont housing appeals data, and what the court decided.</p>
        <p><button type="button" class="copy" data-copy="ask-prompt">Copy</button>
          <a class="btn-link small" href="${BASE}/#connect">Connect your assistant <span aria-hidden="true">→</span></a></p></div>
      <div><p class="label">Cite this page</p>
        <p class="closing-cite" id="cite">Vermont municipal housing appeals data, ${esc(data.version)} (built ${esc(data.built)}), docket ${esc(data.docket)}. ${esc(address)}</p>
        <p><button type="button" class="copy" data-copy="cite">Copy</button></p></div>
    </div>
    <p class="small muted">These facts were drawn from the rulings with the help of AI and checked against the rulings'
      text, but mistakes are possible. Use the sources to confirm anything important. <q>Not stated</q> means the
      rulings don't say, which is different from <q>no</q>.</p></section>`;
}

function render() {
  if (!data.found) return notFound();
  if (!data.current) {
    const banner = $('banner');
    banner.hidden = false;
    banner.innerHTML = `You are looking at version <b>${esc(data.version)}</b>, which is not the current data.
      ${data.current_version ? `<a href="${BASE}/${esc(data.current_version)}/${esc(data.slug)}">See this case in ${esc(data.current_version)}</a>.` : ''}`;
  }
  main.innerHTML = `${heading()}${story()}
    ${data.in_scope === true ? '<p class="how-to-read">Below is everything we recorded about this case, grouped by topic. Select <b>sources</b> next to an answer to read the passage of the ruling it came from.</p>' : ''}
    <div class="case-body">${contents()}<div class="case-main">${sections()}${timeline()}${documentsList()}${linked()}${askAndCite()}</div></div>
    <p class="version-line muted small">Version ${esc(data.version)}, built ${esc(data.built)}${data.current ? ' (current)' : ''}.
      Source: rulings of the Vermont Superior Court, Environmental Division, published at <a href="https://www.vtcourts.gov/opinions-decisions">vtcourts.gov</a>.</p>`;
}

// ---- the reader: a document's text, at the quote's page --------------------------------------------

// Quotes were checked against the page with spacing, case and punctuation evened out, so they are found the same
// way here. `fold` returns the folded text and, for each folded character, where it came from.
function fold(text) {
  const out = [], from = [];
  let space = true;
  for (let i = 0; i < text.length; i++) {
    let c = text[i].replace(/[’‘]/, "'").replace(/[“”]/, '"').toLowerCase();
    if (!/[\p{L}\p{N}_\s'".,;:()-]/u.test(c)) c = ' ';
    if (/\s/.test(c)) {
      if (!space) { out.push(' '); from.push(i); space = true; }
      continue;
    }
    if (out.length >= 2 && out.at(-1) === ' ' && out.at(-2) === '-' && /[\p{L}\p{N}_]/u.test(c)
        && /[\p{L}\p{N}_]/u.test(out.at(-3) || '')) { out.pop(); from.pop(); }   // a word broken across a line
    out.push(c); from.push(i); space = false;
  }
  if (out.at(-1) === ' ') { out.pop(); from.pop(); }
  return { text: out.join(''), from };
}

function locate(pages, startPage, quote) {
  // The quote may run onto the next page, so search the page and the one after it, joined.
  const at = pages.findIndex((p) => p.page === startPage);
  if (at < 0) return null;
  const pair = pages.slice(at, at + 2);
  const joined = pair.map((p) => p.text || '').join('\n');
  const hay = fold(joined), needle = fold(quote).text;
  const found = needle ? hay.text.indexOf(needle) : -1;
  if (found < 0) return null;
  const start = hay.from[found], end = hay.from[found + needle.length - 1] + 1;
  const ranges = {};
  let offset = 0;
  pair.forEach((p) => {
    const len = (p.text || '').length;
    const s = Math.max(start, offset), e = Math.min(end, offset + len);
    if (s < e) ranges[p.page] = [s - offset, e - offset];
    offset += len + 1;
  });
  return ranges;
}

const cache = {};
let lastFocus = null;

async function openReader(n, page, quote) {
  const doc = docs[n] || {};
  lastFocus = document.activeElement;
  $('reader-kicker').textContent = `Document ${n} of ${data.documents.length}${doc.posted ? ` · posted ${sayDate(doc.posted)}` : ''}`;
  $('reader-title').textContent = doc.title || 'Decision';
  $('reader-tools').innerHTML = `${doc.url ? `<a class="btn btn-small" href="${esc(doc.url)}#page=${page}" target="_blank" rel="noopener">Open the court's PDF at page ${page} ↗</a>` : ''}
    ${quote ? `<span class="muted small">The quoted passage is highlighted.</span>` : ''}`;
  const body = $('reader-body');
  body.innerHTML = '<p class="muted">Loading the document…</p>';
  $('reader').hidden = false;
  $('scrim').hidden = false;
  document.body.classList.add('reading');
  $('reader-close').focus();
  try {
    const key = `${n}`;
    cache[key] = cache[key] || await fetch(`${BASE}/api/versions/${encodeURIComponent(data.version)}/dockets/${encodeURIComponent(data.slug)}/documents/${n}`)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))));
    const pages = cache[key].text || [];
    if (!pages.length) {
      body.innerHTML = `<p>The text of this document isn't included in this version of the data.
        ${doc.url ? `Open the <a href="${esc(doc.url)}#page=${page}" target="_blank" rel="noopener">court's PDF at page ${page}</a> to read it.` : ''}</p>`;
      return;
    }
    const ranges = quote ? locate(pages, page, quote) : null;
    body.innerHTML = pages.map((p) => {
      let html;
      const tidy = (t) => esc(t.replace(/\n[ \t]*(?=\n)/g, ''));            // the PDF's empty lines between lines
      if (p.text == null) html = '<p class="muted">This page has no readable text. See the PDF.</p>';
      else if (ranges && ranges[p.page]) {
        const [s, e] = ranges[p.page];
        html = `<pre>${tidy(p.text.slice(0, s))}<mark>${tidy(p.text.slice(s, e))}</mark>${tidy(p.text.slice(e))}</pre>`;
      } else html = `<pre>${tidy(p.text)}</pre>`;
      return `<section class="sheet ${p.page === page ? 'target' : ''}" id="sheet-${p.page}" aria-label="Page ${p.page}">
        <p class="sheet-n">Page ${p.page}</p>${html}</section>`;
    }).join('');
    const target = body.querySelector('mark') || $(`sheet-${page}`);
    if (target) target.scrollIntoView({ block: target.tagName === 'MARK' ? 'center' : 'start' });
    if (quote && !ranges) {
      $('reader-tools').insertAdjacentHTML('beforeend', '<span class="muted small">The passage is on this page; its exact place couldn\'t be marked.</span>');
    }
  } catch {
    body.innerHTML = `<p>The document couldn't be loaded just now.
      ${doc.url ? `Open the <a href="${esc(doc.url)}#page=${page}" target="_blank" rel="noopener">court's PDF at page ${page}</a> instead.` : ''}</p>`;
  }
}

function closeReader() {
  $('reader').hidden = true;
  $('scrim').hidden = true;
  document.body.classList.remove('reading');
  if (lastFocus) lastFocus.focus();
}

// ---- interaction -----------------------------------------------------------------------------------

async function copyText(text) {
  if (navigator.clipboard && window.isSecureContext) return navigator.clipboard.writeText(text);
  const area = Object.assign(document.createElement('textarea'), { value: text });
  area.style.position = 'fixed'; area.style.opacity = '0';
  document.body.append(area); area.select();
  const ok = document.execCommand('copy'); area.remove();
  if (!ok) throw new Error('copy refused');
}

document.addEventListener('click', async (event) => {
  const toggle = event.target.closest('.source-toggle');
  if (toggle) {
    const open = toggle.getAttribute('aria-expanded') !== 'true';
    toggle.setAttribute('aria-expanded', String(open));
    $(toggle.getAttribute('aria-controls')).hidden = !open;
    return;
  }
  const meaning = event.target.closest('.fact-meaning');
  if (meaning) {
    meaning.setAttribute('aria-expanded', String(meaning.getAttribute('aria-expanded') !== 'true'));
    return;
  }
  const opener = event.target.closest('[data-doc]');
  if (opener) {
    if (!data.has_pages || data.in_scope !== true) {
      const doc = docs[opener.dataset.doc];
      if (doc && doc.url) window.open(`${doc.url}#page=${opener.dataset.page}`, '_blank', 'noopener');
      return;
    }
    openReader(Number(opener.dataset.doc), Number(opener.dataset.page), opener.dataset.quote);
    return;
  }
  if (event.target.closest('#reader-close') || event.target.id === 'scrim') return closeReader();
  const button = event.target.closest('button[data-copy]');
  if (button) {
    try {
      await copyText($(button.dataset.copy).textContent.replace(/\s+/g, ' ').trim());
      button.textContent = 'Copied';
      $('copied').textContent = 'Copied to the clipboard.';
    } catch { button.textContent = 'Select and copy'; }
    setTimeout(() => { button.textContent = 'Copy'; }, 2000);
  }
});

document.addEventListener('change', (event) => {
  if (event.target.id === 'show-quiet') document.body.classList.toggle('show-quiet', event.target.checked);
});

document.addEventListener('keydown', (event) => {
  if ($('reader').hidden) return;
  if (event.key === 'Escape') closeReader();
  if (event.key === 'Tab') {                                     // keep focus inside the open document
    const focusable = [...$('reader').querySelectorAll('a, button, [tabindex="0"]')];
    const first = focusable[0], last = focusable.at(-1);
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
  }
});

render();

// The contents list marks the section being read: the last one whose heading has passed the top bar.
if (data.found) {
  const links = [...document.querySelectorAll('[data-spy]')];
  const targets = links.map((a) => $(a.dataset.spy));
  let queued = false;
  const mark = () => {
    queued = false;
    let at = 0;
    targets.forEach((el, i) => { if (el && el.getBoundingClientRect().top < 140) at = i; });
    links.forEach((a, i) => a.toggleAttribute('aria-current', i === at));
  };
  addEventListener('scroll', () => { if (!queued) { queued = true; requestAnimationFrame(mark); } }, { passive: true });
  mark();
}
