# Obiekty i moduły w Pythonie — co czemu odpowiada w PHP i TypeScripcie

> **Zasada jednym zdaniem:** jednostką grupowania jest **moduł**, nie klasa — a większość
> nawyków z Symfony przekłada się jeden do jednego, o ile pamięta się o tej jednej różnicy.

Notatka z 2026-08-11, spisana po serii pytań „czy tak się w Pythonie w ogóle pisze".
Adresat: ktoś, kto myśli obiektowo w PHP albo w TS i chce wiedzieć, gdzie odruch pomaga,
a gdzie zaczyna szkodzić.

---

## 1. Moduł zamiast „jedna klasa na plik"

W PHP jeden plik to jedna klasa, a przestrzeń nazw to katalog. W Pythonie **plik jest
przestrzenią nazw** i mieści tyle rzeczy, ile obejmuje jedno pojęcie — klasy, funkcje,
stałe, wyjątki, obok siebie.

```python
# prompt.py — jedno pojęcie, cztery elementy
_FENCE = "---"                       # prywatna stała

@dataclass(frozen=True, slots=True)
class Prompt: ...                    # wartość

class PromptMetadata(BaseModel): ... # DTO granicy

def parse_prompt(...) -> Prompt: ... # operacja
def _split(...) -> tuple[str, str]:  # prywatny pomocnik
```

To samo w Symfony rozpadłoby się na trzy pliki i katalog. Zysk z trzymania razem: te rzeczy
zmieniają się **jednocześnie** — zmiana formatu nagłówka dotyka wszystkich naraz.

Publiczne API modułu deklaruje się listą `__all__` na górze pliku; wszystko z podkreśleniem
na początku nazwy jest prywatne przez konwencję (język tego nie egzekwuje, narzędzia i
czytelnicy tak).

**Kiedy dzielić:** nie „gdy pojawia się druga klasa", tylko gdy moduł przestaje opisywać
jedno pojęcie albo przestaje się mieścić w głowie — kilkaset linii, nie kilkadziesiąt.

---

## 2. Klasa czy funkcja

Kryterium jest jedno i przenosi się na każdy przypadek:

| Bierz klasę, gdy | Bierz funkcję, gdy |
|---|---|
| obiekt ma **stan** między wywołaniami (sesja, cache, licznik, połączenie) | to czysta transformacja: wejście → wyjście |
| istnieje **druga implementacja** tego samego kontraktu | jest jedna, oczywista realizacja |
| chcesz wstrzykiwać zależności przez konstruktor | zależności można podać argumentami |

Klasa z jedną metodą `execute()` / `handle()` / `parse()` i bez stanu to w Pythonie
funkcja przebrana za obiekt. To najczęstsza uwaga, jaką w code review dostają ludzie
przychodzący z Javy i PHP. Nie jest to błąd stylu — PEP 8 nie mówi o tym ani słowa,
żaden linter tego nie złapie — jest to **akcent**, po którym widać, skąd się przyszło.

Odwrotna obserwacja jest równie ważna: Python celowo **wyjmuje** operacje z klas.
`len(x)`, `sorted(x)`, `json.dumps(obj)`, `copy.deepcopy(obj)`, `dataclasses.replace(obj)`
— wolne funkcje działające na cudzych obiektach. W Symfony każda z nich byłaby usługą.

---

## 3. Wstrzyknąć czy zaimportować

Klasa wołająca funkcję zaimportowaną z innego modułu to norma, nie zapach. Biblioteki
robią tak wszędzie — w `httpx` klasa `Client` importuje `get_environment_proxies` z
`._utils` i woła ją w konstruktorze.

Granica biegnie tam, gdzie **można coś podmienić**:

- **Wstrzykuj przez konstruktor**: I/O, stan, wszystko z drugą implementacją. Klient HTTP,
  klient modelu, zegar, funkcja usypiająca.
- **Importuj**: czyste transformacje. Nie ma czego podmieniać, bo dla tego samego wejścia
  zawsze zwrócą to samo.

Wstrzyknięcie czystej funkcji kupuje jedyną możliwość napisania testu, że wołający ją
**woła** — test tautologiczny, potwierdzający implementację zamiast wymagania.

Praktyczna korzyść z tego podziału jest mierzalna: testy czystej części nie potrzebują ani
dysku, ani sieci, ani atrap. Parser dostający string testuje się dziesięcioma przypadkami
w kilkadziesiąt milisekund; ten sam parser schowany w metodzie klasy czytającej pliki
wymaga dziesięciu plików tymczasowych.

---

## 4. `@property` — metoda, która udaje atrybut

```python
class Settings:
    data_dir: Path = Path("data")

    @property
    def cache_dir(self) -> Path:
        return self.data_dir / "cache"
```

Wołane **bez nawiasów**: `settings.cache_dir`. Odpowiednik `get cacheDir()` z TS i
`getCacheDir()` z PHP (albo hooków właściwości z PHP 8.4).

Domyślnie tylko do odczytu — przypisanie rzuci `AttributeError`, dopóki nie dopiszesz
`@cache_dir.setter`.

**Kiedy używać:** gdy wartość jest **wyliczana** albo **walidowana**. Zwykłe pole zostaje
zwykłym polem — publicznym. Getter i setter do atrybutu, który po prostu leży w obiekcie,
to najczystszy import nawyków z PHP i w Pythonie czyta się jak walka z językiem.

Dobrymi kandydatami są wartości pochodne i orzeczenia o obiekcie: `is_success`,
`is_idempotent`, `should_retry` — nazwy z `is_` / `has_` / `should_`, bo czytają się jak
fakt, nie jak czynność.

**Pułapka:** liczy się przy **każdym** odczycie. Nie wkłada się tam I/O ani niczego, co
kosztuje.

---

## 5. Rekordy: `@dataclass` kontra pydantic

`@dataclass` czyta adnotacje pól i generuje `__init__`, `__repr__` oraz `__eq__`.

```python
@dataclass(frozen=True, slots=True)
class ChatMessage:
    role: Role
    content: str
```

Odpowiednik w PHP 8.2+ jest bardzo bliski:

```php
final class ChatMessage {
    public function __construct(
        public readonly Role $role,
        public readonly string $content,
    ) {}
}
```

| Argument | Co robi | Co z tego masz |
|---|---|---|
| `frozen=True` | pól nie da się podmienić po utworzeniu | niezmienność; obiekt staje się hashowalny, więc może być kluczem słownika lub elementem zbioru |
| `slots=True` | pola deklarowane w `__slots__`, instancja bez `__dict__` | mniej pamięci, ale ważniejsze: **literówka w nazwie pola rzuca `AttributeError` zamiast po cichu tworzyć nowe pole** |

Wygenerowane `__eq__` daje **równość po wartości** — dwa osobno utworzone obiekty o tych
samych polach są sobie równe. W PHP trzeba to napisać ręcznie.

Dwie pułapki, na które się wchodzi:

1. Przy `frozen=True` `__post_init__` nie może zwyczajnie przypisać pola. Normalizację
   robi się przez `object.__setattr__(self, "field", value)` — i taka linia zasługuje na
   komentarz, bo sama z siebie wygląda na obejście zabezpieczenia (i nim jest).
2. Wartość domyślna musi być niezmienna. Lista czy słownik idą przez
   `field(default_factory=list)`, inaczej wszystkie instancje dzieliłyby jeden obiekt.

**Dataclass czy pydantic:**

| | `@dataclass` | `BaseModel` (pydantic) |
|---|---|---|
| waliduje dane | nie | tak, w czasie działania |
| koszt | zerowy, biblioteka standardowa | zależność, wolniejsze tworzenie |
| gdzie | wartości powstające w naszym kodzie | dane **z zewnątrz**: HTTP, plik, odpowiedź modelu |

Adnotacje typów znikają w czasie działania — dokładnie jak typy w TS. Dlatego walidacja
danych z zewnątrz jest osobną warstwą, a pydantic jest tam, czym w TS jest zod.

---

## 6. Dziedziczenie kontra `Protocol`

Nawiasy przy definicji klasy to `extends`:

```python
class Settings(BaseSettings): ...          # class Settings extends BaseSettings
class InvalidRequestError(PigletError, ValueError): ...   # wielodziedziczenie
```

Python pozwala na wiele klas bazowych, więc nawiasy trzymają listę. W PHP wybrałbyś jedną
klasę i dorzucił interfejs.

Ale **kontraktów się nie dziedziczy**. Do tego służy `Protocol` — typowanie strukturalne,
czyli dokładnie `interface` z TypeScriptu:

```python
class HTTPTransport(Protocol):
    async def send(self, request: Request) -> Response: ...


class HttpxTransport:          # <- pusto w nawiasach, żadnego "implements"
    async def send(self, request: Request) -> Response: ...
```

`HttpxTransport` spełnia kontrakt, bo **ma właściwe metody**, a nie dlatego, że to
zadeklarował. Type checker sprawdza zgodność w miejscu przekazania obiektu. Konsekwencje
praktyczne: atrapa w teście też niczego nie dziedziczy, a klasa z cudzej biblioteki może
spełniać Twój kontrakt bez jej modyfikowania.

Stąd reguła: **dziedzicz wyłącznie po to, żeby współdzielić implementację** (framework daje
Ci zachowanie — `BaseModel`, `BaseSettings`), a kontrakty opisuj `Protocol`. `ABC` zostaw
na przypadki, w których naprawdę współdzielisz kod między implementacjami.

`Protocol` pojawia się przy **drugiej** implementacji, nie przy pierwszej — interfejs na
zapas to koszt bez pokrycia.

Generyki od Pythona 3.12 mają składnię bliską TS:

```python
class Numbered[T: BaseModel](BaseModel): ...   # class Numbered<T extends BaseModel>
async def classify[T: BaseModel](records: Sequence[str], schema: type[T]) -> list[T]: ...
```

---

## 7. Ściąga

| PHP / Symfony | TypeScript | Python |
|---|---|---|
| jedna klasa na plik | jeden export na plik | moduł grupuje pokrewne rzeczy |
| `namespace` | ścieżka modułu | plik `.py` **jest** przestrzenią nazw |
| `use App\Foo;` | `import { Foo }` | `from package.module import Foo` (także funkcje i stałe) |
| `extends` | `extends` | nawiasy: `class A(B)` |
| `implements` | `implements` | **nic** — `Protocol` sprawdza strukturę |
| `interface` | `interface` | `Protocol` |
| `readonly` promocja w konstruktorze | `readonly` pola | `@dataclass(frozen=True)` |
| `getFoo()` | `get foo()` | `@property` |
| usługa bezstanowa w kontenerze | funkcja w module | funkcja w module |
| `final class X { public static function y() }` | `export function y()` | funkcja w module |

---

## 8. Czego nie robić, choć w PHP było dobre

- Klasa `Manager`, `Helper`, `Service` bez stanu, będąca workiem na funkcje.
- Interfejs albo `ABC` przy jednej implementacji, „bo może kiedyś".
- Prywatne pola z getterem i setterem zamiast publicznych atrybutów.
- Kontener DI z autowiringiem. Obiekty składa się ręcznie, w jednym miejscu wejścia do
  aplikacji — czyta się to jak lista, a nie jak konfiguracja.
- Encje i repozytoria tam, gdzie nie ma bazy danych.

Żadna z tych rzeczy nie jest błędem, który coś zepsuje. Wszystkie kosztują czytelność u
kogoś, kto Pythona zna, i wszystkie znikają, gdy zamiast pytać „jaka klasa" pyta się
„czy to ma stan i czy istnieje druga implementacja".

---

## Źródła

- PEP 8 — Style Guide for Python Code: <https://peps.python.org/pep-0008/>
- PEP 557 — Data Classes: <https://peps.python.org/pep-0557/>
- PEP 544 — Protocols: Structural subtyping: <https://peps.python.org/pep-0544/>
- PEP 695 — Type Parameter Syntax: <https://peps.python.org/pep-0695/>
- `dataclasses`: <https://docs.python.org/3/library/dataclasses.html>
- `property`: <https://docs.python.org/3/library/functions.html#property>
- pydantic, Models: <https://docs.pydantic.dev/latest/concepts/models/>
