# Pytania do mentorów i organizatora (Odwołania2JSON)

Stan: 21.11. Odpowiedzi wpisać w `CLAUDE.md` §7 (proj1) i §5 (repo główne).

Kontekst do przekazania w rozmowie: lokalny F1 na 60 przykładach treningowych jest bliski 1,0 (dane syntetyczne, KRS `9999…`), więc to górna granica. Rozwiązanie: klasyfikacja i ekstrakcja modelem LLM wołanym przez API zgodne z OpenAI, walidatory formatów w kodzie, klasy dokumentów jako pliki YAML.

## A. Pytania do zadania

### 1. Wagi oceny
Regulamin i README organizatora mówią: etap II = 50% F1 + 50% elastyczność/rozszerzalność. PDF zadania mówi 50/30/20.
- Które obowiązuje?
- Co wchodzi w pozostałe 30% i 20% (jakość kodu, dokumentacja, demo, przezroczystość)?
- Jak jest oceniana "elastyczność": kto i jak ją sprawdza?

### 2. Open source a modele
Zadanie wymaga "wyłącznie open source, w tym modele".
- Czy model open-weights (np. DeepSeek, Qwen, Llama; wagi do pobrania, licencja własna lub MIT/Apache) jest dopuszczalny?
- Czy wymagana jest licencja zatwierdzona przez OSI?
- Czy model może być wołany przez zewnętrzne API (hostowane open-weights), czy musi działać lokalnie?

### 3. Jak jury uruchamia rozwiązanie
- Czy jury uruchamia `docker compose up` u siebie, czy my pokazujemy działanie na naszej maszynie?
- Skąd jury bierze model: dostarczamy endpoint (np. nasz LiteLLM), czy model ma być w Docker Compose?
- Czy na maszynie jury będzie GPU i dostęp do internetu? (Nasz kod nie potrzebuje GPU, ale potrzebuje dostępu do endpointu modelu.)
- Czy klucz API może być w `.env` poza repozytorium?

### 4. Jak liczone jest F1
- Pole `null` w referencji i `null` w naszym wyniku: trafienie (TP) czy pominięte?
- Pole `null` w referencji, a my podajemy wartość: błąd (FP)? A odwrotnie: wartość w referencji, `null` u nas?
- Tablice (`Odwolujacy`, `Zamawiajacy`, `pelnomocnicy`, `podpisujacy`): dopasowanie po kluczu czy po kolejności? Czy nadmiarowy element to FP?
- Porównanie dosłowne czy znormalizowane (spacje, wielkość liter, format dat i liczb)? Czy `pesel` liczbą i tekstem to to samo?
- Czy F1 jest liczone per plik i uśredniane, czy łącznie (micro) po wszystkich polach?
- Dokument spoza klas (`nieznany`) i brak pliku JSON: jak wpływa na wynik? Co z nadmiarowym plikiem JSON dla takiego dokumentu?

### 5. Zbiór testowy
Dane treningowe są syntetyczne, testowy ma być "realny" (min. 10 spraw).
- Czy układ dokumentów będzie podobny do treningowych (ten sam generator), czy z prawdziwych orzeczeń i odwołań?
- Czy będą skany bez warstwy tekstowej? (W 180 treningowych PDF-ach jest 0 skanów, a przykład w `szablon-aplikacja` jest skanem.)
- Czy będą dokumenty dłuższe niż 11 stron?
- Czy będą dokumenty innych klas niż 3 znane?
- Czy zbiór zawiera przypadki brzegowe: konsorcja po stronie odwołującego, kilku zamawiających, brak NIP/KRS?

### 8. Dokument spoza klas
- Czy brak pliku JSON dla dokumentu `nieznany` jest oczekiwanym zachowaniem, czy ma powstać pusty JSON albo wpis w logu?
- Czy zbiór testowy zawiera takie dokumenty (przykład negatywny jest w `szablon-aplikacja`), i ile?

### 9. Dodawanie klas: kto obsługuje system
- Kto po stronie UZP będzie dodawał nowe klasy dokumentów: programista, analityk, urzędnik bez znajomości kodu?
- Czy dodawanie klasy ma odbywać się plikiem konfiguracyjnym (u nas YAML), czy UI/formularzem?
- Kto uruchamia system na co dzień (administrator, urzędnik, zadanie wsadowe po nocach) i gdzie (on-prem, chmura)?
- Jak jury sprawdza elastyczność: dodaje własną klasę i patrzy, czy działa bez zmian w kodzie? Jakiej złożoności (pola zagnieżdżone, tablice)?
- Jak ma wyglądać dokumentacja dla osoby, która dodaje klasę?
- Czy przezroczystość ekstrakcji (cytat źródłowy per pole) ma być w samym JSON-ie, czy w osobnym pliku śladu? (Nasz schemat wyjściowy jest zgodny z organizatorem, więc cytaty zapisujemy osobno w `trace/`.)

## B. Pytania rozwinięte (6, 13, 14)

### 6. `czynnosc_powod_id`: kod 12 i zakres 1–12
**Co to jest.** Pole `OdwolanieKIO.czynnosc_powod_id` to kod zaskarżonej czynności zamawiającego. W naszych danych występują kody 1–11:

| Kod | Czynność |
|---|---|
| 1 | odrzucenie oferty |
| 2 | wybór oferty |
| 3 | wykluczenie wykonawcy |
| 4 | publikacja SWZ |
| 5 | modyfikacja SWZ |
| 6 | odpowiedzi/wyjaśnienia do SWZ |
| 7 | zaniechanie odrzucenia oferty |
| 8 | zaniechanie wykluczenia wykonawcy |
| 9 | unieważnienie postępowania |
| 10 | zaniechanie unieważnienia |
| 11 | opis przedmiotu zamówienia (OPZ) |

**Skąd wątpliwość.** Komentarz w schemacie organizatora (`docs/schematy/odwolanie.json`) mówi "liczba całkowita 1-12", a w 60 przykładach kod 12 nie występuje ani razu (rozkład: 4–9 przypadków na każdy kod 1–11). Mapę kodów na opisy odtworzyliśmy z danych, bo organizator nie podał słownika.

**Dlaczego to ważne.** `czynnosc_powod_id` i `czynnosc_opis` (opis wynika 1:1 z kodu) to dwa pola z największymi stratami w naszych pomiarach. Jeśli w zbiorze testowym pojawi się kod 12 albo kod, którego nie znamy, nasz enum 1–11 go odrzuci (pole `null`), co daje stratę recall.

**Pytania:**
- Co oznacza kod 12 i czy występuje w zbiorze testowym?
- Czy istnieje oficjalna lista kodów z opisami (żeby sprawdzić naszą mapę 1–11)? Czy opisy `czynnosc_opis` mają być dosłownie takie, jak w tabeli powyżej?
- Co zwrócić, gdy zaskarżona czynność nie pasuje do żadnego kodu: `null`, czy najbliższy?
- Czy kod ma być ustalany także dla odwołań wobec czynności złożonych, np. publikacja SWZ razem z ogłoszeniem o zamówieniu (u nas = 4)?

### 13. Czynność zaskarżona: jak ją rozpoznać, gdy zarzutów jest kilka
**Co mówi schemat.** Pola `czynnosc_dzien`, `czynnosc_powod_id` i `czynnosc_opis` mają być ustalane "WYŁĄCZNIE na podstawie pierwszego zarzutu". `czynnosc_dzien` to data czynności uruchamiającej bieg terminu odwołania dla tego zarzutu; jeśli brak wiarygodnej daty, `null`.

**Na czym polega trudność.** Odwołanie zwykle wygląda tak: "Zamawiający w dniu DATA roku [czynność]… Zarzuty: 1) …, 2) …". Model musi:
1. znaleźć zdanie opisujące czynność (a nie ogólne uzasadnienie zarzutu),
2. przypisać mu kod, mimo że sformułowania są różne ("poinformował o odrzuceniu oferty", "zaniechał unieważnienia", "dokonał wyboru oferty"),
3. wziąć właściwą datę, a nie datę pisma odwołania, otwarcia ofert, wezwania do wyjaśnień ani wcześniejszego zdarzenia.

Typowa pułapka: zdanie mówi o wyborze oferty, ale zaskarżone jest zaniechanie wykluczenia ("z której wynika, że zaniechał wykluczenia"). Wtedy kod to 8, nie 2. Dodaliśmy reguły na to w `classes/odwolanie.yaml`.

**Skąd niepewność.** Reguły wywnioskowaliśmy z 60 przykładów. Nie wiemy, jak wygląda to w prawdziwych odwołaniach (czynności złożone, kilka równorzędnych zarzutów bez numeracji, odwołanie wobec kilku czynności naraz).

**Pytania:**
- Co oznacza "pierwszy zarzut", gdy zarzuty nie są ponumerowane albo odwołanie wymienia kilka czynności? Pierwszy w kolejności tekstu, czy zarzut główny?
- Skąd brać datę, gdy zdanie o czynności nie ma daty, a jest tylko "o czym Zamawiający zawiadomił pismem z dnia…"? Czy to jest data czynności?
- Czy to ma być data zdarzenia (czynność zamawiającego), czy data, od której biegnie termin (może być inna, np. data doręczenia lub publikacji)?
- Jak traktować zaniechanie: data = data, kiedy zamawiający powinien był coś zrobić, czy data poinformowania o wyniku?
- Czy możemy dostać 2–3 prawdziwe, anonimowane odwołania z oznaczonym pierwszym zarzutem do sprawdzenia reguł?

### 14. Konsorcja: dane Lidera
**Co mówi schemat.** Dla `Odwolujacy[]` pola `nazwa`, `krs`, `nip`, `regon` to dane "Odwołującego lub Lidera konsorcjum podmiotów Odwołujących (jeśli występuje)". Jeśli występuje konsorcjum, podaje się dane Lidera, a tablica ma jeden element. W 60 przykładach `Odwolujacy` ma zawsze dokładnie jeden element, więc nigdy nie widzieliśmy konsorcjum po stronie odwołującego w odpowiedzi referencyjnej.

**Czy konsorcja w ogóle są w danych.** W tekście 8 z 60 odwołań pada słowo "konsorcjum", ale w obejrzanym przykładzie dotyczyło innych wykonawców (np. oferty konkurentów), a nie odwołującego. Czy w którymś odwołujący jest konsorcjum, nie sprawdzaliśmy. Jeśli tak, to nie wiemy, jak organizator rozstrzygnął, kto jest Liderem.

**Dlaczego to ważne.** Rzeczywiste odwołania często składają konsorcja (lider i partnerzy), a typowy dokument nie podpisuje wprost "Lider": trzeba go odczytać z kolejności, pełnomocnictwa albo umowy konsorcjum. Błąd tu zepsuje jednocześnie `nazwa`, `nip`, `krs`, `regon` i dane pełnomocnika, czyli sporo pól naraz.

**Pytania:**
- Skąd wiadomo, kto jest Liderem, gdy dokument nie używa słowa "Lider"? Pierwszy wymieniony? Wskazany w pełnomocnictwie?
- Czy `przez-pelnomocnika` i `pelnomocnik` dotyczą Lidera, czy każdego członka? (U nas: pełnomocnik odwołującego, jeden.)
- Czy w pełnomocnictwie (`mocodawca[]`) wpisujemy wszystkich członków konsorcjum, czy tylko Lidera? W schemacie `mocodawca` jest tablicą, a `pelnomocnicy` też.
- Czy konsorcjum po stronie zamawiającego (kilku zamawiających, `prowadzacy_postepowanie`) ma te same zasady? W danych 3 przypadki, wszystkie z jednym prowadzącym (1) i jednym nieprowadzącym (0).
- Czy w zbiorze testowym są konsorcja po stronie odwołującego i ile?

## C. Kolejność w rozmowie

1. Najpierw 1–4 (zmieniają decyzje o modelu, dostawie i metryce).
2. Potem 5, 8, 9 (zakres danych i elastyczność).
3. 6, 13, 14 tylko jeśli rozmówca zna domenę UZP/KIO. Jeśli nie, pytania 6, 13, 14 wrzucić na `#zapytaj-organizatora` razem z prośbą o kilka prawdziwych, anonimowych przykładów.
