export function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  let value;
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    if (k === 'class') el.className = v;
    else if (k === 'style') el.style.cssText = v;
    else if (k === 'value') value = v;
    else if (k.startsWith('on')) el.addEventListener(k.slice(2).toLowerCase(), v);
    else if (['checked', 'disabled', 'selected', 'hidden', 'multiple'].includes(k)) el[k] = true;
    else el.setAttribute(k, v === true ? '' : v);
  }
  append(el, kids);
  if (value !== undefined) el.value = value;
  return el;
}

export function append(el, kids) {
  for (const k of kids.flat(Infinity)) {
    if (k == null || k === false) continue;
    el.append(k instanceof Node ? k : document.createTextNode(String(k)));
  }
  return el;
}

export function clear(el, ...kids) {
  el.replaceChildren();
  return append(el, kids);
}

export const pct = (x, d = 1) => (x == null ? '—' : (x * 100).toFixed(d).replace('.', ',') + ' %');
export const num = (x, d = 2) => (x == null ? '—' : Number(x).toFixed(d).replace('.', ','));
export const dur = (s) => (s == null ? '—' : Number(s).toFixed(1).replace('.', ',') + ' s');
export function dt(iso) {
  if (!iso) return '—';
  const d = new Date(iso);
  return isNaN(d) ? '—' : d.toLocaleString('pl-PL', { dateStyle: 'short', timeStyle: 'short' });
}
export function show(v) {
  if (v === null || v === undefined || v === '') return '—';
  return typeof v === 'string' ? v : JSON.stringify(v);
}

export function badge(text, kind = 'idle') {
  return h('span', { class: `badge ${kind}` }, text);
}

export function errorBox(msg) {
  return h('div', { class: 'alert err', role: 'alert' }, msg);
}

export function download(blob, filename) {
  const url = URL.createObjectURL(blob);
  const a = h('a', { href: url, download: filename });
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function isTyping(target) {
  return target && ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName);
}

export function debounce(fn, ms) {
  let t;
  return (...a) => {
    clearTimeout(t);
    t = setTimeout(() => fn(...a), ms);
  };
}
