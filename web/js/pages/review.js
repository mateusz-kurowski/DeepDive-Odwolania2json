import { api } from '../api.js';
import { h, clear, badge, errorBox, dur, show, isTyping, download } from '../ui.js';

const BASE_W = 640;

function typedValue(text, original) {
  const t = text.trim();
  if (t === '') return null;
  if (typeof original === 'number') {
    const n = Number(t.replace(',', '.'));
    if (!Number.isNaN(n)) return n;
  }
  return text;
}

export function mount(root, ctx) {
  const id = ctx.params[0];
  const st = { doc: null, page: 1, zoom: 1, active: null, editing: null, json: false, error: null, busy: false };
  let timer = null;
  let dead = false;
  ctx.onCleanup(() => {
    dead = true;
    clearTimeout(timer);
    document.removeEventListener('keydown', onKey);
  });
  document.addEventListener('keydown', onKey);

  ctx.header(h('div', { class: 'crumbs' }, h('a', { href: '#/documents' }, 'Dokumenty'), ' / ', h('b', null, '…')));
  const metaEl = h('section', { class: 'docmeta', 'aria-label': 'Metadane dokumentu' });
  const viewerEl = h('section', { class: 'viewer', 'aria-label': 'Podgląd PDF' });
  const fieldsEl = h('section', { class: 'fields', 'aria-label': 'Wyodrębnione pola' });
  const msg = h('div', { role: 'status', 'aria-live': 'polite', style: 'padding:0 24px' });
  clear(root, metaEl, msg, h('div', { class: 'split' }, viewerEl, fieldsEl));
  clear(metaEl, h('div', { class: 'loading' }, 'Ładowanie…'));

  const fields = () => (st.doc && st.doc.fields) || [];
  const activeField = () => fields().find((f) => f.path === st.active) || null;

  async function load(quiet = false) {
    try {
      const d = await api.get(`/documents/${id}`);
      if (dead) return;
      st.doc = d;
      st.error = null;
      if (!st.active || !fields().some((f) => f.path === st.active)) st.active = fields()[0]?.path ?? null;
      if (st.page > (d.pages || 1)) st.page = 1;
    } catch (e) {
      if (dead) return;
      st.error = e.message;
    }
    renderAll();
    clearTimeout(timer);
    if (st.doc && (st.doc.status === 'queued' || st.doc.status === 'processing')) timer = setTimeout(() => load(true), 2000);
    void quiet;
  }

  function say(text, err = false) {
    clear(msg, text ? (err ? errorBox(text) : null) : null);
  }

  function renderAll() {
    const label = st.doc ? st.doc.label || st.doc.filename : '…';
    ctx.header(h('div', { class: 'crumbs' }, h('a', { href: '#/documents' }, 'Dokumenty'), ' / ', h('b', null, label)));
    document.title = `${label} · Odwołania2JSON`;
    renderMeta();
    renderViewer();
    renderFields();
  }

  function renderMeta() {
    if (st.error && !st.doc) return clear(metaEl, errorBox(st.error));
    const d = st.doc;
    if (!d) return;
    const approved = fields().filter((f) => f.status === 'approved').length;
    const ready = d.status === 'done';
    clear(metaEl,
      h('div', null,
        h('div', { style: 'display:flex;align-items:baseline;gap:12px;flex-wrap:wrap' },
          h('h1', null, d.label || d.filename),
          h('span', { class: 'muted' }, d.filename)),
        h('div', { class: 'chips' },
          d.class_name ? h('span', { class: 'pill navy' }, d.class_name) : null,
          d.model ? h('span', { class: 'pill' }, `Model: ${d.model}`) : null,
          d.duration_s != null ? h('span', { class: 'pill' }, `Czas: ${dur(d.duration_s)}`) : null,
          d.ocr_used ? h('span', { class: 'pill' }, 'OCR') : null,
          d.status !== 'done' ? badge(d.status === 'error' ? 'Błąd' : 'Przetwarzanie…', d.status === 'error' ? 'err' : 'busy') : null)),
      h('div', { class: 'btn-row' },
        h('span', { 'aria-live': 'polite', style: 'font-size:15px;color:#334155;margin-right:8px' },
          h('b', null, approved), ` z ${fields().length} pól zatwierdzonych`),
        h('button', { class: 'btn', type: 'button', onclick: toggleJson }, st.json ? 'Widok pól' : 'Widok JSON'),
        h('button', { class: 'btn primary', type: 'button', disabled: !ready || !fields().length, onclick: approveAll }, 'Zatwierdź wszystko'),
        h('button', { class: 'btn subtle', type: 'button', disabled: !ready, onclick: exportJson }, 'Pobierz JSON po korektach')));
    if (d.error) clear(msg, errorBox(d.error));
  }

  function renderViewer() {
    const d = st.doc;
    if (!d) return clear(viewerEl);
    const pages = d.pages || 0;
    const w = Math.round(BASE_W * st.zoom);
    const reqW = Math.min(2000, Math.round(w * (window.devicePixelRatio > 1 ? 1.5 : 1)));
    const hls = fields().flatMap((f) =>
      (f.highlights || []).filter((x) => x.page === st.page).map((x) => ({ f, x })));
    const pageEl = pages
      ? h('div', { class: 'page', style: `width:${w}px` },
          h('img', { src: `/api/documents/${id}/pages/${st.page}.png?width=${reqW}`, alt: `Strona ${st.page} dokumentu ${d.filename}` }),
          hls.map(({ f, x }) =>
            h('button', {
              type: 'button', class: 'hl' + (f.path === st.active ? ' active' : ''), 'aria-label': `Pole: ${f.label}`,
              style: `left:${x.x * 100}%;top:${x.y * 100}%;width:${x.w * 100}%;height:${x.h * 100}%`,
              onclick: () => select(f.path, false),
            })))
      : h('div', { class: 'empty' }, d.status === 'done' ? 'Brak podglądu strony.' : 'Dokument jest jeszcze przetwarzany.');
    const thumbs = Array.from({ length: pages }, (_, i) => i + 1).map((n) =>
      h('button', {
        type: 'button', class: 'thumb', 'aria-label': `Strona ${n}`, 'aria-current': n === st.page ? 'true' : null,
        onclick: () => { st.page = n; renderViewer(); },
      }, h('img', { src: `/api/documents/${id}/pages/${n}.png?width=120`, alt: '', loading: 'lazy' }), h('span', null, n)));
    clear(viewerEl,
      h('div', { class: 'vbar' },
        h('button', { class: 'iconbtn', type: 'button', 'aria-label': 'Poprzednia strona', disabled: st.page <= 1, onclick: () => { st.page--; renderViewer(); } }, '‹'),
        h('span', null, 'Strona ', h('b', null, st.page), ` z ${pages || '—'}`),
        h('button', { class: 'iconbtn', type: 'button', 'aria-label': 'Następna strona', disabled: st.page >= pages, onclick: () => { st.page++; renderViewer(); } }, '›'),
        h('span', { class: 'spacer' }),
        h('button', { class: 'iconbtn', type: 'button', 'aria-label': 'Pomniejsz', disabled: st.zoom <= 0.5, onclick: () => { st.zoom = Math.max(0.5, st.zoom - 0.25); renderViewer(); } }, '−'),
        h('span', null, `${Math.round(st.zoom * 100)} %`),
        h('button', { class: 'iconbtn', type: 'button', 'aria-label': 'Powiększ', disabled: st.zoom >= 2.5, onclick: () => { st.zoom = Math.min(2.5, st.zoom + 0.25); renderViewer(); } }, '+')),
      h('div', { class: 'vbody' },
        pages > 1 ? h('div', { class: 'thumbs', role: 'group', 'aria-label': 'Miniatury stron' }, thumbs) : null,
        h('div', { class: 'pagescroll' }, pageEl)));
  }

  function fieldStatus(f) {
    if (f.status === 'approved') return badge('Zatwierdzone', 'ok');
    if (f.status === 'edited') return badge('Poprawione', 'busy');
    return badge('AI', 'outline');
  }
  function citeBadge(f) {
    if (f.citation_ok === true) return badge('Cytat zweryfikowany', 'ok');
    if (f.citation_ok === false) return badge('Cytat niezweryfikowany', 'warn');
    return null;
  }

  function renderFields() {
    if (!st.doc) return clear(fieldsEl);
    if (st.json) {
      return clear(fieldsEl, h('pre', { class: 'jsonview', style: 'margin:0', tabindex: '0', 'aria-label': 'JSON dokumentu' }, JSON.stringify(st.doc.data ?? {}, null, 2)));
    }
    if (st.doc.status !== 'done') {
      return clear(fieldsEl, h('div', { class: 'loading' }, st.doc.status === 'error' ? 'Przetwarzanie nie powiodło się.' : 'Trwa przetwarzanie…'));
    }
    if (!fields().length) {
      return clear(fieldsEl, h('div', { class: 'empty' }, 'Brak wyodrębnionych pól (dokument spoza znanych klas).'));
    }
    const out = [];
    let section = Symbol();
    for (const f of fields()) {
      const sec = f.section || null;
      if (sec !== section) {
        section = sec;
        if (sec) out.push(h('h2', null, sec));
      }
      out.push(fieldRow(f));
    }
    out.push(h('div', { class: 'keys' }, h('b', null, 'Skróty:'), ' J / K – następne / poprzednie pole · A – zatwierdź · E – edytuj · Esc – anuluj edycję'));
    clear(fieldsEl, out);
    const input = fieldsEl.querySelector('[data-edit]');
    if (input) input.focus();
  }

  function fieldRow(f) {
    const active = f.path === st.active;
    const children = [
      h('div', { class: 'head' },
        h('span', { class: 'lbl' }, f.label),
        h('span', { style: 'display:flex;gap:6px;align-items:center;flex-wrap:wrap' }, citeBadge(f), fieldStatus(f))),
    ];
    if (st.editing === f.path) {
      const long = typeof f.value === 'string' && f.value.length > 60;
      const input = long
        ? h('textarea', { 'data-edit': '1', rows: '4', 'aria-label': `Wartość: ${f.label}`, value: f.value ?? '' })
        : h('input', { 'data-edit': '1', type: 'text', 'aria-label': `Wartość: ${f.label}`, value: f.value == null ? '' : String(f.value) });
      const save = () => saveEdit(f, input.value);
      input.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') { e.stopPropagation(); st.editing = null; renderFields(); }
        else if (e.key === 'Enter' && (!long || e.ctrlKey || e.metaKey)) { e.preventDefault(); save(); }
      });
      children.push(input,
        h('div', { class: 'btn-row' },
          h('button', { class: 'btn primary small', type: 'button', onclick: save }, 'Zapisz'),
          h('button', { class: 'btn small', type: 'button', onclick: () => { st.editing = null; renderFields(); } }, 'Anuluj')));
    } else {
      children.push(h('button', {
        type: 'button', class: 'fval' + (f.value == null || f.value === '' ? ' null' : ''),
        'aria-label': `${f.label}: ${show(f.value)}. Wybierz pole`,
        onclick: () => select(f.path, true),
      }, show(f.value)));
    }
    if (active && st.editing !== f.path) {
      const page = f.highlights && f.highlights[0] ? f.highlights[0].page : null;
      if (f.quote) {
        children.push(h('div', { class: 'quote' },
          h('div', { class: 'q' }, 'Cytat ze źródła' + (page ? ` · s. ${page}` : '')), `„${f.quote}”`));
      } else {
        children.push(h('div', { class: 'muted', style: 'font-size:14px' }, 'Brak cytatu źródłowego dla tego pola.'));
      }
      children.push(h('div', { class: 'btn-row' },
        h('button', { class: 'btn primary small', type: 'button', onclick: () => toggleApprove(f) }, f.status === 'approved' ? 'Cofnij zatwierdzenie' : 'Zatwierdź (A)'),
        h('button', { class: 'btn small', type: 'button', onclick: () => startEdit(f) }, 'Edytuj (E)'),
        f.status !== 'ai' && f.status !== 'approved'
          ? h('button', { class: 'btn small subtle', type: 'button', onclick: () => patch(f, { revert: true }) }, 'Cofnij') : null));
    }
    return h('div', { class: 'frow' + (active ? ' active' : ''), 'data-path': f.path }, children);
  }

  function select(path, jump = true) {
    st.active = path;
    st.editing = null;
    const f = activeField();
    if (jump && f && f.highlights && f.highlights[0]) st.page = f.highlights[0].page;
    renderViewer();
    renderFields();
    const el = fieldsEl.querySelector(`[data-path="${CSS.escape(path)}"]`);
    if (el) el.scrollIntoView({ block: 'nearest' });
  }

  function startEdit(f) { st.editing = f.path; st.active = f.path; renderFields(); }

  async function patch(f, body) {
    try {
      const upd = await api.patch(`/documents/${id}/fields`, { path: f.path, ...body });
      const i = st.doc.fields.findIndex((x) => x.path === f.path);
      if (i >= 0) st.doc.fields[i] = upd;
      st.editing = null;
      say('');
    } catch (e) {
      say(e.message, true);
    }
    renderMeta();
    renderViewer();
    renderFields();
  }

  const toggleApprove = (f) => patch(f, { status: f.status === 'approved' ? 'ai' : 'approved' });
  const saveEdit = (f, text) => patch(f, { value: typedValue(text, f.value) });

  async function approveAll() {
    try {
      await api.post(`/documents/${id}/approve-all`);
      say('');
    } catch (e) {
      say(e.message, true);
    }
    await load(true);
  }

  async function toggleJson() {
    st.json = !st.json;
    if (st.json) await load(true); else renderAll();
  }

  async function exportJson() {
    try {
      const { blob, filename } = await api.blob(`/documents/${id}/export`);
      download(blob, filename || `${(st.doc.filename || 'dokument').replace(/\.pdf$/i, '')}.json`);
    } catch (e) {
      say(e.message, true);
    }
  }

  function onKey(e) {
    if (e.ctrlKey || e.metaKey || e.altKey || isTyping(e.target) || st.json || !st.doc) return;
    const list = fields();
    const i = list.findIndex((f) => f.path === st.active);
    const key = e.key.toLowerCase();
    if (key === 'j' && i < list.length - 1) { e.preventDefault(); select(list[i + 1].path); }
    else if (key === 'k' && i > 0) { e.preventDefault(); select(list[i - 1].path); }
    else if (key === 'a' && list[i]) { e.preventDefault(); toggleApprove(list[i]); }
    else if (key === 'e' && list[i]) { e.preventDefault(); startEdit(list[i]); }
  }

  load();
}
