// Readable views of typed values for the side panel: a value type drawn as a shape, an example
// value built from it, and JSON drawn as a collapsible tree.
import { el } from '/common.js';

const NOT_STATED = 'not stated';

// ---- value types: the codebook's own descriptions ({type: 'record', fields: …}) -----------

function pill(text, cls = '') {
  return el('span', { class: `ty ${cls}` }, text);
}

function choices(options) {
  return el('span', { class: 'choices' }, Object.entries(options).map(([name, meaning]) =>
    el('span', { class: `choice${name === NOT_STATED ? ' ns' : ''}`, title: meaning || '' }, name)));
}

// One line per value: a key, its type, and any nested shape indented beneath it.
function typeRows(desc, key) {
  const head = (...rest) => el('div', { class: 'ty-row' }, key ? el('span', { class: 'ty-key' }, key) : null, ...rest);
  const nested = rows => el('div', { class: 'ty-nest' }, rows);
  switch (desc?.type) {
    case 'record':
      return [head(pill('record')), nested(Object.entries(desc.fields).map(([k, v]) => typeRows(v, k)))];
    case 'list':
      return [head(pill('list of'), desc.not_stated ? pill('or not stated', 'ns') : null), nested(typeRows(desc.item, null))];
    case 'quoted': {
      const inner = typeRows(desc.answer, null);
      const [first, ...rest] = inner;
      return [head(pill('quoted', 'quoted'), ...first.childNodes), ...rest];
    }
    case 'one of': return [head(pill('one of'), choices(desc.options))];
    case 'counts by': return [head(pill('count for each of'), choices(desc.options))];
    case 'or not stated': {
      const [first, ...rest] = typeRows(desc.value, null);
      return [head(...first.childNodes, pill('or not stated', 'ns')), ...rest];
    }
    case 'count': return [head(pill('count'), el('span', { class: 'ty-note' }, 'whole number ≥ 0'), pill('or not stated', 'ns'))];
    case 'integer': return [head(pill('integer'), pill('or not stated', 'ns'))];
    case 'date': return [head(pill('date'), el('span', { class: 'ty-note' }, 'YYYY, YYYY-MM or YYYY-MM-DD'), pill('or not stated', 'ns'))];
    default: return [head(pill(desc?.type || '?'))];
  }
}

export function typeView(desc) {
  const quoted = JSON.stringify(desc).includes('"quoted"');
  return el('div', { class: 'typeview' }, typeRows(desc, null),
    quoted ? el('div', { class: 'ty-foot' }, pill('quoted', 'quoted'),
      ' the answer comes with quotes: [{doc, page, quote}], each checked against its page') : null);
}

export function example(desc) {
  switch (desc?.type) {
    case 'record': return Object.fromEntries(Object.entries(desc.fields).map(([k, v]) => [k, example(v)]));
    case 'list': return [example(desc.item)];
    case 'quoted': return { answer: example(desc.answer), quotes: [{ doc: 1, page: 3, quote: '…a short passage copied exactly…' }] };
    case 'one of': return Object.keys(desc.options).find(k => k !== NOT_STATED) ?? NOT_STATED;
    case 'counts by': return { [Object.keys(desc.options)[0]]: 2 };
    case 'or not stated': return example(desc.value);
    case 'count': case 'integer': return 12;
    case 'date': return '2015-06-01';
    case 'name': return 'Jane Doe';
    case 'true or false': return true;
    case 'text': return '…';
    default: return null;
  }
}

// ---- JSON as a collapsible tree ------------------------------------------------------

function scalar(value) {
  if (value === null) return el('span', { class: 'j-null' }, 'null');
  if (typeof value === 'string') return el('span', { class: `j-str${value === NOT_STATED ? ' ns' : ''}` }, JSON.stringify(value));
  if (typeof value === 'number') return el('span', { class: 'j-num' }, String(value));
  if (typeof value === 'boolean') return el('span', { class: 'j-bool' }, String(value));
  return el('span', {}, String(value));
}

function preview(value) {
  const text = JSON.stringify(value);
  return text.length > 60 ? text.slice(0, 59) + '…' : text;
}

function node(value, key, depth, openDepth) {
  const label = key === null ? null : el('span', { class: 'j-key' }, typeof key === 'number' ? `${key}` : key);
  if (value === null || typeof value !== 'object') {
    return el('div', { class: 'j-line' }, label, label ? el('span', { class: 'j-colon' }, ': ') : null, scalar(value));
  }
  const entries = Array.isArray(value) ? value.map((v, i) => [i, v]) : Object.entries(value);
  const [open, close] = Array.isArray(value) ? ['[', ']'] : ['{', '}'];
  if (!entries.length) return el('div', { class: 'j-line' }, label, label ? ': ' : null, el('span', { class: 'j-punct' }, open + close));
  const count = Array.isArray(value) ? `${entries.length} item${entries.length > 1 ? 's' : ''}` : `${entries.length} key${entries.length > 1 ? 's' : ''}`;
  return el('details', { class: 'j-node', open: depth < openDepth },
    el('summary', {}, label, label ? el('span', { class: 'j-colon' }, ': ') : null,
      el('span', { class: 'j-punct' }, open), el('span', { class: 'j-count' }, count),
      el('span', { class: 'j-preview' }, preview(value))),
    el('div', { class: 'j-children' }, entries.map(([k, v]) => node(v, k, depth + 1, openDepth))),
    el('span', { class: 'j-punct' }, close));
}

export function jsonTree(value, openDepth = 4) {
  return el('div', { class: 'jtree' }, node(value, null, 0, openDepth));
}

// A model's reply: parsed and drawn as a tree when it is JSON (fenced or not), else plain text.
export function parseReply(text) {
  if (typeof text !== 'string') return { ok: true, value: text };
  const body = text.trim().replace(/^```(?:json)?\s*/i, '').replace(/```$/, '').trim();
  try { return { ok: true, value: JSON.parse(body) }; } catch { return { ok: false }; }
}
