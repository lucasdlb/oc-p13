import logging
from copy import deepcopy
from pathlib import Path
import tomllib

import pytest

from backend.app.core.settings import (
    Settings,
    SettingsConfigError,
    get_settings,
    _parse_dotenv_line,
    _without_config_secrets,
    _with_secret_env,
)


def _settings_config(**overrides):  # type: ignore[no-untyped-def]
    config = {
        "logging": {"level": "INFO", "format": "json", "request_id_header": "X-Request-ID"},
        "orchestration": {"langgraph_enabled": True},
        "lichess": {
            "enabled": True,
            "base_url": "https://explorer.lichess.org",
            "timeout_seconds": 2.0,
        },
        "youtube": {
            "enabled": True,
            "base_url": "https://www.googleapis.com/youtube/v3",
            "timeout_seconds": 2.0,
            "max_results": 3,
            "relevance_language": "fr",
        },
        "stockfish": {
            "binary": "stockfish",
            "depth": 12,
            "depth_by_level": {"debutant": 12, "intermediaire": 16, "avance": 20},
            "threads": 4,
            "hash_mb": 128,
            "timeout_seconds": 8.0,
        },
        "mongodb": {
            "enabled": True,
            "uri": "mongodb://localhost:27017",
            "database": "chess_agent",
            "connect_timeout_seconds": 1.5,
            "lichess_cache_ttl_seconds": 86400,
            "videos_cache_ttl_seconds": 604800,
        },
        "embeddings": {
            "base_url": "http://localhost:11434",
            "model": "qwen3-embedding:0.6b",
            "dimension": 1024,
            "batch_size": 32,
            "keep_alive": "30m",
            "query_instruction": "Given a web search query, retrieve relevant passages that answer the query",
            "timeout_seconds": 120.0,
        },
        "milvus": {
            "uri": "http://localhost:19530",
            "collection": "chess_knowledge",
            "metric_type": "COSINE",
            "index_type": "HNSW",
            "index_m": 16,
            "index_ef_construction": 200,
            "search_ef": 64,
            "dimension": 1024,
            "max_text_length": 8000,
            "timeout_seconds": 10.0,
        },
        "rag": {"k": 5, "granularity": "section", "min_score": 0.0, "soft_eco_filter": True},
        "llm": {
            "provider": "ollama",
            "base_url": "http://localhost:11434",
            "model": "qwen2.5:7b-instruct",
            "temperature": 0.2,
            "max_tokens": 1000,
            "num_ctx": 16384,
            "think": False,
            "keep_alive": "5m",
            "timeout_seconds": 60.0,
            "coach_timeout_seconds": 60.0,
            "retries": 1,
            "retry_backoff_seconds": 2.0,
        },
        "typesafe": {
            "enabled": False,
            "base_url": "https://api.typesafe.ai",
            "model": "jev-latest",
            "timeout_seconds": 5.0,
            "high_confidence": 0.75,
            "medium_confidence": 0.5,
        },
        "recommendations": {
            "min_move_share": 0.001,
            "min_position_games": 100,
            "default_moves": 12,
            "rating_presets": {
                "debutant": {"min": 1000, "max": 1400},
                "intermediaire": {"min": 1600, "max": 2000},
                "avance": {"min": 2200, "max": 2500},
            },
        },
    }
    _deep_update(config, overrides)
    return config


def _deep_update(target: dict, updates: dict) -> None:
    for key, value in updates.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            _deep_update(target[key], value)
        else:
            target[key] = value


def test_strips_lichess_token_from_config(caplog) -> None:  # type: ignore[no-untyped-def]
    config = {
        "lichess": {
            "enabled": True,
            "base_url": "https://explorer.lichess.org",
            "timeout_seconds": 2.0,
            "token": "toml-secret",
        }
    }

    with caplog.at_level(logging.WARNING, logger="backend.settings"):
        result = _without_config_secrets(config)

    assert result["lichess"] == {
        "enabled": True,
        "base_url": "https://explorer.lichess.org",
        "timeout_seconds": 2.0,
    }
    assert result["lichess"] is not config["lichess"]
    assert any(
        record.name == "backend.settings" and "is ignored" in record.getMessage()
        for record in caplog.records
    )


def test_strips_mongodb_uri_from_config(caplog) -> None:  # type: ignore[no-untyped-def]
    config = {
        "mongodb": {
            "enabled": True,
            "database": "chess_agent",
            "uri": "mongodb://from-config:27017",
        }
    }

    with caplog.at_level(logging.WARNING, logger="backend.settings"):
        result = _without_config_secrets(config)

    assert result["mongodb"] == {"enabled": True, "database": "chess_agent"}
    assert any(
        record.name == "backend.settings"
        and "mongodb.uri" in record.getMessage()
        and "is ignored" in record.getMessage()
        for record in caplog.records
    )


def test_strips_milvus_uri_from_config(caplog) -> None:  # type: ignore[no-untyped-def]
    config = {
        "milvus": {
            "collection": "chess_knowledge",
            "uri": "http://from-config:19530",
        }
    }

    with caplog.at_level(logging.WARNING, logger="backend.settings"):
        result = _without_config_secrets(config)

    assert result["milvus"] == {"collection": "chess_knowledge"}
    assert any(
        record.name == "backend.settings"
        and "milvus.uri" in record.getMessage()
        and "is ignored" in record.getMessage()
        for record in caplog.records
    )


def test_keeps_provider_base_urls_in_config(caplog) -> None:  # type: ignore[no-untyped-def]
    config = {
        "embeddings": {"model": "qwen3-embedding:0.6b", "base_url": "http://from-config:11434"},
        "llm": {"model": "qwen2.5:7b-instruct", "base_url": "http://from-config:11434"},
    }

    with caplog.at_level(logging.WARNING, logger="backend.settings"):
        result = _without_config_secrets(config)

    assert "base_url" not in result["embeddings"]
    assert result["llm"]["base_url"] == "http://from-config:11434"


def test_strips_typesafe_secret_but_keeps_base_url_from_config(caplog) -> None:  # type: ignore[no-untyped-def]
    config = {
        "typesafe": {
            "enabled": True,
            "api_key": "toml-secret",
            "base_url": "https://gateway.example.test/typesafe",
            "model": "jev-1.13.0",
        }
    }

    with caplog.at_level(logging.WARNING, logger="backend.settings"):
        result = _without_config_secrets(config)

    assert result["typesafe"] == {
        "enabled": True,
        "base_url": "https://gateway.example.test/typesafe",
        "model": "jev-1.13.0",
    }
    assert any("typesafe.api_key" in record.getMessage() for record in caplog.records)


def test_strips_llm_api_key_from_config(caplog) -> None:  # type: ignore[no-untyped-def]
    config = {"llm": {"provider": "nvidia", "api_key": "toml-secret"}}

    with caplog.at_level(logging.WARNING, logger="backend.settings"):
        result = _without_config_secrets(config)

    assert result["llm"] == {"provider": "nvidia"}
    assert any("llm.api_key" in record.getMessage() for record in caplog.records)


def test_with_secret_env_prefers_mongodb_uri_from_environment(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.delenv("MONGODB_URI", raising=False)
    monkeypatch.delenv("LICHESS_TOKEN", raising=False)
    monkeypatch.setattr(
        "backend.app.core.settings._read_dotenv_value",
        lambda name: "mongodb://env-host:27017" if name == "MONGODB_URI" else None,
    )

    result = _with_secret_env({"mongodb": {"database": "chess_agent"}})

    assert result["mongodb"]["uri"] == "mongodb://env-host:27017"
    assert result["mongodb"]["database"] == "chess_agent"


def test_with_secret_env_keeps_default_without_mongodb_uri(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.delenv("MONGODB_URI", raising=False)
    monkeypatch.delenv("LICHESS_TOKEN", raising=False)
    monkeypatch.setattr("backend.app.core.settings._read_dotenv_value", lambda _name: None)

    result = _with_secret_env({"mongodb": {"database": "chess_agent"}})

    assert "uri" not in result["mongodb"]


def test_with_secret_env_sets_milvus_uri_and_ollama_embedding_url(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    values = {"MILVUS_URI": "http://milvus:19530", "OLLAMA_BASE_URL": "http://ollama:11434"}
    monkeypatch.delenv("MONGODB_URI", raising=False)
    monkeypatch.delenv("LICHESS_TOKEN", raising=False)
    monkeypatch.delenv("MILVUS_URI", raising=False)
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    monkeypatch.setattr(
        "backend.app.core.settings._read_dotenv_value",
        lambda name: values.get(name),
    )

    result = _with_secret_env({"milvus": {"collection": "chess_knowledge"}})

    assert result["milvus"]["uri"] == "http://milvus:19530"
    assert result["milvus"]["collection"] == "chess_knowledge"
    assert result["embeddings"]["base_url"] == "http://ollama:11434"
    assert "base_url" not in result.get("llm", {})


def test_with_secret_env_sets_typesafe_api_key(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    values = {
        "TYPESAFE_API_KEY": "ts-key",
    }
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    monkeypatch.setattr(
        "backend.app.core.settings._read_dotenv_value",
        lambda name: values.get(name),
    )

    result = _with_secret_env(
        {"typesafe": {"enabled": True, "base_url": "https://api.typesafe.ai"}}
    )

    assert result["typesafe"]["enabled"] is True
    assert result["typesafe"]["api_key"] == "ts-key"
    assert result["typesafe"]["base_url"] == "https://api.typesafe.ai"


def test_with_secret_env_sets_selected_provider_secret(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    values = {
        "OLLAMA_BASE_URL": "http://ollama:11434",
        "MISTRAL_API_KEY": "mistral-test-key",
    }
    for name in values:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(
        "backend.app.core.settings._read_dotenv_value",
        lambda name: values.get(name),
    )

    result = _with_secret_env(
        {
            "llm": {
                "provider": "mistral",
                "providers": {
                    "mistral": {
                        "base_url": "https://api.mistral.ai/v1",
                        "model": "mistral-large-latest",
                    }
                },
            }
        }
    )

    assert result["llm"]["provider"] == "mistral"
    assert result["llm"]["base_url"] == "https://api.mistral.ai/v1"
    assert result["llm"]["model"] == "mistral-large-latest"
    assert result["llm"]["api_key"] == "mistral-test-key"
    assert result["embeddings"]["base_url"] == "http://ollama:11434"


def test_settings_load_explicit_config_values() -> None:
    settings = Settings.model_validate(_settings_config())

    assert settings.embeddings.dimension == 1024
    assert settings.embeddings.model == "qwen3-embedding:0.6b"
    assert settings.embeddings.base_url == "http://localhost:11434"
    assert settings.milvus.collection == "chess_knowledge"
    assert settings.milvus.metric_type == "COSINE"
    assert settings.milvus.uri == "http://localhost:19530"
    assert settings.rag.k == 5
    assert settings.rag.granularity == "section"
    assert settings.llm.model == "qwen2.5:7b-instruct"
    assert settings.llm.base_url == "http://localhost:11434"
    assert settings.llm.provider == "ollama"
    assert settings.llm.api_key is None
    assert settings.llm.num_ctx == 16384
    assert settings.llm.think is False
    assert settings.llm.keep_alive == "5m"
    assert settings.llm.seed is None
    assert settings.typesafe.enabled is False
    assert settings.typesafe.model == "jev-latest"
    assert settings.typesafe.base_url == "https://api.typesafe.ai"
    assert settings.typesafe.api_key is None
    assert settings.typesafe.high_confidence == 0.75
    assert settings.typesafe.medium_confidence == 0.5


def test_provider_requires_its_own_secret() -> None:
    with pytest.raises(ValueError, match="nvidia provider"):
        Settings.model_validate(
            _settings_config(
                llm={
                    "provider": "nvidia",
                    "base_url": "https://integrate.api.nvidia.com/v1",
                    "model": "nvidia/test",
                }
            )
        )


def test_ollama_rejects_a_cloud_api_key() -> None:
    with pytest.raises(ValueError, match="not valid for the ollama provider"):
        Settings.model_validate(
            _settings_config(
                llm={
                    "provider": "ollama",
                    "base_url": "http://localhost:11434",
                    "model": "qwen2.5:7b-instruct",
                    "api_key": "should-not-be-used",
                }
            )
        )


def test_cloud_provider_uses_explicit_provider_values() -> None:
    settings = Settings.model_validate(
        _settings_config(
            llm={
                "provider": "nvidia",
                "base_url": "https://integrate.api.nvidia.com/v1",
                "model": "nvidia/nemotron-3-super-120b-a12b",
                "api_key": "nvidia-key",
            }
        )
    )

    assert settings.llm.base_url == "https://integrate.api.nvidia.com/v1"
    assert settings.llm.model == "nvidia/nemotron-3-super-120b-a12b"
    assert settings.llm.api_key is not None
    assert settings.llm.api_key.get_secret_value() == "nvidia-key"
    assert "nvidia-key" not in repr(settings)


def test_dimensions_must_match() -> None:
    with pytest.raises(ValueError, match="embeddings.dimension must match milvus.dimension"):
        Settings.model_validate(_settings_config(embeddings={"dimension": 768}))


def test_confidence_thresholds_must_be_ordered() -> None:
    with pytest.raises(ValueError, match="high_confidence"):
        Settings.model_validate(
            _settings_config(typesafe={"high_confidence": 0.4, "medium_confidence": 0.5})
        )


def test_rating_preset_bounds_must_be_ordered() -> None:
    with pytest.raises(ValueError, match="min must be less than or equal to max"):
        Settings.model_validate(
            _settings_config(
                recommendations={"rating_presets": {"custom": {"min": 1800, "max": 1200}}}
            )
        )


def test_unknown_settings_keys_are_rejected() -> None:
    with pytest.raises(ValueError, match="timout_seconds"):
        Settings.model_validate(_settings_config(stockfish={"timout_seconds": 2}))


def test_get_settings_requires_config_file(monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    get_settings.cache_clear()
    missing = tmp_path / "missing.toml"
    monkeypatch.setenv("CONFIG_PATH", str(missing))

    with pytest.raises(SettingsConfigError, match="runtime config file not found"):
        get_settings()

    get_settings.cache_clear()


def test_versioned_config_toml_is_valid(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    config_path = Path(__file__).resolve().parents[2] / "config.toml"
    for name, value in {
        "MONGODB_URI": "mongodb://localhost:27017",
        "MILVUS_URI": "http://localhost:19530",
        "OLLAMA_BASE_URL": "http://localhost:11434",
        "NVIDIA_API_KEY": "nvapi-test",
    }.items():
        monkeypatch.setenv(name, value)

    with config_path.open("rb") as config_file:
        config = _without_config_secrets(tomllib.load(config_file))

    settings = Settings.model_validate(_with_secret_env(deepcopy(config)))

    assert settings.llm.provider == "nvidia"
    assert settings.youtube.base_url == "https://www.googleapis.com/youtube/v3"


def test_keeps_config_without_lichess_token_unchanged() -> None:
    config = {"logging": {"level": "INFO"}, "lichess": {"enabled": True}}

    assert _without_config_secrets(config) == config


def test_keeps_config_without_lichess_section_unchanged() -> None:
    config = {"logging": {"level": "INFO"}}

    assert _without_config_secrets(config) == config


def test_parses_plain_assignment() -> None:
    assert _parse_dotenv_line("LICHESS_TOKEN=abc") == ("LICHESS_TOKEN", "abc")


def test_strips_inline_comment() -> None:
    assert _parse_dotenv_line("LICHESS_TOKEN=abc # generated token") == ("LICHESS_TOKEN", "abc")


def test_parses_export_prefixed_assignment() -> None:
    assert _parse_dotenv_line("export LICHESS_TOKEN=abc") == ("LICHESS_TOKEN", "abc")


def test_parses_double_quoted_value() -> None:
    assert _parse_dotenv_line('LICHESS_TOKEN="abc"') == ("LICHESS_TOKEN", "abc")


def test_parses_single_quoted_value() -> None:
    assert _parse_dotenv_line("LICHESS_TOKEN='abc'") == ("LICHESS_TOKEN", "abc")


def test_quoted_value_ignores_trailing_comment() -> None:
    assert _parse_dotenv_line('LICHESS_TOKEN="abc" # note') == ("LICHESS_TOKEN", "abc")


def test_keeps_hash_inside_quoted_value() -> None:
    assert _parse_dotenv_line('LICHESS_TOKEN="ab#c"') == ("LICHESS_TOKEN", "ab#c")


def test_keeps_unspaced_hash_in_value() -> None:
    assert _parse_dotenv_line("LICHESS_TOKEN=abc#note") == ("LICHESS_TOKEN", "abc#note")


def test_ignores_comments_blank_lines_and_bare_text() -> None:
    assert _parse_dotenv_line("# comment") is None
    assert _parse_dotenv_line("") is None
    assert _parse_dotenv_line("   ") is None
    assert _parse_dotenv_line("just_text") is None


def test_empty_value_returns_empty_string() -> None:
    assert _parse_dotenv_line("LICHESS_TOKEN=") == ("LICHESS_TOKEN", "")
