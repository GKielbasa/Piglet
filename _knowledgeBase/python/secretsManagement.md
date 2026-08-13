# Sekrety — gdzie mieszkają, jak nie wyciekają, kiedy `.env` przestaje wystarczać

> **Zasada jednym zdaniem:** sekret ma jedno miejsce zamieszkania i wiele miejsc, w których
> zabraniamy mu się pojawić — i to te drugie wymagają kodu.

Research z 2026-08-06. Źródła na końcu.

---

## 1. Hierarchia miejsc przechowywania (OWASP)

Od najlepszego:

1. **Menedżer sekretów** — HashiCorp Vault, AWS Secrets Manager, Azure Key Vault, GCP
   Secret Manager. Daje trzy rzeczy naraz: kontrolę dostępu, dziennik odczytów i rotację.
2. **Sidecar / wolumen montowany** przez orkiestrator — nigdy wbudowany w obraz, „as this
   will leak the secret".
3. **Zmienne środowiskowe** — akceptowalne, ale **najsłabsze**.
4. Plik konfiguracyjny w repo, kod źródłowy — nigdy.

Zarzuty OWASP wobec zmiennych środowiskowych są konkretne i warto je znać, zanim się je
zlekceważy: „secrets are generally accessible to all processes and may be included in logs
or system dumps", widać je w `kubectl describe pod` i w inspekcji kontenera, i nie da się
ich rotować bez restartu procesu. Osobno: **nigdy** `ENV`/`ARG` w Dockerfile — to ląduje w
warstwach obrazu na zawsze.

**Kiedy `.env` wystarcza:** projekt lokalny, jeden deweloper, sekrety o niskiej wartości,
brak współdzielonej infrastruktury. Dokładnie nasz przypadek.
**Kiedy przestaje:** pierwszy wspólny deploy, pierwszy CI z prawdziwym kluczem, pierwszy
sekret, którego kompromitacja kosztuje pieniądze.

---

## 2. Cykl życia, nie „ustaw i zapomnij"

OWASP rozbija to na cztery etapy, każdy z własnymi regułami:

| Etap | Reguła |
|---|---|
| **utworzenie** | generuj kryptograficznie mocno, przekazuj bezpiecznym kanałem — nigdy Slackiem ani mailem |
| **rotacja** | automatycznie i regularnie; „the shorter the lifespan of a secret, the smaller the window of opportunity" |
| **unieważnienie** | natychmiast po podejrzeniu wycieku, **przed** sprzątaniem |
| **wygaśnięcie** | „create secrets to expire after a defined time where possible" |

Do tego **least privilege**: „Engineers should not have access to all secrets in the secrets
management system" — a klucz w CI ma widzieć tylko to, czego potrzebuje ten pipeline.

Kolejność przy wycieku jest nieoczywista i warto ją pamiętać: **unieważnij → rotuj →
posprzątaj ślady → zaudytuj dostępy.** Sprzątanie repozytorium jako pierwsze jest błędem —
przez ten czas klucz nadal działa.

---

## 3. Sekret w URL to najgorszy przypadek — a czasem nie masz wyboru

OWASP: „Never transmit secrets via plaintext", nagłówek przez TLS zamiast parametru w
adresie. Powód jest przyziemny: URL trafia do logów serwera, do proxy, do historii
przeglądarki, do nagłówka `Referer` i do każdego systemu monitoringu po drodze — a ciało i
nagłówki nie.

Problem: **to nie zawsze jest twoja decyzja.** Bywają API, które trzymają klucz w ścieżce
(`/data/{apikey}/zasob.csv`) — wtedy każde żądanie ma sekret w adresie i nie da się tego
obejść.

Co wtedy robisz — i to jest realna konsekwencja projektowa, nie kosmetyka:

1. traktujesz **URL jako pole zawierające sekret**, a nie jako identyfikator,
2. **redagujesz przy wyjściu do logu**, a nie licząc na to, że nikt go nie zaloguje,
3. nie wkładasz URL-i do cache'owanych nazw plików ani do komunikatów wyjątków, które
   trafiają wyżej.

Reguła „nie logujemy nagłówków" jest tu **niewystarczająca** — sekret jest w polu, które
logujesz zawsze.

---

## 4. Sekrety w logach — maskowanie na wyjściu

OWASP: „must implement either an encryption or masking approach in place to avoid logging
plaintext secrets."

Dwa podejścia, oba mają sens i najlepiej działają razem:

| Podejście | Jak działa | Słabość |
|---|---|---|
| **denylist wartości** | procesor podmienia znane wartości sekretów na `***` w każdym polu | chroni tylko sekrety, które mu podałeś |
| **allowlist pól** | logujesz wyłącznie wypisane pola (`status_code`, `duration_ms`), nigdy „całą odpowiedź" | wymaga dyscypliny przy dokładaniu pól |

W Pythonie denylistę robi się jako procesor `structlog`, wpięty **przed** rendererem:

```python
def _build_redactor(secrets: Sequence[SecretStr]) -> Processor:
    needles = tuple(s.get_secret_value() for s in secrets if s.get_secret_value())

    def redact(logger, method_name, event_dict):
        for key, value in event_dict.items():
            if isinstance(value, str):
                for needle in needles:
                    value = value.replace(needle, "***")
                event_dict[key] = value
        return event_dict

    return redact
```

Dwie pułapki, obie kosztują ciszą, nie błędem:

- **pusty sekret** — `"".replace()` dopasowuje się między każdą parą znaków; niewyfiltrowany
  pusty ciąg zamienia cały log w `***`,
- **denylista musi być kompletna** — sekret, którego procesor nie zna, przechodzi w całości.
  Dlatego lepiej wyprowadzać ją z konfiguracji automatycznie (wszystkie pola `SecretStr`)
  niż wypisywać ręcznie.

Poza tym Azure zaleca, żeby logi **nie były** jedynym zabezpieczeniem: monitoruj dostępy do
sekretów i alarmuj na wzorce.

---

## 5. Co daje `SecretStr` w Pythonie, a czego nie daje

```python
class Settings(BaseSettings):
    openrouter_api_key: SecretStr = SecretStr("")
```

**Daje:** `repr()` i `str()` zwracają `**********`, więc `print(settings)`, wyjątek
pydantica, log pola i traceback nie ujawniają wartości. Wartość wyciągasz jawnie —
`get_secret_value()` — i to wywołanie jest widoczne w review jako świadoma decyzja.

**Nie daje:** ochrony pamięci (wartość leży w `str` w RAM — OWASP wspomina o `bytearray` i
zerowaniu, ale w Pythonie to walka z niezmiennością `str`), ochrony przed świadomym
wypisaniem, ani niczego po stronie sieci.

Czego jeszcze używa się w Pythonie:

- **`pydantic-settings`** — jedno miejsce czytania środowiska i `.env`, z walidacją. Sekret
  nigdy nie jest czytany przez `os.environ` w losowym miejscu kodu.
- **`keyring`** — pęk kluczy systemu operacyjnego dla narzędzi lokalnych; lepszy niż `.env`
  na stacji roboczej, bezużyteczny w kontenerze.
- **`detect-secrets` / `gitleaks`** w `pre-commit` — skan przed commitem. My mamy już
  własny hook `pre-commit`, więc dołożenie skanera to jedno wywołanie.

---

## 6. Wykrywanie wycieku, zanim zrobi to ktoś inny

OWASP zaleca skanowanie **czterech** miejsc, nie jednego: kod źródłowy, **historia
commitów**, logi i pliki konfiguracyjne. Plus korelacja wyników z kilku narzędzi, żeby
ograniczyć fałszywe alarmy.

Historia commitów jest najczęściej pomijana i najgroźniejsza: `git rm` usuwa plik z HEAD,
nie z historii. Klucz, który był w repozytorium przez pięć minut i został „usunięty", nadal
tam jest — a jeśli repo było publiczne, należy zakładać, że został pobrany.

---

## 7. Maska nie odróżnia atrapy od prawdziwego klucza

**Placeholder w `.env` wygląda w wyjściu dokładnie tak samo jak działający sekret**
(`**********`). Konfiguracja mówi wtedy „wartość jest", choć wartość jest bez sensu,
a dowiesz się o tym dopiero z 401 od serwera.

Argument za tym, żeby maskowanie odróżniało „brak wartości" od „wartość jest" — na przykład
wypisując długość albo cztery ostatnie znaki zamiast stałej liczby gwiazdek. Koszt zerowy,
a diagnoza skraca się z kwadransa do sekundy.

## 8. Lista kontrolna sekretów

sekrety poza kodem i poza repo · **jedno** miejsce czytania środowiska · `SecretStr`
w konfiguracji · redakcja przy wyjściu do dziennika · denylista **wyprowadzona
z konfiguracji**, nie przepisana ręcznie — inaczej nowe pole nie jest chronione ·
allowlist logowanych pól zapisana jako reguła, nie jako przypadek · skaner sekretów
w `pre-commit` · rotacja, wygasanie i least privilege — od pierwszego CI, nie wcześniej.

---

## Źródła

- [OWASP — Secrets Management Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Secrets_Management_Cheat_Sheet.html)
- [Microsoft Learn — Best practices for protecting secrets](https://learn.microsoft.com/en-us/azure/security/fundamentals/secrets-best-practices)
- [AWS Secrets Manager — best practices](https://docs.aws.amazon.com/secretsmanager/latest/userguide/best-practices.html)
- [pydantic — SecretStr](https://docs.pydantic.dev/latest/api/types/#pydantic.types.SecretStr)
