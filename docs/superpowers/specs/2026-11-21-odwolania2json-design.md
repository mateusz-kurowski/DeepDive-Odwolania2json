# Odwołania2JSON (UZP) — projekt

Data: 2026-11-21. Zadanie HackNation 2026, Urząd Zamówień Publicznych.
Materiały: `projects/[Urząd Zamówień Publicznych] Odwołania2JSON/` oraz repo organizatora `https://github.com/Urzad-Zamowien-Publicznych/hacknation-2026` (schematy w `oczekiwane-json/`, 60 spraw w `dane/przyklad_01..60/`, szablon w `szablon-aplikacja/`).

## 1. Cel i uzasadnienie

Aplikacja zamienia PDF-y sprawy odwoławczej KIO na kanoniczny JSON: dla każdego PDF-a rozpoznaje klasę dokumentu i wyciąga pola według schematu UZP.

- Wejście: `input/caseN/*.pdf`. Wyjście: `output/caseN/<ta-sama-nazwa>.json`.
- Klasy: `odwolanie`, `pelnomocnictwo`, `przelew`, plus ścieżka `nieznany` (dokument spoza klas, bez pliku JSON, wpis w logu). Przykład negatywny: 9-stronicowy PDF w `szablon-aplikacja`.
- Dlaczego to zadanie: zespół ma doświadczenie z takimi narzędziami, a zadanie jest jasno zdefiniowane i mierzalne (60 spraw z oczekiwanymi JSON-ami).
- Ocena: etap I to F1 na ukrytym zbiorze min. 10 realnych spraw. Etap II to maks. 3 finalistów. Regulamin i README podają 50% F1 i 50% elastyczność/rozszerzalność. PDF zadania podaje 50/30/20 (F1 / elastyczność / architektura). **Rozbieżność do wyjaśnienia z organizatorem.** Premie: konfiguracja nowych klas wyłącznie konfiguracją oraz przezroczystość ekstrakcji.

## 2. Cele, nie-cele, anty-cele

Cele:
- Maksymalne F1 na ukrytym zbiorze, liczone osobno dla każdego pola.
- Nowa klasa dokumentu dodawana wyłącznie przez plik konfiguracyjny, bez zmian kodu.
- Przezroczystość: dla każdego pola cytat źródłowy z dokumentu, weryfikowany w kodzie.
- Spełnienie wymagań dostawy: Python 3.13+, `requirements.txt`, CLI lub `start.bat`, Docker Compose, dokumentacja, instrukcja dodawania nowej klasy, brak GPU, on-prem.

Nie-cele:
- Interfejs graficzny jako element rdzenia. Wynik to CLI i pliki.
- Wsparcie dla dokumentów innych niż wskazane trzy klasy poza mechanizmem konfiguracji.
- Trening lub dostrajanie modeli.

Opcjonalnie (Could, dopiero po spełnieniu wszystkich Must): prosta przeglądarka wyników (PDF obok JSON z podświetlonymi cytatami) na potrzeby pitchu.

Anty-cele (porażka, nawet gdy „działa"):
- Jakikolwiek komponent niezgodny z „wyłącznie open source, w tym modele" (bez modeli komercyjnych, bez Gemini/Claude/GPT w rozwiązaniu).
- Logika klas zaszyta w kodzie, tak że nowa klasa wymaga edycji Pythona.
- Wynik dobry na 60 przykładach syntetycznych, ale kruchy na „realnych" (inne układy, skany).

## 3. Ograniczenia

- Python 3.13+, `requirements.txt`. Tylko open source. Bez GPU na docelowej maszynie, więc model jest wołany przez API zgodne z OpenAI (własny LiteLLM, vLLM, Ollama), nie uruchamiany w procesie.
- Wyłącznie modele open-weights (decyzja zespołu). Konkretny model jeszcze nie wybrany.
- Po wygranej: kod, Docker Compose, dokumentacja i umowa przenosząca prawa autorskie (nagroda 20 tys. zł brutto). Pilnować licencji bibliotek, danych i modeli.
- Hackathon 21–22.11.2026, Bydgoszcz. Wybór zadań w HackTribe do 20:00 21.11 jest nieodwracalny.

## 4. Podejścia rozważone

Wybrane przez zespół: **hybryda** (reguły i walidatory dla pól o sztywnym formacie, model open-weights dla reszty, całość sterowana konfiguracją klasy).

Warstwa ekstrakcji: własna cienka warstwa, bez LangExtract (decyzja zespołu). Powód: wynik jest zagnieżdżony i zawiera pola wyliczane, a few-shot w kodzie koliduje z „config only".

## 5. Projekt

Przepływ dla każdego PDF-a:
1. **Tekst:** warstwa tekstowa PDF (pypdf). Gdy tekstu brak lub jest śmieciowy, OCR przez Tesseract (open source).
2. **Klasyfikacja:** do klasy z konfiguracji albo `nieznany`. Klasa ma w konfiguracji opis i słowa-wskazówki. Rozstrzyga model z listą klas z konfiguracji, wskazówki służą za kontrolę.
3. **Ekstrakcja:** konfiguracja klasy (plik YAML w `classes/`) zawiera: schemat pól, opisy pól dla modelu, przykłady few-shot, walidatory formatów, reguły szczególne w języku naturalnym. Model dostaje schemat i tekst i zwraca JSON przez `response_format` (JSON schema).
4. **Cytaty:** dla każdego pola model zwraca cytat źródłowy; kod sprawdza dopasowanie do tekstu (dopasowanie przybliżone). Niezgodność oznacza obniżone zaufanie i może uruchomić ponowną próbę.
5. **Walidacja i normalizacja:** walidatory formatów (NIP, KRS, REGON, BZP `YYYY/BZP########`, TED `NNNNNN-YYYY`, IBAN, ISO-daty, kwota jako liczba). Błędny format: jedna ponowna próba, potem `null`.
Tryb ekstrakcji (przełącznik): `EXTRACTION_MODE=hybrid|llm_only` w env, nadpisywany flagą CLI `--mode`. Domyślnie `hybrid`. W `llm_only` krok 5 jest pominięty, czyli żadne walidatory ani normalizacja regexem nie ingerują w wynik, a pola zwraca sam model (nadal ze schematem i weryfikacją cytatów z kroku 4). Reguły w języku naturalnym z konfiguracji klasy działają w obu trybach. Przełącznik dotyczy całej warstwy regexowej naraz, nie pojedynczych walidatorów. Komenda `eval` przyjmuje ten sam przełącznik, więc F1 obu trybów porównujemy na 60 przykładach i wybieramy lepszy (liczba na slajd).

6. **Zapis:** `output/caseN/<nazwa>.json` w dokładnym kształcie z `oczekiwane-json/`.

Konfiguracja klasy (kluczowa dla punktacji): nowa klasa to nowy plik w `classes/`, wykrywany automatycznie. Słownik `czynnosc_powod_id` 1–11 mieszka w konfiguracji klasy `odwolanie`. Reguły (pierwszy „Zarzut" wyznacza pola `czynnosc_*`, konsorcjum oznacza dane Lidera, `prowadzacy_postepowanie` ∈ {null,1,0}, `przez-pelnomocnika` ∈ {1,0}) są opisane w konfiguracji.

Model: adres endpointu, nazwa i klucz w zmiennych środowiskowych. Początek budowy: benchmark 2–3 kandydatów open-weights (rząd 30B+, obsługa JSON schema) na 60 przykładach i wybór najlepszego.

Ewaluacja: skrypt lokalny liczy F1 per pole i łącznie na `dane/przyklad_01..60`, dostępny jako `eval` w CLI. Na nim stroimy prompty i reguły.

Dostawa: CLI (`python -m odwolania2json` plus `start.bat`), `requirements.txt`, `Dockerfile` i Docker Compose, README, instrukcja „jak dodać klasę dokumentu" z przykładem.

## 6. Znane pułapki danych

- Schemat `odwolanie.json` w repo ma komentarze `//` i nie jest poprawnym JSON-em.
- `czynnosc_powod_id`: specyfikacja podaje 12 wartości, w danych jest tylko 1–11. Słownik odtwarzamy z przykładów; ID 12 nieznane.
- `data` i `miejscowosc` są `null` w 15 z 60 przykładów.
- `pesel` jest liczbą w schemacie, ale `null` w danych treningowych.
- Dane treningowe są syntetyczne (KRS `9999…`), test jest „realny", więc możliwe skany i inne układy.

## 7. Rozstrzygnięcia po przeglądzie projektu

Odpowiedzi z materiałów:
- Schematy wyjścia są w `oczekiwane-json/` repo organizatora (kształty w przykładzie 01: `OdwolanieKIO`, `Odwolujacy[]` z `pelnomocnik`, `Zamawiajacy[]`, `ZamowieniePubliczne`; `pelnomocnictwo`: `mocodawca[]` + `pelnomocnicy[]`; `przelew`: `przelew_bankowy`). Mapowanie klasy na schemat to właśnie plik klasy.
- Skaner F1 **nie jest opublikowany** (README mówi tylko „F1 względem danych referencyjnych"). Lokalny `eval` przyjmuje założenia: porównanie po normalizacji (białe znaki, wielkość liter, format dat), pole to jednostka oceny, `null` zamiast pola brakującego jest równoważne, tablice dopasowywane po kluczu (NIP/KRS), a gdy nie da się dopasować, po kolejności. Zakładamy też, że `null` przy niepewności jest bezpieczniejszy niż zgadywanie. Metryką oceny jest F1. BLEU odrzucone (mierzy podobieństwo tekstu generowanego, a porównujemy pola strukturalne). `eval` raportuje dodatkowo pomocniczo: precision i recall osobno, exact match na poziomie dokumentu, odsetek poprawnych cytatów i odsetek `null` przy polach z wartością referencyjną.
- W 180 PDF-ach treningowych wszystkie mają warstwę tekstową (0 skanów), najdłuższy ma 11 stron. Skany w zbiorze ukrytym są możliwe, więc OCR jest wariantem awaryjnym, nie rdzeniem.
- Endpoint modelu w czasie hackathonu: własny LiteLLM zespołu (Coolify). Nazwy modeli wybieramy w benchmarku.

Moje decyzje (do sprawdzenia przez zespół):
- Konfiguracja klasy wyraża: typy pól (tekst, liczba, enum z mapowaniem, flaga 0/1, obiekt zagnieżdżony, tablica), nazwane walidatory z rejestru, wartości pochodne przez słownik mapowania, reguły w prompcie. Bez języka wyrażeń. To wystarcza dla trzech obecnych klas, a nowe walidatory dodaje się jednym wpisem w rejestrze.
- Demonstracja rozszerzalności: dodajemy własną czwartą klasę (np. `wezwanie` lub `faktura`) wyłącznie plikiem YAML i opisujemy to w instrukcji. Wejście inne niż PDF jest poza zakresem.
- Tesseract z danymi `pol` pakujemy do obrazu Docker jako zależność opcjonalną (OCR uruchamiany tylko przy braku tekstu).
- Limit czasu: brak twardego; docelowo kilka sekund na dokument przy modelu z API.
- Fałszywa klasa dokumentu: dokument `nieznany` nie generuje pliku JSON.

Pytania do organizatora/mentorów (nie do rozstrzygnięcia przez nas):
1. Wagi oceny: 50/50 (regulamin i README) czy 50/30/20 (PDF zadania).
2. Jak jury uruchamia rozwiązanie: na własnej maszynie (wtedy musi mieć dostęp do modelu) czy u nas? Czy dostarczyć endpoint modelu, czy ma on być wewnątrz Docker Compose?
3. Jak dokładnie liczone jest F1 (pola puste, tablice, nadmiarowe pliki).
4. Czy „wyłącznie open source, w tym modele" dopuszcza modele open-weights (np. Qwen, Mistral na Apache 2.0, Llama na własnej licencji), czy wymaga licencji open source w rozumieniu OSI. Zadać przed wyborem modelu.

## 8. Zostaje budowniczemu

- Wybór modelu na podstawie benchmarku.
- Format konfiguracji klasy (struktura YAML), reguły dopasowania cytatów, próg zaufania.
- Strategia ponownych prób, obsługa wielostronicowych dokumentów, logowanie `nieznany`.
- Struktura repozytorium i obraz Docker.
