# Odwołania2JSON Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** CLI, które zamienia PDF-y spraw KIO z `input/caseN/` na JSON-y w `output/caseN/` zgodne ze schematami UZP, z klasami dokumentów definiowanymi wyłącznie plikami YAML.

**Architecture:** Generyczny silnik (tekst z PDF → klasyfikacja → ekstrakcja modelem ze schematu z YAML → weryfikacja cytatów → walidatory/normalizacja → zapis). Cała wiedza o klasach siedzi w `classes/*.yaml`; Python zna tylko typy pól i rejestr walidatorów. Model wołany przez API zgodne z OpenAI; przełącznik `EXTRACTION_MODE=hybrid|llm_only` pomija warstwę walidatorów.

**Tech Stack:** Python 3.13+, pypdf, pydantic v2, PyYAML, openai SDK (klient OpenAI-compatible), rapidfuzz, pytesseract + pypdfium2 (OCR awaryjny), pytest. Docker + Docker Compose.

**Spec:** `docs/superpowers/specs/2026-11-21-odwolania2json-design.md` (czytać razem z planem; kontekst danych i pułapek w `CLAUDE.md`).

## Global Constraints

- Python 3.13+, zależności w `requirements.txt`, bez GPU na docelowej maszynie; model tylko przez API zgodne z OpenAI (LiteLLM/vLLM/Ollama).
- Wyłącznie open source, w tym modele open-weights. Żadnego Gemini/Claude/GPT w rozwiązaniu (w kodzie, testach ani konfiguracji domyślnej).
- Nowa klasa dokumentu = nowy plik YAML w `classes/`; dodanie klasy nie może wymagać edycji Pythona. Żaden moduł w `odwolania2json/` nie zawiera nazw `odwolanie`, `pelnomocnictwo`, `przelew` (pilnuje tego test w Task 2).
- Nie zgadywać: pole niepewne lub z błędnym formatem po jednej ponownej próbie = `null`.
- Wyjście: `output/caseN/<ta-sama-nazwa-co-PDF>.json` w dokładnym kształcie z `docs/schematy/`. Dokument spoza klas (`nieznany`): bez pliku JSON, wpis w logu. Poza JSON-ami nic nie ląduje w `output/` (ślad cytatów idzie do `trace/`).
- Formaty: daty ISO `YYYY-MM-DD`; BZP `YYYY/BZP########` (bez spacji); TED `NNNNNN-YYYY` (także z `YYYY/S ###-NNNNNN`); IBAN jako 26 cyfr bez spacji i bez `PL`; `prowadzacy_postepowanie` ∈ {null,1,0}; `przez-pelnomocnika` ∈ {1,0}; `czynnosc_powod_id` ∈ 1–11; `pesel` jako liczba lub `null`; kwota jako liczba.
- Reguły danych: `czynnosc_*` tylko z pierwszego „Zarzutu"; konsorcjum = dane Lidera.
- `EXTRACTION_MODE=hybrid|llm_only` (env), nadpisywany flagą `--mode`; domyślnie `hybrid`. `llm_only` pomija walidatory i normalizację, ale nie schemat, cytaty ani reguły w języku naturalnym.
- Zmienne env (nazwy z `.env.example` zespołu): `OPENAI_API_KEY`, `OPENAI_BASE_URL`, `LLM_MODEL`; dodatkowo `EXTRACTION_MODE`, `CLASSES_DIR` (domyślnie `classes`), `CITATION_THRESHOLD` (domyślnie 85).
- Dokumentacja i komunikaty dla użytkownika po polsku; identyfikatory w kodzie po angielsku, z wyjątkiem nazw pól schematu UZP.
- Małe commity na branchu `feat/implementation`; to submoduł, więc po zmergowaniu trzeba zaktualizować gitlink w repo głównym.

## Review Focus

Wejścia, o które spec milczy, a które ugryzą użytkownika (każde ma test w wymienionym tasku):

1. PDF bez warstwy tekstowej, gdy Tesseract nie jest zainstalowany lub OCR rzuca wyjątek: dokument pominięty z wpisem w logu, batch idzie dalej (Task 6, 10).
2. Endpoint modelu zwraca 429/timeout/niepoprawny JSON w środku batcha: ponowienie z backoffem, po wyczerpaniu ten jeden plik pominięty, reszta przetworzona, kod wyjścia ≠ 0 tylko gdy coś padło (Task 7, 10).
3. Dokument dłuższy niż limit tekstu (treningowe mają maks. 11 stron, ukryty zbiór może mieć dłuższe): deterministyczne obcięcie początek + koniec ze znacznikiem, model dostaje informację o niepełności, flaga `truncated` w śladzie, bez wyjątku (Task 9).
4. Nazwy plików ze spacjami, polskimi znakami, `.PDF` wielkimi literami, pliki nie-PDF, pusty `input/`, katalogi zagnieżdżone: spacje i diakrytyki w nazwie wyjściowej zachowane, nie-PDF ignorowane, pusty katalog = komunikat i kod 0 (Task 10).
5. Identyfikatory w „realnym" formacie: NIP `527-000-00-00` / `NIP: 5270000000`, KRS bez zer wiodących, IBAN z `PL` i spacjami, TED `2025/S 123-456789`, daty `13.10.2025` i `13 października 2025 r.`: normalizowane do formatów docelowych (Task 4).

---

## File Structure

```
odwolania2json/
  __init__.py  __main__.py
  settings.py      # Settings.from_env()
  classconfig.py   # modele YAML klasy + load_classes()
  schema.py        # build_response_schema(), unwrap()
  validators.py    # rejestr walidatorów/normalizatorów
  citations.py     # citation_score()
  textextract.py   # read_pdf(), OCR awaryjny
  llm.py           # LLM protocol, OpenAICompatLLM
  classify.py      # classify()
  extract.py       # extract()
  pipeline.py      # process_text(), process_pdf(), run_batch()
  evaluate.py      # flatten(), score_document(), evaluate()
  cli.py           # argparse: run | eval | classes
classes/           # przelew.yaml, pelnomocnictwo.yaml, odwolanie.yaml
classes_examples/  # faktura.yaml (demo "config only", nie ładowana domyślnie)
tests/             # conftest.py (FakeLLM, fixtures), test_*.py
scripts/           # extract_czynnosc_map.py (jednorazowo, Task 14)
Dockerfile  docker-compose.yml  start.bat  requirements.txt  README.md
```

---

### Task 1: Szkielet projektu i ustawienia

**Files:**
- Create: `requirements.txt`, `requirements-dev.txt`, `pytest.ini`, `odwolania2json/__init__.py`, `odwolania2json/__main__.py`, `odwolania2json/settings.py`, `tests/test_settings.py`
- Modify: `.env.example`

**Interfaces:**
- Produces: `Settings` (pydantic `BaseModel`): `openai_api_key: str`, `openai_base_url: str`, `llm_model: str`, `extraction_mode: Literal["hybrid","llm_only"]`, `classes_dir: Path`, `citation_threshold: float`; `Settings.from_env(env: Mapping[str,str] | None = None) -> Settings` (brak `env` = `os.environ`, wczytuje też `.env` jeśli istnieje).

- [ ] **Step 1:** `git merge origin/chore/env-example` (`.env.example` kolegi z nazwami zmiennych; jeśli już jest na `main`, pomiń). Dopisz do niego `EXTRACTION_MODE=hybrid`, `CLASSES_DIR=classes`, `CITATION_THRESHOLD=85`.
- [ ] **Step 2: Failing tests** w `tests/test_settings.py`: `test_defaults` (pusty env poza kluczem → `extraction_mode == "hybrid"`, `classes_dir == Path("classes")`, `citation_threshold == 85`), `test_mode_from_env` (`EXTRACTION_MODE=llm_only` → `"llm_only"`), `test_invalid_mode_rejected` (`EXTRACTION_MODE=foo` → `ValidationError`).
- [ ] **Step 3:** Run `pytest tests/test_settings.py -v`. Expected: FAIL (ModuleNotFoundError).
- [ ] **Step 4:** Utwórz `requirements.txt` (`pypdf`, `pydantic>=2`, `pyyaml`, `openai>=1`, `rapidfuzz`, `pytesseract`, `pypdfium2`, `python-dotenv`), `requirements-dev.txt` (`-r requirements.txt`, `pytest`), `pytest.ini` (`testpaths = tests`), pakiet z `__main__.py` wołającym `cli.main()` (na razie `NotImplementedError` zastąpiony w Task 10) i `Settings`. Zainstaluj: `python -m venv .venv && .venv/bin/pip install -r requirements-dev.txt`.
- [ ] **Step 5:** Run `pytest tests/test_settings.py -v`. Expected: PASS.
- [ ] **Step 6: Commit** `feat: szkielet projektu i Settings`.

---

### Task 2: Konfiguracja klasy (YAML → modele)

**Files:**
- Create: `odwolania2json/classconfig.py`, `tests/test_classconfig.py`, `tests/test_no_hardcoded_classes.py`

**Interfaces:**
- Produces:
  - `FieldSpec` (pydantic): `name: str`, `type: Literal["text","number","integer","flag","enum","object","array"]`, `description: str = ""`, `validator: str | None` (nazwa z rejestru, Task 4), `options: dict[int | str, str] | None` (dla `enum`: wartość wyjściowa → opis dla modelu), `fields: list[FieldSpec] = []` (dla `object` i elementów `array`), `key: list[str] = []` (klucze dopasowania elementów tablicy w `eval`), `derive: Derive | None` (`Derive(from_field: str, map: dict[int | str, str])`, pole wyliczane ze słownika zamiast z modelu; alias YAML `from`), `nullable: bool = True`.
  - `ClassConfig`: `name: str`, `description: str`, `hints: list[str]`, `rules: list[str]`, `examples: list[dict]` (few-shot: `{"text": str, "output": dict}`), `fields: list[FieldSpec]`.
  - `load_classes(directory: Path) -> dict[str, ClassConfig]` (czyta `*.yaml`; `name` musi równać się nazwie pliku bez rozszerzenia; zły plik → `ClassConfigError(path, message)`).

- [ ] **Step 1: Failing tests:** `test_loads_valid_class` (tmp YAML z polami `text`, `enum` z `options`, `array` z `key`, → `cfg.fields[1].options[4] == "..."`), `test_name_must_match_filename`, `test_unknown_field_type_rejected`, `test_array_requires_fields`, `test_derive_must_reference_sibling` (`from` wskazuje nieistniejące pole → błąd), `test_empty_dir_returns_empty_dict`. W `test_no_hardcoded_classes.py`: `test_no_class_names_in_package` — grep po `odwolania2json/*.py` na `odwolanie|pelnomocnictwo|przelew` (case-insensitive), oczekiwane 0 trafień.
- [ ] **Step 2:** Run `pytest tests/test_classconfig.py tests/test_no_hardcoded_classes.py -v`. Expected: FAIL.
- [ ] **Step 3:** Implement `classconfig.py` zgodnie z sygnaturami; walidacja spójności w `model_validator`.
- [ ] **Step 4:** Run the same command. Expected: PASS.
- [ ] **Step 5: Commit** `feat: wczytywanie konfiguracji klas z YAML`.

---

### Task 3: Schemat odpowiedzi modelu i rozpakowanie wyniku

**Files:**
- Create: `odwolania2json/schema.py`, `tests/test_schema.py`

**Interfaces:**
- Consumes: `ClassConfig`, `FieldSpec` (Task 2).
- Produces:
  - `build_response_schema(cfg: ClassConfig) -> dict`: JSON Schema (`type: object`, `additionalProperties: false`, wszystkie klucze `required`) dla `response_format`. Każdy liść ma postać `{"value": <typ lub null>, "quote": <string lub null>}`; `object` i `array` zachowują zagnieżdżenie; pola z `derive` **nie** trafiają do schematu; `enum` ma `enum: [...opcje, null]`; `flag` ma `enum: [1, 0, null]`.
  - `unwrap(raw: dict, cfg: ClassConfig) -> tuple[dict, dict[str, str | None]]`: zwraca (dane w kształcie wyjścia UZP z doliczonymi polami `derive`, mapa ścieżka → cytat); ścieżki w stylu `Odwolujacy[0].krs`.

- [ ] **Step 1: Failing tests:** `test_leaf_has_value_and_quote`, `test_derived_field_not_in_schema`, `test_enum_includes_null_and_options`, `test_array_items_schema`, `test_unwrap_shapes_output_like_uzp` (wejście z opakowanymi liśćmi → zwykłe wartości, tablica obiektów zachowana), `test_unwrap_applies_derive` (`czynnosc_powod_id=9` → `czynnosc_opis` ze słownika), `test_unwrap_derive_null_when_source_null`, `test_unwrap_collects_quotes_by_path`.
- [ ] **Step 2:** Run `pytest tests/test_schema.py -v`. Expected: FAIL.
- [ ] **Step 3:** Implement rekurencyjnie po `FieldSpec`.
- [ ] **Step 4:** Run `pytest tests/test_schema.py -v`. Expected: PASS.
- [ ] **Step 5: Commit** `feat: schemat odpowiedzi modelu i unwrap`.

---

### Task 4: Walidatory i normalizatory

**Files:**
- Create: `odwolania2json/validators.py`, `tests/test_validators.py`

**Interfaces:**
- Produces:
  - `REGISTRY: dict[str, Callable[[Any], Any]]` — każda funkcja zwraca wartość znormalizowaną albo rzuca `ValueError`. Klucze: `nip` (10 cyfr, bez myślników/spacji/prefiksu `NIP`; sama długość i cyfry, bez sumy kontrolnej), `krs` (10 cyfr, dopełnia zerami wiodącymi do 10), `regon` (9 lub 14 cyfr), `bzp` (`YYYY/BZP########`; usuwa spacje, akceptuje sufiks `/##`), `ted` (`NNNNNN-YYYY`; konwertuje `YYYY/S ###-NNNNNN`), `iban` (26 cyfr; usuwa spacje i prefiks `PL`), `date` (→ ISO; akceptuje `DD.MM.YYYY`, `YYYY-MM-DD`, `13 października 2025 r.`), `amount` (→ `float`; akceptuje `10 000,00`, `10000.00`, `10.000,00 zł`), `email`, `pesel` (11 cyfr → `int`).
  - `validate_value(spec: FieldSpec, value: Any) -> Any` — `None` przechodzi bez zmian; gdy `spec.validator` jest ustawiony, woła rejestr; niezarejestrowana nazwa → `KeyError` (błąd konfiguracji, wykrywany też w `load_classes`: dopisz w Task 2 sprawdzenie nazw przy użyciu `REGISTRY`). Dodatkowo `flag` wymusza ∈ {1,0}, `enum` wymusza ∈ `options`.

- [ ] **Step 1: Failing tests** (parametryzowane, dane z Review Focus 5): `nip("527-000-00-00") == "5270000000"`, `nip("NIP: 5270000000") == "5270000000"`, `nip("123")` → `ValueError`; `krs("54588") == "0000054588"`; `iban("PL 60 1010 1010 0081 3622 3100 0000") == "60101010100081362231000000"`; `ted("2025/S 123-456789") == "456789-2025"`, `ted("641651-2025") == "641651-2025"`; `bzp("2026/BZP 00999778") == "2026/BZP00999778"`; `date("13.10.2025") == "2025-10-13"`, `date("13 października 2025 r.") == "2025-10-13"`, `date("2025-13-45")` → `ValueError`; `amount("10 000,00") == 10000.0`; `validate_value` dla `flag` ze wartością `2` → `ValueError`; `test_registry_names_used_by_classes_exist` (pusty dopóki brak klas, uruchamiany ponownie w Task 12–14).
- [ ] **Step 2:** Run `pytest tests/test_validators.py -v`. Expected: FAIL.
- [ ] **Step 3:** Implement; polskie nazwy miesięcy w słowniku genitivu.
- [ ] **Step 4:** Run `pytest tests/test_validators.py -v`. Expected: PASS.
- [ ] **Step 5: Commit** `feat: rejestr walidatorów i normalizatorów`.

---

### Task 5: Weryfikacja cytatów

**Files:**
- Create: `odwolania2json/citations.py`, `tests/test_citations.py`

**Interfaces:**
- Produces: `citation_score(quote: str | None, text: str) -> float` (0–100; `None` lub pusty cytat → `0.0`; normalizuje białe znaki, wielkość liter i łączniki; `rapidfuzz.fuzz.partial_ratio`); `citation_ok(quote, text, threshold: float) -> bool`.

- [ ] **Step 1: Failing tests:** `test_exact_substring_scores_100`, `test_whitespace_and_case_insensitive`, `test_line_break_inside_quote_ok` (cytat z `\n` w środku tekstu PDF), `test_hallucinated_quote_below_threshold` (< 85), `test_none_quote_zero`, `test_pdf_hyphenation_tolerated` (słowo złamane `zamó-\nwienia` w tekście, w cytacie `zamówienia`).
- [ ] **Step 2:** Run `pytest tests/test_citations.py -v`. Expected: FAIL.
- [ ] **Step 3:** Implement; normalizacja usuwa `-\n` przed sklejeniem białych znaków.
- [ ] **Step 4:** Run `pytest tests/test_citations.py -v`. Expected: PASS.
- [ ] **Step 5: Commit** `feat: weryfikacja cytatów źródłowych`.

---

### Task 6: Tekst z PDF i OCR awaryjny

**Files:**
- Create: `odwolania2json/textextract.py`, `tests/test_textextract.py`

**Interfaces:**
- Produces: `DocText` (dataclass): `text: str`, `pages: int`, `ocr_used: bool`; `looks_garbage(text: str, pages: int) -> bool` (średnio < 50 znaków nie-białych na stronę lub < 60% znaków alfanumerycznych/polskich/interpunkcji); `read_pdf(path: Path) -> DocText` (pypdf; jeśli `looks_garbage`, próba OCR: render `pypdfium2` + `pytesseract` z `lang="pol"`; wyjątek OCR → `DocText(text="", ocr_used=False)` + ostrzeżenie w logu, nie wyjątek); `UnreadableDocument` nie jest rzucany, brak tekstu sygnalizuje pusty `text`.

- [ ] **Step 1: Failing tests:** `test_text_pdf_read` (`data/szablon-aplikacja/input/case1/przyklad odwolanie.pdf` → `"Odwo"` w tekście lub inny stały fragment potwierdzony ręcznie, `ocr_used is False`, `pages >= 1`), `test_looks_garbage_empty_and_symbols`, `test_ocr_failure_returns_empty` (monkeypatch OCR rzucającego wyjątek na PDF z `looks_garbage=True` → `text == ""`, brak wyjątku; Review Focus 1), `test_ocr_used_when_no_text_layer` (monkeypatch `pypdf` zwracającego `""`, OCR zwraca `"tekst"` → `ocr_used is True`).
- [ ] **Step 2:** Run `pytest tests/test_textextract.py -v`. Expected: FAIL.
- [ ] **Step 3:** Implement; import OCR leniwie wewnątrz funkcji, żeby brak Tesseracta nie psuł importu.
- [ ] **Step 4:** Run `pytest tests/test_textextract.py -v`. Expected: PASS.
- [ ] **Step 5: Commit** `feat: odczyt tekstu z PDF z OCR awaryjnym`.

---

### Task 7: Klient modelu i FakeLLM

**Files:**
- Create: `odwolania2json/llm.py`, `tests/conftest.py`, `tests/test_llm.py`

**Interfaces:**
- Produces:
  - `LLM` (`typing.Protocol`): `complete_json(system: str, user: str, schema: dict, name: str) -> dict`.
  - `LLMError(Exception)` — po wyczerpaniu prób.
  - `OpenAICompatLLM(settings: Settings, max_attempts: int = 4, sleep: Callable[[float], None] = time.sleep)` — `chat.completions.create` z `response_format={"type":"json_schema","json_schema":{"name": name,"schema": schema,"strict": True}}`, `temperature=0`; ponowienia z wykładniczym backoffem dla 429/5xx/timeout i dla odpowiedzi niebędącej poprawnym JSON-em; potem `LLMError`.
  - W `tests/conftest.py`: `FakeLLM(responses: list[dict | Exception])` zwracający kolejne odpowiedzi i zapisujący wywołania w `.calls`; fixture `fake_llm`.

- [ ] **Step 1: Failing tests** (z fałszywym klientem `openai` wstrzykiwanym przez parametr `client`): `test_returns_parsed_json`, `test_retries_on_429_then_succeeds` (sleep zamockowany, 2 próby), `test_retries_on_invalid_json`, `test_raises_llmerror_after_max_attempts` (Review Focus 2), `test_sends_json_schema_response_format`.
- [ ] **Step 2:** Run `pytest tests/test_llm.py -v`. Expected: FAIL.
- [ ] **Step 3:** Implement (dodaj opcjonalny argument konstruktora `client` do wstrzykiwania w testach).
- [ ] **Step 4:** Run `pytest tests/test_llm.py -v`. Expected: PASS.
- [ ] **Step 5: Commit** `feat: klient modelu OpenAI-compatible z ponowieniami`.

---

### Task 8: Klasyfikator

**Files:**
- Create: `odwolania2json/classify.py`, `tests/test_classify.py`

**Interfaces:**
- Consumes: `LLM`, `ClassConfig`, `DocText`.
- Produces: `UNKNOWN = "nieznany"`; `classify(doc: DocText, classes: dict[str, ClassConfig], llm: LLM) -> str`. Prompt zawiera `name` i `description` każdej klasy oraz pierwsze 3000 znaków tekstu; schemat odpowiedzi to enum nazw klas plus `"nieznany"`. Kontrola wskazówek: jeśli klasa wybrana przez model ma niepuste `hints` i żadna nie występuje w tekście (bez względu na wielkość liter), wynik to `UNKNOWN`. Pusty `doc.text` → `UNKNOWN` bez wywołania modelu. Brak klas → `UNKNOWN`.

- [ ] **Step 1: Failing tests (z `FakeLLM`):** `test_returns_model_class_when_hint_present`, `test_hint_control_downgrades_to_unknown`, `test_class_without_hints_trusted`, `test_empty_text_unknown_without_llm_call` (`fake_llm.calls == []`), `test_prompt_lists_all_classes_from_config` (klasy z tmp YAML trafiają do promptu i do enumu schematu — dowód „config only"), `test_no_classes_unknown`.
- [ ] **Step 2:** Run `pytest tests/test_classify.py -v`. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run `pytest tests/test_classify.py -v`. Expected: PASS.
- [ ] **Step 5: Commit** `feat: klasyfikator dokumentów sterowany konfiguracją`.

---

### Task 9: Ekstrakcja (prompt, cytaty, walidacja, tryby)

**Files:**
- Create: `odwolania2json/extract.py`, `tests/test_extract.py`

**Interfaces:**
- Consumes: `build_response_schema`, `unwrap`, `validate_value`, `citation_ok`, `LLM`, `Settings`.
- Produces:
  - `Extraction` (dataclass): `data: dict`, `quotes: dict[str, str | None]`, `citation_ok: dict[str, bool]` (tylko pola z wartością ≠ null), `nulled: list[str]` (ścieżki wyzerowane przez walidatory), `retries: int`, `truncated: bool`.
  - `MAX_CHARS = 60_000`; `HEAD_RATIO = 0.7`; `truncate(text: str) -> tuple[str, bool]` (tekst ≤ `MAX_CHARS` bez zmian i `False`; dłuższy: pierwsze `HEAD_RATIO * MAX_CHARS` znaków + `\n[...pominięto N znaków...]\n` + końcówka dopełniająca do `MAX_CHARS`, i `True`). Gdy `truncated`, prompt systemowy dostaje zdanie: „Tekst jest niepełny (środek pominięto). Dla pól bez dowodu w widocznym tekście zwracaj null." Cytaty weryfikowane względem tekstu wysłanego do modelu. Nie ma chunkingu ani drugiego przebiegu; do rozważenia dopiero, gdy `eval` pokaże wpływ `truncated` na F1 (zapis w `docs/benchmark.md`).
  - `extract(doc: DocText, cfg: ClassConfig, llm: LLM, mode: Literal["hybrid","llm_only"], threshold: float) -> Extraction`. Prompt systemowy składa się z: opisu klasy, opisu pól, `rules`, `examples` (few-shot) oraz instrukcji „zwracaj `null` gdy nie jesteś pewien; w `quote` dosłowny fragment tekstu". Przebieg: wywołanie → `unwrap` → (tylko `hybrid`) `validate_value` na każdym liściu; jeśli są pola z błędnym formatem lub niezgodnym cytatem, **jedna** ponowna próba z listą problemów w wiadomości użytkownika; po niej błędny format → `null` (dopisane do `nulled`), niezgodny cytat zostaje z `citation_ok[path] = False` (wartość nie jest kasowana). W `llm_only` brak `validate_value` (też brak normalizacji), cytaty nadal liczone, ponowna próba tylko dla cytatów.

- [ ] **Step 1: Failing tests (z `FakeLLM` i tmp klasą):** `test_hybrid_normalizes_value` (model zwraca `"527-000-00-00"` → `"5270000000"`), `test_llm_only_leaves_value_raw` (ten sam input, wynik `"527-000-00-00"`; brak `nulled`), `test_invalid_format_retried_once_then_nulled` (dwie odpowiedzi złe → `None`, `retries == 1`, ścieżka w `nulled`), `test_retry_fixes_value` (druga odpowiedź poprawna → wartość zachowana), `test_bad_citation_flagged_not_nulled`, `test_good_citation_ok`, `test_rules_and_examples_in_prompt` (`fake_llm.calls[0]` zawiera tekst reguły i przykładu), `test_truncate_short_text_unchanged` (`(text, False)`), `test_truncate_keeps_head_and_tail_with_marker` (tekst 200 000 znaków: długość ≤ `MAX_CHARS + len(znacznika)`, początek i koniec obecne, znacznik w środku, flaga `True`; Review Focus 3), `test_truncated_prompt_tells_model_text_incomplete`, `test_extract_long_doc_sets_truncated_and_no_exception`.
- [ ] **Step 2:** Run `pytest tests/test_extract.py -v`. Expected: FAIL.
- [ ] **Step 3:** Implement; budowanie opisu pól rekurencyjnie z `FieldSpec.description` i `options`.
- [ ] **Step 4:** Run `pytest tests/test_extract.py -v`. Expected: PASS.
- [ ] **Step 5: Commit** `feat: ekstrakcja z cytatami, walidacją i trybem llm_only`.

---

### Task 10: Pipeline wsadowy i CLI `run`

**Files:**
- Create: `odwolania2json/pipeline.py`, `odwolania2json/cli.py`, `start.bat`, `tests/test_pipeline.py`, `tests/test_cli.py`
- Modify: `odwolania2json/__main__.py`

**Interfaces:**
- Consumes: Tasks 2–9.
- Produces:
  - `DocResult` (dataclass): `path: Path`, `class_name: str`, `data: dict | None`, `extraction: Extraction | None`, `error: str | None`.
  - `process_text(doc: DocText, classes, llm, mode, threshold) -> DocResult` (bez ścieżki; używane przez `eval`) — klasyfikuje i ekstrahuje; `nieznany` → `data=None`.
  - `process_pdf(path: Path, classes, llm, settings: Settings) -> DocResult` — łapie `LLMError` i inne wyjątki do `error`, nigdy nie przerywa batcha.
  - `run_batch(input_dir: Path, output_dir: Path, trace_dir: Path, classes, llm, settings, workers: int = 4) -> list[DocResult]` — rekurencyjnie `**/*.pdf` (bez względu na wielkość liter rozszerzenia), odtwarza strukturę katalogów `caseN/`, zapisuje `<stem>.json` (`ensure_ascii=False`, `indent=2`, nazwa pliku jak w wejściu), ślad (cytaty, `citation_ok`, `nulled`, `retries`, `truncated`) do `trace_dir/<caseN>/<stem>.json`; `nieznany` i błędy tylko w logu.
  - CLI: `python -m odwolania2json run [--input input] [--output output] [--trace trace] [--mode hybrid|llm_only] [--workers 4]`; `python -m odwolania2json classes` wypisuje wczytane klasy. Kod wyjścia 1 tylko gdy jakikolwiek dokument zakończył się błędem (nie dla `nieznany`).
  - `start.bat`: `python -m odwolania2json run %*`.

- [ ] **Step 1: Failing tests (FakeLLM, `read_pdf` zmockowany lub PDF z `data/dane/przyklad_01/`):** `test_writes_json_with_same_stem_and_structure` (`input/case1/Mój plik.PDF` → `output/case1/Mój plik.json`; Review Focus 4), `test_unknown_writes_no_file_and_logs`, `test_non_pdf_ignored`, `test_empty_input_dir_exit_0_with_message`, `test_llm_failure_on_one_file_does_not_stop_batch_exit_1` (Review Focus 2), `test_unreadable_pdf_skipped_with_log` (Review Focus 1), `test_trace_written_outside_output`, `test_rerun_is_idempotent` (drugie uruchomienie nadpisuje bez błędu), `test_mode_flag_overrides_env`, `test_same_stem_in_two_cases_does_not_collide`.
- [ ] **Step 2:** Run `pytest tests/test_pipeline.py tests/test_cli.py -v`. Expected: FAIL.
- [ ] **Step 3:** Implement; `ThreadPoolExecutor` dla `workers`; logowanie przez `logging` (poziom INFO na stderr).
- [ ] **Step 4:** Run `pytest -v`. Expected: PASS (cały zestaw).
- [ ] **Step 5: Commit** `feat: pipeline wsadowy i CLI run`.

---

### Task 11: Ewaluacja F1 (`eval`)

**Files:**
- Create: `odwolania2json/evaluate.py`, `tests/test_evaluate.py`
- Modify: `odwolania2json/cli.py`

**Interfaces:**
- Consumes: `process_text`, `read_pdf`, `ClassConfig` (`FieldSpec.key`).
- Produces:
  - `flatten(data: dict, cfg: ClassConfig) -> dict[str, Any]` — liście po ścieżkach; elementy tablic indeksowane wartością pól z `FieldSpec.key` (np. `Odwolujacy[krs=0000054588].nazwa`), a gdy brak klucza lub wartości, po kolejności (`[0]`). Wartości normalizowane: `strip`, zwinięte białe znaki, `casefold` dla tekstu, `int`/`float` porównywane liczbowo.
  - `Counts` (dataclass): `tp`, `fp`, `fn` (sumowane per pole przez `Counter`).
  - `score_document(pred: dict | None, ref: dict, cfg: ClassConfig) -> dict[str, Counts]` — reguły: oba `null`/brak → pomijane; pred ≠ null i = ref → TP; pred ≠ null i ≠ ref → FP + FN; pred = null i ref ≠ null → FN; pred ≠ null i ref = null → FP; pred `None` (dokument rozpoznany błędnie lub `nieznany`) → wszystkie pola ref to FN.
  - `Report` (dataclass): `per_field: dict[str, Counts]`, `micro_f1`, `precision`, `recall`, `doc_exact_match`, `classification_accuracy`, `citation_ok_rate`, `null_rate_on_ref_valued`; `Report.render() -> str` (tabela tekstowa).
  - `evaluate(data_dir: Path, classes, llm, settings, limit: int | None = None, workers: int = 4) -> Report` — dla każdego `przyklad_NN`: czyta wszystkie PDF-y, klasyfikuje, ekstrahuje i porównuje z `<klasa>.json` (referencja dobierana po **nazwie klasy = nazwa pliku JSON**, więc nazwa PDF-a nie ma znaczenia). Predykcja klasy, dla której nie ma referencji, liczy się jako FP wszystkich jej pól.
  - CLI: `python -m odwolania2json eval [--data data/dane] [--mode ...] [--model NAZWA] [--limit N] [--workers 4] [--out-json PLIK]`; `--model` nadpisuje `LLM_MODEL`.

- [ ] **Step 1: Failing tests (czyste, bez LLM):** `test_flatten_arrays_by_key`, `test_flatten_arrays_fallback_to_index`, `test_perfect_prediction_f1_1`, `test_wrong_value_counts_fp_and_fn`, `test_null_vs_missing_equivalent`, `test_pred_null_ref_value_is_fn`, `test_pred_value_ref_null_is_fp`, `test_misclassified_doc_all_fn`, `test_normalization_case_and_whitespace`, `test_array_order_irrelevant_when_key_matches` (zamienione `pelnomocnicy` z kluczem `imie_nazwisko`), `test_report_aggregates_micro_f1`.
- [ ] **Step 2:** Run `pytest tests/test_evaluate.py -v`. Expected: FAIL.
- [ ] **Step 3:** Implement; `evaluate` używa `process_text` i `read_pdf`.
- [ ] **Step 4:** Run `pytest tests/test_evaluate.py -v`. Expected: PASS.
- [ ] **Step 5: Commit** `feat: lokalna ewaluacja F1 (eval)`.

---

### Task 12: Klasa `przelew` (walking skeleton) i pierwszy pomiar

**Files:**
- Create: `classes/przelew.yaml`, `tests/test_shipped_classes.py`

**Interfaces:**
- Consumes: format YAML z Task 2. Schemat docelowy: `docs/schematy/przelew.json`, referencje `data/dane/przyklad_*/przelew.json`.

- [ ] **Step 1: Failing test** `test_shipped_classes_load_and_validators_exist` (`load_classes(Path("classes"))` nie rzuca; każdy `validator` istnieje w `REGISTRY`; każde `derive.from_field` istnieje; dla `przelew`: pola `przelew_bankowy.{data_operacji,kwota,na_rachunek,numer_transakcji,tytul,z_rachunku}` oraz typy `date`→`validator: date`, `kwota`→`amount`, rachunki→`iban`). Run → FAIL.
- [ ] **Step 2:** Napisz `classes/przelew.yaml`: `description` (potwierdzenie przelewu bankowego), `hints` (`przelew`, `rachunek`, `kwota`), opisy pól, `rules` (np. `tytul` dosłownie jak w dokumencie; `numer_transakcji` null gdy brak), ≥1 few-shot z przykładu 01. Run `pytest tests/test_shipped_classes.py -v` → PASS.
- [ ] **Step 3: Pomiar (wymaga endpointu z `.env`):** `python -m odwolania2json eval --limit 60 --mode hybrid` i `--mode llm_only`; wpisz F1 per pole i łącznie dla klasy `przelew` do `docs/benchmark.md` (tabela: tryb, F1, precision, recall, ścieżka błędów). Jeśli F1 < 0,9, popraw opisy/reguły i powtórz; każdą iterację odnotuj w tym samym pliku.
- [ ] **Step 4: Commit** `feat: klasa przelew i pierwszy pomiar F1`.

---

### Task 13: Klasa `pelnomocnictwo`

**Files:**
- Create: `classes/pelnomocnictwo.yaml`
- Modify: `tests/test_shipped_classes.py`, `docs/benchmark.md`

**Interfaces:**
- Schemat: `docs/schematy/pelnomocnictwo.json`. Tablice: `mocodawca` (`key: [data.krs, data.nip]` lub `[data.nazwa]` dla osoby fizycznej), `podpisujacy` (`key: [imie_nazwisko]`), `pelnomocnicy` (`key: [imie_nazwisko]`). `data.typ` jako `enum` {`osoba_prawna`, `osoba_fizyczna`}; `pesel` walidator `pesel` (liczba, `null` gdy brak); `imie_nazwisko` pełnomocnika w mianowniku (reguła).

- [ ] **Step 1:** Rozszerz `test_shipped_classes.py` o asercje struktury klasy (tablice `mocodawca` i `pelnomocnicy` z kluczami, `typ` jako enum). Run → FAIL.
- [ ] **Step 2:** Napisz YAML (hints: `pełnomocnictwo`, `udzielam`, `pełnomocnik`; reguła: konsorcjum = kilku mocodawców wspólnie; reguły o mianowniku i `typ`). Run → PASS.
- [ ] **Step 3: Pomiar:** `eval` w obu trybach, wyniki do `docs/benchmark.md`; iteruj po błędach (cel F1 ≥ 0,9 per klasa, bez ścisłego progu).
- [ ] **Step 4: Commit** `feat: klasa pelnomocnictwo`.

---

### Task 14: Klasa `odwolanie` (słownik powodów + reguły)

**Files:**
- Create: `scripts/extract_czynnosc_map.py`, `classes/odwolanie.yaml`
- Modify: `tests/test_shipped_classes.py`, `docs/benchmark.md`

**Interfaces:**
- Schemat: `docs/schematy/odwolanie.json` (to nie jest poprawny JSON — traktować jako opis kształtu; kształt wyjścia = referencje `data/dane/*/odwolanie.json`). `czynnosc_powod_id` jako `enum` z `options` 1–11 (opisy z `CLAUDE.md` sekcja 4), `czynnosc_opis` jako pole `derive` (`from: czynnosc_powod_id`, `map` odtworzony z referencji). `Odwolujacy` i `Zamawiajacy` jako `array` z `key: [krs, nip]`; `pelnomocnik` jako `object` (`imie_nazwisko`, `nazwa`, `mail` z walidatorem `email`); `przez-pelnomocnika` jako `flag`; `prowadzacy_postepowanie` jako `flag` dopuszczający `null`; `numer_bzp`→`bzp`, `numer_ted`→`ted`, daty→`date`, `nip`/`krs`/`regon`→odpowiednie walidatory.

- [ ] **Step 1:** `scripts/extract_czynnosc_map.py` — skanuje `data/dane/*/odwolanie.json` i wypisuje słownik `czynnosc_powod_id → czynnosc_opis`; skrypt kończy się błędem, gdy jeden `id` ma kilka różnych opisów (wtedy ręcznie wybierz kanoniczny). Uruchom: `python scripts/extract_czynnosc_map.py`; wynik wklej do `map` w YAML.
- [ ] **Step 2: Failing test** w `test_shipped_classes.py`: `test_odwolanie_structure` (`enum` ma klucze 1–11, `derive.map` ma te same klucze, `Odwolujacy.key == ["krs","nip"]`, `prowadzacy_postepowanie` i `przez-pelnomocnika` jako `flag`, brak pola `czynnosc_opis` w schemacie modelu — patrz Task 3). Run → FAIL.
- [ ] **Step 3:** Napisz `classes/odwolanie.yaml` z regułami: `czynnosc_*` tylko z pierwszego „Zarzutu"; konsorcjum → Lider; `data` i `miejscowosc` z nagłówka pierwszej strony, `null` gdy brak (w 15 z 60 przykładów); `numer_ted` z formy `YYYY/S ###-NNNNNN` zapisać `NNNNNN-YYYY`; `przez-pelnomocnika` = 1 gdy występuje pełnomocnik Odwołującego; ≥1 few-shot. Run → PASS.
- [ ] **Step 4: Pomiar:** pełny `eval` na 60 przykładach w obu trybach; wyniki do `docs/benchmark.md` z rozbiciem na pola (spodziewane trudne: `czynnosc_*`, `prowadzacy_postepowanie`, `miejscowosc`). Iteruj, po każdej zmianie promptu/reguły zapisz F1 przed i po (wymóg `CLAUDE.md`).
- [ ] **Step 5: Commit** `feat: klasa odwolanie`.

---

### Task 15: Dowód „config only" — czwarta klasa

**Files:**
- Create: `classes_examples/faktura.yaml`, `tests/test_config_only.py`

**Interfaces:**
- Consumes: wyłącznie publiczne API (`load_classes`, `process_text`, `FakeLLM`).

- [ ] **Step 1: Failing test** `test_new_class_added_by_yaml_only`: kopiuje `classes/*.yaml` oraz `classes_examples/faktura.yaml` do tmp `classes/`, `FakeLLM` zwraca najpierw klasę `faktura`, potem wypełnione pola; `process_text` zwraca `class_name == "faktura"` i dane w kształcie z YAML, **bez** żadnej zmiany w `odwolania2json/` (assercja: hash plików pakietu przed i po teście jest ten sam). `test_new_class_visible_in_classes_cli`. Run → FAIL (brak pliku).
- [ ] **Step 2:** Napisz `classes_examples/faktura.yaml` (numer faktury, data wystawienia ISO, sprzedawca/nabywca z `nip`, kwota brutto `amount`, `hints`: `faktura`, `VAT`). Run `pytest tests/test_config_only.py -v` → PASS.
- [ ] **Step 3: Commit** `feat: przykład klasy faktura (config only)`.

---

### Task 16: Docker, README i instrukcja dodawania klasy

**Files:**
- Create: `Dockerfile`, `docker-compose.yml`, `.dockerignore`, `README.md`
- Modify: `.env.example` (jeśli brak którejś zmiennej)

**Interfaces:**
- Produces: `docker compose run --rm app` uruchamia `python -m odwolania2json run` na wolumenach `./input`, `./output`, `./classes`, `./trace`, z `env_file: .env`.

- [ ] **Step 1:** `Dockerfile` na `python:3.13-slim` z `tesseract-ocr` i `tesseract-ocr-pol` (apt), `pip install -r requirements.txt`, `ENTRYPOINT ["python","-m","odwolania2json"]`, `CMD ["run"]`. `docker-compose.yml` z jedną usługą `app`.
- [ ] **Step 2: Weryfikacja:** `docker compose build` kończy się sukcesem; `docker compose run --rm app classes` wypisuje trzy klasy (bez potrzeby modelu); z włączonym endpointem: `docker compose run --rm app run` na `data/szablon-aplikacja/input` kopiuje się do `input/`, wynik w `output/case1/` zgodny kształtem z `data/szablon-aplikacja/output/case1/`.
- [ ] **Step 3:** `README.md` po polsku: uruchomienie (venv, Docker, `start.bat`), zmienne env, tryby `hybrid`/`llm_only`, `eval`, struktura `output/` i `trace/`, licencje zależności i modelu, oraz sekcja **„Jak dodać klasę dokumentu"** krok po kroku na przykładzie `classes_examples/faktura.yaml` (skopiuj do `classes/`, nic więcej).
- [ ] **Step 4: Commit** `feat: Docker, README i instrukcja dodawania klasy`.

---

### Task 17: Benchmark modeli, wybór i aktualizacja dokumentów

**Files:**
- Modify: `docs/benchmark.md`, `.env.example`, `CLAUDE.md` (sekcje 3, 7, 8), `docs/superpowers/specs/2026-11-21-odwolania2json-design.md` (sekcja 8: wybrany model)

**Uwaga:** wymaga endpointu LiteLLM zespołu i odpowiedzi na pytanie 4 do organizatora (open-source vs open-weights) **przed** ostatecznym wyborem.

- [ ] **Step 1:** Dla 2–3 kandydatów open-weights (rząd 30B+, JSON schema; lista z LiteLLM zespołu) uruchom `python -m odwolania2json eval --model <nazwa> --mode hybrid` i `--mode llm_only` (wyniki `--out-json docs/bench/<model>-<mode>.json`).
- [ ] **Step 2:** Uzupełnij tabelę w `docs/benchmark.md` (model, tryb, F1, precision, recall, czas na dokument, licencja modelu). Wybierz model i domyślny tryb (`hybrid` zostaje, chyba że `llm_only` wygrywa wyraźnie); wpisz do `.env.example`.
- [ ] **Step 3:** Zaktualizuj `CLAUDE.md` (sekcja 3: wybrany model i przełącznik `EXTRACTION_MODE`; sekcja 6: status „po zatwierdzeniu, kod gotowy"; sekcja 8: wpis w dzienniku) oraz sekcję 8 spec (model wybrany, link do benchmarku).
- [ ] **Step 4: Commit** `docs: benchmark modeli i wybór`.

---

## Self-Review

- **Pokrycie spec:** przepływ 1–6 → Tasks 6, 8, 9, 5, 4, 10; przełącznik trybu → Tasks 1, 9, 10, 11; konfiguracja klasy i słownik powodów → 2, 3, 14; `eval` z metrykami pomocniczymi → 11; dostawa (CLI, `start.bat`, Docker, README, instrukcja) → 10, 16; `nieznany` → 8, 10; dowód „config only" → 15; model po benchmarku → 17; opcjonalna przeglądarka wyników (Could) świadomie poza planem, do dodania po spełnieniu Must.
- **Spójność typów:** `DocText`, `LLM.complete_json`, `ClassConfig`/`FieldSpec`, `Extraction`, `DocResult` zdefiniowane w Taskach 2–10 i używane z tymi samymi nazwami w 11–15; `process_text` zdefiniowany w Task 10 i użyty w 11 i 15; `validate_value` i `REGISTRY` z Task 4 używane w 9 i 12–14; nazwy zmiennych env jak w `.env.example`.
- **Luka do zamknięcia w trakcie:** Task 2 musi sprawdzać nazwy `validator` względem `REGISTRY` (Task 4 zależy od Task 2, więc sprawdzenie dodać po Task 4 i przetestować w `test_shipped_classes_load_and_validators_exist` z Task 12).
- **Decyzje zostawione implementerowi (zgodnie ze spec sekcja 8):** progi i heurystyki (`looks_garbage`, 3000 znaków do klasyfikacji, `MAX_CHARS`), treść promptów, reguły dopasowania cytatów — stroić na `eval`.
