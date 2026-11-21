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

export function mount(root, ctx) {
  ctx.title('Schematy');
  const st = { list: [], current: null, detail: null, isNew: false, error: null, saveError: null, info: null, loaded: false };
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
    try {
      st.detail = await api.get(`/classes/${encodeURIComponent(name)}`);
      st.error = null;
    } catch (e) {
      st.detail = null;
      st.error = e.message;
    }
    if (dead) return;
    renderList();
    renderEditor();
    renderPreview();
  }

  function renderList() {
    clear(listEl,
      h('h2', { style: 'font-size:16px;margin-bottom:4px' }, 'Typy dokumentów'),
      !st.loaded ? h('div', { class: 'loading' }, 'Ładowanie…') : null,
      st.error && !st.list.length ? errorBox(st.error) : null,
      st.list.map((c) => h('button', {
        type: 'button', class: 'sitem', 'aria-current': !st.isNew && c.name === st.current ? 'true' : null,
        onclick: () => { location.hash = `#/schemas/${encodeURIComponent(c.name)}`; },
      }, c.name, h('small', null, `${c.field_count} pól`))),
      h('button', { class: 'btn', type: 'button', onclick: startNew }, '+ Nowy typ'));
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
    const status = h('div', { role: 'status', 'aria-live': 'polite' },
      st.saveError ? errorBox(st.saveError) : null,
      st.info ? h('div', { class: 'alert info' }, st.info) : null);
    const save = async () => {
      const name = st.isNew ? nameInput.value.trim() : st.current;
      try {
        await api.put(`/classes/${encodeURIComponent(name)}`, { yaml: ta.value });
        st.saveError = null;
        st.info = `Zapisano typ „${name}”.`;
        await loadList();
        if (st.isNew) { location.hash = `#/schemas/${encodeURIComponent(name)}`; return; }
        st.detail = await api.get(`/classes/${encodeURIComponent(name)}`);
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
    clear(previewEl, h('h2', null, 'Pola schematu'),
      d ? [
        h('p', { class: 'muted', style: 'margin:0 0 8px;font-size:14px' }, d.description),
        tree(d.fields || []),
        d.example_count != null ? h('p', { class: 'muted', style: 'font-size:13px' }, `Przykładów w schemacie: ${d.example_count}`) : null,
      ] : h('div', { class: 'empty' }, st.isNew ? 'Podgląd pojawi się po zapisaniu.' : 'Brak wybranego typu.'));
  }

  renderList();
  renderEditor();
  renderPreview();
  loadList().then(() => {
    if (dead) return;
    const name = ctx.params[0];
    if (name) openClass(name);
  });
}
