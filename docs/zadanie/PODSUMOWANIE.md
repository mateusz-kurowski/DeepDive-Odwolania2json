# UZP — Odwołania2JSON (podsumowanie)

Źródła: „Pełna treść zadania konkursowego", „Regulamin zadania konkursowego". Brak zip-ów w folderze; pozostałe materiały (zestawy treningowe, specyfikacja JSON) są na GitHubie UZP, nie w folderze.

## 1. Organizator i nagroda
- Przyrzekający nagrodę: **Urząd Zamówień Publicznych** (Warszawa, ul. Postępu 17A; reprezentowany przez Marka Redźkę, Dyrektora Generalnego). Organizator wydarzenia: Ministerstwo Cyfryzacji; operator: PROIDEA sp. z o.o.
- Jedna nagroda główna: **20 000 zł brutto** (pomniejszona o podatek; UZP jest płatnikiem, zwycięzca nie ponosi dodatkowych kosztów podatkowych). Dla zespołu — równe części dla wszystkich członków.
- Wypłata **do 7 dni** od podpisania umowy przeniesienia autorskich praw majątkowych **i przekazania**: kodu źródłowego, instrukcji uruchomienia, konfiguracji Docker Compose, dokumentacji (opis architektury, konfiguracji ekstrakcji danej klasy dokumentów oraz dodania nowej klasy dokumentów).

## 2. Problem
Sprawa odwoławcza przed KIO to zbiór wielu powiązanych dokumentów PDF (część elektroniczna, część skany) z informacjami o wykonawcach, zamawiających, pełnomocnikach, postępowaniach, płatnościach i czynnościach procesowych. Kluczowe informacje są ułożone w przeróżny sposób, z reguły na pierwszych trzech stronach. Dla systemów administracji konieczna jest zamiana: wiele dokumentów PDF → analiza treści → identyfikacja informacji → model danych JSON.

## 3. Co trzeba zbudować / oczekiwane rezultaty
Działająca aplikacja, która pobiera plik PDF i zwraca plik JSON w ustalonym formacie. Rozwiązanie ma:
1. przyjąć dokument PDF składający się na odwołanie (dokument z treścią odwołania, pełnomocnictwo, dokument potwierdzenia przelewu);
2. rozpoznać rodzaj dokumentu;
3. wyodrębnić informacje biznesowe istotne dla danego typu dokumentu;
4. wygenerować JSON dla każdego dokumentu zgodny z wzorcem w repo UZP (`oczekiwane-json`).

Premiowane (5): łatwa rozszerzalność o nowe klasy dokumentów / konfiguracja nowych klas **bez modyfikacji kodu źródłowego**; wspieranie transparentności procesu ekstrakcji.

## 4. Kryteria oceny z wagami
**Etap 1 — preselekcja:** jedno kryterium: **jakość ekstrakcji danych (F1 Score) — 100%**, na nieujawnionym zbiorze testowym zawierającym **co najmniej 10 spraw odwoławczych** (realne sprawy przygotowane przez organizatora; porównanie z danymi realnymi na dokumentach). Podstawowa miara: F1 na zbiorze testowym.

**Etap 2 — finał** (maksymalnie **trzy zespoły** z najwyższymi wynikami Etapu I; jury wskazuje zwycięzcę). Uwaga: dokumenty podają dwie wersje wag:
- Opis zadania (rozdz. 8): F1 — **50%**; Elastyczność i możliwość rozbudowy (łatwość dodawania nowych typów dokumentów i nowych klas danych bez przebudowy systemu) — **30%**; Architektura i jakość techniczna (przejrzystość, modularność, utrzymanie, dokumentacja) — **20%**.
- Regulamin (§ 2 ust. 4b): F1 — **50%**; elastyczność i łatwość rozbudowy o nowe klasy dokumentów — **50%** (na podstawie opisów architektury, kodu źródłowego i treści prezentacji zespołu).
- Regulamin zadania ma pierwszeństwo przed Regulaminem Wydarzenia (§ 5 ust. 2); rozbieżność opis vs regulamin zadania nie jest rozstrzygnięta w dokumentach.

Jury: min. 3 członków z wiedzą specjalistyczną; skład najpóźniej w dniu rozpoczęcia wydarzenia. Decyzje ostateczne. Skala punktowa poza F1 nie jest podana.

## 5. Dane i materiały
- Organizator udostępnia: **zestawy dokumentów syntetycznych** (zbiór treningowy) oraz **specyfikację oczekiwanego modelu danych** — na GitHubie: https://github.com/Urzad-Zamowien-Publicznych/hacknation-2026 (wzorzec JSON: `.../blob/main/oczekiwane-json`). W opisie URL występuje w dwóch pisowniach (m.in. „UrzadZamowien-Publicznych" i „Urzad-ZamowienPublicznych" w jednym miejscu) — używać wariantu `Urzad-Zamowien-Publicznych`.
- Zbiór testowy: nieudostępniony; realne sprawy odwoławcze od organizatora.
- Mentorzy: techniczni oraz eksperci merytoryczni z zamówień publicznych; kanały i harmonogram dyżurów — przed hackathonem (w dokumentach brak szczegółów).
- Brak zip-ów w folderze.

## 6. Wymagania techniczne / formalne i ograniczenia
**Zgłoszenie (4):** tytuł projektu; **link do GitHuba działającego prototypu umożliwiającego wgranie dokumentów i odczytanie rezultatów ekstrakcji**. Opcjonalnie: dokumentacja techniczna, wyniki własnych testów jakości. (W dokumentach zadania nie ma wymogu PDF-prezentacji ani wideo — te wynikają z regulaminu wydarzenia/CLAUDE.md.)

**Wymagane techniczne (5):**
- **wyłącznie komponenty open source (w tym otwarto-źródłowe modele językowe)**;
- uruchomienie w środowisku lokalnym (**on-premise**) **bez GPU** („LLM po API");
- w praktyce regulamin przy wypłacie wymaga też konfiguracji **Docker Compose**.

**Prawa autorskie (Regulamin § 4):**
- Każdy uczestnik oświadcza, że jest twórcą swojego wkładu i ma pełne autorskie prawa majątkowe; **rozwiązania zewnętrzne trzeba wyraźnie wskazać w prezentacji zadania**; rozwiązanie wolne od wad prawnych, bez naruszeń praw osób trzecich.
- **Zwycięzcy (wszyscy współtwórcy) zawierają z UZP umowę o przeniesienie autorskich praw majątkowych** (wzór — Załącznik nr 1, ma być udostępniony przed wydarzeniem). Pola eksploatacji: art. 74 ust. 4 (program komputerowy: zwielokrotnianie, tłumaczenie/przystosowanie/zmiany, rozpowszechnianie, zezwalanie na prawa zależne) i art. 50 (pozostałe, m.in. publiczne udostępnianie w Internecie, wersje obcojęzyczne); dotyczy też kodów źródłowych, dokumentacji i wszelkich modyfikacji.
- Niepodpisanie umowy w 7 dni od przekazania = utrata nagrody (może trafić do kolejnej drużyny wskazanej przez jury).
- Po wynikach: oświadczenie z danymi do przelewu (Zał. 2 do umowy).
- Dokumenty zadania nie zawierają odrębnych zapisów o RODO/wizerunku (obowiązuje Regulamin Wydarzenia). Brak zapisów o regulacjach dotyczących użycia AI poza wymogiem open source.

## 7. Ryzyka i niejasności / pytania do organizatora
- **Wymóg „wyłącznie open source, w tym otwarto-źródłowe modele językowe" a „LLM po API"** — czy dozwolone jest wywołanie modeli zamkniętych (przez LiteLLM) czy tylko open-weights (np. hostowane po API)? To kluczowe dla naszego stacku (LiteLLM/Voyage). Zapytać mentora/organizatora przed wyborem modelu.
- Rozbieżność wag Etapu 2: opis 50/30/20 vs regulamin 50/50 (elastyczność). W obu wersjach elastyczność/rozszerzalność o nowe klasy dokumentów jest co najmniej 30–50% — projektować konfigurowalne klasy dokumentów (schema w pliku konfiguracyjnym, bez zmian kodu).
- **Etap 1 rozstrzyga wyłącznie F1** na ukrytym zbiorze realnych spraw (≥ 10) — demo/UI i pitch nie liczą się w preselekcji; ryzyko przeuczenia na danych syntetycznych vs realne skany/OCR.
- Nieznany sposób liczenia F1 (poziom pola, normalizacja, dopasowanie podobieństwa) — sprawdzić w repo UZP; niewyspecyfikowane w PDF.
- Sformułowanie „JSON dla każdego dokumentu" oraz opis „wielodokumentowa sprawa → spójny model" — niejasne, czy oczekiwany jest jeden JSON na sprawę, czy na dokument; potwierdzić w specyfikacji w repo.
- W opisie brak informacji o formacie finału (czas pitchu, kolejność) — zgodnie z regulaminem wydarzenia; brak wymogu wideo/PDF poza linkiem do GitHuba (nasze CLAUDE.md zakłada draft w HackTribe i PDF — sprawdzić).
- Link do GitHuba ma pozwalać „wgrać dokumenty i odczytać rezultaty" — sugeruje UI/endpoint do uploadu, nie tylko skrypt batch.
- Skany: OCR bez GPU; koszty tokenów i czas.
- Przeniesienie praw na UZP po wygranej — potwierdzić z organizatorem status wcześniejszego kodu / bibliotek wspólnych.
