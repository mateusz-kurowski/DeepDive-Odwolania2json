import { api } from '../api.js';
import { h, clear, loading, badge, errorBox, progressBar, elapsed, pct, dur, debounce, download } from '../ui.js';

const FILTERS = [
  ['', 'Wszystkie'],
  ['needs_review', 'Wymaga przeglądu'],
  ['done', 'Gotowe'],
  ['processing', 'Przetwarzanie'],
  ['queued', 'W kolejce'],
  ['error', 'Błąd'],
];

function statusBadge(d) {
  if (d.status === 'done') return d.needs_review ? badge('Wymaga przeglądu', 'warn') : badge('Gotowe', 'ok');
  if (d.status === 'processing') return badge('Przetwarzanie', 'busy');
  if (d.status === 'queued') return badge('W kolejce', 'idle');
  return badge('Błąd', 'err');
}

export function mount(root, ctx) {
  ctx.title('Dokumenty');
  const st = { items: [], summary: null, q: '', filter: '', selected: new Set(), loaded: false, error: null };
  let timer = null;
  let dead = false;
  ctx.onCleanup(() => { dead = true; clearTimeout(timer); });

  const msg = h('div', { role: 'status', 'aria-live': 'polite' });
  const fileInput = h('input', {
    type: 'file', accept: 'application/pdf,.pdf', multiple: true, class: 'sr-only', id: 'file-input', tabindex: '-1', 'aria-label': 'Wybierz pliki PDF',
    onchange: () => { upload(fileInput.files); fileInput.value = ''; },
  });
  const demoBtn = h('button', { class: 'btn primary', type: 'button', onclick: loadDemo }, 'Załaduj dokument demo');
  const drop = h('section', { class: 'drop', 'aria-label': 'Dodawanie dokumentów' },
    h('div', null,
      h('div', { class: 't' }, 'Przeciągnij pliki PDF z orzeczeniami KIO'),
      h('div', { class: 's' }, 'Wiele plików naraz. Skany przejdą przez OCR. „Dokument demo” otwiera gotowy, przetworzony dokument bez czekania na model.')),
    h('div', { class: 'btn-row' },
      demoBtn,
      h('button', { class: 'btn', type: 'button', onclick: () => fileInput.click() }, 'Wybierz pliki'),
      h('button', { class: 'btn subtle', type: 'button', onclick: loadSamples }, 'Przetwórz przykładowe orzeczenia (model)')),
    fileInput);
  drop.addEventListener('dragover', (e) => { e.preventDefault(); drop.classList.add('over'); });
  drop.addEventListener('dragleave', () => drop.classList.remove('over'));
  drop.addEventListener('drop', (e) => {
    e.preventDefault();
    drop.classList.remove('over');
    upload(e.dataTransfer.files);
  });

  const batchEl = h('div', { 'aria-live': 'polite' });
  const summaryEl = h('section', { class: 'stats', 'aria-label': 'Podsumowanie' });
  const tbodyHost = h('div', { class: 'table-wrap' });
  const exportBtns = ['json', 'jsonl', 'csv'].map((f) =>
    h('button', { class: 'btn small', type: 'button', 'data-fmt': f, onclick: () => exportSelected(f) }, f.toUpperCase()));
  const search = h('input', {
    type: 'search', id: 'doc-q', placeholder: 'Sygnatura lub nazwa pliku', style: 'width:260px',
    oninput: debounce(() => { st.q = search.value.trim(); load(); }, 300),
  });
  const filter = h('select', { id: 'doc-filter', onchange: () => { st.filter = filter.value; load(); } },
    FILTERS.map(([v, l]) => h('option', { value: v }, l)));
  const exportLabel = h('span', { class: 'muted', style: 'font-size:14px' }, 'Eksport zaznaczonych:');
  const listCard = h('section', { class: 'card', 'aria-label': 'Lista dokumentów' },
    h('div', { class: 'toolbar' },
      h('label', { class: 'field', for: 'doc-q' }, 'Szukaj', search),
      h('label', { class: 'field', for: 'doc-filter' }, 'Status', filter),
      h('span', { class: 'spacer' }), exportLabel, exportBtns),
    tbodyHost);

  clear(root, h('div', { class: 'content' }, drop, msg, batchEl, summaryEl, listCard));

  function say(text, err = false) {
    clear(msg, text ? (err ? errorBox(text) : h('div', { class: 'alert info' }, text)) : null);
  }

  async function load() {
    try {
      const qs = new URLSearchParams();
      if (st.q) qs.set('q', st.q);
      if (st.filter === 'needs_review') qs.set('needs_review', 'true');
      else if (st.filter) qs.set('status', st.filter);
      const r = await api.get('/documents?' + qs);
      if (dead) return;
      st.items = r.items;
      st.summary = r.summary;
      st.error = null;
      const ids = new Set(st.items.map((i) => i.id));
      for (const id of [...st.selected]) if (!ids.has(id)) st.selected.delete(id);
    } catch (e) {
      if (dead) return;
      st.error = e.message;
    }
    st.loaded = true;
    renderSummary();
    renderBatch();
    renderTable();
    clearTimeout(timer);
    if ((st.summary && st.summary.active > 0) || st.items.some((i) => i.status === 'queued' || i.status === 'processing')) {
      timer = setTimeout(load, 2000);
    }
  }

  function renderBatch() {
    // liczby z podsumowania API (dla całego zbioru, niezależnie od filtra i wyszukiwarki na liście)
    const s = st.summary;
    if (!s || !s.active) return clear(batchEl);
    const total = s.total;
    const done = s.processed;
    clear(batchEl, h('div', { class: 'batch' },
      h('div', { class: 'row' },
        h('b', null, `Ekstrakcja w toku: ${done} z ${total} dokumentów przetworzonych`),
        h('span', { class: 'muted' }, `${s.active} w toku${s.failed ? ` · ${s.failed} z błędem` : ''}`)),
      h('div', { class: 'progress tall', role: 'progressbar', 'aria-label': 'Postęp ekstrakcji', 'aria-valuemin': '0', 'aria-valuemax': String(total), 'aria-valuenow': String(done) },
        h('div', { style: `width:${Math.round((done / total) * 100)}%` }))));
  }

  function renderSummary() {
    const s = st.summary;
    const card = (k, v) => h('div', { class: 'stat' }, h('div', { class: 'k' }, k), h('div', { class: 'v' }, v));
    clear(summaryEl,
      card('Przetworzone', s ? `${s.processed} z ${s.total}` : '—'),
      card('Wymaga przeglądu', s ? pct(s.needs_review_rate, 0) : '—'),
      card('Zgodność cytatów', s ? pct(s.avg_citation_ok_rate, 0) : '—'),
      card('Średni czas', s ? dur(s.avg_duration_s) : '—'));
  }

  function renderTable() {
    exportBtns.forEach((b) => { b.disabled = st.selected.size === 0; });
    if (st.error) return clear(tbodyHost, errorBox(st.error, () => { st.loaded = false; renderTable(); load(); }));
    if (!st.loaded) return clear(tbodyHost, loading('Ładowanie…'));
    if (!st.items.length) {
      return clear(tbodyHost, h('div', { class: 'empty' },
        st.q || st.filter ? 'Brak dokumentów spełniających kryteria.' : 'Brak dokumentów. Dodaj pliki PDF albo użyj przykładowych orzeczeń KIO.'));
    }
    const all = st.items.every((i) => st.selected.has(i.id));
    const head = h('tr', null,
      h('th', { scope: 'col' }, h('input', {
        type: 'checkbox', 'aria-label': 'Zaznacz wszystkie', checked: all,
        onchange: (e) => {
          if (e.target.checked) st.items.forEach((i) => st.selected.add(i.id)); else st.selected.clear();
          renderTable();
        },
      })),
      ['Plik', 'Sygnatura', 'Typ', 'Status', 'Zgodność cytatów', 'Czas', 'Akcje'].map((t) => h('th', { scope: 'col' }, t)));
    const rows = st.items.map((d) => h('tr', { class: st.selected.has(d.id) ? 'selected' : null },
      h('td', null, h('input', {
        type: 'checkbox', 'aria-label': `Zaznacz ${d.filename}`, checked: st.selected.has(d.id),
        onchange: (e) => { if (e.target.checked) st.selected.add(d.id); else st.selected.delete(d.id); renderTable(); },
      })),
      h('td', null, d.filename),
      h('td', { style: 'font-weight:600' }, d.label && d.label !== d.filename ? d.label : '—'),
      h('td', null, d.class_name || '—'),
      h('td', null, statusBadge(d),
        d.status === 'processing' ? h('div', { style: 'margin-top:6px;min-width:140px' }, progressBar({ label: `Przetwarzanie ${d.filename}` }), h('div', { class: 'muted', style: 'font-size:13px;margin-top:2px' }, `trwa ${elapsed(d.created_at) || '…'}`)) : null,
        d.error ? h('div', { class: 'muted', style: 'font-size:13px;margin-top:4px' }, d.error) : null),
      h('td', null, pct(d.citation_ok_rate, 0)),
      h('td', { class: 'muted' }, dur(d.duration_s)),
      h('td', null, h('div', { class: 'btn-row', style: 'gap:6px' }, actions(d)))));
    clear(tbodyHost, h('table', null, h('thead', null, head), h('tbody', null, rows)));
  }

  function actions(d) {
    const out = [];
    if (d.status === 'error') {
      out.push(h('button', { class: 'btn small', type: 'button', onclick: () => reprocess(d) }, 'Ponów'));
    } else {
      const label = d.status === 'done' ? (d.needs_review ? 'Przejrzyj' : 'Otwórz') : 'Podgląd';
      out.push(h('a', { class: 'btn small', href: `#/documents/${encodeURIComponent(d.id)}`, style: 'text-decoration:none;display:inline-flex;align-items:center' }, label));
    }
    out.push(h('button', { class: 'btn small danger', type: 'button', 'aria-label': `Usuń ${d.filename}`, onclick: () => remove(d) }, 'Usuń'));
    return out;
  }

  async function upload(fileList) {
    const files = [...fileList];
    const pdfs = files.filter((f) => /\.pdf$/i.test(f.name) || f.type === 'application/pdf');
    if (!pdfs.length) return say('Wybierz pliki PDF.', true);
    const fd = new FormData();
    pdfs.forEach((f) => fd.append('files', f));
    say(`Wysyłanie ${pdfs.length} plików…`);
    try {
      await api.post('/documents', fd);
      say(`Dodano ${pdfs.length} plików do przetwarzania.${pdfs.length < files.length ? ' Pominięto pliki inne niż PDF.' : ''}`);
    } catch (e) {
      say(e.message, true);
    }
    await load();
  }

  async function loadDemo() {
    demoBtn.disabled = true;
    say('Ładowanie dokumentu demo…');
    try {
      const r = await api.post('/documents/demo');
      location.hash = `#/documents/${encodeURIComponent(r[0].id)}`;
      return;
    } catch (e) {
      say(e.message, true);
      demoBtn.disabled = false;
    }
  }

  async function loadSamples() {
    say('Dodawanie przykładowych orzeczeń…');
    try {
      const r = await api.post('/documents/samples');
      say(`Dodano ${r.length} przykładowych dokumentów.`);
    } catch (e) {
      say(e.message, true);
    }
    await load();
  }

  async function reprocess(d) {
    try { await api.post(`/documents/${d.id}/reprocess`); say(`Ponowne przetwarzanie: ${d.filename}`); } catch (e) { say(e.message, true); }
    await load();
  }

  async function remove(d) {
    if (!confirm(`Usunąć dokument „${d.filename}”?`)) return;
    try { await api.del(`/documents/${d.id}`); say(`Usunięto: ${d.filename}`); } catch (e) { say(e.message, true); }
    await load();
  }

  async function exportSelected(format) {
    try {
      const { blob, filename } = await api.blob('/documents/export', { ids: [...st.selected], format });
      download(blob, filename || `dokumenty.${format}`);
    } catch (e) {
      say(e.message, true);
    }
  }

  renderSummary();
  renderTable();
  load();
}
