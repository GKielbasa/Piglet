# Ponowienia, backoff i limity — co jest uniwersalne, a co nigdy nie będzie

> **Zasada jednym zdaniem:** uniwersalny jest *mechanizm* ponawiania, nigdy *decyzja*
> kiedy ponowić — decyzja zależy od serwisu i musi być wstrzykiwana z zewnątrz.

Research z 2026-08-06. Źródła na końcu pliku.

---

## 1. Odpowiedź na pytanie „czy w 100% uniwersalny klient istnieje"

**Nie istnieje i nikt poważny go nie buduje.** Wszystkie duże biblioteki mają ten sam
kształt: uniwersalny rdzeń plus profil dopasowany do konkretnego API. Dowody:

- **AWS** ma jeden ustandaryzowany tryb `standard` we wszystkich swoich SDK — i mimo to
  klient DynamoDB dostaje inne domyślne: `base delay` 25 ms zamiast 50 ms i 4 próby
  zamiast 3, „to match their low-latency profile". Jeden dostawca, jedna firma, jeden
  zespół — a i tak profil per usługa.
- **Azure** pisze wprost: „Many resources and services have well-documented
  transient-failure contracts. When this information isn't available, it becomes harder
  to determine the nature of the fault" oraz „Use the built-in retry mechanism when a
  built-in option is available, unless you have specific and well-understood
  requirements". Czyli: **domyślnie ufaj profilowi dostawcy, nie własnemu**.
- **Google** decyduje o ponowieniu nie po statusie, tylko po **idempotentności operacji**
  — ta sama odpowiedź 503 jest ponawialna dla `get`, a niebezpieczna dla „utwórz klucz
  HMAC".
- **IETF** dopiero teraz standaryzuje nagłówki limitów, bo `X-RateLimit-*` używa
  „inconsistent interpretations (seconds, milliseconds, UNIX timestamps, datetime
  formats)" — jeden nagłówek, cztery znaczenia, zależnie od serwisu.

### Podział odpowiedzialności, który z tego wynika

| Warstwa | Co zawiera | Czy uniwersalna |
|---|---|---|
| **Rdzeń** | wysyłka, timeouty, pętla prób, backoff z jitterem, budżet ponowień, log każdej próby, obsługa `Retry-After` jako mechanizm | **tak** — piszesz raz |
| **Profil serwisu** | które statusy i kody błędów są przejściowe, którym nagłówkom wierzyć i jak je czytać, które operacje są idempotentne, ile czekania wolno | **nie** — jeden na integrację |
| **Wywołanie** | czy ta konkretna operacja jest bezpieczna do powtórzenia, czy wynik da się cache'ować | **nie** — decyzja per żądanie |

To jest dokładnie granica portu i adaptera. Rdzeń nie ma prawa wiedzieć, z kim gada;
profil jest wstrzykiwany.

---

## 2. Nagłówki, którym można wierzyć

### `Retry-After` — jedyny w pełni ustandaryzowany (RFC 9110 §10.2.3)

```
Retry-After = HTTP-date / delay-seconds
delay-seconds = 1*DIGIT
```

- „It is used with a 503 (Service Unavailable) or 429 (Too Many Requests) status code to
  communicate when a client may retry" — a także z 3xx.
- Dwie formy: `Retry-After: 120` albo `Retry-After: Fri, 31 Dec 1999 23:59:59 GMT`.
  **Obie musisz obsłużyć**, bo serwis wybiera dowolnie.
- Azure: „When a response includes a `Retry-After` header, follow it and wait at least
  the specified duration before the next attempt. This server-provided signal reflects
  the service's recovery timeline and **takes precedence over your client-side back-off
  calculation**."

### `RateLimit` i `RateLimit-Policy` — draft IETF, warto znać

Nowy standard zastępuje bałagan `X-RateLimit-*`. Składnia to Structured Fields (RFC 9651):

```
RateLimit-Policy: "burst";q=100;w=60,"daily";q=1000;w=86400
RateLimit: "default";r=50;t=30
```

- `q` — przydzielony limit, `w` — okno w sekundach, `r` — ile zostało, `t` — okno, w którym
  ta reszta obowiązuje.
- **Precedencja jest zdefiniowana:** „If a response contains both the Retry-After and
  RateLimit fields, the Retry-After field MUST take precedence."
- I ostrzeżenie dla klienta: nie zakładaj, że dodatni limit gwarantuje obsługę — to
  wskazówka, nie umowa.

### `X-RateLimit-Reset` — pułapka, nie standard

Draft IETF wymienia to jako problem interoperacyjności: ta sama nazwa bywa sekundami,
milisekundami, timestampem uniksowym albo datą. **Nie da się tego odczytać poprawnie bez
wiedzy o konkretnym serwisie.** Heurystyka „duża liczba to timestamp" jest zgadywaniem —
w profilu serwisu to jest jedna linia konfiguracji, w rdzeniu to jest bug czekający na
okazję.

### Nagłówki własne dostawców

- AWS: `x-amz-retry-after` (milisekundy), a SDK **przycina** wartość do
  `[wyliczony backoff, wyliczony backoff + 5 s]` i nie dokłada do niej jittera, „because
  the service is expected to jitter it".
- OpenAI, Stripe i inni dokładają własne (`retry-after-ms`, `x-should-retry`).

To kolejny dowód na to samo: rdzeń rozumie `Retry-After`, profil rozumie resztę.

---

## 3. Backoff i jitter — trzy warianty, tylko jeden dobrze rozprasza

Cel jittera to **thundering herd**: tysiąc klientów dostaje 503 w tej samej sekundzie i
wraca w tej samej sekundzie.

| Wariant | Wzór | Rozrzut przy backoffie 8 s |
|---|---|---|
| bez jittera | `base · 2ⁿ` | zerowy — wszyscy wracają w tej samej chwili |
| **doklejony ogon** (nasz obecny, urllib3) | `base · 2ⁿ + U(0, jitter)` | `[8.0, 8.5]` przy `jitter=0.5` — praktycznie zerowy |
| równy (equal jitter) | `t/2 + U(0, t/2)` | `[4, 8]` |
| **pełny (full jitter, AWS)** | `U(0, 1) · min(cap, base · 2ⁿ)` | `[0, 8]` — pełne rozproszenie |

Formuła AWS dosłownie:

```
delay = random(0, 1) × min(20_000 ms, base_delay × 2^retry)
```

Wniosek, którego się nie spodziewałem: **doklejony ogon jittera przestaje działać wraz ze
wzrostem opóźnienia.** Przy pierwszym ponowieniu `[0.5, 1.0]` to jeszcze rozrzut 2:1, przy
piątym `[8.0, 8.5]` to szum na poziomie 6%. Full jitter rozprasza tak samo dobrze na
każdym poziomie, bo losuje **całe okno**, nie ogon.

Cena full jittera: bywa krótszy niż potrzeba (losowanie może dać 0.1 s zamiast 8 s), więc
przy usłudze, która naprawdę potrzebuje czasu, marnujesz próbę. Dlatego AWS stosuje różne
`base_delay` dla różnych klas błędów (patrz `httpErrorClassification.md`).

**Zawsze ustaw górny limit pojedynczego opóźnienia:** AWS 20 s, urllib3
`DEFAULT_BACKOFF_MAX = 120` s.

---

## 4. Dwa różne budżety, których nie wolno mylić

| Budżet | Co ogranicza | Kto go ma |
|---|---|---|
| **czasu jednego żądania** | suma czekania w jednym wywołaniu | my (`max_total_delay_seconds`) |
| **ponowień w procesie** | ile ponowień na sekundę w ogóle wolno wysłać | AWS (token bucket), Azure (zalecenie) |

Drugiego u nas nie ma i to jest realna dziura przy `asyncio.gather` na wielu żądaniach.

**Token bucket AWS, konkretne liczby:** pojemność 500 tokenów, ponowienie po błędzie
przejściowym kosztuje 14 tokenów, po throttlingu 5, sukces zwraca tyle, ile pobrała ostatnia
próba (sukces bez ponowień zwraca 1). Gdy budżet spadnie do zera, SDK **przestaje ponawiać
i zwraca błąd natychmiast** — „your application fails fast instead of waiting through
retries that are unlikely to succeed". Przy domyślnych 3 próbach budżet zaczyna spadać
dopiero powyżej ~22% trwałych porażek.

Azure formułuje to samo prościej: „you might allow a process to do no more than 60 retries
per minute against a specified dependency. If you exhaust the budget, fail the request
immediately instead of retrying." I uzasadnia: „Per-request retry limits alone can't
prevent a scenario where many concurrent requests each retry a few times and collectively
overwhelm a struggling downstream service."

---

## 5. Ponawiaj na jednej warstwie

Azure nazywa to antywzorcem *retry storm*: „consider one component that makes a request to
another, which then accesses the target service. A retry with a count of three on both
calls adds up to **nine retry attempts** in total."

Praktyczna konsekwencja dla nas: skoro `ResilientHTTPClient` ponawia, to warstwa zadania
**nie ma prawa** ponawiać drugi raz. A jeśli kiedyś dojdzie SDK dostawcy z własnym retry
(np. `openai` ma wbudowane) — trzeba je wyłączyć albo wyłączyć nasze. Nigdy oba.

Dodatkowo: „Never implement an endless retry mechanism" i „Never do an immediate retry
more than once".

---

## 6. Timeout jest warunkiem wstępnym, nie dodatkiem

Azure: „Set timeouts on every outbound call **before** you implement retry logic. […] A
retry strategy is only as effective as the timeouts that govern each individual attempt.
Timeouts that are too long cause threads and connections to accumulate during outages."

Całkowity czas operacji to `(timeout + opóźnienie) × liczba prób` — i to jest liczba, którą
porównujesz z SLO, nie sam backoff.

W `httpx` timeout ma cztery składowe i można je ustawić osobno:

```python
httpx.Timeout(connect=5.0, read=30.0, write=10.0, pool=5.0)
```

Jedna liczba (`timeout=30.0`) ustawia wszystkie cztery — wygodne, ale zwykle za hojne dla
`connect` i za skąpe dla `read` przy dużych plikach.

---

## 7. Circuit breaker — kiedy naprawdę

Nie przy jednej usłudze i nie „na zapas". Sensowny, gdy ponowienia przestają pomagać:
Azure — „if the number of failures within a specified time window exceeds a threshold,
requests return to the caller immediately as errors". Token bucket AWS to w praktyce
tańszy wariant tego samego pomysłu: nie odcina usługi, tylko odcina *ponawianie*.

---

## 8. Co z tego wynika dla `piglet`

| Praktyka | Stan | Gdzie |
|---|---|---|
| `Retry-After` w obu formach | **jest** | `domain/http/retry_policy.py` |
| backoff wykładniczy + jitter | jest, ale wariant „doklejony ogon" | `_backoff_seconds` |
| **full jitter** | brak — jitter przestaje rozpraszać przy dużych opóźnieniach | — |
| **cap na pojedyncze opóźnienie** | brak — jest tylko budżet sumaryczny | — |
| budżet czasu jednego żądania | jest (`max_total_delay_seconds`) | — |
| **budżet ponowień w procesie** | brak — istotne przy `asyncio.gather` | — |
| **idempotencja przed ponowieniem** | brak — ponawiamy POST-y bez zabezpieczenia | patrz `httpErrorClassification.md` |
| profil serwisu wstrzykiwany | brak — zbiór statusów i odczyt nagłówków są zaszyte w rdzeniu | — |
| timeouty rozbite na składowe | brak — jedna liczba na wszystko | `app/container.py` |
| log każdej próby | jest | `adapters/http/resilient_client.py` |
| ponawianie na jednej warstwie | jest, do pilnowania przy SDK dostawców | — |

---

## Źródła

- [RFC 9110 §10.2.3 — Retry-After](https://httpwg.org/specs/rfc9110.html#field.retry-after)
- [draft-ietf-httpapi-ratelimit-headers — RateLimit header fields for HTTP](https://datatracker.ietf.org/doc/html/draft-ietf-httpapi-ratelimit-headers)
- [AWS SDK — Retry behavior (tryby, formuła full jitter, token bucket)](https://docs.aws.amazon.com/sdkref/latest/guide/feature-retry-behavior.html)
- [Azure Architecture Center — Transient fault handling](https://learn.microsoft.com/en-us/azure/architecture/best-practices/transient-faults)
- [Azure Architecture Center — Retry pattern](https://learn.microsoft.com/en-us/azure/architecture/patterns/retry)
- [urllib3 — Retry: wartości domyślne i wzór backoffu](https://urllib3.readthedocs.io/en/stable/reference/urllib3.util.html)
- [Google Cloud Storage — Retry strategy](https://docs.cloud.google.com/storage/docs/retry-strategy)
