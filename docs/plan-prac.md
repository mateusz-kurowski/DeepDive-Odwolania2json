# Plan pracy: Odwołania2JSON

Kolejność wg wpływu na punkty: preselekcja to 100% F1 na ukrytym zbiorze ze skanami, finał to 50% F1 i 50% elastyczność, GUI jest punktowane dodatkowo (FAQ organizatora v1.0).

## P0: wynik F1 i wymagania twarde (bez tego nie ma zgłoszenia)

1. **Poprawa skanów (OCR).** Skany: F1 0.929, treningowe 0.996. Główna luka na ukrytym zbiorze.
   - [ ] Prośba do administratora LiteLLM o model z wizją (open-weights, UE); przy okazji lokalizacja serwera i polityka prywatności. `extractor` (DeepSeek Flash) jest tekstowy i nie przyjmuje obrazów.
   - [ ] Backend VLM: `OCR_BACKEND=tesseract|vlm` + `VLM_MODEL`, fallback na Tesseracta. Najpierw mock, potem pomiar na 30 skanach.
   - [ ] Poprawki Tesseracta (niezależnie od VLM): wyższy DPI, obróbka obrazu.
   - [ ] Walidacja sumy kontrolnej IBAN: błędny numer rachunku daje `null`.
   - [ ] Klasyfikacja: `KIO_KIO 2617-21.pdf` (wyrok KIO) wpada do `odwolanie`.
2. **Instalacja i uruchomienie jak chce organizator.**
   - [ ] `requirements.txt`: `make requirements`, commit, test zgodności z `uv.lock`.
   - [ ] Czysta instalacja w nowym venv: `pip install -r requirements.txt` + `python -m src run`.
   - [ ] `start.bat`: czy robi to samo (venv, pip, run).
   - [ ] README: instalacja Tesseracta (Windows/Linux/macOS), jeśli VLM nie wejdzie.
   - [ ] `docker compose build` (dotąd nieuruchomione).
3. **Push na GitHub.**
   - [ ] Wypchnąć branch, PR do `main`, zaktualizować gitlink submodułu w repo głównym.
4. **Klucz API w dostawie.**
   - [ ] Jury testuje na komputerze bez GPU, klucz do usługi dostarczamy my. Ustalić, jak go przekazać (nie w repo); dopisać do pytań do mentorów.

## P1: punkty dodatkowe

5. **Lokalne API + UI** (opcjonalne, ale punktowane).
   - [ ] Wymagania z FAQ: wgranie plików, uruchomienie, podgląd JSON obok oryginału.
   - [ ] Cienkie API (FastAPI) nad `process_pdf`.
   - [ ] Jedna komenda, np. `python -m src serve`, frontend serwowany z tego samego procesu (bez Node).
   - [ ] Cytaty źródłowe i podświetlenie w tekście.
6. **Elastyczność (połowa oceny finału).**
   - [ ] Czwarta klasa jako dowód „config only”: `classes_examples/` działa bez edycji Pythona.
   - [ ] Instrukcja dodawania klasy w README + scenariusz do pokazania jurorom.
   - [ ] Pytania o zbiór testowy (konsorcja, `czynnosc_powod_id` 12): `docs/pytania-do-mentorow.md`, część C.

## P2: dokumentacja i prezentacja

7. [ ] Diagram architektury w README (Mermaid): PDF → tekst/OCR → klasyfikacja → ekstrakcja → weryfikacja cytatów → walidatory → JSON.
8. [ ] Screeny UI w README (po punkcie 5), najlepiej skan z podświetlonymi polami.
9. [ ] Instrukcje uruchomienia w README: CLI pip, `start.bat`, Docker, lokalne API + UI.
10. [ ] Wypełnić `docs/benchmark.md`: wiersz „po wszystkich”, hybrid vs llm_only, skany, negatywne.

## P3: pomiary i porządki

11. [ ] Pełny run 60 przykładów w obu trybach po wszystkich poprawkach (ostatni hybrid: F1 0.9956, do potwierdzenia na `llm_only`).
12. [ ] Wybór modelu i licencja: zapytać organizatora, czy open-weights z własną licencją jest OK, przed zamrożeniem modelu.
13. [ ] Czyszczenie `results/`: `smoke-hybrid-3.*`, `old/`, `SUMMARY.md` (czeka na decyzję).
14. [ ] Target `eval-skany` w Makefile z parametrem `DATA`.
15. [ ] Przed zgłoszeniem: `make requirements`, `make lint`, sprawdzenie linków w incognito.

## Kolejność

1. Równolegle: prośba o VLM (1) i push (3), bo zależą od ludzi lub sieci.
2. `requirements.txt` + czysta instalacja + `start.bat` (2): wymóg twardy, szybkie.
3. OCR (1): backend VLM, IBAN, klasyfikacja. Największy zysk F1.
4. Równolegle z OCR: UI (5), może robić druga osoba.
5. Na końcu: diagram, screeny, README, pełny benchmark.
