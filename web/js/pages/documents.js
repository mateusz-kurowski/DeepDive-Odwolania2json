import { api } from '../api.js';
import { h, clear, badge, errorBox, pct, dur, debounce, download } from '../ui.js';

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
    type: 'file', accept: 'application/pdf,.pdf', multiple: true, class: 'sr-only', id: 'file-input', tabindex: '-1',
    onchange: () => { upload(fileInput.files); fileInput.value = ''; },
  });
  const drop = h('section', { class: 'drop', 'aria-label': 'Dodawanie dokumentów' },
    h('div', null,
      h('div', { class: 't' }, 'Przeciągnij pliki PDF z orzeczeniami KIO'),
      h('div', { class: 's' }, 'Wiele plików naraz. Skany przejdą przez OCR.')),
    h('div', { class: 'btn-row' },
      h('button', { class: 'btn primary', type: 'button', onclick: () => fileInput.click() }, 'Wybierz pliki'),
      h('button', { class: 'btn', type: 'button', onclick: loadSamples }, 'Użyj przykładowych orzeczeń KIO')),
    fileInput);
  drop.addEventListener('dragover', (e) => { e.preventDefault(); drop.classList.add('over'); });
  drop.addEventListener('dragleave', () => drop.classList.remove('over'));
  drop.addEventListener('drop', (e) => {
    e.preventDefault();
    drop.classList.remove('over');
    upload(e.dataTransfer.files);
  });

  const summaryEl = h('section', { class: 'stats', 'aria-label': 'Podsumowanie' });
  const tbodyHost = h('div', { class: 'table-wrap' });
  const exportBtns = ['json', 'jsonl', 'csv'].map((f) =>
    h('button', { class: 'btn small', type: 'button', 'data-fmt': f, onclick: () => exportSelected(f) }, f.toUpperCase()));
  const search = h('input', {
    type: 'search', id: 'doc-q', class: 'search', placeholder: 'Nazwa pliku',
    oninput: debounce(() => { st.q = search.value.trim(); load(); }, 300),
  });
  const filter = h('select', { id: 'doc-filter', onchange: () => { st.filter = filter.value; load(); } },
    FILTERS.map(([v, l]) => h('option', { value: v }, l)));
  const exportLabel = h('span', { class: 'lbl' });
  const exportBox = h('div', { class: 'export', role: 'group', 'aria-label': 'Eksport zaznaczonych' }, exportLabel, exportBtns);
  const listCard = h('section', { class: 'card', 'aria-label': 'Lista dokumentów' },
    h('div', { class: 'toolbar' },
      h('label', { class: 'field', for: 'doc-q' }, 'Szukaj', search),
      h('label', { class: 'field', for: 'doc-filter' }, 'Status', filter),
      h('span', { class: 'spacer' }), exportBox),
    tbodyHost);

  clear(root, h('div', { class: 'content' }, drop, msg, summaryEl, listCard));

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
    renderTable();
    clearTimeout(timer);
    if (st.items.some((i) => i.status === 'queued' || i.status === 'processing')) {
      timer = setTimeout(load, 2000);
    }
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
    exportBox.hidden = st.selected.size === 0;
    exportLabel.textContent = `Eksport zaznaczonych (${st.selected.size}):`;
    if (st.error) return clear(tbodyHost, errorBox(st.error));
    if (!st.loaded) return clear(tbodyHost, h('div', { class: 'loading' }, 'Ładowanie…'));
    if (!st.items.length) {
      return clear(tbodyHost, h('div', { class: 'empty' },
        st.q || st.filter ? 'Brak dokumentów spełniających kryteria.' : 'Brak dokumentów. Dodaj pliki PDF, aby rozpocząć.'));
    }
    const all = st.items.every((i) => st.selected.has(i.id));
    const head = h('tr', null,
      h('th', null, h('input', {
        type: 'checkbox', 'aria-label': 'Zaznacz wszystkie', checked: all,
        onchange: (e) => {
          if (e.target.checked) st.items.forEach((i) => st.selected.add(i.id)); else st.selected.clear();
          renderTable();
        },
      })),
      ['Plik', 'Status', 'Typ', 'Zgodność cytatów', 'Czas'].map((t) => h('th', null, t)),
      h('th', null, h('span', { class: 'sr-only' }, 'Akcje')));
    const rows = st.items.map((d) => h('tr', { class: st.selected.has(d.id) ? 'selected' : null },
      h('td', null, h('input', {
        type: 'checkbox', 'aria-label': `Zaznacz ${d.filename}`, checked: st.selected.has(d.id),
        onchange: (e) => { if (e.target.checked) st.selected.add(d.id); else st.selected.delete(d.id); renderTable(); },
      })),
      h('td', { class: 'c-file' }, d.filename),
      h('td', { class: 'c-status' }, statusBadge(d), d.error ? h('div', { class: 'sub' }, d.error) : null),
      h('td', { class: 'c-meta', 'data-label': 'Typ' }, d.class_name || '—'),
      h('td', { class: 'c-meta num', 'data-label': 'Cytaty' }, pct(d.citation_ok_rate, 0)),
      h('td', { class: 'c-meta num muted', 'data-label': 'Czas' }, dur(d.duration_s)),
      h('td', { class: 'c-actions' }, h('div', { class: 'btn-row', style: 'gap:6px' }, actions(d)))));
    clear(tbodyHost, h('table', { class: 'doctable' }, h('thead', null, head), h('tbody', null, rows)));
  }

  function actions(d) {
    const out = [];
    if (d.status === 'error') {
      out.push(h('button', { class: 'btn small', type: 'button', onclick: () => reprocess(d) }, 'Ponów'));
    } else {
      const label = d.status === 'done' ? (d.needs_review ? 'Przejrzyj' : 'Otwórz') : 'Podgląd';
      out.push(h('a', { class: 'btn small', href: `#/documents/${encodeURIComponent(d.id)}` }, label));
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
