# Odwołania2JSON

Zamienia PDF-y sprawy odwoławczej KIO na JSON-y zgodne ze schematem UZP (HackNation 2026, zadanie UZP).

```
input/case1/*.pdf  →  klasyfikacja  →  ekstrakcja modelem  →  walidacja  →  output/case1/<ta-sama-nazwa>.json
```

- Klasy dokumentów: `odwolanie`, `pelnomocnictwo`, `przelew`. Dokument spoza klas (`nieznany`) dostaje pusty JSON `{}` pod oryginalną nazwą pliku oraz wpis w logu.
- Każda klasa to plik YAML w `classes/`. **Nowa klasa nie wymaga zmian w kodzie** (patrz niżej).
- Dla każdego pola model podaje cytat z dokumentu, a kod sprawdza go w tekście. Ślad cytatów trafia do `trace/` (nie do `output/`).
- Tylko open source, w tym modele open-weights. Model jest wołany przez API zgodne z OpenAI (LiteLLM, vLLM, Ollama). Kod nie wymaga GPU. Wymagania organizatora (FAQ): model da się zainstalować lokalnie, a API jest hostowane w UE przez dostawcę z polityką prywatności; klucz API do używanej usługi dostarcza zespół.
- Imiona i nazwiska są zwracane w mianowniku („Mateusz Szymański”), brak informacji to `null`.

## Uruchomienie

Wymagania: [uv](https://docs.astral.sh/uv/) (instaluje Python 3.13+ i zależności), Tesseract z danymi `pol` (tylko do skanów bez warstwy tekstowej; w obrazie Docker jest w środku).

```bash
cp .env.example .env        # uzupełnij OPENAI_API_KEY, OPENAI_BASE_URL, LLM_MODEL
uv sync                      # tworzy .venv i instaluje zależności z uv.lock
mkdir -p input/case1 && cp "twoj plik.pdf" input/case1/
uv run python -m src run
```

Windows: `start.bat` (przekazuje argumenty do `run`). Docker:

```bash
cp .env.example .env
docker compose build
docker compose run --rm app            # = run na input/ → output/
docker compose run --rm app classes    # lista wczytanych klas
```

W kontenerze `localhost` to nie Twój komputer. Jeśli LiteLLM działa na hoście, ustaw `OPENAI_BASE_URL=http://host.docker.internal:4000/v1`.

### Makefile

Skróty do najczęstszych komend: `make help` (lista), `make install`, `make test`, `make run`, `make classes`, `make eval MODE=llm_only LIMIT=10 MODEL=<nazwa>`, `make eval-hybrid`, `make eval-llm-only`, `make docker-build`, `make docker-run`, `make clean`.

### Opcje `run`

| Opcja | Znaczenie |
|---|---|
| `--input`, `--output`, `--trace` | katalogi (domyślnie `input`, `output`, `trace`) |
| `--classes` | katalog z klasami YAML (domyślnie `CLASSES_DIR`, czyli `classes`) |
| `--mode hybrid\|llm_only` | tryb ekstrakcji (nadpisuje `EXTRACTION_MODE`) |
| `--workers N` | równoległość (domyślnie 4) |

Kod wyjścia to 1, gdy jakiś dokument zakończył się błędem (np. model niedostępny, brak tekstu w PDF). Dokument `nieznany` nie jest błędem.

### Zmienne środowiskowe

| Zmienna | Domyślnie | Znaczenie |
|---|---|---|
| `OPENAI_API_KEY`, `OPENAI_BASE_URL`, `LLM_MODEL` | | endpoint i model |
| `EXTRACTION_MODE` | `hybrid` | `hybrid` = model + walidatory/normalizacja; `llm_only` = sam model |
| `CLASSES_DIR` | `classes` | katalog klas |
| `CITATION_THRESHOLD` | `85` | próg dopasowania cytatu (0–100) |

## Tryby ekstrakcji

- `hybrid` (domyślny): po odpowiedzi modelu działają walidatory formatów (NIP, KRS, REGON, BZP, TED, IBAN, daty ISO, kwota). Błędny format = jedna ponowna próba, potem `null`.
- `llm_only`: bez walidatorów i normalizacji; wynik to wartości zwrócone przez model. Schemat, weryfikacja cytatów i reguły w języku naturalnym działają nadal.

## Ewaluacja

Lokalny F1 na przykładach z referencją (`data/dane/przyklad_NN/`):

```bash
uv run python -m src eval --mode hybrid
uv run python -m src eval --mode llm_only --model <nazwa> --out-json wyniki.json
uv run python -m src eval --limit 10        # szybki test
uv run python -m src eval --dump results/dump   # predykcja, referencja i różnice per dokument
uv run python -m src eval --examples 01,02,13   # tylko wybrane przykłady (make eval EXAMPLES=01,02,13)
uv run python -m src eval --cache results/cache  # cache odpowiedzi LLM na dysku (domyślnie wyłączony; też w run)
```

Raport pokazuje precision, recall i F1 per pole oraz łącznie, exact match dokumentu, poprawność klasyfikacji, odsetek poprawnych cytatów i odsetek `null` przy polach z wartością referencyjną. Skaner organizatora nie jest opublikowany, więc założenia porównania są w dokumencie projektowym (sekcja 7). `--dump` zapisuje dla każdego PDF-a predykcję, referencję, listę różnic i ślad cytatów (`<dump>/<przyklad>/<plik>.json`; `_missed.json` dla klas bez dokumentu). `run` zapisuje dodatkowo `trace/_summary.json` (klasa, błąd, plik wyjściowy, tokeny per plik). Wyniki pomiarów: `docs/benchmark.md`.

## Jak dodać klasę dokumentu

Nic nie edytujesz w Pythonie. Przykład: `classes_examples/faktura.yaml`.

1. Skopiuj plik do `classes/` (nazwa pliku = `name` w środku): `cp classes_examples/faktura.yaml classes/`.
2. Opisz klasę: `description` (model rozpoznaje po nim klasę), `hints` (słowa kontrolne, opcjonalnie; dopasowanie bez polskich znaków i wielkości liter, rozstrzelone tytuły typu „P E Ł N O” są sklejane), `hint_veto` (`always` domyślnie: brak hintu unieważnia wybór modelu; `other_class`: tylko gdy pasują hinty innej klasy; `never`), `rules` (reguły w języku naturalnym), `examples` (few-shot, opcjonalnie), `requires` (opcjonalna kontrola spójności w trybie hybrid: `when: Sekcja.pole`, `then: [Sekcja.inne_pole]`; gdy `when` ma wartość, a pole z `then` jest puste, ekstrakcja jest raz ponawiana z tą uwagą).
3. Opisz pola w `fields`. Typy: `text`, `number`, `integer`, `flag` (1/0), `enum` (z `options`), `object`, `array`. Pole może mieć `validator` (`nip`, `krs`, `regon`, `bzp`, `ted`, `iban`, `date`, `amount`, `email`, `pesel`), `description` dla modelu, `nullable`. Dla `array` podaj `key` (pola identyfikujące element, używane przez `eval`). Pole wyliczane ze słownika: `derive: {from: pole, map: {...}}`.
4. Sprawdź: `uv run python -m src classes`. Od tej chwili klasyfikator widzi nową klasę, a `run` zapisuje jej JSON.

Nowy walidator formatu to jeden wpis w `src/validators.py` (`REGISTRY`).

## Struktura

```
src/               kod (generyczny silnik, nie zna nazw klas)
classes/          klasy dokumentów (YAML)
classes_examples/ przykład klasy do skopiowania
docs/             projekt, plan, schematy organizatora, benchmark
data/dane/        60 przykładów z referencją (organizator)
tests/            testy (pytest)
```

Testy: `make test` (`uv run pytest`). Lint i format: `make lint`, `make format` (ruff). Zależności deweloperskie instaluje `uv sync`. `requirements.txt` (wymóg dostawy) generuje `make requirements`.

## Licencje

Zależności: pypdf (BSD), pydantic (MIT), PyYAML (MIT), openai SDK (Apache-2.0), RapidFuzz (MIT), pytesseract (Apache-2.0), pypdfium2 (Apache-2.0/BSD), python-dotenv (BSD). Tesseract: Apache-2.0. Licencja wybranego modelu: patrz `docs/benchmark.md` (po wyborze).
