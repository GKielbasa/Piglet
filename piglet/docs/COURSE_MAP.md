# Mapa kursu AI_devs 4 → moduły `piglet`

Żywy dokument. Po każdej lekcji uzupełniamy kolumnę „moduł" i status.

Legenda statusu: `—` nie zaczęte · `WIP` w toku · `✓` zrobione

## Sezon 1 — fundamenty

| Lekcja | Zdolności techniczne | Moduł | Zadanie | Status |
|---|---|---|---|---|
| S01E01 | structured outputs / JSON Schema, dobór modeli, organizacja instrukcji w kodzie, few/many-shot | `llm/`, `hub/`, `core/http` | **people** — CSV → filtr → klasyfikacja tagów → `/verify` | — |
| S01E02 | function calling, schematy narzędzi, walidacja i zabezpieczenia, workflow vs agent, transformacja zapytań, dynamiczne listy narzędzi, prompt injection | `tools/`, `agent/` | **findhim** — orkiestracja `/api/location` + `/api/accesslevel`, dopasowanie geo do elektrowni | — |
| S01E03 | threat modeling, least privilege, dry-run + HITL, audit trail, zarządzanie sekretami | `config`, `core/trace`, `hub` (dry_run) | ⚠️ **brak pliku lekcji w `teoria/`** — jest tylko transkrypcja wideo | — |
| S01E04 | vision, PDF, audio, wideo, generowanie i edycja obrazów | `llm/` (multimodal), `core/http` | **sendit** — crawl dokumentacji markdown + vision na grafikach + sztywny szablon deklaracji | — |
| S01E05 | limity jawne i niejawne, rate limity, retry na 503, środowisko produkcyjne | `core/http` (retry/backoff), `core/cache` | **railway** — samodokumentujące API, aktywacja trasy X-01 pod ostrymi limitami | — |

## Sezon 2 — kontekst i agenty

| Lekcja | Zdolności techniczne | Moduł | Status |
|---|---|---|---|
| S02E01 | dynamiczna instrukcja systemowa, stan poza oknem kontekstu, maskowanie kontekstu, planowanie i monitorowanie postępów | `agent/context` | — |
| S02E02 | indeksowanie, bazy wektorowe, wyszukiwanie semantyczne, retrieval, RAG | `rag/` | — |
| S02E03 | baza wiedzy jako narzędzie, kategoryzacja, mapa zasobów, grafy, długie formy | `rag/`, `memory/` | — |
| S02E04 | wielowątkowość, globalny kontekst, podział narzędzi między agentów, manager | `agent/` (multi) | — |
| S02E05 | projektowanie agenta: instrukcja, zakres odpowiedzialności, zestaw narzędzi, przypisana wiedza | `agent/` | — |

## Sezon 3 — obserwowalność i ograniczenia

| Lekcja | Zdolności techniczne | Moduł | Status |
|---|---|---|---|
| S03E01 | tracing, odtwarzanie stanu, wersjonowanie promptów, metryki, ewaluacja | `eval/` (czyta `core/trace`) | — |
| S03E02 | kontrola trudności zadania, mitygacja prompt injection, halucynacje | `agent/guards` | — |
| S03E03 | feedback ze środowiska, przestrzeń między wywołaniami narzędzi, HITL | `agent/`, `api/` | — |
| S03E04 | zestawy danych testowych, ensemble modeli, autooptymalizacja schematów | `eval/`, `llm/registry` | — |
| S03E05 | sterowanie rozumowaniem, elastyczne formy prezentacji, generatywne UI | `llm/`, `api/` | — |

## Sezon 4 — wdrożenia i współpraca

| Lekcja | Zdolności techniczne | Moduł | Status |
|---|---|---|---|
| S04E01 | wdrożenia, współpraca synchroniczna i asynchroniczna, mapowanie procesów | — | — |
| S04E02 | interfejs czatu, personalizacja, meta-prompty | `api/`, `agent/` | — |
| S04E03 | zadania w tle, zarządzanie zdarzeniami i komunikacją | `api/` (background), `core/queue` | — |
| S04E04 | własna baza wiedzy w markdown, pamięć długoterminowa vs baza wiedzy | `memory/` | — |
| S04E05 | rozwiązania wewnątrzfirmowe, prywatność, odczyt SQLite, API zamówień | `tools/sqlite` | — |

## Sezon 5 — produkcja

| Lekcja | Zdolności techniczne | Moduł | Status |
|---|---|---|---|
| S05E01 | architektura czatbotów i agentów, integracje z providerami | `llm/registry`, `api/` | — |
| S05E02 | interfejs użytkownika, narzędzia dla agentów, silniki wyszukiwania i bazy wektorowe | `tools/`, `rag/` | — |
| S05E03 | migracje modeli i zmian API, zarządzanie rozwojem agenta | `llm/registry`, ADR | — |
| S05E04 | doświadczenia produkcyjne | całość | — |
| S05E05 | własny asystent — konfiguracja, narzędzia, współpraca, rozwój | całość | — |

## Wnioski dla architektury

Prymitywy powtarzające się w S01E01–E05, czyli te, które budujemy najpierw:

1. `core/http` — retry, backoff, nagłówki rate-limit (wymuszone przez S01E05)
2. `core/cache` — ponowne uruchomienie zadania ma kosztować zero zapytań
3. `core/trace` — JSONL każdego wywołania; fundament pod S03E01, dlatego istnieje od S01E01
4. `llm/` — `complete`, `complete_structured`, vision, tool calling
5. `hub/` — pobieranie danych, `/verify`, ekstrakcja `{FLG:...}`, respektowanie `dry_run`
6. `config` — sekrety poza kodem
7. `tasks/` — jeden moduł na zadanie + rejestr + CLI
