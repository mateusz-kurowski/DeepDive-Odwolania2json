# CLAUDE.md — proj1: Odwołania2JSON (UZP)

Kontekst projektu dla Claude'a i zespołu. Język: polski (nazwy techniczne po angielsku). Nadrzędny kontekst hackathonu: `../CLAUDE.md` (harmonogram, zasady zgłoszenia, pitch). Ten plik dotyczy tylko tego zadania.

## 1. Zadanie w skrócie

PDF-y sprawy odwoławczej KIO → klasyfikacja dokumentu → ekstrakcja pól → JSON zgodny ze schematem UZP.

- Wejście: `input/caseN/*.pdf`. Wyjście: `output/caseN/<ta-sama-nazwa>.json`.
- Klasy: `odwolanie`, `pelnomocnictwo`, `przelew`. Dokument spoza klas = `nieznany`: bez pliku JSON, wpis w logu.
- Ocena: etap I to F1 na ukrytym zbiorze min. 10 realnych spraw; etap II (maks. 3 finalistów) to 50% F1 i 50% elastyczność/rozszerzalność (regulamin i README) albo 50/30/20 (PDF zadania). **Rozbieżność niewyjaśniona** — zapytać organizatora.
- Premie: nowe klasy dokumentów dodawane samą konfiguracją; przezroczystość ekstrakcji (cytaty źródłowe).
- Nagroda 20 000 zł brutto, z przeniesieniem praw autorskich; zwycięzca dostarcza kod, Docker Compose, dokumentację i instrukcję dodawania klasy.

Pełny projekt: `docs/superpowers/specs/2026-11-21-odwolania2json-design.md`. **Zacznij od niego.** Ten plik go nie powtarza.

## 2. Twarde ograniczenia (anty-cele)

- **Wyłącznie open source, w tym modele (open-weights).** Żadnego Gemini/Claude/GPT w rozwiązaniu. Claude służy tylko do budowania kodu, nie jest zależnością działania.
- Python 3.13+, `requirements.txt`, CLI lub `start.bat`, bez GPU na docelowej maszynie (model wołany przez API zgodne z OpenAI: LiteLLM, vLLM, Ollama).
- Logika klas **nie może** być zaszyta w kodzie: nowa klasa = nowy plik YAML w `classes/`. Jeśli coś wymaga edycji Pythona przy dodaniu klasy, to błąd projektu.
- Nie zgadywać: gdy pole niepewne albo walidacja nie przechodzi, `null`.
- Pilnować licencji bibliotek i modeli (przeniesienie praw autorskich).

## 3. Architektura (decyzje podjęte)

- Hybryda: tekst z PDF (pypdf; Tesseract z danymi `pol` tylko gdy brak tekstu) → klasyfikacja → ekstrakcja modelem ze schematu z YAML → walidatory formatów (NIP, KRS, REGON, BZP, TED, IBAN, daty ISO, kwota) → zapis JSON.
- Cytat źródłowy dla każdego pola, weryfikowany w kodzie dopasowaniem przybliżonym do tekstu.
- Przełącznik `EXTRACTION_MODE=hybrid|llm_only` (env, flaga `--mode`; domyślnie `hybrid`): `llm_only` pomija walidatory i normalizację, schemat i cytaty zostają. `eval` przyjmuje ten sam przełącznik (porównanie F1 obu trybów).
- Własna cienka warstwa zamiast LangExtract (powody w dokumencie projektowym, decyzja zespołu).
- Model: endpoint, nazwa i klucz z env. Wybór modelu **po benchmarku** 2–3 kandydatów na 60 przykładach (jeszcze nie wybrany).
- Lokalna ewaluacja F1 per pole na `data/dane/` (komenda `eval`). Skaner organizatora nie jest opublikowany, założenia w dokumencie projektowym (sekcja 7).

## 4. Pułapki danych (łatwo pomylić)

- `czynnosc_*` pochodzą **tylko z pierwszego „Zarzutu"**.
- Konsorcjum: używać danych **Lidera**.
- `czynnosc_powod_id` 1–11 (12 jest w komentarzu schematu, brak w danych): 1 odrzucenie oferty, 2 wybór oferty, 3 wykluczenie wykonawcy, 4 publikacja SWZ, 5 modyfikacja SWZ, 6 odpowiedzi/wyjaśnienia SWZ, 7 zaniechanie odrzucenia oferty, 8 zaniechanie wykluczenia wykonawcy, 9 unieważnienie postępowania, 10 zaniechanie unieważnienia, 11 OPZ.
- Formaty: daty ISO; BZP `YYYY/BZP########`; TED `NNNNNN-YYYY`; `prowadzacy_postepowanie` ∈ {null,1,0}; `przez-pelnomocnika` ∈ {1,0}.
- `data` i `miejscowosc` są `null` w 15 z 60 przykładów. `pesel` jest liczbą w schemacie, ale `null` w danych treningowych.
- `docs/schematy/odwolanie.json` zawiera komentarze `//` i nie jest poprawnym JSON-em.
- Dane treningowe są syntetyczne (KRS `9999…`), zbiór testowy „realny": możliwe inne układy i skany. W 180 treningowych PDF-ach 0 skanów, max 11 stron.

## 5. Układ katalogów

- `docs/superpowers/specs/` — dokument projektowy (zatwierdzany przed budową).
- `docs/schematy/` — oczekiwane JSON-y organizatora (3 klasy).
- `docs/zadanie/` — PDF-y `UZP - Pełna treść zadania konkursowego` i `UZP - Regulamin zadania konkursowego`, README organizatora i `PODSUMOWANIE.md`.
- `data/dane/przyklad_01..60/` — 60 spraw (3 PDF + 3 JSON każda). `data/szablon-aplikacja/` — przykładowe `input/` i `output/` plus przykład negatywny.
- Docelowo: `classes/` (YAML), kod w `src/`, `Dockerfile`, `docker-compose.yml`, README i instrukcja „jak dodać klasę".

## 6. Zasady pracy w tym projekcie

- Status: kod według planu `docs/superpowers/plans/` zbudowany (CLI `run`/`eval`/`classes`, trzy klasy w `classes/`, Docker, README). **Niezmierzone**: F1 na żywym modelu i wybór modelu (potrzebny endpoint, wyniki idą do `docs/benchmark.md`).
- Walking skeleton: jedna klasa (`przelew`, najprostsza) end-to-end z ewaluacją, potem `pelnomocnictwo`, na końcu `odwolanie` (najtrudniejsza). Potem własna czwarta klasa jako dowód „config only".
- Każda zmiana promptu lub reguły: policzyć F1 na 60 przykładach przed i po. Liczba idzie na slajd.
- Małe commity. To jest submoduł: commity trafiają do `HackNation-2026-proj1`, a po zmianie trzeba też zaktualizować gitlink w repo głównym.
- Odpowiedzi zwięzłe, wniosek na początku.

## 7. Otwarte pytania do organizatora/mentorów

1. Wagi oceny: 50/50 czy 50/30/20.
2. Jak jury uruchamia rozwiązanie i skąd bierze model (endpoint od nas czy w Docker Compose).
3. Jak dokładnie liczone jest F1 (pola puste, tablice, nadmiarowe pliki).
4. Czy „wyłącznie open source, w tym modele" dopuszcza open-weights, czy wymaga licencji OSI. Zadać przed wyborem modelu.

## 8. Dziennik

- 21.11 — dokument projektowy napisany i skopiowany do `proj1/`; model jeszcze niewybrany; zatwierdzenie dokumentu przez zespół oczekuje.
- 21.11 — plan implementacji wykonany (Taski 1–16, 144 testy offline). Do zrobienia z endpointem: pomiary F1 (`docs/benchmark.md`), benchmark modeli, `docker compose build` (nieuruchomione, brak daemona). Odkrycie: `szablon-aplikacja/.../przyklad odwolanie.pdf` to skan, więc OCR jest realnie potrzebny.
