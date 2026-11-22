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

export function errorBox(msg, onRetry) {
  return h('div', { class: 'alert err', role: 'alert' },
    h('span', null, msg),
    onRetry ? h('button', { class: 'btn small', type: 'button', onclick: onRetry }, 'Spróbuj ponownie') : null);
}

export function loading(text = 'Ładowanie…') {
  return h('div', { class: 'loading', role: 'status' }, h('span', { class: 'spinner', 'aria-hidden': 'true' }), text);
}

/** Pasek postępu. Bez `max` = nieokreślony (tryb „trwa przetwarzanie”). */
export function progressBar({ value, max, label }) {
  const det = max > 0;
  const attrs = { class: 'progress' + (det ? '' : ' indeterminate'), role: 'progressbar', 'aria-label': label };
  if (det) Object.assign(attrs, { 'aria-valuemin': '0', 'aria-valuemax': String(max), 'aria-valuenow': String(value) });
  return h('div', attrs, h('div', { style: det ? `width:${Math.round((value / max) * 100)}%` : null }));
}

export function elapsed(iso) {
  const t = iso ? Date.parse(iso) : NaN;
  if (isNaN(t)) return null;
  const s = Math.max(0, Math.round((Date.now() - t) / 1000));
  return s < 60 ? `${s} s` : `${Math.floor(s / 60)} min ${String(s % 60).padStart(2, '0')} s`;
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
