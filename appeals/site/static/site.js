// The placeholder dashboard: the current release (or ?release=<id>), its research questions and conventions,
// how to connect over MCP, and every release, old ones marked as such.
const BASE = document.currentScript.dataset.base;
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const get = (path) => fetch(`${BASE}/api/${path}`).then((r) => (r.ok ? r.json() : Promise.reject(r.status)));

async function main() {
  const mcp = `${location.origin}${BASE}/mcp`;
  $('mcp-url').textContent = mcp;
  $('mcp-add').textContent = `claude mcp add --transport http appeals ${mcp}`;

  const releases = await get('releases');
  const wanted = new URLSearchParams(location.search).get('release');
  const chosen = releases.find((r) => r.id === wanted) || releases.find((r) => r.current);
  if (!chosen) {
    $('release').innerHTML = '<p class="muted">No release is published yet.</p>';
    return;
  }
  const o = await get(`releases/${chosen.id}`);
  $('what').textContent = o.what_this_is;
  if (!o.release.current) {
    const banner = $('banner');
    banner.hidden = false;
    banner.innerHTML = `Old data: you are viewing release <b>${esc(o.release.id)}</b> from ${esc(o.release.created_at.slice(0, 10))}, `
      + `which is not the current release. <a href="${BASE}/">See the current data</a>.`;
  }
  const p = o.population;
  $('release').innerHTML = `
    <h2>Release ${esc(o.release.id)} ${o.release.current ? '<span class="tag">current</span>' : '<span class="tag old">old data</span>'}</h2>
    <p class="muted">Built ${esc(o.release.created_at.slice(0, 10))} from run ${esc(o.release.run)}
      (pipeline ${esc(o.release.graph)}).</p>
    <div class="cards">
      <div class="card"><b>${p.dockets}</b>dockets studied</div>
      <div class="card"><b>${p.in_scope}</b>in scope</div>
      <div class="card"><b>${p.out_of_scope}</b>out of scope</div>
      <div class="card"><b>${p.failed + p.not_run}</b>without answers</div>
    </div>`;
  $('questions').innerHTML = '<h2>Research questions</h2>' + o.research_questions.map((q) => `
    <div class="question"><h3>${esc(q.title)}</h3><p>${esc(q.question)}</p>
      <p class="muted">${q.answered_by.map((a) => esc(`${a.code} ${a.label}`)).join(' · ')}</p></div>`).join('');
  $('conventions').innerHTML = '<h2>Conventions</h2><ul>' + o.conventions.map((c) => `<li>${esc(c)}</li>`).join('') + '</ul>';
  $('releases').innerHTML = '<h2>All releases</h2><table><tr><th>Release</th><th>Built</th><th>Run</th><th>In scope</th></tr>'
    + releases.map((r) => `<tr><td><a href="?release=${esc(r.id)}">${esc(r.id)}</a> `
      + `${r.current ? '<span class="tag">current</span>' : '<span class="tag old">old</span>'}`
      + `${(r.tags || []).map((t) => ` <span class="tag">${esc(t)}</span>`).join('')}</td>`
      + `<td>${esc(r.created_at.slice(0, 10))}</td><td>${esc(r.run)}</td><td>${r.population.in_scope}</td></tr>`).join('')
    + '</table>';
}

main().catch((error) => { $('release').innerHTML = `<p class="muted">Could not load the data (${esc(error)}).</p>`; });
