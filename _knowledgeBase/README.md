# Baza wiedzy
Jeden plik = jeden temat. Trzy działy: język, agenci, warsztat.

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

## `workflow/` — warsztat: harness, hooki, proces

| Plik | Temat |
|---|---|
| [bashHooks.md](workflow/bashHooks.md) | hooki jakości: kontrakt z harnessem, konstrukcje bashowe, pułapki |
