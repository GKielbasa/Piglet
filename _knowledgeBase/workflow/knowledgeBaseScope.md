# Baza wiedzy — co tu wchodzi, a co nie

> **Zasada jednym zdaniem:** tu trafia wiedza, która przeżyje ten projekt.
> Jeśli zdanie przestaje być prawdziwe po zamknięciu repozytorium — jest nie na miejscu.

Ta baza istnieje po to, żeby służyć **w pracy**, nie w jednym repo. Uczymy się tu budowy
agentów, Pythona, HTTP i warsztatu pracy z agentowym software devem. Kurs i `piglet` są
okazją do nauki, nie tematem notatek.

---

## Trzy działy

| Katalog | Co tam trafia |
|---|---|
| `python/` | język, biblioteki, wzorce: `uv`, typy, `SecretStr`, HTTP, ponowienia |
| `agents/` | modele, prompty, Structured Outputs, architektura agentów, ewaluacja |
| `workflow/` | warsztat: harness, hooki, proces pracy z agentem kodującym |

Jeden plik = jeden temat.

---

## Test, zanim coś tu dopiszesz

**Czy to zdanie byłoby użyteczne w innej firmie, w innym projekcie, za dwa lata?**

Jeśli tak — zostaje. Jeśli do zrozumienia potrzebuje nazwy naszego pakietu, ścieżki
z naszego drzewa albo treści zadania z kursu — wychodzi.

## Czego tu nie ma

- **Sekcji „Co z tego wynika dla `piglet`".** Stan konkretnego projektu — „jest / brak”,
  ścieżki do plików, lista braków do nadrobienia. To jest raport z jednego repozytorium,
  starzeje się w tydzień i nie uczy niczego.
- **Endpointów i treści zadań** — adresów, formatów odpowiedzi, nazw zadań, flag,
  kryteriów filtrowania.
- **Decyzji projektowych** — one mają swoją formę i swoje miejsce (ADR).

## Gdzie to idzie zamiast tego

| Rodzaj treści | Miejsce |
|---|---|
| treść zadania z kursu, endpointy, format odpowiedzi | `_tasks/<lekcja>-<nazwa>.md` — **gitignored**, jak `_teoria/` |
| stan projektu, czego brakuje, co gdzie leży | `piglet/docs/` |
| decyzja architektoniczna i jej uzasadnienie | `piglet/docs/adr/` |
| notatki robocze jednego kroku | `.piglet-work/` (gitignored) |

## Jak pisać, żeby przeszło test

Konkret zostaje, kontekst się generalizuje. Zamiast „nasz klient ponawia POST-y bez
zabezpieczenia" — „ponawianie POST-a bez sprawdzenia idempotencji łamie RFC 9110 §9.2.2,
a pierwsze API z płatnościami zamienia tę wygodę w duplikaty". Ta sama obserwacja, ale
druga wersja działa u kolejnego pracodawcy.

Przykład, cytat z dokumentacji, numer RFC, pułapka, w którą się wdepnęło — to jest treść.
Nazwa naszej klasy jako ilustracja bywa dopuszczalna; nazwa naszej klasy jako temat już nie.
