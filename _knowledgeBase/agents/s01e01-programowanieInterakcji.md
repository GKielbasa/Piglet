# S01E01 — programowanie interakcji z modelem językowym

> **Zasada jednym zdaniem:** sterowanie modelem = zarządzanie kontekstem.
> Wszystko inne w tej lekcji jest konsekwencją tego zdania.

Źródło: `_teoria/s01e01-programowanie-interakcji-z-modelem-jezykowym-1773053098.md`.
Pominięte świadomie: LM Studio i modele lokalne, lista profili do obserwowania,
schematy baz danych dla czatbotów — tło, które nie zmienia niczego w kodzie.

---

## 1. Model jako niedeterministyczna funkcja

- Model przewiduje **kolejny token** na podstawie całego kontekstu — wejścia *i* tego, co
  sam już wygenerował (**autoregresja**). Wygenerowanego tokenu nie da się cofnąć.
- API jest **bezstanowe**: przy każdym wywołaniu wysyłamy komplet danych. Okno kontekstowe
  obejmuje wszystko, co model przetwarza, plus miejsce na odpowiedź.
- Polski tekst to ~50–70% więcej tokenów niż angielski — wyższy koszt i dłuższa inferencja.
  Konsekwencja dla nas: dane wejściowe bywają polskie, ale prompt i schemat piszemy po
  angielsku.
- Programowanie generatywne to łączenie **deterministycznego kodu** z **niedeterministycznym
  wynikiem** modelu. Ten sam input nie gwarantuje tego samego outputu.

Z tego wynika technika, która przewija się przez cały kurs: **łańcuch wielu zapytań**, gdzie
wynik jednego jest wejściem następnego (klasyfikacja → prompt dobrany do klasy). Dla
użytkownika to nadal „pytanie → odpowiedź"; dla nas — kontrola nad uwagą modelu, kosztem
czasu reakcji i pieniędzy.

---

## 2. Structured Outputs — sedno lekcji

`response_format` / `json_schema` w trybie `strict`. Rozumieć na dwa sposoby:

| | Co dostajesz |
|---|---|
| **Struktura** | **gwarantowana** — odpowiedź ma dokładnie ten kształt |
| **Wartości** | generowane na podstawie treści **oraz nazw pól i ich opisów** |

Trzy reguły, których łatwo nie zauważyć:

1. **Nazwa pola i jego `description` są częścią promptu.** Nie dokumentacją. Autor
   podkreśla, że to jest najczęściej pomijane przy projektowaniu narzędzi i agentów.
2. **Kolejność pól ma znaczenie** — poprzedzające tokeny wpływają na kolejne.
   `reasoning` przed `sentiment`, `sentiment` przed `confidence`. Odwróć kolejność
   i przy identycznym schemacie dostaniesz gorszy wynik.
3. **Zawsze przewiduj wartość „nieznane" / „neutralne".** Zmuszanie modelu do wyboru,
   gdy danych nie ma, to prosta droga do konfabulacji.

Schemat może wygenerować LLM, ale za finalną jakość nazw i opisów odpowiada człowiek.

Zastosowania, które Structured Output otwiera: wnioskowanie, ekstrakcja, kompresja,
wzbogacenie, parafraza, tłumaczenie, **klasyfikacja**, weryfikacja, generowanie, synteza.
Prawie żadnego z nich nie da się zrobić samym kodem.

---

## 3. Trzy mechanizmy z przykładu `01_01_grounding`

Najbardziej inżynierska część lekcji i jedyna, która przekłada się wprost na architekturę:

1. **Przetwarzanie fragmentami nawet wtedy, gdy całość zmieściłaby się w oknie.** Powód nie
   jest techniczny, tylko skutecznościowy: mniejszy zakres = skupiona uwaga modelu = wyższa
   jakość. Dodatkowo otwiera drogę do tańszych i szybszych modeli.
2. **Zapytania równolegle i w grupach.** Równoległość skraca czas, grupowanie chroni przed
   rate-limitem.
3. **Postęp zapisywany na dysk** (JSON), żeby przerwany przebieg dało się wznowić bez
   płacenia drugi raz za to samo.

---

## 4. Wybór modelu

„Który model jest najlepszy" to źle zadane pytanie; poprawne brzmi **„najlepszy w tej
sytuacji"**, a odpowiedź daje wyłącznie test na własnych zadaniach.

| Strategia | Na czym polega |
|---|---|
| Główny | jeden model do wszystkiego — najprostsze |
| Główny + alternatywny | duży do trudnych zadań, mały i tani do reszty — najczęstsze |
| Główny + specjalistyczne | podział wg skuteczności w konkretnych zadaniach, nie wg ceny |
| Zespół małych | dekompozycja i głosowanie zamiast jednego drogiego modelu — rzadkie |

Dwie konsekwencje: unikać **vendor lock-in** (stąd OpenRouter), i **nie sięgać po frameworki
typu AI SDK** — autor odradza je wprost, bo narzucają ograniczenia bez wartości w zamian.

---

## 5. Organizacja instrukcji w kodzie

| Sposób | Kiedy |
|---|---|
| inline, w miejscu wywołania | proste zapytania, rzadko zmieniane |
| osobne pliki z kompozycją promptu | najpopularniejsze i najbardziej elastyczne |
| system zewnętrzny (Langfuse) | wersjonowanie i monitoring poza kodem |
| **markdown + frontmatter yaml** | **wybór autora, gdyby wolno było wybrać jeden** |

Ostatni wariant wygrywa, bo prompt jest wtedy zwykłym plikiem — dostępnym dla agenta jako
jego narzędzie, w czasie działania aplikacji. Dokładnie tak działa Claude Code.

---

## 6. Generalizowanie generalizacji

Gdy model myli narzędzia albo kategorie, **złą** odpowiedzią jest reguła załatwiająca
konkretny błąd. Naprawia jeden przypadek i to, co model z niego wywnioskuje.

**Dobrą** odpowiedzią jest zgeneralizowany proces myślowy: głośne rozważenie wyboru,
określenie poziomu pewności, prośba o doprecyzowanie przy niskiej pewności. Taka instrukcja
nie dotyczy błędu ani nawet jego kategorii — obsługuje szeroki zbiór konfiguracji narzędzi
i zadań.

Anatomia promptu systemowego (z rozbioru promptu Claude): **strukturyzowanie** tagami
XML-like, **tożsamość**, **limity** (czego nie robić), **ograniczenia** (co pod jakim
warunkiem), **styl**, **bezpieczeństwo**, **adaptacja** (co robić, gdy się nie da),
**kalibracja** formatu.

Ostrzeżenie, które autor powtarza dwa razy: instrukcji systemowej **da się nie posłuchać**.
Prompt zmniejsza prawdopodobieństwo niepożądanych zachowań; zabezpieczenie robi się w kodzie
i w założeniach projektowych.

---

## 7. Few-shot i kontekst

Modele uczą się w locie z treści zapytania (**in-context learning**). Sama wiedza
zewnętrzna zwykle wystarczy, że po prostu znajdzie się w kontekście. Ale gdy model ma
wykonać zadanie **według ustalonych zasad**, opis zasad to za mało — potrzebne są
przykłady, bo model rozpoznaje w nich wzorzec.

Kierunek zmiany: sekcja `<examples>` w prompcie systemowym ustępuje miejsca **narzędziom
wczytującym dokumenty na żądanie**. Prompt systemowy ma zawierać zgeneralizowane zasady, nie
szum, który przez większość czasu jest zbędny.

---

## 8. Semantyczne zdarzenia zamiast tekstu

Odpowiedź modelu to nie tekst, tylko **seria zdarzeń**: tokeny rozumowania, wywołania
narzędzi, obrazy, błędy, prośby o potwierdzenie akcji. Zapisywanie samej treści wiadomości
asystenta wygląda na wystarczające na starcie i staje się blokadą na produkcji — rozbudowa
wymaga wtedy zmian od bazy danych po front-end plus migracji danych użytkowników.

Zdarzenie niosące `id`, typ i metadane rozbudowuje się przez dodanie właściwości. Temat
wróci przy systemach wieloagentowych.

---

## Źródła

- `_teoria/s01e01-programowanie-interakcji-z-modelem-jezykowym-1773053098.md`
- Structured Outputs: <https://platform.openai.com/docs/guides/structured-outputs>
- Przykłady z lekcji: `01_01_interaction`, `01_01_structured`, `01_01_grounding`
  w <https://github.com/i-am-alice/4th-devs>
