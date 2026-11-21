# Benchmark i dziennik pomiarów F1

Status: pomiary **jeszcze niewykonane** (budowa kodu odbyła się bez dostępu do endpointu modelu).
Do uruchomienia z działającym `.env` (`OPENAI_API_KEY`, `OPENAI_BASE_URL`, `LLM_MODEL`):

```bash
python -m odwolania2json eval --mode hybrid  --out-json docs/bench/<model>-hybrid.json
python -m odwolania2json eval --mode llm_only --out-json docs/bench/<model>-llm_only.json
# szybki test na części przykładów:
python -m odwolania2json eval --limit 10 --mode hybrid
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
