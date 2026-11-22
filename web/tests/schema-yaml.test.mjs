import test from 'node:test';
import assert from 'node:assert/strict';
import { emptyField, emptyModel, toYaml, validate, parseOptions } from '../js/schema-yaml.js';

const f = (o) => ({ ...emptyField(), ...o });

test('toYaml: pola proste, podpowiedzi i reguły', () => {
  const m = { ...emptyModel(), name: 'uchwala', description: 'Uchwała „KIO”: "tak"', hints: 'uchwała\n\n sygn ', rules: 'Kwota jako liczba.',
    fields: [f({ name: 'sygnatura', description: 'Numer', validator: 'date' }), f({ name: 'ok', type: 'flag', nullable: false })] };
  assert.equal(toYaml(m), [
    'name: uchwala',
    'description: "Uchwała „KIO”: \\"tak\\""',
    'hints:', '  - "uchwała"', '  - "sygn"',
    'rules:', '  - "Kwota jako liczba."',
    'fields:',
    '  - name: sygnatura', '    type: text', '    description: "Numer"', '    validator: date',
    '  - name: ok', '    type: flag', '    nullable: false', '',
  ].join('\n'));
});

test('toYaml: enum z kluczami liczbowymi i tekstowymi oraz zagnieżdżenie', () => {
  const m = { ...emptyModel(), name: 'x', description: 'd', fields: [
    f({ name: 'sekcja', type: 'object', fields: [f({ name: 'rodzaj', type: 'enum', options: '1: oddalone\nuw: uwzględnione' })] }),
  ] };
  const y = toYaml(m);
  assert.match(y, /options:\n {10}1: "oddalone"\n {10}"uw": "uwzględnione"/);
  assert.match(y, / {2}- name: sekcja\n {4}type: object\n {4}fields:\n {6}- name: rodzaj/);
});

test('parseOptions: bez dwukropka klucz = opis', () => {
  assert.deepEqual(parseOptions('a\nb: c: d'), [['a', 'a'], ['b', 'c: d']]);
});

test('validate: poprawny model i typowe błędy', () => {
  const ok = { ...emptyModel(), name: 'ok_1', description: 'd', fields: [f({ name: 'a' })] };
  assert.deepEqual(validate(ok), []);
  const bad = { ...emptyModel(), name: 'Zła Nazwa', description: ' ', fields: [f({ name: 'a' }), f({ name: 'a' }), f({ name: '' }),
    f({ name: 'e', type: 'enum' }), f({ name: 'o', type: 'object' })] };
  const e = validate(bad).join('\n');
  for (const s of ['Nazwa klasy', 'Opis typu', 'się powtarza', 'brak nazwy', 'wymaga co najmniej jednej opcji', 'o: dodaj co najmniej jedno pole']) assert.ok(e.includes(s), s);
});
