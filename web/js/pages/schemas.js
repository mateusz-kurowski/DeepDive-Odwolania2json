import { api } from '../api.js';
import { h, clear, errorBox } from '../ui.js';

const TEMPLATE = (name) => `name: ${name}
description: >-
  Krótki opis dokumentu: po czym go rozpoznać.
hints:
  - słowo kluczowe
rules:
  - "Reguła dla modelu, np. format wartości."
fields:
  - name: dokument
    type: object
    fields:
      - name: pole
        type: text
        description: Opis pola dla modelu.
`;

function tree(fields) {
  return h('ul', { class: 'tree' }, fields.map((f) =>
    h('li', null,
      h('code', null, f.name), ' ', h('span', { class: 'badge idle' }, f.type),
      f.validator ? [' ', h('span', { class: 'badge outline' }, f.validator)] : null,
      f.description ? h('div', { class: 'd' }, f.description) : null,
      f.fields && f.fields.length ? tree(f.fields) : null)));
}

// Cache między remountami (zmiana hasha przebudowuje stronę): brak migania „Ładowanie…”.
const cache = { list: null, details: new Map() };

export function mount(root, ctx) {
  ctx.title('Schematy');
  let savedMode = 'form';
  try { savedMode = localStorage.getItem('schemas.mode') === 'yaml' ? 'yaml' : 'form'; } catch { /* brak storage */ }
  const st = { mode: savedMode, buf: null, list: cache.list || [], current: null, detail: null, isNew: false, error: null, saveError: null, info: null, loaded: !!cache.list, pending: ctx.params[0] || null };
  let dead = false;
  ctx.onCleanup(() => { dead = true; });

  const listEl = h('nav', { class: 'slist', 'aria-label': 'Typy dokumentów' });
  const editorEl = h('section', { class: 'seditor card', 'aria-label': 'Edytor schematu' });
  const previewEl = h('section', { class: 'spreview card', 'aria-label': 'Podgląd pól' });
  clear(root, h('div', { class: 'content' },
    h('div', { class: 'alert info', role: 'note' }, 'Dodanie nowego typu dokumentu nie wymaga zmian w kodzie. Schemat jest plikiem YAML: pola, opisy i podpowiedzi dla modelu.'),
    h('div', { class: 'schemas' }, listEl, editorEl, previewEl)));

  async function loadList() {
    try {
      st.list = await api.get('/classes');
      cache.list = st.list;
      st.error = null;
    } catch (e) {
      st.error = e.message;
    }
    st.loaded = true;
    if (!dead) renderList();
  }

  async function openClass(name) {
    st.isNew = false;
    st.saveError = null;
    st.info = null;
    st.current = name;
    st.pending = null;
    st.detail = cache.details.get(name) || null;
    st.buf = null;
    if (st.detail) { st.error = null; renderList(); prepareEditor(); renderPreview(); }
    try {
      const fresh = await api.get(`/classes/${encodeURIComponent(name)}`);
      cache.details.set(name, fresh);
      const changed = !st.detail || st.detail.yaml !== fresh.yaml;
      st.detail = fresh;
      st.error = null;
      if (!changed) return;
    } catch (e) {
      if (!st.detail) st.error = e.message;
      else return;
    }
    if (dead) return;
    renderList();
    prepareEditor();
    renderPreview();
  }

  function renderList() {
    clear(listEl,
      h('h2', { style: 'font-size:16px;margin-bottom:4px' }, 'Typy dokumentów'),
      h('button', { class: 'btn', type: 'button', onclick: startNew }, '+ Nowy typ'),
      !st.loaded ? [1, 2, 3].map(() => h('div', { class: 'sitem skel', 'aria-hidden': 'true' }, '\u00a0', h('small', null, '\u00a0'))) : null,
      st.error && !st.list.length ? errorBox(st.error, () => { st.error = null; renderList(); loadList(); }) : null,
      st.list.map((c) => h('button', {
        type: 'button', class: 'sitem', 'aria-current': !st.isNew && c.name === st.current ? 'true' : null,
        onclick: () => { location.hash = `#/schemas/${encodeURIComponent(c.name)}`; },
      }, c.name, h('small', null, `${c.field_count} pól`))),
      );
  }

  function startNew() {
    st.isNew = true;
    st.current = null;
    st.detail = null;
    st.saveError = null;
    st.info = null;
    st.buf = null;
    renderList();
    prepareEditor();
    renderPreview();
  }

  // --- edytor: jeden model, dwa widoki (formularz / YAML) -----------------------------------
  // Źródło prawdy: st.buf.yaml (tryb YAML) albo st.buf.data (tryb formularza). Przełączenie
  // konwertuje przez API, więc pola spoza formularza (examples, requires, derive) nie giną.
  function resetBuf() {
    st.buf = { yaml: st.isNew ? TEMPLATE('nowy_typ') : (st.detail ? st.detail.yaml : ''), data: null, newName: 'nowy_typ' };
  }

  async function setMode(next) {
    if (next === st.mode) return;
    try {
      if (next === 'form') {
        st.buf.data = (await api.post('/classes/parse', { yaml: st.buf.yaml })).data;
      } else {
        st.buf.yaml = (await api.post('/classes/dump', { data: st.buf.data })).yaml;
      }
      st.mode = next;
      st.saveError = null;
      try { localStorage.setItem('schemas.mode', next); } catch { /* brak storage */ }
    } catch (e) {
      st.saveError = e.message;
    }
    if (!dead) renderEditor();
  }

  const FIELD_TYPES = ['text', 'number', 'integer', 'flag', 'enum', 'object', 'array'];
  const lines = (v) => v.split('\n').map((x) => x.trim()).filter(Boolean);
  const optionsToText = (o) => Object.entries(o || {}).map(([k, v]) => `${k}: ${v}`).join('\n');
  function textToOptions(t) {
    const out = {};
    for (const l of lines(t)) {
      const i = l.indexOf(':');
      const k = (i < 0 ? l : l.slice(0, i)).trim();
      out[/^-?\d+$/.test(k) ? Number(k) : k] = i < 0 ? '' : l.slice(i + 1).trim();
    }
    return out;
  }
  const lab = (text, input) => h('label', { class: 'field' }, text, input);

  function fieldEditor(list, depth, rerender) {
    const wrap = h('div', { class: 'sf-form' });
    list.forEach((f, i) => {
      const nested = f.type === 'object' || f.type === 'array';
      const sel = h('select', {
        'aria-label': `Typ pola ${f.name || ''}`,
        onchange: () => {
          f.type = sel.value;
          if ((nested || ['object', 'array'].includes(f.type)) && !f.fields) f.fields = [];
          if (f.type === 'enum' && !f.options) f.options = {};
          rerender();
        },
      }, FIELD_TYPES.map((t) => h('option', { value: t, selected: t === f.type }, t)));
      wrap.append(h('div', { class: 'sf-row' },
        h('div', { class: 'sf-head' },
          lab('Nazwa', h('input', { type: 'text', value: f.name || '', oninput: (e) => { f.name = e.target.value; } })),
          lab('Typ', sel),
          lab('Walidator', h('input', { type: 'text', value: f.validator || '', placeholder: 'np. date, nip', style: 'width:130px',
            oninput: (e) => { if (e.target.value.trim()) f.validator = e.target.value.trim(); else delete f.validator; } })),
          h('span', { class: 'spacer' }),
          h('button', { class: 'btn small subtle', type: 'button', disabled: i === 0, 'aria-label': 'Przesuń w górę',
            onclick: () => { [list[i - 1], list[i]] = [list[i], list[i - 1]]; rerender(); } }, '↑'),
          h('button', { class: 'btn small subtle', type: 'button', disabled: i === list.length - 1, 'aria-label': 'Przesuń w dół',
            onclick: () => { [list[i + 1], list[i]] = [list[i], list[i + 1]]; rerender(); } }, '↓'),
          h('button', { class: 'btn small danger', type: 'button', onclick: () => { list.splice(i, 1); rerender(); } }, 'Usuń')),
        lab('Opis dla modelu', h('input', { type: 'text', value: f.description || '', oninput: (e) => { f.description = e.target.value; } })),
        f.type === 'enum'
          ? lab('Opcje (jedna na linię: kod: opis)', h('textarea', { rows: 3, style: 'height:auto;padding:8px 12px', value: optionsToText(f.options),
              oninput: (e) => { f.options = textToOptions(e.target.value); } }))
          : null,
        nested ? h('div', { class: 'sf-nest' }, fieldEditor(f.fields || (f.fields = []), depth + 1, rerender)) : null));
    });
    wrap.append(h('button', { class: 'btn small', type: 'button',
      onclick: () => { list.push({ name: '', type: 'text', description: '' }); rerender(); } }, '+ Pole'));
    return wrap;
  }

  function listEditor(label, key, d) {
    return lab(label, h('textarea', { rows: 3, style: 'height:auto;padding:8px 12px', value: (d[key] || []).join('\n'),
      oninput: (e) => { const v = lines(e.target.value); if (v.length) d[key] = v; else delete d[key]; } }));
  }

  function renderEditor() {
    if (!st.isNew && !st.detail && (st.pending || (st.current && !st.error))) {
      return clear(editorEl,
        h('div', { class: 'toolbar', style: 'margin:0' },
          h('h2', { style: 'margin:0' }, `Typ: ${st.pending || st.current}`),
          h('span', { class: 'spacer' }),
          h('button', { class: 'btn primary', type: 'button', disabled: true }, 'Zapisz')),
        h('div', { class: 'skel-block', 'aria-hidden': 'true' }));
    }
    if (!st.isNew && !st.detail) {
      return clear(editorEl, st.error ? errorBox(st.error) : h('div', { class: 'empty' }, 'Wybierz typ dokumentu z listy albo dodaj nowy.'));
    }
    if (!st.buf || (st.mode === 'form' && !st.buf.data)) { prepareEditor(); return; }
    const buf = st.buf;
    const syncName = (v) => {
      buf.newName = v;
      buf.yaml = buf.yaml.replace(/^name:.*$/m, `name: ${v}`);
      if (buf.data) buf.data.name = v;
    };
    const nameInput = st.isNew
      ? h('input', { type: 'text', id: 'cls-name', value: buf.newName, pattern: '[a-z][a-z0-9_]*', style: 'width:220px',
          oninput: () => syncName(nameInput.value) })
      : null;
    const status = h('div', { role: 'status', 'aria-live': 'polite', style: 'min-height:56px' },
      st.saveError ? errorBox(st.saveError) : null,
      st.info ? h('div', { class: 'alert info' }, st.info) : null);

    let body;
    if (st.mode === 'yaml') {
      body = h('label', { class: 'field', for: 'cls-yaml' }, 'YAML',
        h('textarea', { class: 'yaml', id: 'cls-yaml', spellcheck: 'false', 'aria-label': 'Definicja klasy w YAML', value: buf.yaml,
          oninput: (e) => { buf.yaml = e.target.value; } }));
    } else {
      const d = buf.data;
      body = h('div', { class: 'sf-form' },
        lab('Opis typu (po czym go rozpoznać)', h('textarea', { rows: 3, style: 'height:auto;padding:8px 12px', value: d.description || '',
          oninput: (e) => { d.description = e.target.value; } })),
        listEditor('Podpowiedzi (hints, jedna na linię)', 'hints', d),
        listEditor('Słowa wykluczające (exclude_hints, jedno na linię)', 'exclude_hints', d),
        listEditor('Reguły dla modelu (rules, jedna na linię)', 'rules', d),
        h('h3', { style: 'margin:8px 0 0;font-size:15px' }, 'Pola'),
        fieldEditor(d.fields || (d.fields = []), 0, renderEditor),
        (d.examples && d.examples.length) || d.requires
          ? h('p', { class: 'muted', style: 'font-size:13px;margin:0' },
              'Przykłady (examples) i kontrole (requires) zostają bez zmian; edytujesz je w trybie YAML.')
          : null);
    }

    const save = async () => {
      const name = st.isNew ? nameInput.value.trim() : st.current;
      try {
        if (st.mode === 'form') buf.yaml = (await api.post('/classes/dump', { data: buf.data })).yaml;
        await api.put(`/classes/${encodeURIComponent(name)}`, { yaml: buf.yaml });
        cache.details.delete(name);
        st.saveError = null;
        st.info = `Zapisano typ „${name}”.`;
        await loadList();
        if (st.isNew) { location.hash = `#/schemas/${encodeURIComponent(name)}`; return; }
        st.detail = await api.get(`/classes/${encodeURIComponent(name)}`);
        cache.details.set(name, st.detail);
        resetBuf();
        if (st.mode === 'form') buf.data = (await api.post('/classes/parse', { yaml: st.buf.yaml })).data;
        renderEditor();
        renderPreview();
      } catch (e) {
        st.saveError = e.message;
        st.info = null;
        clear(status, errorBox(e.message));
      }
    };
    const remove = async () => {
      if (!confirm(`Usunąć typ „${st.current}”? Plik YAML zostanie skasowany.`)) return;
      try {
        await api.del(`/classes/${encodeURIComponent(st.current)}`);
        cache.details.delete(st.current);
        st.current = null;
        st.detail = null;
        st.buf = null;
        await loadList();
        location.hash = '#/schemas';
        renderEditor();
        renderPreview();
      } catch (e) {
        clear(status, errorBox(e.message));
      }
    };
    const seg = (id, text) => h('button', { type: 'button', class: 'seg', role: 'tab', 'aria-selected': st.mode === id ? 'true' : 'false',
      onclick: () => setMode(id) }, text);
    clear(editorEl,
      h('div', { class: 'toolbar', style: 'margin:0' },
        h('h2', { style: 'margin:0' }, st.isNew ? 'Nowy typ dokumentu' : `Typ: ${st.current}`),
        h('span', { class: 'spacer' }),
        h('div', { class: 'segs', role: 'tablist', 'aria-label': 'Tryb edycji' }, seg('form', 'Formularz'), seg('yaml', 'YAML')),
        st.isNew ? null : h('button', { class: 'btn danger', type: 'button', onclick: remove }, 'Usuń'),
        h('button', { class: 'btn primary', type: 'button', onclick: save }, 'Zapisz')),
      nameInput ? h('label', { class: 'field', for: 'cls-name' }, 'Nazwa klasy (małe litery, cyfry, _)', nameInput) : null,
      body,
      status);
  }

  // Ładuje bufor dla bieżącego typu i, w trybie formularza, parsuje YAML.
  async function prepareEditor() {
    resetBuf();
    if (st.mode === 'form') {
      try { st.buf.data = (await api.post('/classes/parse', { yaml: st.buf.yaml })).data; }
      catch (e) { st.mode = 'yaml'; st.saveError = e.message; }
    }
    if (!dead) renderEditor();
  }

  function renderPreview() {
    const d = st.detail;
    const busy = !d && !st.isNew && !st.error && (st.pending || st.current);
    clear(previewEl, h('h2', null, 'Pola schematu'),
      busy ? h('div', { class: 'skel-block', 'aria-hidden': 'true' }) : d ? [
        h('p', { class: 'muted', style: 'margin:0 0 8px;font-size:14px' }, d.description),
        tree(d.fields || []),
        d.example_count != null ? h('p', { class: 'muted', style: 'font-size:13px' }, `Przykładów w schemacie: ${d.example_count}`) : null,
      ] : h('div', { class: 'empty' }, st.isNew ? 'Podgląd pojawi się po zapisaniu.' : 'Brak wybranego typu.'));
  }

  const name0 = ctx.params[0];
  if (name0 && cache.details.has(name0)) {
    openClass(name0);
  } else {
    renderList();
    renderEditor();
    renderPreview();
  }
  loadList().then(() => {
    if (dead) return;
    if (name0 && !cache.details.has(name0)) openClass(name0);
  });
}
