from piglet.adapters.llm.openrouter_chat import OpenRouterChatModel
from piglet.adapters.llm.recording_chat import RecordingChatModel
from piglet.app.config import Settings
from piglet.app.container import build_chat_model, build_http_client, build_llm_http_client
from piglet.domain.http.service_profile import ServiceProfile

NO_CACHE = Settings(cache_enabled=False)


async def test_the_composition_root_uses_the_service_profile_it_is_given() -> None:
    profile = ServiceProfile(throttling_statuses=frozenset({503}))

    async with build_http_client(NO_CACHE, profile) as client:
        assert client.profile is profile


async def test_the_composition_root_without_a_profile_takes_the_standard_set() -> None:
    async with build_http_client(NO_CACHE) as client:
        assert client.profile == ServiceProfile()


async def test_the_composition_root_gives_the_client_the_deadline_from_configuration() -> None:
    settings = Settings(cache_enabled=False, http_deadline_seconds=5.0)

    async with build_http_client(settings) as client:
        assert client.retry_policy.max_total_seconds == 5.0


async def test_the_deadline_from_configuration_does_not_move_the_waiting_budget() -> None:
    settings = Settings(cache_enabled=False, http_deadline_seconds=5.0)

    async with build_http_client(settings) as client:
        assert client.retry_policy.max_total_delay_seconds == 60.0


async def test_the_model_client_is_built_without_a_cache() -> None:
    async with build_llm_http_client(Settings(cache_enabled=True)) as client:
        assert client.cache is None


async def test_the_model_client_takes_the_model_timeouts() -> None:
    settings = Settings(llm_deadline_seconds=42.0)

    async with build_llm_http_client(settings) as client:
        assert client.retry_policy.max_total_seconds == 42.0


async def test_exchanges_with_a_model_are_written_down_by_default() -> None:
    settings = Settings()

    async with build_llm_http_client(settings) as client:
        assert isinstance(build_chat_model(settings, client, "a-run"), RecordingChatModel)


async def test_nothing_is_written_down_when_the_configuration_forbids_it() -> None:
    settings = Settings(record_exchanges=False)

    async with build_llm_http_client(settings) as client:
        assert isinstance(build_chat_model(settings, client, "a-run"), OpenRouterChatModel)
