# ADR 0001 — Fundamenty projektu

- **Data:** 2026-08-03
- **Status:** przyjęte

## Kontekst

Projekt powstaje wzdłuż kursu AI_devs 4: Builders, przechodzonego po raz drugi. Cel autora
nie jest zaliczeniowy — flagi są produktem ubocznym. Celem jest zrozumienie budowy agenta
oraz utrwalenie Pythona i poznanie współczesnych bibliotek (m.in. FastAPI).

Trudność: w chwili startu nie znamy dokładnego zakresu późniejszych lekcji, więc ryzyko
zaprojektowania architektury „pod wszystko" jest realne.

## Decyzje

### 1. Dostawca modeli: OpenRouter

Jeden klucz daje dostęp do modeli OpenAI, Anthropic i Google. Kurs w S03E04 wymaga
porównywania zestawu modeli, a w S05E03 migracji między wersjami — z jednym dostawcą
oznaczałoby to zakładanie kolejnych kont w trakcie.

Koszt: obsługa structured outputs różni się między modelami na OpenRouter. Warstwa `llm/`
musi to normalizować i jawnie zgłaszać, gdy wybrany model nie wspiera schematu.

### 2. Własna cienka abstrakcja zamiast frameworka agentowego

Odrzucone: `pydantic-ai`, LangGraph. Oba dają szybciej działający kod, ale ukrywają
mechanikę — pętlę narzędzi, format wiadomości, wymuszanie schematu — czyli dokładnie to,
czego kurs uczy. Przy celu edukacyjnym to jest wada, nie zaleta.

Konwencja kursu też za tym stoi: przykłady referencyjne wołają API gołym `fetch`, bez SDK.

### 3. Biblioteka prymitywów, agent później

Zadania S01E01–E05 to pipeline'y, nie agenty. Budujemy siedem prymitywów wymuszonych przez
te zadania (`http`, `cache`, `trace`, `llm`, `hub`, `config`, `tasks`), a pętlę agenta
dopiero gdy zadanie jej zażąda. Moduły przyszłe opisujemy w `ARCHITECTURE.md`, nie tworzymy
jako puste pakiety.

### 4. `core/trace` istnieje od pierwszego zadania

S03E01 wprowadza obserwowalność i ewaluację. Ewaluacja bez historycznych przebiegów jest
bezwartościowa, a odtworzenie ich wstecz niemożliwe. Dlatego JSONL z każdego wywołania
LLM i HTTP zapisujemy od S01E01, choć „potrzebny" będzie dopiero dwa sezony później.

### 5. Testy: rygor asymetryczny

Obowiązkowe testy jednostkowe dla `core/`, `llm/`, `hub/`. **Zero** testów jednostkowych
dla `tasks/`.

Uzasadnienie empiryczne: meta-analiza 27 badań (Rafique & Mišić, IEEE TSE 2013) pokazuje,
że TDD ma mały pozytywny wpływ na jakość zewnętrzną i brak mierzalnego wpływu na
produktywność, przy czym produktywność wyraźnie spada dla zadań złożonych. To przemawia za
stosowaniem TDD tam, gdzie problem jest prosty i deterministyczny — czyli w `core/`.

Moduły zadań sterują LLM-em i są niedeterministyczne; ich właściwą weryfikacją jest flaga
z Huba, a od S03E01 trace'y i ewaluacje offline. Duplikowanie tego asercjami byłoby
pozorną kontrolą.

### 6. Autor jest właścicielem specyfikacji

Przy agencie piszącym zarówno testy, jak i implementację występuje *test inversion*: testy
zaczynają potwierdzać zachowanie kodu zamiast wymagań. Dlatego dla `core/`, `llm/` i `hub/`
agent kodujący przedstawia najpierw same asercje i czeka na akceptację autora, a dopiero
potem implementuje. Zapisane jako zasada 5 w `CLAUDE.md`.

### 7. CLI i FastAPI od pierwszego dnia

Obie ścieżki wołają te same funkcje; warstwa HTTP nie zawiera logiki domenowej. Autor uczy
się FastAPI stopniowo zamiast zderzyć się z nim w S04, a późniejsze lekcje o zadaniach
w tle i architekturze dokładają trasy zamiast przebudowywać rdzeń.

## Konsekwencje

- Pierwsze zadanie (`s01e01 people`) będzie kosztowniejsze niż napisanie skryptu — trzeba
  najpierw zbudować `http`, `cache`, `trace`, `llm`, `hub`. To jest świadoma inwestycja.
- Rezygnujemy z gotowych integracji frameworków (retry, streaming, tool loop) i piszemy je
  sami. Zgodne z celem edukacyjnym, kosztuje czas.
- Zmiana dostawcy na innego niż OpenRouter będzie wymagała nowego adaptera w `llm/`,
  ale nie zmian w `tasks/`. To jest test poprawności abstrakcji.

## Do rozstrzygnięcia później

- Baza danych: czy potrzebna przed S02E02 (bazy wektorowe)? Na razie pliki na dysku.
- Model domyślny: `openai/gpt-4.1-mini` w `.env.example` to placeholder — do zweryfikowania
  wobec aktualnej listy modeli OpenRouter przy pierwszym uruchomieniu.
