import { api } from '../api.js';
import { h, clear, badge, errorBox, pct, num, dt, show } from '../ui.js';

const STATUS = { running: ['W toku', 'busy'], done: ['Zakończony', 'ok'], error: ['Błąd', 'err'] };
const DIFF_KIND = { TP: 'ok', FP: 'err', FN: 'warn' };

// Model z rozmiarem w mld parametrów (z config/models.yaml), np. „ministral-14b · 14B”.
function modelLabel(r) {
  if (!r.model) return null;
  return r.model_params_b != null ? `${r.model} · ${r.model_params_b}B` : `${r.model} · ?B`;
}

function runLabel(r) {
  return r.name || r.id;
}

const COLS = [
  ['Przebieg', (r) => runLabel(r)], ['Źródło', (r) => r.source], ['Zbiór', (r) => r.dataset], ['Model', (r) => modelLabel(r)],
  ['Tryb', (r) => r.mode], ['Status', (r) => r.status], ['F1', (r) => r.micro_f1], ['P', (r) => r.precision],
  ['R', (r) => r.recall], ['Dok.', (r) => r.docs], ['Błędy', (r) => r.errors], ['Start', (r) => r.started_at],
];

function sortRuns(runs, sort) {
  const get = COLS[sort.col][1];
  const dir = sort.dir === 'asc' ? 1 : -1;
  return runs.slice().sort((a, b) => {
    const x = get(a), y = get(b);
    const xn = x == null || x === '', yn = y == null || y === '';
    if (xn || yn) return xn === yn ? 0 : xn ? 1 : -1; // puste zawsze na końcu
    const c = typeof x === 'number' && typeof y === 'number' ? x - y : String(x).localeCompare(String(y), 'pl', { numeric: true });
    return c * dir;
  });
}

export function mount(root, ctx) {
  ctx.title('Ewaluacja');
  const st = {
    runs: [], datasets: [], settings: null, selectedId: ctx.params[0] || null, detail: null, docs: null,
    sort: { col: 6, dir: 'desc' }, diff: null, diffKey: null, onlyErrors: true, compare: new Set(), compareData: {}, listError: null, loaded: false,
  };
  let timer = null;
  let dead = false;
  ctx.onCleanup(() => { dead = true; clearTimeout(timer); });

  const formEl = h('section', { class: 'card', 'aria-label': 'Uruchom ewaluację' });
  const runsEl = h('section', { class: 'card', 'aria-label': 'Przebiegi ewaluacji' });
  const compareEl = h('section', { class: 'card', 'aria-label': 'Porównanie przebiegów', hidden: true });
  const detailEl = h('div', { style: 'display:flex;flex-direction:column;gap:20px' });
  const msg = h('div', { role: 'status', 'aria-live': 'polite' });
  clear(root, h('div', { class: 'content' }, msg, runsEl, compareEl, detailEl, formEl));

  /* ---------- lista przebiegów ---------- */
  async function loadRuns() {
    try {
      st.runs = await api.get('/evaluation/runs');
      st.listError = null;
    } catch (e) {
      st.listError = e.message;
    }
    st.loaded = true;
    if (dead) return;
    renderRuns();
    clearTimeout(timer);
    const running = st.runs.some((r) => r.status === 'running');
    if (running) {
      timer = setTimeout(async () => {
        await loadRuns();
        if (st.selectedId) await loadDetail(true);
      }, 2000);
    }
  }

  function renderRuns() {
    let body;
    if (st.listError) body = errorBox(st.listError);
    else if (!st.loaded) body = h('div', { class: 'loading' }, 'Ładowanie…');
    else if (!st.runs.length) body = h('div', { class: 'empty' }, 'Brak przebiegów. Uruchom ewaluację poniżej albo dodaj wyniki do katalogu results/.');
    else {
      body = h('div', { class: 'table-wrap' }, h('table', null,
        h('thead', null, h('tr', null,
          h('th', null, h('span', { class: 'sr-only' }, 'Porównaj')),
          COLS.map(([t], i) => {
            const active = st.sort.col === i;
            return h('th', { 'aria-sort': active ? (st.sort.dir === 'asc' ? 'ascending' : 'descending') : 'none' },
              h('button', {
                type: 'button', class: 'linklike', style: 'font:inherit;font-weight:inherit;color:inherit;text-decoration:none',
                onclick: () => { st.sort = { col: i, dir: active && st.sort.dir === 'desc' ? 'asc' : 'desc' }; renderRuns(); },
              }, t, h('span', { 'aria-hidden': 'true' }, active ? (st.sort.dir === 'asc' ? ' ▲' : ' ▼') : ' ↕')));
          }))),
        h('tbody', null, sortRuns(st.runs, st.sort).map((r) => {
          const [stText, stKind] = STATUS[r.status] || [r.status, 'idle'];
          return h('tr', { class: r.id === st.selectedId ? 'selected' : null },
            h('td', null, h('input', {
              type: 'checkbox', 'aria-label': `Porównaj ${runLabel(r)}`, checked: st.compare.has(r.id), disabled: r.status !== 'done',
              onchange: (e) => { if (e.target.checked) st.compare.add(r.id); else st.compare.delete(r.id); loadCompare(); },
            })),
            h('td', null, h('a', { href: `#/evaluation/${encodeURIComponent(r.id)}`, style: 'font-weight:600' }, runLabel(r))),
            h('td', null, badge(r.source === 'local' ? 'lokalny' : 'storage', r.source === 'local' ? 'idle' : 'busy')),
            h('td', null, r.dataset || '—'),
            h('td', null, modelLabel(r) || '—'),
            h('td', null, r.mode || '—'),
            h('td', null, badge(stText, stKind), r.status === 'running' && r.progress && r.progress.total
              ? h('div', { class: 'progress', role: 'progressbar', 'aria-label': 'Postęp ewaluacji', 'aria-valuemin': '0', 'aria-valuemax': String(r.progress.total), 'aria-valuenow': String(r.progress.done), style: 'margin-top:6px' },
                  h('div', { style: `width:${Math.round((r.progress.done / r.progress.total) * 100)}%` })) : null,
              r.error ? h('div', { class: 'muted', style: 'font-size:13px' }, r.error) : null),
            h('td', { style: 'font-weight:700' }, pct(r.micro_f1)),
            h('td', null, pct(r.precision)),
            h('td', null, pct(r.recall)),
            h('td', null, r.docs ?? '—'),
            h('td', null, r.errors ?? '—'),
            h('td', { class: 'muted' }, dt(r.started_at)));
        }))));
    }
    clear(runsEl, h('h2', null, 'Przebiegi ewaluacji'),
      h('p', { class: 'muted', style: 'margin:0 0 12px;font-size:14px' }, 'Wyniki lokalne (katalog results/) są tylko do odczytu; przebiegi uruchomione z UI zapisują się w object storage. Zaznacz co najmniej dwa, aby porównać pola.'),
      body);
  }

  /* ---------- porównanie ---------- */
  async function loadCompare() {
    const ids = [...st.compare];
    compareEl.hidden = ids.length < 2;
    if (ids.length < 2) return;
    clear(compareEl, h('h2', null, 'Porównanie przebiegów'), h('div', { class: 'loading' }, 'Ładowanie…'));
    try {
      await Promise.all(ids.filter((i) => !st.compareData[i]).map(async (i) => { st.compareData[i] = await api.get(`/evaluation/runs/${encodeURIComponent(i)}`); }));
    } catch (e) {
      return clear(compareEl, h('h2', null, 'Porównanie przebiegów'), errorBox(e.message));
    }
    if (dead) return;
    const runs = ids.map((i) => st.compareData[i]);
    const paths = [...new Set(runs.flatMap((r) => Object.keys((r.report && r.report.per_field) || {})))].sort();
    clear(compareEl, h('h2', null, 'Porównanie przebiegów (F1 według pola)'),
      h('div', { class: 'table-wrap scroll' }, h('table', null,
        h('thead', null, h('tr', null, h('th', null, 'Pole'), runs.map((r) => h('th', null, runLabel(r))))),
        h('tbody', null,
          h('tr', null, h('td', { style: 'font-weight:700' }, 'Micro-F1'), runs.map((r) => h('td', { style: 'font-weight:700' }, pct(r.micro_f1)))),
          paths.map((p) => h('tr', null, h('td', null, p), runs.map((r) => {
            const c = r.report && r.report.per_field[p];
            return h('td', null, c ? num(c.f1) : '—');
          })))))));
  }

  /* ---------- szczegóły przebiegu ---------- */
  async function loadDetail(quiet = false) {
    if (!st.selectedId) { clear(detailEl); return; }
    const id = st.selectedId;
    if (!quiet) clear(detailEl, h('div', { class: 'loading' }, 'Ładowanie…'));
    try {
      st.detail = await api.get(`/evaluation/runs/${encodeURIComponent(id)}`);
      if (st.detail.status === 'done' && (!st.docs || st.docsFor !== id)) {
        st.docs = await api.get(`/evaluation/runs/${encodeURIComponent(id)}/documents`);
        st.docsFor = id;
      }
    } catch (e) {
      st.detail = null;
      if (!dead) clear(detailEl, errorBox(e.message));
      return;
    }
    if (!dead) renderDetail();
  }

  function metric(k, v) {
    return h('div', { class: 'metric' }, h('div', { class: 'k' }, k), h('div', { class: 'v' }, v));
  }

  function renderDetail() {
    const d = st.detail;
    if (!d) return;
    const rep = d.report;
    const nodes = [];
    nodes.push(h('section', { class: 'card hero', 'aria-label': 'Wynik główny' },
      h('div', { style: 'display:flex;gap:28px;flex-wrap:wrap;align-items:center' },
        h('div', null,
          h('div', { style: 'font-size:14px;font-weight:600;color:var(--muted)' }, `Micro-F1 · ${runLabel(d)}`),
          h('div', { class: 'big' }, pct(d.micro_f1)),
          h('div', { class: 'muted', style: 'font-size:14px;margin-top:6px' },
            [d.dataset, modelLabel(d), d.mode, d.docs != null ? `${d.docs} dokumentów` : null].filter(Boolean).join(' · '))),
        h('div', { class: 'metrics' },
          metric('Precision', pct(d.precision)),
          metric('Recall', pct(d.recall)),
          rep && rep.doc_exact_match != null ? metric('Dokładne dopasowanie', pct(rep.doc_exact_match)) : null,
          rep && rep.classification_accuracy != null ? metric('Klasyfikacja', pct(rep.classification_accuracy)) : null,
          d.citation_ok_rate != null ? metric('Cytaty OK', pct(d.citation_ok_rate)) : null)),
      h('div', { style: 'max-width:300px' },
        badge((STATUS[d.status] || [d.status])[0], (STATUS[d.status] || [0, 'idle'])[1]),
        d.finished_at ? h('div', { class: 'muted', style: 'font-size:13px;margin-top:6px' }, `Zakończono: ${dt(d.finished_at)}`) : null,
        d.error ? h('div', { class: 'alert err', role: 'alert', style: 'margin-top:8px' }, d.error) : null,
        d.status === 'running' && d.progress ? h('div', { class: 'muted', style: 'font-size:14px;margin-top:6px' }, `Postęp: ${d.progress.done} z ${d.progress.total}`) : null)));

    if (rep && rep.per_field) {
      const rows = Object.entries(rep.per_field).sort((a, b) => a[1].f1 - b[1].f1);
      nodes.push(h('div', { class: 'grid2' },
        h('section', { class: 'card', 'aria-label': 'Wyniki według pola' },
          h('h2', null, 'Wyniki według pola'),
          h('div', { class: 'table-wrap scroll' }, h('table', null,
            h('thead', null, h('tr', null, ['Pole', 'P', 'R', 'F1', '', 'TP/FP/FN'].map((t, i) => h('th', null, i === 4 ? h('span', { class: 'sr-only' }, 'Wykres F1') : t)))),
            h('tbody', null, rows.map(([name, c]) => h('tr', null,
              h('td', { style: 'font-weight:600' }, name), h('td', null, num(c.precision)), h('td', null, num(c.recall)),
              h('td', { style: 'font-weight:700' }, num(c.f1)),
              h('td', { style: 'width:140px' }, h('div', { class: 'bar' + (c.f1 < 0.85 ? ' warn' : '') }, h('div', { style: `width:${Math.round(c.f1 * 100)}%` }))),
              h('td', { class: 'muted' }, `${c.tp}/${c.fp}/${c.fn}`))))))),
        docsSection()));
    } else if (d.status === 'done') {
      nodes.push(docsSection());
    }
    nodes.push(h('div', { id: 'diff-host' }, diffSection()));
    clear(detailEl, nodes);
  }

  function docsSection() {
    const docs = (st.docs || []).slice().sort((a, b) => (a.f1 ?? 2) - (b.f1 ?? 2));
    return h('section', { class: 'card', 'aria-label': 'Wyniki według dokumentu' },
      h('h2', null, 'Wyniki według dokumentu'),
      !docs.length ? h('div', { class: 'empty' }, 'Brak danych per dokument.') :
        h('div', { class: 'table-wrap scroll' }, h('table', null,
          h('thead', null, h('tr', null, ['Dokument', 'Klasa', 'TP', 'FP', 'FN', 'F1'].map((t) => h('th', null, t)))),
          h('tbody', null, docs.map((x) => {
            const key = `${x.label}/${x.stem}`;
            return h('tr', { class: key === st.diffKey ? 'selected' : null },
              h('td', null, h('button', { type: 'button', class: 'linklike', onclick: () => openDiff(x) }, `${x.label}/${x.stem}`),
                x.error ? h('div', { class: 'muted', style: 'font-size:13px' }, x.error) : null),
              h('td', null, x.class_name || '—'), h('td', null, x.tp), h('td', null, x.fp), h('td', null, x.fn),
              h('td', { style: 'font-weight:700' }, x.f1 == null ? '—' : num(x.f1)));
          })))));
  }

  async function openDiff(x) {
    st.diffKey = `${x.label}/${x.stem}`;
    st.diff = { loading: true };
    renderDetail();
    try {
      st.diff = await api.get(`/evaluation/runs/${encodeURIComponent(st.selectedId)}/documents/${encodeURIComponent(x.label)}/${encodeURIComponent(x.stem)}`);
    } catch (e) {
      st.diff = { failed: e.message };
    }
    if (!dead) {
      renderDetail();
      const el = detailEl.querySelector('#diff-host');
      if (el) el.scrollIntoView({ block: 'nearest' });
    }
  }

  function diffSection() {
    if (!st.diff) return null;
    if (st.diff.loading) return h('div', { class: 'loading' }, 'Ładowanie różnic…');
    if (st.diff.failed) return errorBox(st.diff.failed);
    const diffs = (st.diff.diffs || []).filter((x) => !st.onlyErrors || x.status !== 'TP');
    return h('section', { class: 'card', 'aria-label': 'Różnice dla dokumentu' },
      h('div', { class: 'toolbar', style: 'margin-bottom:8px' },
        h('h2', { style: 'margin:0' }, `${st.diffKey} – oczekiwane vs wyodrębnione`),
        h('span', { class: 'spacer' }),
        h('label', { style: 'display:flex;gap:8px;align-items:center;font-size:15px' },
          h('input', { type: 'checkbox', checked: st.onlyErrors, onchange: (e) => { st.onlyErrors = e.target.checked; renderDetail(); } }),
          'Tylko różnice')),
      st.diff.error ? h('div', { class: 'alert err', role: 'alert', style: 'margin-bottom:8px' }, st.diff.error) : null,
      !diffs.length ? h('div', { class: 'empty' }, 'Brak różnic.') :
        h('div', { class: 'table-wrap' }, h('table', null,
          h('thead', null, h('tr', null, ['Pole', 'Oczekiwane', 'Wyodrębnione', 'Wynik'].map((t) => h('th', null, t)))),
          h('tbody', null, diffs.map((x) => h('tr', null,
            h('td', { style: 'font-weight:600' }, x.field), h('td', null, show(x.expected)), h('td', null, show(x.predicted)),
            h('td', null, badge(x.status, DIFF_KIND[x.status] || 'idle'))))))),
      h('p', { class: 'muted', style: 'font-size:13px;margin:10px 0 0' }, 'TP – trafione · FP – wyodrębnione błędnie · FN – pominięte.'));
  }

  /* ---------- formularz uruchomienia ---------- */
  function renderForm() {
    const ds = h('select', { id: 'ev-ds' }, st.datasets.map((d) => h('option', { value: d.id }, `${d.name} (${d.examples})`)));
    const model = h('input', { type: 'text', id: 'ev-model', placeholder: st.settings && st.settings.llm_model ? `domyślnie: ${st.settings.llm_model}` : 'domyślny model API', style: 'width:280px' });
    const mode = h('select', { id: 'ev-mode' },
      h('option', { value: '' }, st.settings ? `domyślny (${st.settings.extraction_mode})` : 'domyślny'),
      h('option', { value: 'hybrid' }, 'hybrid'), h('option', { value: 'llm_only' }, 'llm_only'));
    const limit = h('input', { type: 'number', id: 'ev-limit', min: '1', placeholder: 'wszystkie', style: 'width:120px' });
    const run = h('button', { class: 'btn primary', type: 'button', disabled: !st.datasets.length, onclick: async () => {
      const body = { dataset: ds.value };
      if (model.value.trim()) body.model = model.value.trim();
      if (mode.value) body.mode = mode.value;
      if (limit.value) body.limit = Number(limit.value);
      run.disabled = true;
      try {
        const r = await api.post('/evaluation/runs', body);
        clear(msg, h('div', { class: 'alert info' }, `Uruchomiono ewaluację ${runLabel(r)}. Wyniki zapiszą się w object storage.`));
        location.hash = `#/evaluation/${encodeURIComponent(r.id)}`;
        await loadRuns();
      } catch (e) {
        clear(msg, errorBox(e.message));
      }
      run.disabled = false;
    } }, 'Uruchom ewaluację');
    clear(formEl, h('h2', null, 'Uruchom nowy przebieg'),
      h('p', { class: 'muted', style: 'margin:0 0 12px;font-size:14px' }, 'Dane do ewaluacji są czytane z object storage albo lokalnie (config/eval-datasets.yaml); wynik trafia do object storage.'),
      st.datasets.length ? h('div', { class: 'toolbar' },
        h('label', { class: 'field', for: 'ev-ds' }, 'Zbiór danych', ds),
        h('label', { class: 'field', for: 'ev-model' }, 'Model', model),
        h('label', { class: 'field', for: 'ev-mode' }, 'Tryb', mode),
        h('label', { class: 'field', for: 'ev-limit' }, 'Limit przykładów', limit), run)
        : h('div', { class: 'empty' }, 'Brak skonfigurowanych zbiorów danych.'));
  }

  renderRuns();
  renderForm();
  Promise.all([
    api.get('/evaluation/datasets').then((d) => { st.datasets = d; }).catch((e) => { clear(msg, errorBox(e.message)); }),
    api.get('/settings').then((s) => { st.settings = s; }).catch(() => {}),
  ]).then(() => { if (!dead) renderForm(); });
  loadRuns().then(() => {
    if (dead) return;
    if (!st.selectedId) {
      const first = st.runs.find((r) => r.status === 'done');
      if (first) { st.selectedId = first.id; renderRuns(); }
    }
    return loadDetail();
  });
}
