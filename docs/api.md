# API (kontrakt dla frontendu)

Prefiks `/api`. W Dockerze front (nginx) proxuje `/api/` do kontenera `api` (port 8000). JSON, daty ISO 8601 UTC, błędy: `{"detail": "tekst po polsku"}` z kodem 4xx/5xx.

## Ogólne
- `GET /api/health` → `{status:"ok", storage:"s3"|"local", model:str}`
- `GET /api/settings` → `{llm_model, extraction_mode, ocr_backend, vlm_model, openai_base_url, storage_backend, bucket|null, max_upload_mb, classes:[nazwa]}` (bez kluczy)

## Dokumenty (pliki użytkownika w object storage)
`DocSummary`: `{id, filename, status:"queued"|"processing"|"done"|"error", class_name:str|null, label:str (sygnatura albo nazwa pliku), created_at, duration_s:number|null, citation_ok_rate:number|null (0..1), needs_review:bool, approved_count:int, field_count:int, error:str|null}`

`Field`: `{path, label, section:str|null, value:any, quote:str|null, citation_ok:bool|null, status:"ai"|"edited"|"approved", highlights:[{page:int(1-based), x,y,w,h}]}`; `x,y,w,h` to ułamki 0..1 strony, początek w lewym górnym rogu; `highlights` puste dla skanów lub gdy cytatu nie da się zlokalizować.

- `POST /api/documents` (multipart, pole `files`, wiele) → 201 `[{id, filename, status}]`; tylko PDF, ≤ `max_upload_mb`; przetwarzanie w tle (poll `GET`).
- `POST /api/documents/samples` → 201 jak wyżej (przykładowe PDF-y z katalogu lokalnego).
- `GET /api/documents?q=&status=&needs_review=` → `{items:[DocSummary], summary:{total, processed, needs_review_rate:number|null, avg_citation_ok_rate:number|null, avg_duration_s:number|null}}` (nowe najpierw)
- `GET /api/documents/{id}` → `DocSummary` + `{ocr_used:bool, model:str, pages:int, fields:[Field], data:object}` (`data` = JSON po korektach)
- `GET /api/documents/{id}/pdf` → `application/pdf`
- `GET /api/documents/{id}/pages/{n}.png?width=900` → obraz strony (n od 1)
- `PATCH /api/documents/{id}/fields` body `{path, value?, status?:"ai"|"approved", revert?:bool}` → `Field`. `value` ustawia status `edited` (jeśli różni się od wartości z modelu) i zdejmuje zatwierdzenie; `status:"approved"` zatwierdza; `status:"ai"` zdejmuje zatwierdzenie (edycja zostaje); `revert:true` przywraca wartość z modelu i zdejmuje zatwierdzenie.
- `POST /api/documents/{id}/approve-all` → `DocSummary`
- `POST /api/documents/{id}/reprocess` → 202 `DocSummary`
- `DELETE /api/documents/{id}` → 204; `DELETE /api/documents` → 204 (wszystkie)
- `GET /api/documents/{id}/export` → pobranie JSON po korektach (`Content-Disposition`), format wyjściowy organizatora
- `POST /api/documents/export` body `{ids:[...], format:"json"|"jsonl"|"csv"}` → plik do pobrania

## Schematy (klasy dokumentów = YAML w `classes/`)
- `GET /api/classes` → `[{name, description, field_count, hints:[str]}]`
- `GET /api/classes/{name}` → `{name, description, yaml:str, fields:[{name,type,description,validator|null,options|null,nullable,fields:[...]}], example_count}`
- `PUT /api/classes/{name}` body `{yaml}` → zapis (tworzy lub zmienia); 422 `{detail}` gdy YAML niepoprawny lub `name` w YAML ≠ `{name}`; nazwa `^[a-z][a-z0-9_]*$`
- `DELETE /api/classes/{name}` → 204

## Ewaluacja
Wyniki domyślne są czytane z plików lokalnych (`results/`, tylko do odczytu, `source:"local"`); przebiegi uruchomione z UI zapisują się w object storage (`source:"storage"`). Dane do ewaluacji (`config/eval-datasets.yaml`) są czytane z object storage (`prefix`) albo, gdy tam pusto, lokalnie (`path`); odpowiedź `/eval/datasets` zawiera `source` (`local`/`storage`/`null`).

`RunSummary`: `{id, source:"local"|"storage", name, dataset:str|null, model:str|null, mode:str|null, status:"running"|"done"|"error", started_at:str|null, finished_at:str|null, micro_f1:number|null, precision, recall, docs:int|null, errors:int|null, citation_ok_rate, error:str|null, progress:{done:int,total:int}|null}`

- `GET /api/evaluation/datasets` → `[{id, name, description, path, examples:int}]`
- `GET /api/evaluation/runs` → `[RunSummary]` (najnowsze najpierw; lokalne i z storage razem)
- `POST /api/evaluation/runs` body `{dataset, model?, mode?:"hybrid"|"llm_only", limit?:int}` → 202 `RunSummary` (zapis do storage)
- `GET /api/evaluation/runs/{id}` → `RunSummary` + `{report: <Report.to_dict()>|null}`; `report.per_field` to `{ścieżka: {tp,fp,fn,precision,recall,f1}}`
- `GET /api/evaluation/runs/{id}/documents` → `[{label, stem, class_name, tp, fp, fn, f1:number|null, error:str|null}]`
- `GET /api/evaluation/runs/{id}/documents/{label}/{stem}` → `{source, class, error, ocr_used, prediction, reference, diffs:[{field, predicted, expected, status:"wrong"|"missing"|"extra"}], trace}`
