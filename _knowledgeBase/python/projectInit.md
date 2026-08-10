# Inicjalizacja projektu — uv i zależności

> **Zasada jednym zdaniem:** wersje pakietów wpisuje narzędzie, nigdy ręka.
> Jeśli wpisujesz numer wersji z palca — zgadujesz.

---

## 1. Mapa: uv ↔ composer

`uv` jest dla Pythona tym, czym `composer` dla PHP. Odpowiedniki są niemal jeden do jednego:

| uv | composer | rola |
|---|---|---|
| `pyproject.toml` | `composer.json` | **deklaracja** — czego projekt chce |
| `uv.lock` | `composer.lock` | **fakt** — co dokładnie zainstalowano |
| `.venv/` | `vendor/` | same paczki na dysku |
| `uv init` | `composer init` | szkielet projektu |
| `uv add X` | `composer require X` | widełki **+** rozwiązanie **+** instalacja **+** lock |
| `uv add --dev X` | `composer require --dev X` | to samo, grupa deweloperska |
| `uv remove X` | `composer remove X` | usunięcie |
| `uv sync` | `composer install` | odtworzenie dokładnie z locka |
| `uv lock --upgrade` | `composer update` | przeliczenie locka |
| `uv run pytest` | `vendor/bin/phpunit` | uruchomienie z venv projektu |

Do repo idą `pyproject.toml`, `uv.lock` i `.python-version`. `.venv/` do `.gitignore` —
dokładnie jak `composer.lock` vs `vendor/`.

---

## 2. Czego NIE robić

Świat sprzed uv. Jeśli w tutorialu widzisz to poniżej, tutorial jest stary:

```bash
# Źle — ręczne środowisko i pip
python -m venv .venv
source .venv/bin/activate
pip install httpx
```

```bash
# Dobrze — uv robi jedno i drugie
uv add httpx
uv run python -c "import httpx"
```

Nie ma czego „aktywować". `uv run` sam znajduje `.venv` projektu.

---

## 3. Kolejność startu nowego projektu

```bash
uv init --package nazwa       # 1. szkielet: układ src/, importowalny pakiet
cd nazwa
uv python pin 3.12            # 2. przypięcie interpretera -> .python-version
uv add httpx pydantic         # 3. zależności runtime
uv add --dev ruff mypy pytest # 4. narzędzia
                              # 5. [tool.ruff] / [tool.mypy] — ręcznie, patrz 4
```

Warianty `uv init`:

| Flaga | Układ | Kiedy |
|---|---|---|
| `--package` | `src/nazwa/`, pakiet instalowalny | **domyślny wybór** — `tests/` może zrobić `import nazwa` |
| `--app` | luźny skrypt | jednorazowe narzędzie |
| `--lib` | pakiet pod publikację | biblioteka na PyPI |

---

## 4. Dwie kategorie w `pyproject.toml`

To jest sedno całego pliku. `pyproject.toml` miesza dwie rzeczy o **przeciwnych** regułach:

| Kategoria | Przykład | Kto to pisze |
|---|---|---|
| **Fakty o świecie** | `mypy>=2.3.0` | **narzędzie** (`uv add`), nigdy ręka |
| **Twoje decyzje** | `select = [...]`, `max-args = 6`, `strict = true` | **ręka**, nigdy narzędzie |

Widełki wersji są faktem — uv je zna, ja nie. Reguły lintera są decyzją —
żadne narzędzie nie zna zasad z `CLAUDE.md`.

---

## 5. Pułapki, na które już wdepnąłem

**`uv add` na już zadeklarowanym pakiecie nic nie robi.**
Jeśli `pyproject.toml` ma `mypy>=1.14`, a zainstalowany jest `2.3.0`, to `uv add mypy`
uzna, że widełki są spełnione, i wyjdzie bez zmian. Żeby przepisać widełki:

```bash
uv remove --dev mypy
uv add --dev mypy      # dopiero teraz wpisze >=2.3.0
```

**Za niskie widełki to nie kosmetyka.** Realny przypadek z tego projektu:
konfiguracja ruffa wybierała reguły `UP046`/`UP047`, a zadeklarowane było `ruff>=0.9` —
wersja, która tych reguł jeszcze nie zna. `uv.lock` przypina konkretną wersję, więc
lokalnie działało; deklaracja mimo to kłamała.

**`uv init` nie wygeneruje konfiguracji jakości.** Daje 17 linii boilerplate'u.
Sekcje `[tool.ruff]`, `[tool.mypy]`, `[tool.pytest]` piszesz sam — bo to Twoje decyzje.

---

## 6. Ściąga komend

| Komenda | Co robi |
|---|---|
| `uv sync` | odtwarza środowisko z locka — **pierwsza komenda po `git clone`** |
| `uv add X` / `uv add --dev X` | dodaje zależność |
| `uv remove X` | usuwa |
| `uv lock --upgrade` | podnosi wersje w locku |
| `uv run <cmd>` | uruchamia w środowisku projektu |
| `uv python pin <wersja>` | zapisuje `.python-version` |
| `uv tree` | drzewo zależności |
| `uvx <narzędzie>` | uruchamia narzędzie bez instalowania go w projekcie |
