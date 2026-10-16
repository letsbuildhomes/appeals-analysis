// The graph view: the pipeline drawn from its description, with an optional run overlaid.
import { api, el, short, header, AREA_ORDER, params, setParams } from '/common.js';

const COLUMNS = [
  { layer: 'scan', title: 'Scan', note: 'one decision-model request', width: 230 },
  { layer: 'plan', title: 'Plan', note: 'gates, in code', width: 200 },
  { layer: 'steps', title: 'Steps', note: 'reasoning model, cached base', width: 230 },
  { layer: 'facts', title: 'Facts', note: 'one settled value each', width: 230 },
  { layer: 'derive', title: 'Derive', note: 'plain functions', width: 210 },
  { layer: 'answers', title: 'Answers', note: 'research answers', width: 220 },
];
const LEFT = 140, GAP = 64, TOP = 96, NODE_H = 56, NODE_GAP = 8, LANE_PAD = 16;
const KIND_LAYER = { question: 'scan', 'question set': 'scan', gate: 'plan', base: 'steps', step: 'steps',
  field: 'facts', derive: 'derive', answer: 'answers' };

let graph, byId, positions = {}, run = null, docket = null, records = null, selected = null;

async function main() {
  header('graph');
  const p = params();
  graph = await api('graph');
  if (p.get('run')) await chooseRun(p.get('run'), p.get('docket'));
  else { draw(); controls(); }
}

// ---- controls -----------------------------------------------------------------------

async function controls() {
  const box = document.getElementById('controls');
  const parts = [];
  let runs = [];
  try { runs = await api('runs'); } catch (e) { notice(e.message); }
  const runSelect = el('select', { onchange: e => chooseRun(e.target.value || null, null) },
    el('option', { value: '' }, 'Pipeline only (no run)'),
    runs.map(r => el('option', { value: r.id, selected: r.id === run?.id },
      `${r.id} · ${r.dockets} dockets · ${r.endpoints?.reasoning?.model || ''}${r.tags?.length ? ` · [${r.tags.join(', ')}]` : ''}`)));
  parts.push(el('span', {}, 'Run'), runSelect);
  if (run) {
    const dockets = await api(`runs/${encodeURIComponent(run.id)}/dockets`);
    const docketSelect = el('select', { onchange: e => chooseDocket(e.target.value || null) },
      el('option', { value: '' }, 'Choose a docket'),
      dockets.map(d => el('option', { value: d.docket, selected: d.docket === docket },
        `${d.docket} · ${d.error ? 'failed' : d.proceeds ? `${d.calls} calls` : 'stopped at scan'}`)));
    parts.push(el('span', {}, 'Docket'), docketSelect);
    if (docket) parts.push(el('a', { class: 'button', href: `/case?docket=${encodeURIComponent(docket)}&run=${encodeURIComponent(run.id)}` }, 'Open case'));
  }
  box.replaceChildren(...parts);
}

async function chooseRun(runId, docketNumber) {
  run = null; docket = null; records = null;
  if (runId) {
    const runs = await api('runs');
    run = runs.find(r => r.id === runId) || null;
    if (run && run.graph_hash !== graph.hash) {
      const stored = await api(`graphs/${run.graph_hash}`);
      graph = stored;
      notice(`This run used pipeline ${run.graph_hash}, which differs from the current code (shown as it was).`);
    } else if (!run) {
      graph = await api('graph');
    }
  } else {
    graph = await api('graph');
    notice('');
  }
  setParams({ run: run?.id, docket: null });
  if (docketNumber) return chooseDocket(docketNumber);
  draw();
  controls();
}

async function chooseDocket(number) {
  docket = number;
  records = number ? (await api(`runs/${encodeURIComponent(run.id)}/dockets/${encodeURIComponent(number)}`)).records : null;
  setParams({ run: run?.id, docket: number });
  draw();
  controls();
  if (selected) showPanel(selected);
}

function notice(text) {
  const box = document.getElementById('notice');
  box.innerHTML = '';
  if (text) box.append(el('div', { class: 'notice' }, text));
}

// ---- layout ------------------------------------------------------------------------

function layout() {
  byId = Object.fromEntries(graph.nodes.map(n => [n.id, n]));
  positions = {};
  const x = {};
  let left = LEFT;
  for (const c of COLUMNS) { x[c.layer] = left; left += c.width + GAP; }
  const width = left;
  const visible = graph.nodes.filter(n => n.kind !== 'scan' && n.kind !== 'base');
  const cells = {};
  for (const n of visible) {
    const key = `${n.area}|${KIND_LAYER[n.kind]}`;
    (cells[key] = cells[key] || []).push(n);
  }
  const lanes = [];
  let y = TOP + NODE_H + 30;                    // room for the base node above the lanes
  for (const area of AREA_ORDER) {
    const tallest = Math.max(1, ...COLUMNS.map(c => (cells[`${area}|${c.layer}`] || []).length));
    const height = tallest * (NODE_H + NODE_GAP) - NODE_GAP + LANE_PAD * 2;
    lanes.push({ area, y, height });
    for (const c of COLUMNS) {
      (cells[`${area}|${c.layer}`] || []).forEach((n, i) => {
        positions[n.id] = { x: x[c.layer], y: y + LANE_PAD + i * (NODE_H + NODE_GAP), w: c.width, h: NODE_H };
      });
    }
    y += height;
  }
  positions.base = { x: x.steps, y: TOP, w: COLUMNS[2].width, h: NODE_H };
  return { x, width, height: y + 40, lanes };
}

// ---- drawing -----------------------------------------------------------------------

function draw() {
  const canvas = document.getElementById('canvas');
  const svg = document.getElementById('edges');
  canvas.querySelectorAll('.node, .lane, .colhead, .legend').forEach(n => n.remove());
  const { x, width, height, lanes } = layout();
  canvas.style.width = `${width}px`;
  canvas.style.height = `${height}px`;
  svg.setAttribute('width', width);
  svg.setAttribute('height', height);

  for (const lane of lanes) {
    canvas.append(el('div', { class: 'lane', style: `top:${lane.y}px;height:${lane.height}px` },
      el('div', { class: 'lane-name' }, graph.areas[lane.area])));
  }
  for (const c of COLUMNS) {
    canvas.append(el('div', { class: 'colhead', style: `left:${x[c.layer]}px` }, c.title, el('span', {}, c.note)));
  }
  canvas.append(el('div', { class: 'legend', style: `left:${LEFT}px;top:44px` },
    el('span', {}, el('i', { style: 'background:var(--line-strong)' }), 'data'),
    el('span', {}, el('i', { style: 'background:var(--plan)' }), 'condition'),
    el('span', {}, el('i', { style: 'background:var(--steps)' }), 'chained context'),
    el('span', {}, `pipeline ${graph.hash}`),
    run ? el('span', {}, `run ${run.id}${docket ? ` · docket ${docket}` : ''}`) : null));

  for (const n of graph.nodes) {
    const pos = positions[n.id];
    if (!pos) continue;
    canvas.append(nodeBox(n, pos));
  }
  drawEdges(svg);
  if (selected) highlight(selected);
}

function nodeTitle(n) {
  if (n.kind === 'question' || n.kind === 'question set') return n.ask;
  if (n.kind === 'base') return 'Shared base prompt, cached per docket';
  return n.title || n.label || n.id;
}

function nodeBox(n, pos) {
  const state = overlay(n);
  const box = el('div', {
    class: `node k-${n.kind.replace(' ', '-')}${state.off ? ' off' : ''}${selected === n.id ? ' sel' : ''}`,
    style: `left:${pos.x}px;top:${pos.y}px;width:${pos.w}px;height:${pos.h}px`,
    'data-id': n.id, onclick: () => select(n.id),
  },
    el('div', { class: 'row1' }, el('span', { class: 'id' }, n.code || n.id),
      n.kind === 'question set' ? el('span', {}, n.question_type) : null,
      state.badge ? el('span', { class: `badge tag ${state.badgeClass || ''}` }, state.badge) : null),
    el('div', { class: 'label', title: nodeTitle(n) }, nodeTitle(n)),
    el('div', { class: 'value' }, state.value || ''));
  return box;
}

function drawEdges(svg) {
  svg.innerHTML = '';
  for (const e of graph.edges) {
    if (e.kind === 'asked' || e.kind === 'base') continue;
    const a = positions[e.from], b = positions[e.to];
    if (!a || !b) continue;
    let d;
    if (Math.abs(a.x - b.x) < 5) {               // same column: loop on the right
      const x1 = a.x + a.w, y1 = a.y + a.h / 2, y2 = b.y + b.h / 2, bulge = x1 + 30;
      d = `M${x1},${y1} C${bulge},${y1} ${bulge},${y2} ${x1},${y2}`;
    } else {
      const x1 = a.x + a.w, y1 = a.y + a.h / 2, x2 = b.x, y2 = b.y + b.h / 2, dx = Math.max(30, (x2 - x1) / 2);
      d = `M${x1},${y1} C${x1 + dx},${y1} ${x2 - dx},${y2} ${x2},${y2}`;
    }
    const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    path.setAttribute('d', d);
    path.setAttribute('class', `edge ${e.kind}`);
    path.dataset.from = e.from;
    path.dataset.to = e.to;
    svg.append(path);
  }
}

// ---- selection ----------------------------------------------------------------------

function lineage(id) {
  const up = new Set([id]), down = new Set([id]);
  const edges = graph.edges.filter(e => e.kind !== 'asked');
  let changed = true;
  while (changed) {
    changed = false;
    for (const e of edges) {
      if (up.has(e.to) && !up.has(e.from)) { up.add(e.from); changed = true; }
      if (down.has(e.from) && !down.has(e.to)) { down.add(e.to); changed = true; }
    }
  }
  return new Set([...up, ...down]);
}

function highlight(id) {
  const keep = lineage(id);
  document.querySelectorAll('.node').forEach(n => {
    n.classList.toggle('dim', !keep.has(n.dataset.id));
    n.classList.toggle('sel', n.dataset.id === id);
  });
  document.querySelectorAll('path.edge').forEach(p => {
    const on = keep.has(p.dataset.from) && keep.has(p.dataset.to);
    p.classList.toggle('lit', on);
    p.classList.toggle('faded', !on);
  });
}

function select(id) {
  if (selected === id) {
    selected = null;
    document.querySelectorAll('.node').forEach(n => n.classList.remove('dim', 'sel'));
    document.querySelectorAll('path.edge').forEach(p => p.classList.remove('lit', 'faded'));
    document.getElementById('panel').innerHTML = '<p class="empty">Select a node to see what it does.</p>';
    return;
  }
  selected = id;
  highlight(id);
  showPanel(id);
}

// ---- run overlay --------------------------------------------------------------------

function scanDist(id) {
  return records?.scan?.value?.[id] || null;
}

function top(dist) {
  if (!dist) return null;
  return Object.entries(dist).sort((a, b) => b[1] - a[1])[0];
}

function overlay(n) {
  if (!records) return {};
  if (n.kind === 'question') {
    const best = top(scanDist(n.id));
    return best ? { value: `${best[0]} · ${best[1].toFixed(2)}` } : {};
  }
  if (n.kind === 'question set') {
    const keys = Object.keys(n.options);
    const flagged = keys.filter(k => (scanDist(`${n.id}.${k}`)?.yes || 0) >= (graph.thresholds?.check ?? 0.3));
    return { value: flagged.length ? flagged.join(', ') : 'none flagged' };
  }
  if (n.kind === 'gate') {
    const g = records.plan?.value?.gates?.[n.id];
    return g ? { badge: g.passed ? 'passes' : 'skips', badgeClass: g.passed ? 'pass' : 'skip', off: !g.passed } : {};
  }
  if (n.kind === 'step') {
    const planned = records.plan?.value?.steps?.find(s => s.step === n.id);
    const r = records[n.id]?.value;
    if (r?.skipped) return { badge: r.skipped.startsWith('halted') ? 'halted' : 'skipped', badgeClass: 'skip', off: true, value: r.skipped };
    if (!planned?.runs) return { badge: 'not run', badgeClass: 'skip', off: true, value: planned?.reason || '' };
    if (!r) return { badge: 'planned', value: planned.depends ? `if ${planned.depends}` : '' };
    if (r.error) return { badge: 'failed', badgeClass: 'fail', value: r.error };
    return { badge: r.attempts > 1 ? `ran · ${r.attempts} tries` : 'ran', badgeClass: 'pass',
      value: `quotes ${r.quotes_verified}/${r.quotes_checked} verified${r.variant ? ' · ' + r.variant : ''}` };
  }
  if (n.kind === 'base') {
    return records.base ? { badge: 'built', badgeClass: 'pass' } : { off: true, badge: 'not built', badgeClass: 'skip' };
  }
  if (n.kind === 'field') {
    const f = records.facts?.value?.[n.id];
    if (!f) return {};
    const source = typeof f.source === 'string' ? f.source : 'mixed';
    return { value: short(f.answer, 48), badge: source, badgeClass: source === 'step' ? 'pass' : source === 'none' ? 'skip' : '' };
  }
  if (n.kind === 'derive') {
    const v = records.derive?.value?.[n.id];
    return v === undefined ? {} : { value: short(v, 48) };
  }
  return {};
}

// ---- panel --------------------------------------------------------------------------

function section(title, ...content) {
  return [el('h3', {}, title), ...content];
}

function links(ids) {
  return el('div', { class: 'links' }, ids.map(id => el('span', { class: 'link', onclick: () => select(id) }, byId[id]?.code || id)));
}

function showPanel(id) {
  const n = byId[id];
  const panel = document.getElementById('panel');
  panel.innerHTML = '';
  const from = graph.edges.filter(e => e.to === id && e.kind !== 'asked').map(e => e.from);
  const to = graph.edges.filter(e => e.from === id && e.kind !== 'asked').map(e => e.to);
  panel.append(
    el('div', { class: 'kindline' }, el('span', { class: `tag ${n.layer}` }, n.kind), el('span', { class: 'tag' }, graph.areas[n.area] || n.area)),
    el('h2', {}, `${n.code || n.id}${n.title || n.label ? ' · ' + (n.title || n.label) : ''}`),
    ...renderers[n.kind](n),
    ...(from.length ? section('Reads', links(from)) : []),
    ...(to.length ? section('Feeds', links(to)) : []),
  );
}

function optionList(options, dist) {
  return el('div', { class: 'options' }, Object.entries(options).map(([name, meaning]) => {
    const p = dist ? (dist[name] ?? 0) : null;
    return el('div', { class: 'option' },
      el('span', { class: 'name' }, name),
      p === null ? el('span') : el('span', { class: 'p' }, p.toFixed(2)),
      p === null ? null : el('div', { class: 'bar', style: 'grid-column:1/-1' }, el('span', { style: `width:${(p * 100).toFixed(1)}%` })),
      meaning ? el('span', { class: 'meaning' }, meaning) : null);
  }));
}

function quotes(list) {
  return (list || []).map(q => el('div', { class: `quote ${q.verified ? 'ok' : 'bad'}` },
    el('div', {}, `“${q.quote}”`),
    el('div', { class: 'cite' }, `document ${q.doc}, page ${q.page} · ${q.verified ? 'verified on the page' : 'not found on the page'}`)));
}

function json(value) {
  return el('pre', { class: 'block' }, JSON.stringify(value, null, 1));
}

const renderers = {
  question(n) {
    const dist = scanDist(n.id);
    const out = [el('p', { class: 'ask' }, n.ask), el('p', { class: 'why' }, n.why),
      el('dl', { class: 'kv' }, el('dt', {}, 'Asked as'), el('dd', {}, `${n.question_type}, in the scan`))];
    if (n.options_source) {
      out.push(...section('Options', el('p', {}, 'Built per docket by this function:'), el('pre', { class: 'block' }, n.options_source)));
      if (dist) out.push(...section('This docket', optionList(Object.fromEntries(Object.keys(dist).map(k => [k, ''])), dist)));
    } else out.push(...section(dist ? 'Options · this docket' : 'Options', optionList(n.options, dist)));
    return out;
  },
  'question set'(n) {
    const out = [el('p', { class: 'ask' }, n.ask), el('p', { class: 'why' }, n.why),
      el('p', { class: 'why' }, `Asked as ${Object.keys(n.options).length} separate yes/no questions, one per item.`)];
    const dist = Object.fromEntries(Object.keys(n.options).map(k => [k, scanDist(`${n.id}.${k}`)?.yes ?? null]));
    out.push(...section(records ? 'Items · P(yes) this docket' : 'Items',
      optionList(n.options, records ? dist : null)));
    return out;
  },
  gate(n) {
    const g = records?.plan?.value?.gates?.[n.id];
    const out = [el('p', { class: 'why' }, n.why), ...section('Condition', el('pre', { class: 'block' }, n.condition))];
    if (g) {
      out.push(...section(`This docket · ${g.passed ? 'passes' : 'does not pass'}`,
        el('div', { class: 'terms' }, g.terms.map(t => el('div', {}, el('code', {}, t.term), el('span', {}, String(t.value)))))));
    }
    out.push(...section('Thresholds', el('div', { class: 'terms' },
      Object.entries(graph.thresholds).filter(([k]) => n.condition.includes(`T.${k}`)).map(([k, v]) => el('div', {}, el('code', {}, `T.${k}`), el('span', {}, v))))));
    return out;
  },
  base(n) {
    const out = [el('p', {}, 'Built once per docket and cached by the reasoning model. Every step adds one question to it.'),
      ...section('Framing', el('pre', { class: 'block' }, n.framing)),
      ...section('Then', el('p', { class: 'why' }, 'The docket text, then the scan\'s answers as claims to confirm or refute.'))];
    if (records?.base) out.push(...section('This docket · scan claims', el('pre', { class: 'block' }, records.base.value.claims)));
    return out;
  },
  step(n) {
    const out = [el('dl', { class: 'kv' },
      el('dt', {}, 'Runs when'), el('dd', {}, n.when ? `gate ${n.when}: ${n.when_text}` : n.when_text),
      n.only_if ? [el('dt', {}, 'Only if'), el('dd', {}, el('code', {}, n.only_if))] : null,
      n.choose ? [el('dt', {}, 'Variant'), el('dd', {}, el('code', {}, n.choose))] : null,
      n.chain_after.length ? [el('dt', {}, 'Chained after'), el('dd', {}, n.chain_after.join(', '))] : null,
      n.halt_unless ? [el('dt', {}, 'Halts unless'), el('dd', {}, el('code', {}, n.halt_unless))] : null,
      n.confirms.length ? [el('dt', {}, 'Confirms'), el('dd', {}, n.confirms.join(', '))] : null)];
    const r = records?.[n.id]?.value;
    if (r && !r.skipped && r.prompt) {
      out.push(...section(`Prompt sent${r.variant ? ' · ' + r.variant : ''}`, el('pre', { class: 'block' }, r.prompt)));
      const exchange = records[n.id].exchange;
      if (exchange) {
        out.push(...section(`Replies · ${exchange.attempts.length} attempt${exchange.attempts.length > 1 ? 's' : ''}`,
          exchange.attempts.map((a, i) => el('div', { class: 'attempt' },
            el('div', { class: 'why' }, `Attempt ${i + 1}`),
            el('pre', { class: 'block' }, a.reply),
            a.truncated ? el('div', { class: 'errors' }, `${a.errors.join('; ')}: the same request was sent again`)
              : a.errors.length ? el('div', { class: 'errors' }, 'Sent back: ', a.errors.join('; ')) : el('div', { class: 'why' }, 'Valid')))));
      }
      if (r.answer) out.push(...section('Answer, with quote checks', json(r.answer)));
      out.push(el('p', { class: 'why' }, `Cost $${(records[n.id].cost_usd || 0).toFixed(4)}${records[n.id].reused ? ' (reused from an earlier run)' : ''}`));
    } else if (r?.skipped) {
      out.push(el('p', { class: 'why' }, r.skipped));
    }
    if (n.variants) out.push(...section('Prompt variants', Object.entries(n.variants).map(([k, v]) => [el('p', {}, el('strong', {}, k)), el('pre', { class: 'block' }, v)])));
    else out.push(...section('Prompt', el('pre', { class: 'block' }, n.prompt)));
    out.push(...section('Returns (JSON schema; replies that do not match are sent back)', json(n.schema)));
    return out;
  },
  field(n) {
    const f = records?.facts?.value?.[n.id];
    const out = [el('dl', { class: 'kv' },
      el('dt', {}, 'Rule'), el('dd', {}, n.rule),
      n.from_step ? [el('dt', {}, 'From step'), el('dd', {}, el('code', {}, n.from_step))] : null,
      n.from_scan ? [el('dt', {}, 'From scan'), el('dd', {}, el('code', {}, n.from_scan))] : null,
      n.not_stated_if ? [el('dt', {}, 'Not stated if'), el('dd', {}, el('code', {}, n.not_stated_if))] : null,
      el('dt', {}, 'Scored'), el('dd', {}, n.scored ? 'yes' : 'no (free text)'))];
    if (f) {
      out.push(...section('This docket',
        el('p', { class: 'ask' }, typeof f.answer === 'object' ? '' : String(f.answer)),
        typeof f.answer === 'object' ? json(f.answer) : null,
        el('p', { class: 'why' }, `Source: ${typeof f.source === 'string' ? f.source : JSON.stringify(f.source)}${f.probability != null ? ` · scan probability ${f.probability}` : ''}${f.conflict ? ` · conflicts with the scan (${f.scan_answer})` : ''}${f.note ? ' · ' + f.note : ''}`),
        ...quotes(f.quotes)));
    }
    if (n.source) out.push(...section('Function', el('pre', { class: 'block' }, n.source)));
    out.push(...section('Value type', json(n.value_type)));
    return out;
  },
  derive(n) {
    const v = records?.derive?.value?.[n.id];
    return [
      ...(v !== undefined ? section('This docket', json(v)) : []),
      ...section('Function', el('pre', { class: 'block' }, n.source)),
      ...section('Value type', json(n.value_type)),
    ];
  },
  answer(n) {
    const facts = records?.facts?.value, derived = records?.derive?.value;
    return [el('p', { class: 'ask' }, n.question),
      ...section('Made of', el('div', { class: 'terms' }, n.parts.map(id => el('div', {},
        el('span', { class: 'link', onclick: () => select(id) }, byId[id]?.code || id),
        el('span', {}, records ? short(facts?.[id]?.answer ?? derived?.[id], 50) : byId[id]?.label || ''))))),
    ];
  },
};

main().catch(e => notice(e.message));
