# Dokument demo

`odwolanie.pdf` to przykład treningowy organizatora (`data/dane/przyklad_01/odwolanie.pdf`, dane syntetyczne, KRS `9999…`).
`odwolanie.fixture.json` to **zapisany, niezmieniany wynik prawdziwego przebiegu pipeline'u** (`mistralai/ministral-8b-2512`, tryb hybrid)
na tym PDF-ie: dane, cytaty i flagi weryfikacji. Wynik zgadza się z oczekiwanym `odwolanie.json` w 22 z 22 pól.

Służy do przycisku „Załaduj dokument demo” (`POST /api/documents/demo`): pokazuje gotowy, przetworzony dokument bez wywołania
modelu, więc demo działa bez endpointu LLM i bez sieci. Podświetlenia w PDF-ie liczy API na żywo z cytatów, nie są w fixture.
Aby odtworzyć fixture: wgraj PDF przez UI, po przetworzeniu przepisz `meta`, a z `result.json` dane (`data`), cytaty (`quote`) i `citation_ok` pól do `extraction`.

## Rozszerzalność: demo podąża za schematem klasy

`odwolanie.fixture.json` zawiera surowy wynik modelu (`extraction`: dane, cytaty, flagi weryfikacji), a nie gotowe pola.
Pola dokumentu demo budowane są przy ładowaniu z **aktualnego** `classes/odwolanie.yaml`, tak samo jak po zwykłym
przetwarzaniu. Zmiana etykiet/sekcji w schemacie jest od razu widoczna w demo; pole dodane w edytorze schematów pojawia się
jako puste (model go nie wyodrębniał). Do pokazania „nowe pole na żywo” użyj „Przetwórz ponownie” (wymaga endpointu LLM).
Gdy klasy z fixture nie ma w schematach, API zwraca 409 z czytelnym komunikatem.
Test: `tests/api/test_documents_api.py::test_demo_follows_edited_class_schema`.
