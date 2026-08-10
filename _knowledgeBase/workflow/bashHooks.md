# Hooki jakości — jak działa ten bash

> **Zasada jednym zdaniem:** hook to zwykły skrypt, który harness uruchamia sam
> w wybranym momencie. Cała „magia" to kontrakt: JSON na stdin, kod wyjścia na wyjściu.

Dotyczy czterech skryptów w `.claude/hooks/`: `python-quality.sh` i `quality-gate.sh`
(bramki jakości, sekcje 1–12), oraz `write-scope.sh` i `compaction-priorities.sh`
(obsługa subagentów, sekcje 13–15).

---

## 1. Podział pracy

| | `python-quality.sh` | `quality-gate.sh` |
|---|---|---|
| Kiedy | po każdym zapisie `.py` | przy próbie zakończenia tury |
| Zakres | **jeden plik** | **cały projekt** |
| Sprawdza | ruff (z poprawką), mypy, grep §9, grep §6, grep §5 | ruff, mypy, **pytest** |
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

## 13. Grep §5 — integralność testów

Trzeci grep w `python-quality.sh`, obok §9 i §6. Łapie dwie sztuczki, którymi test
przestaje być testem, a bramka dalej świeci na zielono:

```bash
case "$rel" in
    tests/*)
        if skips=$(grep -nE '@pytest\.mark\.(skip|xfail)|pytest\.skip\(' "$file"); then
        ...
        if grep -qE '^[[:space:]]*(async[[:space:]]+)?def test_' "$file" \
            && ! grep -qE '^[[:space:]]*assert\b|pytest\.raises' "$file"; then
```

Drugi warunek to idiom **„definiuje testy, ale nic nie asertuje"**: `grep -q A && ! grep -q B`.
`-q` nie wypisuje nic, liczy się tylko kod wyjścia, więc oba `grep`i działają tu jak
predykaty logiczne.

### Dlaczego stan pliku, a nie diff

Można było porównywać `old_string` z `new_string` z payloadu — tak robi to rozwiązanie,
z którego brałem pomysł. Odpuściłem, bo:

| Podejście | Łapie | Nie łapie |
|---|---|---|
| diff (`old` vs `new`) | asercje **usunięte tą edycją** | pliku, który powstał od razu pusty |
| stan pliku po edycji | **każdy** wypatroszony test, niezależnie od drogi | — |

Koszt: plik, który miał `skip` już wcześniej, przypomina o sobie przy każdej edycji.
To akceptowalne — `skip` w tym projekcie ma być zdarzeniem, nie tłem.

### Pułapka: `assert` w Pythonie nie ma nawiasu

Oryginał, na którym się wzorowałem, liczył asercje wyrażeniem `assert\w*\s*\(` — czyli
wymagał nawiasu po słowie. To działa dla JS (`expect(...)`) i C# (`Assert.True(...)`),
ale **w Pythonie `assert x == y` to instrukcja, nie wywołanie**. Sprawdziłem na żywym
teście: regex nie złapał ani jednej prawdziwej asercji, za to trafił przypadkiem
w nazwę metody `should_retry(`. Cichy fałszywy spokój — najgorszy rodzaj.

Stąd `^[[:space:]]*assert\b`: zakotwiczone na początku linii (po wcięciu), bez nawiasu.

## 14. `write-scope.sh` — hook podpięty z frontmattera agenta

Do tej pory hooki żyły w `.claude/settings.json` i obowiązywały **zawsze**. Ten jest inny:
deklaruje go subagent w swoim własnym frontmatterze, więc reguła obowiązuje **tylko
dopóki ten agent działa**.

```yaml
hooks:
  PreToolUse:
    - matcher: "Edit|Write|NotebookEdit"
      hooks:
        - type: command
          command: $CLAUDE_PROJECT_DIR/.claude/hooks/write-scope.sh ".piglet-work/" "The reviewer"
```

| | hook z `settings.json` | hook z frontmattera agenta |
|---|---|---|
| Zasięg | cała sesja | jeden agent |
| Po co | reguły projektu | rola agenta (np. reviewer nie pisze kodu) |

`matcher` dopasowuje **nazwy narzędzi**, nigdy ścieżki. Decyzja o ścieżce zapada
w skrypcie — dlatego `Edit|Write|NotebookEdit` łapie wszystkie trzy, a dopiero bash
sprawdza, dokąd ten zapis leci.

### Argumenty i normalizacja ścieżki

```bash
allowed="${1:?allowed prefix required}"
role="${2:-This agent}"
```

| Konstrukcja | Zachowanie przy braku argumentu |
|---|---|
| `${1:?komunikat}` | **przerywa skrypt** z tym komunikatem — argument obowiązkowy |
| `${2:-domyślna}` | podstawia wartość domyślną — argument opcjonalny |

Ścieżka z payloadu przychodzi raz bezwzględna, raz względna, więc sprowadzam ją do
jednej postaci przed porównaniem:

```bash
case "$file" in
    /*) rel="${file#"$ROOT"/}" ;;
    *)  rel="$file" ;;
esac
```

`/*` to wzorzec `case`, nie regex — „zaczyna się od ukośnika".

## 15. `compaction-priorities.sh` — `PreCompact` ma inny kontrakt

Tu tabela z sekcji 2 przestaje obowiązywać i to jest cała lekcja tego skryptu.

| | bramki (`PostToolUse`, `Stop`) | `PreCompact` |
|---|---|---|
| Jak przekazuje wynik | `exit 2` + stderr | **JSON na stdout**, `exit 0` |
| stdout | ignorowany | **jedyny kanał** |
| Co robi | blokuje | dokłada tekst do promptu kompaktowania |

Czyli: `>&2` i `exit 2`, na których stoją tamte hooki, tutaj nie zrobiłyby nic.

### Heredoc do zmiennej

```bash
read -r -d '' PRIORITIES <<'EOF'
...tekst wielolinijkowy...
EOF
```

| Element | Po co |
|---|---|
| `-r` | backslash zostaje znakiem, nie ucieczką |
| `-d ''` | czytaj **do końca**, a nie do pierwszego `\n` |
| `<<'EOF'` | apostrofy wokół `EOF` = **brak podstawień** `$` w treści |

Pułapka: `read -d ''` kończy się kodem **niezerowym** (doszedł do EOF, nie do
separatora). Pod `set -e` ubiłoby to skrypt w tym miejscu. Tutaj przechodzi, bo —
jak w sekcji 3 — `-e` świadomie nie ma.

### JSON składany `jq`, nie `printf`

```bash
jq -n --arg ctx "$PRIORITIES" \
    '{hookSpecificOutput: {hookEventName: "PreCompact", additionalContext: $ctx}}'
```

`-n` znaczy „nie czytaj wejścia, zbuduj od zera". `--arg` wstawia zmienną **jako
poprawnie zakodowany string** — sam ucieka cudzysłowy i zamienia znaki nowej linii
na `\n`. Ręczne sklejanie tego `printf`em wywraca się na pierwszym apostrofie w treści.

## 16. Ściąga konstrukcji

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
| `${x:?komunikat}` | argument obowiązkowy — brak przerywa skrypt |
| `grep -q` | predykat: sam kod wyjścia, bez wypisywania |
| `read -r -d '' V <<'EOF'` | heredoc do zmiennej, bez podstawień |
| `jq -n --arg k "$v"` | zbuduj JSON od zera, bezpiecznie kodując `$v` |
| `case $x in /*)` | wzorzec globa, **nie** regex |
