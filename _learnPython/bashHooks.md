# Hooki jakości — jak działa ten bash

> **Zasada jednym zdaniem:** hook to zwykły skrypt, który harness uruchamia sam
> w wybranym momencie. Cała „magia" to kontrakt: JSON na stdin, kod wyjścia na wyjściu.

Dotyczy `.claude/hooks/python-quality.sh` i `.claude/hooks/quality-gate.sh`.

---

## 1. Podział pracy

| | `python-quality.sh` | `quality-gate.sh` |
|---|---|---|
| Kiedy | po każdym zapisie `.py` | przy próbie zakończenia tury |
| Zakres | **jeden plik** | **cały projekt** |
| Sprawdza | ruff (z poprawką), mypy, grep §9, grep §6 | ruff, mypy, **pytest** |
| Czas | ~0,2 s | ~0,4 s |

Ruff i mypy powtarzają się celowo. Pierwszy daje poprawkę **w tej samej turze**,
zanim powstanie pięć kolejnych plików. Drugi widzi to, czego per-plik nie widzi —
że zmiana nazwy w jednym module rozwaliła import w drugim.

## 2. Kontrakt z harnessem

| Kierunek | Co przechodzi |
|---|---|
| wejście | JSON na **stdin** — m.in. `.tool_input.file_path` |
| wyjście `0` | cicho, wszystko w porządku |
| wyjście `2` | **stderr wraca do agenta jako feedback** |
| stdout | ignorowany |

Stąd `>&2` i `exit 2`. Bez tej pary skrypt działa, ale nikt go nie słyszy.

## 3. Tryb pracy powłoki

```bash
set -uo pipefail
```

| Flaga | Co robi | Po co |
|---|---|---|
| `-u` | użycie niezdefiniowanej zmiennej = błąd | literówka wywala skrypt, zamiast po cichu podstawić puste |
| `-o pipefail` | potok zwraca kod pierwszego niezerowego | bez tego `cmd \| grep` maskuje porażkę `cmd` |

**Celowo bez `-e`.** `-e` przerywa przy pierwszej nieudanej komendzie — tutaj byłoby
szkodliwe, bo chcemy **zebrać wszystkie** problemy, a nie wyjść po pierwszym błędzie
ruffa i przemilczeć mypy.

### Pułapka, w którą wdepnąłem

`pipefail` psuje idiom `komenda | grep -q`:

```bash
# Źle — pod pipefail zwraca kod mypy (1), nie grepa (0)
if uv run mypy "$f" | grep -q "no-untyped-def"; then

# Dobrze — przechwyć wyjście, potem szukaj
out=$(uv run mypy "$f" 2>&1)
if printf '%s' "$out" | grep -q "no-untyped-def"; then
```

Logika wygląda identycznie, a pierwsza wersja raportuje porażkę przy poprawnym działaniu.

## 4. Gdzie ja jestem

```bash
ROOT="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
```

`${ZMIENNA:-domyślna}` to odpowiednik `$x ?? $y` z PHP. Harness ustawia
`CLAUDE_PROJECT_DIR`; przy ręcznym uruchomieniu wyliczamy korzeń z położenia skryptu.

`${BASH_SOURCE[0]}` to ścieżka pliku skryptu — **nie `$0`**, bo przy `source` `$0`
wskazuje na powłokę. `cd ... && pwd` normalizuje do ścieżki bezwzględnej.

## 5. Bramki wejściowe

```bash
file=$(jq -r '.tool_input.file_path // empty')
[ -z "$file" ] && exit 0
case "$file" in *.py) ;; *) exit 0 ;; esac
[ -f "$file" ] || exit 0
case "$file" in "$PROJECT"/*) ;; *) exit 0 ;; esac
```

Cztery szybkie wyjścia, od najtańszego do najdroższego:

1. brak ścieżki — `// empty` w jq daje pusty łańcuch zamiast `null`,
2. nie `.py` — hook odpala się przy **każdej** edycji, także markdown,
3. plik nie istnieje — mógł zniknąć między edycją a hookiem,
4. poza `piglet/` — edycja samego hooka nie ma iść do lintera Pythona.

`case` zamiast `if`, bo dopasowuje **wzorce glob** bez wołania zewnętrznego programu.
Pusta gałąź `*.py) ;;` znaczy „pasuje, nic nie rób, leć dalej".

## 6. Ścieżka względna

```bash
rel="${file#"$PROJECT"/}"
```

`${zmienna#wzorzec}` **ucina wzorzec z początku**. Z `/home/.../piglet/src/piglet/x.py`
robi `src/piglet/x.py`. Potrzebne do dopasowania warstwy w sekcji 9.

## 7. Uruchamianie narzędzi

```bash
uv run ruff format -q "$file" 2>/dev/null

if ! fix_out=$(uv run ruff check --fix "$file" 2>&1); then
    problems+="--- ruff ---
$fix_out
"
fi
```

Formatowanie idzie **bez sprawdzania wyniku** — ma poprawić po cichu, nie meldować.

Idiom `if ! zmienna=$(komenda)` robi trzy rzeczy naraz: uruchamia, **przechwytuje
wyjście** i sprawdza kod wyjścia. Przypisanie w bashu zwraca kod prawej strony, `!`
go odwraca.

`2>&1` scala stderr do stdout. `problems+=` dokleja — dlatego brak `-e`: każdy blok
dokłada swoje, wychodzimy dopiero na końcu.

## 8. Grep §9 — zakazane nazwy

```bash
BANNED='data|info|manager|helper|utils|handler|process|tmp|result2'
grep -nE "\b(def|class)[[:space:]]+(${BANNED})\b|^[[:space:]]*(${BANNED})[[:space:]]*[:=][^=]"
```

Tego ruff nie umie — to reguła projektu, nie standard Pythona. Dwie alternatywy:

| Część wzorca | Łapie |
|---|---|
| `\b(def\|class)[[:space:]]+(BANNED)\b` | `def process(`, `class Manager` |
| `^[[:space:]]*(BANNED)[[:space:]]*[:=][^=]` | `data = x`, `info: str` |

**`\b` na końcu jest kluczowe.** `\b` to granica słowa, a `_` jest znakiem słowa —
więc `process\b` **nie** dopasuje `process_batch`. Dokładnie o to chodzi.

`[^=]` odróżnia przypisanie `data =` od porównania `data ==`.

## 9. Grep §6 — test uniwersalności

```bash
case "$rel" in
    src/piglet/domain/*|src/piglet/adapters/*|src/piglet/app/*)
        grep -niE '(^|[^a-z])(ag3nts|powerplant|ai_?devs|hub|flg|flag|people)'
```

Egzekwuje **architekturę, nie styl**. `application/` jest pominięte celowo — tam
wiedza o kursie wolno się pojawić.

Kotwica `(^|[^a-z])` zamiast `\b` — i to jest **odwrotna decyzja niż w sekcji 8**:

| Wzorzec | `hub_client` | `github` |
|---|---|---|
| `\bhub\b` | nie łapie (błąd) | nie łapie |
| `(^\|[^a-z])hub` | **łapie** | nie łapie (`t` to litera) |

W §9 chodzi o **dokładny** identyfikator → `\b`. W §6 o **jakąkolwiek wzmiankę**,
więc złożenia też — bo domena wycieka właśnie przez `hub_client` i `HubResponse`.

## 10. Marker między hookami

`python-quality.sh` zostawia `touch .claude/.quality-pending`,
`quality-gate.sh` go konsumuje.

Dzięki temu tura bez zmian w Pythonie nie uruchamia pytesta — pytanie „co to znaczy"
nie odpala zestawu testów. Marker jest w `.gitignore`: to stan przejściowy, nie
konfiguracja.

Kasowany **tylko przy powodzeniu**. Przy porażce zostaje, więc następna próba
zakończenia tury znów odpali bramki.

## 11. Zabezpieczenie przed zapętleniem

```bash
payload=$(cat)
if [ "$(printf '%s' "$payload" | jq -r '.stop_hook_active // false')" = "true" ]; then
    exit 0
fi
```

Bez tego: hook blokuje → agent odpowiada → hook blokuje znowu → w nieskończoność.
`stop_hook_active` znaczy „już reagujesz na ten hook", więc przepuszczamy.

`payload=$(cat)` czyta stdin **raz do zmiennej** — stdin da się przeczytać tylko raz.

## 12. Funkcja z argumentami

```bash
run_gate() {
    local label="$1"; shift
    local out; out=$(uv run "$@" 2>&1); local code=$?
    if [ "$label" = "pytest" ] && [ "$code" -eq 5 ]; then return 0; fi
    ...
}
```

`local` ogranicza zmienną do funkcji — bez tego wszystko w bashu jest globalne.

`shift` zjada pierwszy argument, więc `"$@"` to reszta. **`"$@"` w cudzysłowach**
zachowuje argumenty ze spacjami jako osobne; `$@` bez cudzysłowów by je rozbił.

`pytest` z kodem **5** traktowany jak sukces — 5 znaczy „nie zebrano testów", co jest
stanem oczekiwanym, dopóki nie ma pierwszego testu. Bez tego wyjątku hook blokowałby
każdą turę.

## 13. Ściąga konstrukcji

| Konstrukcja | Znaczenie |
|---|---|
| `${x:-y}` | `x`, a jeśli puste — `y` |
| `${x#wzorzec}` | utnij wzorzec z początku |
| `$(cmd)` | podstawienie wyniku komendy |
| `$?` | kod wyjścia poprzedniej komendy |
| `"$@"` | wszystkie argumenty, każdy osobno |
| `local` | zmienna widoczna tylko w funkcji |
| `trap x EXIT` | uruchom `x` przy wyjściu, także przy błędzie |
| `[ -z "$x" ]` / `[ -n "$x" ]` | łańcuch pusty / niepusty |
| `[ -f "$x" ]` | plik istnieje |
| `>&2` | pisz na stderr |
