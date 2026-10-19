// The landing page: fills in the MCP address, runs the assistant tabs and the copy buttons, and shows the
// current release's numbers (or, with ?release=<id>, an older one under an "old data" banner). Without a
// published release the page still reads as complete and says the data is coming.
const BASE = document.currentScript.dataset.base;
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const getJSON = (path) => fetch(`${BASE}${path}`, { headers: { Accept: 'application/json' } })
  .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))));
const number = (n) => Number(n ?? 0).toLocaleString('en-US');

// ---- the address ---------------------------------------------------------------------------

const MCP_URL = `${location.origin}${BASE}/mcp`;
document.querySelectorAll('[data-mcp]').forEach((el) => { el.textContent = MCP_URL; });

// ---- tabs (the WAI-ARIA tabs pattern: arrows, Home and End move between tabs) ----------------

function tabs(root) {
  const list = root.querySelector('[role="tablist"]');
  const all = [...list.querySelectorAll('[role="tab"]')];
  const select = (tab, focus) => {
    all.forEach((t) => {
      const on = t === tab;
      t.setAttribute('aria-selected', String(on));
      t.tabIndex = on ? 0 : -1;
      $(t.getAttribute('aria-controls')).hidden = !on;
    });
    if (focus) tab.focus();
  };
  all.forEach((tab) => tab.addEventListener('click', () => select(tab, false)));
  list.addEventListener('keydown', (event) => {
    const at = all.indexOf(document.activeElement);
    if (at < 0) return;
    const to = { ArrowRight: at + 1, ArrowLeft: at - 1, Home: 0, End: all.length - 1 }[event.key];
    if (to === undefined) return;
    event.preventDefault();
    select(all[(to + all.length) % all.length], true);
  });
  // Open the tab named in the address (#chatgpt), else the first.
  const wanted = all.find((t) => `#${t.id.replace(/^tab-/, '')}` === location.hash);
  select(wanted || all[0], false);
  root.classList.add('ready');
  if (wanted) root.scrollIntoView();
}
document.querySelectorAll('[data-tabs]').forEach(tabs);

// ---- copy buttons ------------------------------------------------------------------------------

async function copyText(text) {
  if (navigator.clipboard && window.isSecureContext) {
    await navigator.clipboard.writeText(text);
    return;
  }
  const area = document.createElement('textarea');           // plain http, such as a preview on the LAN
  area.value = text;
  area.setAttribute('readonly', '');
  area.style.position = 'fixed';
  area.style.opacity = '0';
  document.body.append(area);
  area.select();
  const ok = document.execCommand('copy');
  area.remove();
  if (!ok) throw new Error('copy refused');
}

document.addEventListener('click', async (event) => {
  const button = event.target.closest('button[data-copy]');
  if (!button) return;
  const source = $(button.dataset.copy);
  const text = source.tagName === 'PRE' ? source.textContent.trim() : source.textContent.replace(/\s+/g, ' ').trim();
  try {
    await copyText(text);
    button.textContent = 'Copied';
    button.classList.add('done');
    $('copied').textContent = 'Copied to the clipboard.';
  } catch {
    const range = document.createRange();                    // let the reader copy it by hand
    range.selectNodeContents(source);
    getSelection().removeAllRanges();
    getSelection().addRange(range);
    button.textContent = 'Select and copy';
    $('copied').textContent = 'Could not copy automatically; the text is selected.';
  }
  setTimeout(() => { button.textContent = 'Copy'; button.classList.remove('done'); }, 2000);
});

// ---- the numbers ---------------------------------------------------------------------------------

function coming() {
  $('numbers').innerHTML = `<p class="coming"><span><b>The data is coming.</b> The first release is being prepared.
    When it is published, its numbers will appear here, and an assistant you connect now will be able to answer
    questions about it.</span></p>`;
  $('no-data-note').hidden = false;
}

function show(release) {
  const p = release.population || {};
  const missing = (p.failed || 0) + (p.not_run || 0);
  $('numbers').innerHTML = `
    <p class="release">Release <b>${esc(release.id)}</b>
      ${release.current ? '<span class="tag">current</span>' : '<span class="tag old">old data</span>'}
      <span class="muted">· built ${esc(String(release.created_at || '').slice(0, 10))}</span></p>
    <div class="cards">
      <div class="card"><b>${number(p.dockets)}</b>dockets read</div>
      <div class="card"><b>${number(p.in_scope)}</b>appeals about new housing</div>
      <div class="card"><b>${number(p.out_of_scope)}</b>other cases, out of scope</div>
      ${missing ? `<div class="card"><b>${number(missing)}</b>not yet answered</div>` : ''}
    </div>`;
}

function oldBanner(release) {
  const banner = $('banner');
  banner.hidden = false;
  banner.innerHTML = `Old data: you are looking at release <b>${esc(release.id)}</b>, which is not the current
    release. Assistants connected to this site always use the current one. <a href="${BASE}/">See the current data</a>.`;
}

function listReleases(releases) {
  if (releases.length < 2) return;
  $('releases').innerHTML = `<details><summary>Earlier releases</summary>
    <table><tr><th>Release</th><th>Built</th><th>Appeals about new housing</th></tr>
    ${releases.map((r) => `<tr><td><a href="?release=${encodeURIComponent(r.id)}">${esc(r.id)}</a>
      ${r.current ? '<span class="tag">current</span>' : ''}</td>
      <td>${esc(String(r.created_at || '').slice(0, 10))}</td><td>${number(r.population?.in_scope)}</td></tr>`).join('')}
    </table></details>`;
}

async function numbers() {
  const health = await getJSON('/healthz');                   // open even when the dashboard has a password
  const wanted = new URLSearchParams(location.search).get('release');
  if (!health.current_release && !wanted) return coming();
  const releases = await getJSON('/api/releases');
  const chosen = releases.find((r) => r.id === wanted) || releases.find((r) => r.current);
  if (!chosen) return coming();
  show(chosen);
  if (!chosen.current) oldBanner(chosen);
  listReleases(releases);
}

numbers().catch(() => {
  $('numbers').innerHTML = `<p class="muted">The latest numbers couldn't be loaded just now. Everything else on this
    page still applies; try reloading in a moment.</p>`;
});
