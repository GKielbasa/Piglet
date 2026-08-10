# S01E01 — `people`

Treść zadania sprowadzona do wymagań. Wiedza ogólna z tej lekcji jest w
`_knowledgeBase/agents/s01e01-programowanieInterakcji.md` i nie powtarza się tutaj.

## Wejście

`GET https://hub.ag3nts.org/data/<klucz>/people.csv` — dane osobowe plus opis stanowiska
w kolumnie `job`.

## Kryteria

Osoba, której szukamy, spełnia **wszystkie** cztery warunki:

- mężczyzna,
- urodzony w Grudziądzu,
- w 2026 ma między 20 a 40 lat,
- pracuje w transporcie.

## Taksonomia

Zamknięta, siedem wartości, jedna osoba może mieć wiele tagów:

`IT` · `transport` · `edukacja` · `medycyna` · `praca z ludźmi` · `praca z pojazdami` ·
`praca fizyczna`

## Wyjście

`POST https://hub.ag3nts.org/verify`

```json
{
  "apikey": "<klucz>",
  "task": "people",
  "answer": [
    {
      "name": "Jan",
      "surname": "Kowalski",
      "gender": "M",
      "born": 1987,
      "city": "Warszawa",
      "tags": ["tag1", "tag2"]
    }
  ]
}
```

`born` to **liczba całkowita** (sam rok). `tags` to **tablica stringów**, nie jeden string
z przecinkami. Poprawna odpowiedź zwraca flagę `{FLG:...}`, którą wpisuje się ręcznie na
stronie huba.

## Wskazówki z treści zadania

- **Structured Output** przy tagowaniu — schemat w `response_format`, nie parsowanie JSON-a
  z tekstu. Zadanie da się zrobić bez tego, ale to jest jego cel dydaktyczny.
- **Batch tagging** — jedno wywołanie z ponumerowaną listą stanowisk zamiast N wywołań.
- **Opis przy każdym tagu** w schemacie, bo ratuje niejednoznaczne stanowiska.

## Otwarte, do rozstrzygnięcia przed implementacją

1. **„między 20 a 40 lat" — przedział domknięty czy otwarty?** Przy roczniku i roku 2026:
   domknięty daje `born ∈ [1986, 2006]`, otwarty `[1987, 2005]`. Dwa roczniki różnicy.
2. **Tagujemy wszystkich czy tylko przefiltrowanych?** Kolejność kroków w zadaniu sugeruje
   filtr przed tagowaniem (taniej), ale wysyłane rekordy muszą mieć komplet tagów, nie samo
   „transport / nie transport".
3. **Czy `answer` zawiera wyłącznie osoby z tagiem `transport`.** Treść tak mówi; przykład
   JSON w zadaniu pokazuje kobietę z Warszawy, ale to ilustracja formatu, nie dane.
