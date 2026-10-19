// The list of appeals in one version: find a case by docket, town or name, filter by outcome, and open its page.
const BASE = document.currentScript.dataset.base;
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const data = JSON.parse($('page-data').textContent);
const main = $('main');
const cap = (s) => (s ? s[0].toUpperCase() + s.slice(1) : '');
const day = (iso) => (iso ? new Date(`${iso}T12:00:00Z`).toLocaleDateString('en-US', { timeZone: 'UTC', year: 'numeric', month: 'short', day: 'numeric' }) : '');
const say = (v) => (v == null || v === 'not stated' ? '<span class="muted">Not stated</span>' : esc(cap(v)));
const COLUMNS = [
  ['docket', 'Docket'], ['title', 'Case'], ['municipality', 'Town'], ['town_decision', "Town's decision"],
  ['court_result', 'What the court did'], ['last_posted', 'Latest ruling'],
].filter(([k]) => ['docket', 'title', 'last_posted', ...(data.columns || [])].includes(k));
let sortKey = 'last_posted', descending = true;

function options(key) {
  return [...new Set(data.appeals.map((a) => a[key]).filter(Boolean))].sort();
}

function frame() {
  if (data.missing) {
    main.innerHTML = `<div class="notfound"><h1>No data with that version</h1>
      <p>There is no version <b>${esc(data.missing)}</b>. <a href="${BASE}/latest/">See the current data</a>.</p></div>`;
    return false;
  }
  if (!data.current) {
    $('banner').hidden = false;
    $('banner').innerHTML = `You are looking at version <b>${esc(data.version)}</b>, which is not the current data.
      ${data.current_version ? `<a href="${BASE}/${esc(data.current_version)}/">See the current version</a>.` : ''}`;
  }
  const select = (key, label) => (data.columns.includes(key) ? `<label>${label}<select data-filter="${key}">
      <option value="">Any</option>${options(key).map((o) => `<option value="${esc(o)}">${esc(cap(o))}</option>`).join('')}</select></label>` : '');
  main.innerHTML = `<div class="browse-head">
      <p class="label">Version ${esc(data.version)} · built ${esc(data.built)}</p>
      <h1>All appeals</h1>
      <p>Every case in the data: ${data.appeals.length.toLocaleString('en-US')} appeals of a Vermont town's decision on
        new housing. Search by town, case name or docket number, or filter by outcome. Open a case to see everything we
        recorded about it and the passages of the court's rulings behind each answer.</p></div>
    <form class="finder" role="search" onsubmit="return false">
      <label class="grow">Search<input id="q" type="search" placeholder="Docket number, town or case name" autocomplete="off"></label>
      ${select('town_decision', "Town's decision")}${select('court_result', 'What the court did')}
    </form>
    <p class="count-line"><span id="count" aria-live="polite"></span> <span class="muted">“Not stated” means the rulings don't say.</span></p>
    <table class="appeal-table"><thead><tr>${COLUMNS.map(([k, label]) => `<th scope="col"><button type="button" data-sort="${k}">${esc(label)}<span aria-hidden="true" data-arrow="${k}"></span></button></th>`).join('')}</tr></thead>
      <tbody id="rows"></tbody></table>`;
  return true;
}

function rows() {
  const q = $('q').value.trim().toLowerCase();
  const filters = [...document.querySelectorAll('[data-filter]')].filter((s) => s.value);
  const shown = data.appeals.filter((a) => (!q || [a.docket, a.title, a.municipality].some((v) => String(v || '').toLowerCase().includes(q)))
    && filters.every((s) => a[s.dataset.filter] === s.value));
  shown.sort((a, b) => {
    const x = a[sortKey] ?? '', y = b[sortKey] ?? '';
    return (x < y ? -1 : x > y ? 1 : 0) * (descending ? -1 : 1);
  });
  $('count').textContent = shown.length === data.appeals.length ? `Showing all ${shown.length} appeals.`
    : `Showing ${shown.length} of ${data.appeals.length} appeals.`;
  document.querySelectorAll('[data-arrow]').forEach((el) => { el.textContent = el.dataset.arrow === sortKey ? (descending ? ' ↓' : ' ↑') : ''; });
  document.querySelectorAll('[data-sort]').forEach((b) => b.closest('th').setAttribute('aria-sort',
    b.dataset.sort === sortKey ? (descending ? 'descending' : 'ascending') : 'none'));
  const link = (a) => `${BASE}/${encodeURIComponent(data.version)}/${a.slug}`;
  $('rows').innerHTML = shown.map((a) => `<tr>${COLUMNS.map(([k, label]) => {
    if (k === 'docket') return `<td class="num"><a href="${link(a)}">${esc(a.docket)}</a></td>`;
    if (k === 'title') return `<td><a href="${link(a)}">${esc(String(a.title || 'Untitled').split(/\s+-\s+/)[0])}</a></td>`;
    if (k === 'last_posted') return `<td data-label="${label}"><time datetime="${esc(a.last_posted || '')}">${esc(day(a.last_posted))}</time></td>`;
    return `<td data-label="${label}">${say(a[k])}</td>`;
  }).join('')}</tr>`).join('') || `<tr><td colspan="${COLUMNS.length}" class="muted">No appeals match.</td></tr>`;
}

if (frame()) {
  const q = new URLSearchParams(location.search).get('q');
  if (q) $('q').value = q;
  main.addEventListener('input', rows);
  main.addEventListener('click', (event) => {
    const b = event.target.closest('[data-sort]');
    if (!b) return;
    descending = sortKey === b.dataset.sort ? !descending : b.dataset.sort === 'last_posted';
    sortKey = b.dataset.sort;
    rows();
  });
  rows();
}
