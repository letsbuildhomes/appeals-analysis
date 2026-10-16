// Shared helpers for the dashboard pages. Plain JavaScript, no build step.

export async function api(path) {
  const response = await fetch(`/api/${path}`);
  const body = await response.json();
  if (!response.ok) throw new Error(body.error || response.statusText);
  return body;
}

export function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value === undefined || value === null || value === false) continue;
    if (key === 'class') node.className = value;
    else if (key === 'text') node.textContent = value;
    else if (key.startsWith('on')) node.addEventListener(key.slice(2), value);
    else node.setAttribute(key, value === true ? '' : value);
  }
  for (const child of children.flat()) {
    if (child === undefined || child === null || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

export function short(value, limit = 60) {
  if (value === undefined || value === null) return '';
  let text;
  if (Array.isArray(value)) text = value.length ? `${value.length} item${value.length > 1 ? 's' : ''}` : 'none';
  else if (typeof value === 'object') {
    const entries = Object.entries(value);
    if (entries.every(([, v]) => v === 'yes' || v === 'no')) {
      const yes = entries.filter(([, v]) => v === 'yes').map(([k]) => k);
      text = yes.length ? yes.join(', ') : 'none';
    } else text = entries.map(([k, v]) => `${k}: ${typeof v === 'object' ? JSON.stringify(v) : v}`).join(' · ');
  } else text = String(value);
  return text.length > limit ? text.slice(0, limit - 1) + '…' : text;
}

export function header(active, stats) {
  const bar = document.querySelector('header.top');
  bar.innerHTML = '';
  bar.append(
    el('h1', { text: 'Housing appeals' }),
    el('nav', {},
      el('a', { href: '/', class: active === 'graph' ? 'on' : '' }, 'Graph'),
      el('a', { href: '/case', class: active === 'case' ? 'on' : '' }, 'Case')),
    el('div', { class: 'stats', id: 'stats' }),
    el('div', { class: 'spacer' }),
    el('div', { class: 'control', id: 'controls' }),
  );
  api('stats').then(s => {
    document.getElementById('stats').textContent =
      `${s.dockets.toLocaleString()} dockets · ${s.documents.toLocaleString()} documents · ${s.pages.toLocaleString()} pages · ${s.runs} runs`;
  }).catch(() => { document.getElementById('stats').textContent = 'store busy: a run is writing'; });
}

export const AREA_ORDER = ['scope', 'A', 'B', 'C', 'D', 'E', 'F'];

export function params() {
  return new URLSearchParams(location.search);
}

export function setParams(values) {
  const p = params();
  for (const [k, v] of Object.entries(values)) {
    if (v === null || v === undefined || v === '') p.delete(k); else p.set(k, v);
  }
  history.replaceState(null, '', `${location.pathname}?${p}`);
}
