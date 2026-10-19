// The landing page: the hero numbers (or, with ?release=<id>, an older release under an "old data" banner), the
// walkthrough, and the dialog that shows how to connect an assistant. Without a published release the page still
// reads as complete and says the data is coming.
const BASE = document.currentScript.dataset.base;
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const getJSON = (path) => fetch(`${BASE}${path}`, { headers: { Accept: 'application/json' } })
  .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))));
const number = (n) => Number(n ?? 0).toLocaleString('en-US');

const SITE = document.currentScript.dataset.site || `${location.origin}${BASE}`;   // the public address, from the server
const MCP_URL = `${SITE}/mcp`;
document.querySelectorAll('[data-mcp]').forEach((el) => { el.textContent = MCP_URL; });

// ---- the connect dialog ------------------------------------------------------------------------
// Opened by any link to #connect, including from other pages, so /appeals/#connect lands with it open.

const dialog = $('connect');

function openConnect(app) {
  if (app) selectApp($(`tab-${app}`));
  if (!dialog.open) dialog.showModal();
  if (location.hash !== '#connect') history.replaceState(null, '', '#connect');
}
dialog.addEventListener('close', () => {
  if (location.hash === '#connect') history.replaceState(null, '', location.pathname + location.search);
});
dialog.addEventListener('click', (event) => {
  if (event.target === dialog || event.target.closest('[data-close]')) dialog.close();    // the backdrop, or ✕
});
document.addEventListener('click', (event) => {
  const link = event.target.closest('[data-connect]');
  if (!link) return;
  event.preventDefault();
  openConnect();
});

const appTabs = [...dialog.querySelectorAll('[role="tab"]')];
function selectApp(tab, focus) {
  appTabs.forEach((t) => {
    const on = t === tab;
    t.setAttribute('aria-selected', String(on));
    t.tabIndex = on ? 0 : -1;
    $(t.getAttribute('aria-controls')).hidden = !on;
  });
  if (focus) tab.focus();
}
appTabs.forEach((tab) => tab.addEventListener('click', () => selectApp(tab)));
dialog.querySelector('[role="tablist"]').addEventListener('keydown', (event) => {
  const at = appTabs.indexOf(document.activeElement);
  const to = { ArrowDown: at + 1, ArrowRight: at + 1, ArrowUp: at - 1, ArrowLeft: at - 1, Home: 0,
               End: appTabs.length - 1 }[event.key];
  if (at < 0 || to === undefined) return;
  event.preventDefault();
  selectApp(appTabs[(to + appTabs.length) % appTabs.length], true);
});
if (location.hash === '#connect') openConnect();

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
  (dialog.open ? dialog : document.body).append(area);       // inside the dialog, or the modal blocks the copy
  area.select();
  const ok = document.execCommand('copy');
  area.remove();
  if (!ok) throw new Error('copy refused');
}

document.addEventListener('click', async (event) => {
  const button = event.target.closest('button.copy');
  if (!button) return;
  const text = button.dataset.copyText ?? ('copyMcp' in button.dataset ? MCP_URL
    : $(button.dataset.copy).textContent.replace(/\s+/g, ' ').trim());
  try {
    await copyText(text);
    button.textContent = 'Copied';
    button.classList.add('done');
    $('copied').textContent = 'Copied to the clipboard.';
  } catch {
    button.textContent = 'Copy failed';
    $('copied').textContent = 'Could not copy automatically; select the text and copy it.';
  }
  setTimeout(() => { button.textContent = 'Copy'; button.classList.remove('done'); }, 1800);
});

// ---- the numbers ---------------------------------------------------------------------------------

function coming() {
  $('numbers').innerHTML = `<p class="label">Coming soon</p>
    <p>The first release is being prepared. When it is published, its numbers will appear here, and an assistant
      you connect now will be able to answer questions about it.</p>`;
}

function fillNumbers(release) {
  const p = release.population || {};
  document.querySelectorAll('[data-n]').forEach((el) => {
    const n = p[el.dataset.n];
    if (n) el.textContent = number(n);
  });
  document.querySelectorAll('[data-version]').forEach((el) => { el.textContent = release.version; });
  document.querySelectorAll('a[data-browse]').forEach((a) => { a.href = `${BASE}/${release.version}/`; });
}

function show(release) {
  fillNumbers(release);
  const p = release.population || {};
  const missing = p.not_determined || 0;
  $('numbers').innerHTML = `
    <p class="label">In the data · version ${esc(release.version)}${release.current ? '' : ' · old data'}</p>
    <div class="stat stat-lead"><b>${number(p.in_scope)}</b><span>appeals about new housing</span></div>
    <div class="stat"><b>${number(p.dockets)}</b><span>court cases read to find them</span></div>
    ${missing ? `<div class="stat"><b>${number(missing)}</b><span>cases we couldn't classify</span></div>` : ''}
    <p class="stat-note">Updated ${esc(release.built)}, from every ruling the court has posted since 2000.</p>`;
}

function oldBanner(release) {
  const banner = $('banner');
  banner.hidden = false;
  banner.innerHTML = `Old data: you are looking at version <b>${esc(release.version)}</b>, which is not the current
    one. Assistants connected to this site always use the current one. <a href="${BASE}/">See the current data</a>.`;
}

function listReleases(releases) {
  if (releases.length < 2) return;
  $('releases').innerHTML = `<details><summary>Earlier versions</summary>
    <table><tr><th>Version</th><th>Built</th><th>Appeals about new housing</th></tr>
    ${releases.map((r) => `<tr><td><a href="?release=${encodeURIComponent(r.id)}">${esc(r.version)}</a>
      ${r.current ? '<span class="tag">current</span>' : ''}</td>
      <td>${esc(r.built)}</td><td>${number(r.population?.in_scope)}</td></tr>`).join('')}
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
  $('numbers').innerHTML = '<p class="muted">The latest numbers couldn\'t be loaded just now. Try reloading in a moment.</p>';
});

// ---- the walkthrough ---------------------------------------------------------------------------
// Seven scenes, one at a time. It plays by itself only while it is on screen, stops for good once the reader
// steps through it, and never plays for readers who ask for less motion.

function walkthrough(root) {
  const tabs = [...root.querySelectorAll('[role="tab"]')];
  const scenes = tabs.map((t) => $(t.getAttribute('aria-controls')));
  const bar = root.querySelector('.walk-progress i');
  const play = root.querySelector('[data-walk-play]');
  const still = matchMedia('(prefers-reduced-motion: reduce)').matches;
  const DWELL = 7000;
  let at = 0, timer = null, playing = !still, visible = false;

  const go = (i, focus) => {
    at = (i + tabs.length) % tabs.length;
    tabs.forEach((t, j) => {
      t.setAttribute('aria-selected', String(j === at));
      t.tabIndex = j === at ? 0 : -1;
      t.parentElement.classList.toggle('done', j < at);
      scenes[j].hidden = j !== at;
      scenes[j].classList.remove('on');
    });
    void scenes[at].offsetWidth;                                // restart the scene's animations
    scenes[at].classList.add('on');
    if (focus) tabs[at].focus();
    schedule();
  };
  const schedule = () => {
    clearTimeout(timer);
    bar.style.transition = 'none';
    bar.style.width = `${(at / tabs.length) * 100}%`;
    if (!(playing && visible)) return;
    void bar.offsetWidth;
    bar.style.transition = `width ${DWELL}ms linear`;
    bar.style.width = `${((at + 1) / tabs.length) * 100}%`;
    timer = setTimeout(() => go(at + 1), DWELL);
  };
  const setPlaying = (on) => {
    playing = on;
    play.textContent = on ? '❚❚' : '▶';
    play.setAttribute('aria-label', on ? 'Pause the walkthrough' : 'Play the walkthrough');
    schedule();
  };
  const byHand = (i, focus) => { setPlaying(false); go(i, focus); };

  tabs.forEach((t, i) => t.addEventListener('click', () => byHand(i, false)));
  root.querySelector('[role="tablist"]').addEventListener('keydown', (event) => {
    const to = { ArrowRight: at + 1, ArrowLeft: at - 1, Home: 0, End: tabs.length - 1 }[event.key];
    if (to === undefined) return;
    event.preventDefault();
    byHand(to, true);
  });
  root.querySelector('[data-walk-prev]').addEventListener('click', () => byHand(at - 1));
  root.querySelector('[data-walk-next]').addEventListener('click', () => byHand(at + 1));
  play.addEventListener('click', () => {
    if (!playing && at === tabs.length - 1) at = -1;           // start again from the top
    setPlaying(!playing);
    if (playing && at === -1) go(0);
  });
  new IntersectionObserver(([entry]) => { visible = entry.isIntersecting; schedule(); }, { threshold: 0.5 })
    .observe(root);
  if (still) setPlaying(false);
  go(0);
}
document.querySelectorAll('[data-walk]').forEach(walkthrough);

// ---- the guide's contents: mark the part being read ------------------------------------------------

(() => {
  const links = [...document.querySelectorAll('.longread-nav a')];
  const parts = links.map((a) => document.querySelector(a.getAttribute('href')));
  let queued = false;
  const mark = () => {
    queued = false;
    let at = 0;
    parts.forEach((el, i) => { if (el && el.getBoundingClientRect().top < 160) at = i; });
    links.forEach((a, i) => a.toggleAttribute('aria-current', i === at));
  };
  addEventListener('scroll', () => { if (!queued) { queued = true; requestAnimationFrame(mark); } }, { passive: true });
  mark();
})();
