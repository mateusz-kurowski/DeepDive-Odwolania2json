import { h, clear, errorBox } from './ui.js';
import { FIELD_TYPES, VALIDATORS, emptyField, emptyModel, toYaml, validate } from './schema-yaml.js';

const move = (arr, i, d) => {
  const j = i + d;
  if (j < 0 || j >= arr.length) return;
  [arr[i], arr[j]] = [arr[j], arr[i]];
};

/** Formularz „Nowy typ dokumentu”: zamiast wklejania YAML. onSubmit(name, yaml) może rzucić błąd (pokazany w formularzu). */
export function buildNewTypeForm({ onSubmit, onCancel }) {
  const m = emptyModel();
  const preview = h('pre', { class: 'yaml-preview', 'aria-label': 'Podgląd wygenerowanego YAML', tabindex: '0' });
  const status = h('div', { role: 'status', 'aria-live': 'polite', style: 'min-height:24px' });
  const fieldsEl = h('div', { class: 'frows' });
  const refreshPreview = () => { preview.textContent = toYaml(m); };
  const touch = () => { clear(status); refreshPreview(); };

  const text = (label, key, opts = {}) => {
    const input = h(opts.area ? 'textarea' : 'input', {
      type: opts.area ? null : 'text', rows: opts.area ? '3' : null, value: m[key], placeholder: opts.ph || null,
      oninput: () => { m[key] = input.value; touch(); },
    });
    return h('label', { class: 'field', style: opts.style || null }, label, input);
  };

  function rows(list, depth) {
    const box = h('div', { class: 'frows' });
    const redraw = () => clear(box, ...list.map(row), h('button', { class: 'btn', type: 'button', onclick: () => { list.push(emptyField()); redraw(); touch(); } }, '+ Dodaj pole'));
    function row(f, i) {
      const sub = (f.type === 'object' || f.type === 'array') ? h('div', { class: 'fsub' }, rows(f.fields, depth + 1)) : null;
      if (sub && !f.fields.length) f.fields.push(emptyField());
      const nameIn = h('input', { type: 'text', value: f.name, 'aria-label': `Nazwa pola ${i + 1}`, placeholder: 'nazwa_pola', oninput: () => { f.name = nameIn.value; touch(); } });
      const typeSel = h('select', { 'aria-label': `Typ pola ${i + 1}`, onchange: () => { f.type = typeSel.value; if (f.type === 'object' || f.type === 'array') f.fields = f.fields.length ? f.fields : [emptyField()]; redraw(); touch(); } },
        FIELD_TYPES.map(([v, l]) => h('option', { value: v, selected: v === f.type }, l)));
      const valSel = ['text', 'number', 'integer'].includes(f.type)
        ? h('select', { 'aria-label': `Walidator pola ${i + 1}`, onchange: () => { f.validator = valSel.value; touch(); } },
            h('option', { value: '' }, 'bez walidatora'), VALIDATORS.map((v) => h('option', { value: v, selected: v === f.validator }, v)))
        : null;
      const desc = h('input', { type: 'text', value: f.description, 'aria-label': `Opis pola ${i + 1} dla modelu`, placeholder: 'Opis dla modelu: co to za wartość i jaki format', oninput: () => { f.description = desc.value; touch(); } });
      const opts = f.type === 'enum'
        ? h('textarea', { rows: '3', value: f.options, 'aria-label': `Opcje pola ${i + 1}`, placeholder: 'Jedna opcja w wierszu: klucz: opis\n1: oddalone\n2: uwzględnione', oninput: () => { f.options = opts.value; touch(); } })
        : null;
      const nullable = h('input', { type: 'checkbox', checked: f.nullable, onchange: () => { f.nullable = nullable.checked; touch(); } });
      return h('div', { class: 'frow', role: 'group', 'aria-label': `Pole ${i + 1}${f.name ? `: ${f.name}` : ''}` },
        h('div', { class: 'frow-top' }, nameIn, typeSel, valSel,
          h('button', { class: 'iconbtn sm', type: 'button', 'aria-label': 'Przesuń w górę', disabled: i === 0, onclick: () => { move(list, i, -1); redraw(); touch(); } }, '↑'),
          h('button', { class: 'iconbtn sm', type: 'button', 'aria-label': 'Przesuń w dół', disabled: i === list.length - 1, onclick: () => { move(list, i, 1); redraw(); touch(); } }, '↓'),
          h('button', { class: 'btn danger sm', type: 'button', onclick: () => { list.splice(i, 1); redraw(); touch(); } }, 'Usuń')),
        desc, opts,
        h('label', { class: 'check' }, nullable, 'Może być puste (null, gdy brak w dokumencie)'),
        sub);
    }
    redraw();
    return box;
  }

  clear(fieldsEl, rows(m.fields, 0));
  refreshPreview();

  const submit = async () => {
    const errs = validate(m);
    if (errs.length) {
      return clear(status, h('div', { class: 'alert err', role: 'alert' }, h('b', null, 'Popraw formularz:'), h('ul', { style: 'margin:4px 0 0 18px' }, errs.map((e) => h('li', null, e)))));
    }
    try {
      await onSubmit(m.name.trim(), toYaml(m));
    } catch (e) {
      clear(status, errorBox(e.message));
    }
  };

  return h('form', { class: 'newtype', novalidate: true, onsubmit: (e) => { e.preventDefault(); submit(); } },
    h('div', { class: 'toolbar', style: 'margin:0' },
      h('h2', { style: 'margin:0' }, 'Nowy typ dokumentu'),
      h('span', { class: 'spacer' }),
      h('button', { class: 'btn', type: 'button', onclick: onCancel }, 'Anuluj'),
      h('button', { class: 'btn primary', type: 'submit' }, 'Utwórz typ')),
    h('p', { class: 'muted', style: 'margin:0;font-size:14px' }, 'Wypełnij formularz: aplikacja sama wygeneruje plik YAML schematu i zapisze go bez zmian w kodzie.'),
    text('Nazwa klasy * (małe litery, cyfry, _)', 'name', { ph: 'np. uchwala_kio', style: 'max-width:320px' }),
    text('Opis * (po czym model rozpozna ten dokument)', 'description', { area: true }),
    h('div', { class: 'two' },
      text('Słowa kluczowe rozpoznawania (jedno w wierszu)', 'hints', { area: true }),
      text('Reguły dla modelu (jedna w wierszu)', 'rules', { area: true })),
    h('h3', { class: 'sub' }, 'Pola do wyodrębnienia'),
    fieldsEl,
    status,
    h('details', null, h('summary', null, 'Podgląd wygenerowanego YAML'), preview));
}
