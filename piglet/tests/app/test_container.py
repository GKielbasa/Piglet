from piglet.app.config import Settings
from piglet.app.container import build_http_client
from piglet.domain.http.service_profile import ServiceProfile

NO_CACHE = Settings(cache_enabled=False)


async def test_the_composition_root_uses_the_service_profile_it_is_given() -> None:
    profile = ServiceProfile(throttling_statuses=frozenset({503}))

    async with build_http_client(NO_CACHE, profile) as client:
        assert client.profile is profile


async def test_the_composition_root_without_a_profile_takes_the_standard_set() -> None:
    async with build_http_client(NO_CACHE) as client:
        assert client.profile == ServiceProfile()
