from __future__ import annotations

from pathlib import Path

import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[3]
MAIN_COMPOSE_PATH = PROJECT_ROOT / "docker-compose.yml"
E2E_COMPOSE_PATH = PROJECT_ROOT / "docker-compose.e2e.yml"


def _load_compose(path: Path) -> dict[str, object]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def _volume_for_target(
    service: dict[str, object],
    target: str,
) -> dict[str, object]:
    volumes = service.get("volumes")
    assert isinstance(volumes, list)
    for volume in volumes:
        if isinstance(volume, dict) and volume.get("target") == target:
            return volume
    raise AssertionError(f"missing volume target: {target}")


def test_main_compose_preserves_runtime_and_hardens_each_service() -> None:
    compose = _load_compose(MAIN_COMPOSE_PATH)
    services = compose["services"]
    assert isinstance(services, dict)

    for service_name in ("api", "web", "admin"):
        service = services[service_name]
        assert isinstance(service, dict)
        assert service["init"] is True
        assert service["read_only"] is True
        assert service["restart"] == "unless-stopped"
        assert service["security_opt"] == ["no-new-privileges:true"]
        assert service["cap_drop"] == ["ALL"]
        assert service["cpus"]
        assert service["mem_limit"]
        assert service["pids_limit"]
        assert service["logging"] == {
            "driver": "json-file",
            "options": {"max-size": "10m", "max-file": "3"},
        }

    api = services["api"]
    assert isinstance(api, dict)
    runtime_volume = _volume_for_target(api, "/app/data/runtime")
    assert runtime_volume["type"] == "bind"
    assert runtime_volume["source"] == "./data/runtime"
    assert runtime_volume["bind"] == {"create_host_path": False}
    assert _volume_for_target(api, "/app/data/cases")["type"] == "volume"
    assert _volume_for_target(api, "/app/data/rubrics")["type"] == "volume"
    assert "/ready" in " ".join(str(part) for part in api["healthcheck"]["test"])


def test_main_compose_passes_supported_provider_configuration() -> None:
    compose = _load_compose(MAIN_COMPOSE_PATH)
    environment = compose["services"]["api"]["environment"]
    assert isinstance(environment, dict)
    required_environment = {
        "OSCE_ANTHROPIC_ENABLED",
        "OSCE_ANTHROPIC_API_KEY",
        "OSCE_GEMINI_PATIENT_PROJECT",
        "OSCE_GEMINI_PATIENT_LOCATION",
        "OSCE_VERTEX_API_KEY",
        "OSCE_VERTEX_PROJECT",
        "OSCE_VERTEX_LOCATION",
        "OSCE_VERTEX_MODEL",
        "OSCE_VERTEX_SKILL_CANDIDATE_MODEL",
        "OSCE_VERTEX_EMBEDDING_ENABLED",
        "OSCE_VERTEX_EMBEDDING_API_KEY",
        "OSCE_VERTEX_EMBEDDING_BATCH_SIZE",
        "OSCE_VERTEX_EMBEDDING_BATCH_MAX_BYTES",
        "OSCE_OPENAI_FALLBACK_ALLOW_CROSS_PROVIDER",
        "OSCE_OPENAI_ATTEMPT_TIMEOUT_SECONDS",
        "OSCE_REQUIRE_RUNTIME_MODEL_CONFIG_FOR_TRAINING",
        "OSCE_MODEL_CALL_TIMEOUT_SECONDS",
        "OSCE_REPORT_MODEL_CALL_TIMEOUT_SECONDS",
        "OSCE_MODEL_CALL_MAX_CONCURRENCY",
        "OSCE_LOCAL_EMBEDDING_TIMEOUT_SECONDS",
        "OSCE_LOCAL_EMBEDDING_MAX_CONCURRENCY",
        "OSCE_DASHSCOPE_RERANK_ENABLED",
        "DASHSCOPE_API_KEY",
        "OSCE_DASHSCOPE_RERANK_API_KEY",
        "OSCE_DASHSCOPE_SPEECH_API_KEY",
        "OSCE_DASHSCOPE_ASR_MODEL",
        "OSCE_DASHSCOPE_TTS_MODEL",
    }
    assert required_environment <= set(environment)
    assert (
        environment["OSCE_GEMINI_PATIENT_MODEL"]
        == "${OSCE_GEMINI_PATIENT_MODEL:-gemini-3.5-flash}"
    )
    assert (
        environment["OSCE_VERTEX_MODEL"]
        == "${OSCE_VERTEX_MODEL:-gemini-3.5-flash}"
    )
    assert (
        environment["OSCE_VERTEX_SKILL_CANDIDATE_MODEL"]
        == "${OSCE_VERTEX_SKILL_CANDIDATE_MODEL:-gemini-3.5-flash}"
    )
    assert (
        environment["OSCE_OPENAI_BASE_URL"]
        == "${OSCE_OPENAI_BASE_URL:-https://dashscope.aliyuncs.com/compatible-mode/v1}"
    )
    assert environment["OSCE_OPENAI_MODEL"] == "${OSCE_OPENAI_MODEL:-qwen-plus}"


def test_e2e_compose_uses_disposable_writable_volumes_under_same_hardening() -> None:
    compose = _load_compose(E2E_COMPOSE_PATH)
    services = compose["services"]
    assert isinstance(services, dict)

    for service_name in ("api", "web", "admin"):
        service = services[service_name]
        assert isinstance(service, dict)
        assert service["init"] is True
        assert service["read_only"] is True
        assert service["restart"] == "no"
        assert service["security_opt"] == ["no-new-privileges:true"]
        assert service["cap_drop"] == ["ALL"]

    api = services["api"]
    assert isinstance(api, dict)
    for target in (
        "/app/data/runtime",
        "/app/data/cases",
        "/app/data/rubrics",
    ):
        volume = _volume_for_target(api, target)
        assert volume["type"] == "volume"
        assert volume["volume"] == {"nocopy": False}


def test_runtime_images_drop_root_before_starting() -> None:
    api_dockerfile = (
        PROJECT_ROOT / "services" / "api" / "Dockerfile"
    ).read_text(encoding="utf-8")
    web_dockerfile = (
        PROJECT_ROOT / "apps" / "web" / "Dockerfile"
    ).read_text(encoding="utf-8")
    admin_dockerfile = (
        PROJECT_ROOT / "apps" / "admin" / "Dockerfile"
    ).read_text(encoding="utf-8")

    assert "\nUSER osce\n" in api_dockerfile
    assert "\nUSER node\n" in web_dockerfile
    assert "\nUSER node\n" in admin_dockerfile
