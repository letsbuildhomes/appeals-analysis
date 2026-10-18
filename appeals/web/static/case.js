// The case view: one docket's text beside the answers that cite it.
import { api, el, short, header, params, setParams } from '/common.js';

let graph, current = null, runId = null;

async function main() {
  header('case');
  graph = await api('graph');
  const search = document.getElementById('search');
  let timer;
  search.addEventListener('input', () => { clearTimeout(timer); timer = setTimeout(() => list(search.value), 200); });
  await list('');
  const p = params();
  if (p.get('docket')) open(p.get('docket'), p.get('run'));
}

async function list(query) {
  const rows = await api(`dockets?limit=400${query ? `&search=${encodeURIComponent(query)}` : ''}`);
  const ul = document.getElementById('dockets');
  ul.innerHTML = '';
  for (const r of rows) {
    if (r.number.startsWith('pdf-')) continue;
    ul.append(el('li', { class: r.number === current ? 'on' : '', onclick: () => open(r.number, null), 'data-n': r.number },
      el('div', { class: 'num' }, r.number),
      el('div', { class: 'ttl' }, `${r.documents} doc${r.documents > 1 ? 's' : ''} · ${r.title || ''}`)));
  }
}

async function open(number, wantedRun) {
  current = number;
  document.querySelectorAll('#dockets li').forEach(li => li.classList.toggle('on', li.dataset.n === number));
  const docket = await api(`dockets/${encodeURIComponent(number)}`);
  runId = wantedRun && docket.runs.includes(wantedRun) ? wantedRun : docket.runs[0] || null;
  setParams({ docket: number, run: runId });
  renderText(docket);
  renderAnswers(docket);
}

function renderText(docket) {
  const reader = document.getElementById('reader');
  reader.innerHTML = '';
  reader.scrollTop = 0;
  const pages = docket.documents.reduce((n, d) => n + d.pages.length, 0);
  reader.append(el('h2', {}, docket.number),
    el('div', { class: 'meta' }, `${docket.documents.length} document${docket.documents.length > 1 ? 's' : ''} · ${pages} pages · ${docket.chars.toLocaleString()} characters`));
  for (const d of docket.documents) {
    reader.append(el('section', { class: 'doc', id: `doc-${d.n}` },
      el('div', { class: 'doc-head' },
        el('div', { class: 't' }, `${d.n}. ${d.title}`),
        el('div', { class: 'm' }, `posted ${d.posted} · dockets ${d.dockets.join(', ')}`,
          d.flags.length ? ` · flags: ${d.flags.join(', ')}` : '')),
      d.pages.map(p => el('div', { class: 'page', id: `p-${d.n}-${p.page}` },
        el('span', { class: 'pno' }, p.page),
        el('pre', {}, p.status === 'usable' ? p.text : `[No selected text: ${p.status}]`)))));
  }
}

async function renderAnswers(docket) {
  const box = document.getElementById('answers');
  box.innerHTML = '';
  const runSelect = el('select', { onchange: e => { runId = e.target.value || null; setParams({ run: runId }); renderAnswers(docket); } },
    docket.runs.length ? docket.runs.map(r => el('option', { value: r, selected: r === runId }, docket.run_tags?.[r]?.length ? `${r} · [${docket.run_tags[r].join(', ')}]` : r)) : el('option', { value: '' }, 'No runs include this docket'));
  box.append(el('div', { class: 'control' }, el('span', {}, 'Run'), runSelect,
    runId ? el('a', { class: 'button', href: `/?run=${encodeURIComponent(runId)}&docket=${encodeURIComponent(docket.number)}` }, 'In graph') : null));
  if (!runId) {
    box.append(el('p', { class: 'why' }, 'Run the pipeline over this docket to see its answers here.'));
    return;
  }
  const { records } = await api(`runs/${encodeURIComponent(runId)}/dockets/${encodeURIComponent(docket.number)}`);
  const facts = records.facts?.value || {}, derived = records.derive?.value || {};
  const plan = records.plan?.value;
  if (plan) box.append(el('p', { class: 'why' }, plan.proceeds ? `Proceeded: ${plan.calls} reasoning calls.` : 'Stopped after the scan: not in scope.'));
  const nodes = graph.nodes;
  for (const topic of graph.topics) {
    const items = nodes.filter(n => n.topic === topic.id && (n.kind === 'field' || n.kind === 'derive'));
    if (!items.length) continue;
    box.append(el('h3', {}, topic.title));
    for (const n of items) {
      const f = n.kind === 'field' ? facts[n.id] : { answer: derived[n.id], source: 'derived', quotes: [] };
      if (!f) continue;
      const ref = docket.reference[n.id];
      box.append(el('div', { class: 'fact' },
        el('div', { class: 'lbl' }, el('code', {}, n.id), n.label,
          el('span', { class: 'src' }, typeof f.source === 'string' ? f.source : 'mixed')),
        el('div', { class: 'ans' }, short(f.answer, 120) || '—'),
        ref !== undefined ? el('div', { class: 'ref' }, `reference: ${short(ref, 80)}`) : null,
        (f.quotes || []).map(q => el('div', { class: 'q', title: q.verified ? 'verified on the page' : 'not found on the page',
          onclick: () => jump(q) }, `${q.verified ? '' : '⚠ '}p.${q.doc}:${q.page} “${short(q.quote, 140)}”`))));
    }
  }
}

function jump(q) {
  const page = document.getElementById(`p-${q.doc}-${q.page}`);
  if (!page) return;
  const pre = page.querySelector('pre');
  pre.innerHTML = pre.textContent.replace(/[&<>]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]));
  const words = q.quote.trim().split(/\s+/).map(w => w.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'));
  if (words.length) {
    const pattern = new RegExp(words.join('\\s+'), 'i');
    const text = pre.textContent;
    const m = text.match(pattern);
    if (m) {
      const esc = s => s.replace(/[&<>]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]));
      pre.innerHTML = esc(text.slice(0, m.index)) + '<mark>' + esc(m[0]) + '</mark>' + esc(text.slice(m.index + m[0].length));
    }
  }
  page.scrollIntoView({ behavior: 'smooth', block: 'center' });
  page.classList.add('flash');
  setTimeout(() => page.classList.remove('flash'), 1400);
}

main().catch(e => {
  document.getElementById('notice').append(el('div', { class: 'notice' }, e.message));
});
