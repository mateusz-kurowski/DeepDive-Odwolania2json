import { h, clear } from './ui.js';
import * as documents from './pages/documents.js';
import * as review from './pages/review.js';
import * as schemas from './pages/schemas.js';
import * as evaluation from './pages/evaluation.js';
import * as settings from './pages/settings.js';

const NAV = [
  ['documents', 'Dokumenty', '#/documents'],
  ['schemas', 'Schematy', '#/schemas'],
  ['evaluation', 'Ewaluacja', '#/evaluation'],
  ['settings', 'Ustawienia', '#/settings'],
];

const ROUTES = [
  [/^#\/documents\/([^/]+)$/, review, 'documents'],
  [/^#\/documents\/?$/, documents, 'documents'],
  [/^#\/schemas(?:\/([^/]+))?$/, schemas, 'schemas'],
  [/^#\/evaluation(?:\/([^/]+))?$/, evaluation, 'evaluation'],
  [/^#\/settings\/?$/, settings, 'settings'],
];

const nav = h('nav', { class: 'nav', 'aria-label': 'Główna nawigacja' });
const topbar = h('header', { class: 'topbar' });
const view = h('main', { id: 'view', tabindex: '-1' });
document.getElementById('app').append(
  h('div', { class: 'layout' }, nav, h('div', { class: 'main-col' }, topbar, view)),
);

let cleanups = [];

function renderNav(active) {
  clear(
    nav,
    h('div', { class: 'brand' }, h('b', null, 'Odwołania2JSON'), h('span', null, 'Analiza orzeczeń KIO')),
    NAV.map(([key, label, href]) =>
      h('a', { href, 'aria-current': key === active ? 'page' : null }, label),
    ),
    h('div', { class: 'nav-foot' }, 'Przetwarzanie przez skonfigurowany endpoint API'),
  );
}

function route() {
  cleanups.forEach((fn) => { try { fn(); } catch { /* pomijamy */ } });
  cleanups = [];
  const hash = location.hash || '#/documents';
  let matched = null;
  for (const [re, page, key] of ROUTES) {
    const m = re.exec(hash);
    if (m) { matched = { page, key, params: m.slice(1).map((x) => (x ? decodeURIComponent(x) : x)) }; break; }
  }
  if (!matched) { location.hash = '#/documents'; return; }
  renderNav(matched.key);
  clear(topbar);
  clear(view);
  const ctx = {
    params: matched.params,
    onCleanup: (fn) => cleanups.push(fn),
    header: (...kids) => clear(topbar, ...kids),
    title: (text) => { clear(topbar, h('h1', null, text)); document.title = `${text} · Odwołania2JSON`; },
  };
  matched.page.mount(view, ctx);
  window.scrollTo(0, 0);
}

window.addEventListener('hashchange', route);
route();
