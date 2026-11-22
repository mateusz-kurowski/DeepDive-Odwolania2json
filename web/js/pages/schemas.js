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
  const st = { list: cache.list || [], current: null, detail: null, isNew: false, error: null, saveError: null, info: null, loaded: !!cache.list, pending: ctx.params[0] || null };
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
    if (st.detail) { st.error = null; renderList(); renderEditor(); renderPreview(); }
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
    renderEditor();
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
    renderList();
    renderEditor();
    renderPreview();
  }

  function renderEditor() {
    if (!st.isNew && !st.detail && (st.pending || (st.current && !st.error))) {
      return clear(editorEl,
        h('div', { class: 'toolbar', style: 'margin:0' },
          h('h2', { style: 'margin:0' }, `Typ: ${st.pending || st.current}`),
          h('span', { class: 'spacer' }),
          h('button', { class: 'btn primary', type: 'button', disabled: true }, 'Zapisz')),
        h('label', { class: 'field' }, 'YAML', h('textarea', { class: 'yaml', disabled: true, 'aria-busy': 'true' })),
        h('div', { style: 'min-height:56px' }));
    }
    if (!st.isNew && !st.detail) {
      return clear(editorEl, st.error ? errorBox(st.error) : h('div', { class: 'empty' }, 'Wybierz typ dokumentu z listy albo dodaj nowy.'));
    }
    const nameInput = st.isNew
      ? h('input', {
          type: 'text', id: 'cls-name', value: 'nowy_typ', pattern: '[a-z][a-z0-9_]*', style: 'width:220px',
          oninput: () => {
            const v = nameInput.value;
            ta.value = ta.value.replace(/^name:.*$/m, `name: ${v}`);
          },
        })
      : null;
    const ta = h('textarea', {
      class: 'yaml', id: 'cls-yaml', spellcheck: 'false', 'aria-label': 'Definicja klasy w YAML',
      value: st.isNew ? TEMPLATE('nowy_typ') : st.detail.yaml,
    });
    const status = h('div', { role: 'status', 'aria-live': 'polite', style: 'min-height:56px' },
      st.saveError ? errorBox(st.saveError) : null,
      st.info ? h('div', { class: 'alert info' }, st.info) : null);
    const save = async () => {
      const name = st.isNew ? nameInput.value.trim() : st.current;
      try {
        await api.put(`/classes/${encodeURIComponent(name)}`, { yaml: ta.value });
        cache.details.delete(name);
        st.saveError = null;
        st.info = `Zapisano typ „${name}”.`;
        await loadList();
        if (st.isNew) { location.hash = `#/schemas/${encodeURIComponent(name)}`; return; }
        st.detail = await api.get(`/classes/${encodeURIComponent(name)}`);
        cache.details.set(name, st.detail);
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
        await loadList();
        location.hash = '#/schemas';
        renderEditor();
        renderPreview();
      } catch (e) {
        clear(status, errorBox(e.message));
      }
    };
    clear(editorEl,
      h('div', { class: 'toolbar', style: 'margin:0' },
        h('h2', { style: 'margin:0' }, st.isNew ? 'Nowy typ dokumentu' : `Typ: ${st.current}`),
        h('span', { class: 'spacer' }),
        st.isNew ? null : h('button', { class: 'btn danger', type: 'button', onclick: remove }, 'Usuń'),
        h('button', { class: 'btn primary', type: 'button', onclick: save }, 'Zapisz')),
      nameInput ? h('label', { class: 'field', for: 'cls-name' }, 'Nazwa klasy (małe litery, cyfry, _)', nameInput) : null,
      h('label', { class: 'field', for: 'cls-yaml' }, 'YAML', ta),
      status);
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
