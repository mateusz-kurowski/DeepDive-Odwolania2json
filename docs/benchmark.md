# Benchmark i dziennik pomiarów F1

Status: pomiary **jeszcze niewykonane** (budowa kodu odbyła się bez dostępu do endpointu modelu).
Do uruchomienia z działającym `.env` (`OPENAI_API_KEY`, `OPENAI_BASE_URL`, `LLM_MODEL`):

```bash
python -m src eval --mode hybrid  --out-json docs/bench/<model>-hybrid.json
python -m src eval --mode llm_only --out-json docs/bench/<model>-llm_only.json
# szybki test na części przykładów:
python -m src eval --limit 10 --mode hybrid
```

Zasada z `CLAUDE.md`: każda zmiana promptu lub reguły = F1 przed i po na 60 przykładach.

## Pomiary per klasa

| Data | Klasa | Model | Tryb | F1 | Precision | Recall | Uwagi / zmiana |
|---|---|---|---|---|---|---|---|
| | przelew | | hybrid | | | | |
| | przelew | | llm_only | | | | |
| | pelnomocnictwo | | hybrid | | | | |
| | pelnomocnictwo | | llm_only | | | | |
| | odwolanie | | hybrid | | | | |
| | odwolanie | | llm_only | | | | |

## Benchmark modeli (Task 17)

| Model (open-weights) | Licencja | Tryb | F1 (łącznie) | Precision | Recall | s/dokument |
|---|---|---|---|---|---|---|
| | | hybrid | | | | |
| | | llm_only | | | | |

Wybór modelu czeka na odpowiedź organizatora (open-source vs open-weights, pytanie 4).

## Warunek wrócenia do chunkingu

Jeśli w śladzie (`trace/`) flaga `truncated` pojawia się często i `eval` pokazuje spadek F1 na takich dokumentach, rozważyć podział na okna z scalaniem wyników i weryfikacją (poza obecnym zakresem).

## Poprawa F1 po analizie błędów (21.11): plan pomiaru

Punkt wyjścia: `results/20261121-154630/` (model `extractor`, 60 przykładów, 180 PDF, około 1,3 mln tokenów i 376 wywołań na przebieg).
Precyzja jest bliska 1. Recall traci się głównie na dokumentach, które przepadły w całości (puste odpowiedzi LLM).

| Krok | Commit | Przyczyna | hybrid F1 / P / R | llm_only F1 / P / R | F1 bez błędów (h / l) | PDF z błędem (h / l) | Klasyf. (h / l) | Tokeny (h / l) |
|---|---|---|---|---|---|---|---|---|
| przed | 0fab959 | — | 0,9695 / 0,9928 / 0,9473 | 0,9741 / 0,9944 / 0,9547 | — | 7 / 6 | 0,950 / 0,956 | 1 322 137 / 1 285 885 |
| 1–2. puste odpowiedzi LLM | 41bc51b, bf33324 | A | | | | | | |
| 3. hinty z rozstrzelonym tytułem | 3ccc44f | B | | | | | | |
| 4. numer_bzp z /NN | bae604d | D | | | | | | |
| 5. czynnosc_* + requires | aeb34d5, 2890591 | C | | | | | | |
| 6. pelnomocnik.nazwa + raport awarii | 1bd9b76, 3159700 | E | | | | | | |
| po wszystkich (pełny przebieg) | | A–E | | | | | | |

Pomiar per krok na podzbiorze (szybciej), pełny przebieg na końcu. Kroki 1–6 są w osobnych commitach, więc pomiar „po kroku N” to `git checkout <commit>` i ta sama komenda.

### Komendy (kolejność)

1. Testy offline (bez kosztów):

   ```bash
   make test
   ```

2. Podzbiór 14 przykładów, które pokrywają przyczyny A–E (01, 45, 27, 54: puste odpowiedzi; 02, 32: hinty; 03, 05, 13, 41, 49, 58: czynnosc; 18: BZP; 16: pelnomocnik), oba tryby w jednym katalogu:

   ```bash
   make eval-hybrid eval-llm-only EXAMPLES=01,02,03,05,13,16,18,27,32,41,45,49,54,58 \
     RUN_DIR=results/$(date +%Y%m%d-%H%M%S)-podzbior
   ```

   Diagnostyka pustych odpowiedzi (A), czyli finish_reason, reasoning_tokens, cache_hit:

   ```bash
   grep -h "Niepoprawna odpowiedź\|nie jest obiektem\|Próba\|odrzucił extra_body\|klasa z hintów" results/*-podzbior/*.log
   ```

   Czego się spodziewać: brak „Model niedostępny po 4 próbach”; jeśli pusta odpowiedź się zdarzy, w logu widać jej przyczynę (`finish_reason: length` i duże `reasoning_tokens` oznaczają rozumowanie, a powtarzalność mimo `no-cache` wskazuje na backend), a kolejna próba ją naprawia. Tokeny odpowiedzi powinny wyraźnie spaść, jeśli `reasoning.enabled=false` działa.

3. Pełny przebieg w obu trybach (około 1,3 mln tokenów na tryb, mniej po wyłączeniu rozumowania):

   ```bash
   make eval-hybrid eval-llm-only
   ```

   Do tabeli: `micro_f1`, `precision`, `recall`, `micro_f1_without_errors`, `errors`, `classification_accuracy` i `usage.total_tokens` z `results/<timestamp>/{hybrid,llm_only}.json`.

Opcjonalnie przy kolejnych zmianach samych reguł: `CACHE=results/cache` oszczędza powtarzane identyczne zapytania (głównie klasyfikację). Do pomiaru końcowego lepiej bez cache.
