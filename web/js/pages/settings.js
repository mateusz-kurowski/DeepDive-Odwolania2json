import { api } from '../api.js';
import { h, clear, errorBox } from '../ui.js';

export function mount(root, ctx) {
  ctx.title('Ustawienia');
  const host = h('div', { class: 'content' }, h('div', { class: 'loading' }, 'Ładowanie…'));
  clear(root, host);
  let dead = false;
  ctx.onCleanup(() => { dead = true; });

  const msg = h('div', { role: 'status', 'aria-live': 'polite' });

  async function purge() {
    if (!confirm('Usunąć wszystkie dokumenty i wyniki przeglądu? Tej operacji nie można cofnąć.')) return;
    try {
      await api.del('/documents');
      clear(msg, h('div', { class: 'alert info' }, 'Usunięto wszystkie dokumenty.'));
    } catch (e) {
      clear(msg, errorBox(e.message));
    }
  }

  api.get('/settings').then((s) => {
    if (dead) return;
    const row = (k, v) => [h('dt', null, k), h('dd', null, v == null || v === '' ? '—' : String(v))];
    clear(host,
      h('section', { class: 'card', 'aria-label': 'Konfiguracja przetwarzania' },
        h('h2', null, 'Przetwarzanie'),
        h('dl', { class: 'dl' },
          row('Model ekstrakcji', s.llm_model),
          row('Tryb ekstrakcji', s.extraction_mode),
          row('OCR skanów', s.ocr_backend),
          row('Model VLM (OCR)', s.vlm_model),
          row('Endpoint API modelu', s.openai_base_url),
          row('Typy dokumentów', (s.classes || []).join(', ')),
          row('Limit pliku', s.max_upload_mb != null ? `${s.max_upload_mb} MB` : null))),
      h('section', { class: 'card', 'aria-label': 'Przechowywanie' },
        h('h2', null, 'Przechowywanie'),
        h('dl', { class: 'dl' },
          row('Object storage', s.storage_backend === 's3' ? 'S3 / MinIO' : 'Lokalny katalog (tryb deweloperski)'),
          row('Bucket', s.bucket)),
        h('p', { class: 'muted note', style: 'margin:12px 0 0' }, 'Konfiguracja pochodzi ze zmiennych środowiskowych API; z poziomu UI jest tylko do odczytu.')),
      h('section', { class: 'card', 'aria-label': 'Usuwanie danych' },
        h('h2', null, 'Dane'),
        h('button', { class: 'btn danger', type: 'button', onclick: purge }, 'Usuń wszystkie dokumenty…'),
        msg));
  }).catch((e) => { if (!dead) clear(host, errorBox(e.message)); });
}
