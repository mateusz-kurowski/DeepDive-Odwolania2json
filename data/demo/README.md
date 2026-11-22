# Dokument demo

`odwolanie.pdf` to przykład treningowy organizatora (`data/dane/przyklad_01/odwolanie.pdf`, dane syntetyczne, KRS `9999…`).
`odwolanie.fixture.json` to **zapisany, niezmieniany wynik prawdziwego przebiegu pipeline'u** (`mistralai/ministral-8b-2512`, tryb hybrid)
na tym PDF-ie: dane, cytaty i flagi weryfikacji. Wynik zgadza się z oczekiwanym `odwolanie.json` w 22 z 22 pól.

Służy do przycisku „Załaduj dokument demo” (`POST /api/documents/demo`): pokazuje gotowy, przetworzony dokument bez wywołania
modelu, więc demo działa bez endpointu LLM i bez sieci. Podświetlenia w PDF-ie liczy API na żywo z cytatów, nie są w fixture.
Aby odtworzyć fixture: wgraj PDF przez UI, po przetworzeniu skopiuj `meta`/`result` z magazynu dokumentów.
