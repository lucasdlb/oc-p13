import logging

import pytest

from backend.app.core.settings import (
    Settings,
    _parse_dotenv_line,
    _without_config_secrets,
    _with_secret_env,
)


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


def test_strips_typesafe_secret_and_environment_specific_base_url_from_config(caplog) -> None:  # type: ignore[no-untyped-def]
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

    assert result["typesafe"] == {"enabled": True, "model": "jev-1.13.0"}
    assert any("typesafe.api_key" in record.getMessage() for record in caplog.records)
    assert any("typesafe.base_url" in record.getMessage() for record in caplog.records)


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


def test_with_secret_env_sets_typesafe_api_key_and_base_url(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    values = {
        "TYPESAFE_API_KEY": "ts-key",
        "TYPESAFE_BASE_URL": "https://gateway.example.test/typesafe",
    }
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    monkeypatch.delenv("TYPESAFE_BASE_URL", raising=False)
    monkeypatch.setattr(
        "backend.app.core.settings._read_dotenv_value",
        lambda name: values.get(name),
    )

    result = _with_secret_env({"typesafe": {"enabled": True}})

    assert result["typesafe"]["enabled"] is True
    assert result["typesafe"]["api_key"] == "ts-key"
    assert result["typesafe"]["base_url"] == "https://gateway.example.test/typesafe"


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


def test_settings_expose_rag_defaults() -> None:
    settings = Settings()

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
    assert settings.llm.num_ctx == 4096
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
            {
                "llm": {
                    "provider": "nvidia",
                    "base_url": "https://integrate.api.nvidia.com/v1",
                    "model": "nvidia/test",
                }
            }
        )


def test_ollama_rejects_a_cloud_api_key() -> None:
    with pytest.raises(ValueError, match="not valid for the ollama provider"):
        Settings.model_validate(
            {
                "llm": {
                    "provider": "ollama",
                    "base_url": "http://localhost:11434",
                    "model": "qwen2.5:7b-instruct",
                    "api_key": "should-not-be-used",
                }
            }
        )


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
