# Klasyfikacja porażek HTTP — jak decydować bez zgadywania

> **Zasada jednym zdaniem:** nie pytaj „która to próba", tylko „jakiego rodzaju jest ta
> porażka" — rodzaj wyznacza i decyzję o ponowieniu, i długość czekania, i typ wyjątku.

Research z 2026-08-06. Uzupełnia `httpRetryAndBackoff.md`. Źródła na końcu.

---

## 1. Trzy klasy porażki, nie dwie

Najbardziej dojrzały podział, jaki znalazłem, jest u AWS — i jest trójdzielny, nie
dwudzielny:

| Klasa | Co znaczy | Bazowe opóźnienie AWS | Dlaczego takie |
|---|---|---|---|
| **transient** | coś się potknęło: timeout, zerwane połączenie, 500/502/503/504 bez kodu | **50 ms** | „Transient errors typically resolve within milliseconds" |
| **throttling** | serwis świadomie odmówił: 429, `ThrottlingException`, `SlowDown` | **1 000 ms** | „The service has rate-limited the request. A longer base delay gives time to recover capacity" |
| **permanent** | żądanie jest złe: 400, 401, 403, 404, `ValidationException` | — nie ponawiamy | ponowienie niczego nie zmieni |

To jest kluczowe rozróżnienie, którego nie miałem w głowie: **throttling to nie jest
podtyp awarii przejściowej.** Awaria przejściowa mija sama w milisekundach, limit mija
dopiero po otwarciu okna. Traktowanie ich jednym backoffem oznacza albo za szybkie
wracanie pod limit, albo za wolne wracanie po zwykłym potknięciu.

Token bucket AWS wycenia je różnie z tego samego powodu: ponowienie po błędzie
przejściowym kosztuje 14 tokenów, po throttlingu 5 — bo throttling ma realną szansę
powodzenia, a seria 500-ek zwykle znaczy, że usługa leży.

---

## 2. Kod błędu przed statusem HTTP

AWS: „Classification is based on the **error code** and HTTP status code […]. For example,
an HTTP 400 with the error code `RequestTimeout` is classified as transient and retried.
An HTTP 400 with `ValidationException` is classified as non-retryable." I dalej: „The SDK
matches on **error code first**, then falls back to HTTP status code."

Czyli nawet 400 bywa ponawialne, a 5xx bywa nieponawialne (5xx z kodem throttlingu jest
klasyfikowany jako throttling, nie jako awaria). **Status HTTP to najsłabszy sygnał, jaki
masz** — używasz go, gdy nie masz nic lepszego.

Azure mówi to samo od strony projektanta API: „When you create services or components,
implement error codes and messages that help clients determine whether they should retry
failed operations. For example, return an `isTransient` value."

Praktyczne przykłady sygnałów w nagłówkach: `x-amz-retry-after` (AWS, milisekundy),
`x-should-retry` i `retry-after-ms` (OpenAI). Rdzeń klienta ich nie zna — zna je profil
serwisu.

---

## 3. Statusy: baza startowa, gdy nie wiesz nic o serwisie

| Status | Ponawiać | Uwagi |
|---|---|---|
| 408 Request Timeout | tak | Google i praktyka SDK-ów |
| 413 Content Too Large | *warunkowo* | urllib3 trzyma go w `RETRY_AFTER_STATUS_CODES` — bywa użyty jako throttling |
| 425 Too Early | tak | powtórzenie po zakończeniu handshake'u |
| 429 Too Many Requests | **tak, jako throttling** | prawie zawsze z `Retry-After` |
| 500, 502, 503, 504 | tak | 503 zwykle z `Retry-After` |
| 400, 401, 403, 404, 405, 409, 422 | nie | naprawia się kodem, nie ponowieniem |
| 501, 505 | nie | serwer nie umie tego w ogóle |

Google formułuje to najkrócej: ponawialne są „408, 429, and 5xx response codes" plus
zerwane połączenia i timeouty gniazda. Azure: „status code 429 (Too Many Requests) and 5xx
server errors are typical retry candidates. Most 4xx client errors, like 400, 401, 403,
and 404, indicate problems that a retry doesn't resolve."

**To jest wartość domyślna, nie prawda.** Pierwszy serwis, który zwraca 200 z błędem w
ciele albo 403 przy wygaśnięciu tokenu (do odświeżenia i ponowienia), unieważnia tę tabelę.

---

## 4. Idempotencja — warunek, o którym najłatwiej zapomnieć

RFC 9110 §9.2.2, zdanie normatywne:

> „A client **MUST NOT** automatically retry a request with a non-idempotent method unless
> it has some means of knowing the request was not processed."

I dlaczego: „Requests bearing a method that is idempotent may be automatically retried by
clients if a connection fails, **without a risk of incorrectly duplicating operations**."

Scenariusz, który to uzasadnia: serwer odebrał POST, przetworzył go, po czym padł przed
wysłaniem odpowiedzi. Klient widzi timeout, ponawia — operacja wykonuje się dwa razy.
Azure: „a service might receive the request, process the request successfully, but fail to
send a response."

**Jak to robią inni:**

- **urllib3** rozwiązuje to domyślnymi ustawieniami:
  `DEFAULT_ALLOWED_METHODS = frozenset({'DELETE', 'GET', 'HEAD', 'OPTIONS', 'PUT', 'TRACE'})`
  — POST i PATCH **nie są ponawiane**, chyba że jawnie każesz. Dokumentacja: „By default,
  we only retry on methods which are considered to be idempotent".
- **Google** klasyfikuje operacje, nie metody, na trzy grupy: zawsze idempotentne (odczyty,
  listowania), **warunkowo idempotentne** (bezpieczne dopiero z prekondycją —
  `IfMetagenerationMatch`, `etag`, numer generacji) i nigdy idempotentne (tworzenie klucza
  HMAC — każde powodzenie tworzy nowy zasób).
- **Stripe** daje mechanizm, który zamienia POST w idempotentny: nagłówek
  `Idempotency-Key` z losowym UUID v4. Serwer zapamiętuje wynik pierwszego żądania (łącznie
  z błędem 500) i zwraca ten sam wynik dla powtórzeń przez 24 h. Klucze wysyła się tylko
  przy POST — „GET and DELETE requests […] are idempotent by definition".

**Wniosek dla własnego klienta:** ponawianie POST-a bez prekondycji albo klucza
idempotencji jest naruszeniem RFC, nie tylko ryzykiem. Minimalne wyjście: pozwolić
wywołującemu zadeklarować „ta operacja jest bezpieczna do powtórzenia" i domyślnie
ponawiać tylko metody idempotentne.

---

## 5. Od klasyfikacji do typu wyjątku

Jeśli klient zna **klasę porażki**, typ wyjątku wynika z niej wprost:

| Klasa | Co się stało | Co powinien zobaczyć wywołujący |
|---|---|---|
| permanent | status nie jest ponawialny | „żądanie jest złe" — nie próbuj planu B na tym samym żądaniu |
| transient / throttling, wyczerpane próby | ponawialiśmy i nie wyszło | „przejściowe, poddaliśmy się" — plan B ma sens |
| transient / throttling, wyczerpany budżet | nie zdążyliśmy nawet spróbować | „przejściowe, zabrakło czasu" — sensowne jest odłożenie zadania |

Wyprowadzanie typu wyjątku z numeru próby (`if attempt == 1: permanent`) łączy pierwszy
wiersz z trzecim, bo **numer próby nie niesie przyczyny**. Przy jednym dozwolonym podejściu
albo przy `Retry-After` dłuższym niż budżet dostajesz „żądanie jest złe" o odpowiedzi, która
mówi wyłącznie „za wcześnie".

Azure dorzuca praktykę logowania, która z tego wynika: „Store a value in your log entries
that indicates whether **throttling** in the service or other types of faults, like
connection failures, cause retries. This approach helps you differentiate the causes during
data analysis." Czyli klasa porażki to nie tylko typ wyjątku — to również pole w dzienniku,
po którym potem filtrujesz.

I jeszcze jedno zalecenie o poziomach logowania: „log early failures as *informational
entries* and only the failure of the last of the retry attempts as an actual error" —
inaczej monitoring alarmuje przy każdej próbie, która i tak się udała za drugim razem.

---

## 6. Co z tego wynika dla `piglet`

| Praktyka | Stan |
|---|---|
| zbiór statusów ponawialnych | jest: `{429, 500, 502, 503, 504}` — **brakuje 408 i 425** |
| osobne opóźnienie bazowe dla throttlingu | brak — 429 i 503 czekają tyle samo |
| klasyfikacja porażki jako wartość | brak — `RetryDecision` niesie tylko `should_retry` |
| typ wyjątku z klasy porażki | brak — wyprowadzany z `attempt == 1` |
| **ochrona przed ponowieniem POST-a** | **brak — ponawiamy każdą metodę**, wbrew RFC 9110 §9.2.2 |
| klasa porażki w dzienniku | brak — jest status, nie ma powodu rezygnacji |
| kod błędu z ciała przed statusem | brak — i słusznie, to należy do profilu serwisu |

Najpoważniejsza pozycja to ponawianie POST-ów. W kursie skutek jest łagodny (powtórzony
`/verify` niczego nie psuje), ale narzędzie ma być uniwersalne — a pierwsze API z
płatnościami albo z tworzeniem zasobów zamienia tę wygodę w duplikaty.

---

## Źródła

- [RFC 9110 §9.2.2 — Idempotent methods](https://httpwg.org/specs/rfc9110.html#idempotent.methods)
- [AWS SDK — Retry behavior: klasyfikacja błędów, koszty tokenów](https://docs.aws.amazon.com/sdkref/latest/guide/feature-retry-behavior.html)
- [Google Cloud Storage — Retry strategy: idempotencja operacji](https://docs.cloud.google.com/storage/docs/retry-strategy)
- [urllib3 — Retry: DEFAULT_ALLOWED_METHODS, RETRY_AFTER_STATUS_CODES](https://urllib3.readthedocs.io/en/stable/reference/urllib3.util.html)
- [Stripe — Idempotent requests](https://docs.stripe.com/api/idempotent_requests)
- [Azure Architecture Center — Transient fault handling](https://learn.microsoft.com/en-us/azure/architecture/best-practices/transient-faults)
- [Azure Architecture Center — Retry pattern](https://learn.microsoft.com/en-us/azure/architecture/patterns/retry)
