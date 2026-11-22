# Plan implementacji przed zgłoszeniem (22.11)

Źródło: przegląd projektu względem FAQ v1.0 i README organizatora. Uzupełnia `docs/plan-prac.md`, nie zastępuje go.
Zasada wyboru: preselekcja to 100% F1 na ukrytym zbiorze, finał to 50% F1 i 50% elastyczność, więc najpierw ryzyka dla F1 i wymagań twardych.

Stan wyjściowy: hybrid F1 0,988 (ministral-14b) i 0,9975 (inkling-2-mini) na 180 PDF; skany organizatora (`data/dane/skany`, 30 PDF) F1 0,91–0,94; 272 testy zielone.

## P0: wymagania twarde i ryzyko dyskwalifikacji

### 1. Czas: 150 PDF w ≤45 min (≤18 s/PDF łącznie)
Brak pomiaru. Przekroczenie limitu może przekreślić wynik.
- [x] `run` i `eval`: zapis czasu per plik i łącznie w `trace/_summary.json` i w raporcie (`elapsed_s`, `s_per_doc`, osobno OCR i LLM). Pliki: `src/cli.py` (`_write_summary`), `src/pipeline.py`, `src/evaluate.py`, kolumna `s/dok.` w `src/sweep.py`.
- [x] Pomiar: 150 PDF (50 przykładów treningowych) + 30 skanów, `--workers 4/8/12`, docelowy model. Wynik do README i `docs/benchmark.md`.
- [ ] Domyślne `--workers` (4) zostawić albo podnieść do 8: przy 8 wątkach 1,3 s/PDF tekstowy i 4,5 s/PDF skan (`docs/benchmark.md`). Ustawić na wartość, która mieści się w limicie z zapasem ≥30% (uwaga na rate limit API: retry z backoffem już jest, sprawdzić w logu liczbę 429).
- [x] Twardy limit czasu na dokument (np. 120 s): po przekroczeniu `{}` i wpis w logu, zamiast blokować cały przebieg.
- Gotowe, gdy: czas 150 PDF na docelowym modelu jest w README i wynosi ≤30 min.
- Koszt: ~1,5 h (kod 45 min, pomiary w tle).

### 2. Negatywy: każdy dostaje `{}`
`data/dane/negatywne` (13 PDF) nie jest mierzony. Każdy fałszywy pozytyw to FP na wszystkich polach klasy.
- [x] `eval` na `negatywne`: metryka `negatives_rejected` (ile dostało `{}`) i lista błędnie sklasyfikowanych; włączyć do łącznego raportu i do `sweep` (kolumna).
- [x] Poprawić błędy klasyfikacji (znany przypadek: wyrok KIO `KIO_KIO 2617-21.pdf` → `odwolanie`). Najpierw przez YAML (`description`, `hints`, `hint_veto`, reguła „wyrok/uchwała/ogłoszenie TED/BZP to nie odwołanie”), bez kodu.
- [x] Test regresji (offline): `exclude_hints` w `tests/test_classify.py`; wynik 12/12 i 4/4 w `docs/benchmark.md`. ~~negatywy w `tests/test_shipped_classes.py`~~ (offline, na tekście z hintów).
- Gotowe, gdy: 13/13 negatywów → `{}`, F1 na przykładach bez spadku.
- Koszt: ~1 h.

### 3. Model, licencja i klucz API w dostawie
- [ ] Zamrozić model: małe modele dają punkty w finale (1–20 pkt, im mniejszy, tym lepiej). Kandydaci: ministral-8b (F1 0,983 / skany 0,911) vs routing cls3b + ext8b (skany 0,926, śr. 5,5B). Decyzja na podstawie punktów 1 i 4.
- [ ] Potwierdzić: licencja open-weights bez ograniczeń (Ministral: sprawdzić licencję per rozmiar), serwer API w UE, polityka prywatności dostawcy. Wpis do README (sekcja „Model”) i `docs/benchmark.md`.
- [ ] Klucz dla jury: osobny klucz z limitem budżetu w LiteLLM, przekazany poza repo (pole w HackTribe / mail do UZP); w README instrukcja „wklej klucz do `.env`”.
- [ ] Sprawdzić najnowsze zmiany w repo UZP („Stay tuned” przy punktacji LLM i sposobie testowania).
- Gotowe, gdy: model, licencja, region i sposób przekazania klucza są opisane w README.
- Koszt: ~30 min + odpowiedź organizatora.

## P1: F1 na ukrytym zbiorze

### 4. Skany (największa luka F1: 0,91 vs 0,99)
- [ ] Analiza błędów: `eval --dump` na `data/dane/skany`, pogrupować różnice wg przyczyny (OCR przekręcił cyfry, zgubił stronę, błąd modelu ekstrakcji).
- [ ] OCR: wyższe DPI renderowania (`pypdfium2`), prompt VLM „przepisz dosłownie, zachowaj cyfry, układ tabel, nie poprawiaj”, ewentualnie autoobrót strony. Plik `src/ocr.py`.
- [ ] Porównać modele OCR w sweepie (`sweeps/only-scans.yaml`): 3b / 8b / 14b jako VLM. Rozmiar OCR po API liczy się jak LLM.
- [ ] Odporność: 5 skanów zdegradowanych (obrót, szum, niski DPI) wygenerowanych skryptem `scripts/degrade_scans.py` z istniejących skanów; tylko do pomiaru, oznaczone jako dane syntetyczne.
- Gotowe, gdy: F1 na skanach ≥0,95 przy tym samym rozmiarze modelu albo udokumentowany powód, czemu nie.
- Koszt: ~2–3 h (głównie pomiary).

### 5. `czynnosc_powod_id` = 12
Schemat organizatora mówi 1–12, enum ma 1–11, więc kod 12 zostanie zamieniony na `null`.
- [ ] Zapytać UZP (stoisko) o słownik kodów; odpowiedź do `docs/pytania-do-mentorow.md`.
- [ ] Do czasu odpowiedzi: dodać opcję `12` w `classes/odwolanie.yaml` (opis „inna czynność”) i wpis w `derive.map` (null albo opis z odpowiedzi). Tylko YAML.
- Gotowe, gdy: walidacja przepuszcza 12; F1 bez zmian.
- Koszt: 15 min.

### 6. Długie dokumenty
- [ ] Policzyć w `trace/` flagi `truncated` (limit `MAX_CHARS = 60 000` w `src/extract.py`). Jeśli występują, sprawdzić F1 na tych plikach; chunking tylko przy realnej stracie (warunek z `docs/benchmark.md`).
- Koszt: 15 min na sprawdzenie.

### 7. Pełny przebieg kontrolny
- [ ] Po punktach 2–5: pełny `eval` (60 przykładów + skany + negatywy) na zamrożonym modelu, bez cache. To jest liczba na slajd.

## P2: finał (50% elastyczność) i dokumentacja

### 8. Demo „nowa klasa w 30 s”
- [ ] `classes_examples/faktura.yaml` → `classes/` przez formularz w UI, wgranie faktury, JSON. Nagrać jako fragment wideo.
- [ ] Test end-to-end offline (mock LLM): nowa klasa z YAML jest klasyfikowana i ekstrahowana bez zmian w kodzie (jeśli `tests/test_config_only.py` tego nie pokrywa).
- [ ] Mała, jawnie oznaczona próbka faktur (2–3 PDF) do demo.

### 9. Dokumentacja (wymagana do wypłaty nagrody)
- [ ] `docs/architektura.md`: moduły, przepływ, decyzje (ADR po 1–2 zdania: YAML jako kontrakt, cytaty w `trace/`, hybrid vs llm_only, routing modeli).
- [ ] `docs/nowa-klasa.md`: przewodnik krok po kroku (wyciągnięty z README) z przykładem pól zagnieżdżonych i tablic.
- [ ] `docs/benchmark.md`: uzupełnić tabele z `results/` (punkty 1, 2, 4, 7); dodać wykres F1 vs liczba parametrów do prezentacji.
- [ ] README: screeny UI, sekcja „Model i dane”, „Co powstało podczas HackNation”.

### 10. Docker od zera
- [ ] `docker compose up --build` na czystej maszynie (dotąd nieuruchomione wg `plan-prac.md`), `docker compose run --rm app` na `input/`. Poprawić, co wyjdzie.

## Kolejność i podział (5 osób)

| Osoba | Zadania | Kiedy |
|---|---|---|
| A | 1 (czas) → 7 (pełny przebieg) | od razu; pomiary w tle |
| B | 2 (negatywy) → 5 (kod 12) | od razu |
| C | 4 (skany) | od razu, najdłuższe |
| D | 3 (model, licencja, klucz) → 10 (Docker) | od razu; pytania do UZP |
| E | 8 (demo klasy) → 9 (dokumentacja, slajdy, wideo) | od razu |

Punkt 6 robi ten, kto pierwszy skończy. Decyzja o modelu (3) po wynikach 1 i 4. Pełny przebieg (7) i dokumentacja liczb (9) na końcu, po zamrożeniu modelu.
