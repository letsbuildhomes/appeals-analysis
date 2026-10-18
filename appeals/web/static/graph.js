// The graph view: the pipeline drawn from its description, one row per topic, with an optional run overlaid.
// ELK (static/vendor/elk.bundled.js) lays out each row and routes its lines; this file aligns the rows' columns,
// routes the few lines between rows, and draws everything.
import { api, el, short, header, params, setParams } from '/common.js';
import { typeView, example, jsonTree, parseReply } from '/inspect.js';

const COLUMNS = [
  { title: 'Scan', note: 'decision model, one request', width: 236 },
  { title: 'Gates', note: 'in code', width: 196 },
  { title: 'Steps', note: 'reasoning model', width: 212 },
  { title: 'Facts', note: 'one settled value each', width: 236 },
  { title: 'Derived', note: 'plain functions', width: 236 },
];
const COLUMN_OF = { question: 0, 'question set': 0, 'choice set': 0, gate: 1, step: 2, chain: 2, set: 2, field: 3, derive: 4 };
const LINES = ['data', 'condition', 'chain'];
const KINDS = ['scan', ...LINES];             // drawn: 'scan' is a scan answer feeding a fact directly
const LEFT = 24, HEAD = 40, ROW_HEAD = 34, ROW_GAP = 10;
const CHIP_W = 156, CHIP_GAP = 6, BOX_PAD = 10, BOX_HEAD = 30;
const FAR = 0.55;                               // below this zoom, boxes show only their name, larger

let graph, current, model, drawn = null, run = null, docket = null, records = null, selected = null;
let trace = localStorage.getItem('graph-trace') === '1';

async function main() {
  header('graph');
  const p = params();
  graph = current = await api('graph');
  if (p.get('run')) await chooseRun(p.get('run'), p.get('docket'), p.get('node'));
  else { await draw(); controls(); if (p.get('node')) select(p.get('node'), true); }
}

// ---- controls -----------------------------------------------------------------------

async function controls() {
  const box = document.getElementById('controls');
  let runs = [];
  try { runs = await api('runs'); } catch (e) { notice(e.message, true); }
  const parts = [el('span', {}, 'Run'), el('select', { onchange: e => chooseRun(e.target.value || null, null) },
    el('option', { value: '' }, 'Pipeline only'),
    runs.map(r => el('option', { value: r.id, selected: r.id === run?.id },
      `${r.id} · ${r.dockets} docket${r.dockets === 1 ? '' : 's'} · ${r.endpoints?.reasoning?.model || ''}${r.tags?.length ? ` · ${r.tags.join(', ')}` : ''}`)))];
  if (run) {
    const dockets = await api(`runs/${encodeURIComponent(run.id)}/dockets`);
    parts.push(el('span', {}, 'Docket'), el('select', { onchange: e => chooseDocket(e.target.value || null) },
      el('option', { value: '' }, 'Choose a docket'),
      dockets.map(d => el('option', { value: d.docket, selected: d.docket === docket },
        `${d.docket} · ${d.error ? 'failed' : d.proceeds ? `${d.calls} calls` : 'stopped at scan'}`))));
    if (docket) parts.push(el('a', { class: 'button', href: `/case?docket=${encodeURIComponent(docket)}&run=${encodeURIComponent(run.id)}` }, 'Open case'));
  }
  box.replaceChildren(...parts);
}

async function chooseRun(runId, docketNumber, node) {
  run = null; docket = null; records = null;
  if (runId) {
    run = (await api('runs')).find(r => r.id === runId) || null;
    if (run && run.graph_hash !== current.hash) {
      graph = await api(`graphs/${run.graph_hash}`);
      notice(`Drawn as pipeline ${run.graph_hash}, which this run used: it differs from the current code.`);
    } else {
      graph = current;
      notice('');
    }
  } else {
    graph = current;
    notice('');
  }
  setParams({ run: run?.id, docket: null });
  if (docketNumber) return chooseDocket(docketNumber, node);
  await draw();
  controls();
  if (node) select(node, true);
}

async function chooseDocket(number, node) {
  docket = number;
  records = number ? (await api(`runs/${encodeURIComponent(run.id)}/dockets/${encodeURIComponent(number)}`)).records : null;
  setParams({ run: run?.id, docket: number });
  await draw();
  controls();
  const keep = node || selected;
  selected = null;
  if (keep && model.byId[keep]) select(keep, Boolean(node));
}

// A short note in the dock (such as which pipeline a run used); errors go above the page.
let note = '';
function notice(text, error = false) {
  if (error) document.getElementById('notice').replaceChildren(el('div', { class: 'notice' }, text));
  note = error ? note : text;
  if (drawn) dock();
}

// ---- the model: rows, groups and lines, from the pipeline description -------------------

function parentOf(n) {
  if (n.after !== undefined) return n.after;
  return n.chain_after?.length ? n.chain_after[n.chain_after.length - 1] : null;   // pipelines stored before `after`
}

// A step's own name within its set: "Grounds: traffic and services" → "traffic and services".
function itemName(step) {
  const title = step.title || step.id;
  return title.includes(': ') ? title.slice(title.indexOf(': ') + 2) : title;
}

function buildModel() {
  const byId = Object.fromEntries(graph.nodes.filter(n => n.kind !== 'answer').map(n => [n.id, n]));
  const order = graph.step_order || graph.nodes.filter(n => n.kind === 'step').map(n => n.id);
  const children = {};
  for (const id of order) {
    const parent = parentOf(byId[id]);
    if (parent) (children[parent] = children[parent] || []).push(id);
  }

  // Groups: a chain of steps in one conversation, or a set of one-per-item steps (L3_…, L8_…), drawn as one box.
  const groups = {}, groupOf = {};
  for (const id of order) {
    if (parentOf(byId[id])) continue;
    const set = id.match(/^(L\d+)_/);
    if (set && !children[id]) {
      const gid = `set:${set[1]}`;
      const g = groups[gid] = groups[gid] || { id: gid, kind: 'set', label: set[1], steps: [] };
      g.steps.push(id);
      groupOf[id] = gid;
    } else if (children[id]) {
      const gid = `chain:${id}`;
      const g = groups[gid] = { id: gid, kind: 'chain', label: /^L\d+[a-z]$/.test(id) ? id.slice(0, -1) : id, steps: [] };
      const walk = s => { g.steps.push(s); groupOf[s] = gid; (children[s] || []).forEach(walk); };
      walk(id);
    }
  }
  for (const g of Object.values(groups)) {
    if (g.kind !== 'set') continue;
    const titles = g.steps.map(s => byId[s].title || '');
    const common = titles.every(t => t.includes(': ') && t.split(': ')[0] === titles[0].split(': ')[0]) ? titles[0].split(': ')[0] : '';
    g.title = common;
  }
  // What a line is drawn between: a step in a set is drawn as its set.
  const shown = id => (groupOf[id]?.startsWith('set:') ? groupOf[id] : id);

  // Rows: the pipeline's topics. A pipeline stored before topics borrows the current ones for the steps they
  // share; any other step gets a row of its own step number.
  let topics = graph.topics;
  if (!topics?.length) {
    topics = (current.topics || []).map(t => ({ title: t.title, steps: t.steps.filter(s => byId[s]) }));
    for (const id of order.filter(s => !topics.some(t => t.steps.includes(s)))) {
      const key = id.match(/^L\d+/)?.[0] || id;
      let t = topics.find(x => x.key === key);
      if (!t) topics.push(t = { key, title: key, steps: [] });
      t.steps.push(id);
    }
    topics = topics.filter(t => t.steps.length);
  }
  const row = {};
  topics.forEach((t, i) => t.steps.forEach(s => { row[s] = i; }));
  for (const g of Object.values(groups)) g.steps.forEach(s => { row[s] = row[g.steps[0]]; });

  const lines = graph.edges.filter(e => LINES.includes(e.kind) && byId[e.from] && byId[e.to]);
  const ins = {}, outs = {};
  for (const e of lines) { (ins[e.to] = ins[e.to] || []).push(e.from); (outs[e.from] = outs[e.from] || []).push(e.to); }
  const placed = (ids, pick) => {
    const rows = (ids || []).map(x => row[x]).filter(r => r !== undefined);
    return rows.length ? pick(...rows) : undefined;
  };
  const kinds = k => graph.nodes.filter(n => k.includes(n.kind)).map(n => n.id);
  // Each node goes in the row it belongs with: a gate with the first steps it opens, a fact with the steps that
  // settle it, a scan question with the first row that reads it, a derived value with the last row it reads.
  for (const id of kinds(['gate'])) row[id] = placed(outs[id], Math.min);
  for (const id of kinds(['field'])) row[id] = placed((ins[id] || []).filter(x => byId[x].kind === 'step'), Math.max);
  for (const id of kinds(['question', 'question set', 'choice set'])) row[id] = placed(outs[id], Math.min);
  for (const id of kinds(['field'])) if (row[id] === undefined) row[id] = placed(ins[id], Math.max);
  for (const id of kinds(['gate'])) if (row[id] === undefined) row[id] = placed(ins[id], Math.min);
  for (let pass = 0; pass < 3; pass++) for (const id of kinds(['derive'])) row[id] = placed(ins[id], Math.max) ?? row[id];
  const firstOfArea = area => {
    const step = order.find(s => byId[s].area === area);
    return step === undefined ? 0 : row[step];
  };
  for (const id of Object.keys(byId)) {
    if (row[id] === undefined && COLUMN_OF[byId[id].kind] !== undefined) row[id] = firstOfArea(byId[id].area);
  }

  // The things drawn: nodes, groups; and the lines between them, merged where several join the same two boxes.
  const items = {};
  for (const n of Object.values(byId)) {
    if (COLUMN_OF[n.kind] === undefined || groupOf[n.id]?.startsWith('set:')) continue;
    items[n.id] = { id: n.id, kind: n.kind, column: COLUMN_OF[n.kind], row: row[n.id], group: groupOf[n.id] || null };
  }
  for (const g of Object.values(groups)) items[g.id] = { id: g.id, kind: g.kind, column: 2, row: row[g.steps[0]], group: null };
  const wires = {};
  for (const e of lines) {
    const a = shown(e.from), b = shown(e.to);
    if (a === b || !items[a] || !items[b]) continue;
    const key = `${a}>${b}`;
    const w = wires[key] = wires[key] || { id: `w${Object.keys(wires).length}`, from: a, to: b, kind: e.kind, edges: [] };
    if (LINES.indexOf(e.kind) > LINES.indexOf(w.kind)) w.kind = e.kind;      // chain over data over condition
    w.edges.push(e);
  }
  for (const w of Object.values(wires)) {
    if (COLUMN_OF[byId[w.from]?.kind] === 0 && byId[w.to]?.kind === 'field') w.kind = 'scan';
  }
  return { byId, order, children, groups, groupOf, shown, topics, row, items, wires: Object.values(wires), lines, ins, outs };
}

// ---- sizes --------------------------------------------------------------------------

function cardHeight() { return records ? 96 : 66; }
function chipHeight() { return records ? 46 : 30; }

function setSize(g) {
  const cols = Math.min(2, g.steps.length), rows = Math.ceil(g.steps.length / cols);
  return { width: BOX_PAD * 2 + cols * CHIP_W + (cols - 1) * CHIP_GAP,
    height: BOX_HEAD + BOX_PAD + rows * chipHeight() + (rows - 1) * CHIP_GAP };
}

// ---- layout -------------------------------------------------------------------------

const ELK_OPTIONS = {
  'elk.algorithm': 'layered',
  'elk.direction': 'RIGHT',
  'elk.edgeRouting': 'ORTHOGONAL',
  'elk.partitioning.activate': 'true',
  'elk.separateConnectedComponents': 'false',
  'elk.json.shapeCoords': 'ROOT',
  'elk.json.edgeCoords': 'ROOT',
  'elk.layered.mergeEdges': 'true',
  'elk.layered.considerModelOrder.strategy': 'NODES_AND_EDGES',
  'elk.layered.nodePlacement.strategy': 'NETWORK_SIMPLEX',
  'elk.layered.spacing.nodeNodeBetweenLayers': '44',
  'elk.layered.spacing.edgeNodeBetweenLayers': '14',
  'elk.layered.spacing.edgeEdgeBetweenLayers': '7',
  'elk.spacing.nodeNode': '18',
  'elk.spacing.edgeEdge': '7',
  'elk.spacing.edgeNode': '12',
  'elk.padding': '[top=8,left=0,bottom=16,right=0]',
};
const INDENT = 22, THREAD_GAP = 12;

// A conversation reads top to bottom like a transcript: each step below the one it follows, indented one
// level, so a branch (two steps following the same one) shows as siblings.
function threadShape(g) {
  const H = cardHeight(), W = COLUMNS[2].width;
  const list = [];
  const walk = (s, depth) => { list.push({ id: s, depth }); (model.children[s] || []).forEach(c => walk(c, depth + 1)); };
  walk(g.steps[0], 0);
  list.forEach((s, i) => { s.x = BOX_PAD + s.depth * INDENT; s.y = BOX_HEAD + i * (H + THREAD_GAP); });
  return { list, width: BOX_PAD * 2 + Math.max(...list.map(s => s.depth)) * INDENT + W,
    height: BOX_HEAD + list.length * H + (list.length - 1) * THREAD_GAP + BOX_PAD };
}

async function layout() {
  model = buildModel();
  const { items, groups, wires, topics, groupOf } = model;
  const elk = new window.ELK();
  const H = cardHeight();
  const thread = id => (groupOf[id]?.startsWith('chain:') ? groupOf[id] : null);
  // A step in a conversation joins its lines at its own ports; a set joins them level with its first row of items.
  const end = (id, port) => (thread(id) || groups[id]?.kind === 'set' ? `${id}>${port}` : id);
  // A line from a step to a step in another box of the same row: drawn afterwards, around the right of both
  // boxes, so that ELK can stack the boxes rather than set the second beside the first.
  const outer = id => thread(id) || id;
  const side = w => items[w.from].column === 2 && items[w.to].column === 2 && items[w.from].row === items[w.to].row
    && outer(w.from) !== outer(w.to);
  const shapes = {};
  const rows = await Promise.all(topics.map(async (topic, r) => {
    const children = [];
    for (const it of Object.values(items)) {
      if (it.row !== r || it.group) continue;
      const partition = { 'elk.partitioning.partition': String(it.column) };
      if (it.kind === 'set') {
        const size = setSize(groups[it.id]), y = BOX_HEAD + chipHeight() / 2;
        children.push({ id: it.id, ...size, layoutOptions: { ...partition, 'elk.portConstraints': 'FIXED_POS' },
          ports: [{ id: `${it.id}>in`, x: 0, y, width: 0, height: 0, layoutOptions: { 'elk.port.side': 'WEST' } },
            { id: `${it.id}>out`, x: size.width, y, width: 0, height: 0, layoutOptions: { 'elk.port.side': 'EAST' } }] });
      }
      else if (it.kind === 'chain') {
        const shape = shapes[it.id] = threadShape(groups[it.id]);
        children.push({ id: it.id, width: shape.width, height: shape.height,
          layoutOptions: { ...partition, 'elk.portConstraints': 'FIXED_POS' },
          ports: shape.list.flatMap(s => [
            { id: `${s.id}>in`, x: 0, y: s.y + H / 2, width: 0, height: 0, layoutOptions: { 'elk.port.side': 'WEST' } },
            { id: `${s.id}>out`, x: shape.width, y: s.y + H / 2, width: 0, height: 0, layoutOptions: { 'elk.port.side': 'EAST' } }]) });
      } else children.push({ id: it.id, width: COLUMNS[it.column].width, height: H, layoutOptions: partition });
    }
    const edges = wires.filter(w => items[w.from].row === r && items[w.to].row === r
      && !(thread(w.from) && thread(w.from) === thread(w.to)) && !side(w))
      .map(w => ({ id: w.id, sources: [end(w.from, 'out')], targets: [end(w.to, 'in')],
        // a scan answer feeding a fact is the least important line to keep straight
        layoutOptions: { 'elk.layered.priority.straightness': w.kind === 'scan' ? '0' : '10' } }));
    const out = await elk.layout({ id: `row${r}`, layoutOptions: ELK_OPTIONS, children, edges });
    return { topic, out };
  }));

  // Align the columns across rows: in each row, open up space just before a column so it starts where the
  // furthest-right row starts it. Lines crossing the gap stretch; nothing else moves relative to its neighbours.
  const boxes = {};
  for (const { out } of rows) for (const c of out.children || []) boxes[c.id] = { x: c.x, y: c.y, w: c.width, h: c.height };
  const starts = rows.map(({ out }) => {
    const s = [];
    for (const c of out.children || []) s[items[c.id].column] = Math.min(s[items[c.id].column] ?? Infinity, c.x);
    return s;
  });
  const cuts = rows.map(() => []), moved = rows.map(() => 0), colX = [];
  for (let c = 0; c < COLUMNS.length; c++) {
    const least = c ? colX[c - 1] + COLUMNS[c - 1].width + 44 : 0;
    const here = rows.map((_, r) => r).filter(r => starts[r][c] !== undefined);
    colX[c] = Math.max(least, ...here.map(r => starts[r][c] + moved[r]));
    for (const r of here) {
      const by = colX[c] - (starts[r][c] + moved[r]);
      if (by > 0) { cuts[r].push({ at: starts[r][c] - 1, by }); moved[r] += by; }
    }
  }
  const shiftX = (r, x) => x + cuts[r].filter(c => x >= c.at).reduce((s, c) => s + c.by, 0);

  // Stack the rows; then place each conversation's steps inside its box, and draw its connectors.
  const bands = [], paths = [];
  let y = HEAD;
  rows.forEach(({ topic, out }, r) => {
    const top = y + ROW_HEAD;
    for (const c of out.children || []) { const b = boxes[c.id]; b.x = LEFT + shiftX(r, b.x); b.y = top + b.y; }
    for (const c of out.children || []) {
      if (!shapes[c.id]) continue;
      const box = boxes[c.id];
      for (const s of shapes[c.id].list) boxes[s.id] = { x: box.x + s.x, y: box.y + s.y, w: COLUMNS[2].width, h: H };
    }
    for (const e of out.edges || []) {
      const wire = model.wires.find(w => w.id === e.id);
      for (const s of e.sections || []) {
        const pts = [s.startPoint, ...(s.bendPoints || []), s.endPoint].map(p => ({ x: LEFT + shiftX(r, p.x), y: top + p.y }));
        if (thread(wire.from)) pts.unshift({ x: boxes[wire.from].x + boxes[wire.from].w, y: pts[0].y });
        if (thread(wire.to)) pts.push({ x: boxes[wire.to].x, y: pts[pts.length - 1].y });
        paths.push({ wire, pts });
      }
    }
    bands.push({ topic, row: r, y, h: ROW_HEAD + out.height });
    y += ROW_HEAD + out.height + ROW_GAP;
  });
  let lane = 0;
  for (const w of wires.filter(side)) {
    const a = boxes[w.from], b = boxes[w.to], oa = boxes[outer(w.from)], ob = boxes[outer(w.to)];
    const x = Math.max(oa.x + oa.w, ob.x + ob.w) + 10 + 6 * (lane++ % 3), ya = a.y + a.h / 2;
    const below = b.y > a.y, yb = below ? ob.y - 8 : ob.y + ob.h + 8, bx = b.x + b.w / 2;
    paths.push({ wire: w, pts: [{ x: a.x + a.w, y: ya }, { x, y: ya }, { x, y: yb }, { x: bx, y: yb }, { x: bx, y: below ? b.y : b.y + b.h }] });
  }
  for (const w of wires) {                       // within a conversation: down the left edge, into the next step
    if (!thread(w.from) || thread(w.from) !== thread(w.to)) continue;
    const a = boxes[w.from], b = boxes[w.to], x = a.x + 9;
    paths.push({ wire: w, pts: [{ x, y: a.y + a.h }, { x, y: b.y + b.h / 2 }, { x: b.x, y: b.y + b.h / 2 }], thread: true });
  }
  const columns = COLUMNS.map((c, i) => ({ ...c, x: LEFT + colX[i] }));
  const width = Math.max(...Object.values(boxes).map(b => b.x + b.w)) + 60;
  paths.push(...crossRoutes(boxes, bands, columns));
  return { boxes, bands, paths, columns, width, height: y + 40 };
}

// Lines between rows, which ELK never sees: into a derived value, along the gap before the derived column;
// otherwise out to the right of the source's box and along the target row's heading strip, then down into the
// target, or for a step in a conversation, down its left side and in like its other inputs.
function crossRoutes(boxes, bands, columns) {
  const { items, wires, groupOf } = model;
  const rowOf = id => items[id]?.row ?? items[groupOf[id]]?.row;
  const out = [];
  let lane = 0, gutter = {};
  for (const w of wires) {
    const ra = rowOf(w.from), rb = rowOf(w.to);
    if (ra === rb) continue;
    const a = boxes[w.from], b = boxes[w.to];
    const ca = items[w.from]?.column ?? 2, cb = items[w.to]?.column ?? 2;
    let pts;
    if (cb === 4) {
      const x = columns[4].x - 12 - 6 * (lane++ % 4);
      const ya = a.y + a.h / 2, yb = b.y + b.h / 2;
      pts = ca === 4
        ? [{ x: a.x + a.w, y: ya }, { x: a.x + a.w + 14 + 6 * lane, y: ya }, { x: a.x + a.w + 14 + 6 * lane, y: yb }, { x: b.x + b.w, y: yb }]
        : [{ x: a.x + a.w, y: ya }, { x, y: ya }, { x, y: yb }, { x: b.x, y: yb }];
    } else {
      const outer = groupOf[w.from] && !w.from.startsWith('set:') ? boxes[groupOf[w.from]] : a;
      const down = rb > ra, band = bands[down ? rb : ra];
      const k = gutter[band.row] = (gutter[band.row] || 0) + 1;
      const gy = band.y + ROW_HEAD - 8 - 5 * (k - 1);
      const x1 = outer.x + outer.w + 10 + 5 * (k - 1), ya = a.y + a.h / 2;
      const start = [{ x: a.x + a.w, y: ya }, { x: x1, y: ya }, { x: x1, y: gy }];
      const into = groupOf[w.to]?.startsWith('chain:') ? boxes[groupOf[w.to]] : null;
      if (into) {                                  // a step in a conversation: in from the left, like its other inputs
        const xe = into.x - 10 - 5 * (k - 1), yb = b.y + b.h / 2;
        pts = [...start, { x: xe, y: gy }, { x: xe, y: yb }, { x: b.x, y: yb }];
      } else pts = [...start, { x: b.x + b.w / 2, y: gy }, { x: b.x + b.w / 2, y: down ? b.y : b.y + b.h }];
    }
    out.push({ wire: w, pts, cross: true });
  }
  return out;
}

// An orthogonal polyline with its corners rounded.
function roundedPath(points, radius = 7) {
  const pts = points.filter((p, i) => i === 0 || Math.hypot(p.x - points[i - 1].x, p.y - points[i - 1].y) > 0.5);
  let d = `M${pts[0].x},${pts[0].y}`;
  for (let i = 1; i < pts.length - 1; i++) {
    const p0 = pts[i - 1], p = pts[i], p1 = pts[i + 1];
    const r = Math.min(radius, Math.hypot(p.x - p0.x, p.y - p0.y) / 2, Math.hypot(p1.x - p.x, p1.y - p.y) / 2);
    const toward = (q, len) => {
      const l = Math.hypot(q.x - p.x, q.y - p.y) || 1;
      return { x: p.x + (q.x - p.x) * len / l, y: p.y + (q.y - p.y) * len / l };
    };
    const a = toward(p0, r), b = toward(p1, r);
    d += ` L${a.x},${a.y} Q${p.x},${p.y} ${b.x},${b.y}`;
  }
  const last = pts[pts.length - 1];
  return `${d} L${last.x},${last.y}`;
}

// ---- drawing ------------------------------------------------------------------------

let drawing = 0;

async function draw() {
  const ticket = ++drawing;
  const L = await layout();
  if (ticket !== drawing) return;
  drawn = L;
  const canvas = document.getElementById('canvas');
  canvas.replaceChildren();
  canvas.style.width = `${L.width}px`;
  canvas.style.height = `${L.height}px`;

  canvas.append(el('div', { class: 'colheads', style: `width:${L.width}px` }, L.columns.map((c, i) => el('div', {
    class: 'colhead', style: `left:${c.x}px` }, c.title, el('span', {}, c.note),
    i === 2 && model.byId.base ? el('button', { class: 'basechip', title: 'The shared start of every step\'s prompt',
      onclick: () => select('base') }, 'base prompt') : null))));
  for (const b of L.bands) {
    canvas.append(el('div', { class: 'band', style: `top:${b.y}px;height:${b.h}px` },
      el('div', { class: 'band-head', style: `left:${LEFT}px` }, el('span', { class: 'band-title' }, b.topic.title),
        el('span', { class: 'band-meta' }, bandMeta(b.topic)))));
  }

  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('class', 'wires');
  svg.setAttribute('width', L.width);
  svg.setAttribute('height', L.height);
  svg.innerHTML = `<defs>${KINDS.map(k => `<marker id="tip-${k}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="4.2"
    markerHeight="4.2" orient="auto-start-reverse"><path d="M1,1 L9,5 L1,9 z" class="tip ${k}"/></marker>`).join('')}</defs>`;
  for (const p of L.paths) {
    const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    path.setAttribute('d', roundedPath(p.pts));
    path.setAttribute('class', `wire ${p.wire.kind}${p.cross ? ' cross' : ''}`);
    path.setAttribute('marker-end', `url(#tip-${p.wire.kind})`);
    path.dataset.wire = p.wire.id;
    path.dataset.a = p.wire.from;
    path.dataset.b = p.wire.to;
    svg.append(path);
  }

  for (const [id, box] of Object.entries(L.boxes)) {
    const it = model.items[id] || { kind: 'step' };
    if (it.kind === 'chain') canvas.append(chainBox(model.groups[id], box));
    else if (it.kind === 'set') canvas.append(setBox(model.groups[id], box));
    else canvas.append(card(model.byId[id], box));
  }
  canvas.append(svg);
  dock();
  applyZoom();
  refit();
  if (selected) highlight();
}

function bandMeta(topic) {
  const n = topic.steps.length;
  if (!records) return `${n} step${n === 1 ? '' : 's'}`;
  const ran = topic.steps.filter(s => ranStep(s)).length;
  return `${ran} of ${n} step${n === 1 ? '' : 's'} ran`;
}

function ranStep(id) {
  const r = records?.[id]?.value;
  return Boolean(r && !r.skipped && (r.prompt || r.each));
}

function title(n) {
  if (n.kind === 'question' || n.kind === 'question set') return n.ask;
  if (n.kind === 'choice set') return n.ask.replace(/^.*?\{item\}\.?\s*/, '');
  return n.title || n.label || n.id;
}


function card(n, box) {
  const state = overlay(n);
  const kind = n.kind.replace(' ', '-');
  return el('div', {
    class: `card k-${kind}${state.off ? ' off' : ''}`, 'data-id': n.id,
    style: `left:${box.x}px;top:${box.y}px;width:${box.w}px;height:${box.h}px`,
    onclick: e => { e.stopPropagation(); select(n.id); },
    onmouseenter: () => hover(n.id, true), onmouseleave: () => hover(n.id, false),
  },
    el('div', { class: 'card-top' },
      el('span', { class: 'id' }, code(n)),
      n.kind === 'question set' || n.kind === 'choice set' ? el('span', { class: 'qtype' }, n.question_type) : null,
      state.badge ? el('span', { class: `tag ${state.badgeClass || ''}` }, state.badge) : null),
    el('div', { class: 'card-title', title: title(n) }, n.kind === 'field' ? (n.label || n.id) : title(n)),
    records ? el('div', { class: 'card-value', title: state.full || state.value || '' }, state.value || '') : null);
}

function chainBox(g, box) {
  return el('div', { class: 'box chain', 'data-id': g.id, style: `left:${box.x}px;top:${box.y}px;width:${box.w}px;height:${box.h}px` },
    el('div', { class: 'box-head' }, el('span', { class: 'id' }, g.label), 'one conversation'));
}

function setBox(g, box) {
  const ch = chipHeight();
  const chips = g.steps.map((sid, i) => {
    const n = model.byId[sid], state = overlay(n);
    return el('div', {
      class: `chip${state.off ? ' off' : ''}`, 'data-id': sid,
      style: `left:${BOX_PAD + (i % 2) * (CHIP_W + CHIP_GAP)}px;top:${BOX_HEAD + Math.floor(i / 2) * (ch + CHIP_GAP)}px;width:${CHIP_W}px;height:${ch}px`,
      title: `${sid} · ${n.title}`,
      onclick: e => { e.stopPropagation(); select(sid); },
    }, el('div', { class: 'chip-name' }, state.dot ? el('i', { class: `dot ${state.dot}` }) : null, itemName(n)),
    records ? el('div', { class: 'chip-value' }, state.chip || '') : null);
  });
  return el('div', {
    class: 'box set', 'data-id': g.id, style: `left:${box.x}px;top:${box.y}px;width:${box.w}px;height:${box.h}px`,
    onclick: () => select(g.id), onmouseenter: () => hover(g.id, true), onmouseleave: () => hover(g.id, false),
  }, el('div', { class: 'box-head' }, el('span', { class: 'id' }, `${g.label}_…`), g.title ? `${g.title} · ` : '', 'one call per flagged item'),
  chips);
}

// ---- dock: zoom, trace, legend ---------------------------------------------------------

const ZOOM_MIN = 0.2, ZOOM_MAX = 2, ZOOM_STEP = 1.2;
let zoom = Number(localStorage.getItem('graph-zoom')) || 0;
// Fit mode: the graph fills the width, and keeps filling it as the panel opens and closes or the window
// changes size, until you zoom by hand.
let fitting = localStorage.getItem('graph-fit') !== '0';
let keyOpen = false;

const LINE_NAMES = { scan: 'the scan\'s answer, used for a fact', data: 'an answer read by the next box',
  condition: 'a condition: whether a step runs, or which prompt it gets', chain: 'the next step in the same conversation' };

function swatch(kind) {
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('width', '28');
  svg.setAttribute('height', '10');
  svg.setAttribute('class', 'swatch');
  svg.innerHTML = `<line x1="1" y1="5" x2="27" y2="5" class="${kind}"/>`;
  return svg;
}

function dock() {
  document.getElementById('dock').replaceChildren(...[
    el('div', { class: 'zoombar' },
      el('button', { title: 'Zoom out (−)', onclick: () => setZoom(zoom / ZOOM_STEP) }, '−'),
      el('button', { id: 'zoom-level', title: 'Reset to 100% (0)', onclick: () => setZoom(1) }, `${Math.round(zoom * 100)}%`),
      el('button', { title: 'Zoom in (+)', onclick: () => setZoom(zoom * ZOOM_STEP) }, '+'),
      el('button', { id: 'fit', class: fitting ? 'on' : '', title: 'Fit the width, and keep fitting it (f)', onclick: fit }, 'Fit')),
    el('label', { class: `toggle${trace ? ' on' : ''}`, title: 'Light the whole lineage of the selected box, not just its neighbours (t)' },
      el('input', { type: 'checkbox', checked: trace, onchange: e => setTrace(e.target.checked) }), 'Trace lineage'),
    el('div', { class: 'keywrap' },
      el('button', { class: `keybtn${keyOpen ? ' on' : ''}`, title: 'What the lines and colours mean (k)', onclick: () => toggleKey() }, 'Key'),
      keyOpen ? el('div', { class: 'keycard' },
        el('div', { class: 'label' }, 'Lines'),
        KINDS.map(k => el('div', { class: 'key-row' }, swatch(k), el('span', {}, LINE_NAMES[k]))),
        el('div', { class: 'label' }, 'Boxes'),
        [['scan', 'a scan question'], ['plan', 'a gate, in code'], ['steps', 'a reasoning step'], ['facts', 'a fact: one settled value'],
          ['derive', 'a derived value, in code']].map(([c, t]) => el('div', { class: 'key-row' }, el('i', { class: `kbar ${c}` }), el('span', {}, t))),
        el('div', { class: 'label' }, 'Keys'),
        el('div', { class: 'key-row muted' }, 'f fit · 0 100% · + − zoom · t trace · Esc close'),
        el('div', { class: 'key-foot' }, `Pipeline ${graph.hash}`)) : null),
    note ? el('div', { class: 'note' }, note) : null].filter(Boolean));
}

function toggleKey() {
  keyOpen = !keyOpen;
  dock();
}

function setTrace(on) {
  trace = on;
  localStorage.setItem('graph-trace', on ? '1' : '0');
  document.querySelector('.toggle')?.classList.toggle('on', on);
  const box = document.querySelector('.toggle input');
  if (box) box.checked = on;
  if (selected) highlight();
}

function setFitting(on) {
  fitting = on;
  localStorage.setItem('graph-fit', on ? '1' : '0');
  document.getElementById('fit')?.classList.toggle('on', on);
}

// Zoom about a point of the visible canvas (its centre by default), keeping that point still.
function setZoom(value, at, keepFit = false) {
  if (!keepFit) setFitting(false);
  const wrap = document.getElementById('wrap');
  const next = Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, value));
  const px = at ? at.x : wrap.clientWidth / 2, py = at ? at.y : wrap.clientHeight / 2;
  const cx = (wrap.scrollLeft + px) / zoom, cy = (wrap.scrollTop + py) / zoom;
  zoom = next;
  applyZoom();
  wrap.scrollLeft = cx * zoom - px;
  wrap.scrollTop = cy * zoom - py;
  localStorage.setItem('graph-zoom', String(zoom));
}

function applyZoom() {
  const wrap = document.getElementById('wrap');
  if (!zoom) zoom = Math.min(1, wrap.clientWidth / (drawn?.width || 1));     // first visit: fit the width
  const canvas = document.getElementById('canvas');
  canvas.style.zoom = zoom;
  canvas.style.setProperty('--px', String(1 / zoom));   // one screen pixel, in canvas units
  canvas.classList.toggle('far', zoom < FAR);
  const label = document.getElementById('zoom-level');
  if (label) label.textContent = `${Math.round(zoom * 100)}%`;
}

// Fit the width, keeping the row at the top of the view where it is.
function fit() {
  const wrap = document.getElementById('wrap');
  setFitting(true);
  setZoom(wrap.clientWidth / drawn.width, { x: 0, y: 0 }, true);
  wrap.scrollLeft = 0;
}

// In fit mode, fit again once the panel has opened or closed or the window has changed size.
function refit() {
  if (!fitting || !drawn) return;
  requestAnimationFrame(() => {
    fit();
    if (selected) reveal(selected);
  });
}

function bindZoom() {
  const wrap = document.getElementById('wrap');
  wrap.addEventListener('wheel', e => {                // ctrl/⌘ + wheel, and trackpad pinch
    if (!e.ctrlKey && !e.metaKey) return;
    e.preventDefault();
    const box = wrap.getBoundingClientRect();
    setZoom(zoom * Math.exp(-e.deltaY * 0.0025), { x: e.clientX - box.left, y: e.clientY - box.top });
  }, { passive: false });
  wrap.addEventListener('click', e => { if (e.target === wrap || e.target.id === 'canvas' || e.target.classList.contains('band')) deselect(); });
  document.addEventListener('keydown', e => {
    if (e.target.closest('input, select, textarea') || e.metaKey || e.ctrlKey || e.altKey) return;
    if (e.key === 'Escape' && keyOpen) toggleKey();
    else if (e.key === 'Escape' && selected) deselect();
    else if (e.key === 'f') fit();
    else if (e.key === 't') setTrace(!trace);
    else if (e.key === 'k') toggleKey();
    else if (e.key === '0') setZoom(1);
    else if (e.key === '+' || e.key === '=') setZoom(zoom * ZOOM_STEP);
    else if (e.key === '-') setZoom(zoom / ZOOM_STEP);
  });
}

// ---- selection ----------------------------------------------------------------------

// The pipeline nodes a selection stands for: a set stands for its steps; a chain box for nothing of its own.
function members(id) {
  return model.groups[id]?.kind === 'set' ? model.groups[id].steps : [id];
}

function lit(id) {
  const start = members(id), lines = model.lines;
  const up = new Set(start), down = new Set(start);
  if (trace) {
    for (let changed = true; changed;) {
      changed = false;
      for (const e of lines) {
        if (up.has(e.to) && !up.has(e.from)) { up.add(e.from); changed = true; }
        if (down.has(e.from) && !down.has(e.to)) { down.add(e.to); changed = true; }
      }
    }
  } else {
    for (const e of lines) {
      if (start.includes(e.to)) up.add(e.from);
      if (start.includes(e.from)) down.add(e.to);
    }
  }
  const nodes = new Set([...up, ...down]);
  const edge = e => (up.has(e.from) && up.has(e.to) && (trace || start.includes(e.to)))
    || (down.has(e.from) && down.has(e.to) && (trace || start.includes(e.from)));
  return { nodes, edge };
}

function highlight() {
  const { nodes, edge } = lit(selected);
  const canvas = document.getElementById('canvas');
  canvas.classList.add('focus');
  canvas.querySelectorAll('.card, .chip').forEach(n => {
    n.classList.toggle('lit', nodes.has(n.dataset.id));
    n.classList.toggle('sel', n.dataset.id === selected);
  });
  canvas.querySelectorAll('.box').forEach(b => {
    const g = model.groups[b.dataset.id];
    b.classList.toggle('lit', g.steps.some(s => nodes.has(s)));
    b.classList.toggle('sel', b.dataset.id === selected);
  });
  const wires = Object.fromEntries(model.wires.map(w => [w.id, w]));
  canvas.querySelectorAll('path.wire').forEach(p => p.classList.toggle('lit', wires[p.dataset.wire].edges.some(edge)));
}

function hover(id, on) {
  document.querySelectorAll(`path.wire[data-a="${CSS.escape(id)}"], path.wire[data-b="${CSS.escape(id)}"]`)
    .forEach(p => p.classList.toggle('hover', on));
}

function select(id, scroll = false) {
  if (id === null || id === undefined) return deselect();
  if (selected === id && !scroll) return deselect();
  if (!model.byId[id] && !model.groups[id]) return;
  selected = id;
  setParams({ node: id });
  highlight();
  showPanel(id);
  if (scroll) reveal(id);
}

function deselect() {
  selected = null;
  setParams({ node: null });
  const canvas = document.getElementById('canvas');
  canvas.classList.remove('focus');
  canvas.querySelectorAll('.lit, .sel').forEach(n => n.classList.remove('lit', 'sel'));
  document.getElementById('panel').replaceChildren();
  document.getElementById('page').classList.remove('open');
  refit();
}

// Scroll a box into the middle of the view, unless it is already in view.
function reveal(id) {
  const node = document.querySelector(`[data-id="${CSS.escape(id)}"]`);
  if (!node) return;
  const wrap = document.getElementById('wrap'), r = node.getBoundingClientRect(), w = wrap.getBoundingClientRect();
  if (r.left >= w.left && r.right <= w.right && r.top >= w.top && r.bottom <= w.bottom) return;
  wrap.scrollTo({ left: wrap.scrollLeft + r.left - w.left - (w.width - r.width) / 2,
    top: wrap.scrollTop + r.top - w.top - (w.height - r.height) / 2, behavior: 'smooth' });
}

// ---- run overlay --------------------------------------------------------------------

function scanDist(id) {
  return records?.scan?.value?.[id] || null;
}

function top(dist) {
  if (!dist) return null;
  return Object.entries(dist).sort((a, b) => b[1] - a[1])[0];
}

// A step's answer in a few words: each returned value, without its quotes; `first`: only the first value.
function answerText(answer, first = false) {
  if (!answer || typeof answer !== 'object') return short(answer, 80);
  const plain = v => {
    if (Array.isArray(v)) return v.length ? v.map(x => plain(x?.answer ?? x)).join('; ') : 'none';
    if (v && typeof v === 'object' && 'answer' in v) return plain(v.answer);
    if (v && typeof v === 'object') return Object.values(v).map(plain).join(', ');
    return String(v);
  };
  const parts = Object.entries(answer).map(([k, v]) => [k, plain(v)]);
  if (first) return parts[0]?.[1] ?? '';
  return parts.length === 1 ? parts[0][1] : parts.map(([k, v]) => `${k}: ${v}`).join(' · ');
}

function overlay(n) {
  if (!records) return {};
  if (n.kind === 'question') {
    const best = top(scanDist(n.id));
    return best ? { value: `${best[0]} · ${best[1].toFixed(2)}` } : {};
  }
  if (n.kind === 'choice set') {
    const none = n.null || Object.keys(n.choices)[0];
    const read = Object.keys(n.options).map(k => [k, top(scanDist(`${n.id}.${k}`))]).filter(([, b]) => b && b[0] !== none);
    return { value: read.length ? read.map(([k, b]) => `${k}: ${b[0]}`).join(' · ') : `all ${none}` };
  }
  if (n.kind === 'question set') {
    const flagged = Object.keys(n.options).filter(k => (scanDist(`${n.id}.${k}`)?.yes || 0) >= (graph.thresholds?.check ?? 0.3));
    return { value: flagged.length ? flagged.join(', ') : 'none flagged' };
  }
  if (n.kind === 'gate') {
    const g = records.plan?.value?.gates?.[n.id];
    return g ? { badge: g.passed ? 'passes' : 'skips', badgeClass: g.passed ? 'pass' : 'skip', off: !g.passed,
      value: g.passed ? 'passes' : 'does not pass' } : {};
  }
  if (n.kind === 'step') {
    const planned = records.plan?.value?.steps?.find(s => s.step === n.id);
    const r = records[n.id]?.value;
    if (r?.skipped) return { badge: r.skipped.startsWith('halted') ? 'halted' : 'skipped', badgeClass: 'skip', off: true,
      value: r.skipped, dot: 'skip', chip: 'skipped' };
    if (!planned?.runs) return { badge: 'not run', badgeClass: 'skip', off: true, value: planned?.reason || '', dot: 'skip', chip: 'not run' };
    if (!r) return { badge: 'planned', value: planned.depends ? `if ${planned.depends}` : '', chip: 'planned' };
    if (r.each) return { badge: `ran ×${r.asked}`, badgeClass: r.error ? 'fail' : 'pass', dot: r.error ? 'fail' : 'pass',
      value: `${r.asked} of ${r.items} asked · quotes ${r.quotes_verified}/${r.quotes_checked}`, chip: `${r.asked} asked` };
    if (r.error) return { badge: 'failed', badgeClass: 'fail', value: r.error, dot: 'fail', chip: 'failed' };
    const said = answerText(r.answer);
    return { badge: r.attempts > 1 ? `ran · ${r.attempts} tries` : 'ran', badgeClass: 'pass', dot: 'pass', full: said,
      value: `${said} · quotes ${r.quotes_verified}/${r.quotes_checked}`, chip: answerText(r.answer, true) };
  }
  if (n.kind === 'field') {
    const f = records.facts?.value?.[n.id];
    if (!f) return {};
    const source = typeof f.source === 'string' ? f.source : 'mixed';
    return { value: short(f.answer, 90), full: short(f.answer, 400), badge: source,
      badgeClass: source === 'step' ? 'pass' : source === 'none' ? 'skip' : '' };
  }
  if (n.kind === 'derive') {
    const v = records.derive?.value?.[n.id];
    return v === undefined ? {} : { value: short(v, 90), full: short(v, 400) };
  }
  return {};
}

// ---- panel --------------------------------------------------------------------------
// Every panel has the same shape: what the box is and where it sits, its name and code; on a run, what happened;
// a labelled description and a short list of properties; its connections; then the long material (prompts,
// options, code), each in a section that folds.

const KIND_NAMES = {
  question: 'Scan question', 'question set': 'Scan questions', 'choice set': 'Scan questions', gate: 'Gate',
  base: 'Base prompt', step: 'Reasoning step', set: 'Reasoning steps', field: 'Fact', derive: 'Derived value',
};
const KIND_COLOR = { question: 'scan', 'question set': 'scan', 'choice set': 'scan', gate: 'plan', base: 'steps',
  step: 'steps', set: 'steps', field: 'facts', derive: 'derive' };

function section(title, content, { open = true, aside = '' } = {}) {
  return el('details', { class: 'sec', open },
    el('summary', {}, el('span', {}, title), aside ? el('span', { class: 'sec-aside' }, aside) : null),
    el('div', { class: 'sec-body' }, content));
}

// Labelled properties. A long or code-like value takes the full width under its label.
function props(rows) {
  const list = rows.filter(r => r && r[1] !== null && r[1] !== undefined && r[1] !== '');
  if (!list.length) return null;
  return el('dl', { class: 'props' }, list.map(([label, value, wide]) => el('div', { class: `prop${wide ? ' wide' : ''}` },
    el('dt', {}, label), el('dd', {}, value))));
}

function labelled(label, ...content) {
  return el('div', { class: 'labelled' }, el('div', { class: 'label' }, label), ...content);
}

// An expression broken at its top-level "and"/"or", so a long condition reads as a list.
function expression(text) {
  if (!text) return null;
  let depth = 0, out = '';
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (c === '(' || c === '[') depth++;
    if (c === ')' || c === ']') depth--;
    const rest = text.slice(i);
    if (depth === 0 && (rest.startsWith(' or ') || rest.startsWith(' and '))) { out += '\n'; continue; }
    out += c;
  }
  return el('pre', { class: 'code' }, out);
}

// Facts go by their field name, which is also their column in a release; the rest by their code.
function code(n) {
  return n.kind === 'field' ? n.id : n.code || n.id;
}

function prose(text) {
  return el('pre', { class: 'prose' }, text);
}

function source(text) {
  return el('pre', { class: 'code' }, text);
}

// A link to another box: its kind's colour, its code, and its name.
function ref(id, { row = false } = {}) {
  const n = model.byId[id] || model.groups[id];
  const name = n ? displayName(n) : '';
  return el('button', { class: `ref${row ? ' row' : ''}`, title: name, onclick: () => select(id, true) },
    el('i', { class: `kdot ${KIND_COLOR[n?.kind] || ''}` }), el('code', {}, n ? (n.kind === 'set' ? `${n.label}_…` : code(n)) : id),
    row && name !== (n && code(n)) ? el('span', {}, name) : null);
}

function refs(ids) {
  return el('span', { class: 'refs' }, [...new Set(ids)].map(id => ref(id)));
}

// What a person would call the box: a question's question, a step's or a gate's title, a fact's label.
function displayName(n) {
  if (n.kind === 'set') return n.title ? `${n.title}, one call per flagged item` : 'One call per flagged item';
  if (n.kind === 'base') return 'The base prompt';
  if (n.kind === 'question' || n.kind === 'question set' || n.kind === 'choice set') return questionPart(n.ask);
  return n.title || n.label || n.id;
}

// The question itself, without the item it is asked about or the instructions that follow it.
function questionPart(ask) {
  const body = ask.replace(/^[^.?]*\{item\}\.\s*/, '');
  const q = body.match(/^[^?]*\?/);
  return q ? q[0] : body.split('. ')[0];
}

function topicOf(id) {
  const r = model.row[id] ?? model.row[members(id)[0]];
  return model.topics[r]?.title;
}

function connections(id) {
  const ids = members(id);
  const reads = [...new Set(model.lines.filter(e => ids.includes(e.to) && !ids.includes(e.from)).map(e => e.from))];
  const feeds = [...new Set(model.lines.filter(e => ids.includes(e.from) && !ids.includes(e.to)).map(e => e.to))];
  if (!reads.length && !feeds.length) return null;
  return section('Connections', el('div', { class: 'conns' },
    reads.length ? labelled(`Reads ${reads.length}`, el('div', { class: 'conn-list' }, reads.map(x => ref(x, { row: true })))) : null,
    feeds.length ? labelled(`Feeds ${feeds.length}`, el('div', { class: 'conn-list' }, feeds.map(x => ref(x, { row: true })))) : null));
}

function status(kind, text) {
  return el('div', { class: `status ${kind}` }, el('i', { class: `dot ${kind}` }), el('span', {}, text));
}

function showPanel(id) {
  const n = model.byId[id] || model.groups[id];
  const panel = document.getElementById('panel');
  const opening = !document.getElementById('page').classList.contains('open');
  document.getElementById('page').classList.add('open');
  const meta = { 'question set': `${Object.keys(n.options || {}).length} yes/no questions, one per item`,
    'choice set': `${Object.keys(n.options || {}).length} choice questions, one per item`,
    question: n.question_type ? `${n.question_type}` : '', set: `${n.steps?.length} steps`,
    field: 'column in a release', derive: 'computed in code', gate: 'computed in code', step: '' }[n.kind] || '';
  panel.replaceChildren(...[
    el('div', { class: 'p-head' },
      el('button', { class: 'close', title: 'Close (Esc)', onclick: () => deselect() }, '×'),
      el('div', { class: 'p-kicker' }, el('i', { class: `kdot ${KIND_COLOR[n.kind]}` }), KIND_NAMES[n.kind],
        topicOf(id) ? el('span', {}, ` · ${topicOf(id)}`) : null),
      el('h2', {}, displayName(n)),
      n.kind !== 'base' ? el('div', { class: 'p-meta' }, el('code', {}, n.kind === 'set' ? `${n.label}_…` : code(n)), meta ? ` · ${meta}` : '') : null),
    ...(renderers[n.kind] || (() => []))(n),
  ].flat(Infinity).filter(Boolean));
  panel.scrollTop = 0;
  if (opening) refit();
}

// ---- panel pieces: values, quotes, options, replies ----------------------------------------

function quotes(list) {
  if (!list?.length) return null;
  return el('div', { class: 'quotes' }, list.map(q => el('blockquote', { class: `quote ${q.verified === false ? 'bad' : 'ok'}` },
    el('div', {}, q.quote),
    el('div', { class: 'cite' }, `document ${q.doc}, page ${q.page}`,
      q.verified === undefined ? '' : q.verified ? ' · found on the page' : ' · not found on the page'))));
}

const humanKey = k => { const t = String(k).replace(/_/g, ' '); return t[0].toUpperCase() + t.slice(1); };

function plainValue(v) {
  if (v === null || v === undefined) return el('span', { class: 'v-null' }, '—');
  if (typeof v === 'string') return el('span', { class: v === 'not stated' ? 'v-ns' : '' }, v);
  if (typeof v !== 'object') return el('span', {}, String(v));
  if (Array.isArray(v)) return v.length ? el('ul', { class: 'v-list' }, v.map(x => el('li', {}, plainValue(x)))) : el('span', { class: 'v-ns' }, 'none');
  return el('dl', { class: 'v-rec' }, Object.entries(v).map(([k, x]) => [el('dt', {}, humanKey(k)), el('dd', {}, plainValue(x))]));
}

// A step's reply, read as answers: each key with its value and the quotes behind it.
function answerView(answer) {
  if (!answer || typeof answer !== 'object') return plainValue(answer);
  const one = (v) => {
    if (v && typeof v === 'object' && !Array.isArray(v) && 'answer' in v) return [plainValue(v.answer), quotes(v.quotes)];
    if (Array.isArray(v) && v.some(x => x && typeof x === 'object' && 'answer' in x)) {
      return el('ol', { class: 'answer-list' }, v.map(x => el('li', {}, one(x))));
    }
    return plainValue(v);
  };
  return el('div', { class: 'answer-view' }, Object.entries(answer).map(([k, v]) =>
    el('div', { class: 'answer-item' }, el('div', { class: 'label' }, humanKey(k)), el('div', { class: 'answer-value' }, one(v)))));
}

function raw(value) {
  return el('details', { class: 'raw' }, el('summary', {}, 'raw JSON'), jsonTree(value));
}

function reply(text) {
  const parsed = parseReply(text);
  if (!parsed.ok) return prose(text);
  return [jsonTree(parsed.value), el('details', { class: 'raw' }, el('summary', {}, 'raw text'), prose(text))];
}

function attempts(exchange) {
  if (!exchange) return null;
  return exchange.attempts.map((a, i) => el('div', { class: 'attempt' },
    el('div', { class: 'attempt-head' }, `Attempt ${i + 1}`, a.stop ? el('span', { class: 'muted' }, ` · stopped: ${a.stop}`) : null,
      (a.resent || a.truncated) ? el('span', { class: 'bad' }, ` · ${a.errors.join('; ')}: sent again unchanged`)
        : a.errors.length ? el('span', { class: 'bad' }, ` · sent back: ${a.errors.join('; ')}`) : el('span', { class: 'good' }, ' · valid')),
    reply(a.reply)));
}

function costText(rec) {
  return `$${(rec.cost_usd || 0).toFixed(4)}${rec.reused ? ', reused from an earlier run' : ''}`;
}

// Options or items: a name, what it means, and on a run the scan's probability for it.
function optionList(options, dist) {
  return el('div', { class: 'options' }, Object.entries(options).map(([name, meaning]) => {
    const p = dist ? (dist[name] ?? 0) : null;
    return el('div', { class: 'option' },
      el('div', { class: 'option-head' }, el('span', { class: 'name' }, name),
        p === null ? null : el('span', { class: 'p' }, p.toFixed(2))),
      p === null ? null : el('div', { class: 'bar' }, el('span', { style: `width:${(p * 100).toFixed(1)}%` })),
      meaning && meaning !== name ? el('div', { class: 'meaning' }, meaning) : null);
  }));
}

function scanStatus(dist) {
  const best = top(dist);
  return best ? status('pass', `The scan answered "${best[0]}" with probability ${best[1].toFixed(2)}`) : null;
}

function notesList(n) {
  return n.notes?.length ? section('Notes', el('ul', { class: 'notes' }, n.notes.map(t => el('li', {}, t)))) : null;
}

// ---- panel renderers, one per kind of box ---------------------------------------------------

function fullAsk(n) {
  const text = n.ask.replace('{item}', '[item]');
  return text.trim() !== questionPart(n.ask).trim() ? labelled('The full question', el('p', { class: 'lead' }, text)) : null;
}

function why(n) {
  return n.why ? labelled('Why it is asked', el('p', {}, n.why)) : null;
}

const renderers = {
  question(n) {
    const dist = scanDist(n.id);
    const options = n.options_source ? null : optionList(n.options, dist);
    return [records ? scanStatus(dist) : null, fullAsk(n), why(n),
      n.options_source ? section('Options', [el('p', { class: 'muted' }, 'Built for each docket by this function:'), source(n.options_source),
        dist ? optionList(Object.fromEntries(Object.keys(dist).map(k => [k, ''])), dist) : null])
        : section(dist ? 'Answers it could give, with the scan\'s probabilities' : 'Answers it can give', options,
          { aside: String(Object.keys(n.options).length) }),
      connections(n.id)];
  },
  'question set'(n) {
    const dist = records ? Object.fromEntries(Object.keys(n.options).map(k => [k, scanDist(`${n.id}.${k}`)?.yes ?? 0])) : null;
    const flagged = dist ? Object.keys(dist).filter(k => dist[k] >= (graph.thresholds?.check ?? 0.3)) : [];
    return [records ? status(flagged.length ? 'pass' : 'skip', flagged.length ? `Flagged: ${flagged.join(', ')}` : 'Nothing flagged') : null,
      fullAsk(n), why(n),
      section('Items', optionList(n.options, dist),
        { aside: dist ? 'probability of yes' : String(Object.keys(n.options).length) }),
      connections(n.id)];
  },
  'choice set'(n) {
    const none = n.null || Object.keys(n.choices)[0];
    const items = Object.entries(n.options).map(([k, meaning]) => {
      const dist = scanDist(`${n.id}.${k}`), best = top(dist);
      return el('details', { class: 'item-row' },
        el('summary', {}, el('span', { class: 'name' }, k),
          best ? el('span', { class: `item-val${best[0] === none ? ' muted' : ''}` }, `${best[0]} · ${best[1].toFixed(2)}`) : null),
        el('div', { class: 'meaning' }, meaning), dist ? optionList(n.choices, dist) : null);
    });
    return [fullAsk(n), why(n),
      section('Items', el('div', { class: 'item-rows' }, items),
        { aside: records ? 'the scan\'s most likely answer' : String(items.length) }),
      section('Answers each can give', optionList(n.choices, null), { open: !records }),
      connections(n.id)];
  },
  gate(n) {
    const g = records?.plan?.value?.gates?.[n.id];
    const thresholds = Object.entries(graph.thresholds).filter(([k]) => n.condition.includes(`T.${k}`));
    return [g ? status(g.passed ? 'pass' : 'skip', g.passed ? 'Passes for this docket' : 'Does not pass for this docket') : null,
      n.why ? el('p', { class: 'lead' }, n.why) : null,
      labelled('Passes when', expression(n.condition)),
      g ? section('This docket\'s values', el('table', { class: 'vals' }, g.terms.map(t =>
        el('tr', {}, el('td', {}, el('code', {}, t.term)), el('td', {}, String(t.value)))))) : null,
      thresholds.length ? section('Thresholds', el('table', { class: 'vals' }, thresholds.map(([k, v]) =>
        el('tr', {}, el('td', {}, el('code', {}, `T.${k}`)), el('td', {}, String(v)))))) : null,
      connections(n.id)];
  },
  base(n) {
    return [el('p', { class: 'lead' }, 'Every reasoning step starts from this prompt. It is built once for each docket and cached by the reasoning model, so each step pays only for its own question.'),
      labelled('It holds', el('ol', { class: 'plain' }, el('li', {}, 'the framing below'), el('li', {}, 'the docket\'s text'),
        el('li', {}, 'every scan answer, as a claim to confirm or refute'))),
      section('Framing', prose(n.framing)),
      records?.base ? section('This docket\'s scan claims', prose(records.base.value.claims), { open: false }) : null];
  },
  set(g) {
    const first = model.byId[g.steps[0]];
    return [el('p', { class: 'lead' }, `One reasoning call for each item the scan flags, independent of the others. Choose an item for its prompt${records ? ' and reply' : ''}.`),
      props([['Runs when', first.when ? [ref(first.when), expression(first.when_text)] : first.when_text, true]]),
      section('Items', el('div', { class: 'conn-list' }, g.steps.map(sid => {
        const s = model.byId[sid], state = overlay(s);
        return el('button', { class: `ref row${state.off ? ' off' : ''}`, onclick: () => select(sid, true) },
          el('i', { class: `dot ${state.dot || 'none'}` }), el('code', {}, sid), el('span', {}, itemName(s)),
          records ? el('span', { class: 'ref-aside' }, state.chip || '') : null);
      })), { aside: String(g.steps.length) }),
      connections(g.id)];
  },
  step(n) {
    const rec = records?.[n.id], r = rec?.value;
    const planned = records?.plan?.value?.steps?.find(s => s.step === n.id);
    const ran = Boolean(r && !r.skipped && (r.prompt || r.each));
    let state = null;
    if (records) {
      if (r?.skipped) state = status('skip', r.skipped);
      else if (planned && !planned.runs) state = status('skip', `Not run: ${planned.reason || 'its gate did not pass'}`);
      else if (r?.error) state = status('fail', `Failed: ${r.error}`);
      else if (r?.each) state = status('pass', `Ran for ${r.asked} of ${r.items} items · ${r.quotes_verified} of ${r.quotes_checked} quotes found`);
      else if (ran) state = status('pass', `Ran${r.attempts > 1 ? ` in ${r.attempts} attempts` : ''} · ${r.quotes_verified} of ${r.quotes_checked} quotes found · ${costText(rec)}`);
    }
    const out = [state];
    if (ran && r.answer) out.push(section('Answer', answerView(r.answer)));
    out.push(section('How it runs', props([
      ['Runs when', n.when ? [ref(n.when), expression(n.when_text)] : n.when_text, true],
      ['Only if', expression(n.only_if), true],
      ['Variant', n.choose ? expression(n.choose) : null, true],
      ['Halts unless', expression(n.halt_unless), true],
      ['Follows', parentOf(n) ? refs([parentOf(n)]) : null],
      ['Sees', (n.context || n.chain_after || []).length ? refs(n.context || n.chain_after) : null],
      ['Checks', n.confirms?.length ? refs(n.confirms) : null],
      ['For each', n.for_each ? `item of ${n.for_each}${n.limit ? `, the first ${n.limit}` : ''}` : null],
    ])));
    out.push(connections(n.id));
    if (r?.each) {
      out.push(section(`Calls · ${r.asked}`, r.each.map((e, i) => {
        const sub = records[`${n.id}[${i + 1}]`];
        return el('details', { class: 'call' },
          el('summary', {}, `${i + 1}. ${n.item ? fillItem(n.item, e.item) : JSON.stringify(e.item)}${e.error ? ' · failed' : ''}`),
          e.answer ? answerView(e.answer) : null,
          labelled('Prompt sent', prose(e.prompt)),
          sub?.exchange ? labelled('Replies', attempts(sub.exchange)) : null,
          sub ? el('p', { class: 'muted' }, `Cost ${costText(sub)}`) : null);
      })));
    } else if (ran) {
      out.push(section(`Prompt sent${r.variant ? ` · ${r.variant}` : ''}`, prose(r.prompt), { open: false }));
      if (rec.exchange) out.push(section('Replies', attempts(rec.exchange), { open: false, aside: String(rec.exchange.attempts.length) }));
      if (r.answer) out.push(section('Answer as JSON', jsonTree(r.answer), { open: false }));
    }
    if (n.variants) {
      out.push(section('Prompt variants', Object.entries(n.variants).map(([k, v]) => labelled(k, prose(v))), { open: !ran }));
    } else out.push(section(ran ? 'Prompt template' : 'Prompt', prose(n.prompt), { open: !ran }));
    if (n.returns) {
      out.push(section('Reply shape', [typeView(n.returns), labelled('Example reply', jsonTree(example(n.returns)))], { open: !ran }));
    }
    if (n.schema) out.push(section('JSON schema', jsonTree(n.schema, 2), { open: false }));
    return out;
  },
  field(n) {
    const f = records?.facts?.value?.[n.id];
    const sourceText = f && ({ step: 'from its step, with quotes', scan: `from the scan alone${f.probability != null ? `, probability ${f.probability}` : ''}`,
      rule: 'by a rule', none: 'no source' }[f.source] || (typeof f.source === 'string' ? f.source : 'from several sources'));
    return [
      f ? el('div', { class: 'value-card' },
        el('div', { class: 'label' }, 'This docket'),
        el('div', { class: 'value-main' }, plainValue(f.answer)),
        el('div', { class: 'muted' }, `Settled ${sourceText}${f.conflict ? ` · the scan said "${f.scan_answer}"` : ''}`),
        f.note ? el('div', { class: 'muted' }, f.note) : null,
        quotes(f.quotes)) : null,
      section('How it is settled', [el('p', {}, n.rule), props([
        ['From step', n.from_step ? el('code', {}, n.from_step) : null],
        ['From scan', n.from_scan ? el('code', {}, n.from_scan) : null],
        ['Not stated if', expression(n.not_stated_if), true],
        ['When unsure', n.scan_if_unsure ? 'a step\'s "not stated" keeps the scan\'s answer' : null],
        ['Scored', n.scored ? 'yes, against the answer key' : 'no: free text'],
      ])]),
      notesList(n),
      connections(n.id),
      section('Values it can take', typeView(n.value_type)),
      n.source ? section('Function', source(n.source), { open: false }) : null,
    ];
  },
  derive(n) {
    const v = records?.derive?.value?.[n.id];
    return [
      v !== undefined ? el('div', { class: 'value-card' }, el('div', { class: 'label' }, 'This docket'),
        el('div', { class: 'value-main' }, plainValue(v))) : null,
      notesList(n),
      connections(n.id),
      section('Function', source(n.source)),
      section('Values it can take', typeView(n.value_type)),
    ];
  },
};

function fillItem(template, item) {
  return template.replace(/\{(\w+)\}/g, (_, k) => item?.[k] ?? '');
}

window.addEventListener('resize', () => { if (fitting) refit(); else if (drawn) applyZoom(); });
bindZoom();
main().catch(e => notice(e.message, true));
