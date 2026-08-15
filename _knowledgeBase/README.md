# Baza wiedzy

Wiedza uniwersalna, która ma służyć w pracy, a nie w jednym repozytorium. Jeden plik =
jeden temat. Trzy działy: język, agenci, warsztat.

**Zanim coś tu dopiszesz:** [workflow/knowledgeBaseScope.md](workflow/knowledgeBaseScope.md)
— co tu wchodzi, a co idzie do `_tasks/` albo do `piglet/docs/`.

## `python/` — język i biblioteki

| Plik | Temat |
|---|---|
| [projectInit.md](python/projectInit.md) | uv, `pyproject.toml`, zależności, start nowego projektu |
| [httpRetryAndBackoff.md](python/httpRetryAndBackoff.md) | ponowienia: `Retry-After`, `RateLimit`, jitter, budżety, jedna warstwa |
| [httpErrorClassification.md](python/httpErrorClassification.md) | klasy porażek, idempotencja, statusy — decyzja zamiast zgadywania |
| [secretsManagement.md](python/secretsManagement.md) | sekrety: gdzie mieszkają, redakcja w logach, cykl życia, `SecretStr` |

## `agents/` — modele, prompty, architektura agentów

| Plik | Temat |
|---|---|
| [s01e01-programowanieInterakcji.md](agents/s01e01-programowanieInterakcji.md) | tokeny i autoregresja, Structured Outputs, wybór modelu, organizacja promptów |
| [s01e02-laczenieModeluZNarzedziami.md](agents/s01e02-laczenieModeluZNarzedziami.md) | Function Calling, projektowanie narzędzi, workflow vs agent, prompt cache, prompt injection |

### `agents/skills/` — umiejętności, spisane po zbudowaniu

| Plik | Temat |
|---|---|
| [taxonomyClassification.md](agents/skills/taxonomyClassification.md) | klasyfikacja prozy do zamkniętej taksonomii: kiedy model, anatomia, ewaluacja |
| [supervisedAgentLoop.md](agents/skills/supervisedAgentLoop.md) | pętla agenta pod nadzorem: co decyduje model, trzy rodzaje strażnika, budżet, wyciek do kontekstu |

## `workflow/` — warsztat: harness, hooki, proces

| Plik | Temat |
|---|---|
| [knowledgeBaseScope.md](workflow/knowledgeBaseScope.md) | zakres tej bazy: test uniwersalności, czego tu nie ma i gdzie to idzie |
| [bashHooks.md](workflow/bashHooks.md) | hooki jakości: kontrakt z harnessem, konstrukcje bashowe, pułapki |
