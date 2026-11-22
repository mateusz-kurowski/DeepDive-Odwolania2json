// Model formularza „nowy typ dokumentu” → YAML klasy (bez DOM, testowalne w Node).
// Format zgodny z src/classconfig.py: name, description, hints, rules, fields[].

export const FIELD_TYPES = [
  ['text', 'tekst'], ['number', 'liczba'], ['integer', 'liczba całkowita'], ['flag', 'flaga (1/0)'],
  ['enum', 'lista wartości'], ['object', 'obiekt (grupa pól)'], ['array', 'lista obiektów'],
];
// Zgodne z REGISTRY w src/validators.py.
export const VALIDATORS = ['nip', 'krs', 'regon', 'iban', 'ted', 'bzp', 'date', 'amount', 'email', 'pesel'];

const NAME = /^[a-z][a-z0-9_]*$/;

export const emptyField = () => ({ name: '', type: 'text', description: '', validator: '', options: '', nullable: true, fields: [] });
export const emptyModel = () => ({ name: '', description: '', hints: '', rules: '', fields: [emptyField()] });

const lines = (s) => String(s || '').split('\n').map((x) => x.trim()).filter(Boolean);
const q = (s) => JSON.stringify(String(s)); // łańcuch w cudzysłowie JSON jest poprawnym YAML-em

/** Wiersze opcji enum: „klucz: opis” (pierwszy dwukropek rozdziela). */
export function parseOptions(text) {
  return lines(text).map((l) => {
    const i = l.indexOf(':');
    return i < 0 ? [l, l] : [l.slice(0, i).trim(), l.slice(i + 1).trim()];
  });
}

function fieldYaml(f, ind) {
  const p = ' '.repeat(ind);
  const out = [`${p}- name: ${f.name.trim()}`, `${p}  type: ${f.type}`];
  if (f.description.trim()) out.push(`${p}  description: ${q(f.description.trim())}`);
  if (f.validator && ['text', 'number', 'integer'].includes(f.type)) out.push(`${p}  validator: ${f.validator}`);
  if (f.type === 'enum') {
    out.push(`${p}  options:`);
    for (const [k, v] of parseOptions(f.options)) out.push(`${p}    ${/^\d+$/.test(k) ? k : q(k)}: ${q(v)}`);
  }
  if (f.nullable === false) out.push(`${p}  nullable: false`);
  if (f.type === 'object' || f.type === 'array') {
    out.push(`${p}  fields:`);
    for (const c of f.fields) out.push(...fieldYaml(c, ind + 4));
  }
  return out;
}

export function toYaml(m) {
  const out = [`name: ${m.name.trim()}`, `description: ${q(m.description.trim())}`];
  for (const key of ['hints', 'rules']) {
    const items = lines(m[key]);
    if (items.length) out.push(`${key}:`, ...items.map((x) => `  - ${q(x)}`));
  }
  out.push('fields:');
  for (const f of m.fields) out.push(...fieldYaml(f, 2));
  return out.join('\n') + '\n';
}

/** Lista błędów po polsku; pusta = można zapisać. Backend i tak waliduje ostatecznie. */
export function validate(m) {
  const errs = [];
  if (!NAME.test(m.name.trim())) errs.push('Nazwa klasy: małe litery, cyfry i _, zaczynając od litery.');
  if (!m.description.trim()) errs.push('Opis typu jest wymagany (po czym model rozpozna dokument).');
  const walk = (fields, path) => {
    if (!fields.length) errs.push(`${path}: dodaj co najmniej jedno pole.`);
    const seen = new Set();
    fields.forEach((f, i) => {
      const where = `${path} › pole ${i + 1}`;
      const n = f.name.trim();
      if (!n) errs.push(`${where}: brak nazwy.`);
      else if (!NAME.test(n)) errs.push(`${where}: nazwa „${n}” – małe litery, cyfry i _.`);
      else if (seen.has(n)) errs.push(`${where}: nazwa „${n}” się powtarza.`);
      seen.add(n);
      if (f.type === 'enum' && !parseOptions(f.options).length) errs.push(`${where}: lista wartości wymaga co najmniej jednej opcji.`);
      if (f.type === 'object' || f.type === 'array') walk(f.fields, n ? `${path} › ${n}` : where);
    });
  };
  walk(m.fields, 'Pola');
  return errs;
}
